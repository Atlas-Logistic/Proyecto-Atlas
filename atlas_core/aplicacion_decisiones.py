"""Aplicación transaccional y auditable de decisiones R3.3 de obras."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, ResultadoEvidencia, TipoEvidencia
from atlas_core.decisiones_pendientes import generar_artefacto, regenerar_decisiones_persistidas

ACCIONES = frozenset({"REGISTRAR", "NO_REGISTRAR", "POSPONER"})
LEDGER = "decisiones_aplicadas.json"


class ErrorAplicacionDecision(ValueError): pass
class DecisionObsoletaError(ErrorAplicacionDecision): pass


def _sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest().upper()


def _restaurar(ruta: Path, contenido: bytes | None) -> None:
    if contenido is None:
        ruta.unlink(missing_ok=True); return
    temporal = None
    try:
        with tempfile.NamedTemporaryFile(dir=ruta.parent, prefix=f".{ruta.name}.", suffix=".tmp", delete=False) as archivo:
            temporal = Path(archivo.name); archivo.write(contenido); archivo.flush(); os.fsync(archivo.fileno())
        os.replace(temporal, ruta)
    finally:
        if temporal is not None: temporal.unlink(missing_ok=True)


def aplicar_decision_obra(*, raiz_atlas: str | Path, decision_id: str, accion: str, actor: str = "JAVIER_DESKTOP", reloj=lambda: datetime.now(timezone.utc)) -> dict[str, object]:
    raiz = Path(raiz_atlas); actual = raiz / "operacion" / "actual"; catalogos = raiz / "catalogos_privados"
    artefacto_ruta = actual / "decisiones_pendientes.json"; ledger_ruta = actual / LEDGER
    dataset = actual / "analisis_completo_guias.csv"; catalogo_ruta = catalogos / "obras_destinos.json"
    accion = str(accion).upper(); decision_id = str(decision_id).strip()
    if accion not in ACCIONES or not decision_id: raise ErrorAplicacionDecision("Solicitud de decisión inválida.")
    with bloqueo_sesion(actual, "aplicar_decision_obra"):
        try: ledger = json.loads(ledger_ruta.read_text(encoding="utf-8"))
        except FileNotFoundError: ledger = {"schema_version": 1, "aplicaciones": []}
        except (OSError, json.JSONDecodeError) as error: raise ErrorAplicacionDecision("El historial de decisiones no se puede leer.") from error
        previas = [x for x in ledger.get("aplicaciones", []) if x.get("decision_id") == decision_id]
        if previas:
            return {"ok": True, "idempotente": True, "accion": previas[-1]["accion"], "mensaje": "Esta decisión ya fue aplicada."}
        try: artefacto = json.loads(artefacto_ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error: raise ErrorAplicacionDecision("No se pudo leer la bandeja vigente.") from error
        coincidencias = [d for d in artefacto.get("decisiones", []) if d.get("decision_id") == decision_id]
        if len(coincidencias) != 1: raise ErrorAplicacionDecision("La decisión ya no está pendiente.")
        decision = coincidencias[0]
        if decision.get("tipo") != "OBRA_DESCONOCIDA" or decision.get("estado") != "PENDIENTE": raise ErrorAplicacionDecision("Esta decisión no puede aplicarse en R3.3.")
        codigo_accion = {"REGISTRAR":"REGISTRAR", "NO_REGISTRAR":"NO_REGISTRAR", "POSPONER":"POSPONER"}[accion]
        if codigo_accion not in decision.get("acciones_permitidas", []): raise ErrorAplicacionDecision("La acción no está permitida para esta decisión.")
        if accion == "POSPONER": return {"ok": True, "idempotente": False, "accion": accion, "mensaje": "La decisión permanece pendiente."}
        if _sha(dataset) != artefacto.get("dataset_sha256"): raise DecisionObsoletaError("La decisión quedó obsoleta porque cambió el dataset.")
        for clave, nombre in {"clientes":"clientes.json","vehiculos":"vehiculos.json","obras_destinos":"obras_destinos.json","destinos_maestros":"destinos_maestros.json"}.items():
            esperado = artefacto.get("catalogos_sha256", {}).get(clave)
            ruta = catalogos / nombre
            actual_hash = _sha(ruta) if ruta.is_file() else None
            if esperado != actual_hash: raise DecisionObsoletaError("La decisión quedó obsoleta porque cambiaron los catálogos.")
        contexto = decision.get("contexto") or {}; cliente_id = str(contexto.get("cliente_id", "")); obra = str(decision.get("valor_documental", "")).strip()
        if not cliente_id or not obra: raise ErrorAplicacionDecision("La decisión no contiene identidad suficiente para aplicar la obra.")
        respaldos = {ruta: ruta.read_bytes() if ruta.exists() else None for ruta in (catalogo_ruta, ledger_ruta, artefacto_ruta)}
        obra_id = None
        try:
            if accion == "REGISTRAR":
                # R3.3.1: la evidencia guarda quién observó la obra en esta
                # guía (cliente_id_observado/cliente_canonico_observado) como
                # dato operacional del documento -- NO como propiedad de la
                # obra. `registrar_observacion` busca/crea la obra
                # GLOBALMENTE por nombre; si ya existe (para este u otro
                # cliente) la reutiliza en vez de duplicarla.
                numero_guia = str(decision.get("documento", {}).get("numero_guia") or "")
                evidencia = Evidencia(
                    tipo=TipoEvidencia.GUIA.value,
                    identificador_fuente=str(decision.get("documento", {}).get("numero_guia") or decision.get("documento", {}).get("archivo")),
                    referencia_hash=decision_id,
                    campos_observados={
                        "obra": obra, "decision_id": decision_id,
                        "cliente_id_observado": cliente_id,
                        "cliente_canonico_observado": str(contexto.get("cliente_canonico", "")),
                        "numero_guia": numero_guia,
                    },
                    fecha=reloj().astimezone(timezone.utc).isoformat(), actor_proceso=actor, resultado=ResultadoEvidencia.SOPORTA.value,
                )
                resultado = CatalogoObrasDestinos(ruta=catalogo_ruta, ruta_clientes=catalogos/"clientes.json", ruta_destinos=catalogos/"destinos_maestros.json").registrar_observacion(cliente_id=cliente_id, nombre_obra=obra, evidencia=evidencia)
                obra_id = resultado.obra.obra_id
            aplicacion = {"decision_id":decision_id,"tipo":"OBRA_DESCONOCIDA","accion":accion,"actor":actor,"fecha":reloj().astimezone(timezone.utc).isoformat(),"documento":decision.get("documento"),"valor_documental":obra,"cliente_id":cliente_id,"obra_id":obra_id,"dataset_sha256":artefacto.get("dataset_sha256"),"catalogos_sha256_antes":artefacto.get("catalogos_sha256")}
            ledger.setdefault("aplicaciones", []).append(aplicacion); escribir_json_atomico(ledger_ruta, ledger)
            restantes = regenerar_decisiones_persistidas(decisiones=artefacto.get("decisiones", []), carpeta_catalogos=catalogos, ids_resueltos={decision_id})
            generar_artefacto(ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=restantes, ruta_salida=artefacto_ruta, reloj=reloj)
        except Exception:
            for ruta, contenido in respaldos.items(): _restaurar(ruta, contenido)
            raise
        mensaje = "Obra registrada. Atlas podrá reconocerla en documentos futuros." if accion == "REGISTRAR" else "Decisión guardada. Atlas no registrará esta observación como obra."
        return {"ok": True, "idempotente": False, "accion": accion, "obra_id": obra_id, "mensaje": mensaje}
