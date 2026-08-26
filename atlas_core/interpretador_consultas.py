"""Consultas Atlas V1 -- interpretador: pregunta en lenguaje natural ->
`ConsultaAtlas` (Bloque 1: INTERPRETACIÓN, nunca CÁLCULO -- el resultado
numérico siempre sale de `consultas_atlas.ejecutar_consulta_atlas`).

Camino rápido determinístico (Bloque 10/21: "si la consulta es
determinísticamente interpretable sin LLM, permitir camino rápido" --
"no llamar B1 si una consulta puede interpretarse determinísticamente")
para el vocabulario operacional real de Atlas (chofer/cliente/obra/tipo
de carga/comuna/período/agrupación, tal como aparecen en `viajes.csv`
ya cargado). B1 (`interpretar_con_b1`, Bloque 10) sólo se invoca cuando
el camino rápido no encuentra ninguna métrica reconocible -- y su
salida SIEMPRE se valida con el mismo `validar_consulta` antes de
ejecutarse (Bloque 20: "el LLM nunca calcula, nunca decide solo")."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping

from atlas_core.consultas_atlas import (
    AGRUPACIONES_SOPORTADAS,
    DOMINIO_INCIDENCIAS_DOCUMENTALES,
    DOMINIO_VIAJES,
    ConsultaAtlas,
    METRICA_COUNT_DISTINCT_CHOFER,
    METRICA_COUNT_GUIAS,
    METRICA_COUNT_INCIDENCIAS,
    METRICA_COUNT_VIAJES,
    METRICA_LISTAR_VIAJES,
    METRICA_SUM_KM,
    METRICA_SUM_PESO,
    METRICA_SUM_TIEMPO,
    PERIODO_AYER,
    PERIODO_ESTA_SEMANA,
    PERIODO_ESTE_MES,
    PERIODO_HOY,
    PERIODO_MES_PASADO,
    PERIODO_SEMANA_PASADA,
    normalizar_texto_atlas,
)

RESUELTA = "RESUELTA"
AMBIGUA = "AMBIGUA"
SIN_COINCIDENCIA = "SIN_COINCIDENCIA"

# Palabras genéricas que aparecen dentro de casi cualquier nombre real
# (razón social, nombre de persona) -- nunca cuentan como evidencia de
# coincidencia por sí solas (mismo principio ya calibrado en
# `atlas_core.normalizacion_semantica` para sufijos societarios/palabras
# descriptivas). Lista acotada, nunca "cualquier palabra corta".
_PALABRAS_IGNORADAS_ENTIDAD = frozenset({
    "DE", "DEL", "LA", "EL", "LOS", "LAS", "Y", "A", "PARA", "CON", "EN",
    "SA", "SPA", "LTDA", "EIRL", "LIMITADA", "HNOS", "CIA", "COMPANIA",
})


@dataclass(frozen=True)
class ResolucionEntidad:
    """Decisión trazable, sin adivinar (Bloque 6/14): `RESUELTA` con un
    único `valor` canónico; `AMBIGUA` con los `candidatos` reales entre
    los que Atlas no puede elegir sola; `SIN_COINCIDENCIA` si ningún
    valor conocido del dataset comparte evidencia con el texto."""

    estado: str
    valor: str = ""
    candidatos: tuple[str, ...] = ()
    palabras_coincidentes: frozenset[str] = frozenset()


_PATRON_PALABRA = re.compile(r"[A-Z0-9]+")


def _palabras(texto: str) -> set[str]:
    """Tokeniza en palabras alfanuméricas puras -- nunca deja que
    puntuación pegada ("Villagra." / "¿rollos?") impida una coincidencia
    real por comparación de sets."""
    return set(_PATRON_PALABRA.findall(normalizar_texto_atlas(texto)))


def resolver_entidad_por_palabras(texto: str, valores_conocidos: Iterable[str]) -> ResolucionEntidad:
    """Bloque 6 -- resolución de entidades genérica (chofer/cliente/
    obra/tipo de carga/comuna: cualquier campo cuyos valores reales ya
    están en el dataset cargado, nunca un catálogo aparte inventado
    para esto). Cuenta, para cada valor conocido, cuántas de sus
    palabras significativas (>= 3 letras, fuera de la lista de palabras
    genéricas) aparecen tal cual en el texto -- "Villagra" coincide con
    "PATRICIO VILLAGRA MUÑOZ" por la palabra "VILLAGRA"; "Salomon Sack"
    coincide con "SALOMON SACK SA" por DOS palabras, evidencia más
    fuerte que una coincidencia de una sola palabra en otro valor.
    Nunca elige entre dos valores con el mismo puntaje máximo -- eso es
    ambigüedad real (Bloque 14), se abstiene."""
    palabras_texto = _palabras(texto)
    coincidencias_por_valor: dict[str, frozenset[str]] = {}
    for valor in {str(v).strip() for v in valores_conocidos if str(v).strip()}:
        palabras_valor = {
            p for p in _palabras(valor)
            if len(p) >= 3 and p not in _PALABRAS_IGNORADAS_ENTIDAD
        }
        if not palabras_valor:
            continue
        coincidencias = palabras_valor & palabras_texto
        if coincidencias:
            coincidencias_por_valor[valor] = frozenset(coincidencias)
    if not coincidencias_por_valor:
        return ResolucionEntidad(SIN_COINCIDENCIA)
    mejor_puntaje = max(len(p) for p in coincidencias_por_valor.values())
    mejores = sorted(v for v, p in coincidencias_por_valor.items() if len(p) == mejor_puntaje)
    if len(mejores) == 1:
        return ResolucionEntidad(RESUELTA, valor=mejores[0], palabras_coincidentes=coincidencias_por_valor[mejores[0]])
    # Bloque 14 -- palabras compartidas por TODOS los candidatos empatados
    # (unión, no sólo del primero): si esta ambigüedad queda enteramente
    # explicada por una coincidencia más fuerte de OTRA familia de
    # entidad, el llamador la descarta como evidencia ya cubierta en vez
    # de bloquear la consulta entera por una ambigüedad irrelevante.
    palabras_union = frozenset().union(*(coincidencias_por_valor[v] for v in mejores))
    return ResolucionEntidad(AMBIGUA, candidatos=tuple(mejores), palabras_coincidentes=palabras_union)


@dataclass(frozen=True)
class CatalogosConsulta:
    """Valores reales YA presentes en el `viajes.csv` cargado -- nunca
    un catálogo paralelo inventado para consultas. Se construye una
    sola vez por dataset (`construir_catalogos_consulta`)."""

    choferes: tuple[str, ...]
    clientes: tuple[str, ...]
    obras: tuple[str, ...]
    tipos_carga: tuple[str, ...]
    comunas: tuple[str, ...]


def construir_catalogos_consulta(viajes: Iterable[Mapping[str, str]]) -> CatalogosConsulta:
    from atlas_core.consultas_atlas import _valores_multivalor

    choferes: set[str] = set()
    clientes: set[str] = set()
    obras: set[str] = set()
    tipos_carga: set[str] = set()
    comunas: set[str] = set()
    for viaje in viajes:
        choferes.update(_valores_multivalor(viaje, "choferes"))
        clientes.update(_valores_multivalor(viaje, "clientes"))
        obras.update(_valores_multivalor(viaje, "obras_destino"))
        tipos_carga.update(_valores_multivalor(viaje, "tipos_carga"))
        comuna = str(viaje.get("localidad_entrega", "")).strip()
        if comuna:
            comunas.add(comuna)
    return CatalogosConsulta(
        choferes=tuple(sorted(choferes)), clientes=tuple(sorted(clientes)),
        obras=tuple(sorted(obras)), tipos_carga=tuple(sorted(tipos_carga)),
        comunas=tuple(sorted(comunas)),
    )


# --- Bloque 3/11: vocabulario de métrica -- palabras clave, no frases
# fijas (nunca "una función por cada pregunta"). Bloque B1 V2 (Bloque
# 10 del ticket): "KMS" (plural coloquial) faltaba -- `\bKM\b` nunca
# calzaba contra "KMS" por falta de límite de palabra, así que "¿cuántos
# KMS recorridos...?" caía silenciosamente a COUNT_VIAJES. Se agregan
# aquí, explícitamente, todas las variantes singular/plural reales en
# vez de inventar un stemmer genérico de español (mismo criterio ya
# usado por el resto de esta tabla: cada keyword se lista tal cual). ---
_PALABRAS_PESO = ("TONELADA", "TONELADAS", "PESO", "KILOS", "KG")
_PALABRAS_KM = ("KM", "KMS", "KILOMETRO", "KILOMETROS", "DISTANCIA", "RECORRIDO", "RECORRIDOS")
_PALABRAS_TIEMPO = ("MINUTOS", "TIEMPO", "DURACION")

_PALABRAS_METRICA = (
    (METRICA_SUM_PESO, _PALABRAS_PESO),
    (METRICA_SUM_KM, _PALABRAS_KM),
    (METRICA_SUM_TIEMPO, _PALABRAS_TIEMPO),
    (METRICA_COUNT_GUIAS, ("GUIA", "GUIAS")),
    (METRICA_LISTAR_VIAJES, ("MUESTRAME", "MUESTRA", "LISTA", "LISTAME", "LISTAR", "DETALLE")),
)

# Bloque B1 V2 (Bloque 4.A del ticket) -- dominio INCIDENCIAS_DOCUMENTALES,
# nunca el dominio VIAJES por defecto. Se revisa ANTES que cualquier otra
# cosa: el resto de esta función está pensada para `viajes.csv`, y una
# pregunta sobre incidencias nunca debería pasar por la resolución de
# entidades de chofer/cliente/obra de ese dominio.
_PALABRAS_INCIDENCIA = ("INCIDENCIA", "INCIDENCIAS", "ERROR DOCUMENTAL", "ERRORES DOCUMENTALES")

# Bloque B1 V2 (Bloque 4.C del ticket) -- "choferes"/"conductores" en
# PLURAL, sin ir precedido de "por"/"cada" (esa es la agrupación V1 ya
# existente, "¿cuántos viajes hizo cada chofer?"), es casi siempre una
# pregunta por CANTIDAD DE PERSONAS, nunca de viajes/filas.
_PALABRAS_CHOFER_PLURAL = ("CHOFERES", "CONDUCTORES")
_PATRON_AGRUPACION_CHOFER = re.compile(r"\bPOR CHOFER(ES)?\b|\bCADA CHOFER\b|\bPOR CONDUCTOR(ES)?\b|\bCADA CONDUCTOR\b")

_PALABRAS_PERIODO = (
    (PERIODO_SEMANA_PASADA, ("SEMANA PASADA", "LA SEMANA PASADA")),
    (PERIODO_ESTA_SEMANA, ("ESTA SEMANA",)),
    (PERIODO_MES_PASADO, ("MES PASADO", "EL MES PASADO")),
    (PERIODO_ESTE_MES, ("ESTE MES",)),
    (PERIODO_AYER, ("AYER",)),
    (PERIODO_HOY, ("HOY",)),
)

_PALABRAS_AGRUPACION = (
    ("chofer", ("CHOFER", "CHOFERES")),
    ("cliente", ("CLIENTE", "CLIENTES")),
    ("obra", ("OBRA", "OBRAS")),
    ("destino", ("DESTINO", "DESTINOS")),
    ("comuna", ("COMUNA", "COMUNAS")),
    ("material", ("MATERIAL", "MATERIALES")),
    ("tipo_carga", ("TIPO DE CARGA", "TIPOS DE CARGA")),
    ("dia", ("DIA", "DIAS", "DIARIO")),
    ("semana", ("SEMANA", "SEMANAS", "SEMANAL")),
    ("mes", ("MES", "MESES", "MENSUAL")),
)

# Vocabulario de pregunta/estructura frecuente en español -- nunca se
# trata como posible nombre propio no reconocido, aunque aparezca
# capitalizado (p. ej. al empezar una subordinada).
_PALABRAS_ESTRUCTURA_PREGUNTA = frozenset({
    "CUANTOS", "CUANTAS", "CUANTO", "CUANTA", "VIAJES", "VIAJE", "GUIA", "GUIAS",
    "HIZO", "HICIERON", "FUE", "FUERON", "PARA", "CON", "DE", "DEL", "LA", "EL",
    "LOS", "LAS", "ESTE", "ESTA", "MES", "SEMANA", "HOY", "AYER", "PASADA",
    "PASADO", "MUESTRAME", "MUESTRA", "LISTA", "LISTAME", "LISTAR", "CADA",
    "POR", "TONELADAS", "TONELADA", "PESO", "KILOS", "KM", "KMS", "KILOMETRO", "KILOMETROS",
    "RECORRIDO", "RECORRIDOS", "MINUTOS", "TIEMPO", "DURACION", "DISTANCIA", "TRANSPORTO", "MOVIO",
    "MOVIMOS", "CHOFER", "CHOFERES", "CONDUCTOR", "CONDUCTORES", "CLIENTE", "CLIENTES", "OBRA", "OBRAS",
    "DESTINO", "DESTINOS", "COMUNA", "COMUNAS", "MATERIAL", "MATERIALES",
    "TIPO", "TIPOS", "CARGA", "DETALLE", "SEMANAL", "MENSUAL", "DIARIO", "DIAS", "DIA",
    "INCIDENCIA", "INCIDENCIAS", "ERROR", "ERRORES", "DOCUMENTAL", "DOCUMENTALES",
    "TRABAJARON", "TRABAJO", "CARGARON", "CARGO", "REGISTRADAS", "REGISTRADOS", "TENEMOS",
})
_PATRON_PALABRA_CAPITALIZADA = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")


def _palabras_capitalizadas_sin_explicar(texto: str, palabras_reclamadas: set[str]) -> tuple[str, ...]:
    """Bloque 6/20 -- palabras con mayúscula inicial en el texto
    ORIGINAL (nunca la primera del enunciado, capitalizada sólo por
    posición) que ninguna familia de entidad pudo explicar -- evidencia
    fuerte de un nombre propio real que Atlas no reconoce. Nunca
    decodifica ni adivina de quién se trata, sólo señala que existe."""
    palabras = _PATRON_PALABRA_CAPITALIZADA.findall(texto)
    sospechosas = []
    for indice, palabra in enumerate(palabras):
        if indice == 0 or len(palabra) < 3 or not palabra[0].isupper():
            continue
        normalizada = normalizar_texto_atlas(palabra)
        if normalizada in _PALABRAS_ESTRUCTURA_PREGUNTA or normalizada in palabras_reclamadas:
            continue
        sospechosas.append(palabra)
    return tuple(sospechosas)


def interpretar_consulta_determinista(
    texto: str, *, catalogos: CatalogosConsulta,
) -> tuple[ConsultaAtlas | None, tuple[str, ...]]:
    """Bloque 10/21 -- camino rápido sin B1. Devuelve `(None, avisos)`
    si no logra reconocer ninguna métrica (el llamador debe entonces
    intentar B1); devuelve `(consulta, avisos)` cuando sí puede.
    `avisos` señala ambigüedades encontradas (Bloque 14) -- nunca elige
    arbitrariamente entre dos entidades reales."""
    normalizado = normalizar_texto_atlas(texto)
    avisos: list[str] = []

    # Bloque B1 V2 (Bloque 4.A/9 del ticket) -- dominio
    # INCIDENCIAS_DOCUMENTALES, resuelto ANTES que nada: es una fuente
    # de datos distinta a `viajes.csv`, así que el resto de esta función
    # (resolución de entidades chofer/cliente/obra, agrupación, etc, todo
    # pensado para el reporte de viajes) no aplica en absoluto.
    if any(re.search(rf"\b{re.escape(p)}\b", normalizado) for p in _PALABRAS_INCIDENCIA):
        return ConsultaAtlas(
            metrica=METRICA_COUNT_INCIDENCIAS, dominio=DOMINIO_INCIDENCIAS_DOCUMENTALES, filtros={},
        ), tuple(avisos)

    # Bloque B1 V2 (Bloque 4.C del ticket) -- "cuántos choferes/
    # conductores [trabajaron/hicieron viajes/cargaron]..." pregunta por
    # CANTIDAD DE PERSONAS, nunca por cantidad de viajes/filas. Se separa
    # de "por chofer"/"cada chofer" (agrupación V1 ya existente).
    if (
        any(re.search(rf"\b{re.escape(p)}\b", normalizado) for p in _PALABRAS_CHOFER_PLURAL)
        and not _PATRON_AGRUPACION_CHOFER.search(normalizado)
    ):
        filtros_chofer: dict[str, str] = {}
        for nombre_periodo, frases in _PALABRAS_PERIODO:
            if any(frase in normalizado for frase in frases):
                filtros_chofer["periodo"] = nombre_periodo
                break
        return ConsultaAtlas(metrica=METRICA_COUNT_DISTINCT_CHOFER, filtros=filtros_chofer), tuple(avisos)

    metrica = METRICA_COUNT_VIAJES
    for candidata, palabras in _PALABRAS_METRICA:
        if any(re.search(rf"\b{re.escape(p)}\b", normalizado) for p in palabras):
            metrica = candidata
            break
    else:
        # Bloque B1 V2 (Bloque 7 del ticket) -- "el determinístico
        # construyó algo válido -> B1 no interviene" era el bug: antes,
        # cualquier "cuántos X" sin métrica reconocible caía aquí
        # igual y se aceptaba en silencio como COUNT_VIAJES. Ahora sólo
        # se acepta ese default cuando el texto realmente menciona
        # "viaje(s)" -- cualquier otro "cuántos X" sin evidencia de
        # métrica se cede a B1 (o "no interpretable" sin B1 configurado),
        # nunca se adivina.
        if not any(re.search(rf"\b{re.escape(p)}\b", normalizado) for p in ("VIAJE", "VIAJES")):
            return None, avisos  # ninguna señal de métrica reconocible -- intentar B1

    filtros: dict[str, str] = {}

    for nombre_periodo, frases in _PALABRAS_PERIODO:
        if any(frase in normalizado for frase in frases):
            filtros["periodo"] = nombre_periodo
            break

    agrupacion: str | None = None
    for campo_agrupacion, palabras in _PALABRAS_AGRUPACION:
        patrones = (rf"\bCADA {p}\b" for p in palabras)
        patrones_por = (rf"\bPOR {p}\b" for p in palabras)
        if any(re.search(p, normalizado) for p in (*patrones, *patrones_por)):
            agrupacion = campo_agrupacion
            break

    # Bloque 6/12 -- las 5 familias de entidad se resuelven cada una
    # contra SU PROPIO catálogo (nunca se mezclan), pero un mismo
    # fragmento de texto puede coincidir por casualidad con valores de
    # DOS familias distintas (caso real: "Salomon" es palabra del
    # cliente "SALOMON SACK SA" Y del chofer "SALOMÓN PIZARRO", tras
    # normalizar acentos). Se resuelven TODAS primero, sin comprometer
    # ningún filtro todavía; luego se aceptan de más fuerte a más débil
    # (más palabras coincidentes primero) -- una coincidencia cuyas
    # palabras están COMPLETAMENTE cubiertas por una coincidencia ya
    # aceptada más fuerte de otra familia se descarta (evidencia ya
    # explicada por la más fuerte, nunca un filtro extra espurio).
    candidatos_por_campo: dict[str, ResolucionEntidad] = {}
    for campo, valores, activa in (
        ("chofer", catalogos.choferes, agrupacion != "chofer"),
        ("cliente", catalogos.clientes, agrupacion != "cliente"),
        ("obra", catalogos.obras, agrupacion != "obra"),
        ("tipo_carga", catalogos.tipos_carga, agrupacion != "tipo_carga"),
        ("comuna", catalogos.comunas, agrupacion != "comuna"),
    ):
        if not activa or not valores:
            continue
        resolucion = resolver_entidad_por_palabras(texto, valores)
        if resolucion.estado in (RESUELTA, AMBIGUA):
            candidatos_por_campo[campo] = resolucion

    # Procesa TODAS las familias juntas, de más fuerte a más débil (más
    # palabras coincidentes primero) -- una ambigüedad cuyas palabras ya
    # quedaron enteramente explicadas por una coincidencia RESUELTA más
    # fuerte de otra familia (caso real: "obra" ambigua entre dos
    # variantes OCR de "SALOMON SACK SA ..." queda cubierta por
    # "cliente" = "SALOMON SACK SA") se descarta en silencio; sólo
    # bloquea la consulta una ambigüedad que sigue sin explicación.
    palabras_reclamadas: set[str] = set()
    for campo, resolucion in sorted(
        candidatos_por_campo.items(), key=lambda item: -len(item[1].palabras_coincidentes)
    ):
        if campo == "obra" and "cliente" in filtros:
            continue  # ya cubierto por cliente -- evita sobre-restringir
        if resolucion.palabras_coincidentes and resolucion.palabras_coincidentes <= palabras_reclamadas:
            continue  # evidencia ya explicada por una coincidencia más fuerte de otra familia
        if resolucion.estado == AMBIGUA:
            avisos.append(f"AMBIGUO:{campo}:" + " | ".join(resolucion.candidatos))
            continue
        filtros[campo] = resolucion.valor
        palabras_reclamadas |= resolucion.palabras_coincidentes

    if any(a.startswith("AMBIGUO:") for a in avisos):
        return None, tuple(avisos)

    # Bloque 6/20 -- "no adivinar": si el texto ORIGINAL trae una
    # palabra con mayúscula inicial (nunca la primera del enunciado,
    # capitalizada sólo por posición) que ninguna familia de entidad
    # pudo explicar, es casi con certeza un nombre propio que Atlas no
    # reconoce (caso real: "Lazcano", sin chofer así en el dataset) --
    # nunca se ignora en silencio y se responde sobre TODOS los viajes
    # como si nadie se hubiera mencionado. Se cede a B1 (o se reporta
    # "no interpretable") en vez de adivinar.
    sin_explicar = _palabras_capitalizadas_sin_explicar(texto, palabras_reclamadas)
    if sin_explicar:
        return None, (*avisos, "SIN_COINCIDENCIA:" + ", ".join(sin_explicar))

    return ConsultaAtlas(metrica=metrica, filtros=filtros, agrupacion=agrupacion), tuple(avisos)


def validar_compatibilidad_semantica(pregunta: str, consulta: ConsultaAtlas) -> str | None:
    """Bloque 6/7 -- red de seguridad semántica, NUNCA un solucionador
    completo de la pregunta. Una `ConsultaAtlas` estructuralmente válida
    (pasa `validar_consulta`) no es necesariamente CORRECTA: "¿cuántos
    kms recorridos tiene Retamal?" con `metrica=COUNT_VIAJES` es válida
    y absurda a la vez. Detecta sólo las contradicciones fuertes que el
    Bloque 6 del ticket exige (KM/PESO/CHOFERES-cantidad/INCIDENCIAS
    contra la métrica u dominio efectivamente elegidos); cualquier otra
    cosa se deja pasar -- el llamador escala a B1 cuando esto devuelve
    un motivo no-`None` (Bloque 7: "cambiar el criterio de cuándo entra
    B1"), nunca ejecuta la consulta rechazada tal cual."""
    normalizado = normalizar_texto_atlas(pregunta)

    def _menciona(palabras: tuple[str, ...]) -> bool:
        return any(re.search(rf"\b{re.escape(p)}\b", normalizado) for p in palabras)

    if _menciona(_PALABRAS_KM) and consulta.metrica != METRICA_SUM_KM:
        return "la pregunta pide distancia/km, pero la consulta no calcula distancia"
    if _menciona(_PALABRAS_PESO) and consulta.metrica != METRICA_SUM_PESO:
        return "la pregunta pide peso/toneladas, pero la consulta no suma peso"
    if _menciona(_PALABRAS_INCIDENCIA) and consulta.dominio != DOMINIO_INCIDENCIAS_DOCUMENTALES:
        return "la pregunta pide incidencias documentales, pero la consulta consulta viajes"
    if (
        _menciona(_PALABRAS_CHOFER_PLURAL)
        and not _PATRON_AGRUPACION_CHOFER.search(normalizado)
        and consulta.metrica == METRICA_COUNT_VIAJES
    ):
        return "la pregunta pide cantidad de choferes (personas), pero la consulta cuenta viajes"
    return None
