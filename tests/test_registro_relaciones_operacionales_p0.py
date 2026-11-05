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
