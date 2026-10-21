"""Regresion de tarjetas latentes: solo datos sinteticos locales."""
import csv
import json
import pytest
from test_acciones_operacionales import entorno, _fila, _bandeja
from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.decisiones_pendientes import generar_artefacto
from atlas_core.revalidacion_documental import (
    regenerar_decisiones_obra_faltantes_sin_ocr,
    regenerar_decisiones_vehiculo_faltantes_sin_ocr,
    reconciliar_bandeja_decisiones,
)
from atlas_core.alcance_revalidacion import alcance_guias
from atlas_core.procesamiento_masivo import COLUMNAS

AJENAS = {"475510", "482631", "482487", "482597"}


def preparar(entorno):
    filas = [
        _fila("482673", despachar_a_crudo="", numero_transporte="T-OBJETIVO",
              motivos_revision_documento="FECHA_SIN_CORROBORAR", indicador_revision="REVISAR"),
        _fila("475510", obra_destino="ARVACERO NAICO SA", numero_transporte="T-475510",
              motivos_revision_documento="OBRA_DESTINO_SIN_CORROBORAR", indicador_revision="REVISAR"),
        _fila("482631", obra_destino="IORRZS OCARANZA LTDA", numero_transporte="T-482631",
              motivos_revision_documento="OBRA_DESTINO_SIN_CORROBORAR", indicador_revision="REVISAR"),
        _fila("482487", patente_tracto="JB6878", numero_transporte="T-482487",
              motivos_revision_documento="PATENTE_SIN_HOMOLOGAR", indicador_revision="REVISAR"),
        _fila("482597", patente_tracto="JF9575", numero_transporte="T-482597",
              motivos_revision_documento="PATENTE_SIN_HOMOLOGAR", indicador_revision="REVISAR"),
    ]
    with entorno["dataset"].open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";")
        w.writeheader(); w.writerows(filas)
    nuevas = regenerar_decisiones_obra_faltantes_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["cat"], decisiones_pendientes=[])
    nuevas = regenerar_decisiones_vehiculo_faltantes_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["cat"], decisiones_pendientes=nuevas)
    assert {d["documento"]["numero_guia"] for d in nuevas} == AJENAS
    return nuevas


@pytest.mark.parametrize("existentes", [False, True])
def test_corregir_482673_no_publica_ni_modifica_cuatro_ajenas(entorno, existentes):
    latentes = preparar(entorno)
    previas = latentes if existentes else []
    generar_artefacto(ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["cat"], decisiones=previas)
    antes = _bandeja(entorno)["decisiones"]
    csv_antes = list(csv.DictReader(entorno["dataset"].open(encoding="utf-8-sig"), delimiter=";"))
    cat_antes = {p.name: p.read_bytes() for p in entorno["cat"].glob("*.json")}
    capa = CapaAccionesOperacionales(entorno["raiz"])
    preview = capa.previsualizar("DOCUMENTO_CORREGIR_CAMPO", {
        "numero_guia": "482673", "campo": "despachar_a_crudo",
        "valor": "AVDA IRARRAZAVAL 5497 SANTIAGO NUNOA",
    }, actor="TEST")
    assert preview["estado"] == "PREVIEW", preview
    resultado = capa.ejecutar(preview["token"], actor="TEST", confirmado_por="TEST")
    assert resultado["estado"] == "APLICADA", resultado
    assert _bandeja(entorno)["decisiones"] == antes
    despues = list(csv.DictReader(entorno["dataset"].open(encoding="utf-8-sig"), delimiter=";"))
    assert despues[1:] == csv_antes[1:]
    assert despues[0]["despachar_a_crudo"] == "AVDA IRARRAZAVAL 5497 SANTIAGO NUNOA"
    assert despues[0]["motivos_revision_documento"] == "FECHA_SIN_CORROBORAR"
    assert {p.name: p.read_bytes() for p in entorno["cat"].glob("*.json")} == cat_antes


@pytest.mark.parametrize("objetivo", [set(), {"475510", "482487"}])
def test_bandeja_genera_solo_objetivos_y_conserva_revision_ajena(entorno, objetivo):
    latentes = preparar(entorno)
    existente = next(d for d in latentes if d["documento"]["numero_guia"] == "482597")
    existente["contexto"] = {"nota_prueba": "conservar sin enriquecer ni retirar"}
    generar_artefacto(ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["cat"], decisiones=[existente])
    reconciliar_bandeja_decisiones(raiz_atlas=entorno["raiz"], guias_objetivo=objetivo)
    publicadas = _bandeja(entorno)["decisiones"]
    assert {d["documento"]["numero_guia"] for d in publicadas} == objetivo | {"482597"}
    assert next(d for d in publicadas if d["documento"]["numero_guia"] == "482597") == existente


@pytest.mark.parametrize("explicito", [None, {"475510", "482487"}])
def test_alcance_heredado_no_se_amplia_al_reconciliar(entorno, explicito):
    preparar(entorno)
    generar_artefacto(ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["cat"], decisiones=[])
    with alcance_guias(entorno["dataset"], {"475510"}):
        reconciliar_bandeja_decisiones(raiz_atlas=entorno["raiz"], guias_objetivo=explicito)
    assert {d["documento"]["numero_guia"] for d in _bandeja(entorno)["decisiones"]} == {"475510"}


@pytest.mark.parametrize("detector", [
    "regenerar_decisiones_obra_faltantes_sin_ocr",
    "regenerar_decisiones_vehiculo_faltantes_sin_ocr",
])
def test_error_real_del_detector_no_se_oculta_ni_publica(entorno, monkeypatch, detector):
    import atlas_core.revalidacion_documental as modulo
    preparar(entorno)
    generar_artefacto(ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["cat"], decisiones=[])
    ruta = entorno["actual"] / "decisiones_pendientes.json"
    antes = ruta.read_bytes()
    def fallar(**kwargs):
        raise RuntimeError("error real del detector")
    monkeypatch.setattr(modulo, detector, fallar)
    with pytest.raises(RuntimeError, match="error real del detector"):
        reconciliar_bandeja_decisiones(raiz_atlas=entorno["raiz"], guias_objetivo={"482673"})
    assert ruta.read_bytes() == antes
