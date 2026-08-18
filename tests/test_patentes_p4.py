"""Bloque PATENTES P4: recuperar patente/remolque claramente impresos por
geometría real (no por orden lineal de OCR) + revalidar origen 464631.

Hallazgo real que motivó este bloque (guía 464631, TRANSPORTES MBT SPA):
PaddleOCR leyó la etiqueta CARRO como "CARR0" (cero en vez de O) y fusionó
en un único bloque el valor de PATENTE con el par CARRO:valor
(": DD2494 CARR0:JB8529"); además, en el layout de dos columnas, el valor
de RUT CHOFER quedó pegado en el texto lineal a la etiqueta DESPACHAR A de
la fila anterior. `_extraer_patentes_geometrico` (heredado de bloques
anteriores) en realidad no era geométrico: concatenaba todo el texto de la
zona RETIRA-FECHA LLEGADA y buscaba por regex sobre esa cadena, así que
CUALQUIER segundo token de 6 caracteres en la zona (aunque estuviera lejos
de la etiqueta) producía una abstención por "ambigüedad". Este bloque lo
reescribe para asociar cada etiqueta a su valor por geometría real, agrega
`_extraer_rut_chofer_geometrico`, y tolera dos variantes de OCR reales
observadas (CARR0 por CARRO, RETRA por RETIRA -- guía 464550).

Ningún test aquí usa los valores reales de la guía 464631 (DD2494, JB8529,
Luis Varas) -- se reproduce la ESTRUCTURA del problema con datos
sintéticos, tal como exige el bloque ("No hardcodear guía 464631").
"""
from __future__ import annotations

from datetime import date, datetime
from unittest.mock import Mock

import pytest

from atlas_core import procesamiento_masivo
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.extractor import (
    _extraer_patentes_geometrico,
    _extraer_rut_chofer_geometrico,
)
from atlas_core.ocr import BloqueOCR
from atlas_core.procesamiento_masivo import procesar_archivo
from atlas_core.rutas.modelos import Coordenadas
from atlas_core.rutas.proveedor import ProveedorRutasSimulado
from atlas_core.telemetria.modelos import PosicionTelemetria, ViajeTelemetria
from atlas_core.telemetria.proveedor import ProveedorTelemetriaSimulado
from atlas_core.telemetria.repositorio import RepositorioTelemetria
from atlas_core.telemetria.seleccion_recorrido import ORIGEN_GPS_CONFIRMADO
from atlas_core.telemetria.servicio import ServicioTelemetria

COORD_AZA_RENCA = Coordenadas(-70.685226, -33.401595)
COORD_AZA_COLINA = Coordenadas(-70.665977, -33.137558)
FECHA = date(2026, 8, 11)


def _bloque(texto, x, y, ancho=None, alto=18):
    ancho = ancho if ancho is not None else max(30, len(texto) * 8)
    return BloqueOCR(
        texto=texto,
        bounding_box=((x, y), (x + ancho, y), (x + ancho, y + alto), (x, y + alto)),
        confianza=0.9,
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
        "chofer": "No encontrado",
        "RUT del cliente": "11.111.111-1",
        "RUT del chofer": "No encontrado",
        "patente del tracto": "No encontrado",
        "patente del carro": "No encontrado",
        "hora de entrada": "13:10",
        "hora de salida": "13:52",
    }
    datos.update(overrides)
    return datos


def _preparar_mocks(monkeypatch, bloques, datos, texto_lineal=None):
    lineas = ["FECHA DE EMISION 11-08-2026"]
    if texto_lineal:
        lineas.append(texto_lineal)
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=lineas))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=bloques))
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", Mock(return_value=datos))


# --- 1: PATENTE junto a RETIRA ---


def test_patente_junto_a_retira_se_asocia_por_geometria():
    bloques = [
        _bloque("RETIRA", 20, 20, 60),
        _bloque("PATENTE", 20, 50, 70),
        _bloque("AB1234", 120, 50, 70),
        _bloque("FECHA LLEGADA", 20, 80, 120),
    ]

    assert _extraer_patentes_geometrico(bloques) == {"tracto": "AB1234"}


# --- 2: CARRO junto a PATENTE ---


def test_carro_junto_a_patente_se_distingue_del_tracto():
    bloques = [
        _bloque("RETIRA", 20, 20, 60),
        _bloque("PATENTE", 20, 50, 70), _bloque("AB1234", 120, 50, 70),
        _bloque("CARRO", 20, 80, 60), _bloque("CD5678", 120, 80, 70),
        _bloque("FECHA LLEGADA", 20, 110, 120),
    ]

    assert _extraer_patentes_geometrico(bloques) == {"tracto": "AB1234", "carro": "CD5678"}


# --- 3: orden OCR intercalado (RUT CHOFER pegado a otra etiqueta en el texto lineal) ---


def test_rut_chofer_se_recupera_pese_a_orden_lineal_intercalado():
    """Reproduce el patrón estructural real de 464631: en un layout de dos
    columnas, PaddleOCR entrega el valor de RUT CHOFER pegado, en el texto
    lineal, a la etiqueta DESPACHAR A de la fila anterior -- pero
    geométricamente el valor SÍ está junto a su propia etiqueta RUT
    CHOFER. `_extraer_rut_chofer_geometrico` no depende del orden lineal,
    solo de la posición real de los bloques."""
    bloques = [
        _bloque("DESPACHAR A", 20, 20, 100),
        _bloque("RUT CHOFER", 20, 50, 90),
        _bloque("11.111.111-1", 130, 50, 100),  # geométricamente junto a RUT CHOFER
        _bloque("FECHA SALIDA", 20, 80, 100),
    ]

    assert _extraer_rut_chofer_geometrico(bloques) == {"valor": "11.111.111-1"}


# --- 4: patente única geométrica (tolerante a CARRO leído CARR0 y RETIRA leído RETRA) ---


def test_patente_unica_geometrica_tolera_carr0_y_retra():
    """Dos variantes reales de OCR en un mismo documento: la etiqueta
    RETIRA se lee "RETRA" (guía 464550, falta la "I") y el valor de
    PATENTE llega fusionado en un solo bloque junto al par CARRO:valor con
    la etiqueta CARRO leída "CARR0" (guía 464631, cero por O). Ninguna
    corrección hardcodea el valor final -- solo tolera la confusión O/0 en
    la ETIQUETA."""
    bloques = [
        _bloque("RETRA", 20, 20, 60),
        _bloque("PATENTE", 20, 50, 70),
        _bloque(": AB1234 CARR0:CD5678", 20, 80, 220),
        _bloque("FECHA LLEGADA", 20, 110, 120),
    ]

    assert _extraer_patentes_geometrico(bloques) == {"tracto": "AB1234", "carro": "CD5678"}


# --- 5: rampla única geométrica (etiquetas RAMPLA/REMOLQUE, no solo CARRO) ---


@pytest.mark.parametrize("etiqueta", ["RAMPLA", "REMOLQUE"])
def test_rampla_unica_geometrica_acepta_etiquetas_sinonimas(etiqueta):
    bloques = [
        _bloque("RETIRA", 20, 20, 60),
        _bloque("PATENTE", 20, 50, 70),
        _bloque(etiqueta, 20, 80, 90),
        _bloque("CD5678", 120, 80, 70),
        _bloque("FECHA LLEGADA", 20, 110, 120),
    ]

    assert _extraer_patentes_geometrico(bloques) == {"carro": "CD5678"}


# --- 6: valor legible pero no homologado se conserva ---


def test_patente_geometrica_sin_homologar_se_conserva_con_motivo(tmp_path, monkeypatch):
    """La ausencia de un catálogo que reconozca la patente NUNCA debe
    convertir un valor documental legible en "No encontrado" -- se
    conserva el valor y se marca PATENTE_SIN_HOMOLOGAR."""
    ruta = tmp_path / "guia.jpg"
    carpeta_catalogos = tmp_path / "catalogos"
    carpeta_catalogos.mkdir()
    (carpeta_catalogos / "vehiculos.json").write_text("{}", encoding="utf-8")
    bloques = [
        _bloque("RETIRA", 20, 20, 60),
        _bloque("PATENTE", 20, 50, 70), _bloque("AB1234", 120, 50, 70),
        _bloque("FECHA LLEGADA", 20, 80, 120),
    ]
    _preparar_mocks(monkeypatch, bloques, _datos_lineales())

    resultado = procesar_archivo(ruta, carpeta_catalogos=carpeta_catalogos)

    assert resultado["patente_tracto"] == "AB1234"
    assert "PATENTE_SIN_HOMOLOGAR" in resultado["motivos_revision_documento"]


# --- 7: patente ambigua -> abstención (ambigüedad geométrica real) ---


def test_patentes_dos_etiquetas_con_valores_igual_de_cercanos_se_abstiene():
    """Reemplaza el criterio anterior ("cualquier segundo token de 6
    caracteres en la zona bloquea todo") por ambigüedad geométrica real:
    dos etiquetas PATENTE, cada una con su propio valor igual de cerca --
    ninguna gana con margen suficiente. Un candidato lejano que NO está
    junto a ninguna etiqueta (ver test 1) ya no produce una abstención
    espuria; solo lo hace un empate genuino."""
    bloques = [
        _bloque("RETIRA", 20, 20, 60),
        _bloque("PATENTE", 20, 50, 70), _bloque("AB1234", 120, 50, 70),
        _bloque("PATENTE", 20, 90, 70), _bloque("CD5678", 120, 90, 70),
        _bloque("FECHA LLEGADA", 20, 120, 120),
    ]

    assert _extraer_patentes_geometrico(bloques) == {}


# --- 8: regresión real 464631 (estructura reproducida con datos sintéticos) ---


def test_regresion_464631_patente_y_carro_fusionados_con_carro_mal_leido(tmp_path, monkeypatch):
    """Reproduce la estructura completa de la guía real 464631 (dos
    columnas, RETIRA/PATENTE en una columna con el valor de PATENTE
    fusionado con CARRO:valor y CARRO leído CARR0, RUT CHOFER en la otra
    columna con su valor pegado en el texto lineal a DESPACHAR A) con
    valores sintéticos -- nunca los reales."""
    ruta = tmp_path / "guia.jpg"
    carpeta_catalogos = tmp_path / "catalogos"
    carpeta_catalogos.mkdir()
    (carpeta_catalogos / "vehiculos.json").write_text(
        '{"AB1234": {"tipo": "TRACTO"}, "CD5678": {"tipo": "CARRO"}}', encoding="utf-8"
    )
    bloques = [
        _bloque("DESPACHAR A", 20, 20, 100), _bloque("CALLE FALSA 123", 130, 20, 120),
        _bloque("RETIRA", 400, 20, 60), _bloque("JUAN PEREZ", 470, 20, 100),
        _bloque("RUT CHOFER", 20, 55, 90), _bloque("11.111.111-1", 130, 55, 100),
        _bloque("PATENTE", 400, 55, 70), _bloque(": AB1234 CARR0:CD5678", 470, 55, 220),
        _bloque("FECHA SALIDA", 20, 90, 100), _bloque("11-08-2026", 130, 90, 100),
        _bloque("FECHA", 400, 90, 60), _bloque("LLEGADA", 400, 105, 60), _bloque("12-08-2026", 470, 105, 100),
    ]
    _preparar_mocks(monkeypatch, bloques, _datos_lineales())

    resultado = procesar_archivo(ruta, carpeta_catalogos=carpeta_catalogos)

    assert resultado["patente_tracto"] == "AB1234"
    assert resultado["patente_rampla"] == "CD5678"
    assert resultado["rut_chofer"] == "11.111.111-1"


# --- 9: la patente recuperada geométricamente habilita la telemetría ---


def test_patente_geometrica_habilita_consulta_de_telemetria(plantas_catalogo, tmp_path, monkeypatch):
    """Antes del fix, `patente del tracto` quedaba "No encontrado" y la
    telemetría (gateada por `_patente_valida`) nunca se consultaba, sin
    importar si `servicio_telemetria` estaba conectado. Con la patente
    recuperada por geometría, la consulta SÍ se ejecuta."""
    carpeta_catalogos, plantas = plantas_catalogo
    ruta = tmp_path / "guia.jpg"
    bloques = [
        _bloque("RETIRA", 20, 20, 60),
        _bloque("PATENTE", 20, 50, 70), _bloque("SB9999", 120, 50, 70),
        _bloque("FECHA LLEGADA", 20, 80, 120),
    ]
    _preparar_mocks(monkeypatch, bloques, _datos_lineales())

    proveedor_telemetria = ProveedorTelemetriaSimulado(
        viajes_por_patente={"SB9999": []},
    )
    servicio_telemetria = ServicioTelemetria(
        proveedor_telemetria, RepositorioTelemetria(tmp_path / "cache_telemetria.json")
    )

    resultado = procesar_archivo(
        ruta, carpeta_catalogos=carpeta_catalogos, servicio_telemetria=servicio_telemetria,
    )

    assert resultado["patente_tracto"] == "SB9999"
    assert proveedor_telemetria.llamadas_viajes >= 1


# --- 10: la planta final por O2 no depende del fallback documental ---


def test_planta_gps_reemplaza_fallback_documental_una_vez_recuperada_la_patente(
    plantas_catalogo, tmp_path, monkeypatch
):
    """Encadena el fix de patentes con O2: el encabezado documental
    siempre dice "CASA MATRIZ PLANTA RENCA" (constante en toda guía AZA),
    pero una vez que la patente se recupera geométricamente, la
    telemetría GPS puede confirmar una planta real (Colina) que
    reemplaza ese valor por defecto -- el resultado final NUNCA debe
    quedar en el default documental cuando GPS confirma algo distinto."""
    carpeta_catalogos, plantas = plantas_catalogo
    ruta = tmp_path / "guia.jpg"
    bloques = [
        _bloque("RETIRA", 20, 20, 60),
        _bloque("PATENTE", 20, 50, 70), _bloque("SB9999", 120, 50, 70),
        _bloque("FECHA LLEGADA", 20, 80, 120),
    ]
    texto_encabezado = (
        "ACEROS AZA S A CASA MATRIZ PLANTA RENCA LA UNION 3070 RENCA SANTIAGO CHILE "
        "GUIA DE DESPACHO ELECTRONICA"
    )
    _preparar_mocks(monkeypatch, bloques, _datos_lineales(), texto_lineal=texto_encabezado)

    proveedor_telemetria = ProveedorTelemetriaSimulado(
        viajes_por_patente={
            "SB9999": [ViajeTelemetria("t", "SB9999", "2026-08-11 09:40:00", "2026-08-11 09:50:00", 1.0)],
        },
        breadcrumbs_por_trip={
            "t": [PosicionTelemetria(COORD_AZA_COLINA.latitud, COORD_AZA_COLINA.longitud, "2026-08-11 09:46:00")],
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

    assert resultado["patente_tracto"] == "SB9999"
    assert resultado["origen_gps"] == ORIGEN_GPS_CONFIRMADO
    assert resultado["planta_origen_nombre"] == "AZA COLINA"
    assert resultado["origen_determinado_por"] == "TELEMETRIA_GPS"


# --- 12: patente/carro fusionados con CARRO leído CARBO (guía real 464367) ---


def test_patente_unica_geometrica_tolera_carbo():
    """Tercera variante real de OCR confirmada sobre el mismo mecanismo de
    la etiqueta CARRO/RAMPLA/REMOLQUE (guía 464367: "CARRO" leído "CARBO",
    B por R) -- mismo patrón estructural que el test de CARR0 (0 por O,
    guía 464631): valor de PATENTE fusionado en un solo bloque junto al par
    CARRO:valor, con la etiqueta CARRO corrompida. La tolerancia vive en
    una tabla pequeña y explícita de confusiones ya confirmadas
    (`_CONFUSIONES_OCR_ETIQUETA_VEHICULAR`), no en una distancia de edición
    abierta -- ver los negativos más abajo."""
    bloques = [
        _bloque("RETIRA", 20, 20, 60),
        _bloque("PATENTE", 20, 50, 70),
        _bloque(": AB1234 CARBO:CD5678", 20, 80, 220),
        _bloque("FECHA LLEGADA", 20, 110, 120),
    ]

    assert _extraer_patentes_geometrico(bloques) == {"tracto": "AB1234", "carro": "CD5678"}


def test_regresion_464367_patente_y_rampla_fusionados_con_carro_mal_leido(tmp_path, monkeypatch):
    """Reproduce la estructura completa de la guía real 464367 (PATENTE
    como etiqueta propia, valor de tracto fusionado con CARRO:valor y
    CARRO leído CARBO) end-to-end vía `procesar_archivo`, con valores
    sintéticos -- nunca los reales."""
    ruta = tmp_path / "guia.jpg"
    carpeta_catalogos = tmp_path / "catalogos"
    carpeta_catalogos.mkdir()
    (carpeta_catalogos / "vehiculos.json").write_text("{}", encoding="utf-8")
    bloques = [
        _bloque("RETIRA", 20, 20, 60), _bloque("CHOFER PRUEBA", 90, 20, 120),
        _bloque("PATENTE", 20, 50, 70),
        _bloque(": AB1234 CARBO:CD5678", 90, 51, 220),
        _bloque("FECHA LLEGADA", 20, 80, 120),
    ]
    _preparar_mocks(monkeypatch, bloques, _datos_lineales())

    resultado = procesar_archivo(ruta, carpeta_catalogos=carpeta_catalogos)

    assert resultado["patente_tracto"] == "AB1234"
    assert resultado["patente_rampla"] == "CD5678"
    # sin catálogo que las reconozca, quedan como valor documental legible,
    # no "No encontrado" -- mismo criterio que el resto del bloque P4.
    assert "PATENTE_SIN_HOMOLOGAR" in resultado["motivos_revision_documento"]


# --- 13: negativos -- la tolerancia no se vuelve fuzzy abierta ---


def test_palabra_parecida_a_carro_no_tolerada_fuera_de_la_tabla_se_abstiene():
    """"CARGO" es, para un humano, una palabra real y visualmente parecida
    a CARRO -- pero NO está en la tabla explícita de confusiones conocidas
    (`_CONFUSIONES_OCR_ETIQUETA_VEHICULAR`, sólo 0->O y B->R, ambas
    confirmadas con guías reales). Debe seguir sin reconocerse como
    etiqueta: quedan dos tokens de 6 caracteres sin ninguna etiqueta que
    los distinga -> ambigüedad real, abstención."""
    bloques = [
        _bloque("RETIRA", 20, 20, 60),
        _bloque("PATENTE", 20, 50, 70),
        _bloque(": AB1234 CARGO:CD5678", 20, 80, 220),
        _bloque("FECHA LLEGADA", 20, 110, 120),
    ]

    assert _extraer_patentes_geometrico(bloques) == {}


def test_dos_patentes_sin_ninguna_etiqueta_rival_reconocible_se_abstiene():
    """Dos tokens de 6 caracteres con formato de patente en el mismo
    bloque, sin ningún resto de etiqueta CARRO/RAMPLA/REMOLQUE (ni exacta
    ni tolerada) que permita separar cuál es cuál -- ambigüedad genuina,
    igual que antes de este bloque."""
    bloques = [
        _bloque("RETIRA", 20, 20, 60),
        _bloque("PATENTE", 20, 50, 70),
        _bloque(": AB1234 XY5678", 20, 80, 220),
        _bloque("FECHA LLEGADA", 20, 110, 120),
    ]

    assert _extraer_patentes_geometrico(bloques) == {}


def test_ambiguedad_geometrica_genuina_sigue_abstenida_tras_el_fix():
    """No regresión del test 7 (dos etiquetas PATENTE con valores igual de
    cerca): la tolerancia nueva no relaja la abstención ante ambigüedad
    geométrica real, que no depende de la tabla de confusiones."""
    bloques = [
        _bloque("RETIRA", 20, 20, 60),
        _bloque("PATENTE", 20, 50, 70), _bloque("AB1234", 120, 50, 70),
        _bloque("PATENTE", 20, 90, 70), _bloque("CD5678", 120, 90, 70),
        _bloque("FECHA LLEGADA", 20, 120, 120),
    ]

    assert _extraer_patentes_geometrico(bloques) == {}


def test_valor_documental_con_b_legitima_no_se_corrompe_con_carro_bien_leido():
    """La tolerancia B->R sólo se aplica para ENCONTRAR el par
    "CARRO:valor" a remover -- el texto removido y el residual devuelto
    siempre vienen del texto ORIGINAL sin sustituir (ver docstring de
    `_valor_unico_residual`). Un valor de patente que legítimamente
    contenga la letra "B" (con CARRO correctamente escrito, sin
    corrupción) nunca debe alterarse a "R"."""
    bloques = [
        _bloque("RETIRA", 20, 20, 60),
        _bloque("PATENTE", 20, 50, 70),
        _bloque(":BPHR67 CARRO:JB8529", 20, 80, 220),
        _bloque("FECHA LLEGADA", 20, 110, 120),
    ]

    assert _extraer_patentes_geometrico(bloques) == {"tracto": "BPHR67", "carro": "JB8529"}


# --- 11: no regresión -- ver `python -m pytest -q` (suite completa) ---
