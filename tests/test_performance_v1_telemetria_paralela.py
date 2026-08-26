"""Bloque PERFORMANCE V1 -- caso real 472339: la ventana de origen GPS
encontró 6 trips candidatos (`VENTANA_DOCUMENTAL;...;trips=6 ids`) y
pedía sus breadcrumbs a Onelogis uno tras otro -- cada trip es
independiente de los demás (ningún trip depende del breadcrumb de otro),
así que el tiempo de PARED terminaba siendo la suma de N llamadas de red
(~6.5 s medidos en una corrida real). `ServicioTelemetria.
obtener_breadcrumbs_de_varios` resuelve primero los que ya están en
caché (sin red), pide en PARALELO sólo los que faltan, y escribe la
caché de a uno DESPUÉS -- `RepositorioTelemetria` no soporta escritura
concurrente (lee-modifica-escribe el archivo completo sin lock)."""
from __future__ import annotations

import time

from atlas_core.telemetria.modelos import EstadoTelemetria, PosicionTelemetria, ResultadoBreadcrumbs
from atlas_core.telemetria.repositorio import RepositorioTelemetria
from atlas_core.telemetria.servicio import ServicioTelemetria


class _ProveedorConLatencia:
    """Doble determinista que DUERME (reloj real, nunca mockeado) una
    latencia fija por llamada -- mismo criterio que
    `_OrquestadorConLatenciaReal` del bloque de B1."""

    nombre = "onelogis"

    def __init__(self, *, latencia: float = 0.05) -> None:
        self._latencia = latencia
        self.trip_ids_pedidos: list[str] = []

    def buscar_viajes(self, patente, desde, hasta):
        raise NotImplementedError

    def obtener_breadcrumbs(self, trip_id: str) -> ResultadoBreadcrumbs:
        self.trip_ids_pedidos.append(trip_id)
        time.sleep(self._latencia)
        return ResultadoBreadcrumbs(
            EstadoTelemetria.OK, (PosicionTelemetria(latitud=-33.4, longitud=-70.6, timestamp=f"t-{trip_id}"),),
        )


def test_varios_trips_faltantes_se_piden_en_paralelo_no_secuencial(tmp_path):
    proveedor = _ProveedorConLatencia(latencia=0.3)
    servicio = ServicioTelemetria(proveedor, RepositorioTelemetria(tmp_path / "telemetria_cache.json"))

    inicio = time.perf_counter()
    resultados = servicio.obtener_breadcrumbs_de_varios(["T-1", "T-2", "T-3"])
    pared = time.perf_counter() - inicio

    assert set(resultados) == {"T-1", "T-2", "T-3"}
    assert all(r.estado == EstadoTelemetria.OK for r in resultados.values())
    # 3 llamadas secuenciales serían ~0.9s; en paralelo, ~0.3s. Margen
    # generoso para CI lento, pero estrictamente por debajo de la suma.
    assert pared < 0.75, f"tiempo de pared {pared:.3f}s -- se esperaba paralelo (~0.3s), no secuencial (~0.9s)"


def test_trips_ya_en_cache_nunca_vuelven_a_pedirse_a_la_red(tmp_path):
    repositorio = RepositorioTelemetria(tmp_path / "telemetria_cache.json")
    repositorio.guardar_breadcrumbs("onelogis", "T-1", (PosicionTelemetria(latitud=-33.0, longitud=-70.0),))
    proveedor = _ProveedorConLatencia(latencia=0.01)
    servicio = ServicioTelemetria(proveedor, repositorio)

    resultados = servicio.obtener_breadcrumbs_de_varios(["T-1", "T-2"])

    assert proveedor.trip_ids_pedidos == ["T-2"]  # T-1 nunca golpea la red
    assert resultados["T-1"].desde_cache is True
    assert resultados["T-2"].estado == EstadoTelemetria.OK


def test_resultado_y_cache_final_son_identicos_a_pedir_uno_por_uno(tmp_path):
    """La paralelización sólo cambia CUÁNDO se espera la red -- nunca qué
    queda guardado en caché ni qué se devuelve por trip. Compara el
    resultado de `obtener_breadcrumbs_de_varios` contra llamar
    `obtener_breadcrumbs` uno por uno (versión de control, sin
    paralelismo) sobre cachés separadas pero idénticas al inicio."""
    proveedor_a = _ProveedorConLatencia(latencia=0.0)
    servicio_a = ServicioTelemetria(proveedor_a, RepositorioTelemetria(tmp_path / "a.json"))
    proveedor_b = _ProveedorConLatencia(latencia=0.0)
    servicio_b = ServicioTelemetria(proveedor_b, RepositorioTelemetria(tmp_path / "b.json"))

    trip_ids = ["T-1", "T-2", "T-3"]
    resultados_paralelo = servicio_a.obtener_breadcrumbs_de_varios(trip_ids)
    resultados_secuencial = {trip_id: servicio_b.obtener_breadcrumbs(trip_id) for trip_id in trip_ids}

    for trip_id in trip_ids:
        assert resultados_paralelo[trip_id].estado == resultados_secuencial[trip_id].estado
        assert resultados_paralelo[trip_id].puntos == resultados_secuencial[trip_id].puntos
    # Ambas cachés terminan con exactamente los mismos 3 trips guardados.
    assert servicio_a.repositorio.buscar_breadcrumbs("onelogis", "T-2") == \
        servicio_b.repositorio.buscar_breadcrumbs("onelogis", "T-2")


def test_sin_proveedor_se_abstiene_para_todos_sin_tocar_cache_ni_red(tmp_path):
    servicio = ServicioTelemetria(None, RepositorioTelemetria(tmp_path / "telemetria_cache.json"))
    resultados = servicio.obtener_breadcrumbs_de_varios(["T-1", "T-2"])
    assert all(r.estado == EstadoTelemetria.SIN_CREDENCIAL for r in resultados.values())
