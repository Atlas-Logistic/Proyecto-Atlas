"""Contrato oficial, aislado y sin I/O para cálculos de rutas confirmadas."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Callable, Mapping

from atlas_core.rutas.modelos import Coordenadas, EstadoRuta, ErrorRutas
from atlas_core.rutas.proveedor import ProveedorRutas


PLANTAS_OPERACIONALES = frozenset({"AZA RENCA", "AZA COLINA"})
PERFIL_PREDETERMINADO = "driving-hgv"
_PATRON_PERFIL = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class EstadoCalculoRuta(str, Enum):
    CALCULADA = "CALCULADA"
    SIN_COORDENADAS_ORIGEN = "SIN_COORDENADAS_ORIGEN"
    SIN_COORDENADAS_DESTINO = "SIN_COORDENADAS_DESTINO"
    CREDENCIAL_NO_DISPONIBLE = "CREDENCIAL_NO_DISPONIBLE"
    PROVEEDOR_NO_DISPONIBLE = "PROVEEDOR_NO_DISPONIBLE"
    ERROR_PROVEEDOR = "ERROR_PROVEEDOR"
    DATOS_INVALIDOS = "DATOS_INVALIDOS"
    REVISAR = "REVISAR"


@dataclass(frozen=True)
class SolicitudCalculoRuta:
    planta: str
    planta_confirmada: bool
    coordenadas_origen: object
    destino: str
    destino_confirmado: bool
    coordenadas_destino: object
    proveedor: str
    perfil: str = PERFIL_PREDETERMINADO
    evidencia: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ResultadoCalculoRuta:
    estado: EstadoCalculoRuta
    proveedor: str
    perfil: str
    distancia_metros: float | None
    distancia_kilometros: float | None
    duracion_segundos: float | None
    duracion_legible: str
    coordenadas_origen: dict[str, float] | None
    coordenadas_destino: dict[str, float] | None
    planta: str
    destino: str
    fecha_calculo: str
    evidencia: Mapping[str, object]
    error: str
    requiere_revision: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidencia", MappingProxyType(dict(self.evidencia))
        )
        metricas = (
            self.distancia_metros,
            self.distancia_kilometros,
            self.duracion_segundos,
        )
        if self.estado == EstadoCalculoRuta.CALCULADA:
            if any(
                valor is None or not math.isfinite(valor) or valor <= 0
                for valor in metricas
            ):
                raise ErrorRutas("una ruta calculada requiere métricas positivas")
        elif any(valor is not None for valor in metricas):
            raise ErrorRutas("un resultado fallido no puede contener métricas")


class CalculadorRutas:
    """Orquesta un proveedor reemplazable sin geocodificar ni persistir."""

    def __init__(
        self,
        proveedor: ProveedorRutas,
        *,
        reloj: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.proveedor = proveedor
        self._reloj = reloj

    def calcular(self, solicitud: SolicitudCalculoRuta) -> ResultadoCalculoRuta:
        evidencia = dict(solicitud.evidencia)
        base = dict(
            proveedor=str(solicitud.proveedor).strip(),
            perfil=str(solicitud.perfil).strip(),
            planta=str(solicitud.planta).strip(),
            destino=str(solicitud.destino).strip(),
            fecha_calculo=self._fecha_calculo(),
            evidencia=evidencia,
        )
        if not base["planta"] or not base["destino"]:
            return self._fallo(
                EstadoCalculoRuta.DATOS_INVALIDOS, "NOMBRE_VACIO", base
            )
        if not solicitud.planta_confirmada:
            return self._fallo(
                EstadoCalculoRuta.REVISAR, "PLANTA_NO_CONFIRMADA", base
            )
        if not solicitud.destino_confirmado:
            return self._fallo(
                EstadoCalculoRuta.REVISAR, "DESTINO_NO_CONFIRMADO", base
            )
        if solicitud.coordenadas_origen is None:
            return self._fallo(
                EstadoCalculoRuta.SIN_COORDENADAS_ORIGEN,
                "ORIGEN_SIN_COORDENADAS",
                base,
            )
        if solicitud.coordenadas_destino is None:
            return self._fallo(
                EstadoCalculoRuta.SIN_COORDENADAS_DESTINO,
                "DESTINO_SIN_COORDENADAS",
                base,
            )
        try:
            origen = _coordenadas(solicitud.coordenadas_origen)
            destino = _coordenadas(solicitud.coordenadas_destino)
        except (ErrorRutas, TypeError, ValueError):
            return self._fallo(
                EstadoCalculoRuta.DATOS_INVALIDOS, "COORDENADAS_INVALIDAS", base
            )
        if not base["perfil"] or not _PATRON_PERFIL.fullmatch(base["perfil"]):
            return self._fallo(
                EstadoCalculoRuta.DATOS_INVALIDOS, "PERFIL_INVALIDO", base,
                origen, destino,
            )
        if base["proveedor"] != str(self.proveedor.nombre):
            return self._fallo(
                EstadoCalculoRuta.PROVEEDOR_NO_DISPONIBLE,
                "PROVEEDOR_SELECCIONADO_NO_DISPONIBLE",
                base, origen, destino,
            )
        try:
            resultado = self.proveedor.calcular_ruta(
                origen, destino, base["perfil"]
            )
        except Exception:  # noqa: BLE001 - frontera controlada del proveedor
            return self._fallo(
                EstadoCalculoRuta.ERROR_PROVEEDOR,
                "EXCEPCION_CONTROLADA_DEL_PROVEEDOR",
                base, origen, destino,
            )
        if resultado.estado != EstadoRuta.RUTA_CALCULADA:
            estado = _traducir_estado(resultado.estado)
            return self._fallo(
                estado, resultado.motivo or resultado.estado.value,
                base, origen, destino,
            )
        distancia_km = float(resultado.distancia_km)
        duracion_min = float(resultado.duracion_estimada_min)
        distancia_metros = distancia_km * 1000
        duracion_segundos = duracion_min * 60
        if any(
            not math.isfinite(valor) or valor <= 0
            for valor in (distancia_metros, duracion_segundos)
        ):
            return self._fallo(
                EstadoCalculoRuta.ERROR_PROVEEDOR,
                "METRICAS_INVALIDAS_DEL_PROVEEDOR",
                base, origen, destino,
            )
        return ResultadoCalculoRuta(
            estado=EstadoCalculoRuta.CALCULADA,
            distancia_metros=distancia_metros,
            distancia_kilometros=distancia_km,
            duracion_segundos=duracion_segundos,
            duracion_legible=_duracion_legible(duracion_segundos),
            coordenadas_origen=origen.a_dict(),
            coordenadas_destino=destino.a_dict(),
            error="",
            requiere_revision=False,
            **base,
        )

    def _fecha_calculo(self) -> str:
        instante = self._reloj()
        if instante.tzinfo is None:
            instante = instante.replace(tzinfo=timezone.utc)
        return instante.isoformat()

    @staticmethod
    def _fallo(
        estado: EstadoCalculoRuta,
        error: str,
        base: dict[str, object],
        origen: Coordenadas | None = None,
        destino: Coordenadas | None = None,
    ) -> ResultadoCalculoRuta:
        return ResultadoCalculoRuta(
            estado=estado,
            distancia_metros=None,
            distancia_kilometros=None,
            duracion_segundos=None,
            duracion_legible="",
            coordenadas_origen=origen.a_dict() if origen else None,
            coordenadas_destino=destino.a_dict() if destino else None,
            error=error,
            requiere_revision=True,
            **base,
        )


def _coordenadas(valor: object) -> Coordenadas:
    if isinstance(valor, Coordenadas):
        return valor
    if isinstance(valor, Mapping):
        return Coordenadas(
            longitud=float(valor["longitud"]),
            latitud=float(valor["latitud"]),
        )
    if isinstance(valor, (tuple, list)) and len(valor) == 2:
        return Coordenadas(longitud=float(valor[0]), latitud=float(valor[1]))
    raise TypeError("formato de coordenadas no soportado")


def _traducir_estado(estado: EstadoRuta) -> EstadoCalculoRuta:
    if estado == EstadoRuta.SIN_CREDENCIAL:
        return EstadoCalculoRuta.CREDENCIAL_NO_DISPONIBLE
    if estado in {
        EstadoRuta.SIN_CONEXION,
        EstadoRuta.PROVEEDOR_NO_DISPONIBLE,
    }:
        return EstadoCalculoRuta.PROVEEDOR_NO_DISPONIBLE
    if estado in {
        EstadoRuta.REQUIERE_REVISION,
        EstadoRuta.RESULTADO_AMBIGUO,
    }:
        return EstadoCalculoRuta.REVISAR
    return EstadoCalculoRuta.ERROR_PROVEEDOR


def _duracion_legible(segundos: float) -> str:
    minutos = int(round(segundos / 60))
    horas, resto = divmod(minutos, 60)
    if horas:
        return f"{horas} h {resto} min"
    return f"{resto} min"
