"""Autoridad geográfica multipaís de Atlas."""
from __future__ import annotations

from functools import lru_cache

from .contratos import GeografiaPais
from .modelos import ContextoGeocodificacion, EstadoNormalizacion, ResultadoNormalizacion, UnidadAdministrativa
from .motor import MotorNormalizacion, texto_normalizado


def cargar_geografia(codigo_pais: str) -> GeografiaPais:
    codigo = str(codigo_pais or "").strip().upper()
    if codigo in {"CL", "CHL"}:
        return _cargar_geografia_canonica("CL")
    raise ValueError(f"No existe adaptador geográfico para {codigo_pais!r}")


@lru_cache(maxsize=None)
def _cargar_geografia_canonica(codigo: str) -> GeografiaPais:
    if codigo == "CL":
        from .cl import GeografiaChile
        return GeografiaChile()
    raise ValueError(f"No existe adaptador geográfico para {codigo!r}")


__all__ = [
    "ContextoGeocodificacion", "EstadoNormalizacion", "GeografiaPais", "MotorNormalizacion",
    "ResultadoNormalizacion", "UnidadAdministrativa", "cargar_geografia",
    "texto_normalizado",
]
