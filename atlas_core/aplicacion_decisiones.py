"""Aplicación transaccional y auditable de decisiones R3.3/R3.4 (obras y destinos)."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico
from atlas_core.catalogo_destinos import CatalogoDestinos
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, ResultadoEvidencia, TipoEvidencia
from atlas_core.decisiones_pendientes import generar_artefacto, regenerar_decisiones_persistidas

ACCIONES = frozenset({"REGISTRAR", "NO_REGISTRAR", "CONFIRMAR", "NO_CONFIRMAR", "POSPONER"})
LEDGER = "decisiones_aplicadas.json"

# R3.4: qué acciones son válidas para cada tipo de decisión -- una acción de
# un tipo nunca se aplica a una decisión de otro tipo, aunque comparta el
# mismo código POSPONER.
ACCIONES_POR_TIPO = {
    "OBRA_DESCONOCIDA": frozenset({"REGISTRAR", "NO_REGISTRAR", "POSPONER"}),
    "DESTINO_SIN_CONFIRMAR": frozenset({"CONFIRMAR", "NO_CONFIRMAR", "POSPONER"}),
}

logger = logging.getLogger(__name__)


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
    dataset = actual / "analisis_completo_guias.csv"
    catalogo_obras_ruta = catalogos / "obras_destinos.json"
    catalogo_destinos_ruta = catalogos / "destinos_maestros.json"
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
        tipo = decision.get("tipo")
        acciones_validas_tipo = ACCIONES_POR_TIPO.get(tipo)
        if acciones_validas_tipo is None or decision.get("estado") != "PENDIENTE" or accion not in acciones_validas_tipo:
            raise ErrorAplicacionDecision("Esta decisión no puede aplicarse en este bloque.")
        if accion not in decision.get("acciones_permitidas", []): raise ErrorAplicacionDecision("La acción no está permitida para esta decisión.")
        if accion == "POSPONER": return {"ok": True, "idempotente": False, "accion": accion, "mensaje": "La decisión permanece pendiente."}
        if _sha(dataset) != artefacto.get("dataset_sha256"): raise DecisionObsoletaError("La decisión quedó obsoleta porque cambió el dataset.")
        for clave, nombre in {"clientes":"clientes.json","vehiculos":"vehiculos.json","obras_destinos":"obras_destinos.json","destinos_maestros":"destinos_maestros.json"}.items():
            esperado = artefacto.get("catalogos_sha256", {}).get(clave)
            ruta = catalogos / nombre
            actual_hash = _sha(ruta) if ruta.is_file() else None
            if esperado != actual_hash: raise DecisionObsoletaError("La decisión quedó obsoleta porque cambiaron los catálogos.")

        contexto = decision.get("contexto") or {}
        cliente_id = str(contexto.get("cliente_id", ""))
        respaldos = {ruta: ruta.read_bytes() if ruta.exists() else None for ruta in (catalogo_obras_ruta, catalogo_destinos_ruta, ledger_ruta, artefacto_ruta)}
        resultado_extra: dict[str, object] = {}
        try:
            if tipo == "OBRA_DESCONOCIDA":
                obra_texto = str(decision.get("valor_documental", "")).strip()
                if not cliente_id or not obra_texto:
                    raise ErrorAplicacionDecision("La decisión no contiene identidad suficiente para aplicar la obra.")
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
                            "obra": obra_texto, "decision_id": decision_id,
                            "cliente_id_observado": cliente_id,
                            "cliente_canonico_observado": str(contexto.get("cliente_canonico", "")),
                            "numero_guia": numero_guia,
                        },
                        fecha=reloj().astimezone(timezone.utc).isoformat(), actor_proceso=actor, resultado=ResultadoEvidencia.SOPORTA.value,
                    )
                    resultado_obs = CatalogoObrasDestinos(ruta=catalogo_obras_ruta, ruta_clientes=catalogos/"clientes.json", ruta_destinos=catalogo_destinos_ruta).registrar_observacion(cliente_id=cliente_id, nombre_obra=obra_texto, evidencia=evidencia)
                    resultado_extra["obra_id"] = resultado_obs.obra.obra_id
                aplicacion = {
                    "decision_id": decision_id, "tipo": tipo, "accion": accion, "actor": actor,
                    "fecha": reloj().astimezone(timezone.utc).isoformat(), "documento": decision.get("documento"),
                    "valor_documental": obra_texto, "cliente_id": cliente_id, "obra_id": resultado_extra.get("obra_id"),
                    "dataset_sha256": artefacto.get("dataset_sha256"), "catalogos_sha256_antes": artefacto.get("catalogos_sha256"),
                }
            elif tipo == "DESTINO_SIN_CONFIRMAR":
                identidad_obra = decision.get("identidad_resuelta") or {}
                obra_id = str(identidad_obra.get("entidad_id", ""))
                obra_canonica = str(contexto.get("obra_canonica") or identidad_obra.get("valor_canonico") or "")
                destino_texto = str(contexto.get("destino_documental") or decision.get("valor_documental", "")).strip()
                if not obra_id or not obra_canonica or not destino_texto or not cliente_id:
                    raise ErrorAplicacionDecision("La decisión no contiene identidad suficiente para confirmar el destino.")
                if accion == "CONFIRMAR":
                    # A. Resolver/crear el destino global (nunca duplica: misma
                    # dirección normalizada => mismo destino_id).
                    numero_guia = str(decision.get("documento", {}).get("numero_guia") or "")
                    fuente = f"DECISION_HUMANA_R3_4:{decision_id}"
                    destino = CatalogoDestinos(catalogo_destinos_ruta, ruta_clientes=catalogos/"clientes.json").crear_o_reutilizar_global(
                        nombre_destino=destino_texto, direccion=destino_texto, fuente=fuente,
                    )
                    # B/C. Reutilizar la obra global existente (por nombre
                    # canónico, nunca crea una segunda) y crear/reutilizar la
                    # relación obra<->destino, dejándola CONFIRMADA -- eso
                    # promueve también la obra a CONFIRMADA (API canónica
                    # `confirmar_relacion`, evidencia humana auditable).
                    evidencia = Evidencia(
                        tipo=TipoEvidencia.GUIA.value,
                        identificador_fuente=str(decision.get("documento", {}).get("numero_guia") or decision.get("documento", {}).get("archivo")),
                        referencia_hash=decision_id,
                        campos_observados={
                            "obra": obra_canonica, "destino": destino_texto, "decision_id": decision_id,
                            "cliente_id_observado": cliente_id,
                            "cliente_canonico_observado": str(contexto.get("cliente_canonico", "")),
                            "numero_guia": numero_guia,
                        },
                        fecha=reloj().astimezone(timezone.utc).isoformat(), actor_proceso=actor, resultado=ResultadoEvidencia.SOPORTA.value,
                    )
                    catalogo_obras = CatalogoObrasDestinos(ruta=catalogo_obras_ruta, ruta_clientes=catalogos/"clientes.json", ruta_destinos=catalogo_destinos_ruta)
                    resultado_obs = catalogo_obras.registrar_observacion(
                        cliente_id=cliente_id, nombre_obra=obra_canonica, destino_id=destino.destino_id, evidencia=evidencia,
                    )
                    relacion = resultado_obs.relacion
                    if relacion is None:
                        raise ErrorAplicacionDecision("No se pudo determinar la relación obra-destino.")
                    if relacion.estado == "PENDIENTE":
                        relacion = catalogo_obras.confirmar_relacion(
                            relacion.relacion_id, actor=actor, identificador_fuente=decision_id,
                        )
                    resultado_extra["destino_id"] = destino.destino_id
                    resultado_extra["relacion_id"] = relacion.relacion_id
                aplicacion = {
                    "decision_id": decision_id, "tipo": tipo, "accion": accion, "actor": actor,
                    "fecha": reloj().astimezone(timezone.utc).isoformat(), "documento": decision.get("documento"),
                    "valor_documental": destino_texto, "cliente_id": cliente_id, "obra_id": obra_id,
                    "destino_id": resultado_extra.get("destino_id"), "relacion_id": resultado_extra.get("relacion_id"),
                    "dataset_sha256": artefacto.get("dataset_sha256"), "catalogos_sha256_antes": artefacto.get("catalogos_sha256"),
                }
            else:
                raise ErrorAplicacionDecision("Esta decisión no puede aplicarse en este bloque.")

            ledger.setdefault("aplicaciones", []).append(aplicacion); escribir_json_atomico(ledger_ruta, ledger)
            restantes = regenerar_decisiones_persistidas(decisiones=artefacto.get("decisiones", []), carpeta_catalogos=catalogos, ids_resueltos={decision_id})
            generar_artefacto(ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=restantes, ruta_salida=artefacto_ruta, reloj=reloj)
        except Exception:
            for ruta, contenido in respaldos.items(): _restaurar(ruta, contenido)
            raise

        if tipo == "DESTINO_SIN_CONFIRMAR" and accion == "CONFIRMAR":
            # R3.4 obligatorio: revalidar el dataset y refrescar el reporte
            # oficial SIN OCR para que "Viajes" deje de mostrar
            # OBRA_DESTINO_SIN_CORROBORAR cuando ya quedó resuelto. Best-effort
            # y nunca revierte la confirmación ya persistida arriba -- mismo
            # criterio que usa el resto del pipeline para enriquecimiento
            # secundario (GPS/rutas): nunca bloquea ni invalida lo principal.
            try:
                from atlas_core.revalidacion_documental import revalidar_y_regenerar_reporte
                instante = reloj()
                nombre_carpeta = f"reporte_revalidacion_{instante.strftime('%Y%m%d_%H%M%S')}"
                resultado_extra["revalidacion"] = revalidar_y_regenerar_reporte(
                    raiz_atlas=raiz, nombre_carpeta_reporte=nombre_carpeta, reloj=reloj,
                )
            except Exception as error:
                logger.warning("Revalidación/regeneración de reporte omitida: %s: %s", type(error).__name__, error)

        mensajes = {
            ("OBRA_DESCONOCIDA", "REGISTRAR"): "Obra registrada. Atlas podrá reconocerla en documentos futuros.",
            ("OBRA_DESCONOCIDA", "NO_REGISTRAR"): "Decisión guardada. Atlas no registrará esta observación como obra.",
            ("DESTINO_SIN_CONFIRMAR", "CONFIRMAR"): "Destino confirmado. Atlas podrá reconocer esta obra y destino en documentos futuros.",
            ("DESTINO_SIN_CONFIRMAR", "NO_CONFIRMAR"): "Decisión guardada. Atlas no confirmará esta observación como destino.",
        }
        mensaje = mensajes.get((tipo, accion), "Decisión aplicada.")
        return {"ok": True, "idempotente": False, "accion": accion, **resultado_extra, "mensaje": mensaje}
