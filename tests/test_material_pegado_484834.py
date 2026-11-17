"""P0 material leído pegado en guías nuevas (casos reales del 16/11/2026).

* 484834: dos partidas impresas "B HORMIGON 25MM 9M A630-420HS (N)" y
  "B HORMIGON 25MM 8M A630-420HS (N)". RapidOCR leyó la primera como
  "3HORMIGON25MM9MA630-420HS(N)" (designación pegada: sin límite de palabra
  antes de HORMIGON, se descartaba entera) y la segunda con el largo "BM"
  (confusión 8/B, se publicaba con MATERIAL_OCR_NO_CONFIABLE).
* 484838: "ALAMBRON 6MM SAE 1005 (I)" leído "ALAMBRON6MMSAE1005（I)"; la
  separación familia/diámetro sólo existía para HORMIGON -> MATERIAL_AUSENTE.
* 484835: "B HORMIGON 25MM 11M A630 420HS (N)" leído "HORMIGON 25M11MA630
  420HS(N)": falta una letra del diámetro; no hay forma de reconstruirla sin
  adivinar (25MM 11M o 25MM 1M), así que el material sigue NO confiable.
* Equivalentes en trazas reales, verificados contra el original: 483486
  ("3HORMIGON10MM12MA630-420H(N)"), 484293 ("3HORMIGON18MM6M ...") y 473551
  ("18MM BM A630").

Líneas OCR reales (fixtures recortados a la tabla de productos); no se invoca OCR.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas_core import recuperacion_material as rm
from atlas_core.clasificador_material import TipoCarga, clasificar_material
from atlas_core.procesamiento_masivo import COLUMNAS, extraer_descripcion_material

_FIXTURES = Path(__file__).parent / "fixtures" / "material_lineas_ocr"
NO_CONFIABLE = "MATERIAL_OCR_NO_CONFIABLE"


def _lineas(guia: str) -> list[str]:
    return json.loads((_FIXTURES / f"{guia}.json").read_text(encoding="utf-8"))["lineas"]


def test_484834_recupera_las_dos_partidas_sin_ocr_no_confiable():
    lectura = rm.material_desde_lineas(_lineas("484834"))
    assert lectura.descripcion.split(" | ") == [
        "B HORMIGON 25MM9MA630-420HS(N)",
        "B HORMIGON 25MM 8MA630-420HS (N)",
    ]
    assert lectura.tipo_carga == "BARRAS"
    assert lectura.motivos == ()


def test_484838_alambron_pegado_ya_no_queda_ausente():
    lectura = rm.material_desde_lineas(_lineas("484838"))
    assert lectura.descripcion == "ALAMBRON 6MM SAE1005（I)"
    assert lectura.tipo_carga == "ROLLOS"
    assert lectura.motivos == ()


def test_484835_diametro_sin_letra_sigue_no_confiable():
    lectura = rm.material_desde_lineas(_lineas("484835"))
    assert lectura.descripcion == "HORMIGON 25M11MA630 420HS(N)"
    assert lectura.motivos == (NO_CONFIABLE,)


@pytest.mark.parametrize(("guia", "esperado"), [
    ("483486", ["B HORMIGON 10MM12MA630-420H(N)", "B HORMIGON 8M4A2MA630-420H(N）"]),
    ("484293", ["B HORMIGON 18MM6M A630-420H(N)"]),
    ("473551", ["B HORMIGON 18MM 8M A630-420H (N)"]),
])
def test_equivalentes_reales(guia, esperado):
    assert extraer_descripcion_material(_lineas(guia)).split(" | ") == esperado


@pytest.mark.parametrize(("linea", "esperado"), [
    ("3HORMIGON25MM9MA630-420HS(N)", "B HORMIGON 25MM9MA630-420HS(N)"),
    ("D HORMIGON12MM 6M A630-420H (N)", "B HORMIGON 12MM 6M A630-420H (N)"),
    ("ALAMBRON6MMSAE1005(I)", "ALAMBRON 6MM SAE1005(I)"),
    ("ALAMBRON 5,5MM SAE 1008 (I)", "ALAMBRON 5,5MM SAE 1008 (I)"),
    ("B HORMIGON 12MM BM A630-420H (N)", "B HORMIGON 12MM 8M A630-420H (N)"),
    ("B HORMIGON 12MM BMA630-420H (N)", "B HORMIGON 12MM 8MA630-420H (N)"),
])
def test_formas_pegadas_acotadas(linea, esperado):
    assert extraer_descripcion_material(["DESCRIPCION", linea, "VALOR TOTAL: 1"]) == esperado


@pytest.mark.parametrize("linea", [
    # Sin dígito antes de MM ni calidad detrás: B no está en la posición del largo.
    "B HORMIGON 12MM B A630-420H (N)",
    "B HORMIGON 12MM BMX (N)",
    # La familia pegada a otra palabra sigue sin evidencia (no se separa).
    "XHORMIGON25MM9MA630-420HS(N)",
    "ALAMBRONES6MM",
])
def test_no_se_reescribe_fuera_del_contexto_inequivoco(linea):
    material = extraer_descripcion_material(["DESCRIPCION", linea, "VALOR TOTAL: 1"])
    assert "8M" not in material.replace("8MM", "")
    assert not material.startswith(("B HORMIGON 25MM9M", "ALAMBRON 6MM"))


def test_material_valido_existente_no_cambia():
    for linea in ("B HORMIGON 18MM 8M A630-420H (N)", "ROLLO HORMIGON 8MM A630-420H (N)",
                  "ALAMBRON 6MM SAE 1005 (I)", "B HORMIGON 22MM 12M A630-420H (N)"):
        assert extraer_descripcion_material(["DESCRIPCION", linea, "VALOR TOTAL: 1"]) == linea
    assert clasificar_material("ALAMBRON 6MM SAE1005（I)") == TipoCarga.ROLLOS


# --- acción "Recuperar material" sobre el material no confiable publicado -----

def _fila(descripcion: str, motivos: str = NO_CONFIABLE, **extra) -> dict:
    fila = {c: "" for c in COLUMNAS}
    fila.update({"archivo": "484834.jpeg", "numero_guia": "484834", "descripcion_material": descripcion,
                 "tipo_carga": "BARRAS", "motivos_revision_documento": motivos,
                 "metricas_procesamiento_json": json.dumps({"ocr_seg": 1.0}, sort_keys=True),
                 "estado_ruta": "RUTA_CALCULADA", "despachar_a_crudo": "CERRO SAN LUIS 9890 B SANTIAGO QUILICURA"})
    fila.update(extra)
    return fila


def test_accion_mejora_material_no_confiable_con_lectura_sin_senales():
    fila = _fila("B HORMIGON 25MM BMA630-420HS (N)")
    veredicto, valores = rm.evaluar_recuperacion(fila, rm.material_desde_lineas(_lineas("484834")), [])
    assert veredicto == rm.MEJORAR
    assert set(valores) <= {"descripcion_material", "tipo_carga", "metricas_procesamiento_json", "motivos_revision_documento"}
    assert valores["descripcion_material"].endswith("B HORMIGON 25MM 8MA630-420HS (N)")
    assert valores["motivos_revision_documento"] == ""


def test_accion_no_reemplaza_no_confiable_por_otra_lectura_no_confiable():
    fila = _fila("HORMIGON 25M1MA630 420HS(N)")
    lectura = rm.material_desde_lineas(_lineas("484835"))
    assert rm.evaluar_recuperacion(fila, lectura, [])[0] == rm.SE_CONSERVA


def test_accion_conserva_material_confiable_y_decision_humana():
    confiable = _fila("B HORMIGON 22MM 12M A630-420H (N)", motivos="")
    assert rm.evaluar_recuperacion(confiable, rm.material_desde_lineas(_lineas("484834")), [])[0] == rm.SE_CONSERVA
    # Una partida confiable ya publicada se conserva y sólo se completa la otra.
    parcial = _fila("B HORMIGON 25MM 9M A630-420HS (N)", motivos="")
    veredicto, valores = rm.evaluar_recuperacion(parcial, rm.material_desde_lineas(_lineas("484834")), [])
    assert veredicto == rm.COMPLETAR
    humano = _fila("ALAMBRON 6MM SAE 1005 ( I ). CORRÍGELO", motivos="", archivo="mobile/x/original.jpg",
                   numero_guia="484838")
    ledger = [{"campo": "descripcion_material", "documento": {"archivo": "mobile/x/original.jpg"}}]
    assert rm.evaluar_recuperacion(humano, rm.material_desde_lineas(_lineas("484838")), ledger) == (
        rm.PROTEGIDO_POR_DECISION, {})
