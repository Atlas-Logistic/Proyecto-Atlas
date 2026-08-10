import json
from pathlib import Path

from atlas_core.catalogos import (
    buscar_chofer_por_rut,
    buscar_destino_por_codigo,
    buscar_empresa_por_rut,
    buscar_vehiculo_por_patente,
    cargar_catalogo_json,
    enriquecer_datos_con_catalogos,
    normalizar_patente,
    normalizar_rut,
    resolver_nombre_chofer_difuso,
    resolver_patente_canonica,
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


def test_fuzzy_chofer_coincidencia_exacta_no_degrada_nombre():
    catalogo = {"1": {"nombre": "ÁNGELA SOTO", "activo": True}}

    resultado = resolver_nombre_chofer_difuso(catalogo, "ÁNGELA SOTO")

    assert resultado.estado == "SIN_CAMBIO"
    assert resultado.valor_resultado == "ÁNGELA SOTO"
    assert resultado.similitud == 1.0


def test_fuzzy_chofer_corrige_error_ocr_leve_sobre_umbral():
    catalogo = {"1": {"nombre": "ENRIQUE RAMOS", "activo": True}}

    resultado = resolver_nombre_chofer_difuso(catalogo, "ENRIQUE RANOS")

    assert resultado.estado == "COINCIDENCIA_SEGURA"
    assert resultado.valor_resultado == "ENRIQUE RAMOS"
    assert resultado.similitud >= 0.85


def test_fuzzy_chofer_debajo_umbral_conserva_original():
    catalogo = {"1": {"nombre": "ENRIQUE RAMOS", "activo": True}}

    resultado = resolver_nombre_chofer_difuso(catalogo, "MARTA SILVA")

    assert resultado.estado == "DEBAJO_UMBRAL"
    assert resultado.valor_resultado == "MARTA SILVA"


def test_fuzzy_chofer_ambiguo_se_abstiene():
    catalogo = {
        "1": {"nombre": "MARIO SOTO", "activo": True},
        "2": {"nombre": "MARIA SOTO", "activo": True},
    }

    resultado = resolver_nombre_chofer_difuso(catalogo, "MARI SOTO")

    assert resultado.estado == "AMBIGUO"
    assert resultado.valor_resultado == "MARI SOTO"


def test_fuzzy_chofer_inactivo_no_puede_usarse():
    catalogo = {"1": {"nombre": "ENRIQUE RAMOS", "activo": False}}

    resultado = resolver_nombre_chofer_difuso(catalogo, "ENRIQUE RANOS")

    assert resultado.estado == "CATALOGO_VACIO"
    assert resultado.valor_resultado == "ENRIQUE RANOS"


def test_fuzzy_chofer_catalogo_vacio_o_no_disponible(tmp_path):
    vacio = resolver_nombre_chofer_difuso({}, "NOMBRE ORIGINAL")
    no_disponible = resolver_nombre_chofer_difuso(
        tmp_path / "no_existe.json", "NOMBRE ORIGINAL"
    )

    assert vacio.estado == no_disponible.estado == "CATALOGO_VACIO"
    assert vacio.valor_resultado == no_disponible.valor_resultado == "NOMBRE ORIGINAL"


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


# --- P2: resolucion_patente_canonica (homologacion conservadora de patentes) ---

CATALOGO_VEHICULOS_REAL_464511 = {
    "BKYX63": {"tipo": "TRACTO"},
    "BKYK63": {"tipo": "TRACTO"},
    "DD2494": {"tipo": "TRACTO"},
    "JB8529": {"tipo": "CARRO"},
    "BDFG50": {"tipo": "TRACTO"},
    "BPHR67": {"tipo": "TRACTO"},
    "AL1879": {"tipo": "TRACTO"},
    "JK2501": {"tipo": "CARRO"},
    "TG8925": {"tipo": "TRACTO"},
    "JF9565": {"tipo": "CARRO"},
    "SB6486": {"tipo": "TRACTO"},
    "JF4288": {"tipo": "CARRO"},
}


def test_patente_exacta_resuelve_a_canonica():
    catalogo = {"AB1234": {"tipo": "TRACTO"}}

    resultado = resolver_patente_canonica(catalogo, "ab 1234", tipo_esperado="TRACTO")

    assert resultado.estado == "COINCIDENCIA_EXACTA"
    assert resultado.valor_resultado == "AB1234"


def test_patente_sd6486_resuelve_a_sb6486_con_catalogo_real_simulado():
    """Caso real obligatorio: SD6486 (lectura Paddle) debe resolver a SB6486
    solo porque el catálogo real contiene SB6486 como candidato único seguro
    (una sola diferencia, confusión OCR B/D documentada)."""
    resultado = resolver_patente_canonica(
        CATALOGO_VEHICULOS_REAL_464511, "SD6486", tipo_esperado="TRACTO"
    )

    assert resultado.estado == "CORRECCION_OCR_SEGURA"
    assert resultado.valor_resultado == "SB6486"


def test_patente_rampla_exacta_jf4288_no_se_modifica():
    resultado = resolver_patente_canonica(
        CATALOGO_VEHICULOS_REAL_464511, "JF4288", tipo_esperado="CARRO"
    )

    assert resultado.estado == "COINCIDENCIA_EXACTA"
    assert resultado.valor_resultado == "JF4288"


def test_patente_candidato_ambiguo_se_abstiene():
    # "AD1234" (confusión B/D) y "A81234" (confusión B/8) están, cada uno, a
    # una sola diferencia OCR válida de "AB1234" -> dos candidatos igualmente
    # plausibles, no puede elegir ninguno sin arriesgarse.
    catalogo = {
        "AD1234": {"tipo": "TRACTO"},
        "A81234": {"tipo": "TRACTO"},
    }

    resultado = resolver_patente_canonica(catalogo, "AB1234", tipo_esperado="TRACTO")

    assert resultado.estado == "AMBIGUO"
    assert resultado.valor_resultado == "AB1234"


def test_patente_dos_diferencias_no_se_corrige():
    # "SD64X6" difiere de "SB6486" en dos posiciones (D/B y X/8): no es una
    # corrección segura aunque cada diferencia individual fuera válida.
    catalogo = {"SB6486": {"tipo": "TRACTO"}}

    resultado = resolver_patente_canonica(catalogo, "SD64X6", tipo_esperado="TRACTO")

    assert resultado.estado == "SIN_CANDIDATO"
    assert resultado.valor_resultado == "SD64X6"


def test_patente_desconocida_se_conserva():
    resultado = resolver_patente_canonica(
        CATALOGO_VEHICULOS_REAL_464511, "ZZ9999", tipo_esperado="TRACTO"
    )

    assert resultado.estado == "SIN_CANDIDATO"
    assert resultado.valor_resultado == "ZZ9999"


def test_patente_no_aplica_se_preserva_sin_inventar():
    resultado = resolver_patente_canonica(
        CATALOGO_VEHICULOS_REAL_464511, "NO_APLICA", tipo_esperado="CARRO"
    )

    assert resultado.estado == "SIN_CANDIDATO"
    assert resultado.valor_resultado == "NO_APLICA"


def test_patente_no_encontrado_no_se_toca():
    resultado = resolver_patente_canonica(CATALOGO_VEHICULOS_REAL_464511, "No encontrado")

    assert resultado.estado == "VACIO"
    assert resultado.valor_resultado == "No encontrado"


def test_patente_sin_catalogo_no_inventa():
    vacio = resolver_patente_canonica({}, "SD6486", tipo_esperado="TRACTO")
    inexistente = resolver_patente_canonica(
        Path("no_existe_de_verdad.json"), "SD6486", tipo_esperado="TRACTO"
    )

    assert vacio.estado == "CATALOGO_VACIO"
    assert vacio.valor_resultado == "SD6486"
    assert inexistente.estado == "CATALOGO_VACIO"
    assert inexistente.valor_resultado == "SD6486"


def test_patente_alias_explicito_resuelve_a_canonica():
    catalogo = {"SB6486": {"tipo": "TRACTO", "alias": ["SD6486", "5B6486"]}}

    resultado = resolver_patente_canonica(catalogo, "SD6486", tipo_esperado="TRACTO")

    assert resultado.estado == "ALIAS"
    assert resultado.valor_resultado == "SB6486"


def test_patente_tipo_esperado_filtra_candidatos_entre_tracto_y_carro():
    # SD6486 podría confundirse con un carro "SB6486" si no se filtrara por
    # tipo; al pedir CARRO no debe cruzar hacia el tracto real.
    catalogo = {
        "SB6486": {"tipo": "TRACTO"},
        "SB6489": {"tipo": "CARRO"},
    }

    resultado = resolver_patente_canonica(catalogo, "SD6489", tipo_esperado="CARRO")

    assert resultado.estado == "CORRECCION_OCR_SEGURA"
    assert resultado.valor_resultado == "SB6489"
