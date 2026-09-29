"""Caso real 480715: el orden de lectura OCR (foto inclinada ~4°) pegó a
DESPACHAR A el valor de PESO KG. ("3.812,00"). Un valor sin ninguna letra
nunca es una dirección: se marca contaminado y activa la recuperación
geométrica existente."""
from __future__ import annotations

import pytest

from atlas_core.extractor import _despachar_a_lineal_contaminado
from atlas_core.ocr import BloqueOCR
from atlas_core.rutas.destino_entrega import resolver_entrega_documento

# Líneas y cajas OCR reales de la zona de entrega de la traza de 480715.
_TEXTOS_480715 = [
    "PESO KG.",
    "30.10 AM PATRIC10 975390185",
    "DESPACHAR A",
    ": 3.812,00",
    "RUT CHOFER",
    ": AVENIDA O HIGGIND 208E CHILLAN",
    "15489424-1",
    "PATENTE",
    "RETIRA",
    "FECHA SALIDA",
    "CARLOS SIMONS",
    "VP8521",
]
_BLOQUES_480715 = [
    BloqueOCR("PESO KG.", ((122, 618), (165, 620), (164, 630), (121, 628)), 0.99),
    BloqueOCR("30.10 AM PATRIC10 975390185", ((262, 613), (384, 618), (383, 628), (262, 623)), 0.8),
    BloqueOCR(": 3.812,00", ((181, 623), (231, 623), (231, 633), (181, 633)), 0.97),
    BloqueOCR("DESPACHAR A", ((121, 632), (183, 635), (183, 646), (120, 643)), 0.99),
    BloqueOCR(": AVENIDA O HIGGIND 208E CHILLAN", ((212, 637), (359, 642), (359, 652), (212, 647)), 0.93),
    BloqueOCR("RUT CHOFER", ((121, 641), (177, 644), (176, 655), (120, 652)), 0.99),
    BloqueOCR("RETIRA", ((434, 645), (465, 645), (465, 656), (434, 656)), 0.99),
    BloqueOCR("15489424-1", ((212, 647), (270, 647), (270, 657), (212, 657)), 0.98),
    BloqueOCR("CARLOS SIMONS", ((482, 647), (543, 649), (543, 659), (482, 657)), 0.97),
    BloqueOCR("PATENTE", ((433, 652), (473, 654), (472, 665), (432, 663)), 0.99),
    BloqueOCR("VP8521", ((483, 654), (514, 656), (513, 667), (482, 665)), 0.98),
    BloqueOCR("FECHA SALIDA", ((120, 655), (183, 657), (183, 667), (120, 665)), 0.99),
]


def test_480715_nunca_acepta_el_peso_como_destino_y_recupera_por_geometria():
    resultado = resolver_entrega_documento(
        _TEXTOS_480715, [], None, bloques=_BLOQUES_480715, chofer_resuelto="CARLOS SIMON",
    )
    assert resultado["despachar_a_crudo"] != "3.812,00"
    assert resultado["despachar_a_crudo"] == "AVENIDA O HIGGIND 208E CHILLAN"


@pytest.mark.parametrize("valor", ["3.812,00", ": 3.812,00", "12374", "2.154,00", "30.10 975390185"])
def test_valor_numerico_o_peso_no_puede_ser_destino(valor):
    assert _despachar_a_lineal_contaminado(valor) is True


@pytest.mark.parametrize(
    "direccion",
    ["AVENIDA O HIGGINS 2086 CHILLAN", "CAMINO LOS PINOS 3396 SAN BERNARDO", "AV. FORESTAL - MANZANA 1 1014 CORONEL"],
)
def test_direccion_legitima_con_letras_sigue_aceptandose(direccion):
    assert _despachar_a_lineal_contaminado(direccion) is False
    resultado = resolver_entrega_documento(["DESPACHAR A", f": {direccion}"], [], None, bloques=None)
    assert resultado["despachar_a_crudo"] == direccion
