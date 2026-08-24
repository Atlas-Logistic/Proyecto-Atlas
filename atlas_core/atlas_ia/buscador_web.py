"""Bloque B1 INVESTIGADOR -- herramienta REAL de verificación externa
(búsqueda web) que B1 puede solicitar durante su propio razonamiento.

Cierra el hueco documentado en `contratos.TIPOS_FUENTE_IA` ("EXTERNO --
verificación externa, hoy sin proveedor real conectado"). Reutiliza
OpenRouter (`OPENROUTER_API_KEY`, ya presente en el entorno y ya usado
por `proveedor_openrouter.py` para otro propósito) con un modelo
`:online`/con búsqueda propia (Perplexity Sonar) -- NO es un segundo
razonador de Atlas: su única función es traer texto+citas reales de la
web para que B1 (el único que decide/concluye) las lea y las cruce con
el resto de la evidencia. Nunca decide nada por sí mismo, nunca
reemplaza a B1.

Caché real (mismo patrón que `rutas.cache_geocodificacion`): la misma
consulta nunca se paga dos veces."""

from __future__ import annotations

import json
import os
import re
import socket
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico, ruta_cache


class ErrorBuscadorWeb(Exception):
    """Error base -- nunca se traduce en evidencia fabricada, sólo en abstención."""


class CredencialBuscadorWebAusente(ErrorBuscadorWeb):
    """No hay OPENROUTER_API_KEY en el entorno."""


class BuscadorWebNoDisponible(ErrorBuscadorWeb):
    """El proveedor no respondió o devolvió una respuesta inválida."""


@dataclass(frozen=True)
class Cita:
    titulo: str
    url: str


@dataclass(frozen=True)
class RespuestaBusquedaWeb:
    consulta: str
    respuesta_texto: str
    citas: tuple[Cita, ...]
    proveedor: str
    modelo: str
    fecha: str  # ISO 8601 UTC -- cuándo se obtuvo (real, no de la caché)

    def a_dict(self) -> dict[str, object]:
        return {
            "consulta": self.consulta, "respuesta_texto": self.respuesta_texto,
            "citas": [{"titulo": c.titulo, "url": c.url} for c in self.citas],
            "proveedor": self.proveedor, "modelo": self.modelo, "fecha": self.fecha,
        }

    @classmethod
    def desde_dict(cls, datos: dict[str, object]) -> "RespuestaBusquedaWeb":
        return cls(
            consulta=str(datos.get("consulta", "")), respuesta_texto=str(datos.get("respuesta_texto", "")),
            citas=tuple(
                Cita(str(c.get("titulo", "")), str(c.get("url", "")))
                for c in (datos.get("citas") or []) if isinstance(c, dict)
            ),
            proveedor=str(datos.get("proveedor", "")), modelo=str(datos.get("modelo", "")),
            fecha=str(datos.get("fecha", "")),
        )


@dataclass(frozen=True)
class RespuestaHTTP:
    estado: int
    cuerpo: bytes


TransporteHTTP = Callable[[Request, float], RespuestaHTTP]


def _transporte_urllib(solicitud: Request, timeout: float) -> RespuestaHTTP:
    with urlopen(solicitud, timeout=timeout) as respuesta:  # nosec: B310 - endpoint fijo HTTPS
        return RespuestaHTTP(respuesta.status, respuesta.read())


_URL_COMPLETIONS = "https://openrouter.ai/api/v1/chat/completions"
# Perplexity Sonar: modelo con búsqueda web real integrada en el propio
# proveedor -- no requiere una clave de búsqueda aparte (SerpAPI/Bing/
# etc., ninguna presente en este entorno) y factura a través de la
# MISMA credencial OpenRouter ya usada en el resto del sistema. Costo
# real y pequeño por consulta (~USD 0.005, verificado) -- nunca gratis,
# nunca simulado.
_MODELO_BUSQUEDA = "perplexity/sonar"

_PROMPT_SISTEMA = (
    "Eres una herramienta de verificacion externa para un sistema logistico "
    "chileno (Atlas). Responde SOLO con hechos verificables que encuentres "
    "en la busqueda web real -- direccion exacta, comuna, region, y la "
    "empresa/obra si aparece relacionada. Si no encuentras informacion "
    "confiable, dilo explicitamente en vez de inventar. Se breve (maximo "
    "3-4 lineas). Nunca inventes una direccion ni coordenadas."
)


class BuscadorWebOpenRouter:
    """Ejecuta UNA consulta real de verificación externa vía OpenRouter
    (Perplexity Sonar, búsqueda web real). Nunca decide nada -- sólo
    trae texto+citas para que B1 los lea en su siguiente ronda."""

    nombre = "openrouter_sonar"

    def __init__(
        self, *, api_key: str | None = None, modelo: str = _MODELO_BUSQUEDA,
        timeout: float = 30.0, transporte: TransporteHTTP = _transporte_urllib,
    ) -> None:
        self._api_key = (api_key if api_key is not None else os.getenv("OPENROUTER_API_KEY", "")).strip()
        self._modelo = modelo
        self._timeout = timeout
        self._transporte = transporte

    def buscar(self, consulta: str) -> RespuestaBusquedaWeb:
        if not self._api_key:
            raise CredencialBuscadorWebAusente("No hay OPENROUTER_API_KEY configurada en este entorno.")
        cuerpo = json.dumps({
            "model": self._modelo,
            "messages": [
                {"role": "system", "content": _PROMPT_SISTEMA},
                {"role": "user", "content": str(consulta)},
            ],
            "temperature": 0,
            "max_tokens": 400,
        }, ensure_ascii=False).encode("utf-8")
        solicitud = Request(_URL_COMPLETIONS, data=cuerpo, method="POST")
        solicitud.add_header("authorization", f"Bearer {self._api_key}")
        solicitud.add_header("content-type", "application/json")
        try:
            respuesta = self._transporte(solicitud, self._timeout)
        except HTTPError as error:
            raise BuscadorWebNoDisponible(f"OpenRouter devolvió HTTP {error.code}.") from error
        except (TimeoutError, socket.timeout) as error:
            raise BuscadorWebNoDisponible("Tiempo de espera agotado en la búsqueda web.") from error
        except (URLError, OSError) as error:
            raise BuscadorWebNoDisponible("Sin conexión para la búsqueda web.") from error
        if not 200 <= respuesta.estado < 300:
            raise BuscadorWebNoDisponible(f"OpenRouter devolvió HTTP {respuesta.estado}.")
        try:
            datos = json.loads(respuesta.cuerpo)
            mensaje = datos["choices"][0]["message"]
            texto = str(mensaje.get("content", "")).strip()
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise BuscadorWebNoDisponible("Respuesta de búsqueda web sin contenido válido.") from error
        citas = tuple(
            Cita(str((a.get("url_citation") or {}).get("title", "")), str((a.get("url_citation") or {}).get("url", "")))
            for a in (mensaje.get("annotations") or [])
            if isinstance(a, dict) and a.get("type") == "url_citation"
        )
        return RespuestaBusquedaWeb(
            consulta=str(consulta), respuesta_texto=texto, citas=citas,
            proveedor=self.nombre, modelo=str(datos.get("model", self._modelo)),
            fecha=datetime.now(timezone.utc).isoformat(),
        )


def _normalizar_consulta(consulta: str) -> str:
    texto = unicodedata.normalize("NFKD", str(consulta).strip())
    texto = "".join(c for c in texto if not unicodedata.combining(c)).upper()
    return " ".join(re.findall(r"[A-Z0-9]+", texto))


NOMBRE_ARCHIVO_CACHE_PREDETERMINADO = "busqueda_web_cache.json"
VERSION_FORMATO_CACHE = 1


class RepositorioCacheBusquedaWeb:
    """JSON con escritura atómica -- mismo patrón que
    `rutas.cache_geocodificacion.RepositorioCacheGeocodificacion`: la
    misma consulta nunca se paga dos veces."""

    def __init__(self, ruta: str | Path | None = None) -> None:
        self.ruta = Path(ruta) if ruta is not None else (
            ruta_cache("busqueda_web") / NOMBRE_ARCHIVO_CACHE_PREDETERMINADO
        )

    def buscar(self, consulta: str) -> RespuestaBusquedaWeb | None:
        contenido = self._leer()
        crudo = contenido.get("consultas", {}).get(_normalizar_consulta(consulta))
        return RespuestaBusquedaWeb.desde_dict(crudo) if crudo is not None else None

    def guardar(self, consulta: str, respuesta: RespuestaBusquedaWeb) -> None:
        with bloqueo_sesion(self.ruta.parent, "busqueda_web"):
            contenido = self._leer()
            contenido.setdefault("consultas", {})[_normalizar_consulta(consulta)] = respuesta.a_dict()
            escribir_json_atomico(self.ruta, contenido)

    def _leer(self) -> dict:
        if not self.ruta.exists():
            return {"version_formato": VERSION_FORMATO_CACHE, "consultas": {}}
        try:
            contenido = json.loads(self.ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version_formato": VERSION_FORMATO_CACHE, "consultas": {}}
        if not isinstance(contenido, dict):
            return {"version_formato": VERSION_FORMATO_CACHE, "consultas": {}}
        return contenido


class BuscadorWebConCache:
    """Decorador: cachea `BuscadorWebOpenRouter.buscar` -- interfaz
    idéntica, para que `herramientas.py` no distinga entre pedir una
    consulta ya conocida o una nueva."""

    def __init__(self, interno: BuscadorWebOpenRouter, repositorio: RepositorioCacheBusquedaWeb) -> None:
        self._interno = interno
        self._repositorio = repositorio

    def buscar(self, consulta: str) -> RespuestaBusquedaWeb:
        cache = self._repositorio.buscar(consulta)
        if cache is not None:
            return cache
        resultado = self._interno.buscar(consulta)
        self._repositorio.guardar(consulta, resultado)
        return resultado
