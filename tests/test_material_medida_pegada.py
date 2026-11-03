"""P0 material con diámetro y largo pegados (casos reales 483897 y 483812).

RapidOCR leyó "BHORMIGON10MM6M A630-420H (N)": sin espacio entre la familia y
el diámetro ni entre el diámetro y el largo. La separación de "HORMIGON16MM"
exigía un límite de palabra tras MM, así que la línea quedaba sin evidencia de
material y se descartaba entera. Sólo se separa la familia del diámetro; el
resto de la línea queda como la leyó el OCR. Trazas OCR reales; no se invoca OCR.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas_core.clasificador_material import TipoCarga, clasificar_material
from atlas_core.procesamiento_masivo import extraer_descripcion_material


_FIXTURES = Path(__file__).parent / "fixtures"


def _lineas(guia: str) -> list[str]:
    completa = _FIXTURES / "trazas_ocr_aza" / f"{guia}.json"
    if completa.is_file():
        return json.loads(completa.read_text(encoding="utf-8"))["ocr"]["lineas"]
    return json.loads((_FIXTURES / "material_lineas_ocr" / f"{guia}.json").read_text(encoding="utf-8"))["lineas"]


def test_diametro_y_largo_pegados_483897():
    material = extraer_descripcion_material(_lineas("483897"))

    assert material == "B HORMIGON 10MM6M A630-420H (N)"
    assert clasificar_material(material) == TipoCarga.BARRAS


def test_varias_partidas_pegadas_483812():
    # La guía imprime seis partidas; el OCR sólo trae tres legibles (el resto
    # queda bajo el timbre). Se recuperan esas tres, sin inventar las demás.
    assert extraer_descripcion_material(_lineas("483812")).split(" | ") == [
        "HORMIGON 10MM6MA440-280H （N)",
        "B HORMIGON 16MM7M A630-4201I (N)",
        "B HORMIGON 18MM7MA630-420H(N）",
    ]


@pytest.mark.parametrize(
    ("linea", "esperado"),
    [
        ("BHORMIGON10MM6M A630-420H (N)", "B HORMIGON 10MM6M A630-420H (N)"),
        ("BHORMIGON18MM7MA630-420H(N)", "B HORMIGON 18MM7MA630-420H(N)"),
        ("HORMIGON10MM6MA440-280H (N)", "HORMIGON 10MM6MA440-280H (N)"),
        # Formas que ya funcionaban quedan iguales.
        ("BHORMIGON16MM 11MA630-420H(N)", "B HORMIGON 16MM 11MA630-420H(N)"),
        ("B HORMIGON 10MM 6M A630-420H (N)", "B HORMIGON 10MM 6M A630-420H (N)"),
        ("B HORMIGON 16MM7M A630-4201I (N)", "B HORMIGON 16MM7M A630-4201I (N)"),
        ("ROLLO HORMIGON 12MM A630-420H (N)", "ROLLO HORMIGON 12MM A630-420H (N)"),
        ("ALAMBRON 9,5MM AZA 1006 (N)", "ALAMBRON 9,5MM AZA 1006 (N)"),
    ],
)
def test_linea_aislada(linea, esperado):
    assert extraer_descripcion_material([linea]) == esperado


def test_varias_partidas_en_tabla_conservan_orden_y_formato():
    lineas = ["CANTIDAD", "CODIGO", "DESCRIPCION", "B HORMIGON 22MM 9M A630-420H (N)", "Coladas: 2617880102",
              "BHORMIGON10MM6M A630-420H (N)", "Coladas: 2618015402", "B HORMIGON 22MM 12M A630-420H (N)",
              "TIPODEDOCUMENTO", "VALORTOTAL:24.093.944"]

    assert extraer_descripcion_material(lineas).split(" | ") == [
        "B HORMIGON 22MM 9M A630-420H (N)", "B HORMIGON 10MM6M A630-420H (N)", "B HORMIGON 22MM 12M A630-420H (N)",
    ]


def test_mm_seguido_de_letra_no_se_separa():
    # Sólo el patrón diámetro (+ largo numérico); "HORMIGON10MMX" sigue sin
    # ser evidencia, igual que antes.
    assert extraer_descripcion_material(["HORMIGON10MMX A630"]) == ""
