"""Bloque AUTORIDAD OPERACIONAL / EXTRACCIÓN OBRA DESTINO -- caso real
congelado 472414 (SALOMON SACK, viaje 0000354860).

Con las tres columnas del membrete intercaladas por el OCR, la extracción
tomaba como OBRA DESTINO, según la corrida, "AV PRESID EDO FREI MONTALVA
9770" (una DIRECCION) o "ORDEN DE COMPRA" / "GIRO ..." (etiquetas
administrativas). El valor real -- "TRANSPORTES Y EXCAVACIONES L" -- venía
alineado con la etiqueta "OBRA DESTINO" pero se descartaba porque la
política nominal general excluye por SUBCADENA cualquier candidato que
contenga "TRANSPORTE".

Fix GENERAL: `clasificar_valor_obra_destino` (ADMINISTRATIVO / DIRECCION /
NUMERO / NOMINAL, reusable) + política nominal específica de obra destino
que compara las etiquetas estructurales de una palabra por TOKEN, no por
subcadena. Nunca una lista por guía.
"""
from __future__ import annotations

from atlas_core.extractor import (
    _extraer_asociaciones_geometricas,
    clasificar_valor_obra_destino,
    extraer_datos,
)
from atlas_core.ocr import BloqueOCR


def _b(texto, x, y, ancho=None, alto=20, conf=0.99):
    ancho = ancho if ancho is not None else max(40, len(texto) * 9)
    return BloqueOCR(
        texto=texto,
        bounding_box=((x, y), (x + ancho, y), (x + ancho, y + alto), (x, y + alto)),
        confianza=conf,
    )


def _layout_472414(valor_obra="TRANSPORTES Y EXCAVACIONES L", extra=()):
    """Membrete de 3 columnas de la guía SALOMON SACK, con la etiqueta OBRA
    DESTINO (columna central) y su valor (columna derecha) alineados, más
    la DIRECCION y una etiqueta administrativa como distractores."""
    return [
        _b("ORDEN DE COMPRA", 618, 438, 154),
        _b("3400005427 / 0030022417", 789, 438, 231),
        _b("SOLICITANTE", 617, 460, 105),
        _b("SALOMON SACK SA", 292, 464, 154),
        _b("SEÑOR(ES)", 91, 468, 88),
        _b("TELEFONO", 618, 480, 86),
        _b("90.970.000-0", 294, 485, 126),
        _b("R.U.T", 93, 490, 47),
        _b("OBRA DESTINO", 618, 500, 118),
        _b(valor_obra, 789, 500, 273),
        _b("GIRO", 96, 510, 44),
        _b("COD DESTINATARIO", 619, 522, 152),
        _b("AV PRESID EDO FREI MONTALVA 9770", 298, 525, 298),
        _b("DIRECCION", 98, 528, 88),
        _b("HORA ENTRADA", 618, 542, 124),
        _b("QUILICURA", 300, 546, 100),
        _b("COMUNA", 101, 548, 71),
        *extra,
    ]


# ==========================================================================
# 1. DIRECCION no contamina OBRA DESTINO
# ==========================================================================


def test_1_direccion_no_es_obra_destino():
    r = _extraer_asociaciones_geometricas(_layout_472414())
    assert r.get("obra destino") != "AV PRESID EDO FREI MONTALVA 9770"
    assert "PRESID" not in (r.get("obra destino") or "")
    assert clasificar_valor_obra_destino("AV PRESID EDO FREI MONTALVA 9770") == "DIRECCION"


# ==========================================================================
# 2. ORDEN DE COMPRA / etiquetas administrativas no pueden ser obra
# ==========================================================================


def test_2_etiquetas_administrativas_no_son_obra():
    assert clasificar_valor_obra_destino("ORDEN DE COMPRA") == "ADMINISTRATIVO"
    assert clasificar_valor_obra_destino("GIRO PRESID EDO FREI KONIALVA 9770") == "ADMINISTRATIVO"
    assert clasificar_valor_obra_destino("SOLICITANTE") == "ADMINISTRATIVO"
    assert clasificar_valor_obra_destino("HORA ENTRADA CIUDAD SANTIAGO") == "ADMINISTRATIVO"
    assert clasificar_valor_obra_destino("0080547884") == "NUMERO"
    r = _extraer_asociaciones_geometricas(_layout_472414())
    assert r.get("obra destino") not in ("ORDEN DE COMPRA", "GIRO", None)


# ==========================================================================
# 3. Candidato alineado con OBRA DESTINO se selecciona
# ==========================================================================


def test_3_candidato_alineado_con_la_etiqueta_se_selecciona():
    r = _extraer_asociaciones_geometricas(_layout_472414())
    assert r.get("obra destino") == "TRANSPORTES Y EXCAVACIONES L"


# ==========================================================================
# 4. Obra nominal de varios tokens se conserva completa
# ==========================================================================


def test_4_obra_multi_token_completa():
    r = _extraer_asociaciones_geometricas(
        _layout_472414(valor_obra="CONSTRUCTORA LOS ANDES DEL SUR LIMITADA")
    )
    assert r.get("obra destino") == "CONSTRUCTORA LOS ANDES DEL SUR LIMITADA"


def test_4b_regex_lineal_descarta_captura_no_nominal_y_deja_paso_a_geometria():
    # OCR lineal: entre "OBRA DESTINO" y "COD DESTINATARIO" quedó una
    # etiqueta administrativa + la DIRECCION -> el regex debe abstenerse.
    textos = [
        "S.LL. SANTIAGO PONIENTE",
        "OBRA DESTINO GIRo PRESID EDO FREI KONIALVA 9770 COD DESTINATARIO DIRECCION",
        "DESPACHAR A PEDRO RIVEROS 1411 SANTIAGO QUILICURA",
    ]
    datos = extraer_datos(textos)
    assert datos.get("obra destino") in (None, "", "No encontrado")


# ==========================================================================
# 5. Dos candidatos plausibles sin evidencia suficiente -> abstención
# ==========================================================================


def test_5_dos_candidatos_nominales_plausibles_se_abstiene():
    # Layout limpio con DOS valores NOMINALES simétricos respecto de la
    # etiqueta OBRA DESTINO (misma columna, una fila arriba y una abajo,
    # equidistantes) -> ambigüedad real, nunca se elige por el orden OCR.
    bloques = [
        _b("OBRA DESTINO", 300, 200, 120),
        _b("CONSTRUCTORA ALFA SPA", 470, 182, 200),
        _b("CONSTRUCTORA BETA SPA", 470, 218, 200),
    ]
    r = _extraer_asociaciones_geometricas(bloques)
    assert r.get("obra destino") is None


# ==========================================================================
# 6. No romper extracción de obras actualmente correctas
# ==========================================================================


def test_6_layout_simple_obra_correcta_intacta():
    # Etiqueta + valor en la misma fila, columna derecha, sin distractores.
    bloques = [
        _b("CLIENTE", 100, 100, 80),
        _b("FERRETERIA COVADONGA LTDA", 300, 100, 220),
        _b("OBRA DESTINO", 100, 140, 120),
        _b("HG CONSTRUCTORA SPA", 300, 140, 180),
    ]
    r = _extraer_asociaciones_geometricas(bloques)
    assert r.get("obra destino") == "HG CONSTRUCTORA SPA"
    assert r.get("cliente") == "FERRETERIA COVADONGA LTDA"


def test_6b_nominales_reales_no_los_clasifica_mal():
    for nombre in (
        "CASA HELSINSKI", "CONSTRUCTORA SAN CRISTOBAL LTDA", "EMPRESA CONST SIGRO",
        "AMERICAN SCREW CHILE SPA", "CONST CERRO APOQUINDO CUATRO",
        "DSI UNDERGROUND CHILE SPA", "TRANSPORTES Y EXCAVACIONES L",
        "SALOMON SACK SA SAN BERNARDO", "FERROLUSAC PEDRO DE ONA",
    ):
        assert clasificar_valor_obra_destino(nombre) == "NOMINAL", nombre
