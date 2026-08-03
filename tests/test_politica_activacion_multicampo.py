from types import MappingProxyType

import pytest

from atlas_core.politica_activacion_multicampo import (
    EstadoOperacional,
    REGISTRO_ACTIVACION_MULTICAMPO_FASE1,
    decidir_publicacion,
    validar_registro_activacion,
)


def _registro(**cambios):
    registro = dict(REGISTRO_ACTIVACION_MULTICAMPO_FASE1)
    registro.update(cambios)
    return registro


def test_registro_oficial_reproduce_el_estado_productivo_actual():
    assert REGISTRO_ACTIVACION_MULTICAMPO_FASE1 == {
        "chofer": EstadoOperacional.PRODUCTIVO,
        "cliente": EstadoOperacional.PRODUCTIVO,
        "destino": EstadoOperacional.PRODUCTIVO_CONTROLADO,
        "material": EstadoOperacional.SOMBRA,
    }
    assert isinstance(REGISTRO_ACTIVACION_MULTICAMPO_FASE1, MappingProxyType)
    with pytest.raises(TypeError):
        REGISTRO_ACTIVACION_MULTICAMPO_FASE1["destino"] = (
            EstadoOperacional.PRODUCTIVO
        )


@pytest.mark.parametrize(
    ("estado", "autorizacion", "publicar", "esperado"),
    (
        (EstadoOperacional.DESHABILITADO, False, False, "actual"),
        (EstadoOperacional.SOMBRA, False, False, "actual"),
        (EstadoOperacional.PRODUCTIVO_CONTROLADO, False, False, "actual"),
        (EstadoOperacional.PRODUCTIVO_CONTROLADO, True, True, "resuelto"),
        (EstadoOperacional.PRODUCTIVO, False, True, "resuelto"),
    ),
)
def test_decision_de_publicacion_por_estado(
    estado, autorizacion, publicar, esperado
):
    decision = decidir_publicacion(
        "destino",
        "actual",
        "resuelto",
        registro=_registro(destino=estado),
        autorizacion_controlada=autorizacion,
    )

    assert decision.estado_operacional is estado
    assert decision.publicar is publicar
    assert decision.valor == esperado


def test_rollback_es_solo_un_cambio_de_configuracion():
    productivo = decidir_publicacion(
        "cliente",
        "OCR",
        "CANONICO",
        registro=REGISTRO_ACTIVACION_MULTICAMPO_FASE1,
    )
    rollback = decidir_publicacion(
        "cliente",
        "OCR",
        "CANONICO",
        registro=_registro(cliente="SOMBRA"),
    )

    assert productivo.valor == "CANONICO"
    assert rollback.valor == "OCR"
    assert not rollback.publicar


@pytest.mark.parametrize(
    "registro",
    (
        {"chofer": "PRODUCTIVO"},
        _registro(destino="ESTADO_INEXISTENTE"),
        {**_registro(), "otro": "SOMBRA"},
    ),
)
def test_configuraciones_ambiguas_o_invalidas_fallan_cerradas(registro):
    with pytest.raises(ValueError):
        validar_registro_activacion(registro)


def test_campo_desconocido_no_puede_publicarse():
    with pytest.raises(ValueError, match="campo multicampo desconocido"):
        decidir_publicacion(
            "campo_nuevo",
            "actual",
            "resuelto",
            registro=REGISTRO_ACTIVACION_MULTICAMPO_FASE1,
        )
