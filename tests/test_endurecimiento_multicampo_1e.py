import logging
import socket
from datetime import datetime, timezone

import pytest

from atlas_core.rutas import (
    CacheRutasMemoria,
    Coordenadas,
    EstadoCalculoMulticampo,
    ServicioRutasMulticampo,
    SolicitudRutaMulticampo,
)
from atlas_core.rutas.modelos import EstadoRuta, ResultadoRuta
from atlas_core.rutas.openrouteservice import OpenRouteService
from atlas_core.rutas.proveedor import ProveedorRutasSimulado


def solicitud(**cambios):
    datos = dict(
        id_origen_canonico="origen-1",
        planta_salida="AZA Renca",
        direccion_origen="LA UNION 3070, RENCA, RM",
        coordenadas_origen=Coordenadas(-70.725, -33.403),
        planta_resuelta=True,
        id_destino_canonico="destino-1",
        destino="DESTINO CONFIRMADO",
        direccion_destino="CALLE DEMO 100, RENCA, RM",
        coordenadas_destino=Coordenadas(-70.650, -33.450),
        destino_resuelto=True,
        proveedor="simulado",
        fuente_coordenadas="CATALOGO_CONFIRMADO",
    )
    datos.update(cambios)
    return SolicitudRutaMulticampo(**datos)


def servicio(proveedor=None, cache=None):
    proveedor = proveedor or ProveedorRutasSimulado()
    cache = cache or CacheRutasMemoria()
    return ServicioRutasMulticampo(
        proveedor, cache,
        reloj=lambda: datetime(2026, 7, 30, tzinfo=timezone.utc),
    ), proveedor, cache


def test_cache_reutiliza_calculo_identico_sin_duplicar():
    srv, proveedor, cache = servicio()
    primero = srv.calcular(solicitud())
    segundo = srv.calcular(solicitud())
    assert proveedor.llamadas_ruta == 1
    assert cache.cantidad() == 1
    assert segundo.desde_cache
    assert segundo.fecha_calculo == primero.fecha_calculo


@pytest.mark.parametrize(
    "cambios",
    [
        {"id_origen_canonico": "origen-2", "planta_salida": "AZA Colina"},
        {"id_destino_canonico": "destino-2"},
        {"coordenadas_destino": Coordenadas(-70.66, -33.46)},
        {"direccion_destino": "CALLE DEMO 101, RENCA, RM"},
        {"version_parametros": "rutas-1e-v2"},
        {"perfil_ruta": "driving-car"},
    ],
)
def test_cambios_semanticos_invalidan_clave_cache(cambios):
    srv, proveedor, cache = servicio()
    srv.calcular(solicitud())
    srv.calcular(solicitud(**cambios))
    assert proveedor.llamadas_ruta == 2
    assert cache.cantidad() == 2


@pytest.mark.parametrize(
    ("estado_proveedor", "estado_publico"),
    [
        (EstadoRuta.DIRECCION_NO_ENCONTRADA, EstadoCalculoMulticampo.SIN_RUTA),
        (EstadoRuta.SIN_CREDENCIAL, EstadoCalculoMulticampo.SIN_CREDENCIAL),
        (EstadoRuta.SIN_CONEXION, EstadoCalculoMulticampo.ERROR_PROVEEDOR),
        (EstadoRuta.LIMITE_CUOTA, EstadoCalculoMulticampo.ERROR_PROVEEDOR),
        (EstadoRuta.RESPUESTA_INVALIDA, EstadoCalculoMulticampo.ERROR_PROVEEDOR),
    ],
)
def test_estados_del_proveedor_se_traducen(estado_proveedor, estado_publico):
    proveedor = ProveedorRutasSimulado(
        resultado_ruta=ResultadoRuta(estado_proveedor)
    )
    resultado = servicio(proveedor)[0].calcular(solicitud())
    assert resultado.estado_calculo is estado_publico
    assert resultado.distancia_ida_km is None


def test_timeout_controlado():
    class Timeout(ProveedorRutasSimulado):
        def calcular_ruta(self, *_):
            raise socket.timeout()

    resultado = servicio(Timeout())[0].calcular(solicitud())
    assert resultado.estado_calculo is EstadoCalculoMulticampo.ERROR_PROVEEDOR
    assert resultado.razones == ("EXCEPCION_CONTROLADA_DEL_PROVEEDOR",)


def test_respuesta_mal_formada_controlada():
    class Malformado(ProveedorRutasSimulado):
        def calcular_ruta(self, *_):
            return type("R", (), {
                "estado": EstadoRuta.RUTA_CALCULADA,
                "distancia_km": "x",
                "duracion_estimada_min": 10,
                "motivo": "",
            })()

    assert (
        servicio(Malformado())[0].calcular(solicitud()).estado_calculo
        is EstadoCalculoMulticampo.ERROR_PROVEEDOR
    )


def test_error_no_elimina_dato_previo_valido():
    cache = CacheRutasMemoria()
    srv, proveedor, _ = servicio(cache=cache)
    previo = srv.calcular(solicitud())
    proveedor.resultado_ruta = ResultadoRuta(EstadoRuta.SIN_CONEXION)
    fallo = srv.calcular(solicitud(id_destino_canonico="destino-2"))
    assert fallo.estado_calculo is EstadoCalculoMulticampo.ERROR_PROVEEDOR
    assert cache.cantidad() == 1
    assert srv.calcular(solicitud()).fecha_calculo == previo.fecha_calculo


def test_cliente_chofer_material_no_eligen_planta():
    srv, proveedor, _ = servicio()
    resultado = srv.calcular(solicitud(
        planta_resuelta=False,
        contexto={
            "cliente": "CLIENTE DEMO",
            "chofer": "CHOFER DEMO",
            "material": "ACERO",
        },
    ))
    assert resultado.estado_calculo is EstadoCalculoMulticampo.PENDIENTE_PLANTA
    assert proveedor.llamadas_ruta == 0


def test_ors_sin_credencial_no_abre_red(monkeypatch):
    monkeypatch.delenv("OPENROUTESERVICE_API_KEY", raising=False)
    llamadas = []
    proveedor = OpenRouteService(transporte=lambda *_: llamadas.append(True))
    srv = ServicioRutasMulticampo(
        proveedor, CacheRutasMemoria()
    )
    resultado = srv.calcular(solicitud(proveedor="openrouteservice"))
    assert resultado.estado_calculo is EstadoCalculoMulticampo.SIN_CREDENCIAL
    assert llamadas == []


def test_api_key_no_aparece_en_logs_resultado_o_excepcion(monkeypatch, caplog):
    secreto = "SECRETO_1E_QUE_NO_DEBE_APARECER"
    monkeypatch.setenv("OPENROUTESERVICE_API_KEY", secreto)

    def fallar(*_):
        raise RuntimeError(f"Authorization={secreto}")

    proveedor = OpenRouteService(transporte=fallar)
    srv = ServicioRutasMulticampo(proveedor, CacheRutasMemoria())
    with caplog.at_level(logging.DEBUG):
        resultado = srv.calcular(solicitud(proveedor="openrouteservice"))
    assert secreto not in repr(resultado)
    assert secreto not in caplog.text


def test_no_geocodifica_direccion_ambigua():
    proveedor = ProveedorRutasSimulado()
    srv = ServicioRutasMulticampo(proveedor, CacheRutasMemoria())
    resultado = srv.calcular(solicitud(destino_resuelto=False))
    assert resultado.estado_calculo is EstadoCalculoMulticampo.PENDIENTE_DESTINO
    assert proveedor.llamadas_geocodificacion == 0
    assert proveedor.llamadas_ruta == 0


def test_resultado_y_coordenadas_son_inmutables():
    resultado = servicio()[0].calcular(solicitud())
    with pytest.raises(TypeError):
        resultado.coordenadas_origen["latitud"] = 0
