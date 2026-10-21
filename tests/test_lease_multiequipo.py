"""Coordinación multi-PC: el lease Cloud recupera locks huérfanos igual que
el mutex de equipo único, sin tocar locks vivos ni de otro equipo."""
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from atlas_core import desktop_operacion
from atlas_core.exclusividad_equipo import recuperar_bloqueos_huerfanos
from atlas_core.mobile import RepositorioEnviosMobile
from sincronizar_mobile_cloud import ejecutar_pull_con_escritor

pytestmark = pytest.mark.skipif(os.name != "nt", reason="PID de Windows")


class LeaseFalso:
    """Lease Cloud sintético: exclusión global por una sola ranura."""
    ocupado = False

    def __init__(self, **_):
        self.vigente = False

    def adquirir(self):
        if LeaseFalso.ocupado:
            return False
        LeaseFalso.ocupado = self.vigente = True
        return True

    def renovar(self):
        return self.vigente

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self.vigente:
            LeaseFalso.ocupado = self.vigente = False


def _pid_terminado():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def _lock(actual: Path, nombre: str, *, pid: int, host: str | None = None) -> Path:
    ruta = actual / f".atlas_lock_{nombre}"
    ruta.write_text(json.dumps({"pid": pid, "host": host or socket.gethostname(), "adquirido_en": 0}), encoding="utf-8")
    return ruta


@pytest.fixture
def raiz(tmp_path):
    (tmp_path / "operacion" / "actual").mkdir(parents=True)
    LeaseFalso.ocupado = False
    return tmp_path


def test_recuperacion_exige_escritor_vigente(raiz):
    _lock(raiz / "operacion" / "actual", "desktop_manual", pid=_pid_terminado())
    with pytest.raises(PermissionError):
        recuperar_bloqueos_huerfanos(raiz, escritor=None)
    with pytest.raises(PermissionError):
        recuperar_bloqueos_huerfanos(raiz, escritor=LeaseFalso())


def test_lease_recupera_solo_locks_propios_de_pid_terminado(raiz):
    actual = raiz / "operacion" / "actual"
    huerfano = _lock(actual, "desktop_manual", pid=_pid_terminado())
    vivo = _lock(actual, "revalidacion_dataset", pid=os.getpid())
    ajeno = _lock(actual, "pull", pid=_pid_terminado(), host="OTRO-PC")
    with LeaseFalso() as lease:
        assert lease.adquirir()
        assert recuperar_bloqueos_huerfanos(raiz, escritor=lease) == [huerfano.name]
    assert not huerfano.exists() and vivo.exists() and ajeno.exists()


def test_ingreso_manual_bajo_lease_retoma_tras_caida(raiz, monkeypatch):
    # Raíz "compartida" sin política de equipo único: decide el lease Cloud.
    monkeypatch.setattr(desktop_operacion, "compartida", lambda _r: True)
    monkeypatch.setattr("atlas_core.exclusividad_equipo.politica_equipo_unico", lambda _r: None)
    _lock(raiz / "operacion" / "actual", "desktop_manual", pid=_pid_terminado())
    with desktop_operacion.sesion(raiz, fabrica=LeaseFalso) as comprobar:
        comprobar()
        assert LeaseFalso.ocupado
    assert not LeaseFalso.ocupado
    assert not (raiz / "operacion" / "actual" / ".atlas_lock_desktop_manual").exists()


def test_manual_y_pull_nunca_escriben_a_la_vez(raiz, monkeypatch):
    monkeypatch.setattr(desktop_operacion, "compartida", lambda _r: True)
    monkeypatch.setattr("atlas_core.exclusividad_equipo.politica_equipo_unico", lambda _r: None)
    llamadas = []
    monkeypatch.setattr("sincronizar_mobile_cloud.sincronizar_envios_cloud", lambda **_k: llamadas.append(1) or {"confirmados": []})
    argumentos = dict(base_url="https://cloud.test", token_motor="t", consumidor="pc", repositorio=RepositorioEnviosMobile(raiz),
                      timeout=1, procesar=False, dataset=None, carpeta_catalogos=None, fabrica_escritor=LeaseFalso)
    with desktop_operacion.sesion(raiz, fabrica=LeaseFalso):
        assert ejecutar_pull_con_escritor(**argumentos)["escritor_operativo"] == "NO_ADQUIRIDO"
        with pytest.raises(PermissionError, match="ocupado"):
            with desktop_operacion.sesion(raiz, fabrica=LeaseFalso):
                pass
    assert llamadas == []
    _lock(raiz / "operacion" / "actual", "revalidacion_dataset", pid=_pid_terminado())
    assert ejecutar_pull_con_escritor(**argumentos) == {"confirmados": []}
    assert llamadas == [1]
    assert not (raiz / "operacion" / "actual" / ".atlas_lock_revalidacion_dataset").exists()
