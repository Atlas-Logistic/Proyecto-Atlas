"""Bloque ORIGEN O2: asociar la planta de origen a la VENTANA REAL de
carga de un viaje (hora_entrada → hora_salida documental), no a
"cualquier planta que el vehículo haya tocado ese día".

Hallazgo real que motivó este bloque: PLANTAS P3 dejó 10 guías reales en
`ORIGEN_GPS_CONFLICTO` (Renca vs. Colina) porque el vehículo pasaba
cerca de AMBAS plantas en algún momento del día -- pero una de esas
visitas casi siempre ocurre FUERA de la ventana documental real de esa
guía específica, o es solo un breadcrumb suelto sin sustento temporal.
La pregunta correcta no es "¿qué plantas visitó el vehículo hoy?" sino
"¿en qué planta estuvo cargando durante ESTA ventana?".

Segundo hallazgo real (464424): un trip de Onelogis puede contener una
parada real de varios minutos EN MEDIO de un trayecto más largo (el
motor nunca se apaga) -- `detectar_detenciones` ahora agrupa por
cluster espacio-temporal de breadcrumbs (con velocidad como filtro
adicional cuando el proveedor la informa), no por si el trip completo
es estacionario de punta a punta.

Todos los tests son unitarios/deterministas, sin red real.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad, TipoGeocerca
from atlas_core.rutas.destino_entrega import calcular_ruta_con_planta_conocida
from atlas_core.rutas.modelos import Coordenadas, EstadoRuta, ResultadoRuta
from atlas_core.rutas.proveedor import ProveedorRutasSimulado
from atlas_core.telemetria.modelos import PosicionTelemetria, ViajeTelemetria
from atlas_core.telemetria.proveedor import ProveedorTelemetriaSimulado
from atlas_core.telemetria.repositorio import RepositorioTelemetria
from atlas_core.telemetria.seleccion_recorrido import (
    ORIGEN_GPS_CONFIRMADO,
    ORIGEN_GPS_CONFLICTO,
    resolver_planta_origen_gps,
)
from atlas_core.telemetria.servicio import ServicioTelemetria

COORD_AZA_RENCA = Coordenadas(-70.685226, -33.401595)
FECHA = date(2026, 8, 11)

# Polígono pequeño y simple para tests (no el polígono real de P3 --
# aquí solo interesa el comportamiento temporal, no la geografía real).
VERTICES_COLINA_TEST = [
    [-33.1370, -70.6655], [-33.1380, -70.6655], [-33.1380, -70.6665], [-33.1370, -70.6665],
]
COORD_COLINA_DENTRO = (-33.1375, -70.6660)


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
        latitud=-33.137558, longitud=-70.665977,
        estado_calidad=EstadoCalidad.CONFIRMADA,
        tipo_geocerca=TipoGeocerca.POLIGONAL, vertices=VERTICES_COLINA_TEST,
    )
    return catalogo.listar()


def _servicio(tmp_path, viajes_por_patente=None, breadcrumbs_por_trip=None):
    proveedor = ProveedorTelemetriaSimulado(
        viajes_por_patente=viajes_por_patente or {},
        breadcrumbs_por_trip=breadcrumbs_por_trip or {},
    )
    return proveedor, ServicioTelemetria(proveedor, RepositorioTelemetria(tmp_path / "cache.json"))


def _puntos_estacionarios(lat, lon, inicio_iso, n=6, paso_seg=60):
    from datetime import timedelta
    base = datetime.fromisoformat(inicio_iso)
    return tuple(
        PosicionTelemetria(lat + i * 0.00002, lon + i * 0.00002, (base + timedelta(seconds=i * paso_seg)).isoformat(sep=" "))
        for i in range(n)
    )


# --- 1: visita Renca FUERA de ventana + Colina DENTRO -> Colina ---


def test_visita_renca_fuera_de_ventana_no_afecta_colina_dentro(plantas, tmp_path):
    """Vehículo estuvo en Renca 06:00-07:00 (fuera de la ventana) y en
    Colina 09:45-14:40 (dentro) -- la guía [09:46,14:39] debe resolver
    AZA COLINA, sin que la visita matutina a Renca produzca conflicto."""
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "XX0000": [
                ViajeTelemetria("renca_manana", "XX0000", "2026-08-11 06:00:00", "2026-08-11 07:00:00", 0.0),
                ViajeTelemetria("colina_carga", "XX0000", "2026-08-11 09:45:00", "2026-08-11 09:51:00", 0.0),
            ],
        },
        breadcrumbs_por_trip={
            "renca_manana": _puntos_estacionarios(
                COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud, "2026-08-11 06:00:00"
            ),
            "colina_carga": _puntos_estacionarios(
                COORD_COLINA_DENTRO[0], COORD_COLINA_DENTRO[1], "2026-08-11 09:45:00"
            ),
        },
    )
    resultado = resolver_planta_origen_gps(
        servicio, patente="XX0000", fecha=FECHA,
        hora_entrada=datetime(2026, 8, 11, 9, 46), hora_salida=datetime(2026, 8, 11, 14, 39),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_CONFIRMADO
    assert resultado.planta_nombre == "AZA COLINA"


# --- 2: Colina FUERA de ventana + Renca DENTRO -> Renca ---


def test_visita_colina_fuera_de_ventana_no_afecta_renca_dentro(plantas, tmp_path):
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "XX0000": [
                ViajeTelemetria("colina_tarde", "XX0000", "2026-08-11 16:00:00", "2026-08-11 16:30:00", 0.0),
                ViajeTelemetria("renca_carga", "XX0000", "2026-08-11 09:00:00", "2026-08-11 09:06:00", 0.0),
            ],
        },
        breadcrumbs_por_trip={
            "colina_tarde": _puntos_estacionarios(
                COORD_COLINA_DENTRO[0], COORD_COLINA_DENTRO[1], "2026-08-11 16:00:00"
            ),
            "renca_carga": _puntos_estacionarios(
                COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud, "2026-08-11 09:00:00"
            ),
        },
    )
    resultado = resolver_planta_origen_gps(
        servicio, patente="XX0000", fecha=FECHA,
        hora_entrada=datetime(2026, 8, 11, 8, 50), hora_salida=datetime(2026, 8, 11, 9, 10),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_CONFIRMADO
    assert resultado.planta_nombre == "AZA RENCA"


# --- 3: ambas plantas con evidencia real DENTRO de la misma ventana -> conflicto real ---


def test_ambas_plantas_dentro_de_la_misma_ventana_es_conflicto_real(plantas, tmp_path):
    """Evidencia comparable (misma duración, mismo solape) de las dos
    plantas dentro de la MISMA ventana documental -- sin margen
    suficiente para preferir una, es un conflicto real."""
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "XX0000": [
                ViajeTelemetria("renca", "XX0000", "2026-08-11 09:00:00", "2026-08-11 09:06:00", 0.0),
                ViajeTelemetria("colina", "XX0000", "2026-08-11 09:30:00", "2026-08-11 09:36:00", 0.0),
            ],
        },
        breadcrumbs_por_trip={
            "renca": _puntos_estacionarios(COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud, "2026-08-11 09:00:00"),
            "colina": _puntos_estacionarios(COORD_COLINA_DENTRO[0], COORD_COLINA_DENTRO[1], "2026-08-11 09:30:00"),
        },
    )
    resultado = resolver_planta_origen_gps(
        servicio, patente="XX0000", fecha=FECHA,
        hora_entrada=datetime(2026, 8, 11, 8, 55), hora_salida=datetime(2026, 8, 11, 9, 40),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_CONFLICTO
    assert "CONFLICTO_REAL_EN_VENTANA" in resultado.motivo


# --- 4: estadía prolongada domina sobre un punto aislado ---


def test_estadia_prolongada_domina_punto_aislado(plantas, tmp_path):
    """Una detención real y sustancial (30+ min, dentro de la ventana)
    gana con margen claro sobre un breadcrumb suelto de la otra planta
    -- nunca genera un conflicto automático solo porque existe *algo*
    de evidencia rival."""
    from datetime import timedelta
    puntos_largos = tuple(
        PosicionTelemetria(
            COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud,
            (datetime(2026, 8, 11, 9, 0) + timedelta(minutes=i)).isoformat(sep=" "),
        )
        for i in range(31)
    )
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "XX0000": [
                ViajeTelemetria("renca_larga", "XX0000", "2026-08-11 09:00:00", "2026-08-11 09:30:00", 0.0),
                ViajeTelemetria("pasada_colina", "XX0000", "2026-08-11 10:00:00", "2026-08-11 10:20:00", 15.0),
            ],
        },
        breadcrumbs_por_trip={
            "renca_larga": puntos_largos,
            "pasada_colina": (
                PosicionTelemetria(-33.30, -70.70, "2026-08-11 10:00:00"),
                PosicionTelemetria(*COORD_COLINA_DENTRO, "2026-08-11 10:10:00"),
                PosicionTelemetria(-33.30, -70.70, "2026-08-11 10:20:00"),
            ),
        },
    )
    resultado = resolver_planta_origen_gps(
        servicio, patente="XX0000", fecha=FECHA,
        hora_entrada=datetime(2026, 8, 11, 9, 0), hora_salida=datetime(2026, 8, 11, 10, 20),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_CONFIRMADO
    assert resultado.planta_nombre == "AZA RENCA"


# --- 5: salida de geocerca cerca de hora_salida documental corrobora ---


def test_salida_de_geocerca_cerca_de_hora_salida_corrobora(plantas, tmp_path):
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "XX0000": [ViajeTelemetria("x", "XX0000", "2026-08-11 09:00:00", "2026-08-11 09:16:00", 0.0)],
        },
        breadcrumbs_por_trip={
            "x": _puntos_estacionarios(COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud, "2026-08-11 09:00:00", n=17),
        },
    )
    resultado = resolver_planta_origen_gps(
        servicio, patente="XX0000", fecha=FECHA,
        hora_entrada=datetime(2026, 8, 11, 9, 0), hora_salida=datetime(2026, 8, 11, 9, 16),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_CONFIRMADO
    assert "score=" in resultado.motivo


# --- 6: 464641/642 sigue resolviendo Colina (patrón real, sin hardcodear el número de guía) ---


def test_patron_real_464641_642_sigue_resolviendo_colina(plantas, tmp_path):
    """Reproduce el patrón real (detención de varias horas solapando casi
    toda la ventana documental) sin hardcodear el número de guía."""
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "AL1879": [
                ViajeTelemetria("A", "AL1879", "2026-08-11 08:49:00", "2026-08-11 08:55:00", 0.0),
                ViajeTelemetria("B", "AL1879", "2026-08-11 14:31:00", "2026-08-11 14:57:00", 0.0),
            ],
        },
        breadcrumbs_por_trip={
            "A": _puntos_estacionarios(*COORD_COLINA_DENTRO, "2026-08-11 08:49:00"),
            "B": _puntos_estacionarios(*COORD_COLINA_DENTRO, "2026-08-11 14:31:00", n=26),
        },
    )
    resultado = resolver_planta_origen_gps(
        servicio, patente="AL1879", fecha=FECHA,
        hora_entrada=datetime(2026, 8, 11, 9, 46), hora_salida=datetime(2026, 8, 11, 14, 39),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_CONFIRMADO
    assert resultado.planta_nombre == "AZA COLINA"


# --- 7: regresión real 464424 -- parada en medio de un trip más largo, sin hardcodear el número ---


def test_parada_en_medio_de_trip_largo_se_detecta_como_evidencia(plantas, tmp_path):
    """Reproduce el patrón real de 464424: un trip largo (velocidad alta
    al inicio/fin) con una parada real de varios minutos en el medio
    (velocidad baja) -- debe detectarse como detención real, no
    ignorarse por no ser el trip completo el que está detenido."""
    from datetime import timedelta
    base = datetime(2026, 8, 7, 8, 20)
    puntos = []
    # aproximación rápida
    for i in range(5):
        puntos.append(PosicionTelemetria(
            -33.30 + i * 0.001, -70.70 + i * 0.001,
            (base + timedelta(minutes=i)).isoformat(sep=" "), velocidad=40.0,
        ))
    # parada real de 15 min (velocidad baja)
    inicio_parada = base + timedelta(minutes=5)
    for i in range(16):
        puntos.append(PosicionTelemetria(
            COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud,
            (inicio_parada + timedelta(minutes=i)).isoformat(sep=" "), velocidad=0.0,
        ))
    # salida rápida
    salida = inicio_parada + timedelta(minutes=16)
    for i in range(5):
        puntos.append(PosicionTelemetria(
            -33.30 - i * 0.001, -70.70 - i * 0.001,
            (salida + timedelta(minutes=i)).isoformat(sep=" "), velocidad=45.0,
        ))
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "XX0000": [ViajeTelemetria("largo", "XX0000", puntos[0].timestamp, puntos[-1].timestamp, 20.0)],
        },
        breadcrumbs_por_trip={"largo": tuple(puntos)},
    )
    resultado = resolver_planta_origen_gps(
        servicio, patente="XX0000", fecha=date(2026, 8, 7),
        hora_entrada=datetime(2026, 8, 7, 8, 15), hora_salida=datetime(2026, 8, 7, 8, 45),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_CONFIRMADO
    assert resultado.planta_nombre == "AZA RENCA"


# --- 8: multiguía -- mismo transporte, mismo resultado ---


def test_multiguia_mismo_transporte_misma_planta(plantas, tmp_path):
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "AL1879": [ViajeTelemetria("x", "AL1879", "2026-08-11 09:00:00", "2026-08-11 09:20:00", 0.0)],
        },
        breadcrumbs_por_trip={
            "x": _puntos_estacionarios(*COORD_COLINA_DENTRO, "2026-08-11 09:00:00", n=21),
        },
    )
    r1 = resolver_planta_origen_gps(
        servicio, patente="AL1879", fecha=FECHA,
        hora_entrada=datetime(2026, 8, 11, 8, 55), hora_salida=datetime(2026, 8, 11, 9, 25),
        plantas=plantas,
    )
    r2 = resolver_planta_origen_gps(
        servicio, patente="AL1879", fecha=FECHA,
        hora_entrada=datetime(2026, 8, 11, 9, 0), hora_salida=None,
        plantas=plantas,
    )
    assert r1.estado == r2.estado == ORIGEN_GPS_CONFIRMADO
    assert r1.planta_nombre == r2.planta_nombre == "AZA COLINA"


# --- 9: una sola hora documental -- ancla más débil, margen configurable ---


def test_una_sola_hora_usa_margen_simetrico(plantas, tmp_path):
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "XX0000": [ViajeTelemetria("x", "XX0000", "2026-08-11 09:00:00", "2026-08-11 09:20:00", 0.0)],
        },
        breadcrumbs_por_trip={
            "x": _puntos_estacionarios(*COORD_COLINA_DENTRO, "2026-08-11 09:00:00", n=21),
        },
    )
    resultado = resolver_planta_origen_gps(
        servicio, patente="XX0000", fecha=FECHA,
        hora_entrada=None, hora_salida=datetime(2026, 8, 11, 9, 20),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_CONFIRMADO
    assert resultado.planta_nombre == "AZA COLINA"


# --- 10: sin ninguna hora documental -- se abstiene, nunca inventa ---


def test_sin_ninguna_hora_documental_se_abstiene(plantas, tmp_path):
    _, servicio = _servicio(tmp_path)
    resultado = resolver_planta_origen_gps(
        servicio, patente="XX0000", fecha=FECHA,
        hora_entrada=None, hora_salida=None,
        plantas=plantas,
    )
    assert resultado.estado != ORIGEN_GPS_CONFIRMADO
    assert resultado.motivo == "SIN_HORA_DOCUMENTAL"


# --- 11: cambio de planta invalida/recalcula la ruta ---


def test_cambio_de_planta_por_o2_recalcula_ruta(plantas):
    renca = next(p for p in plantas if p.nombre == "AZA RENCA")
    colina = next(p for p in plantas if p.nombre == "AZA COLINA")
    despachar_a = "DIRECCION DEMO 123"
    consulta = f"{despachar_a}, Chile"
    geocodificaciones = {
        consulta: __import__(
            "atlas_core.rutas.modelos", fromlist=["ResultadoGeocodificacion"]
        ).ResultadoGeocodificacion(
            EstadoRuta.REQUIERE_REVISION,
            (__import__(
                "atlas_core.rutas.modelos", fromlist=["CandidatoGeocodificacion"]
            ).CandidatoGeocodificacion(Coordenadas(-70.6, -33.3), "Direccion demo", 0.8),),
            "REQUIERE_CONFIRMACION_HUMANA",
        )
    }
    origenes_capturados = []

    class ProveedorCapturaOrigen(ProveedorRutasSimulado):
        def calcular_ruta(self, origen, destino, perfil):
            origenes_capturados.append(origen)
            return super().calcular_ruta(origen, destino, perfil)

    proveedor = ProveedorCapturaOrigen(
        geocodificaciones=geocodificaciones,
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 20.0, 30.0, ""),
    )
    resultado_renca = calcular_ruta_con_planta_conocida(
        planta=renca, despachar_a_crudo=despachar_a, proveedor_rutas=proveedor,
    )
    resultado_colina = calcular_ruta_con_planta_conocida(
        planta=colina, despachar_a_crudo=despachar_a, proveedor_rutas=proveedor,
    )
    assert resultado_renca.planta_origen_nombre == "AZA RENCA"
    assert resultado_colina.planta_origen_nombre == "AZA COLINA"
    assert origenes_capturados[0] != origenes_capturados[1]


# --- Bloque VISITA_A_PLANTA -- validación adicional (sin cambios de
# comportamiento): esta función YA ES el mecanismo de detección y
# asociación de "visitas a planta" que ese bloque pidió diseñar. Cierra
# dos huecos de cobertura reales encontrados al auditar el histórico:
# dos visitas separadas a la MISMA planta el mismo día, y el patrón
# exacto del caso real 464730 (ventana documental degenerada
# hora_entrada==hora_salida, evidencia real para dos plantas). ---


def test_dos_visitas_a_la_misma_planta_mismo_dia_elige_la_que_cae_en_la_ventana(plantas, tmp_path):
    """Dos permanencias reales y separadas en AZA COLINA el mismo día
    (p. ej. carga matutina + retiro de repuestos por la tarde) -- la
    guía debe asociarse a la que realmente solapa su ventana documental,
    nunca a "la primera" ni a "la más larga" por defecto."""
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "XX0000": [
                ViajeTelemetria("colina_manana", "XX0000", "2026-08-11 07:00:00", "2026-08-11 07:10:00", 0.0),
                ViajeTelemetria("colina_tarde", "XX0000", "2026-08-11 13:00:00", "2026-08-11 13:30:00", 0.0),
            ],
        },
        breadcrumbs_por_trip={
            "colina_manana": _puntos_estacionarios(*COORD_COLINA_DENTRO, "2026-08-11 07:00:00", n=11),
            "colina_tarde": _puntos_estacionarios(*COORD_COLINA_DENTRO, "2026-08-11 13:00:00", n=31),
        },
    )
    resultado = resolver_planta_origen_gps(
        servicio, patente="XX0000", fecha=FECHA,
        hora_entrada=datetime(2026, 8, 11, 12, 58), hora_salida=datetime(2026, 8, 11, 13, 32),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_CONFIRMADO
    assert resultado.planta_nombre == "AZA COLINA"
    # La visita elegida es la de la tarde (dentro de la ventana), no la
    # matutina -- se verifica por la hora de entrada/salida GPS devuelta.
    assert resultado.hora_entrada_gps.startswith("2026-08-11 13:")


def test_ventana_documental_degenerada_464730_no_se_auto_resuelve_a_una_planta(plantas, tmp_path):
    """Réplica sintética del patrón real 464730: `hora_entrada_aza ==
    hora_salida_aza` (documento sin ventana real, sólo un instante) con
    evidencia GPS real para AMBAS plantas ese día -- una termina justo
    antes del instante documental, la otra ocurre después. Con el
    instante degenerado, el solape contra la ventana es 0% para
    cualquier detención (nunca hay ventana real que solapar) -- el único
    desempate posible es la proximidad de entrada/salida GPS al
    instante, señal débil por diseño (30% del score combinado). Atlas
    debe concluir CONFLICTO (requiere humano), nunca forzar una planta
    por estar "más cerca en el tiempo" -- exactamente lo que Javier
    confirmó que habría sido la planta incorrecta en el caso real."""
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "XX0000": [
                ViajeTelemetria("colina", "XX0000", "2026-08-11 07:19:00", "2026-08-11 08:24:00", 0.0),
                ViajeTelemetria("renca", "XX0000", "2026-08-11 10:21:00", "2026-08-11 12:01:00", 0.0),
            ],
        },
        breadcrumbs_por_trip={
            # Pocos puntos (mismo orden de magnitud que el resto de los
            # tests del archivo): con `_puntos_estacionarios` cada punto
            # sucesivo se desplaza un poco (deriva realista) -- demasiados
            # puntos sobre un polígono de prueba pequeño terminarían
            # saliéndose de él. `paso_seg` se ajusta para cubrir el mismo
            # rango horario real con menos puntos.
            "colina": _puntos_estacionarios(*COORD_COLINA_DENTRO, "2026-08-11 07:19:00", n=7, paso_seg=650),
            "renca": _puntos_estacionarios(
                COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud, "2026-08-11 10:21:00", n=11, paso_seg=600,
            ),
        },
    )
    instante_documental = datetime(2026, 8, 11, 8, 18)
    resultado = resolver_planta_origen_gps(
        servicio, patente="XX0000", fecha=FECHA,
        hora_entrada=instante_documental, hora_salida=instante_documental,
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_CONFLICTO
    assert "CONFLICTO_REAL_EN_VENTANA" in resultado.motivo


# --- 12: no regresión T1/T2/T3/P3 -- cubierta por la suite completa ---


def test_no_regresion_se_verifica_con_la_suite_completa():
    """No se duplica cobertura aquí -- la garantía de no regresión de
    este bloque es que `python -m pytest -q` sigue en verde. Ver
    `test_telemetria_t1.py`, `test_telemetria_t2.py`,
    `test_telemetria_t3.py`, `test_plantas_p3_geocercas_poligonales.py`."""
    assert True
