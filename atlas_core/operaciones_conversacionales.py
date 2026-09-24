"""Operaciones conversacionales V1: asociación explícita chofer-vehículo.

Esta capa sólo traduce una instrucción humana de alta certeza a un comando de
dominio ya existente.  No edita CSV/JSON operacional ni reescribe OCR.
"""
from __future__ import annotations

import hashlib
import json
import re
import csv
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico
from atlas_core.catalogo_vehiculos import (
    asociar_chofer_a_vehiculo_confirmado, cargar_catalogo_vehiculos,
    normalizar_patente_vehiculo,
)
from atlas_core.catalogos import buscar_chofer_por_rut, cargar_catalogo_json, normalizar_rut
from atlas_core.convergencia_identidad_conocida import (
    IdentidadChoferResuelta, RESULTADO_RESUELTO, resolver_identidad_nominal_fuerte_chofer,
)
from atlas_core.validadores import EstadoValidacion, validar_rut_chileno
from atlas_core.convergencia_identidad_conocida import resolver_patente_operacional_canonica_por_chofer

_PATRON = re.compile(
    r"\b(?:(?:EL|LA)\s+)?(?:(TRACTO|RAMPLA|CAMI[ÓO]N)\s+(?:DE\s+)?)?(.+?)\s+(?:ES|USA|UTILIZA|LLEVA)\s+([A-Z0-9-]{4,12})\b",
    re.I,
)
_PATRON_ASOCIA = re.compile(r"\bASOCIA\s+([A-Z0-9-]{4,12})\s+A\s+(.+?)\s*$", re.I)
_NOMBRE_LEDGER = "operaciones_conversacionales.json"


def _sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest() if ruta.is_file() else ""


def _ledger_ruta(raiz: Path) -> Path:
    return raiz / "operacion" / "actual" / _NOMBRE_LEDGER


def _leer_ledger(ruta: Path) -> dict:
    if not ruta.is_file():
        return {"schema_version": 1, "operaciones": []}
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    if datos.get("schema_version") != 1 or not isinstance(datos.get("operaciones"), list):
        raise ValueError("ledger de operaciones conversacionales inválido")
    return datos


def _bandeja_ruta(raiz: Path) -> Path:
    return raiz / "operacion" / "actual" / "decisiones_pendientes.json"


def _plan_impacto_focal(*, raiz: Path, rut_chofer: str, tipo_humano: str, patente: str, aplicar: bool) -> dict:
    """Revalida sólo decisiones vivas del rol afectado; nunca OCR ni el
    orquestador global. Lee filas únicamente hasta hallar los documentos de
    esas tarjetas y conserva las columnas documentales intactas."""
    inicio = time.perf_counter()
    ruta_bandeja = _bandeja_ruta(raiz)
    ruta_dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    base = {"decisiones_retiradas": 0, "viajes_revalidados": 0, "permanecen": 0,
            "errores": [], "decisiones": [], "tiempo_ms": 0.0, "global": False}
    if not ruta_bandeja.is_file() or not ruta_dataset.is_file():
        base["tiempo_ms"] = round((time.perf_counter() - inicio) * 1000, 1)
        return base
    contenido = json.loads(ruta_bandeja.read_text(encoding="utf-8"))
    clave = "decisiones" if isinstance(contenido.get("decisiones"), list) else "decisions"
    decisiones = list(contenido.get(clave) or [])
    campo = "patente_rampla" if tipo_humano == "RAMPLA" else "patente_tracto"
    candidatas = [d for d in decisiones if d.get("tipo") == "VEHICULO_DESCONOCIDO" and d.get("campo") == campo]
    archivos = {str((d.get("documento") or {}).get("archivo", "")) for d in candidatas}
    filas = {}
    with ruta_dataset.open("r", newline="", encoding="utf-8-sig") as archivo:
        for fila in csv.DictReader(archivo, delimiter=";"):
            nombre = str(fila.get("archivo", ""))
            if nombre in archivos:
                filas[nombre] = fila
                if len(filas) == len(archivos):
                    break
    choferes = cargar_catalogo_json(raiz / "catalogos_privados" / "choferes.json")
    vehiculos = list(cargar_catalogo_vehiculos(raiz / "catalogos_privados" / "vehiculos.json").homologables())
    ids_retirar = set()
    tipo_catalogo = "CARRO" if tipo_humano == "RAMPLA" else "TRACTO"
    for decision in candidatas:
        doc = decision.get("documento") or {}; nombre = str(doc.get("archivo", "")); fila = filas.get(nombre)
        if fila is None:
            continue  # obsoleta/no localizable: no recrear ni fallar
        identidad = resolver_identidad_nominal_fuerte_chofer(
            nombre_documental=str(fila.get("chofer", "")), rut_documental=str(fila.get("rut_chofer", "")), choferes=choferes)
        if identidad.resultado != "RESUELTO" or normalizar_rut(identidad.identificador or "") != rut_chofer:
            continue
        base["viajes_revalidados"] += 1
        resultado = resolver_patente_operacional_canonica_por_chofer(
            nombre_documental=str(fila.get("chofer", "")), rut_documental=str(fila.get("rut_chofer", "")),
            choferes=choferes, vehiculos=vehiculos, tipo_esperado=tipo_catalogo)
        detalle = {"guia": str(doc.get("numero_guia", "")), "decision_id": decision.get("decision_id"),
                   "resultado": resultado.resultado, "patente_operacional": resultado.patente}
        base["decisiones"].append(detalle)
        if resultado.resultado == "RESUELTO" and resultado.patente == patente:
            ids_retirar.add(str(decision.get("decision_id"))); base["decisiones_retiradas"] += 1
        else:
            base["permanecen"] += 1
    if aplicar and ids_retirar:
        contenido[clave] = [d for d in decisiones if str(d.get("decision_id")) not in ids_retirar]
        escribir_json_atomico(ruta_bandeja, contenido)
    base["tiempo_ms"] = round((time.perf_counter() - inicio) * 1000, 1)
    return base


def _interpretar(texto: str) -> tuple[str, str, str] | None:
    t = " ".join(str(texto or "").upper().split())
    # "carro" y "rampla" son la misma clase operacional para esta
    # asociación; se preserva como intención explícita, no como inferencia.
    t = re.sub(r"\bCARRO\s+(?=DE\s+)", "RAMPLA ", t)
    # La patente puede aparecer como objeto explícito de la frase humana:
    # "Pizarro usa la patente JF9575" equivale a "Pizarro usa JF9575".
    t = re.sub(r"\b(?:LA\s+)?PATENTE\s+(?=[A-Z0-9-]{4,12}\b)", "", t)
    t = " ".join(t.split())
    m = _PATRON_ASOCIA.search(t)
    if m:
        return "", m.group(2).strip(), m.group(1).strip()
    m = _PATRON.search(t)
    if not m:
        return None
    clase, chofer, patente = m.groups()
    if clase == "RAMPLA":
        tipo = "RAMPLA"
    elif clase:  # TRACTO o CAMIÓN: intención explícita de tracto
        tipo = "TRACTO"
    else:
        tipo = ""  # frase genérica: se determina desde el vehículo confirmado
    return tipo, chofer.strip(), patente.strip()


def _resolver_chofer_b1(choferes: Mapping[str, object], referencia: str) -> IdentidadChoferResuelta:
    """Reutiliza el resolver nominal seguro; RUT explícito es el ancla
    estructural adicional, nunca fuzzy ni historial."""
    validado = validar_rut_chileno(referencia)
    if validado.estado == EstadoValidacion.VALIDO:
        registro = buscar_chofer_por_rut(choferes, referencia)
        if registro is not None and registro.get("activo", True) is True:
            identificador = normalizar_rut(referencia)
            return IdentidadChoferResuelta(RESULTADO_RESUELTO, identificador,
                str(registro.get("nombre", referencia)), referencia, "RUT explícito coincide con chofer activo.")
    return resolver_identidad_nominal_fuerte_chofer(nombre_documental=referencia, rut_documental="", choferes=choferes)


def proponer_asociacion_chofer_vehiculo(*, raiz_atlas: str | Path, texto: str, actor: str = "JAVIER_DESKTOP") -> dict:
    raiz = Path(raiz_atlas)
    interpretada = _interpretar(texto)
    if not interpretada:
        return {"interpretado": False, "estado": "ABSTENCION", "mensaje": "No reconocí una asociación chofer-vehículo de alta certeza."}
    tipo_humano, nombre, patente_cruda = interpretada
    patente = normalizar_patente_vehiculo(patente_cruda)
    if not re.fullmatch(r"(?=.*[A-Z])(?=.*\d)[A-Z0-9]{6}", patente):
        return {"interpretado": True, "estado": "ABSTENCION", "mensaje": "La patente no tiene un formato chileno válido."}
    catalogos = raiz / "catalogos_privados"
    ruta_choferes, ruta_vehiculos = catalogos / "choferes.json", catalogos / "vehiculos.json"
    choferes = cargar_catalogo_json(ruta_choferes)
    identidad = _resolver_chofer_b1(choferes, nombre)
    if identidad.resultado != "RESUELTO" or not identidad.identificador:
        respuesta = {"interpretado": True, "estado": "ABSTENCION", "mensaje": identidad.explicacion}
        if identidad.candidatos:
            respuesta["candidatos"] = list(identidad.candidatos)
            respuesta["acciones"] = ["ELEGIR_CHOFER", "CANCELAR"]
        return respuesta
    catalogo = cargar_catalogo_vehiculos(ruta_vehiculos)
    vehiculo = next((v for v in catalogo.vehiculos if v.patente_canonica == patente), None)
    if vehiculo is None or vehiculo.estado_calidad != "CONFIRMADO" or vehiculo.estado_vigencia != "ACTIVO":
        return {"interpretado": True, "estado": "ABSTENCION", "mensaje": "La patente no existe como vehículo CONFIRMADO y ACTIVO; este comando no crea vehículos."}
    esperado = "CARRO" if tipo_humano == "RAMPLA" else "TRACTO"
    if tipo_humano and vehiculo.tipo != esperado:
        return {"interpretado": True, "estado": "ABSTENCION", "mensaje": f"La patente {patente} es {vehiculo.tipo}, no {esperado}."}
    if not tipo_humano:
        # La frase no declaró tracto/carro: el tipo confirmado del vehículo
        # decide el campo operacional sin inventar una preferencia.
        if vehiculo.tipo == "TRACTO":
            tipo_humano = "TRACTO"
        elif vehiculo.tipo == "CARRO":
            tipo_humano = "RAMPLA"
        else:
            return {"interpretado": True, "estado": "ABSTENCION", "mensaje": "El tipo del vehículo no es determinable con seguridad."}
    rut = normalizar_rut(identidad.identificador)
    ya_asociada = any(str(e.campos_observados.get("rut_chofer_asociado", "")) == rut for e in vehiculo.evidencias)
    cambios = {"rut_chofer": rut, "patente": patente, "tipo": tipo_humano}
    clave = hashlib.sha256(json.dumps(cambios, sort_keys=True).encode()).hexdigest()
    # El catálogo confirmado es la autoridad.  Una instrucción que ya pide
    # exactamente esa relación no es una operación pendiente: no debe crear
    # preview, auditoría, escritura ni revalidación por el solo reintento.
    if ya_asociada:
        return {
            "interpretado": True, "estado": "SIN_CAMBIOS", "operacion_id": clave,
            "texto_original": texto, "intencion": "ASOCIAR_CHOFER_VEHICULO",
            "objetivo": {"chofer": identidad.nombre_canonico, "rut": rut, "vehiculo_id": vehiculo.vehiculo_id},
            "cambios_tipados": cambios, "asignacion_actual": f"{tipo_humano} {patente}",
            "acciones": [],
            "mensaje": f"La asociación {tipo_humano} {patente} ya existe para {identidad.nombre_canonico}; no hay cambios para confirmar.",
        }
    hashes = {"choferes": _sha(ruta_choferes), "vehiculos": _sha(ruta_vehiculos)}
    return {
        "interpretado": True, "estado": "PREVIEW", "operacion_id": clave, "idempotency_key": clave,
        "actor": actor, "texto_original": texto, "intencion": "ASOCIAR_CHOFER_VEHICULO",
        "objetivo": {"chofer": identidad.nombre_canonico, "rut": rut, "vehiculo_id": vehiculo.vehiculo_id},
        "cambios_tipados": cambios, "precondiciones": hashes, "impacto_estimado": {"documentos": [], "viajes": [], "decisiones_posibles": []},
        "asignacion_anterior": "YA_ASOCIADA" if ya_asociada else "SIN_ASOCIACION_EXPLICITA",
        "campos_no_modificados": ["patente_tracto documental", "patente_rampla documental", "analisis_completo_guias.csv"],
        "mensaje": "Revise la asociación propuesta antes de confirmar.",
    }


def confirmar_asociacion_chofer_vehiculo(*, raiz_atlas: str | Path, propuesta: Mapping[str, object], actor: str) -> dict:
    if propuesta.get("estado") != "PREVIEW":
        return {"estado": "ABSTENCION", "mensaje": "Sólo una propuesta PREVIEW puede confirmarse."}
    raiz = Path(raiz_atlas); catalogos = raiz / "catalogos_privados"
    ruta_vehiculos = catalogos / "vehiculos.json"; ruta_ledger = _ledger_ruta(raiz)
    # Un reintento de la MISMA operación ya aplicada debe ser idempotente
    # incluso si la propia primera aplicación cambió el hash del catálogo.
    ledger_existente = _leer_ledger(ruta_ledger)
    clave = str(propuesta["idempotency_key"])
    previo = next((x for x in ledger_existente["operaciones"] if x.get("idempotency_key") == clave and x.get("estado") == "APLICADA"), None)
    if previo:
        # Compatibilidad con confirmaciones ya hechas antes de que existiera
        # este adaptador: se completa UNA vez la revalidación focal ausente,
        # sin tocar de nuevo vehículo ni OCR. Después queda plenamente
        # idempotente como cualquier operación nueva.
        previo_resultado = dict(previo.get("resultado") or {})
        if "revalidacion_focal" not in previo_resultado:
            anterior = dict(previo.get("despues") or {})
            impacto = _plan_impacto_focal(
                raiz=raiz, rut_chofer=str(anterior.get("rut_chofer", "")),
                tipo_humano=str(anterior.get("tipo", "TRACTO")),
                patente=str(anterior.get("patente", "")), aplicar=True,
            )
            previo_resultado["revalidacion_focal"] = impacto
            previo["resultado"] = previo_resultado
            escribir_json_atomico(ruta_ledger, ledger_existente)
        return {"estado": "APLICADA", "aplicado": False, "idempotente": True, "resultado": previo.get("resultado", {})}
    actuales = {"choferes": _sha(catalogos / "choferes.json"), "vehiculos": _sha(ruta_vehiculos)}
    if actuales != propuesta.get("precondiciones"):
        return {"estado": "OBSOLETA", "aplicado": False, "mensaje": "El catálogo cambió desde el preview; no se escribió nada."}
    with bloqueo_sesion(ruta_ledger.parent, "operaciones_conversacionales"):
        ledger = _leer_ledger(ruta_ledger)
        clave = str(propuesta["idempotency_key"])
        previo = next((x for x in ledger["operaciones"] if x.get("idempotency_key") == clave and x.get("estado") == "APLICADA"), None)
        if previo:
            return {"estado": "APLICADA", "aplicado": False, "idempotente": True, "resultado": previo.get("resultado", {})}
        cambio = dict(propuesta["cambios_tipados"])
        vehiculo = next((v for v in cargar_catalogo_vehiculos(ruta_vehiculos).vehiculos
                         if v.patente_canonica == str(cambio["patente"])), None)
        rut = str(cambio["rut_chofer"])
        ya_asociada = bool(vehiculo and any(str(e.campos_observados.get("rut_chofer_asociado", "")) == rut for e in vehiculo.evidencias))
        if not ya_asociada:
            asociar_chofer_a_vehiculo_confirmado(ruta_vehiculos, patente=str(cambio["patente"]), actor=actor,
                fuente_decision=f"OPERACION_CONVERSACIONAL:{clave}", fecha=datetime.now(timezone.utc), rut_chofer_asociado=rut,
                observaciones=f"{propuesta.get('texto_original', '')}")
        # La asociación ya escrita es la única autoridad de esta pasada.
        # No llama `revalidar_y_regenerar_reporte`, no OCR y no recalcula
        # viajes: sólo retira tarjetas VEHICULO_DESCONOCIDO que pertenecen
        # al mismo chofer y al mismo tipo de vehículo.
        impacto = _plan_impacto_focal(
            raiz=raiz, rut_chofer=rut, tipo_humano=str(cambio["tipo"]),
            patente=str(cambio["patente"]), aplicar=True,
        )
        resultado = {"asociacion_agregada": not ya_asociada, "revalidacion_focal": impacto}
        ledger["operaciones"].append({"operacion_id": propuesta["operacion_id"], "idempotency_key": clave, "actor": actor,
            "timestamp": datetime.now(timezone.utc).isoformat(), "texto_original": propuesta.get("texto_original", ""),
            "comando": "ASOCIAR_CHOFER_VEHICULO", "antes": propuesta.get("asignacion_anterior"), "despues": cambio,
            "alcance": propuesta.get("impacto_estimado"), "resultado": resultado, "estado": "APLICADA"})
        escribir_json_atomico(ruta_ledger, ledger)
    return {"estado": "APLICADA", "aplicado": not ya_asociada, "idempotente": ya_asociada, "resultado": resultado}
