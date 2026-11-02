"""Extracción automática de la licencia de conducir recibida desde Mobile.

Lee con el OCR existente (`ocr_provider.ProveedorOCR.leer_texto`) las fotos
ya guardadas en la ficha -- frente y reverso como UN documento, o la única
imagen de una licencia antigua -- y propone nombre, RUT, clase y fecha de
vencimiento. Nunca las confirma:

- El resultado queda en `extraccion_automatica` del mismo documento, con
  `confirmado_por_humano: false`. `estado_revision` sigue
  PENDIENTE_EXTRACCION y `clase`/`vencimiento` del documento siguen vacíos:
  la licencia no pasa a vigente ni reemplaza a otra hasta que una persona
  la registre.
- Un dato ilegible, ausente, ambiguo o contradictorio queda
  PENDIENTE_REVISION con su motivo; nunca se completa por aproximación.
- Las imágenes originales sólo se leen (y se verifica su SHA-256). El
  catálogo de choferes sólo se lee: un RUT que lo contradice se informa.

Corre dentro del ciclo PULL bajo su lease (`comprobar`), después de recibir
las licencias. Cada documento se procesa una sola vez.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import shutil
import unicodedata
import uuid
from pathlib import Path
from typing import Callable, Iterable, Mapping

from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico
from atlas_core.catalogos import rut_canonico_de_registro_chofer
from atlas_core.fichas_choferes import (
    EMPRESA_ACTUAL, ESTADO_PENDIENTE_EXTRACCION, VERSION, _ahora, _validar_v2, leer_almacen, ruta_almacen,
)
from atlas_core.modelos import EstadoValidacion
from atlas_core.validadores import validar_fecha, validar_rut_chileno

logger = logging.getLogger(__name__)

VERSION_EXTRACCION = 1
EXTRAIDO = "EXTRAIDO"
PENDIENTE_REVISION = "PENDIENTE_REVISION"
CAMPOS = ("nombre", "rut", "clase", "vencimiento")
# Clases de la Ley de Tránsito chilena (profesionales A1-A5 y no profesionales).
CLASES_VALIDAS = frozenset({"A1", "A2", "A3", "A4", "A5", "B", "C", "D", "E", "F"})
CARA_UNICA = "UNICA"

_RUT = re.compile(r"(?<![\dK])(\d{1,2}[ .]?\d{3}[ .]?\d{3}\s*-\s*[\dK])(?![\dK])")
_FECHA = re.compile(r"(?<!\d)(\d{1,2})\s*[/.-]\s*(\d{1,2})\s*[/.-]\s*(\d{4})(?!\d)")
_ETIQUETA_VENCIMIENTO = re.compile(
    r"PROXIMO\s+CONTROL|FECHA\s+(?:DE\s+)?CONTROL|VENCIMIENTO|\bVENCE\b|VALIDA\s+HASTA")
_ETIQUETA_CLASE = re.compile(r"\bCLASES?\b")
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
        # Varias clases leídas: puede tener más de una o ser un error de OCR.
        # La ficha admite una sola; la elige una persona.
        campo["motivo"] = "VARIAS_CLASES"
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


def extraer_campos_licencia(caras: Mapping[str, Iterable[str]], *, ruts_catalogo: Iterable[str] = ()) -> dict:
    """Campos propuestos a partir del texto OCR de cada cara del MISMO documento.

    `ruts_catalogo`: RUT canónicos del chofer de la ficha. Un RUT legible que
    no es ninguno de ellos queda PENDIENTE_REVISION (CONTRADICE_CATALOGO); la
    identidad confirmada no se toca."""
    normalizadas = {cara: [l for l in (_normalizar(x) for x in lineas) if l] for cara, lineas in caras.items()}
    campos = {
        "nombre": _extraer_nombre(normalizadas),
        "rut": _extraer_rut(normalizadas),
        "clase": _extraer_clase(normalizadas),
        "vencimiento": _extraer_vencimiento(normalizadas),
    }
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


def _pendientes(datos: Mapping) -> list[tuple[dict, dict]]:
    return [
        (ficha, documento)
        for ficha in datos.get("choferes", [])
        for documento in ficha.get("documentos", [])
        if documento.get("tipo") == "LICENCIA_CONDUCIR"
        and documento.get("estado_revision") == ESTADO_PENDIENTE_EXTRACCION
        and not documento.get("reemplazado_por") and "extraccion_automatica" not in documento
    ]


def _ruts_de_ficha(ficha: Mapping, catalogo: Mapping) -> list[str]:
    ruts = []
    for referencia in ficha.get("referencias_catalogo", []):
        rut = rut_canonico_de_registro_chofer(referencia, catalogo.get(referencia))
        if rut:
            ruts.append(rut)
    return ruts


def _leer_caras(carpeta: Path, documento: Mapping, proveedor: Callable[[], object]) -> tuple[dict, list[dict]]:
    """OCR de cada cara tras verificar que el original sigue intacto."""
    textos, archivos = {}, []
    for cara, archivo, sha256 in _caras_del_documento(documento):
        ruta = (carpeta / archivo).resolve()
        if not ruta.is_relative_to(carpeta.resolve()):
            raise ValueError("Adjunto fuera de la empresa")
        if hashlib.sha256(ruta.read_bytes()).hexdigest() != str(sha256).lower():
            raise ValueError(f"El original de {cara} no coincide con su huella registrada")
        archivos.append({"cara": cara, "archivo": archivo, "sha256": sha256})
        if ruta.suffix.lower() == ".pdf":
            continue  # el OCR existente lee imágenes; un PDF queda para revisión
        textos[cara] = list(proveedor().leer_texto(ruta))
    return textos, archivos


def extraer_licencias_pendientes(
    raiz: str | Path, *, comprobar: Callable[[], None], fabrica_ocr: Callable[[], object],
    empresa: str = EMPRESA_ACTUAL, actor: str = "MOTOR_OCR",
) -> dict:
    """Extrae una vez cada licencia PENDIENTE_EXTRACCION de la ficha.

    El OCR corre fuera del bloqueo; la escritura vuelve a leer la ficha y sólo
    agrega `extraccion_automatica` + historial si el documento sigue igual de
    pendiente. `fabrica_ocr` se invoca sólo si hay algo que leer; el
    proveedor creado se cierra al terminar."""
    resumen: dict = {"pendientes": 0, "extraidas": [], "errores": []}
    datos = leer_almacen(raiz, empresa=empresa)
    if not datos or datos.get("version") != VERSION:
        return resumen
    pendientes = _pendientes(datos)
    resumen["pendientes"] = len(pendientes)
    if not pendientes:
        return resumen
    ruta = ruta_almacen(raiz, empresa)
    catalogo = json.loads((Path(raiz) / "catalogos_privados" / "choferes.json").read_text(encoding="utf-8-sig"))
    creado: list = []

    def proveedor():
        if not creado:
            creado.append(fabrica_ocr())
        return creado[0]

    try:
        for ficha, documento in pendientes:
            comprobar()
            documento_id = documento["documento_id"]
            try:
                textos, archivos = _leer_caras(ruta.parent, documento, proveedor)
            except Exception as error:  # noqa: BLE001 -- una licencia no corta las demás
                logger.warning("Licencia %s sin extracción: %s", documento_id, error)
                resumen["errores"].append({"documento_id": documento_id, "error": str(error)})
                continue
            if textos:
                campos = extraer_campos_licencia(textos, ruts_catalogo=_ruts_de_ficha(ficha, catalogo))
            else:
                campos = {c: _campo(None, "FORMATO_SIN_OCR") for c in CAMPOS}
            extraccion = {
                "version": VERSION_EXTRACCION, "fecha": _ahora(), "actor": actor,
                "motor_ocr": type(creado[0]).__name__ if creado else "",
                "confirmado_por_humano": False, "estado": _resumen_estado(campos),
                "archivos": archivos, "campos": campos,
            }
            if _registrar(raiz, ruta, empresa, ficha["ficha_id"], documento_id, extraccion, actor, comprobar):
                resumen["extraidas"].append({
                    "documento_id": documento_id, "ficha_id": ficha["ficha_id"], "estado": extraccion["estado"],
                    "extraidos": [c for c in CAMPOS if campos[c]["estado"] == EXTRAIDO],
                    "pendientes": {c: campos[c]["motivo"] for c in CAMPOS if campos[c]["estado"] != EXTRAIDO},
                })
    finally:
        cerrar = getattr(creado[0], "cerrar", None) if creado else None
        if callable(cerrar):
            cerrar()
    return resumen


def _registrar(raiz, ruta: Path, empresa: str, ficha_id: str, documento_id: str, extraccion: dict,
               actor: str, comprobar: Callable[[], None]) -> bool:
    with bloqueo_sesion(Path(raiz) / "operacion" / "actual", "fichas_choferes_" + empresa):
        anterior = leer_almacen(raiz, empresa=empresa)
        propuesta = copy.deepcopy(anterior)
        objetivo = next((d for f, d in _pendientes(propuesta)
                         if f["ficha_id"] == ficha_id and d["documento_id"] == documento_id), None)
        if objetivo is None:
            return False  # ya extraída, reemplazada o registrada por una persona entre medio
        objetivo["extraccion_automatica"] = extraccion
        ficha = next(f for f in propuesta["choferes"] if f["ficha_id"] == ficha_id)
        ficha["historial"].append({
            "accion": "LICENCIA_EXTRACCION_AUTOMATICA", "actor": actor, "fecha": extraccion["fecha"],
            "documento_id": documento_id, "estado": extraccion["estado"],
        })
        propuesta["revision"] = int(anterior["revision"]) + 1
        _validar_v2(propuesta)
        respaldo = Path(raiz) / "respaldos" / "fichas_choferes" / uuid.uuid4().hex
        respaldo.mkdir(parents=True)
        shutil.copy2(ruta, respaldo / ruta.name)
        escribir_json_atomico(respaldo / "manifest.json", {
            "empresa": empresa, "actor": actor, "operacion": "LICENCIA_EXTRACCION_AUTOMATICA",
            "ficha_id": ficha_id, "documento_id": documento_id, "revision_anterior": anterior["revision"],
            "ruta_relativa": str(ruta.relative_to(raiz)),
        })
        comprobar()
        escribir_json_atomico(ruta, propuesta)
        return True
