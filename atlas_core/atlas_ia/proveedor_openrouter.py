"""Proveedor remoto OpenRouter para Atlas IA con costo cero forzado."""

from __future__ import annotations

import json
import os
import socket
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from atlas_core.atlas_ia.contratos import (
    ContextoRazonamiento,
    HipotesisIA,
    RESULTADO_HIPOTESIS_ABSTENCION,
    RESULTADO_HIPOTESIS_PROPUESTA,
    RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA,
    RESULTADOS_HIPOTESIS,
    calcular_hipotesis_id,
)
from atlas_core.atlas_ia.politica_prompt import POLITICA_PROMPT_SISTEMA, POLITICA_PROMPT_VERSION
from atlas_core.atlas_ia.proveedor_anthropic import ErrorProveedorModeloIA


class CredencialOpenRouterAusente(ErrorProveedorModeloIA):
    """No existe OPENROUTER_API_KEY en el entorno."""


class ProveedorOpenRouterNoDisponible(ErrorProveedorModeloIA):
    """OpenRouter no responde o devuelve una respuesta inválida."""


class CostoOpenRouterNoCero(ErrorProveedorModeloIA):
    """La respuesta reportó costo y el benchmark debe detenerse."""


@dataclass(frozen=True)
class RespuestaHTTP:
    estado: int
    cuerpo: bytes


TransporteHTTP = Callable[[Request, float], RespuestaHTTP]


def _transporte_urllib(solicitud: Request, timeout: float) -> RespuestaHTTP:
    with urlopen(solicitud, timeout=timeout) as respuesta:  # nosec: B310 - endpoint fijo HTTPS
        return RespuestaHTTP(respuesta.status, respuesta.read())


_URL_COMPLETIONS = "https://openrouter.ai/api/v1/chat/completions"
_MODELO_FREE = "z-ai/glm-5.2:free"
_ESQUEMA_HIPOTESIS = {
    "type": "object",
    "properties": {
        "resultado": {
            "type": "string", "enum": list(RESULTADOS_HIPOTESIS),
            "description": "Conclusión propia; nunca copies el resultado previo del motor.",
        },
        "valor_propuesto": {"type": "string"},
        "evidencia_usada": {"type": "array", "items": {"type": "string"}},
        "evidencia_en_contra": {"type": "array", "items": {"type": "string"}},
        "explicacion": {"type": "string"},
        "herramienta_faltante": {"type": "string"},
        "posible_incidencia_documental": {"type": "boolean"},
        "confianza_declarada": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "resultado", "valor_propuesto", "evidencia_usada", "evidencia_en_contra",
        "explicacion", "herramienta_faltante", "posible_incidencia_documental",
        "confianza_declarada",
    ],
    "additionalProperties": False,
}


def _mensaje_usuario(contexto: ContextoRazonamiento) -> str:
    return json.dumps({
        "campo": contexto.campo,
        "valor_documental_observado": contexto.valor_documental,
        "contexto_operacional": {
            "rut_chofer": contexto.rut_chofer,
            "numero_guia": contexto.numero_guia,
            "numero_transporte": contexto.numero_transporte,
        },
        "evidencia_disponible": [evidencia.a_dict() for evidencia in contexto.evidencias],
        "resultado_previo_del_motor_deterministico": contexto.resultado_motor,
        "explicacion_previa_del_motor_deterministico": contexto.explicacion_motor,
    }, ensure_ascii=False, indent=2)


def _detalle_error_seguro(error: HTTPError, api_key: str) -> str:
    try:
        texto = error.read().decode("utf-8", errors="replace")
        datos = json.loads(texto)
        error_datos = datos.get("error") or {}
        metadata = error_datos.get("metadata") or {}
        seguro = {
            "message": error_datos.get("message", ""),
            "code": error_datos.get("code", ""),
            "provider_name": metadata.get("provider_name", ""),
            "provider_error_code": metadata.get("provider_error_code", ""),
            "retry_after_seconds": metadata.get("retry_after_seconds", ""),
        }
        return json.dumps({clave: valor for clave, valor in seguro.items() if valor != ""})
    except Exception:
        return ""


def _abstencion_invalida(contexto: ContextoRazonamiento, modelo: str, motivo: str) -> HipotesisIA:
    return HipotesisIA(
        hipotesis_id=calcular_hipotesis_id(contexto, ""),
        campo=contexto.campo,
        valor_observado=contexto.valor_documental,
        valor_propuesto="",
        resultado=RESULTADO_HIPOTESIS_ABSTENCION,
        explicacion=f"Respuesta OpenRouter descartada por estructura inválida: {motivo}",
        proveedor="openrouter",
        modelo=modelo,
        metadata={"politica_prompt_version": POLITICA_PROMPT_VERSION, "respuesta_invalida": True},
    )


def _hipotesis_desde_entrada(
    entrada: object, contexto: ContextoRazonamiento, *, modelo: str, metadata: dict[str, object],
) -> HipotesisIA:
    if not isinstance(entrada, dict):
        return _abstencion_invalida(contexto, modelo, "el JSON final no es un objeto")
    resultado = str(entrada.get("resultado", "")).strip()
    if resultado not in RESULTADOS_HIPOTESIS:
        return _abstencion_invalida(contexto, modelo, f"resultado desconocido {resultado!r}")
    valor = str(entrada.get("valor_propuesto", "")).strip() if resultado == RESULTADO_HIPOTESIS_PROPUESTA else ""
    herramienta = (
        str(entrada.get("herramienta_faltante", "")).strip()
        if resultado == RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA else ""
    )
    metadata = dict(metadata)
    metadata["politica_prompt_version"] = POLITICA_PROMPT_VERSION
    if "confianza_declarada" in entrada:
        metadata["confianza_declarada"] = entrada["confianza_declarada"]
    if entrada.get("posible_incidencia_documental"):
        metadata["posible_incidencia_documental"] = True
    try:
        return HipotesisIA(
            hipotesis_id=calcular_hipotesis_id(contexto, valor),
            campo=contexto.campo,
            valor_observado=contexto.valor_documental,
            valor_propuesto=valor,
            resultado=resultado,
            evidencia_usada=tuple(entrada.get("evidencia_usada") or ()),
            evidencia_en_contra=tuple(entrada.get("evidencia_en_contra") or ()),
            explicacion=str(entrada.get("explicacion", "")),
            herramienta_faltante=herramienta,
            proveedor="openrouter",
            modelo=modelo,
            metadata=metadata,
        )
    except (TypeError, ValueError) as error:
        return _abstencion_invalida(contexto, modelo, str(error))


class ProveedorModeloIAOpenRouter:
    """Proveedor OpenAI-compatible con variante ``:free`` concreta."""

    nombre = "openrouter"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        modelo: str = _MODELO_FREE,
        timeout: float = 180.0,
        transporte: TransporteHTTP = _transporte_urllib,
    ) -> None:
        self._api_key = (
            api_key if api_key is not None else os.getenv("OPENROUTER_API_KEY", "")
        ).strip()
        self._modelo = modelo
        self._timeout = timeout
        self._transporte = transporte

    def razonar(self, contexto: ContextoRazonamiento) -> HipotesisIA:
        if not self._api_key:
            raise CredencialOpenRouterAusente("No hay OPENROUTER_API_KEY configurada en este entorno.")
        if not self._modelo.endswith(":free"):
            raise CostoOpenRouterNoCero("El benchmark sólo permite slugs OpenRouter con sufijo :free.")

        cuerpo = json.dumps({
            "model": self._modelo,
            "messages": [
                {"role": "system", "content": POLITICA_PROMPT_SISTEMA},
                {"role": "user", "content": _mensaje_usuario(contexto)},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "hipotesis_atlas", "strict": True, "schema": _ESQUEMA_HIPOTESIS},
            },
            "provider": {
                "require_parameters": True,
                "max_price": {"prompt": 0, "completion": 0},
            },
            "include_reasoning": False,
            "temperature": 0,
            "max_tokens": 1400,
        }, ensure_ascii=False).encode("utf-8")
        solicitud = Request(_URL_COMPLETIONS, data=cuerpo, method="POST")
        solicitud.add_header("authorization", f"Bearer {self._api_key}")
        solicitud.add_header("content-type", "application/json")

        inicio = time.perf_counter()
        try:
            respuesta = self._transporte(solicitud, self._timeout)
        except HTTPError as error:
            detalle = _detalle_error_seguro(error, self._api_key)
            raise ProveedorOpenRouterNoDisponible(
                f"OpenRouter devolvió HTTP {error.code}" + (f": {detalle}" if detalle else ".")
            ) from error
        except (TimeoutError, socket.timeout) as error:
            raise ProveedorOpenRouterNoDisponible("Tiempo de espera agotado consultando OpenRouter.") from error
        except (URLError, OSError) as error:
            raise ProveedorOpenRouterNoDisponible("Sin conexión con OpenRouter.") from error
        latencia = time.perf_counter() - inicio

        if not 200 <= respuesta.estado < 300:
            raise ProveedorOpenRouterNoDisponible(f"OpenRouter devolvió HTTP {respuesta.estado}.")
        try:
            datos = json.loads(respuesta.cuerpo)
        except json.JSONDecodeError as error:
            raise ProveedorOpenRouterNoDisponible("Respuesta HTTP de OpenRouter no es JSON válido.") from error

        uso = dict(datos.get("usage") or {}) if isinstance(datos, dict) else {}
        try:
            costo = Decimal(str(uso.get("cost", "0") or "0"))
        except InvalidOperation as error:
            raise ProveedorOpenRouterNoDisponible("OpenRouter devolvió un costo no interpretable.") from error
        if costo != 0:
            raise CostoOpenRouterNoCero(f"OpenRouter reportó costo distinto de cero: USD {costo}.")

        try:
            contenido = datos["choices"][0]["message"]["content"]
            entrada = json.loads(contenido)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise ProveedorOpenRouterNoDisponible("Respuesta OpenRouter no contiene JSON estructurado válido.") from error

        metadata = {
            "openrouter": {
                "id": datos.get("id", ""),
                "modelo_servido": datos.get("model", ""),
                "provider": datos.get("provider", ""),
                "latencia_segundos": round(latencia, 3),
                "usage": uso,
                "finish_reason": datos.get("choices", [{}])[0].get("finish_reason", ""),
            }
        }
        return _hipotesis_desde_entrada(entrada, contexto, modelo=self._modelo, metadata=metadata)
