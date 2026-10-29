"""B1 bajo SOLO CONSULTA de Desktop (caso real 483633: «El material de la guía
483633 es …» fallaba con PermissionError os.putenv al importar NumPy).

Desktop corre `b1_consulta_cli.py` con el ejecutor `src/consulta_python.py`,
que deniega por auditoría os.putenv, cargas nativas por ctypes, escrituras y
subprocesos. Aquí se reproduce esa guarda con las mismas reglas (sin
aflojarla) sobre una raíz sintética: interpretar una orden nunca debe cargar
OCR/NumPy ni escribir. Nunca G: ni datos productivos."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

MOTOR = Path(__file__).resolve().parents[1]
# Mismas denegaciones que Desktop src/consulta_python.py fuera de modo prueba.
GUARDA = textwrap.dedent("""
    import os, runpy, sys
    script = os.path.abspath(sys.argv[1]); sys.argv = sys.argv[1:]
    sys.dont_write_bytecode = True
    sys.path.insert(0, os.path.dirname(script))
    def solo_lectura(event, args):
        if event in {'ctypes.dlopen', 'ctypes.dlsym'}:
            raise PermissionError('SOLO CONSULTA: carga nativa bloqueada')
        if event == 'open':
            ruta, mode, flags = args
            if (mode and any(c in mode for c in 'wax+')) or (flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
                raise PermissionError('SOLO CONSULTA: escritura Python bloqueada')
        if event in {'os.remove', 'os.rename', 'os.rmdir', 'os.mkdir', 'os.chmod', 'os.chown', 'os.utime', 'os.link',
                     'os.symlink', 'os.truncate', 'os.system', 'os.startfile', 'os.putenv', 'os.unsetenv',
                     'subprocess.Popen', 'os.exec', 'os.posix_spawn', 'os.fork', 'socket.connect', 'socket.bind'}:
            raise PermissionError('SOLO CONSULTA: operación Python bloqueada: ' + event)
    sys.addaudithook(solo_lectura)
    try:
        runpy.run_path(script, run_name='__main__')
    finally:
        print('NUMPY_CARGADO=' + str('numpy' in sys.modules), file=sys.stderr)
""")

ORDENES = [
    "El material de la guía 483633 es B HORMIGON 22MM 8 M A630420H (n)",
    "Recupera el material de la guía 483633",
    "En la guía 483633 el peso correcto es 12.450 kg",
    "Corrige el cliente de la guía 483633 a CLIENTE X",
]


def _b1_consulta(tmp_path, texto, *extra):
    guarda = tmp_path / "guarda.py"
    guarda.write_text(GUARDA, encoding="utf-8")
    (tmp_path / "raiz" / "operacion" / "actual").mkdir(parents=True, exist_ok=True)
    antes = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    entorno = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(MOTOR)}
    entorno.pop("ATLAS_PRUEBA_ROOT", None)
    r = subprocess.run([sys.executable, "-B", str(guarda), str(MOTOR / "b1_consulta_cli.py"),
                        "--raiz-atlas", str(tmp_path / "raiz"), "--texto", texto, *extra],
                       cwd=MOTOR, env=entorno, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == antes, "no debe escribir nada"
    return r


@pytest.mark.parametrize("texto", ORDENES)
def test_orden_autorizada_llega_al_operador_sin_cargar_numpy(tmp_path, texto):
    r = _b1_consulta(tmp_path, texto, "--derivar-operacionales")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"estado": "REQUIERE_OPERADOR"}
    assert "NUMPY_CARGADO=False" in r.stderr and "PermissionError" not in r.stderr


def test_orden_no_autorizada_sigue_bloqueada(tmp_path):
    r = _b1_consulta(tmp_path, ORDENES[0])
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"estado": "RECHAZADA",
                                    "mensaje": "SOLO CONSULTA: las acciones operacionales están deshabilitadas."}


def test_la_guarda_sigue_denegando_os_putenv(tmp_path):
    script = tmp_path / "putenv.py"
    script.write_text("import os\nos.putenv('X', '1')\n", encoding="utf-8")
    guarda = tmp_path / "guarda.py"
    guarda.write_text(GUARDA, encoding="utf-8")
    r = subprocess.run([sys.executable, "-B", str(guarda), str(script)], capture_output=True, text=True,
                       encoding="utf-8", timeout=60, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert r.returncode != 0 and "operación Python bloqueada: os.putenv" in r.stderr


def test_error_inesperado_se_responde_sin_traceback_en_el_mensaje(monkeypatch, capsys):
    import b1_consulta_cli

    class Roto:
        def __init__(self, *_a, **_k):
            pass

        def consultar(self, *_a, **_k):
            raise PermissionError("SOLO CONSULTA: operación Python bloqueada: os.putenv")

    monkeypatch.setattr(b1_consulta_cli, "OperadorB1", Roto)
    monkeypatch.setattr(sys, "argv", ["b1_consulta_cli.py", "--raiz-atlas", "R", "--texto", "x"])
    b1_consulta_cli.main()
    salida = capsys.readouterr()
    respuesta = json.loads(salida.out)
    assert respuesta["estado"] == "FALLIDA"
    assert respuesta["mensaje"] == "B1 no pudo procesar esta consulta por un error interno. No se modificó nada."
    assert respuesta["diagnostico"]["tipo"] == "PermissionError" and "Traceback" in respuesta["diagnostico"]["traza"]
    assert "Traceback" in salida.err
