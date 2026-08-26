"""Bloque CONSULTAS ATLAS V1 -- proveedor B1 real (mecánica HTTP/
credencial/errores), transporte inyectado -- nunca red real en tests."""
from __future__ import annotations

import json
import socket

import pytest

from atlas_core.interpretador_consultas import CatalogosConsulta
from atlas_core.proveedor_interpretacion_consultas import (
    CredencialInterpretacionAusente,
    InterpretacionNoDisponible,
    ProveedorInterpretacionConsultaAnthropic,
    RespuestaHTTP,
)

CATALOGOS = CatalogosConsulta(choferes=("JUAN PEREZ",), clientes=(), obras=(), tipos_carga=("ROLLOS",), comunas=())


def _transporte_tool_use(entrada: dict):
    def transportar(solicitud, timeout):
        cuerpo = {
            "content": [{"type": "tool_use", "name": "interpretar_consulta_atlas", "input": entrada}],
        }
        return RespuestaHTTP(200, json.dumps(cuerpo).encode("utf-8"))
    return transportar


def test_sin_api_key_lanza_credencial_ausente():
    proveedor = ProveedorInterpretacionConsultaAnthropic(api_key="", transporte=lambda *_: None)
    with pytest.raises(CredencialInterpretacionAusente):
        proveedor.interpretar("¿Cuántos viajes?", CATALOGOS)


def test_interpreta_desde_tool_use_valido():
    entrada = {
        "metrica": "COUNT_VIAJES", "filtros": {"chofer": "JUAN PEREZ"},
        "agrupacion": None, "abstencion": False,
    }
    proveedor = ProveedorInterpretacionConsultaAnthropic(api_key="clave-test", transporte=_transporte_tool_use(entrada))
    consulta = proveedor.interpretar("¿Cuántos viajes hizo Juan?", CATALOGOS)
    assert consulta is not None
    assert consulta.metrica == "COUNT_VIAJES"
    assert consulta.filtros == {"chofer": "JUAN PEREZ"}


def test_abstencion_devuelve_none():
    entrada = {"metrica": "COUNT_VIAJES", "filtros": {}, "abstencion": True}
    proveedor = ProveedorInterpretacionConsultaAnthropic(api_key="clave-test", transporte=_transporte_tool_use(entrada))
    assert proveedor.interpretar("no tiene sentido", CATALOGOS) is None


def test_timeout_lanza_no_disponible():
    def fallar(*_):
        raise socket.timeout()
    proveedor = ProveedorInterpretacionConsultaAnthropic(api_key="clave-test", transporte=fallar)
    with pytest.raises(InterpretacionNoDisponible):
        proveedor.interpretar("¿Cuántos viajes?", CATALOGOS)


def test_respuesta_sin_tool_use_lanza_no_disponible():
    def transportar(solicitud, timeout):
        return RespuestaHTTP(200, json.dumps({"content": [{"type": "text", "text": "hola"}]}).encode("utf-8"))
    proveedor = ProveedorInterpretacionConsultaAnthropic(api_key="clave-test", transporte=transportar)
    with pytest.raises(InterpretacionNoDisponible):
        proveedor.interpretar("¿Cuántos viajes?", CATALOGOS)


def test_http_error_no_expone_la_credencial():
    from urllib.error import HTTPError

    def fallar(*_):
        raise HTTPError("url", 500, "error", {}, None)
    proveedor = ProveedorInterpretacionConsultaAnthropic(api_key="clave-secreta-123", transporte=fallar)
    with pytest.raises(InterpretacionNoDisponible) as excinfo:
        proveedor.interpretar("¿Cuántos viajes?", CATALOGOS)
    assert "clave-secreta-123" not in str(excinfo.value)


# --- Bloque UNIVERSAL V1 -- B1 debe poder expresar dominio/relación,
# no sólo VIAJES/filtros -- antes de este bloque el esquema ni siquiera
# los exponía (Bloque 5/7 del ticket: "B1 interpreta hacia un contrato
# universal") ---

def test_esquema_expone_dominio_y_relacion():
    from atlas_core.proveedor_interpretacion_consultas import _herramienta_consulta_atlas
    propiedades = _herramienta_consulta_atlas()["input_schema"]["properties"]
    assert "dominio" in propiedades
    assert "EVENTOS" in propiedades["dominio"]["enum"]
    assert "INCIDENCIAS_DOCUMENTALES" in propiedades["dominio"]["enum"]
    assert "relacion" in propiedades
    assert "vehiculo" in propiedades["relacion"]["enum"]


def test_interpreta_dominio_eventos_desde_tool_use():
    entrada = {
        "dominio": "EVENTOS", "metrica": "COUNT_EVENTOS",
        "filtros": {"tipo_evento": "TIENE_ESTADIA", "chofer": "JUAN PEREZ"},
        "agrupacion": None, "abstencion": False,
    }
    proveedor = ProveedorInterpretacionConsultaAnthropic(api_key="clave-test", transporte=_transporte_tool_use(entrada))
    consulta = proveedor.interpretar("¿Cuántas estadías tuvo Juan?", CATALOGOS)
    assert consulta is not None
    assert consulta.dominio == "EVENTOS"
    assert consulta.filtros["tipo_evento"] == "TIENE_ESTADIA"


def test_interpreta_relacion_desde_tool_use():
    entrada = {
        "metrica": "LIST_RELACION", "relacion": "vehiculo",
        "filtros": {"chofer": "JUAN PEREZ"}, "agrupacion": None, "abstencion": False,
    }
    proveedor = ProveedorInterpretacionConsultaAnthropic(api_key="clave-test", transporte=_transporte_tool_use(entrada))
    consulta = proveedor.interpretar("¿Qué patentes ha usado Juan?", CATALOGOS)
    assert consulta is not None
    assert consulta.relacion == "vehiculo"


def test_dominio_ausente_en_tool_use_sigue_siendo_viajes_por_defecto():
    """Compatibilidad V2: B1 no está obligado a mandar `dominio` --
    sigue significando VIAJES, igual que antes de este bloque."""
    entrada = {"metrica": "COUNT_VIAJES", "filtros": {}, "agrupacion": None, "abstencion": False}
    proveedor = ProveedorInterpretacionConsultaAnthropic(api_key="clave-test", transporte=_transporte_tool_use(entrada))
    consulta = proveedor.interpretar("¿Cuántos viajes hay?", CATALOGOS)
    assert consulta.dominio == "VIAJES"
