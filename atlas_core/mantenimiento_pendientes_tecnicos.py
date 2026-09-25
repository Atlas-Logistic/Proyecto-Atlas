"""Mantenimiento focal de la cola técnica, independiente de Desktop/Mobile."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from atlas_core.almacenamiento_portable import (
    SesionOcupadaError, bloqueo_sesion, escribir_estado_operacion,
    escribir_json_atomico,
)
from atlas_core.capacidades_reevaluacion import versiones_actuales
from atlas_core.decisiones_pendientes import (
    _guias_con_direccion_confirmada_por_humano,
    _guias_destino_terminado_por_humano,
    clasificar_fallo_tecnico,
)
from atlas_core.politica_pendientes_tecnicos import conocimiento_para_guia, elegibilidad
from atlas_core.reconciliacion_estado_derivado import (
    LEDGER, NOMBRE_ARTEFACTO, NOMBRE_PENDIENTES_TECNICOS, RULESET_VERSION,
    _cargar_seguimiento, _ciclo_vida_pendiente, _leer_filas, _pendientes_ruta,
    _registro_pendiente,
)
from atlas_core.reporte_viajes import _sha256_archivo, generar_reporte_viajes
from atlas_core.revalidacion_documental import (
    reconciliar_decisiones_destino_no_resuelto,
    revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr,
    revalidar_ruta_sin_destino_calculado_sin_ocr,
)

# Protección del proveedor: una pasada (cada 5 min) atiende a lo sumo
# este número de guías; el resto sigue elegible en la pasada siguiente.
# Primero los cambios de conocimiento, luego el intento más antiguo.
MAX_GUIAS_POR_PASADA = 10
_CAUSAS_CAMBIO = {"CONOCIMIENTO_CAMBIO", "CAMBIO_NOTIFICADO"}
# Lock exterior de `aplicar_decision_obra`: su plan de impacto ya
# revalida lo afectado; el mantenimiento no compite con él.
_LOCK_DECISION_HUMANA = ".atlas_lock_aplicar_decision_obra"


def _plan(
    raiz: Path, instante: datetime, *, solo_cambios: bool = False,
    guias_forzadas: set[str] | None = None,
) -> tuple[list[dict], dict[str, str], dict[str, str]]:
    actual = raiz / "operacion" / "actual"
    dataset = actual / "analisis_completo_guias.csv"
    decisiones = actual / NOMBRE_ARTEFACTO
    previos = _cargar_seguimiento(actual / NOMBRE_PENDIENTES_TECNICOS)
    filas = {str(f.get("numero_guia", "")).strip(): f for f in _pendientes_ruta(dataset, decisiones)}
    humanas = _guias_con_direccion_confirmada_por_humano(actual / "decisiones_aplicadas.json")
    terminadas = _guias_destino_terminado_por_humano(actual / "decisiones_aplicadas.json")
    versiones = versiones_actuales()
    candidatos: list[tuple[tuple, dict]] = []
    huellas: dict[str, str] = {}
    for guia, fila in filas.items():
        registro = _registro_pendiente(fila, previos.get(guia))
        # La huella previa se conserva aunque la evidencia de ruta cambie:
        # son dos dimensiones independientes de elegibilidad.
        registro["huella_conocimiento"] = (previos.get(guia) or {}).get("huella_conocimiento")
        huella = conocimiento_para_guia(
            fila, catalogos=raiz / "catalogos_privados",
            decisiones_aplicadas=actual / "decisiones_aplicadas.json",
            version_reglas=RULESET_VERSION, versiones_capacidades=versiones,
        )
        huellas[guia] = huella
        elegible, causa = elegibilidad(registro, huella_actual=huella, instante=instante)
        if guia in (guias_forzadas or set()):
            elegible, causa = True, "CAMBIO_NOTIFICADO"
        elif solo_cambios and causa != "CONOCIMIENTO_CAMBIO":
            continue
        if guia in terminadas or (guia in humanas and causa not in {"CONOCIMIENTO_CAMBIO", "CAMBIO_NOTIFICADO"}):
            continue
        if elegible:
            orden = (causa not in _CAUSAS_CAMBIO, str(registro.get("ultimo_intento") or ""), guia)
            candidatos.append((orden, {
                "numero_guia": guia, "causa": causa,
                "clase": clasificar_fallo_tecnico(str(registro["motivo_actual"])),
            }))
    candidatos.sort(key=lambda par: par[0])
    elegibles = [e for _, e in candidatos[:MAX_GUIAS_POR_PASADA]]
    causas = {e["numero_guia"]: e["causa"] for e in elegibles}
    return elegibles, huellas, causas


def mantener_pendientes_tecnicos(
    *, raiz_atlas: str | Path, reloj=lambda: datetime.now(timezone.utc),
    proveedor_rutas=None, proveedor_rutas_fallback=None, solo_plan: bool = False,
    solo_cambios: bool = False, guias_forzadas: set[str] | None = None,
) -> dict[str, object]:
    """Una pasada. Vuelve a seleccionar dentro del lock antes de hacer red.

    `solo_plan` es estrictamente read-only y sirve para verificar una tarea
    instalada sin ejecutar ningún pendiente real.
    """
    raiz = Path(raiz_atlas)
    actual = raiz / "operacion" / "actual"
    dataset = actual / "analisis_completo_guias.csv"
    if not dataset.is_file():
        return {"ejecutado": False, "motivo": "SIN_DATASET", "elegibles": []}
    instante = reloj().astimezone(timezone.utc)
    if solo_plan:
        elegibles, _, _ = _plan(raiz, instante, solo_cambios=solo_cambios,
                                guias_forzadas=guias_forzadas)
        return {"ejecutado": False, "motivo": "SOLO_PLAN", "elegibles": elegibles}
    try:
        with bloqueo_sesion(actual, "reconciliacion_estado_derivado"):
            if (actual / _LOCK_DECISION_HUMANA).exists():
                return {"ejecutado": False, "motivo": "DECISION_EN_CURSO", "elegibles": []}
            # La selección de arriba no se reutiliza: otro proceso pudo
            # resolver o intentar la guía mientras esperábamos el lock.
            elegibles, huellas, causas = _plan(
                raiz, instante, solo_cambios=solo_cambios, guias_forzadas=guias_forzadas,
            )
            previos = _cargar_seguimiento(actual / NOMBRE_PENDIENTES_TECNICOS)
            ids = {e["numero_guia"] for e in elegibles}
            huella_dataset_inicial = _sha256_archivo(dataset)
            if ids:
                # Conocimiento humano/local antes de cualquier geocodificador.
                revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr(
                    ruta_dataset=dataset, carpeta_catalogos=raiz / "catalogos_privados",
                    proveedor_rutas=proveedor_rutas,
                    proveedor_rutas_fallback=proveedor_rutas_fallback,
                    guias_objetivo=ids, solo_con_coordenadas=True,
                )
                filas_intermedias = {str(f.get("numero_guia", "")): f for f in _leer_filas(dataset)}
                # Un AGOTABLE con idéntica evidencia recibe la oportunidad
                # interna de 30 min, pero no repite ORS/Nominatim/B1. El
                # transitorio sí puede mejorar cuando se recupera la red.
                externos = {
                    e["numero_guia"] for e in elegibles
                    if filas_intermedias.get(e["numero_guia"], {}).get("estado_ruta") != "RUTA_CALCULADA"
                    and (e["clase"] == "TRANSITORIO" or e["causa"] in {"CONOCIMIENTO_CAMBIO", "CAMBIO_NOTIFICADO"})
                }
                if externos:
                    revalidar_ruta_sin_destino_calculado_sin_ocr(
                        ruta_dataset=dataset, carpeta_catalogos=raiz / "catalogos_privados",
                        proveedor_rutas=proveedor_rutas,
                        proveedor_rutas_fallback=proveedor_rutas_fallback,
                        guias_objetivo=externos,
                    )

            filas_pendientes = {str(f.get("numero_guia", "")).strip(): f for f in
                                _pendientes_ruta(dataset, actual / NOMBRE_ARTEFACTO)}
            humanas = _guias_con_direccion_confirmada_por_humano(actual / "decisiones_aplicadas.json")
            terminadas = _guias_destino_terminado_por_humano(actual / "decisiones_aplicadas.json")
            registros: list[dict] = []
            for guia, fila in filas_pendientes.items():
                previo = previos.get(guia)
                registro = _registro_pendiente(fila, previo)
                registro["huella_conocimiento"] = huellas.get(guia) or conocimiento_para_guia(
                    fila, catalogos=raiz / "catalogos_privados",
                    decisiones_aplicadas=actual / "decisiones_aplicadas.json",
                    version_reglas=RULESET_VERSION, versiones_capacidades=versiones_actuales(),
                )
                if guia in ids:
                    if causas[guia] in {"CONOCIMIENTO_CAMBIO", "CAMBIO_NOTIFICADO"}:
                        registro["intentos_misma_evidencia"] = 0
                    registro["intentos_misma_evidencia"] = int(registro["intentos_misma_evidencia"]) + 1
                    registro["ultimo_intento"] = instante.isoformat()
                    registro["ultimo_resultado"] = str(fila.get("motivo_ruta", "")) or "SIN_CAMBIO"
                    historial = list(registro["historial_resultados"])[-9:]
                    historial.append({"fecha": instante.isoformat(), "resultado": registro["ultimo_resultado"],
                                     "causa": causas[guia]})
                    registro["historial_resultados"] = historial
                registro.update(_ciclo_vida_pendiente(
                    registro, instante=instante,
                    direccion_confirmada_por_humano=guia in humanas,
                    destino_terminado_por_humano=guia in terminadas,
                ))
                registros.append(registro)
            if not ids and len(registros) == len(previos) and all(
                previos.get(r["numero_guia"]) == r for r in registros
            ):
                return {"ejecutado": False, "motivo": "SIN_ELEGIBLES", "elegibles": []}
            escribir_json_atomico(actual / NOMBRE_PENDIENTES_TECNICOS, {
                "schema_version": 1, "actualizado_en": instante.isoformat(), "pendientes": registros,
            })
            if not ids:
                return {"ejecutado": False, "motivo": "HUELLAS_ACTUALIZADAS", "elegibles": []}

            # Publica únicamente tarjetas de las guías intentadas. Las
            # decisiones ajenas conservan su contenido anterior. Siempre
            # corre: un AGOTABLE que alcanza su límite publica su tarjeta
            # aunque la fila del dataset no haya cambiado.
            reconciliar_decisiones_destino_no_resuelto(
                raiz_atlas=raiz, reloj=lambda: instante, guias_objetivo=ids,
            )
            if _sha256_archivo(dataset) == huella_dataset_inicial:
                # Ninguna fila cambió: el reporte vigente sigue siendo fiel.
                return {"ejecutado": True, "elegibles": elegibles, "resueltas": [],
                        "pendientes": sorted(ids & set(filas_pendientes)),
                        "reporte_regenerado": False}

            reporte = raiz / "reportes" / f"mantenimiento_tecnico_{instante.strftime('%Y%m%d_%H%M%S_%f')}"
            huella_dataset = _sha256_archivo(dataset)
            try:
                generar_reporte_viajes(
                    dataset, reporte, carpeta_catalogos=raiz / "catalogos_privados",
                    ruta_ledger=actual / LEDGER, reloj=lambda: instante,
                )
                if _sha256_archivo(dataset) != huella_dataset:
                    shutil.rmtree(reporte, ignore_errors=True)
                    return {"ejecutado": False, "motivo": "DATASET_AVANZO_DURANTE_REPORTE", "elegibles": elegibles}
                escribir_estado_operacion(
                    reporte_vigente=reporte, dataset_operacional=dataset,
                    decisiones_pendientes=(actual / NOMBRE_ARTEFACTO if (actual / NOMBRE_ARTEFACTO).is_file() else None),
                    raiz=raiz, reloj=lambda: instante, origen="MANTENIMIENTO_PENDIENTES_TECNICOS",
                    dataset_sha256=huella_dataset,
                )
            except Exception:
                shutil.rmtree(reporte, ignore_errors=True)
                raise
            return {"ejecutado": True, "elegibles": elegibles,
                    "resueltas": sorted(ids - set(filas_pendientes)),
                    "pendientes": sorted(ids & set(filas_pendientes)),
                    "reporte_regenerado": True}
    except SesionOcupadaError:
        return {"ejecutado": False, "motivo": "OTRA_SESION_ACTIVA", "elegibles": []}
