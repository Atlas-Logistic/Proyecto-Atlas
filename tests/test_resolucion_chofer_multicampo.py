from __future__ import annotations

from copy import deepcopy

import pytest

from atlas_core.inteligencia.contrato_multicampo import (
    CalidadObservacion,
    EstadoResolucion,
)
from atlas_core.inteligencia.resolucion_chofer import (
    auditar_catalogo_choferes,
    normalizar_nombre_identidad,
    resolver_chofer_rut,
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


def _formatear(clave: str) -> str:
    base, dv = clave[:-1], clave[-1]
    grupos = []
    while base:
        grupos.append(base[-3:])
        base = base[:-3]
    return ".".join(reversed(grupos)) + f"-{dv}"


@pytest.fixture
def catalogo():
    return {
        _rut(101): {
            "nombre": "MARINA DEMO ÁLVAREZ",
            "activo": True,
            "aliases": ["MARINA DEMO", "MARIÑA DEMO"],
        },
        _rut(202): {
            "nombre": "TOMÁS EJEMPLO NORTE",
            "activo": True,
            "aliases": ["TOMAS NORTE"],
        },
        _rut(303): {
            "nombre": "TOMÁS EJEMPLO SUR",
            "activo": True,
            "aliases": ["TOMAS SUR"],
        },
        "PENDIENTE-DEMO-1": {
            "nombre": "PERSONA DEMO SIN RUT",
            "activo": True,
            "aliases": ["PERSONA OCR DEMO"],
        },
        _rut(404): {"nombre": "CHOFER DEMO INACTIVO", "activo": False},
    }


def test_canonico_exacto_y_rut_exacto_confirman(catalogo):
    resultado = resolver_chofer_rut(
        "MARINA DEMO ÁLVAREZ", _formatear(_rut(101)), catalogo
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.identificador_canonico == f"chofer:{_rut(101)}"
    assert resultado.valor_canonico == "MARINA DEMO ÁLVAREZ"
    assert {e.tipo for e in resultado.evidencias} >= {
        "RUT_EXACTO_VALIDO", "NOMBRE_CANONICO_EXACTO"
    }


def test_alias_confirmado_sin_rut_confirma_y_explica(catalogo):
    resultado = resolver_chofer_rut("MARINA DEMO", "", catalogo)
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert any(e.tipo == "ALIAS_CONFIRMADO_EXACTO" for e in resultado.evidencias)
    assert all(e.tipo != "NOMBRE_FUZZY" for e in resultado.evidencias)


def test_nombre_ocr_imperfecto_mas_rut_exacto_confirma(catalogo):
    resultado = resolver_chofer_rut(
        "MARLNA DEMO ALVAREZ", _rut(101), catalogo
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.valores_ocr_originales["nombre_chofer"] == ("MARLNA DEMO ALVAREZ",)
    assert any(e.tipo == "NOMBRE_FUZZY" for e in resultado.evidencias)


def test_nombre_y_rut_contradictorios_requieren_revision(catalogo):
    resultado = resolver_chofer_rut("TOMAS NORTE", _rut(303), catalogo)
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.contradicciones
    contradiccion = resultado.contradicciones[0]
    assert contradiccion.campos_enfrentados == ("nombre_chofer", "rut_chofer")
    assert len(contradiccion.entidades_involucradas) == 2


def test_rut_con_puntos_y_guion_se_normaliza(catalogo):
    resultado = resolver_chofer_rut("", _formatear(_rut(202)), catalogo)
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.observaciones[1].valor_original == _formatear(_rut(202))
    assert resultado.observaciones[1].valor_normalizado == _rut(202)


def test_rut_sin_formato_es_valido(catalogo):
    resultado = resolver_chofer_rut("", _rut(202), catalogo)
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.observaciones[1].calidad is CalidadObservacion.VALIDA


def test_rut_invalido_se_conserva_y_no_fija_identidad(catalogo):
    invalido = _rut(101)[:-1] + ("1" if _rut(101)[-1] != "1" else "2")
    resultado = resolver_chofer_rut("", invalido + "X", catalogo)
    assert resultado.estado is EstadoResolucion.NO_RESUELTO
    assert resultado.observaciones[1].valor_original == invalido + "X"
    assert resultado.observaciones[1].calidad is CalidadObservacion.INVALIDA


def test_nombre_fuerte_y_rut_parcial_compatible(catalogo):
    parcial = _rut(101)[-5:]
    resultado = resolver_chofer_rut("MARINA DEMO", parcial, catalogo)
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert any(e.tipo == "RUT_PARCIAL_COMPATIBLE" for e in resultado.evidencias)


def test_nombre_fuerte_y_rut_parcial_incompatible(catalogo):
    resultado = resolver_chofer_rut("MARINA DEMO", _rut(202)[-5:], catalogo)
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.contradicciones


def test_fuzzy_unico_con_margen_amplio_solo_propone(catalogo):
    resultado = resolver_chofer_rut("MARLNA DEMO ALVAREZ", "", catalogo)
    assert resultado.estado is EstadoResolucion.PROPUESTO
    assert resultado.requiere_revision_humana
    fuzzy = next(e for e in resultado.evidencias if e.tipo == "NOMBRE_FUZZY")
    assert fuzzy.fuerza >= 0.85
    assert "margen" in fuzzy.detalle


def test_fuzzy_ambiguo_con_margen_pequeno_requiere_revision():
    catalogo = {
        _rut(1): {"nombre": "MARIO DEMO A", "activo": True},
        _rut(2): {"nombre": "MARIO DEMO B", "activo": True},
    }
    resultado = resolver_chofer_rut("MARIO DEMO X", "", catalogo)
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert len(resultado.alternativas) == 2


def test_dos_candidatos_de_nombre_parecido_no_dependen_del_orden():
    uno = {
        _rut(1): {"nombre": "MARIO DEMO ESTE", "activo": True},
        _rut(2): {"nombre": "MARIO DEMO OESTE", "activo": True},
    }
    dos = dict(reversed(list(uno.items())))
    assert resolver_chofer_rut("MARIO DEMO", "", uno) == resolver_chofer_rut(
        "MARIO DEMO", "", dos
    )


def test_registro_inactivo_no_se_confirma(catalogo):
    resultado = resolver_chofer_rut("CHOFER DEMO INACTIVO", _rut(404), catalogo)
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.entidad and resultado.entidad.activa is False


def test_alias_duplicado_es_ambiguo():
    catalogo = {
        _rut(1): {"nombre": "DEMO UNO", "activo": True, "aliases": ["ALIAS COMUN"]},
        _rut(2): {"nombre": "DEMO DOS", "activo": True, "aliases": ["ALIAS COMUN"]},
    }
    resultado = resolver_chofer_rut("ALIAS COMUN", "", catalogo)
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert {h.tipo for h in auditar_catalogo_choferes(catalogo)} == {
        "ALIAS_COMPARTIDO"
    }


def test_rut_duplicado_se_detecta_y_no_confirma():
    rut = _rut(1)
    catalogo = {
        rut: {"nombre": "DEMO UNO", "activo": True},
        _formatear(rut): {"nombre": "DEMO DOS", "activo": True},
    }
    resultado = resolver_chofer_rut("", rut, catalogo)
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.entidad is None
    assert any(h.tipo == "RUT_DUPLICADO" for h in auditar_catalogo_choferes(catalogo))


def test_enie_y_ene_se_mantienen_distintas():
    catalogo = {
        _rut(1): {"nombre": "DEMO PEÑA", "activo": True},
        _rut(2): {"nombre": "DEMO PENA", "activo": True},
    }
    assert normalizar_nombre_identidad("PEÑA") != normalizar_nombre_identidad("PENA")
    resultado = resolver_chofer_rut("DEMO PEÑA", "", catalogo)
    assert resultado.identificador_canonico == f"chofer:{_rut(1)}"
    assert any(h.tipo == "COLISION_NORMALIZACION" for h in auditar_catalogo_choferes(catalogo))


def test_acentos_y_espacios_repetidos_no_impiden_exacto(catalogo):
    resultado = resolver_chofer_rut("  MARINA   DEMO ALVAREZ ", "", catalogo)
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.valores_ocr_originales["nombre_chofer"] == ("  MARINA   DEMO ALVAREZ ",)


@pytest.mark.parametrize(
    ("nombre", "rut"),
    [("", ""), (None, None)],
)
def test_ausencia_de_ambos_no_resuelve(catalogo, nombre, rut):
    resultado = resolver_chofer_rut(nombre, rut, catalogo)
    assert resultado.estado is EstadoResolucion.NO_RESUELTO
    assert resultado.entidad is None


def test_ausencia_nombre_permite_rut_exacto(catalogo):
    assert resolver_chofer_rut(None, _rut(101), catalogo).estado is EstadoResolucion.CONFIRMADO


def test_ausencia_rut_permite_canonico_exacto(catalogo):
    assert resolver_chofer_rut("MARINA DEMO ÁLVAREZ", None, catalogo).estado is EstadoResolucion.CONFIRMADO


def test_salida_determinista_y_contexto_no_determinante(catalogo):
    uno = resolver_chofer_rut("MARINA DEMO", "", catalogo, {"vehiculo": "DEMO-A"})
    dos = resolver_chofer_rut("MARINA DEMO", "", catalogo, {"vehiculo": "DEMO-A"})
    assert uno == dos
    assert uno.contexto == {"vehiculo": "DEMO-A"}
    assert all("vehiculo" not in e.tipo.lower() for e in uno.evidencias)


def test_evidencia_y_contradiccion_completas(catalogo):
    resultado = resolver_chofer_rut("TOMAS NORTE", _rut(303), catalogo)
    assert all(e.fuente and e.detalle and e.observado.valor_original for e in resultado.evidencias)
    contradiccion = resultado.contradicciones[0]
    assert contradiccion.razon and contradiccion.efecto
    assert contradiccion.evidencias_enfrentadas


def test_identificador_estable_para_clave_temporal(catalogo):
    resultado = resolver_chofer_rut("PERSONA OCR DEMO", "", catalogo)
    assert resultado.identificador_canonico == "chofer:PENDIENTE-DEMO-1"
    assert resultado.identificador_canonico == resolver_chofer_rut(
        "PERSONA DEMO SIN RUT", "", catalogo
    ).identificador_canonico


def test_catalogo_no_se_modifica_y_propuesta_no_aprende(catalogo):
    original = deepcopy(catalogo)
    primera = resolver_chofer_rut("MARLNA DEMO ALVAREZ", "", catalogo)
    segunda = resolver_chofer_rut("MARLNA DEMO ALVAREZ", "", catalogo)
    assert primera.estado is EstadoResolucion.PROPUESTO
    assert primera == segunda
    assert catalogo == original
    assert all(
        "MARLNA DEMO ALVAREZ" not in registro.get("aliases", [])
        for registro in catalogo.values()
    )


def test_auditoria_detecta_nombre_duplicado_y_activo_inactivo():
    rut = _rut(1)
    catalogo = {
        rut: {"nombre": "DEMO REPETIDO", "activo": True},
        _formatear(rut): {"nombre": "DEMO REPETIDO", "activo": False},
    }
    tipos = {h.tipo for h in auditar_catalogo_choferes(catalogo)}
    assert {"RUT_DUPLICADO", "NOMBRE_DUPLICADO", "IDENTIDAD_ACTIVA_E_INACTIVA"} <= tipos
