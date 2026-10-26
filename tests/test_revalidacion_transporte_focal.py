"""TRANSPORTE_REVALIDAR nunca reconcilia el dataset completo (26/10/2026).

Caso real: recuperar el material de 483106 (transporte 0000366054) con la
reconciliación global recalculaba rutas/destinos/origen de 29 viajes
ajenos. La reconciliación posterior a revalidar un transporte queda acotada
a sus guías; sin alcance demostrable no se reextrae ni se escribe nada.
Sintéticos, nunca tocan G:\\."""
from __future__ import annotations

import json

import pytest

from atlas_core import reprocesamiento_reparador as m
from atlas_core.revalidacion_documental import _leer_filas
from tests.lectura_ocr_reparador import con_lectura
from tests.test_revalidacion_por_transporte import (
    _crear_imagen, _escribir_dataset, _escribir_ledger, _fila_base, _raiz, _stub_reconciliacion,
)

OBJETIVO, AJENO = "0000366054", "0000999999"


def _dataset(raiz, *, guia_objetivo="483106", guia_ajena="999999"):
    _crear_imagen(raiz, "483106.jpg")
    _crear_imagen(raiz, "OTRO.jpg")
    _escribir_dataset(raiz, [
        _fila_base(archivo="483106.jpg", numero_guia=guia_objetivo, numero_transporte=OBJETIVO, peso_kg="19307"),
        _fila_base(archivo="OTRO.jpg", numero_guia=guia_ajena, numero_transporte=AJENO, peso_kg="12345"),
    ])
    _escribir_ledger(raiz, [])


def _marca(raiz, transportes):
    (raiz / "operacion" / "actual" / m.NOMBRE_MARCA_RECONCILIACION_PENDIENTE).write_text(
        json.dumps({"transportes": transportes}), encoding="utf-8")


def test_reconciliacion_tras_revalidar_se_limita_a_las_guias_del_transporte(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path); _dataset(raiz)
    monkeypatch.setattr(m, "procesar_archivo", con_lectura(lambda *a, **kw: {"peso_kg": "9307"}))
    llamadas = []; _stub_reconciliacion(monkeypatch, llamadas)

    resultado = m.revalidar_documentos_por_transporte(
        raiz_atlas=raiz, numero_transporte=OBJETIVO, dry_run=False, proveedor=object())

    assert len(llamadas) == 1
    # Nunca global: `guias_objetivo=None` recalcularía todos los viajes.
    assert llamadas[0]["guias_objetivo"] == {"483106"}
    assert resultado["alcance_reconciliacion"] == ["483106"] and resultado["impedimento"] == ""


def test_marca_pendiente_de_otro_transporte_amplia_el_alcance_solo_a_ese_transporte(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path); _dataset(raiz)
    _marca(raiz, [AJENO])
    monkeypatch.setattr(m, "procesar_archivo", con_lectura(lambda *a, **kw: {"peso_kg": "19307"}))
    llamadas = []; _stub_reconciliacion(monkeypatch, llamadas)

    m.revalidar_documentos_por_transporte(raiz_atlas=raiz, numero_transporte=OBJETIVO, dry_run=False, proveedor=object())

    assert llamadas[0]["guias_objetivo"] == {"483106", "999999"}


def test_sin_alcance_demostrable_no_reextrae_escribe_ni_reconcilia(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path); _dataset(raiz); _marca(raiz, "no-es-lista")
    impedimento = "MARCA_RECONCILIACION_ILEGIBLE"
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    antes = dataset.read_bytes()
    ocr = []
    monkeypatch.setattr(m, "procesar_archivo", con_lectura(lambda *a, **kw: ocr.append(1) or {"peso_kg": "9307"}))
    llamadas = []; _stub_reconciliacion(monkeypatch, llamadas)

    resultado = m.revalidar_documentos_por_transporte(
        raiz_atlas=raiz, numero_transporte=OBJETIVO, dry_run=False, proveedor=object())

    assert resultado["impedimento"] == impedimento
    assert ocr == [] and llamadas == [] and resultado["dataset_escrito"] is False
    assert dataset.read_bytes() == antes


def test_completar_reconciliacion_pendiente_tambien_es_focal(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path); _dataset(raiz)
    _marca(raiz, [OBJETIVO])
    llamadas = []; _stub_reconciliacion(monkeypatch, llamadas)

    resultado = m.completar_reconciliacion_pendiente(raiz_atlas=raiz, puede_escribir=lambda: True)

    assert llamadas[0]["guias_objetivo"] == {"483106"} and resultado["reconciliacion_pendiente"] is False


def test_completar_reconciliacion_con_marca_ilegible_no_reconcilia(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path); _dataset(raiz)
    _marca(raiz, "no-es-lista")
    llamadas = []; _stub_reconciliacion(monkeypatch, llamadas)

    resultado = m.completar_reconciliacion_pendiente(raiz_atlas=raiz, puede_escribir=lambda: True)

    assert llamadas == [] and resultado["impedimento"] == "MARCA_RECONCILIACION_ILEGIBLE"
    assert (raiz / "operacion" / "actual" / m.NOMBRE_MARCA_RECONCILIACION_PENDIENTE).exists()


def test_fila_ajena_queda_intacta(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path); _dataset(raiz)
    monkeypatch.setattr(m, "procesar_archivo", con_lectura(lambda *a, **kw: {"peso_kg": "9307"}))
    _stub_reconciliacion(monkeypatch, [])

    m.revalidar_documentos_por_transporte(raiz_atlas=raiz, numero_transporte=OBJETIVO, dry_run=False, proveedor=object())

    ajena = next(f for f in _leer_filas(raiz / "operacion" / "actual" / "analisis_completo_guias.csv")
                 if f["numero_transporte"] == AJENO)
    assert ajena["peso_kg"] == "12345" and ajena["numero_guia"] == "999999"


def test_documento_propio_sin_guia_se_relee_y_sin_recuperarla_no_escribe(tmp_path, monkeypatch):
    """26/10/2026: el documento sin número de guía del propio transporte se
    relee; si la relectura no lo recupera, no se escribe ni se reconcilia."""
    raiz = _raiz(tmp_path); _dataset(raiz, guia_objetivo="No encontrado")
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    antes = dataset.read_bytes()
    ocr = []
    monkeypatch.setattr(m, "procesar_archivo", con_lectura(lambda *a, **kw: ocr.append(1) or {"peso_kg": "9307"}))
    llamadas = []; _stub_reconciliacion(monkeypatch, llamadas)

    resultado = m.revalidar_documentos_por_transporte(
        raiz_atlas=raiz, numero_transporte=OBJETIVO, dry_run=False, proveedor=object())

    assert ocr and resultado["impedimento"] == "DOCUMENTO_SIN_NUMERO_DE_GUIA"
    assert llamadas == [] and resultado["dataset_escrito"] is False and dataset.read_bytes() == antes


def test_documento_propio_sin_guia_recuperada_se_escribe_y_reconcilia_esa_guia(tmp_path, monkeypatch):
    """Casos 483169/483170/483211: la relectura recupera el número de guía."""
    raiz = _raiz(tmp_path); _dataset(raiz, guia_objetivo="No encontrado")
    monkeypatch.setattr(m, "procesar_archivo", con_lectura(lambda *a, **kw: {"numero_guia": "483169"}))
    llamadas = []; _stub_reconciliacion(monkeypatch, llamadas)

    resultado = m.revalidar_documentos_por_transporte(
        raiz_atlas=raiz, numero_transporte=OBJETIVO, dry_run=False, proveedor=object())

    filas = {f["numero_transporte"]: f for f in _leer_filas(raiz / "operacion" / "actual" / "analisis_completo_guias.csv")}
    assert resultado["impedimento"] == "" and filas[OBJETIVO]["numero_guia"] == "483169"
    assert llamadas[0]["guias_objetivo"] == {"483169"} and filas[AJENO]["numero_guia"] == "999999"
