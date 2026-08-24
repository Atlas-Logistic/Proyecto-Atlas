"""Bloque B1 OBSERVADOR + FALLBACK GEOGRÁFICO -- adaptador HTTP de
Nominatim (geocodificador de RESPALDO estructurado)."""
import json
import socket
from urllib.error import HTTPError, URLError

import pytest

from atlas_core.rutas.modelos import Coordenadas, EstadoRuta
from atlas_core.rutas.nominatim import NominatimGeocoder, RespuestaHTTP


def transporte_json(datos, estado=200, capturas=None):
    def transportar(solicitud, timeout):
        if capturas is not None:
            capturas.append((solicitud, timeout))
        return RespuestaHTTP(estado, json.dumps(datos).encode("utf-8"))
    return transportar


def test_direccion_vacia_no_invoca_transporte():
    llamadas = []
    proveedor = NominatimGeocoder(transporte=lambda *_: llamadas.append(True))
    assert proveedor.geocodificar("").estado == EstadoRuta.DIRECCION_NO_ENCONTRADA
    assert llamadas == []


def test_sin_candidatos_es_direccion_no_encontrada():
    proveedor = NominatimGeocoder(transporte=transporte_json([]))
    assert proveedor.geocodificar("DIRECCION DEMO").estado == EstadoRuta.DIRECCION_NO_ENCONTRADA


def test_candidato_unico_con_numero_de_calle_requiere_revision():
    datos = [{
        "lat": "-33.52", "lon": "-70.75",
        "address": {"house_number": "655", "road": "Vicuña Mackenna", "suburb": "Maipú"},
    }]
    proveedor = NominatimGeocoder(transporte=transporte_json(datos))
    resultado = proveedor.geocodificar("VICUÑA MACKENNA 655, Chile")
    assert resultado.estado == EstadoRuta.REQUIERE_REVISION
    candidato = resultado.candidatos[0]
    assert candidato.etiqueta == "Vicuña Mackenna 655"
    assert candidato.coordenadas == Coordenadas(-70.75, -33.52)
    assert candidato.confianza == 0.9  # tiene número de calle
    # localidad/región derivadas del catálogo territorial cerrado, nunca
    # del string crudo de Nominatim.
    assert candidato.localidad == "Maipú"
    assert candidato.region == "Metropolitana"


def test_candidato_sin_numero_de_calle_tiene_menor_confianza():
    datos = [{
        "lat": "-33.40", "lon": "-70.60",
        "address": {"road": "Vicuña Mackenna", "city": "La Florida"},
    }]
    proveedor = NominatimGeocoder(transporte=transporte_json(datos))
    resultado = proveedor.geocodificar("VICUÑA MACKENNA, Chile")
    assert resultado.candidatos[0].confianza == 0.2  # sin número de calle


def test_comuna_no_reconocida_deja_localidad_region_vacias():
    """Nunca inventa una localidad/región fuera del catálogo territorial
    cerrado -- si Nominatim devuelve algo que no calza con ninguna comuna
    real, se queda vacío (evidencia insuficiente, nunca una etiqueta
    inventada)."""
    datos = [{
        "lat": "-33.0", "lon": "-70.0",
        "address": {"house_number": "1", "road": "Calle X", "suburb": "Zona Inexistente"},
    }]
    proveedor = NominatimGeocoder(transporte=transporte_json(datos))
    resultado = proveedor.geocodificar("CALLE X 1, Chile")
    assert resultado.candidatos[0].localidad == ""
    assert resultado.candidatos[0].region == ""


def test_multiples_candidatos_es_resultado_ambiguo():
    candidato = {"lat": "-20", "lon": "-10", "address": {"road": "Demo"}}
    proveedor = NominatimGeocoder(transporte=transporte_json([candidato, candidato]))
    resultado = proveedor.geocodificar("DIRECCION DEMO")
    assert resultado.estado == EstadoRuta.RESULTADO_AMBIGUO
    assert len(resultado.candidatos) == 2


@pytest.mark.parametrize("error", [socket.timeout(), URLError("sin red")])
def test_timeout_y_error_de_conexion(error):
    def fallar(*_):
        raise error
    proveedor = NominatimGeocoder(transporte=fallar)
    assert proveedor.geocodificar("DIRECCION DEMO").estado == EstadoRuta.SIN_CONEXION


def test_limite_de_cuota_429():
    proveedor = NominatimGeocoder(transporte=transporte_json({}, 429))
    assert proveedor.geocodificar("DIRECCION DEMO").estado == EstadoRuta.LIMITE_CUOTA


def test_bloqueado_sin_user_agent_valido_es_proveedor_no_disponible():
    """Caso real: Nominatim devuelve 403 a solicitudes sin User-Agent
    identificable -- se trata como falla técnica del proveedor, nunca
    como evidencia de dirección inexistente."""
    def fallar_403(*_):
        raise HTTPError("url", 403, "Forbidden", {}, None)
    proveedor = NominatimGeocoder(transporte=fallar_403)
    assert proveedor.geocodificar("DIRECCION DEMO").estado == EstadoRuta.PROVEEDOR_NO_DISPONIBLE


def test_respuesta_invalida_no_es_lista():
    proveedor = NominatimGeocoder(transporte=transporte_json({"no": "es una lista"}))
    assert proveedor.geocodificar("DIRECCION DEMO").estado == EstadoRuta.RESPUESTA_INVALIDA


def test_respuesta_no_json():
    proveedor = NominatimGeocoder(transporte=lambda *_: RespuestaHTTP(200, b"no-json"))
    assert proveedor.geocodificar("DIRECCION DEMO").estado == EstadoRuta.RESPUESTA_INVALIDA


def test_restriccion_de_pais_se_envia_en_la_consulta():
    capturas = []
    proveedor = NominatimGeocoder(pais="CL", transporte=transporte_json([], capturas=capturas))
    proveedor.geocodificar("DIRECCION DEMO")
    assert "countrycodes=cl" in capturas[0][0].full_url


def test_user_agent_siempre_presente_en_la_solicitud():
    capturas = []
    proveedor = NominatimGeocoder(transporte=transporte_json([], capturas=capturas))
    proveedor.geocodificar("DIRECCION DEMO")
    assert capturas[0][0].get_header("User-agent")
