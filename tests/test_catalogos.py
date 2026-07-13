import json

from atlas_core.catalogos import (
    buscar_chofer_por_rut,
    buscar_destino_por_codigo,
    buscar_empresa_por_rut,
    buscar_vehiculo_por_patente,
    cargar_catalogo_json,
    enriquecer_datos_con_catalogos,
    normalizar_patente,
    normalizar_rut,
)
from atlas_core.extractor import extraer_datos


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


def test_enriquecer_datos_con_catalogos(tmp_path):
    catalogos = {
        "empresas.json": {
            "12345678K": {
                "nombre": "EMPRESA FICTICIA OFICIAL SPA",
                "codigo_cliente": "CLIENTE_FICTICIO",
            }
        },
        "destinos.json": {
            "DESTINO001": {
                "nombre": "DESTINO FICTICIO OFICIAL",
                "rut_empresa": "12345678K",
            }
        },
        "choferes.json": {
            "987654321": {"nombre": "CHOFER FICTICIO OFICIAL"}
        },
        "vehiculos.json": {"ABCD12": {"tipo": "TRACTO"}},
    }
    contenido_original = {}
    for nombre_archivo, contenido in catalogos.items():
        ruta = tmp_path / nombre_archivo
        ruta.write_text(json.dumps(contenido), encoding="utf-8")
        contenido_original[nombre_archivo] = ruta.read_bytes()

    datos = {
        "cliente": "EMPRESA MAL LEIDA",
        "RUT del cliente": "12.345.678-k",
        "obra destino": "DESTINO MAL LEIDO",
        "chofer": "CHOFER MAL LEIDO",
        "RUT del chofer": "98.765.432-1",
        "patente del tracto": "ab cd 12",
        "patente del carro": "No encontrado",
    }
    textos = ["CÓDIGO DESTINATARI0: destino001"]

    enriquecidos = enriquecer_datos_con_catalogos(datos, textos, tmp_path)

    assert enriquecidos["cliente"] == "EMPRESA FICTICIA OFICIAL SPA"
    assert enriquecidos["chofer"] == "CHOFER FICTICIO OFICIAL"
    assert enriquecidos["obra destino"] == "DESTINO FICTICIO OFICIAL"
    assert enriquecidos["patente del tracto"] == "ABCD12"
    assert enriquecidos["patente del carro"] == "No encontrado"
    for nombre_archivo, contenido in contenido_original.items():
        assert (tmp_path / nombre_archivo).read_bytes() == contenido


def test_enriquecer_con_catalogos_vacios_conserva_datos(tmp_path):
    for nombre_archivo in (
        "empresas.json",
        "destinos.json",
        "choferes.json",
        "vehiculos.json",
    ):
        (tmp_path / nombre_archivo).write_text("{}", encoding="utf-8")

    datos = {
        "cliente": "EMPRESA ORIGINAL",
        "RUT del cliente": "11.111.111-1",
        "obra destino": "DESTINO ORIGINAL",
        "chofer": "CHOFER ORIGINAL",
        "RUT del chofer": "22.222.222-2",
        "patente del tracto": "xy zt 99",
    }

    assert enriquecer_datos_con_catalogos(datos, ["COD DESTINATARIO OTRO"], tmp_path) == datos


def test_enriquecer_sin_archivos_y_extraer_con_ruta_opcional(tmp_path):
    datos = {
        "cliente": "EMPRESA ORIGINAL",
        "RUT del cliente": "11.111.111-1",
        "chofer": "CHOFER ORIGINAL",
        "RUT del chofer": "22.222.222-2",
    }
    carpeta_inexistente = tmp_path / "sin_catalogos"

    assert enriquecer_datos_con_catalogos(datos, [], carpeta_inexistente) == datos
    extraidos = extraer_datos([], carpeta_catalogos=carpeta_inexistente)
    assert all(valor == "No encontrado" for valor in extraidos.values())
