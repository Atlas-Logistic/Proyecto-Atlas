"""Regresiones AZA sobre trazas focales de las fotos originales.

Las trazas fueron obtenidas una sola vez sobre copias aisladas de 482507 y
482513. Estas pruebas sólo deserializan esos bloques: no invocan OCR ni tocan
datos operacionales, catálogos o decisiones.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas_core.ocr import BloqueOCR
from atlas_core.rutas.destino_entrega import despachar_a_documental


_TRAZAS = Path(__file__).parent / "fixtures" / "trazas_ocr_aza"


def _cargar_bloques(guia: str) -> tuple[list[str], list[BloqueOCR]]:
    contenido = json.loads((_TRAZAS / f"{guia}.json").read_text(encoding="utf-8"))
    ocr = contenido["ocr"]
    assert ocr["estado_bloques"] == "DISPONIBLES"
    bloques = [
        BloqueOCR(
            texto=bloque["texto"],
            bounding_box=tuple(tuple(punto) for punto in bloque["bounding_box"]),
            confianza=bloque["confianza"],
        )
        for bloque in ocr["bloques"]
    ]
    return ocr["lineas"], bloques


@pytest.mark.parametrize(
    ("guia", "chofer", "esperado"),
    [
        ("482507", "PATRICIO VILLAGRA MUÑOZ", "PDTE RIESCO 5903 LAS CONDES"),
        ("482513", "LEANDRO TOLEDO", "VIA MORADA 6480 VITACURA"),
    ],
)
def test_trazas_reales_recuperan_el_destino_documental(guia, chofer, esperado):
    lineas, bloques = _cargar_bloques(guia)

    resultado = despachar_a_documental(lineas, bloques, chofer_resuelto=chofer)

    assert resultado == esperado
    assert chofer not in resultado
    assert "LLEGADA" not in resultado
    assert "PATENTE" not in resultado


def test_prefijo_del_chofer_en_retira_no_sobrevive_como_destino_lineal():
    # El caso real 482507 contiene sólo los dos primeros nombres en RETIRA.
    # Con una dirección válida disponible, esa lectura debe ser descartable.
    lineas, bloques = _cargar_bloques("482507")
    resultado = despachar_a_documental(
        ["DESPACHAR A", "PATRICIO VILLAGRA"],
        bloques,
        chofer_resuelto="PATRICIO VILLAGRA MUÑOZ",
    )

    assert resultado == "PDTE RIESCO 5903 LAS CONDES"
