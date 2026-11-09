"""Credenciales IA por empresa. El perfil de Windows se simula con un winreg falso:
nunca se lee ni escribe HKCU real y ninguna credencial es real."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import atlas_core.aislamiento_empresas as ae
from tests.test_aislamiento_empresas import mundo  # noqa: F401

MOTOR = Path(__file__).resolve().parents[1]
NORTE, SUR = "transportes-norte", "transportes-sur"
MBT_PERFIL = {"OPENROUTER_API_KEY": "or-mbt", "TAVILY_API_KEY": "tv-mbt", "GROQ_API_KEY": "gq-mbt"}
WINREG = textwrap.dedent("""\
    import json, os, sys, types
    _perfil = json.loads(os.environ["H_PERFIL"])
    _w = types.ModuleType("winreg")
    _w.HKEY_CURRENT_USER = 1; _w.KEY_SET_VALUE = 2; _w.REG_SZ = 1
    class _K:
        def __enter__(self): return self
        def __exit__(self, *a): return False
    _w.OpenKey = lambda *a, **k: _K()
    def _q(k, n):
        if n not in _perfil: raise FileNotFoundError(n)
        return (_perfil[n], 1)
    _w.QueryValueEx = _q
    def _s(k, n, r, t, v): _perfil[n] = v
    _w.SetValueEx = _s
    sys.modules["winreg"] = _w
    """)
RESOLVER = """
    from atlas_core.atlas_ia.credenciales import resolver_openrouter_api_key as o, resolver_tavily_api_key as t, resolver_credencial as c
    from atlas_core.atlas_ia.proveedor_groq import resolver_groq_api_key as g
    print(json.dumps([o(), t(), g()]))
"""


def _correr(mundo, empresa, cuerpo, *, perfil=MBT_PERFIL, **extra):  # noqa: F811
    mbt, a, b = mundo
    env = {k: v for k, v in os.environ.items() if not k.startswith("ATLAS_") and k not in MBT_PERFIL}
    env.update(PYTHONPATH=str(MOTOR), H_PERFIL=json.dumps(perfil))
    if empresa is None:
        env["ATLAS_DATA_DIR"] = str(mbt)
    else:
        env.update({"ATLAS_DATA_DIR": str((a if empresa == NORTE else b).raiz), ae.VARIABLE_EMPRESA: empresa, ae.VARIABLE_RAIZ_MBT: str(mbt)})
    env.update(extra)
    r = subprocess.run([sys.executable, "-c", WINREG + textwrap.dedent(cuerpo)], capture_output=True, text=True, env=env, cwd=MOTOR, timeout=120)
    assert r.returncode == 0, r.stderr + r.stdout
    return r.stdout


def _valores(salida):
    return json.loads(salida.strip().splitlines()[-1])


def test_mbt_conserva_perfil_y_entorno(mundo):  # noqa: F811
    assert _valores(_correr(mundo, None, RESOLVER)) == ["or-mbt", "tv-mbt", "gq-mbt"]
    assert _valores(_correr(mundo, None, RESOLVER, OPENROUTER_API_KEY="or-env"))[0] == "or-env"


def test_otra_empresa_no_hereda_del_perfil(mundo):  # noqa: F811
    assert _valores(_correr(mundo, NORTE, RESOLVER)) == ["", "", ""]


def test_otra_empresa_no_hereda_del_entorno_del_proceso(mundo):  # noqa: F811
    extra = {k: f"env-{v}" for k, v in MBT_PERFIL.items()}
    assert _valores(_correr(mundo, NORTE, RESOLVER, **extra)) == ["", "", ""]


def test_credenciales_propias_por_entorno_y_por_perfil(mundo):  # noqa: F811
    perfil = {**MBT_PERFIL, "TAVILY_API_KEY__TRANSPORTES_NORTE": "tv-norte"}
    salida = _correr(mundo, NORTE, RESOLVER, perfil=perfil, OPENROUTER_API_KEY__TRANSPORTES_NORTE="or-norte")
    assert _valores(salida) == ["or-norte", "tv-norte", ""]


def test_una_empresa_no_usa_las_de_otra(mundo):  # noqa: F811
    perfil = {**MBT_PERFIL, "GROQ_API_KEY__TRANSPORTES_NORTE": "gq-norte"}
    assert _valores(_correr(mundo, SUR, RESOLVER, perfil=perfil, TAVILY_API_KEY__TRANSPORTES_NORTE="tv-norte")) == ["", "", ""]


def test_mbt_no_lee_las_de_otra_empresa(mundo):  # noqa: F811
    perfil = {"GROQ_API_KEY__TRANSPORTES_NORTE": "gq-norte"}
    assert _valores(_correr(mundo, None, RESOLVER, perfil=perfil)) == ["", "", ""]


def test_funciones_informan_no_configurada(mundo):  # noqa: F811
    _correr(mundo, NORTE, """
        from atlas_core.atlas_ia.proveedor_openrouter import ProveedorModeloIAOpenRouter as PO, CredencialOpenRouterAusente as CO
        from atlas_core.atlas_ia.proveedor_groq import ProveedorModeloIAGroq as PG, CredencialGroqAusente as CG
        from atlas_core.atlas_ia.buscador_web import BuscadorWebOpenRouter as BO, CredencialBuscadorWebAusente as CB
        from atlas_core.atlas_ia.buscador_tavily import BuscadorWebTavily as BT
        from atlas_core.atlas_ia.investigacion_revision import _buscador_externo_configurado, _estado_busqueda_externa
        def ausente(f, tipo):
            try:
                f()
            except tipo as e:
                assert "configurada" in str(e), str(e)
                return
            raise SystemExit("no informó ausencia")
        ausente(lambda: PO(modelo="m:free").razonar(None), CO)
        ausente(lambda: PG(modelo="m").razonar(None), CG)
        ausente(lambda: BO().buscar("x"), CB)
        ausente(lambda: BT().buscar("x"), CB)
        assert _buscador_externo_configurado() is None
        assert _estado_busqueda_externa(None, None)["estado"] == "NO_DISPONIBLE"
    """)


def test_empresa_con_credencial_propia_sigue_operativa(mundo):  # noqa: F811
    _correr(mundo, NORTE, """
        from atlas_core.atlas_ia.investigacion_revision import _buscador_externo_configurado
        assert _buscador_externo_configurado() is not None
    """, TAVILY_API_KEY__TRANSPORTES_NORTE="tv-norte")


REGISTRAR = """
    from atlas_core.atlas_ia import credenciales as c
    c._notificar_cambio_entorno_windows = lambda: None
    c.registrar_credencial_usuario("TAVILY_API_KEY", "nueva")
    print(json.dumps(_perfil))
"""


def test_registrar_para_una_empresa_no_sobrescribe_la_de_mbt(mundo):  # noqa: F811
    perfil = _valores(_correr(mundo, NORTE, REGISTRAR))
    assert perfil["TAVILY_API_KEY"] == "tv-mbt"
    assert perfil["TAVILY_API_KEY__TRANSPORTES_NORTE"] == "nueva"


def test_registrar_en_mbt_sigue_igual(mundo):  # noqa: F811
    perfil = _valores(_correr(mundo, None, REGISTRAR))
    assert perfil["TAVILY_API_KEY"] == "nueva" and len(perfil) == 3


def test_bajo_solo_consulta_de_desktop(mundo):  # noqa: F811
    """Consultas Desktop: os.putenv y escritura prohibidos; el perfil sigue sin filtrarse."""
    salida = _correr(mundo, NORTE, """
        def veto(e, a):
            if e in ("os.putenv", "os.unsetenv"):
                raise PermissionError("putenv")
        sys.addaudithook(veto)
    """ + RESOLVER, **{
        **ae.abrir_empresa(mundo[0], NORTE).entorno(), "ATLAS_CLOUD_MOTOR_TOKEN": "", "OPENROUTER_API_KEY__TRANSPORTES_NORTE": "or-norte"})
    assert _valores(salida) == ["or-norte", "", ""]
