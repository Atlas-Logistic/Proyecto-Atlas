"""resumen_procesamiento_desktop.py con campos CSV mayores que el límite por
defecto de ``csv`` (131072): el dataset operacional real trae evidencias
por fila de cientos de miles de caracteres. Fixtures sintéticas: nunca G:."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

import resumen_procesamiento_desktop as resumen
from atlas_core.procesamiento_masivo import COLUMNAS

RAIZ_MOTOR = Path(__file__).resolve().parents[1]
CAMPO_GRANDE = "x" * 300_000  # > 131072


def _csv(ruta: Path, filas: list[dict[str, str]]) -> Path:
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        for cambios in filas:
            escritor.writerow({**{c: "" for c in COLUMNAS}, **cambios})
    return ruta


@pytest.fixture
def csv_amplio(tmp_path):
    return _csv(tmp_path / "analisis_completo_guias.csv", [
        {"archivo": "1.jpeg", "numero_transporte": "0000900002", "resultado_atlas_ia_json": CAMPO_GRANDE},
        {"archivo": "2.jpeg", "numero_transporte": "0000900001"},
    ])


def test_leer_csv_conserva_el_campo_grande_completo(csv_amplio):
    filas = resumen._leer_csv(csv_amplio)
    assert len(filas) == 2 and filas[0]["resultado_atlas_ia_json"] == CAMPO_GRANDE
    assert resumen.LIMITE_CAMPO_CSV > 131072


def test_snapshot_en_proceso_nuevo_como_lo_invoca_desktop(csv_amplio, tmp_path):
    # Proceso limpio (el límite por defecto de csv), mismo comando que main.js.
    salida = tmp_path / "_snapshot_antes.json"
    proceso = subprocess.run(
        [sys.executable, str(RAIZ_MOTOR / "resumen_procesamiento_desktop.py"), "snapshot",
         "--csv-masivo", str(csv_amplio), "--salida", str(salida)],
        cwd=RAIZ_MOTOR, capture_output=True, text=True, encoding="utf-8")
    assert proceso.returncode == 0, proceso.stderr
    assert "field larger than field limit" not in proceso.stderr
    assert json.loads(salida.read_text(encoding="utf-8")) == {"transportes_existentes": ["0000900001", "0000900002"]}


def test_otros_errores_csv_se_siguen_propagando(csv_amplio, monkeypatch):
    # El límite sólo se amplía; nunca se capturan ni ocultan errores de csv.
    anterior = csv.field_size_limit()
    try:
        csv.field_size_limit(1000)
        with pytest.raises(csv.Error, match="field larger than field limit"):
            resumen._leer_csv(csv_amplio)
    finally:
        csv.field_size_limit(anterior)


def test_esquema_incompatible_sigue_fallando(tmp_path):
    ruta = tmp_path / "otro.csv"
    ruta.write_text("a;b\n1;2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Esquema CSV incompatible"):
        resumen._leer_csv(ruta)
