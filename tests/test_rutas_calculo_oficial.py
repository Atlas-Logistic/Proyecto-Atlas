from copy import deepcopy
from datetime import datetime, timezone
from importlib import reload
from types import SimpleNamespace

import pytest

import atlas_core.rutas.openrouteservice as modulo_ors
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.rutas.calculo import (
    PERFIL_PREDETERMINADO,
    PLANTAS_OPERACIONALES,
    CalculadorRutas,
    EstadoCalculoRuta,
    SolicitudCalculoRuta,
)
from atlas_core.rutas.modelos import Coordenadas, EstadoRuta, ResultadoRuta
from atlas_core.rutas.openrouteservice import OpenRouteService
from atlas_core.rutas.proveedor import ProveedorRutasSimulado


RELOJ = lambda: datetime(2026, 7, 28, 18, 0, tzinfo=timezone.utc)
ORIGEN = {"longitud": -70.70, "latitud": -33.40}
DESTINO = {"longitud": -70.60, "latitud": -33.50}


def solicitud(**cambios):
    datos = dict(
        planta="AZA Renca",
        planta_confirmada=True,
        coordenadas_origen=ORIGEN,
        destino="Destino sintético Ñuñoa",
        destino_confirmado=True,
        coordenadas_destino=DESTINO,
        proveedor="simulado",
        perfil=PERFIL_PREDETERMINADO,
        evidencia={"fuente": "fixture sintético"},
    )
    datos.update(cambios)
    return SolicitudCalculoRuta(**datos)


def calculador(proveedor=None):
    return CalculadorRutas(proveedor or ProveedorRutasSimulado(), reloj=RELOJ)


def test_ruta_simulada_valida_entrega_contrato_completo():
    resultado = calculador().calcular(solicitud())
    assert resultado.estado == EstadoCalculoRuta.CALCULADA
    assert resultado.distancia_metros == 12500
    assert resultado.distancia_kilometros == 12.5
    assert resultado.duracion_segundos == 1440
    assert resultado.duracion_legible == "24 min"
    assert resultado.fecha_calculo == "2026-07-28T18:00:00+00:00"
    assert resultado.requiere_revision is False


def test_resultado_simulado_es_determinista():
    calc = calculador()
    assert calc.calcular(solicitud()) == calc.calcular(solicitud())


@pytest.mark.parametrize("planta", ["AZA Renca", "AZA Colina"])
def test_soporta_dos_plantas_operacionales_confirmadas(planta):
    resultado = calculador().calcular(solicitud(planta=planta))
    assert resultado.estado == EstadoCalculoRuta.CALCULADA
    assert resultado.planta == planta
    assert planta.upper() in PLANTAS_OPERACIONALES


def test_planta_no_confirmada_no_invoca_proveedor():
    proveedor = ProveedorRutasSimulado()
    resultado = calculador(proveedor).calcular(
        solicitud(planta_confirmada=False)
    )
    assert resultado.estado == EstadoCalculoRuta.REVISAR
    assert resultado.error == "PLANTA_NO_CONFIRMADA"
    assert proveedor.llamadas_ruta == 0


def test_destino_no_confirmado_no_invoca_proveedor():
    proveedor = ProveedorRutasSimulado()
    resultado = calculador(proveedor).calcular(
        solicitud(destino_confirmado=False)
    )
    assert resultado.estado == EstadoCalculoRuta.REVISAR
    assert proveedor.llamadas_ruta == 0


@pytest.mark.parametrize(
    ("campo", "estado"),
    [
        ("coordenadas_origen", EstadoCalculoRuta.SIN_COORDENADAS_ORIGEN),
        ("coordenadas_destino", EstadoCalculoRuta.SIN_COORDENADAS_DESTINO),
    ],
)
def test_coordenadas_ausentes_tienen_estado_explicito(campo, estado):
    assert calculador().calcular(solicitud(**{campo: None})).estado == estado


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("coordenadas_origen", {"longitud": -70, "latitud": 91}),
        ("coordenadas_origen", {"longitud": 181, "latitud": -33}),
        ("coordenadas_destino", {"longitud": "texto", "latitud": -33}),
        ("coordenadas_destino", (-70,)),
    ],
)
def test_coordenadas_invalidas_no_lanzan_excepcion(campo, valor):
    resultado = calculador().calcular(solicitud(**{campo: valor}))
    assert resultado.estado == EstadoCalculoRuta.DATOS_INVALIDOS
    assert resultado.requiere_revision is True


@pytest.mark.parametrize("perfil", ["driving-hgv", "cycling-road", "perfil-2"])
def test_perfil_es_configurable_y_queda_registrado(perfil):
    proveedor = ProveedorRutasSimulado()
    resultado = calculador(proveedor).calcular(solicitud(perfil=perfil))
    assert resultado.perfil == perfil
    assert proveedor.perfiles_usados == [perfil]


def test_perfil_preferente_es_driving_hgv_sin_fallback():
    proveedor = ProveedorRutasSimulado(
        resultado_ruta=ResultadoRuta(EstadoRuta.PROVEEDOR_NO_DISPONIBLE)
    )
    resultado = calculador(proveedor).calcular(solicitud())
    assert resultado.estado == EstadoCalculoRuta.PROVEEDOR_NO_DISPONIBLE
    assert proveedor.perfiles_usados == ["driving-hgv"]


@pytest.mark.parametrize("perfil", ["", "../driving-car", "DRIVING HGV"])
def test_perfil_invalido_se_rechaza(perfil):
    assert (
        calculador().calcular(solicitud(perfil=perfil)).estado
        == EstadoCalculoRuta.DATOS_INVALIDOS
    )


def test_proveedor_seleccionado_debe_coincidir():
    resultado = calculador().calcular(
        solicitud(proveedor="otro-proveedor")
    )
    assert resultado.estado == EstadoCalculoRuta.PROVEEDOR_NO_DISPONIBLE


@pytest.mark.parametrize(
    ("estado_proveedor", "estado_publico"),
    [
        (EstadoRuta.SIN_CREDENCIAL, EstadoCalculoRuta.CREDENCIAL_NO_DISPONIBLE),
        (EstadoRuta.SIN_CONEXION, EstadoCalculoRuta.PROVEEDOR_NO_DISPONIBLE),
        (
            EstadoRuta.PROVEEDOR_NO_DISPONIBLE,
            EstadoCalculoRuta.PROVEEDOR_NO_DISPONIBLE,
        ),
        (EstadoRuta.RESPUESTA_INVALIDA, EstadoCalculoRuta.ERROR_PROVEEDOR),
        (EstadoRuta.LIMITE_CUOTA, EstadoCalculoRuta.ERROR_PROVEEDOR),
    ],
)
def test_estados_del_proveedor_se_traducen_sin_romper_atlas(
    estado_proveedor, estado_publico
):
    proveedor = ProveedorRutasSimulado(
        resultado_ruta=ResultadoRuta(estado_proveedor)
    )
    resultado = calculador(proveedor).calcular(solicitud())
    assert resultado.estado == estado_publico
    assert resultado.distancia_metros is None


def test_excepcion_del_proveedor_se_controla_y_no_expone_detalle():
    class ProveedorQueFalla(ProveedorRutasSimulado):
        def calcular_ruta(self, *_):
            raise RuntimeError("OPENROUTESERVICE_API_KEY=NO_MOSTRAR")

    resultado = calculador(ProveedorQueFalla()).calcular(solicitud())
    assert resultado.estado == EstadoCalculoRuta.ERROR_PROVEEDOR
    assert "NO_MOSTRAR" not in repr(resultado)


@pytest.mark.parametrize(
    ("distancia", "duracion"),
    [(-1, 10), (10, -1), (float("nan"), 10), (10, float("inf"))],
)
def test_metricas_invalidas_del_proveedor_se_rechazan(distancia, duracion):
    class ProveedorMalformado(ProveedorRutasSimulado):
        def calcular_ruta(self, *_):
            return SimpleNamespace(
                estado=EstadoRuta.RUTA_CALCULADA,
                distancia_km=distancia,
                duracion_estimada_min=duracion,
                motivo="",
            )

    resultado = calculador(ProveedorMalformado()).calcular(solicitud())
    assert resultado.estado == EstadoCalculoRuta.ERROR_PROVEEDOR


def test_orden_longitud_latitud_llega_sin_inversion_al_proveedor():
    proveedor = ProveedorRutasSimulado()
    calculador(proveedor).calcular(solicitud())
    origen, destino = proveedor.pares_coordenadas[0]
    assert origen == Coordenadas(-70.70, -33.40)
    assert destino == Coordenadas(-70.60, -33.50)


def test_evidencia_original_se_conserva_ante_error_y_es_inmutable():
    evidencia = {"archivo": "ruta con espacios/guía Ñ.jpg", "texto": "Árbol"}
    resultado = calculador().calcular(
        solicitud(planta_confirmada=False, evidencia=evidencia)
    )
    evidencia["texto"] = "cambiado"
    assert resultado.evidencia["texto"] == "Árbol"
    with pytest.raises(TypeError):
        resultado.evidencia["nuevo"] = "valor"


def test_catalogo_de_entrada_no_se_modifica():
    registro = {"planta": "AZA Renca", "coordenadas": deepcopy(ORIGEN)}
    antes = deepcopy(registro)
    calculador().calcular(
        solicitud(
            planta=registro["planta"],
            coordenadas_origen=registro["coordenadas"],
        )
    )
    assert registro == antes


def test_destinos_similares_con_coordenadas_distintas_no_se_confunden():
    primero = calculador().calcular(
        solicitud(destino="LAS FLORES 10", coordenadas_destino=(-70.60, -33.50))
    )
    segundo = calculador().calcular(
        solicitud(destino="LAS FLORES 11", coordenadas_destino=(-70.61, -33.51))
    )
    assert primero.destino != segundo.destino
    assert primero.coordenadas_destino != segundo.coordenadas_destino


def test_importar_modulo_no_realiza_consulta_externa(monkeypatch):
    llamadas = []
    monkeypatch.setattr(modulo_ors, "urlopen", lambda *_a, **_k: llamadas.append(1))
    reload(modulo_ors)
    assert llamadas == []


def test_ausencia_credencial_ors_no_rompe_calculador(monkeypatch):
    monkeypatch.delenv("OPENROUTESERVICE_API_KEY", raising=False)
    resultado = CalculadorRutas(OpenRouteService(), reloj=RELOJ).calcular(
        solicitud(proveedor="openrouteservice")
    )
    assert resultado.estado == EstadoCalculoRuta.CREDENCIAL_NO_DISPONIBLE


def test_quince_campos_oficiales_del_lector_no_se_alteran():
    antes = tuple(COLUMNAS)
    calculador().calcular(solicitud())
    assert tuple(COLUMNAS) == antes
    assert len(COLUMNAS) == 15
