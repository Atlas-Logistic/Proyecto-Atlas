"""Progreso vivo del CLI: sin OCR/red/datos operacionales."""
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest
from atlas_core import desktop_operacion as d


class Stderr(io.StringIO):
    def __init__(self):
        super().__init__()
        self.flushes = 0

    def flush(self):
        self.flushes += 1


def test_cli_emite_eventos_fragmentados_antes_de_terminar_y_separa_json(monkeypatch, capsys):
    stderr = Stderr()
    monkeypatch.setattr(sys, 'stderr', stderr)
    argv, stdin = sys.argv, sys.stdin
    def ejecutar(*args, **kwargs):
        print('diagnostico interno')
        sys.stdout.write('[1/')
        sys.stdout.write('2] guia uno.pdf::p1')
        assert stderr.getvalue() == ''
        sys.stdout.write('\r\n[2/2] guia_dos.png\n')
        assert stderr.getvalue() == '[1/2] guia uno.pdf::p1\r\n[2/2] guia_dos.png\n'
        assert stderr.flushes == 2  # Ya llegaron, aun dentro de run_path.
        assert sys.stdin.read() == 'entrada'
        print('{"ok":true}')
    monkeypatch.setattr(d.runpy, 'run_path', ejecutar)
    assert d._cli(['sintetico.py'], 'entrada') == 'diagnostico interno\n{"ok":true}\n'
    assert sys.argv is argv and sys.stdin is stdin
    assert capsys.readouterr().out == ''


def test_cli_conserva_texto_sin_salto_y_restaura_al_fallar(monkeypatch):
    stderr = Stderr()
    monkeypatch.setattr(sys, 'stderr', stderr)
    argv, stdin = sys.argv, sys.stdin
    def ejecutar(*args, **kwargs):
        print('[1/1] sintetica.png', end='')
        raise SystemExit(3)
    monkeypatch.setattr(d.runpy, 'run_path', ejecutar)
    with pytest.raises(RuntimeError, match='3'):
        d._cli(['sintetico.py'])
    assert stderr.getvalue() == '[1/1] sintetica.png\n'
    assert stderr.flushes == 1
    assert sys.argv is argv and sys.stdin is stdin
    monkeypatch.setattr(d.runpy, 'run_path', lambda *a, **kw: print('json sin salto', end=''))
    assert d._cli(['sintetico.py']) == 'json sin salto'


def test_progreso_por_pipe_llega_antes_del_json_y_sin_unbuffered(tmp_path):
    # El hijo espera una confirmacion por stdin DESPUES de imprimir progreso.
    # Si el evento queda retenido, el padre no puede liberar el procesamiento.
    codigo = """
import json, sys
sys.path.insert(0, sys.argv[1])
from atlas_core import desktop_operacion as d
def ejecutar(*args, **kwargs):
    print('[1/1] documento_sintetico.pdf::p1')
    assert sys.stdin.readline().strip() == 'continuar'
    print('resultado interno')
d.runpy.run_path = ejecutar
respuesta = d._cli(['sintetico.py'])
print(json.dumps({'ok': True, 'salida': respuesta}))
"""
    with subprocess.Popen([sys.executable, '-c', codigo, str(Path(d.__file__).resolve().parent.parent)],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True) as proceso:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor() as pool:
            lectura = pool.submit(proceso.stderr.readline)
            try:
                assert lectura.result(timeout=10) == '[1/1] documento_sintetico.pdf::p1\n'
                assert proceso.poll() is None
            except BaseException:
                proceso.kill()
                raise
        stdout, stderr = proceso.communicate('continuar\n', timeout=10)
        assert proceso.returncode == 0 and stderr == ''
        assert json.loads(stdout) == {'ok': True, 'salida': 'resultado interno\n'}
