"""Bloque R2.2 -- Clase C: CONTAMINACIÓN DE CAMPOS OPERACIONALES.

Dos frentes reales, misma causa estructural (columnas intercaladas por
PaddleOCR haciendo que el valor de OTRO campo, sin su propia etiqueta,
quede pegado al final de un campo real):

1. DESTINO: un RUT sin etiqueta queda pegado al final de una dirección
   real (`atlas_core.extractor.limpiar_sufijo_rut_pegado`, aplicado en
   `atlas_core.rutas.destino_entrega.resolver_entrega_documento`).
2. MATERIAL: una línea de sello/anotación (código de sección + fecha
   compacta + hora) queda en la misma línea que menciona un término de
   material y se incluye entera
   (`atlas_core.procesamiento_masivo._es_fragmento_estampado_no_material`).

Reglas GENERALES (forma, nunca valores literales) -- nunca hardcodea
"C4"/"C6"/fechas/horas/el RUT real de los casos que revelaron el bug.
"""
from __future__ import annotations

from atlas_core.extractor import limpiar_sufijo_rut_pegado
from atlas_core.procesamiento_masivo import extraer_descripcion_material


# ============================================================
# 5 -- RUT adyacente a dirección no contamina destino operacional
# ============================================================

def test_rut_pegado_al_final_de_direccion_se_recorta():
    """Caso real 464511: 'SANTA ISABEL 585 SANTIAGO LAMPA :15454297-3'."""
    resultado = limpiar_sufijo_rut_pegado("SANTA ISABEL 585 SANTIAGO LAMPA :15454297-3")
    assert resultado == "SANTA ISABEL 585 SANTIAGO LAMPA"


def test_direccion_sin_contaminacion_no_se_toca():
    """Caso real 464489: la misma calle, sin el sufijo -- control."""
    resultado = limpiar_sufijo_rut_pegado("SANTA ISABEL 585 SANTIAGO LAMPA")
    assert resultado == "SANTA ISABEL 585 SANTIAGO LAMPA"


def test_direccion_que_termina_en_numero_de_calle_no_se_confunde_con_rut():
    """Una numeración de calle real (sin guión + dígito verificador) nunca
    debe recortarse -- sólo un sufijo con FORMA de RUT válido."""
    resultado = limpiar_sufijo_rut_pegado("AV LIBERTADOR BERNARDO OHIGGINS 1234")
    assert resultado == "AV LIBERTADOR BERNARDO OHIGGINS 1234"


def test_sufijo_con_forma_de_rut_pero_digito_verificador_invalido_no_se_recorta():
    """No basta con la forma NNN-N: el dígito verificador debe ser
    matemáticamente válido -- nunca se asume que cualquier guion final es
    un RUT."""
    invalido = limpiar_sufijo_rut_pegado("CALLE EJEMPLO 456 :12345678-0")
    # 0 casi nunca es el dígito verificador correcto para un RUT de 8
    # dígitos arbitrario -- si por coincidencia SÍ fuera válido este test
    # necesitaría otro número, pero el punto es: se valida el DV, no la forma.
    from atlas_core.validadores import validar_rut_chileno
    from atlas_core.modelos import EstadoValidacion
    if validar_rut_chileno("12345678-0").estado != EstadoValidacion.VALIDO:
        assert invalido == "CALLE EJEMPLO 456 :12345678-0"


def test_valor_vacio_no_revienta():
    assert limpiar_sufijo_rut_pegado("") == ""
    assert limpiar_sufijo_rut_pegado(None) == ""


# ============================================================
# 6 -- fecha/hora/código de sección adyacente no contamina MATERIAL
# ============================================================

def test_estampado_pegado_a_barras_se_excluye_del_material_464511():
    resultado = extraer_descripcion_material([
        "B HORMIGON 22HM 12M A630-420H (N)\nC6 10.08 12PM/BARRAS CYD"
    ])
    assert "C6" not in resultado
    assert "10.08" not in resultado
    assert "12PM" not in resultado
    assert resultado == "B HORMIGON 22HM 12M A630-420H (N)"


def test_estampado_pegado_a_barras_se_excluye_del_material_464489():
    resultado = extraer_descripcion_material([
        "B HORMIGON 22MM 10M A630-420H (N)\nC4 10.08 8AM/BARRAS CYD"
    ])
    assert "C4" not in resultado
    assert resultado == "B HORMIGON 22MM 10M A630-420H (N)"


def test_material_real_sin_estampado_se_conserva_igual():
    """Control -- una línea de material real (sin código+fecha+hora
    compactos) sigue capturándose exactamente igual que antes."""
    resultado = extraer_descripcion_material(["B HORMIGON 22MM 10M A630-420H (N)"])
    assert resultado == "B HORMIGON 22MM 10M A630-420H (N)"


def test_solo_codigo_corto_sin_fecha_ni_hora_no_se_excluye():
    """La señal exige LAS TRES condiciones juntas -- un material real que
    por coincidencia mencione un código corto (p. ej. un lote "A1") sin
    fecha/hora compactas no debe excluirse."""
    resultado = extraer_descripcion_material(["ROLLOS A1 ALAMBRON TREFILADO"])
    assert "ROLLOS A1 ALAMBRON TREFILADO" in resultado


def test_multiples_lineas_conserva_material_real_y_descarta_solo_el_estampado():
    resultado = extraer_descripcion_material([
        "B HORMIGON 22MM 10M A630-420H (N)\n"
        "C4 10.08 8AM/BARRAS CYD\n"
        "ROLLOS ALAMBRON 6MM"
    ])
    partes = resultado.split(" | ")
    assert "B HORMIGON 22MM 10M A630-420H (N)" in partes
    assert "ROLLOS ALAMBRON 6MM" in partes
    assert not any("10.08" in p or "8AM" in p for p in partes)
