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
from atlas_core.catalogo_clientes import (
    CatalogoClientes, ClienteDuplicadoError, ClienteNoEncontradoError,
    EstadoCalidadCliente, normalizar_nombre_cliente, normalizar_rut_cliente,
)
from atlas_core.catalogo_destinos import CatalogoDestinos, DestinoDuplicadoError, EstadoCalidadDestino
from atlas_core.catalogo_obras_destinos import (
    CatalogoObrasDestinos, ErrorCatalogoObrasDestinos, EstadoVigencia,
    Evidencia, ResultadoEvidencia, TipoEvidencia,
)
from atlas_core.catalogo_plantas import CatalogoPlantas
from atlas_core.catalogo_vehiculos import (
    TipoVehiculo, cargar_catalogo_vehiculos,
    confirmar_vehiculo, normalizar_patente_vehiculo,
)
from atlas_core.decisiones_pendientes import (
    _decisiones_obra_para_cliente, actualizar_contrato_vehiculos_persistidos,
    decision_destino_para_obra_registrada, generar_artefacto,
    regenerar_decisiones_persistidas, rut_documental_de_decision_cliente,
)
from atlas_core.evidencia_entidades import AlmacenEvidenciaEntidades
from atlas_core.incidencias_documentales import (
    AlmacenIncidenciasDocumentales, TIPO_IDENTIDAD_CLIENTE_INCONSISTENTE,
)
from atlas_core.rutas.modelos import EstadoRuta

# Bloque ORIGEN D1: fuente de origen que representa una confirmación humana
# explícita para UN documento/viaje -- máxima precedencia posible (ver
# `atlas_core.gestor_viajes._JERARQUIA_FUENTE_ORIGEN`). Se define aquí (no
# sólo en gestor_viajes) porque es este módulo el que la escribe.
FUENTE_ORIGEN_CONFIRMACION_HUMANA = "CONFIRMACION_HUMANA"

ACCIONES = frozenset({
    "REGISTRAR", "NO_REGISTRAR", "CONFIRMAR", "NO_CONFIRMAR", "POSPONER",
    "CONFIRMAR_PLANTA", "SELECCIONAR_OTRA_PLANTA", "NO_PUEDO_DETERMINAR",
    # Bloque VEHÍCULO D1: patrón documental->canónico para vehículos --
    # reutiliza REGISTRAR/NO_REGISTRAR/POSPONER ya existentes (una patente
    # sin ninguna sugerencia se sigue tratando exactamente igual que
    # antes); estas dos son nuevas, análogas a CONFIRMAR_PLANTA/
    # SELECCIONAR_OTRA_PLANTA pero para vehículos.
    "USAR_PATENTE_EXISTENTE", "SELECCIONAR_OTRA_PATENTE",
    # MOTOR DE EVIDENCIA FASE 3: primera aplicación real para
    # CLIENTE_DESCONOCIDO/ALIAS_CANDIDATO -- hasta este bloque ninguna de
    # las dos tenía backend, sólo UX preparatoria (ver
    # ACCIONES_POR_TIPO/rama final `else` más abajo). REGISTRAR/
    # NO_REGISTRAR/POSPONER se reutilizan tal cual para CLIENTE_DESCONOCIDO
    # (mismo patrón que OBRA_DESCONOCIDA); CONFIRMAR_ALIAS/RECHAZAR son
    # nuevas.
    "CONFIRMAR_ALIAS", "RECHAZAR",
    # Bloque R6 A/B/E: única acción nueva de DESTINO_NO_RESUELTO -- las
    # otras dos (NO_PUEDO_DETERMINAR/POSPONER) ya existen arriba.
    "REGISTRAR_DIRECCION",
    # Bloque R9: única acción nueva de CLIENTE_AUSENTE.
    "REGISTRAR_CLIENTE_MANUAL",
})
LEDGER = "decisiones_aplicadas.json"

# R3.4: qué acciones son válidas para cada tipo de decisión -- una acción de
# un tipo nunca se aplica a una decisión de otro tipo, aunque comparta el
# mismo código POSPONER.
ACCIONES_POR_TIPO = {
    "OBRA_DESCONOCIDA": frozenset({"REGISTRAR", "NO_REGISTRAR", "POSPONER"}),
    "DESTINO_SIN_CONFIRMAR": frozenset({"CONFIRMAR", "NO_CONFIRMAR", "POSPONER"}),
    "VEHICULO_DESCONOCIDO": frozenset({
        "REGISTRAR", "NO_REGISTRAR", "POSPONER",
        "USAR_PATENTE_EXISTENTE", "SELECCIONAR_OTRA_PATENTE",
    }),
    "CLIENTE_DESCONOCIDO": frozenset({"REGISTRAR", "NO_REGISTRAR", "POSPONER"}),
    "CLIENTE_CANDIDATO": frozenset({"CONFIRMAR", "NO_CONFIRMAR", "POSPONER"}),
    "ALIAS_CANDIDATO": frozenset({"CONFIRMAR_ALIAS", "RECHAZAR", "POSPONER"}),
    "ORIGEN_NO_CONFIRMADO": frozenset({
        "CONFIRMAR_PLANTA", "SELECCIONAR_OTRA_PLANTA", "NO_PUEDO_DETERMINAR", "POSPONER",
    }),
    "DESTINO_NO_RESUELTO": frozenset({
        "REGISTRAR_DIRECCION", "NO_PUEDO_DETERMINAR", "POSPONER",
    }),
    "CLIENTE_AUSENTE": frozenset({
        "REGISTRAR_CLIENTE_MANUAL", "NO_PUEDO_DETERMINAR", "POSPONER",
    }),
}

class ErrorAplicacionDecision(ValueError): pass
class DecisionObsoletaError(ErrorAplicacionDecision): pass


def normalizar_rut_cliente_o_vacio(rut: str) -> str:
    """Igual que `normalizar_rut_cliente`, pero nunca lanza -- un RUT
    documental inválido nunca debe interrumpir la aplicación de una
    decisión, sólo tratarse como ausente (ver
    `atlas_core.motor_evidencia_clientes`: RUT inválido nunca es verdad)."""
    try:
        return normalizar_rut_cliente(rut)
    except ValueError:
        return ""


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


def aplicar_decision_obra(*, raiz_atlas: str | Path, decision_id: str, accion: str, tipo_vehiculo: str | None = None, planta_id_elegida: str | None = None, patente_elegida: str | None = None, motivo_rechazo: str | None = None, direccion_manual: str | None = None, razon_social_manual: str | None = None, rut_manual: str | None = None, proveedor_rutas: object = None, actor: str = "JAVIER_DESKTOP", reloj=lambda: datetime.now(timezone.utc)) -> dict[str, object]:
    raiz = Path(raiz_atlas); actual = raiz / "operacion" / "actual"; catalogos = raiz / "catalogos_privados"
    artefacto_ruta = actual / "decisiones_pendientes.json"; ledger_ruta = actual / LEDGER
    dataset = actual / "analisis_completo_guias.csv"
    catalogo_obras_ruta = catalogos / "obras_destinos.json"
    catalogo_destinos_ruta = catalogos / "destinos_maestros.json"
    catalogo_vehiculos_ruta = catalogos / "vehiculos.json"
    catalogo_plantas_ruta = catalogos / "plantas.json"
    catalogo_clientes_ruta = catalogos / "clientes.json"
    evidencia_entidades_ruta = catalogos / "evidencia_entidades.json"
    incidencias_documentales_ruta = catalogos / "incidencias_documentales.json"
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
        if _sha(dataset) != artefacto.get("dataset_sha256"):
            # Bloque R11 -- causa raíz de "la decisión quedó obsoleta porque
            # cambió el dataset" reapareciendo indefinidamente incluso
            # después de "Refrescar datos" (Desktop sólo relee archivos,
            # nunca revalida): el hash del dataset a nivel de ARCHIVO
            # COMPLETO puede cambiar por un motivo ajeno a ESTA decisión --
            # p. ej. otra guía revalidada por separado (caso real: catch-up
            # de R10 aplicado directo contra producción). La protección en
            # sí es correcta (nunca se aplica sobre datos que no vio); lo
            # que faltaba era reconciliar la bandeja aquí mismo, en vez de
            # dejar al usuario atrapado con una tarjeta muerta. Se
            # revalida/republica la bandeja contra el dataset actual (mismo
            # mecanismo que ya usa `revalidar_y_regenerar_reporte`, sin
            # memoria paralela) y se reevalúa ESTA decisión exacta contra el
            # resultado fresco:
            #   - si sigue idéntica y ya vigente -> el cambio era ajeno,
            #     se continúa aplicándola tal cual, sin exigir un segundo
            #     intento;
            #   - si ya no está o cambió de verdad -> se rechaza igual que
            #     antes (nunca se aplica la decisión vieja), pero la bandeja
            #     ya quedó fresca para que Revisión de Atlas muestre la
            #     pregunta vigente (o la ausencia de ella) en el siguiente
            #     refresco, sin que Atlas vuelva a quedarse atascado.
            from atlas_core.revalidacion_documental import revalidar_y_regenerar_reporte
            try:
                revalidar_y_regenerar_reporte(
                    raiz_atlas=raiz,
                    nombre_carpeta_reporte=f"reporte_revalidacion_{reloj().strftime('%Y%m%d_%H%M%S_%f')}",
                    reloj=reloj,
                )
                artefacto_fresco = json.loads(artefacto_ruta.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                # El propio intento de reconciliar falló (dataset realmente
                # corrupto/incompatible, catálogo ilegible, etc.) -- nunca
                # se enmascara con un error distinto ni se deja a medio
                # escribir; se conserva el mensaje original de siempre.
                raise DecisionObsoletaError("La decisión quedó obsoleta porque cambió el dataset.")
            coincidencias_frescas = [d for d in artefacto_fresco.get("decisiones", []) if d.get("decision_id") == decision_id]
            sigue_identica = (
                len(coincidencias_frescas) == 1
                and coincidencias_frescas[0] == decision
                and _sha(dataset) == artefacto_fresco.get("dataset_sha256")
            )
            if not sigue_identica:
                mensaje = (
                    "La decisión quedó obsoleta porque cambió el dataset. Atlas ya actualizó Revisión de Atlas -- "
                    + ("revise la tarjeta vigente." if coincidencias_frescas else "esta pregunta ya no aplica.")
                )
                raise DecisionObsoletaError(mensaje)
            artefacto = artefacto_fresco
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
                catalogo_clientes_ruta, evidencia_entidades_ruta, incidencias_documentales_ruta,
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
                    # Bloque RESOLUCIÓN R16 -- una confirmación humana
                    # explícita ("CONFIRMAR") es exactamente la evidencia
                    # que `estado_calidad=CONFIRMADO` representa; antes de
                    # este bloque el destino quedaba en PENDIENTE para
                    # siempre (nunca promovido en ningún otro lugar),
                    # dejando la Vía A de desambiguación
                    # (`resolver_destino_ambiguo_con_evidencia_inequivoca`)
                    # sin ningún destino real que pudiera usar.
                    destino = CatalogoDestinos(catalogo_destinos_ruta, ruta_clientes=catalogos/"clientes.json").crear_o_reutilizar_global(
                        nombre_destino=destino_texto, direccion=destino_texto, fuente=fuente,
                        estado_calidad=EstadoCalidadDestino.CONFIRMADO,
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
                patente_canonica_elegida = None
                motivo_rechazo_final = None
                # Bloque VEHÍCULO D1 -- patrón documental->canónico: NUNCA
                # modifica el valor documental (`patente`, arriba, sigue
                # siendo exactamente lo que leyó OCR) ni escribe el CSV --
                # sólo el catálogo (ya existente, sin cambios) y el ledger,
                # que es lo que preserva de forma auditable la asociación
                # documento->vehículo canónico. La operación de "usar
                # operacionalmente" esa patente para el viaje queda para un
                # consumidor futuro del ledger (fuera de alcance de este
                # bloque, ver bitácora).
                if accion in ("USAR_PATENTE_EXISTENTE", "SELECCIONAR_OTRA_PATENTE"):
                    candidatos_decision = decision.get("candidatos") or []
                    if accion == "USAR_PATENTE_EXISTENTE":
                        if len(candidatos_decision) != 1:
                            raise ErrorAplicacionDecision(
                                "Esta decisión tiene más de una candidata -- use SELECCIONAR_OTRA_PATENTE para indicar cuál."
                            )
                        patente_objetivo = normalizar_patente_vehiculo(str(candidatos_decision[0].get("patente") or ""))
                    else:
                        patente_objetivo = normalizar_patente_vehiculo(str(patente_elegida or ""))
                        if not patente_objetivo:
                            raise ErrorAplicacionDecision("Indique la patente canónica elegida.")
                    cargado = cargar_catalogo_vehiculos(catalogo_vehiculos_ruta)
                    vehiculo_canonico = next(
                        (
                            v for v in cargado.homologables()
                            if v.patente_canonica == patente_objetivo
                        ),
                        None,
                    )
                    if vehiculo_canonico is None:
                        raise ErrorAplicacionDecision("La patente indicada no existe o no está confirmada/activa.")
                    vehiculo_id = vehiculo_canonico.vehiculo_id
                    patente_canonica_elegida = vehiculo_canonico.patente_canonica
                    tipo_final = vehiculo_canonico.tipo
                    resultado_extra.update({
                        "vehiculo_id": vehiculo_id, "patente_canonica": patente_canonica_elegida,
                        "tipo_vehiculo": tipo_final,
                    })
                elif accion == "NO_REGISTRAR":
                    # Preserva, si se entrega, el motivo humano del rechazo
                    # (p. ej. "ERROR_DOCUMENTAL_MANDANTE") -- puramente
                    # informativo en el ledger, nunca obligatorio (no rompe
                    # la firma ya usada por Desktop hoy).
                    motivo_rechazo_final = str(motivo_rechazo).strip() if motivo_rechazo else None
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
                    "patente_canonica": patente_canonica_elegida,
                    "tipo_vehiculo": tipo_final, "motivo_rechazo": motivo_rechazo_final,
                    "candidatos_previos": decision.get("candidatos") or None,
                    "dataset_sha256": artefacto.get("dataset_sha256"),
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
                    from atlas_core.revalidacion_documental import (
                        _escribir_filas_completas, _leer_filas,
                        derivar_estado_ruta_tras_cambio_origen,
                    )
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
                    # Bloque OBSERVABILIDAD D1 -- si el destino de este
                    # mismo documento sigue sin resolver, `estado_ruta`/
                    # `motivo_ruta` dejan de describir el origen que
                    # acaba de confirmarse (caso real 464717) y pasan a
                    # expresar el bloqueo de destino vigente. Nunca llama
                    # ORS/geocodificación, nunca fuerza RUTA_CALCULADA.
                    fila_objetivo.update(derivar_estado_ruta_tras_cambio_origen(fila_objetivo))
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
            elif tipo == "DESTINO_NO_RESUELTO":
                # Bloque R6 A/B/E -- con origen ya resuelto, el documento
                # nunca trajo una dirección de entrega utilizable (o
                # geocodificaba de forma contradictoria/ambigua/genérica).
                # Un humano escribe la dirección real; se valida con el
                # MISMO mecanismo determinista ya existente
                # (`revalidar_ruta_sin_destino_calculado_sin_ocr`, con su
                # rechazo de comuna contradicha/resultado genérico/
                # múltiples ubicaciones intacto) -- nunca se acepta a
                # ciegas lo que el humano escribió. Si la ruta SÍ se
                # calcula, la relación obra<->destino queda registrada y
                # CONFIRMADA en el catálogo ya existente -- documentos
                # futuros de la misma obra resuelven solos, sin volver a
                # preguntar (ver `resolver_obra_destino_confirmada_global`,
                # ya usado por `decision_destino_para_obra_registrada`).
                documento_decision = decision.get("documento") or {}
                numero_guia_decision = str(documento_decision.get("numero_guia") or "")
                if not numero_guia_decision:
                    raise ErrorAplicacionDecision("La decisión no contiene identidad suficiente para resolver el destino.")
                ruta_resuelta = False
                relacion_id_nueva = None
                destino_id_nuevo = None
                if accion == "REGISTRAR_DIRECCION":
                    direccion_final = str(direccion_manual or "").strip()
                    if not direccion_final:
                        raise ErrorAplicacionDecision("Debe indicar la dirección de entrega.")
                    from atlas_core.revalidacion_documental import (
                        _escribir_filas_completas, _leer_filas,
                        revalidar_ruta_sin_destino_calculado_sin_ocr,
                    )
                    filas_dataset = _leer_filas(dataset)
                    fila_objetivo = next(
                        (f for f in filas_dataset if str(f.get("numero_guia", "")) == numero_guia_decision), None,
                    )
                    if fila_objetivo is None:
                        raise ErrorAplicacionDecision("No se encontró el documento de esta decisión en el dataset vigente.")
                    # Se limpia el bloqueo anterior (nunca inventa un
                    # resultado): la dirección nueva reemplaza la que
                    # faltaba/contradecía, `revalidar_ruta_sin_destino_
                    # calculado_sin_ocr` decide desde cero si esta sí
                    # geocodifica de forma confiable.
                    fila_objetivo["despachar_a_crudo"] = direccion_final
                    fila_objetivo["estado_ruta"] = ""
                    fila_objetivo["motivo_ruta"] = ""
                    fila_objetivo["estado_entrega"] = ""
                    _escribir_filas_completas(dataset, filas_dataset)
                    resultado_revalidacion = revalidar_ruta_sin_destino_calculado_sin_ocr(
                        ruta_dataset=dataset, carpeta_catalogos=catalogos, proveedor_rutas=proveedor_rutas,
                    )
                    # Bloque LOGÍSTICA L1 -- `guias_actualizadas` ya NO es un
                    # proxy fiable de "ruta resuelta": desde este bloque
                    # también incluye filas cuyo intento falló pero cuyo
                    # motivo se refrescó (nunca se deja un "No disponible"
                    # silencioso, ver `revalidar_ruta_sin_destino_calculado_
                    # sin_ocr`). `ruta_resuelta` se verifica directo contra el
                    # estado real de la fila tras el intento.
                    filas_tras_intento = _leer_filas(dataset)
                    fila_tras_intento = next(
                        (f for f in filas_tras_intento if str(f.get("numero_guia", "")) == numero_guia_decision), None,
                    )
                    ruta_resuelta = (
                        fila_tras_intento is not None
                        and str(fila_tras_intento.get("estado_ruta", "")).strip() == EstadoRuta.RUTA_CALCULADA.value
                    )
                    resultado_extra["ruta_resuelta"] = ruta_resuelta
                    if not ruta_resuelta:
                        resultado_extra["motivo_ruta_tras_intento"] = (
                            fila_tras_intento.get("motivo_ruta", "") if fila_tras_intento is not None else ""
                        )
                    # Bloque R13 -- causa raíz real de "Atlas vuelve a preguntar
                    # un destino que Javier ya confirmó" (casos reales 472099/
                    # VISTA CLARA 2351 CERRILLOS y 472163/VIA MORADA 6480
                    # VITACURA): esta persistencia SÓLO corría dentro de
                    # `else: (ruta_resuelta)` -- si el proveedor de rutas no
                    # podía geocodificar la dirección (una limitación externa,
                    # de terceros), la confirmación humana de la dirección se
                    # perdía por completo: nunca quedaba un Destino/Relación
                    # reutilizable en el catálogo, así que la MISMA dirección
                    # en otra guía (misma u otra obra/cliente) volvía a
                    # preguntarse desde cero. "¿Es correcta esta dirección?"
                    # (una confirmación humana) y "¿el proveedor externo puede
                    # ubicarla?" (una limitación de geocodificación) son dos
                    # preguntas distintas -- la primera debe persistir
                    # siempre que un humano confirme explícitamente, la
                    # segunda sigue gobernando sólo km/tiempo/estado_ruta
                    # (nunca inventados). Se corre siempre que hay dirección
                    # manual, geocodifique o no.
                    contexto_decision = decision.get("contexto") or {}
                    obra_canonica = str(contexto_decision.get("obra_canonica", "")).strip()
                    cliente_canonico_decision = str(contexto_decision.get("cliente_canonico", "")).strip()
                    try:
                        filas_confirmadas = _leer_filas(dataset)
                        fila_confirmada = next(
                            (f for f in filas_confirmadas if str(f.get("numero_guia", "")) == numero_guia_decision), None,
                        )
                        cliente_objetivo = next(
                            (
                                c for c in CatalogoClientes(catalogo_clientes_ruta).listar()
                                if c.razon_social == cliente_canonico_decision
                            ),
                            None,
                        ) if cliente_canonico_decision else None
                        catalogo_obras = CatalogoObrasDestinos(
                            ruta=catalogo_obras_ruta, ruta_clientes=catalogo_clientes_ruta,
                            ruta_destinos=catalogo_destinos_ruta,
                        )
                        obra_objetivo = next(
                            (
                                o for o in catalogo_obras.listar_obras()
                                if o.nombre_canonico == obra_canonica and o.estado_vigencia == EstadoVigencia.ACTIVO.value
                            ),
                            None,
                        ) if obra_canonica else None
                        if fila_confirmada is not None and cliente_objetivo is not None and obra_objetivo is not None:
                            # Bloque RESOLUCIÓN R16 -- causa raíz de que Vía A
                            # (`resolver_destino_ambiguo_con_evidencia_
                            # inequivoca`, catálogo confirmado) nunca pudiera
                            # actuar en la práctica: esta confirmación NUNCA
                            # persistía latitud/longitud, aunque la fila ya
                            # las tuviera resueltas (revalidada arriba, línea
                            # ~666) -- el destino quedaba "confirmado" sin
                            # ningún punto reutilizable. Sólo se persiste si
                            # la ruta quedó efectivamente calculada (nunca un
                            # centroide degradado ni una coordenada a medias).
                            latitud_confirmada = longitud_confirmada = None
                            if str(fila_confirmada.get("estado_ruta", "")).strip() == EstadoRuta.RUTA_CALCULADA.value:
                                try:
                                    latitud_confirmada = float(fila_confirmada.get("latitud_entrega") or "")
                                    longitud_confirmada = float(fila_confirmada.get("longitud_entrega") or "")
                                except (TypeError, ValueError):
                                    latitud_confirmada = longitud_confirmada = None
                            destino_creado = CatalogoDestinos(
                                catalogo_destinos_ruta, ruta_clientes=catalogo_clientes_ruta,
                            ).crear_o_reutilizar_global(
                                nombre_destino=fila_confirmada.get("direccion_entrega") or direccion_final,
                                direccion=fila_confirmada.get("direccion_entrega") or direccion_final,
                                comuna=fila_confirmada.get("localidad_entrega", ""),
                                region=fila_confirmada.get("region_entrega", ""),
                                latitud=latitud_confirmada, longitud=longitud_confirmada,
                                fuente=f"DECISION_HUMANA_R6:{decision_id}",
                                estado_calidad=EstadoCalidadDestino.CONFIRMADO,
                            )
                            evidencia_destino = Evidencia(
                                tipo=TipoEvidencia.GUIA.value,
                                identificador_fuente=numero_guia_decision, referencia_hash=decision_id,
                                campos_observados={
                                    "obra": obra_canonica, "destino": direccion_final,
                                    "decision_id": decision_id, "cliente_id_observado": cliente_objetivo.cliente_id,
                                    "cliente_canonico_observado": cliente_canonico_decision,
                                    "numero_guia": numero_guia_decision,
                                },
                                fecha=reloj().astimezone(timezone.utc).isoformat(),
                                actor_proceso=actor, resultado=ResultadoEvidencia.SOPORTA.value,
                            )
                            resultado_obs = catalogo_obras.registrar_observacion(
                                cliente_id=cliente_objetivo.cliente_id, nombre_obra=obra_canonica,
                                destino_id=destino_creado.destino_id, evidencia=evidencia_destino,
                            )
                            if resultado_obs.relacion is not None:
                                relacion = resultado_obs.relacion
                                if relacion.estado == "PENDIENTE":
                                    relacion = catalogo_obras.confirmar_relacion(
                                        relacion.relacion_id, actor=actor, identificador_fuente=decision_id,
                                    )
                                relacion_id_nueva = relacion.relacion_id
                            destino_id_nuevo = destino_creado.destino_id
                    except (OSError, ValueError, ErrorCatalogoObrasDestinos, ClienteDuplicadoError, DestinoDuplicadoError):
                        # El aprendizaje reutilizable es una mejora
                        # aditiva -- si falla, la ruta de ESTE
                        # documento ya quedó calculada y persistida
                        # arriba; nunca se revierte por esto.
                        pass
                    resultado_extra["destino_id"] = destino_id_nuevo
                    resultado_extra["relacion_id"] = relacion_id_nueva
                # NO_PUEDO_DETERMINAR/POSPONER: no tocan el dataset -- el
                # ledger basta para que no vuelva a preguntarse lo mismo
                # mientras la evidencia no cambie.
                aplicacion = {
                    "decision_id": decision_id, "tipo": tipo, "accion": accion, "actor": actor,
                    "fecha": reloj().astimezone(timezone.utc).isoformat(), "documento": decision.get("documento"),
                    "direccion_manual": str(direccion_manual or "").strip() if accion == "REGISTRAR_DIRECCION" else None,
                    "ruta_resuelta": ruta_resuelta, "destino_id": destino_id_nuevo, "relacion_id": relacion_id_nueva,
                    "dataset_sha256": artefacto.get("dataset_sha256"), "catalogos_sha256_antes": artefacto.get("catalogos_sha256"),
                }
            elif tipo == "CLIENTE_AUSENTE":
                # Bloque R9 -- el campo cliente está genuinamente vacío
                # (nada que corroborar ni comparar, a diferencia de
                # CLIENTE_DESCONOCIDO/CLIENTE_CANDIDATO/ALIAS_CANDIDATO,
                # que siempre parten de un texto documental). Un humano
                # mirando el documento físico escribe la razón social
                # real -- se confía igual que en CLIENTE_DESCONOCIDO/
                # REGISTRAR (mismo nivel de autoridad: una acción humana
                # explícita, no una inferencia).
                documento_decision = decision.get("documento") or {}
                numero_guia_decision = str(documento_decision.get("numero_guia") or "")
                if not numero_guia_decision:
                    raise ErrorAplicacionDecision("La decisión no contiene identidad suficiente para registrar el cliente.")
                cliente_id_nuevo = None
                if accion == "REGISTRAR_CLIENTE_MANUAL":
                    razon_social_final = str(razon_social_manual or "").strip()
                    if not razon_social_final:
                        raise ErrorAplicacionDecision("Debe indicar la razón social del cliente.")
                    rut_valido = normalizar_rut_cliente_o_vacio(rut_manual or "")
                    catalogo_clientes = CatalogoClientes(catalogo_clientes_ruta)
                    try:
                        cliente_creado = catalogo_clientes.crear(
                            razon_social=razon_social_final, fuente=f"DECISION_HUMANA_R9:{decision_id}",
                            rut=rut_valido, estado_calidad=EstadoCalidadCliente.CONFIRMADO,
                        )
                    except ClienteDuplicadoError:
                        cliente_creado = next(
                            (
                                c for c in catalogo_clientes.listar()
                                if c.nombre_normalizado == normalizar_nombre_cliente(razon_social_final)
                            ),
                            None,
                        )
                        if cliente_creado is None:
                            raise
                    cliente_id_nuevo = cliente_creado.cliente_id
                    resultado_extra["cliente_id"] = cliente_id_nuevo
                    from atlas_core.revalidacion_documental import _escribir_filas_completas, _leer_filas
                    filas_dataset = _leer_filas(dataset)
                    fila_objetivo = next(
                        (f for f in filas_dataset if str(f.get("numero_guia", "")) == numero_guia_decision), None,
                    )
                    if fila_objetivo is None:
                        raise ErrorAplicacionDecision("No se encontró el documento de esta decisión en el dataset vigente.")
                    fila_objetivo["cliente"] = cliente_creado.razon_social
                    motivos_fila = {
                        m.strip() for m in str(fila_objetivo.get("motivos_revision_documento", "")).split("|") if m.strip()
                    }
                    motivos_fila.discard("CLIENTE_AUSENTE")
                    fila_objetivo["motivos_revision_documento"] = " | ".join(sorted(motivos_fila))
                    fila_objetivo["indicador_revision"] = "REVISAR" if any(
                        m not in MOTIVOS_NO_BLOQUEANTES for m in motivos_fila
                    ) else "OK"
                    fila_objetivo["estado_documental"] = "REQUIERE_REVISION" if fila_objetivo["indicador_revision"] == "REVISAR" else "OK"
                    _escribir_filas_completas(dataset, filas_dataset)
                # NO_PUEDO_DETERMINAR/POSPONER: no tocan el dataset.
                aplicacion = {
                    "decision_id": decision_id, "tipo": tipo, "accion": accion, "actor": actor,
                    "fecha": reloj().astimezone(timezone.utc).isoformat(), "documento": decision.get("documento"),
                    "razon_social_manual": str(razon_social_manual or "").strip() if accion == "REGISTRAR_CLIENTE_MANUAL" else None,
                    "cliente_id": cliente_id_nuevo,
                    "dataset_sha256": artefacto.get("dataset_sha256"), "catalogos_sha256_antes": artefacto.get("catalogos_sha256"),
                }
            elif tipo == "CLIENTE_DESCONOCIDO":
                # MOTOR DE EVIDENCIA FASE 3 -- primera aplicación real para
                # este tipo (antes sólo UX preparatoria). Mismo patrón que
                # OBRA_DESCONOCIDA: REGISTRAR crea la entidad; el valor
                # documental (`cliente` en el CSV) nunca se toca.
                razon_social_doc = str(decision.get("valor_documental", "")).strip()
                rut_doc = rut_documental_de_decision_cliente(decision)
                if not razon_social_doc:
                    raise ErrorAplicacionDecision("La decisión no contiene una razón social documental.")
                cliente_id_nuevo = None
                if accion == "REGISTRAR":
                    rut_valido = normalizar_rut_cliente_o_vacio(rut_doc)
                    catalogo_clientes = CatalogoClientes(catalogo_clientes_ruta)
                    try:
                        cliente_creado = catalogo_clientes.crear(
                            razon_social=razon_social_doc, fuente=f"DECISION_HUMANA:{decision_id}",
                            rut=rut_valido, estado_calidad=EstadoCalidadCliente.CONFIRMADO,
                        )
                    except ClienteDuplicadoError as error:
                        raise ErrorAplicacionDecision(str(error)) from error
                    cliente_id_nuevo = cliente_creado.cliente_id
                    resultado_extra["cliente_id"] = cliente_id_nuevo
                aplicacion = {
                    "decision_id": decision_id, "tipo": tipo, "accion": accion, "actor": actor,
                    "fecha": reloj().astimezone(timezone.utc).isoformat(), "documento": decision.get("documento"),
                    "valor_documental": razon_social_doc, "rut_documental": rut_doc, "cliente_id": cliente_id_nuevo,
                    "motivo_rechazo": (str(motivo_rechazo).strip() if motivo_rechazo and accion == "NO_REGISTRAR" else None),
                    "evaluacion_evidencia_previa": decision.get("evaluacion_evidencia"),
                    "candidatos_evidencia_previos": decision.get("candidatos_evidencia"),
                    "dataset_sha256": artefacto.get("dataset_sha256"), "catalogos_sha256_antes": artefacto.get("catalogos_sha256"),
                }
            elif tipo == "CLIENTE_CANDIDATO":
                # R4.8 -- primera aplicación real para este tipo (reservado
                # desde R3.1, sin backend hasta ahora). A diferencia de
                # ALIAS_CANDIDATO/CONFIRMAR_ALIAS, aquí el texto documental
                # ya coincide (difuso o por alias) con el nombre canónico --
                # no hay ningún alias nuevo que aprender, sólo una identidad
                # SIN RUT que un humano corrobora o rechaza. CONFIRMAR nunca
                # escribe el catálogo de clientes (nada que registrar: la
                # entidad ya existe tal cual) -- sólo deja constancia
                # auditable en el ledger, consumida después por
                # `revalidar_cliente_sin_corroborar_sin_ocr` (retira el
                # motivo documental) y por
                # `detectar_decisiones_obra_para_cliente_confirmado_sin_ocr`
                # (encadena, sin OCR, la pregunta de obra/destino que
                # `detectar_decisiones_documento` no pudo generar en su
                # momento por falta de identidad de cliente confirmada --
                # mismo patrón ya usado por R3.4.2 para OBRA_DESCONOCIDA).
                identidad_candidata = decision.get("identidad_resuelta") or {}
                cliente_id_candidato = str(identidad_candidata.get("entidad_id", ""))
                valor_documental_cliente = str(decision.get("valor_documental", "")).strip()
                if accion == "CONFIRMAR" and not cliente_id_candidato:
                    raise ErrorAplicacionDecision("La decisión no contiene una identidad de cliente candidata.")
                aplicacion = {
                    "decision_id": decision_id, "tipo": tipo, "accion": accion, "actor": actor,
                    "fecha": reloj().astimezone(timezone.utc).isoformat(), "documento": decision.get("documento"),
                    "campo": decision.get("campo"), "valor_documental": valor_documental_cliente,
                    "cliente_id": cliente_id_candidato if accion == "CONFIRMAR" else None,
                    "valor_canonico": str(identidad_candidata.get("valor_canonico", "")) if accion == "CONFIRMAR" else None,
                    "motivo_rechazo": (str(motivo_rechazo).strip() if motivo_rechazo and accion == "NO_CONFIRMAR" else None),
                    "candidatos_previos": decision.get("candidatos"),
                    "dataset_sha256": artefacto.get("dataset_sha256"), "catalogos_sha256_antes": artefacto.get("catalogos_sha256"),
                }
                if accion == "CONFIRMAR":
                    resultado_extra["cliente_id"] = cliente_id_candidato
                    # R4.8 -- encadena, sin OCR, la pregunta de obra/destino
                    # que `detectar_decisiones_documento` no pudo generar en
                    # su momento por falta de identidad de cliente confirmada
                    # (mismo patrón ya usado por OBRA_DESCONOCIDA/REGISTRAR
                    # más arriba, vía `decision_siguiente`): ahora que un
                    # humano confirmó la identidad, se relee ÚNICAMENTE la
                    # fila ya persistida de ESTE documento (numero_guia) --
                    # nunca OCR -- y se reutiliza el mismo motor de
                    # `_decisiones_obra_para_cliente` (Bloque OBRA_DESCONOCIDA/
                    # DESTINO_SIN_CONFIRMAR) que ya usa la detección inicial.
                    numero_guia_doc = str((decision.get("documento") or {}).get("numero_guia") or "")
                    if numero_guia_doc:
                        from atlas_core.revalidacion_documental import _leer_filas
                        try:
                            candidato_confirmado = CatalogoClientes(catalogo_clientes_ruta).obtener(cliente_id_candidato)
                        except ClienteNoEncontradoError:
                            candidato_confirmado = None
                        fila_guia = next(
                            (f for f in _leer_filas(dataset) if str(f.get("numero_guia", "")) == numero_guia_doc), None,
                        )
                        if candidato_confirmado is not None and fila_guia is not None:
                            siguientes = _decisiones_obra_para_cliente(
                                carpeta=catalogos, cliente_id=candidato_confirmado.cliente_id,
                                cliente_razon_social=candidato_confirmado.razon_social,
                                cliente_aliases=candidato_confirmado.aliases,
                                obra_texto=str(fila_guia.get("obra_destino", "")).strip(),
                                despachar_a_documental=str(fila_guia.get("despachar_a_crudo", "")).strip(),
                                comunes={
                                    "archivo": str((decision.get("documento") or {}).get("archivo", "")),
                                    "numero_guia": numero_guia_doc,
                                    "numero_transporte": str((decision.get("documento") or {}).get("numero_transporte", "")),
                                },
                            )
                            decision_siguiente = siguientes[0] if siguientes else None
            elif tipo == "ALIAS_CANDIDATO":
                # MOTOR DE EVIDENCIA FASE 3: CONFIRMAR_ALIAS ahora hace 3
                # cosas donde antes no hacía ninguna (era sólo UX
                # preparatoria) -- (1) vincula el alias documental al
                # cliente ya identificado por RUT exacto (mismo mecanismo
                # ya usado por confirmaciones manuales anteriores,
                # `CatalogoClientes.agregar_alias`); (2) registra una
                # `ConfirmacionIdentidad` (aprendizaje operacional --
                # FASE 4); (3) como un humano acaba de confirmar
                # explícitamente que el texto documental NO es la entidad
                # real, registra una Incidencia Documental -- el documento
                # nunca se toca, sólo queda auditado.
                identidad = decision.get("identidad_resuelta") or {}
                if str(identidad.get("catalogo", "")) == "empresas.json":
                    raise ErrorAplicacionDecision(
                        "Esta variante de alias (identidad resuelta contra empresas.json, sin registro "
                        "formal en clientes.json) todavía no se puede confirmar en este bloque."
                    )
                cliente_id_alias = str(identidad.get("entidad_id", ""))
                valor_canonico = str(identidad.get("valor_canonico", ""))
                valor_documental_alias = str(decision.get("valor_documental", "")).strip()
                if accion == "CONFIRMAR_ALIAS":
                    if not cliente_id_alias or not valor_canonico or not valor_documental_alias:
                        raise ErrorAplicacionDecision("La decisión no contiene identidad suficiente para confirmar el alias.")
                    catalogo_clientes = CatalogoClientes(catalogo_clientes_ruta)
                    catalogo_clientes.agregar_alias(cliente_id_alias, valor_documental_alias, modificacion_manual=True)
                    documento_decision = decision.get("documento") or {}
                    rut_ctx = rut_documental_de_decision_cliente(decision) or str(identidad.get("rut", ""))
                    rut_normalizado_ctx = normalizar_rut_cliente_o_vacio(rut_ctx)
                    if rut_normalizado_ctx:
                        AlmacenEvidenciaEntidades(evidencia_entidades_ruta).registrar_confirmacion(
                            dominio="CLIENTE", contexto_clave=rut_normalizado_ctx,
                            valor_documental=valor_documental_alias, valor_confirmado=valor_canonico,
                            identificador_confirmado=cliente_id_alias,
                            numero_guia=str(documento_decision.get("numero_guia", "")),
                            numero_transporte=str(documento_decision.get("numero_transporte", "")),
                            actor=actor, fuente_decision=f"CONFIRMAR_ALIAS:{decision_id}", fecha=reloj(),
                        )
                    incidencia = AlmacenIncidenciasDocumentales(incidencias_documentales_ruta).registrar(
                        contexto=valor_canonico, numero_guia=str(documento_decision.get("numero_guia", "")),
                        numero_transporte=str(documento_decision.get("numero_transporte", "")), campo="cliente",
                        valor_documental=valor_documental_alias, valor_canonico=valor_canonico,
                        tipo_incidencia=TIPO_IDENTIDAD_CLIENTE_INCONSISTENTE,
                        evidencia=("RUT_EXACTO_COINCIDE", f"CONFIRMADO_POR_HUMANO:{decision_id}"),
                        fecha=reloj(), fuente_resolucion="CONFIRMAR_ALIAS", actor=actor, decision_id=decision_id,
                    )
                    resultado_extra["cliente_id"] = cliente_id_alias
                    resultado_extra["incidencia_id"] = incidencia.incidencia_id
                aplicacion = {
                    "decision_id": decision_id, "tipo": tipo, "accion": accion, "actor": actor,
                    "fecha": reloj().astimezone(timezone.utc).isoformat(), "documento": decision.get("documento"),
                    "valor_documental": valor_documental_alias, "cliente_id": cliente_id_alias if accion == "CONFIRMAR_ALIAS" else None,
                    "valor_canonico": valor_canonico if accion == "CONFIRMAR_ALIAS" else None,
                    # MOTOR DE EVIDENCIA FASE 4 -- trazabilidad completa
                    # exigida por Javier: la evidencia y el nivel de
                    # resultado que motivaron esta aplicación quedan en el
                    # ledger, nunca sólo en la bandeja transitoria. Permite
                    # reconstruir "qué decía la guía" vs "qué usó Atlas" vs
                    # "por qué", incluso mucho después de que la decisión
                    # ya no esté pendiente.
                    "evaluacion_evidencia_previa": decision.get("evaluacion_evidencia"),
                    "candidatos_evidencia_previos": decision.get("candidatos_evidencia"),
                    "dataset_sha256": artefacto.get("dataset_sha256"), "catalogos_sha256_antes": artefacto.get("catalogos_sha256"),
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
            # Bloque CIERRE OPERACIONAL D1 -- USAR_PATENTE_EXISTENTE/
            # SELECCIONAR_OTRA_PATENTE también confirman una canónica (sin
            # tocar el valor documental) y ahora `revalidar_patente_sin_homologar_sin_ocr`
            # sabe reconocerlas vía el ledger -- caso real que lo motivó:
            # 464265 (VP6521->VP8521, confirmado por Javier) seguía
            # mostrando PATENTE_SIN_HOMOLOGAR después de confirmarse.
            # Bloque R10 -- causa raíz de "decisión cerrada pero el viaje
            # sigue REQUIERE_REVISION" (caso real 472163: OBRA_DESCONOCIDA/
            # REGISTRAR sólo escribía el catálogo de obras -- nunca se
            # revalidaba el motivo documental `OBRA_DESTINO_SIN_CORROBORAR`
            # de ESE mismo documento, así que quedaba fijado para siempre
            # aunque `revalidar_obra_destino_sin_ocr` ya sabía retirarlo vía
            # el ledger, R4.9). Antes de este bloque, cada tipo de decisión
            # necesitaba agregarse A MANO a esta condición para heredar la
            # revalidación -- la misma clase de "whitelist cerrada" que R7
            # ya eliminó para B1. Ahora es al revés: CUALQUIER acción que
            # cierre una decisión (nunca POSPONER/NO_PUEDO_DETERMINAR, que
            # no escriben nada) dispara `revalidar_y_regenerar_reporte`
            # -- sin OCR, sin red, idempotente (sólo regenera si algo
            # cambió) -- salvo los 3 tipos que ya regeneran directo más
            # abajo porque SABEN que el dataset cambió (evitar el trabajo
            # redundante, no por riesgo). Cubre obra/cliente/destino/
            # vehículo/alias hoy y cualquier tipo de decisión nuevo mañana,
            # sin volver a tocar esta lista.
            ACCIONES_TERMINALES_SIN_EFECTO_EN_DATASET = ("POSPONER", "NO_PUEDO_DETERMINAR")
            TIPOS_CON_REGENERACION_DIRECTA = {
                ("ORIGEN_NO_CONFIRMADO", "CONFIRMAR_PLANTA"), ("ORIGEN_NO_CONFIRMADO", "SELECCIONAR_OTRA_PLANTA"),
                ("DESTINO_NO_RESUELTO", "REGISTRAR_DIRECCION"),
                ("CLIENTE_AUSENTE", "REGISTRAR_CLIENTE_MANUAL"),
            }
            if (
                accion not in ACCIONES_TERMINALES_SIN_EFECTO_EN_DATASET
                and (tipo, accion) not in TIPOS_CON_REGENERACION_DIRECTA
            ):
                from atlas_core.revalidacion_documental import revalidar_y_regenerar_reporte
                instante = reloj()
                nombre_carpeta = f"reporte_revalidacion_{instante.strftime('%Y%m%d_%H%M%S_%f')}"
                reporte_salida = raiz / "reportes" / nombre_carpeta
                reporte_salida_existia = reporte_salida.exists()
                resultado_extra["revalidacion"] = revalidar_y_regenerar_reporte(
                    raiz_atlas=raiz, nombre_carpeta_reporte=nombre_carpeta, reloj=reloj,
                )
            elif (
                (tipo == "ORIGEN_NO_CONFIRMADO" and accion in ("CONFIRMAR_PLANTA", "SELECCIONAR_OTRA_PLANTA"))
                # Bloque R6 A/B/E -- mismo caso: REGISTRAR_DIRECCION ya
                # escribió el dataset arriba (`despachar_a_crudo` y, si
                # `revalidar_ruta_sin_destino_calculado_sin_ocr` tuvo
                # éxito, también estado_ruta/distancia/duración) -- se
                # regenera el reporte tanto si la ruta quedó calculada
                # como si sigue bloqueada (con un motivo ya reevaluado,
                # nunca uno obsoleto).
                or (tipo == "DESTINO_NO_RESUELTO" and accion == "REGISTRAR_DIRECCION")
                # Bloque R9 -- mismo caso: REGISTRAR_CLIENTE_MANUAL ya
                # escribió el dataset arriba (cliente + motivos_revision_
                # documento/indicador_revision).
                or (tipo == "CLIENTE_AUSENTE" and accion == "REGISTRAR_CLIENTE_MANUAL")
            ):
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
                    ruta_ledger=ledger_ruta,
                )
                ruta_decisiones_operacion = actual / "decisiones_pendientes.json"
                escribir_estado_operacion(
                    reporte_vigente=reporte_salida, dataset_operacional=dataset,
                    decisiones_pendientes=(ruta_decisiones_operacion if ruta_decisiones_operacion.is_file() else None),
                    raiz=raiz,
                )
                resultado_extra["reporte_regenerado"] = True

            # Bloque REGENERACIÓN B1 -- causa raíz real de que 472037/
            # 472044 perdieran el contexto B1 enriquecido: `artefacto` es
            # la bandeja leída al PRINCIPIO de esta función (antes de
            # aplicar nada) -- si la rama de arriba ya llamó a
            # `revalidar_y_regenerar_reporte` (que republica
            # `decisiones_pendientes.json` en disco, con cualquier
            # hallazgo B1 fresco de OTRAS decisiones), regenerar aquí
            # sobre ese `artefacto` VIEJO y volver a escribir con
            # `generar_artefacto` más abajo descartaba silenciosamente lo
            # que el disco ya tenía -- "usa snapshot/artefacto anterior",
            # exactamente el síntoma reportado. Se relee el archivo justo
            # antes de regenerar -- nunca opera sobre una copia en memoria
            # que pudo quedar desactualizada por una escritura propia de
            # esta misma llamada.
            try:
                artefacto = json.loads(artefacto_ruta.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass  # conserva la copia en memoria si el disco no se puede leer justo ahora
            restantes = regenerar_decisiones_persistidas(
                decisiones=artefacto.get("decisiones", []),
                carpeta_catalogos=catalogos,
                ids_resueltos={decision_id},
                ruta_dataset=dataset,
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
            ("VEHICULO_DESCONOCIDO", "USAR_PATENTE_EXISTENTE"): "Patente canónica confirmada. Queda registrada en el historial de este documento sin modificar el valor documental leído.",
            ("VEHICULO_DESCONOCIDO", "SELECCIONAR_OTRA_PATENTE"): "Patente canónica confirmada con la elegida. Queda registrada en el historial de este documento sin modificar el valor documental leído.",
            ("CLIENTE_DESCONOCIDO", "REGISTRAR"): "Cliente registrado. Atlas podrá reconocerlo en documentos futuros.",
            ("CLIENTE_DESCONOCIDO", "NO_REGISTRAR"): "Decisión guardada. Atlas no registrará esta observación como cliente.",
            ("ALIAS_CANDIDATO", "CONFIRMAR_ALIAS"): "Alias confirmado. Atlas reconocerá este texto como la misma entidad en documentos futuros, y queda registrada una Incidencia Documental.",
            ("ALIAS_CANDIDATO", "RECHAZAR"): "Decisión guardada. Atlas no vinculará este texto documental a la entidad sugerida.",
            ("CLIENTE_CANDIDATO", "CONFIRMAR"): "Identidad de cliente confirmada. Atlas dejará de pedir revisión por falta de RUT en este documento.",
            ("CLIENTE_CANDIDATO", "NO_CONFIRMAR"): "Decisión guardada. Atlas no vinculará este documento a la identidad sugerida.",
            ("DESTINO_NO_RESUELTO", "REGISTRAR_DIRECCION"): (
                "Dirección registrada. Ruta calculada y km/tiempo actualizados; Atlas reconocerá esta obra en documentos futuros."
                if resultado_extra.get("ruta_resuelta")
                else "Dirección registrada, pero sigue sin poder calcularse una ruta confiable con ella -- revise el detalle del motivo."
            ),
            ("DESTINO_NO_RESUELTO", "NO_PUEDO_DETERMINAR"): "Decisión guardada. Atlas no volverá a preguntar por este destino mientras la evidencia no cambie.",
            ("CLIENTE_AUSENTE", "REGISTRAR_CLIENTE_MANUAL"): "Cliente registrado. Atlas reconocerá esta razón social en documentos futuros.",
            ("CLIENTE_AUSENTE", "NO_PUEDO_DETERMINAR"): "Decisión guardada. Atlas no volverá a preguntar por este cliente mientras la evidencia no cambie.",
        }
        mensaje = mensajes.get((tipo, accion), "Decisión aplicada.")
        return {"ok": True, "idempotente": False, "accion": accion, **resultado_extra, "mensaje": mensaje}


def resolver_patentes_confirmadas_por_ledger(
    ruta_ledger: str | Path,
) -> dict[tuple[str, str, str], str]:
    """Bloque VEHÍCULO D1 (cierre, G1) -- índice de solo lectura del ledger:
    ``(numero_guia, campo, valor_documental)`` -> ``patente_canonica``, sólo
    para aplicaciones ``VEHICULO_DESCONOCIDO`` con ``accion`` en
    {``USAR_PATENTE_EXISTENTE``, ``SELECCIONAR_OTRA_PATENTE``} -- las dos
    acciones que confirman una canónica SIN modificar el valor documental
    leído (ver rama ``VEHICULO_DESCONOCIDO`` de `aplicar_decision_obra`,
    arriba, y su comentario "queda para un consumidor futuro del ledger").

    Este índice ES ese consumidor: quien genera el reporte de viajes
    (`atlas_core.reporte_viajes.generar_reporte_viajes`, vía
    `atlas_core.gestor_viajes.agrupar_viajes(resolver_patente=...)`) lo usa
    para que el VALOR OPERACIONAL consolidado de un viaje sea la patente
    canónica ya decidida, sin tocar nunca el dataset documental
    (`analisis_completo_guias.csv` conserva la evidencia original tal
    cual, igual que `evidencias_documentos` por viaje).

    Nunca incluye `NO_REGISTRAR` (rechazo explícito, sin canónica -- p. ej.
    un error documental del mandante, caso real 464036: ese caso queda
    deliberadamente sin resolución operacional aquí, es responsabilidad de
    un estado terminal todavía no implementado -- ver G2, fuera de
    alcance) ni `REGISTRAR` (esa patente pasa a ser la propia canónica vía
    catálogo -- ya resuelto directamente por la homologación normal, sin
    necesitar este índice). Ausencia/corrupción del ledger se trata como
    "sin confirmaciones" -- nunca bloquea nada aguas abajo."""
    indice: dict[tuple[str, str, str], str] = {}
    try:
        ledger = json.loads(Path(ruta_ledger).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return indice
    for aplicacion in ledger.get("aplicaciones", []):
        if aplicacion.get("tipo") != "VEHICULO_DESCONOCIDO":
            continue
        if aplicacion.get("accion") not in ("USAR_PATENTE_EXISTENTE", "SELECCIONAR_OTRA_PATENTE"):
            continue
        patente_canonica = str(aplicacion.get("patente_canonica") or "").strip()
        if not patente_canonica:
            continue
        clave = (
            str((aplicacion.get("documento") or {}).get("numero_guia", "")),
            str(aplicacion.get("campo", "")),
            str(aplicacion.get("valor_documental", "")),
        )
        indice[clave] = patente_canonica
    return indice


def resolver_clientes_confirmados_por_ledger(
    ruta_ledger: str | Path,
) -> dict[str, str]:
    """R4.8 -- índice de solo lectura del ledger análogo a
    `resolver_patentes_confirmadas_por_ledger`: ``numero_guia`` ->
    ``valor_canonico``, sólo para aplicaciones `CLIENTE_CANDIDATO` con
    ``accion=CONFIRMAR``. Único consumidor hoy:
    `atlas_core.revalidacion_documental.revalidar_cliente_sin_corroborar_sin_ocr`,
    para retirar el motivo `CLIENTE_SIN_CORROBORAR` de la fila exacta que
    un humano ya confirmó -- nunca de otras filas con el mismo texto
    documental (la confirmación es por documento, no por texto suelto).
    Ausencia/corrupción del ledger se trata como "sin confirmaciones"."""
    indice: dict[str, str] = {}
    try:
        ledger = json.loads(Path(ruta_ledger).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return indice
    for aplicacion in ledger.get("aplicaciones", []):
        if aplicacion.get("tipo") != "CLIENTE_CANDIDATO" or aplicacion.get("accion") != "CONFIRMAR":
            continue
        valor_canonico = str(aplicacion.get("valor_canonico") or "").strip()
        numero_guia = str((aplicacion.get("documento") or {}).get("numero_guia", ""))
        if not valor_canonico or not numero_guia:
            continue
        indice[numero_guia] = valor_canonico
    return indice
