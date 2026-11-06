from __future__ import annotations

import csv
import json

import pytest

import atlas_core.registro_relaciones_operacionales as registro


def _reporte(raiz, nombre, evidencias):
    ruta = raiz / "reportes" / nombre / "viajes.csv"
    ruta.parent.mkdir(parents=True)
    with ruta.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["evidencias_documentos"], delimiter=";")
        w.writeheader(); w.writerow({"evidencias_documentos": json.dumps(evidencias)})
    return ruta


def _relacion(guia="1", patente="AA1111"):
    return {"numero_guia": guia, "numero_transporte": "T1", "rut_chofer": "11111111-1", "patente_tracto": patente, "patente_rampla": ""}


def test_migracion_simulada_compara_y_aplicada_es_idempotente(tmp_path):
    raiz = tmp_path / "Atlas"
    _reporte(raiz, "r1", [_relacion(), _relacion()])
    _reporte(raiz, "r2", [_relacion("2", "BB2222")])
    simulacion = registro.migrar_reportes_historicos(raiz)
    assert simulacion["modo"] == "simulacion"
    assert simulacion["relaciones_extraidas"] == 2
    assert not registro.ruta_registro(raiz).exists()
    aplicado = registro.migrar_reportes_historicos(raiz, aplicar=True)
    assert aplicado["relaciones_agregadas"] == 2
    assert len(registro.leer_relaciones(raiz)) == simulacion["relaciones_extraidas"]
    repetido = registro.migrar_reportes_historicos(raiz, aplicar=True)
    assert repetido["relaciones_agregadas"] == 0


def test_conflicto_y_empresa_separada_se_preservan(tmp_path):
    raiz = tmp_path / "Atlas"
    registro.incorporar_relaciones(raiz, [_relacion("1", "AA1111")], empresa_id="a", procedencia={"tipo": "prueba"})
    registro.incorporar_relaciones(raiz, [_relacion("1", "BB2222")], empresa_id="a", procedencia={"tipo": "prueba2"})
    registro.incorporar_relaciones(raiz, [_relacion("1", "CC3333")], empresa_id="b", procedencia={"tipo": "prueba"})
    contenido = registro.contenido_vigente(raiz)
    assert len(contenido["empresas"]["a"]["relaciones"]) == 2
    assert all(r["conflictos"] for r in contenido["empresas"]["a"]["relaciones"])
    assert len(registro.leer_relaciones(raiz, empresa_id="b")) == 1
    assert contenido["empresas"]["a"]["relaciones"][0]["confirmaciones_humanas"] == []


def test_lectura_operacional_no_abre_reportes(tmp_path, monkeypatch):
    raiz = tmp_path / "Atlas"
    registro.incorporar_relaciones(raiz, [_relacion()], procedencia={"tipo": "prueba"})
    def prohibido(*_args, **_kwargs):
        raise AssertionError("un ciclo normal no debe leer reportes")
    monkeypatch.setattr(registro, "extraer_reporte_historico", prohibido)
    assert registro.leer_relaciones(raiz)[0]["numero_guia"] == "1"


# --- Sin cambio efectivo no se crea ni se reescribe el registro -------------

def _prohibir_escritura(monkeypatch):
    def prohibido(*_args, **_kwargs):
        raise AssertionError("sin cambio efectivo no debe escribirse el registro")
    monkeypatch.setattr(registro, "escribir_json_atomico", prohibido)


def _huella(ruta):
    """Base + diario: cualquier escritura del registro vigente la cambia."""
    archivos = [ruta, *sorted((ruta.parent / registro.CARPETA_DIARIO).glob("*"))]
    return [(a.name, a.read_bytes(), a.stat().st_mtime_ns) for a in archivos if a.is_file()]


def test_sin_relaciones_validas_no_crea_registro(tmp_path, monkeypatch):
    raiz = tmp_path / "Atlas"
    _prohibir_escritura(monkeypatch)
    sin_rut = dict(_relacion(), rut_chofer="")
    sin_guia = dict(_relacion(), numero_guia=" ")
    resultado = registro.incorporar_relaciones(raiz, [], procedencia={"tipo": "prueba"})
    assert resultado == {"relaciones_agregadas": 0, "fuentes_agregadas": 0, "total": 0}
    registro.incorporar_relaciones(raiz, [sin_rut, sin_guia], procedencia={"tipo": "prueba"})
    assert not registro.ruta_registro(raiz).exists()
    assert not (raiz / "catalogos_privados").exists()


def test_dataset_sin_relaciones_no_crea_registro(tmp_path, monkeypatch):
    raiz = tmp_path / "Atlas"
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    dataset.parent.mkdir(parents=True)
    dataset.write_text("numero_guia;rut_chofer;patente_tracto\n482188;;AA1111\n", encoding="utf-8-sig")
    _prohibir_escritura(monkeypatch)
    assert registro.incorporar_dataset(raiz, dataset)["relaciones_agregadas"] == 0
    assert not registro.ruta_registro(raiz).exists()


def test_registro_existente_se_conserva_sin_cambio_efectivo(tmp_path, monkeypatch):
    raiz = tmp_path / "Atlas"
    procedencia = {"tipo": "prueba", "observado_en": "2026-11-05T00:00:00+00:00"}
    registro.incorporar_relaciones(raiz, [_relacion()], procedencia=procedencia)
    ruta = registro.ruta_registro(raiz)
    antes = _huella(ruta)
    _prohibir_escritura(monkeypatch)
    vacio = registro.incorporar_relaciones(raiz, [], procedencia={"tipo": "otra"})
    repetido = registro.incorporar_relaciones(raiz, [_relacion(), _relacion()], procedencia=procedencia)
    assert vacio == {"relaciones_agregadas": 0, "fuentes_agregadas": 0, "total": 1}
    assert repetido == {"relaciones_agregadas": 0, "fuentes_agregadas": 0, "total": 1}
    assert _huella(ruta) == antes


def test_registro_ilegible_no_se_sobrescribe_sin_cambio_efectivo(tmp_path, monkeypatch):
    raiz = tmp_path / "Atlas"
    ruta = registro.ruta_registro(raiz)
    ruta.parent.mkdir(parents=True)
    ruta.write_bytes(b"{no es json")
    antes = _huella(ruta)
    _prohibir_escritura(monkeypatch)
    # Ilegible nunca equivale a vacío: se informa y el archivo queda intacto.
    for relaciones in ([], [_relacion()]):
        with pytest.raises(registro.RegistroIlegible):
            registro.incorporar_relaciones(raiz, relaciones, procedencia={"tipo": "prueba"})
    assert _huella(ruta) == antes


def test_relacion_nueva_sigue_escribiendo_y_conserva_lo_existente(tmp_path):
    raiz = tmp_path / "Atlas"
    registro.incorporar_relaciones(raiz, [_relacion("1", "AA1111")], procedencia={"tipo": "prueba"})
    ruta = registro.ruta_registro(raiz)
    contenido = registro.contenido_vigente(raiz)
    contenido["empresas"]["oficina"]["relaciones"][0]["confirmaciones_humanas"] = [{"por": "humano"}]
    ruta.write_text(json.dumps(contenido), encoding="utf-8")
    resultado = registro.incorporar_relaciones(raiz, [_relacion("2", "BB2222")], procedencia={"tipo": "prueba2"})
    assert resultado == {"relaciones_agregadas": 1, "fuentes_agregadas": 1, "total": 2}
    despues = registro.contenido_vigente(raiz)["empresas"]["oficina"]["relaciones"]
    assert [r["relacion"]["numero_guia"] for r in despues] == ["1", "2"]
    assert despues[0]["confirmaciones_humanas"] == [{"por": "humano"}]
    assert despues[1]["fuentes"][0]["tipo"] == "prueba2"


# --- Procedencias: una regeneración repetida no modifica lo registrado -------

def _dataset(raiz, filas):
    ruta = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(registro.CAMPOS) + ["otro"], delimiter=";")
        w.writeheader()
        w.writerows(filas)
    return ruta


def _entradas(raiz, empresa="oficina"):
    contenido = registro.contenido_vigente(raiz)
    return {e["clave"]: e for e in contenido["empresas"][empresa]["relaciones"]}


def test_regeneraciones_repetidas_no_modifican_relacion_registrada(tmp_path, monkeypatch):
    raiz = tmp_path / "Atlas"
    dataset = _dataset(raiz, [dict(_relacion("1"), otro="a")])
    assert registro.incorporar_dataset(raiz, dataset)["relaciones_agregadas"] == 1
    entrada_1 = next(iter(_entradas(raiz).values()))
    # Otra regeneración: el dataset cambia (huella distinta) y agrega una guía.
    dataset = _dataset(raiz, [dict(_relacion("1"), otro="b"), dict(_relacion("2", "BB2222"), otro="b")])
    assert registro.incorporar_dataset(raiz, dataset) == {"relaciones_agregadas": 1, "fuentes_agregadas": 1, "total": 2}
    entradas = _entradas(raiz)
    assert entradas[entrada_1["clave"]] == entrada_1  # la ya registrada, idéntica
    # Repetir con el mismo dataset (otra hora) no escribe nada.
    ruta = registro.ruta_registro(raiz)
    antes = _huella(ruta)
    _prohibir_escritura(monkeypatch)
    assert registro.incorporar_dataset(raiz, dataset)["fuentes_agregadas"] == 0
    assert _huella(ruta) == antes


def test_misma_procedencia_sin_observado_en_no_duplica_fuente(tmp_path, monkeypatch):
    raiz = tmp_path / "Atlas"
    registro.incorporar_relaciones(raiz, [_relacion()], procedencia={"tipo": "prueba", "sha256": "x"})
    _prohibir_escritura(monkeypatch)
    resultado = registro.incorporar_relaciones(raiz, [_relacion()], procedencia={"tipo": "prueba", "sha256": "y"})
    assert resultado["fuentes_agregadas"] == 0


# --- Integridad: corrupto o incompatible nunca es vacío -----------------------

@pytest.mark.parametrize("contenido, error", [
    (b"{no es json", registro.RegistroIlegible),
    (b"\xff\xfe\x00basura", registro.RegistroIlegible),
    (b'{"version": 1, "empresas": []}', registro.RegistroIlegible),
    (b'{"empresas": {}}', registro.RegistroIlegible),
    (b'{"version": 1, "empresas": {"oficina": {"relaciones": [{"clave": "k", "relacion": {}, "fuentes": {}}]}}}',
     registro.RegistroIlegible),
    (b'{"version": 2, "empresas": {}}', registro.RegistroIncompatible),
])
def test_registro_invalido_se_informa_y_nunca_se_sobrescribe(tmp_path, monkeypatch, contenido, error):
    raiz = tmp_path / "Atlas"
    ruta = registro.ruta_registro(raiz)
    ruta.parent.mkdir(parents=True)
    ruta.write_bytes(contenido)
    antes = _huella(ruta)
    _reporte(raiz, "r1", [_relacion()])
    _prohibir_escritura(monkeypatch)
    with pytest.raises(error):
        registro.incorporar_relaciones(raiz, [_relacion("9")], procedencia={"tipo": "prueba"})
    with pytest.raises(error):
        registro.leer_relaciones(raiz)
    with pytest.raises(error):
        registro.migrar_reportes_historicos(raiz, aplicar=True)
    assert registro.relaciones_si_activo(raiz) is None  # el consumidor vuelve a los históricos
    assert registro.estado_registro(raiz)["legible"] is False
    assert registro.migrar_reportes_historicos(raiz)["registro"]["legible"] is False
    assert _huella(ruta) == antes


def test_regeneracion_con_registro_ilegible_queda_bloqueada_sin_tocarlo(tmp_path):
    raiz = tmp_path / "Atlas"
    ruta = registro.ruta_registro(raiz)
    ruta.parent.mkdir(parents=True)
    ruta.write_bytes(b"{roto")
    dataset = _dataset(raiz, [dict(_relacion(), otro="")])
    with pytest.raises(registro.RegistroIlegible) as error:
        registro.incorporar_dataset(raiz, dataset)
    assert error.value.codigo == "REGISTRO_ILEGIBLE"
    assert ruta.read_bytes() == b"{roto"


# --- Activación: el consumidor no abandona los históricos antes de tiempo ------

def test_consumidor_usa_historicos_hasta_migracion_verificada_y_activada(tmp_path, monkeypatch):
    from atlas_core import revalidacion_documental as rd
    raiz = tmp_path / "Atlas"
    historico = [{"numero_guia": "H", "rut_chofer": "1-9"}]
    monkeypatch.setattr(rd, "_leer_relaciones_historicas_reportadas", lambda _raiz: historico)
    _reporte(raiz, "r1", [_relacion()])
    assert rd._relaciones_historicas_operacionales(raiz) is historico  # sin registro
    registro.incorporar_relaciones(raiz, [_relacion("7")], procedencia={"tipo": "prueba"})
    assert rd._relaciones_historicas_operacionales(raiz) is historico  # registro sin migrar
    with pytest.raises(registro.MigracionNoVerificada):
        registro.activar_registro(raiz)
    assert registro.migrar_reportes_historicos(raiz, aplicar=True)["estado"] == registro.ESTADO_COMPLETA
    assert rd._relaciones_historicas_operacionales(raiz) is historico  # completa, sin verificar
    with pytest.raises(registro.MigracionNoVerificada):
        registro.activar_registro(raiz)
    assert registro.verificar_migracion(raiz)["estado"] == registro.ESTADO_VERIFICADA
    assert rd._relaciones_historicas_operacionales(raiz) is historico  # verificada, sin activar
    assert registro.activar_registro(raiz)["activo"] is True
    activas = rd._relaciones_historicas_operacionales(raiz)
    assert sorted(r["numero_guia"] for r in activas) == ["1", "7"]
    assert registro.desactivar_registro(raiz)["activo"] is False
    assert rd._relaciones_historicas_operacionales(raiz) is historico  # reversión inmediata
    registro.activar_registro(raiz)
    registro.ruta_registro(raiz).write_bytes(b"{daniado")
    assert rd._relaciones_historicas_operacionales(raiz) is historico  # dañado: nunca vacío


def test_activacion_es_por_empresa(tmp_path):
    raiz = tmp_path / "Atlas"
    _reporte(raiz, "r1", [_relacion()])
    registro.migrar_reportes_historicos(raiz, aplicar=True)
    registro.verificar_migracion(raiz)
    registro.activar_registro(raiz)
    registro.incorporar_relaciones(raiz, [_relacion("5")], empresa_id="b", procedencia={"tipo": "prueba"})
    assert registro.relaciones_si_activo(raiz, empresa_id="b") is None
    with pytest.raises(registro.MigracionNoVerificada):
        registro.activar_registro(raiz, empresa_id="b")
    assert [r["numero_guia"] for r in registro.relaciones_si_activo(raiz)] == ["1"]


def test_verificacion_falla_con_relacion_ausente_o_reporte_ilegible_y_no_escribe(tmp_path):
    raiz = tmp_path / "Atlas"
    _reporte(raiz, "r1", [_relacion()])
    registro.migrar_reportes_historicos(raiz, aplicar=True)
    _reporte(raiz, "r2", [_relacion("2", "BB2222")])  # nuevo, nunca migrado ni incorporado
    ruta = registro.ruta_registro(raiz)
    antes = _huella(ruta)
    resultado = registro.verificar_migracion(raiz)
    assert resultado["ok"] is False and resultado["relaciones_ausentes"] == 1
    assert resultado["estado"] == registro.ESTADO_COMPLETA
    assert _huella(ruta) == antes
    # Su relación llega por el dataset operacional: queda cubierta sin migrarlo.
    registro.incorporar_relaciones(
        raiz, [_relacion("2", "BB2222")], procedencia={"tipo": registro.TIPO_DATASET, "dataset": "d"},
    )
    cubierto = registro.verificar_migracion(raiz)
    assert cubierto["ok"] is True and cubierto["no_migrados"] == ["reportes/r2/viajes.csv"]
    # Un reporte ilegible impide completar, verificar y activar.
    raiz2 = tmp_path / "Atlas2"
    _reporte(raiz2, "r1", [_relacion()])
    (raiz2 / "reportes" / "r2").mkdir()
    (raiz2 / "reportes" / "r2" / "viajes.csv").write_bytes(b"\xff\xfe\xfa no utf8")
    aplicado = registro.migrar_reportes_historicos(raiz2, aplicar=True)
    assert aplicado["ilegibles"] == ["reportes/r2/viajes.csv"]
    assert aplicado["estado"] == registro.ESTADO_EN_CURSO
    assert registro.verificar_migracion(raiz2)["ok"] is False
    with pytest.raises(registro.MigracionNoVerificada):
        registro.activar_registro(raiz2)


# --- Migración: interrumpida, reanudada, repetida y concurrente ----------------

def _tres_reportes(raiz):
    _reporte(raiz, "r1", [_relacion("1", "AA1111"), _relacion("1", "AA1111")])
    _reporte(raiz, "r2", [_relacion("2", "BB2222"), _relacion("1", "AA1111")])
    _reporte(raiz, "r3", [_relacion("3", "CC3333"), _relacion("1", "ZZ9999")])


def _resumen(raiz, empresa="oficina"):
    contenido = registro.contenido_vigente(raiz)
    datos = contenido["empresas"][empresa]
    relaciones = {
        e["clave"]: (
            sorted((f["tipo"], f.get("ruta", ""), f.get("sha256", "")) for f in e["fuentes"]),
            e["conflictos"], e["confirmaciones_humanas"],
        )
        for e in datos["relaciones"]
    }
    return relaciones, datos["migracion"]["reportes"], datos["migracion"]["estado"]


def test_migracion_interrumpida_se_reanuda_igual_que_una_completa(tmp_path, monkeypatch):
    control = tmp_path / "Control"
    _tres_reportes(control)
    registro.migrar_reportes_historicos(control, aplicar=True, lote=1)

    raiz = tmp_path / "Atlas"
    _tres_reportes(raiz)
    original = registro._leer_reporte
    llamadas = []

    def falla_en_la_tercera(ruta):
        llamadas.append(ruta)
        if len(llamadas) == 3:
            raise KeyboardInterrupt("corte simulado")
        return original(ruta)

    monkeypatch.setattr(registro, "_leer_reporte", falla_en_la_tercera)
    with pytest.raises(KeyboardInterrupt):
        registro.migrar_reportes_historicos(raiz, aplicar=True, lote=1)
    estado = registro.estado_registro(raiz)
    assert estado["estado_migracion"] == registro.ESTADO_EN_CURSO and estado["reportes_migrados"] == 2
    with pytest.raises(registro.MigracionNoVerificada):
        registro.activar_registro(raiz)

    leidos = []
    monkeypatch.setattr(registro, "_leer_reporte", lambda ruta: leidos.append(ruta) or original(ruta))
    reanudado = registro.migrar_reportes_historicos(raiz, aplicar=True, lote=1)
    assert reanudado["omitidos_ya_migrados"] == 2 and reanudado["procesados"] == 1
    assert [p.parent.name for p in leidos] == ["r3"]  # lo ya migrado no se relee
    assert reanudado["estado"] == registro.ESTADO_COMPLETA
    assert _resumen(raiz)[0] == _resumen(control)[0]
    assert _resumen(raiz)[1] == _resumen(control)[1]
    assert registro.verificar_migracion(raiz)["ok"] is True


def test_migracion_repetida_no_reescribe_ni_duplica(tmp_path, monkeypatch):
    raiz = tmp_path / "Atlas"
    _tres_reportes(raiz)
    primero = registro.migrar_reportes_historicos(raiz, aplicar=True, lote=2)
    assert primero["relaciones_agregadas"] == 4 and primero["estado"] == registro.ESTADO_COMPLETA
    resumen = _resumen(raiz)
    ruta = registro.ruta_registro(raiz)
    antes = _huella(ruta)
    _prohibir_escritura(monkeypatch)
    for _ in range(2):
        repetido = registro.migrar_reportes_historicos(raiz, aplicar=True)
        assert repetido["relaciones_agregadas"] == repetido["fuentes_agregadas"] == repetido["procesados"] == 0
        assert repetido["omitidos_ya_migrados"] == 3
    assert _huella(ruta) == antes and _resumen(raiz) == resumen


def test_conflictos_de_la_migracion_se_conservan(tmp_path):
    raiz = tmp_path / "Atlas"
    _tres_reportes(raiz)
    registro.migrar_reportes_historicos(raiz, aplicar=True, lote=1)
    entradas = {e["relacion"]["patente_tracto"]: e for e in _entradas(raiz).values()}
    discrepante = "RELACION_DOCUMENTAL_DISCREPANTE"
    assert entradas["AA1111"]["conflictos"] == [{"tipo": discrepante, "con": entradas["ZZ9999"]["clave"]}]
    assert entradas["ZZ9999"]["conflictos"] == [{"tipo": discrepante, "con": entradas["AA1111"]["clave"]}]
    # Una sola fuente migrada por relación (la primera observación); el detalle
    # por reporte queda en migracion.reportes, sin hacer crecer cada relación.
    assert [f["ruta"] for f in entradas["AA1111"]["fuentes"]] == ["reportes/r1/viajes.csv"]
    reportes = registro.contenido_vigente(raiz)["empresas"]["oficina"]["migracion"]["reportes"]
    assert sorted(reportes) == ["reportes/r1/viajes.csv", "reportes/r2/viajes.csv", "reportes/r3/viajes.csv"]


def test_tamano_del_registro_no_crece_con_la_cantidad_de_snapshots(tmp_path):
    raiz = tmp_path / "Atlas"
    relaciones = [_relacion(str(g), f"PP{g:04d}") for g in range(40)]
    for indice in range(60):  # 60 snapshots completos con las mismas 40 relaciones
        _reporte(raiz, f"r{indice:03d}", relaciones)
    registro.migrar_reportes_historicos(raiz, aplicar=True, lote=20)
    contenido = registro.contenido_vigente(raiz)
    entradas = contenido["empresas"]["oficina"]["relaciones"]
    assert len(entradas) == 40 and all(len(e["fuentes"]) == 1 for e in entradas)


def test_segunda_migracion_simultanea_queda_bloqueada(tmp_path, monkeypatch):
    raiz = tmp_path / "Atlas"
    _tres_reportes(raiz)
    _prohibir_escritura(monkeypatch)
    with registro._cerrojo(registro.ruta_cerrojo(raiz, "migracion"), 0):
        with pytest.raises(registro.RegistroOcupado):
            registro.migrar_reportes_historicos(raiz, aplicar=True)
    assert not registro.ruta_registro(raiz).exists()


def test_escritura_concurrente_espera_el_cerrojo_y_no_pisa(tmp_path):
    raiz = tmp_path / "Atlas"
    registro.incorporar_relaciones(raiz, [_relacion("1")], procedencia={"tipo": "prueba"})
    ruta = registro.ruta_registro(raiz)
    antes = _huella(ruta)
    with registro._cerrojo(registro.ruta_cerrojo(raiz, "escritura"), 0):
        with pytest.raises(registro.RegistroOcupado):
            registro.incorporar_relaciones(raiz, [_relacion("2")], procedencia={"tipo": "prueba"}, espera=0.2)
    assert _huella(ruta) == antes
    registro.incorporar_relaciones(raiz, [_relacion("2")], procedencia={"tipo": "prueba"})
    assert sorted(_entradas(raiz)) == sorted(registro._clave(_relacion(g)) for g in ("1", "2"))


def test_regeneracion_durante_la_migracion_no_se_pierde(tmp_path, monkeypatch):
    raiz = tmp_path / "Atlas"
    _tres_reportes(raiz)
    original = registro._leer_reporte
    llamadas = []

    def con_regeneracion_intermedia(ruta):
        llamadas.append(ruta)
        if len(llamadas) == 2:  # entre dos lotes ya confirmados
            registro.incorporar_relaciones(
                raiz, [_relacion("88", "DD4444")], procedencia={"tipo": registro.TIPO_DATASET, "dataset": "d"},
            )
        return original(ruta)

    monkeypatch.setattr(registro, "_leer_reporte", con_regeneracion_intermedia)
    resultado = registro.migrar_reportes_historicos(raiz, aplicar=True, lote=1)
    guias = sorted(r["numero_guia"] for r in registro.leer_relaciones(raiz))
    assert guias == ["1", "1", "2", "3", "88"]
    assert resultado["estado"] == registro.ESTADO_COMPLETA


# --- Conservación de datos existentes y separación por empresa -----------------

def test_migracion_y_dataset_conservan_confirmaciones_conflictos_y_otras_empresas(tmp_path):
    raiz = tmp_path / "Atlas"
    registro.incorporar_relaciones(raiz, [_relacion("1", "AA1111")], procedencia={"tipo": "previa"})
    registro.incorporar_relaciones(raiz, [_relacion("1", "QQ0000")], empresa_id="b", procedencia={"tipo": "previa"})
    ruta = registro.ruta_registro(raiz)
    contenido = registro.contenido_vigente(raiz)
    confirmacion = {"por": "operador", "decision_id": "d-1", "en": "2026-11-05"}
    contenido["empresas"]["oficina"]["relaciones"][0]["confirmaciones_humanas"] = [confirmacion]
    contenido["empresas"]["oficina"]["relaciones"][0]["conflictos"] = [{"tipo": "MANUAL", "con": "x"}]
    ruta.write_text(json.dumps(contenido), encoding="utf-8")
    empresa_b = registro.contenido_vigente(raiz)["empresas"]["b"]

    _tres_reportes(raiz)
    registro.migrar_reportes_historicos(raiz, aplicar=True, lote=1)
    registro.incorporar_dataset(raiz, _dataset(raiz, [dict(_relacion("1", "AA1111"), otro="")]))

    contenido = registro.contenido_vigente(raiz)
    relaciones = contenido["empresas"]["oficina"]["relaciones"]
    entrada = next(e for e in relaciones if e["relacion"]["patente_tracto"] == "AA1111")
    assert entrada["confirmaciones_humanas"] == [confirmacion]
    assert entrada["conflictos"][0] == {"tipo": "MANUAL", "con": "x"}
    assert entrada["fuentes"][0]["tipo"] == "previa"
    assert {f["tipo"] for f in entrada["fuentes"]} == {"previa", registro.TIPO_MIGRADO, registro.TIPO_DATASET}
    assert contenido["empresas"]["b"] == empresa_b
    assert all(e["confirmaciones_humanas"] == [] for e in relaciones if e is not entrada)


def test_reporte_con_evidencias_largas_se_migra(tmp_path):
    raiz = tmp_path / "Atlas"
    _reporte(raiz, "r1", [dict(_relacion("1"), texto_ocr="x" * 300_000)])
    previo = csv.field_size_limit()
    csv.field_size_limit(131072)
    try:
        resultado = registro.migrar_reportes_historicos(raiz, aplicar=True)
    finally:
        csv.field_size_limit(max(previo, csv.field_size_limit()))
    assert resultado["ilegibles"] == [] and resultado["relaciones_agregadas"] == 1


# --- Operación normal: sin reparsear el registro ni abrir reportes ------------

def test_lecturas_repetidas_no_reparsean_hasta_que_el_archivo_cambia(tmp_path, monkeypatch):
    raiz = tmp_path / "Atlas"
    registro.incorporar_relaciones(raiz, [_relacion("1")], procedencia={"tipo": "prueba"})
    registro._MEMORIA.clear()
    lecturas = []
    original = registro._leer_fresco
    monkeypatch.setattr(registro, "_leer_fresco", lambda r: lecturas.append(1) or original(r))
    monkeypatch.setattr(registro, "_leer_reporte", lambda *_: (_ for _ in ()).throw(AssertionError("abre reportes")))
    for _ in range(5):
        assert len(registro.leer_relaciones(raiz)) == 1
        registro.incorporar_relaciones(raiz, [_relacion("1")], procedencia={"tipo": "prueba"})
    assert len(lecturas) == 1
    contenido = registro.contenido_vigente(raiz)
    leidas = len(lecturas)
    relaciones = contenido["empresas"]["oficina"]["relaciones"]
    relaciones.append(dict(relaciones[0], clave="otra"))
    registro.ruta_registro(raiz).write_text(json.dumps(contenido), encoding="utf-8")
    assert len(registro.leer_relaciones(raiz)) == 2 and len(lecturas) == leidas + 1


def test_cli_codigos_de_salida(tmp_path, capsys):
    import migrar_relaciones_operacionales as cli
    raiz = tmp_path / "Atlas"
    _reporte(raiz, "r1", [_relacion()])
    base = ["--raiz", str(raiz), "--sin-escritor"]
    assert cli.main([*base, "--activar"]) == 2
    assert cli.main(["--raiz", str(raiz)]) == 0 and not registro.ruta_registro(raiz).exists()
    assert cli.main([*base, "--aplicar"]) == 0
    assert cli.main([*base, "--verificar"]) == 0
    assert cli.main([*base, "--activar"]) == 0
    capsys.readouterr()
    assert cli.main(["--raiz", str(raiz), "--estado"]) == 0
    assert json.loads(capsys.readouterr().out)["activo"] is True


class _EscritorFalso:
    def __init__(self, libre=True):
        self.libre, self.dentro, self.eventos = libre, False, []

    def __enter__(self):
        self.eventos.append("entrar")
        return self

    def __exit__(self, *_a):
        self.dentro = False
        self.eventos.append("cerrar")

    def adquirir(self):
        self.dentro = self.libre
        self.eventos.append("adquirir")
        return self.libre

    @property
    def vigente(self):
        return self.dentro


def test_cli_escribe_solo_dentro_del_turno_del_escritor(tmp_path, monkeypatch):
    import migrar_relaciones_operacionales as cli
    raiz = tmp_path / "Atlas"
    _reporte(raiz, "r1", [_relacion()])
    # Sin escritor configurado (sin token ni política): bloqueado, nada escrito.
    assert cli.main(["--raiz", str(raiz), "--aplicar"], fabrica_escritor=lambda _r: None) == 2
    ocupado = _EscritorFalso(libre=False)
    assert cli.main(["--raiz", str(raiz), "--aplicar"], fabrica_escritor=lambda _r: ocupado) == 2
    assert not registro.ruta_registro(raiz).exists()
    # Con el escritor adquirido, cada escritura del registro ocurre dentro del turno.
    escritor = _EscritorFalso()
    original = registro.escribir_json_atomico

    def vigilada(ruta, contenido):
        assert escritor.vigente, "escritura del registro fuera del turno de custodia"
        return original(ruta, contenido)

    monkeypatch.setattr(registro, "escribir_json_atomico", vigilada)
    lectura_original = registro._leer_reporte
    lecturas_en_turno = []

    def leer_vigilado(ruta):
        lecturas_en_turno.append(escritor.vigente)
        return lectura_original(ruta)

    monkeypatch.setattr(registro, "_leer_reporte", leer_vigilado)
    for accion in ("--aplicar", "--verificar", "--activar", "--desactivar"):
        assert cli.main(["--raiz", str(raiz), accion], fabrica_escritor=lambda _r: escritor) == 0
    assert escritor.eventos.count("adquirir") == 4 and escritor.eventos[-1] == "cerrar"
    assert registro.estado_registro(raiz)["estado_migracion"] == registro.ESTADO_VERIFICADA
    # Los reportes (lectura larga) se leen SIEMPRE fuera del turno: PULL no espera la lectura.
    assert lecturas_en_turno and not any(lecturas_en_turno)
