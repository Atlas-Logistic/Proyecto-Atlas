"""Políticas explícitas, centralizadas y configurables por campo."""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping

from atlas_core.inteligencia.modelos import TipoFuente


PESOS_FUENTE: Mapping[TipoFuente, float] = MappingProxyType(
    {
        TipoFuente.OCR: 0.55,
        TipoFuente.GEOMETRIA: 0.65,
        TipoFuente.CATALOGO: 0.90,
        TipoFuente.RELACION_CAMPO: 0.85,
        TipoFuente.HISTORICO: 0.45,
        TipoFuente.CORRECCION_HUMANA: 1.00,
        TipoFuente.VERIFICACION_EXTERNA: 0.65,
        TipoFuente.MODELO_IA: 0.25,
        TipoFuente.REGLA_DETERMINISTA: 0.95,
    }
)


def _siempre(_valor: str) -> bool:
    return True


def _solo_digitos(valor: str) -> bool:
    return bool(re.fullmatch(r"\d+", valor))


@dataclass(frozen=True)
class PoliticaResolucion:
    campo: str
    umbral_confirmacion: float = 1.25
    umbral_propuesta: float = 0.80
    margen_minimo: float = 0.35
    umbral_contradiccion: float = 0.65
    pesos_fuente: Mapping[TipoFuente, float] = PESOS_FUENTE
    validador: Callable[[str], bool] = _siempre
    inferencias_prohibidas: tuple[str, ...] = ()


_CAMPOS = (
    "chofer",
    "rut_chofer",
    "cliente",
    "destino",
    "patente_tracto",
    "patente_rampla",
    "fecha",
    "numero_transporte",
    "numero_guia",
    "planta_origen",
    "comuna",
    "region",
)

POLITICAS: Mapping[str, PoliticaResolucion] = MappingProxyType(
    {
        campo: PoliticaResolucion(
            campo=campo,
            # Una segunda fecha plausible exige revisión aun si procede de OCR,
            # porque día y mes pueden intercambiarse sin una señal visible.
            umbral_contradiccion=0.50 if campo == "fecha" else 0.65,
            validador=(
                _solo_digitos
                if campo in {"numero_transporte", "numero_guia"}
                else _siempre
            ),
            inferencias_prohibidas={
                "cliente": ("destino",),
                "destino": ("cliente",),
                "chofer": ("patente_tracto", "patente_rampla"),
                "patente_tracto": ("chofer",),
                "patente_rampla": ("chofer",),
                "planta_origen": ("cercania",),
            }.get(campo, ()),
        )
        for campo in _CAMPOS
    }
)


def obtener_politica(campo: str) -> PoliticaResolucion:
    try:
        return POLITICAS[campo]
    except KeyError as exc:
        raise ValueError(f"No existe política para el campo: {campo}") from exc
