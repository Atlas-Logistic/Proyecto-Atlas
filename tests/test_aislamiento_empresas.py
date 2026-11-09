"""Aislamiento entre empresas con dos empresas sintéticas y código real del Motor."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

import atlas_core.aislamiento_empresas as ae
import atlas_core.registro_relaciones_operacionales as registro
from atlas_core import almacenamiento_portable as ap
from atlas_core import escritor_operativo as eo
from atlas_core import estado_confirmado as ec
from atlas_core import exclusion_local as el
from atlas_core import publicacion_reportes as pub
from atlas_core import revalidacion_documental as rd
from tests.test_estado_confirmado import CloudFalsa

MOTOR = Path(__file__).resolve().parents[1]
GUIA = "484176"  # mismo folio en ambas empresas: la colisión realista


def _arbol(raiz: Path) -> dict[str, str]:
    return {p.relative_to(raiz).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(raiz.rglob("*")) if p.is_file()}


def _escribir(ruta: Path, texto: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding="utf-8")


@pytest.fixture
def mundo(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("ATLAS_CACHE_DIR", str(tmp_path / "cache_pruebas"))
    mbt = tmp_path / "Mi unidad" / "Atlas"
    _escribir(mbt / "catalogos_privados" / "choferes.json", '{"chofer": "MBT"}')
    _escribir(mbt / "operacion" / "actual" / "analisis_completo_guias.csv", f"archivo;guia\nmbt.jpg;{GUIA}\n")
    a = ae.inicializar_empresa(mbt, "transportes-norte", nombre="Norte", cloud_id="cloud-norte")
    b = ae.inicializar_empresa(mbt, "transportes-sur", nombre="Sur", cloud_id="cloud-sur")
    return mbt, a, b


# ------------------------------------------------------------ MBT intacta
def test_mbt_conserva_raiz_rutas_y_no_recibe_escrituras(mundo):
    mbt, _a, _b = mundo
    antes = _arbol(mbt)
    c = ae.abrir_empresa(mbt, ae.EMPRESA_MBT)
    assert c.raiz == mbt and c.es_mbt
    assert (c.cloud_id, c.registro_id) == ("empresa-prueba-javier", "oficina")
    assert c.operacion("actual") == ap.ruta_operacion("actual", raiz=mbt)
    assert c.catalogos() == ap.ruta_catalogos_privados(raiz=mbt)
    assert c.reportes() == ap.ruta_reportes(raiz=mbt)
    assert c.respaldos() == ap.ruta_respaldos(raiz=mbt)
    assert c.carpeta_custodia() == ec.ruta_local()
    assert set(c.entorno()) == {"ATLAS_DATA_DIR", "ATLAS_EMPRESA_ID", "ATLAS_RAIZ_MBT"}
    assert _arbol(mbt) == antes and not (mbt / ae.RUTA_MARCA).exists()


def test_sin_variable_de_empresa_el_entorno_es_mbt(mundo, monkeypatch):
    mbt, _a, _b = mundo
    monkeypatch.setenv("ATLAS_DATA_DIR", str(mbt))
    monkeypatch.delenv(ae.VARIABLE_EMPRESA, raising=False)
    assert ae.contexto_desde_entorno().empresa_id == ae.EMPRESA_MBT


# --------------------------------------------------------------- identidad
@pytest.mark.parametrize("valor", ["", "A", "mbt", "oficina", "empresa-prueba-javier", "Norte", "con", "lpt1", "a/b",
                                   "..", "x", "nor_te", "norte-", "ñandu", None])
def test_identificadores_invalidos_o_reservados(valor):
    with pytest.raises(ae.ErrorAislamiento):
        ae.validar_empresa_id(valor)


def test_alta_idempotente_y_sin_redefinir(mundo):
    mbt, a, _b = mundo
    assert ae.inicializar_empresa(mbt, a.empresa_id, nombre="Norte", cloud_id="cloud-norte") == a
    with pytest.raises(ae.ErrorAislamiento, match="EMPRESA_YA_DEFINIDA"):
        ae.inicializar_empresa(mbt, a.empresa_id, nombre="Norte", cloud_id="otro")
    assert ae.listar_empresas(mbt) == ["mbt", "transportes-norte", "transportes-sur"]


@pytest.mark.parametrize("cloud", ["cloud-norte", "empresa-prueba-javier", " "])
def test_cloud_id_no_se_comparte(mundo, cloud):
    mbt, _a, _b = mundo
    with pytest.raises(ae.ErrorAislamiento):
        ae.inicializar_empresa(mbt, "tercera", nombre="X", cloud_id=cloud)


def test_no_adopta_carpeta_con_datos_sin_marca(mundo):
    mbt, a, _b = mundo
    _escribir(a.raiz.parent / "huerfana" / "x.txt", "x")
    with pytest.raises(ae.ErrorAislamiento, match="RAIZ_CON_DATOS_SIN_MARCA"):
        ae.inicializar_empresa(mbt, "huerfana", nombre="H", cloud_id="c-h")


def test_abrir_exige_marca_propia(mundo):
    mbt, a, b = mundo
    with pytest.raises(ae.ErrorAislamiento, match="EMPRESA_INEXISTENTE"):
        ae.abrir_empresa(mbt, "no-existe")
    shutil.copy2(a.raiz / ae.RUTA_MARCA, b.raiz / ae.RUTA_MARCA)
    with pytest.raises(ae.ErrorAislamiento, match="RAIZ_DE_OTRA_EMPRESA"):
        ae.abrir_empresa(mbt, b.empresa_id)
    (b.raiz / ae.RUTA_MARCA).write_text("{roto", encoding="utf-8")
    with pytest.raises(ae.ErrorAislamiento, match="MARCA_ILEGIBLE"):
        ae.abrir_empresa(mbt, b.empresa_id)


def test_mbt_rechaza_una_raiz_marcada(mundo):
    _mbt, a, _b = mundo
    otra = a.raiz.parent.parent / "Atlas2"
    shutil.copytree(a.raiz, otra)
    with pytest.raises(ae.ErrorAislamiento, match="RAIZ_DE_OTRA_EMPRESA"):
        ae.abrir_empresa(otra, ae.EMPRESA_MBT)


def test_raiz_de_empresa_no_sirve_como_mbt(mundo):
    _mbt, a, _b = mundo
    with pytest.raises(ae.ErrorAislamiento, match="RAIZ_MBT_INVALIDA"):
        ae.abrir_empresa(a.raiz, ae.EMPRESA_MBT)


def test_entorno_cruzado_se_rechaza(mundo, monkeypatch):
    _mbt, a, b = mundo
    monkeypatch.setenv("ATLAS_DATA_DIR", str(b.raiz))
    monkeypatch.setenv(ae.VARIABLE_EMPRESA, a.empresa_id)
    monkeypatch.setenv(ae.VARIABLE_RAIZ_MBT, str(a.raiz_mbt))
    with pytest.raises(ae.ErrorAislamiento, match="RAIZ_DE_OTRA_EMPRESA"):
        ae.contexto_desde_entorno()
    for k, v in a.entorno().items():
        monkeypatch.setenv(k, v)
    assert ae.contexto_desde_entorno() == a


def test_portable_a_otra_unidad(mundo, tmp_path):
    mbt, a, _b = mundo
    destino = tmp_path / "otra letra" / "My Drive"
    destino.mkdir(parents=True)
    shutil.copytree(mbt, destino / "Atlas")
    shutil.copytree(a.raiz.parent, destino / ae.CARPETA_EMPRESAS)
    c = ae.abrir_empresa(destino / "Atlas", a.empresa_id)
    assert (c.empresa_id, c.cloud_id) == (a.empresa_id, a.cloud_id) and c.raiz != a.raiz
    assert str(tmp_path) not in (c.raiz / ae.RUTA_MARCA).read_text(encoding="utf-8")


# ------------------------------------------------------------------- rutas
def test_rutas_no_salen_de_la_empresa(mundo):
    mbt, a, b = mundo
    assert a.ruta("operacion/actual/x.json") == a.raiz / "operacion" / "actual" / "x.json"
    for mala in ("../transportes-sur/x", "../../Atlas/x", str(b.raiz / "x"), "C:/x"):
        with pytest.raises(ae.ErrorAislamiento, match="RUTA_FUERA_DE_EMPRESA"):
            a.ruta(mala)
    for ajena in (b.raiz / "x", mbt / "x"):
        with pytest.raises(ae.ErrorAislamiento):
            a.exigir_propia(ajena)


def _junction(enlace: Path, destino: Path) -> None:
    salida = subprocess.run(["cmd", "/c", "mklink", "/J", str(enlace), str(destino)], capture_output=True)
    if salida.returncode:
        pytest.skip("no se pudo crear el enlace")


@pytest.mark.skipif(os.name != "nt", reason="junction de Windows")
def test_raiz_enlazada_a_otra_empresa_se_rechaza(mundo):
    mbt, a, b = mundo
    _junction(a.raiz.parent / "impostora", b.raiz)
    with pytest.raises(ae.ErrorAislamiento, match="RAIZ_ENLAZADA"):
        ae.abrir_empresa(mbt, "impostora")


def test_estado_local_separado(mundo):
    mbt, a, b = mundo
    c_mbt = ae.abrir_empresa(mbt, ae.EMPRESA_MBT)
    assert len({a.carpeta_custodia(), b.carpeta_custodia(), c_mbt.carpeta_custodia()}) == 3
    assert a.entorno()["ATLAS_CACHE_DIR"] != b.entorno()["ATLAS_CACHE_DIR"]
    assert len({el.ruta_turno(a.raiz), el.ruta_turno(b.raiz), el.ruta_turno(mbt)}) == 3


# ------------------------------------------------- Motor real, mismo folio
def _publicar(raiz: Path, nombre: str, chofer: str, tracto: str) -> Path:
    carpeta = pub.ruta_reporte_automatico(raiz, nombre)
    carpeta.mkdir(parents=True)
    doc = {"numero_guia": GUIA, "numero_transporte": "0000369025", "rut_chofer": chofer,
           "patente_tracto": tracto, "patente_rampla": "No encontrado"}
    with open(carpeta / "viajes.csv", "w", newline="", encoding="utf-8-sig") as h:
        w = csv.writer(h, delimiter=";")
        w.writerow(["numero_transporte", "evidencias_documentos"])
        w.writerow(["0000369025", json.dumps([doc])])
    ap.escribir_estado_operacion(reporte_vigente=carpeta, raiz=raiz)
    return carpeta


def _choferes(relaciones) -> set[str]:
    return {r["rut_chofer"] for r in relaciones}


def test_mismo_folio_no_se_mezcla_en_publicacion_registro_y_lector(mundo):
    mbt, a, b = mundo
    antes_mbt = _arbol(mbt)
    for c in (a, b):
        pub.configurar(c.raiz, modo="rotativo")
    va = _publicar(a.raiz, "reporte_a", "11111111-1", "AAAA11")
    antes_b = _arbol(b.raiz)
    assert pub.ruta_reporte_automatico(a.raiz, "x").is_relative_to(a.raiz)
    vb = _publicar(b.raiz, "reporte_b", "22222222-2", "BBBB22")

    assert ap.leer_estado_operacion(raiz=a.raiz)["reporte_vigente"].endswith("reporte_a")
    assert ap.leer_estado_operacion(raiz=b.raiz)["reporte_vigente"].endswith("reporte_b")
    assert _choferes(registro.leer_relaciones(a.raiz)) == {"11111111-1"}
    assert _choferes(registro.leer_relaciones(b.raiz)) == {"22222222-2"}
    assert va.is_relative_to(a.raiz) and vb.is_relative_to(b.raiz)
    assert not set(antes_b) - set(_arbol(b.raiz))  # A no borró nada de B
    assert _arbol(mbt) == antes_mbt
    assert _choferes(rd._relaciones_historicas_operacionales(a.raiz)) == {"11111111-1"}
    assert _choferes(rd._relaciones_historicas_operacionales(b.raiz)) == {"22222222-2"}


def test_poda_rotativa_de_una_empresa_no_afecta_a_otra(mundo):
    _mbt, a, b = mundo
    for c in (a, b):
        pub.configurar(c.raiz, modo="rotativo")
    _publicar(b.raiz, "reporte_b", "22222222-2", "BBBB22")
    antes = _arbol(b.raiz)
    for i in range(6):
        _publicar(a.raiz, f"reporte_a{i}", "11111111-1", "AAAA11")
    pub.podar_vigentes(a.raiz)
    assert _arbol(b.raiz) == antes


@pytest.mark.parametrize("catalogo", ["choferes", "clientes", "vehiculos", "destinos"])
def test_catalogos_y_documentos_separados(mundo, catalogo):
    mbt, a, b = mundo
    antes_b, antes_mbt = _arbol(b.raiz), _arbol(mbt)
    ap.escribir_json_atomico(a.catalogos() / f"{catalogo}.json", {"de": a.empresa_id})
    _escribir(a.operacion("mobile/envios/e1") / "original.jpg", "foto-a")
    assert _arbol(b.raiz) == antes_b and _arbol(mbt) == antes_mbt
    assert not (b.catalogos() / f"{catalogo}.json").exists()


# ------------------------------------------------------- custodia Cloud real
class _Nubes:
    """Una CloudFalsa por token: la misma separación que un empresa_id por token."""

    def __init__(self):
        self.por_token = {"t-a": CloudFalsa(), "t-b": CloudFalsa(), "t-mbt": CloudFalsa()}

    def json(self, base, ruta, token, **kw):
        return self.por_token[token].json(base, ruta, token, **kw)

    def crudo(self, cliente, huella, **kw):
        return self.por_token[cliente.token_motor].crudo(cliente, huella, **kw)

    def __enter__(self):
        self._p = [patch("atlas_core.escritor_operativo._json", side_effect=self.json),
                   patch.object(ec.ClienteEstado, "_crudo", lambda c, h, **kw: self.crudo(c, h, **kw))]
        for p in self._p:
            p.start()
        return self

    def __exit__(self, *_):
        for p in self._p:
            p.stop()
        ec._activas.clear()


def _cliente(token):
    return ec.ClienteEstado("https://cloud.test", token, 5)


def _lease(c: ae.ContextoEmpresa, token: str, equipo: str, local: Path) -> eo.LeaseEscritorOperativo:
    lease = eo.LeaseEscritorOperativo(base_url="https://cloud.test", token_motor=token, escritor_id=equipo,
                                      heartbeat_segundos=0, margen_relevo_segundos=0, ruta_relevo=local / "relevo.json")
    lease.custodia = ec.CustodiaEstado(c.raiz, _cliente(token), carpeta_local=c.carpeta_custodia())
    return lease


def _rutas_cloud(nube: CloudFalsa) -> set[str]:
    return set(nube._vigentes())


def test_turnos_simultaneos_custodian_cada_empresa_por_separado(mundo, tmp_path):
    mbt, a, b = mundo
    c_mbt = ae.abrir_empresa(mbt, ae.EMPRESA_MBT)
    rel = "catalogos_privados/choferes.json"
    with _Nubes() as nubes:
        with _lease(a, "t-a", "pc", tmp_path / "la") as la, _lease(b, "t-b", "pc", tmp_path / "lb") as lb, \
                _lease(c_mbt, "t-mbt", "pc", tmp_path / "lm") as lm:
            assert la.adquirir() and lb.adquirir() and lm.adquirir()
            assert not la.custodia.contiene(b.raiz / rel) and not lm.custodia.contiene(a.raiz / rel)
            ap.escribir_json_atomico(a.raiz / rel, {"de": "a"})
            ap.escribir_json_atomico(b.raiz / rel, {"de": "b"})
            ap.escribir_json_atomico(mbt / rel, {"de": "mbt"})
        por = nubes.por_token
        contenidos = {t: json.loads(n.objetos[dict((r, s) for r, _v, s in n.archivos)[rel]])["de"] for t, n in por.items()}
    assert contenidos == {"t-a": "a", "t-b": "b", "t-mbt": "mbt"}
    assert all(not r.startswith(ae.CARPETA_EMPRESAS) for n in por.values() for r in _rutas_cloud(n))


def _sembrar(c, token, tmp_path):
    with _lease(c, token, "pc-1", tmp_path / "l1") as lease:
        assert lease.adquirir(), lease.motivo
        lease.custodia.sembrar(lease)


def test_recuperacion_desde_cloud_en_equipo_nuevo_sin_tocar_a_mbt(mundo, tmp_path, monkeypatch):
    mbt, a, b = mundo
    ap.escribir_json_atomico(a.catalogos() / "vehiculos.json", {"de": "a"})
    ap.escribir_json_atomico(b.catalogos() / "vehiculos.json", {"de": "b"})
    with _Nubes() as nubes:
        _sembrar(a, "t-a", tmp_path)
        _sembrar(b, "t-b", tmp_path)
        assert ae.RUTA_MARCA in _rutas_cloud(nubes.por_token["t-a"])

        nubes.por_token["t-a"].avanzar(11)  # vence la prioridad del último escritor
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local_nuevo"))
        mbt_nueva = tmp_path / "pc2" / "Atlas"
        _escribir(mbt_nueva / "catalogos_privados" / "choferes.json", "{}")
        antes = _arbol(mbt_nueva)
        c = ae.abrir_empresa(mbt_nueva, a.empresa_id, restauracion=True)
        assert ae.verificar_custodia_cloud(c, _cliente("t-a"))["estado"] == "COINCIDE"
        with _lease(c, "t-a", "pc-2", tmp_path / "l2") as lease:
            assert lease.adquirir(), lease.motivo
        final = ae.confirmar_restauracion(c)
    assert (final.empresa_id, final.cloud_id) == (a.empresa_id, a.cloud_id)
    assert json.loads((final.catalogos() / "vehiculos.json").read_text(encoding="utf-8")) == {"de": "a"}
    assert _arbol(mbt_nueva) == antes and ae.listar_empresas(mbt_nueva) == ["mbt", a.empresa_id]
    assert mbt.is_dir()


def test_restauracion_sin_marca_no_se_confirma(mundo, tmp_path):
    _mbt, a, _b = mundo
    c = ae.abrir_empresa(tmp_path / "pc3" / "Atlas", a.empresa_id, restauracion=True)
    with pytest.raises(ae.ErrorAislamiento, match="EMPRESA_SIN_MARCA"):
        ae.confirmar_restauracion(c)


@pytest.mark.parametrize("token, empresa", [("t-a", "b"), ("t-mbt", "b"), ("t-a", "mbt")])
def test_token_de_otra_empresa_se_detecta_antes_de_restaurar(mundo, tmp_path, token, empresa):
    mbt, a, b = mundo
    c_mbt = ae.abrir_empresa(mbt, ae.EMPRESA_MBT)
    with _Nubes():
        _sembrar(a, "t-a", tmp_path)
        _sembrar(c_mbt, "t-mbt", tmp_path)
        objetivo = {"b": b, "mbt": c_mbt}[empresa]
        antes = _arbol(objetivo.raiz)
        with pytest.raises(ae.ErrorAislamiento, match="CUSTODIA_AJENA"):
            ae.verificar_custodia_cloud(objetivo, _cliente(token))
        assert _arbol(objetivo.raiz) == antes


def test_custodia_vacia_y_marca_alterada(mundo, tmp_path):
    _mbt, a, b = mundo
    with _Nubes() as nubes:
        assert ae.verificar_custodia_cloud(b, _cliente("t-b"))["estado"] == "VACIA"
        _sembrar(a, "t-a", tmp_path)
        nube = nubes.por_token["t-a"]
        huella = dict((r, s) for r, _v, s in nube.archivos)[ae.RUTA_MARCA]
        nube.objetos[huella] = b"alterado"
        (a.raiz / ae.RUTA_MARCA).unlink()  # recuperación: hay que descargarla
        with pytest.raises(ae.ErrorAislamiento, match="CUSTODIA_NO_VERIFICABLE"):
            ae.verificar_custodia_cloud(a, _cliente("t-a"))


# ------------------------------------------------ guarda (proceso separado)
def _en_proceso(mundo, empresa: str, cuerpo: str):
    mbt, a, b = mundo
    guion = textwrap.dedent("""\
        import os, sys, json, pathlib
        import atlas_core.aislamiento_empresas as ae
        from atlas_core import almacenamiento_portable as ap
        mbt, a, b = [pathlib.Path(p) for p in sys.argv[1:4]]
        c = ae.abrir_empresa(mbt, sys.argv[4])
        ae.activar_guarda(c)
        def vetado(f):
            try:
                f()
            except ae.ErrorAislamiento as e:
                assert e.codigo == "ACCESO_ENTRE_EMPRESAS", e.codigo
                return
            raise SystemExit("NO VETADO: " + f.__doc__ if f.__doc__ else "NO VETADO")
        """) + textwrap.dedent(cuerpo)
    env = {**os.environ, "PYTHONPATH": str(MOTOR)}
    r = subprocess.run([sys.executable, "-c", guion, str(mbt), str(a.raiz), str(b.raiz), empresa],
                       capture_output=True, text=True, env=env, cwd=MOTOR, timeout=120)
    assert r.returncode == 0, r.stderr + r.stdout


def test_guarda_veta_lectura_escritura_listado_y_motor(mundo):
    mundo[1].catalogos().joinpath("propio.json").write_text("{}", encoding="utf-8")
    antes = _arbol(mundo[2].raiz), _arbol(mundo[0])
    _en_proceso(mundo, "transportes-norte", """
        m = b / "catalogos_privados" / "empresa_identidad.json"
        vetado(lambda: open(m).read())
        vetado(lambda: open(b / "z.txt", "w"))
        vetado(lambda: os.listdir(b))
        vetado(lambda: list(os.scandir(b.parent)))
        vetado(lambda: os.remove(m))
        vetado(lambda: os.rename(a / "catalogos_privados" / "propio.json", b / "robado.json"))
        vetado(lambda: open(mbt / "catalogos_privados" / "choferes.json").read())
        vetado(lambda: ap.leer_estado_operacion(raiz=b) or ap.escribir_json_atomico(b / "y.json", {}))
        (a / "ok.txt").write_text("ok")
        assert (a / "ok.txt").read_text() == "ok"
        assert json.loads((a / "catalogos_privados" / "propio.json").read_text()) == {}
    """)
    assert (_arbol(mundo[2].raiz), _arbol(mundo[0])) == antes


def test_guarda_mbt_no_entra_a_otras_empresas_y_usa_lo_suyo(mundo):
    _en_proceso(mundo, "mbt", """
        vetado(lambda: open(a / "catalogos_privados" / "empresa_identidad.json").read())
        vetado(lambda: os.listdir(a.parent))
        assert json.loads((mbt / "catalogos_privados" / "choferes.json").read_text()) == {"chofer": "MBT"}
    """)


def test_un_proceso_una_empresa(mundo):
    _en_proceso(mundo, "transportes-norte", """
        ae.activar_guarda(c)  # idempotente
        otra = ae.ContextoEmpresa("transportes-sur", b, mbt, "x", "transportes-sur")
        try:
            ae.activar_guarda(otra)
        except ae.ErrorAislamiento as e:
            assert e.codigo == "PROCESO_DE_OTRA_EMPRESA"
        else:
            raise SystemExit("segunda empresa aceptada")
    """)


@pytest.mark.skipif(os.name != "nt", reason="junction de Windows")
def test_guarda_no_se_elude_con_enlace_dentro_de_la_raiz_propia(mundo):
    mbt, a, b = mundo
    _junction(a.raiz / "atajo", b.raiz)
    _en_proceso(mundo, "transportes-norte", """
        vetado(lambda: open(a / "atajo" / "catalogos_privados" / "empresa_identidad.json").read())
    """)


def test_el_error_de_aislamiento_no_es_oserror():
    assert not issubclass(ae.ErrorAislamiento, OSError)
