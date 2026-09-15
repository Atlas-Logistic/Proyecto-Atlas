"""Comandos estructurados con preview para incidencias operacionales.

No interpreta lenguaje natural ni escribe por sí mismo: B1 sólo puede
proponer estos dicts allowlist; un humano debe llamar ``aplicar_lote`` con
``confirmado=True``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from atlas_core.consultas_atlas import cargar_viajes
from atlas_core.registro_eventos_operacionales import (
    ESTADOS_GESTION_SOPORTADOS, marcar_viaje_revisado_sin_incidencia, registrar_evento,
)

ACCIONES_SOPORTADAS = frozenset({"REGISTRAR_INCIDENCIA", "REVISAR_SIN_INCIDENCIA", "ACTUALIZAR_GESTION"})


def _valores(valor: object) -> tuple[str, ...]:
    return tuple(x.strip() for x in str(valor or "").split("|") if x.strip())


def resolver_guias(*, ruta_viajes: str | Path, guias: Sequence[str]) -> dict[str, dict]:
    """Resuelve guía exacta a un único viaje; no inventa ni elige ambigüedades."""
    indice: dict[str, list[Mapping[str, str]]] = {}
    for viaje in cargar_viajes(ruta_viajes):
        for guia in _valores(viaje.get("numeros_guia")):
            indice.setdefault(guia, []).append(viaje)
    salida: dict[str, dict] = {}
    for guia in guias:
        clave = str(guia).strip()
        candidatos = indice.get(clave, [])
        if len(candidatos) != 1:
            salida[clave] = {"estado": "NO_ENCONTRADA" if not candidatos else "AMBIGUA"}
            continue
        v = candidatos[0]
        salida[clave] = {"estado": "RESUELTA", "viaje": dict(v)}
    return salida


def previsualizar_lote(*, ruta_viajes: str | Path, acciones: Sequence[Mapping[str, object]]) -> dict:
    """Valida allowlist y guía→viaje, sin escribir."""
    guias = [str(a.get("guia", "")).strip() for a in acciones]
    resueltas = resolver_guias(ruta_viajes=ruta_viajes, guias=guias)
    detalle = []
    for accion in acciones:
        clase = str(accion.get("accion", "")).strip()
        guia = str(accion.get("guia", "")).strip()
        item = {"guia": guia, "accion": clase, **resueltas.get(guia, {"estado": "NO_ENCONTRADA"})}
        if clase not in ACCIONES_SOPORTADAS:
            item["estado"] = "ACCION_NO_PERMITIDA"
        if clase in ("REGISTRAR_INCIDENCIA", "ACTUALIZAR_GESTION") and not str(accion.get("tipo", "")).strip():
            item["estado"] = "TIPO_REQUERIDO"
        if clase == "ACTUALIZAR_GESTION" and str(accion.get("estado_gestion", "")) not in ESTADOS_GESTION_SOPORTADOS:
            item["estado"] = "GESTION_NO_PERMITIDA"
        detalle.append(item)
    return {"requiere_confirmacion": True, "acciones": detalle, "aplicable": all(x["estado"] == "RESUELTA" for x in detalle)}


def aplicar_lote(*, raiz: str | Path, ruta_viajes: str | Path, acciones: Sequence[Mapping[str, object]], actor: str, confirmado: bool) -> dict:
    """Aplica sólo un preview válido y confirmado; resultado individual por guía."""
    preview = previsualizar_lote(ruta_viajes=ruta_viajes, acciones=acciones)
    if not confirmado:
        return {**preview, "aplicado": False, "motivo": "CONFIRMACION_HUMANA_REQUERIDA"}
    resultados = []
    for accion, item in zip(acciones, preview["acciones"]):
        if item["estado"] != "RESUELTA":
            resultados.append({"guia": item["guia"], "ok": False, "estado": item["estado"]}); continue
        viaje = item["viaje"]
        enriquecimiento = {"viaje_id": viaje.get("viaje_id", ""), "numeros_guia": list(_valores(viaje.get("numeros_guia"))), "fecha_operacional": viaje.get("fecha", ""), "snapshot": {"chofer": viaje.get("choferes", ""), "cliente": viaje.get("clientes", ""), "obra": viaje.get("obras_destino", "")}, "vinculo_completo": True, "motivo_vinculo_incompleto": ""}
        clase = item["accion"]
        if clase == "REVISAR_SIN_INCIDENCIA":
            r = marcar_viaje_revisado_sin_incidencia(raiz=raiz, numero_transporte=viaje["numero_transporte"], numeros_guia=tuple(enriquecimiento["numeros_guia"]), actor=actor, observacion=str(accion.get("observacion", "")))
        else:
            r = registrar_evento(raiz=raiz, tipo_evento=str(accion.get("tipo", "")), numero_transporte=viaje["numero_transporte"], origen=actor, referencia=f"GUIA:{item['guia']}", nota=str(accion.get("observacion", "")), evidencia=tuple(accion.get("evidencia", ()) or ()), estado_gestion=accion.get("estado_gestion"), enriquecimiento=enriquecimiento)
        resultados.append({"guia": item["guia"], "ok": True, "resultado": r})
    return {"aplicado": True, "resultados": resultados}
