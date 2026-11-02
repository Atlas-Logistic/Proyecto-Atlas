"""P0 glosas ajenas en material OCR (caso real 483843).

La glosa libre impresa junto a VALOR TOTAL ("C2 ROLLOS RICARDO 995468705",
"C1 22.09 BAM/BARRAS CYD", ...) contiene ROLLOS/BARRAS y se publicaba como un
material más. Sólo se descarta lo leído después del pie de la tabla
(TIPO DE DOCUMENTO, VALOR TOTAL, PESO KG, DESPACHAR A) cuando ese pie sigue al
encabezado DESCRIPCION; con el orden de lectura invertido (480604) no se
recorta nada. Trazas OCR reales; no se invoca OCR.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas_core.procesamiento_masivo import extraer_descripcion_material


_FIXTURES = Path(__file__).parent / "fixtures"


def _lineas(guia: str) -> list[str]:
    completa = _FIXTURES / "trazas_ocr_aza" / f"{guia}.json"
    if completa.is_file():
        return json.loads(completa.read_text(encoding="utf-8"))["ocr"]["lineas"]
    return json.loads((_FIXTURES / "material_lineas_ocr" / f"{guia}.json").read_text(encoding="utf-8"))["lineas"]


@pytest.mark.parametrize(
    ("guia", "esperado"),
    [
        ("483843", "ROLLO HORMIGON 12MM A630-420H (N)"),
        ("482101", "B HORMIGON 22MM 9M A630-420H (N) | B HORMIGON 22MM 12M A630-420H (N) | B HORMIGON 22MM 8M A630-420H (N)"),
        ("475096", "B HORMIGON 16MM 6M A630-420H (N) | B HORMIGON 8MM 6M A630-420H (N) | B HORMIGON 10MM 6M A630-420H"),
    ],
)
def test_glosa_del_pie_no_es_material(guia, esperado):
    assert extraer_descripcion_material(_lineas(guia)) == esperado


def test_orden_de_lectura_invertido_conserva_todos_los_productos_480604():
    material = extraer_descripcion_material(_lineas("480604"))

    assert material.split(" | ") == [
        "REDONDO LISO 6MM 6M COMERCIAL (N)", "PLANA 75X8MM 6M A270ES (N)", "ANGULO 50X50X5MM 6M A270ES (N)",
        "REDONDO LISO 12MM 6M SAE 1020 (N)", "REDONDO LISO 16MM 6M SAE 1020 (N)", "ANGULO 20X20X3MM 6M A270ES (N)",
    ]


def test_sin_material_legible_sigue_absteniendose_483859():
    assert extraer_descripcion_material(_lineas("483859")) == ""


@pytest.mark.parametrize(
    "producto",
    ["ROLLO HORMIGON 12MM A630-420H (N)", "B HORMIGON 22MM 12M A630-420H (N)", "ALAMBRON 9,5MM AZA 1006 (N)"],
)
def test_producto_dentro_de_la_tabla_se_conserva(producto):
    lineas = ["CANTIDAD", "CODIGO", "DESCRIPCION", producto, "Coladas: 2617880102", "TIPODEDOCUMENTO",
              "VALORTOTAL:24.093.944", "PESOKG.", "C2 ROLLOS RICARDO 995468705"]

    assert extraer_descripcion_material(lineas) == extraer_descripcion_material([producto])
    assert "RICARDO" not in extraer_descripcion_material(lineas)


def test_sin_encabezado_no_se_recorta():
    # Lecturas focales de la columna DESCRIPCION: sin encabezado ni pie.
    assert extraer_descripcion_material(["VALOR TOTAL", "B HORMIGON 22MM 12M A630-420H (N)"]) == (
        "B HORMIGON 22MM 12M A630-420H (N)"
    )
