"""Bloque FIX GPS ORIGEN: CALIDAD ABSOLUTA + GEOCERCA COLINA (simplificado).

Causa raíz real (472224, BDFG50, transporte 0000354527, 20-08-2026):
`resolver_planta_origen_gps` confirmaba AZA RENCA usando un cluster GPS
real pero LEJANO (07:17-07:23, más de 2h antes de la ventana documental
09:52-10:50) porque era el ÚNICO candidato con match de geocerca --
"único candidato" se trataba como sinónimo de "candidato válido", sin
exigir ninguna coherencia temporal mínima con la ventana documental real
(`score=0.0`, `solape_ventana=0.0%`).

Principio (ticket SIMPLIFICAR): evidencia GPS directa e inequívoca
(ventana + solape real) resuelve y termina, sin capas adicionales; una
evidencia sin coherencia temporal con la ventana documental nunca puede
confirmar origen, tenga o no un rival con quien compararse."""
from __future__ import annotations

from datetime import date, datetime

from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.rutas.geocerca import envolvente_convexa
from atlas_core.rutas.modelos import Coordenadas
from atlas_core.telemetria.modelos import PosicionTelemetria, ViajeTelemetria
from atlas_core.telemetria.proveedor import ProveedorTelemetriaSimulado
from atlas_core.telemetria.repositorio import RepositorioTelemetria
from atlas_core.telemetria.seleccion_recorrido import (
    ORIGEN_GPS_CONFIRMADO,
    ORIGEN_GPS_NO_DETERMINADO,
    construir_geocerca_poligonal_multi_vehiculo,
    resolver_planta_origen_gps,
)
from atlas_core.telemetria.servicio import ServicioTelemetria

COORD_AZA_RENCA = Coordenadas(-70.685226, -33.401595)
COORD_AZA_COLINA = Coordenadas(-70.665977, -33.137558)
FECHA = date(2026, 8, 20)


def _plantas(tmp_path):
    catalogo = CatalogoPlantas(tmp_path / "plantas.json")
    renca = catalogo.crear(
        nombre="AZA RENCA", pais="CHILE", fuente="PRUEBA",
        latitud=COORD_AZA_RENCA.latitud, longitud=COORD_AZA_RENCA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    colina = catalogo.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="PRUEBA",
        latitud=COORD_AZA_COLINA.latitud, longitud=COORD_AZA_COLINA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    return catalogo.listar(), renca, colina


def _servicio(tmp_path, viajes_por_patente=None, breadcrumbs_por_trip=None):
    proveedor = ProveedorTelemetriaSimulado(
        viajes_por_patente=viajes_por_patente or {}, breadcrumbs_por_trip=breadcrumbs_por_trip or {},
    )
    return ServicioTelemetria(proveedor, RepositorioTelemetria(tmp_path / "cache.json"))


# ============================================================
# A. Único candidato con score=0/solape=0% -- NO se confirma
#    (caso real 472224: cluster real en RENCA, pero 2h29min antes
#    de que empezara la ventana documental)
# ============================================================


def test_unico_candidato_fuera_de_ventana_no_confirma_origen(tmp_path):
    plantas, _renca, _colina = _plantas(tmp_path)
    servicio = _servicio(
        tmp_path,
        viajes_por_patente={"BDFG50": [
            ViajeTelemetria("A", "BDFG50", "2026-08-20 07:17:27", "2026-08-20 07:23:28", 0.0),
        ]},
        breadcrumbs_por_trip={"A": (
            PosicionTelemetria(COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud, "2026-08-20 07:17:27"),
            PosicionTelemetria(COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud, "2026-08-20 07:23:28"),
        )},
    )
    resultado = resolver_planta_origen_gps(
        servicio, patente="BDFG50", fecha=FECHA,
        hora_entrada=datetime(2026, 8, 20, 9, 52), hora_salida=datetime(2026, 8, 20, 10, 50),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_NO_DETERMINADO
    assert "AZA RENCA" not in resultado.motivo or "solape=0.0%" in resultado.motivo
    assert resultado.planta_nombre == ""


# ============================================================
# B. Único candidato con evidencia fuerte -- SÍ confirma
#    (control -- evidencia directa inequívoca resuelve y termina,
#    sin exigir fuentes redundantes)
# ============================================================


def test_unico_candidato_con_solape_real_confirma_sin_exigir_nada_mas(tmp_path):
    plantas, _renca, _colina = _plantas(tmp_path)
    servicio = _servicio(
        tmp_path,
        viajes_por_patente={"BDFG50": [
            ViajeTelemetria("A", "BDFG50", "2026-08-20 09:55:00", "2026-08-20 10:45:00", 0.0),
        ]},
        breadcrumbs_por_trip={"A": (
            PosicionTelemetria(COORD_AZA_COLINA.latitud, COORD_AZA_COLINA.longitud, "2026-08-20 09:55:00"),
            PosicionTelemetria(COORD_AZA_COLINA.latitud, COORD_AZA_COLINA.longitud, "2026-08-20 10:45:00"),
        )},
    )
    resultado = resolver_planta_origen_gps(
        servicio, patente="BDFG50", fecha=FECHA,
        hora_entrada=datetime(2026, 8, 20, 9, 52), hora_salida=datetime(2026, 8, 20, 10, 50),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_CONFIRMADO
    assert resultado.planta_nombre == "AZA COLINA"


# ============================================================
# C. Cluster contemporáneo (dentro de ventana) vence a cluster
#    antiguo (fuera de ventana), aunque ambos estén dentro de una
#    geocerca real -- reproduce 472224 con las DOS plantas reales.
# ============================================================


def test_cluster_contemporaneo_vence_a_cluster_lejano_aunque_ambos_tengan_geocerca_real(tmp_path):
    plantas, _renca, _colina = _plantas(tmp_path)
    servicio = _servicio(
        tmp_path,
        viajes_por_patente={"BDFG50": [
            ViajeTelemetria("A", "BDFG50", "2026-08-20 07:17:27", "2026-08-20 07:23:28", 0.0),
            ViajeTelemetria("B", "BDFG50", "2026-08-20 09:55:00", "2026-08-20 10:45:00", 0.0),
        ]},
        breadcrumbs_por_trip={
            "A": (
                PosicionTelemetria(COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud, "2026-08-20 07:17:27"),
                PosicionTelemetria(COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud, "2026-08-20 07:23:28"),
            ),
            "B": (
                PosicionTelemetria(COORD_AZA_COLINA.latitud, COORD_AZA_COLINA.longitud, "2026-08-20 09:55:00"),
                PosicionTelemetria(COORD_AZA_COLINA.latitud, COORD_AZA_COLINA.longitud, "2026-08-20 10:45:00"),
            ),
        },
    )
    resultado = resolver_planta_origen_gps(
        servicio, patente="BDFG50", fecha=FECHA,
        hora_entrada=datetime(2026, 8, 20, 9, 52), hora_salida=datetime(2026, 8, 20, 10, 50),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_CONFIRMADO
    assert resultado.planta_nombre == "AZA COLINA"


# ============================================================
# D/E. envolvente_convexa + geocerca multi-vehículo
# ============================================================


def test_envolvente_convexa_de_un_cuadrado():
    puntos = [(-33.0, -70.0), (-33.0, -70.001), (-33.001, -70.0), (-33.001, -70.001), (-33.0005, -70.0005)]
    hull = envolvente_convexa(puntos)
    assert set(hull) == {(-33.0, -70.0), (-33.0, -70.001), (-33.001, -70.0), (-33.001, -70.001)}
    assert (-33.0005, -70.0005) not in hull  # punto interior, nunca vértice


def test_envolvente_convexa_con_menos_de_3_puntos_no_inventa_poligono():
    assert envolvente_convexa([(-33.0, -70.0)]) == ((-33.0, -70.0),)
    assert envolvente_convexa([]) == ()


def test_geocerca_multi_vehiculo_agrega_evidencia_de_varios_vehiculos_distintos(tmp_path):
    plantas, _renca, colina = _plantas(tmp_path)
    servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "AAAA11": [ViajeTelemetria("A", "AAAA11", "2026-08-17 09:00:00", "2026-08-17 10:00:00", 0.0)],
            "BBBB22": [ViajeTelemetria("B", "BBBB22", "2026-08-18 09:00:00", "2026-08-18 10:00:00", 0.0)],
        },
        breadcrumbs_por_trip={
            "A": (
                PosicionTelemetria(COORD_AZA_COLINA.latitud, COORD_AZA_COLINA.longitud, "2026-08-17 09:00:00"),
                PosicionTelemetria(COORD_AZA_COLINA.latitud + 0.0005, COORD_AZA_COLINA.longitud, "2026-08-17 10:00:00"),
            ),
            "B": (
                PosicionTelemetria(COORD_AZA_COLINA.latitud, COORD_AZA_COLINA.longitud - 0.0005, "2026-08-18 09:00:00"),
                PosicionTelemetria(COORD_AZA_COLINA.latitud, COORD_AZA_COLINA.longitud, "2026-08-18 10:00:00"),
            ),
        },
    )
    vertices = construir_geocerca_poligonal_multi_vehiculo(
        casos=(
            ("AAAA11", date(2026, 8, 17), datetime(2026, 8, 17, 9, 0), datetime(2026, 8, 17, 10, 0)),
            ("BBBB22", date(2026, 8, 18), datetime(2026, 8, 18, 9, 0), datetime(2026, 8, 18, 10, 0)),
        ),
        servicio=servicio, plantas=plantas, planta_id=colina.planta_id,
    )
    assert len(vertices) >= 3  # evidencia real de 2 vehículos -- nunca un polígono vacío
    # Ningún vértice puede venir de un vehículo/fecha que nunca se consultó.
    for lat, lon in vertices:
        assert abs(lat - COORD_AZA_COLINA.latitud) < 0.01
        assert abs(lon - COORD_AZA_COLINA.longitud) < 0.01


def test_geocerca_multi_vehiculo_sin_casos_ni_evidencia_no_inventa_vertices(tmp_path):
    plantas, _renca, colina = _plantas(tmp_path)
    servicio = _servicio(tmp_path)
    assert construir_geocerca_poligonal_multi_vehiculo(
        casos=(), servicio=servicio, plantas=plantas, planta_id=colina.planta_id,
    ) == ()
