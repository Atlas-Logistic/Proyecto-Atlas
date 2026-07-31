from __future__ import annotations

import pytest

from atlas_core.inteligencia.contrato_multicampo import EstadoResolucion
from atlas_core.inteligencia.resolucion_destino import resolver_destino_ubicacion


def _cliente(cliente_id: str):
    return {
        "cliente_id": cliente_id,
        "razon_social": f"CLIENTE {cliente_id}",
        "nombre_comercial": "",
        "rut": "",
        "aliases": [],
    }


def _destino(destino_id: str, cliente_id: str, **extras):
    registro = {
        "destino_id": destino_id,
        "cliente_id": cliente_id,
        "nombre_destino": "BODEGA ACEROS NORTE",
        "direccion": "CAMINO LO RUIZ 2901, RENCA, CHILE",
        "comuna": "RENCA",
        "region": "REGIÓN METROPOLITANA",
        "pais": "CHILE",
        "aliases": [],
        "estado_calidad": "CONFIRMADO",
        "estado_vigencia": "ACTIVO",
    }
    registro.update(extras)
    return registro


CLIENTES = {"clientes": [_cliente("cA"), _cliente("cB")]}
PLANTAS = {"plantas": []}


def _resolver(destinos, cliente="cB", **campos):
    return resolver_destino_ubicacion(
        catalogo_destinos={"destinos": destinos},
        catalogo_clientes=CLIENTES,
        catalogo_plantas=PLANTAS,
        id_cliente_canonico=cliente,
        **campos,
    )


@pytest.mark.parametrize(
    "campos",
    [
        {"obra_destino": "BODEGA ACEROS NORTE"},
        {
            "obra_destino": "BODEGA ACEROS NORT",
            "direccion": "CAMINO LO RUIS 2901",
        },
    ],
)
def test_destino_de_otro_cliente_nunca_confirma_por_ninguna_evidencia(campos):
    resultado = _resolver([_destino("obra-a", "cA")], **campos)
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.requiere_revision_humana
    assert resultado.contradicciones
    assert resultado.id_destino_canonico is None


def test_cliente_correcto_si_cambia_la_decision_del_caso_fuzzy_bloqueante():
    destinos = [_destino("obra-a", "cA")]
    campos = {
        "obra_destino": "BODEGA ACEROS NORT",
        "direccion": "CAMINO LO RUIS 2901",
    }
    correcto = _resolver(destinos, cliente="cA", **campos)
    incorrecto = _resolver(destinos, cliente="cB", **campos)
    assert correcto.estado is EstadoResolucion.CONFIRMADO
    assert correcto.id_destino_canonico == "obra-a"
    assert incorrecto.estado is EstadoResolucion.REQUIERE_REVISION
    assert incorrecto.id_destino_canonico is None


def test_relacion_cliente_destino_ausente_se_abstiene_conservadoramente():
    resultado = _resolver(
        [_destino("sin-relacion", "")],
        obra_destino="BODEGA ACEROS NORTE",
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.id_destino_canonico is None
    assert any("relación" in c.razon.lower() for c in resultado.contradicciones)


def test_destino_compartido_explicito_admite_ambos_clientes():
    destino = _destino(
        "compartido", "cA", clientes_ids=["cA", "cB"]
    )
    resultado = _resolver(
        [destino],
        obra_destino="BODEGA ACEROS NORTE",
        direccion="CAMINO LO RUIZ 2901",
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.id_destino_canonico == "compartido"


def test_mismo_nombre_para_dos_clientes_se_filtra_solo_con_relacion_explicita():
    destinos = [
        _destino("obra-a", "cA"),
        _destino("obra-b", "cB", direccion="OTRA CALLE 20, RENCA, CHILE"),
    ]
    resultado = _resolver(destinos, obra_destino="BODEGA ACEROS NORTE")
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.id_destino_canonico == "obra-b"


def test_sin_cliente_destino_puede_resolverse_conservadoramente():
    resultado = _resolver(
        [_destino("obra-a", "cA")],
        cliente="",
        obra_destino="BODEGA ACEROS NORTE",
        direccion="CAMINO LO RUIZ 2901",
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.id_destino_canonico == "obra-a"
