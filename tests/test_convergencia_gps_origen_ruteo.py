"""Convergencia GPS histórica: la ruta parte del punto de ruteo de la planta.

Caso real AZA COLINA (diagnóstico pruebas/distancias-20261027): su
latitud/longitud es la geocodificación del texto de la dirección y queda a
18,5 km del recinto operacional (`punto_ruteo_*`). Las demás vías de ruteo
ya usaban `coordenada_ruteo_planta`; esta vía usaba la coordenada textual y
calculó 30,13 km para La Estera 525 en vez de 7,00 km.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.revalidacion_documental import revalidar_ruta_por_convergencia_gps_historica_sin_ocr
from atlas_core.rutas.modelos import Coordenadas, EstadoRuta, ResultadoRuta
from atlas_core.rutas.proveedor import ProveedorRutasSimulado
from atlas_core.telemetria.proveedor import ProveedorTelemetriaSoloCache
from atlas_core.telemetria.repositorio import RepositorioTelemetria
from atlas_core.telemetria.servicio import ServicioTelemetria
from tests.test_final_core_v1 import COORD_AUSIN, _cachear_trip_con_destino, _escribir_csv, _fila_csv, _leer_csv

TEXTUAL = Coordenadas(-70.665977, -33.137558)
RUTEO = Coordenadas(-70.730387, -33.294752)


@dataclass
class _ProveedorQueRegistraOrigen(ProveedorRutasSimulado):
    origenes: list = field(default_factory=list)

    def calcular_ruta(self, origen, destino, perfil):
        self.origenes.append(origen)
        return super().calcular_ruta(origen, destino, perfil)


def _ejecutar(tmp_path, **punto_ruteo):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir()
    planta = CatalogoPlantas(carpeta / "plantas.json").crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST", direccion="AV PDTE EDUARDO FREI MONTALVA 18500",
        comuna="COLINA", region="RM", latitud=TEXTUAL.latitud, longitud=TEXTUAL.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA, **punto_ruteo,
    )
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [
        _fila_csv(numero_guia="1", fecha="18-08-2026", planta_origen_id=planta.planta_id, planta_origen_nombre="AZA COLINA"),
        _fila_csv(archivo="2.jpeg", numero_guia="2", fecha="19-08-2026",
                  planta_origen_id=planta.planta_id, planta_origen_nombre="AZA COLINA"),
    ])
    repo = RepositorioTelemetria(carpeta / "telemetria_cache.json")
    for dia in (18, 19):
        _cachear_trip_con_destino(repo, patente="AL1879", fecha_iso=date(2026, 8, dia),
                                  fecha_doc=f"2026-08-{dia}", punto_destino=COORD_AUSIN)
    proveedor = _ProveedorQueRegistraOrigen(resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 7.0, 12.0, "SINTETICO"))
    resultado = revalidar_ruta_por_convergencia_gps_historica_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=proveedor,
        servicio_telemetria=ServicioTelemetria(ProveedorTelemetriaSoloCache(nombre="onelogis"), repo),
    )
    return resultado, proveedor, {f["numero_guia"]: f for f in _leer_csv(dataset)}


def test_ruta_parte_del_punto_de_ruteo_y_no_de_la_coordenada_textual(tmp_path):
    resultado, proveedor, filas = _ejecutar(
        tmp_path, punto_ruteo_latitud=RUTEO.latitud, punto_ruteo_longitud=RUTEO.longitud,
    )
    assert set(resultado["guias_actualizadas"]) == {"1", "2"}
    assert proveedor.origenes == [RUTEO, RUTEO]
    assert TEXTUAL not in proveedor.origenes
    assert filas["1"]["distancia_km"] == "7.0"


def test_planta_sin_punto_de_ruteo_conserva_su_coordenada(tmp_path):
    resultado, proveedor, _ = _ejecutar(tmp_path)
    assert set(resultado["guias_actualizadas"]) == {"1", "2"}
    assert proveedor.origenes == [TEXTUAL, TEXTUAL]
