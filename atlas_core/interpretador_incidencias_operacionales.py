"""Bloque INCIDENCIAS OPERACIONALES V1.1 -- interpretación DETERMINÍSTICA
de instrucciones explícitas en español hacia acciones estructuradas de la
allowlist ya existente (`atlas_core.comandos_incidencias_operacionales.
ACCIONES_SOPORTADAS`: REGISTRAR_INCIDENCIA / REVISAR_SIN_INCIDENCIA /
ACTUALIZAR_GESTION).

Nunca escribe, nunca resuelve guía->viaje (eso sigue siendo trabajo de
`previsualizar_lote`/`aplicar_lote`, en el módulo ya aprobado) y nunca
llama a un LLM: las 5 instrucciones de referencia (V1.1) son lo bastante
mecánicas -- números de guía + vocabulario fijo -- para reconocerlas sin
ambigüedad con reglas, el mismo criterio "determinístico cuando es
posible" que ya usa `atlas_core.interpretador_consultas` para el lado de
sólo-lectura. Un fragmento que esta función no puede clasificar (ninguna
palabra de tipo/gestión reconocida cerca de una guía) NUNCA se descarta
en silencio: se emite con `accion=""`, que `previsualizar_lote` ya
rechaza como `ACCION_NO_PERMITIDA` -- así el humano SIEMPRE ve qué parte
del lote no se entendió, nunca una guía que desaparece sola."""
from __future__ import annotations

import re
from typing import NamedTuple

from atlas_core.consultas_atlas import normalizar_texto_atlas
from atlas_core.interpretador_consultas import _PALABRAS_EVENTO
from atlas_core.registro_eventos_operacionales import ESTADOS_GESTION_SOPORTADOS

_PATRON_GUIA = re.compile(r"\b(\d{6,})\b")
_PATRON_Y = re.compile(r"\bY\b")

# Sólo los 4 tipos MARCA_VIAJE iniciales (ver `TIPOS_MARCA_VIAJE_
# INICIALES` en `registro_eventos_operacionales.py`) son registrables
# aquí -- se reutiliza EXACTAMENTE el vocabulario ya usado para
# consultas (`_PALABRAS_EVENTO`, `interpretador_consultas.py`), nunca una
# copia nueva que pueda desincronizarse. El genérico "DEVOLUCION" (sin
# calificar total/parcial) y "ESPERA_AUTORIZACION_ESTADIA" (vocabulario
# de otro dominio, `atlas_core.mobile`) quedan fuera a propósito: para
# REGISTRAR un hecho Atlas necesita saber cuál de los 4 es -- nunca
# adivina "total" o "parcial" a partir de la palabra genérica sola.
_TIPOS_REGISTRABLES = frozenset({"TIENE_ESTADIA", "DEVOLUCION_TOTAL", "DEVOLUCION_PARCIAL", "DOBLE_VUELTA"})
_PALABRAS_TIPO_REGISTRABLE = tuple(
    (tipo, frases) for tipo, frases in _PALABRAS_EVENTO if tipo in _TIPOS_REGISTRABLES
)

# Vocabulario de ESTADO DE GESTIÓN -- no existía antes (el lado de sólo-
# lectura nunca necesitó distinguir gestión, sólo tipo de evento). Orden =
# especificidad (frase más larga primero dentro de cada tupla, resuelto
# en `_encontrar_keywords`).
_PALABRAS_GESTION = (
    ("PENDIENTE_RESPUESTA", (
        "SIGUE PENDIENTE DE RESPUESTA", "SIGUEN PENDIENTES DE RESPUESTA",
        "PENDIENTE DE RESPUESTA", "PENDIENTES DE RESPUESTA",
        "SIGUE PENDIENTE", "SIGUEN PENDIENTES",
    )),
    # "CONFIRMADA"/"CONFIRMADAS" -- caso real: "tienen estadía confirmada"
    # (Desktop) generaba REGISTRAR_INCIDENCIA sin ESTADO GESTIÓN porque
    # "confirmada" no era sinónimo de ningún estado. Semánticamente
    # equivalente a "aprobada" en este dominio (una gestión SE confirma
    # cuando se aprueba) -- mismo estado GESTION_APROBADA, nunca un estado
    # nuevo.
    ("APROBADA", (
        "FUE APROBADA", "FUERON APROBADAS", "APROBADA", "APROBADAS", "APROBARON", "APROBO",
        "FUE CONFIRMADA", "FUERON CONFIRMADAS", "CONFIRMADA", "CONFIRMADAS", "CONFIRMARON", "CONFIRMO",
    )),
    ("RECHAZADA", ("FUE RECHAZADA", "FUERON RECHAZADAS", "RECHAZADA", "RECHAZADAS", "RECHAZARON", "RECHAZO")),
    ("ENVIADA", ("FUE ENVIADA", "FUERON ENVIADAS", "ENVIADA", "ENVIADAS", "ENVIARON", "ENVIO")),
    ("REPORTADA", ("FUE REPORTADA", "FUERON REPORTADAS", "REPORTADA", "REPORTADAS", "REPORTARON", "REPORTO")),
)
assert {estado for estado, _ in _PALABRAS_GESTION} <= ESTADOS_GESTION_SOPORTADOS

_FRASES_SIN_INCIDENCIA = (
    "SIN INCIDENCIA", "SIN INCIDENCIAS",
    "NO TUVO INCIDENCIA", "NO TUVO INCIDENCIAS", "NO TUVIERON INCIDENCIA", "NO TUVIERON INCIDENCIAS",
    "NO HUBO INCIDENCIA", "NO HUBO INCIDENCIAS",
)


class _Keyword(NamedTuple):
    inicio: int
    fin: int
    categoria: str  # "tipo" | "gestion" | "sin_incidencia"
    valor: str


def _encontrar_keywords(texto: str) -> list[_Keyword]:
    """Todas las palabras clave de tipo/gestión/sin-incidencia en
    `texto`, sin solaparse -- en un empate de posición, la frase MÁS
    LARGA gana (nunca "PENDIENTE" suelto ganándole a "PENDIENTE DE
    RESPUESTA")."""
    candidatos: list[_Keyword] = []
    for tipo, frases in _PALABRAS_TIPO_REGISTRABLE:
        for frase in frases:
            for m in re.finditer(r"\b" + re.escape(frase) + r"\b", texto):
                candidatos.append(_Keyword(m.start(), m.end(), "tipo", tipo))
    for estado, frases in _PALABRAS_GESTION:
        for frase in frases:
            for m in re.finditer(r"\b" + re.escape(frase) + r"\b", texto):
                candidatos.append(_Keyword(m.start(), m.end(), "gestion", estado))
    for frase in _FRASES_SIN_INCIDENCIA:
        for m in re.finditer(r"\b" + re.escape(frase) + r"\b", texto):
            candidatos.append(_Keyword(m.start(), m.end(), "sin_incidencia", "SIN_INCIDENCIA"))
    candidatos.sort(key=lambda k: (k.inicio, -(k.fin - k.inicio)))
    seleccionados: list[_Keyword] = []
    fin_previo = -1
    for k in candidatos:
        if k.inicio < fin_previo:
            continue
        seleccionados.append(k)
        fin_previo = k.fin
    return seleccionados


def _dividir_clausulas(texto: str) -> list[str]:
    """Fronteras de oración (. ;) -- cada oración se procesa aparte."""
    return [p.strip() for p in re.split(r"[.;]+", texto) if p.strip()]


def _sub_clausulas(clausula: str) -> list[str]:
    """Dentro de una oración, ' Y ' puede ser (a) el separador de una
    LISTA de guías ("473001, 473004 Y 473010") -- nunca se corta ahí --
    o (b) el conector entre dos hechos INDEPENDIENTES ("473015 tuvo
    devolución parcial Y 473020 doble vuelta") -- ahí sí se corta, en
    dos sub-cláusulas independientes. La distinción: si entre la ÚLTIMA
    guía mencionada antes de esta "Y" y la "Y" misma ya apareció una
    palabra clave de tipo/gestión, esa "Y" separa dos hechos distintos
    (la primera guía ya "consumió" su propio hecho); si no, sigue siendo
    la misma lista de guías esperando su única palabra clave compartida."""
    guias = [(m.start(), m.end()) for m in _PATRON_GUIA.finditer(clausula)]
    keywords = _encontrar_keywords(clausula)
    puntos_split: list[int] = []
    for m in _PATRON_Y.finditer(clausula):
        y_pos = m.start()
        guias_antes = [g for g in guias if g[1] <= y_pos]
        if not guias_antes:
            continue  # nunca se corta antes de mencionar ninguna guía
        ultima_guia_fin = guias_antes[-1][1]
        hay_keyword_entre = any(
            k.inicio >= ultima_guia_fin and k.fin <= y_pos for k in keywords
        )
        if hay_keyword_entre:
            puntos_split.append(y_pos)
    if not puntos_split:
        return [clausula]
    trozos: list[str] = []
    inicio = 0
    for p in puntos_split:
        trozos.append(clausula[inicio:p])
        inicio = p + 1  # 'Y' es un solo carácter
    trozos.append(clausula[inicio:])
    return [t.strip() for t in trozos if t.strip()]


def _procesar_subclausula(sub: str, *, guias_heredadas: tuple[str, ...] = ()) -> list[dict]:
    """Bloque P0 CASO A -- caso real: "473001 tiene estadía Y fue
    aprobada." `_sub_clausulas` corta en el "Y" (hay una palabra clave de
    tipo entre la guía y el "Y"), dejando "fue aprobada" sin ningún
    número de guía propio. Antes, sin guía -> `[]` -- el hecho
    desaparecía en silencio (ni acción ni error visible), el evento
    quedaba persistido más tarde con `estado_gestion=None` (ver Bug 2) y
    la tarjeta nunca llegaba a un estado terminal -- reaparecía como
    "Lista para aplicar" indefinidamente.

    `guias_heredadas` (la(s) guía(s) de la sub-cláusula ANTERIOR dentro
    de la MISMA oración -- ver `interpretar_instruccion_incidencias`):
    si esta sub-cláusula no menciona ninguna guía propia, hereda esas --
    "fue aprobada" sin sujeto propio se refiere a la guía que la
    sub-cláusula anterior ya estableció, nunca a una guía distinta ni a
    todas las guías vistas en la instrucción completa. Si tampoco hay
    guías heredadas (primera sub-cláusula sin guía), sigue sin generar
    nada -- comportamiento idéntico al de siempre."""
    guias = [m.group(1) for m in _PATRON_GUIA.finditer(sub)]
    hereda_guia = False
    if not guias:
        if not guias_heredadas:
            return []
        guias = list(guias_heredadas)
        hereda_guia = True
    keywords = _encontrar_keywords(sub)
    tipo = next((k.valor for k in keywords if k.categoria == "tipo"), "")
    gestion = next((k.valor for k in keywords if k.categoria == "gestion"), "")
    sin_incidencia = any(k.categoria == "sin_incidencia" for k in keywords)
    if hereda_guia and not (tipo or gestion or sin_incidencia):
        # Fragmento heredado sin ninguna palabra clave reconocible
        # (p. ej. un resto de conjunción) -- no genera una acción vacía
        # repetida por cada guía heredada.
        return []
    acciones: list[dict] = []
    for guia in guias:
        if sin_incidencia:
            acciones.append({"accion": "REVISAR_SIN_INCIDENCIA", "guia": guia})
        elif gestion:
            accion: dict = {"accion": "ACTUALIZAR_GESTION", "guia": guia, "estado_gestion": gestion}
            if tipo:
                accion["tipo"] = tipo
            acciones.append(accion)
        elif tipo:
            acciones.append({"accion": "REGISTRAR_INCIDENCIA", "guia": guia, "tipo": tipo})
        else:
            # Nunca se descarta en silencio: `previsualizar_lote` rechaza
            # `accion=""` como ACCION_NO_PERMITIDA, así este fragmento
            # queda visible en el preview como error, nunca desaparece.
            acciones.append({"accion": "", "guia": guia})
    return acciones


def interpretar_instruccion_incidencias(texto: str) -> list[dict]:
    """Texto libre -> lista de dicts de acción (forma exacta que espera
    `previsualizar_lote`/`aplicar_lote`: ``{"accion", "guia", "tipo"?,
    "estado_gestion"?}``). Una guía puede aparecer más de una vez en la
    lista devuelta si el texto la menciona en más de una oración -- eso
    es responsabilidad del llamador (mismo criterio que cualquier lote:
    dos acciones sobre la misma guía se aplican en orden, la idempotencia
    de `registrar_evento` las hace convivir sin duplicar)."""
    normalizado = normalizar_texto_atlas(texto)
    acciones: list[dict] = []
    for clausula in _dividir_clausulas(normalizado):
        # La herencia de guía (ver `_procesar_subclausula`) nunca cruza
        # una frontera de oración (".", ";") -- una oración nueva
        # reestablece su propio sujeto; sólo se acota a las
        # sub-cláusulas de la MISMA oración, unidas por "Y".
        guias_previas: tuple[str, ...] = ()
        for sub in _sub_clausulas(clausula):
            guias_en_sub = tuple(m.group(1) for m in _PATRON_GUIA.finditer(sub))
            acciones.extend(_procesar_subclausula(sub, guias_heredadas=guias_previas))
            if guias_en_sub:
                guias_previas = guias_en_sub
    return acciones
