from datetime import date

import pytest

from atlas_core.inteligencia import (
    CandidatoDocumento,
    EstadoResolucion,
    resolver_guia_transporte_fecha,
)


HOY = date(2026, 7, 30)


def resolver(**kwargs):
    return resolver_guia_transporte_fecha(fecha_referencia=HOY, **kwargs)


def test_tres_campos_exactos_confirman_y_preservan_originales():
    resultado = resolver(
        numero_guia="00123456",
        numero_transporte="0012345678",
        fecha="14/07/2026",
    )
    assert resultado.numero_guia_original == "00123456"
    assert resultado.numero_transporte_original == "0012345678"
    assert resultado.fecha_original == "14/07/2026"
    assert resultado.numero_guia_canonico == "00123456"
    assert resultado.numero_transporte_canonico == "0012345678"
    assert resultado.fecha_canonica == "14-07-2026"
    assert resultado.estado_resolucion is EstadoResolucion.CONFIRMADO


def test_guia_ausente_no_se_inventa():
    resultado = resolver(numero_transporte="1234567890", fecha="14-07-2026")
    assert resultado.numero_guia_canonico is None
    assert resultado.estado_resolucion is EstadoResolucion.PROPUESTO


def test_dos_guias_plausibles_exigen_revision():
    resultado = resolver(candidatos_guia=[
        {"valor_original": "123456", "contexto": "GUIA"},
        {"valor_original": "654321", "contexto": "GUIA"},
    ])
    assert resultado.numero_guia_canonico is None
    assert "GUIA_AMBIGUO" in resultado.contradicciones


@pytest.mark.parametrize("contexto", ["FACTURA", "TOTAL", "MONTO", "ORDEN COMPRA", "RUT"])
def test_guia_asociada_a_otro_campo_se_descarta(contexto):
    resultado = resolver(candidatos_guia=[
        {"valor_original": "123456", "contexto": contexto},
    ])
    assert resultado.numero_guia_canonico is None


def test_dos_documentos_visibles_no_se_mezclan():
    resultado = resolver(candidatos_guia=[
        {"valor_original": "123456", "contexto": "GUIA", "documento_id": "A"},
        {"valor_original": "123456", "contexto": "GUIA", "documento_id": "B"},
    ])
    assert resultado.estado_resolucion is EstadoResolucion.REQUIERE_REVISION
    assert resultado.numero_guia_canonico is None


@pytest.mark.parametrize("valor", ["0012345678", "00 1234 5678", "00-1234-5678"])
def test_transporte_exactamente_diez_digitos_conserva_ceros(valor):
    resultado = resolver(numero_transporte=valor)
    assert resultado.numero_transporte_canonico == "0012345678"


@pytest.mark.parametrize("valor", ["123456789", "12345678901", "1234A67890"])
def test_transporte_invalido_se_abstiene(valor):
    assert resolver(numero_transporte=valor).numero_transporte_canonico is None


@pytest.mark.parametrize("contexto", ["RUT", "GUIA", "TELEFONO", "OC", "MONTO"])
def test_transporte_no_confunde_competidores(contexto):
    resultado = resolver(candidatos_transporte=[
        {"valor_original": "1234567890", "contexto": contexto},
    ])
    assert resultado.numero_transporte_canonico is None


def test_dos_transportes_validos_exigen_revision():
    resultado = resolver(candidatos_transporte=[
        {"valor_original": "1234567890", "contexto": "TRANSPORTE"},
        {"valor_original": "0987654321", "contexto": "TRANSPORTE"},
    ])
    assert "TRANSPORTE_AMBIGUO" in resultado.contradicciones


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("14/07/2026", "14-07-2026"),
        ("14-07-2026", "14-07-2026"),
        ("14.07.2026", "14-07-2026"),
        ("14 07 2026", "14-07-2026"),
        ("14/07/26", "14-07-2026"),
    ],
)
def test_formatos_fecha_admitidos(valor, esperado):
    assert resolver(fecha=valor).fecha_canonica == esperado


@pytest.mark.parametrize("valor", ["31/04/2026", "01/13/2026", "texto", "29/02/2025"])
def test_fecha_imposible_o_artificial_se_rechaza(valor):
    assert resolver(fecha=valor).fecha_canonica is None


def test_fecha_futura_incompatible_se_rechaza():
    assert resolver(fecha="31/07/2026").fecha_canonica is None


def test_multiples_fechas_de_emision_exigen_revision():
    resultado = resolver(candidatos_fecha=[
        {"valor_original": "14/07/2026", "contexto": "FECHA EMISION"},
        {"valor_original": "15/07/2026", "contexto": "FECHA EMISION"},
    ])
    assert resultado.fecha_canonica is None
    assert "FECHA_AMBIGUO" in resultado.contradicciones


def test_fecha_salida_no_sustituye_fecha_emision():
    resultado = resolver(candidatos_fecha=[
        {"valor_original": "14/07/2026", "contexto": "FECHA SALIDA"},
    ])
    assert resultado.fecha_canonica is None


def test_fecha_archivo_es_auxiliar_y_revisable():
    resultado = resolver(fecha_archivo="13/07/2026")
    assert resultado.fecha_canonica == "13-07-2026"
    assert resultado.fuentes["fecha"] == "METADATO_ARCHIVO"
    assert resultado.estado_resolucion is EstadoResolucion.REQUIERE_REVISION


def test_fuentes_es_inmutable():
    resultado = resolver(fecha_archivo="13/07/2026")
    with pytest.raises(TypeError):
        resultado.fuentes["fecha"] = "OTRA"
