from pathlib import Path
from unittest.mock import Mock

from atlas_core import paddle_runtime


# --- resolución de ruta, portable, sin usuario/Desktop hardcodeados ---

def test_ruta_runtime_usa_localappdata_sin_nombre_de_usuario(monkeypatch):
    monkeypatch.delenv(paddle_runtime.VARIABLE_ENTORNO_OVERRIDE, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\cualquiera\AppData\Local")

    ruta = paddle_runtime.ruta_runtime_paddle()

    assert ruta == Path(r"C:\Users\cualquiera\AppData\Local") / "Atlas" / "runtime" / "paddleocr"
    assert "ocr_eval_gpu_env" not in str(ruta)
    assert "Desktop" not in str(ruta)


def test_ruta_runtime_override_explicito_por_variable_de_entorno(monkeypatch):
    monkeypatch.setenv(paddle_runtime.VARIABLE_ENTORNO_OVERRIDE, r"D:\otra\ruta\paddle")

    ruta = paddle_runtime.ruta_runtime_paddle()

    assert ruta == Path(r"D:\otra\ruta\paddle")


def test_ruta_runtime_sin_localappdata_usa_home(monkeypatch):
    monkeypatch.delenv(paddle_runtime.VARIABLE_ENTORNO_OVERRIDE, raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    ruta = paddle_runtime.ruta_runtime_paddle()

    assert ruta == Path.home() / "AppData" / "Local" / "Atlas" / "runtime" / "paddleocr"


# --- validación de runtime existente, sin ejecutar nada ---

def test_runtime_valido_falso_si_no_existe(tmp_path):
    assert paddle_runtime.runtime_valido(tmp_path / "no-existe") is False


def test_runtime_valido_falso_si_version_no_coincide(tmp_path):
    ruta = tmp_path / "runtime"
    (ruta / "Scripts").mkdir(parents=True)
    (ruta / "Scripts" / "python.exe").write_text("", encoding="utf-8")
    (ruta / paddle_runtime.ARCHIVO_VERSION).write_text("version-vieja", encoding="utf-8")

    assert paddle_runtime.runtime_valido(ruta) is False


def test_runtime_valido_true_si_version_coincide(tmp_path):
    ruta = tmp_path / "runtime"
    (ruta / "Scripts").mkdir(parents=True)
    (ruta / "Scripts" / "python.exe").write_text("", encoding="utf-8")
    (ruta / paddle_runtime.ARCHIVO_VERSION).write_text(paddle_runtime._version_esperada(), encoding="utf-8")

    assert paddle_runtime.runtime_valido(ruta) is True


# --- bootstrap, sin instalar nada de verdad (subprocess mockeado) ---

def test_asegurar_runtime_no_reinstala_si_ya_es_valido(monkeypatch, tmp_path):
    monkeypatch.setattr(paddle_runtime, "ruta_runtime_paddle", lambda: tmp_path)
    monkeypatch.setattr(paddle_runtime, "runtime_valido", lambda ruta: True)
    run_mock = Mock()
    monkeypatch.setattr(paddle_runtime.subprocess, "run", run_mock)

    resultado = paddle_runtime.asegurar_runtime_paddle()

    assert resultado == paddle_runtime.python_runtime(tmp_path)
    run_mock.assert_not_called()


def test_asegurar_runtime_instala_gpu_si_hay_nvidia(monkeypatch, tmp_path):
    monkeypatch.setattr(paddle_runtime, "ruta_runtime_paddle", lambda: tmp_path)
    monkeypatch.setattr(paddle_runtime, "runtime_valido", lambda ruta: False)
    monkeypatch.setattr(paddle_runtime, "_gpu_nvidia_disponible", lambda: True)
    llamadas = []

    def run_falso(cmd, **kwargs):
        llamadas.append(cmd)
        return Mock(returncode=0)

    monkeypatch.setattr(paddle_runtime.subprocess, "run", run_falso)

    resultado = paddle_runtime.asegurar_runtime_paddle()

    assert resultado == paddle_runtime.python_runtime(tmp_path)
    comandos_pip = [c for c in llamadas if "pip" in c]
    assert any("paddlepaddle-gpu==3.3.1" in c for c in comandos_pip)
    assert (tmp_path / paddle_runtime.ARCHIVO_VERSION).read_text(encoding="utf-8") == paddle_runtime._version_esperada()


def test_asegurar_runtime_instala_cpu_si_no_hay_gpu(monkeypatch, tmp_path):
    monkeypatch.setattr(paddle_runtime, "ruta_runtime_paddle", lambda: tmp_path)
    monkeypatch.setattr(paddle_runtime, "runtime_valido", lambda ruta: False)
    monkeypatch.setattr(paddle_runtime, "_gpu_nvidia_disponible", lambda: False)
    llamadas = []

    def run_falso(cmd, **kwargs):
        llamadas.append(cmd)
        return Mock(returncode=0)

    monkeypatch.setattr(paddle_runtime.subprocess, "run", run_falso)

    resultado = paddle_runtime.asegurar_runtime_paddle()

    assert resultado == paddle_runtime.python_runtime(tmp_path)
    comandos_pip = [c for c in llamadas if "pip" in c]
    assert any("paddlepaddle==3.3.1" in c for c in comandos_pip)
    assert not any("paddlepaddle-gpu" in c for c in comandos_pip)


def test_asegurar_runtime_devuelve_none_si_falla_instalacion(monkeypatch, tmp_path):
    monkeypatch.setattr(paddle_runtime, "ruta_runtime_paddle", lambda: tmp_path)
    monkeypatch.setattr(paddle_runtime, "runtime_valido", lambda ruta: False)
    monkeypatch.setattr(paddle_runtime, "_gpu_nvidia_disponible", lambda: False)

    def run_falla(cmd, **kwargs):
        raise OSError("pip no encontrado")

    monkeypatch.setattr(paddle_runtime.subprocess, "run", run_falla)

    resultado = paddle_runtime.asegurar_runtime_paddle()

    assert resultado is None


def test_paddle_runtime_no_depende_de_ocr_eval_gpu_env():
    """Ningún hardcode de ruta de este PC: ni el venv de desarrollo, ni el
    nombre de usuario, ni una ruta absoluta de Windows tipo C:\\Users\\...
    (la palabra "Desktop" sí puede aparecer en la documentación explicando
    que justamente NO se depende de ella — se revisa por ruta, no por
    palabra suelta)."""
    import inspect

    fuente = inspect.getsource(paddle_runtime)
    assert "ocr_eval_gpu_env" not in fuente
    assert "Jjjc0508" not in fuente
    assert r"C:\Users" not in fuente
