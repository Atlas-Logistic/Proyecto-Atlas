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


# --- Bloque CIERRE LOGÍSTICA RESIDUAL -- consulta ESTRUCTURADA ---

def _transporte_por_calle(respuestas_por_calle, *, capturas=None):
    """Doble que simula Nominatim distinguiendo `street=`/`q=` en la URL,
    devolviendo una respuesta distinta según el valor exacto de `street`
    (o `[]` para cualquier otro, incluida una consulta libre `q=`)."""
    def transportar(solicitud, timeout):
        if capturas is not None:
            capturas.append(solicitud.full_url)
        from urllib.parse import parse_qs, urlparse
        parametros = parse_qs(urlparse(solicitud.full_url).query)
        calle = parametros.get("street", [None])[0]
        datos = respuestas_por_calle.get(calle, [])
        return RespuestaHTTP(200, json.dumps(datos).encode("utf-8"))
    return transportar


def test_detecta_comuna_final_y_usa_consulta_estructurada():
    """Caso real 472163 (VIA MORADA 6480 VITACURA): con una comuna real
    reconocible al final del texto, la consulta usa `street=`/`city=`
    (estructurada) en vez de `q=` libre -- y el número de calle exacto sí
    se resuelve, cosa que la búsqueda libre no siempre lograba."""
    datos = [{
        "lat": "-33.38", "lon": "-70.58",
        "address": {"house_number": "6480", "road": "Vía Morada", "suburb": "Vitacura"},
    }]
    proveedor = NominatimGeocoder(
        transporte=_transporte_por_calle({"VIA MORADA 6480": datos}),
    )
    resultado = proveedor.geocodificar("VIA MORADA 6480 VITACURA, Chile")
    assert resultado.estado == EstadoRuta.REQUIERE_REVISION
    candidato = resultado.candidatos[0]
    assert candidato.etiqueta == "Vía Morada 6480"
    assert candidato.confianza == 0.9
    assert candidato.localidad == "Vitacura"


def test_reintenta_con_calle_reducida_cuando_la_completa_no_encuentra_numero():
    """Caso real 472073 (PDTE. RIESCO 5903 LAS CONDES): la calle completa
    (con abreviatura "PDTE.") no encuentra el número exacto -- se
    reintenta progresivamente con menos palabras al principio (nunca
    inventa un nombre de calle nuevo, sólo prueba subconjuntos del mismo
    texto) hasta encontrar un único candidato con el número buscado."""
    datos = [{
        "lat": "-33.40", "lon": "-70.57",
        "address": {"house_number": "5903", "road": "Avenida Presidente Riesco", "suburb": "Las Condes"},
    }]
    capturas = []
    proveedor = NominatimGeocoder(
        transporte=_transporte_por_calle({"RIESCO 5903": datos}, capturas=capturas),
    )
    resultado = proveedor.geocodificar("PDTE. RIESCO 5903 LAS CONDES, Chile")
    assert resultado.estado == EstadoRuta.REQUIERE_REVISION
    assert resultado.candidatos[0].etiqueta == "Avenida Presidente Riesco 5903"
    # Probó la calle completa (sin resultado) antes de reducirla -- nunca
    # se salta directo a la forma corta.
    assert any("street=PDTE" in url for url in capturas)
    assert any("street=RIESCO+5903" in url for url in capturas)


def test_sin_comuna_reconocible_usa_consulta_libre_como_antes():
    """Control -- sin una comuna real detectable al final del texto, el
    comportamiento es exactamente el de antes de este bloque: consulta
    libre `q=`, nunca fuerza una estructura que no está presente."""
    capturas = []
    proveedor = NominatimGeocoder(transporte=transporte_json([], capturas=capturas))
    proveedor.geocodificar("DIRECCION SIN COMUNA RECONOCIBLE")
    assert "q=" in capturas[0][0].full_url
    assert "street=" not in capturas[0][0].full_url


def test_estructurada_sin_resultado_util_cae_a_busqueda_libre():
    """Si ningún intento estructurado (completo ni reducido) encuentra un
    único candidato con el número buscado, se agota también la consulta
    libre antes de rendirse -- nunca abandona tras un solo intento."""
    datos_libre = [{
        "lat": "-33.0", "lon": "-70.0",
        "address": {"house_number": "6480", "road": "Vía Morada", "suburb": "Vitacura"},
    }]

    def transportar(solicitud, timeout):
        from urllib.parse import parse_qs, urlparse
        parametros = parse_qs(urlparse(solicitud.full_url).query)
        if "street" in parametros:
            return RespuestaHTTP(200, b"[]")
        return RespuestaHTTP(200, json.dumps(datos_libre).encode("utf-8"))

    proveedor = NominatimGeocoder(transporte=transportar)
    resultado = proveedor.geocodificar("VIA MORADA 6480 VITACURA, Chile")
    assert resultado.estado == EstadoRuta.REQUIERE_REVISION
    assert resultado.candidatos[0].etiqueta == "Vía Morada 6480"
