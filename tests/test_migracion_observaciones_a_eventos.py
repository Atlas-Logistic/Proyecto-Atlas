"""Bloque EVENTOS OPERACIONALES CANÓNICOS V1 -- migración ÚNICA de las
Observaciones de electron-store (`observaciones.json`) a la fuente
canónica. Idempotente, no destructiva, preserva notas, no inventa
vínculos.
"""

from __future__ import annotations

import json

from atlas_core.almacenamiento_portable import escribir_estado_operacion
from atlas_core.registro_eventos_operacionales import (
    anular_evento,
    leer_eventos_operacionales,
)
from migrar_observaciones_a_eventos import migrar


def _observaciones(tmp_path, datos):
    ruta = tmp_path / "observaciones.json"
    ruta.write_text(json.dumps({"datos": datos}, ensure_ascii=False, indent=2), encoding="utf-8")
    return ruta


def _operacion_vigente(raiz, filas):
    columnas = [
        "viaje_id", "numero_transporte", "fecha", "numeros_guia", "choferes",
        "ruts_chofer", "patentes_tracto", "patentes_rampla",
    ]
    carpeta = raiz / "reportes" / "r1"
    carpeta.mkdir(parents=True, exist_ok=True)
    lineas = [";".join(columnas)]
    for fila in filas:
        lineas.append(";".join(str(fila.get(c, "")) for c in columnas))
    (carpeta / "viajes.csv").write_text("﻿" + "\n".join(lineas) + "\n", encoding="utf-8")
    escribir_estado_operacion(reporte_vigente=carpeta, dataset_operacional=None, raiz=raiz)


NOTA_REAL = "ESTE VIAJE TIENE ESTADIA, SE ENVIO GUÍA FIRMADA AL CORREO\n"


def test_migracion_basica_crea_un_evento_por_tag_y_respalda(tmp_path):
    raiz = tmp_path / "atlas"
    raiz.mkdir()
    _operacion_vigente(raiz, [
        {"viaje_id": "v1", "numero_transporte": "0000352552", "fecha": "10-08-2026",
         "numeros_guia": "464534 | 464535", "choferes": "PATRICIO VILLAGRA", "patentes_tracto": "BDFG50"},
    ])
    obs = _observaciones(tmp_path, {"0000352552": {"tags": ["estadia"], "nota": NOTA_REAL}})

    resultado = migrar(raiz_atlas=raiz, ruta_observaciones=obs)

    assert resultado["ok"] is True
    assert resultado["observaciones_encontradas"] == 1
    assert resultado["tags_encontrados"] == 1
    assert resultado["eventos_creados"] == 1
    assert resultado["tags_por_tipo"] == {"TIENE_ESTADIA": 1}
    assert resultado["tiene_estadia_activos"] == 1
    assert resultado["vinculados_completos"] == 1
    assert resultado["incompletos"] == []

    # respaldo real + manifiesto
    respaldo = resultado["respaldo"]
    assert respaldo is not None
    import pathlib

    manifiesto = json.loads((pathlib.Path(respaldo) / "manifiesto.json").read_text(encoding="utf-8"))
    assert manifiesto["observaciones_sha256"]
    assert (pathlib.Path(respaldo) / "observaciones.json").read_text(encoding="utf-8")

    # nota preservada EXACTAMENTE (incluido el \n final)
    doc = leer_eventos_operacionales(raiz=raiz)
    assert doc["eventos"][0]["nota"] == NOTA_REAL
    assert doc["eventos"][0]["numeros_guia"] == ["464534", "464535"]

    # observaciones.json intacto
    assert json.loads(obs.read_text(encoding="utf-8"))["datos"]["0000352552"]["nota"] == NOTA_REAL


def test_migracion_ejecutada_dos_veces_no_duplica(tmp_path):
    raiz = tmp_path / "atlas"
    raiz.mkdir()
    _operacion_vigente(raiz, [{"viaje_id": "v1", "numero_transporte": "111", "fecha": "10-08-2026"}])
    obs = _observaciones(tmp_path, {
        "111": {"tags": ["estadia"], "nota": "n"},
        "222": {"tags": ["estadia", "doble_vuelta"], "nota": "m"},
    })

    r1 = migrar(raiz_atlas=raiz, ruta_observaciones=obs)
    doc1 = leer_eventos_operacionales(raiz=raiz)
    r2 = migrar(raiz_atlas=raiz, ruta_observaciones=obs)
    doc2 = leer_eventos_operacionales(raiz=raiz)

    assert r1["eventos_creados"] == 3
    assert r2["eventos_creados"] == 0
    assert r2["eventos_ya_existentes"] == 3
    assert len(doc1["eventos"]) == len(doc2["eventos"]) == 3
    # 2ª corrida no reescribe el canónico: misma revisión.
    assert doc1["revision"] == doc2["revision"]


def test_migracion_preserva_tags_y_notas_de_varias_observaciones(tmp_path):
    raiz = tmp_path / "atlas"
    raiz.mkdir()
    datos = {
        f"00003525{n:02d}": {"tags": ["estadia"], "nota": f"nota {n}\n"}
        for n in range(9)
    }
    obs = _observaciones(tmp_path, datos)
    resultado = migrar(raiz_atlas=raiz, ruta_observaciones=obs)

    assert resultado["tags_por_tipo"] == {"TIENE_ESTADIA": 9}
    assert resultado["tiene_estadia_activos"] == 9
    doc = leer_eventos_operacionales(raiz=raiz)
    notas = {e["numero_transporte"]: e["nota"] for e in doc["eventos"]}
    for nt, reg in datos.items():
        assert notas[nt] == reg["nota"]


def test_migracion_sin_operacion_vigente_conserva_evento_con_vinculo_incompleto(tmp_path):
    raiz = tmp_path / "atlas"
    raiz.mkdir()
    obs = _observaciones(tmp_path, {"0000352552": {"tags": ["estadia"], "nota": NOTA_REAL}})

    resultado = migrar(raiz_atlas=raiz, ruta_observaciones=obs)

    assert resultado["eventos_creados"] == 1
    assert resultado["vinculados_completos"] == 0
    assert len(resultado["incompletos"]) == 1
    assert resultado["incompletos"][0]["motivo"] == "SIN_OPERACION_VIGENTE"
    assert resultado["tiene_estadia_activos"] == 1

    doc = leer_eventos_operacionales(raiz=raiz)
    ev = doc["eventos"][0]
    assert ev["vinculo_completo"] is False
    assert ev["viaje_id"] == "" and ev["snapshot"] == {}
    assert ev["nota"] == NOTA_REAL  # la nota se preserva aunque el vínculo esté incompleto


def test_migracion_mapea_los_cuatro_tags_y_reporta_los_desconocidos(tmp_path):
    raiz = tmp_path / "atlas"
    raiz.mkdir()
    obs = _observaciones(tmp_path, {
        "1": {"tags": ["estadia"], "nota": ""},
        "2": {"tags": ["devolucion_parcial"], "nota": ""},
        "3": {"tags": ["devolucion_total"], "nota": ""},
        "4": {"tags": ["doble_vuelta"], "nota": ""},
        "5": {"tags": ["algo_raro"], "nota": ""},
    })
    resultado = migrar(raiz_atlas=raiz, ruta_observaciones=obs)
    assert resultado["tags_por_tipo"] == {
        "TIENE_ESTADIA": 1, "DEVOLUCION_PARCIAL": 1, "DEVOLUCION_TOTAL": 1, "DOBLE_VUELTA": 1,
    }
    assert resultado["tags_no_mapeados"] == [{"numero_transporte": "5", "tag": "algo_raro"}]
    assert resultado["eventos_creados"] == 4


def test_migracion_reactiva_evento_previamente_anulado_sin_duplicar(tmp_path):
    raiz = tmp_path / "atlas"
    raiz.mkdir()
    obs = _observaciones(tmp_path, {"111": {"tags": ["estadia"], "nota": "n"}})
    migrar(raiz_atlas=raiz, ruta_observaciones=obs)
    anular_evento(raiz=raiz, tipo_evento="TIENE_ESTADIA", numero_transporte="111", origen="TEST")

    resultado = migrar(raiz_atlas=raiz, ruta_observaciones=obs)
    assert resultado["eventos_reactivados"] == 1
    assert resultado["eventos_creados"] == 0
    doc = leer_eventos_operacionales(raiz=raiz)
    assert len(doc["eventos"]) == 1
    assert doc["eventos"][0]["estado"] == "ACTIVO"


def test_dry_run_no_escribe_nada(tmp_path):
    raiz = tmp_path / "atlas"
    raiz.mkdir()
    obs = _observaciones(tmp_path, {"111": {"tags": ["estadia"], "nota": "n"}})
    resultado = migrar(raiz_atlas=raiz, ruta_observaciones=obs, dry_run=True)
    assert resultado["dry_run"] is True
    assert resultado["eventos_creados"] == 1
    assert resultado["respaldo"] is None
    assert leer_eventos_operacionales(raiz=raiz)["eventos"] == []
