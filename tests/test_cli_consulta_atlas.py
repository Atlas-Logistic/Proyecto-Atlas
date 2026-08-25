"""Bloque CONSULTAS ATLAS V1 -- CLI que Desktop invoca por IPC (Bloque 6
del ticket "IPC seguro read-only"). Verifica que la salida sea SIEMPRE
JSON parseable en ASCII (Windows console no debe corromper acentos), y
que las columnas de soporte queden recortadas para Desktop."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
COLUMNAS = (
    "viaje_id", "numero_transporte", "fecha", "estado", "numeros_guia", "clientes",
    "obras_destino", "choferes", "patentes_tracto", "materiales", "tipos_carga",
    "peso_total_viaje_kg", "distancia_km", "duracion_min", "direccion_entrega",
    "localidad_entrega", "estado_ruta", "evidencias_documentos",
)


def _escribir_viajes(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _fila(**overrides):
    base = {c: "" for c in COLUMNAS}
    base.update({
        "viaje_id": "v1", "numero_transporte": "T1", "fecha": "18-08-2026", "estado": "CONFIRMADO",
        "numeros_guia": "1", "clientes": "CLIENTE A", "obras_destino": "OBRA A",
        "choferes": "JUAN PEREZ", "patentes_tracto": "AA1111", "materiales": "ROLLO HORMIGON",
        "tipos_carga": "ROLLOS", "peso_total_viaje_kg": "1000", "distancia_km": "10.0",
        "duracion_min": "20.0", "direccion_entrega": "CALLE FALSA 123", "localidad_entrega": "MAIPU",
        "estado_ruta": "RUTA_CALCULADA", "evidencias_documentos": "[" + "x" * 500 + "]",
    })
    base.update(overrides)
    return base


def _ejecutar_cli(pregunta, ruta_viajes):
    resultado = subprocess.run(
        [sys.executable, str(RAIZ_PROYECTO / "consultar_atlas.py"), pregunta, "--viajes", str(ruta_viajes)],
        cwd=str(RAIZ_PROYECTO), capture_output=True, text=True, timeout=30,
    )
    return resultado


def test_cli_devuelve_json_ascii_parseable(tmp_path):
    ruta = tmp_path / "viajes.csv"
    _escribir_viajes(ruta, [_fila(choferes="MUÑOZ PÉREZ")])
    resultado = _ejecutar_cli("¿Cuántos viajes hizo Muñoz?", ruta)
    assert resultado.returncode == 0
    salida = resultado.stdout.strip()
    assert salida.isascii()
    datos = json.loads(salida)
    assert datos["estado"] == "OK"
    assert "Muñoz" in datos["texto_respuesta"] or "MUÑOZ" in datos["texto_respuesta"].upper() or "MUÑOZ" in datos["texto_respuesta"]


def test_cli_recorta_columnas_pesadas_de_soporte(tmp_path):
    ruta = tmp_path / "viajes.csv"
    _escribir_viajes(ruta, [_fila()])
    resultado = _ejecutar_cli("¿Cuántos viajes hizo Juan Perez?", ruta)
    datos = json.loads(resultado.stdout.strip())
    soporte = datos["resultado"]["viajes_soporte"][0]
    assert "evidencias_documentos" not in soporte
    assert soporte["numero_transporte"] == "T1"


def test_cli_nunca_deja_el_proceso_sin_salida_json_ante_error(tmp_path):
    ruta_inexistente = tmp_path / "no_existe.csv"
    resultado = _ejecutar_cli("¿Cuántos viajes hay?", ruta_inexistente)
    datos = json.loads(resultado.stdout.strip())
    assert datos["estado"] == "ERROR"
    assert datos["resultado"] is None
