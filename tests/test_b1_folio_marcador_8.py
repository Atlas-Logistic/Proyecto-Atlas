"""Caso real 8484553 -> 484553 (Mobile, 11-11-2026, transporte 0000369979).

RapidOCR leyó el "Nº" de la guía como "8" ("N8484553"). DOCUMENTO_CORREGIR_NUMERO_GUIA
sólo admitía el marcador leído como "9" y B1 no tenía ninguna frase para corregir
el folio de una guía existente: Desktop terminaba en el intérprete de
incidencias con dos acciones "(no reconocida)".
"""
from __future__ import annotations

import json

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.b1_operador import OperadorB1, interpretar_determinista
from tests.test_acciones_operacionales import (  # noqa: F401
    _escribir_dataset, _fila, _filas_dataset, _sha, _sin_mantenimiento_real, _sin_reporte_real, entorno,
)

ARCHIVO = "mobile/bffe71a1-sintetico/original.jpg"
FRASES = [
    "Corrige el número de guía 8484553 a 484553. No modifiques ningún otro dato del viaje.",
    "La guía 8484553 tiene como número correcto 484553",
]


def _guia_real(**extra):
    return _fila("8484553", archivo=ARCHIVO, numero_transporte="0000369979", chofer="LUIS VARAS",
                 patente_tracto="DD2494", patente_rampla="JB8529", cliente="EBEMA SA", obra_destino="EBEMA SA",
                 descripcion_material="B HORMIGON 8MM12MA630-4201(N)", tipo_carga="BARRAS",
                 motivos_revision_documento="MATERIAL_OCR_NO_CONFIABLE", hora_entrada_aza="No encontrado",
                 estado_ruta="RUTA_CALCULADA", distancia_km="13.17", estado_operacional="OK", **extra)


def _ledger_correcciones(entorno):
    ruta = entorno["actual"] / "decisiones_aplicadas.json"
    aplicaciones = json.loads(ruta.read_text(encoding="utf-8"))["aplicaciones"] if ruta.is_file() else []
    return [a for a in aplicaciones if a.get("tipo") == "CORRECCION_DOCUMENTAL_OPERADOR"]


# --- Acción --------------------------------------------------------------------

def test_marcador_8_corrige_solo_el_folio_y_deja_la_lectura_en_el_ledger(entorno, monkeypatch):
    _escribir_dataset(entorno, [_guia_real(), _fila("500002")])
    antes = _filas_dataset(entorno)
    bandeja_antes = _sha(entorno["actual"] / "decisiones_pendientes.json")
    forzadas, reportes = [], []
    _sin_mantenimiento_real(monkeypatch, forzadas)
    _sin_reporte_real(monkeypatch, reportes)
    capa = CapaAccionesOperacionales(entorno["raiz"])

    preview = capa.previsualizar("DOCUMENTO_CORREGIR_NUMERO_GUIA",
                                 {"numero_guia": "8484553", "numero_guia_corregido": "484553", "archivo": ARCHIVO},
                                 actor="JAVIER")
    assert preview["estado"] == "PREVIEW", preview
    assert preview["requiere_confirmacion"] is True
    assert (preview["valor_actual"], preview["valor_propuesto"]) == ({"numero_guia": "8484553"}, {"numero_guia": "484553"})
    assert _filas_dataset(entorno) == antes  # la vista previa no escribe

    resultado = capa.ejecutar(preview["token"], actor="JAVIER", confirmado_por="JAVIER")
    assert resultado["estado"] == "APLICADA", resultado
    despues = _filas_dataset(entorno)
    assert despues[ARCHIVO]["numero_guia"] == "484553"
    assert {k: v for k, v in despues[ARCHIVO].items() if k != "numero_guia"} == {
        k: v for k, v in antes[ARCHIVO].items() if k != "numero_guia"}
    assert despues["500002.jpeg"] == antes["500002.jpeg"]
    assert forzadas == [] and resultado["reconciliacion"] is None
    assert _sha(entorno["actual"] / "decisiones_pendientes.json") == bandeja_antes
    assert [(a["campo"], a["valor_documental"], a["valor_corregido"], a["documento"]["archivo"])
            for a in _ledger_correcciones(entorno)] == [("numero_guia", "8484553", "484553", ARCHIVO)]


def test_marcador_8_conserva_las_protecciones_del_9(entorno):
    _escribir_dataset(entorno, [_guia_real(), _fila("7484553", archivo="siete.jpeg"), _fila("500001")])
    capa = CapaAccionesOperacionales(entorno["raiz"])

    def preview(actual, nuevo, archivo=""):
        parametros = {"numero_guia": actual, "numero_guia_corregido": nuevo}
        if archivo:
            parametros["archivo"] = archivo
        return capa.previsualizar("DOCUMENTO_CORREGIR_NUMERO_GUIA", parametros, actor="JAVIER")

    assert preview("8484553", "484554")["codigo"] == "PRECONDICION_FALLIDA"   # no es "8" + folio
    assert preview("7484553", "484553")["codigo"] == "PRECONDICION_FALLIDA"   # 7 no es un marcador
    assert preview("500001", "500002")["codigo"] == "PRECONDICION_FALLIDA"    # folio normal
    assert preview("8484553", "4845531")["codigo"] == "PARAMETRO_INVALIDO"
    assert preview("8484553", "084553")["codigo"] == "PARAMETRO_INVALIDO"
    # El folio corregido ya pertenece a otro documento.
    _escribir_dataset(entorno, [_guia_real(), _fila("484553", archivo="otro.jpeg")])
    duplicado = preview("8484553", "484553", ARCHIVO)
    assert duplicado["codigo"] == "PRECONDICION_FALLIDA" and "otro documento" in duplicado["mensaje"]
    # Tarjetas pendientes sobre el folio leído.
    _escribir_dataset(entorno, [_fila("8500001", archivo="x.jpeg")])
    bandeja = json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    bandeja["decisiones"][0]["documento"]["numero_guia"] = "8500001"
    (entorno["actual"] / "decisiones_pendientes.json").write_text(json.dumps(bandeja), encoding="utf-8")
    assert "tarjetas pendientes" in preview("8500001", "500001")["mensaje"]


# --- Intérprete B1 -------------------------------------------------------------

@pytest.mark.parametrize("frase", FRASES + [
    "corrige el numero de la guia 8484553 a 484553",
    "Corrige el folio de la guía 8484553 por 484553",
    "La guía 8484553 tiene como folio correcto 484553, sin cambiar nada más",
])
def test_frases_de_correccion_de_folio(frase):
    intencion = interpretar_determinista(frase)
    assert intencion is not None and intencion.accion == "DOCUMENTO_CORREGIR_NUMERO_GUIA"
    assert (intencion.parametros["numero_guia"], intencion.parametros["numero_guia_corregido"]) == ("8484553", "484553")
    assert "archivo" not in intencion.parametros  # se resuelve contra el dataset, nunca se adivina aquí


@pytest.mark.parametrize("frase", [
    "Corrige el número de guía 8484553 a 484553 y cambia el material a B HORMIGON 8MM",
    "Corrige el número de guía 8484553 a 484553. Cambia el chofer a LUIS REYES",
    "La guía 8484553 tiene como número correcto 484553 y el transporte 0000369979",
    "Corrige el número de guía 8484553 a 4845531",
    "Corrige el número de guía 8484553 a 48455",
    "¿Corrige el número de guía 8484553 a 484553?",
    "La guía 8484553 tiene como número 484553",
    "Corrige la guía 8484553 a 484553",
])
def test_frases_ambiguas_o_compuestas_no_se_interpretan_como_folio(frase):
    intencion = interpretar_determinista(frase)
    assert intencion is None or intencion.accion != "DOCUMENTO_CORREGIR_NUMERO_GUIA"


# --- B1 de extremo a extremo -----------------------------------------------------

def _b1(entorno, monkeypatch, filas):
    _escribir_dataset(entorno, filas)
    _sin_reporte_real(monkeypatch, [])
    _sin_mantenimiento_real(monkeypatch, [])
    capa = CapaAccionesOperacionales(entorno["raiz"])
    return capa, OperadorB1(entorno["raiz"], capa=capa)


@pytest.mark.parametrize("frase", FRASES)
def test_b1_prepara_vista_previa_y_solo_escribe_con_confirmacion(entorno, monkeypatch, frase):
    capa, b1 = _b1(entorno, monkeypatch, [_guia_real(), _fila("500002")])
    antes = _filas_dataset(entorno)
    bytes_antes = entorno["dataset"].read_bytes()

    preview = b1.atender("prueba", frase)
    assert preview["estado"] == "PREVIEW_PENDIENTE", preview
    assert preview["accion"] == "DOCUMENTO_CORREGIR_NUMERO_GUIA"
    assert "8484553" in preview["mensaje"] and "484553" in preview["mensaje"]
    assert entorno["dataset"].read_bytes() == bytes_antes

    resultado = b1.atender("prueba", "si")
    assert resultado["estado"] == "EJECUTADA", resultado
    despues = _filas_dataset(entorno)
    assert despues[ARCHIVO]["numero_guia"] == "484553"
    # Material, transporte, chofer, vehículos, ruta, horarios y estados intactos.
    assert {k: v for k, v in despues[ARCHIVO].items() if k != "numero_guia"} == {
        k: v for k, v in antes[ARCHIVO].items() if k != "numero_guia"}
    assert despues["500002.jpeg"] == antes["500002.jpeg"]
    asientos = _ledger_correcciones(entorno)
    assert len(asientos) == 1 and asientos[0]["confirmado_por"] == "JAVIER"
    assert asientos[0]["documento"]["archivo"] == ARCHIVO
    assert capa.auditoria()[-1]["resultado"] == "APLICADA"


def test_b1_cancelar_no_escribe(entorno, monkeypatch):
    _capa, b1 = _b1(entorno, monkeypatch, [_guia_real()])
    bytes_antes = entorno["dataset"].read_bytes()
    assert b1.atender("prueba", FRASES[0])["estado"] == "PREVIEW_PENDIENTE"
    assert b1.atender("prueba", "no")["estado"] == "CANCELADA"
    assert b1.atender("prueba", "si")["estado"] != "EJECUTADA"
    assert entorno["dataset"].read_bytes() == bytes_antes
    assert _ledger_correcciones(entorno) == []


@pytest.mark.parametrize(("filas", "fragmento"), [
    ([_fila("500002")], "No encontré la guía 8484553"),
    ([_guia_real(), _fila("8484553", archivo="duplicado.jpeg")], "aparece en 2 documentos"),
])
def test_b1_no_elige_documento_ni_inventa_guia(entorno, monkeypatch, filas, fragmento):
    _capa, b1 = _b1(entorno, monkeypatch, filas)
    bytes_antes = entorno["dataset"].read_bytes()
    respuesta = b1.atender("prueba", FRASES[1])
    assert respuesta["estado"] == "ACLARACION_REQUERIDA" and fragmento in respuesta["mensaje"], respuesta
    assert b1.atender("prueba", "si")["estado"] != "EJECUTADA"
    assert entorno["dataset"].read_bytes() == bytes_antes


@pytest.mark.parametrize(("filas", "frase"), [
    # El folio corregido ya es de otro documento.
    ([_guia_real(), _fila("484553", archivo="otro.jpeg")], FRASES[0]),
    # Corrección incompatible: no es el "Nº" absorbido.
    ([_guia_real()], "Corrige el número de guía 8484553 a 484554"),
    ([_fila("500001")], "Corrige el número de guía 500001 a 500002"),
])
def test_b1_rechaza_correcciones_incompatibles_sin_escribir(entorno, monkeypatch, filas, frase):
    _capa, b1 = _b1(entorno, monkeypatch, filas)
    bytes_antes = entorno["dataset"].read_bytes()
    respuesta = b1.atender("prueba", frase)
    assert respuesta["estado"] == "RECHAZADA" and respuesta["codigo"] == "PRECONDICION_FALLIDA", respuesta
    assert b1.atender("prueba", "si")["estado"] != "EJECUTADA"
    assert entorno["dataset"].read_bytes() == bytes_antes


@pytest.mark.parametrize("frase", FRASES)
def test_desktop_deriva_la_orden_a_b1_y_no_a_incidencias(entorno, monkeypatch, frase):
    # Desktop consulta primero en solo lectura; sólo NO_INTERPRETADA cae al
    # intérprete de incidencias ("(no reconocida)").
    _capa, b1 = _b1(entorno, monkeypatch, [_guia_real()])
    assert b1.consultar(frase, derivar_operacionales=True)["estado"] == "REQUIERE_OPERADOR"
    assert b1.consultar(frase)["estado"] == "RECHAZADA"
