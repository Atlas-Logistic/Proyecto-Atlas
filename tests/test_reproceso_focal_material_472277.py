"""Regresión explícita -- REPROCESO FOCAL DE MATERIAL (Codex 0000354651,
472277, PRODALAM SA): `descripcion_material` vacío, `MATERIAL_AUSENTE`,
imagen original conservada. `reprocesar_material_focal_desde_imagen_
original` reintenta `extraer_descripcion_material` sobre la imagen YA
existente -- la ÚNICA función de todo el módulo que ejecuta OCR nuevo, y
sólo cuando se invoca explícitamente para UNA guía. El OCR real (EasyOCR)
se sustituye por un doble de prueba (`atlas_core.ocr.leer_texto_imagen`)
-- nunca se ejercita el motor OCR real en la suite, sólo el contrato de
esta función con lo que el OCR le devuelva."""
from __future__ import annotations

import csv
import json

import pytest
from PIL import Image

from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    reprocesar_material_focal_desde_imagen_original,
)

NUMERO_GUIA = "472277"
ARCHIVO = "472277.jpeg"


def _fila(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update(
        archivo=ARCHIVO, numero_guia=NUMERO_GUIA, numero_transporte="0000354651",
        cliente="PRODALAM SA", descripcion_material="", tipo_carga="NO DETERMINADO",
        motivos_revision_documento="MATERIAL_AUSENTE",
        indicador_revision="OK", estado_documental="OK", estado_operacional="OK",
        estado_ruta="RUTA_CALCULADA", motivo_ruta="",
        resultado_atlas_ia_json=json.dumps([], ensure_ascii=False),
    )
    fila.update(overrides)
    return fila


def _entorno(tmp_path, *, filas, con_imagen=True):
    raiz = tmp_path / "Atlas"
    actual = raiz / "operacion" / "actual"
    entradas = raiz / "operacion" / "entradas" / "20260908_161803"
    actual.mkdir(parents=True)
    entradas.mkdir(parents=True)
    with (actual / "analisis_completo_guias.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS, delimiter=";")
        w.writeheader()
        w.writerows(filas)
    if con_imagen:
        Image.new("RGB", (4, 4), color="white").save(entradas / ARCHIVO)
    return raiz


def _leer_csv(raiz):
    ruta = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    with ruta.open(newline="", encoding="utf-8-sig") as fh:
        return {f["numero_guia"]: f for f in csv.DictReader(fh, delimiter=";")}


# ============================================================
# 1. Recupera el material real desde la imagen
# ============================================================


def test_recupera_material_real_tras_reproceso_focal(tmp_path, monkeypatch):
    raiz = _entorno(tmp_path, filas=[_fila()])
    monkeypatch.setattr(
        "atlas_core.ocr.leer_texto_imagen",
        lambda ruta, lector=None: ["B HORMIGON 25MM 12M A630-420H (N)"],
    )
    resultado = reprocesar_material_focal_desde_imagen_original(raiz_atlas=raiz, numero_guia=NUMERO_GUIA)
    assert resultado["aplicado"] is True
    assert resultado["descripcion_material"] == "B HORMIGON 25MM 12M A630-420H (N)"

    fila = _leer_csv(raiz)[NUMERO_GUIA]
    assert fila["descripcion_material"] == "B HORMIGON 25MM 12M A630-420H (N)"
    assert fila["tipo_carga"] != "NO DETERMINADO"
    assert "MATERIAL_AUSENTE" not in fila["motivos_revision_documento"]
    assert fila["indicador_revision"] == "OK"
    assert fila["estado_documental"] == "OK"


def test_nunca_toca_otros_campos_de_la_fila(tmp_path, monkeypatch):
    raiz = _entorno(tmp_path, filas=[_fila(fecha="23-08-2026", chofer="CRISTOPHER RETAMAL")])
    monkeypatch.setattr(
        "atlas_core.ocr.leer_texto_imagen",
        lambda ruta, lector=None: ["B HORMIGON 25MM 12M A630-420H (N)"],
    )
    reprocesar_material_focal_desde_imagen_original(raiz_atlas=raiz, numero_guia=NUMERO_GUIA)
    fila = _leer_csv(raiz)[NUMERO_GUIA]
    assert fila["fecha"] == "23-08-2026"  # nunca re-derivado, aunque el OCR completo re-lea toda la imagen
    assert fila["chofer"] == "CRISTOPHER RETAMAL"


# ============================================================
# 2. Sigue sin material tras el reproceso -- nunca inventa
# ============================================================


def test_conserva_material_ausente_si_el_reproceso_no_encuentra_nada(tmp_path, monkeypatch):
    raiz = _entorno(tmp_path, filas=[_fila()])
    monkeypatch.setattr(
        "atlas_core.ocr.leer_texto_imagen",
        lambda ruta, lector=None: ["GUIA DE DESPACHO", "PRODALAM SA"],  # sin evidencia de material
    )
    resultado = reprocesar_material_focal_desde_imagen_original(raiz_atlas=raiz, numero_guia=NUMERO_GUIA)
    assert resultado["aplicado"] is False
    assert resultado["motivo"] == "MATERIAL_NO_RECUPERABLE_TRAS_REPROCESO"

    fila = _leer_csv(raiz)[NUMERO_GUIA]
    assert fila["descripcion_material"] == ""
    assert "MATERIAL_AUSENTE" in fila["motivos_revision_documento"]


# ============================================================
# 3. Abstenciones -- nunca sobrescribe evidencia real ni inventa
# ============================================================


def test_abstiene_si_ya_tiene_material(tmp_path, monkeypatch):
    raiz = _entorno(tmp_path, filas=[_fila(descripcion_material="YA TIENE MATERIAL")])
    llamado = []
    monkeypatch.setattr("atlas_core.ocr.leer_texto_imagen", lambda *a, **k: llamado.append(1) or [])
    resultado = reprocesar_material_focal_desde_imagen_original(raiz_atlas=raiz, numero_guia=NUMERO_GUIA)
    assert resultado["aplicado"] is False
    assert resultado["motivo"] == "MATERIAL_YA_PRESENTE"
    assert llamado == []  # nunca ejecuta OCR si no hace falta


def test_abstiene_si_no_tiene_motivo_material_ausente(tmp_path, monkeypatch):
    raiz = _entorno(tmp_path, filas=[_fila(motivos_revision_documento="")])
    llamado = []
    monkeypatch.setattr("atlas_core.ocr.leer_texto_imagen", lambda *a, **k: llamado.append(1) or [])
    resultado = reprocesar_material_focal_desde_imagen_original(raiz_atlas=raiz, numero_guia=NUMERO_GUIA)
    assert resultado["aplicado"] is False
    assert resultado["motivo"] == "SIN_MOTIVO_MATERIAL_AUSENTE"
    assert llamado == []


def test_abstiene_si_la_guia_no_existe(tmp_path):
    raiz = _entorno(tmp_path, filas=[_fila()])
    resultado = reprocesar_material_focal_desde_imagen_original(raiz_atlas=raiz, numero_guia="999999")
    assert resultado["aplicado"] is False
    assert resultado["motivo"] == "GUIA_NO_ENCONTRADA"


def test_abstiene_si_la_imagen_original_no_existe(tmp_path):
    raiz = _entorno(tmp_path, filas=[_fila()], con_imagen=False)
    resultado = reprocesar_material_focal_desde_imagen_original(raiz_atlas=raiz, numero_guia=NUMERO_GUIA)
    assert resultado["aplicado"] is False
    assert resultado["motivo"].startswith("IMAGEN_")
    fila = _leer_csv(raiz)[NUMERO_GUIA]
    assert fila["descripcion_material"] == ""  # dataset intacto


def test_no_genera_ninguna_decision_humana(tmp_path, monkeypatch):
    """MATERIAL_AUSENTE no tiene tipo de decisión asociado (ver Desktop) --
    el reproceso nunca debe empezar a generar una."""
    raiz = _entorno(tmp_path, filas=[_fila()])
    monkeypatch.setattr(
        "atlas_core.ocr.leer_texto_imagen",
        lambda ruta, lector=None: ["GUIA DE DESPACHO"],
    )
    reprocesar_material_focal_desde_imagen_original(raiz_atlas=raiz, numero_guia=NUMERO_GUIA)
    ruta_decisiones = raiz / "operacion" / "actual" / "decisiones_pendientes.json"
    assert not ruta_decisiones.exists()
