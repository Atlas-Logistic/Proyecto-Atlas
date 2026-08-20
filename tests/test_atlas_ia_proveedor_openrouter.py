from __future__ import annotations

import json
import socket
from io import BytesIO
from urllib.error import HTTPError
from urllib.error import URLError

import pytest

from atlas_core.atlas_ia.contratos import ContextoRazonamiento, EvidenciaIA
from atlas_core.atlas_ia.proveedor_openrouter import (
    CostoOpenRouterNoCero,
    CredencialOpenRouterAusente,
    ProveedorModeloIAOpenRouter,
    ProveedorOpenRouterNoDisponible,
    RespuestaHTTP,
)

CLAVE_PRUEBA = "sk-or-v1-CLAVE-FALSA"


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


def _respuesta(*, costo=0) -> dict:
    return {
        "id": "gen-1", "model": "z-ai/glm-5.2:free", "provider": "InferenceNet",
        "choices": [{"message": {"content": json.dumps(_entrada())}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "cost": costo},
    }


def _transporte(datos: dict, capturas: list | None = None):
    def transportar(solicitud, timeout):
        if capturas is not None:
            capturas.append((solicitud, timeout))
        return RespuestaHTTP(200, json.dumps(datos).encode())
    return transportar


def test_sin_credencial_no_hace_llamada(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    llamadas = []
    with pytest.raises(CredencialOpenRouterAusente):
        ProveedorModeloIAOpenRouter(transporte=lambda *_: llamadas.append(True)).razonar(_contexto())
    assert llamadas == []


def test_request_fuerza_free_schema_y_precio_cero():
    capturas = []
    proveedor = ProveedorModeloIAOpenRouter(api_key=CLAVE_PRUEBA, transporte=_transporte(_respuesta(), capturas))
    proveedor.razonar(_contexto())
    solicitud, _ = capturas[0]
    cuerpo = json.loads(solicitud.data)
    assert cuerpo["model"] == "z-ai/glm-5.2:free"
    assert cuerpo["response_format"]["type"] == "json_schema"
    assert cuerpo["response_format"]["json_schema"]["strict"] is True
    assert cuerpo["provider"] == {"require_parameters": True, "max_price": {"prompt": 0, "completion": 0}}
    assert cuerpo["include_reasoning"] is False
    assert solicitud.get_header("Authorization") == f"Bearer {CLAVE_PRUEBA}"
    assert CLAVE_PRUEBA not in solicitud.data.decode()


def test_respuesta_se_normaliza_y_conserva_uso_sin_credencial():
    hipotesis = ProveedorModeloIAOpenRouter(api_key=CLAVE_PRUEBA, transporte=_transporte(_respuesta())).razonar(_contexto())
    assert hipotesis.resultado == "PROPUESTA" and hipotesis.valor_propuesto == "VP8521"
    assert hipotesis.proveedor == "openrouter"
    assert hipotesis.metadata["openrouter"]["usage"]["cost"] == 0
    assert CLAVE_PRUEBA not in json.dumps(hipotesis.a_dict())


def test_costo_no_cero_detiene_el_proveedor():
    proveedor = ProveedorModeloIAOpenRouter(api_key=CLAVE_PRUEBA, transporte=_transporte(_respuesta(costo=0.001)))
    with pytest.raises(CostoOpenRouterNoCero):
        proveedor.razonar(_contexto())


def test_costo_no_cero_se_detecta_aunque_contenido_sea_invalido():
    datos = _respuesta(costo=0.001)
    datos["choices"][0]["message"]["content"] = "no-json"
    proveedor = ProveedorModeloIAOpenRouter(api_key=CLAVE_PRUEBA, transporte=_transporte(datos))
    with pytest.raises(CostoOpenRouterNoCero):
        proveedor.razonar(_contexto())


def test_slug_no_free_se_rechaza_antes_de_red():
    proveedor = ProveedorModeloIAOpenRouter(api_key=CLAVE_PRUEBA, modelo="z-ai/glm-5.2")
    with pytest.raises(CostoOpenRouterNoCero):
        proveedor.razonar(_contexto())


def test_http_error_sanea_metadatos_y_credencial():
    cuerpo = json.dumps({
        "error": {
            "message": "rate limited", "code": 429,
            "metadata": {"provider_name": "Proveedor", "retry_after_seconds": 5, "headers": {"secret": CLAVE_PRUEBA}},
        },
        "user_id": "identificador-privado",
    }).encode()

    def fallar(*_):
        raise HTTPError("url", 429, "rate limit", {}, BytesIO(cuerpo))

    with pytest.raises(ProveedorOpenRouterNoDisponible) as excinfo:
        ProveedorModeloIAOpenRouter(api_key=CLAVE_PRUEBA, transporte=fallar).razonar(_contexto())
    mensaje = str(excinfo.value)
    assert "rate limited" in mensaje and "retry_after_seconds" in mensaje
    assert CLAVE_PRUEBA not in mensaje and "identificador-privado" not in mensaje


@pytest.mark.parametrize("error", [socket.timeout(), URLError("sin red")])
def test_timeout_y_conexion(error):
    def fallar(*_):
        raise error
    with pytest.raises(ProveedorOpenRouterNoDisponible):
        ProveedorModeloIAOpenRouter(api_key=CLAVE_PRUEBA, transporte=fallar).razonar(_contexto())


@pytest.mark.parametrize("cuerpo", [b"no-json", b'{"choices":[{"message":{"content":"no-json"}}]}'])
def test_json_invalido(cuerpo):
    proveedor = ProveedorModeloIAOpenRouter(
        api_key=CLAVE_PRUEBA, transporte=lambda *_: RespuestaHTTP(200, cuerpo),
    )
    with pytest.raises(ProveedorOpenRouterNoDisponible):
        proveedor.razonar(_contexto())
