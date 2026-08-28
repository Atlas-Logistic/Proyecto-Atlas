"""Bloque MATERIALES Y COHERENCIA OPERACIONAL V1 --
`revalidar_tipo_carga_sin_ocr`: resincroniza `tipo_carga` contra
`clasificador_material.clasificar_material` aplicado al `descripcion_
material` YA persistido, sin OCR.

Causa raíz real (guías 460861/460807): "ANGULO"/"PLANA" ya identifican
la categoría ANGULOS en el clasificador vigente, pero ambas guías se
procesaron ANTES de que esa categoría existiera y quedaron con
`tipo_carga=NO DETERMINADO` sin ninguna vía para resincronizar."""
from __future__ import annotations

import csv

from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import revalidar_tipo_carga_sin_ocr


def _fila(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "1.jpeg", "estado_procesamiento": "OK", "numero_guia": "1",
        "numero_transporte": "T1", "fecha": "01-08-2026", "tipo_carga": "NO DETERMINADO",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _leer(ruta):
    return list(csv.DictReader(ruta.open(encoding="utf-8-sig"), delimiter=";"))


# ============================================================
# 1. Clasificación conocida desde configuración -- caso real 460861
# ============================================================


def test_revalida_angulos_desde_no_determinado(tmp_path):
    fila = _fila(
        numero_guia="460861",
        descripcion_material=(
            "ANGULO 65X65X8MM 6M A270ES | ANGULO 30X30X5MM 6M A270ES | "
            "PLANA 100X6MM 6M A270ES (N) | ANGULO 30X30X3MM 6M A270ES (N)"
        ),
    )
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])
    resultado = revalidar_tipo_carga_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == ["460861"]
    fila_final = _leer(dataset)[0]
    assert fila_final["tipo_carga"] == "ANGULOS"


# ============================================================
# 2. Material desconocido no se fuerza -- sigue NO DETERMINADO
# ============================================================


def test_material_sin_evidencia_conocida_no_se_fuerza(tmp_path):
    fila = _fila(numero_guia="900001", descripcion_material="PRODUCTO GENERICO SIN CATEGORIA CONOCIDA")
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])
    resultado = revalidar_tipo_carga_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == []
    fila_final = _leer(dataset)[0]
    assert fila_final["tipo_carga"] == "NO DETERMINADO"


# ============================================================
# 3. Ya coincide -- idempotente, nunca reescribe innecesariamente
# ============================================================


def test_tipo_carga_ya_correcto_no_se_toca(tmp_path):
    fila = _fila(numero_guia="900002", descripcion_material="B HORMIGON 12MM 11M A630-420H (N)", tipo_carga="BARRAS")
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])
    resultado = revalidar_tipo_carga_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == []


# ============================================================
# 4. Preserva raw OCR / otros campos -- sólo tipo_carga cambia
# ============================================================


def test_solo_tipo_carga_cambia_nunca_descripcion_material_ni_otros_campos(tmp_path):
    fila = _fila(
        numero_guia="900003", cliente="CLIENTE GENERICO SA", rut_cliente="76.111.111-6",
        obra_destino="OBRA GENERICA", chofer="JUAN PEREZ", patente_tracto="AB1234",
        descripcion_material="ANGULO 40X40X4MM 6M A270ES",
    )
    otra_fila = _fila(numero_guia="900004", descripcion_material="", tipo_carga="NO DETERMINADO")
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila, otra_fila])
    resultado = revalidar_tipo_carga_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == ["900003"]

    filas = {f["numero_guia"]: f for f in _leer(dataset)}
    objetivo = filas["900003"]
    assert objetivo["tipo_carga"] == "ANGULOS"
    assert objetivo["descripcion_material"] == "ANGULO 40X40X4MM 6M A270ES"
    assert objetivo["cliente"] == "CLIENTE GENERICO SA"
    assert objetivo["rut_cliente"] == "76.111.111-6"
    assert objetivo["obra_destino"] == "OBRA GENERICA"
    assert objetivo["chofer"] == "JUAN PEREZ"
    assert objetivo["patente_tracto"] == "AB1234"
    assert filas["900004"]["tipo_carga"] == "NO DETERMINADO"  # otra fila, intacta


# ============================================================
# 5. Fixture universal -- otro rubro, nada relacionado con acero
# ============================================================


def test_fixture_universal_alias_configurable_por_rubro_distinto(tmp_path):
    """La clasificación es una función pura de `descripcion_material`
    contra las categorías configuradas -- nunca asume acero/construcción.
    Para un rubro sin ninguna de las categorías ya conocidas, el
    resultado correcto y honesto sigue siendo NO DETERMINADO (no se
    inventa una clasificación que Atlas no conoce)."""
    fila = _fila(numero_guia="900005", descripcion_material="CAJA CONGELADOS 20KG | BOTELLA VIDRIO 750ML")
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])
    resultado = revalidar_tipo_carga_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == []
    assert _leer(dataset)[0]["tipo_carga"] == "NO DETERMINADO"


# ============================================================
# 6. Regresión real -- 460807 (mismo patrón que 460861)
# ============================================================


def test_revalida_angulos_460807(tmp_path):
    fila = _fila(
        numero_guia="460807",
        descripcion_material="ANGULO 25X25X3MM 6M A270ES (N) | ANGULO 50X50X5MM 6M A270ES (N) | REDONDO LISO 10MM 6M",
    )
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])
    resultado = revalidar_tipo_carga_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == ["460807"]
    assert _leer(dataset)[0]["tipo_carga"] == "ANGULOS"
