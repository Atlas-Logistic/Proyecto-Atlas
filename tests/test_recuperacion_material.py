"""DOCUMENTO_RECUPERAR_MATERIAL y `atlas_core.recuperacion_material`
(26/10/2026). Líneas OCR reales de 483106/483138/482247/482909; dataset y
catálogos sintéticos (nunca G:\\)."""
from __future__ import annotations

import csv
import json

import pytest

from atlas_core import acciones_operacionales as ao
from atlas_core import recuperacion_material as rm
from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.procesamiento_masivo import COLUMNAS
from tests.test_acciones_operacionales import _EscritorDisponible, _fila, _sha, entorno  # noqa: F401

LINEAS_483106 = ["DESCRIPCION", "CANTIDAD", "CODIGO", "BHORMIGON16MM 11MA630-420H(N)", "27.569110002930"]
MATERIAL_483106 = "B HORMIGON 16MM 11MA630-420H(N)"


def _fila_material(**extra):
    fila = {c: "" for c in COLUMNAS}
    fila.update({"archivo": "mobile/x/original.jpg", "numero_guia": "483106", "descripcion_material": "",
                 "tipo_carga": "NO DETERMINADO", "motivos_revision_documento": "PATENTE_SIN_HOMOLOGAR | MATERIAL_AUSENTE",
                 "metricas_procesamiento_json": json.dumps({"ocr_seg": 1.5}, sort_keys=True),
                 "despachar_a_crudo": "LA ESTERA 525 SANTIAGO", "estado_ruta": "REQUIERE_REVISION"})
    fila.update(extra)
    return fila


# --- lectura: mismas reglas que procesar_archivo -----------------------------

def test_lectura_reutiliza_extractor_clasificador_y_motivos():
    lectura = rm.material_desde_lineas(LINEAS_483106)
    assert lectura.descripcion == MATERIAL_483106 and lectura.tipo_carga == "BARRAS"
    assert rm.MOTIVOS_MATERIAL[0] not in lectura.motivos
    assert rm.material_desde_lineas(["DESCRIPCION", "CANTIDAD"]).motivos[0] == "MATERIAL_AUSENTE"


# --- evaluación: nunca pisa material correcto ni completo por parcial ---------

def test_material_ausente_se_recupera_y_solo_cambian_campos_de_material():
    fila = _fila_material()
    veredicto, valores = rm.evaluar_recuperacion(fila, rm.material_desde_lineas(LINEAS_483106), [])
    assert veredicto == rm.RECUPERAR
    assert set(valores) <= {"descripcion_material", "tipo_carga", "metricas_procesamiento_json", "motivos_revision_documento"}
    assert valores["descripcion_material"] == MATERIAL_483106 and valores["tipo_carga"] == "BARRAS"
    # El motivo ajeno se conserva; sólo se retira el de material.
    assert valores["motivos_revision_documento"] == "PATENTE_SIN_HOMOLOGAR"
    metricas = json.loads(valores["metricas_procesamiento_json"])
    assert metricas["ocr_seg"] == 1.5 and metricas["material_items"][0]["descripcion_ocr"] == MATERIAL_483106


def test_segunda_evaluacion_tras_aplicar_no_cambia_nada():
    fila = _fila_material()
    lectura = rm.material_desde_lineas(LINEAS_483106)
    _, valores = rm.evaluar_recuperacion(fila, lectura, [])
    assert rm.evaluar_recuperacion({**fila, **valores}, lectura, []) == (rm.SIN_CAMBIOS, {})


def test_material_correcto_distinto_no_se_sobrescribe():
    fila = _fila_material(descripcion_material="B HORMIGON 22MM 12M A630-420H (N)", motivos_revision_documento="")
    assert rm.evaluar_recuperacion(fila, rm.material_desde_lineas(LINEAS_483106), []) == (rm.SE_CONSERVA, {})


def test_material_parcial_se_completa_conservando_el_item_actual():
    """482247: faltaba el segundo ítem (BHORMIGON pegado)."""
    actual = "B HORMIGON 8MM12MA630-420H（N）"
    fila = _fila_material(descripcion_material=actual, motivos_revision_documento="")
    lectura = rm.material_desde_lineas([actual, "BHORMIGON 10MM12MA630-420H （N)"])
    veredicto, valores = rm.evaluar_recuperacion(fila, lectura, [])
    assert veredicto == rm.COMPLETAR and valores["descripcion_material"].startswith(actual + " | ")


def test_lectura_parcial_nunca_reemplaza_material_completo():
    completo = "B HORMIGON 8MM 12M A630-420H (N) | B HORMIGON 10MM 12M A630-420H (N)"
    fila = _fila_material(descripcion_material=completo, motivos_revision_documento="")
    lectura = rm.material_desde_lineas(["B HORMIGON 8MM 12M A630-420H (N)"])
    assert rm.evaluar_recuperacion(fila, lectura, []) == (rm.SE_CONSERVA, {})


def test_familia_generica_se_mejora_solo_con_la_misma_familia():
    lectura = rm.material_desde_lineas(["B HORMIGON 10MM 12M A630-420H (N)"])
    assert rm.evaluar_recuperacion(_fila_material(descripcion_material="HORMIGON"), lectura, [])[0] == rm.MEJORAR
    assert rm.evaluar_recuperacion(_fila_material(descripcion_material="CHATARRA"), lectura, [])[0] == rm.SE_CONSERVA


def test_lectura_sin_evidencia_confiable_no_escribe():
    lectura = rm.material_desde_lineas(["DESCRIPCION", "CANTIDAD"])
    assert rm.evaluar_recuperacion(_fila_material(), lectura, []) == (rm.SIN_EVIDENCIA, {})


@pytest.mark.parametrize("campo", ["descripcion_material", "tipo_carga"])
def test_decision_del_ledger_sobre_material_protege_el_documento(campo):
    aplicaciones = [{"documento": {"archivo": "mobile/x/original.jpg"}, "campo": campo, "actor": "JAVIER"}]
    resultado = rm.evaluar_recuperacion(_fila_material(), rm.material_desde_lineas(LINEAS_483106), aplicaciones)
    assert resultado == (rm.PROTEGIDO_POR_DECISION, {})


# --- escritura focal en el dataset ------------------------------------------

def _dataset(tmp_path, filas):
    ruta = tmp_path / "analisis_completo_guias.csv"
    with ruta.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";"); w.writeheader(); w.writerows(filas)
    return ruta


def _filas(ruta):
    with ruta.open(encoding="utf-8-sig", newline="") as f:
        return {r["archivo"]: r for r in csv.DictReader(f, delimiter=";")}


def test_aplicar_solo_toca_la_fila_y_campos_autorizados(tmp_path):
    objetivo, ajena = _fila_material(), _fila_material(archivo="otra.jpg", numero_guia="999999")
    ruta = _dataset(tmp_path, [objetivo, ajena])
    _, valores = rm.evaluar_recuperacion(objetivo, rm.material_desde_lineas(LINEAS_483106), [])
    rm.aplicar_en_dataset(ruta, archivo=objetivo["archivo"], fila_base=objetivo, valores=valores)
    filas = _filas(ruta)
    assert filas["otra.jpg"] == ajena
    assert {c for c in objetivo if objetivo[c] != filas[objetivo["archivo"]][c]} == set(valores)


def test_fila_modificada_concurrentemente_no_se_escribe(tmp_path):
    objetivo = _fila_material()
    ruta = _dataset(tmp_path, [{**objetivo, "estado_ruta": "RUTA_CALCULADA"}])  # otro escritor cambió la fila
    antes = ruta.read_bytes()
    with pytest.raises(rm.ErrorRecuperacionMaterial, match="cambió desde el preview"):
        rm.aplicar_en_dataset(ruta, archivo=objetivo["archivo"], fila_base=objetivo,
                              valores={"descripcion_material": MATERIAL_483106})
    assert ruta.read_bytes() == antes


def test_campos_no_autorizados_se_rechazan(tmp_path):
    objetivo = _fila_material()
    ruta = _dataset(tmp_path, [objetivo])
    with pytest.raises(rm.ErrorRecuperacionMaterial, match="no autorizados"):
        rm.aplicar_en_dataset(ruta, archivo=objetivo["archivo"], fila_base=objetivo,
                              valores={"despachar_a_crudo": "OTRA"})


# --- acción operacional ------------------------------------------------------

@pytest.fixture
def material_ocr(monkeypatch):
    lectura = {"actual": rm.material_desde_lineas(LINEAS_483106)}
    monkeypatch.setattr(ao, "_leer_material_evidencia", lambda ctx, archivo: lectura["actual"])
    return lectura


def _vaciar_material(entorno, guia="500001"):
    filas = list(csv.DictReader(entorno["dataset"].open(encoding="utf-8-sig", newline=""), delimiter=";"))
    for f in filas:
        if f["numero_guia"] == guia:
            f.update(descripcion_material="", tipo_carga="NO DETERMINADO", motivos_revision_documento="MATERIAL_AUSENTE")
    with entorno["dataset"].open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";"); w.writeheader(); w.writerows(filas)


def test_accion_recupera_material_sin_ledger_ni_otras_filas_y_es_idempotente(entorno, material_ocr):
    _vaciar_material(entorno)
    ledger, bandeja = _sha(entorno["actual"] / "decisiones_aplicadas.json"), _sha(entorno["actual"] / "decisiones_pendientes.json")
    antes = _filas(entorno["dataset"])
    capa = CapaAccionesOperacionales(entorno["raiz"], fabrica_escritor=lambda: _EscritorDisponible())
    preview = capa.previsualizar("DOCUMENTO_RECUPERAR_MATERIAL", {"numero_guia": "500001"}, actor="CLAUDE_CODE")
    assert preview["valor_propuesto"]["veredicto"] == rm.RECUPERAR
    resultado = capa.ejecutar(preview["token"], actor="CLAUDE_CODE", confirmado_por="JAVIER")
    assert resultado["estado"] == "APLICADA"
    despues = _filas(entorno["dataset"])
    assert despues["500002.jpeg"] == antes["500002.jpeg"]
    cambiadas = {c for c in antes["500001.jpeg"] if antes["500001.jpeg"][c] != despues["500001.jpeg"][c]}
    assert cambiadas == {"descripcion_material", "tipo_carga", "metricas_procesamiento_json", "motivos_revision_documento"}
    # Ningún resultado OCR queda como decisión humana; la bandeja no cambia.
    assert _sha(entorno["actual"] / "decisiones_aplicadas.json") == ledger
    assert _sha(entorno["actual"] / "decisiones_pendientes.json") == bandeja
    # Segunda ejecución: sin cambios ni duplicados.
    segundo = capa.previsualizar("DOCUMENTO_RECUPERAR_MATERIAL", {"numero_guia": "500001"}, actor="CLAUDE_CODE")
    assert segundo["estado"] == "SIN_CAMBIOS" and segundo["requiere_confirmacion"] is False
    assert _filas(entorno["dataset"]) == despues


def test_accion_con_cambio_concurrente_queda_obsoleta_sin_escribir(entorno, material_ocr):
    _vaciar_material(entorno)
    capa = CapaAccionesOperacionales(entorno["raiz"], fabrica_escritor=lambda: _EscritorDisponible())
    preview = capa.previsualizar("DOCUMENTO_RECUPERAR_MATERIAL", {"numero_guia": "500001"}, actor="CLAUDE_CODE")
    filas = list(csv.DictReader(entorno["dataset"].open(encoding="utf-8-sig", newline=""), delimiter=";"))
    filas[0]["estado_ruta"] = "REQUIERE_REVISION"  # otro escritor tocó la fila
    with entorno["dataset"].open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";"); w.writeheader(); w.writerows(filas)
    antes = entorno["dataset"].read_bytes()
    resultado = capa.ejecutar(preview["token"], actor="CLAUDE_CODE", confirmado_por="JAVIER")
    assert resultado["estado"] == "PREVIEW_OBSOLETO" and entorno["dataset"].read_bytes() == antes


def test_accion_con_escritor_ocupado_no_escribe(entorno, material_ocr):
    _vaciar_material(entorno)

    class Ocupado(_EscritorDisponible):
        def adquirir(self):
            return False

    capa = CapaAccionesOperacionales(entorno["raiz"], fabrica_escritor=lambda: Ocupado())
    preview = capa.previsualizar("DOCUMENTO_RECUPERAR_MATERIAL", {"numero_guia": "500001"}, actor="CLAUDE_CODE")
    antes = entorno["dataset"].read_bytes()
    resultado = capa.ejecutar(preview["token"], actor="CLAUDE_CODE", confirmado_por="JAVIER")
    assert resultado.get("codigo") == "ESCRITOR_OCUPADO" and entorno["dataset"].read_bytes() == antes


def test_accion_respeta_decision_humana_registrada(entorno, material_ocr):
    _vaciar_material(entorno)
    (entorno["actual"] / "decisiones_aplicadas.json").write_text(json.dumps({"schema_version": 1, "aplicaciones": [
        {"documento": {"archivo": "500001.jpeg", "numero_guia": "500001"}, "campo": "descripcion_material",
         "actor": "JAVIER"}]}), encoding="utf-8")
    capa = CapaAccionesOperacionales(entorno["raiz"], fabrica_escritor=lambda: _EscritorDisponible())
    resultado = capa.previsualizar("DOCUMENTO_RECUPERAR_MATERIAL", {"numero_guia": "500001"}, actor="CLAUDE_CODE")
    assert resultado.get("codigo") == "CAMPO_FIJADO_POR_DECISION_HUMANA"
