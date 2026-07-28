"""Verificación opcional y minimizada de destinos mediante Pelias/HeiGIT."""

from __future__ import annotations

import hashlib
import json
import math
import os
import socket
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from types import MappingProxyType
from typing import Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from atlas_core.inteligencia.modelos import (
    EstadoPropuesta,
    Evidencia,
    NivelConfianza,
    TipoFuente,
)
from atlas_core.inteligencia.motor import MotorResolucion, normalizar


class EstadoVerificacionDestino(str, Enum):
    VERIFICADA = "VERIFICADA"
    COINCIDENCIA_PARCIAL = "COINCIDENCIA_PARCIAL"
    CONTRADICCION_COMUNA = "CONTRADICCION_COMUNA"
    CONTRADICCION_REGION = "CONTRADICCION_REGION"
    SIN_RESULTADOS = "SIN_RESULTADOS"
    CREDENCIAL_NO_DISPONIBLE = "CREDENCIAL_NO_DISPONIBLE"
    CUOTA_AGOTADA = "CUOTA_AGOTADA"
    TIMEOUT = "TIMEOUT"
    ERROR_PROVEEDOR = "ERROR_PROVEEDOR"
    DATOS_INSUFICIENTES = "DATOS_INSUFICIENTES"
    CONSULTA_NO_AUTORIZADA = "CONSULTA_NO_AUTORIZADA"
    REVISAR = "REVISAR"


@dataclass(frozen=True)
class SolicitudVerificacionDestino:
    direccion_original: str
    comuna_esperada: str
    region_esperada: str
    pais: str
    identificador_interno: str = ""
    autorizacion_externa: bool = False
    campos_autorizados: frozenset[str] = frozenset()
    contiene_datos_sensibles: bool = False
    contexto_minimo: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "contexto_minimo", MappingProxyType(dict(self.contexto_minimo))
        )


@dataclass(frozen=True)
class ResultadoVerificacionDestino:
    estado: EstadoVerificacionDestino
    consulta_minimizada: str
    direccion_devuelta: str
    comuna_encontrada: str
    region_encontrada: str
    pais_encontrado: str
    latitud: float | None
    longitud: float | None
    tipo_coincidencia: str
    confianza_proveedor: float | None
    codigo_http: int | None
    proveedor: str
    fecha_consulta: datetime
    duracion_ms: float
    error: str
    requiere_revision: bool
    evidencia_original: SolicitudVerificacionDestino
    identificador_consulta: str
    expira_en: datetime
    desde_cache: bool = False


@dataclass(frozen=True)
class RespuestaHTTPDestino:
    estado: int
    cuerpo: bytes


TransporteHTTPDestino = Callable[[Request, float], RespuestaHTTPDestino]


def _transporte_urllib(
    solicitud: Request, timeout: float
) -> RespuestaHTTPDestino:
    with urlopen(solicitud, timeout=timeout) as respuesta:  # nosec B310: host fijo
        return RespuestaHTTPDestino(respuesta.status, respuesta.read())


class CacheVerificaciones(Protocol):
    def obtener(self, clave: str, ahora: datetime) -> ResultadoVerificacionDestino | None: ...
    def guardar(self, clave: str, resultado: ResultadoVerificacionDestino) -> None: ...


class CacheVerificacionesMemoria:
    def __init__(self) -> None:
        self._datos: dict[str, ResultadoVerificacionDestino] = {}

    def obtener(
        self, clave: str, ahora: datetime
    ) -> ResultadoVerificacionDestino | None:
        resultado = self._datos.get(clave)
        if resultado is None or resultado.expira_en <= ahora:
            self._datos.pop(clave, None)
            return None
        return ResultadoVerificacionDestino(
            **{**resultado.__dict__, "desde_cache": True}
        )

    def guardar(
        self, clave: str, resultado: ResultadoVerificacionDestino
    ) -> None:
        self._datos[clave] = resultado


class VerificadorDestinosOpenRouteService:
    """Adaptador real opcional; el motor no conoce sus detalles HTTP."""

    nombre = "openrouteservice-pelias"
    version = "2026-07"
    URL = "https://api.heigit.org/pelias/v1/search"
    _CAMPOS_PERMITIDOS = frozenset(
        {"direccion_original", "comuna_esperada", "region_esperada", "pais"}
    )

    def __init__(
        self,
        *,
        api_key: str | None = None,
        timeout: float = 8.0,
        limite_consultas: int = 20,
        cache: CacheVerificaciones | None = None,
        usar_cache: bool = True,
        ttl: timedelta = timedelta(hours=24),
        transporte: TransporteHTTPDestino = _transporte_urllib,
        reloj: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        monotono: Callable[[], float] = time.monotonic,
    ) -> None:
        if timeout <= 0 or limite_consultas < 0 or ttl.total_seconds() <= 0:
            raise ValueError("timeout, límite y TTL deben ser válidos")
        self._api_key = (
            api_key
            if api_key is not None
            else os.getenv("OPENROUTESERVICE_API_KEY", "")
        ).strip()
        self.timeout = timeout
        self.limite_consultas = limite_consultas
        self.cache = cache or CacheVerificacionesMemoria()
        self.usar_cache = usar_cache
        self.ttl = ttl
        self._transporte = transporte
        self._reloj = reloj
        self._monotono = monotono
        self.consultas_realizadas = 0

    def verificar(
        self, solicitud: SolicitudVerificacionDestino
    ) -> ResultadoVerificacionDestino:
        ahora = self._reloj()
        consulta = _consulta_minimizada(solicitud)
        clave = _identificador_consulta(consulta)
        base = dict(
            consulta_minimizada=consulta,
            proveedor=self.nombre,
            fecha_consulta=ahora,
            evidencia_original=solicitud,
            identificador_consulta=clave,
            expira_en=ahora + self.ttl,
        )
        if not solicitud.autorizacion_externa:
            return self._fallo(
                EstadoVerificacionDestino.CONSULTA_NO_AUTORIZADA,
                "CONSULTA_EXTERNA_NO_AUTORIZADA", base,
            )
        requeridos = {"direccion_original", "pais"}
        autorizados = solicitud.campos_autorizados & self._CAMPOS_PERMITIDOS
        if not requeridos <= autorizados:
            return self._fallo(
                EstadoVerificacionDestino.DATOS_INSUFICIENTES,
                "CAMPOS_MINIMOS_NO_AUTORIZADOS", base,
            )
        if not solicitud.direccion_original.strip() or not solicitud.pais.strip():
            return self._fallo(
                EstadoVerificacionDestino.DATOS_INSUFICIENTES,
                "DIRECCION_O_PAIS_AUSENTE", base,
            )
        if not self._api_key:
            return self._fallo(
                EstadoVerificacionDestino.CREDENCIAL_NO_DISPONIBLE,
                "CREDENCIAL_NO_DISPONIBLE", base,
            )
        if self.usar_cache:
            almacenado = self.cache.obtener(clave, ahora)
            if almacenado is not None:
                return almacenado
        if self.consultas_realizadas >= self.limite_consultas:
            return self._fallo(
                EstadoVerificacionDestino.CUOTA_AGOTADA,
                "LIMITE_LOCAL_DE_CONSULTAS", base,
            )

        parametros = {"text": consulta, "size": 2}
        peticion = Request(f"{self.URL}?{urlencode(parametros)}", method="GET")
        peticion.add_header("Authorization", self._api_key)
        peticion.add_header("Accept", "application/json")
        inicio = self._monotono()
        self.consultas_realizadas += 1
        try:
            respuesta = self._transporte(peticion, self.timeout)
        except HTTPError as error:
            estado = (
                EstadoVerificacionDestino.CUOTA_AGOTADA
                if error.code in (403, 429)
                else EstadoVerificacionDestino.ERROR_PROVEEDOR
            )
            return self._fallo(estado, f"HTTP_{error.code}", base, error.code, inicio)
        except (TimeoutError, socket.timeout):
            return self._fallo(
                EstadoVerificacionDestino.TIMEOUT, "TIMEOUT", base, None, inicio
            )
        except (URLError, OSError):
            return self._fallo(
                EstadoVerificacionDestino.ERROR_PROVEEDOR,
                "CONEXION_NO_DISPONIBLE", base, None, inicio,
            )
        if respuesta.estado in (403, 429):
            return self._fallo(
                EstadoVerificacionDestino.CUOTA_AGOTADA,
                f"HTTP_{respuesta.estado}", base, respuesta.estado, inicio,
            )
        if not 200 <= respuesta.estado < 300:
            return self._fallo(
                EstadoVerificacionDestino.ERROR_PROVEEDOR,
                f"HTTP_{respuesta.estado}", base, respuesta.estado, inicio,
            )
        try:
            datos = json.loads(respuesta.cuerpo.decode("utf-8"))
            features = datos["features"]
            if not isinstance(features, list):
                raise TypeError
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
            return self._fallo(
                EstadoVerificacionDestino.ERROR_PROVEEDOR,
                "RESPUESTA_INVALIDA", base, respuesta.estado, inicio,
            )
        if not features:
            resultado = self._fallo(
                EstadoVerificacionDestino.SIN_RESULTADOS,
                "SIN_RESULTADOS", base, respuesta.estado, inicio,
            )
        elif len(features) > 1:
            resultado = self._fallo(
                EstadoVerificacionDestino.REVISAR,
                "MULTIPLES_RESULTADOS", base, respuesta.estado, inicio,
            )
        else:
            resultado = self._interpretar(
                features[0], solicitud, base, respuesta.estado, inicio
            )
        if self.usar_cache:
            self.cache.guardar(clave, resultado)
        return resultado

    def _interpretar(self, feature, solicitud, base, codigo, inicio):
        try:
            propiedades = feature["properties"]
            coordenadas = feature["geometry"]["coordinates"]
            longitud, latitud = float(coordenadas[0]), float(coordenadas[1])
            if not (
                math.isfinite(longitud)
                and math.isfinite(latitud)
                and -180 <= longitud <= 180
                and -90 <= latitud <= 90
            ):
                raise ValueError
            direccion = str(propiedades.get("label", "")).strip()
            comuna = str(
                propiedades.get("locality")
                or propiedades.get("localadmin")
                or propiedades.get("county")
                or ""
            ).strip()
            region = str(propiedades.get("region", "")).strip()
            pais = str(propiedades.get("country", "")).strip()
            confianza = _confianza(propiedades.get("confidence"))
            if not direccion:
                raise ValueError
        except (KeyError, TypeError, ValueError, IndexError):
            return self._fallo(
                EstadoVerificacionDestino.ERROR_PROVEEDOR,
                "RESULTADO_INCOMPLETO_O_INVALIDO", base, codigo, inicio,
            )
        comuna_ok = _compatible(solicitud.comuna_esperada, comuna)
        region_ok = _compatible(solicitud.region_esperada, region)
        direccion_exacta = normalizar(solicitud.direccion_original) in normalizar(direccion)
        if solicitud.region_esperada.strip() and not region_ok:
            estado, tipo = EstadoVerificacionDestino.CONTRADICCION_REGION, "CONTRADICCION"
        elif solicitud.comuna_esperada.strip() and not comuna_ok:
            estado, tipo = EstadoVerificacionDestino.CONTRADICCION_COMUNA, "CONTRADICCION"
        elif direccion_exacta and comuna_ok and region_ok:
            estado, tipo = EstadoVerificacionDestino.VERIFICADA, "EXACTA"
        else:
            estado, tipo = EstadoVerificacionDestino.COINCIDENCIA_PARCIAL, "APROXIMADA"
        revisar = estado != EstadoVerificacionDestino.VERIFICADA
        return ResultadoVerificacionDestino(
            estado, base["consulta_minimizada"], direccion, comuna, region, pais,
            latitud, longitud, tipo, confianza, codigo, self.nombre,
            base["fecha_consulta"], _duracion(self._monotono, inicio), "",
            revisar, solicitud, base["identificador_consulta"], base["expira_en"],
        )

    def _fallo(self, estado, error, base, codigo=None, inicio=None):
        return ResultadoVerificacionDestino(
            estado, base["consulta_minimizada"], "", "", "", "", None, None,
            "NINGUNA", None, codigo, self.nombre, base["fecha_consulta"],
            _duracion(self._monotono, inicio), error, True,
            base["evidencia_original"], base["identificador_consulta"],
            base["expira_en"],
        )


def convertir_a_evidencia(
    resultado: ResultadoVerificacionDestino,
) -> Evidencia | None:
    if not resultado.direccion_devuelta:
        return None
    confianza = resultado.confianza_proveedor
    return Evidencia(
        campo_objetivo="destino",
        valor_observado=resultado.direccion_devuelta,
        valor_normalizado=normalizar(resultado.direccion_devuelta),
        fuente=resultado.proveedor,
        tipo_fuente=TipoFuente.VERIFICACION_EXTERNA,
        confianza_fuente=max(0.0, min(1.0, confianza if confianza is not None else 0.5)),
        fecha_observacion=resultado.fecha_consulta,
        documento_origen=resultado.evidencia_original.identificador_interno,
        referencia=resultado.identificador_consulta,
        detalles={
            "estado": resultado.estado.value,
            "comuna": resultado.comuna_encontrada,
            "region": resultado.region_encontrada,
            "pais": resultado.pais_encontrado,
            "tipo_coincidencia": resultado.tipo_coincidencia,
            "requiere_revision": resultado.requiere_revision,
        },
        contiene_datos_sensibles=True,
    )


def resolver_destino_con_verificacion(
    valor_original: str,
    evidencias_internas: tuple[Evidencia, ...],
    resultado: ResultadoVerificacionDestino,
):
    externa = convertir_a_evidencia(resultado)
    evidencias = evidencias_internas + ((externa,) if externa else ())
    propuesta = MotorResolucion().resolver("destino", valor_original, evidencias)
    if resultado.requiere_revision and propuesta.estado not in {
        EstadoPropuesta.REVISAR, EstadoPropuesta.CONTRADICCION
    }:
        # La verificación es sólo evidencia: un estado externo dudoso prevalece
        # como requisito de revisión, nunca como escritura.
        return replace(
            propuesta,
            valor_propuesto=valor_original,
            estado=EstadoPropuesta.REVISAR,
            confianza=NivelConfianza.BAJA,
            explicacion=propuesta.explicacion
            + (f"Verificación externa: {resultado.estado.value}.",),
            accion_recomendada="REVISAR",
        )
    return propuesta


def _consulta_minimizada(solicitud: SolicitudVerificacionDestino) -> str:
    valores = []
    for campo in (
        "direccion_original", "comuna_esperada", "region_esperada", "pais"
    ):
        if campo in solicitud.campos_autorizados:
            valor = str(getattr(solicitud, campo)).strip()
            if valor:
                valores.append(valor)
    return ", ".join(valores)


def _identificador_consulta(consulta: str) -> str:
    return hashlib.sha256(normalizar(consulta).encode("utf-8")).hexdigest()


def _compatible(esperado: str, encontrado: str) -> bool:
    return not esperado.strip() or normalizar(esperado) == normalizar(encontrado)


def _confianza(valor: object) -> float | None:
    try:
        numero = float(valor)
        return numero if math.isfinite(numero) else None
    except (TypeError, ValueError):
        return None


def _duracion(monotono, inicio) -> float:
    return 0.0 if inicio is None else round((monotono() - inicio) * 1000, 3)
