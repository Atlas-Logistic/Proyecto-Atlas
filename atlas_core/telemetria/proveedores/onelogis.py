"""Adaptador HTTP de Onelogis (OnlApp Client API), Bloque TELEMETRÍA T1.

Contrato leído completo del OpenAPI real
(`https://app.onelogis.com/docs/api/openapi.yaml`, resumen en
`telemetria_eval/fase_a_openapi_resumen.md`, fuera del repo) -- ningún
parámetro fue adivinado.

Nunca loguea ni expone el valor de la credencial (Authorization: Bearer
<token>) -- ni en excepciones, ni en logs, ni en el valor de retorno.
Errores tipados (`EstadoTelemetria`), nunca lanza por un fallo de red o
de la API; solo lanza por un error de programación (parámetros
inválidos del propio Atlas).
"""

from __future__ import annotations

import json
import logging
import socket
from dataclasses import dataclass
from datetime import date
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from atlas_core.telemetria.modelos import (
    EstadoTelemetria,
    PosicionTelemetria,
    ResultadoBreadcrumbs,
    ResultadoPosicion,
    ResultadoVehiculos,
    ResultadoViajes,
    VehiculoTelemetria,
    ViajeTelemetria,
)

logger = logging.getLogger(__name__)

BASE_URL_PREDETERMINADA = "https://app.onelogis.com/api/client/v1"


@dataclass(frozen=True)
class RespuestaHTTP:
    estado: int
    cuerpo: bytes


TransporteHTTP = Callable[[Request, float], RespuestaHTTP]


def _transporte_urllib(solicitud: Request, timeout: float) -> RespuestaHTTP:
    with urlopen(solicitud, timeout=timeout) as respuesta:  # nosec: B310 - URL fija del adaptador
        return RespuestaHTTP(respuesta.status, respuesta.read())


class OnelogisProvider:
    nombre = "onelogis"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = BASE_URL_PREDETERMINADA,
        timeout: float = 15.0,
        transporte: TransporteHTTP = _transporte_urllib,
    ) -> None:
        import os

        self._api_key = (
            api_key if api_key is not None else os.getenv("ATLAS_ONELOGIS_API_KEY", "")
        ).strip()
        if timeout <= 0:
            raise ValueError("timeout debe ser positivo")
        self._base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._transporte = transporte

    def _solicitar(self, path: str, parametros: dict | None = None):
        if not self._api_key:
            return EstadoTelemetria.SIN_CREDENCIAL, None
        url = f"{self._base_url}{path}"
        if parametros:
            url = f"{url}?{urlencode(parametros)}"
        solicitud = Request(url, method="GET")
        solicitud.add_header("Authorization", f"Bearer {self._api_key}")
        solicitud.add_header("Accept", "application/json")
        try:
            respuesta = self._transporte(solicitud, self.timeout)
        except HTTPError as error:
            if error.code in (401, 403):
                return EstadoTelemetria.NO_AUTORIZADO, None
            if error.code == 404:
                return EstadoTelemetria.VEHICULO_NO_ENCONTRADO, None
            if error.code == 429:
                return EstadoTelemetria.LIMITE_CUOTA, None
            logger.warning("Onelogis: error HTTP %s en %s", error.code, path)
            return EstadoTelemetria.ERROR_PROVEEDOR, None
        except (TimeoutError, socket.timeout):
            return EstadoTelemetria.SIN_CONEXION, None
        except (URLError, OSError):
            return EstadoTelemetria.SIN_CONEXION, None
        if respuesta.estado == 429:
            return EstadoTelemetria.LIMITE_CUOTA, None
        if not 200 <= respuesta.estado < 300:
            return EstadoTelemetria.ERROR_PROVEEDOR, None
        try:
            return None, json.loads(respuesta.cuerpo.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return EstadoTelemetria.RESPUESTA_INVALIDA, None

    def listar_vehiculos(self) -> ResultadoVehiculos:
        estado, datos = self._solicitar("/vehicles")
        if estado:
            return ResultadoVehiculos(estado, motivo=estado.value)
        try:
            items = datos["data"]["items"]
            vehiculos = tuple(
                VehiculoTelemetria(
                    patente=str(item.get("plate", "")).strip().upper(),
                    proveedor_id=str(item.get("vehicle_id", "")),
                    alias=str(item.get("alias", "")),
                    marca=str(item.get("brand", "")),
                    modelo=str(item.get("model", "")),
                )
                for item in items
            )
        except (KeyError, TypeError):
            return ResultadoVehiculos(
                EstadoTelemetria.RESPUESTA_INVALIDA, motivo="ESTRUCTURA_INESPERADA"
            )
        return ResultadoVehiculos(EstadoTelemetria.OK, vehiculos)

    def obtener_posicion_actual(self, patente: str) -> ResultadoPosicion:
        patente_normalizada = str(patente or "").strip().upper()
        if not patente_normalizada:
            return ResultadoPosicion(
                EstadoTelemetria.VEHICULO_NO_ENCONTRADO, motivo="PATENTE_VACIA"
            )
        estado, datos = self._solicitar(f"/vehicles/{patente_normalizada}/position")
        if estado:
            return ResultadoPosicion(estado, motivo=estado.value)
        try:
            posicion = datos["data"]["position"]
            resultado = PosicionTelemetria(
                latitud=float(posicion["lat"]),
                longitud=float(posicion["long"]),
                timestamp=str(posicion.get("device_time", "")),
                velocidad=(
                    float(posicion["speed"]) if posicion.get("speed") is not None else None
                ),
                evento=str(posicion.get("event", "")),
            )
        except (KeyError, TypeError, ValueError):
            return ResultadoPosicion(
                EstadoTelemetria.RESPUESTA_INVALIDA, motivo="ESTRUCTURA_INESPERADA"
            )
        return ResultadoPosicion(EstadoTelemetria.OK, resultado)

    def buscar_viajes(self, patente: str, desde: date, hasta: date) -> ResultadoViajes:
        patente_normalizada = str(patente or "").strip().upper()
        if not patente_normalizada:
            return ResultadoViajes(
                EstadoTelemetria.VEHICULO_NO_ENCONTRADO, motivo="PATENTE_VACIA"
            )
        if hasta < desde:
            return ResultadoViajes(
                EstadoTelemetria.ERROR_PROVEEDOR, motivo="RANGO_DE_FECHAS_INVALIDO"
            )
        estado, datos = self._solicitar(
            f"/vehicles/{patente_normalizada}/trips",
            {"start_date": desde.isoformat(), "end_date": hasta.isoformat(), "per_page": 100},
        )
        if estado:
            return ResultadoViajes(estado, motivo=estado.value)
        try:
            items = datos["data"]["items"]
            viajes = tuple(
                ViajeTelemetria(
                    proveedor_trip_id=str(item.get("trip_id", "")),
                    patente=patente_normalizada,
                    inicio=str(item.get("start_time", "")),
                    fin=str(item.get("end_time", "")),
                    distancia_km=(
                        float(item["distance_km"]) if item.get("distance_km") is not None else None
                    ),
                )
                for item in items
            )
        except (KeyError, TypeError, ValueError):
            return ResultadoViajes(
                EstadoTelemetria.RESPUESTA_INVALIDA, motivo="ESTRUCTURA_INESPERADA"
            )
        if not viajes:
            return ResultadoViajes(EstadoTelemetria.SIN_HISTORICO, motivo="SIN_VIAJES_EN_VENTANA")
        return ResultadoViajes(EstadoTelemetria.OK, viajes)

    def obtener_breadcrumbs(self, trip_id: str) -> ResultadoBreadcrumbs:
        trip_id_texto = str(trip_id or "").strip()
        if not trip_id_texto:
            return ResultadoBreadcrumbs(
                EstadoTelemetria.TRIP_NO_ENCONTRADO, motivo="TRIP_ID_VACIO"
            )
        estado, datos = self._solicitar(f"/trips/{trip_id_texto}/breadcrumbs")
        if estado:
            return ResultadoBreadcrumbs(estado, motivo=estado.value)
        try:
            puntos_crudos = datos["data"]["points"]
            puntos = tuple(
                PosicionTelemetria(
                    latitud=float(p["lat"]),
                    longitud=float(p["long"]),
                    timestamp=str(p.get("device_time", "")),
                    velocidad=(float(p["speed"]) if p.get("speed") is not None else None),
                    evento=str(p.get("event", "")),
                )
                for p in puntos_crudos
            )
        except (KeyError, TypeError, ValueError):
            return ResultadoBreadcrumbs(
                EstadoTelemetria.RESPUESTA_INVALIDA, motivo="ESTRUCTURA_INESPERADA"
            )
        if not puntos:
            return ResultadoBreadcrumbs(EstadoTelemetria.SIN_HISTORICO, motivo="SIN_PUNTOS")
        return ResultadoBreadcrumbs(EstadoTelemetria.OK, puntos)
