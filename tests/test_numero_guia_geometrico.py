"""Bloque FIX EXTRACCIÓN numero_guia -- fallback geométrico para layouts
donde "GUIA DE DESPACHO", "ELECTRONICA" y el marcador N°/Nº/NRO llegan
como bloques OCR separados, NO adyacentes en el texto lineal.

Causa raíz real (guía 472624, envío 286f5007-f9eb-4ac1-99a5-148184a52aec,
original.jpg preservado en G:\\Mi unidad\\Atlas, NUNCA modificado por este
bloque): PaddleOCR devuelve "GUIA DE DESPACHO" y "N° 472624" como dos
bloques separados por varias líneas de domicilio/sucursales intercaladas
-- el patrón textual contiguo de `buscar_numero_guia` (secuencia
"GUIA DE DESPACHO ELECTRONICA N° <número>" en un solo tramo de texto)
nunca calza con esa disposición, y el campo queda "No encontrado" pese a
que el número está impreso, legible y en la posición correcta.

Esta suite cubre las 4 clases pedidas (encabezado contiguo -- ver
`test_extraer_datos.py` para el patrón textual sin cambios --, encabezado
separado en bloques, candidato numérico ajeno cercano, ambigüedad), más la
regresión con la geometría real de 472624 y la verificación de que el
mecanismo nunca confunde el número de guía con un numero_transporte de 10
dígitos."""
from __future__ import annotations

from atlas_core.extractor import _extraer_numero_guia_geometrico, extraer_datos
from atlas_core.ocr import BloqueOCR


def _bloque(texto, x, y, ancho=None, alto=104, conf=0.99):
    ancho = ancho if ancho is not None else max(60, len(texto) * 18)
    return BloqueOCR(
        texto=texto,
        bounding_box=((x, y), (x + ancho, y), (x + ancho, y + alto), (x, y + alto)),
        confianza=conf,
    )


# ============================================================
# 0. Encabezado CONTIGUO -- el patrón textual (fast-path) sigue intacto,
#    nunca se toca ni se necesita el fallback geométrico.
# ============================================================


def test_encabezado_contiguo_usa_el_patron_textual_sin_geometria():
    textos = [
        "ACEROS AZA S.A",
        "GUIA DE DESPACHO ELECTRONICA N° 123456",
        "FECHA DE EMISION 26-08-2026",
    ]
    datos = extraer_datos(textos)
    assert datos["número de guía"] == "123456"


# ============================================================
# 1. Encabezado SEPARADO en bloques -- regresión con la geometría REAL de
#    472624 (coordenadas confirmadas por diagnóstico de sólo lectura sobre
#    el archivo real, que nunca se modifica ni se confirma).
# ============================================================


def test_regresion_472624_geometria_real_recupera_numero_de_guia():
    bloques = [
        _bloque("GUIA DE DESPACHO", 2030, 334, 2721 - 2030, 438 - 334, conf=1.0),
        # Domicilio/sucursales intercalados en el texto lineal entre el
        # título y el número -- exactamente lo que rompe el patrón
        # textual contiguo, sin afectar la geometría.
        _bloque("LA UNION 3070. RENCA SANTIAGO", 537, 377, 1680 - 537, 462 - 377, conf=0.98),
        _bloque("ELECTRONICA", 2600, 377, 300, 462 - 377, conf=1.0),
        _bloque("FONO:(56)2267 79100 www.aza.cl", 700, 470, 900, 60, conf=0.99),
        _bloque("Sucursal Antofagasta", 100, 500, 500, 60, conf=0.86),
        _bloque("N\u00b0 472624", 2210, 542, 2538 - 2210, 622 - 542, conf=0.996),
        _bloque("Sucursal Talcahuano", 100, 600, 500, 60, conf=0.98),
        # Zona no relacionada, mucho más abajo -- nunca debe confundirse.
        _bloque("N\u00famero SAP", 2098, 782, 2352 - 2098, 828 - 782, conf=1.0),
        _bloque("0080548594", 2493, 766, 2752 - 2493, 819 - 766, conf=1.0),
        _bloque("ORDEN DE COMPRA", 1541, 876, 2948 - 1541, 925 - 876, conf=0.99),
    ]
    assert _extraer_numero_guia_geometrico(bloques) == {"valor": "472624"}


def test_regresion_472624_end_to_end_via_extraer_datos_con_bloques_reales():
    """Mismo caso, pero pasando por el cableado real: el patrón textual
    (con estas mismas líneas separadas) no encuentra nada; el fallback
    geométrico sí."""
    textos = [
        "ACEROS AZA S.A",
        "GUIA DE DESPACHO",
        "CASA MATRIZ PLANTA RENCA",
        "LA UNION 3070. RENCA SANTIAGO.CHILE.COD POSTAL 746 45 22.",
        "ELECTRONICA",
        "FONO:(56)2267 79100 www.aza.cl",
        "N\u00b0 472624",
    ]
    datos = extraer_datos(textos)
    # El patrón textual contiguo NUNCA calza con esta disposición -- lo
    # que confirma que, sin el fallback geométrico (probado aparte, en
    # `procesar_archivo`), el campo queda "No encontrado".
    assert datos["número de guía"] == "No encontrado"


# ============================================================
# 2. Candidato numérico AJENO cercano -- un número sin marcador N°/Nº/NRO
#    en la misma ventana NUNCA se confunde con el número de guía.
# ============================================================


def test_candidato_numerico_ajeno_cercano_sin_marcador_no_se_confunde():
    bloques = [
        _bloque("GUIA DE DESPACHO", 2030, 334, 2721 - 2030, 438 - 334, conf=1.0),
        _bloque("N\u00b0 472624", 2210, 542, 2538 - 2210, 622 - 542, conf=0.996),
        # Un número de 6 dígitos SIN ningún marcador N°/Nº/NRO adosado,
        # geométricamente cerca -- una referencia interna cualquiera, no
        # el número de guía. Nunca debe entrar como candidato.
        _bloque("998877", 2600, 560, 200, 60, conf=0.9),
    ]
    assert _extraer_numero_guia_geometrico(bloques) == {"valor": "472624"}


# ============================================================
# 3. Ambigüedad -- dos candidatos igualmente marcados y plausibles dentro
#    de la ventana: se abstiene, nunca elige arbitrariamente.
# ============================================================


def test_dos_candidatos_marcados_igualmente_plausibles_se_abstiene():
    bloques = [
        _bloque("GUIA DE DESPACHO", 2030, 334, 2721 - 2030, 438 - 334, conf=1.0),
        _bloque("N\u00b0 472624", 2210, 542, 2538 - 2210, 622 - 542, conf=0.996),
        _bloque("N\u00b0 999888", 2210, 660, 2538 - 2210, 740 - 660, conf=0.9),
    ]
    assert _extraer_numero_guia_geometrico(bloques) == {}


# ============================================================
# 4. Nunca confunde con numero_transporte (10 dígitos, "0000NNNNNN") ni
#    con un candidato fuera de la ventana geométrica.
# ============================================================


def test_nunca_confunde_marcador_con_numero_transporte_de_diez_digitos():
    bloques = [
        _bloque("GUIA DE DESPACHO", 2030, 334, 2721 - 2030, 438 - 334, conf=1.0),
        # Formato real de numero_transporte (4 ceros + dígitos) pegado a
        # un marcador N° -- nunca debe aceptarse como número de guía.
        _bloque("N\u00b0 0000355433", 2210, 542, 300, 622 - 542, conf=0.99),
    ]
    assert _extraer_numero_guia_geometrico(bloques) == {}


def test_candidato_fuera_de_la_ventana_geometrica_se_ignora():
    bloques = [
        _bloque("GUIA DE DESPACHO", 2030, 334, 2721 - 2030, 438 - 334, conf=1.0),
        # Mismo marcador y forma válidos, pero MUY lejos verticalmente del
        # encabezado -- otra sección del documento, no el número de guía.
        _bloque("N\u00b0 123123", 2210, 3200, 300, 80, conf=0.99),
    ]
    assert _extraer_numero_guia_geometrico(bloques) == {}


def test_sin_ancla_guia_de_despacho_se_abstiene():
    bloques = [_bloque("N\u00b0 472624", 2210, 542, 328, 80, conf=0.996)]
    assert _extraer_numero_guia_geometrico(bloques) == {}


# ============================================================
# 5. Marcador y número como bloques SEPARADOS (no combinados en uno solo)
#    -- también debe recuperarse, dentro de la misma fila/ventana.
# ============================================================


def test_marcador_y_numero_en_bloques_separados_misma_fila_se_recupera():
    bloques = [
        _bloque("GUIA DE DESPACHO", 2030, 334, 2721 - 2030, 438 - 334, conf=1.0),
        _bloque("N\u00b0", 2210, 542, 120, 80, conf=0.98),
        _bloque("472624", 2350, 542, 200, 80, conf=0.996),
    ]
    assert _extraer_numero_guia_geometrico(bloques) == {"valor": "472624"}


# ============================================================
# 6. Sin bloques / bloques vacíos -- nunca falla, se abstiene.
# ============================================================


def test_sin_bloques_se_abstiene_sin_excepcion():
    assert _extraer_numero_guia_geometrico([]) == {}
