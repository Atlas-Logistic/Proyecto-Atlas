"""Bloque CONSULTAS ATLAS V1 -- intérprete determinístico (Bloque 6/10/
12/14/21 del ticket). Fixtures sintéticas propias -- el E2E real vive
en `tests/test_consultas_atlas_e2e.py`."""
from __future__ import annotations

from atlas_core.consultas_atlas import (
    DOMINIO_EVENTOS,
    DOMINIO_INCIDENCIAS_DOCUMENTALES,
    DOMINIO_VIAJES,
    ConsultaAtlas,
    METRICA_COUNT_DISTINCT_CHOFER,
    METRICA_COUNT_EVENTOS,
    METRICA_COUNT_INCIDENCIAS,
    METRICA_COUNT_VIAJES,
    METRICA_LIST_RELACION,
    METRICA_LISTAR_VIAJES,
    METRICA_SUM_KM,
    METRICA_SUM_PESO,
    PERIODO_ESTE_MES,
)
from atlas_core.interpretador_consultas import (
    AMBIGUA,
    RESUELTA,
    SIN_COINCIDENCIA,
    CatalogosConsulta,
    interpretar_consulta_determinista,
    resolver_entidad_por_palabras,
    resolver_patente_por_texto,
    validar_compatibilidad_semantica,
)

CATALOGOS = CatalogosConsulta(
    choferes=("PATRICIO VILLAGRA MUÑOZ", "JUAN PEREZ", "SALOMÓN PIZARRO"),
    clientes=("SALOMON SACK SA", "ACMA SA"),
    obras=("SALOMON SACK SA SAN BERNARDO",),
    tipos_carga=("ROLLOS", "BARRAS", "NO DETERMINADO"),
    comunas=("Maipú", "San Bernardo"),
)

CATALOGOS_UNIVERSAL = CatalogosConsulta(
    choferes=("CRISTOPHER RETAMAL", "RODRIGO NAHUELÑIR"),
    clientes=("YOLITO BALART HNOS LTDA",), obras=(), tipos_carga=(), comunas=(),
    patentes=("JB8529", "JF4288", "BPHR67"),
)


# --- Bloque 6: resolución de entidades por palabras ---

def test_resuelve_por_coincidencia_parcial_de_una_palabra():
    r = resolver_entidad_por_palabras("¿Cuántos viajes hizo Villagra?", CATALOGOS.choferes)
    assert r.estado == RESUELTA
    assert r.valor == "PATRICIO VILLAGRA MUÑOZ"


def test_ignora_puntuacion_pegada():
    r = resolver_entidad_por_palabras("Muéstrame los viajes de Villagra.", CATALOGOS.choferes)
    assert r.estado == RESUELTA
    assert r.valor == "PATRICIO VILLAGRA MUÑOZ"


def test_prefiere_coincidencia_de_mas_palabras():
    r = resolver_entidad_por_palabras("¿Cuántos viajes fueron para Salomon Sack?", CATALOGOS.clientes)
    assert r.estado == RESUELTA
    assert r.valor == "SALOMON SACK SA"


def test_ambigua_cuando_dos_valores_empatan():
    r = resolver_entidad_por_palabras("Juan", ("JUAN PEREZ", "JUAN GOMEZ"))
    assert r.estado == AMBIGUA
    assert set(r.candidatos) == {"JUAN PEREZ", "JUAN GOMEZ"}


def test_sin_coincidencia_si_nada_calza():
    r = resolver_entidad_por_palabras("¿Cuántos viajes hizo Lazcano?", CATALOGOS.choferes)
    assert r.estado == SIN_COINCIDENCIA


# --- Bloque 10: interpretador determinístico -- vocabulario general ---

def test_interpreta_metrica_count_viajes_por_defecto():
    consulta, avisos = interpretar_consulta_determinista("¿Cuántos viajes hizo Juan Perez?", catalogos=CATALOGOS)
    assert consulta is not None
    assert consulta.metrica == METRICA_COUNT_VIAJES
    assert consulta.filtros["chofer"] == "JUAN PEREZ"


def test_interpreta_metrica_listar():
    consulta, _ = interpretar_consulta_determinista("Muéstrame los viajes de Juan Perez.", catalogos=CATALOGOS)
    assert consulta.metrica == METRICA_LISTAR_VIAJES


def test_interpreta_metrica_sum_peso_toneladas():
    consulta, _ = interpretar_consulta_determinista("¿Cuántas toneladas transportó Juan Perez?", catalogos=CATALOGOS)
    assert consulta.metrica == METRICA_SUM_PESO


def test_interpreta_periodo_este_mes():
    consulta, _ = interpretar_consulta_determinista("¿Cuántos viajes hizo Juan Perez este mes?", catalogos=CATALOGOS)
    assert consulta.filtros["periodo"] == PERIODO_ESTE_MES


def test_interpreta_agrupacion_cada_chofer():
    consulta, _ = interpretar_consulta_determinista("¿Cuántos viajes hizo cada chofer?", catalogos=CATALOGOS)
    assert consulta.agrupacion == "chofer"
    assert "chofer" not in consulta.filtros


def test_interpreta_agrupacion_por_cliente():
    consulta, _ = interpretar_consulta_determinista("¿Cuántas toneladas movimos por cliente?", catalogos=CATALOGOS)
    assert consulta.agrupacion == "cliente"


# --- Bloque 7: tipo de carga vs material -- nunca se mezclan ---

def test_reconoce_tipo_de_carga_rollos():
    consulta, _ = interpretar_consulta_determinista("¿Cuántos viajes fueron con rollos?", catalogos=CATALOGOS)
    assert consulta.filtros.get("tipo_carga") == "ROLLOS"
    assert "material" not in consulta.filtros


# --- Bloque 12: consultas compuestas ---

def test_consulta_compuesta_chofer_tipo_carga_periodo():
    consulta, _ = interpretar_consulta_determinista(
        "¿Cuántos viajes hizo Villagra con rollos este mes?", catalogos=CATALOGOS,
    )
    assert consulta.filtros == {
        "chofer": "PATRICIO VILLAGRA MUÑOZ", "tipo_carga": "ROLLOS", "periodo": PERIODO_ESTE_MES,
    }


# --- Bloque 14: ambigüedad real -- nunca elige arbitrariamente ---

def test_ambiguedad_entre_dos_choferes_bloquea_interpretacion():
    catalogos = CatalogosConsulta(
        choferes=("JUAN PEREZ", "JUAN GOMEZ"), clientes=(), obras=(), tipos_carga=(), comunas=(),
    )
    consulta, avisos = interpretar_consulta_determinista("¿Cuántos viajes hizo Juan?", catalogos=catalogos)
    assert consulta is None
    assert any(a.startswith("AMBIGUO:chofer:") for a in avisos)


# --- Bloque 6/20: colisión entre familias -- gana la coincidencia más
# fuerte, nunca sobre-restringe con la más débil ---

def test_coincidencia_debil_de_otra_familia_no_sobre_restringe():
    """Caso real: "Salomon" coincide con el chofer "SALOMÓN PIZARRO" (1
    palabra) Y con el cliente "SALOMON SACK SA" (2 palabras) -- gana el
    cliente, el chofer NO se agrega como filtro espurio."""
    consulta, _ = interpretar_consulta_determinista("¿Cuántos viajes fueron para Salomon Sack?", catalogos=CATALOGOS)
    assert consulta.filtros == {"cliente": "SALOMON SACK SA"}


def test_obra_ambigua_ya_cubierta_por_cliente_no_bloquea():
    """Dos variantes de obra (dos guías con OCR distinto para la misma
    obra real) quedan ambiguas por sí solas, pero como ambas comparten
    las mismas palabras que ya explicó "cliente", no bloquean la
    consulta."""
    catalogos = CatalogosConsulta(
        choferes=(), clientes=("SALOMON SACK SA",),
        obras=("SALOMON SACK SA SAN BERNARDO", "SALOMON SACK SA SAN BERNGARDO"),
        tipos_carga=(), comunas=(),
    )
    consulta, avisos = interpretar_consulta_determinista("¿Cuántos viajes fueron para Salomon Sack?", catalogos=catalogos)
    assert consulta is not None
    assert consulta.filtros == {"cliente": "SALOMON SACK SA"}
    assert not any(a.startswith("AMBIGUO:") for a in avisos)


# --- Bloque 6/20: nombre propio no reconocido nunca se ignora ---

def test_nombre_propio_no_reconocido_no_se_ignora():
    consulta, avisos = interpretar_consulta_determinista("¿Cuántos viajes hizo Lazcano?", catalogos=CATALOGOS)
    assert consulta is None
    assert any(a.startswith("SIN_COINCIDENCIA:") for a in avisos)


def test_pregunta_sin_metrica_reconocible_devuelve_none():
    consulta, avisos = interpretar_consulta_determinista("Hola, ¿cómo estás?", catalogos=CATALOGOS)
    assert consulta is None


# --- Bloque B1 V2 -- Caso real A: "incidencias documentales" NUNCA cae
# a COUNT_VIAJES (Bloque 4.A/9 del ticket) ---

def test_incidencias_documentales_activa_dominio_propio_no_viajes():
    consulta, _ = interpretar_consulta_determinista("¿Cuántas incidencias documentales hay?", catalogos=CATALOGOS)
    assert consulta is not None
    assert consulta.dominio == DOMINIO_INCIDENCIAS_DOCUMENTALES
    assert consulta.metrica == METRICA_COUNT_INCIDENCIAS


def test_sinonimo_errores_documentales_activa_incidencias():
    consulta, _ = interpretar_consulta_determinista("¿Cuántos errores documentales tenemos?", catalogos=CATALOGOS)
    assert consulta.dominio == DOMINIO_INCIDENCIAS_DOCUMENTALES


# --- Bloque B1 V2 -- Caso real B: "kms" (plural) reconoce SUM_KM,
# nunca cae a COUNT_VIAJES por falta de sinónimo (Bloque 10 del ticket) ---

def test_kms_plural_reconoce_sum_km():
    catalogos = CatalogosConsulta(choferes=("CRISTOPHER RETAMAL",), clientes=(), obras=(), tipos_carga=(), comunas=())
    consulta, _ = interpretar_consulta_determinista("¿Cuántos kms recorridos tiene Retamal?", catalogos=catalogos)
    assert consulta is not None
    assert consulta.metrica == METRICA_SUM_KM
    assert consulta.filtros["chofer"] == "CRISTOPHER RETAMAL"


def test_distancia_de_apellido_reconoce_sum_km():
    catalogos = CatalogosConsulta(choferes=("CRISTOPHER RETAMAL",), clientes=(), obras=(), tipos_carga=(), comunas=())
    consulta, _ = interpretar_consulta_determinista("distancia de cristopher retamal", catalogos=catalogos)
    assert consulta.metrica == METRICA_SUM_KM


# --- Bloque B1 V2 -- Caso real C: "choferes"/"conductores" en plural
# pide CANTIDAD DE PERSONAS, nunca cuenta viajes (Bloque 4.C) ---

def test_cuantos_choferes_trabajaron_activa_count_distinct_chofer():
    consulta, _ = interpretar_consulta_determinista("¿Cuántos choferes trabajaron este mes?", catalogos=CATALOGOS)
    assert consulta is not None
    assert consulta.metrica == METRICA_COUNT_DISTINCT_CHOFER
    assert consulta.filtros["periodo"] == PERIODO_ESTE_MES


def test_cuantos_conductores_cargaron_activa_count_distinct_chofer():
    consulta, _ = interpretar_consulta_determinista("cuántos conductores cargaron este mes", catalogos=CATALOGOS)
    assert consulta.metrica == METRICA_COUNT_DISTINCT_CHOFER


def test_cada_chofer_sigue_siendo_agrupacion_no_count_distinct():
    """Nunca romper el V1 existente: "cada chofer"/"por chofer" (singular)
    sigue siendo agrupación, no dispara la cuenta de personas."""
    consulta, _ = interpretar_consulta_determinista("¿Cuántos viajes hizo cada chofer?", catalogos=CATALOGOS)
    assert consulta.agrupacion == "chofer"
    assert consulta.metrica == METRICA_COUNT_VIAJES


# --- Bloque B1 V2 (Bloque 7) -- el bug arquitectónico: "cuántos X" sin
# métrica reconocible YA NO cae en silencio a COUNT_VIAJES; cede a B1 ---

def test_cuantos_sin_metrica_ni_viaje_cede_a_b1_en_vez_de_asumir_viajes():
    consulta, _ = interpretar_consulta_determinista("¿Cuánto hizo Juan Perez?", catalogos=CATALOGOS)
    assert consulta is None


def test_cuantos_viajes_explicito_sigue_siendo_determinista():
    consulta, _ = interpretar_consulta_determinista("¿Cuántos viajes hay?", catalogos=CATALOGOS)
    assert consulta is not None
    assert consulta.metrica == METRICA_COUNT_VIAJES


# --- Bloque B1 V2 (Bloque 6) -- validador semántico: red de seguridad ---

def test_semantica_rechaza_km_con_count_viajes():
    consulta = ConsultaAtlas(metrica=METRICA_COUNT_VIAJES)
    motivo = validar_compatibilidad_semantica("¿Cuántos km hizo Juan Perez?", consulta)
    assert motivo is not None


def test_semantica_rechaza_incidencias_con_dominio_viajes():
    consulta = ConsultaAtlas(metrica=METRICA_COUNT_VIAJES, dominio=DOMINIO_VIAJES)
    motivo = validar_compatibilidad_semantica("¿Cuántas incidencias documentales hay?", consulta)
    assert motivo is not None


def test_semantica_rechaza_choferes_cantidad_con_count_viajes():
    consulta = ConsultaAtlas(metrica=METRICA_COUNT_VIAJES)
    motivo = validar_compatibilidad_semantica("¿Cuántos choferes trabajaron este mes?", consulta)
    assert motivo is not None


def test_semantica_rechaza_peso_con_count_viajes():
    consulta = ConsultaAtlas(metrica=METRICA_COUNT_VIAJES)
    motivo = validar_compatibilidad_semantica("¿Cuántas toneladas transportó Juan Perez?", consulta)
    assert motivo is not None


def test_semantica_acepta_consulta_compatible():
    consulta = ConsultaAtlas(metrica=METRICA_SUM_KM)
    assert validar_compatibilidad_semantica("¿Cuántos km hizo Juan Perez?", consulta) is None


def test_semantica_no_rechaza_agrupacion_por_chofer():
    """"por chofer" (agrupación V1) nunca se confunde con la pregunta de
    cantidad de personas."""
    consulta = ConsultaAtlas(metrica=METRICA_COUNT_VIAJES, agrupacion="chofer")
    assert validar_compatibilidad_semantica("¿Cuántos viajes hizo cada chofer?", consulta) is None


# --- Bloque UNIVERSAL V1 -- resolución de PATENTE: token exacto, nunca
# por subcadena (Bloque 7/18 del ticket) ---

def test_resolver_patente_token_exacto():
    r = resolver_patente_por_texto("¿En qué viajes aparece la patente JB8529?", CATALOGOS_UNIVERSAL.patentes)
    assert r.estado == RESUELTA
    assert r.valor == "JB8529"


def test_resolver_patente_no_confunde_subcadena():
    r = resolver_patente_por_texto("JB85", CATALOGOS_UNIVERSAL.patentes)
    assert r.estado == SIN_COINCIDENCIA


# --- Bloque UNIVERSAL V1 (Bloque 18 del ticket) -- 5 preguntas
# RELACIONALES, un solo motor genérico (LIST_RELACION/LISTAR_VIAJES) ---

def test_relacional_en_que_viajes_aparece_patente():
    c, avisos = interpretar_consulta_determinista("¿En qué viajes aparece la patente JB8529?", catalogos=CATALOGOS_UNIVERSAL)
    assert c == ConsultaAtlas(metrica=METRICA_LISTAR_VIAJES, filtros={"patente": "JB8529"})
    assert avisos == ()


def test_relacional_con_que_chofer_esta_vinculada_patente():
    c, _ = interpretar_consulta_determinista("¿Con qué chofer está vinculada JF4288?", catalogos=CATALOGOS_UNIVERSAL)
    assert c.metrica == METRICA_LIST_RELACION
    assert c.relacion == "chofer"
    assert c.filtros == {"patente": "JF4288"}


def test_relacional_que_patentes_ha_usado_chofer():
    c, _ = interpretar_consulta_determinista("¿Qué patentes ha usado Retamal?", catalogos=CATALOGOS_UNIVERSAL)
    assert c.metrica == METRICA_LIST_RELACION
    assert c.relacion == "vehiculo"
    assert c.filtros == {"chofer": "CRISTOPHER RETAMAL"}


def test_relacional_en_que_guias_aparece_patente():
    c, _ = interpretar_consulta_determinista("¿En qué guías aparece JF4288?", catalogos=CATALOGOS_UNIVERSAL)
    assert c.metrica == METRICA_LIST_RELACION
    assert c.relacion == "guia"
    assert c.filtros == {"patente": "JF4288"}


def test_relacional_que_cliente_aparece_en_el_viaje():
    c, _ = interpretar_consulta_determinista("¿Qué cliente aparece en el viaje 0000354805?", catalogos=CATALOGOS_UNIVERSAL)
    assert c.metrica == METRICA_LIST_RELACION
    assert c.relacion == "cliente"
    assert c.filtros == {"numero_transporte": "0000354805"}


def test_relacional_patente_ambigua_bloquea():
    catalogos = CatalogosConsulta(
        choferes=(), clientes=(), obras=(), tipos_carga=(), comunas=(), patentes=("AA1111", "AA1111X"),
    )
    # Frase artificial con dos patentes reales mencionadas a la vez.
    c, avisos = interpretar_consulta_determinista("¿En qué viajes aparece AA1111 o AA1111X?", catalogos=catalogos)
    assert c is None
    assert any(a.startswith("AMBIGUO:patente:") for a in avisos)


# --- Bloque UNIVERSAL V1 (Bloque 9/19 del ticket) -- dominio EVENTOS ---

def test_evento_estadia_singular_chofer():
    c, _ = interpretar_consulta_determinista("¿Cuántas estadías tuvo Retamal?", catalogos=CATALOGOS_UNIVERSAL)
    assert c.dominio == DOMINIO_EVENTOS
    assert c.metrica == METRICA_COUNT_EVENTOS
    assert c.filtros == {"tipo_evento": "TIENE_ESTADIA", "chofer": "CRISTOPHER RETAMAL"}


def test_evento_devolucion_generica_no_confunde_cliente_con_chofer():
    """Caso real: "Salomon Sack" comparte una palabra con un chofer
    ("SALOMÓN...") pero DOS con el cliente -- debe ganar el cliente,
    igual que en el flujo de viajes (Bloque 6/12)."""
    catalogos = CatalogosConsulta(
        choferes=("SALOMÓN PIZARRO",), clientes=("SALOMON SACK SA",), obras=(), tipos_carga=(), comunas=(),
    )
    c, _ = interpretar_consulta_determinista("¿Cuántas devoluciones tuvo Salomon Sack?", catalogos=catalogos)
    assert c.dominio == DOMINIO_EVENTOS
    assert c.filtros == {"tipo_evento": "DEVOLUCION", "cliente": "SALOMON SACK SA"}


def test_evento_doble_vuelta_agrupado_por_obra():
    catalogos = CatalogosConsulta(choferes=(), clientes=(), obras=("OBRA Y",), tipos_carga=(), comunas=())
    c, _ = interpretar_consulta_determinista("¿Qué obras tuvieron doble vuelta?", catalogos=catalogos)
    assert c.dominio == DOMINIO_EVENTOS
    assert c.filtros == {"tipo_evento": "DOBLE_VUELTA"}
    assert c.agrupacion == "obra"
    assert c.limite is None


def test_evento_top_chofer_con_mas_devoluciones():
    c, _ = interpretar_consulta_determinista("¿Qué chofer tuvo más devoluciones?", catalogos=CATALOGOS_UNIVERSAL)
    assert c.dominio == DOMINIO_EVENTOS
    assert c.filtros == {"tipo_evento": "DEVOLUCION"}
    assert c.agrupacion == "chofer"
    assert c.limite == 1


def test_evento_semantica_rechaza_dominio_viajes():
    consulta = ConsultaAtlas(metrica=METRICA_COUNT_VIAJES)
    motivo = validar_compatibilidad_semantica("¿Cuántas estadías tuvo Retamal?", consulta)
    assert motivo is not None
