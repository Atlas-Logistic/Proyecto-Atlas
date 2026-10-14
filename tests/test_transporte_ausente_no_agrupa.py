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


def test_corroboracion_de_chofer_no_cuenta_transporte_ausente_como_senal(tmp_path):
    from atlas_core.procesamiento_masivo import _corroborar_documentos_relacionados_bajo_lock

    dataset = tmp_path / "analisis_completo_guias.csv"
    comunes = {"fecha": "13-10-2026", "chofer": "LUIS VARAS", "patente_tracto": "DD2494",
               "numero_transporte": "No encontrado", "estado_procesamiento": "OK"}
    _escribir(dataset, [
        {**comunes, "archivo": "482179.jpeg", "numero_guia": "482179", "obra_destino": "OBRA A",
         "rut_chofer": "No encontrado", "motivos_revision_documento": "CHOFER_SIN_CORROBORAR"},
        {**comunes, "archivo": "472126.jpeg", "numero_guia": "472126", "obra_destino": "OBRA B",
         "rut_chofer": "14293816-2"},
    ])

    # fecha + chofer + patente = 3 señales; el transporte ausente en ambas
    # no puede ser la cuarta.
    assert _corroborar_documentos_relacionados_bajo_lock(dataset, {"482179.jpeg"}) == 0


def test_evidencia_b1_de_documento_relacionado_no_cuenta_transporte_ausente():
    from atlas_core.atlas_ia.registro_problemas import recopilar_evidencia_documentos_relacionados

    fila = {"archivo": "482179.jpeg", "numero_guia": "482179", "fecha": "13-10-2026",
            "numero_transporte": "No encontrado", "chofer": "LUIS VARAS", "patente_tracto": "DD2494",
            "obra_destino": "OBRA A", "rut_chofer": ""}
    otra = {**fila, "archivo": "472126.jpeg", "numero_guia": "472126", "rut_chofer": "14293816-2",
            "patente_tracto": "XX1111"}

    # fecha + chofer + obra = 3 señales reales: alcanza sin el transporte.
    assert recopilar_evidencia_documentos_relacionados("rut_chofer", 3)(fila, [fila, otra])
    # Con 4 exigidas, el transporte ausente compartido no completa el umbral.
    assert recopilar_evidencia_documentos_relacionados("rut_chofer", 4)(fila, [fila, otra]) == ()
