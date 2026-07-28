"""Aprendizaje controlado: las correcciones nunca se activan solas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from atlas_core.inteligencia.modelos import Evidencia


class EstadoCorreccion(str, Enum):
    PENDIENTE = "PENDIENTE"
    APROBADA = "APROBADA"
    RECHAZADA = "RECHAZADA"
    INACTIVA = "INACTIVA"


@dataclass(frozen=True)
class CorreccionHumana:
    campo: str
    valor_original: str
    valor_corregido: str
    evidencia: Evidencia
    actor: str
    fecha: datetime
    numero_confirmaciones: int
    estado: EstadoCorreccion
    vigencia: str


class RepositorioCorrecciones(Protocol):
    def registrar(self, correccion: CorreccionHumana) -> None: ...
    def aprobadas(self, campo: str, valor_original: str) -> tuple[CorreccionHumana, ...]: ...
    def desactivar(self, correccion: CorreccionHumana) -> None: ...


class RepositorioCorreccionesMemoria:
    def __init__(self) -> None:
        self._correcciones: list[CorreccionHumana] = []

    def registrar(self, correccion: CorreccionHumana) -> None:
        self._correcciones.append(correccion)

    def aprobadas(
        self, campo: str, valor_original: str
    ) -> tuple[CorreccionHumana, ...]:
        return tuple(
            c
            for c in self._correcciones
            if c.campo == campo
            and c.valor_original == valor_original
            and c.estado == EstadoCorreccion.APROBADA
        )

    def desactivar(self, correccion: CorreccionHumana) -> None:
        indice = self._correcciones.index(correccion)
        self._correcciones[indice] = CorreccionHumana(
            **{**correccion.__dict__, "estado": EstadoCorreccion.INACTIVA}
        )
