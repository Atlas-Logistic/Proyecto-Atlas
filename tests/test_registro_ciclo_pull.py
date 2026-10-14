"""Registro por ciclo del PULL: cada ciclo deja su propio archivo y uno
interrumpido desde fuera queda identificable (sin línea final)."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from atlas_core import registro_ciclo_pull as r

RAIZ_REPO = Path(__file__).resolve().parents[1]


def _archivos(directorio):
    return sorted(directorio.glob("pull_*.log"))


def test_ciclo_normal_registra_inicio_salida_y_fin(tmp_path, capsys):
    def principal():
        print('{"confirmados": []}')
        print("aviso OCR", file=sys.stderr)

    r.ejecutar_con_registro_de_ciclo(principal, directorio=tmp_path)

    salida = capsys.readouterr()
    assert '{"confirmados": []}' in salida.out and "aviso OCR" in salida.err  # el log fijo no cambia
    (archivo,) = _archivos(tmp_path)
    texto = archivo.read_text(encoding="utf-8")
    assert "### INICIO" in texto and f'"pid": {os.getpid()}' in texto
    assert '{"confirmados": []}' in texto and "aviso OCR" in texto
    assert texto.rstrip().endswith('"codigo": 0}')
    assert sys.stdout is not None and not isinstance(sys.stdout, r._Duplicador)


def test_cada_ciclo_tiene_su_propio_archivo(tmp_path):
    r.ejecutar_con_registro_de_ciclo(lambda: print("uno"), directorio=tmp_path)
    time.sleep(1.1)
    r.ejecutar_con_registro_de_ciclo(lambda: print("dos"), directorio=tmp_path)
    archivos = _archivos(tmp_path)
    assert len(archivos) == 2
    assert "uno" in archivos[0].read_text(encoding="utf-8") and "dos" in archivos[1].read_text(encoding="utf-8")


def test_system_exit_conserva_codigo_y_se_propaga(tmp_path):
    def principal():
        raise SystemExit(2)

    with pytest.raises(SystemExit) as salida:
        r.ejecutar_con_registro_de_ciclo(principal, directorio=tmp_path)

    assert salida.value.code == 2
    assert '### FIN' in _archivos(tmp_path)[0].read_text(encoding="utf-8")
    assert '"codigo": 2' in _archivos(tmp_path)[0].read_text(encoding="utf-8")


def test_excepcion_queda_con_traza_y_se_propaga(tmp_path):
    def principal():
        raise RuntimeError("cloud caído")

    with pytest.raises(RuntimeError):
        r.ejecutar_con_registro_de_ciclo(principal, directorio=tmp_path)

    texto = _archivos(tmp_path)[0].read_text(encoding="utf-8")
    assert "### EXCEPCION" in texto and "cloud ca" in texto and "RuntimeError" in texto
    assert "### FIN" not in texto


def test_registro_inutilizable_no_impide_el_pull(tmp_path):
    bloqueado = tmp_path / "es_un_archivo"
    bloqueado.write_text("x", encoding="utf-8")
    ejecutado = []

    r.ejecutar_con_registro_de_ciclo(lambda: ejecutado.append(True), directorio=bloqueado / "sub")

    assert ejecutado == [True]
    assert not isinstance(sys.stdout, r._Duplicador)


def test_retencion_borra_solo_registros_antiguos(tmp_path):
    viejo = tmp_path / "pull_20260101_000000_1.log"
    reciente = tmp_path / "pull_20261014_000000_2.log"
    ajeno = tmp_path / "otro.log"
    for ruta in (viejo, reciente, ajeno):
        ruta.write_text("x", encoding="utf-8")
    antiguo = time.time() - (r.RETENCION_DIAS + 1) * 86400
    os.utime(viejo, (antiguo, antiguo))
    os.utime(ajeno, (antiguo, antiguo))

    r.ejecutar_con_registro_de_ciclo(lambda: None, directorio=tmp_path)

    assert not viejo.exists() and reciente.exists() and ajeno.exists()


def test_terminacion_externa_deja_archivo_sin_linea_final(tmp_path):
    hijo = (
        "import sys, time\n"
        "from atlas_core.registro_ciclo_pull import ejecutar_con_registro_de_ciclo\n"
        "def principal():\n"
        "    print('procesando envio', flush=True)\n"
        "    time.sleep(60)\n"
        "ejecutar_con_registro_de_ciclo(principal)\n"
    )
    entorno = {**os.environ, "ATLAS_PULL_LOG_DIR": str(tmp_path), "PYTHONPATH": str(RAIZ_REPO)}
    proceso = subprocess.Popen([sys.executable, "-B", "-c", hijo], env=entorno, cwd=RAIZ_REPO,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert "procesando envio" in proceso.stdout.readline()
    finally:
        proceso.kill()  # TerminateProcess en Windows: igual que una terminación externa
        proceso.wait(timeout=30)

    (archivo,) = _archivos(tmp_path)
    texto = archivo.read_text(encoding="utf-8")
    assert "### INICIO" in texto and "procesando envio" in texto
    assert "### FIN" not in texto and "### EXCEPCION" not in texto


def test_cli_pull_registra_su_ciclo(tmp_path):
    entorno = {k: v for k, v in os.environ.items() if k != "ATLAS_CLOUD_MOTOR_TOKEN"}
    entorno["ATLAS_PULL_LOG_DIR"] = str(tmp_path)
    resultado = subprocess.run(
        [sys.executable, "-B", str(RAIZ_REPO / "sincronizar_mobile_cloud.py"), "--raiz-atlas", str(tmp_path / "x")],
        env=entorno, cwd=RAIZ_REPO, capture_output=True, text=True, timeout=120,
    )

    assert resultado.returncode == 2 and "Falta --token" in resultado.stderr  # sin token no toca Cloud
    texto = _archivos(tmp_path)[0].read_text(encoding="utf-8")
    assert "Falta --token" in texto and '"codigo": 2' in texto
