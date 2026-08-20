"""Bloque ATLAS IA A1 -- contratos propios (`atlas_core.atlas_ia.contratos`).

Cubre T7 (identidad reproducible de `hipotesis_id`) y las invariantes
estructurales de cada dataclass -- nunca prueba capacidad de razonamiento
(no hay proveedor real en A1)."""
from __future__ import annotations

import pytest

from atlas_core.atlas_ia.contratos import (
    ContextoRazonamiento,
    EvidenciaIA,
    HipotesisIA,
    MOTIVO_FORMATO_INVALIDO,
    RESULTADO_HIPOTESIS_ABSTENCION,
    RESULTADO_HIPOTESIS_PROPUESTA,
    RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA,
    ResultadoValidacionHipotesis,
    calcular_hipotesis_id,
)


def _evidencia(**overrides) -> EvidenciaIA:
    base = dict(
        identificador="veh-1", campo="patente_tracto", valor="XF3629",
        tipo_fuente="HISTORICO", nivel="DOCUMENTAL_INDEPENDIENTE",
    )
    base.update(overrides)
    return EvidenciaIA(**base)


def _contexto(**overrides) -> ContextoRazonamiento:
    base = dict(
        campo="patente_tracto", valor_documental="XF3662", rut_chofer="18626166-6",
        numero_guia="1", numero_transporte="T-1", evidencias=(_evidencia(),),
        resultado_motor="SUGERENCIA_HUMANA", explicacion_motor="explicación de prueba",
    )
    base.update(overrides)
    return ContextoRazonamiento(**base)


# ---------------------------------------------------------------------
# EvidenciaIA
# ---------------------------------------------------------------------


def test_evidencia_ia_rechaza_tipo_fuente_invalido():
    with pytest.raises(ValueError, match="tipo_fuente"):
        _evidencia(tipo_fuente="INVENTADO")


def test_evidencia_ia_decision_humana_exige_tipo_fuente_coherente():
    with pytest.raises(ValueError, match="es_decision_humana"):
        _evidencia(tipo_fuente="HISTORICO", es_decision_humana=True)


def test_evidencia_ia_decision_humana_valida():
    evidencia = _evidencia(tipo_fuente="DECISION_HUMANA", es_decision_humana=True)
    assert evidencia.es_decision_humana is True


# ---------------------------------------------------------------------
# ContextoRazonamiento
# ---------------------------------------------------------------------


def test_valores_evidencia_deduplica_y_ordena():
    contexto = _contexto(evidencias=(
        _evidencia(identificador="a", valor="XF3629"),
        _evidencia(identificador="b", valor="XF3629"),
        _evidencia(identificador="c", valor="AB1234"),
    ))
    assert contexto.valores_evidencia() == ("AB1234", "XF3629")


# ---------------------------------------------------------------------
# hipotesis_id -- T7
# ---------------------------------------------------------------------


def test_hipotesis_id_reproducible_mismo_caso_misma_evidencia():
    contexto_a = _contexto()
    contexto_b = _contexto()  # construido de nuevo, pero con los mismos datos
    assert calcular_hipotesis_id(contexto_a, "XF3629") == calcular_hipotesis_id(contexto_b, "XF3629")


def test_hipotesis_id_cambia_si_cambia_el_valor_propuesto():
    contexto = _contexto()
    assert calcular_hipotesis_id(contexto, "XF3629") != calcular_hipotesis_id(contexto, "OTRO01")


def test_hipotesis_id_cambia_si_cambia_la_evidencia_considerada():
    id_original = calcular_hipotesis_id(_contexto(), "XF3629")
    contexto_con_mas_evidencia = _contexto(evidencias=(
        _evidencia(), _evidencia(identificador="veh-2", valor="ZZ0000", nivel="DOCUMENTAL_DEBIL"),
    ))
    assert calcular_hipotesis_id(contexto_con_mas_evidencia, "XF3629") != id_original


def test_hipotesis_id_cambia_si_cambia_el_nivel_de_una_evidencia():
    """Un candidato que sube de nivel (p.ej. tras una nueva corroboración
    independiente) debe producir un hipotesis_id distinto -- el nivel
    forma parte del payload canónico."""
    id_original = calcular_hipotesis_id(_contexto(), "XF3629")
    contexto_nivel_distinto = _contexto(evidencias=(_evidencia(nivel="CONFIRMACION_HUMANA"),))
    assert calcular_hipotesis_id(contexto_nivel_distinto, "XF3629") != id_original


def test_hipotesis_id_no_es_un_uuid_aleatorio():
    """Mismo caso llamado dos veces produce exactamente el mismo hash --
    nunca un valor aleatorio distinto en cada llamada."""
    valores = {calcular_hipotesis_id(_contexto(), "XF3629") for _ in range(5)}
    assert len(valores) == 1


# ---------------------------------------------------------------------
# HipotesisIA
# ---------------------------------------------------------------------


def test_hipotesis_propuesta_exige_valor_propuesto():
    with pytest.raises(ValueError, match="valor_propuesto"):
        HipotesisIA(
            hipotesis_id="x", campo="patente_tracto", valor_observado="XF3662",
            valor_propuesto="", resultado=RESULTADO_HIPOTESIS_PROPUESTA,
        )


def test_hipotesis_requiere_herramienta_exige_herramienta_faltante():
    with pytest.raises(ValueError, match="herramienta_faltante"):
        HipotesisIA(
            hipotesis_id="x", campo="patente_tracto", valor_observado="XF3662",
            valor_propuesto="", resultado=RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA,
        )


def test_hipotesis_abstencion_no_exige_valor_propuesto():
    hipotesis = HipotesisIA(
        hipotesis_id="x", campo="patente_tracto", valor_observado="XF3662",
        valor_propuesto="", resultado=RESULTADO_HIPOTESIS_ABSTENCION,
    )
    assert hipotesis.valor_propuesto == ""


def test_hipotesis_resultado_no_soportado_se_rechaza():
    with pytest.raises(ValueError, match="resultado de hipótesis"):
        HipotesisIA(
            hipotesis_id="x", campo="patente_tracto", valor_observado="XF3662",
            valor_propuesto="XF3629", resultado="INVENTADO",
        )


# ---------------------------------------------------------------------
# ResultadoValidacionHipotesis
# ---------------------------------------------------------------------


def test_resultado_validacion_rechazada_exige_motivo_valido():
    with pytest.raises(ValueError, match="motivo_rechazo"):
        ResultadoValidacionHipotesis(aceptada=False, motivo_rechazo="")


def test_resultado_validacion_rechazada_motivo_desconocido_se_rechaza():
    with pytest.raises(ValueError, match="motivo_rechazo"):
        ResultadoValidacionHipotesis(aceptada=False, motivo_rechazo="INVENTADO")


def test_resultado_validacion_aceptada_no_debe_traer_motivo():
    with pytest.raises(ValueError, match="aceptada"):
        ResultadoValidacionHipotesis(aceptada=True, motivo_rechazo=MOTIVO_FORMATO_INVALIDO)


def test_resultado_validacion_aceptada_valida():
    resultado = ResultadoValidacionHipotesis(aceptada=True)
    assert resultado.motivo_rechazo == ""
