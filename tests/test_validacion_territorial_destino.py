"""Validación territorial de coordenadas (25/11/2026).

Casos reales: HELSINSKI 5810 LA REINA (punto en Conchalí/Huechuraba),
AV. VICUNA MACKENNA 3451 SAN JOAQUIN SANTIAGO (punto en Santiago centro;
la base INE tiene la dirección exacta en San Joaquín), HOLANDA 2040
PROVIDENCIA PROVIDENCIA (centroide genérico; la base tiene la exacta).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from atlas_core.rutas import destino_entrega as de
from atlas_core.rutas.destino_entrega import (
    MOTIVO_FUERA_DE_COMUNA_CONOCIDA,
    _candidato_geocodificacion_desde_base_local,
    motivo_punto_fuera_de_comuna_conocida,
)
from atlas_core.rutas.modelos import CandidatoGeocodificacion, Coordenadas

CONCHALI = Coordenadas(longitud=-70.674204, latitud=-33.375286)
SAN_JOAQUIN_INE = Coordenadas(longitud=-70.620657, latitud=-33.484758)
SANTIAGO_CENTRO = Coordenadas(longitud=-70.631456, latitud=-33.449747)


class Base:
    """Base territorial falsa: qué comunas cubren el punto."""

    def __init__(self, cubiertas=(), sin_cobertura=()):
        self.cubiertas, self.sin_cobertura, self.consultas = set(cubiertas), set(sin_cobertura), []

    def comuna_cubre_punto(self, *, comuna, latitud, longitud, radio_m):
        self.consultas.append(comuna)
        if comuna in self.sin_cobertura:
            return None
        return comuna in self.cubiertas


@pytest.fixture
def sin_ine(monkeypatch):
    monkeypatch.setattr(de, "_candidato_geocodificacion_desde_base_local", lambda *a, **k: None)


def _ine(coordenadas):
    return CandidatoGeocodificacion(coordenadas=coordenadas, etiqueta="X [INE]", confianza=1.0)


def test_punto_en_otra_comuna_se_rechaza(sin_ine):
    motivo = motivo_punto_fuera_de_comuna_conocida(
        CONCHALI, Base(cubiertas={"Conchalí"}), comunas=("HELSINSKI 5810 LA REINA SANTIAGO",),
        despachar_a_crudo="HELSINSKI 5810 LA REINA SANTIAGO")
    assert motivo == f"{MOTIVO_FUERA_DE_COMUNA_CONOCIDA}: La Reina (punto en Conchalí)"


def test_punto_sin_cobertura_de_ninguna_comuna_no_se_rechaza(sin_ine):
    # Zona rural (p. ej. AZA COLINA): ninguna comuna tiene direcciones cerca.
    assert motivo_punto_fuera_de_comuna_conocida(
        CONCHALI, Base(), comunas=("PARAMERICANA NORTE 18500 COLINA",),
        despachar_a_crudo="PARAMERICANA NORTE 18500 COLINA") == ""


def test_punto_dentro_de_la_comuna_se_acepta(sin_ine):
    assert motivo_punto_fuera_de_comuna_conocida(
        CONCHALI, Base(cubiertas={"La Reina", "Conchalí"}), comunas=("HELSINSKI 5810 LA REINA",),
        despachar_a_crudo="HELSINSKI 5810 LA REINA") == ""


def test_comuna_fuera_de_la_base_no_decide(sin_ine):
    base = Base(cubiertas={"Santiago"}, sin_cobertura={"Concepción"})
    assert motivo_punto_fuera_de_comuna_conocida(
        SANTIAGO_CENTRO, base, comunas=("CONCEPCION",), despachar_a_crudo="SAN MARTIN 262") == ""


def test_etiqueta_de_ciudad_santiago_no_es_comuna_de_control(sin_ine):
    base = Base(cubiertas={"Conchalí"})
    assert motivo_punto_fuera_de_comuna_conocida(
        CONCHALI, base, comunas=("SANTIAGO",), despachar_a_crudo="HELSINSKI 5810 SANTIAGO") == ""
    assert base.consultas == []


def test_sin_base_o_sin_coordenadas_no_decide():
    assert motivo_punto_fuera_de_comuna_conocida(CONCHALI, None, comunas=("LA REINA",)) == ""
    assert motivo_punto_fuera_de_comuna_conocida(None, Base(), comunas=("LA REINA",)) == ""


def test_direccion_exacta_de_la_base_lejos_del_punto_se_rechaza(monkeypatch):
    monkeypatch.setattr(de, "_candidato_geocodificacion_desde_base_local", lambda *a, **k: _ine(SAN_JOAQUIN_INE))
    motivo = motivo_punto_fuera_de_comuna_conocida(
        SANTIAGO_CENTRO, Base(cubiertas={"Santiago"}),
        comunas=("AV. VICUNA MACKENNA 3451 SAN JOAQUIN SANTIAGO",),
        despachar_a_crudo="AV. VICUNA MACKENNA 3451 SAN JOAQUIN SANTIAGO")
    assert motivo == f"{MOTIVO_FUERA_DE_COMUNA_CONOCIDA}: San Joaquín (dirección exacta en la base territorial)"


def test_direccion_exacta_con_punto_sin_cobertura_tambien_se_corrige(monkeypatch):
    # HOLANDA 2040: centroide genérico donde ninguna comuna tiene direcciones.
    monkeypatch.setattr(de, "_candidato_geocodificacion_desde_base_local", lambda *a, **k: _ine(SAN_JOAQUIN_INE))
    assert motivo_punto_fuera_de_comuna_conocida(
        CONCHALI, Base(), comunas=("HOLANDA 2040 PROVIDENCIA PROVIDENCIA",),
        despachar_a_crudo="HOLANDA 2040 PROVIDENCIA PROVIDENCIA") != ""


def test_punto_dentro_de_la_comuna_no_se_mueve_aunque_la_base_tenga_otro_punto(monkeypatch):
    # Alcance: validación TERRITORIAL. Un punto dentro de su comuna no se
    # reemplaza por la dirección exacta de la base (eso sería otra política).
    monkeypatch.setattr(de, "_candidato_geocodificacion_desde_base_local", lambda *a, **k: _ine(SAN_JOAQUIN_INE))
    dentro = Coordenadas(longitud=-70.6100, latitud=-33.4950)
    assert motivo_punto_fuera_de_comuna_conocida(
        dentro, Base(cubiertas={"San Joaquín"}), comunas=("VICUNA MACKENNA 3451 SAN JOAQUIN",),
        despachar_a_crudo="VICUNA MACKENNA 3451 SAN JOAQUIN") == ""


def test_candidato_ine_consulta_calle_y_numero_con_la_comuna_conocida(monkeypatch):
    consultas = []

    def evidencia(base, texto, *, comuna=""):
        consultas.append((texto, comuna))
        if texto != "AVENIDA VICUNA MACKENNA 3451":
            return SimpleNamespace(resultado="CALLE_NO_ENCONTRADA", candidatos=())
        fila = SimpleNamespace(coordenadas=(-70.620657, -33.484758), numero_coincide=True, codigo_comuna="13129",
                               calle_canonica="VICUÑA MACKENNA", numero="3451", comuna_canonica="San Joaquín")
        return SimpleNamespace(resultado="DIRECCION_EXACTA", candidatos=(fila,))

    monkeypatch.setattr(de, "evidencia_local_para_direccion", evidencia)
    candidato = _candidato_geocodificacion_desde_base_local(
        object(), "AV. VICUNA MACKENNA 3451 SAN JOAQUIN SANTIAGO", comuna_territorial_conocida="San Joaquín")
    assert candidato is not None and candidato.localidad == "San Joaquín" and candidato.codigo_unidad == "13129"
    assert consultas == [("AV. VICUNA MACKENNA 3451 SAN JOAQUIN SANTIAGO", "San Joaquín"),
                         ("AVENIDA VICUNA MACKENNA 3451", "San Joaquín")]


def test_sin_comuna_conocida_no_reintenta(monkeypatch):
    consultas = []
    monkeypatch.setattr(de, "evidencia_local_para_direccion", lambda base, texto, *, comuna="": (
        consultas.append(texto) or SimpleNamespace(resultado="CALLE_NO_ENCONTRADA", candidatos=())))
    assert _candidato_geocodificacion_desde_base_local(object(), "HOLANDA 2040 PROVIDENCIA PROVIDENCIA") is None
    assert consultas == ["HOLANDA 2040 PROVIDENCIA PROVIDENCIA"]
