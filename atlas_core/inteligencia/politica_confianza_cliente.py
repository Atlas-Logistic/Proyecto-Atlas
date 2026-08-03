"""Política versionada para resolución aislada de cliente + RUT."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class ViaDecisionCliente(str, Enum):
    RUT_EXACTO_UNICO = "RUT_EXACTO_UNICO"
    RUT_EXACTO_MAS_NOMBRE_COMPATIBLE = "RUT_EXACTO_MAS_NOMBRE_COMPATIBLE"
    ALIAS_HUMANO_UNICO = "ALIAS_HUMANO_UNICO"
    CANONICO_EXACTO_UNICO = "CANONICO_EXACTO_UNICO"
    FUZZY_MAS_RUT = "FUZZY_MAS_RUT"
    FUZZY_ALTA_CONFIANZA = "FUZZY_ALTA_CONFIANZA"
    FUZZY_UNICO = "FUZZY_UNICO"
    CONTRADICCION = "CONTRADICCION"
    DUPLICADO = "DUPLICADO"
    INACTIVO = "INACTIVO"
    CALIDAD_NO_CONFIRMADA = "CALIDAD_NO_CONFIRMADA"
    NO_RESUELTO = "NO_RESUELTO"


@dataclass(frozen=True)
class PoliticaConfianzaCliente:
    version: str
    valores: Mapping[ViaDecisionCliente, float]

    def __post_init__(self) -> None:
        faltantes = set(ViaDecisionCliente) - set(self.valores)
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
                via: float(self.valores[via]) for via in ViaDecisionCliente
            }),
        )

    def confianza(
        self, via: ViaDecisionCliente, *, medicion_fuzzy: float | None = None
    ) -> float:
        if (
            via in (ViaDecisionCliente.FUZZY_UNICO, ViaDecisionCliente.FUZZY_ALTA_CONFIANZA)
            and medicion_fuzzy is not None
        ):
            return max(0.0, min(1.0, float(medicion_fuzzy)))
        return self.valores[via]


POLITICA_CONFIANZA_CLIENTE_V1 = PoliticaConfianzaCliente(
    version="cliente-rut-1.0",
    valores={
        ViaDecisionCliente.RUT_EXACTO_UNICO: 0.95,
        ViaDecisionCliente.RUT_EXACTO_MAS_NOMBRE_COMPATIBLE: 1.0,
        ViaDecisionCliente.ALIAS_HUMANO_UNICO: 0.90,
        ViaDecisionCliente.CANONICO_EXACTO_UNICO: 0.90,
        ViaDecisionCliente.FUZZY_MAS_RUT: 0.98,
        ViaDecisionCliente.FUZZY_ALTA_CONFIANZA: 0.95,
        ViaDecisionCliente.FUZZY_UNICO: 0.85,
        ViaDecisionCliente.CONTRADICCION: 0.0,
        ViaDecisionCliente.DUPLICADO: 0.0,
        ViaDecisionCliente.INACTIVO: 0.0,
        ViaDecisionCliente.CALIDAD_NO_CONFIRMADA: 0.0,
        ViaDecisionCliente.NO_RESUELTO: 0.0,
    },
)
