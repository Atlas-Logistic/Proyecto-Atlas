"""Política versionada para destino, ubicación y planta de salida."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class ViaDecisionDestino(str, Enum):
    DESTINO_EXACTO_UNICO = "DESTINO_EXACTO_UNICO"
    ALIAS_EXACTO_UNICO = "ALIAS_EXACTO_UNICO"
    DIRECCION_EXACTA_UNICA = "DIRECCION_EXACTA_UNICA"
    NOMBRE_MAS_DIRECCION = "NOMBRE_MAS_DIRECCION"
    FUZZY_MAS_DIRECCION = "FUZZY_MAS_DIRECCION"
    FUZZY_O_PARCIAL = "FUZZY_O_PARCIAL"
    CODIGO_DESTINATARIO_EXACTO = "CODIGO_DESTINATARIO_EXACTO"
    CONTRADICCION = "CONTRADICCION"
    DUPLICADO = "DUPLICADO"
    INACTIVO = "INACTIVO"
    CALIDAD_INCOMPLETA = "CALIDAD_INCOMPLETA"
    NO_RESUELTO = "NO_RESUELTO"


@dataclass(frozen=True)
class PoliticaConfianzaDestino:
    version: str
    valores: Mapping[ViaDecisionDestino, float]

    def __post_init__(self) -> None:
        faltantes = set(ViaDecisionDestino) - set(self.valores)
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
                via: float(self.valores[via]) for via in ViaDecisionDestino
            }),
        )

    def confianza(
        self, via: ViaDecisionDestino, *, medicion: float | None = None
    ) -> float:
        if via is ViaDecisionDestino.FUZZY_O_PARCIAL and medicion is not None:
            return max(0.0, min(1.0, float(medicion)))
        return self.valores[via]


POLITICA_CONFIANZA_DESTINO_V1 = PoliticaConfianzaDestino(
    "destino-ubicacion-1.0",
    {
        ViaDecisionDestino.DESTINO_EXACTO_UNICO: 0.95,
        ViaDecisionDestino.ALIAS_EXACTO_UNICO: 0.93,
        ViaDecisionDestino.DIRECCION_EXACTA_UNICA: 0.98,
        ViaDecisionDestino.NOMBRE_MAS_DIRECCION: 1.0,
        ViaDecisionDestino.FUZZY_MAS_DIRECCION: 0.92,
        ViaDecisionDestino.FUZZY_O_PARCIAL: 0.65,
        # Código Destinatario exacto y único contra un registro maestro
        # CONFIRMADO/CONFIRMADO_DOCUMENTAL: sin ninguna comparación difusa
        # de texto, al mismo nivel de exigencia que una dirección completa
        # exacta.
        ViaDecisionDestino.CODIGO_DESTINATARIO_EXACTO: 0.98,
        ViaDecisionDestino.CONTRADICCION: 0.0,
        ViaDecisionDestino.DUPLICADO: 0.0,
        ViaDecisionDestino.INACTIVO: 0.0,
        ViaDecisionDestino.CALIDAD_INCOMPLETA: 0.0,
        ViaDecisionDestino.NO_RESUELTO: 0.0,
    },
)
