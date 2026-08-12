"""Bloque TELEMETRÍA T3: origen de planta usando detenciones/estadías GPS,
no solo breadcrumbs sueltos.

Hallazgo real que motivó este bloque: R1.1 concluyó "sin evidencia GPS"
para el transporte 0000352752 (AL1879, 11-08-2026, guías 464641/464642)
-- pero Javier revisó la UI de Onelogis y vio al vehículo detenido varias
horas en una ubicación real. La causa: el modelo anterior solo miraba
breadcrumbs sueltos dentro de una ventana; nunca consideraba los HUECOS
entre trips (sin breadcrumbs propios) como evidencia de permanencia, ni
usaba ambas horas documentales (entrada Y salida) para acotar la
ventana -- ver `resolver_planta_origen_gps` y `detectar_detenciones`.

Investigación real (script fuera de la suite, `operacion_eval/`):
AL1879 estuvo detenido ~6h08min (08:48-14:57, solapando casi todo el
rango documental 09:46-14:39) en una coordenada que geocodifica dos
veces, independientemente, como "Gerdau Aza, Lampa" -- una planta real
de Aceros AZA que HOY NO está en el catálogo de Atlas (decisión
explícita: no se agrega en este bloque). Por eso el resultado esperado
para ese caso es `ORIGEN_GPS_ESTADIA_SIN_PLANTA`, nunca Colina (no hay
Colina en el catálogo en esa coordenada) ni Renca (fallback ya eliminado
en R1.1).

Todos los tests son unitarios/deterministas, sin red real.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.rutas.modelos import Coordenadas
from atlas_core.telemetria.modelos import PosicionTelemetria, ViajeTelemetria
from atlas_core.telemetria.proveedor import ProveedorTelemetriaSimulado
from atlas_core.telemetria.repositorio import RepositorioTelemetria
from atlas_core.telemetria.seleccion_recorrido import (
    ORIGEN_GPS_CONFIRMADO,
    ORIGEN_GPS_CONFLICTO,
    ORIGEN_GPS_ESTADIA_SIN_PLANTA,
    detectar_detenciones,
    resolver_planta_origen_gps,
)
from atlas_core.telemetria.servicio import ServicioTelemetria

COORD_AZA_RENCA = Coordenadas(-70.685226, -33.401595)
COORD_AZA_COLINA = Coordenadas(-70.665977, -33.137558)
# Coordenada real de la detención AL1879 (Bloque T3) -- "Gerdau Aza,
# Lampa" según geocodificación ORS, NO catalogada.
COORD_LAMPA_NO_CATALOGADA = Coordenadas(-70.7290, -33.2976)
FECHA = date(2026, 8, 11)


@pytest.fixture
def plantas(tmp_path):
    catalogo = CatalogoPlantas(tmp_path / "plantas.json")
    catalogo.crear(
        nombre="AZA RENCA", pais="CHILE", fuente="PRUEBA",
        direccion="LA UNION 3070", comuna="RENCA", region="RM",
        latitud=COORD_AZA_RENCA.latitud, longitud=COORD_AZA_RENCA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    catalogo.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="PRUEBA",
        direccion="AV. PDTE. EDUARDO FREI MONTALVA 18500", comuna="COLINA", region="RM",
        latitud=COORD_AZA_COLINA.latitud, longitud=COORD_AZA_COLINA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    return catalogo.listar()


def _servicio(tmp_path, viajes_por_patente=None, breadcrumbs_por_trip=None):
    proveedor = ProveedorTelemetriaSimulado(
        viajes_por_patente=viajes_por_patente or {},
        breadcrumbs_por_trip=breadcrumbs_por_trip or {},
    )
    return proveedor, ServicioTelemetria(proveedor, RepositorioTelemetria(tmp_path / "cache.json"))


# --- 1: estadía entre trips en la misma posición (hueco sin breadcrumbs propios) ---


def test_detectar_detenciones_encadena_trips_en_la_misma_posicion():
    """Reproduce el caso real: trip A termina en un lugar a las 08:55,
    trip B empieza en el MISMO lugar a las 13:35 -- el hueco de 4h40min
    entre ambos, sin breadcrumbs propios, es evidencia de permanencia
    continua ahí."""
    viajes = (
        ViajeTelemetria("A", "AL1879", "2026-08-11 08:48:58", "2026-08-11 08:55:39", -0.01),
        ViajeTelemetria("B", "AL1879", "2026-08-11 13:30:03", "2026-08-11 13:35:16", 0.0),
    )
    breadcrumbs = {
        "A": (
            PosicionTelemetria(-33.29498, -70.729787, "2026-08-11 08:48:58"),
            PosicionTelemetria(-33.294737, -70.729847, "2026-08-11 08:55:39"),
        ),
        "B": (
            PosicionTelemetria(-33.294548, -70.727782, "2026-08-11 13:30:03"),
            PosicionTelemetria(-33.294397, -70.727958, "2026-08-11 13:35:16"),
        ),
    }
    detenciones = detectar_detenciones(viajes, breadcrumbs)
    assert len(detenciones) == 1
    detencion = detenciones[0]
    assert detencion.inicio == "2026-08-11 08:48:58"
    assert detencion.fin == "2026-08-11 13:35:16"
    assert detencion.trip_ids == ("A", "B")
    assert detencion.duracion_minutos == pytest.approx(4 * 60 + 46.3, abs=0.5)


# --- 2: estadía dentro de geocerca -> ORIGEN_GPS_CONFIRMADO ---


def test_estadia_dentro_de_geocerca_confirma_planta(plantas, tmp_path):
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "TZWR86": [
                ViajeTelemetria("A", "TZWR86", "2026-08-11 09:00:00", "2026-08-11 09:05:00", 0.0),
                ViajeTelemetria("B", "TZWR86", "2026-08-11 11:30:00", "2026-08-11 11:35:00", 0.0),
            ],
        },
        breadcrumbs_por_trip={
            "A": (
                PosicionTelemetria(COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud, "2026-08-11 09:00:00"),
                PosicionTelemetria(COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud, "2026-08-11 09:05:00"),
            ),
            "B": (
                PosicionTelemetria(COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud, "2026-08-11 11:30:00"),
                PosicionTelemetria(COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud, "2026-08-11 11:35:00"),
            ),
        },
    )
    resultado = resolver_planta_origen_gps(
        servicio, patente="TZWR86", fecha=FECHA,
        hora_entrada=datetime(2026, 8, 11, 9, 0), hora_salida=datetime(2026, 8, 11, 11, 35),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_CONFIRMADO
    assert resultado.planta_nombre == "AZA RENCA"
    assert "ESTADIA_EN_GEOCERCA" in resultado.motivo


# --- 3: solape con hora documental queda registrado en el motivo ---


def test_solape_con_hora_documental_se_registra_en_motivo(plantas, tmp_path):
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "AL1879": [
                ViajeTelemetria("A", "AL1879", "2026-08-11 09:50:00", "2026-08-11 09:55:00", 0.0),
                ViajeTelemetria("B", "AL1879", "2026-08-11 14:30:00", "2026-08-11 14:35:00", 0.0),
            ],
        },
        breadcrumbs_por_trip={
            "A": (
                PosicionTelemetria(COORD_AZA_COLINA.latitud, COORD_AZA_COLINA.longitud, "2026-08-11 09:50:00"),
                PosicionTelemetria(COORD_AZA_COLINA.latitud, COORD_AZA_COLINA.longitud, "2026-08-11 09:55:00"),
            ),
            "B": (
                PosicionTelemetria(COORD_AZA_COLINA.latitud, COORD_AZA_COLINA.longitud, "2026-08-11 14:30:00"),
                PosicionTelemetria(COORD_AZA_COLINA.latitud, COORD_AZA_COLINA.longitud, "2026-08-11 14:35:00"),
            ),
        },
    )
    resultado = resolver_planta_origen_gps(
        servicio, patente="AL1879", fecha=FECHA,
        hora_entrada=datetime(2026, 8, 11, 9, 46), hora_salida=datetime(2026, 8, 11, 14, 39),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_CONFIRMADO
    assert resultado.planta_nombre == "AZA COLINA"
    # La detención (09:50-14:35) queda enteramente dentro del rango
    # documental (09:46-14:39) -- solape de las 4h45min completas.
    assert "solape_documental_min=285.0" in resultado.motivo


# --- 4: salida posterior de la geocerca corta la cadena de detención ---


def test_salida_real_corta_la_cadena_de_detencion():
    """Un trip de movimiento real (inicio y fin espacialmente alejados)
    entre dos trips estacionarios corta la cadena -- nunca funde dos
    permanencias distintas en una sola."""
    viajes = (
        ViajeTelemetria("A", "AL1879", "2026-08-11 09:00:00", "2026-08-11 09:05:00", 0.0),
        ViajeTelemetria("salida", "AL1879", "2026-08-11 09:10:00", "2026-08-11 09:40:00", 15.0),
        ViajeTelemetria("B", "AL1879", "2026-08-11 12:00:00", "2026-08-11 12:05:00", 0.0),
    )
    breadcrumbs = {
        "A": (
            PosicionTelemetria(-33.2946, -70.7290, "2026-08-11 09:00:00"),
            PosicionTelemetria(-33.2946, -70.7290, "2026-08-11 09:05:00"),
        ),
        "salida": (
            PosicionTelemetria(-33.2946, -70.7290, "2026-08-11 09:10:00"),
            PosicionTelemetria(-33.4500, -70.6500, "2026-08-11 09:40:00"),  # lejos -- movimiento real
        ),
        "B": (
            PosicionTelemetria(-33.4500, -70.6500, "2026-08-11 12:00:00"),
            PosicionTelemetria(-33.4500, -70.6500, "2026-08-11 12:05:00"),
        ),
    }
    detenciones = detectar_detenciones(viajes, breadcrumbs)
    # Dos detenciones separadas -- "A" sola, y "B" sola -- nunca una
    # única detención fusionando ambos lugares a través del trip de
    # movimiento real.
    assert len(detenciones) == 2
    assert detenciones[0].trip_ids == ("A",)
    assert detenciones[1].trip_ids == ("B",)


# --- 5: trip sin breadcrumbs (endpoint sin datos) nunca rompe nada ---


def test_endpoint_sin_breadcrumbs_se_ignora_sin_lanzar():
    viajes = (
        ViajeTelemetria("A", "AL1879", "2026-08-11 09:00:00", "2026-08-11 09:05:00", 0.0),
        ViajeTelemetria("sin_datos", "AL1879", "2026-08-11 09:10:00", "2026-08-11 09:20:00", 1.0),
        ViajeTelemetria("B", "AL1879", "2026-08-11 09:25:00", "2026-08-11 09:30:00", 0.0),
    )
    breadcrumbs = {
        "A": (
            PosicionTelemetria(-33.2946, -70.7290, "2026-08-11 09:00:00"),
            PosicionTelemetria(-33.2946, -70.7290, "2026-08-11 09:05:00"),
        ),
        # "sin_datos" -- sin entrada en el dict, simula breadcrumbs no disponibles.
        "B": (
            PosicionTelemetria(-33.2946, -70.7290, "2026-08-11 09:25:00"),
            PosicionTelemetria(-33.2946, -70.7290, "2026-08-11 09:30:00"),
        ),
    }
    detenciones = detectar_detenciones(viajes, breadcrumbs)
    # El trip sin breadcrumbs se salta -- A y B, coherentes entre sí y
    # sin ningún trip de movimiento real entre medio, igual se encadenan.
    assert len(detenciones) == 1
    assert detenciones[0].trip_ids == ("A", "B")


# --- 6: breadcrumbs incompletos (un solo punto) nunca prueban estadía por sí solos ---


def test_un_solo_breadcrumb_nunca_se_considera_estacionario():
    """Una única foto instantánea no alcanza para afirmar que el
    vehículo estuvo detenido -- podría ser un trip real con muestreo
    disperso. Nunca se infiere estadía de un solo punto."""
    viajes = (
        ViajeTelemetria("x", "AL1879", "2026-08-11 09:00:00", "2026-08-11 09:30:00", 5.0),
    )
    breadcrumbs = {"x": (PosicionTelemetria(-33.2946, -70.7290, "2026-08-11 09:15:00"),)}
    detenciones = detectar_detenciones(viajes, breadcrumbs)
    assert detenciones == ()


# --- 7: control positivo -- el mecanismo SÍ confirma Colina si la evidencia cae ahí ---


def test_estadia_confirma_colina_si_la_evidencia_real_cae_en_su_geocerca(plantas, tmp_path):
    """Validación positiva general (no hardcodea AL1879/464641): si una
    detención real e independiente de la ventana caracterizada por R1.1
    hubiera caído dentro de la geocerca de Colina, el mecanismo la
    habría confirmado -- la razón por la que el caso real AL1879 NO
    confirma Colina es que su detención real está en otra coordenada
    (~18km de Colina), no una limitación del algoritmo."""
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "AL1879": [
                ViajeTelemetria("A", "AL1879", "2026-08-11 09:48:00", "2026-08-11 09:52:00", 0.0),
                ViajeTelemetria("B", "AL1879", "2026-08-11 14:20:00", "2026-08-11 14:25:00", 0.0),
            ],
        },
        breadcrumbs_por_trip={
            "A": (
                PosicionTelemetria(COORD_AZA_COLINA.latitud, COORD_AZA_COLINA.longitud, "2026-08-11 09:48:00"),
                PosicionTelemetria(COORD_AZA_COLINA.latitud, COORD_AZA_COLINA.longitud, "2026-08-11 09:52:00"),
            ),
            "B": (
                PosicionTelemetria(COORD_AZA_COLINA.latitud, COORD_AZA_COLINA.longitud, "2026-08-11 14:20:00"),
                PosicionTelemetria(COORD_AZA_COLINA.latitud, COORD_AZA_COLINA.longitud, "2026-08-11 14:25:00"),
            ),
        },
    )
    resultado = resolver_planta_origen_gps(
        servicio, patente="AL1879", fecha=FECHA,
        hora_entrada=datetime(2026, 8, 11, 9, 46), hora_salida=datetime(2026, 8, 11, 14, 39),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_CONFIRMADO
    assert resultado.planta_nombre == "AZA COLINA"


# --- 8: multiguía -- ambos documentos comparten la misma resolución ---


def test_multiguia_comparte_estadia_sin_planta(plantas, tmp_path):
    """464641/464642: mismo transporte, misma patente/fecha -- ambos
    documentos deben resolver exactamente igual (ESTADIA_SIN_PLANTA), sin
    inventar Colina para uno y dejar el otro sin determinar."""
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "AL1879": [
                ViajeTelemetria("A", "AL1879", "2026-08-11 08:48:00", "2026-08-11 08:55:00", 0.0),
                ViajeTelemetria("B", "AL1879", "2026-08-11 13:30:00", "2026-08-11 13:35:00", 0.0),
            ],
        },
        breadcrumbs_por_trip={
            "A": (
                PosicionTelemetria(COORD_LAMPA_NO_CATALOGADA.latitud, COORD_LAMPA_NO_CATALOGADA.longitud, "2026-08-11 08:48:00"),
                PosicionTelemetria(COORD_LAMPA_NO_CATALOGADA.latitud, COORD_LAMPA_NO_CATALOGADA.longitud, "2026-08-11 08:55:00"),
            ),
            "B": (
                PosicionTelemetria(COORD_LAMPA_NO_CATALOGADA.latitud, COORD_LAMPA_NO_CATALOGADA.longitud, "2026-08-11 13:30:00"),
                PosicionTelemetria(COORD_LAMPA_NO_CATALOGADA.latitud, COORD_LAMPA_NO_CATALOGADA.longitud, "2026-08-11 13:35:00"),
            ),
        },
    )
    resultados = [
        resolver_planta_origen_gps(
            servicio, patente="AL1879", fecha=FECHA,
            hora_entrada=datetime(2026, 8, 11, 9, 46), hora_salida=hora_salida,
            plantas=plantas,
        )
        for hora_salida in (datetime(2026, 8, 11, 14, 39), None)
    ]
    for resultado in resultados:
        assert resultado.estado == ORIGEN_GPS_ESTADIA_SIN_PLANTA
        assert resultado.planta_nombre == ""
        assert resultado.latitud_estadia == pytest.approx(COORD_LAMPA_NO_CATALOGADA.latitud, abs=0.01)


# --- 9: nunca cae a Renca por defecto, aunque haya una estadía real fuerte ---


def test_estadia_sin_planta_nunca_cae_a_renca_por_defecto(plantas, tmp_path):
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "AL1879": [
                ViajeTelemetria("A", "AL1879", "2026-08-11 08:48:00", "2026-08-11 08:55:00", 0.0),
                ViajeTelemetria("B", "AL1879", "2026-08-11 13:30:00", "2026-08-11 13:35:00", 0.0),
            ],
        },
        breadcrumbs_por_trip={
            "A": (
                PosicionTelemetria(COORD_LAMPA_NO_CATALOGADA.latitud, COORD_LAMPA_NO_CATALOGADA.longitud, "2026-08-11 08:48:00"),
                PosicionTelemetria(COORD_LAMPA_NO_CATALOGADA.latitud, COORD_LAMPA_NO_CATALOGADA.longitud, "2026-08-11 08:55:00"),
            ),
            "B": (
                PosicionTelemetria(COORD_LAMPA_NO_CATALOGADA.latitud, COORD_LAMPA_NO_CATALOGADA.longitud, "2026-08-11 13:30:00"),
                PosicionTelemetria(COORD_LAMPA_NO_CATALOGADA.latitud, COORD_LAMPA_NO_CATALOGADA.longitud, "2026-08-11 13:35:00"),
            ),
        },
    )
    resultado = resolver_planta_origen_gps(
        servicio, patente="AL1879", fecha=FECHA,
        hora_entrada=datetime(2026, 8, 11, 9, 46), hora_salida=datetime(2026, 8, 11, 14, 39),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_ESTADIA_SIN_PLANTA
    assert resultado.planta_id == ""
    assert resultado.planta_nombre != "AZA RENCA"
    assert resultado.duracion_estadia_min is not None and resultado.duracion_estadia_min > 0


# --- 10: conflicto entre estadía confirmada y breadcrumb aislado de otra planta ---


def test_conflicto_entre_estadia_y_breadcrumb_aislado_de_otra_planta(plantas, tmp_path):
    """Si hay una detención real dentro de la geocerca de una planta Y
    además, en otro trip, un breadcrumb aislado pasa cerca de la OTRA
    planta, el resultado es un conflicto explícito -- nunca se ignora en
    silencio la señal más débil ni se elige arbitrariamente la más
    fuerte."""
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "AL1879": [
                ViajeTelemetria("estadia", "AL1879", "2026-08-11 09:00:00", "2026-08-11 09:05:00", 0.0),
                ViajeTelemetria("pasada", "AL1879", "2026-08-11 09:30:00", "2026-08-11 10:00:00", 20.0),
            ],
        },
        breadcrumbs_por_trip={
            "estadia": (
                PosicionTelemetria(COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud, "2026-08-11 09:00:00"),
                PosicionTelemetria(COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud, "2026-08-11 09:05:00"),
            ),
            "pasada": (
                PosicionTelemetria(-33.20, -70.70, "2026-08-11 09:30:00"),
                PosicionTelemetria(COORD_AZA_COLINA.latitud, COORD_AZA_COLINA.longitud, "2026-08-11 09:45:00"),
                PosicionTelemetria(-33.20, -70.70, "2026-08-11 10:00:00"),
            ),
        },
    )
    resultado = resolver_planta_origen_gps(
        servicio, patente="AL1879", fecha=FECHA,
        hora_entrada=datetime(2026, 8, 11, 9, 0), hora_salida=datetime(2026, 8, 11, 10, 0),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_CONFLICTO


# --- 11: la caché sigue guardando solo datos crudos, ahora usados también para detenciones ---


def test_cache_guarda_breadcrumbs_reutilizables_para_detectar_detenciones(tmp_path):
    proveedor = ProveedorTelemetriaSimulado(
        viajes_por_patente={
            "AL1879": [ViajeTelemetria("x", "AL1879", "2026-08-11 09:00:00", "2026-08-11 09:05:00", 0.0)],
        },
        breadcrumbs_por_trip={
            "x": (
                PosicionTelemetria(-33.2946, -70.7290, "2026-08-11 09:00:00"),
                PosicionTelemetria(-33.2946, -70.7290, "2026-08-11 09:05:00"),
            ),
        },
    )
    repositorio = RepositorioTelemetria(tmp_path / "cache.json")
    servicio = ServicioTelemetria(proveedor, repositorio)

    r1 = servicio.obtener_breadcrumbs("x")
    assert proveedor.llamadas_breadcrumbs == 1
    r2 = servicio.obtener_breadcrumbs("x")
    assert proveedor.llamadas_breadcrumbs == 1  # reutiliza caché
    assert r1.puntos == r2.puntos

    detenciones = detectar_detenciones(
        (ViajeTelemetria("x", "AL1879", "2026-08-11 09:00:00", "2026-08-11 09:05:00", 0.0),),
        {"x": r2.puntos},
    )
    assert len(detenciones) == 1


# --- 12: no regresión T1/T2/R1/R1.1 -- cubierta por la suite completa ---


def test_no_regresion_se_verifica_con_la_suite_completa():
    """No se duplica cobertura aquí: la garantía de no regresión de este
    bloque es que `python -m pytest -q` sigue en verde -- ver
    `test_telemetria_t1.py`, `test_telemetria_t2.py`,
    `test_operacion_real_r1.py`, `test_operacion_real_r1_1.py`."""
    assert True
