"""Regresiones estructurales de extracción: título/RETIRA/material degradados.

Origen: guía real 475256 (título sin DESPACHO, RETIRA leído AETIRA, fila de
material fusionada con el membrete). Las pruebas fijan los PATRONES con
valores sintéticos; ninguna depende del folio, chofer o RUT del caso.
"""

from atlas_core.catalogos import corroborar_chofer_por_nombre_y_rut_documental, resolver_nombre_chofer_difuso
from atlas_core.extractor import _es_ancla_retira, _extraer_chofer_geometrico, _extraer_numero_guia_geometrico
from atlas_core.ocr import BloqueOCR
from atlas_core.procesamiento_masivo import extraer_descripcion_material


def _b(texto, x, y, ancho=80, alto=18):
    return BloqueOCR(texto, ((x, y), (x + ancho, y), (x + ancho, y + alto), (x, y + alto)), 0.9)


# --- N.º de guía con título degradado ---------------------------------------

def test_titulo_sin_despacho_pero_con_electronica_contigua_recupera_folio():
    bloques = [_b("GUIA DE", 580, 220), _b("ELECTRONICA", 610, 232, 140, 30), _b("N? 123456", 636, 268)]
    assert _extraer_numero_guia_geometrico(bloques) == {"valor": "123456"}


def test_guia_de_aislado_no_es_evidencia_de_encabezado():
    assert _extraer_numero_guia_geometrico([_b("GUIA DE", 580, 220), _b("N? 123456", 636, 268)]) == {}


def test_electronica_lejana_o_en_otra_columna_no_completa_el_encabezado():
    # Misma fila de bloques, pero ELECTRONICA en otra columna o muy abajo:
    # no es la misma cabecera tipográfica.
    otra_columna = [_b("GUIA DE", 580, 220), _b("ELECTRONICA", 100, 232, 140, 30), _b("N? 123456", 636, 268)]
    muy_abajo = [_b("GUIA DE", 580, 220), _b("ELECTRONICA", 610, 400, 140, 30), _b("N? 123456", 636, 268)]
    assert _extraer_numero_guia_geometrico(otra_columna) == {}
    assert _extraer_numero_guia_geometrico(muy_abajo) == {}


# --- Etiqueta RETIRA con una sustitución OCR ----------------------------------

def test_retira_tolera_una_sustitucion_en_el_bloque_completo():
    assert _es_ancla_retira("AETIRA")
    assert _es_ancla_retira("RETIPA")


def test_retira_no_acepta_palabras_reales_vecinas_ni_dos_errores_ni_subcadenas():
    assert not _es_ancla_retira("RETIRO")
    assert not _es_ancla_retira("RETIRE")
    assert not _es_ancla_retira("AETIPA")
    assert not _es_ancla_retira("XAETIRA")
    assert not _es_ancla_retira("AETIRA JUAN")


def test_retira_degradada_ancla_el_nombre_junto_a_patente():
    bloques = [
        _b("aetira", 525, 855, 44, 14),
        _b("uan PEREz", 601, 855, 84, 14),
        _b("PATENTE", 525, 867, 56, 14),
        _b("RUT CHOFER", 65, 873, 74, 14),
    ]
    assert _extraer_chofer_geometrico(bloques) == {"valor": "uan PEREz"}


def test_retira_degradada_no_ancla_nombre_sin_contexto_vehicular_cercano():
    # Sin PATENTE junto a la etiqueta, el único contexto (RUT CHOFER) queda
    # en la otra columna: la proximidad exigida no se relaja.
    bloques = [_b("aetira", 520, 850), _b("uan PEREz", 600, 850, 100), _b("RUT CHOFER", 60, 873)]
    assert _extraer_chofer_geometrico(bloques) == {}


# --- Aislamiento de la fila de material ---------------------------------------

def test_material_aisla_fila_de_tabla_fusionada_con_membrete():
    lectura = (
        "Codigo Cliente 0001000000 FECHA DE EMISION CLIENTE DEMO SPA "
        "EMPRESA TRANSPORTE DESCRIPCION CANTIDAD CODIGO "
        "ROLLO HORMIGON 10MM A630-420H (N) 061 0001111 Coladas 1111111111,2222222222"
    )
    assert extraer_descripcion_material([lectura]) == (
        "ROLLO HORMIGON 10MM A630-420H (N) 061 0001111 Coladas 1111111111,2222222222"
    )


def test_material_sin_cabecera_descripcion_previa_no_se_recorta():
    lectura = "ROLLO HORMIGON 10MM A630-420H (N) Coladas 1111111111"
    assert extraer_descripcion_material([lectura]) == lectura


# --- Homologación de chofer por fuzzy seguro + RUT documental -----------------

_CATALOGO = {"152345674": {"nombre": "JUAN PEREZ", "activo": True}}


def test_fuzzy_seguro_con_rut_documental_invalido_adopta_rut_canonico():
    decision = resolver_nombre_chofer_difuso(_CATALOGO, "uan PEREz")
    assert decision.estado == "COINCIDENCIA_SEGURA"
    assert corroborar_chofer_por_nombre_y_rut_documental(
        _CATALOGO, decision.valor_resultado, "15234567-9"
    ) == ("JUAN PEREZ", "15.234.567-4")


def test_fuzzy_seguro_no_sobrescribe_un_rut_documental_valido_y_distinto():
    decision = resolver_nombre_chofer_difuso(_CATALOGO, "uan PEREz")
    assert decision.estado == "COINCIDENCIA_SEGURA"
    assert corroborar_chofer_por_nombre_y_rut_documental(
        _CATALOGO, decision.valor_resultado, "12345678-5"
    ) is None


# --- DV calculado por Atlas no es evidencia documental -------------------------

def test_dv_calculado_con_cuerpo_a_un_digito_del_canonico_adopta_canonico():
    # Cuerpo leído 15234569 (un dígito distinto); el DV 0 lo calculó Atlas.
    assert corroborar_chofer_por_nombre_y_rut_documental(
        _CATALOGO, "JUAN PEREZ", "15234569-0", dv_documental_leido=False
    ) == ("JUAN PEREZ", "15.234.567-4")


def test_dv_calculado_con_cuerpo_lejano_sigue_siendo_contradiccion():
    assert corroborar_chofer_por_nombre_y_rut_documental(
        _CATALOGO, "JUAN PEREZ", "12345678-5", dv_documental_leido=False
    ) is None


def test_dv_leido_con_cuerpo_a_un_digito_sigue_siendo_contradiccion():
    assert corroborar_chofer_por_nombre_y_rut_documental(
        _CATALOGO, "JUAN PEREZ", "15234569-0"
    ) is None


def test_extractor_marca_dv_calculado_solo_cuando_el_ocr_no_lo_leyo():
    from atlas_core.extractor import extraer_datos

    sin_dv = extraer_datos(["RUT CHOFER 15234569 FECHA SALIDA 01-01-2026"])
    con_dv = extraer_datos(["RUT CHOFER 15234569-0 FECHA SALIDA 01-01-2026"])
    assert sin_dv["RUT del chofer"] == con_dv["RUT del chofer"] == "15234569-0"
    assert sin_dv.get("RUT del chofer (dv calculado)") is True
    assert "RUT del chofer (dv calculado)" not in con_dv


def test_material_creible_con_etiqueta_descripcion_y_varios_items_no_se_recorta():
    lectura = "DESCRIPCION B HORMIGON 10MM 6M (N) Coladas: 1,2 B HORMIGON 12MM 6M (N) Coladas: 3,4"
    partes = extraer_descripcion_material([lectura]).split(" | ")
    assert len(partes) == 2
    assert partes[0].startswith("DESCRIPCION B HORMIGON")


def test_material_recortado_conserva_todos_los_items_tras_el_membrete():
    lectura = (
        "Codigo Cliente 0001000000 FECHA DE EMISION CLIENTE DEMO SPA SENOR(ES) RUT DIRECCION COMUNA "
        "EMPRESA TRANSPORTE DESCRIPCION CANTIDAD CODIGO "
        "B HORMIGON 10MM 6M (N) Coladas: 1,2 B HORMIGON 12MM 6M (N) Coladas: 3,4"
    )
    assert extraer_descripcion_material([lectura]).split(" | ") == [
        "B HORMIGON 10MM 6M (N) Coladas: 1,2", "B HORMIGON 12MM 6M (N) Coladas: 3,4",
    ]
