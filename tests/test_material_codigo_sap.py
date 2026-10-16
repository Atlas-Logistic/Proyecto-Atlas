"""Materiales AZA, fase 1: código SAP por ítem y material OCR no confiable.

Bloques reales (texto, caja, confianza) tomados de las trazas OCR de 482229,
473309, 474216 y 475346. El material nunca se reemplaza: sólo se observa.
"""
from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from atlas_core import procesamiento_masivo
from atlas_core.material_codigo_sap import (
    ADVERTENCIA_CONTRADICCION_CODIGO, EVIDENCIA_AMBIGUA, EVIDENCIA_MISMA_FILA, EVIDENCIA_SIN_CODIGO,
    EVIDENCIA_UNICO_ITEM_TEXTO, analizar_items_material, codigos_sap_en_texto, senales_material,
)
from atlas_core.procesamiento_masivo import MOTIVOS_NO_BLOQUEANTES, MotivoRevisionDocumento, procesar_archivo


def _b(texto, x0, y0, x1, y1, confianza):
    return {"texto": texto, "bounding_box": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "confianza": confianza}


ENCABEZADO = [_b("CANTIDAD", 98, 376, 139, 387, 1.0), _b("CODIGO", 169, 376, 200, 387, 0.998),
              _b("DESCRIPCION", 326, 377, 381, 388, 0.998)]
BLOQUES_482229 = ENCABEZADO + [_b("27,871110002701", 110, 390, 182, 401, 0.9263),
                               _b("ROLLO HORNIOON 12HéE AE30-420N (N)", 230, 389, 379, 402, 0.6761)]
BLOQUES_473309 = [_b("27.886110002706", 93, 420, 208, 433, 0.9909),
                  _b("ROLLO HORMIGON 8MM A630-420B (N)", 288, 416, 514, 432, 0.9647),
                  _b("Coladas: 2617772102", 289, 432, 425, 447, 0.9952)]
BLOQUES_474216 = [_b("6.050110002847", 127, 481, 199, 491, 0.9984),
                  _b("3 HORMIGON BM4 12H A630-420H (N)", 253, 482, 406, 495, 0.8791),
                  _b("Coladas:2617928302,2617928402", 255, 493, 399, 503, 0.9979)]
REFERENCIAS = {"110002701": "ROLLO HORMIGON 16MM A630-420H (N)", "110002704": "ROLLO HORMIGON 12MM A630-420H (N)",
               "110002706": "ROLLO HORMIGON 8MM A630-420H (N)", "110002847": "B HORMIGON 8MM 12M A630-420H (N)",
               "110002936": "B HORMIGON 12MM 12M A630-420H (N)"}


def test_codigo_sap_se_separa_de_la_cantidad_pegada():
    assert codigos_sap_en_texto("27,871110002701") == ["110002701"]
    assert codigos_sap_en_texto("6.050110002847") == ["110002847"]
    assert codigos_sap_en_texto("1.056,0110002701 | 110002701") == ["110002701"]
    assert codigos_sap_en_texto("Coladas: 2617772102 RUT 92.176.000-0") == []
    assert codigos_sap_en_texto("11000270199") == []  # un dígito más ya no es el código


def test_482229_material_ilegible_con_codigo_de_su_fila_y_texto_original_intacto():
    [item] = analizar_items_material("ROLLO HORNIOON 12HéE AE30-420N (N)", bloques=BLOQUES_482229,
                                     referencias=REFERENCIAS)
    assert item.descripcion_ocr == "ROLLO HORNIOON 12HéE AE30-420N (N)"  # nunca se normaliza
    assert (item.codigo_sap, item.evidencia_codigo) == ("110002701", EVIDENCIA_MISMA_FILA)
    assert item.no_confiable
    assert {"CARACTER_NO_ESPERADO", "FAMILIA_DEFORMADA", "CONFIANZA_OCR_BAJA"} <= set(item.senales)
    # El código leído (701 = 16MM) contradice el "12" legible: advertencia, no corrección.
    assert item.advertencias == [ADVERTENCIA_CONTRADICCION_CODIGO]


def test_473309_calidad_deformada_y_codigo_coherente():
    [item] = analizar_items_material("ROLLO HORMIGON 8MM A630-420B (N)", bloques=BLOQUES_473309,
                                     referencias=REFERENCIAS)
    assert (item.codigo_sap, item.evidencia_codigo) == ("110002706", EVIDENCIA_MISMA_FILA)
    assert item.senales == ["CALIDAD_DEFORMADA"] and item.advertencias == []


def test_474216_diametro_ilegible_aunque_el_extractor_cambio_el_prefijo():
    # El extractor persiste "B HORMIGON..." aunque el bloque OCR diga "3 HORMIGON...".
    [item] = analizar_items_material("B HORMIGON BM4 12H A630-420H (N)", bloques=BLOQUES_474216,
                                     referencias=REFERENCIAS)
    assert (item.codigo_sap, item.evidencia_codigo) == ("110002847", EVIDENCIA_MISMA_FILA)
    assert item.senales == ["MEDIDA_DEFORMADA"]
    assert item.advertencias == []  # "BM4" no trae un diámetro legible que contradiga


@pytest.mark.parametrize("material", [
    "B HORMIGON 8MM 12M A630-420H (N)", "ROLLO HORMIGON 16MM A630-420H (N)", "ALAMBRON 5,5MM AZA 1006 (N)",
    "B HORMIGON 32MM 11M A630-420HS (N)", "ROLLO HORMIGON 12MM A440-280H (N)", "HORMIGON 22MM 12M A630-420H (N)",
    "B HORMIGON 8MM12M A630-420H (N)", "B HORMIGON 12MM/12M A630-420H (N)", "B HORMIGON 10MM 6MA630-420H (N)",
    "B HORMIGON 8MM 12M A630 420H (N)", "B HORMIGON 12MM 6M A630-42OH (N)", "HORMIGON 22MM 6MA630-420H（N)",
    "PLANA 38X5MM 6M A270ES (N)", "ANGULO 120X120X12MM 12M A572 (I)", "CHATARRA C PESADA PARA PROCESAR",
    "SAFEROCK 25MM 12M A420", "ALAMBRON 5,5MM SAE 1005 (I)",
])
def test_materiales_legibles_no_se_marcan(material):
    assert senales_material(material) == ([], [])


@pytest.mark.parametrize("material,senal", [
    ("B HORMIGON 25MM 7N A630-420H", "LARGO_DEFORMADO"),
    ("B HORMIGON 22MM 9K A630-420H (N)", "LARGO_DEFORMADO"),
    ("ALAMBRON 5, 5HM AZA 1006 (N)", "MEDIDA_DEFORMADA"),
    ("ROLLO RORM3 GON 1219M A630-4208 (N)", "FAMILIA_DEFORMADA"),
    ("C1 22.09 BAM/BARRAS CYD", "FRAGMENTO_NO_MATERIAL"),
    ("HORMIGON (DETALLE ILEGIBLE EN OCR)", "DETALLE_ILEGIBLE"),
    ("B HORMIGON 25MM 12M A630-420E (N)", "CALIDAD_DEFORMADA"),
])
def test_deformaciones_reales_se_marcan(material, senal):
    assert senal in senales_material(material)[0]


def test_475346_codigo_mal_leido_contradice_pero_no_vuelve_no_confiable_al_material():
    """La foto dice 110002938 "18MM 12M"; el OCR leyó "...936" (= 12MM 12M)."""
    bloques = [_b("9.401110002936", 87, 457, 170, 467, 0.996),
               _b("B HORMIGON 18MM 12M A630-420H (N)", 229, 453, 415, 464, 0.947)]
    [item] = analizar_items_material("B HORMIGON 18MM 12M A630-420H (N)", bloques=bloques, referencias=REFERENCIAS)
    assert item.codigo_sap == "110002936" and item.senales == []
    assert item.advertencias == [ADVERTENCIA_CONTRADICCION_CODIGO] and not item.no_confiable


def test_codigo_ambiguo_o_compartido_nunca_se_asigna():
    dos_en_fila = BLOQUES_473309 + [_b("110002707", 150, 421, 200, 431, 0.99)]
    [item] = analizar_items_material("ROLLO HORMIGON 8MM A630-420B (N)", bloques=dos_en_fila)
    assert (item.codigo_sap, item.evidencia_codigo) == ("", EVIDENCIA_AMBIGUA)
    # Sin geometría: sólo un ítem con un único código en todo el texto.
    [solo] = analizar_items_material("ROLLO HORMIGON 8MM A630-420B (N)", textos=["27.886110002706"])
    assert (solo.codigo_sap, solo.evidencia_codigo) == ("110002706", EVIDENCIA_UNICO_ITEM_TEXTO)
    varios = analizar_items_material("ROLLO HORMIGON 8MM A630-420H (N) | ROLLO HORMIGON 10MM A630-420H (N)",
                                     textos=["110002706 110002707"])
    assert [i.evidencia_codigo for i in varios] == [EVIDENCIA_SIN_CODIGO, EVIDENCIA_SIN_CODIGO]


# --- conexión en el ingreso ---------------------------------------------------


def _procesar(tmp_path, monkeypatch, material, lineas):
    datos = {"número de guía": "482229", "número de transporte": "0000364161", "cliente": "COMERCIAL PRUEBA SPA",
             "obra destino": "OBRA DE PRUEBA CENTRAL", "chofer": "CHOFER DE PRUEBA",
             "RUT del cliente": "11.111.111-1", "RUT del chofer": "11.111.111-1",
             "patente del tracto": "AB1234", "patente del carro": "CD5678"}
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=lineas))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", Mock(return_value=datos))
    monkeypatch.setattr(procesamiento_masivo, "extraer_descripcion_material", Mock(return_value=material))
    return procesar_archivo(tmp_path / "guia.jpg")


def test_ingreso_marca_material_no_confiable_sin_bloquear_ni_cambiar_el_texto(tmp_path, monkeypatch):
    material = "ROLLO HORNIOON 12HéE AE30-420N (N)"
    resultado = _procesar(tmp_path, monkeypatch, material, ["FECHA DE EMISION 16-10-2026", "27,871110002701", material])
    assert resultado["descripcion_material"] == material
    motivos = resultado["motivos_revision_documento"].split(" | ")
    assert MotivoRevisionDocumento.MATERIAL_OCR_NO_CONFIABLE.value in motivos
    assert MotivoRevisionDocumento.MATERIAL_OCR_NO_CONFIABLE.value in MOTIVOS_NO_BLOQUEANTES
    [item] = json.loads(resultado["metricas_procesamiento_json"])["material_items"]
    assert item["descripcion_ocr"] == material and item["codigo_sap"] == "110002701"
    assert item["evidencia_codigo"] == EVIDENCIA_UNICO_ITEM_TEXTO
    assert "FAMILIA_DEFORMADA" in item["senales"]


def test_ingreso_material_legible_no_agrega_motivo(tmp_path, monkeypatch):
    material = "ROLLO HORMIGON 12MM A630-420H (N)"
    resultado = _procesar(tmp_path, monkeypatch, material, ["FECHA DE EMISION 16-10-2026", "27,871110002704", material])
    assert MotivoRevisionDocumento.MATERIAL_OCR_NO_CONFIABLE.value not in resultado["motivos_revision_documento"]
    [item] = json.loads(resultado["metricas_procesamiento_json"])["material_items"]
    assert item["codigo_sap"] == "110002704" and item["senales"] == []
