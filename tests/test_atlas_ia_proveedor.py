"""Bloque ATLAS IA A1 -- proveedor simulado (`atlas_core.atlas_ia.proveedor`).

`ProveedorModeloIASimulado` no simula capacidad de razonamiento (ver
AJUSTE 3 del bloque): estos tests prueban únicamente que el enchufe
funciona -- determinismo, configurabilidad, trazabilidad -- nunca
"accuracy" de ningún tipo."""
from __future__ import annotations

from atlas_core.atlas_ia.contratos import (
    ContextoRazonamiento,
    EvidenciaIA,
    RESULTADO_HIPOTESIS_ABSTENCION,
    RESULTADO_HIPOTESIS_PROPUESTA,
    calcular_hipotesis_id,
)
from atlas_core.atlas_ia.proveedor import ProveedorModeloIASimulado, RespuestaSimulada


def _contexto(valor_documental="XF3662") -> ContextoRazonamiento:
    return ContextoRazonamiento(
        campo="patente_tracto", valor_documental=valor_documental, rut_chofer="18626166-6",
        numero_guia="1", numero_transporte="T-1",
        evidencias=(
            EvidenciaIA(
                identificador="veh-1", campo="patente_tracto", valor="XF3629",
                tipo_fuente="HISTORICO", nivel="DOCUMENTAL_INDEPENDIENTE",
            ),
        ),
        resultado_motor="SUGERENCIA_HUMANA",
    )


def test_proveedor_simulado_devuelve_la_respuesta_configurada():
    proveedor = ProveedorModeloIASimulado(respuestas_por_valor_documental={
        "XF3662": RespuestaSimulada(resultado=RESULTADO_HIPOTESIS_PROPUESTA, valor_propuesto="XF3629"),
    })
    contexto = _contexto()
    hipotesis = proveedor.razonar(contexto)
    assert hipotesis.resultado == RESULTADO_HIPOTESIS_PROPUESTA
    assert hipotesis.valor_propuesto == "XF3629"
    assert hipotesis.hipotesis_id == calcular_hipotesis_id(contexto, "XF3629")


def test_proveedor_simulado_es_determinista():
    proveedor = ProveedorModeloIASimulado(respuestas_por_valor_documental={
        "XF3662": RespuestaSimulada(resultado=RESULTADO_HIPOTESIS_PROPUESTA, valor_propuesto="XF3629"),
    })
    contexto = _contexto()
    primera = proveedor.razonar(contexto)
    segunda = proveedor.razonar(contexto)
    assert primera == segunda


def test_proveedor_simulado_sin_respuesta_configurada_devuelve_abstencion():
    """T5 (a nivel de proveedor): sin ninguna respuesta configurada para
    este valor documental, el doble se abstiene -- nunca inventa algo por
    su cuenta."""
    proveedor = ProveedorModeloIASimulado(respuestas_por_valor_documental={})
    hipotesis = proveedor.razonar(_contexto("VALOR-NO-CONFIGURADO"))
    assert hipotesis.resultado == RESULTADO_HIPOTESIS_ABSTENCION
    assert hipotesis.valor_propuesto == ""


def test_proveedor_simulado_registra_contextos_recibidos():
    proveedor = ProveedorModeloIASimulado(respuestas_por_valor_documental={})
    contexto = _contexto()
    proveedor.razonar(contexto)
    assert proveedor.contextos_recibidos == [contexto]


def test_proveedor_simulado_sin_red_ni_credenciales():
    """El proveedor no acepta ni requiere ninguna credencial/URL -- su
    único estado es el diccionario de respuestas entregado al construirlo."""
    proveedor = ProveedorModeloIASimulado(respuestas_por_valor_documental={})
    assert not hasattr(proveedor, "api_key")
    assert not hasattr(proveedor, "url")
