from __future__ import annotations

import pytest

from atlas_core.inteligencia.contrato_multicampo import EstadoResolucion
from atlas_core.inteligencia.resolucion_vehiculo import resolver_vehiculo_patente


def _vehiculo(patente: str, tipo: str, **extras):
    return {
        "vehiculo_id": extras.pop("vehiculo_id", f"id-{patente}"),
        "patente": patente,
        "tipo": tipo,
        "aliases": extras.pop("aliases", []),
        "estado_vigencia": "ACTIVO",
        "estado_calidad": "CONFIRMADO",
        **extras,
    }


CATALOGO = {
    "vehiculos": [
        _vehiculo("AABB11", "TRACTO"),
        _vehiculo("CCDD22", "RAMPLA"),
        _vehiculo("EEFF33", "TRACTO"),
        _vehiculo("GGHH44", "CAMION_CAJITA"),
    ]
}


@pytest.mark.parametrize("generica", ["", "AABB11", "CCDD22"])
def test_par_tracto_rampla_mantiene_identidad_patente_y_rol_coherentes(generica):
    resultado = resolver_vehiculo_patente(
        patente_tracto="AABB11",
        patente_rampla="CCDD22",
        patente=generica,
        catalogo=CATALOGO,
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.id_vehiculo_canonico == "id-AABB11"
    assert resultado.patente_canonica == "AABB11"
    assert resultado.rol_patente == "TRACTO"
    assert not resultado.contradicciones


@pytest.mark.parametrize("generica", ["EEFF33", "GGHH44"])
def test_tercera_patente_valida_incompatible_con_par_exige_revision(generica):
    resultado = resolver_vehiculo_patente(
        patente_tracto="AABB11",
        patente_rampla="CCDD22",
        patente=generica,
        catalogo=CATALOGO,
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.requiere_revision_humana
    assert resultado.contradicciones
    assert resultado.id_vehiculo_canonico == "id-AABB11"
    assert resultado.patente_canonica == "AABB11"
    assert resultado.rol_patente == "TRACTO"


def test_tercera_patente_inexistente_no_se_ignora_y_conserva_ocr():
    resultado = resolver_vehiculo_patente(
        patente_tracto="AABB11",
        patente_rampla="CCDD22",
        patente="IIJJ55",
        catalogo=CATALOGO,
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.contradicciones
    assert resultado.patente_original == "IIJJ55"
    assert resultado.patente_tracto_original == "AABB11"
    assert resultado.patente_rampla_original == "CCDD22"
    assert resultado.patente_canonica == "AABB11"


def test_tercera_patente_ambigua_no_confirma_el_par():
    catalogo = {
        "vehiculos": CATALOGO["vehiculos"] + [
            _vehiculo("KKLL66", "TRACTO", aliases=["MMNN77"]),
            _vehiculo("OOPP88", "TRACTO", aliases=["MMNN77"]),
        ]
    }
    resultado = resolver_vehiculo_patente(
        patente_tracto="AABB11",
        patente_rampla="CCDD22",
        patente="MMNN77",
        catalogo=catalogo,
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.patente_canonica == "AABB11"


def test_roles_intercambiados_no_pueden_confirmarse():
    resultado = resolver_vehiculo_patente(
        patente_tracto="CCDD22",
        patente_rampla="AABB11",
        catalogo=CATALOGO,
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.contradicciones
