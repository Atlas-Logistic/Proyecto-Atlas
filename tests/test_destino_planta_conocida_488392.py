"""Caso real 488392 (viaje 0000370857): AZA COLINA como destino conocido.

La guía imprime "DESPACHAR A: PARAMERICANA NORTE 1850O SANTIAGO COLINA"
(PARAMERICANA en el documento, 1850O por OCR; el encabezado trae 18500).
Es la planta AZA COLINA, confirmada en el catálogo de plantas como "AV.
PDTE. EDUARDO FREI MONTALVA 18500, COLINA" (nombre oficial de la
Panamericana Norte en ese tramo), con punto de ruteo validado con GPS.

El geocodificador no ubica esa escritura (sólo el centro de Colina, a
~18 km del recinto) y la tolerancia OCR no componía la O final de la
numeración con la letra cambiada de la vía. Reconocer el destino no debe
depender del geocodificador ni de que el proveedor de rutas responda.
"""
from __future__ import annotations

import pytest

from atlas_core.catalogo_destinos import direccion_confirmada_coincide, variantes_nombre_via
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.rutas.destino_entrega import (
    METODO_PLANTA_CONOCIDA_CATALOGO,
    calcular_ruta_con_planta_conocida,
    calcular_ruta_entrega_para_viaje,
    planta_conocida_como_destino,
)
from atlas_core.rutas.modelos import Coordenadas, EstadoRuta, ResultadoRuta
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

DESPACHAR_A_488392 = "PARAMERICANA NORTE 1850O SANTIAGO COLINA"
PUNTO_RUTEO_COLINA = Coordenadas(-70.730387, -33.294752)
# Coordenada de texto de la planta (centro de Colina): nunca es el destino.
CENTRO_COLINA = Coordenadas(-70.665977, -33.137558)


def _crear(repo, **campos):
    base = dict(pais="CHILE", fuente="PRUEBA", region="RM", estado_calidad=EstadoCalidad.CONFIRMADA)
    base.update(campos)
    return repo.crear(**base)


@pytest.fixture
def catalogo(tmp_path):
    repo = CatalogoPlantas(tmp_path / "plantas.json")
    renca = _crear(
        repo, nombre="AZA RENCA", direccion="LA UNIÓN 3070", comuna="RENCA",
        latitud=-33.401595, longitud=-70.685226,
        punto_ruteo_latitud=-33.399989, punto_ruteo_longitud=-70.687632,
    )
    colina = _crear(
        repo, nombre="AZA COLINA", direccion="AV. PDTE. EDUARDO FREI MONTALVA 18500", comuna="COLINA",
        latitud=CENTRO_COLINA.latitud, longitud=CENTRO_COLINA.longitud,
        punto_ruteo_latitud=PUNTO_RUTEO_COLINA.latitud, punto_ruteo_longitud=PUNTO_RUTEO_COLINA.longitud,
    )
    return repo, renca, colina


def _proveedor(ruta=None):
    return ProveedorRutasSimulado(
        resultado_ruta=ruta or ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 13.6, 20.0, ""),
    )


# --- corroboración de la dirección -------------------------------------

def test_variante_oficial_y_comun_de_la_misma_via():
    assert variantes_nombre_via("AV. PDTE. EDUARDO FREI MONTALVA 18500") == ("PANAMERICANA NORTE 18500",)
    assert variantes_nombre_via("PANAMERICANA NORTE 18500") == ("PRESIDENTE EDUARDO FREI MONTALVA 18500",)
    assert variantes_nombre_via("LA UNION 3070") == ()
    # Nunca por prefijo de palabra: otra vía que sólo empieza igual.
    assert variantes_nombre_via("PANAMERICANA NORTEÑA 18500") == ()


@pytest.mark.parametrize("texto", [
    DESPACHAR_A_488392,
    "PARAMERICANA NORTE 185O0 SANTIAGO COLINA",  # 488100
    "PARAMERICANA NORTE 18500 SANTIAGO COLINA",  # 477043, 488237
])
def test_o_de_numeracion_se_compone_con_una_letra_de_la_via(texto):
    assert direccion_confirmada_coincide("PANAMERICANA NORTE 18500", texto, comuna_confirmada="COLINA")


@pytest.mark.parametrize("texto", [
    "PARAMERICANA NORTE 1860O SANTIAGO COLINA",   # otro número
    "PARAMERICANA NORTE 1850O SANTIAGO LAMPA",    # otra comuna
    "PARAMERICANO NORTI 1850O SANTIAGO COLINA",   # dos tokens alterados
    "PARAMERICANA NORTE 1850 SANTIAGO COLINA",    # falta un dígito
    "PARAMERICANA NORTE 18O500 SANTIAGO COLINA",  # número más largo
])
def test_composicion_no_afloja_las_anclas(texto):
    assert not direccion_confirmada_coincide("PANAMERICANA NORTE 18500", texto, comuna_confirmada="COLINA")


def test_composicion_exige_comuna_confirmada():
    assert not direccion_confirmada_coincide("PANAMERICANA NORTE 18500", "PARAMERICANA NORTE 1850O")


# --- reconocimiento de planta como destino -----------------------------

@pytest.mark.parametrize("texto", [
    DESPACHAR_A_488392,
    "PARAMERICANA NORTE 185O0 SANTIAGO COLINA",
    "PANAMERICANA NORTE 18500, COLINA",
    "AV PDTE EDUARDO FREI MONTALVA 18500 COLINA",
])
def test_reconoce_aza_colina(catalogo, texto):
    repo, _, colina = catalogo
    assert planta_conocida_como_destino(texto, repo.listar()).planta_id == colina.planta_id


def test_comuna_confirmada_por_humano_reemplaza_la_del_texto(catalogo):
    repo, _, colina = catalogo
    assert planta_conocida_como_destino("PARAMERICANA NORTE 18500", repo.listar()) is None
    planta = planta_conocida_como_destino(
        "PARAMERICANA NORTE 18500", repo.listar(), comuna_confirmada_humano="COLINA",
    )
    assert planta.planta_id == colina.planta_id


@pytest.mark.parametrize("texto", [
    "PANAMERICANA NORTE 22650 SANTIAGO LAMPA",       # AGF, destino de cliente
    "PARAMERICANA NORTE 1850O SANTIAGO LAMPA",
    "PARAMERICANA NORTE 1860O SANTIAGO COLINA",
    "AV. PDTE. EDUARDO FREI MONTALVA 20670 COLINA",  # Easy Retail, otro número
    "PRESIDENTE EDUARDO FREI MONTALVA 1850 COLINA",
    "CALLE COQUIMBO S/N SANTIAGO COLINA",
    "",
])
def test_no_reconoce_destinos_ajenos(catalogo, texto):
    repo, _, _ = catalogo
    assert planta_conocida_como_destino(texto, repo.listar()) is None


def test_comuna_explicita_incompatible_se_abstiene(catalogo):
    repo, _, _ = catalogo
    assert planta_conocida_como_destino("PANAMERICANA NORTE 18500 COLINA QUILICURA", repo.listar()) is None


def test_planta_de_origen_nunca_es_su_propio_destino(catalogo):
    repo, _, colina = catalogo
    assert planta_conocida_como_destino(DESPACHAR_A_488392, repo.listar(), planta_origen_id=colina.planta_id) is None


def test_planta_pendiente_inactiva_o_sin_coordenadas_no_cuenta(tmp_path):
    repo = CatalogoPlantas(tmp_path / "plantas.json")
    pendiente = _crear(
        repo, nombre="COLINA PENDIENTE", direccion="PANAMERICANA NORTE 18500", comuna="COLINA",
        latitud=-33.29, longitud=-70.73, estado_calidad=EstadoCalidad.PENDIENTE,
    )
    assert planta_conocida_como_destino(DESPACHAR_A_488392, repo.listar()) is None
    repo.editar(pendiente.planta_id, estado_calidad=EstadoCalidad.CONFIRMADA, limpiar_coordenadas=True)
    assert planta_conocida_como_destino(DESPACHAR_A_488392, repo.listar()) is None
    repo.editar(pendiente.planta_id, modificacion_manual=True, latitud=-33.29, longitud=-70.73)
    assert planta_conocida_como_destino(DESPACHAR_A_488392, repo.listar()) is not None
    repo.desactivar(pendiente.planta_id, modificacion_manual=True)
    assert planta_conocida_como_destino(DESPACHAR_A_488392, repo.listar()) is None


def test_dos_plantas_en_la_misma_direccion_es_ambiguo(catalogo):
    repo, _, _ = catalogo
    _crear(
        repo, nombre="OTRA COLINA", direccion="PANAMERICANA NORTE 18500", comuna="COLINA",
        latitud=-33.29, longitud=-70.73,
    )
    assert planta_conocida_como_destino(DESPACHAR_A_488392, repo.listar()) is None


# --- ruta: reconocimiento separado del proveedor -----------------------

def test_488392_ruta_al_punto_de_ruteo_sin_geocodificar(catalogo):
    repo, renca, _ = catalogo
    proveedor = _proveedor()
    resultado = calcular_ruta_con_planta_conocida(
        planta=renca, despachar_a_crudo=DESPACHAR_A_488392, proveedor_rutas=proveedor,
        origen_determinado_por="MOBILE", evidencia_origen="MOBILE_INFORMADO",
        plantas_conocidas=repo.listar(),
    )
    assert proveedor.llamadas_geocodificacion == 0
    assert resultado.estado_ruta == EstadoRuta.RUTA_CALCULADA.value
    assert resultado.metodo_confirmacion_destino == METODO_PLANTA_CONOCIDA_CATALOGO
    assert resultado.direccion_entrega_geocodificada == "AV. PDTE. EDUARDO FREI MONTALVA 18500, COLINA"
    assert (resultado.localidad_entrega, resultado.region_entrega, resultado.codigo_unidad) == (
        "Colina", "Metropolitana", "13301",
    )
    assert (float(resultado.latitud_entrega), float(resultado.longitud_entrega)) == (
        PUNTO_RUTEO_COLINA.latitud, PUNTO_RUTEO_COLINA.longitud,
    )
    # La evidencia documental y el origen informado se conservan.
    assert resultado.despachar_a_crudo == DESPACHAR_A_488392
    assert resultado.planta_origen_id == renca.planta_id
    assert resultado.origen_determinado_por == "MOBILE"


def test_proveedor_de_rutas_caido_no_borra_el_destino_reconocido(catalogo):
    repo, renca, _ = catalogo
    proveedor = _proveedor(ResultadoRuta(EstadoRuta.PROVEEDOR_NO_DISPONIBLE, motivo="PROVEEDOR_NO_DISPONIBLE"))
    resultado = calcular_ruta_con_planta_conocida(
        planta=renca, despachar_a_crudo=DESPACHAR_A_488392, proveedor_rutas=proveedor,
        plantas_conocidas=repo.listar(),
    )
    assert proveedor.llamadas_geocodificacion == 0
    assert resultado.estado_ruta == EstadoRuta.PROVEEDOR_NO_DISPONIBLE.value
    assert resultado.direccion_entrega_geocodificada == "AV. PDTE. EDUARDO FREI MONTALVA 18500, COLINA"
    assert resultado.distancia_km == ""


def test_sin_catalogo_de_plantas_comportamiento_previo(catalogo):
    _, renca, _ = catalogo
    proveedor = _proveedor()
    resultado = calcular_ruta_con_planta_conocida(
        planta=renca, despachar_a_crudo=DESPACHAR_A_488392, proveedor_rutas=proveedor,
    )
    assert proveedor.llamadas_geocodificacion > 0
    assert resultado.metodo_confirmacion_destino != METODO_PLANTA_CONOCIDA_CATALOGO


def test_ingesta_conserva_planta_de_origen_mobile(catalogo):
    repo, renca, _ = catalogo
    proveedor = _proveedor()
    resultado = calcular_ruta_entrega_para_viaje(
        despachar_a_crudo=DESPACHAR_A_488392, patente=None, instante_salida=None,
        plantas=repo.listar(), proveedor_posicion=None, proveedor_rutas=proveedor,
        codigo_planta_mobile="AZA_RENCA",
    )
    assert resultado.planta_origen_id == renca.planta_id
    assert resultado.estado_ruta == EstadoRuta.RUTA_CALCULADA.value
    assert resultado.metodo_confirmacion_destino == METODO_PLANTA_CONOCIDA_CATALOGO
    assert proveedor.llamadas_geocodificacion == 0


def test_ingesta_destino_de_cliente_sigue_geocodificando(catalogo):
    repo, _, _ = catalogo
    proveedor = _proveedor()
    resultado = calcular_ruta_entrega_para_viaje(
        despachar_a_crudo="PANAMERICANA NORTE 22650 SANTIAGO LAMPA", patente=None, instante_salida=None,
        plantas=repo.listar(), proveedor_posicion=None, proveedor_rutas=proveedor,
        codigo_planta_mobile="AZA_COLINA",
    )
    assert proveedor.llamadas_geocodificacion > 0
    assert resultado.metodo_confirmacion_destino != METODO_PLANTA_CONOCIDA_CATALOGO
