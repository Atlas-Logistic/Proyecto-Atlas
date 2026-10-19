"""Regresiones focales AZA: RETIRA no puede convertirse en DESPACHAR A.

Las escenas reproducen sólo los bloques ya disponibles del documento. No
invocan motores OCR, catálogos, decisiones ni rutas reales.
"""
from __future__ import annotations

import pytest

from atlas_core.ocr import BloqueOCR
from atlas_core.rutas.destino_entrega import despachar_a_documental


def _bloque(texto: str, x: int, y: int, ancho: int | None = None) -> BloqueOCR:
    ancho = ancho if ancho is not None else max(36, len(texto) * 9)
    return BloqueOCR(
        texto=texto,
        bounding_box=((x, y), (x + ancho, y), (x + ancho, y + 20), (x, y + 20)),
        confianza=0.99,
    )


def _escena_aza(*, chofer: str, direccion: str) -> list[BloqueOCR]:
    """Dirección debajo de DESPACHAR A; RETIRA queda antes en orden OCR."""
    return [
        _bloque("DESPACHAR A", 20, 100, 110),
        # El nombre de RETIRA aparece al lado de la etiqueta de despacho por
        # el orden de lectura, aunque su etiqueta propia está más a la derecha.
        _bloque(chofer, 150, 100),
        _bloque("RETIRA", 440, 100, 70),
        _bloque(direccion, 25, 128),
        _bloque("RUT CHOFER", 440, 128, 105),
        _bloque("17.576.134-9", 560, 128),
        _bloque("PATENTE", 440, 156, 75),
        _bloque("BPHR67", 530, 156),
        _bloque("FECHA LLEGADA", 440, 184, 125),
        _bloque("12-10-2026", 580, 184),
    ]


@pytest.mark.parametrize(
    ("guia", "chofer", "direccion"),
    [
        ("482507", "CARLOS PEREZ", "AVENIDA EL SALTO 1200 HUECHURABA"),
        ("482513", "MARIO GONZALEZ", "CAMINO LO ECHEVERS 550 QUILICURA"),
    ],
)
def test_guias_aza_recuperan_despachar_a_geometrico_y_no_aceptan_retira(
    guia, chofer, direccion,
):
    # La lectura lineal contaminada toma el nombre de RETIRA. La evidencia
    # geométrica suficiente recupera exclusivamente el valor bajo DESPACHAR A.
    textos = [
        "DESPACHAR A", f": {chofer}", "RETIRA", chofer,
        "RUT CHOFER", "17.576.134-9", "PATENTE", "BPHR67",
        "FECHA LLEGADA", "12-10-2026",
    ]
    resultado = despachar_a_documental(
        textos, _escena_aza(chofer=chofer, direccion=direccion), chofer_resuelto=chofer,
    )

    assert resultado == direccion, guia
    assert chofer not in resultado
    assert "PATENTE" not in resultado
    assert "FECHA" not in resultado


def test_direccion_legitima_que_contiene_el_nombre_del_chofer_no_se_rechaza():
    chofer = "JUAN PEREZ"
    direccion = "PASAJE JUAN PEREZ 123 SANTIAGO"
    resultado = despachar_a_documental(
        ["DESPACHAR A", f": {direccion}", "RETIRA", chofer],
        [_bloque("DESPACHAR A", 20, 100), _bloque(direccion, 150, 100), _bloque("RETIRA", 440, 100)],
        chofer_resuelto=chofer,
    )
    assert resultado == direccion


def test_sin_evidencia_geometrica_no_inventa_un_destino_alternativo():
    chofer = "CARLOS PEREZ"
    # No existe dirección bajo la etiqueta; el nombre contaminado no se
    # convierte en una dirección inventada ni se sustituye por un catálogo.
    resultado = despachar_a_documental(
        ["DESPACHAR A", f": {chofer}", "RETIRA", chofer, "PATENTE", "BPHR67"],
        [_bloque("DESPACHAR A", 20, 100), _bloque(chofer, 150, 100), _bloque("RETIRA", 440, 100)],
        chofer_resuelto=chofer,
    )
    assert resultado == ""
