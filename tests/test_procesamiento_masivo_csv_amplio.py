"""procesamiento_masivo con campos CSV mayores que el límite por defecto de
``csv`` (131072): el dataset operacional real trae `resultado_atlas_ia_json`
de cientos de miles de caracteres. Cada caso corre en un proceso NUEVO (el
límite de ``csv`` es global y otros módulos ya lo amplían dentro de pytest).
Fixtures sintéticas: nunca G:."""
from __future__ import annotations

import csv
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from atlas_core.procesamiento_masivo import COLUMNAS

RAIZ_MOTOR = Path(__file__).resolve().parents[1]
LARGO = 300_000  # > 131072


@pytest.fixture
def dataset(tmp_path):
    ruta = tmp_path / "analisis_completo_guias.csv"
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerow({**{c: "" for c in COLUMNAS}, "archivo": "1.jpeg", "numero_guia": "700001",
                           "resultado_atlas_ia_json": "x" * LARGO})
        escritor.writerow({**{c: "" for c in COLUMNAS}, "archivo": "2.jpeg", "numero_guia": "700002"})
    return ruta


def _python(codigo: str, *argumentos: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", codigo, *argumentos], cwd=RAIZ_MOTOR,
                          capture_output=True, text=True, encoding="utf-8")


def test_validar_csv_existente_con_campo_grande_en_proceso_nuevo(dataset):
    huella = hashlib.sha256(dataset.read_bytes()).hexdigest()
    proceso = _python(
        "import csv, sys\n"
        "from pathlib import Path\n"
        "from atlas_core.procesamiento_masivo import _validar_csv_existente\n"
        "ruta = Path(sys.argv[1])\n"
        "print(_validar_csv_existente(ruta))\n"
        "filas = list(csv.DictReader(ruta.open(encoding='utf-8-sig', newline=''), delimiter=';'))\n"
        "print(len(filas), len(filas[0]['resultado_atlas_ia_json']))\n",
        str(dataset))
    assert proceso.returncode == 0, proceso.stderr
    assert "field larger than field limit" not in proceso.stderr
    assert proceso.stdout.split() == ["True", "2", str(LARGO)]   # validación sigue; campo íntegro
    assert hashlib.sha256(dataset.read_bytes()).hexdigest() == huella  # validar no reescribe


def test_otros_errores_csv_se_siguen_propagando(dataset):
    proceso = _python(
        "import csv, sys\n"
        "from pathlib import Path\n"
        "from atlas_core.procesamiento_masivo import _validar_csv_existente\n"
        "csv.field_size_limit(1000)\n"
        "try:\n"
        "    _validar_csv_existente(Path(sys.argv[1]))\n"
        "except csv.Error as error:\n"
        "    print('csv.Error', error)\n",
        str(dataset))
    assert proceso.returncode == 0, proceso.stderr
    assert proceso.stdout.startswith("csv.Error field larger than field limit (1000)")


def test_esquema_incompatible_sigue_fallando(tmp_path):
    ruta = tmp_path / "otro.csv"
    ruta.write_text("a;b\n1;2\n", encoding="utf-8")
    from atlas_core.procesamiento_masivo import _validar_csv_existente
    with pytest.raises(ValueError, match="esquema incompatible"):
        _validar_csv_existente(ruta)


def test_limite_ampliado_al_importar():
    proceso = _python("import csv, atlas_core.procesamiento_masivo as m; print(csv.field_size_limit() == m.LIMITE_CAMPO_CSV > 131072)")
    assert proceso.returncode == 0, proceso.stderr
    assert proceso.stdout.strip() == "True"
