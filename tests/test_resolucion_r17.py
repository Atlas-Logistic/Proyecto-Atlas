"""Bloque RESOLUCIÓN R17 -- cierre de los viajes reales sin km/tiempo:
"SANTIAGO" como etiqueta de ciudad/área metropolitana, cuando aparece
junto a otra comuna real distinta, se quita SÓLO de la consulta que se
envía al geocodificador (nunca del texto documental almacenado) --
casos reales 472018 (CAMINO LOS PINOS 3396 SANTIAGO SAN BERNARDO, 5
candidatos dispersos -> 1 inequívoco) y 464981 (CAMINO A MELIPILLA
10800 SANTIAGO MAIPU)."""
from __future__ import annotations

from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.rutas.destino_entrega import (
    _texto_geocodificable_sin_etiqueta_ciudad_santiago,
    calcular_ruta_con_planta_conocida,
)
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion, ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

COORD_AZA_COLINA = Coordenadas(-70.669, -33.201)


def _planta(tmp_path):
    plantas = CatalogoPlantas(tmp_path / "plantas.json")
    return plantas.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        direccion="RUTA 5", comuna="COLINA", region="RM",
        latitud=COORD_AZA_COLINA.latitud, longitud=COORD_AZA_COLINA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )


def test_quita_santiago_cuando_hay_otra_comuna_real():
    texto = "CAMINO LOS PINOS 3396 SANTIAGO SAN BERNARDO"
    assert _texto_geocodificable_sin_etiqueta_ciudad_santiago(texto) == "CAMINO LOS PINOS 3396 SAN BERNARDO"


def test_quita_santiago_caso_real_464981():
    texto = "CAMINO A MELIPILLA 10800 SANTIAGO MAIPU"
    assert _texto_geocodificable_sin_etiqueta_ciudad_santiago(texto) == "CAMINO A MELIPILLA 10800 MAIPU"


def test_conserva_santiago_si_es_la_unica_comuna_mencionada():
    """Control -- sin ninguna otra comuna real en el texto, "Santiago"
    podría ser genuinamente la comuna real de entrega; nunca se quita."""
    texto = "ALGUNA CALLE 100 SANTIAGO"
    assert _texto_geocodificable_sin_etiqueta_ciudad_santiago(texto) == texto


def test_conserva_texto_sin_ninguna_comuna_reconocida():
    texto = "VICUÑA MACKENNA 655"
    assert _texto_geocodificable_sin_etiqueta_ciudad_santiago(texto) == texto


def test_caso_real_472018_multiples_dispersos_se_resuelve(tmp_path):
    """E2E completo -- caso real 472018 (SALOMON SACK SA SAN BERNARDO):
    con "SANTIAGO" en la consulta el proveedor real devolvía 5
    candidatos dispersos; sin él, un único candidato inequívoco -- nunca
    se adivina, el propio geocodificador deja de dispersarse."""
    planta = _planta(tmp_path)
    consulta_limpia = "CAMINO LOS PINOS 3396 SAN BERNARDO, Chile"
    proveedor = ProveedorRutasSimulado(
        geocodificaciones={
            consulta_limpia: ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(Coordenadas(-70.7056, -33.5702), "Camino Los Pinos, San Bernardo, RM, Chile", 0.8, "San Bernardo", "Metropolitana"),),
                "RESUELTO",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 22.4, 30.0, "SINTETICO"),
    )
    resultado = calcular_ruta_con_planta_conocida(
        planta=planta, despachar_a_crudo="CAMINO LOS PINOS 3396 SANTIAGO SAN BERNARDO", proveedor_rutas=proveedor,
    )
    assert resultado.estado_ruta == EstadoRuta.RUTA_CALCULADA.value
    assert resultado.distancia_km == "22.4"
    # El texto documental ORIGINAL (con "SANTIAGO") se conserva como
    # destino operacional mostrado -- sólo la consulta interna cambió.
    assert resultado.despachar_a_crudo == "CAMINO LOS PINOS 3396 SANTIAGO SAN BERNARDO"
