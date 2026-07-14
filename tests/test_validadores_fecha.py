import json

import pytest

from atlas_core.modelos import EstadoValidacion, FuenteCampo
from atlas_core.validadores import validar_fecha


def test_fecha_iso_valida():
    campo = validar_fecha("2026-07-14")
    assert campo.valor == "2026-07-14"
    assert campo.estado is EstadoValidacion.VALIDO


def test_fecha_dia_mes_anio_se_normaliza():
    campo = validar_fecha("14/07/2026", formato_esperado="DD/MM/YYYY")
    assert campo.valor == "2026-07-14"
    assert campo.estado is EstadoValidacion.VALIDO


def test_conserva_valor_original_al_normalizar():
    campo = validar_fecha("14/07/2026", formato_esperado="DD/MM/YYYY")
    assert campo.valor_original == "14/07/2026"


def test_conserva_valor_original_con_espacios_exteriores():
    campo = validar_fecha(" 2026-07-14 ")
    assert campo.valor == "2026-07-14"
    assert campo.valor_original == " 2026-07-14 "


def test_anio_bisiesto_valido():
    assert validar_fecha("29/02/2024", formato_esperado="DD/MM/YYYY").estado is EstadoValidacion.VALIDO


def test_anio_no_bisiesto_invalido():
    campo = validar_fecha("29/02/2025", formato_esperado="DD/MM/YYYY")
    assert campo.estado is EstadoValidacion.INVALIDO
    assert "no existe" in campo.advertencias[0]


def test_fecha_imposible_invalida():
    campo = validar_fecha("31/04/2026", formato_esperado="DD/MM/YYYY")
    assert campo.estado is EstadoValidacion.INVALIDO
    assert "no existe" in campo.advertencias[0]


def test_mes_13_invalido():
    campo = validar_fecha("2026-13-01")
    assert campo.estado is EstadoValidacion.INVALIDO


def test_none_y_vacio_son_ausentes():
    for valor in (None, "", "   "):
        campo = validar_fecha(valor)
        assert campo.valor is None
        assert campo.estado is EstadoValidacion.AUSENTE
        assert campo.requiere_revision is True


def test_entero_es_invalido():
    campo = validar_fecha(20260714)
    assert campo.estado is EstadoValidacion.INVALIDO
    assert campo.valor == 20260714


def test_rechaza_formato_dia_mes_con_esperado_iso():
    assert validar_fecha("14/07/2026").estado is EstadoValidacion.INVALIDO


def test_rechaza_formato_iso_con_esperado_dia_mes():
    assert validar_fecha("2026-07-14", formato_esperado="DD/MM/YYYY").estado is EstadoValidacion.INVALIDO


def test_rechaza_separadores_mezclados():
    assert validar_fecha("2026/07-14").estado is EstadoValidacion.INVALIDO


@pytest.mark.parametrize(
    "valor",
    [
        "２０２６-０７-１４",
        "202-07-14",
        "20260-07-14",
        "2026-07-14 texto",
        "2026-07-14 2026-07-15",
        "2026 -07-14",
        "2026-07 -14",
    ],
)
def test_rechaza_fechas_con_formato_no_estricto(valor):
    assert validar_fecha(valor).estado is EstadoValidacion.INVALIDO


def test_conserva_fuente_y_confianza():
    campo = validar_fecha("2026-07-14", fuente=FuenteCampo.OCR, confianza=0.74)
    assert campo.fuente is FuenteCampo.OCR
    assert campo.confianza == 0.74


def test_fecha_valida_puede_requerir_revision():
    campo = validar_fecha("2026-07-14", revision_humana=True)
    assert campo.estado is EstadoValidacion.VALIDO
    assert campo.requiere_revision is True


def test_formato_no_soportado_lanza_value_error():
    with pytest.raises(ValueError, match="no soportado"):
        validar_fecha("2026.07.14", formato_esperado="YYYY.MM.DD")


def test_fecha_se_serializa():
    serializado = validar_fecha("2026-07-14").a_diccionario()
    assert serializado["valor"] == "2026-07-14"
    assert json.dumps(serializado, ensure_ascii=False)
