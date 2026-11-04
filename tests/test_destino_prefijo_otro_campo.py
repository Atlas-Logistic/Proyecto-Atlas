"""P0 contaminación del destino OCR (caso real 483939, RapidOCR, 04/11/2026).

La lectura lineal antepuso el valor de RETIRA (chofer) a DESPACHAR A:
"PATRICK ORTIZ MAESTRA LIDIA TORRES 92 SANTIAGO RECOLETA". La lectura
geométrica, con las cajas de la misma fila separadas, dio la dirección
correcta. `despachar_a_documental` sólo prefiere la geométrica cuando la
lineal es exactamente <chofer ya resuelto> + <geométrica completa>.

El fixture contiene lecturas RapidOCR de originales Mobile de guías
operacionales reales (ninguna del lote inicial). El replay es idéntico a
producción: los valores sin corrección coinciden con los persistidos."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas_core.ocr import BloqueOCR
from atlas_core.rapidocr_adapter import adaptar_bloques_rapidocr, filas_resultado_rapidocr
from atlas_core.rutas.destino_entrega import _geometrico_tras_prefijo_chofer, despachar_a_documental

_FIXTURE = Path(__file__).parent / "fixtures" / "destino_prefijo" / "lecturas_rapidocr_operacionales.json"
_DOCUMENTOS = {d["numero_guia"]: d for d in json.loads(_FIXTURE.read_text(encoding="utf-8"))["documentos"]}

_DIRECCION_483939 = "MAESTRA LIDIA TORRES 92 SANTIAGO RECOLETA"
_LINEAL_483939 = "PATRICK ORTIZ " + _DIRECCION_483939


def _bloques(guia: str) -> list[BloqueOCR]:
    filas = filas_resultado_rapidocr(_DOCUMENTOS[guia]["filas_rapidocr"])
    return [b.a_bloque_atlas() for b in adaptar_bloques_rapidocr(filas)]


def _destino(guia: str, *, con_bloques: bool = True, chofer: str | None = None) -> str:
    bloques = _bloques(guia)
    return despachar_a_documental(
        [b.texto for b in bloques],
        bloques if con_bloques else None,
        chofer_resuelto=_DOCUMENTOS[guia]["chofer_resuelto"] if chofer is None else chofer,
    )


def test_483939_prefiere_direccion_geometrica_sin_chofer_antepuesto():
    assert _destino("483939") == _DIRECCION_483939


def test_483939_sin_bloques_no_cambia():
    # Sin lectura geométrica no hay respaldo OCR: se conserva la lineal.
    assert _destino("483939", con_bloques=False) == _LINEAL_483939


@pytest.mark.parametrize("chofer", ["", "JOSE LAZCANO", "PATRICK", "PATRICIO ORTEGA"])
def test_483939_sin_evidencia_de_campo_ajeno_no_cambia(chofer):
    assert _destino("483939", chofer=chofer) == _LINEAL_483939


@pytest.mark.parametrize("guia, esperado", [
    ("482107", "PANAMERICANA NORTE 22650 SANTIAGO LAMPA"),
    ("483897", "CAMINO A MELIPILLA 10800 SANTIAGO MAIPU"),
    ("483940", _DIRECCION_483939),
    ("483941", _DIRECCION_483939),
])
def test_destinos_validos_operacionales_no_cambian(guia, esperado):
    assert _destino(guia) == esperado


@pytest.mark.parametrize("lineal, geometrico, chofer, esperado", [
    (_LINEAL_483939, _DIRECCION_483939, "PATRICK ORTIZ", True),
    # OCR tolerante en el nombre y chofer con segundo apellido cortado.
    ("PATRIK ORTIZ " + _DIRECCION_483939, _DIRECCION_483939, "PATRICK ORTIZ", True),
    (_LINEAL_483939, _DIRECCION_483939, "PATRICK ORTIZ SOTO", True),
    # La geometría debe ser exactamente la cola de la lineal.
    (_LINEAL_483939, "MAESTRA LIDIA TORRES 92", "PATRICK ORTIZ", False),
    (_LINEAL_483939, "MAESTRA LIDIA TORRES 93 SANTIAGO RECOLETA", "PATRICK ORTIZ", False),
    # Un solo token del chofer no basta.
    ("ORTIZ " + _DIRECCION_483939, _DIRECCION_483939, "PATRICK ORTIZ", False),
    ("PATRICK " + _DIRECCION_483939, _DIRECCION_483939, "PATRICK", False),
    # El prefijo no puede exceder al chofer.
    ("PATRICK ORTIZ SOTO " + _DIRECCION_483939, _DIRECCION_483939, "PATRICK ORTIZ", False),
    # Calle que lleva el nombre del chofer: lineal y geométrica iguales.
    ("PASAJE JUAN PEREZ 123", "PASAJE JUAN PEREZ 123", "JUAN PEREZ", False),
    ("JUAN PEREZ 123 SANTIAGO", "JUAN PEREZ 123 SANTIAGO", "JUAN PEREZ", False),
    # Geométrica sin numeración: no se reemplaza.
    ("PATRICK ORTIZ AV KENNEDY", "AV KENNEDY", "PATRICK ORTIZ", False),
    ("", _DIRECCION_483939, "PATRICK ORTIZ", False),
    (_LINEAL_483939, "", "PATRICK ORTIZ", False),
])
def test_regla_prefijo_chofer_es_exacta(lineal, geometrico, chofer, esperado):
    assert _geometrico_tras_prefijo_chofer(lineal, geometrico, chofer) is esperado
