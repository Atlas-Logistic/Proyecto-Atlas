"""Extracción automática del vencimiento de SOAP, revisión técnica y permiso de circulación.

Lee con el OCR existente (`ProveedorOCR.leer_texto`) el original ya guardado
del documento de vehículo y extrae la fecha de vencimiento impresa:

- La lectura queda en `extraccion_automatica` del mismo documento
  (`campos.vencimiento`, con evidencia y las otras fechas leídas),
  `procedencia: AUTOMATICA_OCR` y `confirmado_por_humano: false`.
- Una fecha inequívoca (EXTRAIDO, con evidencia, del mismo original) de un
  documento asociado a un vehículo pasa a ser su `vencimiento` operativo
  (`activar_vencimientos_extraidos`, sin volver a leer el OCR):
  `estado_revision` VENCIMIENTO_OCR_AUTOMATICO y `vencimiento_registro` con
  procedencia OCR_AUTOMATICO, evidencia y `confirmado_por_humano: false`.
  Nunca es una confirmación humana. La vigencia (vigente, próximo a vencer,
  vencido) no se guarda: quien la muestra la calcula con la fecha del día.
  Una abstención deja el documento PENDIENTE_EXTRACCION, sin vencimiento.
- Se distingue el vencimiento de las fechas de emisión, pago, contratación,
  inspección o inicio de vigencia por el rótulo impreso que las acompaña. En
  el SOAP los rótulos RIGE DESDE / HASTA salen en una columna y sus valores en
  otra: se toma el par en orden. Una fecha con hora es la marca de emisión.
- Ante varias fechas posibles, un rótulo sin fecha legible, una fecha
  anterior a la de emisión/pago/inspección o un plazo improbable, el campo
  queda PENDIENTE_REVISION con su motivo; nunca se elige por aproximación.
- El original sólo se lee (se verifica su SHA-256). Un documento con
  vencimiento registrado por una persona, ya revisado o confirmado no se
  procesa ni se sobrescribe. Cada documento se lee una vez por `VERSION_EXTRACCION`; una
  extracción anterior se conserva en `extracciones_anteriores`.

Corre en el ciclo PULL bajo su lease (`comprobar`), después de identificar la
patente.
"""
from __future__ import annotations

import copy
import hashlib
import logging
import re
import shutil
import unicodedata
import uuid
from datetime import date
from pathlib import Path
from typing import Callable, Iterable

from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico
from atlas_core.fichas_choferes import EMPRESA_ACTUAL, ESTADO_PENDIENTE_EXTRACCION, VERSION, _ahora, _validar_v2, \
    leer_almacen, ruta_almacen
from atlas_core.fichas_vehiculos import PENDIENTES, TIPOS_VEHICULO, _validar_vehiculos

logger = logging.getLogger(__name__)

VERSION_EXTRACCION = 2
PROCEDENCIA = "AUTOMATICA_OCR"
# Vencimiento operativo registrado sin intervención humana.
ESTADO_VENCIMIENTO_AUTOMATICO = "VENCIMIENTO_OCR_AUTOMATICO"
PROCEDENCIA_VENCIMIENTO = "OCR_AUTOMATICO"
EXTRAIDO = "EXTRAIDO"
PENDIENTE_REVISION = "PENDIENTE_REVISION"
# Ventana de líneas tras un rótulo sin valor: el OCR lee primero la columna de
# rótulos y después la de valores.
VENTANA = 8
VENTANA_REFERENCIA = 3
# Ninguno de estos documentos rige más de un año (el permiso de vehículos
# pesados va de octubre a septiembre): más de 25 meses es una lectura errónea.
PLAZO_MAXIMO_DIAS = 760

_MESES = {"ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6, "JULIO": 7, "AGOSTO": 8,
          "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12}
_HORA = r"(\s*\d{1,2}:\d{2}(?::\d{2})?)?(?!\d)"
_FECHA_NUMERICA = re.compile(r"(?<!\d)(\d{1,2})\s*[/.-]\s*(\d{1,2})\s*[/.-]\s*(\d{4})" + _HORA)
_FECHA_TEXTO = re.compile(r"(?<!\d)(\d{1,2})\s*(?:DE\s*)?(" + "|".join(_MESES) + r")\s*(?:DEL?\s*)?(\d{4})" + _HORA)
# Algo con forma de fecha que no se pudo leer completa (año de dos cifras...).
_FECHA_INCOMPLETA = re.compile(r"\d{1,2}\s*[/.-]\s*\d{1,2}\s*[/.-]\s*\d{2,3}(?!\d)")

# Rótulos. El OCR real junta palabras ("VALIDAHASTA"): espacios opcionales.
FIN, INICIO, REFERENCIA = "FIN", "INICIO", "REFERENCIA"
_ROTULOS_COMUNES = [
    (FIN, r"FECHA\s*(?:DE\s*)?VENCIMIENTO|VENCIMIENTO|\bVENCE\b|VALID[AO]\s*HASTA|VIGENTE\s*HASTA"),
    (INICIO, r"RIGE\s*DESDE|VIGENCIA\s*DESDE|\bDESDE\b|\bRIGE\b"),
    (REFERENCIA, r"FECHA\s*(?:DE\s*)?(?:EMISION|PAGO|CONTRATACION|INSPECCION|REVISION|EMITIDO)|\bFECHA\b|"
                 r"\bEMISION\b|\bEMITID[OA]\b|CONTRATACION|INSPECCION|\bPAGAD[OA]\b"),
]
# Reglas por tipo: qué rótulos cierran la vigencia en cada documento.
_FIN_POR_TIPO = {
    # Póliza: vigencia RIGE DESDE ... HASTA ...
    "SOAP": r"\bHASTA\b|VIGENCIA\s*HASTA|TERMINO\s*(?:DE\s*)?VIGENCIA",
    # Certificado: REVISION TECNICA VALIDA HASTA / PROXIMA REVISION.
    "REVISION_TECNICA": r"PROXIMA\s*REVISION|PROXIMO\s*CONTROL",
    # Comprobante de pago: VENCE / VENCIMIENTO (cuerpo y talones).
    "PERMISO_CIRCULACION": r"",
}
# El vencimiento de una cuota es un plazo de pago, no de vigencia.
_CUOTA = re.compile(r"CUOTA")


def _rotulos(tipo: str) -> list[tuple[str, re.Pattern]]:
    reglas = list(_ROTULOS_COMUNES)
    if _FIN_POR_TIPO.get(tipo):
        reglas.insert(1, (FIN, _FIN_POR_TIPO[tipo]))
    return [(clase, re.compile(patron)) for clase, patron in reglas]


def _normalizar(linea: object) -> str:
    texto = unicodedata.normalize("NFKD", str(linea or "").upper())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(texto.split())  # ":" se conserva: separa la hora de una marca de emisión


def _fechas(texto: str) -> tuple[list[dict], list[str]]:
    """Fechas legibles (ISO, con marca de hora) y fragmentos con forma de fecha ilegibles."""
    halladas, ilegibles, ocupado = [], [], []
    for patron, mes_texto in ((_FECHA_NUMERICA, False), (_FECHA_TEXTO, True)):
        for m in patron.finditer(texto):
            dia, mes, anio, hora = m.groups()
            mes = _MESES[mes] if mes_texto else int(mes)
            ocupado.append(m.span())
            try:
                valor = date(int(anio), mes, int(dia))
            except ValueError:
                ilegibles.append(m.group(0).strip())
                continue
            if not 2000 <= valor.year <= 2100:
                ilegibles.append(m.group(0).strip())
                continue
            halladas.append({"valor": valor.isoformat(), "texto": m.group(0).strip(), "hora": bool(hora),
                             "posicion": m.start()})
    for m in _FECHA_INCOMPLETA.finditer(texto):
        if not any(a <= m.start() < b for a, b in ocupado):
            ilegibles.append(m.group(0).strip())
    return sorted(halladas, key=lambda f: f["posicion"]), ilegibles


def _segmentos(linea: str, reglas) -> list[tuple[str, str, str]]:
    """(clase, rótulo, texto que le sigue hasta el próximo rótulo) en orden."""
    marcas = []
    for clase, patron in reglas:
        for m in patron.finditer(linea):
            if not any(a < m.end() and m.start() < b for _, _, a, b in marcas):
                marcas.append((clase, m.group(0), m.start(), m.end()))
    marcas.sort(key=lambda x: x[2])
    return [(clase, rotulo, linea[fin:(marcas[i + 1][2] if i + 1 < len(marcas) else len(linea))])
            for i, (clase, rotulo, _, fin) in enumerate(marcas)]


def extraer_vencimiento(tipo: str, lineas: Iterable[str]) -> dict:
    """Decisión pura sobre el texto OCR de un documento de vehículo."""
    if tipo not in TIPOS_VEHICULO:
        raise ValueError(f"Tipo de documento de vehículo no admitido: {tipo}")
    reglas = _rotulos(tipo)
    normalizadas = [l for l in (_normalizar(x) for x in lineas) if l]
    analisis = []  # por línea: segmentos con sus fechas, y fechas libres (sin rótulo en la línea)
    for linea in normalizadas:
        segmentos = _segmentos(linea, reglas)
        if segmentos:
            libres = _fechas(linea[:linea.find(segmentos[0][1])])[0]
            detalle = [(clase, rotulo, *_fechas(texto)) for clase, rotulo, texto in segmentos]
        else:
            libres, detalle = _fechas(linea)[0], []
        analisis.append({"linea": linea, "segmentos": detalle, "libres": libres})

    candidatos, referencias, ilegibles, evidencia, otras, usadas = [], [], [], [], [], set()
    abstenciones = []  # motivos que impiden decidir aunque haya una fecha
    hubo_rotulo = False

    def otra(fecha: dict, rol: str, linea: str):
        otras.append({"valor": fecha["valor"], "rol": rol, "texto": linea})

    def siguientes_libres(i: int, alcance: int) -> list[tuple[int, dict]]:
        salida = []
        for j in range(i + 1, min(len(analisis), i + 1 + alcance)):
            salida.extend((j, f) for f in analisis[j]["libres"] if (j, f["posicion"]) not in usadas)
        return salida

    for i, fila in enumerate(analisis):
        linea = fila["linea"]
        for k, (clase, rotulo, fechas, malas) in enumerate(fila["segmentos"]):
            if clase == FIN and _CUOTA.search(linea):
                for f in fechas:
                    otra(f, "PLAZO_CUOTA", linea)
                continue
            if clase in (INICIO, REFERENCIA):
                for f in fechas:
                    referencias.append(f["valor"]); otra(f, clase, linea)
                if not fechas and k == len(fila["segmentos"]) - 1 and clase == REFERENCIA:
                    # FECHA en su línea y el valor en la siguiente (pago, inspección).
                    for j, f in siguientes_libres(i, VENTANA_REFERENCIA)[:1]:
                        if not f["hora"]:
                            usadas.add((j, f["posicion"])); referencias.append(f["valor"])
                            otra(f, clase, f"{linea} / {analisis[j]['linea']}")
                continue
            hubo_rotulo = True
            if fechas or malas:
                ilegibles.extend(malas)
                for f in fechas:
                    if f["hora"]:
                        otra(f, "MARCA_HORARIA", linea)
                    else:
                        candidatos.append(f["valor"]); evidencia.append({"rotulo": rotulo, "texto": linea})
                continue
            if k != len(fila["segmentos"]) - 1:
                continue  # rótulo seguido de otro rótulo en la misma línea: el par se resuelve abajo
            # Rótulo sin valor: columna de rótulos, valores en las líneas siguientes.
            par = any(c == INICIO and not f for c, _, f, _ in fila["segmentos"][:k]) or any(
                c == INICIO and not f for prev in analisis[max(0, i - 2):i] for c, _, f, _ in prev["segmentos"])
            ventana = [(j, f) for j, f in siguientes_libres(i, VENTANA)]
            for j, f in ventana:
                if f["hora"]:
                    usadas.add((j, f["posicion"])); otra(f, "MARCA_HORARIA", analisis[j]["linea"])
            ventana = [(j, f) for j, f in ventana if not f["hora"]]
            if par:
                if len(ventana) == 2 and ventana[0][1]["valor"] < ventana[1][1]["valor"]:
                    (j0, desde), (j1, hasta) = ventana
                    usadas.update({(j0, desde["posicion"]), (j1, hasta["posicion"])})
                    referencias.append(desde["valor"]); otra(desde, INICIO, analisis[j0]["linea"])
                    candidatos.append(hasta["valor"])
                    evidencia.append({"rotulo": rotulo, "texto": f"{linea} / {analisis[j1]['linea']}",
                                      "par_desde": desde["valor"]})
                else:
                    # Desde/hasta sin un par ordenado: no se adivina cuál es cuál.
                    candidatos.extend(f["valor"] for _, f in ventana)
                    evidencia.extend({"rotulo": rotulo, "texto": analisis[j]["linea"]} for j, _ in ventana)
                    abstenciones.append("FECHAS_CONTRADICTORIAS" if len(ventana) == 2 else
                                        "VARIAS_FECHAS" if len(ventana) > 2 else "PAR_DESDE_HASTA_INCOMPLETO")
                continue
            for j, f in ventana:
                usadas.add((j, f["posicion"]))
                candidatos.append(f["valor"]); evidencia.append({"rotulo": rotulo, "texto": f"{linea} / {analisis[j]['linea']}"})

    distintos = sorted(set(candidatos))
    base = {"evidencia": evidencia[:10], "otras_fechas": otras[:20], "observados": distintos,
            "referencias": sorted(set(referencias))}
    if abstenciones:
        return {**base, "valor": None, "estado": PENDIENTE_REVISION, "motivo": abstenciones[0]}
    if len(distintos) > 1:
        return {**base, "valor": None, "estado": PENDIENTE_REVISION, "motivo": "VARIAS_FECHAS"}
    if not distintos:
        motivo = "ILEGIBLE" if ilegibles or hubo_rotulo else "NO_ENCONTRADO"
        return {**base, "valor": None, "estado": PENDIENTE_REVISION, "motivo": motivo, "observados": ilegibles[:10]}
    valor = distintos[0]
    if referencias and valor <= max(referencias):
        return {**base, "valor": None, "estado": PENDIENTE_REVISION, "motivo": "FECHAS_CONTRADICTORIAS"}
    if referencias and (date.fromisoformat(valor) - date.fromisoformat(max(referencias))).days > PLAZO_MAXIMO_DIAS:
        return {**base, "valor": None, "estado": PENDIENTE_REVISION, "motivo": "PLAZO_IMPROBABLE"}
    return {**base, "valor": valor, "estado": EXTRAIDO, "motivo": ""}


# ------------------------------------------------------------------ ciclo PULL


def _vencimiento_automatico(documento: dict) -> bool:
    return documento.get("estado_revision") == ESTADO_VENCIMIENTO_AUTOMATICO and \
        (documento.get("vencimiento_registro") or {}).get("procedencia") == PROCEDENCIA_VENCIMIENTO


def _confirmado_por_persona(documento: dict) -> bool:
    if documento.get("confirmacion_humana") or documento.get("revision_humana"):
        return True
    if _vencimiento_automatico(documento):
        return False
    return bool(documento.get("vencimiento")) or documento.get("estado_revision") != ESTADO_PENDIENTE_EXTRACCION


def _por_extraer(documento: dict) -> bool:
    if documento.get("tipo") not in TIPOS_VEHICULO or documento.get("reemplazado_por") \
            or _confirmado_por_persona(documento) or _vencimiento_automatico(documento):
        return False
    previa = documento.get("extraccion_automatica")
    if previa is None:
        return True
    return previa.get("estado") != "COMPLETA" and int(previa.get("version") or 0) < VERSION_EXTRACCION


def _ubicaciones(datos: dict) -> list[tuple[str | None, dict]]:
    salida = [(v.get("patente"), d) for v in datos.get("vehiculos", []) for d in v.get("documentos", [])]
    return salida + [(None, d) for d in datos.get(PENDIENTES, [])]


def _leer(carpeta: Path, documento: dict, proveedor: Callable[[], object]) -> list[str] | None:
    ruta = (carpeta / documento["archivo"]).resolve()
    if not ruta.is_relative_to(carpeta.resolve()):
        raise ValueError("Adjunto fuera de la empresa")
    if hashlib.sha256(ruta.read_bytes()).hexdigest() != str(documento.get("sha256", "")).lower():
        raise ValueError("El original no coincide con su huella registrada")
    from atlas_core.lectura_documento_vehiculo import leer_texto_documento
    return leer_texto_documento(ruta, proveedor)


def extraer_vencimientos_vehiculos(
    raiz: str | Path, *, comprobar: Callable[[], None], fabrica_ocr: Callable[[], object],
    empresa: str = EMPRESA_ACTUAL, actor: str = "MOTOR_OCR",
) -> dict:
    """Propone una vez el vencimiento de cada documento de vehículo pendiente.

    El OCR corre fuera del bloqueo; la escritura vuelve a leer la ficha y sólo
    agrega `extraccion_automatica` + historial si el documento sigue igual de
    pendiente. Un original alterado o un fallo del OCR no registran nada (se
    reintenta en el ciclo siguiente)."""
    resumen: dict = {"pendientes": 0, "extraidos": [], "errores": [], "activados": []}
    datos = leer_almacen(raiz, empresa=empresa)
    if not datos or datos.get("version") != VERSION:
        return resumen
    objetivos = [(p, d) for p, d in _ubicaciones(datos) if _por_extraer(d)]
    resumen["pendientes"] = len(objetivos)
    if objetivos:
        _extraer(raiz, objetivos, resumen, comprobar=comprobar, fabrica_ocr=fabrica_ocr, empresa=empresa, actor=actor)
    # Lecturas inequívocas (nuevas o de ciclos anteriores) -> vencimiento operativo, sin OCR.
    activacion = activar_vencimientos_extraidos(raiz, comprobar=comprobar, empresa=empresa, actor=actor)
    resumen["activados"] = activacion["activados"]
    resumen["errores"] += activacion["errores"]
    return resumen


def _extraer(raiz, objetivos, resumen: dict, *, comprobar, fabrica_ocr, empresa: str, actor: str) -> None:
    ruta = ruta_almacen(raiz, empresa)
    creado: list = []

    def proveedor():
        if not creado:
            creado.append(fabrica_ocr())
        return creado[0]

    try:
        for patente, documento in objetivos:
            comprobar()
            documento_id = documento["documento_id"]
            try:
                lineas = _leer(ruta.parent, documento, proveedor)
            except Exception as error:  # noqa: BLE001 -- un documento no corta los demás
                logger.warning("Documento de vehículo %s sin extracción de vencimiento: %s", documento_id, error)
                resumen["errores"].append({"documento_id": documento_id, "error": str(error)})
                continue
            if lineas is None:
                campo = {"valor": None, "estado": PENDIENTE_REVISION, "motivo": "FORMATO_SIN_OCR", "evidencia": [],
                         "otras_fechas": [], "observados": [], "referencias": []}
            else:
                campo = extraer_vencimiento(documento["tipo"], lineas)
            from atlas_core.lectura_documento_vehiculo import extraer_campos_adicionales
            adicionales = extraer_campos_adicionales(lineas or [])
            extraccion = {
                "version": VERSION_EXTRACCION, "fecha": _ahora(), "actor": actor, "procedencia": PROCEDENCIA,
                "motor_ocr": type(creado[0]).__name__ if creado else "", "confirmado_por_humano": False,
                "estado": "COMPLETA" if campo["estado"] == EXTRAIDO else "SIN_DATOS", "regla": documento["tipo"],
                "archivos": [{"archivo": documento["archivo"], "sha256": documento["sha256"]}],
                "campos": {"vencimiento": campo, **adicionales},
            }
            if _registrar(raiz, ruta, empresa, documento_id, extraccion, actor, comprobar):
                resumen["extraidos"].append({
                    "documento_id": documento_id, "tipo": documento["tipo"], "patente": patente,
                    "estado": campo["estado"], "vencimiento": campo["valor"], "motivo": campo["motivo"],
                })
    finally:
        cerrar = getattr(creado[0], "cerrar", None) if creado else None
        if callable(cerrar):
            cerrar()


def _registrar(raiz, ruta: Path, empresa: str, documento_id: str, extraccion: dict, actor: str,
               comprobar: Callable[[], None]) -> bool:
    with bloqueo_sesion(Path(raiz) / "operacion" / "actual", "fichas_choferes_" + empresa):
        anterior = leer_almacen(raiz, empresa=empresa)
        propuesta = copy.deepcopy(anterior)
        actual = next(((p, d) for p, d in _ubicaciones(propuesta) if d.get("documento_id") == documento_id), None)
        # Movido, revisado por una persona o ya extraído entre medio: no se toca.
        if actual is None or not _por_extraer(actual[1]):
            return False
        patente, documento = actual
        if documento.get("sha256") != extraccion["archivos"][0]["sha256"]:
            return False
        previa = documento.get("extraccion_automatica")
        if previa is not None:
            documento.setdefault("extracciones_anteriores", []).append(previa)
        documento["extraccion_automatica"] = extraccion
        campo = extraccion["campos"]["vencimiento"]
        evento = {"accion": "DOCUMENTO_VEHICULO_EXTRACCION_VENCIMIENTO", "actor": actor, "fecha": extraccion["fecha"],
                  "documento_id": documento_id, "tipo": documento["tipo"], "estado": campo["estado"],
                  "vencimiento_propuesto": campo["valor"], "motivo": campo["motivo"],
                  "version": extraccion["version"]}
        if patente:
            ficha = next(v for v in propuesta["vehiculos"] if v.get("patente") == patente)
            ficha.setdefault("historial", []).append(evento)
        else:
            documento.setdefault("historial", []).append(evento)
        propuesta["revision"] = int(anterior["revision"]) + 1
        _validar_v2(propuesta)
        _validar_vehiculos(propuesta)
        respaldo = Path(raiz) / "respaldos" / "fichas_choferes" / uuid.uuid4().hex
        respaldo.mkdir(parents=True)
        shutil.copy2(ruta, respaldo / ruta.name)
        escribir_json_atomico(respaldo / "manifest.json", {
            "empresa": empresa, "actor": actor, "operacion": "EXTRACCION_VENCIMIENTO_DOCUMENTO_VEHICULO",
            "documento_id": documento_id, "patente": patente, "estado": campo["estado"],
            "revision_anterior": anterior["revision"], "ruta_relativa": str(ruta.relative_to(raiz)),
        })
        comprobar()
        escribir_json_atomico(ruta, propuesta)
        return True


# ------------------------------------------------ vencimiento operativo (sin OCR)


def _activable(patente: str | None, documento: dict) -> bool:
    """Lectura inequívoca, con evidencia y del mismo original, de un documento
    asociado a un vehículo, aún sin vencimiento ni intervención humana."""
    if not patente or documento.get("tipo") not in TIPOS_VEHICULO or documento.get("reemplazado_por") \
            or documento.get("estado_revision") != ESTADO_PENDIENTE_EXTRACCION or documento.get("vencimiento") \
            or _confirmado_por_persona(documento):
        return False
    extraccion = documento.get("extraccion_automatica") or {}
    campo = (extraccion.get("campos") or {}).get("vencimiento") or {}
    archivos = extraccion.get("archivos") or []
    try:
        date.fromisoformat(str(campo.get("valor") or ""))
    except ValueError:
        return False
    return (extraccion.get("estado") == "COMPLETA" and extraccion.get("confirmado_por_humano") is False
            and extraccion.get("procedencia") == PROCEDENCIA and campo.get("estado") == EXTRAIDO
            and not campo.get("motivo") and bool(campo.get("evidencia"))
            and len(archivos) == 1 and archivos[0].get("sha256") == documento.get("sha256")
            and archivos[0].get("archivo") == documento.get("archivo"))


def activar_vencimientos_extraidos(
    raiz: str | Path, *, comprobar: Callable[[], None], empresa: str = EMPRESA_ACTUAL, actor: str = "MOTOR_OCR",
) -> dict:
    """Registra como vencimiento operativo cada lectura inequívoca ya extraída.

    No ejecuta OCR: usa `extraccion_automatica` y verifica que el original
    conserve su huella. No toca archivo, sha256, patente, asociación ni la
    lectura; una abstención o un dato humano nunca se activan."""
    resumen: dict = {"activados": [], "errores": []}
    datos = leer_almacen(raiz, empresa=empresa)
    if not datos or datos.get("version") != VERSION:
        return resumen
    ruta = ruta_almacen(raiz, empresa)
    for patente, documento in [(p, d) for p, d in _ubicaciones(datos) if _activable(p, d)]:
        comprobar()
        documento_id = documento["documento_id"]
        original = (ruta.parent / documento["archivo"]).resolve()
        try:
            if not original.is_relative_to(ruta.parent.resolve()) or \
                    hashlib.sha256(original.read_bytes()).hexdigest() != str(documento["sha256"]).lower():
                raise ValueError("El original no coincide con su huella registrada")
        except (OSError, ValueError) as error:
            resumen["errores"].append({"documento_id": documento_id, "error": str(error)})
            continue
        valor = _activar(raiz, ruta, empresa, documento_id, actor, comprobar)
        if valor:
            resumen["activados"].append({"documento_id": documento_id, "tipo": documento["tipo"], "patente": patente,
                                         "vencimiento": valor})
    return resumen


def _activar(raiz, ruta: Path, empresa: str, documento_id: str, actor: str, comprobar: Callable[[], None]) -> str | None:
    with bloqueo_sesion(Path(raiz) / "operacion" / "actual", "fichas_choferes_" + empresa):
        anterior = leer_almacen(raiz, empresa=empresa)
        propuesta = copy.deepcopy(anterior)
        actual = next(((p, d) for p, d in _ubicaciones(propuesta) if d.get("documento_id") == documento_id), None)
        # Movido, registrado o revisado por una persona entre medio: no se toca.
        if actual is None or not _activable(*actual):
            return None
        patente, documento = actual
        extraccion = documento["extraccion_automatica"]
        campo = extraccion["campos"]["vencimiento"]
        instante = _ahora()
        documento["vencimiento"] = campo["valor"]
        documento["estado_revision"] = ESTADO_VENCIMIENTO_AUTOMATICO
        documento["vencimiento_registro"] = {
            "procedencia": PROCEDENCIA_VENCIMIENTO, "confirmado_por_humano": False, "actor": actor, "fecha": instante,
            "estado_revision_anterior": ESTADO_PENDIENTE_EXTRACCION, "version_extraccion": extraccion["version"],
            "fecha_extraccion": extraccion["fecha"], "motor_ocr": extraccion.get("motor_ocr", ""),
            "archivo": documento["archivo"], "sha256": documento["sha256"], "evidencia": campo["evidencia"],
        }
        ficha = next(v for v in propuesta["vehiculos"] if v.get("patente") == patente)
        ficha.setdefault("historial", []).append({
            "accion": "DOCUMENTO_VEHICULO_VENCIMIENTO_AUTOMATICO", "actor": actor, "fecha": instante,
            "documento_id": documento_id, "tipo": documento["tipo"], "vencimiento": campo["valor"],
            "procedencia": PROCEDENCIA_VENCIMIENTO, "confirmado_por_humano": False,
            "version_extraccion": extraccion["version"],
        })
        propuesta["revision"] = int(anterior["revision"]) + 1
        _validar_v2(propuesta)
        _validar_vehiculos(propuesta)
        respaldo = Path(raiz) / "respaldos" / "fichas_choferes" / uuid.uuid4().hex
        respaldo.mkdir(parents=True)
        shutil.copy2(ruta, respaldo / ruta.name)
        escribir_json_atomico(respaldo / "manifest.json", {
            "empresa": empresa, "actor": actor, "operacion": "ACTIVACION_VENCIMIENTO_AUTOMATICO_DOCUMENTO_VEHICULO",
            "documento_id": documento_id, "patente": patente, "vencimiento": campo["valor"],
            "revision_anterior": anterior["revision"], "ruta_relativa": str(ruta.relative_to(raiz)),
        })
        comprobar()
        escribir_json_atomico(ruta, propuesta)
        return campo["valor"]
