"""Integración multiempresa: entradas reales, estado local, custodia, recuperación y concurrencia."""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import atlas_core.aislamiento_empresas as ae
import atlas_core.registro_relaciones_operacionales as registro
from atlas_core import almacenamiento_portable as ap
from atlas_core import estado_confirmado as ec
from atlas_core.exclusion_local import TurnoEscritura
from tests.test_aislamiento_empresas import GUIA, _arbol, _cliente, _escribir, _lease, _Nubes, _sembrar, mundo  # noqa: F401

MOTOR = Path(__file__).resolve().parents[1]
PRELUDIO = textwrap.dedent("""\
    import os, sys, json, glob, shutil, pathlib
    from pathlib import Path
    import atlas_core
    import atlas_core.aislamiento_empresas as ae
    from atlas_core import almacenamiento_portable as ap
    mbt, a, b, local = [Path(p) for p in sys.argv[1:5]]
    def vetado(f, codigo="ACCESO_ENTRE_EMPRESAS"):
        try:
            f()
        except ae.ErrorAislamiento as e:
            assert e.codigo == codigo, e.codigo
            return
        raise SystemExit("NO VETADO")
    """)


def _entorno(mundo, empresa: str | None, **extra) -> dict[str, str]:
    mbt, a, b = mundo
    env = {k: v for k, v in os.environ.items() if not k.startswith("ATLAS_")}
    env["PYTHONPATH"] = str(MOTOR)
    if empresa is None:
        env["ATLAS_DATA_DIR"] = str(mbt)
    else:
        contexto = {a.empresa_id: a, b.empresa_id: b}[empresa]
        env.update({"ATLAS_DATA_DIR": str(contexto.raiz), ae.VARIABLE_EMPRESA: empresa, ae.VARIABLE_RAIZ_MBT: str(mbt)})
    env.update(extra)
    return env


def _proceso(mundo, empresa, cuerpo, **extra):
    mbt, a, b = mundo
    local = Path(os.environ["LOCALAPPDATA"])
    r = subprocess.run([sys.executable, "-c", PRELUDIO + textwrap.dedent(cuerpo), str(mbt), str(a.raiz), str(b.raiz), str(local)],
                       capture_output=True, text=True, env=_entorno(mundo, empresa, **extra), cwd=MOTOR, timeout=180)
    assert r.returncode == 0, r.stderr + r.stdout
    return r.stdout


NORTE, SUR = "transportes-norte", "transportes-sur"


# --------------------------------------------------- 1. metadatos y lectura
SONDAS = """
    objetivo = OBJETIVO
    m = objetivo / "catalogos_privados" / "choferes.json"
    for f in (lambda: os.stat(m), lambda: os.lstat(m), lambda: os.access(m, os.R_OK), lambda: os.path.exists(m),
              lambda: os.path.lexists(m), lambda: os.path.isfile(m), lambda: os.path.isdir(objetivo),
              lambda: os.path.islink(m), lambda: os.path.getsize(m), lambda: os.path.getmtime(m),
              lambda: Path(m).exists(), lambda: Path(m).stat(), lambda: Path(m).is_file(),
              lambda: Path(objetivo).is_dir(), lambda: list(Path(objetivo).iterdir()), lambda: list(os.walk(objetivo)),
              lambda: glob.glob(str(objetivo / "*")), lambda: shutil.copy(m, a / "copia.json"),
              lambda: open(m).read(), lambda: Path(m).read_bytes(), lambda: Path(m).write_text("x"),
              lambda: Path(m).unlink(), lambda: shutil.rmtree(objetivo),
              lambda: os.stat(str(m).encode()), lambda: os.path.exists(str(objetivo / "no-existe"))):
        vetado(f)
"""


@pytest.fixture
def con_choferes(mundo):  # noqa: F811
    for c in mundo[1:]:
        ap.escribir_json_atomico(c.catalogos() / "choferes.json", {"de": c.empresa_id})
    return mundo


@pytest.mark.parametrize("empresa, objetivo", [(NORTE, "b"), (NORTE, "mbt"), (SUR, "a"), (None, "a"), (None, "b")])
def test_ninguna_sonda_ni_operacion_alcanza_otra_empresa(con_choferes, empresa, objetivo):
    antes = [_arbol(con_choferes[0]), _arbol(con_choferes[1].raiz), _arbol(con_choferes[2].raiz)]
    copia = "a" if empresa == NORTE else ("b" if empresa == SUR else "mbt")
    _proceso(con_choferes, empresa, SONDAS.replace("OBJETIVO", objetivo).replace('a / "copia.json"', f'{copia} / "copia.json"'))
    assert [_arbol(con_choferes[0]), _arbol(con_choferes[1].raiz), _arbol(con_choferes[2].raiz)] == antes


def test_lo_propio_y_los_ancestros_siguen_operando(con_choferes):
    _proceso(con_choferes, NORTE, """
        assert (a / "catalogos_privados" / "choferes.json").is_file() and os.path.getsize(a / "catalogos_privados" / "choferes.json")
        (a / "nueva" / "sub").mkdir(parents=True, exist_ok=True)
        ap.escribir_json_atomico(a / "nueva" / "sub" / "x.json", {})
        assert a.parent.is_dir() and a.parent.parent.exists()
        vetado(lambda: os.listdir(a.parent))
        shutil.rmtree(a / "nueva")
    """)


def test_estado_local_de_mbt_y_de_otra_empresa_vetado_salvo_runtime(mundo):  # noqa: F811
    local = Path(os.environ["LOCALAPPDATA"]) / "Atlas"
    _escribir(local / "desktop_operacion.json", "{}")
    _escribir(local / "runtime" / "rapidocr" / "x.txt", "ok")
    _escribir(local / "empresas" / SUR / "desktop_operacion.json", "{}")
    _proceso(mundo, NORTE, """
        L = local / "Atlas"
        for f in (lambda: open(L / "desktop_operacion.json").read(), lambda: os.path.exists(L / "pull_autorizacion.json"),
                  lambda: os.path.exists(L / "escritor_operativo_id.txt"), lambda: os.listdir(L / "cache"),
                  lambda: open(L / "empresas" / "transportes-sur" / "desktop_operacion.json").read()):
            vetado(f)
        assert (L / "runtime" / "rapidocr" / "x.txt").read_text() == "ok"
    """)
    _proceso(mundo, None, """
        vetado(lambda: open(local / "Atlas" / "empresas" / "transportes-sur" / "desktop_operacion.json").read())
        assert (local / "Atlas" / "desktop_operacion.json").read_text() == "{}"
    """)


# ------------------------------------------------- 2. MBT intacta y entradas
def test_mbt_sin_otras_empresas_no_cambia_nada(tmp_path, monkeypatch):
    local = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    mbt = tmp_path / "Atlas"
    _escribir(mbt / "catalogos_privados" / "choferes.json", "{}")
    antes = _arbol(mbt)
    env = {k: v for k, v in os.environ.items() if not k.startswith("ATLAS_")}
    env.update(PYTHONPATH=str(MOTOR), ATLAS_DATA_DIR=str(mbt), ATLAS_CLOUD_MOTOR_TOKEN="tok")
    codigo = textwrap.dedent("""\
        import os, sys, json
        import atlas_core.aislamiento_empresas as ae
        from atlas_core import escritor_operativo as eo, estado_confirmado as ec, exclusion_local as el, exclusividad_equipo as ex
        from atlas_core.registro_ciclo_pull import directorio_ciclos
        assert ae._guarda is None and type(os.stat).__name__ == "builtin_function_or_method"
        print(json.dumps({"id": str(eo.ruta_identidad_escritor()), "relevo": str(eo.ruta_relevo_confirmado()),
            "custodia": str(ec.ruta_local()), "abandonos": str(el.ruta_registro_abandonos()), "politica": str(ex.ruta_politica()),
            "ciclos": str(directorio_ciclos()), "token": os.environ["ATLAS_CLOUD_MOTOR_TOKEN"],
            "fichas": __import__("atlas_core.fichas_choferes", fromlist=["x"]).EMPRESA_ACTUAL,
            "cache": os.environ.get("ATLAS_CACHE_DIR")}))
        """)
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, env=env, cwd=MOTOR, timeout=120)
    assert r.returncode == 0, r.stderr
    L = local / "Atlas"
    assert json.loads(r.stdout) == {
        "id": str(L / "escritor_operativo_id.txt"), "relevo": str(L / "escritor_operativo_relevo.json"),
        "custodia": str(L / "cache" / "estado_confirmado"), "abandonos": str(L / "cache" / "exclusion_local" / "abandonos.jsonl"),
        "politica": str(L / "desktop_operacion.json"), "ciclos": str(L / "logs" / "pull_ciclos"), "token": "tok", "fichas": "MBT", "cache": None}
    assert _arbol(mbt) == antes


@pytest.mark.parametrize("cli", [["migrar_relaciones_operacionales.py", "--raiz", "B", "--estado"],
                                 ["publicacion_reportes.py", "--raiz", "B", "--estado"],
                                 ["sincronizar_mobile_cloud.py", "--raiz-atlas", "B"],
                                 ["generar_reporte_viajes.py", "B/operacion/actual/x.csv", "B/reportes/z"],
                                 ["b1_consulta_cli.py", "--raiz-atlas", "B", "--texto", "Cuántos viajes tienen revisión"]])
def test_entradas_reales_no_alcanzan_otra_empresa(con_choferes, cli):
    mbt, a, b = con_choferes
    antes = _arbol(b.raiz)
    args = [p.replace("B", str(b.raiz), 1) if p.startswith("B") else p for p in cli]
    r = subprocess.run([sys.executable, *args], capture_output=True, text=True, env=_entorno(con_choferes, NORTE, ATLAS_CLOUD_MOTOR_TOKEN__TRANSPORTES_NORTE="t"),
                       cwd=MOTOR, timeout=180)
    salida = r.stdout + r.stderr
    assert "ACCESO_ENTRE_EMPRESAS" in salida or "RAIZ_DE_OTRA_EMPRESA" in salida, salida[-1500:]
    assert _arbol(b.raiz) == antes


def test_entrada_real_opera_su_propia_empresa(con_choferes):
    mbt, a, _b = con_choferes
    r = subprocess.run([sys.executable, "migrar_relaciones_operacionales.py", "--raiz", str(a.raiz), "--estado"], capture_output=True, text=True,
                       env=_entorno(con_choferes, NORTE), cwd=MOTOR, timeout=120)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["empresa"] == NORTE


def test_desktop_rechaza_raiz_ajena(con_choferes):
    _proceso(con_choferes, NORTE, """
        from atlas_core.desktop_operacion import ejecutar
        try:
            ejecutar({"raiz": str(b), "accion": "ingresar"})
        except ae.ErrorAislamiento as e:
            assert e.codigo in ("ACCESO_ENTRE_EMPRESAS", "RAIZ_DE_OTRA_EMPRESA"), e.codigo
        else:
            raise SystemExit("aceptada")
    """)


@pytest.mark.parametrize("empresa, data_dir", [(None, "a"), (NORTE, "b"), (NORTE, "mbt")])
def test_entorno_ambiguo_falla_cerrado_al_importar(con_choferes, empresa, data_dir):
    mbt, a, b = con_choferes
    raiz = {"a": a.raiz, "b": b.raiz, "mbt": mbt}[data_dir]
    r = subprocess.run([sys.executable, "-c", "import atlas_core"], capture_output=True, text=True,
                       env=_entorno(con_choferes, empresa, ATLAS_DATA_DIR=str(raiz)), cwd=MOTOR, timeout=60)
    assert r.returncode != 0 and "ErrorAislamiento" in r.stderr


def test_empresa_sin_variable_raiz_mbt_falla_cerrado(con_choferes):
    env = _entorno(con_choferes, NORTE)
    del env[ae.VARIABLE_RAIZ_MBT]
    r = subprocess.run([sys.executable, "-c", "import atlas_core"], capture_output=True, text=True, env=env, cwd=MOTOR, timeout=60)
    assert r.returncode != 0 and "ENTORNO_INCOMPLETO" in r.stderr


# --------------------------------------------------------- 3. estado local
LISTA_LOCAL = """
    from atlas_core import escritor_operativo as eo, estado_confirmado as ec, exclusion_local as el, exclusividad_equipo as ex
    from atlas_core.registro_ciclo_pull import directorio_ciclos
    from atlas_core.fichas_choferes import EMPRESA_ACTUAL
    print(json.dumps({"id": str(eo.ruta_identidad_escritor()), "relevo": str(eo.ruta_relevo_confirmado()),
        "custodia": str(ec.ruta_local()), "abandonos": str(el.ruta_registro_abandonos()), "politica": str(ex.ruta_politica()),
        "ciclos": str(directorio_ciclos()), "config": os.environ["ATLAS_OPERACION_CONFIG"], "aut": os.environ["ATLAS_PULL_AUTORIZACION"],
        "cache": os.environ["ATLAS_CACHE_DIR"], "diag": os.environ["ATLAS_DIAGNOSTICO_DIR"], "token": os.environ.get("ATLAS_CLOUD_MOTOR_TOKEN"), "fichas": EMPRESA_ACTUAL}))
"""


def test_todo_el_estado_local_es_de_la_empresa(mundo):  # noqa: F811
    extra = {"ATLAS_CLOUD_MOTOR_TOKEN": "token-mbt", "ATLAS_CLOUD_MOTOR_TOKEN__TRANSPORTES_NORTE": "token-norte"}
    n = json.loads(_proceso(mundo, NORTE, LISTA_LOCAL, **extra))
    s = json.loads(_proceso(mundo, SUR, LISTA_LOCAL, **extra))
    assert (n.pop("token"), s.pop("token")) == ("token-norte", None)  # jamás hereda el token de MBT
    assert (n.pop("fichas"), s.pop("fichas")) == (NORTE, SUR)
    base = Path(os.environ["LOCALAPPDATA"]) / "Atlas" / "empresas"
    for empresa, rutas in ((NORTE, n), (SUR, s)):
        assert all(Path(v).is_relative_to(base / empresa) for v in rutas.values()), rutas
    assert not set(n.values()) & set(s.values())


def test_entorno_completo_no_exige_putenv_bajo_solo_consulta(mundo):  # noqa: F811
    """Desktop corre sus consultas con os.putenv prohibido."""
    _m, a, _b = mundo
    entorno = {**a.entorno(), "ATLAS_CLOUD_MOTOR_TOKEN": "t-n", "ATLAS_CLOUD_MOTOR_TOKEN__TRANSPORTES_NORTE": "t-n"}
    env = {k: v for k, v in os.environ.items() if not k.startswith("ATLAS_")}
    env.update(entorno, PYTHONPATH=str(MOTOR))
    codigo = textwrap.dedent("""\
        import sys
        def veto(e, a):
            if e in ("os.putenv", "os.unsetenv"):
                raise PermissionError("putenv")
        sys.addaudithook(veto)
        import atlas_core.aislamiento_empresas as ae
        assert ae._guarda["empresa_id"] == "transportes-norte"
        """)
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, env=env, cwd=MOTOR, timeout=60)
    assert r.returncode == 0, r.stderr


def test_sin_token_propio_no_hay_lease(mundo):  # noqa: F811
    _proceso(mundo, SUR, """
        from atlas_core.escritor_operativo import lease_desde_entorno
        assert lease_desde_entorno() is None
    """, ATLAS_CLOUD_MOTOR_TOKEN="token-mbt")


def _ps1(mundo, empresa, tmp_path, *, token=True):
    mbt, a, _b = mundo
    local = Path(os.environ["LOCALAPPDATA"])
    base = local / "Atlas" / "empresas" / empresa if empresa else local / "Atlas"
    config = {"modo_escritor": "lease_cloud", "autorizada": True, "habilitada": True, "proyecto": str(MOTOR),
              "raiz": str(a.raiz if empresa else mbt), "python": sys.executable}
    if empresa:
        config["raiz_mbt"] = str(mbt)
    vence = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    _escribir(base / "desktop_operacion.json", json.dumps(config))
    _escribir(base / "pull_autorizacion.json", json.dumps({"autor": "Javier", "exclusividad_verificada": True, "modo": "temporal", "vence_utc": vence}))
    env = {k: v for k, v in os.environ.items() if not k.startswith("ATLAS_")}
    env["ATLAS_RAPIDOCR_PYTHON"] = sys.executable
    if token:
        env["ATLAS_CLOUD_MOTOR_TOKEN" + (f"__{empresa.upper().replace('-', '_')}" if empresa else "")] = "t"
    args = ["-Empresa", empresa] if empresa else []
    return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(MOTOR / "scripts" / "pull_pc_nuevo.ps1"), *args, "-Validar"],
                          capture_output=True, text=True, env=env, cwd=MOTOR, timeout=120)


@pytest.mark.skipif(os.name != "nt", reason="PowerShell")
def test_lanzador_pull_por_empresa_y_mbt_igual(mundo, tmp_path):  # noqa: F811
    r = _ps1(mundo, NORTE, tmp_path)
    assert r.returncode == 0, r.stderr + r.stdout
    d = json.loads(r.stdout)
    assert d["Empresa"] == NORTE and Path(d["Raiz"]).name == NORTE and NORTE in d["Config"]
    r = _ps1(mundo, None, tmp_path)
    assert r.returncode == 0, r.stderr + r.stdout
    d = json.loads(r.stdout)
    assert "Empresa" not in d and Path(d["Raiz"]).name == "Atlas"
    assert _ps1(mundo, NORTE, tmp_path, token=False).returncode != 0


# ------------------------------------------------- 4. custodia por empresa
def test_custodia_rechaza_raiz_ajena_en_el_proceso(mundo):  # noqa: F811
    _proceso(mundo, NORTE, """
        from atlas_core import estado_confirmado as ec
        vetado(lambda: ec.CustodiaEstado(b, ec.ClienteEstado("https://x", "t", 1)), "RAIZ_DE_OTRA_EMPRESA")
        ec.CustodiaEstado(a, ec.ClienteEstado("https://x", "t", 1))
    """)


@pytest.mark.parametrize("token, destino", [("t-a", "b"), ("t-mbt", "b"), ("t-a", "mbt")])
def test_lease_con_token_ajeno_no_restaura_nada(mundo, tmp_path, token, destino):  # noqa: F811
    mbt, a, b = mundo
    c_mbt = ae.abrir_empresa(mbt, ae.EMPRESA_MBT)
    with _Nubes() as nubes:
        _sembrar(a, "t-a", tmp_path)
        _sembrar(c_mbt, "t-mbt", tmp_path)
        objetivo = {"b": b, "mbt": c_mbt}[destino]
        nubes.por_token[token].avanzar(11)
        antes, version = _arbol(objetivo.raiz), nubes.por_token[token].marca["version"]
        with _lease(objetivo, token, "pc-x", tmp_path / "lx") as lease:
            assert not lease.adquirir()  # falla cerrado: se libera sin escribir
            assert not lease.lease_token
        assert _arbol(objetivo.raiz) == antes and nubes.por_token[token].marca["version"] == version


# ------------------------------------------------- 5. registro sin 'oficina'
def _reporte_historico(raiz: Path, nombre: str, chofer: str, tracto: str) -> None:
    carpeta = raiz / "reportes" / nombre
    carpeta.mkdir(parents=True)
    doc = {"numero_guia": GUIA, "numero_transporte": "0000369025", "rut_chofer": chofer, "patente_tracto": tracto, "patente_rampla": "No encontrado"}
    with open(carpeta / "viajes.csv", "w", newline="", encoding="utf-8-sig") as h:
        w = csv.writer(h, delimiter=";")
        w.writerow(["numero_transporte", "evidencias_documentos"])
        w.writerow(["0000369025", json.dumps([doc])])


def _claves_registro(raiz: Path) -> set[str]:
    return set(json.loads((raiz / "catalogos_privados" / "registro_relaciones_operacionales.json").read_text(encoding="utf-8"))["empresas"])


def test_empresa_nueva_migra_activa_y_consulta_sin_oficina(mundo):  # noqa: F811
    mbt, a, b = mundo
    for c, chofer in ((a, "11111111-1"), (b, "22222222-2")):
        _reporte_historico(c.raiz, "r1", chofer, "XX1111")
        registro.migrar_reportes_historicos(c.raiz, aplicar=True)
        assert registro.verificar_migracion(c.raiz)["ok"]
        registro.activar_registro(c.raiz)
        assert _claves_registro(c.raiz) == {c.registro_id} and "oficina" not in _claves_registro(c.raiz)
        assert registro.estado_registro(c.raiz)["empresa"] == c.empresa_id
    assert {r["rut_chofer"] for r in registro.relaciones_si_activo(a.raiz)} == {"11111111-1"}
    assert {r["rut_chofer"] for r in registro.relaciones_si_activo(b.raiz)} == {"22222222-2"}


def test_mbt_conserva_oficina_y_el_explicito_se_respeta(mundo):  # noqa: F811
    mbt, a, _b = mundo
    assert ae.registro_id_de_raiz(mbt) == "oficina"
    assert registro.estado_registro(mbt)["empresa"] == "oficina"
    assert registro.ruta_plan_migracion(mbt) == registro.ruta_plan_migracion(mbt, "oficina")
    assert registro.ruta_plan_migracion(a.raiz) == registro.ruta_plan_migracion(a.raiz, a.empresa_id)
    assert registro.estado_registro(a.raiz, empresa_id="otra")["empresa"] == "otra"


# ---------------------------------- 7. identificadores coincidentes, lectura
def _reporte_vigente(c: ae.ContextoEmpresa, chofer: str, cliente: str) -> None:
    carpeta = c.reportes("vig")
    carpeta.mkdir(parents=True)
    with open(carpeta / "viajes.csv", "w", newline="", encoding="utf-8-sig") as h:
        w = csv.writer(h, delimiter=";")
        w.writerow(["numero_transporte", "numero_guia", "cliente", "rut_chofer"])
        w.writerow(["0000369025", GUIA, cliente, chofer])
    ap.escribir_estado_operacion(reporte_vigente=carpeta, raiz=c.raiz)


def test_mobile_y_b1_con_folio_y_cliente_iguales_ven_solo_lo_suyo(mundo):  # noqa: F811
    _m, a, b = mundo
    _reporte_vigente(a, "11111111-1", "ACME")
    _reporte_vigente(b, "22222222-2", "ACME")
    cuerpo = """
        from atlas_core.mobile import _viajes_del_reporte_vigente
        v = _viajes_del_reporte_vigente(PROPIA)
        assert [x["rut_chofer"] for x in v] == [CHOFER], v
        vetado(lambda: _viajes_del_reporte_vigente(AJENA))
        from atlas_core.b1_operador import OperadorB1
        vetado(lambda: OperadorB1(AJENA).consultar("Cuántos viajes tienen revisión"))
        assert OperadorB1(PROPIA).consultar("Cuántos viajes tienen revisión")["estado"] != "FALLIDA"
    """
    _proceso(mundo, NORTE, cuerpo.replace("PROPIA", "a").replace("AJENA", "b").replace("CHOFER", '"11111111-1"'))
    _proceso(mundo, SUR, cuerpo.replace("PROPIA", "b").replace("AJENA", "a").replace("CHOFER", '"22222222-2"'))


def test_lease_cloud_de_otra_empresa_se_rechaza(mundo):  # noqa: F811
    _proceso(mundo, NORTE, """
        ae.exigir_lease_empresa("cloud-norte")
        vetado(lambda: ae.exigir_lease_empresa("cloud-sur"), "LEASE_DE_OTRA_EMPRESA")
        vetado(lambda: ae.exigir_lease_empresa("empresa-prueba-javier"), "LEASE_DE_OTRA_EMPRESA")
    """)
    _proceso(mundo, None, """
        ae.exigir_lease_empresa("empresa-prueba-javier")
        vetado(lambda: ae.exigir_lease_empresa("cloud-norte"), "LEASE_DE_OTRA_EMPRESA")
    """)


def test_cliente_cloud_real_no_descarga_un_lease_de_otra_empresa(monkeypatch):
    from unittest.mock import MagicMock, patch
    monkeypatch.setattr(ae, "_guarda", {"empresa_id": NORTE, "cloud_id": "cloud-norte", "propias": [], "vetadas": []})
    repo, descarga = MagicMock(), MagicMock()
    repo.historial.return_value = []
    def falso(_base, ruta, _token, **_kw):
        return {"envios": [{"envio_id": "e1"}]} if ruta.endswith("pendientes") else {"lease_token": "l", "empresa_id": "cloud-sur", "envio_id": "e1"}
    with patch("atlas_core.cloud_mobile_sync_cliente._json", side_effect=falso), patch("atlas_core.cloud_mobile_sync_cliente._descargar", descarga):
        with pytest.raises(ae.ErrorAislamiento, match="LEASE_DE_OTRA_EMPRESA"):
            from atlas_core.cloud_mobile_sync_cliente import sincronizar_envios_cloud
            sincronizar_envios_cloud(base_url="https://x.test", token_motor="t", consumidor="c", repositorio=repo, timeout=1)
    descarga.assert_not_called()
    repo.recibir.assert_not_called()


# ---------------------------------------------------------- 8. concurrencia
PUBLICAR = """
    from atlas_core import publicacion_reportes as pub
    import csv
    empresa = os.environ["ATLAS_EMPRESA_ID"]
    raiz = Path(os.environ["ATLAS_DATA_DIR"])
    pub.configurar(raiz, modo="rotativo")
    for i in range(12):
        carpeta = pub.ruta_reporte_automatico(raiz, f"rep_{i}")
        carpeta.mkdir(parents=True)
        doc = {"numero_guia": "484176", "numero_transporte": "0000369025", "rut_chofer": empresa, "patente_tracto": "AA1111", "patente_rampla": "No encontrado"}
        with open(carpeta / "viajes.csv", "w", newline="", encoding="utf-8-sig") as h:
            w = csv.writer(h, delimiter=";")
            w.writerow(["numero_transporte", "evidencias_documentos"])
            w.writerow(["0000369025", json.dumps([doc])])
        ap.escribir_estado_operacion(reporte_vigente=carpeta, raiz=raiz)
"""


def test_procesos_simultaneos_de_dos_empresas_no_se_cruzan(mundo):  # noqa: F811
    mbt, a, b = mundo
    antes = _arbol(mbt)
    local = os.environ["LOCALAPPDATA"]
    procesos = [subprocess.Popen([sys.executable, "-c", PRELUDIO + textwrap.dedent(PUBLICAR), str(mbt), str(a.raiz), str(b.raiz), local],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=_entorno(mundo, e), cwd=MOTOR) for e in (NORTE, SUR)]
    for p in procesos:
        _out, err = p.communicate(timeout=180)
        assert p.returncode == 0, err
    assert {r["rut_chofer"] for r in registro.leer_relaciones(a.raiz)} == {NORTE}
    assert {r["rut_chofer"] for r in registro.leer_relaciones(b.raiz)} == {SUR}
    assert _arbol(mbt) == antes


def test_turnos_de_escritura_independientes_entre_empresas_y_exclusivos_dentro(mundo):  # noqa: F811
    _m, a, b = mundo
    ta, tb, otra_a = TurnoEscritura(a.raiz), TurnoEscritura(b.raiz), TurnoEscritura(a.raiz)
    try:
        assert ta.adquirir() and tb.adquirir()
        assert not otra_a.adquirir()
    finally:
        ta.soltar()
        tb.soltar()
        otra_a.soltar()


# ------------------------------------- 8. cambio de computador y recuperación
def _copia_pc(mundo, nombre, tmp_path, monkeypatch, empresa_ctx):  # noqa: F811
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / f"local_{nombre}"))
    return ae.abrir_empresa(tmp_path / nombre / "Unidad" / "Atlas", empresa_ctx.empresa_id, restauracion=True)


def test_cambio_de_computador_casa_oficina_casa(mundo, tmp_path, monkeypatch):  # noqa: F811
    _m, a, b = mundo
    rel = "catalogos_privados/vehiculos.json"
    ap.escribir_json_atomico(a.raiz / rel, {"v": 1})
    ap.escribir_json_atomico(b.raiz / rel, {"v": "sur"})
    antes_b = _arbol(b.raiz)
    with _Nubes() as nubes:
        nube = nubes.por_token["t-a"]
        _sembrar(a, "t-a", tmp_path)
        nube.avanzar(11)
        # OFICINA: Drive todavía vacío, otra letra de unidad y otro LOCALAPPDATA.
        oficina = _copia_pc(mundo, "oficina", tmp_path, monkeypatch, a)
        assert ae.verificar_custodia_cloud(oficina, _cliente("t-a"))["estado"] == "COINCIDE"
        with _lease(oficina, "t-a", "pc-oficina", tmp_path / "lo") as lease:
            assert lease.adquirir(), lease.motivo
            assert ae.confirmar_restauracion(oficina).cloud_id == a.cloud_id
            ap.escribir_json_atomico(oficina.raiz / rel, {"v": 2})
        nube.avanzar(11)
        # De vuelta en CASA, con su copia atrasada y su LOCALAPPDATA.
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
        assert json.loads((a.raiz / rel).read_text(encoding="utf-8")) == {"v": 1}
        with _lease(a, "t-a", "pc-1", tmp_path / "l1") as lease:
            assert lease.adquirir(), lease.motivo
        assert json.loads((a.raiz / rel).read_text(encoding="utf-8")) == {"v": 2}
    assert _arbol(b.raiz) == antes_b
    assert "pc-oficina" in str(nube.lease) or nube.lease["epoca"] >= 3


def test_perdida_total_recupera_cada_empresa_lo_suyo_con_mismo_folio(mundo, tmp_path, monkeypatch):  # noqa: F811
    _m, a, b = mundo
    rel = "operacion/actual/analisis_completo_guias.csv"
    for c in (a, b):
        _escribir(c.raiz / rel, f"archivo;guia;empresa\nx.jpg;{GUIA};{c.empresa_id}\n")
    with _Nubes() as nubes:
        for c, token in ((a, "t-a"), (b, "t-b")):
            _sembrar(c, token, tmp_path)
            nubes.por_token[token].avanzar(11)
        for c, token in ((a, "t-a"), (b, "t-b")):
            nuevo = _copia_pc(mundo, f"nuevo_{token}", tmp_path, monkeypatch, c)
            otro = "t-b" if token == "t-a" else "t-a"
            with pytest.raises(ae.ErrorAislamiento, match="CUSTODIA_AJENA"):
                ae.verificar_custodia_cloud(nuevo, _cliente(otro))
            with _lease(nuevo, token, f"pc-{token}", tmp_path / f"l{token}") as lease:
                assert lease.adquirir(), lease.motivo
            final = ae.confirmar_restauracion(nuevo)
            assert (final.empresa_id, final.cloud_id) == (c.empresa_id, c.cloud_id)
            assert (final.raiz / rel).read_text(encoding="utf-8").strip().endswith(c.empresa_id)
