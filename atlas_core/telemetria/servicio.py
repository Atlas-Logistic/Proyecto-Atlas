"""Servicio de aplicación de telemetría: cachea sobre cualquier
`ProveedorTelemetria` (Bloque TELEMETRÍA T1, Fase M).

`proveedor=None` es un caso de primera clase (Fase L): cualquier consulta
devuelve `SIN_CREDENCIAL`/sin datos de inmediato, sin tocar red ni caché
-- el resto del pipeline sigue exactamente igual que sin telemetría.
"""

from __future__ import annotations

from datetime import date

from atlas_core.telemetria.modelos import (
    EstadoTelemetria,
    ResultadoBreadcrumbs,
    ResultadoViajes,
)
from atlas_core.telemetria.proveedor import ProveedorTelemetria
from atlas_core.telemetria.repositorio import RepositorioTelemetria


class ServicioTelemetria:
    def __init__(
        self,
        proveedor: ProveedorTelemetria | None,
        repositorio: RepositorioTelemetria,
    ) -> None:
        self.proveedor = proveedor
        self.repositorio = repositorio

    def buscar_viajes(self, patente: str, desde: date, hasta: date) -> ResultadoViajes:
        if self.proveedor is None:
            return ResultadoViajes(
                EstadoTelemetria.SIN_CREDENCIAL, motivo="SIN_PROVEEDOR_TELEMETRIA"
            )
        cache = self.repositorio.buscar_viajes(self.proveedor.nombre, patente, desde, hasta)
        if cache is not None:
            return ResultadoViajes(
                EstadoTelemetria.RESULTADO_DESDE_CACHE, tuple(cache),
                motivo="VIAJES_REUTILIZADOS", desde_cache=True,
            )
        resultado = self.proveedor.buscar_viajes(patente, desde, hasta)
        if resultado.estado == EstadoTelemetria.OK:
            self.repositorio.guardar_viajes(
                self.proveedor.nombre, patente, desde, hasta, resultado.viajes
            )
        return resultado

    def obtener_breadcrumbs(self, trip_id: str) -> ResultadoBreadcrumbs:
        if self.proveedor is None:
            return ResultadoBreadcrumbs(
                EstadoTelemetria.SIN_CREDENCIAL, motivo="SIN_PROVEEDOR_TELEMETRIA"
            )
        cache = self.repositorio.buscar_breadcrumbs(self.proveedor.nombre, trip_id)
        if cache is not None:
            return ResultadoBreadcrumbs(
                EstadoTelemetria.RESULTADO_DESDE_CACHE, tuple(cache),
                motivo="BREADCRUMBS_REUTILIZADOS", desde_cache=True,
            )
        resultado = self.proveedor.obtener_breadcrumbs(trip_id)
        if resultado.estado == EstadoTelemetria.OK:
            self.repositorio.guardar_breadcrumbs(
                self.proveedor.nombre, trip_id, resultado.puntos
            )
        return resultado
