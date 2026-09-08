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
    PresupuestoGroqExcedido,
    ProveedorGroqNoDisponible,
    ProveedorModeloIAGroq,
    RespuestaHTTP,
    _estimar_tokens_conservador,
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


def test_rate_limit_reintenta_una_vez_respetando_espera():
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

    hipotesis = ProveedorModeloIAGroq(
        api_key=CLAVE_PRUEBA, transporte=transportar, dormir=esperas.append,
    ).razonar(_contexto())
    assert hipotesis.resultado == "PROPUESTA"
    assert len(llamadas) == 2 and esperas == [2.0]


def test_payload_sobredimensionado_se_compacta_antes_del_request():
    capturas = []
    evidencias = tuple(
        EvidenciaIA(
            identificador=f"baja-{indice}", campo="patente_tracto", valor="x" * 320,
            tipo_fuente="HISTORICO", nivel="GPS_CANDIDATO", independencia=0,
        )
        for indice in range(80)
    )
    contexto = _contexto().__class__(**{**_contexto().__dict__, "evidencias": evidencias})
    ProveedorModeloIAGroq(api_key=CLAVE_PRUEBA, transporte=_transporte(_respuesta(), capturas)).razonar(contexto)
    cuerpo = capturas[0][0].data
    enviado = json.loads(cuerpo)["messages"][1]["content"]
    assert _estimar_tokens_conservador(cuerpo) <= 6_200
    assert len(json.loads(enviado)["evidencia_disponible"]) < len(evidencias)


def test_compactacion_conserva_evidencia_prioritaria_y_contradiccion():
    alta = EvidenciaIA(
        identificador="catalogo-confirmado", campo="destino", valor="MARURI 1942 RENCA",
        tipo_fuente="CATALOGO", nivel="CATALOGO_CONFIRMADO", independencia=2,
    )
    contradiccion = EvidenciaIA(
        identificador="ocr-difiere", campo="destino", valor="MARURI 1942 RENCA",
        tipo_fuente="DOCUMENTAL", nivel="GPS_CANDIDATO", en_contra=("OCR: MARURI 1942 QUILICURA",),
    )
    relleno = tuple(
        EvidenciaIA(
            identificador=f"baja-{indice}", campo="destino", valor="z" * 320,
            tipo_fuente="HISTORICO", nivel="GPS_CANDIDATO",
        ) for indice in range(80)
    )
    contexto = _contexto().__class__(**{**_contexto().__dict__, "evidencias": (alta, contradiccion, *relleno)})
    capturas = []
    ProveedorModeloIAGroq(api_key=CLAVE_PRUEBA, transporte=_transporte(_respuesta(), capturas)).razonar(contexto)
    evidencias_enviadas = json.loads(json.loads(capturas[0][0].data)["messages"][1]["content"])["evidencia_disponible"]
    assert {"catalogo-confirmado", "ocr-difiere"} <= {e["identificador"] for e in evidencias_enviadas}
    assert evidencias_enviadas[0]["identificador"] == "catalogo-confirmado"
    ocr = next(e for e in evidencias_enviadas if e["identificador"] == "ocr-difiere")
    assert ocr["en_contra"] == ["OCR: MARURI 1942 QUILICURA"]


def test_payload_imposible_no_se_envia():
    llamadas = []
    critica_gigante = EvidenciaIA(
        identificador="contradiccion-gigante", campo="destino", valor="A",
        tipo_fuente="DOCUMENTAL", nivel="DOCUMENTAL_INDEPENDIENTE", en_contra=("x" * 30_000,),
    )
    contexto = _contexto().__class__(**{**_contexto().__dict__, "evidencias": (critica_gigante,)})
    with pytest.raises(PresupuestoGroqExcedido, match="no se envió"):
        ProveedorModeloIAGroq(api_key=CLAVE_PRUEBA, transporte=lambda *_: llamadas.append(True)).razonar(contexto)
    assert llamadas == []


def test_429_largo_no_reintenta_ni_espera_y_activa_cooldown():
    llamadas = []
    esperas = []

    def transportar(*_):
        llamadas.append(True)
        cuerpo = json.dumps({"error": {"message": "Please try again in 60s."}}).encode()
        raise HTTPError("url", 429, "rate", {}, BytesIO(cuerpo))

    proveedor = ProveedorModeloIAGroq(
        api_key=CLAVE_PRUEBA, transporte=transportar, dormir=esperas.append, reloj_monotono=lambda: 100.0,
    )
    with pytest.raises(ProveedorGroqNoDisponible):
        proveedor.razonar(_contexto())
    with pytest.raises(ProveedorGroqNoDisponible, match="no se envió"):
        proveedor.razonar(_contexto())
    assert len(llamadas) == 1 and esperas == []


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
