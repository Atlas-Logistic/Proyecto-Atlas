from copy import deepcopy
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
from atlas_core.rutas.proveedor import ProveedorRutasSimulado


RELOJ = lambda: datetime(2026, 7, 30, 20, 0, tzinfo=timezone.utc)
COLINA = Coordenadas(-70.704, -33.185)
RENCA = Coordenadas(-70.725, -33.403)
DESTINO = Coordenadas(-70.650, -33.450)


def solicitud(**cambios):
    datos = dict(
        id_origen_canonico="planta-renca",
        planta_salida="AZA Renca",
        direccion_origen="LA UNION 3070, RENCA, REGION METROPOLITANA",
        coordenadas_origen=RENCA,
        planta_resuelta=True,
        id_destino_canonico="destino-demo",
        destino="DESTINO DEMO",
        direccion_destino="AVENIDA DEMO 100, RENCA, REGION METROPOLITANA",
        coordenadas_destino=DESTINO,
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
        proveedor, cache, reloj=RELOJ
    ), proveedor, cache


def test_renca_a_destino_valido_entrega_contrato_completo():
    resultado = servicio()[0].calcular(solicitud())
    assert resultado.estado_calculo is EstadoCalculoMulticampo.CALCULADO
    assert resultado.id_origen_canonico == "planta-renca"
    assert resultado.planta_salida == "AZA Renca"
    assert resultado.distancia_ida_km == 12.5
    assert resultado.duracion_ida_minutos == 24.0
    assert resultado.fecha_calculo == "2026-07-30T20:00:00+00:00"
    assert resultado.fuente_coordenadas == "CATALOGO_CONFIRMADO"


def test_colina_a_destino_valido():
    resultado = servicio()[0].calcular(solicitud(
        id_origen_canonico="planta-colina",
        planta_salida="AZA Colina",
        direccion_origen="AV FREI MONTALVA 18500, COLINA, RM",
        coordenadas_origen=COLINA,
    ))
    assert resultado.estado_calculo is EstadoCalculoMulticampo.CALCULADO
    assert resultado.coordenadas_origen["latitud"] == COLINA.latitud


def test_mismo_destino_con_plantas_distintas_invoca_pares_distintos():
    srv, proveedor, _ = servicio()
    srv.calcular(solicitud())
    srv.calcular(solicitud(
        id_origen_canonico="planta-colina",
        planta_salida="AZA Colina",
        coordenadas_origen=COLINA,
        direccion_origen="AV FREI MONTALVA 18500, COLINA, RM",
    ))
    assert proveedor.llamadas_ruta == 2
    assert proveedor.pares_coordenadas[0] != proveedor.pares_coordenadas[1]


@pytest.mark.parametrize(
    ("cambios", "estado"),
    [
        ({"planta_resuelta": False}, EstadoCalculoMulticampo.PENDIENTE_PLANTA),
        ({"id_origen_canonico": ""}, EstadoCalculoMulticampo.PENDIENTE_PLANTA),
        ({"destino_resuelto": False}, EstadoCalculoMulticampo.PENDIENTE_DESTINO),
        ({"id_destino_canonico": ""}, EstadoCalculoMulticampo.PENDIENTE_DESTINO),
        ({"coordenadas_origen": None}, EstadoCalculoMulticampo.PENDIENTE_COORDENADAS),
        ({"coordenadas_destino": None}, EstadoCalculoMulticampo.PENDIENTE_COORDENADAS),
        ({"fuente_coordenadas": ""}, EstadoCalculoMulticampo.PENDIENTE_COORDENADAS),
    ],
)
def test_abstenciones_previas_no_invocan_proveedor(cambios, estado):
    srv, proveedor, _ = servicio()
    resultado = srv.calcular(solicitud(**cambios))
    assert resultado.estado_calculo is estado
    assert resultado.requiere_revision
    assert proveedor.llamadas_ruta == 0


@pytest.mark.parametrize(
    "coordenadas",
    [
        {"longitud": 181, "latitud": -33},
        {"longitud": -70, "latitud": 91},
        {"longitud": "x", "latitud": -33},
        (-70,),
    ],
)
def test_coordenadas_invalidas_se_abstienen(coordenadas):
    resultado = servicio()[0].calcular(
        solicitud(coordenadas_destino=coordenadas)
    )
    assert resultado.estado_calculo is EstadoCalculoMulticampo.PENDIENTE_COORDENADAS
    assert resultado.distancia_ida_km is None


def test_destino_o_planta_pendiente_se_modela_como_no_resuelto():
    srv, proveedor, _ = servicio()
    assert srv.calcular(solicitud(destino_resuelto=False)).razones == (
        "DESTINO_NO_RESUELTO",
    )
    assert srv.calcular(solicitud(planta_resuelta=False)).razones == (
        "PLANTA_NO_RESUELTA",
    )
    assert proveedor.llamadas_ruta == 0


def test_planta_contradictoria_exige_revision():
    resultado = servicio()[0].calcular(solicitud(
        planta_salida="PLANTA DESCONOCIDA",
        contradicciones=("OCR_COLINA_DOCUMENTO_RENCA",),
    ))
    assert resultado.estado_calculo is EstadoCalculoMulticampo.REQUIERE_REVISION


def test_ida_y_vuelta_es_derivada_y_separada():
    resultado = servicio()[0].calcular(solicitud(calcular_ida_vuelta=True))
    assert resultado.distancia_ida_km == 12.5
    assert resultado.distancia_ida_vuelta_km == 25.0


def test_redondeo_y_duracion_son_consistentes():
    proveedor = ProveedorRutasSimulado(
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 1.2345, 2.345)
    )
    resultado = servicio(proveedor)[0].calcular(solicitud())
    assert resultado.distancia_ida_km == 1.235
    assert resultado.duracion_ida_minutos == 2.35


def test_catalogos_y_solicitud_no_se_modifican():
    catalogo = {"plantas": [{"nombre": "AZA Renca"}]}
    antes = deepcopy(catalogo)
    req = solicitud(contexto={"catalogo": catalogo})
    servicio()[0].calcular(req)
    assert catalogo == antes
    assert req.contexto["catalogo"] is catalogo
