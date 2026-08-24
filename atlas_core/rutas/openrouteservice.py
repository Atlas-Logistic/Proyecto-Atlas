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


def _es_error_sin_acceso_vial(cuerpo: bytes) -> bool:
    """Bloque R9 -- True sólo si el cuerpo de un 404 de ORS confirma
    explícitamente su código de error propio 2010 ("no routable point
    within a radius..."). Nunca infiere esto de un 404 vacío/no-JSON --
    esos siguen siendo PROVEEDOR_NO_DISPONIBLE genérico."""
    try:
        return json.loads(cuerpo.decode("utf-8")).get("error", {}).get("code") == 2010
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return False


def _transporte_urllib(solicitud: Request, timeout: float) -> RespuestaHTTP:
    with urlopen(solicitud, timeout=timeout) as respuesta:  # nosec: B310 - URL fija del adaptador
        return RespuestaHTTP(respuesta.status, respuesta.read())


class OpenRouteService:
    nombre = "openrouteservice"
    version = "v2"
    # Host vigente HeiGIT (api.heigit.org), confirmado contra el anuncio oficial
    # de deprecación (ask.openrouteservice.org, 2026-04-28) y verificado en vivo
    # (ambos hosts responden 401 sin credencial, es decir la ruta existe).
    # "api.openrouteservice.org" deja de funcionar el 2026-08-24 -- la misma
    # API key sirve para ambos hosts, no requiere cambio de credencial.
    URL_GEOCODIFICACION = "https://api.heigit.org/pelias/v1/search"
    URL_DIRECCIONES = "https://api.heigit.org/openrouteservice/v2/directions/{perfil}"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        timeout: float = 10.0,
        transporte: TransporteHTTP = _transporte_urllib,
        pais: str | None = None,
    ) -> None:
        self._api_key = (api_key if api_key is not None else os.getenv(
            "OPENROUTESERVICE_API_KEY", ""
        )).strip()
        if timeout <= 0:
            raise ValueError("timeout debe ser positivo")
        self.timeout = timeout
        self._transporte = transporte
        # Bloque E2E R1.1 -- `pais` (código ISO 3166-1 alfa-2, p. ej. "CL")
        # es un parámetro explícito del contexto operativo de quien
        # construye el proveedor -- nunca un valor fijo dentro de este
        # adaptador. Sin `pais`, Pelias busca sin filtro de país, idéntico
        # al comportamiento de antes de este bloque. Ver
        # `boundary.country` en `geocodificar`.
        self._pais = (pais or "").strip().upper() or None
        # Bloque RESOLUCIÓN R19 -- causa raíz real de que el fix `pais=CL`
        # (Bloque RESOLUCIÓN R16) nunca tuviera efecto sobre una dirección
        # YA CACHEADA (caso real 472037: seguía devolviendo Córdoba,
        # Argentina, desde caché, mucho después de restringir la consulta
        # a Chile): `RepositorioCacheGeocodificacion` cachea por
        # `(proveedor_nombre, proveedor_version, dirección)` -- `version`
        # era un atributo de CLASE fijo ("v2"), idéntico sin importar
        # `pais`, así que una consulta restringida y una sin restringir
        # compartían la MISMA entrada de caché. Ahora `version` es de
        # INSTANCIA e incluye el contexto de país -- una entrada cacheada
        # ANTES de restringir por país queda invisible para las consultas
        # YA restringidas (se re-consulta una vez, con caché real
        # después); nunca hay dos configuraciones distintas del
        # proveedor compartiendo caché por error.
        self.version = f"v2:pais={self._pais or 'SIN_RESTRICCION'}"

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
            if error.code == 404:
                try:
                    cuerpo_error = error.read()
                except (OSError, AttributeError):
                    cuerpo_error = b""
                if _es_error_sin_acceso_vial(cuerpo_error):
                    return EstadoRuta.SIN_ACCESO_VIAL, None
                return EstadoRuta.PROVEEDOR_NO_DISPONIBLE, None
            return EstadoRuta.PROVEEDOR_NO_DISPONIBLE, None
        except (TimeoutError, socket.timeout):
            return EstadoRuta.SIN_CONEXION, None
        except (URLError, OSError):
            return EstadoRuta.SIN_CONEXION, None
        if respuesta.estado in (403, 429):
            return EstadoRuta.LIMITE_CUOTA, None
        if not 200 <= respuesta.estado < 300:
            # Bloque R9 -- caso real 472044: distingue el 404 genérico
            # (proveedor caído/endpoint inválido) del 404 específico de
            # ORS "no se encontró un punto ruteable cerca de la
            # coordenada" (código de error propio 2010) -- ese NO es una
            # falla técnica externa, es evidencia real de que el punto
            # geocodificado (p. ej. un centroide de comuna, confianza
            # baja) es demasiado impreciso para calcular ruta. Nunca se
            # asume: sólo se reclasifica si el propio cuerpo de la
            # respuesta lo confirma explícitamente.
            if respuesta.estado == 404 and _es_error_sin_acceso_vial(respuesta.cuerpo):
                return EstadoRuta.SIN_ACCESO_VIAL, None
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
        parametros = {"text": direccion, "size": 5}
        if self._pais:
            # Filtro estructurado de Pelias (no un simple ", <país>" pegado
            # al texto de búsqueda) -- reduce candidatos fuera del país de
            # operación sin depender de que el texto libre lo mencione.
            parametros["boundary.country"] = self._pais
        url = f"{self.URL_GEOCODIFICACION}?{urlencode(parametros)}"
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
                    str(item.get("properties", {}).get("locality", "")).strip(),
                    str(item.get("properties", {}).get("region", "")).strip(),
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
