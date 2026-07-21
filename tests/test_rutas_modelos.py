from datetime import datetime, timezone

import pytest

from atlas_core.rutas.modelos import Coordenadas, ErrorRutas, EstadoRuta, ResultadoRuta


def test_estados_minimos_estan_disponibles():
    esperados = {
        "RUTA_CALCULADA", "RESULTADO_DESDE_CACHE", "SIN_CREDENCIAL",
        "SIN_CONEXION", "DIRECCION_NO_ENCONTRADA", "RESULTADO_AMBIGUO",
        "PROVEEDOR_NO_DISPONIBLE", "LIMITE_CUOTA", "RESPUESTA_INVALIDA",
        "REQUIERE_REVISION",
    }
    assert {estado.value for estado in EstadoRuta} == esperados


@pytest.mark.parametrize(
    ("longitud", "latitud"),
    [(181, 0), (-181, 0), (0, 91), (0, -91), (float("inf"), 0)],
)
def test_coordenadas_invalidas_se_rechazan(longitud, latitud):
    with pytest.raises(ErrorRutas):
        Coordenadas(longitud, latitud)


def test_coordenadas_explicitan_orden_longitud_latitud():
    coordenadas = Coordenadas(longitud=-20.0, latitud=-10.0)
    assert coordenadas.a_dict() == {"longitud": -20.0, "latitud": -10.0}


def test_ruta_calculada_requiere_distancia_y_duracion_positivas():
    with pytest.raises(ErrorRutas):
        ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 0, 10)
    with pytest.raises(ErrorRutas):
        ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 10, 0)
    resultado = ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 10.5, 20.25)
    assert resultado.distancia_km > 0
    assert resultado.duracion_estimada_min > 0


def test_fallo_no_puede_disfrazarse_como_distancia_cero():
    with pytest.raises(ErrorRutas):
        ResultadoRuta(EstadoRuta.SIN_CONEXION, 0, 0)
    assert ResultadoRuta(EstadoRuta.SIN_CONEXION).distancia_km is None
