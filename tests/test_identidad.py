"""Identidad y permisos: clasificación de puntos de entrada, roles y puerta del proceso."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from atlas_core import identidad as idn

MOTOR = Path(__file__).resolve().parents[1]


def test_todo_punto_de_entrada_del_motor_esta_clasificado():
    """Con la identidad exigida, un CLI no clasificado se niega: uno nuevo debe decidirse aquí."""
    scripts = {p.name for p in MOTOR.glob("*.py") if p.name != "conftest.py"}
    assert scripts - set(idn.CAPACIDADES) == set()


@pytest.mark.parametrize("argv, esperado", [
    (["python", "-B", "b1_consulta_cli.py", "--texto", "x"], "b1_consulta_cli.py"),
    (["python", "-B", "-m", "atlas_core.estado_confirmado", "--sembrar"], "atlas_core.estado_confirmado"),
    (["python", "-c", "import atlas_core"], "-c"),
    (["python", "-X", "utf8", r"C:\x\consulta_python.py", r"C:\m\consultar_atlas.py", "--a"], "consultar_atlas.py"),
    (["python", "-W", "ignore", "C:/m/usuarios_atlas.py", "listar"], "usuarios_atlas.py"),
])
def test_entrada_del_proceso(monkeypatch, argv, esperado):
    monkeypatch.setattr(sys, "orig_argv", argv, raising=False)
    assert idn.entrada_proceso() == esperado


def test_roles_y_permisos():
    assert idn.PERMISOS[idn.ROL_SUPERADMIN] == {idn.ADMINISTRADORES}  # nada operacional
    assert not idn.PERMISOS[idn.ROL_CHOFER]
    assert idn.GESTIONAR not in idn.PERMISOS[idn.ROL_SUPERVISOR] and idn.CORREGIR in idn.PERMISOS[idn.ROL_SUPERVISOR]
    assert idn.PERMISOS["operacion"] == idn.PERMISOS[idn.ROL_SUPERVISOR]  # rol de la rama de acceso Desktop
    assert idn.PERMISOS["consulta"] == {idn.CONSULTAR}


@pytest.mark.parametrize("rol, objetivo, accion, activos, permitido", [
    (idn.ROL_ADMIN, idn.ROL_SUPERVISOR, "crear", 1, True),
    (idn.ROL_ADMIN, idn.ROL_ADMIN, "crear", 1, True),
    (idn.ROL_ADMIN, idn.ROL_SUPERADMIN, "crear", 1, False),
    (idn.ROL_SUPERVISOR, idn.ROL_SUPERVISOR, "crear", 1, False),
    (idn.ROL_SUPERADMIN, idn.ROL_ADMIN, "crear", 0, True),
    (idn.ROL_SUPERADMIN, idn.ROL_ADMIN, "crear", 1, False),
    (idn.ROL_SUPERADMIN, idn.ROL_ADMIN, "restablecer", 0, False),
    (idn.ROL_SUPERADMIN, idn.ROL_ADMIN, "desactivar", 1, True),
    (idn.ROL_SUPERADMIN, idn.ROL_SUPERVISOR, "desactivar", 1, False),
    (idn.ROL_CHOFER, idn.ROL_SUPERVISOR, "crear", 1, False),
])
def test_quien_gestiona_a_quien(rol, objetivo, accion, activos, permitido):
    registro = {"usuarios": [{"usuario": f"a{i}", "rol": idn.ROL_ADMIN, "activo": True} for i in range(activos)]}
    sesion = {"rol": rol, "usuario": "actor", "tipo": "plataforma" if rol == idn.ROL_SUPERADMIN else "empresa"}
    if permitido:
        idn._autorizar_sobre(sesion, registro, rol_objetivo=objetivo, accion=accion, usuario="otro")
    else:
        with pytest.raises(idn.ErrorIdentidad):
            idn._autorizar_sobre(sesion, registro, rol_objetivo=objetivo, accion=accion, usuario="otro")


def test_admin_no_se_desactiva_ni_cambia_su_rol():
    sesion = {"rol": idn.ROL_ADMIN, "usuario": "yo"}
    for accion in ("desactivar", "cambiar_rol"):
        with pytest.raises(idn.ErrorIdentidad):
            idn._autorizar_sobre(sesion, {"usuarios": []}, rol_objetivo=idn.ROL_ADMIN, accion=accion, usuario="YO")


# ---- puerta del proceso (subprocesos: se activa al importar atlas_core)
def _mundo(tmp_path: Path, registro: dict | str | None) -> dict:
    raiz = tmp_path / "Atlas"
    (raiz / "catalogos_privados").mkdir(parents=True)
    if registro is not None:
        texto = registro if isinstance(registro, str) else json.dumps(registro)
        (raiz / "catalogos_privados" / "desktop_usuarios.json").write_text(texto, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("ATLAS_")}
    env.update(PYTHONPATH=str(MOTOR), ATLAS_DATA_DIR=str(raiz), LOCALAPPDATA=str(tmp_path / "local"), PYTHONIOENCODING="utf-8")
    return env


def _correr(env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-B", *args], capture_output=True, text=True, encoding="utf-8",
                          env=env, cwd=MOTOR, timeout=120)


def test_sin_registro_o_sin_exigencia_nada_cambia(tmp_path):
    for registro in (None, {"version": 1, "empresa_id": "mbt", "exigir_identidad": False, "usuarios": []}):
        env = _mundo(tmp_path / str(bool(registro)), registro)
        assert _correr(env, "-c", "import atlas_core").returncode == 0


def test_exigencia_activa_niega_sin_sesion_y_entradas_no_clasificadas(tmp_path):
    env = _mundo(tmp_path, {"version": 1, "empresa_id": "mbt", "exigir_identidad": True, "usuarios": []})
    r = _correr(env, "-c", "import atlas_core")
    assert r.returncode == idn.SALIDA_DENEGADO and "ENTRADA_NO_CLASIFICADA" in r.stderr
    r = _correr(env, str(MOTOR / "b1_consulta_cli.py"), "--help")
    assert r.returncode == idn.SALIDA_DENEGADO and "SIN_SESION" in r.stderr
    assert _correr(env, str(MOTOR / "sincronizar_mobile_cloud.py"), "--help").returncode == 0  # sistema


@pytest.mark.parametrize("contenido, codigo", [
    ("{no es json", "REGISTRO_ILEGIBLE"),
    (json.dumps({"version": 1, "empresa_id": "otra-empresa", "exigir_identidad": False, "usuarios": []}), "REGISTRO_DE_OTRA_EMPRESA"),
])
def test_registro_danado_o_ajeno_falla_cerrado(tmp_path, contenido, codigo):
    r = _correr(_mundo(tmp_path, contenido), str(MOTOR / "b1_consulta_cli.py"), "--help")
    assert r.returncode == idn.SALIDA_DENEGADO and codigo in r.stderr
