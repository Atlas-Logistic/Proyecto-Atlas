"""Bloque ATLAS IA A1 -- validadores anti-alucinación
(`atlas_core.atlas_ia.validadores`). Cubre T1-T6 del bloque."""
from __future__ import annotations

from atlas_core.atlas_ia.contratos import (
    ContextoRazonamiento,
    EvidenciaIA,
    HipotesisIA,
    MOTIVO_CONTRADICE_EVIDENCIA_SUPERIOR,
    MOTIVO_ESTRUCTURA_INVALIDA,
    MOTIVO_FORMATO_INVALIDO,
    MOTIVO_VALOR_NO_RESPALDADO,
    RESULTADO_HIPOTESIS_ABSTENCION,
    RESULTADO_HIPOTESIS_PROPUESTA,
    RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA,
)
from atlas_core.atlas_ia.validadores import validar_hipotesis_vehiculo


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
        resultado_motor="SUGERENCIA_HUMANA",
    )
    base.update(overrides)
    return ContextoRazonamiento(**base)


def _hipotesis(**overrides) -> HipotesisIA:
    base = dict(
        hipotesis_id="hip-1", campo="patente_tracto", valor_observado="XF3662",
        valor_propuesto="XF3629", resultado=RESULTADO_HIPOTESIS_PROPUESTA,
    )
    base.update(overrides)
    return HipotesisIA(**base)


# ---------------------------------------------------------------------
# T1 -- hipótesis válida
# ---------------------------------------------------------------------


def test_t1_hipotesis_respaldada_por_evidencia_se_acepta():
    contexto = _contexto()  # evidencia contiene XF3629
    hipotesis = _hipotesis(valor_propuesto="XF3629")
    resultado = validar_hipotesis_vehiculo(hipotesis, contexto)
    assert resultado.aceptada is True
    assert resultado.motivo_rechazo == ""


# ---------------------------------------------------------------------
# T2 -- alucinación (V2, candidato inventado)
# ---------------------------------------------------------------------


def test_t2_valor_no_respaldado_por_evidencia_se_rechaza():
    contexto = _contexto()  # evidencia NO contiene ZZ9999
    hipotesis = _hipotesis(valor_propuesto="ZZ9999")
    resultado = validar_hipotesis_vehiculo(hipotesis, contexto)
    assert resultado.aceptada is False
    assert resultado.motivo_rechazo == MOTIVO_VALOR_NO_RESPALDADO


# ---------------------------------------------------------------------
# T3 -- formato inválido (V1)
# ---------------------------------------------------------------------


def test_t3_formato_invalido_se_rechaza():
    contexto = _contexto(evidencias=(_evidencia(valor="XYZ"),))
    hipotesis = _hipotesis(valor_propuesto="XYZ")
    resultado = validar_hipotesis_vehiculo(hipotesis, contexto)
    assert resultado.aceptada is False
    assert resultado.motivo_rechazo == MOTIVO_FORMATO_INVALIDO


# ---------------------------------------------------------------------
# T4 -- contradicción con decisión humana previa (V3)
# ---------------------------------------------------------------------


def test_t4_contradice_decision_humana_previa_se_rechaza():
    contexto = _contexto(evidencias=(
        _evidencia(
            identificador="veh-humano", valor="VP8521", tipo_fuente="DECISION_HUMANA",
            nivel="CONFIRMACION_HUMANA", es_decision_humana=True,
        ),
        _evidencia(identificador="veh-otro", valor="VP6521"),
    ))
    hipotesis = _hipotesis(valor_observado="XF3662", valor_propuesto="VP6521")
    resultado = validar_hipotesis_vehiculo(hipotesis, contexto)
    assert resultado.aceptada is False
    assert resultado.motivo_rechazo == MOTIVO_CONTRADICE_EVIDENCIA_SUPERIOR


def test_t4_coincide_con_decision_humana_previa_se_acepta():
    contexto = _contexto(evidencias=(
        _evidencia(
            identificador="veh-humano", valor="VP8521", tipo_fuente="DECISION_HUMANA",
            nivel="CONFIRMACION_HUMANA", es_decision_humana=True,
        ),
    ))
    hipotesis = _hipotesis(valor_propuesto="VP8521")
    resultado = validar_hipotesis_vehiculo(hipotesis, contexto)
    assert resultado.aceptada is True


# ---------------------------------------------------------------------
# T5 -- abstención: nunca se convierte en error
# ---------------------------------------------------------------------


def test_t5_abstencion_se_acepta_estructuralmente():
    contexto = _contexto()
    hipotesis = HipotesisIA(
        hipotesis_id="hip-abstencion", campo="patente_tracto", valor_observado="XF3662",
        valor_propuesto="", resultado=RESULTADO_HIPOTESIS_ABSTENCION,
    )
    resultado = validar_hipotesis_vehiculo(hipotesis, contexto)
    assert resultado.aceptada is True
    assert resultado.motivo_rechazo == ""


# ---------------------------------------------------------------------
# T6 -- herramienta faltante: se preserva, no se ejecuta nada
# ---------------------------------------------------------------------


def test_t6_requiere_herramienta_se_acepta_y_preserva_el_dato():
    contexto = _contexto()
    hipotesis = HipotesisIA(
        hipotesis_id="hip-herramienta", campo="patente_tracto", valor_observado="XF3662",
        valor_propuesto="", resultado=RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA,
        herramienta_faltante="HISTORIAL_VEHICULO",
    )
    resultado = validar_hipotesis_vehiculo(hipotesis, contexto)
    assert resultado.aceptada is True
    # el dato no se pierde ni se transforma -- sigue en la propia hipótesis
    assert hipotesis.herramienta_faltante == "HISTORIAL_VEHICULO"


# ---------------------------------------------------------------------
# V4 -- estructura (campo/valor observado inconsistentes con el contexto)
# ---------------------------------------------------------------------


def test_estructura_invalida_se_rechaza_si_el_campo_no_corresponde():
    contexto = _contexto(campo="patente_tracto")
    hipotesis = _hipotesis(campo="patente_rampla", valor_propuesto="XF3629")
    resultado = validar_hipotesis_vehiculo(hipotesis, contexto)
    assert resultado.aceptada is False
    assert resultado.motivo_rechazo == MOTIVO_ESTRUCTURA_INVALIDA


def test_estructura_invalida_se_rechaza_si_el_valor_observado_no_corresponde():
    contexto = _contexto(valor_documental="XF3662")
    hipotesis = _hipotesis(valor_observado="OTRO-DOC", valor_propuesto="XF3629")
    resultado = validar_hipotesis_vehiculo(hipotesis, contexto)
    assert resultado.aceptada is False
    assert resultado.motivo_rechazo == MOTIVO_ESTRUCTURA_INVALIDA
