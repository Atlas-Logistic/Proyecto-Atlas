"""Exclusión local (C1) frente a los flujos reales del Motor, con la guardia en
``exigir`` sobre una raíz sintética protegida:

- Los lectores que Desktop lanza DIRECTAMENTE (sin sesión ni turno) siguen
  funcionando y no escriben en la raíz.
- La sesión Desktop y una pasada PULL completa escriben bajo su turno y lo
  sueltan al terminar; con el turno tomado por otro proceso no escriben.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from atlas_core import desktop_operacion as do
from atlas_core import escritor_operativo as eo
from atlas_core import exclusion_local as el
from tests.test_b1_operador import raiz  # noqa: F401  (fixture sintética de B1)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="bloqueo de archivo de Windows")
REPO = Path(__file__).resolve().parent.parent
AYUDANTE = Path(__file__).with_name("ayudante_exclusion_local.py")


def _cloud(_base, ruta, _token, *, method="GET", body=None, timeout=0):
    if ruta.endswith("/estado"):
        return {"epoca": 0, "vigente": False}
    if ruta.endswith("/adquirir"):
        return {"estado": "ADQUIRIDO", "lease_token": "t", "epoca": 1}
    return {"estado": "LIBERADO" if ruta.endswith("/liberar") else "RENOVADO"}


class _LeaseSinCustodia(eo.LeaseEscritorOperativo):
    """Lease real (turno incluido) con Cloud falsa y sin custodia de red."""

    def __init__(self, **_kwargs):
        super().__init__(base_url="https://cloud.falsa", token_motor="x", escritor_id="pc-prueba",
                         heartbeat_segundos=0, margen_relevo_segundos=0,
                         ruta_relevo=Path(os.environ["LOCALAPPDATA"]) / "relevo.json")

    def vincular_raiz(self, raiz) -> None:
        os.environ["ATLAS_DATA_DIR"] = str(raiz)  # raíz del turno, sin protocolo 2


@pytest.fixture
def protegida(raiz, monkeypatch):  # noqa: F811
    monkeypatch.setenv("ATLAS_EXCLUSION_RAICES", str(raiz))
    monkeypatch.setenv("ATLAS_EXCLUSION_LOCAL", "exigir")
    monkeypatch.setattr(eo, "_json", _cloud)
    monkeypatch.setenv("ATLAS_DATA_DIR", str(raiz))
    return raiz


def _foto(raiz: Path) -> dict[str, bytes]:
    return {str(p.relative_to(raiz)): p.read_bytes() for p in sorted(raiz.rglob("*")) if p.is_file()}


def _otro_proceso_con_turno(raiz: Path, control: Path) -> subprocess.Popen:
    env = {**os.environ, "ATLAS_EXCLUSION_RAICES": str(raiz)}
    proceso = subprocess.Popen([sys.executable, str(AYUDANTE), "tomar", str(raiz), str(control)], cwd=str(REPO),
                               env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    fin = time.monotonic() + 30
    while not (control / "tomar.json").exists():
        assert time.monotonic() < fin and proceso.poll() is None, proceso.stderr.read().decode(errors="replace")
        time.sleep(0.02)
    assert json.loads((control / "tomar.json").read_text(encoding="utf-8"))["ok"] is True
    return proceso


def _soltar(proceso: subprocess.Popen, control: Path) -> None:
    (control / "soltar").write_text("1", encoding="utf-8")
    assert proceso.wait(timeout=30) == 0


# ------------------------------------------------- lectores directos de Desktop

def test_lectores_directos_de_desktop_no_escriben_ni_fallan_con_la_guardia(protegida, tmp_path):
    raiz = protegida
    from atlas_core.reporte_viajes import generar_reporte_viajes
    reporte = raiz / "reportes" / "vigente"
    with el.TurnoEscritura(raiz):  # el reporte lo publica un escritor, con turno
        generar_reporte_viajes(raiz / "operacion" / "actual" / "analisis_completo_guias.csv", reporte,
                               carpeta_catalogos=raiz / "catalogos_privados")
    viajes = reporte / "viajes.csv"
    assert viajes.is_file()
    antes = _foto(raiz)
    env = {k: v for k, v in os.environ.items() if k != "ATLAS_DATA_DIR"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # Mismos argumentos que main.js usa para cada lector directo.
    lectores = [
        ["b1_consulta_cli.py", "--raiz-atlas", str(raiz), "--texto", "Muéstrame los choferes activos"],
        ["consultar_atlas.py", "cuántos viajes hay", "--viajes", str(viajes), "--raiz-atlas", str(raiz)],
        ["consultar_incidencias_operacionales.py", "incidencias abiertas", "--raiz-atlas", str(raiz), "--viajes", str(viajes)],
        ["construir_fichas_catalogos.py", "--raiz-atlas", str(raiz)],
        ["retomar_entradas_desktop.py", "--raiz-atlas", str(raiz), "--listar"],
    ]
    for argumentos in lectores:
        r = subprocess.run([sys.executable, "-B", *argumentos], cwd=str(REPO), env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=300)
        salida = r.stdout + r.stderr
        assert "EscrituraSinTurno" not in salida, (argumentos[0], salida[-3000:])
        assert r.returncode == 0, (argumentos[0], salida[-3000:])
        if argumentos[0] == "b1_consulta_cli.py":  # este CLI responde 0 aun si falla por dentro
            assert json.loads(r.stdout.strip().splitlines()[-1])["estado"] == "RESULTADO_LECTURA", salida[-3000:]
    assert _foto(raiz) == antes


# ------------------------------------------------------------ sesión Desktop

def test_sesion_desktop_escribe_bajo_turno_y_lo_suelta(protegida, monkeypatch):
    raiz = protegida
    monkeypatch.setattr(do, "compartida", lambda _raiz: True)
    with do.sesion(raiz, fabrica=_LeaseSinCustodia) as comprobar:
        comprobar()
        assert el.posee_turno(raiz)
        assert (raiz / "operacion" / "actual" / ".atlas_lock_desktop_manual").exists()
        (raiz / "operacion" / "actual" / "escrito_por_sesion.txt").write_text("x", encoding="utf-8")
    assert not el.posee_turno(raiz)
    assert not (raiz / "operacion" / "actual" / ".atlas_lock_desktop_manual").exists()
    with pytest.raises(el.EscrituraSinTurno):
        (raiz / "operacion" / "actual" / "fuera_de_sesion.txt").write_text("x", encoding="utf-8")


def test_sesion_desktop_espera_acotada_si_otro_proceso_tiene_el_turno(protegida, monkeypatch, tmp_path):
    raiz = protegida
    monkeypatch.setattr(do, "compartida", lambda _raiz: True)
    monkeypatch.setattr(do, "ESPERA_ESCRITOR_OCUPADO_SEGUNDOS", 0.5)
    monkeypatch.setattr(do, "INTERVALO_ESCRITOR_OCUPADO_SEGUNDOS", 0.05)
    control = tmp_path / "control"
    control.mkdir()
    otro = _otro_proceso_con_turno(raiz, control)
    antes = _foto(raiz)
    try:
        with pytest.raises(PermissionError, match="Escritor ocupado"):
            with do.sesion(raiz, fabrica=_LeaseSinCustodia):
                pass
        assert _foto(raiz) == antes  # ni siquiera el lock de sesión
    finally:
        _soltar(otro, control)
    with do.sesion(raiz, fabrica=_LeaseSinCustodia):
        assert el.posee_turno(raiz)


# ---------------------------------------------------------------- pasada PULL

def _pull(raiz, monkeypatch):
    import sincronizar_mobile_cloud as smc

    def escribe(nombre):
        def paso(*_args, **_kwargs):
            assert el.posee_turno(raiz)
            (raiz / "operacion" / f"pull_{nombre}.txt").write_text("x", encoding="utf-8")
            return {"confirmados": []} if nombre == "envios" else {"ok": True}
        return paso

    for nombre, funcion in [("envios", "sincronizar_envios_cloud"), ("licencias", "sincronizar_licencias_cloud"),
                            ("extraccion", "extraer_licencias_pendientes"),
                            ("patentes", "identificar_patentes_documentos"),
                            ("vencimientos", "extraer_vencimientos_vehiculos"),
                            ("asignaciones", "publicar_asignaciones_cloud")]:
        monkeypatch.setattr(smc, funcion, escribe(nombre))
    monkeypatch.delenv("ATLAS_PULL_AUTORIZACION", raising=False)
    repositorio = type("Repositorio", (), {"raiz_atlas": raiz})()
    return smc.ejecutar_pull_con_escritor(base_url="https://cloud.falsa", token_motor="x", consumidor="pc-prueba",
                                          repositorio=repositorio, timeout=1, procesar=True, dataset=None,
                                          carpeta_catalogos=None, fabrica_escritor=_LeaseSinCustodia)


def test_pasada_pull_completa_escribe_bajo_turno_y_lo_suelta(protegida, monkeypatch):
    raiz = protegida
    resultado = _pull(raiz, monkeypatch)
    assert resultado["confirmados"] == []
    assert sorted(p.name for p in (raiz / "operacion").glob("pull_*.txt")) == [
        "pull_asignaciones.txt", "pull_envios.txt", "pull_extraccion.txt", "pull_licencias.txt",
        "pull_patentes.txt", "pull_vencimientos.txt"]
    assert not el.posee_turno(raiz)


def test_pasada_pull_con_turno_ajeno_no_escribe_ni_consume(protegida, monkeypatch, tmp_path):
    raiz = protegida
    control = tmp_path / "control"
    control.mkdir()
    otro = _otro_proceso_con_turno(raiz, control)
    try:
        resultado = _pull(raiz, monkeypatch)
    finally:
        _soltar(otro, control)
    assert resultado["escritor_operativo"] == "NO_ADQUIRIDO"
    assert resultado["motivo"] == el.CODIGO_OCUPADO
    assert not list((raiz / "operacion").glob("pull_*.txt"))
    # El ciclo siguiente (otro ya terminó) procede normalmente.
    assert _pull(raiz, monkeypatch)["confirmados"] == []
