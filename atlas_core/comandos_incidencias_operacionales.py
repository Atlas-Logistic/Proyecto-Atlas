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
    CONTEXTO_EMPRESARIAL_SIN_ASIGNAR, ESTADOS_GESTION_SOPORTADOS,
    clave_idempotencia, leer_eventos_operacionales,
    marcar_viaje_revisado_sin_incidencia, registrar_evento,
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


def _estado_idempotencia(*, raiz: str | Path | None, accion: Mapping[str, object], item: Mapping[str, object]) -> str:
    """Clasifica sólo contra hechos ya persistidos; nunca escribe en preview."""
    if raiz is None or item.get("estado") != "RESUELTA":
        return str(item.get("estado", ""))
    viaje = item.get("viaje") or {}
    clase = str(accion.get("accion", ""))
    eventos = leer_eventos_operacionales(raiz=raiz)
    transporte = str(viaje.get("numero_transporte", ""))
    if clase == "REVISAR_SIN_INCIDENCIA":
        return (
            "YA_REGISTRADA"
            if any(str(r.get("numero_transporte", "")) == transporte for r in eventos.get("revisiones_incidencias", []))
            else "RESUELTA"
        )
    tipo = str(accion.get("tipo", "")).strip()
    if not tipo:
        return "RESUELTA"
    clave = clave_idempotencia(
        contexto_empresarial=CONTEXTO_EMPRESARIAL_SIN_ASIGNAR,
        tipo_evento=tipo, numero_transporte=transporte,
    )
    existente = next((e for e in eventos.get("eventos", []) if e.get("clave_idempotencia") == clave and e.get("estado") == "ACTIVO"), None)
    if existente is None:
        return "RESUELTA"
    if clase == "ACTUALIZAR_GESTION" and existente.get("estado_gestion") != accion.get("estado_gestion"):
        return "RESUELTA"
    return "YA_REGISTRADA"


def previsualizar_lote(*, ruta_viajes: str | Path, acciones: Sequence[Mapping[str, object]], raiz: str | Path | None = None) -> dict:
    """Valida cada acción independientemente y clasifica su idempotencia, sin escribir."""
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
        item["estado"] = _estado_idempotencia(raiz=raiz, accion=accion, item=item)
        detalle.append(item)
    aplicables = [x for x in detalle if x["estado"] == "RESUELTA"]
    ya_registradas = [x for x in detalle if x["estado"] == "YA_REGISTRADA"]
    no_resueltas = [x for x in detalle if x["estado"] not in {"RESUELTA", "YA_REGISTRADA"}]
    return {
        "requiere_confirmacion": bool(aplicables), "acciones": detalle,
        "aplicable": bool(aplicables),
        "resumen": {
            "aplicables": len(aplicables), "ya_registradas": len(ya_registradas),
            "no_resueltas": len(no_resueltas),
        },
    }


def aplicar_lote(*, raiz: str | Path, ruta_viajes: str | Path, acciones: Sequence[Mapping[str, object]], actor: str, confirmado: bool) -> dict:
    """Aplica sólo un preview válido y confirmado; resultado individual por guía."""
    preview = previsualizar_lote(ruta_viajes=ruta_viajes, acciones=acciones, raiz=raiz)
    if not confirmado:
        return {**preview, "aplicado": False, "motivo": "CONFIRMACION_HUMANA_REQUERIDA"}
    if not preview["aplicable"]:
        return {
            **preview, "aplicado": False, "motivo": "SIN_ACCIONES_APLICABLES",
            "resultados": [
                {"guia": item["guia"], "ok": False, "estado": item["estado"]}
                for item in preview["acciones"]
            ],
        }
    resultados = []
    for accion, item in zip(acciones, preview["acciones"]):
        if item["estado"] == "YA_REGISTRADA":
            resultados.append({"guia": item["guia"], "ok": True, "ya_registrada": True, "resultado": {}})
            continue
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
