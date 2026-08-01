"""Política versionada: el estado se decide antes y nunca por el número."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class ViaDecisionChofer(str, Enum):
    RUT_EXACTO_UNICO = "RUT_EXACTO_UNICO"
    RUT_EXACTO_MAS_NOMBRE_COMPATIBLE = "RUT_EXACTO_MAS_NOMBRE_COMPATIBLE"
    ALIAS_HUMANO_UNICO = "ALIAS_HUMANO_UNICO"
    CANONICO_EXACTO_UNICO = "CANONICO_EXACTO_UNICO"
    RUT_PARCIAL_COMPATIBLE = "RUT_PARCIAL_COMPATIBLE"
    FUZZY_UNICO = "FUZZY_UNICO"
    CONTRADICCION = "CONTRADICCION"
    DUPLICADO = "DUPLICADO"
    INACTIVO = "INACTIVO"
    NO_RESUELTO = "NO_RESUELTO"


@dataclass(frozen=True)
class PoliticaConfianzaChofer:
    version: str
    valores: Mapping[ViaDecisionChofer, float]

    def __post_init__(self) -> None:
        faltantes = set(ViaDecisionChofer) - set(self.valores)
        if faltantes:
            raise ValueError(f"faltan vías de decisión: {sorted(v.value for v in faltantes)}")
        if any(not 0.0 <= valor <= 1.0 for valor in self.valores.values()):
            raise ValueError("las confianzas deben estar entre 0 y 1")
        object.__setattr__(
            self, "valores",
            MappingProxyType({via: float(self.valores[via]) for via in ViaDecisionChofer}),
        )

    def confianza(
        self, via: ViaDecisionChofer, *, medicion_fuzzy: float | None = None
    ) -> float:
        if via is ViaDecisionChofer.FUZZY_UNICO and medicion_fuzzy is not None:
            return max(0.0, min(1.0, float(medicion_fuzzy)))
        return self.valores[via]


POLITICA_CONFIANZA_CHOFER_V1_1 = PoliticaConfianzaChofer(
    version="chofer-rut-1.1",
    valores={
        ViaDecisionChofer.RUT_EXACTO_UNICO: 0.95,
        ViaDecisionChofer.RUT_EXACTO_MAS_NOMBRE_COMPATIBLE: 1.0,
        ViaDecisionChofer.ALIAS_HUMANO_UNICO: 0.90,
        ViaDecisionChofer.CANONICO_EXACTO_UNICO: 0.90,
        ViaDecisionChofer.RUT_PARCIAL_COMPATIBLE: 0.55,
        ViaDecisionChofer.FUZZY_UNICO: 0.85,
        ViaDecisionChofer.CONTRADICCION: 0.0,
        ViaDecisionChofer.DUPLICADO: 0.0,
        ViaDecisionChofer.INACTIVO: 0.0,
        ViaDecisionChofer.NO_RESUELTO: 0.0,
    },
)
