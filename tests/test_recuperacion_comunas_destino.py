"""Recuperación de comunas que impedían calcular kilómetros (25/11/2026).

Casos reales:
- 492036 "APOQUINDO OE.605 PISO 6 6410 LAS CONDES": el número de la oficina
  (605) se leía como número de calle y rechazaba la geocodificación
  correcta (APOQUINDO 6410).
- Etiquetas del geocodificador con el número primero ("6410 Avenida
  Apoquindo, Santiago, RM, Chile") se rechazaban como DEMASIADO_GENERICA.
- 492008 "VISTA CLARA 2351 CERRILLOS" / 484015: el punto era correcto, pero
  la comuna publicada era la etiqueta de ciudad "Santiago".
"""
from __future__ import annotations

import pytest

from atlas_core.rutas.destino_entrega import (
    ESTADO_RESUELTO,
    ResultadoDestinoEntrega,
    _numero_calle,
    _numeros_de_calle,
    _nucleo_calle,
    motivo_incoherencia_destino_documental,
    precisar_comuna_tras_etiqueta_santiago,
    sin_complementos_direccion,
)
from atlas_core.rutas.modelos import Coordenadas


@pytest.mark.parametrize("texto,numero", [
    ("APOQUINDO OE.605 PISO 6 6410 LAS CONDES", "6410"),
    ("APOQUINDO OF. 605 PISO 6410", "6410"),          # "PISO 6410" no es un piso
    ("AV PROVIDENCIA 1208 OFICINA 1502 PROVIDENCIA", "1208"),
    ("OFICINA 1502 AV PROVIDENCIA 1208", "1208"),
    ("LOS LEONES 382 DEPTO 1504 PROVIDENCIA", "382"),
    ("SAN DIEGO LOCAL 12 2045 SANTIAGO", "2045"),
    ("VISTA CLARA 2351 CERRILLOS", "2351"),
    ("OFICINA 605", ""),                               # sólo complemento: sin número de calle
])
def test_numero_de_calle_ignora_complementos(texto, numero):
    assert _numero_calle(texto) == numero


def test_oe_sin_punto_no_es_complemento():
    assert sin_complementos_direccion("CALLE OE 120 MAIPU") == "CALLE OE 120 MAIPU"
    assert "605" not in _numeros_de_calle("APOQUINDO OE.605 PISO 6 6410 LAS CONDES")


def test_etiqueta_con_numero_primero_conserva_la_calle():
    assert _nucleo_calle("6410 Avenida Apoquindo, Santiago, RM, Chile") == {"APOQUINDO"}
    assert motivo_incoherencia_destino_documental(
        despachar_a_crudo="APOQUINDO OE.605 PISO 6 6410 LAS CONDES",
        etiqueta_geocodificada="6410 Avenida Apoquindo, Santiago, RM, Chile", localidad="Santiago") == ""


def test_numero_distinto_sigue_siendo_contradiccion():
    assert motivo_incoherencia_destino_documental(
        despachar_a_crudo="APOQUINDO OE.605 PISO 6 6410 LAS CONDES",
        etiqueta_geocodificada="6450 Avenida Apoquindo, Santiago, RM, Chile", localidad="Santiago",
    ).startswith("GEOCODIFICACION_NUMERO_INCOMPATIBLE")


def test_otra_calle_con_el_mismo_numero_sigue_rechazada():
    assert motivo_incoherencia_destino_documental(
        despachar_a_crudo="APOQUINDO OE.605 PISO 6 6410 LAS CONDES",
        etiqueta_geocodificada="6410 Latadia, Santiago, RM, Chile", localidad="Santiago",
    ) != ""


class BaseLocal:
    def __init__(self, cubre):
        self.cubre, self.consultas = cubre, []

    def comuna_cubre_punto(self, *, comuna, latitud, longitud, radio_m):
        self.consultas.append((comuna, radio_m))
        return self.cubre


def _resuelto(localidad="Santiago"):
    return ResultadoDestinoEntrega(
        despachar_a_crudo="VISTA CLARA 2351 CERRILLOS", coordenadas=Coordenadas(-70.715483, -33.523918),
        etiqueta_geocodificada="VISTA CLARA 2351 CERRILLOS", confianza=1.0, estado=ESTADO_RESUELTO,
        localidad=localidad, region="Metropolitana", codigo_pais="CL", codigo_unidad="13101", codigo_contexto="13")


def test_comuna_documental_reemplaza_la_etiqueta_santiago_si_la_base_local_confirma_el_punto():
    base = BaseLocal(True)
    r = precisar_comuna_tras_etiqueta_santiago(_resuelto(), despachar_a_crudo="VISTA CLARA 2351 CERRILLOS",
                                               base_geografica_local=base)
    assert (r.localidad, r.codigo_unidad, r.codigo_contexto) == ("Cerrillos", "13102", "13")
    assert r.coordenadas == _resuelto().coordenadas  # el punto nunca se mueve
    assert base.consultas == [("Cerrillos", 1000.0)]


@pytest.mark.parametrize("cubre", [False, None])
def test_sin_confirmacion_territorial_no_se_inventa_comuna(cubre):
    r = precisar_comuna_tras_etiqueta_santiago(_resuelto(), despachar_a_crudo="VISTA CLARA 2351 CERRILLOS",
                                               base_geografica_local=BaseLocal(cubre))
    assert r == _resuelto()


def test_sin_base_local_o_sin_comuna_documental_queda_igual():
    assert precisar_comuna_tras_etiqueta_santiago(
        _resuelto(), despachar_a_crudo="VISTA CLARA 2351 CERRILLOS", base_geografica_local=None) == _resuelto()
    assert precisar_comuna_tras_etiqueta_santiago(
        _resuelto(), despachar_a_crudo="PEDRO AGUIRRE CERDA 7060", base_geografica_local=BaseLocal(True)) == _resuelto()


def test_comuna_documental_y_humana_en_conflicto_se_abstiene():
    assert precisar_comuna_tras_etiqueta_santiago(
        _resuelto(), despachar_a_crudo="VISTA CLARA 2351 CERRILLOS", comuna_confirmada_humano="MAIPU",
        base_geografica_local=BaseLocal(True)) == _resuelto()


def test_localidad_ya_especifica_no_se_toca():
    especifica = _resuelto(localidad="Cerrillos")
    assert precisar_comuna_tras_etiqueta_santiago(
        especifica, despachar_a_crudo="VISTA CLARA 2351 CERRILLOS", base_geografica_local=BaseLocal(True)) == especifica
