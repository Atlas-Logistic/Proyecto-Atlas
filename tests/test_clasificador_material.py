"""Pruebas del clasificador de material."""

from atlas_core.clasificador_material import TipoCarga, clasificar_material


def test_clasifica_barras() -> None:
    resultado = clasificar_material("B HORMIGÓN 16 MM 12 M")

    assert resultado == TipoCarga.BARRAS


def test_clasifica_rollos() -> None:
    resultado = clasificar_material("ROLLO HORMIGÓN 10 MM")

    assert resultado == TipoCarga.ROLLOS


def test_clasifica_mixto() -> None:
    resultado = clasificar_material("BARRAS 16 MM Y ROLLO 10 MM")

    assert resultado == TipoCarga.MIXTO


def test_clasifica_no_determinado() -> None:
    resultado = clasificar_material("MATERIAL ACERO")

    assert resultado == TipoCarga.NO_DETERMINADO


def test_ignora_tildes_y_mayusculas() -> None:
    resultado = clasificar_material("rollo hormigón 8 mm")

    assert resultado == TipoCarga.ROLLOS


def test_clasifica_barra_hormigon_a630_sin_prefijo_b() -> None:
    """La especificación completa identifica barras aunque OCR omita "B"."""
    resultado = clasificar_material("HORMIGON 22MM 12M A630-420H (N)")

    assert resultado == TipoCarga.BARRAS


def test_clasifica_barra_a630_con_medidas_ocr_degradadas() -> None:
    resultado = clasificar_material("HORMIGON 8MN 12K A630-420H")

    assert resultado == TipoCarga.BARRAS


def test_rolleo_hormigon_a630_sigue_siendo_rollo() -> None:
    """La regla abreviada nunca degrada una declaración explícita de rollo."""
    resultado = clasificar_material("ROLLO HORMIGON 10MM 12M A630-420H")

    assert resultado == TipoCarga.ROLLOS
