"""Proceso de alta (ATLAS_EMPRESA_ALTA): N-ésima empresa, sin abrir la frontera.

Antes, con una empresa ya creada, ningún proceso podía crear otra ni repetir el
alta (la guarda de MBT veta Atlas_empresas). Cada caso corre en un proceso
nuevo: la guarda se activa al importar atlas_core y es irreversible.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

MOTOR = Path(__file__).resolve().parents[1]


def correr(entorno: dict, codigo: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("ATLAS_")}
    env.update(PYTHONPATH=str(MOTOR), PYTHONIOENCODING="utf-8", **entorno)
    return subprocess.run([sys.executable, "-B", "-c", "import atlas_core.aislamiento_empresas as ae, os, json\n" + codigo],
                          capture_output=True, text=True, encoding="utf-8", env=env, cwd=MOTOR, timeout=120)


def proceso_alta(mbt: Path, local: Path, empresa: str, alta: str | None = None) -> dict:
    return {"ATLAS_EMPRESA_ID": empresa, "ATLAS_EMPRESA_ALTA": alta or empresa, "ATLAS_RAIZ_MBT": str(mbt),
            "ATLAS_DATA_DIR": str(mbt.parent / "Atlas_empresas" / empresa), "LOCALAPPDATA": str(local)}


def alta(mbt: Path, local: Path, empresa: str, cloud: str) -> subprocess.CompletedProcess:
    return correr(proceso_alta(mbt, local, empresa),
                  f"c = ae.inicializar_empresa(os.environ['ATLAS_RAIZ_MBT'], {empresa!r}, nombre='N', cloud_id={cloud!r})\n"
                  "print(json.dumps(ae.listar_empresas(os.environ['ATLAS_RAIZ_MBT'])))")


def mundo(tmp_path: Path) -> tuple[Path, Path]:
    mbt = tmp_path / "drive" / "Atlas"
    (mbt / "catalogos_privados").mkdir(parents=True)
    (tmp_path / "local").mkdir()
    return mbt, tmp_path / "local"


def test_tercera_empresa_y_repeticion(tmp_path):
    mbt, local = mundo(tmp_path)
    assert alta(mbt, local, "uno", "c-uno").returncode == 0
    r = alta(mbt, local, "dos", "c-dos")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == '["mbt", "dos", "uno"]'
    assert alta(mbt, local, "dos", "c-dos").returncode == 0  # idempotente
    r = alta(mbt, local, "tres", "c-uno")
    assert "CLOUD_ID_EN_USO" in r.stderr


def test_alta_no_abre_datos_de_otra_empresa(tmp_path):
    mbt, local = mundo(tmp_path)
    alta(mbt, local, "uno", "c-uno")
    ajena = mbt.parent / "Atlas_empresas" / "uno" / "catalogos_privados"
    (ajena / "choferes.json").write_text("{}", encoding="utf-8")
    r = correr(proceso_alta(mbt, local, "dos"), f"""
base = {str(ajena)!r}
for accion in (lambda: open(os.path.join(base, 'choferes.json')).read(),
               lambda: open(os.path.join(base, 'empresa_identidad.json'), 'a'),
               lambda: os.listdir(os.path.dirname(base))):
    try:
        accion(); print('PERMITIDO')
    except ae.ErrorAislamiento as e:
        print(e.codigo)
print(json.loads(open(os.path.join(base, 'empresa_identidad.json')).read())['empresa_id'])
""")
    assert r.stdout.split() == ["ACCESO_ENTRE_EMPRESAS"] * 3 + ["uno"], r.stderr


def test_procesos_normales_siguen_sin_ver_el_registro(tmp_path):
    mbt, local = mundo(tmp_path)
    alta(mbt, local, "uno", "c-uno")
    alta(mbt, local, "dos", "c-dos")
    base = str(mbt.parent / "Atlas_empresas")
    codigo = f"""
for accion in (lambda: os.listdir({base!r}), lambda: open(os.path.join({base!r}, 'uno', 'catalogos_privados', 'empresa_identidad.json')).read()):
    try:
        accion(); print('PERMITIDO')
    except ae.ErrorAislamiento as e:
        print(e.codigo)
"""
    normal = {"ATLAS_EMPRESA_ID": "dos", "ATLAS_RAIZ_MBT": str(mbt), "ATLAS_DATA_DIR": str(mbt.parent / "Atlas_empresas" / "dos"),
              "LOCALAPPDATA": str(local)}
    for entorno in (normal, {"ATLAS_DATA_DIR": str(mbt), "LOCALAPPDATA": str(local)}):
        r = correr(entorno, codigo)
        assert r.stdout.split() == ["ACCESO_ENTRE_EMPRESAS"] * 2, r.stderr


def test_mbt_no_crea_empresas_y_alta_exige_coincidencia(tmp_path):
    mbt, local = mundo(tmp_path)
    alta(mbt, local, "uno", "c-uno")
    r = correr({"ATLAS_DATA_DIR": str(mbt), "LOCALAPPDATA": str(local)},
               "ae.inicializar_empresa(os.environ['ATLAS_DATA_DIR'], 'dos', nombre='N', cloud_id='c-dos')")
    assert "ACCESO_ENTRE_EMPRESAS" in r.stderr
    r = correr(proceso_alta(mbt, local, "dos", alta="uno"), "pass")
    assert "ALTA_DE_OTRA_EMPRESA" in r.stderr
    sucia = mbt.parent / "Atlas_empresas" / "sucia"
    sucia.mkdir()
    (sucia / "dato.txt").write_text("x", encoding="utf-8")
    r = correr(proceso_alta(mbt, local, "sucia"), "pass")
    assert "RAIZ_CON_DATOS_SIN_MARCA" in r.stderr
