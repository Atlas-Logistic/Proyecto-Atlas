"""Adaptadores de sólo lectura -- Bloque A1.

Traducen el resultado REAL de
`atlas_core.decisiones_pendientes.evaluar_evidencia_patente` (el Motor
determinista de vehículos ya en producción, ver
`atlas_core.motor_evidencia` para el patrón general que este motor
inspiró) a los contratos propios de Atlas IA (`contratos.py`).

Nota de compatibilidad: `evaluar_evidencia_patente` es anterior al
contrato genérico `atlas_core.motor_evidencia.CandidatoEvidencia` y no lo
usa -- devuelve un `dict` plano con claves `resultado`/`candidatos`/
`explicacion`, donde cada candidato es a su vez un `dict` con claves
propias del dominio vehicular (`patente`, `vehiculo_id`, `nivel`,
`evidencias`, `conflictos`, `transportes_independientes`, ...). Este
adaptador consume exactamente esa forma real -- nunca reinterpreta ni
recalcula nada que el Motor determinista ya decidió."""

from __future__ import annotations

from typing import Iterable, Mapping

from atlas_core.atlas_ia.contratos import ContextoRazonamiento, EvidenciaIA

_PROCEDENCIA_MOTOR_VEHICULOS = "atlas_core.decisiones_pendientes.evaluar_evidencia_patente"


def _tipo_fuente_desde_evidencias(evidencias: tuple[str, ...]) -> str:
    """Clasifica el tipo de fuente de un candidato vehicular a partir de
    los códigos de evidencia que ya calculó `evaluar_evidencia_patente` --
    nunca inventa una categoría nueva, sólo mapea las ya existentes en el
    Motor determinista (ver `_razon_legible_candidato` en
    `decisiones_pendientes.py` para el vocabulario completo de códigos)."""
    if "CONFIRMACION_HUMANA_ASOCIADA_AL_CHOFER" in evidencias:
        return "DECISION_HUMANA"
    if any(
        e == "CORROBORACION_MISMO_TRANSPORTE" or e.startswith("CORROBORACION_TRANSPORTE_INDEPENDIENTE")
        for e in evidencias
    ):
        return "HISTORICO"
    return "DOCUMENTAL"


def evidencias_ia_desde_candidatos_vehiculo(
    candidatos: Iterable[Mapping[str, object]], *, campo: str,
) -> tuple[EvidenciaIA, ...]:
    """Traduce la lista `candidatos` que devuelve `evaluar_evidencia_patente`
    a `EvidenciaIA`, una por candidato -- sin descartar ninguno (el Motor
    determinista nunca oculta un candidato que perdió, y este adaptador
    tampoco)."""
    resultado: list[EvidenciaIA] = []
    for candidato in candidatos:
        evidencias_codigos = tuple(candidato.get("evidencias") or ())
        tipo_fuente = _tipo_fuente_desde_evidencias(evidencias_codigos)
        resultado.append(EvidenciaIA(
            identificador=str(candidato.get("vehiculo_id", "")),
            campo=campo,
            valor=str(candidato.get("patente", "")),
            tipo_fuente=tipo_fuente,
            nivel=str(candidato.get("nivel", "")),
            a_favor=evidencias_codigos,
            en_contra=tuple(candidato.get("conflictos") or ()),
            independencia=int(candidato.get("transportes_independientes", 0) or 0),
            es_decision_humana=(tipo_fuente == "DECISION_HUMANA"),
            procedencia=_PROCEDENCIA_MOTOR_VEHICULOS,
        ))
    return tuple(resultado)


def contexto_desde_resultado_evaluar_evidencia_patente(
    *,
    campo: str,
    valor_documental: str,
    rut_chofer: str,
    numero_guia: str,
    numero_transporte: str,
    resultado_evidencia: Mapping[str, object],
) -> ContextoRazonamiento:
    """Adaptador principal de A1 (vertical vehículos): construye un
    `ContextoRazonamiento` a partir del `dict` REAL que devuelve
    `evaluar_evidencia_patente` -- sin volver a llamar al Motor
    determinista, sin releer el dataset ni los catálogos. `campo`,
    `valor_documental`, `rut_chofer`, `numero_guia` y `numero_transporte`
    son exactamente los mismos argumentos ya usados para producir
    `resultado_evidencia` -- este adaptador no los deriva de nuevo, los
    recibe para no duplicar ninguna lógica de resolución."""
    candidatos = resultado_evidencia.get("candidatos") or []
    evidencias = evidencias_ia_desde_candidatos_vehiculo(candidatos, campo=campo)
    return ContextoRazonamiento(
        campo=campo,
        valor_documental=valor_documental,
        rut_chofer=rut_chofer,
        numero_guia=numero_guia,
        numero_transporte=numero_transporte,
        evidencias=evidencias,
        resultado_motor=str(resultado_evidencia.get("resultado", "")),
        explicacion_motor=str(resultado_evidencia.get("explicacion", "")),
    )
