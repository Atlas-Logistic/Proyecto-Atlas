"""Puertos reemplazables y dobles deterministas, sin red."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from atlas_core.inteligencia.modelos import Evidencia


@dataclass(frozen=True)
class RespuestaProveedor:
    evidencias: tuple[Evidencia, ...] = ()
    estado: str = "OK"
    motivo: str = ""


class ProveedorModeloInteligente(Protocol):
    def analizar(self, contexto_autorizado: Mapping[str, object]) -> RespuestaProveedor: ...


class ProveedorVerificacionExterna(Protocol):
    def verificar(self, contexto_autorizado: Mapping[str, object]) -> RespuestaProveedor: ...


class ProveedorModeloSimulado:
    def __init__(self, respuesta: RespuestaProveedor = RespuestaProveedor()) -> None:
        self.respuesta = respuesta
        self.solicitudes: list[dict[str, object]] = []

    def analizar(self, contexto_autorizado: Mapping[str, object]) -> RespuestaProveedor:
        self.solicitudes.append(dict(contexto_autorizado))
        return self.respuesta


class ProveedorExternoSimulado:
    def __init__(self, respuesta: RespuestaProveedor = RespuestaProveedor()) -> None:
        self.respuesta = respuesta
        self.solicitudes: list[dict[str, object]] = []

    def verificar(self, contexto_autorizado: Mapping[str, object]) -> RespuestaProveedor:
        self.solicitudes.append(dict(contexto_autorizado))
        return self.respuesta
