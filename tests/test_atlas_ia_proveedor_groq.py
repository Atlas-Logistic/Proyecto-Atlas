from __future__ import annotations

import json
import socket
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from atlas_core.atlas_ia.contratos import ContextoRazonamiento, EvidenciaIA
from atlas_core.atlas_ia.proveedor_groq import (
    CostoGroqNoCero,
    CredencialGroqAusente,
    ProveedorGroqNoDisponible,
    ProveedorModeloIAGroq,
    RespuestaHTTP,
)

CLAVE_PRUEBA = "gsk_CLAVE_FALSA"


def _contexto() -> ContextoRazonamiento:
    return ContextoRazonamiento(
        campo="patente_tracto", valor_documental="VP6521", rut_chofer="15.489.424-1",
        numero_guia="464265", numero_transporte="T-1",
        evidencias=(EvidenciaIA(
            identificador="veh-1", campo="patente_tracto", valor="VP8521",
            tipo_fuente="HISTORICO", nivel="DOCUMENTAL_INDEPENDIENTE", independencia=1,
        ),), resultado_motor="SUGERENCIA_HUMANA", explicacion_motor="evidencia",
    )


def _entrada() -> dict:
    return {
        "resultado": "PROPUESTA", "valor_propuesto": "VP8521",
        "evidencia_usada": ["veh-1"], "evidencia_en_contra": ["OCR_ACTUAL_DIFIERE"],
        "explicacion": "inferencia", "herramienta_faltante": "",
        "posible_incidencia_documental": True, "confianza_declarada": 0.7,
    }


def _respuesta(*, costo=None) -> dict:
    uso = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
    if costo is not None:
        uso["cost"] = costo
    return {
        "id": "chatcmpl-1", "model": "openai/gpt-oss-120b", "service_tier": "on_demand",
        "choices": [{"message": {"content": json.dumps(_entrada())}, "finish_reason": "stop"}],
        "usage": uso, "x_groq": {"id": "req-1"},
    }


def _transporte(datos: dict, capturas: list | None = None):
    def transportar(solicitud, timeout):
        if capturas is not None:
            capturas.append((solicitud, timeout))
        return RespuestaHTTP(200, json.dumps(datos).encode())
    return transportar


def test_sin_credencial_no_hace_llamada(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    llamadas = []
    with pytest.raises(CredencialGroqAusente):
        ProveedorModeloIAGroq(api_key="", transporte=lambda *_: llamadas.append(True)).razonar(_contexto())
    assert llamadas == []


def test_request_usa_endpoint_modelo_y_schema_strict_completo():
    capturas = []
    proveedor = ProveedorModeloIAGroq(api_key=CLAVE_PRUEBA, transporte=_transporte(_respuesta(), capturas))
    proveedor.razonar(_contexto())
    solicitud, _ = capturas[0]
    cuerpo = json.loads(solicitud.data)
    schema = cuerpo["response_format"]["json_schema"]["schema"]
    assert solicitud.full_url == "https://api.groq.com/openai/v1/chat/completions"
    assert cuerpo["model"] == "openai/gpt-oss-120b"
    assert cuerpo["response_format"]["json_schema"]["strict"] is True
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["additionalProperties"] is False
    assert cuerpo["include_reasoning"] is False and cuerpo["reasoning_effort"] == "medium"
    assert solicitud.get_header("Authorization") == f"Bearer {CLAVE_PRUEBA}"
    assert solicitud.get_header("User-agent") == "Atlas-IA/1.0"
    assert CLAVE_PRUEBA not in solicitud.data.decode()


def test_respuesta_se_normaliza_y_registra_usage_sin_inventar_costo():
    hipotesis = ProveedorModeloIAGroq(api_key=CLAVE_PRUEBA, transporte=_transporte(_respuesta())).razonar(_contexto())
    assert hipotesis.resultado == "PROPUESTA" and hipotesis.valor_propuesto == "VP8521"
    assert hipotesis.proveedor == "groq"
    assert hipotesis.metadata["groq"]["usage"]["total_tokens"] == 150
    assert hipotesis.metadata["groq"]["costo_reportado"] is None
    assert CLAVE_PRUEBA not in json.dumps(hipotesis.a_dict())


def test_costo_no_cero_detiene_antes_de_normalizar():
    datos = _respuesta(costo=0.01)
    datos["choices"][0]["message"]["content"] = "no-json"
    with pytest.raises(CostoGroqNoCero):
        ProveedorModeloIAGroq(api_key=CLAVE_PRUEBA, transporte=_transporte(datos)).razonar(_contexto())


def test_http_error_sanea_body_y_credencial():
    cuerpo = json.dumps({
        "error": {"message": "rate limit", "type": "tokens", "code": "rate_limit", "secret": CLAVE_PRUEBA},
        "user_id": "privado",
    }).encode()

    def fallar(*_):
        raise HTTPError("url", 429, "rate", {}, BytesIO(cuerpo))

    with pytest.raises(ProveedorGroqNoDisponible) as excinfo:
        ProveedorModeloIAGroq(api_key=CLAVE_PRUEBA, transporte=fallar).razonar(_contexto())
    mensaje = str(excinfo.value)
    assert "rate limit" in mensaje
    assert CLAVE_PRUEBA not in mensaje and "privado" not in mensaje


def test_rate_limit_reintenta_respetando_espera(monkeypatch):
    llamadas = []
    esperas = []

    def transportar(*_):
        llamadas.append(True)
        if len(llamadas) == 1:
            cuerpo = json.dumps({
                "error": {
                    "message": "Rate limit for organization org_privada. Please try again in 2s.",
                    "type": "tokens", "code": "rate_limit_exceeded",
                }
            }).encode()
            raise HTTPError("url", 429, "rate", {}, BytesIO(cuerpo))
        return RespuestaHTTP(200, json.dumps(_respuesta()).encode())

    monkeypatch.setattr("atlas_core.atlas_ia.proveedor_groq.time.sleep", esperas.append)
    hipotesis = ProveedorModeloIAGroq(api_key=CLAVE_PRUEBA, transporte=transportar).razonar(_contexto())
    assert hipotesis.resultado == "PROPUESTA"
    assert len(llamadas) == 2 and esperas == [3.0]


@pytest.mark.parametrize("error", [socket.timeout(), URLError("sin red")])
def test_timeout_y_conexion(error):
    def fallar(*_):
        raise error
    with pytest.raises(ProveedorGroqNoDisponible):
        ProveedorModeloIAGroq(api_key=CLAVE_PRUEBA, transporte=fallar).razonar(_contexto())


@pytest.mark.parametrize("cuerpo", [b"no-json", b'{"choices":[{"message":{"content":"no-json"}}]}'])
def test_json_invalido(cuerpo):
    proveedor = ProveedorModeloIAGroq(api_key=CLAVE_PRUEBA, transporte=lambda *_: RespuestaHTTP(200, cuerpo))
    with pytest.raises(ProveedorGroqNoDisponible):
        proveedor.razonar(_contexto())
