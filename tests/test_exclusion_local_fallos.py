"""Exclusión local (C1): fallos inyectados, carreras entre hilos y cobertura
REAL de la guardia. Corrige los bloqueos de la revisión de Codex a 1364fd1:

1. Hilo dueño que falla antes de informar -> sin espera indefinida.
2. Cierre de LeaseEscritorOperativo / EscritorEquipoUnico con excepciones ->
   el turno se suelta siempre y la excepción se propaga.
3. Carreras adquirir/soltar entre hilos y entre raíces -> sin "ocupado" falso
   y sin cerrojo global sostenido durante una espera.
4. Cobertura de la guardia: lo cubierto se prueba; lo NO cubierto (descriptor
   abierto, llamadas nativas, alias de ruta, eventos no listados) se demuestra
   como límite, no se afirma protección.

Mutex, hilos y procesos son reales (Windows). Nada toca G: ni Cloud.
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

pytestmark = pytest.mark.skipif(os.name != "nt", reason="mutex con nombre de Windows")


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


# ------------------------------------------- 1. hilo dueño que falla o no responde

@pytest.mark.parametrize("fallo", ["kernel32", "create_mutex"])
def test_fallo_del_hilo_dueno_antes_de_informar_no_deja_espera_indefinida(entorno, monkeypatch, fallo):  # noqa: F811
    real = el._kernel32

    def kernel32_roto():
        if fallo == "kernel32":
            raise OSError("kernel32 no disponible (inyectado)")
        k = real()

        class Envoltura:
            def __getattr__(self, nombre):
                return getattr(k, nombre)

            @staticmethod
            def CreateMutexW(*_args):
                return None
        return Envoltura()

    monkeypatch.setattr(el, "_kernel32", kernel32_roto)
    turno = el.TurnoEscritura(entorno["raiz"])
    resultado = _en_hilo(turno.adquirir, limite=10)
    assert isinstance(resultado.get("error"), el.ErrorTurno), resultado
    assert resultado["duracion"] < 2
    assert not turno.vigente and not el.posee_turno(entorno["raiz"])
    monkeypatch.setattr(el, "_kernel32", real)
    turno = el.TurnoEscritura(entorno["raiz"])
    assert turno.adquirir()  # el estado quedó limpio
    turno.soltar()


def test_hilo_dueno_que_no_responde_en_plazo_es_error_y_no_retiene_el_mutex(entorno, monkeypatch):  # noqa: F811
    real = el._kernel32
    monkeypatch.setattr(el, "MARGEN_RESPUESTA_SEGUNDOS", 0.5)

    def kernel32_lento():
        time.sleep(2.0)  # el hilo dueño se demora más que espera + margen
        return real()

    monkeypatch.setattr(el, "_kernel32", kernel32_lento)
    turno = el.TurnoEscritura(entorno["raiz"])
    resultado = _en_hilo(turno.adquirir, limite=10)
    assert isinstance(resultado.get("error"), el.ErrorTurno) and "no respondió" in str(resultado["error"])
    assert resultado["duracion"] < 1.5
    monkeypatch.setattr(el, "_kernel32", real)
    time.sleep(2.5)  # el hilo tardío toma el mutex y, con la orden de soltar ya dada, lo libera
    assert _otro_proceso_obtiene(entorno, "tras_tardio")


def test_fallo_al_iniciar_el_hilo_es_error_y_libera_la_transicion(entorno, monkeypatch):  # noqa: F811
    def no_inicia(_self):
        raise RuntimeError("can't start new thread (inyectado)")

    monkeypatch.setattr(el._Poseedor, "start", no_inicia)
    resultado = _en_hilo(el.TurnoEscritura(entorno["raiz"]).adquirir, limite=10)
    assert isinstance(resultado.get("error"), el.ErrorTurno)
    monkeypatch.undo()
    t = el.TurnoEscritura(entorno["raiz"])
    assert _en_hilo(t.adquirir, limite=10)["valor"] is True
    t.soltar()


def test_interrupcion_tras_tomar_el_mutex_lo_suelta_y_se_propaga(entorno, monkeypatch):  # noqa: F811
    def interrumpir(*_args):
        raise KeyboardInterrupt

    monkeypatch.setattr(el, "_escribir_marcador", interrumpir)
    with pytest.raises(KeyboardInterrupt):
        el.TurnoEscritura(entorno["raiz"]).adquirir()
    assert not el.posee_turno(entorno["raiz"])
    assert _otro_proceso_obtiene(entorno, "tras_interrupcion")


def test_espera_infinita_o_negativa_se_rechaza():
    for valor in (float("inf"), float("nan"), -1):
        with pytest.raises(ValueError):
            el.TurnoEscritura("C:\\x", espera_segundos=valor)


def test_liberacion_no_confirmada_se_informa_como_error(entorno, monkeypatch):  # noqa: F811
    turno = el.TurnoEscritura(entorno["raiz"])
    assert turno.adquirir()
    poseedor = el._estados[turno.raiz_norm].poseedor
    real = el._Poseedor.soltar
    monkeypatch.setattr(el._Poseedor, "soltar", lambda self: False)
    with pytest.raises(el.ErrorTurno, match="No se confirmó la liberación"):
        turno.soltar()
    assert not el.posee_turno(entorno["raiz"])  # la guardia ya no permite escribir
    assert real(poseedor) is True  # (limpieza real del mutex de la prueba)


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

def test_adquirir_durante_una_liberacion_pausada_espera_y_obtiene_el_turno(entorno, monkeypatch):  # noqa: F811
    """Revisión Codex (2): antes, soltar borraba el registro antes de liberar el
    mutex y una adquisición concurrente del MISMO proceso devolvía ocupado."""
    real = el._Poseedor.soltar
    liberando = threading.Event()

    def soltar_lento(self):
        liberando.set()
        time.sleep(1.0)
        return real(self)

    monkeypatch.setattr(el._Poseedor, "soltar", soltar_lento)
    primero = el.TurnoEscritura(entorno["raiz"])
    assert primero.adquirir()
    hilo_soltar = threading.Thread(target=primero.soltar)
    hilo_soltar.start()
    assert liberando.wait(5)
    segundo = el.TurnoEscritura(entorno["raiz"])
    resultado = _en_hilo(segundo.adquirir, limite=20)
    hilo_soltar.join(20)
    assert resultado.get("valor") is True, resultado
    assert resultado["duracion"] >= 0.5  # esperó a que la liberación terminara
    assert el.posee_turno(entorno["raiz"])
    monkeypatch.undo()
    segundo.soltar()
    assert not el.posee_turno(entorno["raiz"])


def test_espera_en_una_raiz_no_bloquea_la_adquisicion_de_otra(entorno, tmp_path):  # noqa: F811
    """Revisión Codex: el cerrojo global de adquisición se sostenía durante la
    espera del mutex. Ahora cada raíz tiene su transición."""
    a = entorno["lanzar"]("tomar")  # otro proceso sostiene la raíz protegida
    senal(entorno["control"], "tomar", proceso=a)
    otra = tmp_path / "otra_raiz"
    otra.mkdir()
    esperando = el.TurnoEscritura(entorno["raiz"], espera_segundos=3)
    hilo = threading.Thread(target=esperando.adquirir)
    hilo.start()
    time.sleep(0.3)  # el hilo ya está esperando el mutex de la primera raíz
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


def test_hilos_concurrentes_adquieren_y_sueltan_sin_falsos_ocupados_ni_bloqueos(entorno):  # noqa: F811
    raiz = entorno["raiz"]
    fallos: list = []

    def trabajar(n):
        for i in range(40):
            turno = el.TurnoEscritura(raiz, espera_segundos=5)
            try:
                if not turno.adquirir():
                    fallos.append(("ocupado", n, i))
                    continue
                (raiz / f"hilo_{n}.txt").write_text(str(i), encoding="utf-8")
            except BaseException as error:  # noqa: BLE001
                fallos.append((type(error).__name__, n, i))
            finally:
                turno.soltar()

    hilos = [threading.Thread(target=trabajar, args=(n,), daemon=True) for n in range(12)]
    inicio = time.monotonic()
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(120)
    assert not any(h.is_alive() for h in hilos), "bloqueo entre hilos"
    assert fallos == []
    assert time.monotonic() - inicio < 120
    assert not el.posee_turno(raiz)
    assert _otro_proceso_obtiene(entorno, "tras_hilos")


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
