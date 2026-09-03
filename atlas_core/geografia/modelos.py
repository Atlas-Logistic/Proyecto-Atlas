"""Tipos neutrales de país para la autoridad geográfica de Atlas."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping


class EstadoNormalizacion(str, Enum):
    EXACTA = "EXACTA"
    NORMALIZADA_SEGURA = "NORMALIZADA_SEGURA"
    AMBIGUA = "AMBIGUA"
    NO_RECONOCIDA = "NO_RECONOCIDA"


@dataclass(frozen=True)
class UnidadAdministrativa:
    codigo_pais: str
    nivel: int
    codigo: str
    codigo_padre: str | None
    nombre_canonico: str
    nombre_normalizado: str
    aliases: tuple[str, ...] = ()
    geometria: Any | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.nivel < 1:
            raise ValueError("nivel debe ser un ordinal positivo")
        if not self.codigo or not self.nombre_canonico:
            raise ValueError("codigo y nombre_canonico son obligatorios")


@dataclass(frozen=True)
class ResultadoNormalizacion:
    estado: EstadoNormalizacion
    valor_original: str
    unidad: UnidadAdministrativa | None = None
    similitud: float | None = None
    evidencia: Mapping[str, Any] = field(default_factory=dict)
    _buscar_codigo: Callable[[str], UnidadAdministrativa | None] | None = field(
        default=None, repr=False, compare=False
    )

    def unidad_de_nivel(self, nivel: int) -> UnidadAdministrativa | None:
        unidad = self.unidad
        while unidad is not None and unidad.nivel > nivel:
            if unidad.codigo_padre is None or self._buscar_codigo is None:
                return None
            unidad = self._buscar_codigo(unidad.codigo_padre)
        return unidad if unidad is not None and unidad.nivel == nivel else None
