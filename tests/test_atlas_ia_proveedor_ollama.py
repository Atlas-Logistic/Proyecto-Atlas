from __future__ import annotations

import json
import socket
from urllib.error import URLError

import pytest

from atlas_core.atlas_ia.contratos import ContextoRazonamiento, EvidenciaIA
from atlas_core.atlas_ia.proveedor_ollama import (
    ProveedorModeloIAOllama,
    ProveedorOllamaNoDisponible,
    RespuestaHTTP,
)


def _contexto() -> ContextoRazonamiento:
    return ContextoRazonamiento(
        campo="patente_tracto", valor_documental="VP6521", rut_chofer="15.489.424-1",
        numero_guia="464265", numero_transporte="T-1",
        evidencias=(EvidenciaIA(
            identificador="veh-1", campo="patente_tracto", valor="VP8521",
            tipo_fuente="HISTORICO", nivel="DOCUMENTAL_INDEPENDIENTE", independencia=1,
            referencias_fuente=("guia=2;transporte=T-2;relacion=TRANSPORTE_INDEPENDIENTE",),
        ),),
        resultado_motor="SUGERENCIA_HUMANA", explicacion_motor="evidencia real",
    )


def _respuesta(entrada: dict | None = None) -> dict:
    entrada = entrada or {
        "resultado": "PROPUESTA", "valor_propuesto": "VP8521",
        "evidencia_usada": ["veh-1"], "evidencia_en_contra": ["OCR_ACTUAL_DIFIERE"],
        "explicacion": "inferencia local", "herramienta_faltante": "",
        "posible_incidencia_documental": True, "confianza_declarada": 0.6,
    }
    return {
        "message": {"role": "assistant", "content": json.dumps(entrada), "thinking": "privado"},
        "done": True, "total_duration": 2_000_000_000, "prompt_eval_count": 100,
        "eval_count": 30, "eval_duration": 1_000_000_000,
    }


def _transporte(datos: dict, capturas: list | None = None):
    def transportar(solicitud, timeout):
        if capturas is not None:
            capturas.append((solicitud, timeout))
        return RespuestaHTTP(200, json.dumps(datos).encode("utf-8"))
    return transportar


def test_request_local_usa_schema_thinking_separado_y_no_credenciales(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "NO-DEBE-USARSE")
    capturas = []
    proveedor = ProveedorModeloIAOllama(transporte=_transporte(_respuesta(), capturas))
    proveedor.razonar(_contexto())
    solicitud, timeout = capturas[0]
    cuerpo = json.loads(solicitud.data)
    assert solicitud.full_url == "http://localhost:11434/api/chat"
    assert timeout == 300.0
    assert cuerpo["model"] == "qwen3:4b"
    assert cuerpo["stream"] is False and cuerpo["think"] is False
    assert cuerpo["format"]["properties"]["resultado"]["enum"] == [
        "PROPUESTA", "ABSTENCION", "REQUIERE_HERRAMIENTA",
    ]
    assert solicitud.get_header("Authorization") is None
    assert solicitud.get_header("X-api-key") is None
    assert "NO-DEBE-USARSE" not in solicitud.data.decode("utf-8")


def test_respuesta_estructurada_se_normaliza_sin_persistir_thinking():
    hipotesis = ProveedorModeloIAOllama(transporte=_transporte(_respuesta())).razonar(_contexto())
    assert hipotesis.resultado == "PROPUESTA"
    assert hipotesis.valor_propuesto == "VP8521"
    assert hipotesis.proveedor == "ollama" and hipotesis.modelo == "qwen3:4b"
    assert hipotesis.metadata["confianza_declarada"] == 0.6
    assert hipotesis.metadata["ollama"]["total_duration"] == 2_000_000_000
    assert "thinking" not in json.dumps(hipotesis.a_dict())


def test_abstencion_y_requiere_herramienta_se_normalizan():
    for resultado, herramienta in (("ABSTENCION", ""), ("REQUIERE_HERRAMIENTA", "HISTORIAL")):
        entrada = {
            "resultado": resultado, "valor_propuesto": "", "evidencia_usada": [],
            "evidencia_en_contra": [], "explicacion": "sin evidencia",
            "herramienta_faltante": herramienta, "posible_incidencia_documental": False,
            "confianza_declarada": 0.1,
        }
        hipotesis = ProveedorModeloIAOllama(transporte=_transporte(_respuesta(entrada))).razonar(_contexto())
        assert hipotesis.resultado == resultado
        assert hipotesis.herramienta_faltante == herramienta


@pytest.mark.parametrize("error", [socket.timeout(), URLError("sin servicio")])
def test_timeout_y_ollama_no_disponible(error):
    def fallar(*_):
        raise error
    proveedor = ProveedorModeloIAOllama(transporte=fallar)
    with pytest.raises(ProveedorOllamaNoDisponible):
        proveedor.razonar(_contexto())


@pytest.mark.parametrize("datos", [b"no-json", b'{"message":{"content":"no-json"}}'])
def test_json_invalido(datos):
    proveedor = ProveedorModeloIAOllama(transporte=lambda *_: RespuestaHTTP(200, datos))
    with pytest.raises(ProveedorOllamaNoDisponible):
        proveedor.razonar(_contexto())


def test_resultado_fuera_de_contrato_degrada_a_abstencion_auditable():
    entrada = {
        "resultado": "SUGERENCIA_HUMANA", "valor_propuesto": "VP8521",
        "evidencia_usada": [], "evidencia_en_contra": [], "explicacion": "inválida",
        "herramienta_faltante": "", "posible_incidencia_documental": False,
        "confianza_declarada": 0.2,
    }
    hipotesis = ProveedorModeloIAOllama(transporte=_transporte(_respuesta(entrada))).razonar(_contexto())
    assert hipotesis.resultado == "ABSTENCION"
    assert hipotesis.metadata["respuesta_invalida"] is True


def test_proveedor_no_accede_a_drive(monkeypatch):
    from pathlib import Path

    def prohibido(*_args, **_kwargs):
        raise AssertionError("el proveedor no debe leer Drive")

    monkeypatch.setattr(Path, "open", prohibido)
    hipotesis = ProveedorModeloIAOllama(transporte=_transporte(_respuesta())).razonar(_contexto())
    assert hipotesis.resultado == "PROPUESTA"
