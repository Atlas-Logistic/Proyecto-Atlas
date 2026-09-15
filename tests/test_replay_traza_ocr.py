"""Contrato del replay puro de trazas OCR; no usa imágenes ni proveedores."""
from __future__ import annotations

import copy
import json

import pytest

from atlas_core.replay_traza_ocr import (
    ErrorReplayTrazaOCR,
    reconstruir_bloques_desde_traza,
    reproducir_extraccion_geometrica_desde_traza,
)
from atlas_core.trazabilidad_ocr import construir_traza_ocr, persistir_traza_ocr
from atlas_core.ocr import BloqueOCR


def _bloque(texto, x, y, ancho=None, alto=18):
    ancho = ancho if ancho is not None else max(30, len(texto) * 8)
    return BloqueOCR(texto, ((x, y), (x + ancho, y), (x + ancho, y + alto), (x, y + alto)), 0.9)


def _traza(bloques, referencia="lote/guia.jpeg"):
    return construir_traza_ocr(referencia_imagen=referencia, textos=[b.texto for b in bloques], bloques=bloques)


def _bloques_472437_sinteticos():
    return [
        _bloque("SEÑOR(ES)", 114, 348, 102, 45),
        _bloque("GIRO", 116, 390, 54, 32),
        _bloque("AGF ACEROS", 260, 375, 92, 18),
        _bloque("DE", 356, 381, 22, 14),
        _bloque("CHILE", 384, 381, 46, 16),
        _bloque("SPA", 436, 385, 28, 14),
        _bloque("OBRA DESTINO", 648, 438, 114, 24),
        _bloque("CONSTRUCTORA", 829, 436, 111, 24),
        _bloque("IGNACIO", 947, 439, 64, 14),
        _bloque("HURTADO", 1017, 439, 66, 16),
        _bloque("CODIGO", 121, 295, 70, 40),
        _bloque("CLIENTE", 180, 309, 65, 40),
    ]


def _bloques_472211_sinteticos(con_duplicado):
    bloques = [
        _bloque("AR A", 0, 1175, 35, 14), _bloque("RETIRA", 511, 1167, 54, 16),
        _bloque("PATENTE", 509, 1179, 70, 20), _bloque("ESTERA", 129, 1173, 54, 16),
        _bloque("634", 189, 1173, 26, 14), _bloque("LANPA", 221, 1173, 46, 14),
    ]
    if con_duplicado:
        bloques += [
            _bloque("ESTERA", 191, 613, 52, 14), _bloque("634", 249, 611, 26, 14),
            _bloque("LAMPA", 167, 631, 44, 14),
        ]
    return bloques


def _bloques_464453_sinteticos():
    return [_bloque("GUIA DE DESPAC", 570, 272, 169, 30), _bloque("N? 464453", 622, 334, 98, 26)]


def test_replay_valido_reconstruye_bloques_y_declara_que_no_hizo_ocr():
    traza = _traza(_bloques_464453_sinteticos())
    resultado = reproducir_extraccion_geometrica_desde_traza(traza, referencia_esperada="lote/guia.jpeg")

    assert resultado["extraccion"]["numero_guia"] == "464453"
    assert resultado["diagnostico"]["bloques_reconstruidos"] == 2
    assert resultado["diagnostico"]["sin_ocr"] is True
    assert resultado["diagnostico"]["sin_io"] is True


def test_writer_productivo_json_y_replay_son_directamente_compatibles(tmp_path):
    """No fabrica un dict de sidecar: usa el writer real y relee su JSON."""
    referencia = "lote\\subcarpeta\\guia.jpeg"
    ruta = persistir_traza_ocr(
        directorio=tmp_path,
        referencia_imagen=referencia,
        textos=["GUIA DE DESPAC", "N? 464453"],
        bloques=_bloques_464453_sinteticos(),
        identificadores={"numero_guia": "464453"},
    )
    sidecar_real = json.loads(ruta.read_text(encoding="utf-8"))

    bloques = reconstruir_bloques_desde_traza(
        sidecar_real, referencia_esperada="lote/subcarpeta/guia.jpeg"
    )
    resultado = reproducir_extraccion_geometrica_desde_traza(
        sidecar_real, referencia_esperada="lote/subcarpeta/guia.jpeg"
    )

    assert isinstance(bloques[0], BloqueOCR)
    assert bloques[0].bounding_box == ((570.0, 272.0), (739.0, 272.0), (739.0, 302.0), (570.0, 302.0))
    assert resultado["extraccion"]["numero_guia"] == "464453"


def test_replay_rechaza_bloques_no_disponibles():
    traza = _traza([], referencia="lote/a.jpeg")
    traza["ocr"]["bloques"] = None
    traza["ocr"]["estado_bloques"] = "NO_DISPONIBLES"

    with pytest.raises(ErrorReplayTrazaOCR, match="no tiene bloques"):
        reconstruir_bloques_desde_traza(traza, referencia_esperada="lote/a.jpeg")


def test_replay_rechaza_caja_invalida():
    traza = _traza(_bloques_464453_sinteticos())
    traza["ocr"]["bloques"][0]["bounding_box"] = [[1, 1], [2, 2], [3, 3]]

    with pytest.raises(ErrorReplayTrazaOCR, match="cuatro puntos"):
        reconstruir_bloques_desde_traza(traza, referencia_esperada="lote/guia.jpeg")


def test_replay_rechaza_referencia_inconsistente():
    traza = _traza(_bloques_464453_sinteticos())

    with pytest.raises(ErrorReplayTrazaOCR, match="referencia"):
        reconstruir_bloques_desde_traza(traza, referencia_esperada="otro/guia.jpeg")


def test_replay_472437_reutiliza_geometria_productiva_para_cliente_y_obra():
    resultado = reproducir_extraccion_geometrica_desde_traza(
        _traza(_bloques_472437_sinteticos()), referencia_esperada="lote/guia.jpeg"
    )

    assert resultado["extraccion"]["cliente"] == "AGF ACEROS DE CHILE SPA"
    assert resultado["extraccion"]["obra destino"] == "CONSTRUCTORA IGNACIO HURTADO"


def test_replay_472211_acepta_despacho_recortado_solo_con_corroboracion_independiente():
    con_respaldo = reproducir_extraccion_geometrica_desde_traza(
        _traza(_bloques_472211_sinteticos(True)), referencia_esperada="lote/guia.jpeg"
    )
    sin_respaldo = reproducir_extraccion_geometrica_desde_traza(
        _traza(_bloques_472211_sinteticos(False)), referencia_esperada="lote/guia.jpeg"
    )

    assert con_respaldo["extraccion"]["despachar_a_crudo"] == "ESTERA 634 LANPA"
    assert con_respaldo["diagnostico"]["evidencia"]["despachar_a"]["senal_calidad_captura"] == "CAPTURA_RECORTADA_POSIBLE"
    assert "despachar_a_crudo" not in sin_respaldo["extraccion"]


def test_replay_464453_acepta_guia_solo_dentro_de_ventana_geometrica():
    dentro = reproducir_extraccion_geometrica_desde_traza(
        _traza(_bloques_464453_sinteticos()), referencia_esperada="lote/guia.jpeg"
    )
    fuera_bloques = [_bloque("GUIA DE DESPAC", 570, 272, 169, 30), _bloque("464453", 50, 900, 60, 20)]
    fuera = reproducir_extraccion_geometrica_desde_traza(
        _traza(fuera_bloques), referencia_esperada="lote/guia.jpeg"
    )

    assert dentro["extraccion"]["numero_guia"] == "464453"
    assert "numero_guia" not in fuera["extraccion"]


def test_replay_no_muta_la_traza_recibida():
    traza = _traza(_bloques_464453_sinteticos())
    original = copy.deepcopy(traza)

    reproducir_extraccion_geometrica_desde_traza(traza, referencia_esperada="lote/guia.jpeg")

    assert traza == original
