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