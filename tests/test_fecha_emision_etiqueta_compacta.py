"""Fecha de emisión con etiqueta compacta ("FECHA DEEMISION").

RapidOCR (camino Mobile/PULL) puede omitir espacios dentro de la etiqueta.
Sin reconocerla, la fecha de emisión pierde prioridad frente a otra fecha del
pie (salida/llegada) y la corroboración geométrica se abstiene. Datos
sintéticos con la disposición relativa observada en el diagnóstico de
experimentos_atlas_ia/diagnostico_fecha_emision/.
"""

import pytest

from atlas_core.extractor import _extraer_fecha_geometrico
from atlas_core.ocr import BloqueOCR
from atlas_core.procesamiento_masivo import _clasificar_contexto_fecha, _normalizar, extraer_fecha

EMISION, LLEGADA, SALIDA = "01-01-2030", "02-01-2030", "03-01-2030"


def _bloque(texto, x0, y0, x1, y1):
    return BloqueOCR(texto=texto, bounding_box=((x0, y0), (x1, y0), (x1, y1), (x0, y1)), confianza=0.95)


def _guia(etiqueta_emision):
    # Encabezado con emisión; pie con FECHA SALIDA sin valor legible y LLEGADA
    # separada de "FECHA", como entregó el OCR en el caso observado.
    return [
        (etiqueta_emision, 346, 1021, 707, 1076),
        (EMISION, 846, 1036, 1116, 1090),
        ("SENOR(ES)", 346, 1080, 600, 1125),
        ("CLIENTE SINTETICO SA", 846, 1085, 1300, 1130),
        ("FECHA", 1836, 2791, 1977, 2841),
        ("FECHA SALIDA", 280, 2812, 568, 2864),
        ("LLEGADA", 1836, 2837, 2023, 2881),
        (LLEGADA, 2081, 2818, 2319, 2860),
    ]


def _textos(lineas):
    return [texto for texto, *_ in lineas]


def _bloques(lineas):
    return [_bloque(*linea) for linea in lineas]


def _clasificar(texto, candidato):
    normalizado = _normalizar(texto)
    inicio = normalizado.index(candidato)
    return _clasificar_contexto_fecha(normalizado, inicio, inicio + len(candidato))


ETIQUETAS_COMPACTAS = ("FECHA DEEMISION", "FECHADE EMISION", "FECHADEEMISION", "FECHAEMISION", "FECHA DEEMISIÓN")


@pytest.mark.parametrize("etiqueta", ETIQUETAS_COMPACTAS)
def test_regresion_emision_compacta_no_toma_fecha_de_llegada(etiqueta):
    lineas = _guia(etiqueta)

    assert extraer_fecha(_textos(lineas)) == EMISION
    assert _extraer_fecha_geometrico(_bloques(lineas))["valor"] == EMISION


@pytest.mark.parametrize("etiqueta", ("FECHA DE EMISION", "FECHA DE EMISIÓN", "FECHA EMISION"))
def test_etiquetas_normales_siguen_reconocidas(etiqueta):
    lineas = _guia(etiqueta)

    assert extraer_fecha(_textos(lineas)) == EMISION
    assert _extraer_fecha_geometrico(_bloques(lineas))["valor"] == EMISION


@pytest.mark.parametrize("etiqueta", ETIQUETAS_COMPACTAS)
def test_clasificacion_compacta_es_emision(etiqueta):
    assert _clasificar(f"{etiqueta}\n{EMISION}", EMISION) == (0, "FECHA DE EMISION")


@pytest.mark.parametrize(
    "etiqueta, esperado",
    (
        ("FECHASALIDA", (1, "FECHA SALIDA")),
        ("FECHA DESALIDA", (1, "FECHA SALIDA")),
        ("FECHALLEGADA", (2, "FECHA LLEGADA")),
        ("FECHA DELLEGADA", (2, "FECHA LLEGADA")),
    ),
)
def test_salida_y_llegada_compactas_conservan_su_distincion(etiqueta, esperado):
    assert _clasificar(f"{etiqueta}\n{SALIDA}", SALIDA) == esperado


def test_emision_compacta_prioriza_sobre_salida_legible():
    textos = ["FECHA DEEMISION", EMISION, "FECHA SALIDA", SALIDA, "FECHA LLEGADA", LLEGADA]

    assert extraer_fecha(textos) == EMISION


def test_geometria_compacta_se_abstiene_si_el_candidato_esta_junto_a_salida():
    bloques = [
        _bloque("FECHADEEMISION", 20, 20, 170, 38),
        _bloque("FECHASALIDA", 20, 60, 140, 78),
        _bloque(EMISION, 190, 60, 280, 78),
    ]

    assert _extraer_fecha_geometrico(bloques) == {}


def test_emision_ausente_la_geometria_no_confirma_otra_fecha():
    lineas = [linea for linea in _guia("FECHA DEEMISION") if linea[0] not in ("FECHA DEEMISION", EMISION)]

    assert _extraer_fecha_geometrico(_bloques(lineas)) == {}
    # La regla lineal conserva su comportamiento previo (no inventa EMISION):
    # sin la fecha impresa, nunca devuelve la fecha de emisión ausente.
    assert extraer_fecha(_textos(lineas)) != EMISION


def test_palabras_que_solo_contienen_emision_no_son_etiqueta():
    assert _clasificar(f"FECHAS VARIAS SIN EMISION\n{EMISION}", EMISION)[1] != "FECHA DE EMISION"
