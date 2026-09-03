"""Contrato que implementan los adaptadores geográficos por país."""
from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable

from .modelos import ContextoGeocodificacion, ResultadoNormalizacion, UnidadAdministrativa


@runtime_checkable
class GeografiaPais(Protocol):
    codigo_pais: str
    codigos_pais: tuple[str, ...]
    niveles: tuple[str, ...]
    nivel_geocodificable: int
    nivel_region_geocodificacion: int

    def normalizar(self, texto: str, nivel: int | None = None) -> ResultadoNormalizacion: ...
    def normalizar_direccion(self, texto: str) -> str: ...
    def buscar_por_codigo(self, codigo: str) -> UnidadAdministrativa | None: ...
    def parametros_geocodificacion(self, unidad: UnidadAdministrativa) -> ContextoGeocodificacion: ...
    def compatibilidad_territorial(self, a: UnidadAdministrativa, b: UnidadAdministrativa) -> bool: ...
