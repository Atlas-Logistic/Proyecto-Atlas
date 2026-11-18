"""Frontera explícita de procesamiento documental.

El perfil AZA encapsula el pipeline heredado completo. Los perfiles externos
son experimentales y deben implementar el contrato de salida del consumidor;
no se registran ni se seleccionan automáticamente en flujos operacionales.
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol


class PerfilDocumental(Protocol):
    def procesar(self, **contexto: Any) -> dict[str, str]:
        """Procesa el documento completo y conserva su evidencia y revisión."""
        ...


class FormatoDocumentalDesconocido(ValueError):
    """Abstención: no existe perfil válido para procesar el documento."""


class _PerfilAza:
    """Identidad del pipeline heredado, despachado en procesamiento_masivo."""


PERFIL_AZA = _PerfilAza()


def ejecutar_perfil_explicito(perfil: object, contexto: Mapping[str, Any]) -> dict[str, str]:
    procesar = getattr(perfil, "procesar", None)
    if not callable(procesar):
        raise FormatoDocumentalDesconocido("FORMATO_DOCUMENTAL_DESCONOCIDO: perfil no válido; requiere revisión")
    resultado = procesar(**contexto)
    if not isinstance(resultado, dict):
        raise TypeError("El perfil documental debe devolver un diccionario")
    return resultado
