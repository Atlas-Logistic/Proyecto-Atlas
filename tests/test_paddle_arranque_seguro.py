"""Arranque seguro del worker PaddleOCR.

1. Precarga de DLL: `paddle/__init__.py` (Windows) precarga todos los
   `paddle/libs/*.dll`; el worker omite sólo las DLL de la lista explícita
   (`warprnnt.dll`, bloqueada por Smart App Control y ajena a la inferencia).
2. stderr del worker: se drena en paralelo, así que un worker que escribe
   más que el búfer del pipe (~4 KB) ya no queda bloqueado hasta el timeout
   de arranque, y su fallo se reporta en segundos con resumen apto para UI.

Workers simulados con procesos Python reales (sin PaddleOCR ni G:).
"""
from __future__ import annotations

import glob
import importlib
import subprocess
import sys
import textwrap
import time

import pytest

from atlas_core import ocr_provider, paddleocr_worker
from atlas_core.ocr_provider import EasyOCRProvider, PaddleOCRProvider, ProveedorOCRNoDisponible

_STDERR_GRANDE = "x" * 120 + "\n"  # * 200 líneas = 24 KB, muy por encima del pipe


# --- precarga de DLL -------------------------------------------------------

def test_lista_de_exclusion_es_explicita_y_minima():
    assert paddleocr_worker.DLL_EXCLUIDAS_PRECARGA_PADDLE == frozenset({"warprnnt.dll"})


def test_import_paddle_omite_solo_las_dll_excluidas_y_restaura_glob(tmp_path, monkeypatch):
    libs = tmp_path / "libs"
    libs.mkdir()
    for nombre in ("common.dll", "mkldnn.dll", "phi.dll", "warpctc.dll", "warprnnt.dll"):
        (libs / nombre).write_bytes(b"")
    paquete = tmp_path / "pkgs" / "paddle"
    paquete.mkdir(parents=True)
    (paquete / "__init__.py").write_text(textwrap.dedent(f"""
        import glob, os
        PRECARGADAS = sorted(os.path.basename(p) for p in glob.glob(os.path.join({str(libs)!r}, "*.dll")))
    """), encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path / "pkgs"))
    monkeypatch.delitem(sys.modules, "paddle", raising=False)
    monkeypatch.setattr(paddleocr_worker.os, "name", "nt")
    glob_antes = glob.glob

    paddleocr_worker._importar_paddle_sin_dlls_excluidas()

    paddle = importlib.import_module("paddle")
    assert paddle.PRECARGADAS == ["common.dll", "mkldnn.dll", "phi.dll", "warpctc.dll"]
    assert glob.glob is glob_antes
    # Fuera de la importación, glob vuelve a ver la DLL (el archivo no se toca).
    assert (libs / "warprnnt.dll").exists()
    assert len(glob.glob(str(libs / "*.dll"))) == 5


# --- stderr del worker / arranque ------------------------------------------

def _worker(tmp_path, cuerpo: str):
    ruta = tmp_path / "worker_falso.py"
    ruta.write_text("import sys, time, json\n" + textwrap.dedent(cuerpo), encoding="utf-8")
    return ruta


def _proveedor(monkeypatch, worker):
    monkeypatch.setattr(ocr_provider, "RUTA_WORKER_PADDLE", worker)
    return PaddleOCRProvider(device="cpu", ruta_python=__import__("pathlib").Path(sys.executable))


def _vivo(proceso) -> bool:
    return proceso is not None and proceso.poll() is None


def test_fallo_de_arranque_con_stderr_grande_se_detecta_en_segundos(tmp_path, monkeypatch, caplog):
    worker = _worker(tmp_path, f"""
        sys.stdin.readline()
        sys.stderr.write({_STDERR_GRANDE!r} * 200)
        sys.stderr.write('OSError: [WinError 4551] Bloqueado. Error loading "C:\\\\runtime\\\\paddle\\\\libs\\\\warprnnt.dll" or one of its dependencies.\\n')
        sys.exit(1)
    """)
    proveedor = _proveedor(monkeypatch, worker)
    inicio = time.perf_counter()
    with caplog.at_level("WARNING"), pytest.raises(ProveedorOCRNoDisponible) as error:
        proveedor._asegurar_proceso()
    assert time.perf_counter() - inicio < 15  # nunca el timeout de 120 s

    mensaje = str(error.value)
    assert "código 1" in mensaje
    assert "WinError 4551" in mensaje and '"warprnnt.dll"' in mensaje
    assert "C:\\" not in mensaje and "Traceback" not in mensaje
    assert "C:\\runtime\\paddle\\libs\\warprnnt.dll" in error.value.detalle_tecnico
    assert "C:\\runtime\\paddle\\libs\\warprnnt.dll" in caplog.text  # detalle completo en log
    assert proveedor._proceso is None


def test_worker_que_escribe_mucho_stderr_arranca_y_procesa_sin_bloquearse(tmp_path, monkeypatch):
    worker = _worker(tmp_path, f"""
        sys.stdin.readline()
        sys.stderr.write({_STDERR_GRANDE!r} * 200)
        sys.stderr.flush()
        print(json.dumps({{"ok": True, "device": "cpu"}}), flush=True)
        for linea in sys.stdin:
            sys.stderr.write({_STDERR_GRANDE!r} * 200)
            print(json.dumps({{"ok": True, "resultado": "linea uno\\nlinea dos"}}), flush=True)
    """)
    proveedor = _proveedor(monkeypatch, worker)
    try:
        inicio = time.perf_counter()
        assert proveedor.leer_texto("guia.jpg") == ["linea uno", "linea dos"]
        assert proveedor.leer_texto("guia.jpg") == ["linea uno", "linea dos"]
        assert time.perf_counter() - inicio < 15
        proceso = proveedor._proceso
        assert _vivo(proceso)
    finally:
        proveedor.cerrar()
    proceso.wait(timeout=10)
    assert not _vivo(proceso)


def test_cuelgue_real_sigue_cortado_por_timeout_y_sin_proceso_huerfano(tmp_path, monkeypatch):
    worker = _worker(tmp_path, """
        sys.stdin.readline()
        time.sleep(120)
    """)
    monkeypatch.setattr(ocr_provider, "TIMEOUT_INICIO_SEG", 1)
    procesos = []
    popen_real = subprocess.Popen

    def popen(*args, **kwargs):
        procesos.append(popen_real(*args, **kwargs))
        return procesos[-1]

    monkeypatch.setattr(ocr_provider.subprocess, "Popen", popen)
    proveedor = _proveedor(monkeypatch, worker)
    with pytest.raises(ProveedorOCRNoDisponible, match="no respondió en 1s al iniciar"):
        proveedor._asegurar_proceso()
    for _ in range(50):
        if not _vivo(procesos[0]):
            break
        time.sleep(0.1)
    assert not _vivo(procesos[0])


def test_worker_que_muere_procesando_reporta_resumen_y_se_recrea(tmp_path, monkeypatch):
    worker = _worker(tmp_path, f"""
        sys.stdin.readline()
        print(json.dumps({{"ok": True, "device": "cpu"}}), flush=True)
        sys.stdin.readline()
        sys.stderr.write({_STDERR_GRANDE!r} * 200 + "MemoryError: sin memoria\\n")
        sys.exit(3)
    """)
    proveedor = _proveedor(monkeypatch, worker)
    proveedor._asegurar_proceso()
    with pytest.raises(ProveedorOCRNoDisponible, match=r"procesando guia\.jpg \(código 3\): MemoryError: sin memoria"):
        proveedor._comando(op="texto", ruta="C:/datos/guia.jpg")
    assert proveedor._proceso is None


def test_fallo_real_de_paddle_cae_a_easyocr_rapido(tmp_path, monkeypatch):
    worker = _worker(tmp_path, f"""
        sys.stdin.readline()
        sys.stderr.write({_STDERR_GRANDE!r} * 200 + "OSError: [WinError 4551] bloqueado\\n")
        sys.exit(1)
    """)
    monkeypatch.setattr(ocr_provider, "RUTA_WORKER_PADDLE", worker)
    monkeypatch.setattr(ocr_provider, "asegurar_runtime_paddle", lambda: __import__("pathlib").Path(sys.executable))
    monkeypatch.setattr(ocr_provider, "_gpu_nvidia_disponible", lambda: False)
    inicio = time.perf_counter()
    proveedor = ocr_provider.crear_proveedor_ocr()
    assert isinstance(proveedor, EasyOCRProvider)
    assert time.perf_counter() - inicio < 15
