from __future__ import annotations

import pytest

from atlas_core.inteligencia.contrato_multicampo import (
    Disponibilidad,
    EstadoResolucion,
)
from atlas_core.inteligencia.resolucion_cliente import resolver_cliente_rut


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


def _cliente(cliente_id: str, nombre: str, rut: str):
    return {
        "cliente_id": cliente_id,
        "razon_social": nombre,
        "nombre_comercial": "",
        "rut": rut,
        "aliases": [],
        "estado_calidad": "CONFIRMADO",
        "estado_vigencia": "ACTIVO",
    }


@pytest.mark.parametrize(
    ("ocr", "canonico"),
    [
        ("EMPRESASPA", "EMPRESA SpA"),
        ("EMPRESALTDA", "EMPRESA LTDA"),
        ("EMPRESAEIRL", "EMPRESA EIRL"),
        ("EMPRESASA", "EMPRESA SA"),
    ],
)
def test_sufijo_societario_pegado_separa_solo_para_match_exacto(ocr, canonico):
    catalogo = {"clientes": [_cliente("uno", canonico, _rut(1))]}
    resultado = resolver_cliente_rut(ocr, "", catalogo)
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.cliente_original == ocr
    assert resultado.cliente_canonico == canonico
    assert any(
        evidencia.tipo == "SUFIJO_SOCIETARIO_PEGADO_NORMALIZADO"
        for evidencia in resultado.evidencias
    )


@pytest.mark.parametrize("nombre", ["NASA", "MELISSA", "FANTASPA", "CALTDA"])
def test_sufijo_incrustado_legitimo_no_se_corta(nombre):
    catalogo = {"clientes": [_cliente("literal", nombre, _rut(1))]}
    resultado = resolver_cliente_rut(nombre, "", catalogo)
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.cliente_canonico == nombre
    assert all(
        evidencia.tipo != "SUFIJO_SOCIETARIO_PEGADO_NORMALIZADO"
        for evidencia in resultado.evidencias
    )


def test_literal_y_sufijo_separado_distintos_se_abstiene():
    catalogo = {
        "clientes": [
            _cliente("literal", "EMPRESASPA", _rut(1)),
            _cliente("societario", "EMPRESA SPA", _rut(2)),
        ]
    }
    resultado = resolver_cliente_rut("EMPRESASPA", "", catalogo)
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.entidad is None


def test_base_corta_no_habilita_separacion():
    catalogo = {"clientes": [_cliente("uno", "MELIS SA", _rut(1))]}
    resultado = resolver_cliente_rut("MELISSA", "", catalogo)
    assert resultado.estado is EstadoResolucion.NO_RESUELTO
    assert resultado.entidad is None


def test_catalogo_sin_sufijo_explicito_no_habilita_separacion():
    catalogo = {"clientes": [_cliente("uno", "EMPRESA", _rut(1))]}
    resultado = resolver_cliente_rut("EMPRESASPA", "", catalogo)
    assert resultado.estado is EstadoResolucion.NO_RESUELTO


def test_reproduce_hallazgo_claude_y_ahora_resuelve_seguro():
    catalogo = {
        "clientes": [
            _cliente("uno", "TRANSPORTES DEMO LTDA", _rut(1)),
        ]
    }
    resultado = resolver_cliente_rut("TRANSPORTES DEMOLTDA", "", catalogo)
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.cliente_original == "TRANSPORTES DEMOLTDA"


def test_rut_parcial_unico_no_busca_ni_confirma():
    rut = _rut(101)
    catalogo = {"clientes": [_cliente("uno", "CLIENTE DEMO UNO SA", rut)]}
    resultado = resolver_cliente_rut("", rut[-5:], catalogo)
    assert resultado.estado is EstadoResolucion.NO_RESUELTO
    assert resultado.entidad is None
    assert resultado.observaciones[1].disponibilidad is Disponibilidad.PARCIAL
    assert any(
        evidencia.tipo == "RUT_PARCIAL_NO_IDENTIFICANTE"
        for evidencia in resultado.evidencias
    )


def test_rut_parcial_ambiguo_tampoco_busca_identidad():
    rut_uno = _rut(101)
    rut_dos = _rut(1101)
    parcial = rut_uno[-4:]
    catalogo = {
        "clientes": [
            _cliente("uno", "CLIENTE DEMO UNO SA", rut_uno),
            _cliente("dos", "CLIENTE DEMO DOS SA", rut_dos[:-4] + parcial),
        ]
    }
    resultado = resolver_cliente_rut("", parcial, catalogo)
    assert resultado.estado is EstadoResolucion.NO_RESUELTO
    assert resultado.entidad is None


def test_rut_parcial_invalido_no_se_clasifica_como_evidencia_parcial():
    catalogo = {
        "clientes": [_cliente("uno", "CLIENTE DEMO UNO SA", _rut(101))]
    }
    resultado = resolver_cliente_rut("", "12K4", catalogo)
    assert resultado.estado is EstadoResolucion.NO_RESUELTO
    assert resultado.entidad is None
    assert resultado.observaciones[1].disponibilidad is Disponibilidad.DISPONIBLE
    assert any(e.tipo == "RUT_INVALIDO" for e in resultado.evidencias)
    assert all(
        e.tipo != "RUT_PARCIAL_NO_IDENTIFICANTE"
        for e in resultado.evidencias
    )


def test_rut_parcial_compatible_mas_nombre_fuerte_requiere_revision():
    rut = _rut(101)
    catalogo = {"clientes": [_cliente("uno", "CLIENTE DEMO UNO SA", rut)]}
    resultado = resolver_cliente_rut("CLIENTE DEMO UNO", rut[-5:], catalogo)
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.identificador_canonico == "cliente:uno"
    assert resultado.requiere_revision


def test_rut_parcial_contradictorio_materializa_revision():
    catalogo = {
        "clientes": [
            _cliente("uno", "CLIENTE DEMO UNO SA", _rut(101)),
            _cliente("dos", "CLIENTE DEMO DOS SA", _rut(202)),
        ]
    }
    parcial_otro = _rut(202)[-5:]
    resultado = resolver_cliente_rut(
        "CLIENTE DEMO UNO", parcial_otro, catalogo
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.contradicciones
    assert {
        evidencia.observado.campo
        for evidencia in resultado.contradicciones[0].evidencias_enfrentadas
    } == {"cliente", "rut_cliente"}


def test_rut_completo_invalido_sigue_siendo_invalido():
    valido = _rut(101)
    invalido = valido[:-1] + ("1" if valido[-1] != "1" else "2")
    catalogo = {
        "clientes": [_cliente("uno", "CLIENTE DEMO UNO SA", valido)]
    }
    resultado = resolver_cliente_rut("CLIENTE DEMO UNO", invalido, catalogo)
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.observaciones[1].disponibilidad is Disponibilidad.DISPONIBLE
    assert any(e.tipo == "RUT_INVALIDO" for e in resultado.evidencias)
