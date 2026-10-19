"""Filas de material omitidas: la tabla trae más filas CANTIDAD/CODIGO que
ítems leídos, y la suma de cantidades es PESO KG.

- 482396 (Mobile, RapidOCR): el PULL no guarda traza OCR, así que la
  geometría está RECONSTRUIDA desde el papel (posiciones aproximadas de la
  foto original 3120x4160): 3 filas, falta "B HORMIGON 22MM 6M", 4.695 kg.
- 472818, 473253, 473519, 482247, 473546: líneas REALES de sus trazas OCR
  persistidas (sólo texto, sin geometría).

Sólo observa: nunca cambia la descripción, motivos ni estados.
"""
from __future__ import annotations

import json
from unittest.mock import Mock

from atlas_core import procesamiento_masivo
from atlas_core.material_codigo_sap import (
    FILAS_NO_CONCLUYENTE, FILAS_OMISION_CONFIRMADA, FILAS_OMISION_SIN_IDENTIFICAR, FILAS_SIN_EVIDENCIA,
    FILAS_SIN_OMISION, MOTIVO_CANTIDAD_NO_LEIDA, MOTIVO_CODIGO_REPETIDO, MOTIVO_FILAS_NO_SUPERAN_ITEMS,
    MOTIVO_PESO_AUSENTE, MOTIVO_SUMA_DISTINTA_PESO, analizar_items_material, detectar_filas_material_omitidas,
    filas_material_documentales,
)
from atlas_core.procesamiento_masivo import procesar_archivo


def _b(texto, x0, y0, x1, y1, confianza=0.95):
    return {"texto": texto, "bounding_box": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "confianza": confianza}


def _detectar(descripcion, peso, *, textos=(), bloques=None):
    items = analizar_items_material(descripcion, textos=textos, bloques=bloques)
    return detectar_filas_material_omitidas(items, peso_kg=peso, textos=textos, bloques=bloques)


# --- 482396: geometría reconstruida desde el papel ---------------------------

FILA_22MM = [_b("4.695110002953", 312, 1772, 635, 1808), _b("B HORMIGON 22MM 6M A630-420H (N)", 905, 1772, 1625, 1808),
             _b("Coladas: 2617815302,2617815702", 905, 1816, 1580, 1850)]
FILA_10MM = [_b("7.078110002866", 312, 1870, 635, 1906), _b("B HORMIGON 10MM 6M A440-280H(N)", 905, 1870, 1625, 1906),
             _b("Coladas: 2617012402,2617014302", 905, 1914, 1580, 1948)]
FILA_16MM = [_b("9.519110002928", 312, 1966, 635, 2002), _b("B HORMIGON 16MM 6M A630-420H (N)", 905, 1966, 1625, 2002),
             _b("Coladas: 2617925102,2617996502", 905, 2010, 1580, 2044)]
ENCABEZADO = [_b("CANTIDAD", 220, 1700, 410, 1740), _b("CODIGO", 590, 1700, 730, 1740),
              _b("DESCRIPCION", 1390, 1700, 1650, 1740)]
DESCRIPCION_482396 = "B HORMIGON 10MM 6M A440-280H(N) | B HORMIGON 16MM 6M A630-420H (N)"


def test_482396_fila_sin_descripcion_es_omision_confirmada_con_codigo_y_cantidad():
    # El OCR leyó la fila 22MM (cantidad + código) pero no su descripción.
    bloques = ENCABEZADO + [FILA_22MM[0], FILA_22MM[2]] + FILA_10MM + FILA_16MM
    r = _detectar(DESCRIPCION_482396, "21292", bloques=bloques)
    assert r["estado"] == FILAS_OMISION_CONFIRMADA
    assert r["faltantes"] == [{"codigo_sap": "110002953", "cantidad_kg": 4695}]
    assert (r["suma_cantidades_kg"], r["items_leidos"], r["filas_faltantes"]) == (21292, 2, 1)


def test_482396_completo_no_marca_omision():
    descripcion = "B HORMIGON 22MM 6M A630-420H (N) | " + DESCRIPCION_482396
    r = _detectar(descripcion, "21292", bloques=ENCABEZADO + FILA_22MM + FILA_10MM + FILA_16MM)
    assert r["estado"] == FILAS_SIN_OMISION and r["suma_coincide_peso"] is True and r["faltantes"] == []


def test_cantidad_en_bloque_propio_de_la_misma_fila():
    separada = [_b("4.695", 312, 1772, 420, 1808), _b("110002953", 430, 1772, 635, 1808)]
    r = _detectar(DESCRIPCION_482396, "21292", bloques=separada + FILA_10MM + FILA_16MM)
    assert r["estado"] == FILAS_OMISION_CONFIRMADA
    assert r["faltantes"] == [{"codigo_sap": "110002953", "cantidad_kg": 4695}]


def test_dos_cantidades_sueltas_en_la_fila_no_se_elige_ninguna():
    ambigua = [_b("4.695", 312, 1772, 380, 1808), _b("4.659", 385, 1772, 425, 1808), _b("110002953", 430, 1772, 635, 1808)]
    r = _detectar(DESCRIPCION_482396, "21292", bloques=ambigua + FILA_10MM + FILA_16MM)
    assert (r["estado"], r["motivo"]) == (FILAS_NO_CONCLUYENTE, MOTIVO_CANTIDAD_NO_LEIDA)


def test_item_sin_codigo_propio_no_identifica_cual_falta():
    # La descripción de 16MM quedó fuera de su fila: su código no la ata.
    corrida = [FILA_16MM[0], _b("B HORMIGON 16MM 6M A630-420H (N)", 905, 2300, 1625, 2336)]
    r = _detectar(DESCRIPCION_482396, "21292", bloques=[FILA_22MM[0]] + FILA_10MM + corrida)
    assert r["estado"] == FILAS_OMISION_SIN_IDENTIFICAR
    assert r["filas_faltantes"] == 1 and r["faltantes"] == []


def test_suma_distinta_del_peso_no_concluye():
    bloques = [FILA_22MM[0]] + FILA_10MM + FILA_16MM
    r = _detectar(DESCRIPCION_482396, "21300", bloques=bloques)
    assert (r["estado"], r["motivo"]) == (FILAS_NO_CONCLUYENTE, MOTIVO_SUMA_DISTINTA_PESO)
    # Dentro de la tolerancia de 1 kg sí concluye.
    assert _detectar(DESCRIPCION_482396, "21293", bloques=bloques)["estado"] == FILAS_OMISION_CONFIRMADA


def test_peso_ausente_no_concluye():
    r = _detectar(DESCRIPCION_482396, "No encontrado", bloques=[FILA_22MM[0]] + FILA_10MM + FILA_16MM)
    assert (r["estado"], r["motivo"]) == (FILAS_NO_CONCLUYENTE, MOTIVO_PESO_AUSENTE)


def test_codigo_repetido_no_concluye():
    repetido = [_b("4.695110002866", 312, 1772, 635, 1808)]
    r = _detectar(DESCRIPCION_482396, "21292", bloques=repetido + FILA_10MM + FILA_16MM)
    assert (r["estado"], r["motivo"]) == (FILAS_NO_CONCLUYENTE, MOTIVO_CODIGO_REPETIDO)


def test_sin_codigos_en_la_tabla_no_hay_evidencia():
    r = _detectar("B HORMIGON 10MM 6M A440-280H(N)", "7078", textos=["B HORMIGON 10MM 6M A440-280H(N)"])
    assert r["estado"] == FILAS_SIN_EVIDENCIA


# --- trazas reales (sólo texto) ------------------------------------------------

TRAZA_472818 = ["CANTIDAD", "4.554110002824", "Coladas:2617594504,2617594506,2617594603",
                "B HORMIGON 10MM 10M A630-420H (N)", "6.267110002850", "Coladas: 2617834302",
                "Tara : 8.740,000 Peso Bruto : 19.561,000", "PESO KG."]
TRAZA_473253 = ["CANTIDAD", "1.018110002901", "Coladas: 2617116402", "2.282110002923",
                "B HORMIGON 25MM 6M A630-420H (N)", "Coladas: 2617862503", "7.229110002953",
                "B HORMIGON 22MM 6M A630-420H (N)", "Coladas: 2617815602"]
TRAZA_473519 = ["CANTIDAD", "1.520110002847", "Coladas: 2617889602", "1.555110002852",
                "B HORMIGON 10MM 12M A630-420H (N)", "Coladas: 2617871502", "3.134110002936",
                "B HORMIGON 12MM 12M A630-420H (N)", "Coladas: 2617902702"]
TRAZA_482247 = ["CANTIDAD", "13.996110002847", "3HORMIGON 8MM12MA630-420H（N）", "Coladas:2617986502",
                "110002852", "BHORMIGON 10MM12MA630-420H （N)", "Tara:13.580,000 Peso Bruto: 40.408,000"]
TRAZA_473546 = ["CANTIDAD cooIGO 120/110002944", "200/110002921", "051/110002693"]


def test_472818_traza_real_dos_filas_un_item_omision_sin_identificar():
    r = _detectar("B HORMIGON 10MM 10M A630-420H (N)", "10821", textos=TRAZA_472818)
    assert r["estado"] == FILAS_OMISION_SIN_IDENTIFICAR
    assert (r["suma_cantidades_kg"], r["filas_faltantes"]) == (10821, 1)


def test_473253_y_473519_trazas_reales_tres_filas_dos_items():
    for traza, descripcion, peso in (
        (TRAZA_473253, "B HORMIGON 25MM 6M A630-420H (N) | B HORMIGON 22MM 6M A630-420H (N)", "10529"),
        (TRAZA_473519, "B HORMIGON 10MM 12M A630-420H (N) | B HORMIGON 12MM 12M A630-420H (N)", "6209"),
    ):
        r = _detectar(descripcion, peso, textos=traza)
        assert (r["estado"], r["filas_faltantes"], r["suma_cantidades_kg"]) == (FILAS_OMISION_SIN_IDENTIFICAR, 1, int(peso))


def test_482247_traza_real_cantidad_no_leida_es_lectura_parcial():
    r = _detectar("B HORMIGON 8MM 12M A630-420H (N)", "26828", textos=TRAZA_482247)
    assert (r["estado"], r["motivo"]) == (FILAS_NO_CONCLUYENTE, MOTIVO_CANTIDAD_NO_LEIDA)


def test_473546_easyocr_cantidad_truncada_con_barra_no_se_toma():
    filas = filas_material_documentales(textos=TRAZA_473546)
    assert [f.cantidad_kg for f in filas] == [None, None, None]
    r = _detectar("HORMIGON 22MM | HORMIGON 25MM", "27371", textos=TRAZA_473546)
    assert (r["estado"], r["motivo"]) == (FILAS_NO_CONCLUYENTE, MOTIVO_CANTIDAD_NO_LEIDA)


def test_mas_items_que_filas_no_es_omision():
    # Un ítem partido en dos líneas OCR: 2 ítems, 1 fila con suma = peso.
    r = _detectar("B HORMIGON 10MM 10M | A630-420H (N)", "4554", textos=["4.554110002824", "6.267"])
    assert (r["estado"], r["motivo"]) == (FILAS_NO_CONCLUYENTE, MOTIVO_FILAS_NO_SUPERAN_ITEMS)
    r = detectar_filas_material_omitidas(
        analizar_items_material("ITEM A | ITEM B | ITEM C"), peso_kg="10821", textos=TRAZA_472818)
    assert (r["estado"], r["motivo"]) == (FILAS_NO_CONCLUYENTE, MOTIVO_FILAS_NO_SUPERAN_ITEMS)


# --- conexión en el ingreso ----------------------------------------------------


def _procesar(tmp_path, monkeypatch, material, lineas):
    datos = {"número de guía": "472818", "número de transporte": "0000356000", "cliente": "COMERCIAL PRUEBA SPA",
             "obra destino": "OBRA DE PRUEBA CENTRAL", "chofer": "CHOFER DE PRUEBA",
             "RUT del cliente": "11.111.111-1", "RUT del chofer": "11.111.111-1",
             "patente del tracto": "AB1234", "patente del carro": "CD5678", "peso": "10.821,00"}
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=lineas))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", Mock(return_value=datos))
    monkeypatch.setattr(procesamiento_masivo, "extraer_descripcion_material", Mock(return_value=material))
    return procesar_archivo(tmp_path / "guia.jpg")


def test_ingreso_registra_filas_omitidas_solo_en_metricas(tmp_path, monkeypatch):
    material = "B HORMIGON 10MM 10M A630-420H (N)"
    resultado = _procesar(tmp_path, monkeypatch, material, ["FECHA DE EMISION 03-09-2026", *TRAZA_472818])
    filas = json.loads(resultado["metricas_procesamiento_json"])["material_filas"]
    assert filas["estado"] == FILAS_OMISION_SIN_IDENTIFICAR and filas["filas_faltantes"] == 1
    assert resultado["descripcion_material"] == material
    assert "MATERIAL" not in resultado["motivos_revision_documento"]


def test_ingreso_sin_codigos_no_agrega_la_clave(tmp_path, monkeypatch):
    material = "B HORMIGON 10MM 10M A630-420H (N)"
    resultado = _procesar(tmp_path, monkeypatch, material, ["FECHA DE EMISION 03-09-2026", material])
    assert "material_filas" not in json.loads(resultado["metricas_procesamiento_json"])
