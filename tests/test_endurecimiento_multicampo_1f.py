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


def test_baja_calidad_no_confirma():
    resultado = resolver(candidatos_guia=[
        CandidatoDocumento("123456", "GUIA", calidad=0.40),
    ])
    assert resultado.numero_guia_canonico == "123456"
    assert resultado.estado_resolucion is EstadoResolucion.REQUIERE_REVISION
    assert "GUIA_BAJA_CALIDAD" in resultado.contradicciones


@pytest.mark.parametrize("campo", ["guia", "transporte", "fecha"])
def test_digito_alterado_ocr_solo_propone_revision(campo):
    candidato = CandidatoDocumento(
        "123456" if campo == "guia" else
        "0012345678" if campo == "transporte" else "14/07/2026",
        "GUIA" if campo == "guia" else
        "TRANSPORTE" if campo == "transporte" else "FECHA EMISION",
        alterado_ocr=True,
    )
    resultado = resolver(**{f"candidatos_{campo}": [candidato]})
    assert resultado.estado_resolucion is EstadoResolucion.REQUIERE_REVISION
    assert f"{campo.upper()}_ALTERADO_OCR" in resultado.contradicciones


def test_guia_y_transporte_iguales_generan_contradiccion():
    resultado = resolver(numero_guia="12345678", numero_transporte="0012345678")
    assert resultado.numero_guia_canonico == "12345678"
    assert resultado.numero_transporte_canonico == "0012345678"
    resultado = resolver(numero_guia="12345678", numero_transporte="12345678")
    assert resultado.numero_transporte_canonico is None


def test_no_corrige_letras_como_digitos():
    resultado = resolver(
        numero_guia="I23456",
        numero_transporte="OO12345678",
        fecha="I4/07/2026",
    )
    assert resultado.numero_guia_canonico is None
    assert resultado.numero_transporte_canonico is None
    assert resultado.fecha_canonica is None


def test_originales_preservan_espacios_y_separadores():
    resultado = resolver(
        numero_guia=" 001234 ",
        numero_transporte="00-1234-5678",
        fecha="14.07.2026",
    )
    assert resultado.numero_guia_original == " 001234 "
    assert resultado.numero_transporte_original == "00-1234-5678"
    assert resultado.fecha_original == "14.07.2026"


def test_candidato_contextual_unico_v1f_se_resuelve():
    resultado = resolver(candidatos_guia=[
        {"valor_original": "765432", "contexto": "GUIA DE DESPACHO"},
        {"valor_original": "999999", "contexto": "FACTURA"},
    ])
    assert resultado.numero_guia_canonico == "765432"


def test_no_elige_numero_mas_largo():
    resultado = resolver(candidatos_guia=[
        {"valor_original": "12345", "contexto": "GUIA"},
        {"valor_original": "12345678", "contexto": "GUIA"},
    ])
    assert resultado.numero_guia_canonico is None


def test_documento_id_unico_no_mezcla_campos_de_otro_documento():
    resultado = resolver(
        candidatos_guia=[
            {"valor_original": "123456", "contexto": "GUIA", "documento_id": "A"},
        ],
        candidatos_transporte=[
            {"valor_original": "1234567890", "contexto": "TRANSPORTE", "documento_id": "B"},
        ],
    )
    assert resultado.numero_guia_canonico is None
    assert resultado.numero_transporte_canonico is None
    assert "MULTIPLES_DOCUMENTOS_VISIBLES" in resultado.contradicciones


def test_fecha_documental_domina_metadato_archivo():
    resultado = resolver(fecha="14/07/2026", fecha_archivo="13/07/2026")
    assert resultado.fecha_canonica == "14-07-2026"
    assert resultado.fuentes["fecha"] == "OCR"


def test_anio_dos_digitos_fuera_de_rango_se_rechaza():
    assert resolver(fecha="14/07/99").fecha_canonica is None


def test_campo_vacio_total_no_resuelto():
    resultado = resolver()
    assert resultado.estado_resolucion is EstadoResolucion.NO_RESUELTO
    assert resultado.confianza == 0


def test_resultado_determinista():
    kwargs = dict(
        numero_guia="123456",
        numero_transporte="0012345678",
        fecha="14/07/2026",
    )
    assert resolver(**kwargs) == resolver(**kwargs)


def test_no_hay_efectos_secundarios(monkeypatch):
    import atlas_core.extractor as extractor

    antes = extractor.extraer_datos
    resolver(numero_guia="123456")
    assert extractor.extraer_datos is antes
