"""Etiqueta DESPACHAR A con el comienzo perdido por el recorte de la foto
("SPACHAR A": faltan sólo "DE", caso real que lo motivó). La tolerancia es
de la ETIQUETA, nunca del valor, y conserva las exigencias geométricas
(margen izquierdo + zona de entrega). Recortes más severos siguen exigiendo
un duplicado documental del valor. Bloques sintéticos."""
from __future__ import annotations

from types import SimpleNamespace

from atlas_core.extractor import _extraer_despachar_a_geometrico

VALOR = "AV LOS ALAMOS 120 SANTIAGO COLINA"


def _bloque(texto, x1, y1, x2, y2, confianza=0.99):
    return SimpleNamespace(texto=texto, bounding_box=[[x1, y1], [x2, y1], [x2, y2], [x1, y2]], confianza=confianza)


def _documento(etiqueta, *, x_etiqueta=0, con_zona=True, duplicado=False):
    bloques = [
        _bloque("GUIA DE DESPACHO", 480, 110, 650, 125),
        _bloque(etiqueta, x_etiqueta, 720, x_etiqueta + 65, 735),
        _bloque(VALOR, 115, 718, 315, 733),
    ]
    if con_zona:
        bloques += [_bloque("RETIRA", 423, 716, 467, 730), _bloque("JUAN PEREZ", 491, 716, 573, 730),
                    _bloque("PATENTE", 424, 740, 477, 752)]
    if duplicado:
        bloques.append(_bloque(VALOR, 160, 300, 360, 314))
    return bloques


def test_despachar_a_completo():
    assert _extraer_despachar_a_geometrico(_documento("DESPACHAR A"))["valor"] == VALOR


def test_spachar_a_recortada_extrae_el_valor_asociado_sin_duplicado():
    resultado = _extraer_despachar_a_geometrico(_documento("SPACHAR A"))
    assert resultado["valor"] == VALOR  # el valor inmediatamente asociado, intacto


def test_espachar_a_sigue_reconocida():
    assert _extraer_despachar_a_geometrico(_documento("ESPACHAR A"))["valor"] == VALOR


def test_spachar_a_lejos_del_margen_o_fuera_de_la_zona_de_entrega_no_es_etiqueta():
    assert _extraer_despachar_a_geometrico(_documento("SPACHAR A", x_etiqueta=200)) == {}
    assert _extraer_despachar_a_geometrico(_documento("SPACHAR A", con_zona=False)) == {}


def test_recorte_mas_severo_sigue_exigiendo_duplicado_documental():
    assert _extraer_despachar_a_geometrico(_documento("PACHAR A")) == {}
    assert _extraer_despachar_a_geometrico(_documento("PACHAR A", duplicado=True))["valor"] == VALOR


def test_texto_no_relacionado_no_activa_la_regla():
    for texto in ("SPACHARA", "SPA CHAR A", "DESPACHO", "CHARLA A", "SPACHAR"):
        assert _extraer_despachar_a_geometrico(_documento(texto)) == {}, texto
