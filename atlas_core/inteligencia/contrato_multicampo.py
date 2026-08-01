"""Contrato común, inmutable y explicable para resolución multicampo."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from types import MappingProxyType
from typing import Any, Mapping


def congelar_profundo(valor: Any) -> Any:
    """Copia y congela estructuras JSON-like con orden determinista."""
    if isinstance(valor, float) and not math.isfinite(valor):
        raise ValueError("los valores flotantes deben ser finitos")
    if valor is None or isinstance(valor, (bool, int, float, str)):
        return valor
    if isinstance(valor, Mapping):
        return MappingProxyType({
            str(clave): congelar_profundo(valor[clave])
            for clave in sorted(valor, key=lambda item: str(item))
        })
    if isinstance(valor, (set, frozenset)):
        congelados = [congelar_profundo(item) for item in valor]
        return tuple(sorted(congelados, key=lambda item: repr(descongelar(item))))
    if isinstance(valor, (list, tuple)):
        return tuple(congelar_profundo(item) for item in valor)
    raise TypeError(f"tipo no congelable: {type(valor).__name__}")


def descongelar(valor: Any) -> Any:
    """Devuelve una representación serializable sin exponer referencias internas."""
    if isinstance(valor, Mapping):
        return {clave: descongelar(item) for clave, item in valor.items()}
    if isinstance(valor, tuple):
        return [descongelar(item) for item in valor]
    return valor


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
    version_politica: str = ""
    via_decision: str = ""
    version_catalogo: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.confianza <= 1.0:
            raise ValueError("confianza debe estar entre 0 y 1")
        congelado = congelar_profundo(self.contexto or {})
        object.__setattr__(self, "contexto", congelado)

    @property
    def valores_ocr_originales(self) -> Mapping[str, tuple[str, ...]]:
        """Todos los originales agrupados por campo, sin descartar repetidos."""
        agrupados: dict[str, list[str]] = {}
        for item in self.observaciones:
            agrupados.setdefault(item.campo, []).append(item.valor_original)
        return MappingProxyType({
            campo: tuple(valores) for campo, valores in agrupados.items()
        })

    @property
    def ultimos_valores_ocr_originales(self) -> Mapping[str, str]:
        """Vista explícita del último original de cada campo."""
        return MappingProxyType({
            item.campo: item.valor_original for item in self.observaciones
        })

    @property
    def valor_canonico(self) -> str | None:
        return self.entidad.valor if self.entidad else None

    @property
    def identificador_canonico(self) -> str | None:
        return self.entidad.identificador if self.entidad else None


def requiere_revision_por_estado(
    estado: EstadoResolucion, *, campo_obligatorio: bool = True
) -> bool:
    """Semántica conservadora; solo un campo opcional explícito puede cerrar ausencia."""
    if estado is EstadoResolucion.CONFIRMADO:
        return False
    if estado is EstadoResolucion.NO_RESUELTO:
        return campo_obligatorio
    return True
