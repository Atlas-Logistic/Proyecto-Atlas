"""Extracción automática de la licencia de conducir (Mobile y Desktop).

Lee los originales ya guardados en la ficha -- frente y reverso como UN
documento, la única imagen de una licencia antigua o un PDF -- y propone
nombre, RUT, clase y fecha de vencimiento. Las imágenes y las páginas PDF
escaneadas pasan por el OCR existente (`ocr_provider.ProveedorOCR.leer_texto`);
una página PDF con texto embebido utilizable se lee sin OCR, con las mismas
reglas que la ingesta de guías (`ingesta_pdf`).

- El resultado queda en `extraccion_automatica` del mismo documento, con
  `confirmado_por_humano: false`.
- Un dato ilegible, ausente, ambiguo o contradictorio queda
  PENDIENTE_REVISION con su motivo; nunca se completa por aproximación.
- Licencia recibida desde Mobile: nunca se registra sola. `estado_revision`
  sigue PENDIENTE_EXTRACCION y `clase`/`vencimiento` siguen vacíos hasta que
  una persona la confirme.
- Licencia adjuntada en Desktop (origen DESKTOP): si la identidad coincide
  con el chofer del catálogo y el vencimiento es confiable, se registran
  automáticamente los datos confiables (`evaluar_registro_automatico`) con
  `estado_revision` VENCIMIENTO_OCR_AUTOMATICO y `registro_automatico`
  (procedencia, sin confirmación humana). Lo que no es confiable queda vacío
  para que una persona lo complete. Nunca reemplaza una licencia con un
  vencimiento posterior ni toca una confirmación humana.
- Los originales sólo se leen (y se verifica su SHA-256). El catálogo de
  choferes sólo se lee: un RUT que lo contradice se informa.

Corre dentro del ciclo PULL bajo su lease (`comprobar`), después de recibir
las licencias, y también al adjuntar en Desktop sin OCR (`permitir_ocr=False`:
sólo PDF con texto embebido; lo demás queda para el ciclo PULL). Cada
documento se procesa una vez por versión del extractor (`VERSION_EXTRACCION`),
conservando la extracción anterior.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import shutil
import tempfile
import unicodedata
import uuid
from datetime import date
from pathlib import Path
from typing import Callable, Iterable, Mapping

from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico
from atlas_core.catalogos import normalizar_rut, rut_canonico_de_registro_chofer
from atlas_core.fichas_choferes import (
    EMPRESA_ACTUAL, ESTADO_PENDIENTE_EXTRACCION, ESTADO_REGISTRO_AUTOMATICO, ORIGEN_DESKTOP, VERSION, _ahora,
    _validar_v2, leer_almacen, nombre_coincide_con_catalogo, ruta_almacen,
)
from atlas_core.modelos import EstadoValidacion
from atlas_core.validadores import validar_fecha, validar_rut_chileno

logger = logging.getLogger(__name__)

# Subirla re-extrae UNA vez las licencias cuya extracción anterior quedó
# incompleta (ver `_pendientes`); la anterior se conserva. 3: lectura de PDF.
VERSION_EXTRACCION = 3
# Una licencia en PDF tiene una o dos páginas; más es otro documento.
MAX_PAGINAS_LICENCIA_PDF = 4
DPI_OCR_PDF = 300
MAX_PIXELES_OCR_PDF = 12_000_000
# Vencimiento plausible de una licencia (control cada 2 a 6 años en Chile):
# fuera de este rango es una lectura dudosa y la completa una persona.
ANIOS_VENCIMIENTO_PASADO = 20
ANIOS_VENCIMIENTO_FUTURO = 10
PROCEDENCIA_AUTOMATICA = "EXTRACCION_AUTOMATICA"
EXTRAIDO = "EXTRAIDO"
PENDIENTE_REVISION = "PENDIENTE_REVISION"
CAMPOS = ("nombre", "rut", "clase", "vencimiento")
# Clases de la Ley de Tránsito chilena (profesionales A1-A5 y no profesionales).
CLASES_VALIDAS = frozenset({"A1", "A2", "A3", "A4", "A5", "B", "C", "D", "E", "F"})
CARA_UNICA = "UNICA"

_RUT = re.compile(r"(?<![\dK])(\d{1,2}[ .]?\d{3}[ .]?\d{3}\s*-\s*[\dK])(?![\dK])")
_FECHA = re.compile(r"(?<!\d)(\d{1,2})\s*[/.-]\s*(\d{1,2})\s*[/.-]\s*(\d{4})(?!\d)")
# El OCR real junta palabras de los rótulos ("FECHAULTIMO CONTROL",
# "REPUBLICADECHHLE"): los espacios entre palabras del rótulo son opcionales.
_ETIQUETA_VENCIMIENTO = re.compile(
    r"PROXIMO\s*CONTROL|FECHA\s*(?:DE\s*)?CONTROL|VENCIMIENTO|\bVENCE\b|VALIDA\s*HASTA")
# "ULTIMO CONTROL" con los cortes reales del OCR ("FECHAULTIMOCONTROL", "ULTMOCONTROL").
_ETIQUETA_ULTIMO_CONTROL = re.compile(r"ULT\w*\s*CONTROL")
_ETIQUETA_CLASE = re.compile(r"\bCLASES?\b")
# Licencia real sin rótulo CLASE legible: la clase profesional va impresa
# junto a su ley ("A4 Ley19495"). Sólo A1-A5, que son las de la Ley 19.495.
_CLASE_CON_LEY = re.compile(r"(?<![A-Z0-9])(A[1-5])\s*LEY\s*19\.?495(?!\d)")
_ETIQUETAS_NOMBRE = {"apellidos": re.compile(r"\bAPELLIDOS?\b"), "nombres": re.compile(r"\bNOMBRES?\b")}
# Cualquier rótulo impreso: nunca puede tomarse como el valor de otro rótulo.
_ROTULO = re.compile(
    r"\b(?:APELLIDOS?|NOMBRES?|RUN|RUT|CLASES?|FECHA|CONTROL|VENCIMIENTO|DOMICILIO|DIRECCION|COMUNA|"
    r"MUNICIPALIDAD|LICENCIA|CONDUCTOR|REPUBLICA|CHILE|RESTRICCIONES?|OBSERVACIONES?|NACIMIENTO|FIRMA)\b")
_NOMBRE_VALIDO = re.compile(r"[A-Z]{2,}(?: [A-Z]{2,}){0,3}")


def _normalizar(linea: object) -> str:
    texto = unicodedata.normalize("NFKD", str(linea or "").upper())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(texto.replace(":", " ").split())


def _campo(valor, motivo: str = "", *, caras=(), observados=()) -> dict:
    return {
        "valor": valor if not motivo else None,
        "estado": PENDIENTE_REVISION if motivo else EXTRAIDO,
        "motivo": motivo,
        "caras": sorted(set(caras)),
        "observados": sorted(set(observados)),
    }


def _unico(hallazgos: list[tuple[str, str]], *, ilegibles: Iterable[str] = ()) -> dict:
    """(valor, cara) -> campo: un único valor válido, o pendiente con motivo."""
    ilegibles = list(ilegibles)
    valores = {valor for valor, _ in hallazgos}
    caras = [cara for _, cara in hallazgos]
    if len(valores) == 1:
        return _campo(next(iter(valores)), caras=caras, observados=valores)
    if len(valores) > 1:
        return _campo(None, "CONTRADICCION", caras=caras, observados=valores)
    return _campo(None, "ILEGIBLE" if ilegibles else "NO_ENCONTRADO", observados=ilegibles)


def _valor_tras_etiqueta(lineas: list[str], i: int, etiqueta: re.Pattern) -> list[str]:
    """Texto que sigue al rótulo en su línea; si no hay, la línea siguiente."""
    resto = etiqueta.split(lineas[i], maxsplit=1)[-1].strip()
    return [resto] if resto else lineas[i + 1:i + 2]


def _extraer_rut(caras: Mapping[str, list[str]]) -> dict:
    hallazgos, ilegibles = [], []
    for cara, lineas in caras.items():
        for linea in lineas:
            for candidato in _RUT.findall(linea):
                campo = validar_rut_chileno(candidato)
                if campo.estado == EstadoValidacion.VALIDO:
                    hallazgos.append((campo.valor, cara))
                else:
                    ilegibles.append(candidato)
    return _unico(hallazgos, ilegibles=ilegibles)


def _extraer_clase(caras: Mapping[str, list[str]]) -> dict:
    hallazgos, ilegibles = [], []
    for cara, lineas in caras.items():
        for i, linea in enumerate(lineas):
            hallazgos.extend((clase, cara) for clase in _CLASE_CON_LEY.findall(linea))
            if not _ETIQUETA_CLASE.search(linea):
                continue
            for texto in _valor_tras_etiqueta(lineas, i, _ETIQUETA_CLASE):
                for token in re.findall(r"[A-Z0-9]+", texto):
                    if token in CLASES_VALIDAS:
                        hallazgos.append((token, cara))
                    elif re.fullmatch(r"[A-Z][0-9]?", token):
                        ilegibles.append(token)
    campo = _unico(hallazgos, ilegibles=ilegibles)
    if campo["motivo"] == "CONTRADICCION":
        # Varias clases leídas: la licencia puede acreditar más de una (p. ej. A2 y A5) o ser un error de
        # OCR. Se informan como valores individuales reconocidos (`valores`, nunca un rango) y una persona
        # las confirma o corrige contra el original; no se registran solas.
        campo["motivo"] = "VARIAS_CLASES"
        orden = ("A1", "A2", "A3", "A4", "A5", "B", "C", "D", "E", "F")
        campo["valores"] = sorted({valor for valor, _ in hallazgos}, key=orden.index)
    return campo


def _extraer_vencimiento(caras: Mapping[str, list[str]]) -> dict:
    hallazgos, ilegibles = [], []
    for cara, lineas in caras.items():
        for i, linea in enumerate(lineas):
            if not _ETIQUETA_VENCIMIENTO.search(linea) or "ULTIMO" in linea:
                continue
            textos = _valor_tras_etiqueta(lineas, i, _ETIQUETA_VENCIMIENTO)
            fechas = [f for texto in textos for f in _FECHA.findall(texto)]
            if not fechas:
                ilegibles.extend(t for t in textos if t)
            for dia, mes, anio in fechas:
                campo = validar_fecha(f"{int(dia):02d}/{int(mes):02d}/{anio}", formato_esperado="DD/MM/YYYY")
                if campo.estado == EstadoValidacion.VALIDO:
                    hallazgos.append((campo.valor, cara))
                else:
                    ilegibles.append(f"{dia}/{mes}/{anio}")
    return _unico(hallazgos, ilegibles=ilegibles)


def _extraer_nombre(caras: Mapping[str, list[str]]) -> dict:
    partes = {}
    for parte, etiqueta in _ETIQUETAS_NOMBRE.items():
        hallazgos, ilegibles = [], []
        for cara, lineas in caras.items():
            for i, linea in enumerate(lineas):
                # "APELLIDOS Y NOMBRES" en un solo rótulo: no se separa a ojo.
                if not etiqueta.search(linea) or all(e.search(linea) for e in _ETIQUETAS_NOMBRE.values()):
                    continue
                for texto in _valor_tras_etiqueta(lineas, i, etiqueta):
                    if _ROTULO.search(texto):
                        continue
                    if _NOMBRE_VALIDO.fullmatch(texto):
                        hallazgos.append((texto, cara))
                    elif texto:
                        ilegibles.append(texto)
        partes[parte] = _unico(hallazgos, ilegibles=ilegibles)
    nombres, apellidos = partes["nombres"], partes["apellidos"]
    if nombres["estado"] == EXTRAIDO and apellidos["estado"] == EXTRAIDO:
        return _campo(f"{nombres['valor']} {apellidos['valor']}", caras=nombres["caras"] + apellidos["caras"],
                      observados=[f"{nombres['valor']} {apellidos['valor']}"])
    motivo = next(p["motivo"] for p in (nombres, apellidos) if p["estado"] != EXTRAIDO)
    return _campo(None, motivo, observados=nombres["observados"] + apellidos["observados"])


def _vencimiento_por_fechas_de_control(caras: Mapping[str, list[str]]) -> dict | None:
    """Frente de la licencia actual: «FECHA ÚLTIMO CONTROL» y «FECHA DE CONTROL»
    con una fecha cada uno, y el OCR suele entregar la fecha ANTES de su rótulo
    (o el rótulo cortado). Si la cara con el rótulo de último control trae
    exactamente dos fechas válidas separadas por 1 a 8 años, la posterior es el
    próximo control (el vencimiento). Más fechas (licencia antigua con tabla de
    clases) o dos caras que no concuerdan: no se infiere nada."""
    candidatos = []
    for cara, lineas in caras.items():
        if not any(_ETIQUETA_ULTIMO_CONTROL.search(l) for l in lineas):
            continue
        fechas = set()
        for linea in lineas:
            for dia, mes, anio in _FECHA.findall(linea):
                campo = validar_fecha(f"{int(dia):02d}/{int(mes):02d}/{anio}", formato_esperado="DD/MM/YYYY")
                if campo.estado == EstadoValidacion.VALIDO:
                    fechas.add(campo.valor)
        if len(fechas) != 2:
            return None
        anterior, posterior = sorted(fechas, key=date.fromisoformat)
        if not 1 <= date.fromisoformat(posterior).year - date.fromisoformat(anterior).year <= 8:
            return None
        candidatos.append((posterior, anterior, cara))
    if len({c[0] for c in candidatos}) != 1:
        return None
    posterior, anterior, cara = candidatos[0]
    return {**_campo(posterior, caras=[cara], observados=[anterior, posterior]), "metodo": "PAR_FECHAS_CONTROL"}


def extraer_campos_licencia(caras: Mapping[str, Iterable[str]], *, ruts_catalogo: Iterable[str] = (),
                            inferir_vencimiento_por_controles: bool = False) -> dict:
    """Campos propuestos a partir del texto OCR de cada cara del MISMO documento.

    `ruts_catalogo`: RUT canónicos del chofer de la ficha. Un RUT legible que
    no es ninguno de ellos queda PENDIENTE_REVISION (CONTRADICE_CATALOGO); la
    identidad confirmada no se toca. `inferir_vencimiento_por_controles`
    (licencias adjuntadas en Desktop): si el rótulo no entrega el vencimiento,
    se intenta con el par de fechas de control (`_vencimiento_por_fechas_de_control`)."""
    normalizadas = {cara: [l for l in (_normalizar(x) for x in lineas) if l] for cara, lineas in caras.items()}
    campos = {
        "nombre": _extraer_nombre(normalizadas),
        "rut": _extraer_rut(normalizadas),
        "clase": _extraer_clase(normalizadas),
        "vencimiento": _extraer_vencimiento(normalizadas),
    }
    if inferir_vencimiento_por_controles and campos["vencimiento"]["motivo"] in ("NO_ENCONTRADO", "ILEGIBLE"):
        campos["vencimiento"] = _vencimiento_por_fechas_de_control(normalizadas) or campos["vencimiento"]
    ruts = {validar_rut_chileno(r).valor for r in ruts_catalogo} - {None}
    if campos["rut"]["estado"] == EXTRAIDO and ruts and campos["rut"]["valor"] not in ruts:
        campos["rut"] = _campo(None, "CONTRADICE_CATALOGO", caras=campos["rut"]["caras"],
                               observados=campos["rut"]["observados"])
    return campos


def _resumen_estado(campos: Mapping[str, Mapping]) -> str:
    extraidos = sum(1 for c in campos.values() if c["estado"] == EXTRAIDO)
    return "COMPLETA" if extraidos == len(CAMPOS) else ("PARCIAL" if extraidos else "SIN_DATOS")


def _caras_del_documento(documento: Mapping) -> list[tuple[str, str, str]]:
    if documento.get("caras"):
        return [(c["cara"], c["archivo"], c.get("sha256", "")) for c in documento["caras"]]
    # Licencia antigua de una sola imagen: su `sha256` es el de esa imagen.
    return [(CARA_UNICA, documento["archivo"], documento.get("sha256", ""))]


def _por_extraer(documento: Mapping) -> bool:
    """Sin extracción, o con una incompleta de una versión anterior del
    extractor: una re-extracción por versión, nunca en cada ciclo."""
    previa = documento.get("extraccion_automatica")
    if previa is None:
        return True
    return previa.get("estado") != "COMPLETA" and int(previa.get("version") or 0) < VERSION_EXTRACCION


def _pendientes(datos: Mapping) -> list[tuple[dict, dict]]:
    return [
        (ficha, documento)
        for ficha in datos.get("choferes", [])
        for documento in ficha.get("documentos", [])
        if documento.get("tipo") == "LICENCIA_CONDUCIR"
        and documento.get("estado_revision") == ESTADO_PENDIENTE_EXTRACCION
        and not documento.get("reemplazado_por") and _por_extraer(documento)
    ]


def _ruts_de_ficha(ficha: Mapping, catalogo: Mapping) -> list[str]:
    ruts = []
    for referencia in ficha.get("referencias_catalogo", []):
        rut = rut_canonico_de_registro_chofer(referencia, catalogo.get(referencia))
        if rut:
            ruts.append(rut)
    return ruts


class _RequiereOCR(Exception):
    """El original necesita OCR y esta lectura no lo permite (adjunto en Desktop)."""


def _dpi_ocr(ancho_pt: float, alto_pt: float) -> float:
    """300 dpi, o menos si la página es grande: un PDF armado desde fotos de
    celular trae páginas de varios metros y a 300 dpi superaría el límite de
    píxeles. Se apunta a una imagen del tamaño de una foto (~12 Mpx)."""
    area = max(float(ancho_pt) * float(alto_pt), 1.0)
    return min(float(DPI_OCR_PDF), 72.0 * (MAX_PIXELES_OCR_PDF / area) ** 0.5)


def _lineas_pdf(ruta: Path, *, permitir_ocr: bool, proveedor: Callable[[], object],
                temporal: Callable[[], Path]) -> tuple[dict, list[str]]:
    """Texto de cada página: el embebido si es utilizable (mismas reglas que la
    ingesta de guías); si no, OCR de la página rasterizada. Un PDF que PDFium
    no abre devuelve {} (queda FORMATO_SIN_OCR, sin OCR)."""
    import pypdfium2 as pdfium

    from atlas_core.ingesta_pdf import (
        _caracteres_pagina, _clasificar_texto_pagina, _rasterizar_pagina, _segmentos_texto_pagina,
    )
    try:
        documento = pdfium.PdfDocument(str(ruta))
    except Exception as error:  # noqa: BLE001 -- PDF dañado, cifrado o no PDF: nada que leer
        logger.warning("PDF de licencia ilegible %s: %s", ruta.name, error)
        return {}, []
    try:
        paginas = len(documento)
        if not 0 < paginas <= MAX_PAGINAS_LICENCIA_PDF:
            raise ValueError(f"El PDF tiene {paginas} páginas; una licencia tiene a lo más {MAX_PAGINAS_LICENCIA_PDF}")
        textos, metodos = {}, []
        for indice in range(paginas):
            cara = f"PAGINA_{indice + 1}"
            pagina = documento[indice]
            try:
                ancho_pt, alto_pt = pagina.get_size()
                caracteres = _caracteres_pagina(pagina)
                utilizable, _ = _clasificar_texto_pagina(caracteres)
                lineas = [s["texto"] for s in _segmentos_texto_pagina(pagina, caracteres, DPI_OCR_PDF)] if utilizable else None
            finally:
                pagina.close()
            if lineas is not None:
                textos[cara] = lineas
                metodos.append("TEXTO_EMBEBIDO")
                continue
            if not permitir_ocr:
                raise _RequiereOCR(cara)
            imagen = temporal() / f"{uuid.uuid4().hex}.png"
            _rasterizar_pagina(documento, indice, imagen, _dpi_ocr(ancho_pt, alto_pt))
            try:
                textos[cara] = list(proveedor().leer_texto(imagen))
            finally:
                imagen.unlink(missing_ok=True)
            metodos.append("OCR")
        return textos, metodos
    finally:
        documento.close()


def _leer_caras(carpeta: Path, documento: Mapping, proveedor: Callable[[], object], *,
                permitir_ocr: bool = True, temporal: Callable[[], Path] | None = None) -> tuple[dict, list[dict]]:
    """Texto de cada cara (o página PDF) tras verificar que el original sigue intacto.

    Sin `permitir_ocr` lanza `_RequiereOCR` si algo sólo se puede leer con OCR."""
    textos, archivos = {}, []
    for cara, archivo, sha256 in _caras_del_documento(documento):
        ruta = (carpeta / archivo).resolve()
        if not ruta.is_relative_to(carpeta.resolve()):
            raise ValueError("Adjunto fuera de la empresa")
        if hashlib.sha256(ruta.read_bytes()).hexdigest() != str(sha256).lower():
            raise ValueError(f"El original de {cara} no coincide con su huella registrada")
        entrada = {"cara": cara, "archivo": archivo, "sha256": sha256}
        archivos.append(entrada)
        if ruta.suffix.lower() == ".pdf":
            paginas, metodos = _lineas_pdf(ruta, permitir_ocr=permitir_ocr, proveedor=proveedor,
                                           temporal=temporal or (lambda: Path(tempfile.gettempdir())))
            if metodos:
                entrada["paginas"] = metodos
            textos.update(paginas)
            continue
        if not permitir_ocr:
            raise _RequiereOCR(cara)
        textos[cara] = list(proveedor().leer_texto(ruta))
    return textos, archivos


def _vencimiento_plausible(valor: str, hoy: date) -> bool:
    try:
        fecha = date.fromisoformat(str(valor))
    except ValueError:
        return False
    return (date(hoy.year - ANIOS_VENCIMIENTO_PASADO, 1, 1) <= fecha
            <= date(hoy.year + ANIOS_VENCIMIENTO_FUTURO, 12, 31))


def evaluar_registro_automatico(campos: Mapping[str, Mapping], *, ruts_catalogo: Iterable[str],
                                registros_catalogo: Iterable[Mapping], vigentes: Iterable[Mapping],
                                hoy: date) -> dict:
    """Qué datos de una licencia adjuntada en Desktop son confiables para
    registrarlos sin confirmación humana. Función pura.

    - Identidad: el RUT leído es el del chofer en el catálogo, o -- sin RUT
      legible -- el nombre leído contiene el del catálogo. Un RUT o nombre
      leído que contradice al chofer bloquea todo el registro.
    - Vencimiento: leído sin ambigüedad y dentro de un rango plausible. Sin
      él no se registra nada (la licencia no tendría vigencia).
    - Nunca deja atrás una licencia registrada que vence después.
    Devuelve `registrar`, `valores` confiables, `pendientes` {campo: motivo},
    `motivo` si no se registra y `reemplaza` (licencias vigentes superadas)."""
    # Mismo RUT aunque venga escrito con o sin puntos y guion.
    ruts = {normalizar_rut(validar_rut_chileno(r).valor or "") for r in ruts_catalogo} - {""}
    registros = [r for r in registros_catalogo if isinstance(r, Mapping)]
    rut, nombre = campos.get("rut") or {}, campos.get("nombre") or {}
    nombre_leido = nombre.get("estado") == EXTRAIDO and nombre.get("valor")
    nombre_ok = bool(nombre_leido) and any(nombre_coincide_con_catalogo(nombre["valor"], r) for r in registros)
    rut_ok = rut.get("estado") == EXTRAIDO and normalizar_rut(rut.get("valor") or "") in ruts
    resultado = {"registrar": False, "valores": {}, "pendientes": {}, "motivo": "", "reemplaza": []}
    if rut.get("motivo") == "CONTRADICE_CATALOGO" or (rut.get("estado") == EXTRAIDO and not rut_ok and ruts) \
            or (nombre_leido and not nombre_ok):
        resultado["motivo"] = "IDENTIDAD_NO_COINCIDE"
        return resultado
    if not (rut_ok or (rut.get("motivo") in ("NO_ENCONTRADO", "ILEGIBLE") and nombre_ok)):
        resultado["motivo"] = "IDENTIDAD_NO_VERIFICADA"
        return resultado
    valores, pendientes = {}, {}
    for clave, confiable in (("rut", rut_ok), ("nombre", nombre_ok)):
        if confiable:
            valores[clave] = campos[clave]["valor"]
        else:
            pendientes[clave] = (campos.get(clave) or {}).get("motivo") or "NO_VERIFICABLE"
    clase = campos.get("clase") or {}
    if clase.get("estado") == EXTRAIDO and clase.get("valor") in CLASES_VALIDAS:
        valores["clase"] = clase["valor"]
    else:
        pendientes["clase"] = clase.get("motivo") or "NO_ENCONTRADO"
    vencimiento = campos.get("vencimiento") or {}
    if vencimiento.get("estado") != EXTRAIDO:
        pendientes["vencimiento"] = vencimiento.get("motivo") or "NO_ENCONTRADO"
    elif not _vencimiento_plausible(vencimiento.get("valor"), hoy):
        pendientes["vencimiento"] = "FUERA_DE_RANGO"
    else:
        valores["vencimiento"] = vencimiento["valor"]
    resultado.update(valores=valores, pendientes=pendientes)
    if "vencimiento" not in valores:
        resultado["motivo"] = "VENCIMIENTO_NO_CONFIABLE"
        return resultado
    vigentes = [d for d in vigentes if d.get("vencimiento")]
    if any(str(d["vencimiento"]) > valores["vencimiento"] for d in vigentes):
        resultado["motivo"] = "VENCE_ANTES_QUE_LA_REGISTRADA"
        return resultado
    resultado.update(registrar=True, reemplaza=[d["documento_id"] for d in vigentes])
    return resultado


def _licencias_vigentes(ficha: Mapping, excepto: str) -> list[dict]:
    """Licencias registradas (con datos) que siguen activas en la ficha."""
    return [d for d in ficha.get("documentos", [])
            if d.get("tipo") == "LICENCIA_CONDUCIR" and d.get("documento_id") != excepto
            and not d.get("reemplazado_por") and d.get("estado_revision") != ESTADO_PENDIENTE_EXTRACCION]


def extraer_licencias_pendientes(
    raiz: str | Path, *, comprobar: Callable[[], None], fabrica_ocr: Callable[[], object] | None,
    empresa: str = EMPRESA_ACTUAL, actor: str = "MOTOR_OCR", documento_id: str | None = None,
    permitir_ocr: bool = True, hoy: date | None = None,
) -> dict:
    """Extrae una vez cada licencia PENDIENTE_EXTRACCION de la ficha.

    El OCR corre fuera del bloqueo; la escritura vuelve a leer la ficha y sólo
    agrega `extraccion_automatica` + historial (y, si corresponde, el registro
    automático) si el documento sigue igual de pendiente. `fabrica_ocr` se
    invoca sólo si hay algo que leer con OCR; el proveedor creado se cierra al
    terminar. `documento_id` limita la lectura a ese documento. Sin
    `permitir_ocr`, lo que necesita OCR queda en `diferidas`, sin escribir,
    para el próximo ciclo PULL."""
    resumen: dict = {"pendientes": 0, "extraidas": [], "errores": []}
    datos = leer_almacen(raiz, empresa=empresa)
    if not datos or datos.get("version") != VERSION:
        return resumen
    pendientes = [(f, d) for f, d in _pendientes(datos) if documento_id is None or d["documento_id"] == documento_id]
    resumen["pendientes"] = len(pendientes)
    if not pendientes:
        return resumen
    ruta = ruta_almacen(raiz, empresa)
    catalogo = json.loads((Path(raiz) / "catalogos_privados" / "choferes.json").read_text(encoding="utf-8-sig"))
    hoy = hoy or date.today()
    creado: list = []
    carpeta_temporal: list = []

    def proveedor():
        if fabrica_ocr is None:
            raise _RequiereOCR("sin proveedor OCR")
        if not creado:
            creado.append(fabrica_ocr())
        return creado[0]

    def temporal() -> Path:
        if not carpeta_temporal:
            carpeta_temporal.append(tempfile.TemporaryDirectory(prefix="atlas-licencia-"))
        return Path(carpeta_temporal[0].name)

    try:
        for ficha, documento in pendientes:
            comprobar()
            doc_id = documento["documento_id"]
            try:
                textos, archivos = _leer_caras(ruta.parent, documento, proveedor,
                                               permitir_ocr=permitir_ocr and fabrica_ocr is not None, temporal=temporal)
            except _RequiereOCR:
                resumen.setdefault("diferidas", []).append(doc_id)
                continue
            except Exception as error:  # noqa: BLE001 -- una licencia no corta las demás
                logger.warning("Licencia %s sin extracción: %s", doc_id, error)
                resumen["errores"].append({"documento_id": doc_id, "error": str(error)})
                continue
            if textos:
                # La inferencia por fechas de control sólo para lo adjuntado en Desktop:
                # las propuestas de la revisión Mobile no cambian.
                campos = extraer_campos_licencia(
                    textos, ruts_catalogo=_ruts_de_ficha(ficha, catalogo),
                    inferir_vencimiento_por_controles=documento.get("origen") == ORIGEN_DESKTOP)
            else:
                campos = {c: _campo(None, "FORMATO_SIN_OCR") for c in CAMPOS}
            extraccion = {
                "version": VERSION_EXTRACCION, "fecha": _ahora(), "actor": actor,
                "motor_ocr": type(creado[0]).__name__ if creado else "",
                "confirmado_por_humano": False, "estado": _resumen_estado(campos),
                "archivos": archivos, "campos": campos,
            }
            registro = _registrar(raiz, ruta, empresa, ficha["ficha_id"], doc_id, extraccion, actor, comprobar,
                                  catalogo=catalogo, hoy=hoy)
            if registro is not None:
                resumen["extraidas"].append({
                    "documento_id": doc_id, "ficha_id": ficha["ficha_id"], "estado": extraccion["estado"],
                    "extraidos": [c for c in CAMPOS if campos[c]["estado"] == EXTRAIDO],
                    "pendientes": {c: campos[c]["motivo"] for c in CAMPOS if campos[c]["estado"] != EXTRAIDO},
                    **({"registro": registro} if registro else {}),
                })
    finally:
        cerrar = getattr(creado[0], "cerrar", None) if creado else None
        if callable(cerrar):
            cerrar()
        if carpeta_temporal:
            carpeta_temporal[0].cleanup()
    return resumen


def _aplicar_registro(ficha: dict, objetivo: dict, extraccion: dict, actor: str,
                      catalogo: Mapping, hoy: date) -> dict:
    """Registro automático de una licencia adjuntada en Desktop (bajo el bloqueo)."""
    evaluacion = evaluar_registro_automatico(
        extraccion["campos"], ruts_catalogo=_ruts_de_ficha(ficha, catalogo),
        registros_catalogo=[catalogo.get(r) for r in ficha.get("referencias_catalogo", [])],
        vigentes=_licencias_vigentes(ficha, objetivo["documento_id"]), hoy=hoy)
    resumen = {"registrada": evaluacion["registrar"], "registrados": sorted(evaluacion["valores"]),
               "por_completar": sorted(evaluacion["pendientes"]), "motivo": evaluacion["motivo"]}
    extraccion["registro"] = {"registrada": evaluacion["registrar"], "motivo": evaluacion["motivo"],
                              "pendientes": evaluacion["pendientes"]}
    if not evaluacion["registrar"]:
        return resumen
    valores = evaluacion["valores"]
    objetivo["vencimiento"] = valores["vencimiento"]
    if "clase" in valores:
        objetivo["clase"] = valores["clase"]
        objetivo["clases"] = [valores["clase"]]
    titular = {k: valores[k] for k in ("rut", "nombre") if k in valores}
    if titular:
        objetivo["titular"] = titular
    objetivo["estado_revision"] = ESTADO_REGISTRO_AUTOMATICO
    objetivo["registro_automatico"] = {
        "procedencia": PROCEDENCIA_AUTOMATICA, "confirmado_por_humano": False, "actor": actor,
        "fecha": extraccion["fecha"], "extraccion_version": extraccion["version"], "sha256": objetivo.get("sha256"),
        "campos": sorted(valores), "pendientes": evaluacion["pendientes"],
    }
    if evaluacion["reemplaza"]:
        objetivo["reemplaza_documentos"] = evaluacion["reemplaza"]
        for previo in ficha["documentos"]:
            if previo.get("documento_id") in evaluacion["reemplaza"]:
                previo["reemplazado_por"] = objetivo["documento_id"]
    ficha["historial"].append({
        "accion": "LICENCIA_REGISTRADA_AUTOMATICA", "actor": actor, "fecha": extraccion["fecha"],
        "documento_id": objetivo["documento_id"], "campos": sorted(valores),
        "pendientes": sorted(evaluacion["pendientes"]), "reemplaza_documentos": evaluacion["reemplaza"],
    })
    resumen["reemplazados"] = len(evaluacion["reemplaza"])
    resumen["vencimiento"] = valores["vencimiento"]
    return resumen


def _registrar(raiz, ruta: Path, empresa: str, ficha_id: str, documento_id: str, extraccion: dict,
               actor: str, comprobar: Callable[[], None], *, catalogo: Mapping, hoy: date) -> dict | None:
    """Escribe la extracción. None si el documento ya no está pendiente; {} si
    se escribió sin registro automático (Mobile); el resumen del registro si es
    una licencia adjuntada en Desktop."""
    with bloqueo_sesion(Path(raiz) / "operacion" / "actual", "fichas_choferes_" + empresa):
        anterior = leer_almacen(raiz, empresa=empresa)
        propuesta = copy.deepcopy(anterior)
        objetivo = next((d for f, d in _pendientes(propuesta)
                         if f["ficha_id"] == ficha_id and d["documento_id"] == documento_id), None)
        if objetivo is None:
            return None  # ya extraída, reemplazada o registrada por una persona entre medio
        previa = objetivo.get("extraccion_automatica")
        if previa is not None:
            objetivo.setdefault("extracciones_anteriores", []).append(previa)
        objetivo["extraccion_automatica"] = extraccion
        ficha = next(f for f in propuesta["choferes"] if f["ficha_id"] == ficha_id)
        ficha["historial"].append({
            "accion": "LICENCIA_EXTRACCION_AUTOMATICA", "actor": actor, "fecha": extraccion["fecha"],
            "documento_id": documento_id, "estado": extraccion["estado"], "version": extraccion["version"],
            **({"version_anterior": previa.get("version"), "estado_anterior": previa.get("estado")} if previa else {}),
        })
        # Sólo la licencia adjuntada en Desktop se registra sola; la de Mobile sigue su revisión.
        registro = (_aplicar_registro(ficha, objetivo, extraccion, actor, catalogo, hoy)
                    if objetivo.get("origen") == ORIGEN_DESKTOP else {})
        propuesta["revision"] = int(anterior["revision"]) + 1
        _validar_v2(propuesta)
        respaldo = Path(raiz) / "respaldos" / "fichas_choferes" / uuid.uuid4().hex
        respaldo.mkdir(parents=True)
        shutil.copy2(ruta, respaldo / ruta.name)
        escribir_json_atomico(respaldo / "manifest.json", {
            "empresa": empresa, "actor": actor, "operacion": "LICENCIA_EXTRACCION_AUTOMATICA",
            "ficha_id": ficha_id, "documento_id": documento_id, "revision_anterior": anterior["revision"],
            "ruta_relativa": str(ruta.relative_to(raiz)),
            **({"registro_automatico": registro["registrada"]} if registro else {}),
        })
        comprobar()
        escribir_json_atomico(ruta, propuesta)
        return registro
