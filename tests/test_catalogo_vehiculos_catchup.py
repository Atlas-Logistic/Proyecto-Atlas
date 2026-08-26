"""Bloque BARRIDO GENERAL DE PATENTES SOSPECHOSAS -- catch-up FOCAL del
catálogo/histórico de vehículos, read-only.

Caso real que motivó los umbrales calibrados: BKYX63 (1 aparición
total) vs BKYK63 (15), mismo chofer/RUT, K/X ya calibrada -> se plegó
(bloque anterior). Este mismo catch-up, corrido contra el catálogo
real completo, encontró además 3 pares estructuralmente sospechosos
que NO deben plegarse -- JD8659/JE8659 y PXHH31/PXHH32 (ambos lados con
`procedencia=CONFIRMACION_HUMANA`, Javier verificó cada patente contra
guías/imágenes reales y las registró como entidades DISTINTAS -- ver
`respaldos/JD8659_Y_REFRESCO_464717_.../LEEME_ROLLBACK.md`) y
JF9565/JF9575 (sin confusión OCR calibrada entre "6"/"7", evidencia no
suficientemente lopsided). Los tests de este archivo usan patentes
sintéticas para probar la regla GENERAL; el caso real completo se
valida por separado contra producción."""
from __future__ import annotations

from dataclasses import dataclass

from atlas_core.catalogo_vehiculos_catchup import (
    CLASE_AMBIGUO,
    CLASE_OCR_INEQUIVOCO,
    CLASE_VEHICULO_REAL,
    clasificar_par,
    construir_universo_patentes,
    detectar_pares_sospechosos,
    generar_reporte_catchup_patentes,
)
from atlas_core.procesamiento_masivo import COLUMNAS


def _fila(**cambios):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "1.jpeg", "estado_procesamiento": "OK", "numero_guia": "1",
        "numero_transporte": "T-1", "fecha": "18-08-2026", "chofer": "CHOFER PRUEBA",
        "rut_chofer": "12.345.678-5", "patente_tracto": "AB1234", "patente_rampla": "",
    })
    fila.update(cambios)
    return fila


@dataclass
class _VehiculoFake:
    patente_canonica: str
    tipo: str = "TRACTO"
    procedencia: str = "CATALOGO_LEGACY"
    confirmado_por: str = ""


# ============================================================
# A -- OCR inequívoco: único candidato, contexto convergente, lopsided
# ============================================================


def test_ocr_inequivoco_se_pliega_con_contexto_convergente_y_frecuencia_lopsided():
    filas = [
        _fila(numero_guia="1", chofer="CHOFER PRUEBA", rut_chofer="12.345.678-5", patente_tracto="AD1234"),
        _fila(numero_guia="2", chofer="CHOFER PRUEBA", rut_chofer="12.345.678-5", patente_tracto="AD1234"),
        _fila(numero_guia="3", chofer="CHOFER PRUEBA", rut_chofer="12.345.678-5", patente_tracto="AD1234"),
        _fila(numero_guia="4", chofer="CHOFER PRUEBA", rut_chofer="12.345.678-5", patente_tracto="AB1234"),
    ]
    vehiculos = {"AD1234": _VehiculoFake("AD1234")}
    universo = construir_universo_patentes(filas=filas, vehiculos_por_patente=vehiculos)
    pares = detectar_pares_sospechosos(universo)
    assert ("AB1234", "AD1234") in pares
    resultado = clasificar_par(("AB1234", "AD1234"), universo)
    assert resultado.clase == CLASE_OCR_INEQUIVOCO
    assert resultado.patente_sospechosa == "AB1234"
    assert resultado.patente_candidata == "AD1234"


# ============================================================
# B -- frecuencia baja pero vehículo real (sin confusión calibrada / sin candidato)
# ============================================================


def test_frecuencia_baja_sin_confusion_ocr_calibrada_nunca_se_pliega():
    # "AB1234" vs "AC1234": B/C no es una confusión OCR calibrada.
    filas = [
        _fila(numero_guia="1", patente_tracto="AC1234"),
        _fila(numero_guia="2", patente_tracto="AC1234"),
        _fila(numero_guia="3", patente_tracto="AC1234"),
        _fila(numero_guia="4", patente_tracto="AB1234"),
    ]
    universo = construir_universo_patentes(filas=filas)
    resultado = clasificar_par(("AB1234", "AC1234"), universo)
    assert resultado.clase == CLASE_AMBIGUO


def test_patente_unica_sin_par_sospechoso_no_genera_ninguna_clasificacion():
    filas = [_fila(numero_guia="1", patente_tracto="ZZ9999")]
    universo = construir_universo_patentes(filas=filas)
    assert detectar_pares_sospechosos(universo) == []


# ============================================================
# C -- confirmación humana explícita: nunca se pliega (caso real
# JD8659/JE8659, PXHH31/PXHH32)
# ============================================================


def test_confirmacion_humana_explicita_protege_incluso_con_confusion_ocr_calibrada_y_baja_frecuencia():
    filas = [
        _fila(numero_guia="1", patente_tracto="AD1234"),
        _fila(numero_guia="2", patente_tracto="AD1234"),
        _fila(numero_guia="3", patente_tracto="AD1234"),
        _fila(numero_guia="4", patente_tracto="AB1234"),
    ]
    vehiculos = {
        "AD1234": _VehiculoFake("AD1234"),
        "AB1234": _VehiculoFake("AB1234", procedencia="CONFIRMACION_HUMANA", confirmado_por="JAVIER_MBT"),
    }
    universo = construir_universo_patentes(filas=filas, vehiculos_por_patente=vehiculos)
    resultado = clasificar_par(("AB1234", "AD1234"), universo)
    assert resultado.clase == CLASE_VEHICULO_REAL
    assert "CONFIRMACION_HUMANA_EN_CATALOGO" in resultado.evidencia


# ============================================================
# D -- dos patentes similares, mismo chofer, cambio REAL de vehículo
# (ninguna lopsided) -> AMBIGUO, nunca fusionar (Sección 12, caso B)
# ============================================================


def test_mismo_chofer_con_evidencia_comparable_en_ambos_lados_no_se_fusiona():
    filas = [
        _fila(numero_guia="1", chofer="CHOFER PRUEBA", rut_chofer="12.345.678-5", patente_tracto="AD1234"),
        _fila(numero_guia="2", chofer="CHOFER PRUEBA", rut_chofer="12.345.678-5", patente_tracto="AD1234"),
        _fila(numero_guia="3", chofer="CHOFER PRUEBA", rut_chofer="12.345.678-5", patente_tracto="AD1234"),
        _fila(numero_guia="4", chofer="CHOFER PRUEBA", rut_chofer="12.345.678-5", patente_tracto="AB1234"),
        _fila(numero_guia="5", chofer="CHOFER PRUEBA", rut_chofer="12.345.678-5", patente_tracto="AB1234"),
        _fila(numero_guia="6", chofer="CHOFER PRUEBA", rut_chofer="12.345.678-5", patente_tracto="AB1234"),
    ]
    universo = construir_universo_patentes(filas=filas)
    resultado = clasificar_par(("AB1234", "AD1234"), universo)
    assert resultado.clase == CLASE_AMBIGUO  # 3 vs 3 -- ninguno "aparece 1-2 veces", nunca se fusiona


# ============================================================
# Rol incompatible -- TRACTO vs CARRO nunca se comparan (Sección 12, caso C)
# ============================================================


def test_mismo_patron_textual_pero_roles_distintos_nunca_se_compara():
    filas = [
        _fila(numero_guia="1", patente_tracto="AD1234", patente_rampla=""),
        _fila(numero_guia="2", patente_tracto="", patente_rampla="AB1234"),
    ]
    universo = construir_universo_patentes(filas=filas)
    assert universo["AD1234"].roles == frozenset({"TRACTO"})
    assert universo["AB1234"].roles == frozenset({"CARRO"})
    assert detectar_pares_sospechosos(universo) == []


# ============================================================
# Confusión OCR calibrada pero sin ningún contexto convergente ->
# tampoco se resuelve sola (ninguna elección "a ciegas")
# ============================================================


def test_confusion_calibrada_sin_ningun_chofer_rut_en_comun_no_se_resuelve_sola():
    filas = [
        _fila(numero_guia="1", chofer="CHOFER A", rut_chofer="1-9", patente_tracto="AD1234"),
        _fila(numero_guia="2", chofer="CHOFER A", rut_chofer="1-9", patente_tracto="AD1234"),
        _fila(numero_guia="3", chofer="CHOFER A", rut_chofer="1-9", patente_tracto="AD1234"),
        _fila(numero_guia="4", chofer="CHOFER B", rut_chofer="2-7", patente_tracto="AB1234"),
    ]
    universo = construir_universo_patentes(filas=filas)
    # "AB1234"/"AD1234" difieren en B/D (calibrada) y la frecuencia es
    # lopsided (1 vs 3), pero ningún chofer/RUT es compartido -- Atlas
    # nunca elige a ciegas sólo por la forma del texto.
    resultado = clasificar_par(("AB1234", "AD1234"), universo)
    assert resultado.clase == CLASE_AMBIGUO


# ============================================================
# Histórico/ledger preservados -- nunca escribe nada
# ============================================================


def test_generar_reporte_nunca_escribe_nada(tmp_path):
    import csv
    import json

    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    catalogos.mkdir(parents=True)
    actual.mkdir(parents=True)
    (catalogos / "vehiculos.json").write_text(json.dumps({"version": 1, "vehiculos": []}), encoding="utf-8")
    dataset = actual / "analisis_completo_guias.csv"
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerow(_fila())

    antes_catalogo = (catalogos / "vehiculos.json").read_bytes()
    antes_dataset = dataset.read_bytes()
    reporte = generar_reporte_catchup_patentes(raiz_atlas=raiz)
    assert (catalogos / "vehiculos.json").read_bytes() == antes_catalogo
    assert dataset.read_bytes() == antes_dataset
    assert isinstance(reporte["patentes_revisadas"], int)
    assert isinstance(reporte["clasificaciones"], list)


# ============================================================
# E2E -- reproduce el catálogo real (valores sintéticos, mismo patrón
# ya usado en test_vehiculo_autonomia_e2.py y en el bloque BKYX63)
# ============================================================


def test_e2e_catalogo_con_par_confirmado_humano_y_par_ocr_inequivoco():
    filas = [
        # Par OCR_INEQUIVOCO real (BKYX63/BKYK63 con valores sintéticos).
        _fila(numero_guia="1", chofer="CHOFER UNO", rut_chofer="1-9", patente_tracto="BKYK63"),
        _fila(numero_guia="2", chofer="CHOFER UNO", rut_chofer="1-9", patente_tracto="BKYK63"),
        _fila(numero_guia="3", chofer="CHOFER UNO", rut_chofer="1-9", patente_tracto="BKYK63"),
        _fila(numero_guia="4", chofer="CHOFER UNO", rut_chofer="1-9", patente_tracto="BKYX63"),
    ]
    vehiculos = {
        "BKYK63": _VehiculoFake("BKYK63"),
        # Par CONFIRMACION_HUMANA real (JD8659/JE8659 con valores
        # sintéticos) -- sin apariciones en el dataset vigente, igual
        # que el caso real.
        "JD8659": _VehiculoFake("JD8659", tipo="CARRO", procedencia="CONFIRMACION_HUMANA", confirmado_por="JAVIER_MBT"),
        "JE8659": _VehiculoFake("JE8659", tipo="CARRO", procedencia="CONFIRMACION_HUMANA", confirmado_por="JAVIER_MBT"),
    }
    universo = construir_universo_patentes(filas=filas, vehiculos_por_patente=vehiculos)
    clasificaciones = {
        frozenset(par): clasificar_par(par, universo) for par in detectar_pares_sospechosos(universo)
    }
    ocr = clasificaciones[frozenset({"BKYX63", "BKYK63"})]
    assert ocr.clase == CLASE_OCR_INEQUIVOCO
    protegido = clasificaciones[frozenset({"JD8659", "JE8659"})]
    assert protegido.clase == CLASE_VEHICULO_REAL
