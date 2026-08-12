"""Puente entre telemetría genérica y el contrato GPS que ya usa la
resolución de planta origen (Bloque RUTAS R1 -- `resolver_planta_origen`/
`calcular_ruta_para_viaje`/`calcular_ruta_entrega_para_viaje`, parámetro
`proveedor_posicion`). Ese contrato (`ProveedorPosicionVehiculo`) existía
desde antes de este bloque, sin ningún adaptador real conectado -- este
módulo NO abre un camino nuevo, conecta el que ya estaba.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from atlas_core.rutas.modelos import Coordenadas
from atlas_core.rutas.posicion_vehiculo import (
    EstadoPosicionVehiculo,
    ResultadoPosicionVehiculo,
)
from atlas_core.telemetria.modelos import EstadoTelemetria, PosicionTelemetria, ViajeTelemetria
from atlas_core.telemetria.servicio import ServicioTelemetria

_ESTADOS_CON_DATOS = (EstadoTelemetria.OK, EstadoTelemetria.RESULTADO_DESDE_CACHE)


def _instante_de(texto: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(texto).strip())
    except (TypeError, ValueError):
        return None


def _viaje_mas_cercano(
    viajes: tuple[ViajeTelemetria, ...], instante: datetime
) -> ViajeTelemetria | None:
    """Ancla temporal conservadora: prioriza un viaje cuyo intervalo
    [inicio, fin] CONTIENE el instante buscado; si ninguno lo contiene,
    el de borde más cercano. Nunca elige "el más largo" ni "el de más
    distancia" -- solo cercanía temporal, que es lo único que este
    contrato pide (posición cerca de un instante dado)."""
    mejor: ViajeTelemetria | None = None
    mejor_distancia: timedelta | None = None
    for viaje in viajes:
        inicio = _instante_de(viaje.inicio)
        fin = _instante_de(viaje.fin)
        if inicio is None or fin is None:
            continue
        if inicio <= instante <= fin:
            distancia = timedelta(0)
        else:
            distancia = min(abs(instante - inicio), abs(instante - fin))
        if mejor_distancia is None or distancia < mejor_distancia:
            mejor, mejor_distancia = viaje, distancia
    return mejor


def _punto_mas_cercano(puntos, instante: datetime) -> PosicionTelemetria | None:
    mejor: PosicionTelemetria | None = None
    mejor_distancia: timedelta | None = None
    for punto in puntos:
        momento = _instante_de(punto.timestamp)
        if momento is None:
            continue
        distancia = abs(instante - momento)
        if mejor_distancia is None or distancia < mejor_distancia:
            mejor, mejor_distancia = punto, distancia
    return mejor


class AdaptadorPosicionTelemetria:
    """Implementa `ProveedorPosicionVehiculo` sobre cualquier
    `ServicioTelemetria` (Onelogis hoy). `ventana_busqueda_dias` acota
    cuántos días de historial se piden -- por defecto solo el día del
    propio instante, para no golpear la API pidiendo rangos amplios sin
    necesidad (Bloque M, costo)."""

    def __init__(
        self, servicio: ServicioTelemetria, *, ventana_busqueda_dias: int = 0
    ) -> None:
        self._servicio = servicio
        self._ventana_dias = max(0, ventana_busqueda_dias)
        self.nombre = (
            servicio.proveedor.nombre if servicio.proveedor is not None else "telemetria"
        )

    def obtener_posicion(
        self, patente: str, instante: datetime
    ) -> ResultadoPosicionVehiculo:
        fecha = instante.date()
        desde = fecha - timedelta(days=self._ventana_dias)
        hasta = fecha + timedelta(days=self._ventana_dias)
        resultado_viajes = self._servicio.buscar_viajes(patente, desde, hasta)
        if resultado_viajes.estado == EstadoTelemetria.SIN_HISTORICO:
            # Proveedor respondió correctamente: simplemente no hay viajes
            # de este vehículo en la ventana -- no es un fallo del
            # proveedor, es ausencia de dato.
            return ResultadoPosicionVehiculo(
                EstadoPosicionVehiculo.SIN_DATOS,
                proveedor=self.nombre, motivo=resultado_viajes.estado.value,
            )
        if resultado_viajes.estado not in _ESTADOS_CON_DATOS:
            return ResultadoPosicionVehiculo(
                EstadoPosicionVehiculo.PROVEEDOR_NO_DISPONIBLE,
                proveedor=self.nombre, motivo=resultado_viajes.estado.value,
            )
        candidato = _viaje_mas_cercano(resultado_viajes.viajes, instante)
        if candidato is None:
            return ResultadoPosicionVehiculo(
                EstadoPosicionVehiculo.SIN_DATOS,
                proveedor=self.nombre, motivo="SIN_VIAJES_EN_LA_VENTANA",
            )
        resultado_bc = self._servicio.obtener_breadcrumbs(candidato.proveedor_trip_id)
        if resultado_bc.estado not in _ESTADOS_CON_DATOS or not resultado_bc.puntos:
            return ResultadoPosicionVehiculo(
                EstadoPosicionVehiculo.SIN_DATOS,
                proveedor=self.nombre, motivo="SIN_BREADCRUMBS_DEL_VIAJE_CANDIDATO",
            )
        punto = _punto_mas_cercano(resultado_bc.puntos, instante)
        if punto is None:
            return ResultadoPosicionVehiculo(
                EstadoPosicionVehiculo.SIN_DATOS,
                proveedor=self.nombre, motivo="BREADCRUMBS_SIN_TIMESTAMP_VALIDO",
            )
        return ResultadoPosicionVehiculo(
            EstadoPosicionVehiculo.POSICION_ENCONTRADA,
            coordenadas=Coordenadas(punto.longitud, punto.latitud),
            timestamp_gps=punto.timestamp,
            proveedor=self.nombre,
        )
