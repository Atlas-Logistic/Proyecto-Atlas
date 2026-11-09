"""Exclusión local por bloqueo de archivo: F1-F4 de la revisión de Codex a
b4d0de2 y las invariantes de REEVALUACION.md, con hilos y procesos Windows
reales. Nada toca G:, Cloud ni datos operacionales.
"""
from __future__ import annotations

import errno
import os
import subprocess
import threading
import time

import pytest

from atlas_core import exclusion_local as el
from tests.test_exclusion_local import entorno, ordenar, senal, terminar_ok  # noqa: F401
from tests.test_exclusion_local_fallos import _lease, _otro_proceso_obtiene, _Cloud

pytestmark = pytest.mark.skipif(os.name != "nt", reason="bloqueo de archivo de Windows")


@pytest.fixture(autouse=True)
def sin_propietarios_residuales():
    """Una prueba fallida no contamina las siguientes con un turno tomado."""
    yield
    for propietario in list(el._propietarios.values()):
        propietario.archivo.close()
    el._propietarios.clear()


class _Interrupcion(Exception):
    """Excepción propia: no es OSError y no debe convertirse en ErrorTurno."""


def _control(tmp_path, nombre):
    carpeta = tmp_path / f"control_{nombre}"
    carpeta.mkdir()
    return carpeta


def _matar(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=True, capture_output=True)


def _inyectar(monkeypatch, punto, excepcion):
    disparos = []

    def disparar(nombre):
        if nombre == punto and not disparos:
            disparos.append(nombre)
            raise excepcion()

    monkeypatch.setattr(el, "_punto", disparar)
    return disparos


# ------------------------------------------------------------------- F1 a F4

def test_f1_terminar_el_hilo_que_adquirio_no_pierde_el_turno(entorno):  # noqa: F811
    """F1: con mutex, la muerte del hilo dueño lo abandonaba y otro proceso lo
    tomaba mientras este seguía creyéndose dueño."""
    turno = el.TurnoEscritura(entorno["raiz"])
    hilo = threading.Thread(target=turno.adquirir)
    hilo.start()
    hilo.join(10)
    assert not hilo.is_alive() and turno.vigente and el.posee_turno(entorno["raiz"])
    assert _otro_proceso_obtiene(entorno, "con_hilo_muerto") is False
    assert turno.vigente
    turno.soltar()
    assert _otro_proceso_obtiene(entorno, "tras_soltar")


def test_f2_interrupcion_tras_conceder_el_bloqueo_no_lo_retiene(entorno, monkeypatch):  # noqa: F811
    """F2: una interrupción entre la concesión y el registro retenía el mutex."""
    _inyectar(monkeypatch, "tras_bloquear", KeyboardInterrupt)
    turno = el.TurnoEscritura(entorno["raiz"])
    with pytest.raises(KeyboardInterrupt):
        turno.adquirir()
    assert not turno.vigente and not el.posee_turno(entorno["raiz"])
    assert _otro_proceso_obtiene(entorno, "f2")


def test_f3_interrupcion_al_limpiar_en_soltar_no_retiene_el_bloqueo(entorno, monkeypatch):  # noqa: F811
    """F3: una interrupción al borrar el marcador dejaba el registro sin turno
    y el mutex retenido."""
    turno = el.TurnoEscritura(entorno["raiz"])
    assert turno.adquirir()
    _inyectar(monkeypatch, "durante_vaciado", KeyboardInterrupt)
    with pytest.raises(KeyboardInterrupt):
        turno.soltar()
    assert not turno.vigente and not el.posee_turno(entorno["raiz"])
    assert _otro_proceso_obtiene(entorno, "f3")


def test_f4_varios_hilos_con_la_misma_instancia_aportan_una_sola_posesion(entorno):  # noqa: F811
    """F4: dos hilos con la misma instancia sumaban dos referencias y un
    soltar dejaba posesión sin dueño."""
    for ciclo in range(20):
        turno = el.TurnoEscritura(entorno["raiz"])
        barrera = threading.Barrier(8)
        resultados: list = []

        def pedir():
            barrera.wait(10)
            resultados.append(turno.adquirir())

        hilos = [threading.Thread(target=pedir) for _ in range(8)]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join(20)
        assert all(not h.is_alive() for h in hilos) and resultados == [True] * 8, ciclo
        assert len(el._propietarios) == 1 and turno.vigente
        turno.soltar()  # un solo soltar la libera por completo
        assert not el.posee_turno(entorno["raiz"]) and el._propietarios == {}
    assert _otro_proceso_obtiene(entorno, "f4")


# -------------------------------------------------- interrupción en cada punto

PUNTOS_ADQUIRIR = ["tras_abrir", "tras_bloquear", "tras_leer_previo", "tras_escribir_pid", "antes_registrar", "tras_registrar"]
PUNTOS_SOLTAR = ["tras_retirar_registro", "durante_vaciado", "durante_desbloqueo"]


@pytest.mark.parametrize("excepcion", [KeyboardInterrupt, _Interrupcion], ids=["keyboard", "propia"])
@pytest.mark.parametrize("punto", PUNTOS_ADQUIRIR)
def test_interrupcion_al_adquirir_no_deja_posesion(entorno, monkeypatch, punto, excepcion):  # noqa: F811
    disparos = _inyectar(monkeypatch, punto, excepcion)
    turno = el.TurnoEscritura(entorno["raiz"])
    with pytest.raises(excepcion):
        turno.adquirir()
    assert disparos == [punto]
    assert not turno.vigente and not el.posee_turno(entorno["raiz"]) and el._propietarios == {}
    assert _otro_proceso_obtiene(entorno, "adq")


@pytest.mark.parametrize("excepcion", [KeyboardInterrupt, _Interrupcion], ids=["keyboard", "propia"])
@pytest.mark.parametrize("punto", PUNTOS_SOLTAR)
def test_interrupcion_al_soltar_libera_lo_fisico(entorno, monkeypatch, punto, excepcion):  # noqa: F811
    turno = el.TurnoEscritura(entorno["raiz"])
    assert turno.adquirir()
    archivo = el._propietarios[turno.raiz_norm].archivo
    disparos = _inyectar(monkeypatch, punto, excepcion)
    with pytest.raises(excepcion):
        turno.soltar()
    assert disparos == [punto] and archivo.closed
    assert not turno.vigente and not el.posee_turno(entorno["raiz"]) and el._propietarios == {}
    assert _otro_proceso_obtiene(entorno, "sol")
    turno.soltar()  # idempotente tras el fallo


def test_interrupcion_al_volver_de_tomar_no_deja_posesion_desconocida(entorno, monkeypatch):  # noqa: F811
    real = el.TurnoEscritura._tomar

    def tomar_e_interrumpir(self, fin):
        assert real(self, fin) is True
        raise KeyboardInterrupt

    monkeypatch.setattr(el.TurnoEscritura, "_tomar", tomar_e_interrumpir)
    turno = el.TurnoEscritura(entorno["raiz"])
    with pytest.raises(KeyboardInterrupt):
        turno.adquirir()
    assert not turno.vigente and el._propietarios == {}
    assert _otro_proceso_obtiene(entorno, "al_volver")


def test_interrupcion_al_entrar_al_with_no_deja_posesion(entorno, monkeypatch):  # noqa: F811
    real = el.TurnoEscritura.adquirir

    def adquirir_e_interrumpir(self):
        assert real(self) is True
        raise KeyboardInterrupt

    monkeypatch.setattr(el.TurnoEscritura, "adquirir", adquirir_e_interrumpir)
    turno = el.TurnoEscritura(entorno["raiz"])
    with pytest.raises(KeyboardInterrupt):
        with turno:
            raise AssertionError("no debe entrar")
    assert not turno.vigente and el._propietarios == {}


def test_transicion_no_queda_tomada_tras_una_interrupcion(entorno, monkeypatch):  # noqa: F811
    _inyectar(monkeypatch, "tras_bloquear", KeyboardInterrupt)
    turno = el.TurnoEscritura(entorno["raiz"])
    with pytest.raises(KeyboardInterrupt):
        turno.adquirir()
    assert el._transicion(turno.raiz_norm).dueno is None


def test_lo_logico_nunca_indica_posesion_sin_el_bloqueo(entorno, monkeypatch):  # noqa: F811
    """I1: antes de registrar no hay posesión lógica y al soltar se retira
    primero lo lógico, con el bloqueo aún concedido."""
    vistos = {}
    turno = el.TurnoEscritura(entorno["raiz"])

    def observar(nombre):
        vistos[nombre] = turno.vigente

    monkeypatch.setattr(el, "_punto", observar)
    assert turno.adquirir()
    turno.soltar()
    assert vistos == {"tras_abrir": False, "tras_bloquear": False, "tras_leer_previo": False,
                      "tras_escribir_pid": False, "antes_registrar": False, "tras_registrar": True,
                      "tras_retirar_registro": False, "durante_vaciado": False, "durante_desbloqueo": False}


# -------------------------------------------- terminación del proceso por punto

@pytest.mark.parametrize("punto,abandonado", [
    ("tras_abrir", False), ("tras_bloquear", False), ("tras_leer_previo", False),
    ("tras_escribir_pid", True), ("antes_registrar", True), ("tras_registrar", True),
    ("tras_retirar_registro", True), ("durante_vaciado", True), ("durante_desbloqueo", False),
])
def test_matar_el_proceso_en_cada_punto_libera_y_senala_abandono(entorno, tmp_path, punto, abandonado):  # noqa: F811
    a = entorno["lanzar"]("pausar_en", punto)
    pid = senal(entorno["control"], "en_punto", proceso=a)["pid"]
    _matar(pid)
    a.wait(timeout=30)
    control = _control(tmp_path, "siguiente")
    b = entorno["lanzar"]("tomar", "5", control_propio=control)
    resultado = senal(control, "tomar", proceso=b)
    assert resultado["ok"] is True and resultado["abandonado"] is abandonado
    assert resultado["espera"] < 5
    ordenar(control, "soltar")
    terminar_ok(b)


def test_interrupcion_antes_de_registrar_conserva_la_senal_de_un_abandono_previo(entorno, tmp_path, monkeypatch):  # noqa: F811
    a = entorno["lanzar"]("tomar_y_morir")
    _matar(senal(entorno["control"], "tomar", proceso=a)["pid"])
    a.wait(timeout=30)
    _inyectar(monkeypatch, "antes_registrar", KeyboardInterrupt)
    with pytest.raises(KeyboardInterrupt):
        el.TurnoEscritura(entorno["raiz"]).adquirir()
    monkeypatch.setattr(el, "_punto", lambda _nombre: None)
    siguiente = el.TurnoEscritura(entorno["raiz"])
    assert siguiente.adquirir() and siguiente.abandonado is True
    siguiente.soltar()
    otro = el.TurnoEscritura(entorno["raiz"])
    assert otro.adquirir() and otro.abandonado is False
    otro.soltar()


# ------------------------------------------- exclusión e hilos, procesos reales

def test_sin_solapamiento_de_intervalos_entre_procesos_reales(entorno, tmp_path):  # noqa: F811
    controles = [_control(tmp_path, n) for n in ("uno", "dos", "tres")]
    procesos = [entorno["lanzar"]("intervalos", "5", control_propio=c) for c in controles]
    por_proceso = [senal(c, "intervalos", limite=60, proceso=p) for c, p in zip(controles, procesos)]
    for proceso in procesos:
        assert proceso.wait(timeout=30) == 0
    assert all(d["colisiones"] == 0 for d in por_proceso)
    assert sum(1 for d in por_proceso if d["intervalos"]) >= 2  # hubo competencia real
    intervalos = sorted((tuple(i), n) for n, d in enumerate(por_proceso) for i in d["intervalos"])
    assert len(intervalos) > 20
    for (anterior, _), (siguiente, _) in zip(intervalos, intervalos[1:]):
        assert anterior[1] <= siguiente[0], (anterior, siguiente)


def test_instancias_distintas_en_hilos_nunca_son_dos_duenas(entorno):  # noqa: F811
    raiz = entorno["raiz"]
    duenas, maximo, fallos = [0], [0], []
    cuenta = threading.Lock()

    def trabajar(n):
        hechos = 0
        fin = time.monotonic() + 60
        while hechos < 40 and time.monotonic() < fin:
            turno = el.TurnoEscritura(raiz)
            try:
                if not turno.adquirir():
                    time.sleep(0.001)
                    continue
                with cuenta:
                    duenas[0] += 1
                    maximo[0] = max(maximo[0], duenas[0])
                (raiz / f"hilo_{n}.txt").write_text(str(hechos), encoding="utf-8")
                with cuenta:
                    duenas[0] -= 1
                hechos += 1
                turno.soltar()
            except BaseException as error:  # noqa: BLE001
                fallos.append(repr(error))
                return
        if hechos < 40:
            fallos.append(("incompleto", n, hechos))

    hilos = [threading.Thread(target=trabajar, args=(n,), daemon=True) for n in range(12)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(90)
    assert not any(h.is_alive() for h in hilos), "bloqueo entre hilos"
    assert fallos == [] and maximo[0] == 1
    assert not el.posee_turno(raiz) and _otro_proceso_obtiene(entorno, "hilos")


def test_soltar_desde_otro_hilo_libera(entorno):  # noqa: F811
    turno = el.TurnoEscritura(entorno["raiz"])
    assert turno.adquirir()
    hilo = threading.Thread(target=turno.soltar)
    hilo.start()
    hilo.join(10)
    assert not turno.vigente and _otro_proceso_obtiene(entorno, "otro_hilo")


def test_adquirir_durante_una_liberacion_lenta_espera_la_transicion(entorno, monkeypatch):  # noqa: F811
    liberando = threading.Event()

    def pausar(nombre):
        if nombre == "durante_desbloqueo":
            liberando.set()
            time.sleep(0.6)

    monkeypatch.setattr(el, "_punto", pausar)
    primero = el.TurnoEscritura(entorno["raiz"])
    assert primero.adquirir()
    hilo = threading.Thread(target=primero.soltar)
    hilo.start()
    assert liberando.wait(5)
    segundo = el.TurnoEscritura(entorno["raiz"])
    assert segundo.adquirir() is True
    hilo.join(10)
    assert segundo.vigente and not primero.vigente
    monkeypatch.setattr(el, "_punto", lambda _nombre: None)
    segundo.soltar()


@pytest.mark.parametrize("variante", ["sin_heredar", "heredar"])
def test_hijos_no_conservan_el_bloqueo(entorno, tmp_path, variante):  # noqa: F811
    a = entorno["lanzar"]("tomar_con_hijo", *(["heredar"] if variante == "heredar" else []))
    datos = senal(entorno["control"], "tomar", proceso=a)
    hijo = datos["hijo"]
    try:
        assert _otro_proceso_obtiene(entorno, "con_padre") is False
        _matar(datos["pid"])
        a.wait(timeout=30)
        assert subprocess.run(["tasklist", "/FI", f"PID eq {hijo}", "/NH"], capture_output=True, text=True).stdout.count(str(hijo)) == 1
        control = _control(tmp_path, "con_hijo_vivo")
        b = entorno["lanzar"]("tomar", "5", control_propio=control)
        assert senal(control, "tomar", proceso=b)["ok"] is True
        ordenar(control, "soltar")
        terminar_ok(b)
    finally:
        subprocess.run(["taskkill", "/PID", str(hijo), "/F"], capture_output=True)


def test_archivo_de_turno_no_se_puede_borrar_mientras_esta_tomado(entorno):  # noqa: F811
    turno = el.TurnoEscritura(entorno["raiz"])
    assert turno.adquirir()
    with pytest.raises(PermissionError):
        os.remove(el.ruta_turno(entorno["raiz"]))
    turno.soltar()


# ------------------------------------------------------------ esperas y errores

def test_espera_ocupada_termina_en_plazo(entorno):  # noqa: F811
    a = entorno["lanzar"]("tomar")
    senal(entorno["control"], "tomar", proceso=a)
    turno = el.TurnoEscritura(entorno["raiz"], espera_segundos=1.0)
    inicio = time.monotonic()
    assert turno.adquirir() is False
    assert 0.9 <= time.monotonic() - inicio < 2.5
    assert not turno.vigente
    ordenar(entorno["control"], "soltar")
    terminar_ok(a)


def _capturar_archivos(monkeypatch):
    abiertos = []
    real = el._abrir_archivo_turno

    def abrir(raiz_norm):
        abiertos.append(real(raiz_norm))
        return abiertos[-1]

    monkeypatch.setattr(el, "_abrir_archivo_turno", abrir)
    return abiertos


def test_error_del_sistema_al_bloquear_es_error_turno_sin_handles(entorno, monkeypatch):  # noqa: F811
    abiertos = _capturar_archivos(monkeypatch)

    def locking(*_args):
        raise OSError(errno.EIO, "fallo de E/S inyectado")

    monkeypatch.setattr(el.msvcrt, "locking", locking)
    turno = el.TurnoEscritura(entorno["raiz"])
    with pytest.raises(el.ErrorTurno):
        turno.adquirir()
    assert len(abiertos) == 1 and abiertos[0].closed and not turno.vigente


def test_apertura_denegada_es_error_turno(entorno, monkeypatch):  # noqa: F811
    def denegar(_ruta, _banderas):
        raise PermissionError(errno.EACCES, "denegado (inyectado)")

    monkeypatch.setattr(el, "_abrir_o_crear", denegar)
    turno = el.TurnoEscritura(entorno["raiz"])
    with pytest.raises(el.ErrorTurno):
        turno.adquirir()
    assert not turno.vigente and not el.posee_turno(entorno["raiz"])


def test_cache_inaccesible_es_error_turno(entorno, monkeypatch, tmp_path):  # noqa: F811
    bloqueo = tmp_path / "no_es_carpeta"
    bloqueo.write_text("x", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(bloqueo))
    with pytest.raises(el.ErrorTurno):
        el.TurnoEscritura(entorno["raiz"]).adquirir()
    assert not el.posee_turno(entorno["raiz"])


def test_fallo_al_escribir_el_dueno_es_error_y_libera(entorno, monkeypatch):  # noqa: F811
    abiertos = _capturar_archivos(monkeypatch)

    def sin_espacio(*_args):
        raise OSError(errno.ENOSPC, "sin espacio (inyectado)")

    monkeypatch.setattr(el, "_escribir_dueno", sin_espacio)
    with pytest.raises(el.ErrorTurno):
        el.TurnoEscritura(entorno["raiz"]).adquirir()
    assert abiertos[0].closed and _otro_proceso_obtiene(entorno, "sin_espacio")


def test_fallo_al_desbloquear_es_error_pero_cierra_el_handle(entorno, monkeypatch):  # noqa: F811
    turno = el.TurnoEscritura(entorno["raiz"])
    assert turno.adquirir()
    archivo = el._propietarios[turno.raiz_norm].archivo
    real = el.msvcrt.locking

    def locking(fd, modo, n):
        if modo == el.msvcrt.LK_UNLCK:
            raise OSError(errno.EIO, "fallo inyectado")
        return real(fd, modo, n)

    monkeypatch.setattr(el.msvcrt, "locking", locking)
    with pytest.raises(el.ErrorTurno, match="desbloquear"):
        turno.soltar()
    assert archivo.closed and not turno.vigente and not el.posee_turno(entorno["raiz"])
    assert _otro_proceso_obtiene(entorno, "tras_fallo_desbloqueo")


def test_plataforma_sin_msvcrt_falla_cerrado(entorno, monkeypatch):  # noqa: F811
    monkeypatch.setattr(el, "msvcrt", None)
    turno = el.TurnoEscritura(entorno["raiz"])
    with pytest.raises(el.ErrorTurno):
        turno.adquirir()
    assert not turno.vigente


# ------------------------------------------------------------------ escritores

def test_lease_deja_de_estar_vigente_si_el_turno_se_pierde(entorno, monkeypatch):  # noqa: F811
    escritor = _lease(entorno, monkeypatch, _Cloud())
    assert escritor.adquirir() and escritor.vigente
    el._propietarios[escritor.turno.raiz_norm].archivo.close()  # pérdida forzada
    assert not escritor.turno.vigente and escritor.vigente is False and not el.posee_turno(entorno["raiz"])
    escritor.cerrar()
    assert el._propietarios == {} and escritor.turno is None


def test_equipo_unico_deja_de_estar_vigente_si_el_turno_se_pierde(entorno):  # noqa: F811
    from atlas_core.exclusividad_equipo import EscritorEquipoUnico
    escritor = EscritorEquipoUnico(entorno["raiz"], verificar=lambda: None)
    assert escritor.adquirir() and escritor.vigente
    el._propietarios[escritor.turno.raiz_norm].archivo.close()
    assert escritor.vigente is False
    escritor.cerrar()
    assert el._propietarios == {}


def test_adquisicion_anidada_de_escritores_falla_con_ocupado_local(entorno, monkeypatch):  # noqa: F811
    primero = _lease(entorno, monkeypatch, _Cloud())
    assert primero.adquirir()
    segundo = _lease(entorno, monkeypatch, _Cloud())
    assert segundo.adquirir() is False and segundo.motivo == el.CODIGO_OCUPADO and segundo.ocupado is True
    assert primero.vigente
    primero.cerrar()
    assert el._propietarios == {}
