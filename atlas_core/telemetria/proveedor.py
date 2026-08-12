"""Puerto genérico de telemetría (Bloque TELEMETRÍA T1) y doble simulado.

Contrato mínimo que cualquier proveedor de telemetría (Onelogis hoy,
cualquier otro mañana, o ninguno) debe cumplir. El núcleo de Atlas
(extractor, rutas, gestor_viajes, procesamiento_masivo) solo debe conocer
este módulo -- nunca `proveedores/onelogis.py` directamente. La ausencia
de proveedor (`proveedor_telemetria=None`) es un caso de primera clase en
todo el pipeline, no una excepción.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from atlas_core.telemetria.modelos import (
    EstadoTelemetria,
    PosicionTelemetria,
    ResultadoBreadcrumbs,
    ResultadoPosicion,
    ResultadoVehiculos,
    ResultadoViajes,
    ViajeTelemetria,
)


class ProveedorTelemetria(Protocol):
    nombre: str

    def listar_vehiculos(self) -> ResultadoVehiculos: ...

    def obtener_posicion_actual(self, patente: str) -> ResultadoPosicion: ...

    def buscar_viajes(
        self, patente: str, desde: date, hasta: date
    ) -> ResultadoViajes: ...

    def obtener_breadcrumbs(self, trip_id: str) -> ResultadoBreadcrumbs: ...


@dataclass
class ProveedorTelemetriaSimulado:
    """Doble determinista para tests -- nunca toca la red."""

    vehiculos: tuple = ()
    posiciones: dict = field(default_factory=dict)
    viajes_por_patente: dict = field(default_factory=dict)
    breadcrumbs_por_trip: dict = field(default_factory=dict)
    nombre: str = "simulado"
    llamadas_vehiculos: int = 0
    llamadas_viajes: int = 0
    llamadas_breadcrumbs: int = 0

    def listar_vehiculos(self) -> ResultadoVehiculos:
        self.llamadas_vehiculos += 1
        return ResultadoVehiculos(EstadoTelemetria.OK, tuple(self.vehiculos))

    def obtener_posicion_actual(self, patente: str) -> ResultadoPosicion:
        posicion = self.posiciones.get(patente.strip().upper())
        if posicion is None:
            return ResultadoPosicion(
                EstadoTelemetria.VEHICULO_NO_ENCONTRADO, motivo="PATENTE_NO_ENCONTRADA"
            )
        return ResultadoPosicion(EstadoTelemetria.OK, posicion)

    def buscar_viajes(self, patente: str, desde: date, hasta: date) -> ResultadoViajes:
        self.llamadas_viajes += 1
        viajes = self.viajes_por_patente.get(patente.strip().upper())
        if viajes is None:
            return ResultadoViajes(
                EstadoTelemetria.VEHICULO_NO_ENCONTRADO, motivo="PATENTE_NO_ENCONTRADA"
            )
        if not viajes:
            return ResultadoViajes(EstadoTelemetria.SIN_HISTORICO, motivo="SIN_VIAJES_EN_VENTANA")
        return ResultadoViajes(EstadoTelemetria.OK, tuple(viajes))

    def obtener_breadcrumbs(self, trip_id: str) -> ResultadoBreadcrumbs:
        self.llamadas_breadcrumbs += 1
        puntos = self.breadcrumbs_por_trip.get(str(trip_id))
        if puntos is None:
            return ResultadoBreadcrumbs(
                EstadoTelemetria.TRIP_NO_ENCONTRADO, motivo="TRIP_ID_NO_ENCONTRADO"
            )
        return ResultadoBreadcrumbs(EstadoTelemetria.OK, tuple(puntos))
