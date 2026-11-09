"""Exclusión local de escritores (Etapa 1, C1) con PROCESOS WINDOWS REALES.

Cada escritor es un proceso Python independiente (tests/ayudante_exclusion_local.py)
que importa atlas_core. La raíz protegida es una carpeta temporal declarada en
ATLAS_EXCLUSION_RAICES; las señales viajan por una carpeta de control fuera de
ella. Nada toca G:, Cloud ni datos operacionales.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from atlas_core import escritor_operativo as eo
from atlas_core import exclusion_local as el

pytestmark = pytest.mark.skipif(os.name != "nt", reason="bloqueo de archivo de Windows")

AYUDANTE = Path(__file__).with_name("ayudante_exclusion_local.py")
REPO = AYUDANTE.parent.parent


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    raiz = tmp_path / "raiz_protegida"
    control = tmp_path / "control"
    local = tmp_path / "localappdata"
    for carpeta in (raiz, control, local):
        carpeta.mkdir()
    env = {k: v for k, v in os.environ.items() if k not in {"ATLAS_DATA_DIR", "ATLAS_OPERACION_CONFIG"}}
    env.update(ATLAS_EXCLUSION_RAICES=str(raiz), ATLAS_EXCLUSION_LOCAL="exigir", LOCALAPPDATA=str(local),
               PYTHONDONTWRITEBYTECODE="1")
    # Mismo entorno para lo que la prueba haga en su propio proceso.
    for clave in ("ATLAS_DATA_DIR", "ATLAS_OPERACION_CONFIG"):
        monkeypatch.delenv(clave, raising=False)
    monkeypatch.setenv("ATLAS_EXCLUSION_RAICES", str(raiz))
    monkeypatch.setenv("ATLAS_EXCLUSION_LOCAL", "exigir")
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    procesos: list[subprocess.Popen] = []

    def lanzar(modo: str, *extra: str, control_propio: Path | None = None) -> subprocess.Popen:
        proceso = subprocess.Popen([sys.executable, str(AYUDANTE), modo, str(raiz), str(control_propio or control), *extra],
                                   cwd=str(REPO), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        procesos.append(proceso)
        return proceso

    yield {"raiz": raiz, "control": control, "local": local, "lanzar": lanzar, "env": env}
    for proceso in procesos:
        if proceso.poll() is None:
            proceso.kill()
        proceso.wait(timeout=30)


def senal(control: Path, nombre: str, limite: float = 30.0, proceso: subprocess.Popen | None = None) -> dict:
    ruta = control / f"{nombre}.json"
    fin = time.monotonic() + limite
    while not ruta.exists():
        if proceso is not None and proceso.poll() is not None and not ruta.exists():
            raise AssertionError(f"el proceso terminó ({proceso.returncode}) sin señal {nombre}: "
                                 f"{proceso.stderr.read().decode(errors='replace')[-2000:]}")
        if time.monotonic() > fin:
            raise AssertionError(f"sin señal {nombre}")
        time.sleep(0.02)
    return json.loads(ruta.read_text(encoding="utf-8"))


def ordenar(control: Path, nombre: str) -> None:
    (control / nombre).write_text("1", encoding="utf-8")


def terminar_ok(proceso: subprocess.Popen, limite: float = 30.0) -> int:
    codigo = proceso.wait(timeout=limite)
    assert codigo in (0, 3), proceso.stderr.read().decode(errors="replace")[-2000:]
    return codigo


# ------------------------------------------------------------ concurrencia

def test_segundo_proceso_no_obtiene_el_turno_ni_escribe_mientras_el_primero_lo_sostiene(entorno, tmp_path):
    a = entorno["lanzar"]("tomar")
    tomado = senal(entorno["control"], "tomar", proceso=a)
    assert tomado["ok"] is True and tomado["abandonado"] is False
    control_b = tmp_path / "control_b"
    control_b.mkdir()
    b = entorno["lanzar"]("tomar", control_propio=control_b)
    assert senal(control_b, "tomar", proceso=b)["ok"] is False
    assert terminar_ok(b) == 3
    control_c = tmp_path / "control_c"
    control_c.mkdir()
    c = entorno["lanzar"]("escribir", control_propio=control_c)
    escrito = senal(control_c, "escribir", proceso=c)
    assert escrito["ok"] is False and escrito["error"] == "EscrituraSinTurno"
    terminar_ok(c)
    assert not list(entorno["raiz"].glob("escrito_*"))
    # Liberado el turno, otro proceso lo obtiene y escribe.
    ordenar(entorno["control"], "soltar")
    senal(entorno["control"], "soltado", proceso=a)
    terminar_ok(a)
    control_d = tmp_path / "control_d"
    control_d.mkdir()
    d = entorno["lanzar"]("escribir", "con_turno", control_propio=control_d)
    assert senal(control_d, "escribir", proceso=d)["ok"] is True
    terminar_ok(d)


def test_espera_bloqueante_obtiene_el_turno_cuando_el_otro_lo_suelta(entorno, tmp_path):
    a = entorno["lanzar"]("tomar")
    senal(entorno["control"], "tomar", proceso=a)
    control_b = tmp_path / "control_b"
    control_b.mkdir()
    b = entorno["lanzar"]("tomar", "20", control_propio=control_b)
    time.sleep(1.0)
    assert not (control_b / "tomar.json").exists()  # bloqueado, no adquirido
    ordenar(entorno["control"], "soltar")
    resultado = senal(control_b, "tomar", proceso=b)
    assert resultado["ok"] is True and resultado["abandonado"] is False
    assert 0.8 <= resultado["espera"] < 20
    ordenar(control_b, "soltar")
    terminar_ok(a)
    terminar_ok(b)


# ------------------------------------------- terminación inesperada / abandono

@pytest.mark.parametrize("forma", ["terminate", "exit"])
def test_proceso_terminado_sin_soltar_no_deja_el_turno_bloqueado(entorno, tmp_path, forma):
    a = entorno["lanzar"]("tomar_y_morir", *(["exit"] if forma == "exit" else []))
    pid_a = senal(entorno["control"], "tomar", proceso=a)["pid"]
    if forma == "terminate":
        # TerminateProcess sobre el proceso que sostiene el turno (el venv usa un
        # lanzador: se termina el intérprete real, no sólo el lanzador).
        subprocess.run(["taskkill", "/PID", str(pid_a), "/F"], check=True, capture_output=True)
    else:
        ordenar(entorno["control"], "morir")  # os._exit(7): sin finally ni atexit
    assert a.wait(timeout=30) != 0
    control_b = tmp_path / "control_b"
    control_b.mkdir()
    b = entorno["lanzar"]("tomar", control_propio=control_b)
    resultado = senal(control_b, "tomar", proceso=b)
    assert resultado["ok"] is True
    assert resultado["abandonado"] is True  # señal para la recuperación de la etapa siguiente
    abandonos = (entorno["local"] / "Atlas" / "cache" / "exclusion_local" / "abandonos.jsonl").read_text(encoding="utf-8")
    registro = json.loads(abandonos.splitlines()[-1])
    assert registro["pid"] == resultado["pid"]
    assert registro["anterior"]["pid"] == pid_a
    ordenar(control_b, "soltar")
    terminar_ok(b)
    # Tras un abandono atendido, el siguiente turno es normal (no abandonado).
    control_c = tmp_path / "control_c"
    control_c.mkdir()
    c = entorno["lanzar"]("tomar", control_propio=control_c)
    assert senal(control_c, "tomar", proceso=c)["abandonado"] is False
    ordenar(control_c, "soltar")
    terminar_ok(c)


def test_excepcion_dentro_del_turno_lo_libera(entorno, tmp_path):
    a = entorno["lanzar"]("excepcion")
    senal(entorno["control"], "soltado", proceso=a)
    terminar_ok(a)
    control_b = tmp_path / "control_b"
    control_b.mkdir()
    b = entorno["lanzar"]("tomar", control_propio=control_b)
    resultado = senal(control_b, "tomar", proceso=b)
    assert resultado["ok"] is True and resultado["abandonado"] is False
    ordenar(control_b, "soltar")
    terminar_ok(b)


# ----------------------------------------------------- integración con el lease

def test_escritor_con_lease_vencido_sigue_solo_y_el_otro_proceso_no_escribe(entorno, tmp_path):
    """Escenario de test_lease_fencing.py en el MISMO equipo: aunque Cloud
    concediera el lease al segundo proceso, el turno local lo impide; no hay
    nada del segundo que el primero (atrasado) pueda pisar."""
    a = entorno["lanzar"]("lease_sostener")
    assert senal(entorno["control"], "lease", proceso=a)["ok"] is True
    control_b = tmp_path / "control_b"
    control_b.mkdir()
    b = entorno["lanzar"]("lease_intentar", control_propio=control_b)
    intento = senal(control_b, "intento", proceso=b)
    assert intento["ok"] is False
    assert intento["motivo"] == el.CODIGO_OCUPADO and intento["ocupado"] is True
    assert intento["llamadas_cloud"] == 0  # ni siquiera consulta Cloud sin turno
    assert intento["escrito"] is False and intento["sin_turno"] == "RECHAZADO"
    terminar_ok(b)
    ordenar(entorno["control"], "soltar")
    assert senal(entorno["control"], "soltado", proceso=a)["turno_libre"] is True
    terminar_ok(a)
    assert (entorno["raiz"] / "dataset.csv").read_text(encoding="utf-8") == "version_A_tardia"
    assert not (entorno["raiz"] / "intento_sin_turno.txt").exists()
    # cerrar() soltó el turno: el siguiente lease lo obtiene.
    control_c = tmp_path / "control_c"
    control_c.mkdir()
    c = entorno["lanzar"]("lease_intentar", control_propio=control_c)
    assert senal(control_c, "intento", proceso=c)["ok"] is True
    terminar_ok(c)


def test_equipo_unico_y_lease_comparten_el_turno(entorno, tmp_path):
    a = entorno["lanzar"]("equipo_unico")
    assert senal(entorno["control"], "equipo_unico", proceso=a)["ok"] is True
    control_b = tmp_path / "control_b"
    control_b.mkdir()
    b = entorno["lanzar"]("lease_intentar", control_propio=control_b)
    assert senal(control_b, "intento", proceso=b)["motivo"] == el.CODIGO_OCUPADO
    terminar_ok(b)
    ordenar(entorno["control"], "soltar")
    senal(entorno["control"], "soltado", proceso=a)
    terminar_ok(a)


def test_ciclos_concurrentes_tipo_pull_y_desktop_sin_bloqueos_ni_solapamiento(entorno):
    """Tres procesos repiten turnos cortos (como PULL cada 2 min y Desktop con su
    espera acotada). Ninguno se bloquea, todos completan y la sección crítica
    nunca tiene dos dueños (marcador creado con O_EXCL)."""
    ciclos = 25
    procesos = {n: entorno["lanzar"]("ciclos", n, str(ciclos)) for n in ("pull", "desktop", "mantenimiento")}
    for nombre, proceso in procesos.items():
        resultado = senal(entorno["control"], f"ciclos_{nombre}", limite=120, proceso=proceso)
        assert resultado["ok"] is True, resultado
        assert resultado["hechos"] == ciclos
        assert resultado["espera_max"] < 30
        assert proceso.wait(timeout=60) == 0, proceso.stderr.read().decode(errors="replace")[-2000:]
    assert not (entorno["raiz"] / "seccion_critica.marca").exists()


# ------------------------------------------------------- límites demostrados

def test_limite_un_proceso_ajeno_al_motor_escribe_aunque_otro_tenga_el_turno(entorno):
    """LÍMITE (no se asume protección): el mutex es cooperativo. Un proceso que
    no importa atlas_core (Drive, Explorador, otro programa, un script suelto)
    escribe en la raíz aunque un escritor del Motor tenga el turno."""
    a = entorno["lanzar"]("tomar")
    assert senal(entorno["control"], "tomar", proceso=a)["ok"] is True
    ajeno = entorno["raiz"] / "escrito_por_ajeno.txt"
    r = subprocess.run([sys.executable, "-I", "-c", f"open(r'{ajeno}', 'w').write('ajeno')"],
                       env=entorno["env"], capture_output=True, timeout=60)
    assert r.returncode == 0
    assert ajeno.read_text() == "ajeno"
    ordenar(entorno["control"], "soltar")
    terminar_ok(a)


def test_limite_un_proceso_colgado_retiene_el_turno_hasta_que_termina(entorno, tmp_path):
    """LÍMITE: una interrupción (terminación) libera el turno, pero un proceso
    vivo y colgado lo retiene. Los demás fallan cerrado (no escriben) y lo
    obtienen en cuanto ese proceso termina."""
    a = entorno["lanzar"]("tomar_y_morir")  # duerme 600 s con el turno
    pid_a = senal(entorno["control"], "tomar", proceso=a)["pid"]
    for intento in range(3):
        control = tmp_path / f"control_{intento}"
        control.mkdir()
        b = entorno["lanzar"]("tomar", control_propio=control)
        assert senal(control, "tomar", proceso=b)["ok"] is False
        terminar_ok(b)
    subprocess.run(["taskkill", "/PID", str(pid_a), "/F"], check=True, capture_output=True)
    a.wait(timeout=30)
    control = tmp_path / "control_final"
    control.mkdir()
    c = entorno["lanzar"]("tomar", control_propio=control)
    assert senal(control, "tomar", proceso=c)["ok"] is True
    ordenar(control, "soltar")
    terminar_ok(c)


# ------------------------------------------------------------ en el proceso

def test_guardia_en_proceso_exige_turno_y_respeta_modos(entorno):
    raiz = entorno["raiz"]
    with pytest.raises(el.EscrituraSinTurno):
        (raiz / "a.txt").write_text("x", encoding="utf-8")
    with pytest.raises(el.EscrituraSinTurno):
        (raiz / "sub").mkdir()
    fuera = entorno["control"] / "libre.txt"
    fuera.write_text("x", encoding="utf-8")  # fuera de la raíz: permitido
    with el.TurnoEscritura(raiz):
        (raiz / "a.txt").write_text("x", encoding="utf-8")
        os.replace(raiz / "a.txt", raiz / "b.txt")
        hilo_ok = []
        hilo = threading.Thread(target=lambda: hilo_ok.append((raiz / "c.txt").write_text("y", encoding="utf-8")))
        hilo.start()
        hilo.join()
        assert hilo_ok  # el turno es del proceso: otro hilo también escribe
    with pytest.raises(el.EscrituraSinTurno):
        os.remove(raiz / "b.txt")
    os.environ["ATLAS_EXCLUSION_LOCAL"] = "observar"
    try:
        os.remove(raiz / "b.txt")  # observar: no bloquea, anota
        anotadas = (entorno["local"] / "Atlas" / "cache" / "exclusion_local" / "observaciones.jsonl").read_text(encoding="utf-8")
        assert "b.txt" in anotadas
        os.environ["ATLAS_EXCLUSION_LOCAL"] = "desactivada"
        os.remove(raiz / "c.txt")
    finally:
        os.environ["ATLAS_EXCLUSION_LOCAL"] = "exigir"


def test_turno_no_es_reentrante_y_otra_instancia_lo_obtiene_tras_soltar(entorno, tmp_path):
    raiz = entorno["raiz"]
    primero, segundo = el.TurnoEscritura(raiz), el.TurnoEscritura(raiz)
    assert primero.adquirir()
    assert primero.adquirir()  # la misma instancia: sin efecto, una sola posesión
    assert segundo.adquirir() is False and not segundo.vigente
    segundo.soltar()  # no es dueña: no libera lo ajeno
    assert primero.vigente and el.posee_turno(raiz / "x")
    control_b = tmp_path / "control_b"
    control_b.mkdir()
    b = entorno["lanzar"]("tomar", control_propio=control_b)
    assert senal(control_b, "tomar", proceso=b)["ok"] is False
    terminar_ok(b)
    primero.soltar()  # un solo soltar basta
    primero.soltar()  # idempotente
    assert not el.posee_turno(raiz / "x")
    assert segundo.adquirir() and segundo.vigente
    segundo.soltar()


class _CloudSecuencia:
    def __init__(self, adquirir):
        self.adquirir = adquirir
        self.llamadas = []

    def __call__(self, _base, ruta, _token, *, method="GET", body=None, timeout=0):
        self.llamadas.append(ruta)
        if ruta.endswith("/estado"):
            return {"epoca": 0, "vigente": False}
        if ruta.endswith("/adquirir"):
            return self.adquirir()
        return {"estado": "LIBERADO" if ruta.endswith("/liberar") else "RENOVADO"}


def _lease(entorno, monkeypatch, cloud):
    monkeypatch.setattr(eo, "_json", cloud)
    monkeypatch.setenv("ATLAS_DATA_DIR", str(entorno["raiz"]))
    return eo.LeaseEscritorOperativo(base_url="https://cloud.falsa", token_motor="x", escritor_id="pc-prueba",
                                     heartbeat_segundos=0, margen_relevo_segundos=0,
                                     ruta_relevo=entorno["local"] / "relevo.json")


def test_lease_rechazado_por_cloud_suelta_el_turno(entorno, monkeypatch):
    def ocupado():
        raise eo.EscritorOcupado("409", "ESCRITOR_OCUPADO")
    escritor = _lease(entorno, monkeypatch, _CloudSecuencia(ocupado))
    assert escritor.adquirir() is False and escritor.motivo == "ESCRITOR_OCUPADO"
    assert escritor.turno is None and not el.posee_turno(entorno["raiz"])


def test_error_inesperado_al_adquirir_suelta_el_turno(entorno, monkeypatch):
    def roto():
        raise RuntimeError("fallo inesperado")
    escritor = _lease(entorno, monkeypatch, _CloudSecuencia(roto))
    with pytest.raises(RuntimeError):
        escritor.adquirir()
    assert not el.posee_turno(entorno["raiz"])


def test_turno_se_mantiene_hasta_despues_de_confirmar_y_liberar(entorno, monkeypatch):
    escritor = _lease(entorno, monkeypatch, _CloudSecuencia(lambda: {"estado": "ADQUIRIDO", "lease_token": "t", "epoca": 1}))
    vistos = []

    class CustodiaQueFalla:
        raiz = entorno["raiz"]

        def confirmar(self, _lease):
            vistos.append(("confirmar", el.posee_turno(entorno["raiz"])))
            raise RuntimeError("Cloud caído al confirmar")

        def detener(self):
            vistos.append(("detener", el.posee_turno(entorno["raiz"])))

    assert escritor.adquirir()
    custodia = CustodiaQueFalla()
    escritor.custodia = custodia
    monkeypatch.setattr(eo, "_custodias_activas", lambda: [custodia])
    escritor.cerrar()
    assert vistos == [("confirmar", True), ("detener", True)]
    assert not el.posee_turno(entorno["raiz"])
    assert escritor.lease_token == ""


def test_raices_protegidas_solo_compartidas_salvo_declaracion_explicita(monkeypatch, tmp_path):
    monkeypatch.delenv("ATLAS_EXCLUSION_RAICES", raising=False)
    monkeypatch.delenv("ATLAS_OPERACION_CONFIG", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path / "local"))
    assert el.raices_protegidas() == ()
    politica = tmp_path / "Atlas" / "desktop_operacion.json"
    politica.parent.mkdir(parents=True)
    politica.write_text(json.dumps({"raiz": "G:\\Mi unidad\\Atlas"}), encoding="utf-8")
    monkeypatch.setenv("ATLAS_DATA_DIR", "G:\\Mi unidad\\Atlas")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path) + os.sep)  # invalida la caché
    assert el.raices_protegidas() == (el.normalizar_raiz("G:\\Mi unidad\\Atlas"),)
