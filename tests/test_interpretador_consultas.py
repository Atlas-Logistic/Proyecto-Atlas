"""Bloque CONSULTAS ATLAS V1 -- intérprete determinístico (Bloque 6/10/
12/14/21 del ticket). Fixtures sintéticas propias -- el E2E real vive
en `tests/test_consultas_atlas_e2e.py`."""
from __future__ import annotations

from atlas_core.consultas_atlas import (
    METRICA_COUNT_VIAJES,
    METRICA_LISTAR_VIAJES,
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
)

CATALOGOS = CatalogosConsulta(
    choferes=("PATRICIO VILLAGRA MUÑOZ", "JUAN PEREZ", "SALOMÓN PIZARRO"),
    clientes=("SALOMON SACK SA", "ACMA SA"),
    obras=("SALOMON SACK SA SAN BERNARDO",),
    tipos_carga=("ROLLOS", "BARRAS", "NO DETERMINADO"),
    comunas=("Maipú", "San Bernardo"),
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
