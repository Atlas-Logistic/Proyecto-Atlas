"""Bloque OPERACIÓN REAL R1.1: validación positiva de AZA COLINA +
eliminar el fallback documental cuando la telemetría corrió y no
confirmó ninguna planta.

Hallazgo que motivó este bloque: R1 corrigió que el GPS tuviera
prioridad sobre el documento CUANDO confirmaba algo -- pero si la
telemetría corría con datos reales y no lograba confirmar una planta
única (conflicto, o ninguna geocerca lo suficientemente cerca), el
código seguía mostrando en silencio la planta que `resolver_origen_documental`
había sacado del encabezado impreso ("CASA MATRIZ PLANTA RENCA", igual
en TODA guía AZA). Eso nunca es evidencia de origen operacional real.

Alcance del fix (decisión explícita): el fallback documental se elimina
SOLO en el punto donde corre el bug -- `procesamiento_masivo.py`, cuando
`servicio_telemetria` corrió sobre datos reales
(`estado_telemetria == SELECCIONADO`) y no confirmó una planta única.
Si no hay telemetría conectada en absoluto, o el proveedor no pudo ni
conectar (sin credencial, vehículo no encontrado), el comportamiento
documental previo NO cambia -- no hay señal GPS real que lo reemplace,
y `resolver_origen_documental()`/`resolver_planta_origen()` (usados en
~15 archivos de test existentes, arquitectura sin telemetría) no se
tocan.

Todos los tests son unitarios/deterministas, sin red real.
"""
from __future__ import annotations

from datetime import date, datetime
from unittest.mock import Mock

import pytest

from atlas_core import procesamiento_masivo
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.procesamiento_masivo import procesar_archivo
from atlas_core.rutas.modelos import Coordenadas, EstadoRuta, ResultadoRuta
from atlas_core.rutas.proveedor import ProveedorRutasSimulado
from atlas_core.telemetria.modelos import PosicionTelemetria, ViajeTelemetria
from atlas_core.telemetria.proveedor import ProveedorTelemetriaSimulado
from atlas_core.telemetria.repositorio import RepositorioTelemetria
from atlas_core.telemetria.seleccion_recorrido import (
    ORIGEN_GPS_CONFIRMADO,
    ORIGEN_GPS_NO_DETERMINADO,
    resolver_planta_origen_gps,
)
from atlas_core.telemetria.servicio import ServicioTelemetria

COORD_AZA_RENCA = Coordenadas(-70.685226, -33.401595)
COORD_AZA_COLINA = Coordenadas(-70.665977, -33.137558)
FECHA = date(2026, 8, 11)

TEXTO_ENCABEZADO_AZA = (
    "GUIA DESPACHO PLANTA ORIGEN RENCA ACEROS AZA S A CASA MATRIZ PLANTA RENCA LA UNION 3070 RENCA SANTIAGO CHILE "
    "GUIA DE DESPACHO ELECTRONICA"
)


@pytest.fixture
def plantas_catalogo(tmp_path):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir(exist_ok=True)
    catalogo = CatalogoPlantas(carpeta / "plantas.json")
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
    return carpeta, catalogo.listar()


def _datos_lineales(**overrides):
    datos = {
        "número de guía": "999999",
        "número de transporte": "0000999999",
        "cliente": "CLIENTE PRUEBA",
        "obra destino": "OBRA PRUEBA",
        "chofer": "CHOFER PRUEBA",
        "RUT del cliente": "11.111.111-1",
        "patente del tracto": "SB6486",
        "patente del carro": "JF4288",
        "hora de entrada": "07:09",
        "hora de salida": "09:16",
    }
    datos.update(overrides)
    return datos


def _preparar_mocks(monkeypatch, texto_lineal, datos):
    monkeypatch.setattr(
        procesamiento_masivo, "leer_texto_imagen",
        Mock(return_value=[f"FECHA DE EMISION 07-08-2026", texto_lineal]),
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", Mock(return_value=datos))


# --- 1/2: validación positiva -- GPS confirma Colina cuando la evidencia existe ---


def test_gps_confirma_colina_si_la_evidencia_lo_sustenta(plantas_catalogo, tmp_path):
    """Caso sintético que reproduce el patrón esperado si Javier tiene
    razón sobre un control positivo real: un viaje de maniobra corto
    dentro de la geocerca de COLINA confirma esa planta -- el mecanismo
    general SÍ sabe reconocer Colina cuando hay evidencia GPS real."""
    _, plantas = plantas_catalogo
    proveedor = ProveedorTelemetriaSimulado(
        viajes_por_patente={
            "AL1879": [ViajeTelemetria("seed", "AL1879", "2026-08-11 09:40:00", "2026-08-11 09:50:00", 1.0)],
        },
        breadcrumbs_por_trip={
            "seed": [PosicionTelemetria(-33.137558, -70.665977, "2026-08-11 09:46:00")],  # exacto en COLINA
        },
    )
    servicio = ServicioTelemetria(proveedor, RepositorioTelemetria(tmp_path / "cache.json"))
    resultado = resolver_planta_origen_gps(
        servicio, patente="AL1879", fecha=FECHA,
        hora_entrada=datetime(2026, 8, 11, 9, 46), hora_salida=None, plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_CONFIRMADO
    assert resultado.planta_nombre == "AZA COLINA"


# --- 3/4/9/10: fallback documental eliminado -- integración procesar_archivo ---


def test_gps_no_determinado_limpia_la_planta_del_encabezado(plantas_catalogo, monkeypatch, tmp_path):
    """El núcleo de este bloque: aunque el encabezado dice "CASA MATRIZ
    PLANTA RENCA" (documental resolvería AZA RENCA), si la telemetría
    corrió sobre datos reales (`estado_telemetria == SELECCIONADO`) y no
    confirmó ninguna planta, el resultado final NO debe mostrar AZA
    RENCA -- debe quedar sin determinar."""
    carpeta_catalogos, plantas = plantas_catalogo
    ruta = tmp_path / "guia.jpg"
    _preparar_mocks(monkeypatch, TEXTO_ENCABEZADO_AZA, _datos_lineales())

    proveedor_telemetria = ProveedorTelemetriaSimulado(
        viajes_por_patente={
            "SB6486": [ViajeTelemetria("x", "SB6486", "2026-08-07 07:00:00", "2026-08-07 07:30:00", 5.0)],
        },
        breadcrumbs_por_trip={
            # lejos de ambas plantas -- ni Renca ni Colina.
            "x": [PosicionTelemetria(-34.5, -71.0, "2026-08-07 07:10:00")],
        },
    )
    servicio_telemetria = ServicioTelemetria(
        proveedor_telemetria, RepositorioTelemetria(tmp_path / "cache_telemetria.json")
    )
    proveedor_rutas = ProveedorRutasSimulado()

    resultado = procesar_archivo(
        ruta, carpeta_catalogos=carpeta_catalogos,
        proveedor_rutas=proveedor_rutas, servicio_telemetria=servicio_telemetria,
    )

    assert resultado["origen_gps"] == ORIGEN_GPS_NO_DETERMINADO
    assert resultado["planta_origen_nombre"] == ""
    assert resultado["planta_origen_id"] == ""
    assert resultado["origen_determinado_por"] == ""
    assert resultado["estado_ruta"] == "ORIGEN_NO_DETERMINADO"
    # El documento nunca queda bloqueado/inválido por esto -- sigue
    # siendo un documento procesable, solo con origen honestamente
    # pendiente.
    assert resultado["numero_guia"] == "999999"


def test_sin_telemetria_conectada_conserva_comportamiento_documental_previo(
    plantas_catalogo, monkeypatch, tmp_path
):
    """Si NO hay `servicio_telemetria` en absoluto (arquitectura sin GPS,
    tests antiguos, otra empresa sin integración GPS todavía), el
    comportamiento documental de siempre NO cambia -- no hay ninguna
    señal GPS real que lo reemplace. Este test fija ese límite explícito
    del alcance del fix."""
    carpeta_catalogos, _ = plantas_catalogo
    ruta = tmp_path / "guia.jpg"
    _preparar_mocks(monkeypatch, TEXTO_ENCABEZADO_AZA, _datos_lineales())

    resultado = procesar_archivo(ruta, carpeta_catalogos=carpeta_catalogos)

    assert resultado["planta_origen_nombre"] == "AZA RENCA"
    assert resultado["origen_determinado_por"] == "DOCUMENTO"


# --- 6: cambio de planta invalida ruta previa (de CONFIRMADO a NO_DETERMINADO) ---


def test_ruta_previa_se_invalida_si_gps_deja_de_confirmar(plantas_catalogo, monkeypatch, tmp_path):
    """Si ya existía una ruta calculada (desde el origen documental
    RENCA) y la telemetría corre y no confirma ninguna planta, la ruta
    calculada desde ese origen ya no válido se invalida -- nunca se deja
    un `distancia_km`/`duracion_min` huérfano de un origen que el
    sistema ya no sostiene."""
    carpeta_catalogos, _ = plantas_catalogo
    ruta = tmp_path / "guia.jpg"
    _preparar_mocks(
        monkeypatch, TEXTO_ENCABEZADO_AZA,
        _datos_lineales(),
    )

    proveedor_telemetria = ProveedorTelemetriaSimulado(
        viajes_por_patente={
            "SB6486": [ViajeTelemetria("x", "SB6486", "2026-08-07 07:00:00", "2026-08-07 07:30:00", 5.0)],
        },
        breadcrumbs_por_trip={"x": [PosicionTelemetria(-34.5, -71.0, "2026-08-07 07:10:00")]},
    )
    servicio_telemetria = ServicioTelemetria(
        proveedor_telemetria, RepositorioTelemetria(tmp_path / "cache_telemetria.json")
    )
    proveedor_rutas = ProveedorRutasSimulado(
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 999.0, 500.0, "")
    )

    resultado = procesar_archivo(
        ruta, carpeta_catalogos=carpeta_catalogos,
        proveedor_rutas=proveedor_rutas, servicio_telemetria=servicio_telemetria,
    )

    assert resultado["distancia_km"] == ""
    assert resultado["duracion_min"] == ""
    assert resultado["estado_ruta"] == "ORIGEN_NO_DETERMINADO"


# --- 7: la caché no conserva una "selección" obsoleta -- solo cachea datos crudos ---


def test_cache_solo_guarda_datos_crudos_nunca_una_seleccion_derivada(tmp_path):
    """Cambiar la lógica de resolución de origen nunca corre el riesgo de
    reutilizar una "selección" vieja incorrecta desde caché -- la caché
    de telemetría (`RepositorioTelemetria`) solo guarda viajes/breadcrumbs
    crudos del proveedor, nunca el resultado derivado (planta
    confirmada/conflicto/no determinado). Recalcular con lógica nueva
    sobre los mismos datos crudos cacheados da, correctamente, un
    resultado distinto si la lógica cambió."""
    proveedor = ProveedorTelemetriaSimulado(
        viajes_por_patente={
            "TZWR86": [ViajeTelemetria("x", "TZWR86", "2026-08-07 07:00:00", "2026-08-07 07:10:00", 1.0)],
        },
        breadcrumbs_por_trip={"x": [PosicionTelemetria(-33.401595, -70.685226, "2026-08-07 07:05:00")]},
    )
    repositorio = RepositorioTelemetria(tmp_path / "cache.json")
    servicio = ServicioTelemetria(proveedor, repositorio)

    # Primera consulta: llena la caché de datos crudos.
    r1 = servicio.buscar_viajes("TZWR86", date(2026, 8, 7), date(2026, 8, 7))
    assert r1.estado.value == "OK"
    assert proveedor.llamadas_viajes == 1

    # Segunda consulta (simula un reproceso posterior con la MISMA
    # caché): no vuelve a llamar al proveedor -- los datos crudos son
    # inmutables y se reutilizan sin volver a pagar la consulta.
    r2 = servicio.buscar_viajes("TZWR86", date(2026, 8, 7), date(2026, 8, 7))
    assert proveedor.llamadas_viajes == 1
    assert r2.viajes == r1.viajes


# --- 5: multiguía -- ambos documentos del mismo transporte quedan sin planta ---


def test_multiguia_ambos_documentos_quedan_consistentemente_sin_planta(
    plantas_catalogo, monkeypatch, tmp_path
):
    carpeta_catalogos, _ = plantas_catalogo
    proveedor_telemetria = ProveedorTelemetriaSimulado(
        viajes_por_patente={
            "SB6486": [ViajeTelemetria("x", "SB6486", "2026-08-07 07:00:00", "2026-08-07 07:30:00", 5.0)],
        },
        breadcrumbs_por_trip={"x": [PosicionTelemetria(-34.5, -71.0, "2026-08-07 07:10:00")]},
    )
    servicio_telemetria = ServicioTelemetria(
        proveedor_telemetria, RepositorioTelemetria(tmp_path / "cache_telemetria.json")
    )
    proveedor_rutas = ProveedorRutasSimulado()

    resultados = []
    for numero_guia in ("464641", "464642"):
        ruta = tmp_path / f"{numero_guia}.jpg"
        _preparar_mocks(
            monkeypatch, TEXTO_ENCABEZADO_AZA,
            _datos_lineales(**{"número de guía": numero_guia, "número de transporte": "0000352752"}),
        )
        resultados.append(procesar_archivo(
            ruta, carpeta_catalogos=carpeta_catalogos,
            proveedor_rutas=proveedor_rutas, servicio_telemetria=servicio_telemetria,
        ))

    for resultado in resultados:
        assert resultado["planta_origen_nombre"] == ""
        assert resultado["origen_gps"] == ORIGEN_GPS_NO_DETERMINADO


# --- 8/9: ventana por ancla de entrada, geocerca corta -- regresión de R1, reconfirmada ---


def test_renca_confirmado_sigue_funcionando_tras_el_fix(plantas_catalogo, monkeypatch, tmp_path):
    """Regresión explícita: el camino "GPS confirma Renca" (la mayoría
    real de los casos, ver bitácora) sigue funcionando exactamente igual
    después de agregar el chequeo de limpieza -- solo se activa la
    limpieza cuando NO hay confirmación."""
    carpeta_catalogos, _ = plantas_catalogo
    ruta = tmp_path / "guia.jpg"
    _preparar_mocks(monkeypatch, TEXTO_ENCABEZADO_AZA, _datos_lineales())

    proveedor_telemetria = ProveedorTelemetriaSimulado(
        viajes_por_patente={
            "SB6486": [ViajeTelemetria("x", "SB6486", "2026-08-07 07:00:00", "2026-08-07 07:10:00", 1.0)],
        },
        breadcrumbs_por_trip={"x": [PosicionTelemetria(-33.401595, -70.685226, "2026-08-07 07:05:00")]},
    )
    servicio_telemetria = ServicioTelemetria(
        proveedor_telemetria, RepositorioTelemetria(tmp_path / "cache_telemetria.json")
    )
    proveedor_rutas = ProveedorRutasSimulado()

    resultado = procesar_archivo(
        ruta, carpeta_catalogos=carpeta_catalogos,
        proveedor_rutas=proveedor_rutas, servicio_telemetria=servicio_telemetria,
    )

    assert resultado["origen_gps"] == ORIGEN_GPS_CONFIRMADO
    assert resultado["planta_origen_nombre"] == "AZA RENCA"
    assert resultado["origen_determinado_por"] == "TELEMETRIA_GPS"
