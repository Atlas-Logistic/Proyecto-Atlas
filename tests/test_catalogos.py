import json

from atlas_core.catalogos import (
    buscar_chofer_por_rut,
    buscar_destino_por_codigo,
    buscar_empresa_por_rut,
    buscar_vehiculo_por_patente,
    cargar_catalogo_json,
    normalizar_patente,
    normalizar_rut,
)


def test_normalizar_rut():
    assert normalizar_rut(" 12.345.678 - k ") == "12345678K"
    assert normalizar_rut("12 345 678-9") == "123456789"


def test_normalizar_patente():
    assert normalizar_patente(" ab cd 12 ") == "ABCD12"
    assert normalizar_patente("xyzt99") == "XYZT99"


def test_cargar_catalogo_json_existente(tmp_path):
    ruta = tmp_path / "empresas.json"
    contenido = {
        "12345678K": {
            "nombre": "EMPRESA FICTICIA SPA",
            "codigo_cliente": "CLIENTE_001",
        }
    }
    ruta.write_text(json.dumps(contenido), encoding="utf-8")

    assert cargar_catalogo_json(ruta) == contenido


def test_cargar_catalogo_json_inexistente_o_vacio(tmp_path):
    assert cargar_catalogo_json(tmp_path / "inexistente.json") == {}

    ruta_vacia = tmp_path / "vacio.json"
    ruta_vacia.write_text("", encoding="utf-8")
    assert cargar_catalogo_json(ruta_vacia) == {}


def test_busquedas_en_los_cuatro_catalogos(tmp_path):
    empresas = {
        "12345678K": {
            "nombre": "EMPRESA FICTICIA SPA",
            "codigo_cliente": "CLIENTE_001",
        }
    }
    destinos = {
        "DESTINO001": {
            "nombre": "DESTINO FICTICIO",
            "rut_empresa": "12345678K",
        }
    }
    choferes = {"987654321": {"nombre": "CHOFER FICTICIO"}}
    vehiculos = {"ABCD12": {"tipo": "TRACTO"}}

    ruta_empresas = tmp_path / "empresas.json"
    ruta_empresas.write_text(json.dumps(empresas), encoding="utf-8")

    assert buscar_empresa_por_rut(ruta_empresas, "12.345.678-k") == empresas["12345678K"]
    assert buscar_destino_por_codigo(destinos, " destino001 ") == destinos["DESTINO001"]
    assert buscar_chofer_por_rut(choferes, "98.765.432-1") == choferes["987654321"]
    assert buscar_vehiculo_por_patente(vehiculos, "ab cd 12") == vehiculos["ABCD12"]


def test_busquedas_desconocidas_devuelven_none(tmp_path):
    catalogo_vacio = tmp_path / "no_existe.json"

    assert buscar_empresa_por_rut(catalogo_vacio, "1-9") is None
    assert buscar_destino_por_codigo({}, "SIN_DESTINO") is None
    assert buscar_chofer_por_rut({}, "2-K") is None
    assert buscar_vehiculo_por_patente({}, "ZZZZ99") is None
