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

from atlas_core.credibilidad_campos import NivelCredibilidad, evaluar_credibilidad_material
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


# ============================================================
# 7 -- Bloque PROPAGACIÓN MATERIAL M1: varios ítems reales fusionados en
# UNA sola línea OCR (imagen inclinada/de baja calidad, sin salto de
# línea limpio entre filas de la tabla) no deben tratarse como un único
# ítem larguísimo -- eso disparaba LONGITUD_EXCESIVA en `evaluar_
# credibilidad_material` y Desktop terminaba mostrando "NO DETERMINADO"
# para un material que sí se había leído (caso real 472640, DSI
# UNDERGROUND CHILE SPA). Reglas GENERALES (forma, nunca el texto/guía
# literal del caso que reveló el bug).
# ============================================================


def test_dos_items_reales_fusionados_en_una_linea_se_separan_por_coladas():
    """Dos filas reales de la tabla DESCRIPCIÓN, cada una cerrada con su
    propio "Coladas: <números>", que el OCR devolvió como una ÚNICA línea
    (sin salto de línea entre ellas) -- deben quedar como DOS ítems
    separados por " | ", cada uno corto y CONFIABLE, en vez de un solo
    bloque larguísimo."""
    resultado = extraer_descripcion_material([
        "ENCABEZADO B HORMIGON 32MM 11M A630 420KS (N) Coladas: 111,222,333 "
        "B HORMIGON 22MM 10M A630 A20HS (N) Coladas : 444,555"
    ])
    partes = resultado.split(" | ")
    assert len(partes) == 2
    assert partes[0].endswith("Coladas: 111,222,333")
    assert partes[1] == "B HORMIGON 22MM 10M A630 A20HS (N) Coladas : 444,555"
    for parte in partes:
        assert evaluar_credibilidad_material(parte).nivel == NivelCredibilidad.CONFIABLE
    # El resultado COMPLETO (ya unido con "|") también debe evaluarse
    # como confiable -- el mismo criterio que ya protege la unión legítima
    # con "|" mide por ítem, nunca sobre el texto ya unido completo.
    assert evaluar_credibilidad_material(resultado).nivel == NivelCredibilidad.CONFIABLE


def test_un_solo_item_con_termino_repetido_nunca_se_fragmenta_por_error():
    """Un ítem real ÚNICO que menciona dos términos de material juntos
    (p. ej. "Rollos de alambrón") nunca debe partirse sólo porque
    aparezca más de un término reconocido -- sin ningún "Coladas" de por
    medio, no hay límite real entre ítems distintos."""
    resultado = extraer_descripcion_material(["ROLLOS ALAMBRON 6MM TREFILADO"])
    assert resultado == "ROLLOS ALAMBRON 6MM TREFILADO"


def test_un_solo_item_con_su_propio_coladas_no_se_fragmenta():
    """Con un único "Coladas" (una sola fila real), nada debe dividirse --
    el patrón exige al menos DOS cierres para considerar que hay más de
    un ítem fusionado."""
    resultado = extraer_descripcion_material([
        "B HORMIGON 22MM 10M A630-420H (N) Coladas: 111,222,333"
    ])
    assert resultado == "B HORMIGON 22MM 10M A630-420H (N) Coladas: 111,222,333"
    assert evaluar_credibilidad_material(resultado).nivel == NivelCredibilidad.CONFIABLE


def test_texto_previo_al_primer_item_fusionado_no_se_pierde_ni_se_trata_aparte():
    """Cualquier texto ANTES del primer ítem real (p. ej. la etiqueta de
    columna "DESCRIPCION" que el OCR fusionó con la primera fila) debe
    quedar dentro del primer segmento -- nunca como un ítem vacío/propio,
    nunca descartado en silencio."""
    resultado = extraer_descripcion_material([
        "DESCRIPCION B HORMIGON 10MM 6M (N) Coladas: 1,2 B HORMIGON 12MM 6M (N) Coladas: 3,4"
    ])
    partes = resultado.split(" | ")
    assert len(partes) == 2
    assert partes[0].startswith("DESCRIPCION B HORMIGON")


# ============================================================
# 8 -- corrección Codex (bloqueante único): el remanente DESPUÉS del
# último "Coladas:" sólo puede convertirse en ítem si trae su PROPIA
# evidencia explícita de material -- nunca se acepta a ciegas sólo por
# venir después de un cierre real. Ejemplo real reportado: "... Coladas:
# 2 OBSERVACIONES GENERALES" -- "OBSERVACIONES GENERALES" es pie de
# página/observación, nunca un ítem de material. Reglas GENERALES (la
# clase "texto sin evidencia de material tras el último Coladas"), nunca
# un caso hardcodeado a esa frase en particular.
# ============================================================


def test_remanente_sin_evidencia_de_material_tras_el_ultimo_coladas_se_descarta():
    """Caso real reportado: '... Coladas: 2 OBSERVACIONES GENERALES' --
    el remanente tras el último "Coladas:" no menciona ningún término de
    material, así que se descarta por completo (nunca se convierte en un
    ítem "OBSERVACIONES GENERALES", nunca se pega al segmento anterior)."""
    resultado = extraer_descripcion_material([
        "B HORMIGON 32MM 11M A630 420KS (N) Coladas: 111,222,333 "
        "B HORMIGON 22MM 10M A630 A20HS (N) Coladas: 2 OBSERVACIONES GENERALES"
    ])
    partes = resultado.split(" | ")
    assert len(partes) == 2
    assert "OBSERVACIONES" not in resultado.upper()
    for parte in partes:
        assert evaluar_credibilidad_material(parte).nivel == NivelCredibilidad.CONFIABLE


def test_remanente_sin_evidencia_de_material_se_descarta_para_cualquier_pie_de_pagina():
    """Misma clase, otro texto de cierre cualquiera (nunca hardcodeado a
    'OBSERVACIONES GENERALES') -- ninguno de estos debe colarse como
    ítem."""
    for pie in ("2 FIRMA RECEPTOR CONFORME", "3 TIMBRE ELECTRONICO SII", "OBSERVACIONES: NINGUNA"):
        resultado = extraer_descripcion_material([
            "B HORMIGON 32MM 11M A630 420KS (N) Coladas: 111,222 "
            f"B HORMIGON 22MM 10M A630 A20HS (N) Coladas: 4,5 {pie}"
        ])
        partes = resultado.split(" | ")
        assert len(partes) == 2, pie
        for termino in ("FIRMA", "TIMBRE", "OBSERVACIONES", "NINGUNA"):
            assert termino not in resultado.upper(), pie


def test_remanente_con_evidencia_real_de_material_se_conserva():
    """Control -- si el remanente SÍ trae su propia evidencia de material
    (p. ej. el OCR no alcanzó a leer su "Coladas:" propio pero la
    descripción es real), se conserva como ítem -- la corrección de
    Codex nunca debe descartar un ítem real."""
    resultado = extraer_descripcion_material([
        "B HORMIGON 32MM 11M A630 420KS (N) Coladas: 111,222 "
        "B HORMIGON 22MM 10M A630 A20HS (N) Coladas: 4,5 ROLLOS ALAMBRON 6MM"
    ])
    partes = resultado.split(" | ")
    assert len(partes) == 3
    assert partes[2] == "ROLLOS ALAMBRON 6MM"
