"""Bloque INCIDENCIAS OPERACIONALES V1.1 -- integración B1/"Pregúntale a
Atlas" sobre la V1 ya aprobada (``comandos_incidencias_operacionales``,
``registro_eventos_operacionales``). Orquesta, sin ampliar arquitectura:

    texto libre -> interpretación DETERMINÍSTICA (``interpretador_
    incidencias_operacionales``) -> preview OBLIGATORIO
    (``previsualizar_lote``, ya existente, nunca escribe) -> confirmación
    humana explícita -> ``aplicar_lote(confirmado=True)`` (ya existente).

Contrato de seguridad (nunca se relaja aquí): esta capa NUNCA escribe
directamente ni por su cuenta -- toda mutación pasa siempre por
``aplicar_lote``, y ``aplicar_lote`` sólo escribe si ``confirmado=True``.
Dos funciones separadas materializan las dos mitades del flujo para que
sea estructuralmente imposible confundir "proponer" con "aplicar":
``proponer_lote_incidencias`` jamás llama a ``aplicar_lote``;
``confirmar_lote_incidencias`` jamás interpreta texto.

Lado de consulta (sólo lectura): reutiliza ``consultar_incidencias_
operacionales`` y ``estado_revision_viajes`` (nunca una fuente ni un
cálculo paralelo) para las dos capacidades que el motor genérico de
"Pregúntale a Atlas" (``responder_consulta_atlas``) todavía no cubre
(estado de gestión, "no revisado por incidencias") -- cualquier otra
pregunta se delega TAL CUAL a ese motor ya existente, nunca se duplica."""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Mapping, Sequence

from atlas_core.comandos_incidencias_operacionales import (
    aplicar_lote,
    previsualizar_lote,
    resolver_guias,
)
from atlas_core.consultas_atlas import _valores_multivalor, cargar_viajes, normalizar_texto_atlas, resolver_periodo
from atlas_core.interpretador_consultas import (
    AMBIGUA,
    RESUELTA,
    _PALABRAS_EVENTO,
    _PALABRAS_PERIODO,
    construir_catalogos_consulta,
    resolver_entidad_por_palabras,
)
from atlas_core.interpretador_incidencias_operacionales import interpretar_instruccion_incidencias
from atlas_core.registro_eventos_operacionales import (
    consultar_incidencias_operacionales,
    estado_revision_viajes,
)

# --------------------------------------------------------------------------
# Lado de ESCRITURA -- proponer (nunca escribe) / confirmar (única puerta
# de escritura real).
# --------------------------------------------------------------------------


def _backfill_tipo_pendiente(*, raiz: str | Path, ruta_viajes: str | Path, acciones: Sequence[Mapping[str, object]]) -> list[dict]:
    """Cuando el texto no nombró el tipo de incidencia (caso real: "473020
    sigue pendiente de respuesta"), se intenta completar sólo si existe
    EXACTAMENTE una incidencia ACTIVA ya registrada para ese viaje --
    nunca se adivina entre varias. Si no hay ninguna, o hay más de una, se
    deja el `tipo` vacío: `previsualizar_lote` ya lo marca `TIPO_REQUERIDO`
    de forma visible, nunca se aplica a ciegas.

    Bloque P0 CASO A -- caso real: "473001 tiene estadía. 473001 fue
    aprobada." (dos oraciones, misma guía) llega aquí como DOS acciones
    en el MISMO lote -- REGISTRAR_INCIDENCIA(TIENE_ESTADIA) seguida de
    ACTUALIZAR_GESTION sin tipo. Antes, el backfill sólo consultaba el
    ledger YA ESCRITO (`consultar_incidencias_operacionales`), que
    todavía no conoce la primera acción del MISMO lote (se aplican en
    orden, una a la vez, más adelante) -- la segunda quedaba
    `TIPO_REQUERIDO` aunque el tipo fuera obvio, y `registrar_evento`
    nunca llegaba a escribir el estado de gestión: el evento persistía
    con `estado_gestion=None`, un estado no-terminal que vuelve a
    calificar como "aplicable" en cualquier consulta posterior. Ahora se
    mira PRIMERO si el MISMO lote ya trae un `REGISTRAR_INCIDENCIA` para
    la misma guía con un tipo -- sólo si es único (nunca adivina entre
    dos tipos distintos del mismo lote) se usa esa evidencia, sin
    esperar a que el ledger la refleje. Si el lote no la trae, se cae al
    mismo camino de siempre (ledger persistido)."""
    salida: list[dict] = []
    guias = [str(a.get("guia", "")).strip() for a in acciones]
    resueltas = resolver_guias(ruta_viajes=ruta_viajes, guias=guias)
    tipos_por_guia_en_lote: dict[str, set[str]] = {}
    for a in acciones:
        if str(a.get("accion", "")) == "REGISTRAR_INCIDENCIA":
            tipo_lote = str(a.get("tipo", "")).strip()
            if tipo_lote:
                tipos_por_guia_en_lote.setdefault(str(a.get("guia", "")).strip(), set()).add(tipo_lote)
    for accion in acciones:
        accion = dict(accion)
        necesita_tipo = accion.get("accion") == "ACTUALIZAR_GESTION" and not str(accion.get("tipo", "")).strip()
        if necesita_tipo:
            tipos_lote = tipos_por_guia_en_lote.get(str(accion.get("guia", "")).strip(), set())
            if len(tipos_lote) == 1:
                accion["tipo"] = next(iter(tipos_lote))
                accion["tipo_inferido_de_incidencia_existente"] = True
                necesita_tipo = False
        if necesita_tipo:
            info = resueltas.get(str(accion.get("guia", "")).strip())
            if info and info.get("estado") == "RESUELTA":
                numero_transporte = str(info["viaje"].get("numero_transporte", ""))
                activas = consultar_incidencias_operacionales(
                    raiz=raiz, numero_transporte=numero_transporte
                )["incidencias"]
                if len(activas) == 1:
                    accion["tipo"] = str(activas[0].get("tipo_evento", ""))
                    accion["tipo_inferido_de_incidencia_existente"] = True
        salida.append(accion)
    return salida


def proponer_lote_incidencias(*, texto: str, raiz: str | Path, ruta_viajes: str | Path) -> dict:
    """Interpreta la instrucción y arma el preview -- NUNCA escribe. Si el
    texto no contiene ninguna instrucción reconocible, lo dice
    explícitamente en vez de devolver un preview vacío engañoso."""
    acciones = interpretar_instruccion_incidencias(texto)
    if not acciones:
        return {
            "interpretado": False,
            "acciones": [],
            "preview": None,
            "mensaje": "No reconocí ninguna instrucción de incidencias en ese texto -- no se propuso ningún cambio.",
        }
    acciones = _backfill_tipo_pendiente(raiz=raiz, ruta_viajes=ruta_viajes, acciones=acciones)
    preview = previsualizar_lote(ruta_viajes=ruta_viajes, acciones=acciones, raiz=raiz)
    # Distingue, aparte del rechazo de `previsualizar_lote`, el fragmento
    # que esta capa ni siquiera pudo interpretar (`accion==""`) del que sí
    # se interpretó pero el allowlist/resolución de guía rechaza -- ambos
    # ya llegan visibles en `preview.acciones`, esto sólo los cuenta para
    # un mensaje humano más claro.
    no_reconocidas = sum(1 for a in acciones if not a.get("accion"))
    return {
        "interpretado": True,
        "acciones": acciones,
        "preview": preview,
        "fragmentos_no_reconocidos": no_reconocidas,
        "mensaje": (
            f"{preview['resumen']['aplicables']} aplicable(s), {preview['resumen']['ya_registradas']} ya registrada(s) y {preview['resumen']['no_resueltas']} no resuelta(s) -- revise el detalle antes de confirmar."
            if preview["aplicable"]
            else "No hay acciones aplicables; las no resueltas quedan sólo como información."
        ),
    }


def confirmar_lote_incidencias(
    *, raiz: str | Path, ruta_viajes: str | Path, acciones: Sequence[Mapping[str, object]],
    actor: str, confirmado: bool,
) -> dict:
    """Única puerta de escritura real de este módulo -- delega
    íntegramente en `aplicar_lote` (idempotente, ya aprobado). Nunca
    interpreta texto: recibe exactamente las `acciones` que el humano ya
    vio en el preview devuelto por `proponer_lote_incidencias`."""
    resultado = aplicar_lote(
        raiz=raiz, ruta_viajes=ruta_viajes, acciones=acciones, actor=actor, confirmado=confirmado,
    )
    if not resultado.get("aplicado"):
        # confirmado=False (o preview no aplicable): nunca escribió nada.
        return resultado
    aplicados = 0
    ya_registrados = 0
    errores: list[dict] = []
    for item in resultado["resultados"]:
        if not item.get("ok"):
            errores.append({"guia": item["guia"], "estado": item["estado"]})
            continue
        detalle = item.get("resultado") or {}
        if "idempotente" in detalle:
            # marcar_viaje_revisado_sin_incidencia
            ya_estaba = bool(detalle.get("idempotente"))
        else:
            # registrar_evento
            ya_estaba = not (detalle.get("creado") or detalle.get("cambio") or detalle.get("reactivado"))
        if ya_estaba:
            ya_registrados += 1
        else:
            aplicados += 1
    return {
        **resultado,
        "resumen": {
            "aplicados": aplicados,
            "ya_registrados": ya_registrados,
            "no_aplicados": len(errores),
            "no_resueltas": len(errores),
            "errores": errores,
        },
    }


# --------------------------------------------------------------------------
# Lado de CONSULTA -- sólo lectura. Cubre las dos capacidades que
# `responder_consulta_atlas` todavía no tiene (estado de gestión, "no
# revisado"); todo lo demás se delega tal cual a ese motor ya existente.
# --------------------------------------------------------------------------

_MESES = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6,
    "JULIO": 7, "AGOSTO": 8, "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCTUBRE": 10,
    "NOVIEMBRE": 11, "DICIEMBRE": 12,
}
_PATRON_MES_NOMBRADO = re.compile(
    r"\bDE\s+(ENERO|FEBRERO|MARZO|ABRIL|MAYO|JUNIO|JULIO|AGOSTO|SEPTIEMBRE|SETIEMBRE|OCTUBRE|NOVIEMBRE|DICIEMBRE)\b"
)


def _rango_mes_nombrado(nombre_mes: str, *, hoy: date) -> tuple[date, date] | None:
    """El mes nombrado más reciente que ya pasó (o el actual) -- nunca un
    mes futuro: "de agosto" preguntado en septiembre es este agosto; en
    enero del año siguiente, sigue siendo el agosto anterior."""
    mes = _MESES.get(nombre_mes)
    if mes is None:
        return None
    anio = hoy.year if mes <= hoy.month else hoy.year - 1
    inicio = date(anio, mes, 1)
    fin = date(anio + 1, 1, 1) - timedelta(days=1) if mes == 12 else date(anio, mes + 1, 1) - timedelta(days=1)
    return inicio, fin


def _reescribir_mes_nombrado(texto: str, *, hoy: date | None = None) -> str:
    """"...de agosto" -> se AGREGA (nunca se borra el texto original) un
    rango explícito "entre 01/08/2026 y 31/08/2026" -- el mismo patrón
    ENTRE/Y que `interpretador_consultas._filtros_periodo` ya reconoce por
    posición, sin tocar ese módulo. Deliberadamente no reemplaza "agosto"
    en el texto: otros nombres propios de la pregunta deben seguir
    intactos para el resto del intérprete."""
    coincidencia = _PATRON_MES_NOMBRADO.search(normalizar_texto_atlas(texto))
    if not coincidencia:
        return texto
    rango = _rango_mes_nombrado(coincidencia.group(1), hoy=hoy or date.today())
    if rango is None:
        return texto
    inicio, fin = rango
    return f"{texto} entre {inicio.day:02d}/{inicio.month:02d}/{inicio.year} y {fin.day:02d}/{fin.month:02d}/{fin.year}"


def _resolver_chofer_mencionado(texto: str, choferes: Sequence[str]) -> tuple[str | None, tuple[str, ...]]:
    """(chofer resuelto o None, candidatos si es ambigua) -- nunca
    adivina entre dos coincidencias igual de fuertes."""
    resolucion = resolver_entidad_por_palabras(texto, choferes)
    if resolucion.estado == RESUELTA:
        return resolucion.valor, ()
    if resolucion.estado == AMBIGUA:
        return None, resolucion.candidatos
    return None, ()


_PATRON_NO_REVISADO = re.compile(
    r"\bNO\s+(HE\s+|HA\s+|HAN\s+)?REVISAD[OA]S?\b.*\bINCIDENCIAS?\b|\bSIN\s+REVISAR\s+POR\s+INCIDENCIAS?\b"
)


def _consulta_no_revisados(texto: str, *, raiz: str | Path, ruta_viajes: str | Path) -> dict:
    viajes = cargar_viajes(ruta_viajes)
    catalogos = construir_catalogos_consulta(viajes)
    chofer, candidatos_ambiguos = _resolver_chofer_mencionado(texto, catalogos.choferes)
    if candidatos_ambiguos:
        return {
            "estado": "AMBIGUA",
            "texto_respuesta": f"Encontré más de un chofer que coincide con tu pregunta: {', '.join(candidatos_ambiguos)}. ¿Cuál quieres consultar?",
            "opciones_aclaracion": list(candidatos_ambiguos),
            "viajes": [],
        }
    viajes_filtrados = (
        [v for v in viajes if chofer in _valores_multivalor(v, "choferes")] if chofer else viajes
    )
    clasificados = estado_revision_viajes(raiz=raiz, viajes=viajes_filtrados)
    transportes_no_revisados = {
        c["numero_transporte"] for c in clasificados if c["estado_revision_incidencias"] == "NO_REVISADO"
    }
    resultado = [v for v in viajes_filtrados if v.get("numero_transporte", "") in transportes_no_revisados]
    sujeto = f" de {chofer}" if chofer else ""
    return {
        "estado": "OK" if resultado else "SIN_RESULTADOS",
        "texto_respuesta": f"{len(resultado)} viaje(s){sujeto} todavía sin revisar por incidencias.",
        "viajes": resultado,
    }


_PATRON_APROBADA = re.compile(r"\bAPROBAD[OA]S?\b|\bAPROBARON\b")
_PATRON_RECHAZADA = re.compile(r"\bRECHAZAD[OA]S?\b|\bRECHAZARON\b")
_PATRON_PENDIENTE_RESPUESTA = re.compile(r"\bPENDIENTE(S)?\s+DE\s+RESPUESTA\b")
_PATRON_PENDIENTE_GENERICO = re.compile(r"\bPENDIENTE(S)?\b")
_PATRON_INCIDENCIA_KW = re.compile(r"\bINCIDENCIAS?\b")


def _detectar_intencion_gestion(normalizado: str) -> tuple[str | None, bool]:
    """(estado_gestion exacto, o None con `generico=True` para "pendiente"
    sin calificar -- ahí se usa `pendientes_gestion` completo, que ya
    agrupa REPORTADA/ENVIADA/PENDIENTE_RESPUESTA, en vez de adivinar cuál
    de los tres quiso decir Javier)."""
    if _PATRON_APROBADA.search(normalizado):
        return "APROBADA", False
    if _PATRON_RECHAZADA.search(normalizado):
        return "RECHAZADA", False
    if _PATRON_PENDIENTE_RESPUESTA.search(normalizado):
        return "PENDIENTE_RESPUESTA", False
    if _PATRON_PENDIENTE_GENERICO.search(normalizado):
        return None, True
    return None, False


def _detectar_tipo_consulta(normalizado: str) -> tuple[str | None, bool]:
    """(tipo_evento exacto para filtrar, es_generico) -- "devoluciones"
    sin calificar (ver `_PALABRAS_EVENTO`, reutilizado tal cual) filtra
    por PREFIJO (DEVOLUCION_TOTAL + DEVOLUCION_PARCIAL), nunca inventa
    cuál de las dos."""
    for tipo, frases in _PALABRAS_EVENTO:
        if tipo == "ESPERA_AUTORIZACION_ESTADIA":
            continue
        if any(re.search(r"\b" + re.escape(frase) + r"\b", normalizado) for frase in frases):
            return tipo, tipo == "DEVOLUCION"
    return None, False


def _rango_periodo_mencionado(normalizado: str, texto_original: str, *, hoy: date | None = None) -> tuple[str, str] | None:
    """(fecha_desde, fecha_hasta) ISO si el texto menciona un período
    reconocible -- reutiliza EXACTAMENTE el vocabulario/resolución ya
    existentes (`_PALABRAS_PERIODO`/`resolver_periodo`), más el mes
    nombrado ("de agosto") que este módulo ya resuelve para el motor
    genérico. Nunca una tercera forma de calcular fechas."""
    hoy = hoy or date.today()
    mes = _PATRON_MES_NOMBRADO.search(normalizado)
    if mes:
        rango = _rango_mes_nombrado(mes.group(1), hoy=hoy)
        if rango is not None:
            return rango[0].isoformat(), rango[1].isoformat()
    for nombre_periodo, frases in _PALABRAS_PERIODO:
        if any(frase in normalizado for frase in frases):
            inicio, fin = resolver_periodo(nombre_periodo, hoy=hoy)
            return inicio.isoformat(), fin.isoformat()
    return None


def _consulta_por_gestion(texto: str, *, raiz: str | Path) -> dict:
    normalizado = normalizar_texto_atlas(texto)
    estado_exacto, generico_pendiente = _detectar_intencion_gestion(normalizado)
    tipo_evento, tipo_generico = _detectar_tipo_consulta(normalizado)
    filtros: dict[str, str] = {}
    if tipo_evento and not tipo_generico:
        filtros["tipo"] = tipo_evento
    if estado_exacto:
        filtros["estado_gestion"] = estado_exacto
    rango = _rango_periodo_mencionado(normalizado, texto)
    if rango is not None:
        filtros["fecha_desde"], filtros["fecha_hasta"] = rango
    datos = consultar_incidencias_operacionales(raiz=raiz, **filtros)
    incidencias = list(datos["pendientes_gestion"] if generico_pendiente else datos["incidencias"])
    if tipo_generico:
        incidencias = [i for i in incidencias if str(i.get("tipo_evento", "")).startswith(tipo_evento)]
    etiqueta_estado = {
        "APROBADA": "aprobada(s)", "RECHAZADA": "rechazada(s)", "PENDIENTE_RESPUESTA": "pendiente(s) de respuesta",
    }.get(estado_exacto or "", "pendiente(s) de gestión" if generico_pendiente else "")
    return {
        "estado": "OK" if incidencias else "SIN_RESULTADOS",
        "texto_respuesta": f"{len(incidencias)} incidencia(s) {etiqueta_estado}.".replace("  ", " "),
        "incidencias": incidencias,
    }


def responder_consulta_incidencias_conversacional(
    texto: str, *, raiz: str | Path, ruta_viajes: str | Path,
) -> dict:
    """Punto de entrada único de consulta conversacional sobre incidencias
    operacionales. Cubre, con las funciones YA existentes (nunca una
    fuente ni un cálculo paralelo):

    - "...que todavía no he revisado por incidencias" -> `estado_
      revision_viajes` (capacidad nueva, no existía en ningún lado).
    - estado de gestión (aprobadas/rechazadas/pendientes) -> `consultar_
      incidencias_operacionales` (capacidad nueva).
    - cualquier otra pregunta (incluida "...de <mes>", reescrita a un
      rango explícito) -> se delega TAL CUAL a `responder_consulta_atlas`,
      el motor genérico de "Pregúntale a Atlas" ya existente."""
    normalizado = normalizar_texto_atlas(texto)
    if _PATRON_NO_REVISADO.search(normalizado):
        return {"origen": "INCIDENCIAS_NO_REVISADAS", **_consulta_no_revisados(texto, raiz=raiz, ruta_viajes=ruta_viajes)}

    estado_exacto, generico_pendiente = _detectar_intencion_gestion(normalizado)
    # Un estado EXACTO (aprobada/rechazada/pendiente de respuesta) ya es
    # inequívocamente una pregunta de gestión, mencione o no la palabra
    # "incidencia(s)" ("las estadías... pendientes" nunca dice
    # "incidencia"). El genérico "pendiente" solo, en cambio, es
    # demasiado ambiguo ("pendiente técnico" es otra cosa que el motor
    # genérico ya entiende) -- sólo cuenta si el resto de la frase
    # menciona incidencias o un tipo de evento conocido (estadía,
    # devolución, doble vuelta).
    menciona_incidencia_o_tipo = bool(_PATRON_INCIDENCIA_KW.search(normalizado)) or _detectar_tipo_consulta(normalizado)[0] is not None
    if estado_exacto or (generico_pendiente and menciona_incidencia_o_tipo):
        return {"origen": "INCIDENCIAS_GESTION", **_consulta_por_gestion(texto, raiz=raiz)}

    from atlas_core.responder_consulta_atlas import responder_consulta_atlas

    texto_final = _reescribir_mes_nombrado(texto)
    respuesta = responder_consulta_atlas(texto_final, ruta_viajes=ruta_viajes, raiz_atlas=raiz)
    return {
        "origen": "DELEGADO_RESPONDER_CONSULTA_ATLAS",
        "estado": respuesta.estado,
        "texto_respuesta": respuesta.texto_respuesta,
        "opciones_aclaracion": list(respuesta.opciones_aclaracion),
        "resultado": respuesta.resultado,
    }
