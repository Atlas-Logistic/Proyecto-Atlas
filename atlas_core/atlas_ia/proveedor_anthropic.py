"""Proveedor real de razonamiento -- Anthropic (Claude), vía HTTP directo,
sin SDK -- Bloque A2.

Mismo patrón ya usado en producción por
`atlas_core.rutas.openrouteservice.OpenRouteService` y
`atlas_core.telemetria.proveedores.onelogis.OnelogisProvider`: transporte
HTTP inyectable (`TransporteHTTP`, nunca red real en la suite de tests),
credencial leída de variable de entorno o parámetro explícito, nunca
impresa ni registrada en ningún log/excepción.

Implementa el mismo `Protocol`
`atlas_core.atlas_ia.proveedor.ProveedorModeloIA`.
Atlas IA no conoce ni depende de Anthropic específicamente.

Salida estructurada forzada vía tool-use (`tool_choice`) -- nunca se
parsea prosa libre. Genérico por diseño: el campo y la evidencia vienen
del `ContextoRazonamiento` recibido.
"""

from __future__ import annotations

import json
import os
import re
import socket
from dataclasses import dataclass
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from atlas_core.atlas_ia.contratos import (
    ContextoRazonamiento,
    HipotesisIA,
    RESULTADO_HIPOTESIS_ABSTENCION,
    RESULTADOS_HIPOTESIS,
    calcular_hipotesis_id,
)
from atlas_core.atlas_ia.politica_prompt import (
    POLITICA_PROMPT_SISTEMA,
    POLITICA_PROMPT_VERSION,
)


class ErrorProveedorModeloIA(RuntimeError):
    """Error base -- ningún subtipo incluye la credencial en su mensaje."""


class CredencialProveedorIAAusente(ErrorProveedorModeloIA):
    """No hay credencial configurada."""


class ProveedorIANoDisponible(ErrorProveedorModeloIA):
    """Fallo de red, proveedor o respuesta."""


@dataclass(frozen=True)
class RespuestaHTTP:
    estado: int
    cuerpo: bytes


TransporteHTTP = Callable[[Request, float], RespuestaHTTP]


def _transporte_urllib(
    solicitud: Request,
    timeout: float,
) -> RespuestaHTTP:
    with urlopen(solicitud, timeout=timeout) as respuesta:  # nosec: B310
        return RespuestaHTTP(respuesta.status, respuesta.read())


_URL_MENSAJES = "https://api.anthropic.com/v1/messages"
_VERSION_API_ANTHROPIC = "2023-06-01"
_NOMBRE_HERRAMIENTA = "reportar_hipotesis"
_CLAVES_SECRETAS = frozenset({"api_key", "x-api-key", "authorization", "cookie", "set-cookie"})


_HERRAMIENTA_HIPOTESIS = {
    "name": _NOMBRE_HERRAMIENTA,
    "description": (
        "Reporta la conclusión estructurada de razonar sobre la evidencia "
        "entregada. Uso obligatorio: toda respuesta debe llegar exclusivamente "
        "a través de esta herramienta."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "resultado": {
                "type": "string",
                "enum": list(RESULTADOS_HIPOTESIS),
                "description": (
                    "Conclusión propia obligatoria. Use exclusivamente uno de los valores del enum; "
                    "nunca copie resultado_previo_del_motor_deterministico. "
                    "PROPUESTA si hay un valor concreto respaldado por evidencia; "
                    "ABSTENCION si la evidencia no alcanza; "
                    "REQUIERE_HERRAMIENTA si falta una consulta concreta."
                ),
            },
            "valor_propuesto": {
                "type": "string",
                "description": (
                    "Obligatorio si resultado=PROPUESTA. Debe aparecer "
                    "literalmente como 'valor' de alguna evidencia entregada."
                ),
            },
            "evidencia_usada": {
                "type": "array",
                "items": {"type": "string"},
            },
            "evidencia_en_contra": {
                "type": "array",
                "items": {"type": "string"},
            },
            "explicacion": {
                "type": "string",
                "description": (
                    "Explicación breve en español, en lenguaje humano."
                ),
            },
            "herramienta_faltante": {
                "type": "string",
                "description": (
                    "Obligatorio si resultado=REQUIERE_HERRAMIENTA. "
                    "Qué evidencia o consulta adicional haría falta."
                ),
            },
            "posible_incidencia_documental": {
                "type": "boolean",
            },
            "confianza_declarada": {
                "type": "number",
                "description": (
                    "Estimación de confianza entre 0 y 1. Se registra sólo como "
                    "metadato de auditoría y nunca decide autonomía por sí sola."
                ),
            },
        },
        "required": [
            "resultado",
            "explicacion",
        ],
    },
}


def _detalle_http_saneado(error: HTTPError, *, api_key: str) -> str:
    """Extrae un detalle útil sin exponer credenciales ni headers."""
    try:
        texto = error.read().decode("utf-8", errors="replace")
    except Exception:
        return ""

    try:
        datos = json.loads(texto)

        def sanear(valor: object) -> object:
            if isinstance(valor, dict):
                return {
                    clave: "[REDACTADO]" if str(clave).lower() in _CLAVES_SECRETAS else sanear(contenido)
                    for clave, contenido in valor.items()
                }
            if isinstance(valor, list):
                return [sanear(elemento) for elemento in valor]
            return valor

        texto = json.dumps(sanear(datos), ensure_ascii=False)
    except json.JSONDecodeError:
        texto = re.sub(
            r"(?i)(api[_-]?key|x-api-key|authorization|cookie)\s*[:=]\s*\S+",
            r"\1=[REDACTADO]",
            texto,
        )

    if api_key:
        texto = texto.replace(api_key, "[REDACTADO]")
    return texto[:4000] + ("...[truncado]" if len(texto) > 4000 else "")


def _mensaje_usuario_desde_contexto(
    contexto: ContextoRazonamiento,
) -> str:
    """Construye el mensaje usando sólo evidencia ya reunida por Atlas."""

    return json.dumps(
        {
            "campo": contexto.campo,
            "valor_documental_observado": contexto.valor_documental,
            "contexto_operacional": {
                "rut_chofer": contexto.rut_chofer,
                "numero_guia": contexto.numero_guia,
                "numero_transporte": contexto.numero_transporte,
            },
            "evidencia_disponible": [
                evidencia.a_dict()
                for evidencia in contexto.evidencias
            ],
            "resultado_previo_del_motor_deterministico": (
                contexto.resultado_motor
            ),
            "explicacion_previa_del_motor_deterministico": (
                contexto.explicacion_motor
            ),
            "identidad_documento": contexto.identidad_documento,
            "identidad_operacional": dict(contexto.identidad_operacional),
            "herramientas_disponibles": list(contexto.herramientas_disponibles),
            "restricciones_dominio": list(contexto.restricciones_dominio),
        },
        ensure_ascii=False,
        indent=2,
    )


def _hipotesis_abstencion_por_respuesta_invalida(
    contexto: ContextoRazonamiento,
    *,
    modelo: str,
    motivo: str,
) -> HipotesisIA:
    """Degrada respuestas inválidas del proveedor a abstención segura."""

    return HipotesisIA(
        hipotesis_id=calcular_hipotesis_id(contexto, ""),
        campo=contexto.campo,
        valor_observado=contexto.valor_documental,
        valor_propuesto="",
        resultado=RESULTADO_HIPOTESIS_ABSTENCION,
        explicacion=(
            "Respuesta del proveedor descartada por estructura inválida: "
            f"{motivo}"
        ),
        proveedor="anthropic",
        modelo=modelo,
    )


def _hipotesis_desde_respuesta(
    datos: dict[str, object],
    contexto: ContextoRazonamiento,
    *,
    modelo: str,
) -> HipotesisIA:
    bloques_tool_use = [
        bloque
        for bloque in (datos.get("content") or [])
        if isinstance(bloque, dict)
        and bloque.get("type") == "tool_use"
    ]

    if not bloques_tool_use:
        raise ProveedorIANoDisponible(
            "La respuesta no contiene una llamada a la herramienta esperada."
        )

    entrada = bloques_tool_use[0].get("input") or {}

    if not isinstance(entrada, dict):
        return _hipotesis_abstencion_por_respuesta_invalida(
            contexto,
            modelo=modelo,
            motivo="input de tool_use no es un objeto",
        )

    resultado = str(
        entrada.get("resultado", "")
    ).strip()

    if resultado not in RESULTADOS_HIPOTESIS:
        return _hipotesis_abstencion_por_respuesta_invalida(
            contexto,
            modelo=modelo,
            motivo=f"resultado desconocido {resultado!r}",
        )

    valor_propuesto = (
        str(
            entrada.get("valor_propuesto", "")
        ).strip()
        if resultado == "PROPUESTA"
        else ""
    )

    herramienta_faltante = (
        str(
            entrada.get("herramienta_faltante", "")
        ).strip()
        if resultado == "REQUIERE_HERRAMIENTA"
        else ""
    )

    metadata: dict[str, object] = {}

    if "confianza_declarada" in entrada:
        metadata["confianza_declarada"] = (
            entrada["confianza_declarada"]
        )

    if entrada.get("posible_incidencia_documental"):
        metadata["posible_incidencia_documental"] = True

    if datos.get("usage"):
        metadata["usage"] = datos["usage"]

    metadata["politica_prompt_version"] = (
        POLITICA_PROMPT_VERSION
    )

    try:
        return HipotesisIA(
            hipotesis_id=calcular_hipotesis_id(
                contexto,
                valor_propuesto,
            ),
            campo=contexto.campo,
            valor_observado=contexto.valor_documental,
            valor_propuesto=valor_propuesto,
            resultado=resultado,
            evidencia_usada=tuple(
                entrada.get("evidencia_usada") or ()
            ),
            evidencia_en_contra=tuple(
                entrada.get("evidencia_en_contra") or ()
            ),
            explicacion=str(
                entrada.get("explicacion", "")
            ),
            herramienta_faltante=herramienta_faltante,
            proveedor="anthropic",
            modelo=modelo,
            metadata=metadata,
        )

    except ValueError as error:
        return _hipotesis_abstencion_por_respuesta_invalida(
            contexto,
            modelo=modelo,
            motivo=str(error),
        )


class ProveedorModeloIAAnthropic:
    """Proveedor Claude real para Atlas IA."""

    nombre = "anthropic"

    def __init__(
        self,
        *,
        modelo: str = "claude-sonnet-5",
        api_key: str | None = None,
        timeout: float = 30.0,
        transporte: TransporteHTTP = _transporte_urllib,
        max_tokens: int = 1024,
    ) -> None:
        self._api_key = (
            api_key
            if api_key is not None
            else os.getenv("ANTHROPIC_API_KEY", "")
        ).strip()

        self._modelo = modelo
        self._timeout = timeout
        self._transporte = transporte
        self._max_tokens = max_tokens

    def razonar(
        self,
        contexto: ContextoRazonamiento,
    ) -> HipotesisIA:
        if not self._api_key:
            raise CredencialProveedorIAAusente(
                "No hay ANTHROPIC_API_KEY configurada en este entorno."
            )

        cuerpo = json.dumps(
            {
                "model": self._modelo,
                "max_tokens": self._max_tokens,
                "system": POLITICA_PROMPT_SISTEMA,
                "tools": [
                    _HERRAMIENTA_HIPOTESIS
                ],
                "tool_choice": {
                    "type": "tool",
                    "name": _NOMBRE_HERRAMIENTA,
                },
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            _mensaje_usuario_desde_contexto(
                                contexto
                            )
                        ),
                    }
                ],
            }
        ).encode("utf-8")

        solicitud = Request(
            _URL_MENSAJES,
            data=cuerpo,
            method="POST",
        )

        solicitud.add_header(
            "x-api-key",
            self._api_key,
        )
        solicitud.add_header(
            "anthropic-version",
            _VERSION_API_ANTHROPIC,
        )
        solicitud.add_header(
            "content-type",
            "application/json",
        )

        try:
            respuesta = self._transporte(
                solicitud,
                self._timeout,
            )

        except HTTPError as error:
            detalle = _detalle_http_saneado(error, api_key=self._api_key)

            raise ProveedorIANoDisponible(
                f"Anthropic devolvió HTTP {error.code}"
                + (f": {detalle}" if detalle else ".")
            ) from error

        except (
            TimeoutError,
            socket.timeout,
        ) as error:
            raise ProveedorIANoDisponible(
                "Tiempo de espera agotado consultando Anthropic."
            ) from error

        except (
            URLError,
            OSError,
        ) as error:
            raise ProveedorIANoDisponible(
                "Sin conexión con Anthropic."
            ) from error

        if not 200 <= respuesta.estado < 300:
            raise ProveedorIANoDisponible(
                f"Anthropic devolvió HTTP {respuesta.estado}."
            )

        try:
            datos = json.loads(
                respuesta.cuerpo
            )
        except json.JSONDecodeError as error:
            raise ProveedorIANoDisponible(
                "Respuesta de Anthropic no es JSON válido."
            ) from error

        return _hipotesis_desde_respuesta(
            datos,
            contexto,
            modelo=self._modelo,
        )
