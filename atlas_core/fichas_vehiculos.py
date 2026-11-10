"""Documentos de vehículo enviados desde Mobile -> ficha del vehículo.

Los documentos vehiculares llegan desde Cloud con la
patente que Cloud fijó al recibirlos (la asignación que Motor le publicó,
`cloud_asignaciones_vehiculo`). Motor la acepta sólo si la asignación
confirmada vigente la respalda sin ambigüedad, con la misma regla de la
ficha (`fichas_choferes.asignaciones_de_chofer`): nunca OCR ni viajes.

- Asociado: el tracto CONFIRMADO del chofer es esa patente y no tiene carro
  confirmado ni en conflicto -> el documento va a `vehiculos[patente]`.
- Pendiente de clasificación: con un carro confirmado o en conflicto el
  documento puede ser de cualquiera de los dos; si la asignación cambió, no
  existe, o el chofer no está vigente / no tiene RUT, tampoco se elige. Queda
  en `documentos_vehiculo_pendientes` con su motivo y candidatos, sin patente
  inventada (Desktop ignora esa lista y no la muestra como vigente).

En ambos casos el documento queda PENDIENTE_EXTRACCION (sin vencimiento ni
revisión humana), con su original y SHA-256 intactos, procedencia y
auditoría. Idempotente por `origen_documento_id`; el mismo archivo (tipo +
SHA-256) recibido otra vez para el mismo destino no duplica: se anota como
origen adicional. Lo invoca el PULL bajo su lease (`comprobar`).
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import uuid
from pathlib import Path, PureWindowsPath

from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico
from atlas_core.catalogo_vehiculos import cargar_catalogo_vehiculos, normalizar_patente_vehiculo
from atlas_core.catalogos import rut_canonico_de_registro_chofer
from atlas_core.fichas_choferes import (
    ESTADO_PENDIENTE_EXTRACCION, VERSION, _ahora, _original_valido, _validar_v2, asignaciones_de_chofer,
    leer_almacen, ruta_almacen,
)

TIPOS_VEHICULO = ("SOAP", "REVISION_TECNICA", "PERMISO_CIRCULACION",
                  "CERTIFICADO_EMISION_GASES", "POLIZA_RESPONSABILIDAD_CIVIL", "POLIZA_ROBO")
TIPO_SEGURO_CARGA = "SEGURO_CARGA"
ESTADO_PENDIENTE_CLASIFICACION = "PENDIENTE_CLASIFICACION"
PENDIENTES = "documentos_vehiculo_pendientes"
_PATENTE = re.compile(r"[A-Z0-9]{4,8}")


def _clasificar(chofer_id: str, patente_cloud: str, choferes: dict, vehiculos) -> dict:
    """{patente, motivo, candidatos}: patente sólo si es inequívoca."""
    registro = choferes.get(chofer_id)
    if not isinstance(registro, dict) or not registro.get("activo", True):
        return {"patente": None, "motivo": "CHOFER_NO_VIGENTE", "candidatos": []}
    rut = rut_canonico_de_registro_chofer(chofer_id, registro)
    if not rut:
        return {"patente": None, "motivo": "CHOFER_SIN_RUT", "candidatos": []}
    asignacion = asignaciones_de_chofer(rut, vehiculos)
    tracto, rampla = asignacion["tracto"], asignacion["rampla"]
    candidatos = sorted(set(tracto["candidatos"]) | set(rampla["candidatos"]))
    if tracto["estado"] != "CONFIRMADO":
        return {"patente": None, "motivo": "SIN_ASIGNACION_CONFIRMADA", "candidatos": candidatos}
    if tracto["patente"] != patente_cloud:
        return {"patente": None, "motivo": "ASIGNACION_DISTINTA", "candidatos": candidatos}
    if rampla["estado"] != "SIN_ASIGNACION":
        # Tracto y carro tienen cada uno su SOAP, revisión y permiso.
        return {"patente": None, "motivo": "TRACTO_Y_CARRO", "candidatos": candidatos}
    return {"patente": patente_cloud, "motivo": "", "candidatos": [patente_cloud]}


def _validar_vehiculos(datos: dict) -> None:
    patentes, ids = set(), {d["documento_id"] for f in datos["choferes"] for d in f["documentos"]}
    entradas = [(v, v.get("documentos")) for v in datos.get("vehiculos", [])]
    entradas.append((None, datos.get(PENDIENTES, [])))
    for vehiculo, documentos in entradas:
        if vehiculo is not None:
            patente = normalizar_patente_vehiculo(str(vehiculo.get("patente", "")))
            if not patente or patente in patentes:
                raise ValueError("Ficha de vehículo sin patente o duplicada")
            patentes.add(patente)
        if not isinstance(documentos, list):
            raise ValueError("Documentos de vehículo inválidos")
        for doc in documentos:
            if not isinstance(doc, dict) or (doc.get("documento_id") and doc["documento_id"] in ids):
                raise ValueError("Identificador de documento de vehículo inválido o duplicado")
            if vehiculo is None and not doc.get("documento_id"):
                raise ValueError("Documento por clasificar sin identificador")
            if doc.get("documento_id"):  # un documento heredado de v1 puede no traerlo
                ids.add(doc["documento_id"])
            p = PureWindowsPath(doc.get("archivo") or "")
            if doc.get("archivo") and (p.is_absolute() or p.drive or ".." in p.parts or p.parts[0] != "archivos"):
                raise ValueError("Adjunto de vehículo fuera de la empresa")


def _existente(datos: dict, origen_documento_id: str):
    for vehiculo in datos.get("vehiculos", []):
        for doc in vehiculo.get("documentos", []):
            if origen_documento_id in (doc.get("origen_documento_id"), *doc.get("origenes_adicionales", [])):
                return vehiculo.get("patente"), doc
    for doc in datos.get(PENDIENTES, []):
        if origen_documento_id in (doc.get("origen_documento_id"), *doc.get("origenes_adicionales", [])):
            return None, doc
    return None, None


def registrar_documento_vehiculo_mobile(
    raiz, *, empresa, origen_documento_id, chofer_id, tipo, patente_cloud, recibido_en, contenido, mime_type,
    sha256, comprobar, actor="MOBILE", reemplaza_origen_id="",
):
    """Guarda el original y lo asocia al vehículo o lo deja por clasificar.

    Devuelve {ok, idempotente, duplicado, documento_id, patente|None, motivo}.
    Un catálogo ilegible lanza (el PULL no confirma y reintenta)."""
    origen_documento_id = str(origen_documento_id or "")
    reemplaza_origen_id = str(reemplaza_origen_id or "")
    if reemplaza_origen_id and (tipo not in ("POLIZA_RESPONSABILIDAD_CIVIL", "POLIZA_ROBO")
                                  or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", reemplaza_origen_id)
                                  or reemplaza_origen_id == origen_documento_id):
        reemplaza_origen_id = ""
    chofer_id = str(chofer_id or "")
    if not origen_documento_id or not chofer_id:
        raise ValueError("Documento Mobile sin chofer o sin identificador")
    if tipo not in (*TIPOS_VEHICULO, TIPO_SEGURO_CARGA):
        raise ValueError(f"Tipo de documento de vehículo no admitido: {tipo}")
    patente_cloud = normalizar_patente_vehiculo(str(patente_cloud or ""))
    if tipo == TIPO_SEGURO_CARGA and patente_cloud:
        raise ValueError("El seguro de carga debe recibirse sin patente asociada")
    original = _original_valido(contenido, mime_type, sha256)
    comprobar()
    ruta = ruta_almacen(raiz, empresa)
    carpeta = Path(raiz) / "catalogos_privados"
    with bloqueo_sesion(Path(raiz) / "operacion" / "actual", "fichas_choferes_" + empresa):
        choferes_bytes = (carpeta / "choferes.json").read_bytes()
        vehiculos_bytes = (carpeta / "vehiculos.json").read_bytes()
        choferes = json.loads(choferes_bytes.decode("utf-8-sig"))
        if not isinstance(choferes, dict) or not choferes:
            raise ValueError("Catálogo de choferes vacío o inválido")
        vehiculos = cargar_catalogo_vehiculos(carpeta / "vehiculos.json").homologables()
        anterior = leer_almacen(raiz, empresa=empresa)
        if not anterior or anterior.get("version") != VERSION:
            raise ValueError("La base de fichas debe inicializarse antes de recibir documentos de vehículo")
        patente_previa, previo = _existente(anterior, origen_documento_id)
        if previo is not None:
            if tipo == TIPO_SEGURO_CARGA and (previo.get("tipo") != tipo or
                    (previo.get("procedencia") or {}).get("chofer_id") != chofer_id):
                raise ValueError("El identificador de seguro pertenece a otro remitente o tipo")
            return {"ok": True, "idempotente": True, "duplicado": False, "documento_id": previo["documento_id"],
                    "patente": patente_previa, "motivo": (previo.get("clasificacion") or {}).get("motivo", "")}
        clasificacion = _clasificar(chofer_id, patente_cloud, choferes, vehiculos) if _PATENTE.fullmatch(patente_cloud) \
            else {"patente": None, "motivo": "SIN_PATENTE_CLOUD", "candidatos": []}
        if tipo == TIPO_SEGURO_CARGA:
            clasificacion = {"patente": None, "motivo": "SEGURO_SIN_VEHICULO_ACREDITADO", "candidatos": []}
        patente = clasificacion["patente"]
        propuesta = copy.deepcopy(anterior)
        propuesta.setdefault("vehiculos", [])
        instante = _ahora()
        if patente:
            ficha = next((v for v in propuesta["vehiculos"]
                          if normalizar_patente_vehiculo(str(v.get("patente", ""))) == patente), None)
            if ficha is None:
                ficha = {"patente": patente, "documentos": [], "historial": []}
                propuesta["vehiculos"].append(ficha)
            destino_lista, carpeta_relativa = ficha["documentos"], Path("archivos") / "vehiculos" / patente
        else:
            ficha = None
            destino_lista = propuesta.setdefault(PENDIENTES, [])
            carpeta_relativa = Path("archivos") / "vehiculos" / "sin_clasificar"
        procedencia = {"chofer_id": chofer_id, "patente_cloud": patente_cloud, "recibido_en": str(recibido_en or instante)}
        polizas = ("POLIZA_RESPONSABILIDAD_CIVIL", "POLIZA_ROBO")
        igual = next((d for d in destino_lista if (d.get("tipo") == tipo or (tipo in polizas and d.get("tipo") in polizas))
                      and d.get("sha256") == original["sha256"]
                      and (patente or (d.get("clasificacion") or {}).get("patente_cloud") == patente_cloud)
                      and (tipo != TIPO_SEGURO_CARGA or (d.get("procedencia") or {}).get("chofer_id") == chofer_id)), None)
        escritos = []
        if igual is not None:
            # El mismo archivo otra vez: un solo documento, con ambos orígenes.
            igual.setdefault("origenes_adicionales", []).append(origen_documento_id)
            igual.setdefault("procedencias_adicionales", []).append(procedencia)
            documento_id, accion = igual["documento_id"], "DOCUMENTO_VEHICULO_REPETIDO"
        else:
            documento_id, accion = str(uuid.uuid4()), "DOCUMENTO_VEHICULO_RECIBIDO_MOBILE"
            relativo = carpeta_relativa / (documento_id + original["extension"])
            destino = ruta.parent / relativo
            destino.parent.mkdir(parents=True, exist_ok=True)
            if not destino.parent.resolve().is_relative_to(ruta.parent.resolve()):
                raise ValueError("La carpeta de adjuntos apunta fuera de la empresa")
            temporal = destino.with_name("." + destino.name + ".tmp-" + uuid.uuid4().hex)
            try:
                with temporal.open("xb") as salida:
                    salida.write(original["contenido"])
                if destino.exists():
                    raise FileExistsError("Ya existe un adjunto con ese identificador")
                os.rename(temporal, destino)
                escritos.append(destino)
            except Exception:
                temporal.unlink(missing_ok=True)
                raise
            documento = {
                "documento_id": documento_id, "tipo": tipo, "estado_revision": ESTADO_PENDIENTE_EXTRACCION,
                "origen": "MOBILE", "origen_documento_id": origen_documento_id, "archivo": relativo.as_posix(),
                "sha256": original["sha256"], "bytes": len(original["contenido"]), "mime_type": mime_type,
                "creado_en": instante, "recibido_en": procedencia["recibido_en"], "procedencia": procedencia,
            }
            if reemplaza_origen_id:
                documento["reemplaza_origen_id"] = reemplaza_origen_id
            if patente:
                documento["asociacion"] = {"metodo": "ASIGNACION_CONFIRMADA", "rol": "TRACTO", "chofer_id": chofer_id,
                                           "fecha": instante}
            else:
                documento["clasificacion"] = {"estado": ESTADO_PENDIENTE_CLASIFICACION, "motivo": clasificacion["motivo"],
                                              "patente_cloud": patente_cloud, "candidatos": clasificacion["candidatos"]}
            destino_lista.append(documento)
        evento = {"accion": accion, "actor": actor, "fecha": instante, "documento_id": documento_id, "tipo": tipo,
                  "origen_documento_id": origen_documento_id, "sha256": original["sha256"]}
        if ficha is not None:
            ficha["historial"].append(evento)
        else:
            objetivo = next(d for d in destino_lista if d["documento_id"] == documento_id)
            objetivo.setdefault("historial", []).append({**evento, "motivo": clasificacion["motivo"]})

        def deshacer():
            for archivo in escritos:
                archivo.unlink(missing_ok=True)

        try:
            propuesta["revision"] = int(anterior["revision"]) + 1
            _validar_v2(propuesta)
            _validar_vehiculos(propuesta)
            respaldo = Path(raiz) / "respaldos" / "fichas_choferes" / uuid.uuid4().hex
            respaldo.mkdir(parents=True)
            shutil.copy2(ruta, respaldo / ruta.name)
            escribir_json_atomico(respaldo / "manifest.json", {
                "empresa": empresa, "actor": actor, "operacion": accion, "documento_id": documento_id, "tipo": tipo,
                "origen_documento_id": origen_documento_id, "sha256": original["sha256"], "patente": patente,
                "motivo": clasificacion["motivo"], "revision_anterior": anterior["revision"],
                "ruta_relativa": str(ruta.relative_to(raiz)),
            })
            comprobar()
            if (carpeta / "choferes.json").read_bytes() != choferes_bytes or \
                    (carpeta / "vehiculos.json").read_bytes() != vehiculos_bytes:
                raise ValueError("Un catálogo cambió durante la recepción; no se publicó el documento")
            escribir_json_atomico(ruta, propuesta)
        except Exception:
            deshacer()
            raise
        return {"ok": True, "idempotente": False, "duplicado": igual is not None, "documento_id": documento_id,
                "patente": patente, "motivo": clasificacion["motivo"], "revision": propuesta["revision"]}
