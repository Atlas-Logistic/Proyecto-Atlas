from __future__ import annotations

import json
import socket
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError

import pytest

from atlas_core.inteligencia import (
    EstadoPropuesta,
    EstadoVerificacionDestino,
    Evidencia,
    SolicitudVerificacionDestino,
    TipoFuente,
    VerificadorDestinosOpenRouteService,
    convertir_a_evidencia,
    resolver_destino_con_verificacion,
)
from atlas_core.inteligencia.motor import normalizar
from atlas_core.inteligencia.verificacion_destinos import RespuestaHTTPDestino
from atlas_core.procesamiento_masivo import COLUMNAS


AHORA = datetime(2026, 7, 28, 19, 0, tzinfo=timezone.utc)


def solicitud(**cambios):
    datos = dict(
        direccion_original="CALLE SINTETICA 123",
        comuna_esperada="COMUNA DEMO",
        region_esperada="REGION DEMO",
        pais="CHILE",
        identificador_interno="DESTINO-SINTETICO-001",
        autorizacion_externa=True,
        campos_autorizados=frozenset(
            {
                "direccion_original",
                "comuna_esperada",
                "region_esperada",
                "pais",
            }
        ),
        contiene_datos_sensibles=True,
        contexto_minimo={"rut": "NO-ENVIAR", "patente": "NO-ENVIAR"},
    )
    datos.update(cambios)
    return SolicitudVerificacionDestino(**datos)


def feature(
    *,
    label="CALLE SINTETICA 123, COMUNA DEMO, REGION DEMO",
    comuna="COMUNA DEMO",
    region="REGION DEMO",
    pais="CHILE",
    coords=(-70.6, -33.5),
    confidence=0.9,
):
    return {
        "geometry": {"coordinates": list(coords)},
        "properties": {
            "label": label,
            "locality": comuna,
            "region": region,
            "country": pais,
            "confidence": confidence,
        },
    }


def transporte(datos, estado=200, capturas=None):
    def enviar(peticion, timeout):
        if capturas is not None:
            capturas.append((peticion, timeout))
        return RespuestaHTTPDestino(estado, json.dumps(datos).encode())
    return enviar


def verificador(datos=None, **opciones):
    datos = {"features": [feature()]} if datos is None else datos
    return VerificadorDestinosOpenRouteService(
        api_key="CLAVE-SINTETICA",
        transporte=transporte(datos),
        reloj=lambda: AHORA,
        monotono=lambda: 10.0,
        **opciones,
    )


def test_direccion_y_comuna_coinciden():
    assert verificador().verificar(solicitud()).estado == EstadoVerificacionDestino.VERIFICADA


def test_direccion_aproximada_con_comuna_coincidente():
    datos = {"features": [feature(label="AVENIDA PARECIDA 123")]}
    assert verificador(datos).verificar(solicitud()).estado == EstadoVerificacionDestino.COINCIDENCIA_PARCIAL


@pytest.mark.parametrize(
    ("cambio", "estado"),
    [
        ({"comuna": "OTRA COMUNA"}, EstadoVerificacionDestino.CONTRADICCION_COMUNA),
        ({"region": "OTRA REGION"}, EstadoVerificacionDestino.CONTRADICCION_REGION),
    ],
)
def test_contradicciones_geograficas(cambio, estado):
    assert verificador({"features": [feature(**cambio)]}).verificar(solicitud()).estado == estado


def test_sin_resultados():
    assert verificador({"features": []}).verificar(solicitud()).estado == EstadoVerificacionDestino.SIN_RESULTADOS


def test_varios_resultados_son_ambiguos():
    resultado = verificador({"features": [feature(), feature()]}).verificar(solicitud())
    assert resultado.estado == EstadoVerificacionDestino.REVISAR
    assert resultado.error == "MULTIPLES_RESULTADOS"


@pytest.mark.parametrize("coords", [(181, -33), (-70, 91), ("x", -33)])
def test_coordenadas_invalidas(coords):
    resultado = verificador({"features": [feature(coords=coords)]}).verificar(solicitud())
    assert resultado.estado == EstadoVerificacionDestino.ERROR_PROVEEDOR


def test_credencial_ausente_no_consulta(monkeypatch):
    monkeypatch.delenv("OPENROUTESERVICE_API_KEY", raising=False)
    llamadas = []
    proveedor = VerificadorDestinosOpenRouteService(
        transporte=lambda *_: llamadas.append(1), reloj=lambda: AHORA
    )
    assert proveedor.verificar(solicitud()).estado == EstadoVerificacionDestino.CREDENCIAL_NO_DISPONIBLE
    assert llamadas == []


def test_consulta_no_autorizada():
    assert verificador().verificar(solicitud(autorizacion_externa=False)).estado == EstadoVerificacionDestino.CONSULTA_NO_AUTORIZADA


@pytest.mark.parametrize(
    "cambios",
    [
        {"direccion_original": ""},
        {"pais": ""},
        {"campos_autorizados": frozenset({"direccion_original"})},
        {"campos_autorizados": frozenset({"pais"})},
    ],
)
def test_datos_insuficientes(cambios):
    assert verificador().verificar(solicitud(**cambios)).estado == EstadoVerificacionDestino.DATOS_INSUFICIENTES


@pytest.mark.parametrize("error", [TimeoutError(), socket.timeout()])
def test_timeout_controlado(error):
    proveedor = VerificadorDestinosOpenRouteService(
        api_key="SINTETICA",
        transporte=lambda *_: (_ for _ in ()).throw(error),
        reloj=lambda: AHORA,
    )
    assert proveedor.verificar(solicitud()).estado == EstadoVerificacionDestino.TIMEOUT


@pytest.mark.parametrize(
    ("codigo", "estado"),
    [
        (400, EstadoVerificacionDestino.ERROR_PROVEEDOR),
        (401, EstadoVerificacionDestino.ERROR_PROVEEDOR),
        (403, EstadoVerificacionDestino.CUOTA_AGOTADA),
        (404, EstadoVerificacionDestino.ERROR_PROVEEDOR),
        (429, EstadoVerificacionDestino.CUOTA_AGOTADA),
        (500, EstadoVerificacionDestino.ERROR_PROVEEDOR),
    ],
)
def test_estados_http(codigo, estado):
    resultado = VerificadorDestinosOpenRouteService(
        api_key="SINTETICA",
        transporte=lambda *_: RespuestaHTTPDestino(codigo, b"{}"),
        reloj=lambda: AHORA,
    ).verificar(solicitud())
    assert resultado.estado == estado
    assert resultado.codigo_http == codigo


@pytest.mark.parametrize(
    "cuerpo",
    [b"no-json", b"{}", b'{"features": {}}'],
)
def test_json_invalido(cuerpo):
    proveedor = VerificadorDestinosOpenRouteService(
        api_key="SINTETICA",
        transporte=lambda *_: RespuestaHTTPDestino(200, cuerpo),
        reloj=lambda: AHORA,
    )
    assert proveedor.verificar(solicitud()).estado == EstadoVerificacionDestino.ERROR_PROVEEDOR


@pytest.mark.parametrize(
    "elemento",
    [
        {},
        {"properties": {}, "geometry": {"coordinates": [-70, -33]}},
        {"properties": {"label": "X"}, "geometry": {}},
    ],
)
def test_respuesta_incompleta(elemento):
    resultado = verificador({"features": [elemento]}).verificar(solicitud())
    assert resultado.estado == EstadoVerificacionDestino.ERROR_PROVEEDOR


def test_minimizacion_excluye_contexto_rut_patente_e_imagen():
    capturas = []
    proveedor = VerificadorDestinosOpenRouteService(
        api_key="SINTETICA",
        transporte=transporte({"features": [feature()]}, capturas=capturas),
        reloj=lambda: AHORA,
    )
    original = solicitud(
        contexto_minimo={
            "rut": "12.345.678-5",
            "patente": "ABC123",
            "imagen_completa": b"NO ENVIAR",
            "numero_transporte": "0001",
        }
    )
    resultado = proveedor.verificar(original)
    url = capturas[0][0].full_url
    assert "12.345" not in url and "ABC123" not in url and "0001" not in url
    assert resultado.evidencia_original.contexto_minimo["rut"] == "12.345.678-5"


def test_clave_no_aparece_en_url_resultado_o_error():
    clave = "SECRETO_QUE_NO_DEBE_APARECER"
    capturas = []
    proveedor = VerificadorDestinosOpenRouteService(
        api_key=clave,
        transporte=transporte({"features": [feature()]}, capturas=capturas),
        reloj=lambda: AHORA,
    )
    resultado = proveedor.verificar(solicitud())
    assert clave not in capturas[0][0].full_url
    assert clave not in repr(resultado)


def test_cache_evitar_consulta_duplicada():
    capturas = []
    proveedor = VerificadorDestinosOpenRouteService(
        api_key="SINTETICA",
        transporte=transporte({"features": [feature()]}, capturas=capturas),
        reloj=lambda: AHORA,
    )
    assert proveedor.verificar(solicitud()).desde_cache is False
    assert proveedor.verificar(solicitud()).desde_cache is True
    assert len(capturas) == 1


def test_expiracion_cache_vuelve_a_consultar():
    reloj = [AHORA]
    capturas = []
    proveedor = VerificadorDestinosOpenRouteService(
        api_key="SINTETICA",
        transporte=transporte({"features": [feature()]}, capturas=capturas),
        reloj=lambda: reloj[0],
        ttl=timedelta(seconds=1),
    )
    proveedor.verificar(solicitud())
    reloj[0] += timedelta(seconds=2)
    proveedor.verificar(solicitud())
    assert len(capturas) == 2


def test_cache_puede_desactivarse():
    capturas = []
    proveedor = VerificadorDestinosOpenRouteService(
        api_key="SINTETICA",
        transporte=transporte({"features": [feature()]}, capturas=capturas),
        reloj=lambda: AHORA,
        usar_cache=False,
    )
    proveedor.verificar(solicitud())
    proveedor.verificar(solicitud())
    assert len(capturas) == 2


def test_limite_local_impide_consulta_adicional():
    proveedor = verificador(limite_consultas=0)
    assert proveedor.verificar(solicitud()).estado == EstadoVerificacionDestino.CUOTA_AGOTADA
    assert proveedor.consultas_realizadas == 0


def test_error_de_conexion_no_rompe_motor():
    proveedor = VerificadorDestinosOpenRouteService(
        api_key="SINTETICA",
        transporte=lambda *_: (_ for _ in ()).throw(URLError("sin red")),
        reloj=lambda: AHORA,
    )
    resultado = proveedor.verificar(solicitud())
    propuesta = resolver_destino_con_verificacion("DESTINO ORIGINAL", (), resultado)
    assert resultado.estado == EstadoVerificacionDestino.ERROR_PROVEEDOR
    assert propuesta.valor_original == "DESTINO ORIGINAL"


def evidencia_interna(valor="DIRECCION INTERNA"):
    return Evidencia(
        "destino", valor, normalizar(valor), "catalogo_sintetico",
        TipoFuente.CATALOGO, 1.0, AHORA, referencia="CAT-1"
    )


def test_resultado_se_convierte_en_evidencia_externa():
    resultado = verificador().verificar(solicitud())
    evidencia = convertir_a_evidencia(resultado)
    assert evidencia.tipo_fuente == TipoFuente.VERIFICACION_EXTERNA
    assert evidencia.detalles["comuna"] == "COMUNA DEMO"


def test_contradiccion_externa_produce_revisar_y_conserva_original():
    resultado = verificador({"features": [feature(region="OTRA REGION")]}).verificar(solicitud())
    propuesta = resolver_destino_con_verificacion(
        "DIRECCION INTERNA", (evidencia_interna(),), resultado
    )
    assert propuesta.estado == EstadoPropuesta.REVISAR
    assert propuesta.valor_original == "DIRECCION INTERNA"


def test_explicacion_es_auditable():
    resultado = verificador().verificar(solicitud())
    propuesta = resolver_destino_con_verificacion(
        "DIRECCION INTERNA", (evidencia_interna(),), resultado
    )
    assert propuesta.explicacion
    assert propuesta.trazabilidad["puntajes"]


def test_resultado_sin_evidencia_no_se_acepta():
    resultado = verificador({"features": []}).verificar(solicitud())
    assert convertir_a_evidencia(resultado) is None
    assert resolver_destino_con_verificacion("ORIGINAL", (), resultado).valor_propuesto == "ORIGINAL"


def test_varias_respuestas_no_se_suman_como_fuentes():
    resultado = verificador({"features": [feature(), feature()]}).verificar(solicitud())
    assert convertir_a_evidencia(resultado) is None


def test_solicitud_y_catalogo_sintetico_no_se_modifican():
    catalogo = {"direccion": "CALLE SINTETICA 123"}
    original = dict(catalogo)
    pedido = solicitud(contexto_minimo=catalogo)
    verificador().verificar(pedido)
    assert catalogo == original


def test_determinismo_con_transporte_simulado():
    a = verificador().verificar(solicitud())
    b = verificador().verificar(solicitud())
    assert a == b


def test_importar_no_consulta_red(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *_: pytest.fail("red"))
    assert VerificadorDestinosOpenRouteService.__name__ == "VerificadorDestinosOpenRouteService"


def test_no_hay_consulta_automatica_al_construir():
    llamadas = []
    VerificadorDestinosOpenRouteService(
        api_key="SINTETICA", transporte=lambda *_: llamadas.append(1)
    )
    assert llamadas == []


def test_quince_campos_oficiales_permanecen_intactos():
    antes = tuple(COLUMNAS)
    verificador().verificar(solicitud())
    assert tuple(COLUMNAS) == antes and len(COLUMNAS) == 15
