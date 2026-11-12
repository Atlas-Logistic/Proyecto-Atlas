"""Identificación OCR de la patente de SOAP, revisión técnica y permiso de circulación.

La recepción (`fichas_vehiculos`) ubica el documento con la asignación que
publicó Cloud, pero eso no dice de qué vehículo es: un chofer de tracto y
rampla puede fotografiar el SOAP de la rampla. Esta etapa lee con el OCR
existente (`ProveedorOCR.leer_texto`) la patente impresa y decide con el
catálogo de vehículos (sólo vehículos CONFIRMADOS y ACTIVOS):

- Una sola patente legible, con formato chileno, que es exactamente la de un
  vehículo conocido (o un alias ya confirmado) y ninguna otra lectura con
  forma de patente -> el documento queda en `vehiculos[patente]` con
  `asociacion.metodo = PATENTE_DOCUMENTAL` y el tipo del vehículo (tracto,
  carro o camión rígido), aunque no sea la patente que fijó Cloud.
- Varias patentes, una lectura que sólo calza corrigiendo el OCR, una
  patente desconocida o no confirmada, ninguna patente, un PDF ilegible o un error de
  OCR -> `documentos_vehiculo_pendientes` con motivo y candidatos; un
  documento que estaba sólo por asignación también vuelve ahí. Nunca se
  inventa ni se corrige una patente.

Nada de esto es revisión humana: el documento sigue PENDIENTE_EXTRACCION, sin
vencimiento. La lectura queda en `identificacion_patente` (líneas con forma
de patente, candidatos) y la ubicación anterior se conserva. Los originales no
se mueven ni se tocan (se verifica su SHA-256). Una clasificación humana nunca
se reevalúa. Cada documento se lee una vez por `VERSION_IDENTIFICACION`.
"""
from __future__ import annotations

import copy
import hashlib
import logging
import re
import shutil
import unicodedata
import uuid
from pathlib import Path
from typing import Callable, Iterable

from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico
from atlas_core.catalogo_vehiculos import cargar_catalogo_vehiculos, es_confusion_ocr_de_patente, normalizar_patente_vehiculo
from atlas_core.extractor import patente_tiene_formato_chileno_estandar
from atlas_core.fichas_choferes import EMPRESA_ACTUAL, VERSION, _ahora, _validar_v2, leer_almacen, ruta_almacen
from atlas_core.fichas_vehiculos import ESTADO_PENDIENTE_CLASIFICACION, PENDIENTES, TIPOS_VEHICULO, _validar_vehiculos
from atlas_core.lectura_documento_vehiculo import TIPO_PENDIENTE

logger = logging.getLogger(__name__)

VERSION_IDENTIFICACION = 2
METODO = "PATENTE_DOCUMENTAL"
_ROTULO = re.compile(r"\b(?:PATENTE|PPU|PLACA|INSCRIPCION)\b")
# Desde 2007 las patentes usan sólo consonantes: "HORA 12" nunca es patente.
_CONSONANTES = frozenset("BCDFGHJKLMNPRSTVWXYZ")


def _patron(separador: str) -> re.Pattern:
    s = f"[.\\-·{separador}]?"
    return re.compile(rf"(?<![A-Z0-9])([A-Z]{{2}}){s}([A-Z]{{2}}|\d{{2}}){s}(\d{{2}})(?:\s?-\s?[0-9K])?(?![A-Z0-9])")


# Sin rótulo, la patente va junta o con punto/guion ("DE 2026" no lo es);
# en la línea de un rótulo PATENTE/PPU (o la siguiente) también con espacios.
_PATENTE_COMPACTA = _patron("")
_PATENTE_ROTULADA = _patron(r"\s")


def _normalizar(linea: object) -> str:
    texto = unicodedata.normalize("NFKD", str(linea or "").upper())
    return " ".join("".join(c for c in texto if not unicodedata.combining(c)).replace(":", " ").split())


def _lecturas(lineas: Iterable[str]) -> list[tuple[str, str]]:
    """(patente leída, línea) con forma de patente chilena."""
    normalizadas = [l for l in (_normalizar(x) for x in lineas) if l]
    salida = []
    for i, linea in enumerate(normalizadas):
        rotulada = bool(_ROTULO.search(linea)) or (i > 0 and bool(_ROTULO.search(normalizadas[i - 1])))
        for patron in ((_PATENTE_ROTULADA,) if rotulada else (_PATENTE_COMPACTA,)):
            for a, b, c in patron.findall(linea):
                patente = a + b + c
                if not patente_tiene_formato_chileno_estandar(patente):
                    continue
                if b.isalpha() and not set(a + b) <= _CONSONANTES:
                    continue
                salida.append((patente, linea))
    return salida


def identificar_patente(lineas: Iterable[str], vehiculos_catalogo) -> dict:
    """Decisión pura sobre el texto OCR de un documento."""
    homologables = {v.patente_canonica: v for v in vehiculos_catalogo.homologables()}
    alias = {}
    for v in homologables.values():
        for a in v.aliases:
            alias.setdefault(normalizar_patente_vehiculo(a), set()).add(v.patente_canonica)
    no_homologables = {v.patente_canonica for v in vehiculos_catalogo.vehiculos} - set(homologables)
    conocidas, dudosas, desconocidas, no_confirmadas, evidencia = set(), {}, set(), set(), []
    for leida, linea in _lecturas(lineas):
        if linea not in evidencia:
            evidencia.append(linea)
        if leida in homologables:
            conocidas.add(leida)
        elif len(alias.get(leida, ())) == 1:
            conocidas.add(next(iter(alias[leida])))
        elif leida in no_homologables:
            no_confirmadas.add(leida)
        else:
            candidatos = sorted(p for p in homologables if es_confusion_ocr_de_patente(leida, p)) or \
                sorted(alias.get(leida, ()))
            if candidatos:
                dudosas[leida] = candidatos
            else:
                desconocidas.add(leida)
    lectura = {"conocidas": sorted(conocidas), "dudosas": dudosas, "desconocidas": sorted(desconocidas),
               "no_confirmadas": sorted(no_confirmadas), "evidencia": evidencia[:10]}
    candidatos = sorted(conocidas | {c for cs in dudosas.values() for c in cs})
    if len(conocidas) == 1 and not (dudosas or desconocidas or no_confirmadas):
        patente = next(iter(conocidas))
        return {**lectura, "patente": patente, "tipo_vehiculo": homologables[patente].tipo, "motivo": "",
                "candidatos": [patente]}
    if len(conocidas) > 1 or (conocidas and (dudosas or desconocidas or no_confirmadas)):
        motivo = "VARIAS_PATENTES"
    elif dudosas:
        motivo = "LECTURA_DUDOSA"
    elif no_confirmadas:
        motivo = "PATENTE_NO_CONFIRMADA_EN_CATALOGO"
    elif desconocidas:
        motivo = "PATENTE_DESCONOCIDA"
    else:
        motivo = "PATENTE_NO_ENCONTRADA"
    return {**lectura, "patente": None, "tipo_vehiculo": None, "motivo": motivo, "candidatos": candidatos}


def _es_humana(documento: dict) -> bool:
    return bool(documento.get("clasificacion_humana")) or \
        str((documento.get("asociacion") or {}).get("metodo", "")).upper().startswith("HUMAN")


def _por_identificar(documento: dict) -> bool:
    previa = documento.get("identificacion_patente")
    # Un documento cuyo tipo quedó pendiente por OCR sigue siendo vehicular.
    return (documento.get("tipo") in (*TIPOS_VEHICULO, TIPO_PENDIENTE) and documento.get("origen") == "MOBILE"
            and not documento.get("revision_humana") and not documento.get("rechazo")
            and not documento.get("reemplazado_por") and not _es_humana(documento)
            and (previa is None or (int(previa.get("version") or 0) < VERSION_IDENTIFICACION
                 and previa.get("motivo") == "FORMATO_SIN_OCR" and str(documento.get("archivo", "")).lower().endswith(".pdf"))))


def _ubicaciones(datos: dict) -> list[tuple[str | None, dict]]:
    """(patente | None si está por clasificar, documento)."""
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


def identificar_patentes_documentos(
    raiz: str | Path, *, comprobar: Callable[[], None], fabrica_ocr: Callable[[], object],
    empresa: str = EMPRESA_ACTUAL, actor: str = "MOTOR_OCR",
) -> dict:
    resumen: dict = {"pendientes": 0, "asociados": [], "por_clasificar": [], "errores": []}
    datos = leer_almacen(raiz, empresa=empresa)
    if not datos or datos.get("version") != VERSION:
        return resumen
    objetivos = [(p, d) for p, d in _ubicaciones(datos) if _por_identificar(d)]
    resumen["pendientes"] = len(objetivos)
    if not objetivos:
        return resumen
    ruta = ruta_almacen(raiz, empresa)
    creado: list = []

    def proveedor():
        if not creado:
            creado.append(fabrica_ocr())
        return creado[0]

    try:
        for patente_actual, documento in objetivos:
            comprobar()
            documento_id = documento["documento_id"]
            try:
                lineas = _leer(ruta.parent, documento, proveedor)
            except ValueError as error:  # original alterado: no se decide nada
                resumen["errores"].append({"documento_id": documento_id, "error": str(error)})
                continue
            except Exception as error:  # noqa: BLE001 -- el OCR falló para este documento
                logger.warning("Documento de vehículo %s sin lectura OCR: %s", documento_id, error)
                lineas, motivo_fijo = [], "ERROR_OCR"
            else:
                motivo_fijo = "FORMATO_SIN_OCR" if lineas is None else ""
            catalogo = cargar_catalogo_vehiculos(Path(raiz) / "catalogos_privados" / "vehiculos.json")
            decision = identificar_patente(lineas or [], catalogo)
            if motivo_fijo:
                decision.update(patente=None, tipo_vehiculo=None, motivo=motivo_fijo, candidatos=[])
            identificacion = {
                "version": VERSION_IDENTIFICACION, "fecha": _ahora(), "actor": actor,
                "motor_ocr": type(creado[0]).__name__ if creado else "", "confirmado_por_humano": False,
                "estado": "ASOCIADA" if decision["patente"] else ESTADO_PENDIENTE_CLASIFICACION,
                "patente": decision["patente"], "tipo_vehiculo": decision["tipo_vehiculo"], "motivo": decision["motivo"],
                "conocidas": decision["conocidas"], "dudosas": decision["dudosas"],
                "desconocidas": decision["desconocidas"], "no_confirmadas": decision["no_confirmadas"],
                "evidencia": decision["evidencia"],
            }
            if _aplicar(raiz, ruta, empresa, documento_id, patente_actual, identificacion, decision, actor, comprobar):
                (resumen["asociados"] if decision["patente"] else resumen["por_clasificar"]).append({
                    "documento_id": documento_id, "tipo": documento["tipo"], "patente": decision["patente"],
                    "tipo_vehiculo": decision["tipo_vehiculo"], "motivo": decision["motivo"],
                })
    finally:
        cerrar = getattr(creado[0], "cerrar", None) if creado else None
        if callable(cerrar):
            cerrar()
    return resumen


def _ficha_vehiculo(datos: dict, patente: str) -> dict:
    ficha = next((v for v in datos.setdefault("vehiculos", [])
                  if normalizar_patente_vehiculo(str(v.get("patente", ""))) == patente), None)
    if ficha is None:
        ficha = {"patente": patente, "documentos": [], "historial": []}
        datos["vehiculos"].append(ficha)
    ficha.setdefault("historial", [])
    return ficha


def _aplicar(raiz, ruta: Path, empresa: str, documento_id: str, patente_actual: str | None, identificacion: dict,
             decision: dict, actor: str, comprobar: Callable[[], None]) -> bool:
    with bloqueo_sesion(Path(raiz) / "operacion" / "actual", "fichas_choferes_" + empresa):
        anterior = leer_almacen(raiz, empresa=empresa)
        propuesta = copy.deepcopy(anterior)
        actual = next(((p, d) for p, d in _ubicaciones(propuesta) if d.get("documento_id") == documento_id), None)
        # Si alguien lo movió, lo clasificó o ya se identificó entre medio, no se toca.
        if actual is None or actual[0] != patente_actual or not _por_identificar(actual[1]):
            return False
        documento = actual[1]
        instante = identificacion["fecha"]
        origen = _ficha_vehiculo(propuesta, patente_actual)["documentos"] if patente_actual else propuesta[PENDIENTES]
        destino_patente = decision["patente"]
        documento["identificacion_patente"] = identificacion
        evento = {"actor": actor, "fecha": instante, "documento_id": documento_id, "tipo": documento["tipo"],
                  "motivo": decision["motivo"], "patente": destino_patente}
        if destino_patente:
            previa = documento.pop("asociacion", None)
            if previa:
                documento.setdefault("asociaciones_anteriores", []).append(previa)
            if "clasificacion" in documento:
                documento["clasificacion_anterior"] = documento.pop("clasificacion")
            documento["asociacion"] = {
                "metodo": METODO, "patente": destino_patente, "tipo_vehiculo": decision["tipo_vehiculo"],
                "coincide_con_patente_cloud": destino_patente == (documento.get("procedencia") or {}).get("patente_cloud"),
                "fecha": instante,
            }
            if patente_actual != destino_patente:
                origen.remove(documento)
                _ficha_vehiculo(propuesta, destino_patente)["documentos"].append(documento)
                if patente_actual:
                    _ficha_vehiculo(propuesta, patente_actual)["historial"].append(
                        {**evento, "accion": "DOCUMENTO_VEHICULO_REASIGNADO_POR_PATENTE"})
            _ficha_vehiculo(propuesta, destino_patente)["historial"].append(
                {**evento, "accion": "DOCUMENTO_VEHICULO_IDENTIFICADO_POR_PATENTE"})
        else:
            previa_clasificacion = documento.get("clasificacion") or {}
            candidatos = set(decision["candidatos"]) | set(previa_clasificacion.get("candidatos", []))
            if patente_actual:
                # Sólo estaba por asignación: sin patente documental no queda asociado.
                documento["asociacion_anterior"] = documento.pop("asociacion", None)
                candidatos.add(patente_actual)
                origen.remove(documento)
                propuesta.setdefault(PENDIENTES, []).append(documento)
                _ficha_vehiculo(propuesta, patente_actual)["historial"].append(
                    {**evento, "accion": "DOCUMENTO_VEHICULO_SIN_PATENTE_DOCUMENTAL"})
            documento["clasificacion"] = {
                "estado": ESTADO_PENDIENTE_CLASIFICACION, "motivo": decision["motivo"],
                "patente_cloud": (documento.get("procedencia") or {}).get("patente_cloud", ""),
                "candidatos": sorted(candidatos),
                "motivo_asignacion": previa_clasificacion.get("motivo_asignacion")
                or previa_clasificacion.get("motivo") or ("ASIGNACION_CONFIRMADA" if patente_actual else ""),
            }
            documento.setdefault("historial", []).append({**evento, "accion": "DOCUMENTO_VEHICULO_POR_CLASIFICAR"})
        propuesta["revision"] = int(anterior["revision"]) + 1
        _validar_v2(propuesta)
        _validar_vehiculos(propuesta)
        respaldo = Path(raiz) / "respaldos" / "fichas_choferes" / uuid.uuid4().hex
        respaldo.mkdir(parents=True)
        shutil.copy2(ruta, respaldo / ruta.name)
        escribir_json_atomico(respaldo / "manifest.json", {
            "empresa": empresa, "actor": actor, "operacion": "IDENTIFICACION_PATENTE_DOCUMENTO_VEHICULO",
            "documento_id": documento_id, "desde": patente_actual, "hacia": destino_patente,
            "motivo": decision["motivo"], "revision_anterior": anterior["revision"],
            "ruta_relativa": str(ruta.relative_to(raiz)),
        })
        comprobar()
        escribir_json_atomico(ruta, propuesta)
        return True
