import json

import pytest

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
