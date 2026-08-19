"""Aplicación transaccional y auditable de decisiones R3.3/R3.4 (obras y destinos)."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico
from atlas_core.catalogo_destinos import CatalogoDestinos
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, ResultadoEvidencia, TipoEvidencia
from atlas_core.catalogo_plantas import CatalogoPlantas
from atlas_core.catalogo_vehiculos import (
    TipoVehiculo, cargar_catalogo_vehiculos,
    confirmar_vehiculo, normalizar_patente_vehiculo,
)
from atlas_core.decisiones_pendientes import (
    actualizar_contrato_vehiculos_persistidos, decision_destino_para_obra_registrada,
    generar_artefacto, regenerar_decisiones_persistidas,
)

# Bloque ORIGEN D1: fuente de origen que representa una confirmación humana
# explícita para UN documento/viaje -- máxima precedencia posible (ver
# `atlas_core.gestor_viajes._JERARQUIA_FUENTE_ORIGEN`). Se define aquí (no
# sólo en gestor_viajes) porque es este módulo el que la escribe.
FUENTE_ORIGEN_CONFIRMACION_HUMANA = "CONFIRMACION_HUMANA"

ACCIONES = frozenset({
    "REGISTRAR", "NO_REGISTRAR", "CONFIRMAR", "NO_CONFIRMAR", "POSPONER",
    "CONFIRMAR_PLANTA", "SELECCIONAR_OTRA_PLANTA", "NO_PUEDO_DETERMINAR",
})
LEDGER = "decisiones_aplicadas.json"

# R3.4: qué acciones son válidas para cada tipo de decisión -- una acción de
# un tipo nunca se aplica a una decisión de otro tipo, aunque comparta el
# mismo código POSPONER.
ACCIONES_POR_TIPO = {
    "OBRA_DESCONOCIDA": frozenset({"REGISTRAR", "NO_REGISTRAR", "POSPONER"}),
    "DESTINO_SIN_CONFIRMAR": frozenset({"CONFIRMAR", "NO_CONFIRMAR", "POSPONER"}),
    "VEHICULO_DESCONOCIDO": frozenset({"REGISTRAR", "NO_REGISTRAR", "POSPONER"}),
    "ORIGEN_NO_CONFIRMADO": frozenset({
        "CONFIRMAR_PLANTA", "SELECCIONAR_OTRA_PLANTA", "NO_PUEDO_DETERMINAR", "POSPONER",
    }),
}

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


def _instante_iso(valor: object) -> datetime | None:
    try:
        instante = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        return instante if instante.tzinfo is not None else instante.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _reconciliar_bandeja_legacy_publicada(
    *, raiz: Path, actual: Path, catalogos: Path, dataset: Path,
    artefacto_ruta: Path, artefacto: dict[str, object], ledger: dict[str, object], reloj,
) -> dict[str, object]:
    """R3.5.1: repara exclusivamente la ventana legacy R3.4 demostrable.

    R3.4 publicaba la bandeja y luego revalidaba dataset/reporte. Para no
    debilitar la barrera de obsolescencia, no basta con que el hash difiera:
    estado_operacion + manifest del reporte deben acreditar el dataset actual,
    los catálogos deben seguir iguales a la bandeja y el ledger debe enlazar
    cronológicamente una CONFIRMAR de destino contra el hash anterior.
    Cualquier cambio externo posterior hace fallar al menos una condición y
    se conserva el rechazo normal.
    """
    hash_actual = _sha(dataset)
    hash_artefacto = str(artefacto.get("dataset_sha256") or "").upper()
    if not hash_artefacto or hash_actual == hash_artefacto:
        return artefacto

    for clave, nombre in {
        "clientes": "clientes.json", "vehiculos": "vehiculos.json",
        "obras_destinos": "obras_destinos.json", "destinos_maestros": "destinos_maestros.json",
    }.items():
        ruta = catalogos / nombre
        actual_hash = _sha(ruta) if ruta.is_file() else None
        if artefacto.get("catalogos_sha256", {}).get(clave) != actual_hash:
            return artefacto

    try:
        estado = json.loads((actual / "estado_operacion.json").read_text(encoding="utf-8"))
        dataset_estado = (raiz / str(estado["dataset_operacional"])).resolve()
        decisiones_estado = (raiz / str(estado["decisiones_pendientes"])).resolve()
        reporte = (raiz / str(estado["reporte_vigente"])).resolve()
        manifest = json.loads((reporte / "manifest_reporte_viajes.json").read_text(encoding="utf-8"))
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return artefacto
    if dataset_estado != dataset.resolve() or decisiones_estado != artefacto_ruta.resolve():
        return artefacto
    try:
        reporte.relative_to((raiz / "reportes").resolve())
    except ValueError:
        return artefacto
    if not reporte.name.startswith("reporte_revalidacion_"):
        return artefacto
    origen = manifest.get("origen") or {}
    try:
        origen_ruta = Path(str(origen.get("ruta"))).resolve()
    except (OSError, ValueError):
        return artefacto
    if origen_ruta != dataset.resolve() or str(origen.get("sha256") or "").upper() != hash_actual:
        return artefacto

    generado_bandeja = _instante_iso(artefacto.get("generado_en"))
    generado_reporte = _instante_iso(manifest.get("fecha_generacion"))
    if generado_bandeja is None or generado_reporte is None or generado_reporte <= generado_bandeja:
        return artefacto
    aplicaciones_legacy = [
        item for item in ledger.get("aplicaciones", [])
        if item.get("tipo") == "DESTINO_SIN_CONFIRMAR"
        and item.get("accion") == "CONFIRMAR"
        and str(item.get("dataset_sha256") or "").upper() == hash_artefacto
        and (_instante_iso(item.get("fecha")) or generado_reporte) <= generado_bandeja
    ]
    if not aplicaciones_legacy:
        return artefacto

    restantes = regenerar_decisiones_persistidas(
        decisiones=artefacto.get("decisiones", []), carpeta_catalogos=catalogos,
    )
    return generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=restantes,
        ruta_salida=artefacto_ruta, reloj=reloj,
    )


def aplicar_decision_obra(*, raiz_atlas: str | Path, decision_id: str, accion: str, tipo_vehiculo: str | None = None, planta_id_elegida: str | None = None, actor: str = "JAVIER_DESKTOP", reloj=lambda: datetime.now(timezone.utc)) -> dict[str, object]:
    raiz = Path(raiz_atlas); actual = raiz / "operacion" / "actual"; catalogos = raiz / "catalogos_privados"
    artefacto_ruta = actual / "decisiones_pendientes.json"; ledger_ruta = actual / LEDGER
    dataset = actual / "analisis_completo_guias.csv"
    catalogo_obras_ruta = catalogos / "obras_destinos.json"
    catalogo_destinos_ruta = catalogos / "destinos_maestros.json"
    catalogo_vehiculos_ruta = catalogos / "vehiculos.json"
    catalogo_plantas_ruta = catalogos / "plantas.json"
    estado_operacion_ruta = actual / "estado_operacion.json"
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
        artefacto = _reconciliar_bandeja_legacy_publicada(
            raiz=raiz, actual=actual, catalogos=catalogos, dataset=dataset,
            artefacto_ruta=artefacto_ruta, artefacto=artefacto, ledger=ledger, reloj=reloj,
        )
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

        # R3.6.1: las bandejas creadas antes del contrato estructurado de
        # vehículos pueden tener hashes vigentes pero carecer de clasificación
        # de tipo. Sólo después de superar la barrera de obsolescencia se
        # actualiza el contrato desde las decisiones/documentos ya persistidos,
        # sin OCR ni lectura de imágenes.
        regeneradas_contrato = actualizar_contrato_vehiculos_persistidos(
            artefacto.get("decisiones", []),
        )
        if regeneradas_contrato != artefacto.get("decisiones", []):
            artefacto = generar_artefacto(
                ruta_dataset=dataset, carpeta_catalogos=catalogos,
                decisiones=regeneradas_contrato, ruta_salida=artefacto_ruta, reloj=reloj,
            )
            coincidencias = [d for d in artefacto.get("decisiones", []) if d.get("decision_id") == decision_id]
            if len(coincidencias) != 1:
                raise ErrorAplicacionDecision("La decisión ya no está pendiente.")
            decision = coincidencias[0]
            tipo = decision.get("tipo")

        contexto = decision.get("contexto") or {}
        cliente_id = str(contexto.get("cliente_id", ""))
        respaldos = {
            ruta: ruta.read_bytes() if ruta.exists() else None
            for ruta in (
                catalogo_obras_ruta, catalogo_destinos_ruta, ledger_ruta,
                catalogo_vehiculos_ruta, artefacto_ruta, dataset, estado_operacion_ruta,
            )
        }
        resultado_extra: dict[str, object] = {}
        reporte_salida: Path | None = None
        reporte_salida_existia = False
        decision_siguiente: dict[str, object] | None = None
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
                    catalogo_obras_destinos = CatalogoObrasDestinos(ruta=catalogo_obras_ruta, ruta_clientes=catalogos/"clientes.json", ruta_destinos=catalogo_destinos_ruta)
                    resultado_obs = catalogo_obras_destinos.registrar_observacion(cliente_id=cliente_id, nombre_obra=obra_texto, evidencia=evidencia)
                    resultado_extra["obra_id"] = resultado_obs.obra.obra_id
                    # R3.4.2: registrar la obra responde "¿qué obra es?", pero
                    # no "¿a qué destino corresponde?". Si ese destino todavía
                    # no puede corroborarse sin intervención humana (CASO A) y
                    # el documento sí trajo un destino (CASO B), Atlas debe
                    # generar esa siguiente pregunta accionable -- si no hay
                    # destino documental capturado (CASO C), se abstiene: no
                    # inventa. Ver decision_destino_para_obra_registrada.
                    decision_siguiente = decision_destino_para_obra_registrada(
                        obra=resultado_obs.obra, cliente_id=cliente_id,
                        cliente_canonico=str(contexto.get("cliente_canonico", "")),
                        destino_documental=contexto.get("destino_documental", ""),
                        documento=decision.get("documento"),
                        catalogo_obras=catalogo_obras_destinos,
                    )
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
            elif tipo == "VEHICULO_DESCONOCIDO":
                patente = normalizar_patente_vehiculo(str(decision.get("valor_documental") or ""))
                resolucion = decision.get("tipo_resolucion")
                propuesto = decision.get("tipo_vehiculo_propuesto")
                recibido = str(tipo_vehiculo or "").strip().upper()
                if accion != "REGISTRAR" and recibido:
                    raise ErrorAplicacionDecision("El tipo de vehículo sólo corresponde al registrar.")
                tipo_final = None
                vehiculo_id = None
                if accion == "REGISTRAR":
                    if resolucion == "INEQUIVOCO" and propuesto in {"TRACTO", "CARRO"}:
                        if recibido and recibido != propuesto:
                            raise ErrorAplicacionDecision("El tipo recibido contradice el tipo documental inequívoco.")
                        tipo_final = str(propuesto)
                    elif resolucion == "REQUIERE_CONFIRMACION_HUMANA":
                        if recibido not in {"TRACTO", "CAMION_RIGIDO"}:
                            raise ErrorAplicacionDecision("Seleccione Tracto o Camión rígido para registrar esta patente.")
                        tipo_final = recibido
                    else:
                        raise ErrorAplicacionDecision("La decisión no contiene una clasificación de vehículo segura.")
                    cargado = cargar_catalogo_vehiculos(catalogo_vehiculos_ruta)
                    existente = next((v for v in cargado.homologables() if v.patente_canonica == patente), None)
                    if existente is not None:
                        if existente.tipo != tipo_final:
                            raise ErrorAplicacionDecision("La patente ya existe con un tipo diferente.")
                        vehiculo = existente
                    else:
                        vehiculo = confirmar_vehiculo(
                            catalogo_vehiculos_ruta, patente=patente,
                            tipo=TipoVehiculo(tipo_final), actor="JAVIER_MBT",
                            fuente_decision=f"DECISION_HUMANA_R3_6:{decision_id}",
                            fecha=reloj(), referencia_hash=decision_id,
                            observaciones=f"Guía {(decision.get('documento') or {}).get('numero_guia', '')}; campo {decision.get('campo', '')}",
                        )
                    vehiculo_id = vehiculo.vehiculo_id
                    resultado_extra.update({"vehiculo_id": vehiculo_id, "tipo_vehiculo": tipo_final})
                aplicacion = {
                    "decision_id": decision_id, "tipo": tipo, "accion": accion,
                    "actor": "JAVIER_MBT", "fecha": reloj().astimezone(timezone.utc).isoformat(),
                    "documento": decision.get("documento"), "campo": decision.get("campo"),
                    "valor_documental": patente, "vehiculo_id": vehiculo_id,
                    "tipo_vehiculo": tipo_final, "dataset_sha256": artefacto.get("dataset_sha256"),
                    "catalogos_sha256_antes": artefacto.get("catalogos_sha256"),
                }
            elif tipo == "ORIGEN_NO_CONFIRMADO":
                # Bloque ORIGEN D1 -- confirmación humana AUDITABLE de la
                # planta de origen de UN documento/viaje. Nunca modifica
                # plantas.json (sólo lo lee para validar); nunca aprende una
                # asociación chofer->planta ni vehículo->planta. Preserva
                # siempre la evidencia anterior (GPS/documento) -- sólo
                # cambia cuál queda como origen CANÓNICO.
                documento_decision = decision.get("documento") or {}
                numero_guia_decision = str(documento_decision.get("numero_guia") or "")
                if not numero_guia_decision:
                    raise ErrorAplicacionDecision("La decisión no contiene identidad suficiente para confirmar el origen.")

                planta_id_objetivo = None
                if accion == "CONFIRMAR_PLANTA":
                    candidatos_decision = decision.get("candidatos") or []
                    if len(candidatos_decision) != 1:
                        raise ErrorAplicacionDecision(
                            "Esta decisión tiene más de un candidato -- use SELECCIONAR_OTRA_PLANTA para indicar cuál."
                        )
                    planta_id_objetivo = str(candidatos_decision[0].get("planta_id") or "")
                elif accion == "SELECCIONAR_OTRA_PLANTA":
                    planta_id_objetivo = str(planta_id_elegida or "").strip()
                    if not planta_id_objetivo:
                        raise ErrorAplicacionDecision("Debe indicar qué planta corresponde.")

                valor_anterior = None
                planta_confirmada_id = None
                planta_confirmada_nombre = None
                if accion in ("CONFIRMAR_PLANTA", "SELECCIONAR_OTRA_PLANTA"):
                    plantas_vigentes = CatalogoPlantas(catalogo_plantas_ruta).listar()
                    planta_confirmada = next(
                        (
                            p for p in plantas_vigentes
                            if p.planta_id == planta_id_objetivo
                            and p.estado_calidad == "CONFIRMADA" and p.estado_vigencia == "ACTIVA"
                        ),
                        None,
                    )
                    if planta_confirmada is None:
                        raise ErrorAplicacionDecision("La planta indicada no existe o no está confirmada/activa.")
                    from atlas_core.revalidacion_documental import _escribir_filas_completas, _leer_filas
                    filas_dataset = _leer_filas(dataset)
                    fila_objetivo = next(
                        (f for f in filas_dataset if str(f.get("numero_guia", "")) == numero_guia_decision), None,
                    )
                    if fila_objetivo is None:
                        raise ErrorAplicacionDecision("No se encontró el documento de esta decisión en el dataset vigente.")
                    valor_anterior = {
                        "planta_origen_id": fila_objetivo.get("planta_origen_id", ""),
                        "planta_origen_nombre": fila_objetivo.get("planta_origen_nombre", ""),
                        "origen_determinado_por": fila_objetivo.get("origen_determinado_por", ""),
                        "evidencia_origen": fila_objetivo.get("evidencia_origen", ""),
                    }
                    # La evidencia GPS/documental original NUNCA se borra --
                    # queda íntegra en `motivo_origen_gps`/`evidencia_telemetria`/
                    # etc., columnas que este bloque no toca. Sólo cambian
                    # las 4 columnas de origen canónico.
                    fila_objetivo["planta_origen_id"] = planta_confirmada.planta_id
                    fila_objetivo["planta_origen_nombre"] = planta_confirmada.nombre
                    fila_objetivo["origen_determinado_por"] = FUENTE_ORIGEN_CONFIRMACION_HUMANA
                    fila_objetivo["evidencia_origen"] = f"DECISION_HUMANA:{decision_id}"
                    _escribir_filas_completas(dataset, filas_dataset)
                    planta_confirmada_id = planta_confirmada.planta_id
                    planta_confirmada_nombre = planta_confirmada.nombre
                    resultado_extra["planta_id"] = planta_confirmada_id
                    resultado_extra["planta_nombre"] = planta_confirmada_nombre
                # NO_PUEDO_DETERMINAR: no se toca el dataset -- sólo queda
                # registrado en el ledger (ver más abajo), lo que basta para
                # que `generar_artefacto` no vuelva a preguntar lo mismo
                # mientras la evidencia no cambie (acción terminal, ver
                # `decisiones_pendientes.generar_artefacto`).

                aplicacion = {
                    "decision_id": decision_id, "tipo": tipo, "accion": accion, "actor": actor,
                    "fecha": reloj().astimezone(timezone.utc).isoformat(),
                    "documento": decision.get("documento"),
                    "planta_id": planta_confirmada_id, "planta_nombre": planta_confirmada_nombre,
                    "valor_anterior": valor_anterior, "evidencia_previa": decision.get("evidencias"),
                    "candidatos_previos": decision.get("candidatos"),
                    "fuente": FUENTE_ORIGEN_CONFIRMACION_HUMANA if planta_confirmada_id else None,
                    "dataset_sha256": artefacto.get("dataset_sha256"),
                    "catalogos_sha256_antes": artefacto.get("catalogos_sha256"),
                }
            else:
                raise ErrorAplicacionDecision("Esta decisión no puede aplicarse en este bloque.")

            ledger.setdefault("aplicaciones", []).append(aplicacion)
            escribir_json_atomico(ledger_ruta, ledger)

            # R3.5/R3.6.2: cualquier revalidación que cambie el dataset debe
            # ocurrir ANTES de publicar la nueva bandeja. Así el artefacto
            # restante nace con los hashes finales del flujo canónico y la
            # siguiente decisión puede aplicarse inmediatamente, sin
            # debilitar la comprobación de obsolescencia realizada al
            # entrar. R3.6.2 añade el disparo cuando REGISTRAR confirma
            # canónicamente una patente -- puede resolver PATENTE_SIN_HOMOLOGAR
            # en cualquier fila del dataset, no sólo en la guía de origen de
            # la decisión (misma política ya vigente para obra/destino).
            if (tipo == "DESTINO_SIN_CONFIRMAR" and accion == "CONFIRMAR") or (
                tipo == "VEHICULO_DESCONOCIDO" and accion == "REGISTRAR"
            ):
                from atlas_core.revalidacion_documental import revalidar_y_regenerar_reporte
                instante = reloj()
                nombre_carpeta = f"reporte_revalidacion_{instante.strftime('%Y%m%d_%H%M%S_%f')}"
                reporte_salida = raiz / "reportes" / nombre_carpeta
                reporte_salida_existia = reporte_salida.exists()
                resultado_extra["revalidacion"] = revalidar_y_regenerar_reporte(
                    raiz_atlas=raiz, nombre_carpeta_reporte=nombre_carpeta, reloj=reloj,
                )
            elif tipo == "ORIGEN_NO_CONFIRMADO" and accion in ("CONFIRMAR_PLANTA", "SELECCIONAR_OTRA_PLANTA"):
                # Bloque ORIGEN D1 -- a diferencia de DESTINO_SIN_CONFIRMAR/
                # VEHICULO_DESCONOCIDO, aquí ya sabemos que el dataset
                # cambió (se acaba de escribir arriba, en el bloque de
                # aplicación) -- no hace falta una revalidación condicional
                # que decida si algo cambió, sólo regenerar el reporte con
                # el mecanismo canónico ya existente.
                from atlas_core.almacenamiento_portable import escribir_estado_operacion
                from atlas_core.reporte_viajes import generar_reporte_viajes
                instante = reloj()
                nombre_carpeta = f"reporte_revalidacion_{instante.strftime('%Y%m%d_%H%M%S_%f')}"
                reporte_salida = raiz / "reportes" / nombre_carpeta
                reporte_salida_existia = reporte_salida.exists()
                generar_reporte_viajes(
                    dataset, reporte_salida, carpeta_catalogos=catalogos, reloj=lambda: instante,
                )
                ruta_decisiones_operacion = actual / "decisiones_pendientes.json"
                escribir_estado_operacion(
                    reporte_vigente=reporte_salida, dataset_operacional=dataset,
                    decisiones_pendientes=(ruta_decisiones_operacion if ruta_decisiones_operacion.is_file() else None),
                    raiz=raiz,
                )
                resultado_extra["reporte_regenerado"] = True

            restantes = regenerar_decisiones_persistidas(
                decisiones=artefacto.get("decisiones", []),
                carpeta_catalogos=catalogos,
                ids_resueltos={decision_id},
            )
            if decision_siguiente is not None:
                # R3.4.2: la nueva pregunta de destino entra a la bandeja
                # igual que cualquier otra -- `generar_artefacto` la
                # deduplica/filtra contra el ledger como a cualquier decisión
                # (idempotente; nunca resucita una ya decidida terminalmente).
                restantes.append(decision_siguiente)
            bandeja = generar_artefacto(
                ruta_dataset=dataset, carpeta_catalogos=catalogos,
                decisiones=restantes, ruta_salida=artefacto_ruta, reloj=reloj,
            )
            resultado_extra["decisiones_pendientes"] = len(bandeja["decisiones"])
        except Exception:
            for ruta, contenido in respaldos.items(): _restaurar(ruta, contenido)
            if reporte_salida is not None and not reporte_salida_existia and reporte_salida.exists():
                shutil.rmtree(reporte_salida)
            raise

        mensajes = {
            ("OBRA_DESCONOCIDA", "REGISTRAR"): "Obra registrada. Atlas podrá reconocerla en documentos futuros.",
            ("OBRA_DESCONOCIDA", "NO_REGISTRAR"): "Decisión guardada. Atlas no registrará esta observación como obra.",
            ("DESTINO_SIN_CONFIRMAR", "CONFIRMAR"): "Destino confirmado. Atlas podrá reconocer esta obra y destino en documentos futuros.",
            ("DESTINO_SIN_CONFIRMAR", "NO_CONFIRMAR"): "Decisión guardada. Atlas no confirmará esta observación como destino.",
            ("VEHICULO_DESCONOCIDO", "REGISTRAR"): "Vehículo registrado. Atlas reconocerá esta patente en documentos futuros.",
            ("VEHICULO_DESCONOCIDO", "NO_REGISTRAR"): "Decisión guardada. Atlas no registrará esta observación como vehículo.",
            ("ORIGEN_NO_CONFIRMADO", "CONFIRMAR_PLANTA"): "Origen confirmado. La planta elegida queda como origen canónico de este viaje.",
            ("ORIGEN_NO_CONFIRMADO", "SELECCIONAR_OTRA_PLANTA"): "Origen confirmado con la planta indicada. Queda como origen canónico de este viaje.",
            ("ORIGEN_NO_CONFIRMADO", "NO_PUEDO_DETERMINAR"): "Decisión guardada. Atlas no volverá a preguntar por este origen mientras la evidencia no cambie.",
        }
        mensaje = mensajes.get((tipo, accion), "Decisión aplicada.")
        return {"ok": True, "idempotente": False, "accion": accion, **resultado_extra, "mensaje": mensaje}
