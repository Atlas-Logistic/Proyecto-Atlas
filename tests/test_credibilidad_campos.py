"""Bloque C1 -- capa general de credibilidad de campos documentales.

Casos reales usados sólo como EVIDENCIA de que las señales generales
(nunca reglas puntuales de 472623/472624/SODIMAC/TRANSPORTES/JB6878)
detectan lo que ya se observó en la prueba real Mobile."""
from __future__ import annotations

from atlas_core.credibilidad_campos import (
    UMBRAL_LONGITUD_MATERIAL_INVALIDO,
    NivelCredibilidad,
    evaluar_credibilidad_direccion,
    evaluar_credibilidad_entidad_nombre,
    evaluar_credibilidad_material,
    evaluar_credibilidad_peso,
)


# ============================================================
# MATERIAL
# ============================================================


def test_material_normal_es_confiable():
    resultado = evaluar_credibilidad_material("HORMIGON 8MM 12M A630-420H (N)")
    assert resultado.nivel == NivelCredibilidad.CONFIABLE


def test_material_ausente_es_confiable_no_es_asunto_de_esta_capa():
    """La ausencia ya la cubre MATERIAL_AUSENTE (motivo aparte) -- esta
    capa sólo opina sobre contenido presente."""
    assert evaluar_credibilidad_material("").nivel == NivelCredibilidad.CONFIABLE
    assert evaluar_credibilidad_material("No encontrado").nivel == NivelCredibilidad.CONFIABLE


def test_material_contaminado_por_bloque_completo_de_otra_seccion_es_invalido():
    """Caso real 472624: el "material" trae, de hecho, el bloque
    completo cliente/fecha/RUT/dirección/transportista de la guía."""
    valor = (
        "Codigo Cliente 0001004274 FECHA DE EMISION 26-08-2026 SODIMAC SA "
        "SENOR(ES) 96.792.430-K RUT VIA AL X MENOR MAI C GIRO AV PDIE "
        "EDUARDO FREI 3092 DIRECCION COMUNA RENCA CIUDAD SANTIAGO "
        "Operacion constituye Venta INDICADOR TRASLADO TRANSPORTE "
        "TRANSPORTES MBI SPA EMPRESA DESCRIPCION CANTIDAD Codigo "
        "HORMIGON 8MM 12M A630-420H (N) 3.025/110002847 B Coladas: 2617677302"
    )
    resultado = evaluar_credibilidad_material(valor)
    assert resultado.nivel == NivelCredibilidad.INVALIDO
    assert resultado.motivo == "MATERIAL_POSIBLEMENTE_CONTAMINADO"
    assert any(s.startswith("ETIQUETAS_DE_OTRAS_SECCIONES") for s in resultado.senales)


def test_material_con_una_sola_etiqueta_ajena_es_solo_dudoso_no_invalido():
    """Señal moderada (una única etiqueta), nunca tan fuerte como el
    caso contaminado real -- la capa distingue intensidad, no sólo
    presencia/ausencia."""
    resultado = evaluar_credibilidad_material("HORMIGON 8MM RUT ADJUNTO EN GUIA FISICA")
    assert resultado.nivel == NivelCredibilidad.DUDOSO


def test_material_con_varios_items_reales_unidos_por_pipe_sigue_siendo_confiable():
    """Caso real (guías 460807/464991/472037 y otras): `extraer_
    descripcion_material` une varios ítems reales del mismo documento
    con " | " -- la longitud TOTAL crece con el número de ítems, sin
    que eso sea contaminación. La señal de longitud debe medir cada
    ítem individual, nunca el texto ya unido completo (bug real
    encontrado y corregido durante este mismo bloque: la primera
    versión marcaba estas 9+ guías reales como INVALIDO sólo por
    longitud, un falso positivo puro)."""
    valor = (
        "ANGULO 25X25X3MM 6M A270ES (N) | ANGULO 50X50X5MM 6M A270ES (N) | "
        "REDONDO LISO 18MM 6M SAE 1020 (N) | REDONDO LISO 8MM 6M SAE 1020 (N) | "
        "CUADRADO 10MM 6M COMERCIAL (N) | PLANA 100X5MM 6M A270ES (N) | "
        "PLANA 20X3MM 6M COMERCIAL (I) | PLANA 25X3MM 6M A270ES (N) | "
        "PLANA 32X3MM 6M A270ES (N)"
    )
    assert len(valor) > UMBRAL_LONGITUD_MATERIAL_INVALIDO  # el texto unido SÍ es largo
    resultado = evaluar_credibilidad_material(valor)
    assert resultado.nivel == NivelCredibilidad.CONFIABLE


def test_material_generico_de_otra_empresa_hipotetica_tambien_se_detecta():
    """Control de generalidad: el mecanismo no depende de SODIMAC/AZA/
    ninguna empresa -- una guía hipotética completamente distinta con el
    mismo patrón estructural (bloque societario mezclado en material)
    dispara igual."""
    valor = (
        "Codigo Cliente 999 FECHA DE EMISION 01-01-2027 FERRETERIA LOS "
        "ROBLES LTDA SENOR(ES) 77.111.222-3 RUT GIRO CALLE FICTICIA 100 "
        "DIRECCION COMUNA PUDAHUEL CIUDAD SANTIAGO TRANSPORTE"
    )
    resultado = evaluar_credibilidad_material(valor)
    assert resultado.nivel in (NivelCredibilidad.DUDOSO, NivelCredibilidad.INVALIDO)


# ============================================================
# ENTIDAD (obra_destino / cliente-como-nombre)
# ============================================================


def test_entidad_nombre_normal_es_confiable():
    assert evaluar_credibilidad_entidad_nombre("SODIMAC SA").nivel == NivelCredibilidad.CONFIABLE
    assert evaluar_credibilidad_entidad_nombre("EMPRESA CONST SIGRO").nivel == NivelCredibilidad.CONFIABLE


def test_entidad_palabra_generica_documental_es_dudosa():
    """Caso real: obra_destino llega como "TRANSPORTES" -- una etiqueta
    documental genérica, nunca una obra confirmada. La señal es la
    PALABRA genérica en sí (vocabulario general de dominio), no el
    número de guía que la trae."""
    resultado = evaluar_credibilidad_entidad_nombre("TRANSPORTES")
    assert resultado.nivel == NivelCredibilidad.DUDOSO
    assert resultado.motivo == "VALOR_ES_ETIQUETA_GENERICA_NO_ENTIDAD"


def test_entidad_cliente_representado_solo_por_rut_formateado_es_dudoso():
    resultado = evaluar_credibilidad_entidad_nombre("96.792.430-K")
    assert resultado.nivel == NivelCredibilidad.DUDOSO
    assert resultado.motivo == "VALOR_ES_RUT_CRUDO_SIN_RAZON_SOCIAL"


def test_entidad_cliente_representado_por_rut_desalineado_por_ocr_tambien_es_dudoso():
    """Caso real 472624: el RUT documental quedó con un espacio de más
    ("96 .792.430-K") -- ya no calza con el formato estricto de RUT,
    pero sigue siendo casi puros dígitos/puntuación: nunca una razón
    social real. Señal general (conteo de letras), no un regex de un
    RUT puntual."""
    resultado = evaluar_credibilidad_entidad_nombre("96 .792.430-K")
    assert resultado.nivel == NivelCredibilidad.DUDOSO
    assert resultado.motivo == "VALOR_ES_RUT_CRUDO_SIN_RAZON_SOCIAL"


def test_entidad_fragmento_demasiado_corto_es_dudoso():
    assert evaluar_credibilidad_entidad_nombre("AB").nivel == NivelCredibilidad.DUDOSO


def test_entidad_ausente_es_confiable_no_es_asunto_de_esta_capa():
    assert evaluar_credibilidad_entidad_nombre("").nivel == NivelCredibilidad.CONFIABLE
    assert evaluar_credibilidad_entidad_nombre("No encontrado").nivel == NivelCredibilidad.CONFIABLE


# ============================================================
# DIRECCIÓN / DESTINO
# ============================================================


def test_direccion_completa_es_confiable():
    resultado = evaluar_credibilidad_direccion("SAN LUIS 1201 QUILICURA")
    assert resultado.nivel == NivelCredibilidad.CONFIABLE


def test_direccion_fragmento_truncado_de_una_sola_palabra_corta_es_dudosa():
    """Caso real 472624: DESPACHAR A quedó truncado en "SAN" -- un
    fragmento de una sola palabra corta nunca es un destino operacional
    confirmado, sin importar cuál sea la palabra."""
    resultado = evaluar_credibilidad_direccion("SAN")
    assert resultado.nivel == NivelCredibilidad.DUDOSO
    assert resultado.motivo == "DESTINO_FRAGMENTO_TRUNCADO"


def test_direccion_fragmento_corto_generico_tambien_se_detecta_sin_ser_san():
    """Control de generalidad: cualquier fragmento corto dispara igual,
    no sólo "SAN"."""
    for valor in ("LOS", "AV", "MAI"):
        assert evaluar_credibilidad_direccion(valor).nivel == NivelCredibilidad.DUDOSO


def test_direccion_contaminada_por_etiqueta_de_otra_seccion_es_invalida():
    resultado = evaluar_credibilidad_direccion("PATENTE BDFG50")
    assert resultado.nivel == NivelCredibilidad.INVALIDO
    assert resultado.motivo == "DESTINO_CONTAMINADO_POR_OTRA_SECCION"


def test_direccion_ausente_es_confiable_no_es_asunto_de_esta_capa():
    assert evaluar_credibilidad_direccion("").nivel == NivelCredibilidad.CONFIABLE
    assert evaluar_credibilidad_direccion("No encontrado").nivel == NivelCredibilidad.CONFIABLE


# ============================================================
# PESO -- nunca se reemplaza, sólo se marca.
# ============================================================


def test_peso_tipico_es_confiable():
    assert evaluar_credibilidad_peso("3025").nivel == NivelCredibilidad.CONFIABLE


def test_peso_bajo_atipico_queda_sospechoso_sin_reemplazarlo():
    """Caso real 472623: 87 kg -- legible, pero operacionalmente
    atípico para una guía de despacho de material a granel. La función
    NUNCA devuelve otro peso -- sólo clasifica; el valor documental
    sigue siendo responsabilidad exclusiva de quien lo extrajo."""
    resultado = evaluar_credibilidad_peso("87")
    assert resultado.nivel == NivelCredibilidad.DUDOSO
    assert resultado.motivo == "PESO_OPERACIONALMENTE_ATIPICO"
    assert resultado.senales == ("PESO_KG=87",)


def test_peso_alto_atipico_tambien_queda_sospechoso():
    resultado = evaluar_credibilidad_peso("50000")
    assert resultado.nivel == NivelCredibilidad.DUDOSO


def test_peso_ausente_o_ilegible_es_confiable_no_es_asunto_de_esta_capa():
    assert evaluar_credibilidad_peso(None).nivel == NivelCredibilidad.CONFIABLE
    assert evaluar_credibilidad_peso("No encontrado").nivel == NivelCredibilidad.CONFIABLE
    assert evaluar_credibilidad_peso("no-numero").nivel == NivelCredibilidad.CONFIABLE
