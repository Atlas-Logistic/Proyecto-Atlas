"""Contratos inmutables y auditables del motor inteligente."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class TipoFuente(str, Enum):
    OCR = "OCR"
    GEOMETRIA = "GEOMETRIA"
    CATALOGO = "CATALOGO"
    RELACION_CAMPO = "RELACION_CAMPO"
    HISTORICO = "HISTORICO"
    CORRECCION_HUMANA = "CORRECCION_HUMANA"
    VERIFICACION_EXTERNA = "VERIFICACION_EXTERNA"
    MODELO_IA = "MODELO_IA"
    REGLA_DETERMINISTA = "REGLA_DETERMINISTA"


class EstadoPropuesta(str, Enum):
    CONFIRMADO = "CONFIRMADO"
    PROPUESTO = "PROPUESTO"
    SIN_EVIDENCIA_SUFICIENTE = "SIN_EVIDENCIA_SUFICIENTE"
    CONTRADICCION = "CONTRADICCION"
    REVISAR = "REVISAR"
    NO_APLICA = "NO_APLICA"
    SIN_CAMBIO = "SIN_CAMBIO"


class NivelConfianza(str, Enum):
    ALTA = "ALTA"
    MEDIA = "MEDIA"
    BAJA = "BAJA"
    NULA = "NULA"


@dataclass(frozen=True)
class Evidencia:
    campo_objetivo: str
    valor_observado: str
    valor_normalizado: str
    fuente: str
    tipo_fuente: TipoFuente
    confianza_fuente: float
    fecha_observacion: datetime
    documento_origen: str = ""
    referencia: str = ""
    detalles: Mapping[str, object] = field(default_factory=dict)
    contiene_datos_sensibles: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.confianza_fuente <= 1:
            raise ValueError("confianza_fuente debe estar entre 0 y 1")
        object.__setattr__(self, "detalles", MappingProxyType(dict(self.detalles)))


@dataclass(frozen=True)
class Contradiccion:
    campo: str
    valores_en_conflicto: tuple[str, ...]
    evidencias: tuple[Evidencia, ...]
    gravedad: str
    motivo: str
    requiere_revision: bool = True


@dataclass(frozen=True)
class Propuesta:
    campo: str
    valor_original: str
    valor_propuesto: str
    estado: EstadoPropuesta
    confianza: NivelConfianza
    evidencias_favorables: tuple[Evidencia, ...]
    evidencias_contrarias: tuple[Evidencia, ...]
    contradicciones: tuple[Contradiccion, ...]
    explicacion: tuple[str, ...]
    accion_recomendada: str
    trazabilidad: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "trazabilidad", MappingProxyType(dict(self.trazabilidad))
        )
