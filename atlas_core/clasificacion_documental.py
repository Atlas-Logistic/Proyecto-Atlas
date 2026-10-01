"""Evaluación conservadora de hallazgos documentales.

No modifica OCR ni datos operacionales. Este módulo sólo decide si una
observación puede acusar a la guía; ante evidencia histórica incompleta se
abstiene.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping

from atlas_core.incidencias_documentales import (
    ClasificacionDocumental, IncidenciaDocumental, TIPO_RUT_DOCUMENTAL_AUSENTE,
    TIPO_RUT_DOCUMENTAL_INVALIDO,
)

_AUSENTES = {"", "No encontrado", "REVISAR", "Ilegible"}


@dataclass(frozen=True)
class EvaluacionIncidencia:
    clasificacion: ClasificacionDocumental
    vigente_documental: bool
    razon: str


def evaluar_incidencia(incidencia: IncidenciaDocumental, fila: Mapping[str, object] | None = None,
                       confirmaciones: Iterable[object] = ()) -> EvaluacionIncidencia:
    """Clasifica sin inferir culpa desde ausencia, catálogo o decisión operativa."""
    if any(getattr(c, "incidencia_id", "") == incidencia.incidencia_id
           and getattr(c, "clasificacion", "") == ClasificacionDocumental.DOCUMENTAL_CONFIRMADA.value
           for c in confirmaciones):
        return EvaluacionIncidencia(ClasificacionDocumental.DOCUMENTAL_CONFIRMADA, True,
                                    "CONFIRMACION_DOCUMENTAL_HUMANA_EXPLICITA")
    if incidencia.clasificacion != ClasificacionDocumental.NO_VERIFICABLE.value:
        clasificacion = ClasificacionDocumental(incidencia.clasificacion)
        return EvaluacionIncidencia(clasificacion, clasificacion is ClasificacionDocumental.DOCUMENTAL_CONFIRMADA,
                                    "CLASIFICACION_EXPLICITA")
    rut_vigente = str((fila or {}).get("rut_chofer", "")).strip()
    if incidencia.tipo_incidencia == TIPO_RUT_DOCUMENTAL_AUSENTE:
        if not incidencia.numero_guia.isdigit():
            return EvaluacionIncidencia(ClasificacionDocumental.NO_VERIFICABLE, False,
                                        "IDENTIDAD_DE_GUIA_AUSENTE_NO_PERMITE_VERIFICACION")
        if rut_vigente not in _AUSENTES:
            return EvaluacionIncidencia(ClasificacionDocumental.ATLAS_EXTRACCION_ERRONEA, False,
                                        "AUSENCIA_OBSOLETA_EXTRACCION_VIGENTE_CON_RUT")
        return EvaluacionIncidencia(ClasificacionDocumental.NO_VERIFICABLE, False,
                                    "AUSENCIA_EN_EXTRACCION_NO_PRUEBA_AUSENCIA_DOCUMENTAL")
    # Sólo el RUT implausible es una regla estructural existente que conserva
    # el valor observado; cualquier otra diferencia histórica queda pendiente
    # hasta que una persona la confirme explícitamente sobre el documento.
    if incidencia.tipo_incidencia == TIPO_RUT_DOCUMENTAL_INVALIDO:
        return EvaluacionIncidencia(ClasificacionDocumental.DOCUMENTAL_CONFIRMADA, True,
                                    "RUT_DOCUMENTAL_ESTRUCTURALMENTE_INVALIDO")
    return EvaluacionIncidencia(ClasificacionDocumental.NO_VERIFICABLE, False,
                                "EVIDENCIA_HISTORICA_SIN_CONFIRMACION_DOCUMENTAL_EXPLICITA")


def simular_evaluaciones(incidencias: Iterable[IncidenciaDocumental], filas: Iterable[Mapping[str, object],],
                         confirmaciones: Iterable[object] = ()) -> dict[str, object]:
    """Read-only. Conserva cada registro y devuelve su visibilidad propuesta."""
    por_guia = {str(f.get("numero_guia", "")): f for f in filas}
    resultado = []
    for incidencia in incidencias:
        evaluacion = evaluar_incidencia(incidencia, por_guia.get(incidencia.numero_guia), confirmaciones)
        resultado.append({
            "incidencia_id": incidencia.incidencia_id, "numero_guia": incidencia.numero_guia,
            "clasificacion": evaluacion.clasificacion.value,
            "vigente_documental": evaluacion.vigente_documental, "razon": evaluacion.razon,
        })
    return {"conteos": dict(Counter(x["clasificacion"] for x in resultado)), "evaluaciones": resultado}
