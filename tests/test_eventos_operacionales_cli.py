"""Bloque EVENTOS OPERACIONALES CANÓNICOS V1 -- CLI estrecho que Desktop
invoca (registrar / anular / listar). Contrato: una sola línea de JSON
ASCII en stdout, `ok` siempre presente, nunca un stacktrace.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parents[1]
CLI = RAIZ_REPO / "eventos_operacionales_cli.py"


def _run(*args):
    proceso = subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True, text=True, cwd=RAIZ_REPO, timeout=60,
    )
    assert proceso.returncode == 0, proceso.stderr
    lineas = [l for l in proceso.stdout.splitlines() if l.strip()]
    assert len(lineas) == 1, proceso.stdout
    lineas[0].encode("ascii")  # ASCII puro
    return json.loads(lineas[0])


def test_registrar_anular_listar_ciclo(tmp_path):
    raiz = str(tmp_path)
    nt = "0000352552"

    alta = _run("registrar", "--raiz-atlas", raiz, "--numero-transporte", nt,
                "--tipo-evento", "TIENE_ESTADIA", "--nota", "tiene estadia")
    assert alta["ok"] is True and alta["creado"] is True
    assert alta["enriquecimiento"]["motivo_vinculo_incompleto"] == "SIN_OPERACION_VIGENTE"

    de_nuevo = _run("registrar", "--raiz-atlas", raiz, "--numero-transporte", nt,
                    "--tipo-evento", "TIENE_ESTADIA", "--nota", "tiene estadia")
    assert de_nuevo["creado"] is False and de_nuevo["cambio"] is False

    listado = _run("listar", "--raiz-atlas", raiz, "--numero-transporte", nt)
    assert listado["ok"] is True and len(listado["eventos"]) == 1

    baja = _run("anular", "--raiz-atlas", raiz, "--numero-transporte", nt,
                "--tipo-evento", "TIENE_ESTADIA", "--motivo", "humano")
    assert baja["anulado"] is True

    baja2 = _run("anular", "--raiz-atlas", raiz, "--numero-transporte", nt,
                 "--tipo-evento", "TIENE_ESTADIA")
    assert baja2["anulado"] is False and baja2["ya_anulado"] is True

    reactiva = _run("registrar", "--raiz-atlas", raiz, "--numero-transporte", nt,
                    "--tipo-evento", "TIENE_ESTADIA", "--nota", "tiene estadia")
    assert reactiva["reactivado"] is True
    assert reactiva["evento"]["evento_id"] == alta["evento"]["evento_id"]

    solo_activos = _run("listar", "--raiz-atlas", raiz, "--numero-transporte", nt, "--solo-activos")
    assert len(solo_activos["eventos"]) == 1


def test_listar_transporte_sin_eventos_no_es_error(tmp_path):
    salida = _run("listar", "--raiz-atlas", str(tmp_path), "--numero-transporte", "999")
    assert salida == {"ok": True, "numero_transporte": "999", "eventos": []}
