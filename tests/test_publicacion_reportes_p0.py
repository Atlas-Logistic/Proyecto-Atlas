"""Publicación rotativa del reporte vigente: sin snapshot permanente por cambio."""
from __future__ import annotations

import csv
import json

import pytest

from atlas_core import mobile
from atlas_core import publicacion_reportes as pub
from atlas_core import registro_relaciones_operacionales as registro
from atlas_core import revalidacion_documental as rd
from atlas_core.almacenamiento_portable import escribir_estado_operacion, leer_estado_operacion
from atlas_core.aplicacion_decisiones import aplicar_decision_obra
from atlas_core.revalidacion_documental import _leer_filas
from tests.test_decision_alcance_focal_p0 import preparar


@pytest.fixture(autouse=True)
def _proceso_nuevo():
    """Cada prueba empieza como un proceso nuevo (sin capturas propias)."""
    pub._CAPTURADAS_EN_PROCESO.clear()
    yield
    pub._CAPTURADAS_EN_PROCESO.clear()


def _snapshots(raiz):
    """Snapshots permanentes: lo que el lector histórico recorre y nunca se borra."""
    return sorted(p.parent.name for p in (raiz / "reportes").glob("*/viajes.csv"))


def _rotativos(raiz):
    return sorted(p.parent.name for p in (raiz / "reportes" / "vigentes").glob("*/viajes.csv"))


def _claves(relaciones):
    return {tuple(str(r.get(k, "")).strip() for k in registro.CAMPOS) for r in relaciones}


def _reporte(directorio, evidencias):
    directorio.mkdir(parents=True)
    with (directorio / "viajes.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["numero_transporte", "evidencias_documentos"], delimiter=";")
        w.writeheader()
        w.writerow({"numero_transporte": "1", "evidencias_documentos": json.dumps(evidencias)})
    return directorio


def _rel(guia, patente="AA1111", transporte="0000990001"):
    return {"numero_guia": guia, "numero_transporte": transporte, "rut_chofer": "11111111-1",
            "patente_tracto": patente, "patente_rampla": ""}


def _publicar(raiz, nombre, evidencias):
    """Un productor automático: ruta según modo + publicación del vigente."""
    salida = _reporte(pub.ruta_reporte_automatico(raiz, nombre), evidencias)
    escribir_estado_operacion(reporte_vigente=salida, raiz=raiz)
    return salida


# --- Medición en escenarios equivalentes con productores reales ---------------

def _escenario_real(tmp_path, monkeypatch, modo, ingresos):
    monkeypatch.setenv("ATLAS_IA_B1_OPERACIONAL", "0")
    raiz, actual, decision, _ajenas = preparar(tmp_path / modo)
    historicos_antes = {p: p.read_bytes() for p in (raiz / "reportes").rglob("*") if p.is_file()}
    if modo == pub.MODO_ROTATIVO:
        pub.configurar(raiz, modo=pub.MODO_ROTATIVO, conservar=2)
    dataset = actual / "analisis_completo_guias.csv"
    base = _leer_filas(dataset)[3]
    # 1) Una revalidación por decisión humana (productor reporte_revalidacion_*).
    assert aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR")["ok"]
    # 2) Varios ingresos Mobile reales con OCR simulado (productor reporte_mobile_*).
    repo = mobile.RepositorioEnviosMobile(raiz)
    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda *a, **kw: object())
    for indice in range(ingresos):
        envio = f"ingreso-{indice}"
        repo.recibir(envio_id=envio, imagen=b"foto-sintetica", mime="image/jpeg",
                     metadata={"chofer_id": "TEST", "planta_origen_informada": "AZA_COLINA"})
        fila = dict(archivo=f"mobile/{envio}/original.jpg", numero_guia=f"90000{indice}",
                    numero_transporte=f"000099000{indice}", cliente=base["cliente"], obra_destino=base["obra_destino"],
                    rut_chofer="11111111-1", chofer=base.get("chofer", ""), patente_tracto=f"ZZ{indice}{indice}11",
                    estado_procesamiento="OK", indicador_revision="OK", estado_documental="OK",
                    estado_operacional="OK", motivos_revision_documento="", estado_ruta="SIN_CREDENCIAL",
                    motivo_ruta="SIN_CREDENCIAL")
        monkeypatch.setattr(mobile, "procesar_archivo", lambda *a, _f=fila, **kw: dict(_f))
        salida = mobile.procesar_y_revalidar_envio_mobile(
            repo, envio, dataset=dataset, carpeta_catalogos=raiz / "catalogos_privados")
        assert salida == {"procesamiento_ok": True, "reconciliacion_ok": True}
    # 3) Dos revalidaciones globales posteriores (productor reporte_revalidacion_*).
    for indice in range(2):
        rd.revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte=f"reporte_revalidacion_global_{indice}")
    historicos_despues = {p: p.read_bytes() for p in historicos_antes}
    return raiz, actual, historicos_antes, historicos_despues


def _viajes_vigentes(raiz):
    estado = leer_estado_operacion(raiz=raiz)
    with (raiz / estado["reporte_vigente"] / "viajes.csv").open(encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f, delimiter=";"))
    salida = []
    for fila in filas:
        fila = {k: v for k, v in fila.items() if "fecha_creacion" not in k and "fecha_ingesta" not in k}
        # Tiempos de procesamiento medidos en cada corrida: no dependen del modo.
        evidencias = json.loads(fila["evidencias_documentos"])
        for evidencia in evidencias:
            evidencia.pop("metricas_procesamiento_json", None)
        fila["evidencias_documentos"] = evidencias
        salida.append(fila)
    return salida


def test_medicion_snapshots_antes_y_despues_con_mobile_y_revalidacion(tmp_path, monkeypatch, capsys):
    ingresos = 4
    raiz_a, actual_a, *_ = _escenario_real(tmp_path, monkeypatch, pub.MODO_SNAPSHOTS, ingresos)
    raiz_b, actual_b, hist_antes, hist_despues = _escenario_real(tmp_path, monkeypatch, pub.MODO_ROTATIVO, ingresos)

    antes, despues = _snapshots(raiz_a), _snapshots(raiz_b)
    with capsys.disabled():
        print(f"\n[MEDICION] snapshots permanentes: antes={len(antes)} despues={len(despues)} "
              f"rotativos_vivos={len(_rotativos(raiz_b))} (decision + {ingresos} ingresos Mobile + 2 revalidaciones globales)")
    assert len(antes) >= ingresos + 1  # una carpeta completa por publicación
    assert despues == []               # ninguna permanente nueva
    # Todo ocurrió en un mismo proceso: nada capturado aquí se poda todavía
    # (su segmento no está confirmado en Cloud). El siguiente proceso (próximo
    # ciclo de PULL) poda hasta conservar 2.
    assert pub._CAPTURADAS_EN_PROCESO
    pub._CAPTURADAS_EN_PROCESO.clear()
    pub.podar_vigentes(raiz_b)
    assert len(_rotativos(raiz_b)) <= 2
    assert hist_despues == hist_antes  # nada previo tocado
    # Modo por defecto sin migración: catalogos_privados (custodiado) sin registro.
    assert not registro.ruta_registro(raiz_a).exists()

    # Mismo resultado operacional: reporte vigente, dataset, bandeja y ledger.
    assert _viajes_vigentes(raiz_b) == _viajes_vigentes(raiz_a)
    for nombre in ("decisiones_pendientes.json", "decisiones_aplicadas.json"):
        a = json.loads((actual_a / nombre).read_text(encoding="utf-8"))
        b = json.loads((actual_b / nombre).read_text(encoding="utf-8"))
        assert len(a.get("decisiones", a.get("aplicaciones", []))) == len(b.get("decisiones", b.get("aplicaciones", [])))
    assert len(_leer_filas(actual_b / "analisis_completo_guias.csv")) == len(_leer_filas(actual_a / "analisis_completo_guias.csv"))
    vigente = leer_estado_operacion(raiz=raiz_b)["reporte_vigente"]
    assert vigente.startswith("reportes/vigentes/reporte_") and (raiz_b / vigente / "viajes.csv").is_file()
    assert leer_estado_operacion(raiz=raiz_a)["reporte_vigente"] == vigente.replace("reportes/vigentes/", "reportes/")

    # El lector histórico recibe exactamente la misma evidencia en ambos modos.
    assert _claves(rd._relaciones_historicas_operacionales(raiz_b)) == _claves(rd._relaciones_historicas_operacionales(raiz_a))
    guias = {c[0] for c in _claves(rd._relaciones_historicas_operacionales(raiz_b))}
    assert {f"90000{i}" for i in range(ingresos)} <= guias
    # Una sola fuente por relación aunque se haya publicado varias veces.
    contenido = registro.contenido_vigente(raiz_b)
    for entrada in contenido["empresas"]["oficina"]["relaciones"]:
        tipos = [f["tipo"] for f in entrada["fuentes"]]
        assert tipos.count(registro.TIPO_PUBLICADO) <= 1
        assert entrada["confirmaciones_humanas"] == []


# --- Configuración, reversión y salvaguardas ------------------------------------

def test_sin_configuracion_o_invalida_se_conservan_los_snapshots(tmp_path):
    raiz = tmp_path / "Atlas"
    assert pub.ruta_reporte_automatico(raiz, "reporte_mobile_x") == raiz / "reportes" / "reporte_mobile_x"
    pub.ruta_configuracion(raiz).parent.mkdir(parents=True)
    for contenido in ("{roto", '{"modo": "otro"}', '{"modo": "rotativo", "conservar": 0}'):
        pub.ruta_configuracion(raiz).write_text(contenido, encoding="utf-8")
        assert pub.modo_efectivo(raiz) == pub.MODO_SNAPSHOTS
    with pytest.raises(ValueError):
        pub.ruta_reporte_automatico(raiz, "vigentes")


def test_registro_ilegible_impide_rotativo_y_vuelve_a_snapshots(tmp_path):
    raiz = tmp_path / "Atlas"
    pub.configurar(raiz, modo=pub.MODO_ROTATIVO)
    assert pub.ruta_reporte_automatico(raiz, "r") == raiz / "reportes" / "vigentes" / "r"
    registro.ruta_registro(raiz).parent.mkdir(parents=True)
    registro.ruta_registro(raiz).write_bytes(b"{roto")
    assert pub.ruta_reporte_automatico(raiz, "r") == raiz / "reportes" / "r"
    with pytest.raises(ValueError):
        pub.configurar(raiz, modo=pub.MODO_ROTATIVO)
    assert registro.ruta_registro(raiz).read_bytes() == b"{roto"


def test_captura_fallida_preserva_el_reporte_como_snapshot(tmp_path, monkeypatch):
    raiz = tmp_path / "Atlas"
    pub.configurar(raiz, modo=pub.MODO_ROTATIVO)

    def ocupado(*_a, **_k):
        raise registro.RegistroOcupado("cerrojo ocupado")

    monkeypatch.setattr(registro, "capturar_reporte_publicado", ocupado)
    salida = _publicar(raiz, "reporte_mobile_1", [_rel("1")])
    marcador = json.loads((salida / pub.MARCADOR).read_text(encoding="utf-8"))
    assert marcador["capturado"] is False and marcador["preservado_en"] == "reportes/reporte_mobile_1"
    assert _snapshots(raiz) == ["reporte_mobile_1"]
    assert (raiz / "reportes" / "reporte_mobile_1" / "viajes.csv").read_bytes() == (salida / "viajes.csv").read_bytes()
    assert not (raiz / "reportes" / "reporte_mobile_1" / pub.MARCADOR).exists()


def test_poda_conserva_vigente_recientes_y_lo_no_capturado(tmp_path):
    raiz = tmp_path / "Atlas"
    pub.configurar(raiz, modo=pub.MODO_ROTATIVO, conservar=2)
    for i in range(5):
        _publicar(raiz, f"reporte_mobile_{i}", [_rel(str(i))])
    # Mismo proceso: capturas aún sin confirmar en Cloud, nada se poda.
    assert len(_rotativos(raiz)) == 5
    pub._CAPTURADAS_EN_PROCESO.clear()  # próximo proceso (ciclo de PULL siguiente)
    _publicar(raiz, "reporte_mobile_5", [_rel("5")])
    assert _rotativos(raiz) == ["reporte_mobile_4", "reporte_mobile_5"]

    otra = tmp_path / "Otra"
    vigentes = pub.raiz_vigentes(otra)
    marcas = {"a": ("2026-01-01", True), "b": ("2026-01-02", True), "c": ("2026-01-03", True),
              "d": ("2026-01-04", True), "sin_captura": ("2025-01-01", False)}
    for nombre, (fecha, capturado) in marcas.items():
        carpeta = _reporte(vigentes / nombre, [_rel(nombre)])
        (carpeta / pub.MARCADOR).write_text(json.dumps({"publicado_en": fecha, "capturado": capturado}), encoding="utf-8")
    _reporte(vigentes / "en_generacion", [_rel("g")])  # sin marcador: aún no publicada
    (otra / "operacion" / "actual").mkdir(parents=True)
    (otra / "operacion" / "actual" / "estado_operacion.json").write_text(
        json.dumps({"schema_version": 1, "reporte_vigente": "reportes/vigentes/a"}), encoding="utf-8")
    # "b" dice capturado, pero su evidencia NO está en el registro de esta
    # raíz (p. ej. su segmento quedó en cuarentena tras un relevo): se vuelve
    # a capturar y se conserva.
    poda = pub.podar_vigentes(otra, conservar=2)
    assert poda["borradas"] == [] and sorted(poda["retenidas"]) == ["b", "sin_captura"]
    assert {"numero_guia": "b"}.items() <= registro.leer_relaciones(otra)[0].items()
    # Proceso siguiente: la evidencia ya está en el registro -> se poda.
    pub._CAPTURADAS_EN_PROCESO.clear()
    poda = pub.podar_vigentes(otra, conservar=2)
    assert poda["borradas"] == ["b"]
    assert sorted(poda["conservadas"]) == ["a", "c", "d"] and poda["retenidas"] == ["sin_captura"]
    assert sorted(_rotativos(otra)) == ["a", "c", "d", "en_generacion", "sin_captura"]


def test_reportes_historicos_nunca_se_tocan(tmp_path):
    raiz = tmp_path / "Atlas"
    historico = _reporte(raiz / "reportes" / "reporte_mobile_20261101_000000", [_rel("h")])
    huella = (historico / "viajes.csv").read_bytes()
    pub.configurar(raiz, modo=pub.MODO_ROTATIVO, conservar=2)
    for i in range(6):
        _publicar(raiz, f"reporte_mobile_{i}", [_rel(str(i))])
    assert _snapshots(raiz) == ["reporte_mobile_20261101_000000"]
    assert (historico / "viajes.csv").read_bytes() == huella
    assert sorted(p.name for p in historico.iterdir()) == ["viajes.csv"]


def test_snapshot_explicito_bajo_demanda(tmp_path):
    raiz = tmp_path / "Atlas"
    pub.configurar(raiz, modo=pub.MODO_ROTATIVO)
    vigente = _publicar(raiz, "reporte_mobile_1", [_rel("1")])
    destino = pub.snapshot_explicito(raiz)
    assert destino.parent == raiz / "reportes" and destino.name.startswith("snapshot_")
    assert (destino / "viajes.csv").read_bytes() == (vigente / "viajes.csv").read_bytes()
    assert not (destino / pub.MARCADOR).exists()
    assert _snapshots(raiz) == [destino.name]
    with pytest.raises(FileNotFoundError):
        pub.snapshot_explicito(tmp_path / "Vacia")


def test_reversion_a_snapshots_conserva_la_evidencia_capturada(tmp_path, monkeypatch):
    raiz = tmp_path / "Atlas"
    monkeypatch.setattr(rd, "_leer_relaciones_historicas_reportadas", lambda _r: [])
    pub.configurar(raiz, modo=pub.MODO_ROTATIVO, conservar=2)
    for i in range(4):
        _publicar(raiz, f"reporte_mobile_{i}", [_rel(str(i), patente=f"P{i}")])
    pub.configurar(raiz, modo=pub.MODO_SNAPSHOTS)
    _publicar(raiz, "reporte_mobile_9", [_rel("9")])
    assert _snapshots(raiz) == ["reporte_mobile_9"]
    guias = {c[0] for c in _claves(rd._relaciones_historicas_operacionales(raiz))}
    assert guias == {"0", "1", "2", "3"}  # el snapshot nuevo lo lee el lector histórico real


def test_union_sin_duplicados_y_registro_activo_manda(tmp_path, monkeypatch):
    raiz = tmp_path / "Atlas"
    historico = [{**_rel("1"), "numero_guia": " 1 "}]
    monkeypatch.setattr(rd, "_leer_relaciones_historicas_reportadas", lambda _r: historico)
    pub.configurar(raiz, modo=pub.MODO_ROTATIVO)
    _publicar(raiz, "reporte_mobile_1", [_rel("1"), _rel("2", "BB2222")])
    union = rd._relaciones_historicas_operacionales(raiz)
    assert union[0] is historico[0] and len(union) == 2
    # Sin publicaciones rotativas, el resultado es exactamente el del lector histórico.
    otra = tmp_path / "Otra"
    assert rd._relaciones_historicas_operacionales(otra) is historico
    # Con el registro activado, el consumidor usa el registro (incluye lo capturado).
    _reporte(raiz / "reportes" / "r_hist", [_rel("1")])
    registro.migrar_reportes_historicos(raiz, aplicar=True)
    assert registro.verificar_migracion(raiz)["ok"] is True
    registro.activar_registro(raiz)
    assert {c[0] for c in _claves(rd._relaciones_historicas_operacionales(raiz))} == {"1", "2"}


def test_lector_historico_y_migracion_no_recorren_vigentes(tmp_path, monkeypatch):
    raiz = tmp_path / "Atlas"
    _reporte(raiz / "reportes" / "r_hist", [_rel("h")])
    pub.configurar(raiz, modo=pub.MODO_ROTATIVO, conservar=2)
    _publicar(raiz, "reporte_mobile_0", [_rel("0")])
    lecturas = []
    original = rd._leer_reporte_historico
    monkeypatch.setattr(rd, "_leer_reporte_historico", lambda ruta: lecturas.append(ruta.parent.name) or original(ruta))
    assert {c[0] for c in _claves(rd._leer_relaciones_historicas_reportadas(raiz))} == {"h"}
    for i in range(1, 5):  # publicar y podar no invalida la caché del lector histórico
        _publicar(raiz, f"reporte_mobile_{i}", [_rel(str(i))])
    rd._leer_relaciones_historicas_reportadas(raiz)
    assert lecturas == ["r_hist"]
    simulacion = registro.migrar_reportes_historicos(raiz)
    assert [f["ruta"] for f in simulacion["fuentes"]] == ["reportes/r_hist/viajes.csv"]


def test_republicar_no_recaptura_ni_hace_crecer_el_registro(tmp_path, monkeypatch):
    raiz = tmp_path / "Atlas"
    pub.configurar(raiz, modo=pub.MODO_ROTATIVO)
    salida = _publicar(raiz, "reporte_mobile_1", [_rel("1")])
    _publicar(raiz, "reporte_mobile_2", [_rel("1")])  # misma evidencia, otro reporte
    def almacenado():
        archivos = [registro.ruta_registro(raiz), *sorted(registro.ruta_diario(raiz).glob("*"))]
        return [(a.name, a.read_bytes()) for a in archivos if a.is_file()]
    antes = almacenado()
    assert antes
    capturas = []
    monkeypatch.setattr(registro, "capturar_reporte_publicado", lambda *a, **k: capturas.append(a) or {})
    escribir_estado_operacion(reporte_vigente=salida, raiz=raiz)  # republicación del mismo vigente
    assert capturas == [] and almacenado() == antes
    entrada = registro.contenido_vigente(raiz)["empresas"]["oficina"]["relaciones"][0]
    assert [f["tipo"] for f in entrada["fuentes"]] == [registro.TIPO_PUBLICADO]


def test_gancho_nunca_impide_publicar(tmp_path, monkeypatch):
    raiz = tmp_path / "Atlas"
    pub.configurar(raiz, modo=pub.MODO_ROTATIVO)
    monkeypatch.setattr(pub, "podar_vigentes", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("falla")))
    salida = _publicar(raiz, "reporte_mobile_1", [_rel("1")])
    assert leer_estado_operacion(raiz=raiz)["reporte_vigente"] == "reportes/vigentes/reporte_mobile_1"
    assert salida.exists()


def test_cli(tmp_path, capsys):
    import publicacion_reportes as cli
    raiz = tmp_path / "Atlas"
    assert cli.main(["--raiz", str(raiz), "--snapshot"]) == 2
    assert cli.main(["--raiz", str(raiz), "--rotativo", "--conservar", "4"]) == 0
    capsys.readouterr()
    assert cli.main(["--raiz", str(raiz), "--estado"]) == 0
    estado = json.loads(capsys.readouterr().out)
    assert estado["modo_efectivo"] == pub.MODO_ROTATIVO and estado["conservar"] == 4
    assert cli.main(["--raiz", str(raiz), "--snapshots"]) == 0
    assert pub.modo_efectivo(raiz) == pub.MODO_SNAPSHOTS
