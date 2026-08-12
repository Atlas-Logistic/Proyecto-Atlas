"""Orquestación de telemetría a nivel de documento (Bloque TELEMETRÍA T2,
Fase I). Enriquecimiento OPCIONAL: sin `ServicioTelemetria` conectado,
Atlas funciona exactamente igual que antes de este bloque. Nunca se llama
desde funciones "universales" sin que quien orquesta (`procesamiento_masivo`)
decida explícitamente conectar un proveedor -- ver límites multiempresa.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

from atlas_core.catalogo_plantas import Planta
from atlas_core.telemetria.modelos import EstadoTelemetria
from atlas_core.telemetria.seleccion_recorrido import (
    EstadoSeleccionRecorrido,
    ResultadoOrigenGPS,
    completar_recorrido_con_breadcrumbs,
    detectar_entrada_salida_planta,
    obtener_breadcrumbs_recorrido,
    seleccionar_recorrido_operacional,
)
from atlas_core.telemetria.servicio import ServicioTelemetria

CAMPOS_TELEMETRIA_DOCUMENTO = (
    "proveedor_telemetria",
    "estado_telemetria",
    "origen_gps",
    "hora_entrada_gps",
    "hora_salida_gps",
    "distancia_gps_km",
    "evidencia_telemetria",
)


@dataclass(frozen=True)
class ResultadoEnriquecimientoTelemetria:
    campos: dict[str, str]
    punto_gps_destino: object | None  # Coordenadas | None, evita import circular con atlas_core.rutas


def enriquecer_documento_con_telemetria(
    *,
    servicio: ServicioTelemetria,
    patente: str,
    fecha: date,
    hora_entrada: datetime | None,
    hora_salida: datetime | None,
    plantas: Iterable[Planta],
) -> ResultadoEnriquecimientoTelemetria:
    """Selecciona el recorrido GPS relevante para UN documento y devuelve
    los campos resumen (Fase L) + el último punto real del recorrido (para
    que quien llama, si hace falta, intente desambiguar destino -- ver
    `descartar_candidatos_lejos_de_gps`). Nunca lanza."""
    from atlas_core.rutas.modelos import Coordenadas

    campos = {campo: "" for campo in CAMPOS_TELEMETRIA_DOCUMENTO}
    campos["proveedor_telemetria"] = servicio.proveedor.nombre if servicio.proveedor else ""

    resultado_viajes = servicio.buscar_viajes(patente, fecha, fecha)
    if resultado_viajes.estado not in (EstadoTelemetria.OK, EstadoTelemetria.RESULTADO_DESDE_CACHE):
        campos["estado_telemetria"] = resultado_viajes.estado.value
        return ResultadoEnriquecimientoTelemetria(campos, None)

    seleccion = seleccionar_recorrido_operacional(
        resultado_viajes.viajes, patente=patente, fecha=fecha.isoformat(),
        hora_entrada=hora_entrada, hora_salida=hora_salida,
    )
    campos["estado_telemetria"] = seleccion.estado.value
    if seleccion.estado != EstadoSeleccionRecorrido.SELECCIONADO or seleccion.recorrido is None:
        return ResultadoEnriquecimientoTelemetria(campos, None)

    recorrido = completar_recorrido_con_breadcrumbs(servicio, seleccion.recorrido)
    campos["distancia_gps_km"] = (
        str(recorrido.distancia_gps_total_km) if recorrido.distancia_gps_total_km is not None else ""
    )
    campos["evidencia_telemetria"] = recorrido.evidencia_seleccion

    puntos = obtener_breadcrumbs_recorrido(servicio, recorrido)
    origen: ResultadoOrigenGPS = detectar_entrada_salida_planta(puntos, plantas)
    campos["origen_gps"] = origen.estado
    campos["hora_entrada_gps"] = origen.hora_entrada_gps
    campos["hora_salida_gps"] = origen.hora_salida_gps

    punto_gps_destino = (
        Coordenadas(recorrido.ultimo_punto.longitud, recorrido.ultimo_punto.latitud)
        if recorrido.ultimo_punto is not None
        else None
    )
    return ResultadoEnriquecimientoTelemetria(campos, punto_gps_destino)
