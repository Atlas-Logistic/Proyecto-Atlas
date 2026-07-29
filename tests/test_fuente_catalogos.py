import json

import pytest

from atlas_core.catalogos import resolver_nombre_chofer_difuso
from atlas_core.fuente_catalogos import (
    ARCHIVOS_REQUERIDOS,
    ErrorFuenteCatalogos,
    validar_fuente_catalogos,
)


def _fuente_valida(tmp_path):
    contenidos = {
        "choferes.json": {
            "111111111": {"nombre": "ALFREDO MONTERO", "activo": True,
                          "aliases": ["ALEREDO MONTERO"]},
            "222222222": {"nombre": "ALFREDO MONTERO SUR", "activo": True},
            "333333333": {"nombre": "ALFREDO MONTERO", "activo": False},
        },
        "clientes.json": {"clientes": []},
        "empresas.json": {},
        "destinos_maestros.json": {"destinos": []},
        "vehiculos.json": {},
        "plantas.json": {"plantas": []},
        "rutas.json": {"rutas": []},
    }
    for nombre in ARCHIVOS_REQUERIDOS:
        (tmp_path / nombre).write_text(
            json.dumps(contenidos[nombre]), encoding="utf-8"
        )
    return contenidos


def test_fuente_valida_y_conteos(tmp_path):
    _fuente_valida(tmp_path)
    estado = validar_fuente_catalogos(tmp_path)
    assert estado.modo == "CATALOGOS_VALIDOS"
    assert estado.conteos["choferes.json"] == 3


def test_fuente_inexistente_incompleta_e_invalida(tmp_path, monkeypatch):
    monkeypatch.delenv("ATLAS_CATALOGOS_DIR", raising=False)
    with pytest.raises(ErrorFuenteCatalogos, match="Falta la fuente"):
        validar_fuente_catalogos()
    with pytest.raises(ErrorFuenteCatalogos, match="no existe"):
        validar_fuente_catalogos(tmp_path / "ausente")
    tmp_path.joinpath("choferes.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ErrorFuenteCatalogos, match="Fuente incompleta"):
        validar_fuente_catalogos(tmp_path)
    _fuente_valida(tmp_path)
    tmp_path.joinpath("clientes.json").write_text("{", encoding="utf-8")
    with pytest.raises(ErrorFuenteCatalogos, match="JSON inválido"):
        validar_fuente_catalogos(tmp_path)


def test_modo_sin_catalogos_debe_ser_explicito(monkeypatch):
    monkeypatch.delenv("ATLAS_CATALOGOS_DIR", raising=False)
    estado = validar_fuente_catalogos(permitir_sin_catalogos=True)
    assert estado.modo == "SIN_CATALOGOS_EXPLICITO"
    assert estado.ruta is None


def test_alias_se_resuelve_con_margen_suficiente(tmp_path):
    catalogos = _fuente_valida(tmp_path)
    resultado = resolver_nombre_chofer_difuso(
        catalogos["choferes.json"], "ALEREDO MONTERO"
    )
    assert resultado.estado == "COINCIDENCIA_SEGURA"
    assert resultado.valor_resultado == "ALFREDO MONTERO"
    assert resultado.similitud == 1.0
    assert resultado.segunda_similitud < resultado.similitud
    assert resultado.margen >= 0.05


def test_alias_inactivo_no_contamina_y_duda_preserva_original():
    catalogo = {
        "1": {"nombre": "ALFA UNO", "activo": False, "aliases": ["OCR EXACTO"]},
        "2": {"nombre": "MARIO SOTO", "activo": True},
        "3": {"nombre": "MARIA SOTO", "activo": True},
    }
    inactivo = resolver_nombre_chofer_difuso(catalogo, "OCR EXACTO")
    ambiguo = resolver_nombre_chofer_difuso(catalogo, "MARI SOTO")
    assert inactivo.valor_resultado == "OCR EXACTO"
    assert ambiguo.estado == "AMBIGUO"
    assert ambiguo.valor_resultado == "MARI SOTO"


def test_caso_autorizado_pairicio_patritio_depende_de_alias_explicito():
    catalogo = {
        "ID-ESTABLE": {
            "nombre": "PATRICIO VILLAGRA MUÑOZ", "activo": True,
        },
        "ID-PENDIENTE": {
            "nombre": "PATRICIO VILLAGRA", "activo": True,
            "aliases": ["PAIRICIO VILLAGRA"],
        },
    }

    resultado = resolver_nombre_chofer_difuso(catalogo, "PAIRICIO VILLAGRA")

    assert resultado.valor_resultado == "PATRICIO VILLAGRA"
    assert resultado.similitud == 1.0
    assert resultado.segunda_similitud == 0.8
    assert resultado.margen == pytest.approx(0.2)
