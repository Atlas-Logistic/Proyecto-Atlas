"""Interpretación acotada del error documental de equipo para integrar en B1.

Devuelve únicamente los parámetros de una acción oficial. El llamador debe
usar CapaAccionesOperacionales.previsualizar y su confirmación habitual; este
módulo no lee ni escribe datos y no cambia asignaciones de vehículos.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class IntencionErrorEquipo:
    accion: str
    parametros: dict[str, str]


def interpretar_error_equipo(texto: str) -> IntencionErrorEquipo | None:
    """Reconoce sólo una declaración explícita de error documental en UNA guía.

    Una patente indicada en una frase genérica puede significar corrección OCR
    o cambio de equipo; no la interpreta como autorización para ninguno de los
    dos. Se requiere mencionar el error y el equipo/asignación vigente.
    """
    original = " ".join(str(texto or "").split())
    plano = unicodedata.normalize("NFKD", original.upper())
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    plano = plano.strip().rstrip(".!")
    especifica = re.fullmatch(
        r"(?:CORRIGE|CORREGIR|CONFIRMA|CONFIRMAR) (?:EL )?ERROR (?:DOCUMENTAL|(?:DE )?OCR) "
        r"(?:DE |EN )?(?:LA )?GUIA\s*(?:N[°º]?\s*)?(?P<guia>\d{3,12})[,:]? "
        r"(?:LA )?PATENTE (?:(?:DEL|DE LA|DE) )?(?P<tipo>TRACTO|CAMION|RAMPLA|CARRO) "
        r"(?:ES|A|POR) (?P<patente>[A-Z0-9]{6})", plano)
    if especifica:
        tipo = especifica.group("tipo")
        return IntencionErrorEquipo(
            accion="DOCUMENTO_CONFIRMAR_ERROR_DOCUMENTAL_AZA",
            parametros={"numero_guia": especifica.group("guia"), "referencia": original[:500],
                        "campo_declarado": "patente_tracto" if tipo in {"TRACTO", "CAMION"} else "patente_rampla",
                        "patente_declarada": especifica.group("patente")})
    patron = (
        r"(?:CONFIRMA|CONFIRMAR) (?:EL )?ERROR DOCUMENTAL(?: DE AZA| AZA)? "
        r"(?:DE |EN )?(?:LA )?GUIA\s*(?:N[°º]?\s*)?(?P<guia>\d{3,12}) "
        r"(?:Y )?(?:USA|USAR) (?:EL )?(?:EQUIPO|ASIGNACION) VIGENTE"
    )
    coincidencia = re.fullmatch(patron, plano)
    if coincidencia is None:
        return None
    return IntencionErrorEquipo(
        accion="DOCUMENTO_CONFIRMAR_ERROR_DOCUMENTAL_AZA",
        parametros={"numero_guia": coincidencia.group("guia"), "referencia": original[:500]},
    )
