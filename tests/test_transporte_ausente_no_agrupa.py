"""Caso real 482179: "No encontrado" en `numero_transporte` es ausencia,
nunca la identidad de un viaje compartido."""
import csv

from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.registro_obra_destino import guias_afectadas_por_registro


def _escribir(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        for fila in filas:
            escritor.writerow({c: "" for c in COLUMNAS} | fila)


def test_registro_de_obra_no_arrastra_guias_ajenas_sin_transporte(tmp_path):
    dataset = tmp_path / "analisis_completo_guias.csv"
    _escribir(dataset, [
        {"numero_guia": "482179", "numero_transporte": "No encontrado", "obra_destino": "OBRA A"},
        {"numero_guia": "472126", "numero_transporte": "No encontrado", "obra_destino": "OBRA B"},
        {"numero_guia": "475000", "numero_transporte": "0000363997", "obra_destino": "OBRA C"},
    ])

    guias, transportes = guias_afectadas_por_registro(
        ruta_dataset=dataset, numero_guia="482179", nombres_obra=["OBRA A"],
    )

    assert guias == {"482179"}
    assert transportes == set()
