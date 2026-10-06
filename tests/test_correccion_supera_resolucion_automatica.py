"""Una resolución automática de Atlas/B1 no bloquea una corrección humana.

Caso real 474708: `ATLAS_AUTOMATICO` eligió una rampla errónea
(SELECCIONAR_OTRA_PATENTE) y `DOCUMENTO_CORREGIR_CAMPO` con la rampla real
confirmada por Javier era rechazada con CAMPO_FIJADO_POR_DECISION_HUMANA.
Una decisión humana explícita sigue protegida. Sintético, nunca G:.
"""
from __future__ import annotations

import csv
import json

from atlas_core.acciones_operacionales import CapaAccionesOperacionales, TIPO_LEDGER_CORRECCION
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import revalidar_y_regenerar_reporte
from test_acciones_operacionales import _fila, _vehiculo, entorno  # noqa: F401 (fixture)

LEIDA, REAL, ERRONEA = "JE6159", "JE6359", "JD8659"


def _preparar(entorno, *aplicaciones):
    vehiculos = json.loads((entorno["raiz"] / "catalogos_privados" / "vehiculos.json").read_text(encoding="utf-8"))
    vehiculos["vehiculos"] += [_vehiculo(REAL, "CARRO"), _vehiculo(ERRONEA, "CARRO")]
    (entorno["raiz"] / "catalogos_privados" / "vehiculos.json").write_text(json.dumps(vehiculos), encoding="utf-8")
    with entorno["dataset"].open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows([_fila("500001", patente_rampla=LEIDA), _fila("500002", obra_destino="OBRA OTRA")])
    (entorno["actual"] / "decisiones_aplicadas.json").write_text(
        json.dumps({"schema_version": 1, "aplicaciones": list(aplicaciones)}), encoding="utf-8")


def _eleccion_previa(actor, accion="SELECCIONAR_OTRA_PATENTE"):
    return {
        "decision_id": f"previa-{actor}", "tipo": "VEHICULO_DESCONOCIDO", "accion": accion, "actor": actor,
        "campo": "patente_rampla", "valor_documental": LEIDA, "patente_canonica": ERRONEA,
        "documento": {"archivo": "500001.jpeg", "numero_guia": "500001", "numero_transporte": "0000900001"},
    }


def _corregir(capa):
    return capa.previsualizar(
        "DOCUMENTO_CORREGIR_CAMPO", {"numero_guia": "500001", "campo": "PATENTE_RAMPLA", "valor": REAL,
                                     "referencia": "rampla real confirmada"},
        actor="OPERADOR", origen="HUMANO")


def _fila_vigente(entorno):
    with entorno["dataset"].open(encoding="utf-8-sig", newline="") as archivo:
        return next(f for f in csv.DictReader(archivo, delimiter=";") if f["numero_guia"] == "500001")


def test_A_resolucion_de_atlas_automatico_no_bloquea_la_correccion(entorno):
    _preparar(entorno, _eleccion_previa("ATLAS_AUTOMATICO"))
    capa = CapaAccionesOperacionales(entorno["raiz"])
    preview = _corregir(capa)
    assert preview["estado"] == "PREVIEW", preview
    r = capa.ejecutar(preview["token"], actor="OPERADOR", origen="HUMANO", confirmado_por="JAVIER")
    assert r["estado"] == "APLICADA", r
    assert _fila_vigente(entorno)["patente_rampla"] == REAL


def test_B_resolucion_de_b1_no_bloquea_la_correccion(entorno):
    _preparar(entorno, _eleccion_previa("B1", accion="USAR_PATENTE_EXISTENTE"))
    assert _corregir(CapaAccionesOperacionales(entorno["raiz"]))["estado"] == "PREVIEW"


def test_C_decision_humana_explicita_sigue_protegida(entorno):
    _preparar(entorno, _eleccion_previa("JAVIER_MBT"))
    r = _corregir(CapaAccionesOperacionales(entorno["raiz"]))
    assert r["codigo"] == "CAMPO_FIJADO_POR_DECISION_HUMANA"
    assert _fila_vigente(entorno)["patente_rampla"] == LEIDA
    # una aplicación antigua sin actor se sigue tratando como humana
    sin_actor = _eleccion_previa("")
    sin_actor.pop("actor")
    _preparar(entorno, sin_actor)
    assert _corregir(CapaAccionesOperacionales(entorno["raiz"]))["codigo"] == "CAMPO_FIJADO_POR_DECISION_HUMANA"


def test_D_correccion_queda_trazada_y_es_idempotente(entorno):
    _preparar(entorno, _eleccion_previa("ATLAS_AUTOMATICO"))
    capa = CapaAccionesOperacionales(entorno["raiz"])
    capa.ejecutar(_corregir(capa)["token"], actor="OPERADOR", origen="HUMANO", confirmado_por="JAVIER")

    ledger = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))["aplicaciones"]
    (correccion,) = [a for a in ledger if a["tipo"] == TIPO_LEDGER_CORRECCION]
    assert (correccion["campo"], correccion["valor_documental"], correccion["valor_corregido"]) == (
        "patente_rampla", LEIDA, REAL)
    assert any(a["decision_id"] == "previa-ATLAS_AUTOMATICO" for a in ledger)  # la historia no se borra
    assert _corregir(capa)["estado"] == "SIN_CAMBIOS"
    assert len(json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))["aplicaciones"]) == 2


def test_E_resolucion_automatica_no_reaparece_tras_revalidar(entorno):
    _preparar(entorno, _eleccion_previa("ATLAS_AUTOMATICO"))
    capa = CapaAccionesOperacionales(entorno["raiz"])
    capa.ejecutar(_corregir(capa)["token"], actor="OPERADOR", origen="HUMANO", confirmado_por="JAVIER")

    revalidar_y_regenerar_reporte(raiz_atlas=entorno["raiz"], nombre_carpeta_reporte="reporte_e")

    assert _fila_vigente(entorno)["patente_rampla"] == REAL
    with (entorno["raiz"] / "reportes" / "reporte_e" / "viajes.csv").open(encoding="utf-8-sig", newline="") as archivo:
        viaje = next(v for v in csv.DictReader(archivo, delimiter=";") if "500001" in v["numeros_guia"])
    assert viaje["patentes_rampla"] == REAL
    assert ERRONEA not in viaje["patentes_rampla"]
    bandeja = json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    assert not [d for d in bandeja["decisiones"] if d["tipo"] == "VEHICULO_DESCONOCIDO"]
