"""Bloque B1 INVESTIGADOR -- herramienta real de verificación externa
(búsqueda web) que B1 puede solicitar durante su propio razonamiento.
Sin red -- transporte HTTP inyectado, mismo patrón que el resto de la
base de código."""
from __future__ import annotations

import json

import pytest

from atlas_core.atlas_ia.buscador_web import (
    BuscadorWebConCache,
    BuscadorWebNoDisponible,
    BuscadorWebOpenRouter,
    CredencialBuscadorWebAusente,
    RepositorioCacheBusquedaWeb,
    RespuestaHTTP,
)
from atlas_core.atlas_ia.contratos import ContextoRazonamiento
from atlas_core.atlas_ia.herramientas import herramienta_verificacion_externa


def _transporte_ok(texto="Direccion X 100, San Bernardo, Chile", citas=None):
    def transportar(solicitud, timeout):
        cuerpo = {
            "model": "perplexity/sonar",
            "choices": [{"message": {
                "content": texto,
                "annotations": [
                    {"type": "url_citation", "url_citation": {"title": t, "url": u}}
                    for t, u in (citas or [("Fuente", "https://ejemplo.cl")])
                ],
            }}],
        }
        return RespuestaHTTP(200, json.dumps(cuerpo).encode("utf-8"))
    return transportar


def test_sin_credencial_lanza_error_tipado():
    buscador = BuscadorWebOpenRouter(api_key="", transporte=_transporte_ok())
    with pytest.raises(CredencialBuscadorWebAusente):
        buscador.buscar("consulta de prueba")


def test_busqueda_real_devuelve_texto_y_citas():
    buscador = BuscadorWebOpenRouter(api_key="X", transporte=_transporte_ok())
    resultado = buscador.buscar("INTERIOR NUEVA 01148 SAN BERNARDO, Chile")
    assert resultado.respuesta_texto == "Direccion X 100, San Bernardo, Chile"
    assert resultado.citas == (("Fuente", "https://ejemplo.cl"),) or resultado.citas[0].url == "https://ejemplo.cl"


def test_error_http_no_fabrica_resultado():
    buscador = BuscadorWebOpenRouter(api_key="X", transporte=lambda *_: (_ for _ in ()).throw(OSError("sin red")))
    with pytest.raises(BuscadorWebNoDisponible):
        buscador.buscar("consulta")


def test_cache_evita_segunda_llamada_real(tmp_path):
    llamadas = {"n": 0}

    def transportar(solicitud, timeout):
        llamadas["n"] += 1
        return _transporte_ok()(solicitud, timeout)

    buscador = BuscadorWebConCache(
        BuscadorWebOpenRouter(api_key="X", transporte=transportar),
        RepositorioCacheBusquedaWeb(tmp_path / "cache.json"),
    )
    r1 = buscador.buscar("MISMA CONSULTA")
    r2 = buscador.buscar("misma consulta")  # normalizada -- misma clave
    assert llamadas["n"] == 1
    assert r1.respuesta_texto == r2.respuesta_texto


class _BuscadorFalla:
    def buscar(self, consulta):
        raise BuscadorWebNoDisponible("sin red")


class _BuscadorRegistraConsultas:
    def __init__(self):
        self.consultas: list[str] = []

    def buscar(self, consulta):
        self.consultas.append(consulta)
        from atlas_core.atlas_ia.buscador_web import RespuestaBusquedaWeb
        return RespuestaBusquedaWeb(
            consulta=consulta, respuesta_texto=f"Respuesta real para: {consulta}",
            citas=(), proveedor="test", modelo="test", fecha="2026-01-01T00:00:00+00:00",
        )


def _contexto_destino(**cambios):
    datos = {
        "campo": "despachar_a_crudo", "valor_documental": "INTERIOR NUEVA 01148 SAN BERNARDO",
        "rut_chofer": "", "numero_guia": "472008", "numero_transporte": "T1",
        "identidad_operacional": {"obra_destino": "AUSIN SAN BERNARDO", "cliente": "AUSIN HNOS LTDA"},
    }
    datos.update(cambios)
    return ContextoRazonamiento(**datos)


def test_vincula_direccion_con_obra_nunca_string_aislado():
    """Regla crítica (Bloque B1 INVESTIGADOR): con obra/cliente
    disponibles, la primera consulta SIEMPRE los incluye -- nunca
    investiga la dirección como string aislado."""
    buscador = _BuscadorRegistraConsultas()
    herramienta = herramienta_verificacion_externa(buscador)
    herramienta.consultar(_contexto_destino())
    assert buscador.consultas  # se ejecutó al menos una consulta
    assert "AUSIN SAN BERNARDO" in buscador.consultas[0]
    assert "INTERIOR NUEVA 01148 SAN BERNARDO" in buscador.consultas[0]


def test_sin_obra_ni_cliente_usa_contexto_territorial_explicito():
    buscador = _BuscadorRegistraConsultas()
    herramienta = herramienta_verificacion_externa(buscador)
    herramienta.consultar(_contexto_destino(identidad_operacional={}))
    assert len(buscador.consultas) == 1
    assert "Chile" in buscador.consultas[0]


def test_produce_evidencia_tipo_externo():
    buscador = _BuscadorRegistraConsultas()
    herramienta = herramienta_verificacion_externa(buscador)
    evidencias = herramienta.consultar(_contexto_destino())
    assert evidencias
    assert all(e.tipo_fuente == "EXTERNO" for e in evidencias)
    assert all(e.campo == "despachar_a_crudo" for e in evidencias)


def test_falla_del_buscador_nunca_lanza_se_abstiene():
    herramienta = herramienta_verificacion_externa(_BuscadorFalla())
    evidencias = herramienta.consultar(_contexto_destino())
    assert evidencias == ()


def test_maximo_de_consultas_por_invocacion_respetado():
    from atlas_core.atlas_ia.herramientas import MAXIMO_CONSULTAS_POR_INVOCACION

    buscador = _BuscadorRegistraConsultas()
    herramienta = herramienta_verificacion_externa(buscador)
    herramienta.consultar(_contexto_destino())
    assert len(buscador.consultas) <= MAXIMO_CONSULTAS_POR_INVOCACION
