"""Capa genérica del Motor de Evidencia -- reutilizada por vehículos
(patrón ya validado en producción, no reescrito) y por los motores nuevos
de clientes/obras de este bloque."""
from __future__ import annotations

import pytest

from atlas_core.motor_evidencia import (
    NIVEL_CONFIRMACION_HUMANA, NIVEL_DOCUMENTAL_DEBIL, NIVEL_DOCUMENTAL_INDEPENDIENTE, NIVEL_EXTERNO_OFICIAL,
    RESULTADO_ABSTENCION_REAL,
    CandidatoEvidencia, ResultadoEvidencia, elegir_mejor_candidato, hay_empate_en_el_tope, orden_nivel,
)


def test_orden_nivel_confirmacion_humana_es_el_mas_fuerte():
    assert orden_nivel(NIVEL_CONFIRMACION_HUMANA) < orden_nivel(NIVEL_EXTERNO_OFICIAL)
    assert orden_nivel(NIVEL_EXTERNO_OFICIAL) < orden_nivel(NIVEL_DOCUMENTAL_INDEPENDIENTE)
    assert orden_nivel(NIVEL_DOCUMENTAL_INDEPENDIENTE) < orden_nivel(NIVEL_DOCUMENTAL_DEBIL)


def test_nivel_desconocido_nunca_gana_por_accidente():
    assert orden_nivel("NIVEL_INVENTADO_QUE_NO_EXISTE") > orden_nivel(NIVEL_DOCUMENTAL_DEBIL)


def test_elegir_mejor_candidato_respeta_jerarquia_no_cantidad():
    debil_con_mucha_evidencia = CandidatoEvidencia(
        identificador="A", valor_canonico="A", nivel=NIVEL_DOCUMENTAL_DEBIL,
        evidencias=("e1", "e2", "e3", "e4", "e5"),
    )
    fuerte_sin_evidencia_extra = CandidatoEvidencia(
        identificador="B", valor_canonico="B", nivel=NIVEL_CONFIRMACION_HUMANA,
    )
    mejor = elegir_mejor_candidato((debil_con_mucha_evidencia, fuerte_sin_evidencia_extra))
    assert mejor is not None and mejor.identificador == "B"


def test_hay_empate_en_el_tope_dos_candidatos_mismo_nivel():
    a = CandidatoEvidencia(identificador="A", valor_canonico="A", nivel=NIVEL_DOCUMENTAL_INDEPENDIENTE)
    b = CandidatoEvidencia(identificador="B", valor_canonico="B", nivel=NIVEL_DOCUMENTAL_INDEPENDIENTE)
    assert hay_empate_en_el_tope((a, b)) is True


def test_no_hay_empate_si_uno_es_mas_fuerte():
    a = CandidatoEvidencia(identificador="A", valor_canonico="A", nivel=NIVEL_CONFIRMACION_HUMANA)
    b = CandidatoEvidencia(identificador="B", valor_canonico="B", nivel=NIVEL_DOCUMENTAL_INDEPENDIENTE)
    assert hay_empate_en_el_tope((a, b)) is False


def test_no_hay_empate_con_un_solo_candidato_o_ninguno():
    assert hay_empate_en_el_tope(()) is False
    assert hay_empate_en_el_tope((CandidatoEvidencia(identificador="A", valor_canonico="A", nivel=NIVEL_DOCUMENTAL_DEBIL),)) is False


def test_resultado_evidencia_rechaza_resultado_no_soportado():
    with pytest.raises(ValueError):
        ResultadoEvidencia(resultado="RESULTADO_INVENTADO")


def test_resultado_evidencia_serializa_candidatos_completos():
    candidato = CandidatoEvidencia(
        identificador="X", valor_canonico="X SA", nivel=NIVEL_CONFIRMACION_HUMANA,
        evidencias=("E1",), conflictos=("C1",), razon_legible="porque sí", metadatos={"k": "v"},
    )
    resultado = ResultadoEvidencia(resultado=RESULTADO_ABSTENCION_REAL, candidatos=(candidato,), explicacion="no puedo")
    datos = resultado.a_dict()
    assert datos["resultado"] == RESULTADO_ABSTENCION_REAL
    assert datos["candidatos"][0]["identificador"] == "X"
    assert datos["candidatos"][0]["metadatos"] == {"k": "v"}
