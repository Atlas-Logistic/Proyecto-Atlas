import json
import socket
from urllib.error import URLError

import pytest

from atlas_core.rutas.modelos import Coordenadas, EstadoRuta
from atlas_core.rutas.openrouteservice import OpenRouteService, RespuestaHTTP


def transporte_json(datos, estado=200, capturas=None):
    def transportar(solicitud, timeout):
        if capturas is not None:
            capturas.append((solicitud, timeout))
        return RespuestaHTTP(estado, json.dumps(datos).encode("utf-8"))
    return transportar


def test_falta_de_clave_no_invoca_transporte(monkeypatch):
    monkeypatch.delenv("OPENROUTESERVICE_API_KEY", raising=False)
    llamadas = []
    proveedor = OpenRouteService(transporte=lambda *_: llamadas.append(True))
    assert proveedor.geocodificar("DIRECCION DEMO").estado == EstadoRuta.SIN_CREDENCIAL
    assert llamadas == []


def test_direccion_no_encontrada():
    proveedor = OpenRouteService(api_key="SECRETO_DE_PRUEBA", transporte=transporte_json({"features": []}))
    assert proveedor.geocodificar("DIRECCION DEMO").estado == EstadoRuta.DIRECCION_NO_ENCONTRADA


def test_resultado_ambiguo():
    candidato = {"geometry": {"coordinates": [-20, -10]}, "properties": {"label": "DEMO"}}
    proveedor = OpenRouteService(api_key="SECRETO_DE_PRUEBA", transporte=transporte_json({"features": [candidato, candidato]}))
    resultado = proveedor.geocodificar("DIRECCION DEMO")
    assert resultado.estado == EstadoRuta.RESULTADO_AMBIGUO
    assert len(resultado.candidatos) == 2


@pytest.mark.parametrize("error", [socket.timeout(), URLError("sin red")])
def test_timeout_y_error_de_conexion(error):
    def fallar(*_):
        raise error
    proveedor = OpenRouteService(api_key="SECRETO_DE_PRUEBA", transporte=fallar)
    assert proveedor.geocodificar("DIRECCION DEMO").estado == EstadoRuta.SIN_CONEXION


@pytest.mark.parametrize("codigo", [403, 429])
def test_limite_de_cuota(codigo):
    proveedor = OpenRouteService(api_key="SECRETO_DE_PRUEBA", transporte=transporte_json({}, codigo))
    assert proveedor.geocodificar("DIRECCION DEMO").estado == EstadoRuta.LIMITE_CUOTA


def test_respuesta_invalida():
    proveedor = OpenRouteService(
        api_key="SECRETO_DE_PRUEBA",
        transporte=lambda *_: RespuestaHTTP(200, b"no-json"),
    )
    assert proveedor.geocodificar("DIRECCION DEMO").estado == EstadoRuta.RESPUESTA_INVALIDA


def test_geocodificacion_unica_requiere_revision():
    datos = {"features": [{
        "geometry": {"coordinates": [-20.0, -10.0]},
        "properties": {"label": "UBICACION DEMO", "confidence": 0.9},
    }]}
    proveedor = OpenRouteService(api_key="SECRETO_DE_PRUEBA", transporte=transporte_json(datos))
    resultado = proveedor.geocodificar("DIRECCION DEMO")
    assert resultado.estado == EstadoRuta.REQUIERE_REVISION
    assert resultado.candidatos[0].coordenadas == Coordenadas(-20, -10)


def test_calculo_correcto_convierte_unidades_y_envia_lon_lat():
    capturas = []
    proveedor = OpenRouteService(
        api_key="SECRETO_DE_PRUEBA",
        transporte=transporte_json({"routes": [{"summary": {"distance": 12500, "duration": 1440}}]}, capturas=capturas),
    )
    resultado = proveedor.calcular_ruta(Coordenadas(-20, -10), Coordenadas(-20.1, -10.1), "driving-car")
    cuerpo = json.loads(capturas[0][0].data)
    assert cuerpo["coordinates"][0] == [-20, -10]
    assert resultado.distancia_km == 12.5
    assert resultado.duracion_estimada_min == 24


def test_clave_no_aparece_en_resultados_ni_errores():
    secreto = "SECRETO_QUE_NO_DEBE_APARECER"
    proveedor = OpenRouteService(api_key=secreto, transporte=lambda *_: RespuestaHTTP(500, b""))
    resultado = proveedor.geocodificar("DIRECCION DEMO")
    assert secreto not in repr(resultado)
