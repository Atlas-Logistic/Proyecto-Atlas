"""Contrato común, inmutable y explicable para resolución multicampo."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class Disponibilidad(str, Enum):
    DISPONIBLE = "DISPONIBLE"
    AUSENTE = "AUSENTE"
    PARCIAL = "PARCIAL"


class CalidadObservacion(str, Enum):
    VALIDA = "VALIDA"
    INVALIDA = "INVALIDA"
    NO_EVALUADA = "NO_EVALUADA"


class EstadoResolucion(str, Enum):
    CONFIRMADO = "CONFIRMADO"
    PROPUESTO = "PROPUESTO"
    REQUIERE_REVISION = "REQUIERE_REVISION"
    NO_RESUELTO = "NO_RESUELTO"


class GravedadContradiccion(str, Enum):
    BAJA = "BAJA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"


@dataclass(frozen=True)
class ValorObservado:
    campo: str
    valor_original: str
    valor_normalizado: str
    fuente: str
    disponibilidad: Disponibilidad
    calidad: CalidadObservacion = CalidadObservacion.NO_EVALUADA
    detalle_calidad: str = ""


@dataclass(frozen=True)
class EntidadCanonica:
    identificador: str
    valor: str
    tipo_entidad: str
    origen: str
    activa: bool | None = None


@dataclass(frozen=True)
class EvidenciaResolucion:
    tipo: str
    fuente: str
    observado: ValorObservado
    candidato: EntidadCanonica | None
    fuerza: float
    detalle: str
    apoya: bool

    def __post_init__(self) -> None:
        if not 0.0 <= self.fuerza <= 1.0:
            raise ValueError("fuerza debe estar entre 0 y 1")


@dataclass(frozen=True)
class ContradiccionResolucion:
    campos_enfrentados: tuple[str, ...]
    evidencias_enfrentadas: tuple[EvidenciaResolucion, ...]
    entidades_involucradas: tuple[EntidadCanonica, ...]
    razon: str
    gravedad: GravedadContradiccion
    efecto: str


@dataclass(frozen=True)
class AlternativaResolucion:
    entidad: EntidadCanonica
    similitud: float | None
    razon: str


@dataclass(frozen=True)
class ResultadoResolucion:
    tipo_entidad: str
    observaciones: tuple[ValorObservado, ...]
    entidad: EntidadCanonica | None
    estado: EstadoResolucion
    confianza: float
    evidencias: tuple[EvidenciaResolucion, ...]
    contradicciones: tuple[ContradiccionResolucion, ...]
    razones: tuple[str, ...]
    requiere_revision_humana: bool
    alternativas: tuple[AlternativaResolucion, ...] = ()
    contexto: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confianza <= 1.0:
            raise ValueError("confianza debe estar entre 0 y 1")
        object.__setattr__(
            self, "contexto", MappingProxyType(dict(self.contexto or {}))
        )

    @property
    def valores_ocr_originales(self) -> Mapping[str, str]:
        return {item.campo: item.valor_original for item in self.observaciones}

    @property
    def valor_canonico(self) -> str | None:
        return self.entidad.valor if self.entidad else None

    @property
    def identificador_canonico(self) -> str | None:
        return self.entidad.identificador if self.entidad else None
