"""Proveedor local Ollama para Atlas IA.

Usa exclusivamente la API HTTP local de Ollama, sin API key, cloud ni
dependencias externas. La respuesta se fuerza mediante JSON Schema y el
thinking separado por Ollama nunca se persiste en ``HipotesisIA``.
"""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
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
from atlas_core.atlas_ia.politica_prompt import (
    POLITICA_PROMPT_SISTEMA,
    POLITICA_PROMPT_VERSION,
)
from atlas_core.atlas_ia.proveedor_anthropic import ErrorProveedorModeloIA


class ProveedorOllamaNoDisponible(ErrorProveedorModeloIA):
    """Ollama local no responde o devuelve una respuesta inválida."""


@dataclass(frozen=True)
class RespuestaHTTP:
    estado: int
    cuerpo: bytes


TransporteHTTP = Callable[[Request, float], RespuestaHTTP]


def _transporte_urllib(solicitud: Request, timeout: float) -> RespuestaHTTP:
    with urlopen(solicitud, timeout=timeout) as respuesta:  # nosec: B310 - URL local configurable
        return RespuestaHTTP(respuesta.status, respuesta.read())


_ESQUEMA_HIPOTESIS = {
    "type": "object",
    "properties": {
        "resultado": {"type": "string", "enum": list(RESULTADOS_HIPOTESIS)},
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
    datos = {
        "instruccion_salida": (
            "Devuelve solamente el objeto JSON del schema. resultado debe ser exclusivamente "
            "PROPUESTA, ABSTENCION o REQUIERE_HERRAMIENTA; nunca copies el resultado previo del motor."
        ),
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
    }
    return json.dumps(datos, ensure_ascii=False, indent=2)


def _abstencion_invalida(contexto: ContextoRazonamiento, modelo: str, motivo: str) -> HipotesisIA:
    return HipotesisIA(
        hipotesis_id=calcular_hipotesis_id(contexto, ""),
        campo=contexto.campo,
        valor_observado=contexto.valor_documental,
        valor_propuesto="",
        resultado=RESULTADO_HIPOTESIS_ABSTENCION,
        explicacion=f"Respuesta local descartada por estructura inválida: {motivo}",
        proveedor="ollama",
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
            proveedor="ollama",
            modelo=modelo,
            metadata=metadata,
        )
    except (TypeError, ValueError) as error:
        return _abstencion_invalida(contexto, modelo, str(error))


class ProveedorModeloIAOllama:
    """Razonador Atlas mediante un modelo servido por Ollama local."""

    nombre = "ollama"

    def __init__(
        self,
        *,
        modelo: str = "qwen3:4b",
        base_url: str = "http://localhost:11434",
        timeout: float = 300.0,
        transporte: TransporteHTTP = _transporte_urllib,
    ) -> None:
        self._modelo = modelo
        self._url = f"{base_url.rstrip('/')}/api/chat"
        self._timeout = timeout
        self._transporte = transporte

    def razonar(self, contexto: ContextoRazonamiento) -> HipotesisIA:
        cuerpo = json.dumps({
            "model": self._modelo,
            "stream": False,
            "think": False,
            "format": _ESQUEMA_HIPOTESIS,
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": POLITICA_PROMPT_SISTEMA},
                {"role": "user", "content": _mensaje_usuario(contexto)},
            ],
        }, ensure_ascii=False).encode("utf-8")
        solicitud = Request(self._url, data=cuerpo, method="POST")
        solicitud.add_header("content-type", "application/json")

        try:
            respuesta = self._transporte(solicitud, self._timeout)
        except HTTPError as error:
            try:
                detalle = error.read().decode("utf-8", errors="replace")[:2000]
            except Exception:
                detalle = ""
            raise ProveedorOllamaNoDisponible(
                f"Ollama devolvió HTTP {error.code}" + (f": {detalle}" if detalle else ".")
            ) from error
        except (TimeoutError, socket.timeout) as error:
            raise ProveedorOllamaNoDisponible("Tiempo de espera agotado consultando Ollama local.") from error
        except (URLError, OSError) as error:
            raise ProveedorOllamaNoDisponible("Ollama local no está disponible en el endpoint configurado.") from error

        if not 200 <= respuesta.estado < 300:
            raise ProveedorOllamaNoDisponible(f"Ollama devolvió HTTP {respuesta.estado}.")
        try:
            datos = json.loads(respuesta.cuerpo)
            contenido = datos["message"]["content"]
            entrada = json.loads(contenido)
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise ProveedorOllamaNoDisponible("Respuesta final de Ollama no contiene JSON estructurado válido.") from error

        metricas = {
            clave: datos[clave]
            for clave in (
                "total_duration", "load_duration", "prompt_eval_count", "prompt_eval_duration",
                "eval_count", "eval_duration", "done_reason",
            )
            if clave in datos
        }
        return _hipotesis_desde_entrada(
            entrada, contexto, modelo=self._modelo, metadata={"ollama": metricas},
        )
