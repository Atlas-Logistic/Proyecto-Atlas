"""Las licencias se guardan bajo la empresa activa, con el código del almacén."""
from __future__ import annotations

import json
import subprocess
import sys

import atlas_core.aislamiento_empresas as ae
from atlas_core import fichas_choferes as fc
from tests.test_aislamiento_empresas import _arbol, mundo  # noqa: F401
from tests.test_multiempresa_integracion import MOTOR, _entorno

CATALOGO = {"123456785": {"nombre": "ANA", "rut": "12345678-5", "aliases": [], "activo": True}}


def _inicializar(mundo, empresa, raiz):  # noqa: F811
    r = subprocess.run([sys.executable, "inicializar_fichas_choferes.py", "--raiz-atlas", str(raiz), "--actor", "PRUEBA"],
                       capture_output=True, text=True, env=_entorno(mundo, empresa), cwd=MOTOR, timeout=120)
    assert r.returncode == 0, r.stderr


def test_escritor_real_usa_el_codigo_en_mayusculas_y_no_toca_otras(mundo):  # noqa: F811
    mbt, norte, sur = mundo
    for raiz in (mbt, norte.raiz, sur.raiz):
        (raiz / "catalogos_privados" / "choferes.json").write_text(json.dumps(CATALOGO), encoding="utf-8")
    antes = _arbol(mbt), _arbol(sur.raiz)
    _inicializar(mundo, norte.empresa_id, norte.raiz)
    almacen = fc.leer_almacen(norte.raiz, empresa="TRANSPORTES-NORTE")
    assert almacen["empresa"] == "TRANSPORTES-NORTE" and almacen["choferes"][0]["referencias_catalogo"] == ["123456785"]
    assert (_arbol(mbt), _arbol(sur.raiz)) == antes


def test_mbt_conserva_su_almacen(mundo):  # noqa: F811
    mbt, _n, _s = mundo
    (mbt / "catalogos_privados" / "choferes.json").write_text(json.dumps(CATALOGO), encoding="utf-8")
    _inicializar(mundo, None, mbt)
    assert fc.leer_almacen(mbt, empresa="MBT")["empresa"] == "MBT"
    assert not (mbt / "fichas_digitales" / "mbt").exists() or (mbt / "fichas_digitales" / "MBT").samefile(mbt / "fichas_digitales" / "mbt")


def test_admite_el_identificador_mas_largo_de_empresa(tmp_path):
    empresa = ("e" + "a" * 38 + "z").upper()
    assert ae._PATRON_ID.fullmatch(empresa.lower())
    assert fc.ruta_almacen(tmp_path, empresa).parent.name == empresa
    assert fc.ruta_almacen(tmp_path, "MBT").parent.name == "MBT"
