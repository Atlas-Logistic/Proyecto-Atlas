from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from atlas_core.inteligencia import (
    EstadoCoincidenciaDireccion,
    EstadoVerificacionDestino,
    SolicitudVerificacionDestino,
    VerificadorDestinosOpenRouteService,
    comparar_direccion,
    normalizar_region_chile,
)
from atlas_core.inteligencia.verificacion_destinos import RespuestaHTTPDestino


AHORA = datetime(2026, 7, 28, tzinfo=timezone.utc)


def comparar(direccion_esperada="AVENIDA CENTRAL 123",
             direccion_encontrada="AVENIDA CENTRAL 123",
             comuna_esperada="CERRILLOS", comuna_encontrada="CERRILLOS",
             region_esperada="REGIÓN METROPOLITANA",
             region_encontrada="METROPOLITANA", coordenadas_validas=True):
    return comparar_direccion(
        direccion_esperada=direccion_esperada,
        direccion_encontrada=direccion_encontrada,
        comuna_esperada=comuna_esperada,
        comuna_encontrada=comuna_encontrada,
        region_esperada=region_esperada,
        region_encontrada=region_encontrada,
        coordenadas_validas=coordenadas_validas,
    )


@pytest.mark.parametrize("alias", [
    "REGIÓN METROPOLITANA", "REGION METROPOLITANA", "METROPOLITANA", "RM",
    "REGIÓN METROPOLITANA DE SANTIAGO", "METROPOLITANA DE SANTIAGO",
])
def test_alias_metropolitanos_tienen_un_canonico(alias):
    resultado = normalizar_region_chile(alias)
    assert resultado.canonico == "REGIÓN METROPOLITANA"
    assert resultado.reconocido
    assert resultado.original == alias


def test_transformacion_de_region_es_trazable():
    resultado = normalizar_region_chile("RM")
    assert resultado.transformaciones
    assert "REGIÓN METROPOLITANA" in resultado.transformaciones[-1]


@pytest.mark.parametrize("comuna", ["CERRILLOS", "QUILICURA"])
def test_santiago_no_equivale_a_comuna_especifica(comuna):
    resultado = comparar(comuna_esperada=comuna, comuna_encontrada="SANTIAGO")
    assert resultado.estado == EstadoCoincidenciaDireccion.CONTRADICCION_COMUNA
    assert not resultado.confirmable


def test_calle_correcta_sin_numero_no_confirma():
    resultado = comparar(direccion_encontrada="AVENIDA CENTRAL")
    assert resultado.estado == EstadoCoincidenciaDireccion.COINCIDENCIA_PARCIAL_SIN_NUMERO
    assert not resultado.confirmable


def test_numero_correcto_con_abreviatura_controlada():
    resultado = comparar(
        direccion_esperada="AVENIDA PRESIDENTE RIESCO 123",
        direccion_encontrada="AV. PDTE. RIESCO 123",
    )
    assert resultado.estado == EstadoCoincidenciaDireccion.COINCIDENCIA_NORMALIZADA
    assert resultado.confirmable


def test_numero_diferente_es_contradiccion():
    resultado = comparar(direccion_encontrada="AVENIDA CENTRAL 124")
    assert resultado.estado == EstadoCoincidenciaDireccion.CONTRADICCION_NUMERO
    assert not resultado.confirmable


def test_comuna_diferente_es_contradiccion():
    assert comparar(comuna_encontrada="LAMPA").estado == (
        EstadoCoincidenciaDireccion.CONTRADICCION_COMUNA
    )


def test_region_diferente_es_contradiccion():
    assert comparar(region_encontrada="VALPARAÍSO").estado == (
        EstadoCoincidenciaDireccion.CONTRADICCION_REGION
    )


def test_calle_con_tilde_compara_sin_fuzzy():
    resultado = comparar(
        direccion_esperada="AVENIDA UNIÓN 123",
        direccion_encontrada="AVENIDA UNION 123",
    )
    assert resultado.confirmable


def test_avenida_abreviada():
    assert comparar(
        direccion_esperada="AVENIDA CENTRAL 123",
        direccion_encontrada="AV. CENTRAL 123",
    ).confirmable


def test_camino_abreviado():
    assert comparar(
        direccion_esperada="CAMINO CENTRAL 123",
        direccion_encontrada="CAM. CENTRAL 123",
    ).confirmable


def test_sin_numero_debe_coincidir_expresamente():
    resultado = comparar(
        direccion_esperada="CAMINO EL MONTE S/N",
        direccion_encontrada="CAM. EL MONTE S/N",
    )
    assert resultado.confirmable
    assert resultado.numero_coincide


def test_ruta_con_kilometro_no_pierde_el_kilometro():
    bien = comparar(
        direccion_esperada="RUTA 5 KM 40 S/N",
        direccion_encontrada="RUTA 5 KM 40 S/N",
    )
    mal = comparar(
        direccion_esperada="RUTA 5 KM 40 S/N",
        direccion_encontrada="RUTA 5 KM 41 S/N",
    )
    assert bien.confirmable
    assert not mal.confirmable


def test_complemento_de_fundo_no_cambia_numero():
    resultado = comparar(
        direccion_esperada="CALLE INTERIOR 700, FUNDO LA MONTAÑA",
        direccion_encontrada="CALLE INTERIOR 700, FUNDO LA MONTAÑA",
    )
    assert resultado.numero_coincide and resultado.confirmable


def test_direccion_generica_no_confirma():
    resultado = comparar(direccion_encontrada="SANTIAGO, CHILE")
    assert resultado.estado in {
        EstadoCoincidenciaDireccion.RESPUESTA_GENERICA,
        EstadoCoincidenciaDireccion.CONTRADICCION_COMUNA,
    }
    assert not resultado.confirmable


def test_resultado_sin_propiedades_administrativas_no_confirma():
    resultado = comparar(comuna_encontrada="", region_encontrada="")
    assert not resultado.confirmable


def test_coordenadas_validas_no_compensan_direccion_contradictoria():
    resultado = comparar(
        direccion_encontrada="AVENIDA CENTRAL 999",
        coordenadas_validas=True,
    )
    assert resultado.estado == EstadoCoincidenciaDireccion.CONTRADICCION_NUMERO
    assert not resultado.confirmable


def test_original_se_preserva_en_componentes():
    original = "Av. Presidente Riesco 123"
    assert comparar(direccion_esperada=original).componentes_esperados.original == original


def _feature(label, comuna="RENCA", region="Metropolitana"):
    return {
        "geometry": {"coordinates": [-70.685, -33.401]},
        "properties": {
            "label": label, "localadmin": comuna, "locality": "Santiago",
            "region": region, "country": "Chile", "confidence": 0.9,
        },
    }


def _verificar(features):
    proveedor = VerificadorDestinosOpenRouteService(
        api_key="SINTETICA",
        transporte=lambda *_: RespuestaHTTPDestino(
            200, json.dumps({"features": features}).encode()
        ),
        reloj=lambda: AHORA,
        monotono=lambda: 10.0,
    )
    return proveedor.verificar(SolicitudVerificacionDestino(
        direccion_original="LA UNION 3070",
        comuna_esperada="RENCA",
        region_esperada="REGIÓN METROPOLITANA",
        pais="CHILE",
        autorizacion_externa=True,
        campos_autorizados=frozenset({
            "direccion_original", "comuna_esperada", "region_esperada", "pais"
        }),
    ))


def test_unico_candidato_normalizado_confirma_la_union():
    resultado = _verificar([_feature("3070 La Union, Renca, RM, Chile")])
    assert resultado.estado == EstadoVerificacionDestino.VERIFICADA
    assert resultado.tipo_coincidencia == "COINCIDENCIA_NORMALIZADA"
    assert resultado.detalle_comparacion["region_canonica"] == "REGIÓN METROPOLITANA"


def test_dos_candidatos_compatibles_siguen_ambiguos():
    resultado = _verificar([
        _feature("3070 La Union, Renca, RM, Chile"),
        _feature("La Union 3070, Renca, RM, Chile"),
    ])
    assert resultado.estado == EstadoVerificacionDestino.REVISAR
    assert resultado.tipo_coincidencia == "AMBIGUA"
