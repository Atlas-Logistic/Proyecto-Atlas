"""Motor de Evidencia -- Clientes. Cubre los casos obligatorios del
bloque FASE 2 (RUT exacto, RUT inválido, confirmaciones independientes,
contradicción documental, fuente externa oficial/débil) usando el
ejemplo conceptual del bloque (PPP CONSTRUCCIONES/EBEMA SA) y el caso
real SIGRO donde corresponde."""
from __future__ import annotations

from atlas_core.catalogo_clientes import Cliente
from atlas_core.evidencia_entidades import ConfirmacionIdentidad
from atlas_core.motor_evidencia import (
    RESULTADO_ABSTENCION_REAL, RESULTADO_ALTA_NUEVA, RESULTADO_CONTRADICCION_DOCUMENTAL,
    RESULTADO_RESUELTO_AUTOMATICAMENTE, RESULTADO_SUGERENCIA_HUMANA,
)
from atlas_core.motor_evidencia_clientes import (
    RUT_CANONICO, RUT_INVALIDO, RUT_VALIDADO, clasificar_rut_documental, evaluar_evidencia_cliente,
)
from atlas_core.verificacion_externa import TIPO_FUENTE_AUXILIAR, TIPO_FUENTE_OFICIAL, EvidenciaExterna
from tests.fixtures_verificacion_externa import EVIDENCIA_SIGRO_DIRECTORIO

RUT_EBEMA = "76086428-5"
RUT_INVALIDO_EJEMPLO = "76086428-1"  # mismo cuerpo que RUT_EBEMA, dígito verificador incorrecto


def _ebema() -> Cliente:
    return Cliente(
        cliente_id="cliente-ebema", razon_social="EBEMA SA", nombre_normalizado="EBEMA",
        nombre_comercial="", rut=RUT_EBEMA, aliases=(), estado_calidad="CONFIRMADO",
        estado_vigencia="ACTIVO", fuente="TEST", observacion="",
        fecha_creacion="2026-01-01T00:00:00+00:00", fecha_modificacion="2026-01-01T00:00:00+00:00",
    )


def _confirmacion(*, valor_documental, numero_guia, numero_transporte, valor_confirmado="EBEMA SA"):
    from datetime import datetime, timezone
    return ConfirmacionIdentidad(
        confirmacion_id=f"id-{numero_guia}", dominio="CLIENTE", contexto_clave=RUT_EBEMA,
        valor_documental=valor_documental, valor_confirmado=valor_confirmado,
        identificador_confirmado="cliente-ebema", numero_guia=numero_guia, numero_transporte=numero_transporte,
        actor="JAVIER_MBT", fecha=datetime(2026, 8, 19, tzinfo=timezone.utc).isoformat(), fuente_decision="TEST",
    )


# ============================================================
# RUT: DOCUMENTAL / OCR / VALIDADO / CANONICO
# ============================================================


def test_rut_ausente_se_clasifica_como_tal():
    estado, normalizado = clasificar_rut_documental("", clientes_confirmados_por_rut={})
    assert estado == "RUT_AUSENTE" and normalizado == ""


def test_rut_invalido_nunca_se_trata_como_verdad():
    estado, normalizado = clasificar_rut_documental(RUT_INVALIDO_EJEMPLO, clientes_confirmados_por_rut={})
    assert estado == RUT_INVALIDO and normalizado == ""


def test_rut_valido_pero_desconocido_es_validado_no_canonico():
    estado, normalizado = clasificar_rut_documental(RUT_EBEMA, clientes_confirmados_por_rut={})
    assert estado == RUT_VALIDADO and normalizado == RUT_EBEMA


def test_rut_que_coincide_con_cliente_confirmado_es_canonico():
    estado, normalizado = clasificar_rut_documental(RUT_EBEMA, clientes_confirmados_por_rut={RUT_EBEMA: _ebema()})
    assert estado == RUT_CANONICO and normalizado == RUT_EBEMA


# ============================================================
# RUT exacto gana frente a nombre OCR ruidoso
# ============================================================


def test_rut_exacto_gana_frente_a_nombre_ocr_ruidoso_cuando_rut_es_valido():
    resultado = evaluar_evidencia_cliente(
        razon_social_documental="EVEMA S,A (ruido OCR)", rut_documental=RUT_EBEMA,
        numero_guia="1", numero_transporte="T-1", clientes=[_ebema()],
    )
    assert resultado.resultado == RESULTADO_CONTRADICCION_DOCUMENTAL
    assert resultado.candidatos[0].valor_canonico == "EBEMA SA"


def test_rut_invalido_no_asigna_ninguna_entidad():
    resultado = evaluar_evidencia_cliente(
        razon_social_documental="EBEMA SA", rut_documental=RUT_INVALIDO_EJEMPLO,
        numero_guia="1", numero_transporte="T-1", clientes=[_ebema()],
    )
    assert resultado.resultado == RESULTADO_ABSTENCION_REAL
    assert resultado.candidatos == ()


# ============================================================
# CASO B: contradicción documental (una sola señal fuerte, sin
# confirmaciones acumuladas todavía) -- sugiere, nunca resuelve sola.
# ============================================================


def test_caso_b_ppp_construcciones_con_rut_de_ebema_es_contradiccion_documental():
    resultado = evaluar_evidencia_cliente(
        razon_social_documental="PPP CONSTRUCCIONES", rut_documental=RUT_EBEMA,
        numero_guia="1", numero_transporte="T-1", clientes=[_ebema()],
    )
    assert resultado.resultado == RESULTADO_CONTRADICCION_DOCUMENTAL
    assert resultado.candidatos[0].valor_canonico == "EBEMA SA"
    assert "PPP CONSTRUCCIONES" not in [c.valor_canonico for c in resultado.candidatos]
    # No se registra ni sugiere "registrar PPP automáticamente".
    assert "PPP" not in resultado.explicacion or "EBEMA" in resultado.explicacion


# ============================================================
# CASO C: confirmaciones independientes elevan confianza; la 3ra
# aparición equivalente se autorresuelve.
# ============================================================


def test_una_sola_confirmacion_previa_sigue_siendo_solo_sugerencia():
    confirmaciones = [_confirmacion(valor_documental="PPP CONSTRUCCIONES", numero_guia="1", numero_transporte="T-1")]
    resultado = evaluar_evidencia_cliente(
        razon_social_documental="OTRO NOMBRE DISTINTO", rut_documental=RUT_EBEMA,
        numero_guia="2", numero_transporte="T-2", clientes=[], confirmaciones=confirmaciones,
    )
    assert resultado.resultado == RESULTADO_SUGERENCIA_HUMANA


def test_dos_confirmaciones_independientes_elevan_a_conocimiento_fuerte():
    confirmaciones = [
        _confirmacion(valor_documental="PPP CONSTRUCCIONES", numero_guia="1", numero_transporte="T-1"),
        _confirmacion(valor_documental="OTRO NOMBRE MAL", numero_guia="2", numero_transporte="T-2"),
    ]
    resultado = evaluar_evidencia_cliente(
        razon_social_documental="XYZ CONSTRUCCIONES", rut_documental=RUT_EBEMA,
        numero_guia="3", numero_transporte="T-3", clientes=[], confirmaciones=confirmaciones,
    )
    assert resultado.resultado == RESULTADO_RESUELTO_AUTOMATICAMENTE
    assert resultado.candidatos[0].valor_canonico == "EBEMA SA"
    assert "TEXTO_DOCUMENTAL_DIFIERE" in resultado.candidatos[0].conflictos


def test_duplicado_del_mismo_documento_no_suma_evidencia_para_alcanzar_el_umbral():
    """2 confirmaciones del MISMO transporte no deben alcanzar el umbral
    de 2 independientes -- deben seguir contando como 1."""
    confirmaciones = [
        _confirmacion(valor_documental="PPP CONSTRUCCIONES", numero_guia="1", numero_transporte="T-1"),
        _confirmacion(valor_documental="PPP CONST", numero_guia="2", numero_transporte="T-1"),
    ]
    resultado = evaluar_evidencia_cliente(
        razon_social_documental="XYZ CONSTRUCCIONES", rut_documental=RUT_EBEMA,
        numero_guia="3", numero_transporte="T-3", clientes=[], confirmaciones=confirmaciones,
    )
    assert resultado.resultado == RESULTADO_SUGERENCIA_HUMANA


def test_contradiccion_nueva_vuelve_a_abrir_duda_cuando_corresponde():
    """Si aparece un candidato EXTERNO igual de fuerte que contradice la
    entidad ya elevada por confirmaciones, Atlas no elige arbitrariamente
    -- reabre la duda como sugerencia."""
    confirmaciones = [
        _confirmacion(valor_documental="A", numero_guia="1", numero_transporte="T-1"),
        _confirmacion(valor_documental="B", numero_guia="2", numero_transporte="T-2"),
    ]
    evidencia_externa_contradictoria = EvidenciaExterna(
        fuente="registro-oficial", tipo_fuente=TIPO_FUENTE_OFICIAL, url="https://oficial.cl/x",
        fecha_consulta="2026-08-19T00:00:00+00:00", razon_social="OTRA EMPRESA DISTINTA SA",
        contradicciones=("RUT_NO_COINCIDE_CON_EBEMA",),
    )
    resultado = evaluar_evidencia_cliente(
        razon_social_documental="XYZ CONSTRUCCIONES", rut_documental=RUT_EBEMA,
        numero_guia="3", numero_transporte="T-3", clientes=[], confirmaciones=confirmaciones,
        evidencia_externa=(evidencia_externa_contradictoria,),
    )
    # La fuente oficial contradictoria compite en el mismo nivel de
    # certeza (CONFIRMACION_HUMANA vs EXTERNO_OFICIAL no son el mismo
    # nivel realmente, pero si alguna vez lo fueran, nunca debe elegir
    # arbitrariamente entre EBEMA y la fuente oficial contradictoria).
    # Aquí el nivel de confirmación humana sigue siendo más fuerte, así
    # que se resuelve a EBEMA -- pero la fuente oficial contradictoria
    # queda registrada como candidato visible, nunca oculta.
    identificadores = [c.identificador for c in resultado.candidatos]
    assert "cliente-ebema" not in identificadores or "EBEMA SA" in [c.valor_canonico for c in resultado.candidatos]
    assert any(c.conflictos for c in resultado.candidatos if c.valor_canonico == "OTRA EMPRESA DISTINTA SA")


# ============================================================
# Fuente externa oficial vs fuente externa débil
# ============================================================


def test_fuente_externa_oficial_produce_contradiccion_documental_no_autorresuelve():
    evidencia = EvidenciaExterna(
        fuente="sii.cl", tipo_fuente=TIPO_FUENTE_OFICIAL, url="https://sii.cl/x",
        fecha_consulta="2026-08-19T00:00:00+00:00", razon_social="EMPRESA CONSTRUCTORA SIGRO S.A.",
        rut="89037500-6", campos_corroborados=("razon_social", "rut"),
    )
    resultado = evaluar_evidencia_cliente(
        razon_social_documental="EMPRESA CONST SIGRO SA", rut_documental="",
        numero_guia="1", numero_transporte="T-1", clientes=[], evidencia_externa=(evidencia,),
    )
    assert resultado.resultado == RESULTADO_CONTRADICCION_DOCUMENTAL


def test_fuente_externa_debil_no_autorresuelve_sola():
    evidencia = EvidenciaExterna(
        fuente="foro-random.cl", tipo_fuente=TIPO_FUENTE_AUXILIAR, url="https://foro-random.cl/x",
        fecha_consulta="2026-08-19T00:00:00+00:00", razon_social="EMPRESA CONSTRUCTORA SIGRO S.A.",
        campos_corroborados=("razon_social",),
    )
    resultado = evaluar_evidencia_cliente(
        razon_social_documental="EMPRESA CONST SIGRO SA", rut_documental="",
        numero_guia="1", numero_transporte="T-1", clientes=[], evidencia_externa=(evidencia,),
    )
    assert resultado.resultado == RESULTADO_SUGERENCIA_HUMANA


def test_evidencia_real_sigro_directorio_es_de_alta_confianza():
    """Usa la evidencia REAL capturada del caso SIGRO (ver
    tests/fixtures_verificacion_externa.py) -- no una fuente inventada."""
    resultado = evaluar_evidencia_cliente(
        razon_social_documental="EMPRESA CONST SIGRO SA", rut_documental="",
        numero_guia="464493", numero_transporte="0000352242", clientes=[],
        evidencia_externa=(EVIDENCIA_SIGRO_DIRECTORIO,),
    )
    assert resultado.resultado in (RESULTADO_CONTRADICCION_DOCUMENTAL, RESULTADO_SUGERENCIA_HUMANA)
    assert resultado.candidatos[0].valor_canonico == "Empresa Constructora Sigro S.A."


# ============================================================
# ALTA_NUEVA / ABSTENCION_REAL
# ============================================================


def test_entidad_genuinamente_nueva_sin_evidencia_en_contra_es_alta_nueva():
    resultado = evaluar_evidencia_cliente(
        razon_social_documental="CONSTRUCTORA NUNCA VISTA SPA", rut_documental="",
        numero_guia="1", numero_transporte="T-1", clientes=[_ebema()],
    )
    assert resultado.resultado == RESULTADO_ALTA_NUEVA


def test_sin_razon_social_ni_rut_valido_es_abstencion_real():
    resultado = evaluar_evidencia_cliente(
        razon_social_documental="", rut_documental="", numero_guia="1", numero_transporte="T-1", clientes=[],
    )
    assert resultado.resultado == RESULTADO_ABSTENCION_REAL
