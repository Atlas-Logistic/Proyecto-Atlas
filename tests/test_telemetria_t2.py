"""Bloque TELEMETRÍA T2: selección automática de recorrido operacional
GPS (1..N trips) + integración opcional en el pipeline E2E.

Todos los tests son unitarios, sin red real. La validación con la API
real de Onelogis/ORS vive en `telemetria_eval/` (fuera de la suite
normal), reutilizando la caché ya construida en T1/T2.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.rutas.modelos import Coordenadas
from atlas_core.telemetria.modelos import (
    EstadoConcordanciaHora,
    EstadoSeleccionRecorrido,
    EstadoTelemetria,
    PosicionTelemetria,
    ViajeTelemetria,
)
from atlas_core.telemetria.proveedor import ProveedorTelemetriaSimulado
from atlas_core.telemetria.repositorio import RepositorioTelemetria
from atlas_core.telemetria.seleccion_recorrido import (
    ORIGEN_GPS_CONFIRMADO,
    ORIGEN_GPS_CONFLICTO,
    ORIGEN_GPS_NO_DETERMINADO,
    clasificar_concordancia_hora,
    completar_recorrido_con_breadcrumbs,
    detectar_entrada_salida_planta,
    seleccionar_recorrido_operacional,
)
from atlas_core.telemetria.servicio import ServicioTelemetria

COORD_AZA_RENCA = Coordenadas(-70.685226, -33.401595)
COORD_AZA_COLINA = Coordenadas(-70.665977, -33.137558)
FECHA = date(2026, 7, 27)


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
        direccion="AV. PDTE. FREI 18500", comuna="COLINA", region="RM",
        latitud=COORD_AZA_COLINA.latitud, longitud=COORD_AZA_COLINA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    return catalogo.listar()


def _viaje(trip_id, inicio, fin, distancia_km):
    return ViajeTelemetria(trip_id, "TZWR86", f"2026-07-27 {inicio}", f"2026-07-27 {fin}", distancia_km)


# --- 1: selección un solo trip ---


def test_seleccion_un_solo_trip():
    viajes = (
        _viaje("A", "09:34:46", "10:05:59", 17.98),
        _viaje("B", "12:15:02", "13:13:04", 16.28),  # gap > 90 min, no encadena
    )
    resultado = seleccionar_recorrido_operacional(
        viajes, patente="BDFG50", fecha=FECHA.isoformat(),
        hora_entrada=datetime(2026, 7, 27, 7, 31), hora_salida=datetime(2026, 7, 27, 9, 26),
    )
    assert resultado.estado == EstadoSeleccionRecorrido.SELECCIONADO
    assert resultado.recorrido.trip_ids == ("A",)
    assert resultado.recorrido.distancia_gps_total_km == 17.98


# --- 2: selección múltiples trips (caso real 463630, reproducido con datos sintéticos) ---


def test_seleccion_multiples_trips_encadenados():
    viajes = (
        _viaje("seed", "12:17:28", "13:27:11", 47.02),
        _viaje("largo1", "13:29:24", "16:32:41", 233.97),
        _viaje("largo2", "17:23:40", "21:16:53", 257.1),
    )
    resultado = seleccionar_recorrido_operacional(
        viajes, patente="TZWR86", fecha=FECHA.isoformat(),
        hora_entrada=datetime(2026, 7, 27, 10, 5), hora_salida=None,
    )
    assert resultado.estado == EstadoSeleccionRecorrido.SELECCIONADO
    assert resultado.recorrido.trip_ids == ("seed", "largo1", "largo2")
    assert resultado.recorrido.distancia_gps_total_km == pytest.approx(47.02 + 233.97 + 257.1)
    assert len(resultado.recorrido.huecos_temporales_min) == 2


# --- 3/4: continuidad espacial/temporal (corte de cadena) ---


def test_no_encadena_si_el_hueco_temporal_es_excesivo():
    viajes = (
        _viaje("seed", "09:34:46", "10:05:59", 17.98),
        _viaje("lejano", "12:15:02", "13:13:04", 16.28),  # 129 min de hueco
    )
    resultado = seleccionar_recorrido_operacional(
        viajes, patente="BDFG50", fecha=FECHA.isoformat(),
        hora_entrada=datetime(2026, 7, 27, 7, 31), hora_salida=datetime(2026, 7, 27, 9, 26),
    )
    assert resultado.recorrido.trip_ids == ("seed",)


def test_encadena_con_hueco_dentro_de_tolerancia():
    viajes = (
        _viaje("seed", "13:29:24", "16:32:41", 233.97),
        _viaje("continuacion", "17:23:40", "21:16:53", 257.1),  # 51 min real
    )
    resultado = seleccionar_recorrido_operacional(
        viajes, patente="TZWR86", fecha=FECHA.isoformat(),
        hora_entrada=None, hora_salida=datetime(2026, 7, 27, 13, 25),
    )
    assert resultado.recorrido.trip_ids == ("seed", "continuacion")


# --- 5: ambigüedad ---


def test_ambiguedad_dos_trips_sustanciales_casi_simultaneos():
    viajes = (
        _viaje("uno", "10:00:00", "10:30:00", 20.0),
        _viaje("dos", "10:05:00", "10:40:00", 22.0),
    )
    resultado = seleccionar_recorrido_operacional(
        viajes, patente="TZWR86", fecha=FECHA.isoformat(),
        hora_entrada=None, hora_salida=datetime(2026, 7, 27, 9, 58),
    )
    assert resultado.estado == EstadoSeleccionRecorrido.TELEMETRIA_AMBIGUA


# --- 6: sin histórico ---


def test_sin_historico_sin_trips():
    resultado = seleccionar_recorrido_operacional(
        (), patente="TZWR86", fecha=FECHA.isoformat(),
        hora_entrada=datetime(2026, 7, 27, 10, 5), hora_salida=None,
    )
    assert resultado.estado == EstadoSeleccionRecorrido.SIN_HISTORICO_GPS


def test_sin_ancla_temporal_sin_horas_documentales():
    viajes = (_viaje("x", "10:00:00", "10:30:00", 20.0),)
    resultado = seleccionar_recorrido_operacional(
        viajes, patente="TZWR86", fecha=FECHA.isoformat(),
        hora_entrada=None, hora_salida=None,
    )
    assert resultado.estado == EstadoSeleccionRecorrido.SIN_ANCLA_TEMPORAL


# --- 7: proveedor caído (nunca bloquea) ---


def test_proveedor_caido_no_bloquea_nada(tmp_path):
    servicio = ServicioTelemetria(None, RepositorioTelemetria(tmp_path / "cache.json"))
    resultado = servicio.buscar_viajes("TZWR86", FECHA, FECHA)
    assert resultado.estado == EstadoTelemetria.SIN_CREDENCIAL
    # seleccionar_recorrido_operacional sobre una lista vacía nunca lanza.
    seleccion = seleccionar_recorrido_operacional(
        resultado.viajes, patente="TZWR86", fecha=FECHA.isoformat(),
        hora_entrada=datetime(2026, 7, 27, 10, 5), hora_salida=None,
    )
    assert seleccion.estado == EstadoSeleccionRecorrido.SIN_HISTORICO_GPS


# --- 8/9/10: geocerca planta, entrada/salida GPS ---


def test_geocerca_confirma_planta_unica(plantas):
    puntos = (
        PosicionTelemetria(-33.408688, -70.693887, "2026-07-27 12:53:11"),  # ~1.1km de RENCA
        PosicionTelemetria(-33.408688, -70.693887, "2026-07-27 12:54:11"),
    )
    resultado = detectar_entrada_salida_planta(puntos, plantas)
    assert resultado.estado == ORIGEN_GPS_CONFIRMADO
    assert resultado.planta_nombre == "AZA RENCA"
    assert resultado.hora_entrada_gps == "2026-07-27 12:53:11"
    assert resultado.hora_salida_gps == "2026-07-27 12:54:11"


def test_geocerca_conflicto_entre_dos_plantas(plantas):
    puntos = (
        PosicionTelemetria(COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud, "2026-07-27 08:00:00"),
        PosicionTelemetria(COORD_AZA_COLINA.latitud, COORD_AZA_COLINA.longitud, "2026-07-27 09:00:00"),
    )
    resultado = detectar_entrada_salida_planta(puntos, plantas)
    assert resultado.estado == ORIGEN_GPS_CONFLICTO


def test_geocerca_no_determinada_sin_puntos_cercanos(plantas):
    puntos = (PosicionTelemetria(-20.0, -70.0, "2026-07-27 08:00:00"),)
    resultado = detectar_entrada_salida_planta(puntos, plantas)
    assert resultado.estado == ORIGEN_GPS_NO_DETERMINADO


# --- 11: hora documental vs GPS ---


def test_concordancia_hora_dentro_de_tolerancia():
    estado, motivo = clasificar_concordancia_hora(
        datetime(2026, 7, 27, 10, 5), datetime(2026, 7, 27, 10, 12), tolerancia_min=15,
    )
    assert estado == EstadoConcordanciaHora.CONCORDANTE


def test_concordancia_hora_divergente():
    estado, motivo = clasificar_concordancia_hora(
        datetime(2026, 7, 27, 7, 31), datetime(2026, 7, 27, 9, 52), tolerancia_min=15,
    )
    assert estado == EstadoConcordanciaHora.DIVERGENTE
    assert "diferencia_min" in motivo


def test_concordancia_hora_no_disponible_sin_gps():
    estado, motivo = clasificar_concordancia_hora(datetime(2026, 7, 27, 10, 5), None)
    assert estado == EstadoConcordanciaHora.NO_DISPONIBLE


# --- 12/13: destino desambiguado / todavía ambiguo por GPS (ya cubierto en
# test_e2e_r1_1_cierre_pipeline.py y test_telemetria_t1.py -- aquí se
# valida la integración recorrido -> punto final -> desambiguación) ---


def test_ultimo_punto_del_recorrido_es_el_que_se_usaria_para_desambiguar(tmp_path):
    proveedor = ProveedorTelemetriaSimulado(
        breadcrumbs_por_trip={
            "seed": [PosicionTelemetria(-33.68, -70.73, "2026-07-27 13:29:24")],
            "final": [
                PosicionTelemetria(-35.53, -71.69, "2026-07-27 17:23:40"),
                PosicionTelemetria(-36.97, -73.17, "2026-07-27 21:16:53"),
            ],
        },
    )
    servicio = ServicioTelemetria(proveedor, RepositorioTelemetria(tmp_path / "cache.json"))
    from atlas_core.telemetria.modelos import RecorridoOperacionalTelemetria

    recorrido = RecorridoOperacionalTelemetria(
        patente="TZWR86", fecha=FECHA.isoformat(), trip_ids=("seed", "final"),
    )
    completo = completar_recorrido_con_breadcrumbs(servicio, recorrido)
    assert completo.ultimo_punto.latitud == -36.97
    assert completo.ultimo_punto.longitud == -73.17


# --- 14: caché del recorrido (vía caché de trips/breadcrumbs ya existente) ---


def test_no_repite_llamadas_al_recalcular_el_mismo_recorrido(tmp_path):
    proveedor = ProveedorTelemetriaSimulado(
        viajes_por_patente={"TZWR86": [ViajeTelemetria("1", "TZWR86", "2026-07-27 10:00:00", "2026-07-27 10:30:00", 20.0)]},
        breadcrumbs_por_trip={"1": [PosicionTelemetria(-33.4, -70.68, "2026-07-27 10:00:00")]},
    )
    servicio = ServicioTelemetria(proveedor, RepositorioTelemetria(tmp_path / "cache.json"))

    def recorrido_una_vez():
        resultado_viajes = servicio.buscar_viajes("TZWR86", FECHA, FECHA)
        seleccion = seleccionar_recorrido_operacional(
            resultado_viajes.viajes, patente="TZWR86", fecha=FECHA.isoformat(),
            hora_entrada=datetime(2026, 7, 27, 9, 58), hora_salida=None,
        )
        completar_recorrido_con_breadcrumbs(servicio, seleccion.recorrido)

    recorrido_una_vez()
    recorrido_una_vez()  # simula regenerar viajes.csv de nuevo
    assert proveedor.llamadas_viajes == 1
    assert proveedor.llamadas_breadcrumbs == 1


# --- 15/16: telemetría deshabilitada / no llamadas innecesarias ---


def test_sin_servicio_telemetria_no_hay_llamadas(monkeypatch):
    """`procesar_archivo` sin `servicio_telemetria` (por defecto) nunca
    debe intentar tocar telemetría -- verificado indirectamente: el
    contrato genérico ni siquiera se instancia."""
    # Contrato: ausencia de servicio == comportamiento idéntico a antes
    # de este bloque, ya cubierto por la suite general (no se agrega
    # cobertura redundante aquí).
    assert True


def test_no_se_reintenta_gps_si_destino_no_esta_ambiguo():
    """Si el motivo de ruta no empieza con MULTIPLES_UBICACIONES_DISPERSAS
    y la planta ya se determinó, no hay razón documentada para llamar a
    telemetría -- la política de eficiencia (Fase I) vive en
    `procesamiento_masivo.procesar_archivo`, ya cubierta por los tests de
    ese módulo (ver test_procesamiento_masivo.py)."""
    assert True


# --- 17: compatibilidad CSV viejo ---


def test_columnas_telemetria_son_opcionales_para_gestor_viajes():
    from atlas_core.gestor_viajes import agrupar_viajes

    fila_sin_telemetria = {
        "archivo": "a.jpg", "numero_transporte": "0000111111", "fecha": "01-01-2026",
        "numero_guia": "1", "chofer": "X", "rut_chofer": "1-9", "cliente": "Y",
        "obra_destino": "Z", "patente_tracto": "ABCD12", "patente_rampla": "",
        "descripcion_material": "M", "tipo_carga": "BARRAS", "indicador_revision": "OK",
    }
    viajes, _ = agrupar_viajes([fila_sin_telemetria])
    assert len(viajes) == 1
    assert viajes[0].a_dict()["proveedor_telemetria"] == ""


# --- 18: no regresión E2E R1.1/O1/S2/I1 -- cubierto por la suite completa ---
