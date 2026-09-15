"""Regresiones de selección geométrica cliente/GIRO con cajas PaddleOCR."""
from __future__ import annotations

import pytest

from atlas_core.extractor import _extraer_asociaciones_geometricas
from atlas_core.ocr import BloqueOCR


def _b(texto, x, y, ancho=None, alto=18):
    ancho = ancho if ancho is not None else max(30, len(texto) * 8)
    return BloqueOCR(texto, ((x, y), (x + ancho, y), (x + ancho, y + alto), (x, y + alto)), 0.9)


def _escena_paddle_casi_empate(con_administrativa=True):
    """GIRO gana al SEÑOR por ~0.014 antes del margen de tolerancia."""
    bloques = [
        _b("SEÑOR(ES)", 100, 100, 80, 18),
        _b("GIRO", 100, 112, 70, 18),
        _b("AGF ACEROS DE CHILE SPA", 285, 108, 180, 18),
    ]
    if con_administrativa:
        bloques.append(_b("ORDEN DE COMPRA", 195, 100, 130, 18))
    return bloques


def test_giro_casi_empata_con_senor_y_no_roba_cliente_paddleocr():
    resultado = _extraer_asociaciones_geometricas(_escena_paddle_casi_empate())

    assert resultado["cliente"] == "AGF ACEROS DE CHILE SPA"
    assert resultado["cliente"] != "ORDEN DE COMPRA"


@pytest.mark.parametrize("etiqueta", [
    "ORDEN DE COMPRA", "INDICADOR TRASLADO", "EMPRESA TRANSPORTE",
])
def test_etiqueta_administrativa_nunca_se_convierte_en_cliente(etiqueta):
    bloques = [_b("SEÑOR(ES)", 100, 100, 80, 18), _b(etiqueta, 195, 100, 150, 18)]

    assert "cliente" not in _extraer_asociaciones_geometricas(bloques)


def test_cliente_legitimo_cercano_a_senor_se_conserva():
    bloques = [_b("SEÑOR(ES)", 100, 100, 80, 18), _b("ACEROS DEL PACIFICO SPA", 195, 100, 175, 18)]

    assert _extraer_asociaciones_geometricas(bloques)["cliente"] == "ACEROS DEL PACIFICO SPA"
