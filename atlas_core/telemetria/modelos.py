"""Modelos genéricos de telemetría GPS (Bloque TELEMETRÍA T1).

Ningún tipo de este módulo expone la forma JSON de un proveedor concreto
(Onelogis u otro) al resto de Atlas -- el adaptador (`proveedores/*.py`)
es responsable de traducir su respuesta cruda a estos modelos. Atlas es
multiempresa y multiproveedor: hoy el único adaptador es Onelogis, pero
el núcleo (extractor/rutas/gestor_viajes/Desktop) nunca debe importar
nada de `proveedores/` directamente.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum


class EstadoTelemetria(str, Enum):
    """Nunca lanza: cualquier fallo del proveedor de telemetría se expresa
    como uno de estos estados -- la ausencia/fallo de GPS nunca debe
    romper el resto del pipeline (ver Bloque L)."""

    OK = "OK"
    SIN_CREDENCIAL = "SIN_CREDENCIAL"
    NO_AUTORIZADO = "NO_AUTORIZADO"
    VEHICULO_NO_ENCONTRADO = "VEHICULO_NO_ENCONTRADO"
    TRIP_NO_ENCONTRADO = "TRIP_NO_ENCONTRADO"
    SIN_HISTORICO = "SIN_HISTORICO"
    SIN_CONEXION = "SIN_CONEXION"
    LIMITE_CUOTA = "LIMITE_CUOTA"
    RESPUESTA_INVALIDA = "RESPUESTA_INVALIDA"
    ERROR_PROVEEDOR = "ERROR_PROVEEDOR"
    RESULTADO_DESDE_CACHE = "RESULTADO_DESDE_CACHE"


@dataclass(frozen=True)
class VehiculoTelemetria:
    patente: str
    proveedor_id: str = ""
    alias: str = ""
    marca: str = ""
    modelo: str = ""

    def a_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PosicionTelemetria:
    latitud: float
    longitud: float
    timestamp: str = ""
    velocidad: float | None = None
    evento: str = ""

    def a_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ViajeTelemetria:
    proveedor_trip_id: str
    patente: str
    inicio: str = ""
    fin: str = ""
    distancia_km: float | None = None

    def a_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RecorridoTelemetria:
    viaje: ViajeTelemetria
    breadcrumbs: tuple[PosicionTelemetria, ...] = ()

    def a_dict(self) -> dict[str, object]:
        return {
            "viaje": self.viaje.a_dict(),
            "breadcrumbs": [p.a_dict() for p in self.breadcrumbs],
        }


@dataclass(frozen=True)
class ResultadoVehiculos:
    estado: EstadoTelemetria
    vehiculos: tuple[VehiculoTelemetria, ...] = ()
    motivo: str = ""


@dataclass(frozen=True)
class ResultadoPosicion:
    estado: EstadoTelemetria
    posicion: PosicionTelemetria | None = None
    motivo: str = ""


@dataclass(frozen=True)
class ResultadoViajes:
    estado: EstadoTelemetria
    viajes: tuple[ViajeTelemetria, ...] = ()
    motivo: str = ""
    desde_cache: bool = False


@dataclass(frozen=True)
class ResultadoBreadcrumbs:
    estado: EstadoTelemetria
    puntos: tuple[PosicionTelemetria, ...] = ()
    motivo: str = ""
    desde_cache: bool = False
