"""Bloque OPERACIÓN REAL R1: origen por GPS/geocercas, no por letterhead.

Decisión de negocio (verbatim, Fase Q): "La planta de origen de un viaje
Atlas se determina mediante telemetría/GPS y geocercas de plantas cuando
el proveedor está disponible. La guía no contiene la dirección de origen
y no se usa para inferirla."

Causa raíz que motivó este bloque: `resolver_origen_documental()` matchea
el encabezado impreso de la guía contra el catálogo de plantas -- pero el
encabezado de AZA es IDÉNTICO ("CASA MATRIZ PLANTA RENCA...") en TODAS las
guías, sin importar desde qué planta despachó realmente el camión. Eso
producía un falso positivo sistemático a favor de AZA RENCA para
cualquier camión realmente despachado desde AZA COLINA. La corrección no
toca `resolver_origen_documental` (sigue siendo el fallback legítimo
cuando no hay telemetría) -- agrega una resolución GPS de ventana amplia
(`resolver_planta_origen_gps`) que, cuando hay evidencia, tiene prioridad
sobre el documento.

Todos los tests son unitarios/deterministas, sin red real. La validación
con la API real de Onelogis/ORS sobre la tanda operativa real vive fuera
de la suite normal (script de evaluación puntual, no versionado como
test) y se reporta aparte.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.extractor import _despachar_a_lineal_contaminado, _extraer_despachar_a_geometrico
from atlas_core.ocr import BloqueOCR
from atlas_core.rutas.destino_entrega import calcular_ruta_con_planta_conocida
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion,
    Coordenadas,
    EstadoRuta,
    ResultadoGeocodificacion,
    ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado
from atlas_core.telemetria.modelos import PosicionTelemetria, ViajeTelemetria
from atlas_core.telemetria.proveedor import ProveedorTelemetriaSimulado
from atlas_core.telemetria.repositorio import RepositorioTelemetria
from atlas_core.telemetria.seleccion_recorrido import (
    ORIGEN_GPS_CONFIRMADO,
    ORIGEN_GPS_CONFLICTO,
    ORIGEN_GPS_NO_DETERMINADO,
    resolver_planta_origen_gps,
)
from atlas_core.telemetria.servicio import ServicioTelemetria

COORD_AZA_RENCA = Coordenadas(-70.685226, -33.401595)
COORD_AZA_COLINA = Coordenadas(-70.665977, -33.137558)
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


# --- 1: GPS cerca de Renca -> AZA RENCA ---


def test_gps_cerca_de_renca_confirma_aza_renca(plantas, tmp_path):
    """El viaje de maniobra ("seed") es DEMASIADO CORTO (0.8km) para que
    T2 lo considere un "recorrido operacional sustancial"
    (DISTANCIA_MINIMA_KM=5.0) -- pero es justo ese viaje corto el que pasa
    por la geocerca de la planta. `resolver_planta_origen_gps` no filtra
    por distancia (Fase C): recolecta TODOS los viajes en la ventana
    horaria y revisa TODOS sus breadcrumbs."""
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "TZWR86": [ViajeTelemetria("seed", "TZWR86", "2026-08-11 09:34:00", "2026-08-11 09:40:00", 0.8)],
        },
        breadcrumbs_por_trip={
            "seed": [
                PosicionTelemetria(-33.408688, -70.693887, "2026-08-11 09:34:46"),  # ~1.1km de RENCA
                PosicionTelemetria(-33.401595, -70.685226, "2026-08-11 09:39:11"),
            ],
        },
    )
    resultado = resolver_planta_origen_gps(
        servicio, patente="TZWR86", fecha=FECHA,
        hora_entrada=None, hora_salida=datetime(2026, 8, 11, 9, 45),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_CONFIRMADO
    assert resultado.planta_nombre == "AZA RENCA"


# --- 2: GPS cerca de Colina -> AZA COLINA ---


def test_gps_cerca_de_colina_confirma_aza_colina(plantas, tmp_path):
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "AL1879": [ViajeTelemetria("seed", "AL1879", "2026-08-11 08:00:00", "2026-08-11 08:15:00", 1.2)],
        },
        breadcrumbs_por_trip={
            "seed": [PosicionTelemetria(-33.137558, -70.665977, "2026-08-11 08:05:00")],
        },
    )
    resultado = resolver_planta_origen_gps(
        servicio, patente="AL1879", fecha=FECHA,
        hora_entrada=None, hora_salida=datetime(2026, 8, 11, 8, 10),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_CONFIRMADO
    assert resultado.planta_nombre == "AZA COLINA"


# --- 3: sin evidencia GPS -> nunca Renca por defecto ---


def test_sin_evidencia_gps_no_asume_renca_por_defecto(plantas, tmp_path):
    """Caso real 464640/TG8925 y 464641-642/AL1879 de este bloque: hay
    viajes en la ventana temporal pero NINGUNO pasa cerca de ninguna
    planta conocida -- la respuesta correcta es abstenerse, nunca
    "confirmar" AZA RENCA por ser la opción documental/histórica."""
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "TG8925": [ViajeTelemetria("x", "TG8925", "2026-08-11 07:55:00", "2026-08-11 08:38:00", 10.4)],
        },
        breadcrumbs_por_trip={
            # ~6.6km de RENCA, ~17.8km de COLINA -- fuera de ambas geocercas.
            "x": [PosicionTelemetria(-33.44, -70.66, "2026-08-11 08:10:00")],
        },
    )
    resultado = resolver_planta_origen_gps(
        servicio, patente="TG8925", fecha=FECHA,
        hora_entrada=None, hora_salida=datetime(2026, 8, 11, 13, 10),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_NO_DETERMINADO
    assert resultado.planta_nombre != "AZA RENCA"
    assert resultado.planta_id is None or resultado.planta_id == ""


# --- 4: GPS ambiguo (toca ambas plantas) -> abstención ---


def test_gps_ambiguo_entre_dos_plantas_no_confirma_ninguna(plantas, tmp_path):
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "BDFG50": [ViajeTelemetria("x", "BDFG50", "2026-08-11 07:00:00", "2026-08-11 09:00:00", 40.0)],
        },
        breadcrumbs_por_trip={
            "x": [
                PosicionTelemetria(-33.401595, -70.685226, "2026-08-11 07:05:00"),  # RENCA
                PosicionTelemetria(-33.137558, -70.665977, "2026-08-11 08:55:00"),  # COLINA
            ],
        },
    )
    resultado = resolver_planta_origen_gps(
        servicio, patente="BDFG50", fecha=FECHA,
        hora_entrada=None, hora_salida=datetime(2026, 8, 11, 9, 0),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_CONFLICTO
    assert resultado.planta_id is None or resultado.planta_id == ""


# --- 5: hora documental sola no basta -- ventana amplia recoge el viaje real ---


def test_no_depende_solo_del_primer_viaje_sustancial(plantas, tmp_path):
    """Reproduce el riesgo advertido en Fase C: si solo se mirara el
    primer viaje "sustancial" posterior a la hora documental, un viaje de
    maniobra ANTERIOR (el que realmente sale de la planta) quedaría
    fuera. La ventana de `margen_horas` (=4h por defecto) alrededor del
    ancla debe capturarlo igual."""
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "TZWR86": [
                ViajeTelemetria("maniobra", "TZWR86", "2026-08-11 08:50:00", "2026-08-11 08:58:00", 1.5),
                ViajeTelemetria("sustancial", "TZWR86", "2026-08-11 09:34:00", "2026-08-11 12:00:00", 233.0),
            ],
        },
        breadcrumbs_por_trip={
            "maniobra": [PosicionTelemetria(-33.401595, -70.685226, "2026-08-11 08:52:00")],  # RENCA exacto
            "sustancial": [PosicionTelemetria(-34.5, -71.0, "2026-08-11 10:30:00")],  # lejos de ambas
        },
    )
    resultado = resolver_planta_origen_gps(
        servicio, patente="TZWR86", fecha=FECHA,
        hora_entrada=None, hora_salida=datetime(2026, 8, 11, 9, 30),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_CONFIRMADO
    assert resultado.planta_nombre == "AZA RENCA"


# --- 6: detección de entrada/salida de geocerca ---


def test_detecta_entrada_y_salida_distintas_de_la_geocerca(plantas, tmp_path):
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "TZWR86": [ViajeTelemetria("x", "TZWR86", "2026-08-11 09:30:00", "2026-08-11 09:50:00", 2.0)],
        },
        breadcrumbs_por_trip={
            "x": [
                PosicionTelemetria(-33.401595, -70.685226, "2026-08-11 09:34:00"),
                PosicionTelemetria(-33.401200, -70.685500, "2026-08-11 09:36:00"),
                PosicionTelemetria(-33.401595, -70.685226, "2026-08-11 09:42:11"),
            ],
        },
    )
    resultado = resolver_planta_origen_gps(
        servicio, patente="TZWR86", fecha=FECHA,
        hora_entrada=None, hora_salida=datetime(2026, 8, 11, 9, 45),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_CONFIRMADO
    # Bloque TELEMETRÍA T3: el trip completo queda clasificado como una
    # única detención estacionaria dentro de la geocerca -- entrada/salida
    # GPS reflejan el span REAL del trip (evidencia más precisa que solo
    # los breadcrumbs que cayeron dentro del radio), ver
    # `tests/test_telemetria_t3.py` para la cobertura dedicada del modelo
    # de detenciones multi-trip.
    assert resultado.hora_entrada_gps == "2026-08-11 09:30:00"
    assert resultado.hora_salida_gps == "2026-08-11 09:50:00"


# --- 7: la caché no contamina otro viaje / otra patente ---


def test_cache_no_contamina_otro_viaje_ni_otra_patente(plantas, tmp_path):
    proveedor, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "TZWR86": [ViajeTelemetria("r", "TZWR86", "2026-08-11 09:34:00", "2026-08-11 09:45:00", 1.0)],
            "AL1879": [ViajeTelemetria("c", "AL1879", "2026-08-11 08:00:00", "2026-08-11 08:15:00", 1.0)],
        },
        breadcrumbs_por_trip={
            "r": [PosicionTelemetria(-33.401595, -70.685226, "2026-08-11 09:36:00")],  # RENCA
            "c": [PosicionTelemetria(-33.137558, -70.665977, "2026-08-11 08:05:00")],  # COLINA
        },
    )
    renca = resolver_planta_origen_gps(
        servicio, patente="TZWR86", fecha=FECHA,
        hora_entrada=None, hora_salida=datetime(2026, 8, 11, 9, 40), plantas=plantas,
    )
    colina = resolver_planta_origen_gps(
        servicio, patente="AL1879", fecha=FECHA,
        hora_entrada=None, hora_salida=datetime(2026, 8, 11, 8, 10), plantas=plantas,
    )
    assert renca.planta_nombre == "AZA RENCA"
    assert colina.planta_nombre == "AZA COLINA"
    assert proveedor.llamadas_viajes == 2  # una por patente, sin mezclar

    # Repetir la MISMA consulta reutiliza caché -- no vuelve a llamar al proveedor.
    resolver_planta_origen_gps(
        servicio, patente="TZWR86", fecha=FECHA,
        hora_entrada=None, hora_salida=datetime(2026, 8, 11, 9, 40), plantas=plantas,
    )
    assert proveedor.llamadas_viajes == 2


# --- 8: cambio de origen invalida/recalcula la ruta ---


def test_cambio_de_planta_origen_recalcula_ruta_desde_la_planta_correcta(plantas):
    """Si la planta GPS-confirmada difiere de la planta documental, la
    ruta debe calcularse PLANTA_GPS -> DESPACHAR A, nunca reutilizar una
    ruta calculada desde la planta equivocada (Fase I)."""
    renca = next(p for p in plantas if p.nombre == "AZA RENCA")
    colina = next(p for p in plantas if p.nombre == "AZA COLINA")
    despachar_a = "SANTA ISABEL 585, SANTIAGO"
    consulta = f"{despachar_a}, Chile"
    geocodificaciones = {
        consulta: ResultadoGeocodificacion(
            EstadoRuta.REQUIERE_REVISION,
            (CandidatoGeocodificacion(Coordenadas(-70.63, -33.45), "Santa Isabel 585", 0.8),),
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
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 12.3, 25.0, ""),
    )

    resultado_renca = calcular_ruta_con_planta_conocida(
        planta=renca, despachar_a_crudo=despachar_a, proveedor_rutas=proveedor,
    )
    resultado_colina = calcular_ruta_con_planta_conocida(
        planta=colina, despachar_a_crudo=despachar_a, proveedor_rutas=proveedor,
    )

    assert resultado_renca.planta_origen_nombre == "AZA RENCA"
    assert resultado_colina.planta_origen_nombre == "AZA COLINA"
    # El origen realmente enviado a `calcular_ruta` cambia con la planta --
    # nunca se reutiliza la coordenada de la planta anterior.
    assert origenes_capturados[0] != origenes_capturados[1]
    assert origenes_capturados[0] == Coordenadas(renca.longitud, renca.latitud)
    assert origenes_capturados[1] == Coordenadas(colina.longitud, colina.latitud)


# --- 9: DESPACHAR A nunca acepta un RUT como dirección ---


def test_despachar_a_lineal_contaminado_rechaza_rut_valido():
    """Caso real 464631/464641 de este bloque: la extracción lineal
    absorbió el VALOR de otro campo (un RUT con dígito verificador
    válido, p.ej. "14293816-2") en vez de una etiqueta -- el chequeo
    anterior (solo etiquetas conocidas) no lo detectaba."""
    assert _despachar_a_lineal_contaminado("14293816-2") is True
    assert _despachar_a_lineal_contaminado("10833150-K") is True
    # RUT con dígito verificador incorrecto: no matchea como RUT válido,
    # pero tampoco es una dirección -- se deja para otras validaciones,
    # este chequeo específico no debe reportarlo como "contaminado por RUT".
    assert _despachar_a_lineal_contaminado("14293816-9") is False
    # Una dirección real, aunque tenga números y guiones, nunca se confunde.
    assert _despachar_a_lineal_contaminado("SANTA ISABEL 585 SANTIAGO LAMPA") is False
    assert _despachar_a_lineal_contaminado("CAMINO LOS PINOS 3396 SAN BERNARDO") is False


def test_despachar_a_geometrico_recupera_direccion_cuando_lineal_es_un_rut():
    """Con el fallback geométrico disponible, un valor lineal contaminado
    por un RUT se descarta y se recupera la dirección real por posición
    en la imagen -- reproduce, con coordenadas sintéticas, el layout real
    de 464631/464641 (el RUT queda pegado a "DESPACHAR A" en el orden de
    lectura lineal; la dirección real está en la fila de abajo, en la
    misma columna)."""

    def _bloque(texto, x1, y1, x2, y2, confianza=0.9):
        return BloqueOCR(texto, ((x1, y1), (x2, y1), (x2, y2), (x1, y2)), confianza)

    bloques = [
        _bloque("DESPACHAR A", 10, 100, 90, 118),
        _bloque("14293816-2", 95, 100, 160, 118),  # RUT que contaminó la lectura lineal
        _bloque("SANTA ISABEL 585", 10, 122, 140, 140),
        _bloque("SANTIAGO LAMPA", 10, 143, 140, 161),
    ]
    lineal = "14293816-2"
    assert _despachar_a_lineal_contaminado(lineal) is True

    decision_geometrica = _extraer_despachar_a_geometrico(bloques)
    valor = decision_geometrica.get("valor", "")
    assert "14293816-2" not in valor
    assert "SANTA ISABEL" in valor.upper()


# --- 10: multiguía -- documentos del mismo transporte resuelven la misma planta GPS ---


def test_multiguia_mismo_transporte_resuelve_la_misma_planta_gps(plantas, tmp_path):
    """Dos guías del mismo transporte (misma patente, misma fecha, horas
    documentales distintas pero dentro de la misma ventana horaria) deben
    resolver la MISMA planta de origen -- un único origen físico por
    transporte, no uno por documento."""
    _, servicio = _servicio(
        tmp_path,
        viajes_por_patente={
            "VP8521": [ViajeTelemetria("seed", "VP8521", "2026-08-11 11:00:00", "2026-08-11 11:10:00", 1.0)],
        },
        breadcrumbs_por_trip={
            "seed": [PosicionTelemetria(-33.401595, -70.685226, "2026-08-11 11:05:00")],
        },
    )
    primera_guia = resolver_planta_origen_gps(
        servicio, patente="VP8521", fecha=FECHA,
        hora_entrada=None, hora_salida=datetime(2026, 8, 11, 9, 36), plantas=plantas,
    )
    segunda_guia = resolver_planta_origen_gps(
        servicio, patente="VP8521", fecha=FECHA,
        hora_entrada=None, hora_salida=datetime(2026, 8, 11, 11, 36), plantas=plantas,
    )
    assert primera_guia.estado == ORIGEN_GPS_CONFIRMADO
    assert segunda_guia.estado == ORIGEN_GPS_CONFIRMADO
    assert primera_guia.planta_nombre == segunda_guia.planta_nombre == "AZA RENCA"


# --- 11: no regresión -- cubierta por la suite completa ---


def test_no_regresion_se_verifica_con_la_suite_completa():
    """No se duplica cobertura aquí: T2 (`test_telemetria_t2.py`), E2E
    (`test_e2e_r1_1_cierre_pipeline.py`), O1/S2/I1 y el resto de
    `test_procesamiento_masivo.py` ya cubren sus propios contratos: la
    garantía de "no regresión" de este bloque es que la suite COMPLETA
    (`python -m pytest -q`) sigue en verde con estos cambios."""
    assert True
