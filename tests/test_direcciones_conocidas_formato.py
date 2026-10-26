"""Direcciones confirmadas reconocidas pese a diferencias de escritura/OCR
(26/10/2026). Destinos reales del catálogo: CAMINO LO RUIZ 2901 y 3099
(RENCA), PDTE. RIESCO 5903 (LAS CONDES), SANTA ISABEL 585 (LAMPA)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from atlas_core.catalogo_destinos import (
    consolidar_destinos_equivalentes, direccion_confirmada_coincide, forma_comparable_direccion,
)


def _coincide(calle, texto, comuna="RENCA"):
    return direccion_confirmada_coincide(calle, texto, comuna_confirmada=comuna)


@pytest.mark.parametrize("texto", [
    "CAMINO LO RUIZ 290I SANTIAGO RENCA",      # 482771: I leída por 1 al final
    "CAMINOLO RUIZ 2901 RENCA",                # palabras pegadas
    "CAMINO LORUIZ 2901",
    "CAMINO LO-RUIZ 2.901 RENCA",              # separador de miles
    "CAMINO LÓ RUÍZ 2901",                     # tildes
    "CAMINO LO RUIZ N° 2901",                  # marcador de número
    "CAM. LO RUIZ 2901 RENCA",                 # abreviatura de vía
    "camino lo ruiz, 2901, renca",             # minúsculas y comas
])
def test_variantes_de_formato_reconocen_la_direccion_confirmada(texto):
    assert _coincide("CAMINO LO RUIZ 2901", texto)
    assert not _coincide("CAMINO LO RUIZ 3099", texto)


@pytest.mark.parametrize("texto", [
    "CAMINO LO RUIZ 3099",                     # otra dirección real de la misma calle
    "CAMINO LO RUIZ 901 SANTIAGO RENCA",       # número incompleto (474065)
    "CAMINO LO RUIZ 2091 RENCA",               # dígitos permutados
    "CAMINO LO RUIZ 29011 RENCA",              # número más largo: antes coincidía por subcadena
    "CAMINO LO RUIZ 290I",                     # I final sin comuna que la respalde
    "AVENIDA LO RUIZ 2901 RENCA",              # otra vía
])
def test_numeraciones_distintas_nunca_se_fusionan(texto):
    assert not _coincide("CAMINO LO RUIZ 2901", texto)


def test_otras_direcciones_confirmadas_con_abreviaturas():
    assert _coincide("PDTE. RIESCO 5903", "PRESIDENTE RIESCO 5903 LAS CONDES", "LAS CONDES")
    assert not _coincide("PDTE. RIESCO 5903", "PDTE. RIESCO 6903", "LAS CONDES")  # 464653
    assert _coincide("AV, CENTRAL 8260", "AV. CENTRAL 8260 LO ESPEJO LO ESPEJO", "LO ESPEJO")
    assert _coincide("SANTA ISABEL 585", "STA ISABEL 585 SANTIAGO LAMPA", "LAMPA")


def test_forma_comparable_no_altera_numeros_ni_palabras():
    assert forma_comparable_direccion("Cam. Lo Ruiz N° 2901, Renca") == "CAMINO LO RUIZ 2901 RENCA"
    assert forma_comparable_direccion("NO HAY NUMERO") == "NO HAY NUMERO"


def _destino(direccion, comuna, lat=None, lon=None):
    return SimpleNamespace(direccion=direccion, comuna=comuna, latitud=lat, longitud=lon)


def test_misma_direccion_confirmada_dos_veces_es_una_sola_coincidencia():
    a = _destino("CAMINO LO RUIZ 2901, RENCA, CHILE", "RENCA", -33.402531, -70.686461)
    b = _destino("CAMINO LO RUIZ 2901", "RENCA", -33.402531, -70.686461)
    assert consolidar_destinos_equivalentes([a, b]) == [a]
    sin_coordenada = _destino("CAMINO LO RUIZ 2901", "RENCA")
    assert consolidar_destinos_equivalentes([sin_coordenada, b]) == [b]


@pytest.mark.parametrize("otro", [
    # Santa Isabel 585 real: mismas letras, coordenadas a ~600 m -> contradicción real.
    _destino("SANTA ISABEL 585", "LAMPA", -33.3076, -70.7331),
    _destino("SANTA ISABEL 595", "LAMPA", -33.3107, -70.7376),
    _destino("SANTA ISABEL 585", "COLINA", -33.3107, -70.7376),
])
def test_destinos_que_difieren_siguen_siendo_ambiguos(otro):
    base = _destino("SANTA ISABEL 585, LAMPA, CHILE", "LAMPA", -33.3107, -70.7376)
    assert consolidar_destinos_equivalentes([base, otro]) == [base, otro]
