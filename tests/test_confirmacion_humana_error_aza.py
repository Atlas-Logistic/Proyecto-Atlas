"""DOCUMENTO_CONFIRMAR_ERROR_DOCUMENTAL_AZA aceptaba confirmado_por=
ATLAS_AUTOMATICO (u otra identidad técnica): se registraba como confirmación
humana sin persona. Ahora el canal aplica a TODA acción que exige
confirmación la misma regla de identidad humana (`_confirmante_humano`).
Sólo fixtures sintéticas: nunca G: ni datos productivos."""
from __future__ import annotations

import hashlib

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales, _confirmante_humano
from atlas_core.incidencias_documentales import AlmacenIncidenciasDocumentales
from tests.test_acciones_operacionales import entorno  # noqa: F401 -- fixture compartida
from tests.test_errores_documentales_aza import _ejecutar, _filas, varas  # noqa: F401 -- fixture compartida

ACCION = "DOCUMENTO_CONFIRMAR_ERROR_DOCUMENTAL_AZA"
TECNICAS = ["ATLAS_AUTOMATICO", "atlas-automatico", "ATLAS", "ATLAS_IA", "B1", "SISTEMA", "Sistema",
            "MOTOR_RECUPERACION_INCREMENTAL", "MOTOR", "MOBILE", "DESKTOP", "PULL", "PULL_CASA", "CLOUD",
            "CLOUD_WORKER", "OCR", "PROCESO_AUTOMATICO", "AUTOMATICO", "BOT_REVISION", "", "  "]


def _huellas(e):
    rutas = {"dataset": e["dataset"], "ledger": e["actual"] / "decisiones_aplicadas.json",
             "incidencias": e["cat"] / "incidencias_documentales.json", "bandeja": e["actual"] / "decisiones_pendientes.json"}
    return {n: hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None for n, p in rutas.items()}


def _preparar(e, guia="482816"):
    """Chofer operacional confirmado por una persona (precondición de la acción) y preview listo."""
    capa = CapaAccionesOperacionales(e["raiz"])
    assert _ejecutar(capa, "DOCUMENTO_CORREGIR_CHOFER_OPERACIONAL",
                     {"numero_guia": guia, "chofer": "142938162", "confirmar_discrepancia_rut": True}
                     )["estado"] == "APLICADA"
    preview = capa.previsualizar(ACCION, {"numero_guia": guia}, actor="B1", origen="B1")
    assert preview["estado"] == "PREVIEW", preview
    return capa, preview["token"]


@pytest.mark.parametrize("confirmante", TECNICAS)
def test_identidades_tecnicas_o_automaticas_no_son_confirmantes(confirmante):
    assert _confirmante_humano(confirmante) is False


@pytest.mark.parametrize("confirmante", ["JAVIER", "JAVIER_DESKTOP", "JAVIER_MBT", "maria.perez", "OPERADOR_1"])
def test_personas_son_confirmantes(confirmante):
    assert _confirmante_humano(confirmante) is True


def test_origen_sistema_nunca_es_confirmacion_humana():
    assert _confirmante_humano("JAVIER", origen="SISTEMA") is False


@pytest.mark.parametrize("confirmante", ["ATLAS_AUTOMATICO", "MOTOR_RECUPERACION_INCREMENTAL", "SISTEMA", "B1"])
def test_error_documental_aza_rechaza_confirmacion_automatica_sin_escribir(varas, confirmante):
    capa, token = _preparar(varas)
    antes = _huellas(varas)
    r = capa.ejecutar(token, actor="B1", origen="B1", confirmado_por=confirmante)
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "CONFIRMACION_REQUERIDA", r
    assert _huellas(varas) == antes
    assert all(a["accion"] != ACCION for a in capa.auditoria())
    assert not [i for i in AlmacenIncidenciasDocumentales(varas["cat"] / "incidencias_documentales.json").listar()
                if i.tipo_incidencia == "ERROR_DOCUMENTAL_AZA"]
    # El preview sigue vigente: una persona puede confirmarlo después.
    humana = capa.ejecutar(token, actor="B1", origen="B1", confirmado_por="JAVIER_DESKTOP")
    assert humana["estado"] == "APLICADA", humana


def test_error_documental_aza_con_origen_sistema_se_rechaza(varas):
    capa, token = _preparar(varas)
    antes = _huellas(varas)
    r = capa.ejecutar(token, actor="MOTOR", origen="SISTEMA", confirmado_por="JAVIER")
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "CONFIRMACION_REQUERIDA", r
    assert _huellas(varas) == antes


def test_error_documental_aza_confirmado_por_persona_aplica_con_auditoria(varas):
    antes = _filas(varas)
    capa, token = _preparar(varas)
    r = capa.ejecutar(token, actor="B1", origen="B1", confirmado_por="JAVIER")
    assert r["estado"] == "APLICADA" and r["persistencia_verificada"] is True, r
    [registro] = [a for a in capa.auditoria() if a["accion"] == ACCION]
    assert registro["confirmado_por"] == "JAVIER" and registro["origen"] == "B1"
    despues = _filas(varas)
    for campo in ("patente_tracto", "patente_rampla", "rut_chofer"):
        assert despues["482816"][campo] == antes["482816"][campo]  # lo impreso no cambia
    assert despues["500003"] == antes["500003"]


def test_otras_acciones_con_confirmacion_tampoco_aceptan_identidad_tecnica(entorno):  # noqa: F811
    capa = CapaAccionesOperacionales(entorno["raiz"])
    preview = capa.previsualizar("VIAJE_AGREGAR_OBSERVACION", {"guias": ["500001"], "texto": "REVISAR CARGA"},
                                 actor="B1", origen="B1")
    assert preview["estado"] == "PREVIEW", preview
    r = capa.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por="ATLAS_AUTOMATICO")
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "CONFIRMACION_REQUERIDA", r
