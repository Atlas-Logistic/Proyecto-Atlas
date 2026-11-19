import hashlib
import json

import pytest

from atlas_core import desktop_operacion as desktop
from atlas_core.ingreso_multiempresa import ErrorIngresoMultiempresa, capacidades, normalizar_solicitud_ingreso, resolver_perfil
from atlas_core.perfiles_documentales import FormatoDocumentalDesconocido
from atlas_core.procesamiento_masivo import procesar_carpeta


def _raiz_mbt(tmp_path):
    raiz = tmp_path / "mbt"
    (raiz / "catalogos_privados").mkdir(parents=True)
    return raiz


def test_capacidades_solo_anuncia_aza_para_mbt_y_nunca_escribe(tmp_path):
    raiz = _raiz_mbt(tmp_path)
    antes = sorted(str(p.relative_to(raiz)) for p in raiz.rglob("*"))
    assert capacidades(raiz, "mbt") == {"empresa_id": "mbt", "perfil_documental": "aza", "perfiles_documentales": ["aza"]}
    assert antes == sorted(str(p.relative_to(raiz)) for p in raiz.rglob("*"))


def test_norte_configurada_no_hereda_aza_y_se_abstiene(tmp_path):
    raiz_mbt = tmp_path / "mbt"
    raiz = tmp_path / "Atlas_empresas" / "norte"
    catalogos = raiz / "catalogos_privados"
    catalogos.mkdir(parents=True)
    (catalogos / "perfil_documental.json").write_text(json.dumps({"empresa_id": "norte", "perfil_documental": "norte-v1"}), encoding="utf-8")
    # El proceso de prueba representa Norte explícitamente sin crear ninguna
    # carpeta al lado de una raíz real de G:.
    import os
    anterior = os.environ.get("ATLAS_EMPRESA_ID")
    os.environ["ATLAS_EMPRESA_ID"] = "norte"
    try:
        assert capacidades(raiz, "norte")["perfiles_documentales"] == []
        with pytest.raises(FormatoDocumentalDesconocido):
            resolver_perfil(raiz, "norte", "norte-v1")
    finally:
        if anterior is None: os.environ.pop("ATLAS_EMPRESA_ID", None)
        else: os.environ["ATLAS_EMPRESA_ID"] = anterior


def test_rechaza_empresa_o_perfil_antes_de_copiar_original(tmp_path):
    raiz = _raiz_mbt(tmp_path)
    original = tmp_path / "sintetica.jpg"
    original.write_bytes(b"original sintetico")
    with pytest.raises(ErrorIngresoMultiempresa):
        desktop.ingresar(raiz, [original], lambda: None, empresa_id="norte", perfil_documental="aza", usuario_recibido="ana")
    with pytest.raises(ErrorIngresoMultiempresa):
        desktop.ingresar(raiz, [original], lambda: None, empresa_id="mbt", perfil_documental="otro", usuario_recibido="ana")
    assert original.read_bytes() == b"original sintetico"
    assert not (raiz / "operacion").exists()


def test_normaliza_solo_el_sobre_antiguo_mbt_completamente_ausente(tmp_path):
    mbt = _raiz_mbt(tmp_path)
    assert normalizar_solicitud_ingreso(mbt, None, None) == ("mbt", "aza")
    for empresa, perfil in (("", "aza"), ("mbt", ""), (None, "aza"), ("mbt", None)):
        with pytest.raises(ErrorIngresoMultiempresa):
            normalizar_solicitud_ingreso(mbt, empresa, perfil)
    with pytest.raises(ErrorIngresoMultiempresa, match="EMPRESA_NO_AUTORIZADA"):
        resolver_perfil(mbt, *normalizar_solicitud_ingreso(mbt, "norte", "aza"))

    norte = tmp_path / "Atlas_empresas" / "norte"
    (norte / "catalogos_privados").mkdir(parents=True)
    with pytest.raises(ErrorIngresoMultiempresa, match="OBLIGATORIA"):
        normalizar_solicitud_ingreso(norte, None, None)


def test_ingreso_mbt_antiguo_audita_huella_usuario_y_propaga_aza(monkeypatch, tmp_path):
    raiz = _raiz_mbt(tmp_path)
    original = tmp_path / "sintetica.jpg"
    original.write_bytes(b"original sintetico")
    llamadas = []
    def cli(args, entrada=None):
        llamadas.append(args)
        if args[1] == "snapshot":
            return ""
        if args[1] == "resumen":
            return "[]"
        if args[0] == "analizar_guias_masivo.py":
            dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
            dataset.parent.mkdir(parents=True, exist_ok=True)
            dataset.write_text("archivo;estado_procesamiento;error\n", encoding="utf-8-sig")
        if args[0] == "generar_reporte_viajes.py":
            reporte = raiz / "reportes" / "actual"
            (reporte / "viajes.csv").parent.mkdir(parents=True, exist_ok=True)
            (reporte / "viajes.csv").write_text("x", encoding="utf-8")
        return ""
    monkeypatch.setattr(desktop, "_cli", cli)
    monkeypatch.setattr(desktop, "leer_estado_operacion", lambda **_: {"reporte_vigente": "reportes/actual"})
    monkeypatch.setattr("atlas_core.fuente_catalogos.validar_fuente_catalogos", lambda *_: None)
    # Desktop anterior no envía empresa ni perfil; en proceso MBT ambos se
    # normalizan juntos, sin aceptar ninguna ausencia parcial.
    respuesta = desktop.ingresar(raiz, [original], lambda: None, usuario_recibido={"id": "ana"})
    auditoria = next((raiz / "operacion" / "entradas").glob("*/_ingreso_multiempresa.json"))
    contenido = json.loads(auditoria.read_text(encoding="utf-8"))
    assert contenido["usuario_verificado_por_motor"] is False
    assert contenido["originales"][0]["sha256"] == hashlib.sha256(original.read_bytes()).hexdigest()
    assert any("--perfil-documental" in args and args[args.index("--perfil-documental") + 1] == "aza" for args in llamadas)
    assert respuesta["ok"] is True


def test_ingreso_mbt_nuevo_explicito_sigue_siendovalido(tmp_path):
    raiz = _raiz_mbt(tmp_path)
    assert resolver_perfil(raiz, *normalizar_solicitud_ingreso(raiz, "mbt", "aza")) is not None


def test_fallo_tecnico_conserva_original_y_no_declara_exito(monkeypatch, tmp_path):
    raiz = _raiz_mbt(tmp_path)
    original = tmp_path / "sintetica.jpg"
    original.write_bytes(b"original sintetico")
    monkeypatch.setattr("atlas_core.fuente_catalogos.validar_fuente_catalogos", lambda *_: None)
    monkeypatch.setattr(desktop, "_cli", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("OCR caído")))
    with pytest.raises(RuntimeError, match="OCR caído"):
        desktop.ingresar(raiz, [original], lambda: None, empresa_id="mbt", perfil_documental="aza")
    copia = next((raiz / "operacion" / "entradas").glob("*/sintetica.jpg"))
    assert original.read_bytes() == copia.read_bytes() == b"original sintetico"


def test_procesar_carpeta_propaga_perfil_a_cada_guia(tmp_path):
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    (entrada / "a.jpg").write_bytes(b"a")
    perfil = object()
    recibidos = []
    import atlas_core.procesamiento_masivo as pm
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(pm, "procesar_archivo", lambda ruta, **kw: recibidos.append(kw["perfil_documental"]) or {"numero_guia": "1"})
    try:
        procesar_carpeta(entrada, tmp_path / "salida.csv", perfil_documental=perfil, lector_ocr=object(), orquestador_ia=object())
    finally:
        monkeypatch.undo()
    assert recibidos == [perfil]
