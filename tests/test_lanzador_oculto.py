import subprocess
import time
from pathlib import Path

WRAPPER = Path(__file__).resolve().parents[1] / 'scripts' / 'lanzar_oculto.vbs'


def test_lanzador_espera_y_preserva_codigo_y_argumentos(tmp_path):
    script = tmp_path / 'con espacio.ps1'
    salida = tmp_path / 'resultado con espacio.txt'
    script.write_text('param($salida)\n[IO.File]::WriteAllText($salida,"OK")\nStart-Sleep -Milliseconds 300\nexit 37\n', encoding='ascii')
    inicio = time.monotonic()
    resultado = subprocess.run(['cscript.exe','//nologo',str(WRAPPER), 'powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(script), str(salida)], capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
    assert resultado.returncode == 37
    assert time.monotonic() - inicio >= .3
    assert salida.read_text() == 'OK'


def test_rechaza_entrada_ambigua_y_ausente():
    def run(*args):
        return subprocess.run(['cscript.exe','//nologo',str(WRAPPER),*args], capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW).returncode
    assert run() == 64
    assert run('C:\\invalido\\') == 65
