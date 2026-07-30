"""Contratos inmutables del Motor Multicampo 1E."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from atlas_core.rutas.modelos import Coordenadas


class EstadoCalculoMulticampo(str, Enum):
    CALCULADO = "CALCULADO"
    PENDIENTE_COORDENADAS = "PENDIENTE_COORDENADAS"
    PENDIENTE_PLANTA = "PENDIENTE_PLANTA"
    PENDIENTE_DESTINO = "PENDIENTE_DESTINO"
    REQUIERE_REVISION = "REQUIERE_REVISION"
    SIN_RUTA = "SIN_RUTA"
    ERROR_PROVEEDOR = "ERROR_PROVEEDOR"
    SIN_CREDENCIAL = "SIN_CREDENCIAL"


@dataclass(frozen=True)
class SolicitudRutaMulticampo:
    id_origen_canonico: str
    planta_salida: str
    direccion_origen: str
    coordenadas_origen: Coordenadas | Mapping[str, float] | tuple[float, float] | None
    planta_resuelta: bool
    id_destino_canonico: str
    destino: str
    direccion_destino: str
    coordenadas_destino: Coordenadas | Mapping[str, float] | tuple[float, float] | None
    destino_resuelto: bool
    proveedor: str
    perfil_ruta: str = "driving-hgv"
    version_parametros: str = "rutas-1e-v1"
    fuente_coordenadas: str = ""
    calcular_ida_vuelta: bool = False
    contradicciones: tuple[str, ...] = ()
    contexto: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "contradicciones", tuple(self.contradicciones))
        object.__setattr__(
            self, "contexto", MappingProxyType(dict(self.contexto))
        )


@dataclass(frozen=True)
class ResultadoRutaMulticampo:
    id_origen_canonico: str
    planta_salida: str
    direccion_origen: str
    coordenadas_origen: Mapping[str, float] | None
    id_destino_canonico: str
    destino: str
    direccion_destino: str
    coordenadas_destino: Mapping[str, float] | None
    distancia_ida_km: float | None
    duracion_ida_minutos: float | None
    distancia_ida_vuelta_km: float | None
    proveedor: str
    perfil_ruta: str
    fecha_calculo: str | None
    version_parametros: str
    estado_calculo: EstadoCalculoMulticampo
    razones: tuple[str, ...]
    requiere_revision: bool
    fuente_coordenadas: str
    desde_cache: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "razones", tuple(self.razones))
        for campo in ("coordenadas_origen", "coordenadas_destino"):
            valor = getattr(self, campo)
            if valor is not None:
                object.__setattr__(self, campo, MappingProxyType(dict(valor)))
        metricas = (
            self.distancia_ida_km,
            self.duracion_ida_minutos,
        )
        if self.estado_calculo is EstadoCalculoMulticampo.CALCULADO:
            if (
                not self.fecha_calculo
                or any(
                    valor is None or not math.isfinite(valor) or valor <= 0
                    for valor in metricas
                )
            ):
                raise ValueError("un cálculo válido requiere fecha y métricas positivas")
        elif any(valor is not None for valor in metricas):
            raise ValueError("una abstención no puede publicar métricas")
        if (
            self.distancia_ida_vuelta_km is not None
            and self.distancia_ida_km is None
        ):
            raise ValueError("ida y vuelta requiere distancia de ida")
