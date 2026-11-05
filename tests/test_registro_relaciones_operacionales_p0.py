from __future__ import annotations

import csv
import json

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
    contenido = json.loads(registro.ruta_registro(raiz).read_text(encoding="utf-8"))
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
    return ruta.read_bytes(), ruta.stat().st_mtime_ns


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
    registro.incorporar_relaciones(raiz, [], procedencia={"tipo": "prueba"})
    assert _huella(ruta) == antes


def test_relacion_nueva_sigue_escribiendo_y_conserva_lo_existente(tmp_path):
    raiz = tmp_path / "Atlas"
    registro.incorporar_relaciones(raiz, [_relacion("1", "AA1111")], procedencia={"tipo": "prueba"})
    ruta = registro.ruta_registro(raiz)
    contenido = json.loads(ruta.read_text(encoding="utf-8"))
    contenido["empresas"]["oficina"]["relaciones"][0]["confirmaciones_humanas"] = [{"por": "humano"}]
    ruta.write_text(json.dumps(contenido), encoding="utf-8")
    resultado = registro.incorporar_relaciones(raiz, [_relacion("2", "BB2222")], procedencia={"tipo": "prueba2"})
    assert resultado == {"relaciones_agregadas": 1, "fuentes_agregadas": 1, "total": 2}
    despues = json.loads(ruta.read_text(encoding="utf-8"))["empresas"]["oficina"]["relaciones"]
    assert [r["relacion"]["numero_guia"] for r in despues] == ["1", "2"]
    assert despues[0]["confirmaciones_humanas"] == [{"por": "humano"}]
    assert despues[1]["fuentes"][0]["tipo"] == "prueba2"
