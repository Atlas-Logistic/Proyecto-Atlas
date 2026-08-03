"""Política operativa de publicación para resultados multicampo."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Generic, Mapping, TypeVar


class EstadoOperacional(str, Enum):
    DESHABILITADO = "DESHABILITADO"
    SOMBRA = "SOMBRA"
    PRODUCTIVO_CONTROLADO = "PRODUCTIVO_CONTROLADO"
    PRODUCTIVO = "PRODUCTIVO"


CAMPOS_MULTICAMPO = frozenset({"chofer", "cliente", "destino", "material"})


REGISTRO_ACTIVACION_MULTICAMPO_FASE1: Mapping[str, EstadoOperacional] = (
    MappingProxyType({
        "chofer": EstadoOperacional.PRODUCTIVO,
        "cliente": EstadoOperacional.PRODUCTIVO,
        "destino": EstadoOperacional.PRODUCTIVO_CONTROLADO,
        "material": EstadoOperacional.PRODUCTIVO_CONTROLADO,
    })
)


T = TypeVar("T")


@dataclass(frozen=True)
class DecisionPublicacion(Generic[T]):
    campo: str
    estado_operacional: EstadoOperacional
    publicar: bool
    valor: T
    motivo: str


def validar_registro_activacion(
    registro: Mapping[str, EstadoOperacional | str],
) -> Mapping[str, EstadoOperacional]:
    """Normaliza un registro completo y rechaza configuraciones ambiguas."""
    campos = set(registro)
    if campos != CAMPOS_MULTICAMPO:
        faltantes = sorted(CAMPOS_MULTICAMPO - campos)
        adicionales = sorted(campos - CAMPOS_MULTICAMPO)
        raise ValueError(
            "registro de activación incompleto o desconocido: "
            f"faltantes={faltantes}, adicionales={adicionales}"
        )
    try:
        normalizado = {
            campo: EstadoOperacional(estado)
            for campo, estado in registro.items()
        }
    except (TypeError, ValueError) as exc:
        raise ValueError("estado operacional inválido") from exc
    return MappingProxyType(normalizado)


def decidir_publicacion(
    campo: str,
    valor_actual: T,
    valor_resuelto: T,
    *,
    registro: Mapping[str, EstadoOperacional | str] = (
        REGISTRO_ACTIVACION_MULTICAMPO_FASE1
    ),
    autorizacion_controlada: bool = False,
) -> DecisionPublicacion[T]:
    """Decide la publicación sin intervenir en resolución ni negocio."""
    estados = validar_registro_activacion(registro)
    if campo not in CAMPOS_MULTICAMPO:
        raise ValueError(f"campo multicampo desconocido: {campo}")
    estado = estados[campo]
    publicar = estado is EstadoOperacional.PRODUCTIVO or (
        estado is EstadoOperacional.PRODUCTIVO_CONTROLADO
        and autorizacion_controlada
    )
    if publicar:
        motivo = (
            "publicacion-productiva"
            if estado is EstadoOperacional.PRODUCTIVO
            else "publicacion-controlada-autorizada"
        )
        valor = valor_resuelto
    else:
        motivo = {
            EstadoOperacional.DESHABILITADO: "publicacion-deshabilitada",
            EstadoOperacional.SOMBRA: "resultado-solo-observable",
            EstadoOperacional.PRODUCTIVO_CONTROLADO: "sin-autorizacion-controlada",
        }[estado]
        valor = valor_actual
    return DecisionPublicacion(campo, estado, publicar, valor, motivo)
