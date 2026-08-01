"""Adaptador HTTP de OpenRouteService, inyectable y sin reintentos automáticos."""

from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion,
    Coordenadas,
    EstadoRuta,
    ResultadoGeocodificacion,
    ResultadoRuta,
)


@dataclass(frozen=True)
class RespuestaHTTP:
    estado: int
    cuerpo: bytes


TransporteHTTP = Callable[[Request, float], RespuestaHTTP]


def _transporte_urllib(solicitud: Request, timeout: float) -> RespuestaHTTP:
    with urlopen(solicitud, timeout=timeout) as respuesta:  # nosec: B310 - URL fija del adaptador
        return RespuestaHTTP(respuesta.status, respuesta.read())


class OpenRouteService:
    nombre = "openrouteservice"
    version = "v2"
    URL_GEOCODIFICACION = "https://api.openrouteservice.org/geocode/search"
    URL_DIRECCIONES = "https://api.openrouteservice.org/v2/directions/{perfil}"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        timeout: float = 10.0,
        transporte: TransporteHTTP = _transporte_urllib,
    ) -> None:
        self._api_key = (api_key if api_key is not None else os.getenv(
            "OPENROUTESERVICE_API_KEY", ""
        )).strip()
        if timeout <= 0:
            raise ValueError("timeout debe ser positivo")
        self.timeout = timeout
        self._transporte = transporte

    def _solicitar(self, solicitud: Request) -> tuple[EstadoRuta | None, object | None]:
        if not self._api_key:
            return EstadoRuta.SIN_CREDENCIAL, None
        solicitud.add_header("Authorization", self._api_key)
        solicitud.add_header("Accept", "application/json")
        try:
            respuesta = self._transporte(solicitud, self.timeout)
        except HTTPError as error:
            if error.code in (403, 429):
                return EstadoRuta.LIMITE_CUOTA, None
            return EstadoRuta.PROVEEDOR_NO_DISPONIBLE, None
        except (TimeoutError, socket.timeout):
            return EstadoRuta.SIN_CONEXION, None
        except (URLError, OSError):
            return EstadoRuta.SIN_CONEXION, None
        if respuesta.estado in (403, 429):
            return EstadoRuta.LIMITE_CUOTA, None
        if not 200 <= respuesta.estado < 300:
            return EstadoRuta.PROVEEDOR_NO_DISPONIBLE, None
        try:
            return None, json.loads(respuesta.cuerpo.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return EstadoRuta.RESPUESTA_INVALIDA, None

    def geocodificar(self, direccion: str) -> ResultadoGeocodificacion:
        if not str(direccion).strip():
            return ResultadoGeocodificacion(
                EstadoRuta.DIRECCION_NO_ENCONTRADA, motivo="DIRECCION_VACIA"
            )
        url = f"{self.URL_GEOCODIFICACION}?{urlencode({'text': direccion, 'size': 5})}"
        estado, datos = self._solicitar(Request(url, method="GET"))
        if estado:
            return ResultadoGeocodificacion(estado, motivo=estado.value)
        try:
            features = datos["features"]
            if not isinstance(features, list):
                raise TypeError
            candidatos = tuple(
                CandidatoGeocodificacion(
                    Coordenadas(float(item["geometry"]["coordinates"][0]),
                                float(item["geometry"]["coordinates"][1])),
                    str(item.get("properties", {}).get("label", "")).strip(),
                    _confianza(item.get("properties", {}).get("confidence")),
                )
                for item in features
            )
        except (KeyError, TypeError, ValueError, IndexError):
            return ResultadoGeocodificacion(
                EstadoRuta.RESPUESTA_INVALIDA, motivo="RESPUESTA_GEOCODIFICACION_INVALIDA"
            )
        if not candidatos:
            return ResultadoGeocodificacion(
                EstadoRuta.DIRECCION_NO_ENCONTRADA, motivo="SIN_CANDIDATOS"
            )
        if len(candidatos) > 1:
            return ResultadoGeocodificacion(
                EstadoRuta.RESULTADO_AMBIGUO, candidatos, "MULTIPLES_CANDIDATOS"
            )
        return ResultadoGeocodificacion(
            EstadoRuta.REQUIERE_REVISION, candidatos, "REQUIERE_CONFIRMACION_HUMANA"
        )

    def calcular_ruta(
        self, origen: Coordenadas, destino: Coordenadas, perfil: str
    ) -> ResultadoRuta:
        cuerpo = json.dumps({
            "coordinates": [
                [origen.longitud, origen.latitud],
                [destino.longitud, destino.latitud],
            ]
        }).encode("utf-8")
        solicitud = Request(
            self.URL_DIRECCIONES.format(perfil=perfil), data=cuerpo, method="POST",
            headers={"Content-Type": "application/json"},
        )
        estado, datos = self._solicitar(solicitud)
        if estado:
            return ResultadoRuta(estado, motivo=estado.value)
        try:
            resumen = datos["routes"][0]["summary"]
            distancia = float(resumen["distance"]) / 1000
            duracion = float(resumen["duration"]) / 60
            return ResultadoRuta(EstadoRuta.RUTA_CALCULADA, distancia, duracion)
        except (KeyError, TypeError, ValueError, IndexError):
            return ResultadoRuta(
                EstadoRuta.RESPUESTA_INVALIDA, motivo="RESPUESTA_RUTA_INVALIDA"
            )


def _confianza(valor: object) -> float | None:
    try:
        return None if valor is None else float(valor)
    except (TypeError, ValueError):
        return None
