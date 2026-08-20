"""Bloque ATLAS IA A2 -- proveedor real Anthropic
(`atlas_core.atlas_ia.proveedor_anthropic`).

Misma convención que `tests/test_rutas_openrouteservice.py`: transporte
HTTP inyectado y determinista, NUNCA red real, NUNCA depende de
`ANTHROPIC_API_KEY` para pasar. Todas las claves usadas aquí son literales
de prueba, nunca una credencial real."""
from __future__ import annotations

import json
import socket
from urllib.error import HTTPError, URLError

import pytest

from atlas_core.atlas_ia.contratos import ContextoRazonamiento, EvidenciaIA
from atlas_core.atlas_ia.proveedor_anthropic import (
    CredencialProveedorIAAusente,
    ProveedorIANoDisponible,
    ProveedorModeloIAAnthropic,
    RespuestaHTTP,
)

CLAVE_DE_PRUEBA = "sk-ant-CLAVE-DE-PRUEBA-NUNCA-REAL"


def _contexto(**overrides) -> ContextoRazonamiento:
    base = dict(
        campo="patente_tracto", valor_documental="XF3662", rut_chofer="18626166-6",
        numero_guia="1", numero_transporte="T-1",
        evidencias=(
            EvidenciaIA(
                identificador="veh-1", campo="patente_tracto", valor="XF3629",
                tipo_fuente="HISTORICO", nivel="DOCUMENTAL_INDEPENDIENTE",
            ),
        ),
        resultado_motor="SUGERENCIA_HUMANA", explicacion_motor="explicación de prueba",
    )
    base.update(overrides)
    return ContextoRazonamiento(**base)


def _respuesta_tool_use(**overrides):
    entrada = {"resultado": "PROPUESTA", "valor_propuesto": "XF3629", "explicacion": "prueba"}
    entrada.update(overrides)
    return {
        "content": [{"type": "tool_use", "name": "reportar_hipotesis", "input": entrada}],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


def transporte_json(datos, estado=200, capturas=None):
    def transportar(solicitud, timeout):
        if capturas is not None:
            capturas.append((solicitud, timeout))
        return RespuestaHTTP(estado, json.dumps(datos).encode("utf-8"))
    return transportar


# ---------------------------------------------------------------------
# Credencial
# ---------------------------------------------------------------------


def test_sin_credencial_no_invoca_transporte_ni_expone_nada(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    llamadas = []
    proveedor = ProveedorModeloIAAnthropic(transporte=lambda *_: llamadas.append(True))
    with pytest.raises(CredencialProveedorIAAusente) as excinfo:
        proveedor.razonar(_contexto())
    assert llamadas == []
    assert "ANTHROPIC_API_KEY" in str(excinfo.value)
    # el mensaje de error nunca debe traer una credencial real -- aquí no
    # hay ninguna configurada, así que no puede haber fuga posible.


def test_credencial_explicita_nunca_se_lee_del_entorno(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "OTRA_CLAVE_DE_ENTORNO")
    capturas = []
    proveedor = ProveedorModeloIAAnthropic(
        api_key=CLAVE_DE_PRUEBA, transporte=transporte_json(_respuesta_tool_use(), capturas=capturas),
    )
    proveedor.razonar(_contexto())
    solicitud, _ = capturas[0]
    assert solicitud.get_header("X-api-key") == CLAVE_DE_PRUEBA


# ---------------------------------------------------------------------
# Solicitud bien formada
# ---------------------------------------------------------------------


def test_solicitud_incluye_politica_de_sistema_y_fuerza_la_herramienta():
    capturas = []
    proveedor = ProveedorModeloIAAnthropic(
        api_key=CLAVE_DE_PRUEBA, transporte=transporte_json(_respuesta_tool_use(), capturas=capturas),
    )
    proveedor.razonar(_contexto())
    solicitud, _ = capturas[0]
    cuerpo = json.loads(solicitud.data)
    assert "Razona únicamente con la evidencia entregada" in cuerpo["system"]
    assert cuerpo["tool_choice"] == {"type": "tool", "name": "reportar_hipotesis"}
    assert cuerpo["temperature"] == 0.0


def test_mensaje_al_modelo_nunca_incluye_ground_truth():
    """El mensaje construido a partir del contexto sólo contiene lo que
    ContextoRazonamiento ya trae -- nunca una clave/campo adicional con
    la respuesta correcta."""
    capturas = []
    proveedor = ProveedorModeloIAAnthropic(
        api_key=CLAVE_DE_PRUEBA, transporte=transporte_json(_respuesta_tool_use(), capturas=capturas),
    )
    proveedor.razonar(_contexto())
    solicitud, _ = capturas[0]
    cuerpo = json.loads(solicitud.data)
    mensaje = cuerpo["messages"][0]["content"]
    for termino_prohibido in ("ground_truth", "respuesta_correcta", "ERROR_DOCUMENTAL_MANDANTE"):
        assert termino_prohibido not in mensaje


# ---------------------------------------------------------------------
# Parseo de respuesta válida
# ---------------------------------------------------------------------


def test_respuesta_propuesta_se_traduce_a_hipotesis():
    proveedor = ProveedorModeloIAAnthropic(
        api_key=CLAVE_DE_PRUEBA, transporte=transporte_json(_respuesta_tool_use()),
    )
    hipotesis = proveedor.razonar(_contexto())
    assert hipotesis.resultado == "PROPUESTA"
    assert hipotesis.valor_propuesto == "XF3629"
    assert hipotesis.proveedor == "anthropic"
    assert hipotesis.metadata["usage"] == {"input_tokens": 10, "output_tokens": 5}
    assert "politica_prompt_version" in hipotesis.metadata


def test_respuesta_abstencion_se_traduce_correctamente():
    proveedor = ProveedorModeloIAAnthropic(
        api_key=CLAVE_DE_PRUEBA,
        transporte=transporte_json(_respuesta_tool_use(resultado="ABSTENCION", valor_propuesto="")),
    )
    hipotesis = proveedor.razonar(_contexto())
    assert hipotesis.resultado == "ABSTENCION"
    assert hipotesis.valor_propuesto == ""


def test_respuesta_requiere_herramienta_se_preserva():
    proveedor = ProveedorModeloIAAnthropic(
        api_key=CLAVE_DE_PRUEBA,
        transporte=transporte_json(_respuesta_tool_use(
            resultado="REQUIERE_HERRAMIENTA", valor_propuesto="", herramienta_faltante="HISTORIAL_VEHICULO",
        )),
    )
    hipotesis = proveedor.razonar(_contexto())
    assert hipotesis.resultado == "REQUIERE_HERRAMIENTA"
    assert hipotesis.herramienta_faltante == "HISTORIAL_VEHICULO"


def test_confianza_declarada_y_posible_incidencia_quedan_en_metadata():
    proveedor = ProveedorModeloIAAnthropic(
        api_key=CLAVE_DE_PRUEBA,
        transporte=transporte_json(_respuesta_tool_use(
            confianza_declarada=0.87, posible_incidencia_documental=True,
        )),
    )
    hipotesis = proveedor.razonar(_contexto())
    assert hipotesis.metadata["confianza_declarada"] == 0.87
    assert hipotesis.metadata["posible_incidencia_documental"] is True


def test_hipotesis_id_es_reproducible_igual_que_con_el_simulado():
    from atlas_core.atlas_ia.contratos import calcular_hipotesis_id
    proveedor = ProveedorModeloIAAnthropic(
        api_key=CLAVE_DE_PRUEBA, transporte=transporte_json(_respuesta_tool_use()),
    )
    contexto = _contexto()
    hipotesis = proveedor.razonar(contexto)
    assert hipotesis.hipotesis_id == calcular_hipotesis_id(contexto, "XF3629")


# ---------------------------------------------------------------------
# Respuestas mal formadas -- nunca deben tumbar el caso ni inventar datos
# ---------------------------------------------------------------------


def test_sin_bloque_tool_use_es_error_de_proveedor_no_disponible():
    proveedor = ProveedorModeloIAAnthropic(
        api_key=CLAVE_DE_PRUEBA,
        transporte=transporte_json({"content": [{"type": "text", "text": "prosa libre"}]}),
    )
    with pytest.raises(ProveedorIANoDisponible):
        proveedor.razonar(_contexto())


def test_propuesta_sin_valor_propuesto_degrada_a_abstencion_segura():
    """El modelo dijo PROPUESTA pero no trajo valor_propuesto -- viola su
    propio contrato. Nunca debe tumbar el caso ni inventar un valor: se
    degrada a abstención explícita y auditable."""
    proveedor = ProveedorModeloIAAnthropic(
        api_key=CLAVE_DE_PRUEBA,
        transporte=transporte_json(_respuesta_tool_use(valor_propuesto="")),
    )
    hipotesis = proveedor.razonar(_contexto())
    assert hipotesis.resultado == "ABSTENCION"
    assert "estructura inválida" in hipotesis.explicacion.lower()


def test_resultado_desconocido_degrada_a_abstencion_segura():
    proveedor = ProveedorModeloIAAnthropic(
        api_key=CLAVE_DE_PRUEBA,
        transporte=transporte_json(_respuesta_tool_use(resultado="INVENTADO")),
    )
    hipotesis = proveedor.razonar(_contexto())
    assert hipotesis.resultado == "ABSTENCION"


# ---------------------------------------------------------------------
# Errores de red/HTTP -- mismo tratamiento que OpenRouteService
# ---------------------------------------------------------------------


@pytest.mark.parametrize("error", [socket.timeout(), URLError("sin red")])
def test_timeout_y_error_de_conexion(error):
    def fallar(*_):
        raise error
    proveedor = ProveedorModeloIAAnthropic(api_key=CLAVE_DE_PRUEBA, transporte=fallar)
    with pytest.raises(ProveedorIANoDisponible):
        proveedor.razonar(_contexto())


def test_http_error_se_traduce_a_proveedor_no_disponible():
    def fallar(*_):
        raise HTTPError("url", 500, "error interno", {}, None)
    proveedor = ProveedorModeloIAAnthropic(api_key=CLAVE_DE_PRUEBA, transporte=fallar)
    with pytest.raises(ProveedorIANoDisponible):
        proveedor.razonar(_contexto())


def test_respuesta_no_json_se_traduce_a_proveedor_no_disponible():
    proveedor = ProveedorModeloIAAnthropic(
        api_key=CLAVE_DE_PRUEBA, transporte=lambda *_: RespuestaHTTP(200, b"no-json"),
    )
    with pytest.raises(ProveedorIANoDisponible):
        proveedor.razonar(_contexto())


@pytest.mark.parametrize("codigo", [401, 403, 429, 500])
def test_codigos_de_error_http_se_rechazan(codigo):
    proveedor = ProveedorModeloIAAnthropic(
        api_key=CLAVE_DE_PRUEBA, transporte=transporte_json({}, estado=codigo),
    )
    with pytest.raises(ProveedorIANoDisponible):
        proveedor.razonar(_contexto())
