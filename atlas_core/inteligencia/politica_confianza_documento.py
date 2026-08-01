"""Política versionada para guía, transporte y fecha documental."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PoliticaConfianzaDocumento:
    version: str = "guia-transporte-fecha-1.0"
    calidad_minima_confirmacion: float = 0.80
    longitud_minima_guia: int = 5
    longitud_maxima_guia: int = 8
    longitud_transporte: int = 10
    anio_minimo: int = 2000

    def __post_init__(self) -> None:
        if not 0 <= self.calidad_minima_confirmacion <= 1:
            raise ValueError("calidad mínima fuera de rango")
        if self.longitud_minima_guia > self.longitud_maxima_guia:
            raise ValueError("rango de guía inválido")


POLITICA_CONFIANZA_DOCUMENTO_V1 = PoliticaConfianzaDocumento()
