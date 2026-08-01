"""Política versionada para la resolución aislada de vehículo + patente."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class ViaDecisionVehiculo(str, Enum):
    PATENTE_EXACTA_UNICA = "PATENTE_EXACTA_UNICA"
    PAR_TRACTO_RAMPLA_EXACTO = "PAR_TRACTO_RAMPLA_EXACTO"
    CORRECCION_VISUAL_UNICA = "CORRECCION_VISUAL_UNICA"
    ALIAS_SIN_PATENTE = "ALIAS_SIN_PATENTE"
    CONTRADICCION_ROL = "CONTRADICCION_ROL"
    TRACTO_RAMPLA_INTERCAMBIADOS = "TRACTO_RAMPLA_INTERCAMBIADOS"
    DUPLICADO = "DUPLICADO"
    INACTIVO = "INACTIVO"
    EVIDENCIA_BAJA = "EVIDENCIA_BAJA"
    NO_RESUELTO = "NO_RESUELTO"


@dataclass(frozen=True)
class PoliticaConfianzaVehiculo:
    version: str
    valores: Mapping[ViaDecisionVehiculo, float]

    def __post_init__(self) -> None:
        faltantes = set(ViaDecisionVehiculo) - set(self.valores)
        if faltantes:
            raise ValueError(
                f"faltan vías de decisión: {sorted(v.value for v in faltantes)}"
            )
        if any(not 0.0 <= valor <= 1.0 for valor in self.valores.values()):
            raise ValueError("las confianzas deben estar entre 0 y 1")
        object.__setattr__(
            self,
            "valores",
            MappingProxyType({
                via: float(self.valores[via]) for via in ViaDecisionVehiculo
            }),
        )

    def confianza(self, via: ViaDecisionVehiculo) -> float:
        return self.valores[via]


POLITICA_CONFIANZA_VEHICULO_V1 = PoliticaConfianzaVehiculo(
    version="vehiculo-patente-1.0",
    valores={
        ViaDecisionVehiculo.PATENTE_EXACTA_UNICA: 0.98,
        ViaDecisionVehiculo.PAR_TRACTO_RAMPLA_EXACTO: 1.0,
        ViaDecisionVehiculo.CORRECCION_VISUAL_UNICA: 0.75,
        ViaDecisionVehiculo.ALIAS_SIN_PATENTE: 0.45,
        ViaDecisionVehiculo.CONTRADICCION_ROL: 0.0,
        ViaDecisionVehiculo.TRACTO_RAMPLA_INTERCAMBIADOS: 0.0,
        ViaDecisionVehiculo.DUPLICADO: 0.0,
        ViaDecisionVehiculo.INACTIVO: 0.0,
        ViaDecisionVehiculo.EVIDENCIA_BAJA: 0.0,
        ViaDecisionVehiculo.NO_RESUELTO: 0.0,
    },
)
