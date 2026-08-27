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
    DOMINIO_EVENTOS,
    DOMINIO_INCIDENCIAS_DOCUMENTALES,
    DOMINIO_VIAJES,
    ConsultaAtlas,
    METRICA_COUNT_DISTINCT_CHOFER,
    METRICA_COUNT_DISTINCT_RELACION,
    METRICA_COUNT_EVENTOS,
    METRICA_COUNT_GUIAS,
    METRICA_COUNT_INCIDENCIAS,
    METRICA_COUNT_VIAJES,
    METRICA_LIST_RELACION,
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
    RELACIONES_SOPORTADAS,
    normalizar_texto_atlas,
)
from atlas_core.extractor import _patente_valida

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
    # Bloque UNIVERSAL V1.1 -- sólo lo usa `resolver_patente_por_texto`:
    # cuando el estado es SIN_COINCIDENCIA pero el texto trae un token con
    # FORMA de patente (misma regla que ya usa el resto de Atlas,
    # `atlas_core.extractor._patente_valida` -- nunca una regla nueva)
    # que no coincide con ninguna patente conocida, se conserva aquí para
    # poder responder "no encontré viajes asociados a X" en vez de perder
    # el filtro en silencio (Bloque 1 del ticket UNIVERSAL V1.1).
    token_no_reconocido: str = ""


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


def resolver_patente_por_texto(texto: str, valores_conocidos: Iterable[str]) -> ResolucionEntidad:
    """Bloque UNIVERSAL V1 (Bloque 7/18 del ticket) -- resolución de
    entidad para patentes: a diferencia de chofer/cliente/obra (nombres
    largos, coincidencia por PALABRAS significativas), una patente es un
    único token alfanumérico corto -- coincidencia EXACTA de token,
    nunca por subcadena (evita que "JB8" coincida con "JB8529"). Reusa
    el mismo tokenizador `_palabras` (ya separa "JB8529" como un token
    completo)."""
    palabras_texto = _palabras(texto)
    conocidas = {normalizar_texto_atlas(v): str(v).strip() for v in valores_conocidos if str(v).strip()}
    encontradas = sorted({conocidas[p] for p in palabras_texto if p in conocidas})
    if not encontradas:
        # Bloque UNIVERSAL V1.1 (Bloque 1 del ticket) -- "filtro no
        # resuelto ≠ quitar filtro": si ningún token conocido coincidió
        # pero el texto SÍ trae un token con forma de patente (misma
        # validación que ya usa el resto de Atlas), se conserva para que
        # el llamador pueda responder "no encontré viajes asociados a
        # X" en vez de degradar silenciosamente a un conteo sin filtro.
        candidato = next((p for p in sorted(palabras_texto) if _patente_valida(p)), "")
        return ResolucionEntidad(SIN_COINCIDENCIA, token_no_reconocido=candidato)
    if len(encontradas) == 1:
        return ResolucionEntidad(
            RESUELTA, valor=encontradas[0], palabras_coincidentes=frozenset({normalizar_texto_atlas(encontradas[0])}),
        )
    return ResolucionEntidad(
        AMBIGUA, candidatos=tuple(encontradas),
        palabras_coincidentes=frozenset(normalizar_texto_atlas(v) for v in encontradas),
    )


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
    # Bloque UNIVERSAL V1 (Bloque 7 del ticket) -- tracto + rampla
    # combinados: un usuario que pregunta por una patente no sabe (ni
    # debería saber) cuál de las dos es.
    patentes: tuple[str, ...] = ()


def construir_catalogos_consulta(viajes: Iterable[Mapping[str, str]]) -> CatalogosConsulta:
    from atlas_core.consultas_atlas import _valores_multivalor

    choferes: set[str] = set()
    clientes: set[str] = set()
    obras: set[str] = set()
    tipos_carga: set[str] = set()
    comunas: set[str] = set()
    patentes: set[str] = set()
    for viaje in viajes:
        choferes.update(_valores_multivalor(viaje, "choferes"))
        clientes.update(_valores_multivalor(viaje, "clientes"))
        obras.update(_valores_multivalor(viaje, "obras_destino"))
        tipos_carga.update(_valores_multivalor(viaje, "tipos_carga"))
        patentes.update(_valores_multivalor(viaje, "patentes_tracto"))
        patentes.update(_valores_multivalor(viaje, "patentes_rampla"))
        comuna = str(viaje.get("localidad_entrega", "")).strip()
        if comuna:
            comunas.add(comuna)
    return CatalogosConsulta(
        choferes=tuple(sorted(choferes)), clientes=tuple(sorted(clientes)),
        obras=tuple(sorted(obras)), tipos_carga=tuple(sorted(tipos_carga)),
        comunas=tuple(sorted(comunas)), patentes=tuple(sorted(patentes)),
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
# Bloque UNIVERSAL V1.1 (Bloque 3 del ticket) -- unidad de PIEZAS/UNIDADES
# físicas, que `viajes.csv` NUNCA registra (sólo `peso_total_viaje_kg`,
# nunca un conteo de piezas) -- caso real: "¿Cuántas barras de hormigón
# se movieron?" no puede responderse con toneladas como si fuera lo
# mismo. Lista abierta a cualquier unidad física de pieza, no sólo
# "barras" (Bloque 12: "no hardcodear frases" -- esto es vocabulario de
# UNIDAD, igual que _PALABRAS_PESO/_PALABRAS_KM ya existentes, no una
# frase fija).
_PALABRAS_UNIDADES_FISICAS = (
    "BARRA", "BARRAS", "PIEZA", "PIEZAS", "UNIDAD", "UNIDADES",
    "ROLLO", "ROLLOS", "PLANCHA", "PLANCHAS", "PAQUETE", "PAQUETES",
)
# Bloque UNIVERSAL V1.1 (Bloque 2 del ticket) -- "la entidad después de
# CUÁNTOS/CUÁNTAS debe corresponder a la dimensión contada": caso real
# "¿Cuántas patentes están vinculadas correctamente a choferes?"
# respondía "10 choferes" porque el chequeo de CHOFERES en plural (ver
# `_PALABRAS_CHOFER_PLURAL` más abajo) no distinguía "cuántos choferes"
# (cuenta personas) de "cuántas patentes...a choferes" (cuenta
# patentes, "choferes" es sólo un calificador). Reutiliza las mismas
# columnas ya declaradas como RELACIÓN (`RELACIONES_SOPORTADAS`) --
# nunca una dimensión nueva por fuera de ese contrato. "chofer" queda
# deliberadamente FUERA de esta tabla: ese caso ya lo resuelve
# `_PALABRAS_CHOFER_PLURAL`/`METRICA_COUNT_DISTINCT_CHOFER`, no se toca
# para no arriesgar ninguna regresión ya probada.
_SUSTANTIVO_CUANTOS_A_RELACION = {
    "PATENTE": "vehiculo", "PATENTES": "vehiculo", "VEHICULO": "vehiculo", "VEHICULOS": "vehiculo",
    "CLIENTE": "cliente", "CLIENTES": "cliente",
    "OBRA": "obra", "OBRAS": "obra",
    "DESTINO": "destino", "DESTINOS": "destino",
    "COMUNA": "comuna", "COMUNAS": "comuna",
    "MATERIAL": "material", "MATERIALES": "material",
}
_PATRON_CUANTOS_SUSTANTIVO = re.compile(r"\bCUANT[OA]S?\b\s+([A-Z]+)")

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

# Bloque UNIVERSAL V1 (Bloque 9 del ticket) -- vocabulario de EVENTOS
# operacionales. Orden = especificidad: los tipos específicos
# (ESPERA_AUTORIZACION_ESTADIA, DEVOLUCION_TOTAL/PARCIAL, DOBLE_VUELTA)
# se revisan ANTES que el genérico "DEVOLUCION" (Bloque 19, caso B:
# "cuántas devoluciones tuvo Cliente X" debe contar TOTAL + PARCIAL
# juntas) -- primer match gana, mismo criterio que `_PALABRAS_METRICA`.
# Los códigos son EXACTAMENTE los de `atlas_core.mobile.TIPOS_NOVEDAD`
# (única fuente real hoy), pero el ejecutor (`ejecutar_consulta_eventos`)
# nunca valida contra esta lista -- cualquier `tipo_evento` presente en
# los datos es consultable, incluido uno de un rubro futuro que esta
# tabla no conoce (Bloque 20/21: anti-hardcode).
_PALABRAS_EVENTO = (
    ("ESPERA_AUTORIZACION_ESTADIA", ("ESPERA DE AUTORIZACION", "ESPERA AUTORIZACION")),
    ("DEVOLUCION_TOTAL", ("DEVOLUCION TOTAL", "DEVOLUCIONES TOTALES")),
    ("DEVOLUCION_PARCIAL", ("DEVOLUCION PARCIAL", "DEVOLUCIONES PARCIALES")),
    ("DOBLE_VUELTA", ("DOBLE VUELTA", "DOBLES VUELTAS")),
    ("TIENE_ESTADIA", ("ESTADIA", "ESTADIAS")),
    ("DEVOLUCION", ("DEVOLUCION", "DEVOLUCIONES")),
)
_PALABRAS_EVENTO_AGRUPACION = (
    ("chofer", ("CHOFER", "CHOFERES")),
    ("cliente", ("CLIENTE", "CLIENTES")),
    ("obra", ("OBRA", "OBRAS")),
)
_PATRON_TOP = re.compile(r"\bMAS\b|\bMAYOR\b")

# Bloque UNIVERSAL V1 (Bloque 8/18 del ticket) -- vocabulario de
# preguntas RELACIONALES: "en qué VIAJES/GUÍAS aparece", "con qué
# CHOFER/CLIENTE está vinculada", "qué PATENTES/VEHÍCULOS ha usado".
_PATRON_APARECE = re.compile(r"\bAPARECE(N)?\b")
_PATRON_VINCULAD = re.compile(r"\bVINCULAD[OA]S?\b")
_PATRON_HA_USADO = re.compile(r"\bHAN? (USADO|UTILIZADO)\b|\bUSO\b|\bUTILIZO\b")
_PATRON_PATENTE_KW = re.compile(r"\bPATENTES?\b|\bVEHICULOS?\b")
_PATRON_GUIA_KW = re.compile(r"\bGUIAS?\b")
_PATRON_CHOFER_KW = re.compile(r"\bCHOFER(ES)?\b|\bCONDUCTOR(ES)?\b")
_PATRON_CLIENTE_KW = re.compile(r"\bCLIENTES?\b")
_PATRON_VIAJE_KW = re.compile(r"\bVIAJES?\b")
_PATRON_NUMERO_TRANSPORTE = re.compile(r"\b(\d{6,})\b")

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
    "PATENTE", "PATENTES", "VEHICULO", "VEHICULOS", "VINCULADA", "VINCULADO", "VINCULADAS",
    "VINCULADOS", "APARECE", "APARECEN", "USADO", "UTILIZADO", "USO", "UTILIZO", "HAN", "HA",
    "ESTADIA", "ESTADIAS", "DEVOLUCION", "DEVOLUCIONES", "TOTAL", "TOTALES", "PARCIAL",
    "PARCIALES", "VUELTA", "VUELTAS", "DOBLE", "DOBLES", "MAS", "MAYOR", "AUTORIZACION", "ESPERA",
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


def _intentar_consulta_relacional(
    texto: str, normalizado: str, catalogos: CatalogosConsulta,
) -> tuple[ConsultaAtlas | None, tuple[str, ...]] | None:
    """Bloque UNIVERSAL V1 (Bloque 8/18 del ticket) -- detecta preguntas
    RELACIONALES ("en qué viajes aparece X", "con qué chofer está
    vinculada X", "qué patentes ha usado X", "en qué guías aparece X",
    "qué cliente aparece en el viaje N") y las traduce al MISMO
    `METRICA_LIST_RELACION`/`LISTAR_VIAJES` genéricos -- nunca un
    comando nuevo por combinación entidad-relación. Devuelve `None`
    (nunca `(None, avisos)`) cuando el texto no calza con ninguna forma
    relacional conocida -- el llamador sigue con el resto del flujo."""
    # E) "qué cliente aparece en el viaje <numero_transporte>"
    if _PATRON_CLIENTE_KW.search(normalizado) and _PATRON_APARECE.search(normalizado) and _PATRON_VIAJE_KW.search(normalizado):
        numero = _PATRON_NUMERO_TRANSPORTE.search(normalizado)
        if numero:
            return ConsultaAtlas(
                metrica=METRICA_LIST_RELACION, relacion="cliente", filtros={"numero_transporte": numero.group(1)},
            ), ()

    resolucion_patente = (
        resolver_patente_por_texto(texto, catalogos.patentes) if catalogos.patentes else ResolucionEntidad(SIN_COINCIDENCIA)
    )
    if resolucion_patente.estado == AMBIGUA:
        return None, ("AMBIGUO:patente:" + " | ".join(resolucion_patente.candidatos),)

    # Bloque UNIVERSAL V1.1 (Bloque 1/10 del ticket) -- casos reales
    # "¿En qué viajes aparece JD8659?"/"JE8659?": el token SÍ tiene forma
    # de patente pero no existe en ninguna patente real del dataset. Sin
    # esto, el resto de esta función nunca calza (exige RESUELTA) y el
    # texto cae al flujo genérico de más abajo -- que tampoco lo explica
    # (un token alfanumérico nunca activa `_palabras_capitalizadas_sin_explicar`,
    # esa función sólo mira letras) -- terminando en un COUNT_VIAJES SIN
    # FILTRO ("universo completo"), exactamente el bug reportado. Se
    # exige evidencia de que la pregunta SÍ es sobre una patente
    # (keyword de patente/vehículo, o "aparece"/"vinculada" + guía/chofer)
    # para no interceptar cualquier token de 6 caracteres suelto.
    if (
        resolucion_patente.estado == SIN_COINCIDENCIA
        and resolucion_patente.token_no_reconocido
        and (
            _PATRON_PATENTE_KW.search(normalizado)
            or _PATRON_APARECE.search(normalizado)
            or _PATRON_VINCULAD.search(normalizado)
        )
    ):
        return None, (f"SIN_COINCIDENCIA_PATENTE:{resolucion_patente.token_no_reconocido}",)

    if resolucion_patente.estado == RESUELTA and _PATRON_APARECE.search(normalizado):
        # A) "en qué viajes aparece la patente X"
        # D) "en qué guías aparece X"
        if _PATRON_GUIA_KW.search(normalizado):
            return ConsultaAtlas(
                metrica=METRICA_LIST_RELACION, relacion="guia", filtros={"patente": resolucion_patente.valor},
            ), ()
        return ConsultaAtlas(metrica=METRICA_LISTAR_VIAJES, filtros={"patente": resolucion_patente.valor}), ()

    # B) "con qué chofer está vinculada X"
    if resolucion_patente.estado == RESUELTA and _PATRON_VINCULAD.search(normalizado) and _PATRON_CHOFER_KW.search(normalizado):
        return ConsultaAtlas(
            metrica=METRICA_LIST_RELACION, relacion="chofer", filtros={"patente": resolucion_patente.valor},
        ), ()

    # C) "qué patentes ha usado <chofer>"
    if _PATRON_HA_USADO.search(normalizado) and _PATRON_PATENTE_KW.search(normalizado):
        resolucion_chofer = resolver_entidad_por_palabras(texto, catalogos.choferes)
        if resolucion_chofer.estado == RESUELTA:
            return ConsultaAtlas(
                metrica=METRICA_LIST_RELACION, relacion="vehiculo", filtros={"chofer": resolucion_chofer.valor},
            ), ()
        if resolucion_chofer.estado == AMBIGUA:
            return None, ("AMBIGUO:chofer:" + " | ".join(resolucion_chofer.candidatos),)

    return None


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

    # Bloque UNIVERSAL V1 (Bloque 8/18 del ticket) -- preguntas
    # RELACIONALES ("en qué viajes aparece X", "qué patentes ha usado
    # X"...). Se revisa ANTES que el resto: estas preguntas casi nunca
    # contienen "cuántos" y su métrica (LIST_RELACION/LISTAR_VIAJES) no
    # tiene nada que ver con el conteo por defecto de más abajo.
    relacional = _intentar_consulta_relacional(texto, normalizado, catalogos)
    if relacional is not None:
        return relacional

    # Bloque UNIVERSAL V1 (Bloque 9/19 del ticket) -- dominio EVENTOS
    # (estadía, espera autorización, devolución total/parcial, doble
    # vuelta -- y cualquier tipo futuro, nunca una lista cerrada en el
    # EJECUTOR; sólo esta tabla de vocabulario conoce los nombres de hoy).
    # Se revisa ANTES que el resto por la misma razón que INCIDENCIAS:
    # es una fuente de datos distinta a `viajes.csv`.
    tipo_evento_detectado: str | None = None
    for tipo, palabras in _PALABRAS_EVENTO:
        if any(re.search(rf"\b{re.escape(p)}\b", normalizado) for p in palabras):
            tipo_evento_detectado = tipo
            break
    if tipo_evento_detectado is not None:
        filtros_evento: dict[str, str] = {"tipo_evento": tipo_evento_detectado}
        for nombre_periodo, frases in _PALABRAS_PERIODO:
            if any(frase in normalizado for frase in frases):
                filtros_evento["periodo"] = nombre_periodo
                break
        agrupacion_evento: str | None = None
        limite_evento: int | None = None
        for campo_agrupacion, palabras_campo in _PALABRAS_EVENTO_AGRUPACION:
            patrones_agrup = [rf"\bPOR {pal}\b" for pal in palabras_campo] + [rf"\bCADA {pal}\b" for pal in palabras_campo]
            patrones_top = [rf"\bQUE {pal}\b" for pal in palabras_campo]
            if any(re.search(p, normalizado) for p in patrones_agrup):
                agrupacion_evento = campo_agrupacion
                break
            if any(re.search(p, normalizado) for p in patrones_top):
                agrupacion_evento = campo_agrupacion
                if _PATRON_TOP.search(normalizado):
                    limite_evento = 1
                break
        # Bloque 6/12 -- misma lógica que el flujo de viajes: resuelve
        # las 3 familias primero, sin comprometer nada, y sólo acepta de
        # más fuerte a más débil (evita el mismo cruce real "Salomon
        # Sack" -> coincide 1 palabra con el chofer "SALOMÓN PIZARRO" Y
        # 2 palabras con el cliente "SALOMON SACK SA"; sin este orden,
        # ganaría el primero que se probara, casi siempre el equivocado).
        candidatos_evento: dict[str, ResolucionEntidad] = {}
        for campo, valores, activa in (
            ("chofer", catalogos.choferes, agrupacion_evento != "chofer"),
            ("cliente", catalogos.clientes, agrupacion_evento != "cliente"),
            ("obra", catalogos.obras, agrupacion_evento != "obra"),
        ):
            if not activa or not valores:
                continue
            resolucion = resolver_entidad_por_palabras(texto, valores)
            if resolucion.estado in (RESUELTA, AMBIGUA):
                candidatos_evento[campo] = resolucion
        palabras_reclamadas_evento: set[str] = set()
        for campo, resolucion in sorted(
            candidatos_evento.items(), key=lambda item: -len(item[1].palabras_coincidentes)
        ):
            if resolucion.palabras_coincidentes and resolucion.palabras_coincidentes <= palabras_reclamadas_evento:
                continue
            if resolucion.estado == AMBIGUA:
                return None, (f"AMBIGUO:{campo}:" + " | ".join(resolucion.candidatos),)
            filtros_evento[campo] = resolucion.valor
            palabras_reclamadas_evento |= resolucion.palabras_coincidentes
        return ConsultaAtlas(
            metrica=METRICA_COUNT_EVENTOS, dominio=DOMINIO_EVENTOS, filtros=filtros_evento,
            agrupacion=agrupacion_evento, limite=limite_evento,
        ), tuple(avisos)

    # Bloque UNIVERSAL V1.1 (Bloque 2 del ticket) -- "cuántas patentes/
    # vehículos/clientes/obras/destinos/comunas/materiales...": la
    # dimensión contada es la que sigue a CUÁNTOS/CUÁNTAS, nunca otra
    # entidad que la frase sólo mencione como calificador (caso real:
    # "cuántas patentes están vinculadas correctamente a CHOFERES" cuenta
    # patentes, no choferes). Se revisa ANTES que el chequeo de CHOFERES
    # en plural de más abajo, precisamente para que ese chequeo no se
    # dispare por error cuando "choferes" aparece pero no es la
    # dimensión pedida. "chofer" no está en la tabla de dispatch a
    # propósito -- ese caso lo sigue resolviendo, sin cambios, el
    # chequeo de CHOFERES en plural.
    coincidencia_cuantos = _PATRON_CUANTOS_SUSTANTIVO.search(normalizado)
    if coincidencia_cuantos is not None:
        relacion_contada = _SUSTANTIVO_CUANTOS_A_RELACION.get(coincidencia_cuantos.group(1))
        if relacion_contada is not None:
            filtros_relacion: dict[str, str] = {}
            for nombre_periodo, frases in _PALABRAS_PERIODO:
                if any(frase in normalizado for frase in frases):
                    filtros_relacion["periodo"] = nombre_periodo
                    break
            return ConsultaAtlas(
                metrica=METRICA_COUNT_DISTINCT_RELACION, relacion=relacion_contada, filtros=filtros_relacion,
            ), tuple(avisos)

    # Bloque UNIVERSAL V1.1 (Bloque 3 del ticket) -- unidad de piezas/
    # unidades físicas que `viajes.csv` no registra (caso real: "¿Cuántas
    # barras de hormigón se movieron?"). Mismo principio que el bloque
    # anterior (Bloque 2): sólo dispara cuando la unidad física es la
    # dimensión CONTADA (el sustantivo justo después de CUÁNTOS/CUÁNTAS)
    # -- nunca cuando sólo aparece como filtro/calificador ("¿Cuántos
    # VIAJES hizo Villagra con rollos...?" sigue contando viajes, sin
    # esto "rollos" hubiera secuestrado esa consulta entera, regresión
    # real encontrada al implementar este bloque). Nunca reinterpreta en
    # silencio como peso: construye la consulta de peso que SÍ puede
    # responder (filtrada por tipo de carga si el propio texto lo nombra,
    # p. ej. "BARRAS" ya es un valor real de `tipos_carga`) y dispara un
    # aviso `UNIDAD_NO_DISPONIBLE` para que la presentación explique la
    # limitación en vez de mostrar toneladas como si fuera la cantidad
    # de piezas pedida (Bloque 22: la explicación vive en la
    # presentación, aquí sólo se señala el hecho).
    sustantivo_contado = coincidencia_cuantos.group(1) if coincidencia_cuantos is not None else None
    if (
        sustantivo_contado in _PALABRAS_UNIDADES_FISICAS
        and not any(re.search(rf"\b{re.escape(p)}\b", normalizado) for p in _PALABRAS_PESO)
    ):
        filtros_unidad: dict[str, str] = {}
        resolucion_tipo_carga = resolver_entidad_por_palabras(texto, catalogos.tipos_carga)
        if resolucion_tipo_carga.estado == RESUELTA:
            filtros_unidad["tipo_carga"] = resolucion_tipo_carga.valor
        for nombre_periodo, frases in _PALABRAS_PERIODO:
            if any(frase in normalizado for frase in frases):
                filtros_unidad["periodo"] = nombre_periodo
                break
        avisos.append(f"UNIDAD_NO_DISPONIBLE:{sustantivo_contado}")
        return ConsultaAtlas(metrica=METRICA_SUM_PESO, filtros=filtros_unidad), tuple(avisos)

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
    # Bloque UNIVERSAL V1.1 (Bloque 3/12 del ticket) -- red de seguridad
    # para cuando B1 (no el determinístico, que ya no comete este error
    # desde este bloque) reinterpreta "cuántas piezas/unidades/barras" como
    # SUM_PESO sin que la pregunta mencione peso en absoluto: se rechaza
    # como respuesta directa -- nunca se ejecuta un peso como si fuera un
    # conteo de piezas.
    if (
        _menciona(_PALABRAS_UNIDADES_FISICAS)
        and not _menciona(_PALABRAS_PESO)
        and consulta.metrica == METRICA_SUM_PESO
    ):
        return "la pregunta pide cantidad de piezas/unidades, pero la consulta suma peso (unidad distinta)"
    # Bloque UNIVERSAL V1.1 (Bloque 2/12 del ticket) -- "cuántas patentes/
    # vehículos" nunca debe resolverse como cantidad de choferes (mismo
    # caso real de `_PATRON_CUANTOS_SUSTANTIVO`, aplicado también a lo
    # que B1 pudiera proponer).
    if (
        _PATRON_PATENTE_KW.search(normalizado)
        and re.search(r"\bCUANT[OA]S?\b", normalizado)
        and consulta.metrica == METRICA_COUNT_DISTINCT_CHOFER
    ):
        return "la pregunta pide cantidad de patentes/vehículos, pero la consulta cuenta choferes"
    if _menciona(_PALABRAS_INCIDENCIA) and consulta.dominio != DOMINIO_INCIDENCIAS_DOCUMENTALES:
        return "la pregunta pide incidencias documentales, pero la consulta consulta viajes"
    if (
        _menciona(_PALABRAS_CHOFER_PLURAL)
        and not _PATRON_AGRUPACION_CHOFER.search(normalizado)
        and consulta.metrica == METRICA_COUNT_VIAJES
    ):
        return "la pregunta pide cantidad de choferes (personas), pero la consulta cuenta viajes"
    # Bloque UNIVERSAL V1 (Bloque 6/9 del ticket) -- eventos operacionales
    # (estadía/devolución/doble vuelta/espera autorización) piden el
    # dominio EVENTOS, nunca VIAJES ni INCIDENCIAS_DOCUMENTALES.
    if (
        any(_menciona(palabras) for _, palabras in _PALABRAS_EVENTO)
        and consulta.dominio != DOMINIO_EVENTOS
    ):
        return "la pregunta pide un evento operacional (estadía/devolución/doble vuelta), pero la consulta no usa ese dominio"
    return None
