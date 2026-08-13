"""INFRAESTRUCTURA S2.2 -- el CLI publica el manifiesto portable de operación vigente."""

from __future__ import annotations

import csv
import json
import sys

import generar_reporte_viajes
from atlas_core.reporte_viajes import COLUMNAS_OFICIALES


def _fila(**cambios):
    fila = {columna: "" for columna in COLUMNAS_OFICIALES}
    fila.update(
        archivo="guia1.jpg",
        estado_procesamiento="OK",
        numero_guia="462429",
        numero_transporte="0000346311",
        fecha="2026-07-28",
        chofer="JUAN PEREZ",
        rut_chofer="18.611.137-0",
        cliente="CONSTRUCTORA EJEMPLO SPA",
        obra_destino="EDIFICIO ATLAS",
        patente_tracto="BKYX63",
        patente_rampla="JB8529",
        descripcion_material="FIERRO",
        tipo_carga="FIERRO",
        indicador_revision="OK",
    )
    fila.update(cambios)
    return fila


def _escribir_csv(ruta, filas):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(
            archivo, fieldnames=list(COLUMNAS_OFICIALES), delimiter=";", extrasaction="ignore",
        )
        escritor.writeheader()
        escritor.writerows(filas)


def test_publica_manifiesto_si_salida_y_csv_viven_dentro_de_atlas_data_dir(tmp_path, monkeypatch):
    raiz = tmp_path / "Atlas"
    monkeypatch.setenv("ATLAS_DATA_DIR", str(raiz))
    csv_origen = raiz / "operacion" / "procesamiento" / "analisis_completo_guias.csv"
    _escribir_csv(csv_origen, [_fila()])
    salida = raiz / "reportes" / "actual"

    monkeypatch.setattr(
        sys, "argv",
        ["generar_reporte_viajes.py", str(csv_origen), str(salida), "--catalogos", str(tmp_path / "catalogos")],
    )
    generar_reporte_viajes.main()

    ruta_manifiesto = raiz / "operacion" / "actual" / "estado_operacion.json"
    assert ruta_manifiesto.is_file()
    contenido = json.loads(ruta_manifiesto.read_text(encoding="utf-8"))
    assert contenido["schema_version"] == 1
    assert contenido["reporte_vigente"] == "reportes/actual"
    assert contenido["dataset_operacional"] == "operacion/procesamiento/analisis_completo_guias.csv"
    assert contenido["fecha_actualizacion"]


def test_no_publica_nada_si_salida_vive_fuera_de_atlas_data_dir(tmp_path, monkeypatch):
    # Uso local/de desarrollo de siempre -- ATLAS_DATA_DIR apunta a otro
    # lado, --salida/csv no viven ahi. Debe comportarse exactamente igual
    # que antes de S2.2: sin manifiesto, sin error, reporte generado igual.
    raiz = tmp_path / "Atlas"
    monkeypatch.setenv("ATLAS_DATA_DIR", str(raiz))
    csv_origen = tmp_path / "analisis_completo_guias.csv"
    _escribir_csv(csv_origen, [_fila()])
    salida = tmp_path / "output" / "reporte_local"

    monkeypatch.setattr(
        sys, "argv",
        ["generar_reporte_viajes.py", str(csv_origen), str(salida), "--catalogos", str(tmp_path / "catalogos")],
    )
    generar_reporte_viajes.main()

    assert not (raiz / "operacion" / "actual" / "estado_operacion.json").exists()
    assert salida.is_dir()  # el reporte se genero igual, con normalidad


def test_no_publica_nada_sin_atlas_data_dir_configurado(tmp_path, monkeypatch):
    monkeypatch.delenv("ATLAS_DATA_DIR", raising=False)
    csv_origen = tmp_path / "analisis_completo_guias.csv"
    _escribir_csv(csv_origen, [_fila()])
    salida = tmp_path / "reporte_local"

    monkeypatch.setattr(
        sys, "argv",
        ["generar_reporte_viajes.py", str(csv_origen), str(salida), "--catalogos", str(tmp_path / "catalogos")],
    )
    generar_reporte_viajes.main()

    assert salida.is_dir()
