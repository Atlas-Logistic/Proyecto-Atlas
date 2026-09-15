"""Bloque AUTORIDAD OPERACIONAL / DESTINO SIN OBRA (Codex 472623/472624).

Causa raíz real: la única vía de evidencia que el dominio DESTINO tenía
para B1 (`recopilar_evidencia_destino`, antes `..._por_obra_relacionada`)
exigía una `obra_destino` ya resuelta -- sin ella, `evidencias` quedaba
`[]` aunque el Motor YA hubiera leído `despachar_a_crudo` directamente
del documento por un método confiable, o aunque una guía hermana del
mismo transporte imprimiera exactamente el mismo valor. La barrera
anti-alucinación (`validadores.validar_hipotesis_multicampo`) rechazaba
entonces CUALQUIER propuesta con `VALOR_NO_RESPALDADO_POR_EVIDENCIA`,
sin importar cuán clara fuera la dirección en la imagen -- caso real
472623/472624: "SAN LUIS 1201 QUILICURA" impreso limpio en DESPACHAR A
de dos guías hermanas, `obra_destino="No encontrado"` en ambas.

Este bloque nunca hardcodea un número de guía ni un valor de dirección:
las dos fuentes nuevas (extracción confiable propia, corroboración entre
guías hermanas del mismo transporte) son capacidades generales."""
from __future__ import annotations

from atlas_core.atlas_ia.contratos import (
    ContextoRazonamiento,
    EvidenciaIA,
    HipotesisIA,
    MOTIVO_VALOR_NO_RESPALDADO,
    RESULTADO_HIPOTESIS_PROPUESTA,
)
from atlas_core.atlas_ia.registro_problemas import recopilar_evidencia_destino
from atlas_core.atlas_ia.validadores import validar_hipotesis_multicampo
from atlas_core.procesamiento_masivo import COLUMNAS


def _fila(**cambios):
    fila = {columna: "" for columna in COLUMNAS}
    fila.update({
        "numero_guia": "SIM-1", "numero_transporte": "T-SIM-1",
        "archivo": "sim1.jpeg", "obra_destino": "No encontrado",
    })
    fila.update(cambios)
    return fila


# ---------------------------------------------------------------------
# 1. Extracción confiable respalda destino SIN obra resuelta.
# ---------------------------------------------------------------------

def test_extraccion_confiable_respalda_destino_sin_obra_resuelta():
    fila = _fila(
        despachar_a_crudo="SAN LUIS 1201 QUILICURA",
        metodos_recuperacion_documento="CATALOGO | CONTEXTUAL | GEOMETRICO",
    )

    evidencias = recopilar_evidencia_destino(fila, [fila])

    assert any(
        e.valor == "SAN LUIS 1201 QUILICURA" and e.tipo_fuente == "DOCUMENTAL"
        for e in evidencias
    )


def test_extraccion_no_confiable_no_respalda_destino_sin_obra():
    """Control: un método de recuperación NO confiable (ninguno de
    GEOMETRICO/CONTEXTUAL -- p. ej. sólo homologación de catálogo de otro
    campo) no genera evidencia DOCUMENTAL por sí solo."""
    fila = _fila(
        despachar_a_crudo="UNA DIRECCION CUALQUIERA 123",
        metodos_recuperacion_documento="HOMOLOGADO",
    )

    evidencias = recopilar_evidencia_destino(fila, [fila])

    assert evidencias == ()


# ---------------------------------------------------------------------
# 2. Dos guías hermanas del mismo transporte corroboran el mismo destino.
# ---------------------------------------------------------------------

def test_guias_hermanas_mismo_transporte_corroboran_destino():
    fila_a = _fila(
        numero_guia="A", archivo="a.jpeg", numero_transporte="T-HERMANAS",
        despachar_a_crudo="SAN LUIS 1201 QUILICURA",
        metodos_recuperacion_documento="",  # sin extracción confiable propia
    )
    fila_b = _fila(
        numero_guia="B", archivo="b.jpeg", numero_transporte="T-HERMANAS",
        despachar_a_crudo="SAN LUIS 1201 QUILICURA",
        metodos_recuperacion_documento="GEOMETRICO",
    )

    evidencias_a = recopilar_evidencia_destino(fila_a, [fila_a, fila_b])

    assert any(
        e.valor == "SAN LUIS 1201 QUILICURA" and e.tipo_fuente == "HISTORICO"
        and e.nivel == "TRANSPORTE_RELACIONADO"
        for e in evidencias_a
    )


# ---------------------------------------------------------------------
# 3. Misma dirección en TRANSPORTES DISTINTOS no es evidencia cruzada.
# ---------------------------------------------------------------------

def test_misma_direccion_en_transporte_distinto_no_es_evidencia_cruzada():
    fila_a = _fila(
        numero_guia="A", archivo="a.jpeg", numero_transporte="T-UNO",
        despachar_a_crudo="AV SIEMPRE VIVA 742",
        metodos_recuperacion_documento="",
    )
    fila_c = _fila(
        numero_guia="C", archivo="c.jpeg", numero_transporte="T-OTRO-DISTINTO",
        despachar_a_crudo="AV SIEMPRE VIVA 742",
        metodos_recuperacion_documento="",
    )

    evidencias_a = recopilar_evidencia_destino(fila_a, [fila_a, fila_c])

    assert evidencias_a == ()


# ---------------------------------------------------------------------
# 4. Evidencia contradictoria sigue bloqueando aceptación.
# ---------------------------------------------------------------------

def test_hermanas_con_valores_distintos_no_se_corroboran_entre_si():
    """Dos guías del mismo transporte que imprimen direcciones DISTINTAS
    -- evidencia real de desacuerdo -- nunca se fabrica una corroboración
    falsa para ninguna de las dos por la vía de guía hermana."""
    fila_a = _fila(
        numero_guia="A", archivo="a.jpeg", numero_transporte="T-CONTRADICTORIO",
        despachar_a_crudo="CALLE UNO 100",
        metodos_recuperacion_documento="",
    )
    fila_b = _fila(
        numero_guia="B", archivo="b.jpeg", numero_transporte="T-CONTRADICTORIO",
        despachar_a_crudo="CALLE DOS 200",
        metodos_recuperacion_documento="",
    )

    evidencias_a = recopilar_evidencia_destino(fila_a, [fila_a, fila_b])

    assert not any(e.nivel == "TRANSPORTE_RELACIONADO" for e in evidencias_a)


def test_decision_humana_contradictoria_sigue_bloqueando_pese_a_evidencia_nueva():
    """La barrera anti-alucinación (`validadores`) sigue rechazando una
    propuesta que contradiga una decisión HUMANA ya aplicada -- la
    evidencia nueva (documental/hermana) nunca la pasa por encima."""
    contexto = ContextoRazonamiento(
        campo="despachar_a_crudo", valor_documental="SAN LUIS 1201 QUILICURA",
        rut_chofer="10833150-K", numero_guia="472623", numero_transporte="0000355433",
        evidencias=(
            EvidenciaIA(
                identificador="documento:a.jpeg:destino_propio", campo="despachar_a_crudo",
                valor="SAN LUIS 1201 QUILICURA", tipo_fuente="DOCUMENTAL", nivel="EXTRACCION_CONFIABLE",
            ),
            EvidenciaIA(
                identificador="ledger:decision-humana", campo="despachar_a_crudo",
                valor="OTRA DIRECCION CONFIRMADA POR JAVIER 999", tipo_fuente="DECISION_HUMANA",
                nivel="CONFIRMACION_HUMANA", es_decision_humana=True,
            ),
        ),
    )
    hipotesis = HipotesisIA(
        hipotesis_id="x", campo="despachar_a_crudo",
        valor_observado="SAN LUIS 1201 QUILICURA", valor_propuesto="SAN LUIS 1201 QUILICURA",
        resultado=RESULTADO_HIPOTESIS_PROPUESTA,
    )

    resultado = validar_hipotesis_multicampo(hipotesis, contexto)

    assert resultado.aceptada is False


# ---------------------------------------------------------------------
# Integración: el caso real 472623/472624 -- evidencia nueva revierte el
# rechazo VALOR_NO_RESPALDADO_POR_EVIDENCIA sin necesitar obra resuelta.
# ---------------------------------------------------------------------

def test_caso_real_472623_472624_evidencia_nueva_revierte_rechazo():
    fila_472623 = _fila(
        numero_guia="472623", archivo="mobile/a/original.jpg", numero_transporte="0000355433",
        despachar_a_crudo="SAN LUIS 1201 QUILICURA",
        metodos_recuperacion_documento="CATALOGO | CONTEXTUAL | GEOMETRICO",
        obra_destino="No encontrado",
    )
    fila_472624 = _fila(
        numero_guia="472624", archivo="mobile/b/original.jpg", numero_transporte="0000355433",
        despachar_a_crudo="SAN LUIS 1201 QUILICURA",
        metodos_recuperacion_documento="GEOMETRICO",
        obra_destino="No encontrado",
    )

    evidencias = recopilar_evidencia_destino(fila_472623, [fila_472623, fila_472624])
    assert evidencias  # Antes del fix: () -- ningún elemento posible.

    contexto = ContextoRazonamiento(
        campo="despachar_a_crudo", valor_documental="SAN LUIS 1201 QUILICURA",
        rut_chofer="10833150-K", numero_guia="472623", numero_transporte="0000355433",
        evidencias=evidencias,
    )
    hipotesis = HipotesisIA(
        hipotesis_id="x", campo="despachar_a_crudo",
        valor_observado="SAN LUIS 1201 QUILICURA", valor_propuesto="SAN LUIS 1201 QUILICURA",
        resultado=RESULTADO_HIPOTESIS_PROPUESTA,
    )

    resultado = validar_hipotesis_multicampo(hipotesis, contexto)

    assert resultado.aceptada is True
    assert resultado.motivo_rechazo != MOTIVO_VALOR_NO_RESPALDADO
