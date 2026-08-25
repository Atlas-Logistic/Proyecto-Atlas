"""Consultas Atlas V1 -- B1 como INTÉRPRETE de lenguaje natural hacia
`ConsultaAtlas` (Bloque 10), nunca como calculador. Reutiliza la misma
infraestructura HTTP/credencial/errores ya construida para Atlas IA
(`atlas_core.atlas_ia.proveedor_anthropic`) -- transporte inyectable,
credencial desde variable de entorno, salida estructurada FORZADA vía
tool-use (nunca prosa libre a parsear) -- en vez de duplicar esa capa,
sólo se define aquí el esquema/prompt propio de ConsultaAtlas, distinto
del de `HipotesisIA` (Bloque A1/A2) porque la tarea es genuinamente
otra: interpretar una pregunta completa, no evaluar una hipótesis de
identidad de un campo.

Camino LENTO (Bloque 21): sólo se invoca cuando el intérprete
determinístico (`interpretador_consultas.interpretar_consulta_
determinista`) no reconoce ninguna métrica. Una sola llamada
estructurada, nunca varias, nunca web/geocoding/routing/OCR."""

from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from typing import Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from atlas_core.consultas_atlas import (
    AGRUPACIONES_SOPORTADAS,
    FILTROS_SOPORTADOS,
    METRICAS_SOPORTADAS,
    PERIODOS_SOPORTADOS,
    ConsultaAtlas,
    ErrorConsultaAtlas,
)
from atlas_core.interpretador_consultas import CatalogosConsulta

_URL_MENSAJES = "https://api.anthropic.com/v1/messages"
_VERSION_API_ANTHROPIC = "2023-06-01"
_NOMBRE_HERRAMIENTA = "interpretar_consulta_atlas"


class ErrorProveedorInterpretacion(RuntimeError):
    """Error base -- nunca incluye la credencial en el mensaje."""


class CredencialInterpretacionAusente(ErrorProveedorInterpretacion):
    pass


class InterpretacionNoDisponible(ErrorProveedorInterpretacion):
    pass


@dataclass(frozen=True)
class RespuestaHTTP:
    estado: int
    cuerpo: bytes


TransporteHTTP = Callable[[Request, float], RespuestaHTTP]


def _transporte_urllib(solicitud: Request, timeout: float) -> RespuestaHTTP:
    with urlopen(solicitud, timeout=timeout) as respuesta:  # nosec: B310 - URL fija
        return RespuestaHTTP(respuesta.status, respuesta.read())


class ProveedorInterpretacionConsulta(Protocol):
    """B1 recibe SÓLO la pregunta y los valores reales ya conocidos del
    dataset (`CatalogosConsulta`) -- nunca acceso directo al CSV ni a
    catálogos privados. Devuelve `None` cuando se abstiene (Bloque 14:
    "si no sabe, se abstiene/aclara") -- nunca inventa una consulta."""

    def interpretar(self, pregunta: str, catalogos: CatalogosConsulta) -> ConsultaAtlas | None: ...


def _herramienta_consulta_atlas() -> dict:
    return {
        "name": _NOMBRE_HERRAMIENTA,
        "description": (
            "Convierte una pregunta operacional en lenguaje natural sobre "
            "viajes de Atlas a una consulta estructurada. Nunca calcules "
            "ningún número -- sólo identifica métrica, filtros, "
            "agrupación y período."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "metrica": {"type": "string", "enum": sorted(METRICAS_SOPORTADAS)},
                "filtros": {
                    "type": "object",
                    "description": "Sólo campos con evidencia real en la pregunta.",
                    "properties": {campo: {"type": "string"} for campo in sorted(FILTROS_SOPORTADOS)},
                    "additionalProperties": False,
                },
                "agrupacion": {"type": ["string", "null"], "enum": [*sorted(AGRUPACIONES_SOPORTADAS), None]},
                "limite": {"type": ["integer", "null"]},
                "abstencion": {
                    "type": "boolean",
                    "description": "true si la pregunta no es interpretable como consulta operacional de Atlas.",
                },
            },
            "required": ["metrica", "filtros", "abstencion"],
        },
    }


def _prompt_sistema(catalogos: CatalogosConsulta) -> str:
    return (
        "Eres el intérprete de Consultas Atlas. Tu única tarea es traducir "
        "una pregunta en lenguaje natural sobre la operación de transporte "
        "a los campos de una consulta estructurada. NUNCA calcules ni "
        "inventes un número de respuesta -- eso lo hace el Motor "
        "determinístico después. Usa filtros SÓLO cuando la pregunta "
        "mencione algo compatible con estos valores reales del dataset "
        "ya cargado (nunca inventes un valor que no esté en estas listas):\n"
        f"choferes: {', '.join(catalogos.choferes) or '(ninguno)'}\n"
        f"clientes: {', '.join(catalogos.clientes) or '(ninguno)'}\n"
        f"obras: {', '.join(catalogos.obras) or '(ninguno)'}\n"
        f"tipos_carga: {', '.join(catalogos.tipos_carga) or '(ninguno)'}\n"
        f"comunas: {', '.join(catalogos.comunas) or '(ninguno)'}\n"
        f"períodos válidos: {', '.join(sorted(PERIODOS_SOPORTADOS))}\n"
        "Si la pregunta no es una consulta operacional interpretable con "
        "esta evidencia, responde abstencion=true."
    )


class ProveedorInterpretacionConsultaAnthropic:
    """Implementación real -- misma mecánica HTTP/errores que
    `atlas_ia.proveedor_anthropic.ProveedorModeloIAAnthropic`, esquema
    propio."""

    nombre = "anthropic"

    def __init__(
        self, *, modelo: str = "claude-sonnet-5", api_key: str | None = None,
        timeout: float = 30.0, transporte: TransporteHTTP = _transporte_urllib, max_tokens: int = 1024,
    ) -> None:
        self._api_key = (api_key if api_key is not None else os.getenv("ANTHROPIC_API_KEY", "")).strip()
        self._modelo = modelo
        self._timeout = timeout
        self._transporte = transporte
        self._max_tokens = max_tokens

    def interpretar(self, pregunta: str, catalogos: CatalogosConsulta) -> ConsultaAtlas | None:
        if not self._api_key:
            raise CredencialInterpretacionAusente("No hay ANTHROPIC_API_KEY configurada en este entorno.")
        cuerpo = json.dumps({
            "model": self._modelo, "max_tokens": self._max_tokens,
            "system": _prompt_sistema(catalogos),
            "tools": [_herramienta_consulta_atlas()],
            "tool_choice": {"type": "tool", "name": _NOMBRE_HERRAMIENTA},
            "messages": [{"role": "user", "content": pregunta}],
        }).encode("utf-8")
        solicitud = Request(_URL_MENSAJES, data=cuerpo, method="POST")
        solicitud.add_header("x-api-key", self._api_key)
        solicitud.add_header("anthropic-version", _VERSION_API_ANTHROPIC)
        solicitud.add_header("content-type", "application/json")
        try:
            respuesta = self._transporte(solicitud, self._timeout)
        except HTTPError as error:
            raise InterpretacionNoDisponible(f"Anthropic devolvió HTTP {error.code}.") from error
        except (TimeoutError, socket.timeout) as error:
            raise InterpretacionNoDisponible("Tiempo de espera agotado consultando Anthropic.") from error
        except (URLError, OSError) as error:
            raise InterpretacionNoDisponible("Sin conexión con Anthropic.") from error
        if not 200 <= respuesta.estado < 300:
            raise InterpretacionNoDisponible(f"Anthropic devolvió HTTP {respuesta.estado}.")
        try:
            datos = json.loads(respuesta.cuerpo)
            bloque = next(b for b in datos["content"] if b.get("type") == "tool_use")
            entrada = bloque["input"]
        except (json.JSONDecodeError, KeyError, StopIteration, TypeError):
            raise InterpretacionNoDisponible("Respuesta de Anthropic no tiene la forma esperada.")
        return _consulta_desde_entrada_herramienta(entrada)


def _consulta_desde_entrada_herramienta(entrada: dict) -> ConsultaAtlas | None:
    if not isinstance(entrada, dict) or entrada.get("abstencion"):
        return None
    filtros = entrada.get("filtros") or {}
    if not isinstance(filtros, dict):
        return None
    agrupacion = entrada.get("agrupacion") or None
    limite = entrada.get("limite")
    try:
        return ConsultaAtlas(
            metrica=str(entrada.get("metrica", "")),
            filtros={str(k): str(v) for k, v in filtros.items()},
            agrupacion=str(agrupacion) if agrupacion else None,
            limite=int(limite) if isinstance(limite, (int, float)) else None,
        )
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class RespuestaSimuladaInterpretacion:
    """Plantilla determinista para tests -- nunca red real."""

    consulta: ConsultaAtlas | None


class ProveedorInterpretacionConsultaSimulado:
    """Doble determinista (mismo patrón que `ProveedorModeloIASimulado`
    de Atlas IA): responde, para cada `pregunta` exacta, lo que el test
    configuró -- nunca simula capacidad de razonamiento real."""

    nombre = "SIMULADO"

    def __init__(self, *, respuestas_por_pregunta: dict[str, RespuestaSimuladaInterpretacion]) -> None:
        self._respuestas = dict(respuestas_por_pregunta)
        self.preguntas_recibidas: list[str] = []

    def interpretar(self, pregunta: str, catalogos: CatalogosConsulta) -> ConsultaAtlas | None:
        self.preguntas_recibidas.append(pregunta)
        plantilla = self._respuestas.get(pregunta)
        return plantilla.consulta if plantilla is not None else None
