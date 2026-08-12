"""Bloque PLANTAS P3: geocercas operacionales poligonales + corrección
real de AZA COLINA.

Contexto real: T3 encontró que AL1879 (464641/464642) estuvo detenido
6h08min en una coordenada que geocodifica como "Gerdau Aza, Lampa" --
18,4 km del punto CIRCULAR de AZA COLINA en el catálogo (geocodificado
de texto, confianza 0.6). Javier confirmó visualmente en Onelogis que
ese lugar ES el recinto operacional real de AZA COLINA (acceso,
estacionamientos, zonas de carga) -- un punto+radio pequeño nunca
representa bien un complejo real amplio. Se generalizó el modelo de
plantas para soportar geocercas POLIGONALES (backward-compatible con
CIRCULAR) y se corrigió AZA COLINA con un polígono derivado de
evidencia GPS real (envolvente convexa de 117 breadcrumbs reales) +
validación cartográfica independiente (ORS/Pelias).

Decisión separada (confirmada por el usuario): la geocerca (polígono)
determina IDENTIDAD de planta; el `punto_ruteo` (nuevo, opcional)
determina desde dónde parte una ruta ORS -- nunca el centroide del
polígono ni la coordenada histórica ya demostrada imprecisa.

Todos los tests son unitarios/deterministas, sin red real.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from atlas_core.catalogo_plantas import (
    CatalogoPlantas,
    EstadoCalidad,
    ErrorCatalogoPlantas,
    TipoGeocerca,
)
from atlas_core.rutas.geocerca import (
    coordenada_ruteo_planta,
    punto_en_poligono,
    resolver_planta_por_posicion,
)
from atlas_core.rutas.modelos import Coordenadas
from atlas_core.rutas.destino_entrega import calcular_ruta_con_planta_conocida
from atlas_core.rutas.modelos import EstadoRuta, ResultadoRuta
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
# Polígono real (Bloque P3) -- envolvente convexa de breadcrumbs reales AL1879.
VERTICES_COLINA_REAL = [
    [-33.296312, -70.72894], [-33.296028, -70.729433], [-33.294752, -70.730387],
    [-33.294637, -70.730298], [-33.293927, -70.728425], [-33.293915, -70.728377],
    [-33.293893, -70.727475], [-33.293902, -70.727395], [-33.29401, -70.727315],
    [-33.294153, -70.727317],
]
PUNTO_DENTRO = Coordenadas(-70.7290, -33.2947)  # dentro del polígono real
PUNTO_FUERA = Coordenadas(-70.6660, -33.1376)  # el viejo punto CIRCULAR, lejos del polígono
FECHA = date(2026, 8, 11)


@pytest.fixture
def plantas(tmp_path):
    catalogo = CatalogoPlantas(tmp_path / "plantas.json")
    colina = catalogo.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="PRUEBA",
        direccion="AV. PDTE. EDUARDO FREI MONTALVA 18500", comuna="COLINA", region="RM",
        latitud=-33.137558, longitud=-70.665977,  # dirección histórica -- sin cambiar
        estado_calidad=EstadoCalidad.CONFIRMADA,
        tipo_geocerca=TipoGeocerca.POLIGONAL,
        vertices=VERTICES_COLINA_REAL,
        punto_ruteo_latitud=-33.294752, punto_ruteo_longitud=-70.730387,
    )
    renca = catalogo.crear(
        nombre="AZA RENCA", pais="CHILE", fuente="PRUEBA",
        direccion="LA UNION 3070", comuna="RENCA", region="RM",
        latitud=COORD_AZA_RENCA.latitud, longitud=COORD_AZA_RENCA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
        # CIRCULAR por defecto -- Fase H, no se toca.
    )
    return catalogo.listar()


def _servicio(tmp_path, viajes_por_patente=None, breadcrumbs_por_trip=None):
    proveedor = ProveedorTelemetriaSimulado(
        viajes_por_patente=viajes_por_patente or {},
        breadcrumbs_por_trip=breadcrumbs_por_trip or {},
    )
    return proveedor, ServicioTelemetria(proveedor, RepositorioTelemetria(tmp_path / "cache.json"))


# --- 1/2/3: point-in-polygon dentro / fuera / borde ---


def test_punto_en_poligono_dentro():
    assert punto_en_poligono(PUNTO_DENTRO, VERTICES_COLINA_REAL) is True


def test_punto_en_poligono_fuera():
    assert punto_en_poligono(PUNTO_FUERA, VERTICES_COLINA_REAL) is False


def test_punto_en_poligono_en_el_borde_no_lanza():
    """Un punto exactamente sobre un vértice o arista no debe lanzar --
    el resultado (dentro/fuera) puede depender de convención numérica,
    pero la función siempre responde un booleano determinista."""
    vertice = Coordenadas(VERTICES_COLINA_REAL[0][1], VERTICES_COLINA_REAL[0][0])
    resultado = punto_en_poligono(vertice, VERTICES_COLINA_REAL)
    assert resultado in (True, False)
    # Polígono degenerado (menos de 3 vértices) nunca contiene nada, nunca lanza.
    assert punto_en_poligono(PUNTO_DENTRO, [[-33.0, -70.0], [-33.1, -70.1]]) is False


# --- 4: planta circular legacy sigue funcionando igual ---


def test_planta_circular_legacy_sin_tipo_geocerca_usa_radio(tmp_path):
    """Un registro que nunca tuvo `tipo_geocerca`/`vertices` (formato de
    antes de este bloque) se carga con el default CIRCULAR -- mismo
    comportamiento de siempre."""
    catalogo = CatalogoPlantas(tmp_path / "legado.json")
    catalogo.crear(
        nombre="PLANTA LEGADO", pais="CHILE", fuente="PRUEBA",
        latitud=-33.0, longitud=-70.0, estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    import json
    contenido = json.loads((tmp_path / "legado.json").read_text(encoding="utf-8"))
    del contenido["plantas"][0]["tipo_geocerca"]
    del contenido["plantas"][0]["vertices"]
    (tmp_path / "legado.json").write_text(json.dumps(contenido), encoding="utf-8")

    recargado = CatalogoPlantas(tmp_path / "legado.json").listar()[0]
    assert recargado.tipo_geocerca == "CIRCULAR"
    assert recargado.vertices == ()

    resultado = resolver_planta_por_posicion(Coordenadas(-70.001, -33.001), [recargado], radio_km=1.5)
    assert resultado.determinada is True
    assert resultado.planta_nombre == "PLANTA LEGADO"


# --- 5: estadía mayoritaria dentro confirma la planta ---


# Puntos claramente INTERIORES al polígono real (no sobre el borde/vértices,
# donde el resultado de contención es ambiguo por definición matemática).
PUNTOS_INTERIORES = [
    (-33.2947, -70.7290), (-33.2949, -70.7288), (-33.2946, -70.7292),
    (-33.2948, -70.7286), (-33.2945, -70.7289),
]


def test_estadia_mayoritaria_dentro_confirma_colina(plantas, tmp_path):
    """Caso real generalizado (sin hardcodear AL1879): una detención con
    mayoría de puntos dentro del polígono, que solapa la ventana
    documental, resuelve AZA COLINA."""
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "XX0000": [
                ViajeTelemetria("A", "XX0000", "2026-08-11 09:00:00", "2026-08-11 09:10:00", 0.0),
                ViajeTelemetria("B", "XX0000", "2026-08-11 13:00:00", "2026-08-11 13:10:00", 0.0),
            ],
        },
        breadcrumbs_por_trip={
            "A": tuple(
                PosicionTelemetria(lat, lon, f"2026-08-11 09:0{i}:00")
                for i, (lat, lon) in enumerate(PUNTOS_INTERIORES[:3])
            ),
            "B": tuple(
                PosicionTelemetria(lat, lon, f"2026-08-11 13:0{i}:00")
                for i, (lat, lon) in enumerate(PUNTOS_INTERIORES[3:])
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
    # Bloque ORIGEN O2: el motivo final ahora describe el score contra la
    # ventana documental (solape/duración/margen), no la proporción cruda
    # de puntos del cluster (esa señal sigue existiendo internamente, ver
    # `_resolver_planta_para_detencion`).
    assert "VENTANA_DOCUMENTAL" in resultado.motivo


# --- 6: maniobra parcial en el borde no rompe la confirmación (mayoría, no 100%) ---


def test_maniobra_parcial_fuera_del_borde_no_impide_confirmar(plantas, tmp_path):
    """Fase E: no se exige que TODOS los breadcrumbs estén dentro -- una
    maniobra que se asoma levemente fuera del polígono a mitad de una
    detención (inicio y fin del trip permanecen dentro/coherentes) no
    debe impedir la confirmación, mientras la MAYORÍA de los puntos
    sigan dentro."""
    puntos = [
        PosicionTelemetria(PUNTOS_INTERIORES[0][0], PUNTOS_INTERIORES[0][1], "2026-08-11 09:00:00"),
        PosicionTelemetria(PUNTOS_INTERIORES[1][0], PUNTOS_INTERIORES[1][1], "2026-08-11 09:05:00"),
        # maniobra que se asoma levemente fuera del polígono
        PosicionTelemetria(-33.2990, -70.7250, "2026-08-11 09:10:00"),
        PosicionTelemetria(PUNTOS_INTERIORES[2][0], PUNTOS_INTERIORES[2][1], "2026-08-11 09:15:00"),
        PosicionTelemetria(PUNTOS_INTERIORES[3][0], PUNTOS_INTERIORES[3][1], "2026-08-11 09:20:00"),
    ]
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "XX0000": [ViajeTelemetria("A", "XX0000", "2026-08-11 09:00:00", "2026-08-11 09:20:00", 0.0)],
        },
        breadcrumbs_por_trip={"A": tuple(puntos)},
    )
    resultado = resolver_planta_origen_gps(
        servicio, patente="XX0000", fecha=FECHA,
        hora_entrada=None, hora_salida=datetime(2026, 8, 11, 9, 20),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_CONFIRMADO
    assert resultado.planta_nombre == "AZA COLINA"


# --- 7: dos plantas en conflicto ---


def test_dos_plantas_en_conflicto_via_detenciones(plantas, tmp_path):
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "XX0000": [
                ViajeTelemetria("colina", "XX0000", "2026-08-11 09:00:00", "2026-08-11 09:10:00", 0.0),
                ViajeTelemetria("renca", "XX0000", "2026-08-11 11:00:00", "2026-08-11 11:10:00", 0.0),
            ],
        },
        breadcrumbs_por_trip={
            "colina": tuple(
                PosicionTelemetria(lat, lon, f"2026-08-11 09:0{i}:00")
                for i, (lat, lon) in enumerate(PUNTOS_INTERIORES[:3])
            ),
            "renca": (
                PosicionTelemetria(COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud, "2026-08-11 11:00:00"),
                PosicionTelemetria(COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud, "2026-08-11 11:10:00"),
            ),
        },
    )
    resultado = resolver_planta_origen_gps(
        servicio, patente="XX0000", fecha=FECHA,
        hora_entrada=datetime(2026, 8, 11, 9, 0), hora_salida=datetime(2026, 8, 11, 11, 10),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_CONFLICTO


# --- 8: AL1879 -> Colina (regresión real, con datos sintéticos que reproducen el patrón) ---


def test_transito_aislado_por_el_poligono_no_confirma_sin_detencion(plantas, tmp_path):
    """Caso real que motivó el fix de exclusión de polígonos del chequeo
    por punto suelto: un vehículo que solo ATRAVIESA el polígono no debe
    confirmar la planta con un único breadcrumb aislado -- solo una
    detención real (2+ puntos coherentes entre sí) puede hacerlo. Nunca
    confundir con el caso real 464424 (Bloque ORIGEN O2): una parada
    real de varios minutos DENTRO de un trip más largo SÍ debe confirmar
    -- ver `test_telemetria_o2.py`. Aquí, en cambio, un solo punto
    aislado cae dentro del polígono, rodeado de puntos lejanos antes y
    después -- nunca dos puntos consecutivos coherentes entre sí."""
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "XX0000": [
                ViajeTelemetria("transito", "XX0000", "2026-08-07 08:00:00", "2026-08-07 08:46:00", 29.79),
            ],
        },
        breadcrumbs_por_trip={
            "transito": (
                PosicionTelemetria(-33.40, -70.60, "2026-08-07 08:00:00"),
                PosicionTelemetria(-33.2949, -70.7285, "2026-08-07 08:33:00"),  # único punto dentro
                PosicionTelemetria(-33.30, -70.60, "2026-08-07 08:46:00"),
            ),
        },
    )
    resultado = resolver_planta_origen_gps(
        servicio, patente="XX0000", fecha=FECHA,
        hora_entrada=None, hora_salida=datetime(2026, 8, 7, 8, 30),
        plantas=plantas,
    )
    assert resultado.planta_nombre != "AZA COLINA"


# --- 9: multiguía comparte planta ---


def test_multiguia_comparte_colina(plantas, tmp_path):
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "XX0000": [
                ViajeTelemetria("A", "XX0000", "2026-08-11 09:00:00", "2026-08-11 09:10:00", 0.0),
                ViajeTelemetria("B", "XX0000", "2026-08-11 13:00:00", "2026-08-11 13:10:00", 0.0),
            ],
        },
        breadcrumbs_por_trip={
            "A": tuple(
                PosicionTelemetria(lat, lon, f"2026-08-11 09:0{i}:00")
                for i, (lat, lon) in enumerate(PUNTOS_INTERIORES[:3])
            ),
            "B": tuple(
                PosicionTelemetria(lat, lon, f"2026-08-11 13:0{i}:00")
                for i, (lat, lon) in enumerate(PUNTOS_INTERIORES[3:])
            ),
        },
    )
    resultados = [
        resolver_planta_origen_gps(
            servicio, patente="XX0000", fecha=FECHA,
            hora_entrada=datetime(2026, 8, 11, 9, 46), hora_salida=hs,
            plantas=plantas,
        )
        for hs in (datetime(2026, 8, 11, 14, 39), None)
    ]
    for resultado in resultados:
        assert resultado.estado == ORIGEN_GPS_CONFIRMADO
        assert resultado.planta_nombre == "AZA COLINA"


# --- 10: Renca no regresiona ---


def test_renca_circular_sigue_confirmando_igual(plantas, tmp_path):
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "TZWR86": [ViajeTelemetria("x", "TZWR86", "2026-08-07 08:00:00", "2026-08-07 08:10:00", 1.0)],
        },
        breadcrumbs_por_trip={
            "x": (
                PosicionTelemetria(COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud, "2026-08-07 08:03:00"),
                PosicionTelemetria(COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud, "2026-08-07 08:05:00"),
            ),
        },
    )
    resultado = resolver_planta_origen_gps(
        servicio, patente="TZWR86", fecha=date(2026, 8, 7),
        hora_entrada=None, hora_salida=datetime(2026, 8, 7, 8, 5),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_CONFIRMADO
    assert resultado.planta_nombre == "AZA RENCA"
    assert resultado.distancia_minima_km is not None  # Renca sigue reportando distancia real


# --- 11: alias cartográfico no crea planta nueva ---


def test_no_existe_planta_aza_lampa_en_el_catalogo(plantas):
    nombres = {p.nombre for p in plantas}
    assert "AZA LAMPA" not in nombres
    assert "GERDAU AZA" not in nombres
    assert len(plantas) == 2  # solo AZA COLINA y AZA RENCA, ninguna nueva


# --- 12: cambio de planta invalida ruta ---


def test_cambio_de_planta_recalcula_desde_punto_ruteo_no_desde_centroide(plantas):
    """El punto de ruteo real (Fase I) se usa para calcular la ruta --
    nunca el centroide del polígono ni la coordenada histórica ya
    demostrada imprecisa."""
    colina = next(p for p in plantas if p.nombre == "AZA COLINA")
    origenes_capturados = []

    class ProveedorCapturaOrigen(ProveedorRutasSimulado):
        def calcular_ruta(self, origen, destino, perfil):
            origenes_capturados.append(origen)
            return super().calcular_ruta(origen, destino, perfil)

    proveedor = ProveedorCapturaOrigen(
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 10.0, 15.0, "")
    )
    calcular_ruta_con_planta_conocida(
        planta=colina, despachar_a_crudo="", proveedor_rutas=proveedor,
    )
    # Sin despachar_a, no llega a calcular ruta -- se prueba directo la
    # función de resolución de coordenada de ruteo, que es lo que
    # garantiza el comportamiento correcto en el camino real.
    coordenada = coordenada_ruteo_planta(colina)
    assert coordenada == Coordenadas(-70.730387, -33.294752)
    assert coordenada != Coordenadas(colina.longitud, colina.latitud)  # nunca el punto histórico
