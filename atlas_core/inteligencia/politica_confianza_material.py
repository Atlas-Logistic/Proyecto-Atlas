"""Política versionada del Motor Multicampo 1G."""

from dataclasses import dataclass
from enum import Enum


class ViaDecisionMaterial(str, Enum):
    EXACTO = "EXACTO"
    ALIAS = "ALIAS"
    ABREVIACION = "ABREVIACION"
    FUZZY_MAS_TIPO = "FUZZY_MAS_TIPO"
    FUZZY_AISLADO = "FUZZY_AISLADO"
    COMPUESTO = "COMPUESTO"
    CONTRADICCION = "CONTRADICCION"
    AMBIGUO = "AMBIGUO"
    INACTIVO = "INACTIVO"
    NO_RESUELTO = "NO_RESUELTO"


@dataclass(frozen=True)
class PoliticaConfianzaMaterial:
    version: str = "material-tipo-carga-1.0"
    umbral_fuzzy: float = 0.88
    margen_fuzzy: float = 0.08
    calidad_minima: float = 0.80

    def __post_init__(self) -> None:
        for valor in (self.umbral_fuzzy, self.margen_fuzzy, self.calidad_minima):
            if not 0 <= valor <= 1:
                raise ValueError("umbral fuera de rango")


POLITICA_CONFIANZA_MATERIAL_V1 = PoliticaConfianzaMaterial()
