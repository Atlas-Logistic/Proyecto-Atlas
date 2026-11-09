"""Reintentos de correcciones sobre un dataset sintético, nunca producción."""
import json

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from tests.test_acciones_operacionales import entorno, _escribir_dataset, _fila, _sin_reporte_real


def test_interrupcion_tras_ledger_no_duplica_folio(entorno, monkeypatch):
    archivo = "mobile/prueba/original.jpg"
    _escribir_dataset(entorno, [_fila("No encontrado", archivo=archivo, numero_transporte="0000369009")])
    _sin_reporte_real(monkeypatch, [])
    capa = CapaAccionesOperacionales(entorno["raiz"])
    preview = capa.previsualizar("DOCUMENTO_CORREGIR_NUMERO_GUIA", {
        "numero_guia": "No encontrado", "numero_guia_corregido": "484180", "archivo": archivo,
    }, actor="B1", origen="B1")
    assert preview["estado"] == "PREVIEW"

    def corte(*args, **kwargs):
        raise SystemExit("corte simulado antes de auditar")

    monkeypatch.setattr(capa, "_auditar", corte)
    with pytest.raises(SystemExit):
        capa.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")

    ledger_path = entorno["actual"] / "decisiones_aplicadas.json"
    antes = ledger_path.read_bytes()
    reintento = CapaAccionesOperacionales(entorno["raiz"]).ejecutar(
        preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    assert reintento["codigo"] == "PUBLICACION_INCOMPLETA"
    assert ledger_path.read_bytes() == antes
    entradas = json.loads(antes)["aplicaciones"]
    assert len([e for e in entradas if e["decision_id"] == f"ACCION_OPERACIONAL:{preview['token']}"]) == 1
    assert entradas[-1]["confirmado_por"] == "JAVIER"


def test_interrupcion_antes_ledger_bloquea_reintento(entorno, monkeypatch):
    import atlas_core.acciones_operacionales as acciones

    archivo = "mobile/prueba/original.jpg"
    _escribir_dataset(entorno, [_fila("No encontrado", archivo=archivo, numero_transporte="0000369009")])
    _sin_reporte_real(monkeypatch, [])
    capa = CapaAccionesOperacionales(entorno["raiz"])
    preview = capa.previsualizar("DOCUMENTO_CORREGIR_NUMERO_GUIA", {
        "numero_guia": "No encontrado", "numero_guia_corregido": "484180", "archivo": archivo,
    }, actor="B1", origen="B1")
    escribir = acciones.escribir_json_atomico

    def interrumpir_ledger(ruta, contenido):
        if ruta == entorno["actual"] / "decisiones_aplicadas.json":
            raise SystemExit("corte simulado antes del ledger")
        return escribir(ruta, contenido)

    monkeypatch.setattr(acciones, "escribir_json_atomico", interrumpir_ledger)
    with pytest.raises(SystemExit):
        capa.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    antes = entorno["dataset"].read_bytes()
    reintento = CapaAccionesOperacionales(entorno["raiz"]).ejecutar(
        preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    assert reintento["codigo"] == "PUBLICACION_INCOMPLETA"
    assert entorno["dataset"].read_bytes() == antes


@pytest.mark.parametrize("confirmante", ["B1", "ATLAS_AUTOMATICO"])
def test_confirmacion_automatica_no_autoriza_folio(entorno, confirmante):
    archivo = "mobile/prueba/original.jpg"
    _escribir_dataset(entorno, [_fila("No encontrado", archivo=archivo, numero_transporte="0000369009")])
    capa = CapaAccionesOperacionales(entorno["raiz"])
    preview = capa.previsualizar("DOCUMENTO_CORREGIR_NUMERO_GUIA", {
        "numero_guia": "No encontrado", "numero_guia_corregido": "484180", "archivo": archivo,
    }, actor="B1", origen="B1")
    antes = entorno["dataset"].read_bytes()
    resultado = capa.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por=confirmante)
    assert resultado["codigo"] == "CONFIRMACION_REQUERIDA"
    assert entorno["dataset"].read_bytes() == antes
