from __future__ import annotations

from copy import deepcopy

import pytest

from atlas_core.inteligencia.contrato_multicampo import EstadoResolucion
from atlas_core.inteligencia.politica_confianza_cliente import (
    POLITICA_CONFIANZA_CLIENTE_V1,
    PoliticaConfianzaCliente,
    ViaDecisionCliente,
)
from atlas_core.inteligencia.resolucion_cliente import resolver_cliente_rut
from atlas_core.inteligencia.snapshot_catalogo_clientes import (
    crear_snapshot_catalogo_clientes,
)


def _dv(base: str) -> str:
    suma = 0
    factor = 2
    for digito in reversed(base):
        suma += int(digito) * factor
        factor = factor + 1 if factor < 7 else 2
    resto = 11 - suma % 11
    return "0" if resto == 11 else "K" if resto == 10 else str(resto)


def _rut(numero: int) -> str:
    base = f"{numero:08d}"
    return base + _dv(base)


def _cliente(cliente_id, nombre, rut, **cambios):
    base = {
        "cliente_id": cliente_id,
        "razon_social": nombre,
        "nombre_comercial": "",
        "rut": rut,
        "aliases": [],
        "estado_calidad": "CONFIRMADO",
        "estado_vigencia": "ACTIVO",
    }
    return {**base, **cambios}


@pytest.fixture
def catalogo():
    return {
        "clientes": [
            _cliente("uno", "INDUSTRIAS DEMO CENTRAL SPA", _rut(101)),
            _cliente("dos", "INDUSTRIAS DEMO COSTA LTDA", _rut(202)),
        ]
    }


def test_snapshot_inmutable_hash_determinista_y_orden_independiente(catalogo):
    invertido = {"clientes": list(reversed(catalogo["clientes"]))}
    uno = crear_snapshot_catalogo_clientes(catalogo)
    dos = crear_snapshot_catalogo_clientes(invertido)
    assert uno.sha256 == dos.sha256
    assert uno.version == dos.version
    catalogo["clientes"][0]["razon_social"] = "MUTADO"
    assert uno.registros["uno"]["razon_social"] == "INDUSTRIAS DEMO CENTRAL SPA"
    with pytest.raises(TypeError):
        uno.registros["uno"]["razon_social"] = "OTRO"


def test_snapshot_empresas_relaciona_por_rut_sin_duplicar_cliente(catalogo):
    empresas = {
        _rut(101): {"nombre": "IDC DEMO"},
        _rut(303): {"nombre": "EMPRESA LEGADO DEMO"},
    }
    snapshot = crear_snapshot_catalogo_clientes(catalogo, empresas)
    assert snapshot.cantidad_registros == 3
    assert "IDC DEMO" in snapshot.registros["uno"]["aliases"]
    legado = snapshot.registros[f"empresa:{_rut(303)}"]
    assert legado["estado_calidad"] == "LEGADO"


def test_empresa_legado_sola_no_se_confirma_automaticamente():
    resultado = resolver_cliente_rut(
        "",
        _rut(303),
        {"clientes": []},
        catalogo_empresas={_rut(303): {"nombre": "EMPRESA LEGADO DEMO"}},
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.via_decision == "CALIDAD_NO_CONFIRMADA"


def test_cliente_pendiente_o_inactivo_no_se_confirma(catalogo):
    pendiente = deepcopy(catalogo)
    pendiente["clientes"][0]["estado_calidad"] = "PENDIENTE"
    assert resolver_cliente_rut(
        "", _rut(101), pendiente
    ).via_decision == "CALIDAD_NO_CONFIRMADA"
    inactivo = deepcopy(catalogo)
    inactivo["clientes"][0]["estado_vigencia"] = "INACTIVO"
    assert resolver_cliente_rut(
        "", _rut(101), inactivo
    ).via_decision == "INACTIVO"


def test_politica_visible_y_fuzzy_jamas_confirma_por_confianza(catalogo):
    valores = dict(POLITICA_CONFIANZA_CLIENTE_V1.valores)
    valores[ViaDecisionCliente.FUZZY_UNICO] = 1.0
    politica = PoliticaConfianzaCliente("prueba-cliente", valores)
    resultado = resolver_cliente_rut(
        "INDUSTRIAS DEM0 CENTRAL", "",
        catalogo,
        politica_confianza=politica,
    )
    assert resultado.estado is EstadoResolucion.PROPUESTO
    assert resultado.confianza < 1.0
    assert resultado.version_politica == "prueba-cliente"


def test_rut_valido_del_cliente_incorrecto_domina_fuzzy(catalogo):
    resultado = resolver_cliente_rut(
        "INDUSTRIAS DEM0 CENTRAL", _rut(202), catalogo
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.via_decision == "CONTRADICCION"
    assert resultado.confianza == 0.0


def test_salida_independiente_del_orden_y_contexto_no_determinante(catalogo):
    invertido = {"clientes": list(reversed(catalogo["clientes"]))}
    contexto = {"obra": "INDUSTRIAS DEMO COSTA", "destino": "PLANTA DEMO"}
    uno = resolver_cliente_rut(
        "INDUSTRIAS DEM0 CENTRAL", "", catalogo, contexto
    )
    dos = resolver_cliente_rut(
        "INDUSTRIAS DEM0 CENTRAL", "", invertido, contexto
    )
    assert uno == dos
    assert uno.estado is EstadoResolucion.PROPUESTO


def test_no_resuelto_obligatorio_y_opcional(catalogo):
    obligatorio = resolver_cliente_rut("", "", catalogo)
    opcional = resolver_cliente_rut(
        "", "", catalogo, campo_obligatorio=False
    )
    assert obligatorio.requiere_revision_humana is True
    assert opcional.requiere_revision_humana is False


def test_rut_invalido_de_ocho_digitos_se_clasifica_invalido(catalogo):
    valido = _rut(101)
    invalido = valido[:-1] + ("1" if valido[-1] != "1" else "2")
    resultado = resolver_cliente_rut("", invalido, catalogo)
    assert resultado.estado is EstadoResolucion.NO_RESUELTO
    assert resultado.observaciones[1].calidad.value == "INVALIDA"
    assert "módulo 11" in resultado.observaciones[1].detalle_calidad
