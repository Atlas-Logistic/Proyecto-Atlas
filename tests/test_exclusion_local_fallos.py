"""Exclusión local (C1): cierre con fallos, esperas entre raíces y cobertura
REAL de la guardia. Lo cubierto se prueba; lo NO cubierto (descriptor abierto,
llamadas nativas, alias de ruta, eventos no listados) se demuestra como límite,
no se afirma protección. Las interrupciones por punto, F1-F4 y las invariantes
del bloqueo están en tests/test_exclusion_local_bloqueo.py.

Hilos y procesos son reales (Windows). Nada toca G: ni Cloud.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

import pytest

from atlas_core import escritor_operativo as eo
from atlas_core import exclusion_local as el
from tests.test_exclusion_local import entorno, ordenar, senal, terminar_ok  # noqa: F401

pytestmark = pytest.mark.skipif(os.name != "nt", reason="bloqueo de archivo de Windows")


def _en_hilo(funcion, limite: float = 30.0):
    """Ejecuta en un hilo y exige que termine: detecta esperas indefinidas sin
    colgar la prueba."""
    salida: dict = {}

    def correr():
        try:
            salida["valor"] = funcion()
        except BaseException as error:  # noqa: BLE001
            salida["error"] = error

    hilo = threading.Thread(target=correr, daemon=True)
    inicio = time.monotonic()
    hilo.start()
    hilo.join(limite)
    assert not hilo.is_alive(), f"espera indefinida (> {limite} s)"
    salida["duracion"] = time.monotonic() - inicio
    return salida


def _otro_proceso_obtiene(entorno, nombre: str) -> bool:  # noqa: F811
    control = entorno["control"].parent / f"control_{nombre}"
    control.mkdir()
    proceso = entorno["lanzar"]("tomar", control_propio=control)
    ok = senal(control, "tomar", proceso=proceso)["ok"]
    if ok:
        ordenar(control, "soltar")
    terminar_ok(proceso)
    return ok


# ------------------------------------------- 1. parámetros

def test_espera_infinita_o_negativa_se_rechaza():
    for valor in (float("inf"), float("nan"), -1):
        with pytest.raises(ValueError):
            el.TurnoEscritura("C:\\x", espera_segundos=valor)


# ------------------------------------------- 2. cierre con excepciones inesperadas

class _Cloud:
    def __init__(self, *, liberar_falla: bool = False):
        self.liberar_falla = liberar_falla

    def __call__(self, _base, ruta, _token, *, method="GET", body=None, timeout=0):
        if ruta.endswith("/estado"):
            return {"epoca": 0, "vigente": False}
        if ruta.endswith("/adquirir"):
            return {"estado": "ADQUIRIDO", "lease_token": "t", "epoca": 1}
        if ruta.endswith("/liberar") and self.liberar_falla:
            raise RuntimeError("fallo inesperado al liberar (inyectado)")
        return {"estado": "LIBERADO" if ruta.endswith("/liberar") else "RENOVADO"}


def _lease(entorno, monkeypatch, cloud, *, heartbeat=0.0):  # noqa: F811
    monkeypatch.setattr(eo, "_json", cloud)
    monkeypatch.setenv("ATLAS_DATA_DIR", str(entorno["raiz"]))
    return eo.LeaseEscritorOperativo(base_url="https://cloud.falsa", token_motor="x", escritor_id="pc-prueba",
                                     heartbeat_segundos=heartbeat, margen_relevo_segundos=0,
                                     ruta_relevo=entorno["local"] / "relevo.json")


@pytest.mark.parametrize("donde", ["detener_custodia", "liberar_lease", "join_heartbeat", "soltar_turno_tardio"])
def test_cierre_del_lease_suelta_el_turno_ante_cualquier_excepcion(entorno, monkeypatch, donde):  # noqa: F811
    escritor = _lease(entorno, monkeypatch, _Cloud(liberar_falla=donde == "liberar_lease"), heartbeat=30)
    assert escritor.adquirir() and el.posee_turno(entorno["raiz"])
    if donde == "detener_custodia":
        class Custodia:
            raiz = entorno["raiz"]

            def confirmar(self, _lease):
                pass

            def detener(self):
                raise RuntimeError("fallo inesperado en detener (inyectado)")

        custodia = Custodia()
        escritor.custodia = custodia
        monkeypatch.setattr(eo, "_custodias_activas", lambda: [custodia])
    elif donde == "join_heartbeat":
        hilo = escritor._hilo

        class HiloRoto:
            def join(self, timeout=None):
                hilo.join(timeout)
                raise RuntimeError("fallo inesperado en join (inyectado)")

            def is_alive(self):
                return hilo.is_alive()

        escritor._hilo = HiloRoto()
    elif donde == "soltar_turno_tardio":
        # El propio paso final informa un error DESPUÉS de soltar: se propaga
        # (no se oculta) y el heartbeat y el lease ya quedaron cerrados.
        real = el.TurnoEscritura.soltar

        def soltar_y_fallar(self):
            real(self)
            raise el.ErrorTurno("error informado al soltar (inyectado)")

        monkeypatch.setattr(el.TurnoEscritura, "soltar", soltar_y_fallar)
    with pytest.raises((RuntimeError, el.ErrorTurno)):
        escritor.cerrar()
    assert escritor._detener.is_set()  # el heartbeat se detuvo igual
    assert escritor.lease_token == ""
    assert escritor.turno is None
    assert not el.posee_turno(entorno["raiz"])
    assert _otro_proceso_obtiene(entorno, f"tras_{donde}")


def test_cierre_de_equipo_unico_suelta_el_turno_si_falla_release_mutex(entorno):  # noqa: F811
    from atlas_core.exclusividad_equipo import EscritorEquipoUnico
    escritor = EscritorEquipoUnico(entorno["raiz"], verificar=lambda: None)
    assert escritor.adquirir()

    class Kernel:
        def __init__(self, real):
            self.real = real

        def ReleaseMutex(self, handle):
            self.real.ReleaseMutex(handle)
            raise OSError("fallo inesperado en ReleaseMutex (inyectado)")

        def __getattr__(self, nombre):
            return getattr(self.real, nombre)

    escritor._k = Kernel(escritor._k)
    with pytest.raises(OSError, match="inyectado"):
        escritor.cerrar()
    assert escritor.handle is None and escritor.turno is None
    assert not el.posee_turno(entorno["raiz"])
    assert _otro_proceso_obtiene(entorno, "tras_equipo_unico")


# ------------------------------------------------- 3. carreras entre hilos y raíces

def test_espera_en_una_raiz_no_bloquea_la_adquisicion_de_otra(entorno, tmp_path):  # noqa: F811
    """Cada raíz tiene su transición: esperar una no bloquea otra."""
    a = entorno["lanzar"]("tomar")  # otro proceso sostiene la raíz protegida
    senal(entorno["control"], "tomar", proceso=a)
    otra = tmp_path / "otra_raiz"
    otra.mkdir()
    esperando = el.TurnoEscritura(entorno["raiz"], espera_segundos=3)
    hilo = threading.Thread(target=esperando.adquirir)
    hilo.start()
    time.sleep(0.3)  # el hilo ya está esperando el bloqueo de la primera raíz
    rapido = el.TurnoEscritura(otra)
    resultado = _en_hilo(rapido.adquirir, limite=10)
    assert resultado.get("valor") is True and resultado["duracion"] < 1.0, resultado
    rapido.soltar()
    hilo.join(10)
    assert not esperando.vigente  # su espera terminó (acotada) sin obtenerlo
    ordenar(entorno["control"], "soltar")
    terminar_ok(a)


def test_esperas_cruzadas_entre_procesos_terminan_acotadas_sin_interbloqueo(entorno, tmp_path):  # noqa: F811
    otra = tmp_path / "raiz_dos"
    otra.mkdir()
    c1, c2 = tmp_path / "c1", tmp_path / "c2"
    c1.mkdir()
    c2.mkdir()
    env = entorno["env"]
    env["ATLAS_EXCLUSION_RAICES"] = os.pathsep.join([str(entorno["raiz"]), str(otra)])
    p1 = subprocess.Popen([sys.executable, str(Path(__file__).with_name("ayudante_exclusion_local.py")), "cruzado",
                           str(entorno["raiz"]), str(c1), str(otra), "1.5"], env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    p2 = subprocess.Popen([sys.executable, str(Path(__file__).with_name("ayudante_exclusion_local.py")), "cruzado",
                           str(otra), str(c2), str(entorno["raiz"]), "1.5"], env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        senal(c1, "cruzado_tomado", proceso=p1)
        senal(c2, "cruzado_tomado", proceso=p2)
        ordenar(c1, "pedir")
        ordenar(c2, "pedir")
        r1, r2 = senal(c1, "cruzado", proceso=p1), senal(c2, "cruzado", proceso=p2)
        # Sin interbloqueo: ambas esperas terminan acotadas. A lo sumo uno
        # obtiene la otra raíz (si el otro ya agotó su espera y soltó).
        assert not (r1["ok"] and r2["ok"])
        assert r1["duracion"] < 5 and r2["duracion"] < 5
        assert p1.wait(30) == 0 and p2.wait(30) == 0
    finally:
        for p in (p1, p2):
            if p.poll() is None:
                p.kill()


# ---------------------------------------------------- 4. cobertura de la guardia

def _operaciones_cubiertas(raiz: Path, fuera: Path):
    if fuera.is_dir():
        (fuera / "fuente.txt").write_text("f", encoding="utf-8")
        (fuera / "arbol").mkdir(exist_ok=True)
        (fuera / "arbol" / "hoja.txt").write_text("h", encoding="utf-8")
    return {
        "open_w": lambda: open(raiz / "a.txt", "w").close(),
        "open_a": lambda: open(raiz / "existente.txt", "a").close(),
        "open_x": lambda: open(raiz / "x.txt", "x").close(),
        "open_r+": lambda: open(raiz / "existente.txt", "r+").close(),
        "os_open_creat": lambda: os.close(os.open(raiz / "b.txt", os.O_CREAT | os.O_WRONLY)),
        "path_touch": lambda: (raiz / "c.txt").touch(),
        "write_text": lambda: (raiz / "d.txt").write_text("x", encoding="utf-8"),
        "os_replace": lambda: os.replace(fuera / "fuente.txt", raiz / "e.txt"),
        "os_rename": lambda: os.rename(raiz / "existente.txt", raiz / "f.txt"),
        "os_remove": lambda: os.remove(raiz / "existente.txt"),
        "os_mkdir": lambda: os.mkdir(raiz / "g"),
        "os_makedirs": lambda: os.makedirs(raiz / "h" / "i"),
        "os_rmdir": lambda: os.rmdir(raiz / "vacia"),
        "shutil_rmtree": lambda: shutil.rmtree(raiz / "vacia"),
        "shutil_copy": lambda: shutil.copy(fuera / "fuente.txt", raiz / "j.txt"),
        "shutil_copy2": lambda: shutil.copy2(fuera / "fuente.txt", raiz / "j2.txt"),  # CopyFile2 nativo
        "shutil_copytree": lambda: shutil.copytree(fuera / "arbol", raiz / "arbol"),
        "shutil_move": lambda: shutil.move(str(fuera / "fuente.txt"), str(raiz / "k.txt")),
        "os_truncate": lambda: os.truncate(raiz / "existente.txt", 0),
        "os_chmod": lambda: os.chmod(raiz / "existente.txt", 0o444),
        "os_utime": lambda: os.utime(raiz / "existente.txt"),
        "os_link": lambda: os.link(raiz / "existente.txt", raiz / "l.txt"),
    }


_NOMBRES_OPERACIONES = list(_operaciones_cubiertas(Path("__no_existe__"), Path("__no_existe__")).keys())


@pytest.mark.parametrize("operacion", _NOMBRES_OPERACIONES)  # la recolección no escribe nada
def test_guardia_cubre_estas_operaciones_por_ruta(entorno, operacion):  # noqa: F811
    raiz, fuera = entorno["raiz"], entorno["control"]
    with el.TurnoEscritura(raiz):
        (raiz / "existente.txt").write_text("e", encoding="utf-8")
        (raiz / "vacia").mkdir()
    antes = sorted(p.name for p in raiz.iterdir())
    with pytest.raises(el.EscrituraSinTurno):
        _operaciones_cubiertas(raiz, fuera)[operacion]()
    assert sorted(p.name for p in raiz.iterdir()) == antes
    assert (raiz / "existente.txt").read_text(encoding="utf-8") == "e"


def test_limite_descriptor_abierto_antes_escribe_sin_turno(entorno):  # noqa: F811
    """NO CUBIERTO: la guardia actúa al abrir, no al escribir. Un descriptor
    abierto con turno (o antes de importar atlas_core) sigue escribiendo
    después de soltarlo."""
    raiz = entorno["raiz"]
    with el.TurnoEscritura(raiz):
        descriptor = os.open(raiz / "abierto.txt", os.O_CREAT | os.O_WRONLY)
    try:
        os.write(descriptor, b"escrito sin turno")
    finally:
        os.close(descriptor)
    assert (raiz / "abierto.txt").read_bytes() == b"escrito sin turno"


def test_limite_llamada_nativa_escribe_sin_turno(entorno):  # noqa: F811
    """NO CUBIERTO: CreateFileW/WriteFile por ctypes no generan eventos de auditoría."""
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateFileW.restype = wintypes.HANDLE
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                              wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    handle = k.CreateFileW(str(entorno["raiz"] / "nativo.txt"), 0x40000000, 0, None, 2, 0x80, None)
    assert handle and handle != wintypes.HANDLE(-1).value
    escritos = wintypes.DWORD()
    assert k.WriteFile(handle, b"nativo", 6, ctypes.byref(escritos), None)
    k.CloseHandle(handle)
    assert (entorno["raiz"] / "nativo.txt").read_bytes() == b"nativo"


def test_limite_alias_de_ruta_escribe_sin_turno(entorno, tmp_path):  # noqa: F811
    """NO CUBIERTO: la comparación es textual. Un junction o el prefijo \\\\?\\
    apuntan a la raíz protegida por otra ruta."""
    raiz = entorno["raiz"]
    alias = tmp_path / "alias_junction"
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(alias), str(raiz)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    (alias / "por_junction.txt").write_text("x", encoding="utf-8")
    assert (raiz / "por_junction.txt").exists()
    extendida = "\\\\?\\" + str(raiz / "por_prefijo.txt")
    with open(extendida, "w", encoding="utf-8") as archivo:
        archivo.write("x")
    assert (raiz / "por_prefijo.txt").exists()
    os.rmdir(alias)  # quita el junction, no el destino


def test_limite_eventos_no_listados_sqlite_escribe_sin_turno(entorno):  # noqa: F811
    """NO CUBIERTO: sqlite3 crea y escribe la base con su propio evento
    (sqlite3.connect), sin `open` auditado."""
    conexion = sqlite3.connect(entorno["raiz"] / "base.sqlite")
    conexion.execute("create table t(x)")
    conexion.commit()
    conexion.close()
    assert (entorno["raiz"] / "base.sqlite").stat().st_size > 0


def test_limite_modos_observar_y_desactivada_no_protegen(entorno, monkeypatch):  # noqa: F811
    for modo in ("observar", "desactivada"):
        monkeypatch.setenv("ATLAS_EXCLUSION_LOCAL", modo)
        (entorno["raiz"] / f"modo_{modo}.txt").write_text("x", encoding="utf-8")
    assert {p.name for p in entorno["raiz"].iterdir()} >= {"modo_observar.txt", "modo_desactivada.txt"}
