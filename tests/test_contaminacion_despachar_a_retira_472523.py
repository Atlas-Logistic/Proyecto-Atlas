"""Bloque CONTAMINACIÓN ENTRE CAMPOS -- DESPACHAR A / RETIRA (caso real
472523, obra "EMPRESA CONST SIGRO", cliente PRODALAM SA).

Causa raíz: el mismo intercalado de columnas de PaddleOCR que ya cubren
`_despachar_a_lineal_contaminado` (etiqueta ajena) y
`limpiar_sufijo_rut_pegado` (RUT ajeno pegado) tiene una TERCERA forma:
el VALOR NOMINAL de OTRO campo estructural -- aquí, el nombre del chofer
impreso bajo la etiqueta RETIRA -- queda pegado, en el texto lineal,
justo después de la etiqueta "DESPACHAR A", mientras la dirección real
apareció ANTES, fuera de orden. Ninguna de las dos reglas anteriores lo
detecta: el nombre de una persona no ES una etiqueta estructural
conocida ni un RUT.

Reglas GENERALES (forma del layout, nunca el texto/guía literal del caso
que reveló el bug): ninguno de los tests de este archivo usa "PATRICK
ORTIZ" ni la dirección real de 472523 -- ver
`test_regresion_472523_direccion_real_no_se_confunde_con_chofer` para la
única excepción deliberada (cobertura de regresión exacta del caso
real, además de la cobertura general)."""
from __future__ import annotations

from atlas_core.extractor import _despachar_a_lineal_contaminado
from atlas_core.ocr import BloqueOCR
from atlas_core.rutas.destino_entrega import resolver_entrega_documento


def _bloque(texto, x, y, ancho=None, alto=18):
    ancho = ancho if ancho is not None else max(30, len(texto) * 8)
    return BloqueOCR(
        texto=texto,
        bounding_box=((x, y), (x + ancho, y), (x + ancho, y + alto), (x, y + alto)),
        confianza=0.95,
    )


# ============================================================
# 1 -- _despachar_a_lineal_contaminado detecta la colisión con el chofer
# ============================================================


def test_valor_identico_al_chofer_resuelto_se_marca_contaminado():
    assert _despachar_a_lineal_contaminado("JUAN PEREZ", valor_chofer_resuelto="JUAN PEREZ") is True


def test_valor_identico_ignorando_acentos_y_espacios_tambien_se_marca_contaminado():
    """`_texto_simple` normaliza acentos/espacios en ambos lados -- una
    variante OCR menor del mismo nombre sigue siendo la misma colisión."""
    assert _despachar_a_lineal_contaminado("  Juan   Pérez ", valor_chofer_resuelto="JUAN PEREZ") is True


def test_sin_chofer_resuelto_comportamiento_identico_a_antes():
    """`valor_chofer_resuelto` es opcional -- ausente (default ""), la
    función se comporta exactamente como antes de este bloque."""
    assert _despachar_a_lineal_contaminado("JUAN PEREZ") is False


def test_direccion_real_no_se_confunde_con_chofer_distinto():
    """Control -- una dirección real, que NO coincide con el chofer
    resuelto, nunca se marca contaminada por esta regla."""
    assert _despachar_a_lineal_contaminado("AV SIEMPRE VIVA 742 SANTIAGO", valor_chofer_resuelto="JUAN PEREZ") is False


def test_direccion_que_por_coincidencia_menciona_al_chofer_como_substring_no_se_confunde():
    """La colisión exige coincidencia EXACTA del valor completo
    (normalizado) -- una dirección real que simplemente CONTIENE el
    nombre del chofer como subcadena (coincidencia parcial) nunca se
    trata como contaminada; sólo values estructuralmente ajenos, nunca
    un match parcial que podría ser una calle real con ese nombre."""
    assert _despachar_a_lineal_contaminado(
        "PASAJE JUAN PEREZ 123 SANTIAGO", valor_chofer_resuelto="JUAN PEREZ"
    ) is False


def test_etiquetas_y_rut_ajenos_conocidos_siguen_detectandose_igual():
    """Control de no-regresión -- las dos reglas previas (etiqueta
    estructural / RUT completo) siguen intactas con el nuevo parámetro
    opcional presente pero sin coincidir."""
    assert _despachar_a_lineal_contaminado("PATENTE", valor_chofer_resuelto="JUAN PEREZ") is True
    assert _despachar_a_lineal_contaminado("14293816-2", valor_chofer_resuelto="JUAN PEREZ") is True


# ============================================================
# 2 -- resolver_entrega_documento recupera la dirección real por
# geometría cuando el lineal absorbió el nombre del chofer (forma
# GENERAL del layout AZA real: DESPACHAR A a la izquierda con su valor
# a la derecha en la misma fila; RETIRA más a la derecha con SU valor
# aún más a la derecha -- el texto lineal, leído en orden de aparición,
# entrelaza ambas columnas).
# ============================================================


def _zona_entrega_con_chofer_intercalado(direccion, nombre_chofer):
    """Reproduce, con valores sintéticos, la MISMA geometría relativa
    del caso real 472523 (nunca sus valores): DESPACHAR A (izquierda) +
    su dirección a la derecha; RETIRA (más a la derecha, misma fila) +
    su nombre de chofer aún más a la derecha; PATENTE/RUT CHOFER debajo,
    como apoyo geométrico ya usado por `_extraer_despachar_a_geometrico`."""
    return [
        _bloque(f": {direccion}", 234, 1092, 380),
        _bloque("RETIRA", 730, 1083, 66),
        _bloque("DESPACHAR A", 55, 1093, 123),
        _bloque(f": {nombre_chofer}", 827, 1084, 155),
        _bloque("PATENTE", 728, 1103, 88),
        _bloque("RUT CHOFER", 54, 1113, 113),
    ]


def _textos_lineal_con_chofer_intercalado(direccion, nombre_chofer, rut_chofer, patente):
    """Mismo orden de lectura lineal que el caso real 472523: la
    dirección real aparece ANTES de su propia etiqueta, y el nombre del
    chofer queda pegado justo DESPUÉS de "DESPACHAR A"."""
    return [
        f": {direccion}",
        "RETIRA",
        "DESPACHAR A",
        f": {nombre_chofer}",
        "PATENTE",
        "RUT CHOFER",
        f":{rut_chofer}",
        f": {patente}",
    ]


def test_despachar_a_recupera_la_direccion_real_cuando_el_lineal_absorbio_el_chofer():
    direccion = "AV SIEMPRE VIVA 742 SANTIAGO PROVIDENCIA"
    chofer = "JUAN PEREZ"
    textos = _textos_lineal_con_chofer_intercalado(direccion, chofer, "11111111-1", "AA1234")
    bloques = _zona_entrega_con_chofer_intercalado(direccion, chofer)

    resultado = resolver_entrega_documento(
        textos, [], None, bloques=bloques, chofer_resuelto=chofer,
    )
    assert resultado["despachar_a_crudo"] == direccion


def test_sin_chofer_resuelto_el_lineal_contaminado_queda_tal_cual_comportamiento_previo():
    """Control de no-regresión: sin `chofer_resuelto` (parámetro
    ausente), el resultado es idéntico al comportamiento previo a este
    bloque -- el valor lineal contaminado (nombre, no dirección) queda
    tal cual, porque ninguna de las reglas anteriores lo detecta."""
    direccion = "AV SIEMPRE VIVA 742 SANTIAGO PROVIDENCIA"
    chofer = "JUAN PEREZ"
    textos = _textos_lineal_con_chofer_intercalado(direccion, chofer, "11111111-1", "AA1234")
    bloques = _zona_entrega_con_chofer_intercalado(direccion, chofer)

    resultado = resolver_entrega_documento(textos, [], None, bloques=bloques)
    assert resultado["despachar_a_crudo"] == chofer


def test_direccion_lineal_correcta_nunca_se_reemplaza_aunque_haya_chofer_resuelto():
    """Control -- cuando el lineal YA leyó la dirección real (sin
    intercalado), pasar `chofer_resuelto` nunca la reemplaza: la
    detección de contaminación exige coincidencia EXACTA con el chofer,
    nunca se dispara sobre un valor que ya es una dirección real."""
    direccion = "AV SIEMPRE VIVA 742 SANTIAGO PROVIDENCIA"
    chofer = "JUAN PEREZ"
    textos = [
        "DESPACHAR A",
        f": {direccion}",
        "RETIRA",
        f": {chofer}",
        "PATENTE",
        "RUT CHOFER",
        ":11111111-1",
        ": AA1234",
    ]
    bloques = _zona_entrega_con_chofer_intercalado(direccion, chofer)

    resultado = resolver_entrega_documento(
        textos, [], None, bloques=bloques, chofer_resuelto=chofer,
    )
    assert resultado["despachar_a_crudo"] == direccion


# ============================================================
# 3 -- regresión exacta del caso real 472523 (además de la cobertura
# general de arriba) -- traza OCR real, geometría real.
# ============================================================


def test_regresion_472523_direccion_real_no_se_confunde_con_chofer():
    direccion_real = "AVDA IRARRAZAVAL 5497 SANTIAGO NUÑOA"
    chofer_real = "PATRICK ORTIZ"
    textos = _textos_lineal_con_chofer_intercalado(direccion_real, chofer_real, "18626166-6", "XF3629")
    bloques = _zona_entrega_con_chofer_intercalado(direccion_real, chofer_real)

    resultado = resolver_entrega_documento(
        textos, [], None, bloques=bloques, chofer_resuelto=chofer_real,
    )
    assert resultado["despachar_a_crudo"] == direccion_real
