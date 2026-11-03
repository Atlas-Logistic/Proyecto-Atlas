"""P0 materiales contaminados nunca se persisten (03/11/2026).

EasyOCR (paragraph=True) fusiona membrete, cliente, transportista y producto
en un solo renglón (482107, 482166). Si lo depurado seguía sin pasar el
evaluador de credibilidad, el extractor conservaba la línea completa (473444)
y el valor contaminado se publicaba como material. Ahora cada ítem creíble se
conserva, el que sigue contaminado se recorta hasta su primer marcador de
producto o se descarta, y lo que aun así quede contaminado no se registra
como material: queda vacío, con su motivo y la lectura en las métricas.
Lecturas reales: párrafos EasyOCR de los originales Mobile y trazas OCR.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from unittest.mock import Mock

import pytest

from atlas_core import procesamiento_masivo, revalidacion_documental
from atlas_core.credibilidad_campos import NivelCredibilidad, evaluar_credibilidad_material
from atlas_core.procesamiento_masivo import extraer_descripcion_material, procesar_archivo
from atlas_core.revalidacion_documental import recuperar_material_ausente_desde_traza_ocr_sin_ocr
from tests.test_c1_credibilidad_general import _MATERIAL_CONTAMINADO_472624, _datos_base, _preparar_mocks
from tests.test_material_ocr_vocabulario_y_degradado import _fila, _leer, _raiz

_FIXTURES = Path(__file__).parent / "fixtures"
# Etiquetas de otras secciones de la guía que nunca son material.
_AJENAS = ("CLIENTE", "EMISION", "SENOR", "RUT", "GIRO", "DIRECCION", "COMUNA", "CIUDAD", "TRASLADO",
           "TRANSPORTE", "VALOR TOTAL", "DESPACHAR", "CHOFER", "FECHA SALIDA")


def _lineas(guia: str) -> list[str]:
    completa = _FIXTURES / "trazas_ocr_aza" / f"{guia}.json"
    if completa.is_file():
        return json.loads(completa.read_text(encoding="utf-8"))["ocr"]["lineas"]
    return json.loads((_FIXTURES / "material_lineas_ocr" / f"{guia}.json").read_text(encoding="utf-8"))["lineas"]


def _sin_secciones_ajenas(material: str) -> bool:
    normalizado = procesamiento_masivo._normalizar(material)
    return not any(etiqueta in normalizado for etiqueta in _AJENAS)


def _creible(material: str) -> bool:
    return evaluar_credibilidad_material(material).nivel != NivelCredibilidad.INVALIDO


# ------------------------------------------------------------ extractor, evidencia real


def test_482107_parrafo_easyocr_conserva_solo_el_producto():
    material = extraer_descripcion_material(_lineas("482107"))

    assert material == "ROLLO HORMIGON 1 6MM A630-420H (N) 16 Coladas 2617901502,261790]602"
    assert _sin_secciones_ajenas(material) and _creible(material)


def test_482166_parrafo_easyocr_conserva_las_cuatro_partidas_sin_membrete():
    material = extraer_descripcion_material(_lineas("482166"))

    assert material.split(" | ") == [
        "HORMIGON 161M 9K A630-4205 (N) Coladas: 2617994602,2617995002",
        "HORMIGON 1OvM 12M A630-420H (N) 3.124/110002852 Coladas 2617661902 3",
        ".043/110002936 3 HORKIGON 121M 12M A630-4201 (n) [coladas: 2617853002",
        "HORKIGON 221M BK 1630-420H (N) 3.118/110002945 Coladas 2617820202",
    ]
    assert _sin_secciones_ajenas(material) and _creible(material)


def test_482151_pie_de_tabla_fusionado_se_descarta():
    material = extraer_descripcion_material(_lineas("482151"))

    assert material == "ROLLO HORMIGON 1 6MM 1630-420H (N) Coladas 2617901202,2617901702,2617902102,26179021 03"
    assert _sin_secciones_ajenas(material) and _creible(material)


def test_473444_lo_depurado_contaminado_ya_no_devuelve_la_linea_completa():
    material = extraer_descripcion_material(_lineas("473444"))

    assert material.split(" | ") == [
        "HORMIGON BVN I2H 1630 420x Coladas 2617889202 3",
        ".048/110002929 HORYIGON 16YY 12k A630-420H Coladas: 2617858702,2617880805 3",
    ]
    assert _sin_secciones_ajenas(material) and _creible(material)


def test_473391_partidas_legitimas_fusionadas_se_conservan_todas():
    # Siete partidas reales en un renglón: sólo es largo, no contaminado.
    assert extraer_descripcion_material(_lineas("473391")).split(" | ") == [
        "HORKIGON 22MM 6K 4630-420H (N) Coladas: 2617815602",
        "HORMIGON 22MM BM 1630 4204 (N) Coladas : 2617677702,2617690612",
        "HORKIGON 22MM 9M 4630 4204 (N) Coladas 2617813402",
        "HORMIGON 22MM 7M 1630 4201 (N) Coladas: 2617818102",
        "HORMIGON 25MM 1OM A630-420H (N) Coladas: 2617768002",
        "HORMIGON 32MM 1OM A630- 4204 Coladas: 2617652002",
        "HORMIGON 6MK 12K 4630 4204 (N) Coladas 2617880903",
    ]


@pytest.mark.parametrize(("guia", "esperado"), [
    ("483897", "B HORMIGON 10MM6M A630-420H (N)"),
    ("483812", "HORMIGON 10MM6MA440-280H （N) | B HORMIGON 16MM7M A630-4201I (N) | B HORMIGON 18MM7MA630-420H(N）"),
])
def test_materiales_ya_correctos_no_cambian(guia, esperado):
    assert extraer_descripcion_material(_lineas(guia)) == esperado


@pytest.mark.parametrize("producto", [
    "ROLLO HORMIGON 12MM A630-420H (N)", "B HORMIGON 22MM 12M A630-420H (N)", "ALAMBRON 9,5MM AZA 1006 (N)",
    "SAFEROCK 25MM 12M A420",
])
def test_materiales_legitimos_en_tabla_no_cambian(producto):
    lineas = ["CANTIDAD", "CODIGO", "DESCRIPCION", producto, "Coladas: 2617880102", "TIPODEDOCUMENTO"]
    assert extraer_descripcion_material(lineas) == producto


def test_linea_contaminada_que_no_se_puede_recortar_se_abstiene():
    # Acentos descompuestos (NFD): los índices normalizados no sirven para
    # cortar; antes se conservaba la línea completa con el membrete.
    linea = unicodedata.normalize("NFD", _lineas("482107")[
        next(i for i, l in enumerate(_lineas("482107")) if "ROLLO HORMIGON" in l)])

    assert extraer_descripcion_material([linea]) == ""


# ------------------------------------------------------------ barreras antes de persistir


def test_procesar_archivo_no_registra_material_contaminado(tmp_path, monkeypatch):
    _preparar_mocks(monkeypatch, _datos_base(), descripcion_material=_MATERIAL_CONTAMINADO_472624)

    resultado = procesar_archivo(tmp_path / "guia.jpg")

    assert resultado["descripcion_material"] == ""
    assert "MATERIAL_POSIBLEMENTE_CONTAMINADO" in resultado["motivos_revision_documento"]
    assert resultado["estado_documental"] == "REQUIERE_REVISION"
    descartado = json.loads(resultado["metricas_procesamiento_json"])["material_contaminado_descartado"]
    assert descartado["lectura_ocr"] == _MATERIAL_CONTAMINADO_472624
    assert "ETIQUETAS_DE_OTRAS_SECCIONES" in " ".join(descartado["senales"])


def test_procesar_archivo_material_creible_no_cambia(tmp_path, monkeypatch):
    _preparar_mocks(monkeypatch, _datos_base(), descripcion_material="ROLLO HORMIGON 16MM A630-420H (N)")

    resultado = procesar_archivo(tmp_path / "guia.jpg")

    assert resultado["descripcion_material"] == "ROLLO HORMIGON 16MM A630-420H (N)"
    assert "material_contaminado_descartado" not in json.loads(resultado["metricas_procesamiento_json"])


def test_revalidacion_desde_traza_no_completa_con_material_contaminado(tmp_path, monkeypatch):
    ruta = _raiz(tmp_path, [_fila()], {"lote/a.jpeg": ["B HORMIGON 16MM 12M A630-420H (N)"]})
    monkeypatch.setattr(revalidacion_documental, "extraer_descripcion_material",
                        Mock(return_value=_MATERIAL_CONTAMINADO_472624))

    resultado = recuperar_material_ausente_desde_traza_ocr_sin_ocr(raiz_atlas=tmp_path)

    fila = _leer(ruta)[0]
    assert resultado["guias_actualizadas"] == []
    assert fila["descripcion_material"] == "" and "MATERIAL_AUSENTE" in fila["motivos_revision_documento"]
    traza = json.loads(fila["metricas_procesamiento_json"])["recuperacion_p0"]["material_traza"]
    assert traza["resultado"] == "ABSTENCION"
