"""DOCUMENTO_RECUPERAR_MATERIAL lee primero la traza OCR guardada (caso 483897).

La acción releía el original con el proveedor del canal: por Desktop el worker
RapidOCR queda bloqueado y EasyOCR propuso «HORMIGON (DETALLE ILEGIBLE EN OCR)»
para una partida que RapidOCR ya había leído completa. Ahora reutiliza la
traza vigente del documento (misma ruta y referencia de imagen, backend
declarado, evidencia original disponible) con el extractor vigente; sin traza
válida o sin evidencia suficiente en ella se mantiene la relectura. Fixtures
sintéticas con las líneas OCR reales de 483897 y 483812; nunca G: ni OCR.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from atlas_core import acciones_operacionales as ao
from atlas_core import recuperacion_material as rm
from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.trazabilidad_ocr import ruta_traza_ocr
from tests.test_acciones_operacionales import _EscritorDisponible, entorno  # noqa: F401 -- fixture compartida

GUIA = "500001"
ARCHIVO = f"{GUIA}.jpeg"
_FIXTURES = Path(__file__).parent / "fixtures" / "trazas_ocr_aza"
MATERIAL_483897 = "B HORMIGON 10MM6M A630-420H (N)"
# Lo que EasyOCR leyó del original de 483897 por el canal Desktop.
RELECTURA_DEGRADADA = rm.material_desde_lineas(["DESCRIPCION", "HORMTGON 1OMN 6M"])
INTOCABLES = ("numero_guia", "numero_transporte", "peso_kg", "fecha", "chofer", "rut_chofer", "patente_tracto",
              "cliente", "obra_destino", "despachar_a_crudo", "direccion_entrega", "estado_ruta", "archivo",
              "estado_documental", "estado_operacional")


def _lineas_reales(guia):
    return json.loads((_FIXTURES / f"{guia}.json").read_text(encoding="utf-8"))["ocr"]["lineas"]


def _filas(entorno):
    with entorno["dataset"].open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _escribir_filas(entorno, filas):
    with entorno["dataset"].open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _traza(entorno, lineas=None, **cambios):
    traza = {"schema_version": 2, "procesado_en_utc": "2026-11-03T12:11:55+00:00",
             "imagen": {"referencia": ARCHIVO, "nombre_archivo": ARCHIVO},
             "ocr": {"backend": {"nombre": "atlas_core.ocr_manual.RapidOCRManualProvider", "version": None,
                                 "configuracion": None},
                     "lineas": lineas if lineas is not None else _lineas_reales("483897"),
                     "bloques": None, "estado_bloques": "NO_SOLICITADOS"},
             "identificadores_extraidos": {}}
    for clave, valor in cambios.items():
        destino, _, campo = clave.partition("__")
        (traza[destino] if campo else traza).__setitem__(campo or destino, valor)
    ruta = ruta_traza_ocr(entorno["raiz"] / "operacion" / "trazas_ocr", ARCHIVO)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(traza, ensure_ascii=False), encoding="utf-8")
    return ruta


@pytest.fixture
def doc(entorno, monkeypatch):
    """500001 sin material, con su original en una entrada Desktop; la
    relectura OCR se simula y se cuenta."""
    filas = _filas(entorno)
    for f in filas:
        if f["numero_guia"] == GUIA:
            f.update(descripcion_material="", tipo_carga="NO DETERMINADO", motivos_revision_documento="MATERIAL_AUSENTE",
                     peso_kg="27235", fecha="02-11-2026", estado_documental="OK", estado_operacional="OK")
        else:
            f.update(descripcion_material="ACERO 12MM", tipo_carga="FIERRO")
    _escribir_filas(entorno, filas)
    lote = entorno["raiz"] / "operacion" / "entradas" / "20261103_091113_a47dfe1c"
    lote.mkdir(parents=True)
    (lote / ARCHIVO).write_bytes(b"jpeg original")
    relecturas = []

    def relectura(ctx, archivo):
        relecturas.append(archivo)
        return RELECTURA_DEGRADADA

    monkeypatch.setattr(ao, "_leer_material_evidencia", relectura)
    entorno["relecturas"] = relecturas
    entorno["capa"] = CapaAccionesOperacionales(entorno["raiz"], fabrica_escritor=lambda: _EscritorDisponible())
    return entorno


def _preview(doc):
    return doc["capa"].previsualizar("DOCUMENTO_RECUPERAR_MATERIAL", {"numero_guia": GUIA, "referencia": "test"},
                                     actor="CLAUDE_CODE")


def _sha(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


# ------------------------------------------------------------ traza válida


def test_483897_recupera_desde_la_traza_sin_releer_ocr(doc):
    traza = _traza(doc)
    antes_traza = _sha(traza)
    p = _preview(doc)

    assert p["estado"] == "PREVIEW", p
    assert p["valor_propuesto"]["veredicto"] == rm.RECUPERAR
    assert p["valor_propuesto"]["descripcion_material"] == MATERIAL_483897
    assert p["valor_propuesto"]["tipo_carga"] == "BARRAS"
    assert p["valor_propuesto"]["motivos_revision_documento"] == ""
    assert p["valor_propuesto"]["fuente_lectura"] == "TRAZA_OCR_GUARDADA"
    assert p["valor_propuesto"]["traza_ocr"] == traza.name
    assert doc["relecturas"] == []
    assert _sha(traza) == antes_traza  # el OCR bruto no se toca


def test_483897_ejecutar_solo_cambia_material_y_conserva_traza_y_ledger(doc):
    traza = _traza(doc)
    antes = {f["numero_guia"]: f for f in _filas(doc)}
    ledger = _sha(doc["actual"] / "decisiones_aplicadas.json")
    sha_traza = _sha(traza)
    p = _preview(doc)

    r = doc["capa"].ejecutar(p["token"], actor="CLAUDE_CODE", confirmado_por="JAVIER",
                             accion_esperada="DOCUMENTO_RECUPERAR_MATERIAL")

    assert r["estado"] == "APLICADA", r
    despues = {f["numero_guia"]: f for f in _filas(doc)}
    assert despues[GUIA]["descripcion_material"] == MATERIAL_483897
    assert despues[GUIA]["tipo_carga"] == "BARRAS"
    assert despues[GUIA]["motivos_revision_documento"] == ""
    assert all(despues[GUIA][c] == antes[GUIA][c] for c in INTOCABLES)
    assert despues["500002"] == antes["500002"]
    assert _sha(doc["actual"] / "decisiones_aplicadas.json") == ledger
    assert _sha(traza) == sha_traza
    assert doc["relecturas"] == []


def test_483812_completa_solo_lo_legible_y_no_lo_marca_confiable(doc):
    filas = _filas(doc)
    for f in filas:
        if f["numero_guia"] == GUIA:
            f.update(descripcion_material="B HORMIGON 16MM7M A630-4201I (N)", tipo_carga="BARRAS",
                     motivos_revision_documento="OBRA_DESTINO_SIN_CORROBORAR | MATERIAL_OCR_NO_CONFIABLE")
    _escribir_filas(doc, filas)
    _traza(doc, lineas=_lineas_reales("483812"))

    p = _preview(doc)

    propuesto = p["valor_propuesto"]
    assert propuesto["veredicto"] == rm.COMPLETAR
    # La guía imprime seis partidas; la traza sólo permite tres.
    assert len(propuesto["material_items"]) == 3
    assert len(propuesto["descripcion_material"].split(" | ")) == 3
    assert "B HORMIGON 16MM7M A630-4201I (N)" in propuesto["descripcion_material"]
    # Los motivos no cambian: sigue MATERIAL_OCR_NO_CONFIABLE.
    assert "motivos_revision_documento" not in propuesto
    assert "MATERIAL_OCR_NO_CONFIABLE" in p["valor_actual"]["motivos_revision_documento"]
    assert doc["relecturas"] == []


def test_traza_cambiada_despues_del_preview_lo_invalida(doc):
    _traza(doc)
    p = _preview(doc)
    _traza(doc, procesado_en_utc="2026-11-03T13:00:00+00:00")

    r = doc["capa"].ejecutar(p["token"], actor="CLAUDE_CODE", confirmado_por="JAVIER",
                             accion_esperada="DOCUMENTO_RECUPERAR_MATERIAL")

    assert r["estado"] == "PREVIEW_OBSOLETO"
    assert next(f for f in _filas(doc) if f["numero_guia"] == GUIA)["descripcion_material"] == ""


# ------------------------------------------------------------ sin traza válida: relectura


def test_sin_traza_mantiene_la_relectura(doc):
    p = _preview(doc)

    assert doc["relecturas"] == [ARCHIVO]
    assert p["valor_propuesto"]["fuente_lectura"] == "RELECTURA_OCR"
    assert p["valor_propuesto"]["lectura_ocr"] == RELECTURA_DEGRADADA.descripcion


@pytest.mark.parametrize("cambios", [
    {"imagen__referencia": "otra/500001.jpeg"},           # identidad: otro documento
    {"ocr__backend": {"nombre": ""}},                      # procedencia no declarada
    {"ocr__lineas": []},                                   # sin lectura
    {"ocr__lineas": ["DESCRIPCION", 7]},                   # lectura corrupta
    {"ocr__bloques": [{"texto": "B HORMIGON", "bounding_box": [[0, 0]]}]},  # bloques corruptos
])
def test_traza_invalida_mantiene_la_relectura(doc, cambios):
    _traza(doc, **cambios)

    p = _preview(doc)

    assert doc["relecturas"] == [ARCHIVO]
    assert p["valor_propuesto"]["fuente_lectura"] == "RELECTURA_OCR"


def test_traza_ilegible_mantiene_la_relectura(doc):
    ruta = _traza(doc)
    ruta.write_text("{no es json", encoding="utf-8")

    _preview(doc)

    assert doc["relecturas"] == [ARCHIVO]


def test_traza_sin_evidencia_suficiente_mantiene_la_relectura(doc):
    _traza(doc, lineas=["DESCRIPCION", "Coladas: 2618015402", "TIPODEDOCUMENTO"])

    p = _preview(doc)

    assert doc["relecturas"] == [ARCHIVO]
    assert p["valor_propuesto"]["fuente_lectura"] == "RELECTURA_OCR"


def test_traza_que_solo_sincroniza_mantiene_la_relectura(doc):
    # Mismo material que la fila: la traza (sin bloques) no mejora nada.
    filas = _filas(doc)
    for f in filas:
        if f["numero_guia"] == GUIA:
            f.update(descripcion_material=MATERIAL_483897, tipo_carga="NO DETERMINADO", motivos_revision_documento="")
    _escribir_filas(doc, filas)
    _traza(doc)

    p = _preview(doc)

    assert doc["relecturas"] == [ARCHIVO]
    assert p["valor_propuesto"]["fuente_lectura"] == "RELECTURA_OCR"


def test_sin_evidencia_original_no_usa_la_traza(doc, monkeypatch):
    _traza(doc)
    for archivo in (doc["raiz"] / "operacion" / "entradas").rglob(ARCHIVO):
        archivo.unlink()
    monkeypatch.undo()  # relectura real: falla por evidencia ausente, sin OCR

    p = _preview(doc)

    assert p["estado"] == "RECHAZADA" and p["codigo"] == "PRECONDICION_FALLIDA"


# ------------------------------------------------------------ decisión humana


def test_correccion_humana_previa_no_se_sobrescribe(doc):
    _traza(doc)
    ledger = doc["actual"] / "decisiones_aplicadas.json"
    ledger.write_text(json.dumps({"schema_version": 1, "aplicaciones": [{
        "campo": "descripcion_material", "valor": "B HORMIGON 10MM 6M A630-420H (N)",
        "documento": {"archivo": ARCHIVO, "numero_guia": GUIA}}]}), encoding="utf-8")
    dataset = _sha(doc["dataset"])

    p = _preview(doc)

    assert p["estado"] == "RECHAZADA" and p["codigo"] == "CAMPO_FIJADO_POR_DECISION_HUMANA"
    assert doc["relecturas"] == []
    assert _sha(doc["dataset"]) == dataset
