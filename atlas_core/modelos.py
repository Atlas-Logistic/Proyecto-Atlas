"""Modelos generales para representar el procesamiento de documentos."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class FuenteCampo(str, Enum):
    """Origen del valor actual de un campo procesado."""

    OCR = "OCR"
    EXTRACCION = "EXTRACCION"
    VALIDACION = "VALIDACION"
    CATALOGO = "CATALOGO"
    CONFIRMACION_HUMANA = "CONFIRMACION_HUMANA"


class EstadoValidacion(str, Enum):
    """Estado conocido de un campo dentro del flujo de procesamiento."""

    AUSENTE = "AUSENTE"
    INVALIDO = "INVALIDO"
    VALIDO = "VALIDO"
    ENRIQUECIDO = "ENRIQUECIDO"
    PENDIENTE_CONFIRMACION = "PENDIENTE_CONFIRMACION"


@dataclass
class CampoProcesado:
    """Valor procesado junto con su confianza y trazabilidad."""

    nombre: str
    valor: Any = None
    fuente: FuenteCampo = FuenteCampo.EXTRACCION
    estado: EstadoValidacion = EstadoValidacion.AUSENTE
    confianza: float = 0.0
    revision_humana: bool = False
    advertencias: List[str] = field(default_factory=list)
    valor_original: Any = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confianza <= 1.0:
            raise ValueError("La confianza debe estar entre 0 y 1")
        if self.valor is None and self.estado in {
            EstadoValidacion.VALIDO,
            EstadoValidacion.ENRIQUECIDO,
        }:
            raise ValueError("Un campo sin valor no puede declararse válido o enriquecido")

    @property
    def requiere_revision(self) -> bool:
        """Indica si el campo necesita intervención humana."""
        return self.revision_humana or self.valor is None or self.estado in {
            EstadoValidacion.AUSENTE,
            EstadoValidacion.INVALIDO,
            EstadoValidacion.PENDIENTE_CONFIRMACION,
        }

    def a_diccionario(self) -> Dict[str, Any]:
        """Devuelve una representación apta para serializar como JSON."""
        return {
            "nombre": self.nombre,
            "valor": self.valor,
            "fuente": self.fuente.value,
            "estado": self.estado.value,
            "confianza": self.confianza,
            "requiere_revision": self.requiere_revision,
            "advertencias": list(self.advertencias),
            "valor_original": self.valor_original,
        }


@dataclass
class ResultadoDocumento:
    """Resultado trazable del procesamiento completo de un documento."""

    textos_ocr: List[str] = field(default_factory=list)
    campos: Dict[str, CampoProcesado] = field(default_factory=dict)
    advertencias: List[str] = field(default_factory=list)
    errores: List[str] = field(default_factory=list)
    perfil: str = "generico"
    version_formato: str = "1.0"

    @property
    def requiere_revision(self) -> bool:
        """Indica si algún campo o error requiere revisión humana."""
        return bool(self.errores) or any(
            campo.requiere_revision for campo in self.campos.values()
        )

    def a_diccionario(self) -> Dict[str, Any]:
        """Devuelve el resultado completo como estructuras serializables."""
        return {
            "version_formato": self.version_formato,
            "perfil": self.perfil,
            "textos_ocr": list(self.textos_ocr),
            "campos": {
                nombre: campo.a_diccionario()
                for nombre, campo in self.campos.items()
            },
            "advertencias": list(self.advertencias),
            "errores": list(self.errores),
            "requiere_revision": self.requiere_revision,
        }
