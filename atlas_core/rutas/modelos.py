"""Modelos de dominio del módulo aislado de rutas."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum


class ErrorRutas(ValueError):
    """Error base de validación del dominio de rutas."""


class EstadoRuta(str, Enum):
    RUTA_CALCULADA = "RUTA_CALCULADA"
    RESULTADO_DESDE_CACHE = "RESULTADO_DESDE_CACHE"
    SIN_CREDENCIAL = "SIN_CREDENCIAL"
    SIN_CONEXION = "SIN_CONEXION"
    DIRECCION_NO_ENCONTRADA = "DIRECCION_NO_ENCONTRADA"
    RESULTADO_AMBIGUO = "RESULTADO_AMBIGUO"
    PROVEEDOR_NO_DISPONIBLE = "PROVEEDOR_NO_DISPONIBLE"
    LIMITE_CUOTA = "LIMITE_CUOTA"
    RESPUESTA_INVALIDA = "RESPUESTA_INVALIDA"
    REQUIERE_REVISION = "REQUIERE_REVISION"


@dataclass(frozen=True)
class Coordenadas:
    longitud: float
    latitud: float

    def __post_init__(self) -> None:
        if not all(math.isfinite(valor) for valor in (self.longitud, self.latitud)):
            raise ErrorRutas("las coordenadas deben ser finitas")
        if not -180 <= self.longitud <= 180:
            raise ErrorRutas("longitud fuera de rango")
        if not -90 <= self.latitud <= 90:
            raise ErrorRutas("latitud fuera de rango")

    def a_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class CandidatoGeocodificacion:
    coordenadas: Coordenadas
    etiqueta: str
    confianza: float | None = None


@dataclass(frozen=True)
class ResultadoGeocodificacion:
    estado: EstadoRuta
    candidatos: tuple[CandidatoGeocodificacion, ...] = ()
    motivo: str = ""


@dataclass(frozen=True)
class ResultadoRuta:
    estado: EstadoRuta
    distancia_km: float | None = None
    duracion_estimada_min: float | None = None
    motivo: str = ""

    def __post_init__(self) -> None:
        if self.estado == EstadoRuta.RUTA_CALCULADA:
            valores = (self.distancia_km, self.duracion_estimada_min)
            if any(valor is None or not math.isfinite(valor) or valor <= 0 for valor in valores):
                raise ErrorRutas("una ruta calculada requiere distancia y duración positivas")
        elif self.distancia_km is not None or self.duracion_estimada_min is not None:
            raise ErrorRutas("un fallo no puede contener distancia ni duración")


@dataclass(frozen=True)
class RegistroRuta:
    ruta_id: str
    planta_id: str
    destino_id: str
    perfil_ruta: str
    proveedor: str
    version_proveedor: str
    distancia_km: float
    duracion_estimada_min: float
    longitud_origen: float
    latitud_origen: float
    longitud_destino: float
    latitud_destino: float
    direccion_origen_normalizada: str
    direccion_destino_normalizada: str
    huella_direccion_origen: str
    huella_direccion_destino: str
    estado: str
    motivo: str
    vigente: bool
    fecha_calculo: str
    fecha_creacion: str
    fecha_modificacion: str

    def __post_init__(self) -> None:
        for valor, campo in ((self.ruta_id, "ruta_id"), (self.planta_id, "planta_id"),
                             (self.destino_id, "destino_id"), (self.perfil_ruta, "perfil_ruta"),
                             (self.proveedor, "proveedor"), (self.version_proveedor, "version_proveedor")):
            if not str(valor).strip():
                raise ErrorRutas(f"{campo} es obligatorio")
        Coordenadas(self.longitud_origen, self.latitud_origen)
        Coordenadas(self.longitud_destino, self.latitud_destino)
        ResultadoRuta(EstadoRuta.RUTA_CALCULADA, self.distancia_km, self.duracion_estimada_min)
        if self.estado != EstadoRuta.RUTA_CALCULADA.value:
            raise ErrorRutas("solo se persisten rutas calculadas")
        for valor in (self.fecha_calculo, self.fecha_creacion, self.fecha_modificacion):
            try:
                fecha = datetime.fromisoformat(valor)
            except (TypeError, ValueError) as error:
                raise ErrorRutas("fecha inválida") from error
            if fecha.tzinfo is None:
                raise ErrorRutas("las fechas requieren zona horaria")

    @property
    def clave_logica(self) -> tuple[str, str, str, str, str]:
        return (self.planta_id, self.destino_id, self.perfil_ruta,
                self.proveedor, self.version_proveedor)

    def a_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def desde_dict(cls, datos: object) -> "RegistroRuta":
        if not isinstance(datos, dict) or set(datos) != set(cls.__dataclass_fields__):
            raise ErrorRutas("campos de ruta incompatibles")
        return cls(**datos)


@dataclass(frozen=True)
class ResultadoServicioRutas:
    estado: EstadoRuta
    motivo: str = ""
    origen: ResultadoGeocodificacion | None = None
    destino: ResultadoGeocodificacion | None = None
    ruta: RegistroRuta | None = None
