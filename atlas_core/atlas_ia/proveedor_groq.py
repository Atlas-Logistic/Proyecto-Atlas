"""Proveedor remoto Groq para Atlas IA mediante Chat Completions."""

from __future__ import annotations

import json
import os
import re
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


class CredencialGroqAusente(ErrorProveedorModeloIA):
    """No existe GROQ_API_KEY en el entorno."""


class ProveedorGroqNoDisponible(ErrorProveedorModeloIA):
    """Groq no responde o devuelve una respuesta inválida."""


class CostoGroqNoCero(ErrorProveedorModeloIA):
    """Groq reportó un costo distinto de cero y el lote debe detenerse."""


@dataclass(frozen=True)
class RespuestaHTTP:
    estado: int
    cuerpo: bytes


TransporteHTTP = Callable[[Request, float], RespuestaHTTP]


def _transporte_urllib(solicitud: Request, timeout: float) -> RespuestaHTTP:
    with urlopen(solicitud, timeout=timeout) as respuesta:  # nosec: B310 - endpoint fijo HTTPS
        return RespuestaHTTP(respuesta.status, respuesta.read())


_URL_COMPLETIONS = "https://api.groq.com/openai/v1/chat/completions"
_MODELO = "openai/gpt-oss-120b"
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
        "identidad_documento": contexto.identidad_documento,
        "identidad_operacional": dict(contexto.identidad_operacional),
        "herramientas_disponibles": list(contexto.herramientas_disponibles),
        "restricciones_dominio": list(contexto.restricciones_dominio),
    }, ensure_ascii=False, indent=2)


def _detalle_error_seguro(error: HTTPError) -> str:
    try:
        datos = json.loads(error.read().decode("utf-8", errors="replace"))
        detalle = datos.get("error") or {}
        mensaje = str(detalle.get("message", ""))
        if error.code == 429:
            espera = re.search(r"try again in (\d+(?:\.\d+)?)s", mensaje, flags=re.IGNORECASE)
            mensaje = "rate limit reached" + (
                f"; retry_after_seconds={espera.group(1)}" if espera else ""
            )
        seguro = {
            clave: valor for clave, valor in {
                "message": mensaje, "type": detalle.get("type"), "code": detalle.get("code"),
            }.items() if valor
        }
        return json.dumps(seguro, ensure_ascii=False)
    except Exception:
        return ""


def _abstencion_invalida(contexto: ContextoRazonamiento, modelo: str, motivo: str) -> HipotesisIA:
    return HipotesisIA(
        hipotesis_id=calcular_hipotesis_id(contexto, ""),
        campo=contexto.campo,
        valor_observado=contexto.valor_documental,
        valor_propuesto="",
        resultado=RESULTADO_HIPOTESIS_ABSTENCION,
        explicacion=f"Respuesta Groq descartada por estructura inválida: {motivo}",
        proveedor="groq",
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
            proveedor="groq",
            modelo=modelo,
            metadata=metadata,
        )
    except (TypeError, ValueError) as error:
        return _abstencion_invalida(contexto, modelo, str(error))


class ProveedorModeloIAGroq:
    """Razonador Atlas sobre Groq, sin SDK y con salida JSON estricta."""

    nombre = "groq"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        modelo: str = _MODELO,
        timeout: float = 180.0,
        transporte: TransporteHTTP = _transporte_urllib,
    ) -> None:
        self._api_key = (api_key if api_key is not None else os.getenv("GROQ_API_KEY", "")).strip()
        self._modelo = modelo
        self._timeout = timeout
        self._transporte = transporte

    def razonar(self, contexto: ContextoRazonamiento) -> HipotesisIA:
        if not self._api_key:
            raise CredencialGroqAusente("No hay GROQ_API_KEY configurada en este entorno.")
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
            "include_reasoning": False,
            "reasoning_effort": "medium",
            "temperature": 0,
            "max_completion_tokens": 1800,
        }, ensure_ascii=False).encode("utf-8")
        solicitud = Request(_URL_COMPLETIONS, data=cuerpo, method="POST")
        solicitud.add_header("authorization", f"Bearer {self._api_key}")
        solicitud.add_header("content-type", "application/json")
        solicitud.add_header("user-agent", "Atlas-IA/1.0")

        inicio = time.perf_counter()
        respuesta = None
        for intento in range(3):
            try:
                respuesta = self._transporte(solicitud, self._timeout)
                break
            except HTTPError as error:
                detalle = _detalle_error_seguro(error)
                espera = re.search(r"retry_after_seconds=(\d+(?:\.\d+)?)", detalle)
                if error.code == 429 and intento < 2 and espera:
                    time.sleep(min(float(espera.group(1)) + 1, 60.0))
                    continue
                raise ProveedorGroqNoDisponible(
                    f"Groq devolvió HTTP {error.code}" + (f": {detalle}" if detalle else ".")
                ) from error
            except (TimeoutError, socket.timeout) as error:
                raise ProveedorGroqNoDisponible("Tiempo de espera agotado consultando Groq.") from error
            except (URLError, OSError) as error:
                raise ProveedorGroqNoDisponible("Sin conexión con Groq.") from error
        if respuesta is None:  # defensa; el bucle siempre retorna o lanza antes
            raise ProveedorGroqNoDisponible("Groq no devolvió respuesta.")
        latencia = time.perf_counter() - inicio

        if not 200 <= respuesta.estado < 300:
            raise ProveedorGroqNoDisponible(f"Groq devolvió HTTP {respuesta.estado}.")
        try:
            datos = json.loads(respuesta.cuerpo)
        except json.JSONDecodeError as error:
            raise ProveedorGroqNoDisponible("Respuesta HTTP de Groq no es JSON válido.") from error

        uso = dict(datos.get("usage") or {}) if isinstance(datos, dict) else {}
        costo_reportado = uso.get("cost", datos.get("cost") if isinstance(datos, dict) else None)
        if costo_reportado is not None:
            try:
                costo = Decimal(str(costo_reportado or "0"))
            except InvalidOperation as error:
                raise ProveedorGroqNoDisponible("Groq devolvió un costo no interpretable.") from error
            if costo != 0:
                raise CostoGroqNoCero(f"Groq reportó costo distinto de cero: USD {costo}.")

        try:
            eleccion = datos["choices"][0]
            entrada = json.loads(eleccion["message"]["content"])
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise ProveedorGroqNoDisponible("Respuesta Groq no contiene JSON estructurado válido.") from error
        metadata = {
            "groq": {
                "id": datos.get("id", ""), "modelo_servido": datos.get("model", ""),
                "latencia_segundos": round(latencia, 3), "usage": uso,
                "costo_reportado": costo_reportado, "service_tier": datos.get("service_tier"),
                "finish_reason": eleccion.get("finish_reason", ""),
                "x_groq": datos.get("x_groq", {}),
            }
        }
        return _hipotesis_desde_entrada(entrada, contexto, modelo=self._modelo, metadata=metadata)
