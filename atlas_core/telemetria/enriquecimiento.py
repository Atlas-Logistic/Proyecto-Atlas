"""Orquestación de telemetría a nivel de documento (Bloque TELEMETRÍA T2,
Fase I; corregido en Bloque OPERACIÓN REAL R1). Enriquecimiento OPCIONAL:
sin `ServicioTelemetria` conectado, Atlas funciona exactamente igual que
antes de este bloque. Nunca se llama desde funciones "universales" sin
que quien orquesta (`procesamiento_masivo`) decida explícitamente
conectar un proveedor -- ver límites multiempresa.

Bloque OPERACIÓN REAL R1 -- causa raíz corregida: el origen (¿desde qué
planta salió el camión?) y el recorrido de entrega (¿qué tramos
representan el viaje documental hacia el destino?) son preguntas
DISTINTAS y ahora se resuelven por separado. Antes, el origen dependía
de que la selección de recorrido de entrega tuviera éxito -- si no
encontraba un tramo "sustancial" (>= 5 km), `origen_gps` quedaba vacío
aunque hubiera evidencia GPS real de la planta en tramos de maniobra más
cortos, excluidos a propósito de esa selección (ver
`resolver_planta_origen_gps`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

from atlas_core.catalogo_plantas import Planta
from atlas_core.telemetria.modelos import EstadoTelemetria
from atlas_core.telemetria.seleccion_recorrido import (
    ORIGEN_GPS_NO_DETERMINADO,
    EstadoSeleccionRecorrido,
    completar_recorrido_con_breadcrumbs,
    resolver_planta_origen_gps,
    seleccionar_recorrido_operacional,
)
from atlas_core.telemetria.servicio import ServicioTelemetria

CAMPOS_TELEMETRIA_DOCUMENTO = (
    "proveedor_telemetria",
    "estado_telemetria",
    "origen_gps",
    "planta_gps_id",
    "planta_gps_nombre",
    "hora_entrada_gps",
    "hora_salida_gps",
    "distancia_gps_km",
    "evidencia_telemetria",
    # Bloque TELEMETRÍA T3: motivo/evidencia de la resolución de ORIGEN
    # (distinto de `evidencia_telemetria`, que describe el recorrido de
    # ENTREGA hacia el destino). Poblado siempre que hay una decisión de
    # origen que explicar (ESTADIA_EN_GEOCERCA, conflicto, etc.).
    # `latitud_estadia_gps`/`longitud_estadia_gps`/`duracion_estadia_gps_min`
    # solo se llenan en `ORIGEN_GPS_ESTADIA_SIN_PLANTA`: una detención GPS
    # real y prolongada cuya coordenada no cae en ninguna geocerca
    # catalogada -- nunca se le asigna nombre de planta, pero la
    # evidencia queda visible para revisión humana en vez de perderse.
    "motivo_origen_gps",
    "latitud_estadia_gps",
    "longitud_estadia_gps",
    "duracion_estadia_gps_min",
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
    """Resuelve, para UN documento: (1) desde qué planta salió realmente
    el camión (ventana temporal amplia, independiente de si hay un
    recorrido de entrega "sustancial"), y (2) el recorrido de entrega
    hacia el destino (para desambiguar geocodificación -- ver
    `descartar_candidatos_lejos_de_gps`). Nunca lanza. Nunca asume una
    planta por defecto: sin evidencia GPS suficiente, `origen_gps` queda
    en un estado explícito (`ORIGEN_GPS_NO_DETERMINADO`), nunca vacío
    sin motivo."""
    from atlas_core.rutas.modelos import Coordenadas

    plantas = list(plantas)
    campos = {campo: "" for campo in CAMPOS_TELEMETRIA_DOCUMENTO}
    campos["proveedor_telemetria"] = servicio.proveedor.nombre if servicio.proveedor else ""

    resultado_viajes = servicio.buscar_viajes(patente, fecha, fecha)
    if resultado_viajes.estado not in (EstadoTelemetria.OK, EstadoTelemetria.RESULTADO_DESDE_CACHE):
        campos["estado_telemetria"] = resultado_viajes.estado.value
        # `origen_gps` usa siempre el vocabulario ORIGEN_GPS_* (Fase B) --
        # nunca vacío sin motivo (Fase G: sin evidencia GPS, no se
        # inventa una planta, pero el motivo del porqué queda explícito
        # en `estado_telemetria`).
        campos["origen_gps"] = ORIGEN_GPS_NO_DETERMINADO
        campos["motivo_origen_gps"] = resultado_viajes.estado.value
        return ResultadoEnriquecimientoTelemetria(campos, None)
    campos["estado_telemetria"] = EstadoSeleccionRecorrido.SELECCIONADO.value

    # (1) Origen -- ventana amplia, independiente del recorrido de entrega.
    origen = resolver_planta_origen_gps(
        servicio, patente=patente, fecha=fecha,
        hora_entrada=hora_entrada, hora_salida=hora_salida, plantas=plantas,
    )
    campos["origen_gps"] = origen.estado
    campos["planta_gps_id"] = origen.planta_id or ""
    campos["planta_gps_nombre"] = origen.planta_nombre or ""
    campos["hora_entrada_gps"] = origen.hora_entrada_gps
    campos["hora_salida_gps"] = origen.hora_salida_gps
    campos["motivo_origen_gps"] = origen.motivo
    campos["latitud_estadia_gps"] = str(origen.latitud_estadia) if origen.latitud_estadia is not None else ""
    campos["longitud_estadia_gps"] = str(origen.longitud_estadia) if origen.longitud_estadia is not None else ""
    campos["duracion_estadia_gps_min"] = (
        str(origen.duracion_estadia_min) if origen.duracion_estadia_min is not None else ""
    )

    # (2) Recorrido de entrega -- para desambiguar destino (Bloque T1/T2).
    seleccion = seleccionar_recorrido_operacional(
        resultado_viajes.viajes, patente=patente, fecha=fecha.isoformat(),
        hora_entrada=hora_entrada, hora_salida=hora_salida,
    )
    if seleccion.estado != EstadoSeleccionRecorrido.SELECCIONADO or seleccion.recorrido is None:
        return ResultadoEnriquecimientoTelemetria(campos, None)

    recorrido = completar_recorrido_con_breadcrumbs(servicio, seleccion.recorrido)
    campos["distancia_gps_km"] = (
        str(recorrido.distancia_gps_total_km) if recorrido.distancia_gps_total_km is not None else ""
    )
    campos["evidencia_telemetria"] = recorrido.evidencia_seleccion

    punto_gps_destino = (
        Coordenadas(recorrido.ultimo_punto.longitud, recorrido.ultimo_punto.latitud)
        if recorrido.ultimo_punto is not None
        else None
    )
    return ResultadoEnriquecimientoTelemetria(campos, punto_gps_destino)
