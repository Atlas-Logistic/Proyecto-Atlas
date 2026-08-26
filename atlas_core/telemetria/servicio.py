"""Servicio de aplicación de telemetría: cachea sobre cualquier
`ProveedorTelemetria` (Bloque TELEMETRÍA T1, Fase M).

`proveedor=None` es un caso de primera clase (Fase L): cualquier consulta
devuelve `SIN_CREDENCIAL`/sin datos de inmediato, sin tocar red ni caché
-- el resto del pipeline sigue exactamente igual que sin telemetría.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Iterable

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

    def obtener_breadcrumbs_de_varios(self, trip_ids: Iterable[str]) -> dict[str, ResultadoBreadcrumbs]:
        """Bloque PERFORMANCE V1 -- caso real 472339: una ventana de
        origen con varios trips candidatos (ver
        `seleccion_recorrido.recolectar_puntos_ventana_origen`) pedía los
        breadcrumbs de cada uno, uno tras otro -- ningún trip depende del
        resultado de otro, así que el tiempo de PARED terminaba siendo la
        suma de N llamadas de red independientes (~6.5 s medidos para 6
        trips en un caso real).

        Los trips que YA están en caché se resuelven de inmediato (sólo
        lectura, sin red, seguro en paralelo); sólo los que faltan
        disparan la llamada de red real, EN PARALELO. Cada resultado
        nuevo se guarda en la caché uno a la vez, DESPUÉS de que todas
        las llamadas de red terminan -- nunca en paralelo:
        `RepositorioTelemetria` lee-modifica-escribe el archivo completo
        sin lock, dos escrituras simultáneas se pisarían (la última
        ganaría, la anterior se perdería). El resultado final -- qué
        queda cacheado y qué se devuelve por trip -- es idéntico al que
        ya daba llamar `obtener_breadcrumbs` una por una; sólo cambia
        cuándo se espera la red."""
        ids = list(dict.fromkeys(str(trip_id) for trip_id in trip_ids if trip_id))
        if self.proveedor is None:
            return {
                trip_id: ResultadoBreadcrumbs(EstadoTelemetria.SIN_CREDENCIAL, motivo="SIN_PROVEEDOR_TELEMETRIA")
                for trip_id in ids
            }
        resultados: dict[str, ResultadoBreadcrumbs] = {}
        faltantes: list[str] = []
        for trip_id in ids:
            cache = self.repositorio.buscar_breadcrumbs(self.proveedor.nombre, trip_id)
            if cache is not None:
                resultados[trip_id] = ResultadoBreadcrumbs(
                    EstadoTelemetria.RESULTADO_DESDE_CACHE, tuple(cache),
                    motivo="BREADCRUMBS_REUTILIZADOS", desde_cache=True,
                )
            else:
                faltantes.append(trip_id)

        if len(faltantes) == 1:
            # Un solo faltante -- ningún beneficio de un hilo aparte.
            trip_id = faltantes[0]
            resultados[trip_id] = self._pedir_y_guardar_breadcrumbs(trip_id)
        elif faltantes:
            with ThreadPoolExecutor(max_workers=len(faltantes)) as pool:
                crudos = list(pool.map(self.proveedor.obtener_breadcrumbs, faltantes))
            for trip_id, resultado in zip(faltantes, crudos):
                if resultado.estado == EstadoTelemetria.OK:
                    self.repositorio.guardar_breadcrumbs(self.proveedor.nombre, trip_id, resultado.puntos)
                resultados[trip_id] = resultado
        return resultados

    def _pedir_y_guardar_breadcrumbs(self, trip_id: str) -> ResultadoBreadcrumbs:
        resultado = self.proveedor.obtener_breadcrumbs(trip_id)
        if resultado.estado == EstadoTelemetria.OK:
            self.repositorio.guardar_breadcrumbs(self.proveedor.nombre, trip_id, resultado.puntos)
        return resultado
