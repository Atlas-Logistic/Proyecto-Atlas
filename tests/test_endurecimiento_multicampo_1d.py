from __future__ import annotations

import hashlib
import json

from atlas_core.inteligencia.contrato_multicampo import EstadoResolucion
from atlas_core.inteligencia.politica_confianza_destino import (
    POLITICA_CONFIANZA_DESTINO_V1,
    PoliticaConfianzaDestino,
    ViaDecisionDestino,
)
from atlas_core.inteligencia.resolucion_destino import (
    auditar_catalogo_destinos,
    resolver_destino_ubicacion,
)
from atlas_core.inteligencia.snapshot_catalogo_destinos import (
    crear_snapshot_catalogo_destinos,
)


def _cliente(cliente_id="cox", nombre="ACEROS COX COMERCIAL SA"):
    return {
        "cliente_id": cliente_id,
        "razon_social": nombre,
        "nombre_comercial": "",
        "rut": "77004250-K",
        "aliases": [],
    }


def _destino(
    destino_id="cox-renca",
    cliente_id="cox",
    calidad="PENDIENTE",
    **cambios,
):
    base = {
        "destino_id": destino_id,
        "cliente_id": cliente_id,
        "nombre_destino": "CAMINO LO RUIZ 2901",
        "direccion": "CAMINO LO RUIZ 2901, RENCA, CHILE",
        "comuna": "RENCA",
        "region": "RM",
        "pais": "CHILE",
        "aliases": [],
        "estado_calidad": calidad,
        "estado_vigencia": "ACTIVO",
    }
    base.update(cambios)
    return base


def _plantas():
    return {
        "plantas": [
            {
                "planta_id": "colina",
                "nombre": "AZA COLINA",
                "direccion": "AV. PDTE. EDUARDO FREI MONTALVA 18500",
                "comuna": "COLINA",
                "region": "REGIÓN METROPOLITANA",
                "estado_calidad": "CONFIRMADA",
                "estado_vigencia": "ACTIVA",
            },
            {
                "planta_id": "renca",
                "nombre": "AZA RENCA",
                "direccion": "LA UNIÓN 3070",
                "comuna": "RENCA",
                "region": "REGIÓN METROPOLITANA",
                "estado_calidad": "CONFIRMADA",
                "estado_vigencia": "ACTIVA",
            },
        ]
    }


def test_caso_cox_existe_pero_pendiente_y_compartido_requiere_revision():
    destinos = {
        "destinos": [
            _destino(),
            _destino(
                "sodimac-renca", "sodimac",
                nombre_destino="CAMINO LO RUIZ 2901",
            ),
        ]
    }
    clientes = {
        "clientes": [
            _cliente(),
            _cliente("sodimac", "SODIMAC SA"),
        ]
    }
    resultado = resolver_destino_ubicacion(
        obra_destino="CAMINO LO RUIZ 2901",
        direccion="CAMINO LO RUIZ 2901, RENCA",
        comuna="RENCA",
        region="REGIÓN METROPOLITANA",
        id_cliente_canonico="cox",
        catalogo_destinos=destinos,
        catalogo_clientes=clientes,
        catalogo_plantas=_plantas(),
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.id_destino_canonico == "cox-renca"
    assert resultado.via_decision == "CALIDAD_INCOMPLETA"
    assert resultado.direccion_canonica == (
        "CAMINO LO RUIZ 2901, RENCA, CHILE"
    )


def test_cliente_no_fuerza_cox_sin_evidencia_destino():
    resultado = resolver_destino_ubicacion(
        id_cliente_canonico="cox",
        catalogo_destinos={"destinos": [_destino()]},
        catalogo_clientes={"clientes": [_cliente()]},
        catalogo_plantas=_plantas(),
    )
    assert resultado.estado is EstadoResolucion.NO_RESUELTO
    assert resultado.entidad is None


def test_fuzzy_aislado_no_confirma_aunque_politica_valga_uno():
    valores = dict(POLITICA_CONFIANZA_DESTINO_V1.valores)
    valores[ViaDecisionDestino.FUZZY_O_PARCIAL] = 1.0
    politica = PoliticaConfianzaDestino("prueba", valores)
    resultado = resolver_destino_ubicacion(
        obra_destino="CAMINO LO RUI2 2901",
        catalogo_destinos={
            "destinos": [_destino(calidad="CONFIRMADO")]
        },
        catalogo_clientes={"clientes": [_cliente()]},
        catalogo_plantas=_plantas(),
        politica_confianza=politica,
    )
    assert resultado.estado is EstadoResolucion.PROPUESTO
    assert resultado.confianza < 1.0


def test_destino_incompleto_es_auditable_y_revisable():
    destinos = {
        "destinos": [
            _destino(calidad="CONFIRMADO", comuna="")
        ]
    }
    clientes = {"clientes": [_cliente()]}
    snapshot = crear_snapshot_catalogo_destinos(
        destinos, clientes, _plantas()
    )
    assert any(
        h.codigo == "DESTINO_INCOMPLETO"
        for h in auditar_catalogo_destinos(snapshot)
    )
    resultado = resolver_destino_ubicacion(
        obra_destino="CAMINO LO RUIZ 2901",
        catalogo_destinos=snapshot,
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION


def test_planta_desconocida_no_se_convierte_en_colina():
    resultado = resolver_destino_ubicacion(
        obra_destino="CAMINO LO RUIZ 2901",
        planta_salida="PLANTA DESCONOCIDA",
        catalogo_destinos={
            "destinos": [_destino(calidad="CONFIRMADO")]
        },
        catalogo_clientes={"clientes": [_cliente()]},
        catalogo_plantas=_plantas(),
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.planta_salida_canonica is None


def test_region_rm_y_forma_desarrollada_son_equivalentes():
    resultado = resolver_destino_ubicacion(
        obra_destino="CAMINO LO RUIZ 2901",
        comuna="RENCA",
        region="Metropolitana",
        catalogo_destinos={
            "destinos": [_destino(calidad="CONFIRMADO")]
        },
        catalogo_clientes={"clientes": [_cliente()]},
        catalogo_plantas=_plantas(),
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.region_canonica == "REGIÓN METROPOLITANA"


def test_orden_catalogo_no_cambia_resultado():
    registros = [
        _destino(calidad="CONFIRMADO"),
        _destino(
            "otro", "cox", calidad="CONFIRMADO",
            nombre_destino="OTRA OBRA", direccion="OTRA CALLE 1, RENCA",
        ),
    ]
    clientes = {"clientes": [_cliente()]}
    uno = resolver_destino_ubicacion(
        obra_destino="CAMINO LO RUIZ 2901",
        catalogo_destinos={"destinos": registros},
        catalogo_clientes=clientes,
        catalogo_plantas=_plantas(),
    )
    dos = resolver_destino_ubicacion(
        obra_destino="CAMINO LO RUIZ 2901",
        catalogo_destinos={"destinos": list(reversed(registros))},
        catalogo_clientes=clientes,
        catalogo_plantas=_plantas(),
    )
    assert uno == dos


def test_snapshot_semantico_tiene_hash_determinista():
    snapshot = crear_snapshot_catalogo_destinos(
        {"destinos": [_destino()]},
        {"clientes": [_cliente()]},
        _plantas(),
    )
    serial = json.dumps(
        {
            "destinos": snapshot.cantidad_destinos,
            "clientes": snapshot.cantidad_clientes,
            "plantas": snapshot.cantidad_plantas,
        },
        sort_keys=True,
    ).encode()
    assert snapshot.sha256
    assert hashlib.sha256(serial).hexdigest() != snapshot.sha256


def test_contexto_queda_congelado_y_no_decide():
    contexto = {
        "ruta": {"origen": "AZA COLINA", "km": 1},
        "cliente": "OTRO",
    }
    resultado = resolver_destino_ubicacion(
        obra_destino="CAMINO LO RUIZ 2901",
        contexto=contexto,
        catalogo_destinos={
            "destinos": [_destino(calidad="CONFIRMADO")]
        },
        catalogo_clientes={"clientes": [_cliente()]},
        catalogo_plantas=_plantas(),
    )
    contexto["ruta"]["origen"] = "AZA RENCA"
    assert resultado.contexto["ruta"]["origen"] == "AZA COLINA"
    assert resultado.planta_salida_canonica is None


def test_evidencia_exacta_de_baja_calidad_no_confirma():
    resultado = resolver_destino_ubicacion(
        obra_destino="CAMINO LO RUIZ 2901",
        calidades={"obra_destino": 0.4},
        catalogo_destinos={
            "destinos": [_destino(calidad="CONFIRMADO")]
        },
        catalogo_clientes={"clientes": [_cliente()]},
        catalogo_plantas=_plantas(),
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.via_decision == "CALIDAD_INCOMPLETA"
