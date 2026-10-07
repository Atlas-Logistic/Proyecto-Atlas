"""B1 OPERADOR -- conecta órdenes en lenguaje natural con la capa canónica
de acciones operacionales (`atlas_core.acciones_operacionales`).

    texto -> intención (determinista o modelo) -> validación contra
    `catalogo_acciones()` -> resolución de entidades (sin adivinar) ->
    `previsualizar(origen="B1")` -> preview pendiente de ESTA conversación
    -> "sí" -> `ejecutar(token pendiente, confirmado_por=<humano>)`.

Reglas:
- LECTURA se responde directo, sin confirmación y sin tocar el pendiente.
- OPERACIONAL_REVERSIBLE: preview + una confirmación humana.
- SENSIBLE: se informa que requiere autorización sensible; nunca queda
  pendiente, así que ningún "sí" puede ejecutarla por esta vía.
- DESTRUCTIVA: la capa la rechaza.
- Una confirmación sólo ejecuta el token pendiente de su conversación; sin
  pendiente no se ejecuta nada; expirado u obsoleto -> se muestra el preview
  nuevo, nunca se ejecuta en silencio.
- Una instrucción operacional nueva reemplaza al pendiente anterior.
- Una mención de chofer ambigua o desconocida -> se pregunta, no se adivina.
- Lo que proponga un modelo es DATO: sólo {accion, parametros, menciones},
  acción del catálogo, parámetros del esquema, sin rutas/comandos/código.
- Una investigación deja en ESTA conversación su resultado estructurado (no
  su texto); "corrige la obra/el destino con lo que acabas de identificar"
  sólo lo reutiliza si es de la misma guía, exitoso, no ambiguo y reciente,
  y lo convierte en un preview del mecanismo controlado existente:
  DOCUMENTO_ASIGNAR_OBRA (obra existente) o DECISION_APLICAR/
  REGISTRAR_DIRECCION (revisión de destino pendiente).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Protocol

from atlas_core.acciones_operacionales import (
    ACCIONES, DESTRUCTIVA, LECTURA, ORIGEN_B1, SENSIBLE, CapaAccionesOperacionales, _esquema,
)
from atlas_core.almacenamiento_portable import SesionOcupadaError, bloqueo_sesion, escribir_json_atomico
from atlas_core.identidad_canonica import clave_identidad, misma_identidad, nombre_visible

NOMBRE_ESTADO = "b1_operador_conversaciones.json"
ACTOR_B1 = "B1"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

# --------------------------------------------------------------- texto


def _plano(texto: str) -> str:
    """Mayúsculas sin tildes, MISMO largo que `texto.upper()` (carácter a
    carácter), para capturar valores del original con los mismos índices."""
    salida = []
    for caracter in str(texto or "").upper():
        base = unicodedata.normalize("NFKD", caracter)
        salida.append(base[0] if base and not unicodedata.combining(base[0]) else caracter)
    return "".join(salida)


def _limpio(texto: str) -> tuple[str, str]:
    original = " ".join(str(texto or "").split()).strip(" .!?¿¡").upper()
    return original, _plano(original)


_CONFIRMAR_FUERTES = {"SI", "CONFIRMA", "CONFIRMO", "CONFIRMADO", "APLICA", "APLICALO", "APLICAR", "DALE",
                      "OK", "OKAY", "HAZLO", "ADELANTE", "PROCEDE", "EJECUTA", "EJECUTALO", "ACUERDO"}
_CONFIRMAR_RELLENO = {"DE", "YA", "POR", "FAVOR", "PORFA", "NOMAS"}
_CANCELAR = {"NO", "CANCELA", "CANCELAR", "CANCELALO", "ANULA", "ANULALO", "OLVIDALO", "DEJALO", "MEJOR", "NADA"}


def _palabras(plano: str) -> list[str]:
    return re.findall(r"[A-Z0-9]+", plano)


def es_confirmacion(texto: str) -> bool:
    palabras = _palabras(_limpio(texto)[1])
    return (bool(palabras) and len(palabras) <= 5 and any(p in _CONFIRMAR_FUERTES for p in palabras)
            and all(p in _CONFIRMAR_FUERTES | _CONFIRMAR_RELLENO for p in palabras)
            and palabras[0] != "NO")


def es_cancelacion(texto: str) -> bool:
    palabras = _palabras(_limpio(texto)[1])
    return bool(palabras) and len(palabras) <= 4 and palabras[0] in _CANCELAR and all(p in _CANCELAR for p in palabras)


# --------------------------------------------------------------- intención


@dataclass
class Intencion:
    accion: str
    parametros: dict[str, object] = field(default_factory=dict)
    menciones: dict[str, str] = field(default_factory=dict)
    tipo_vehiculo_declarado: str = ""
    fuente: str = "DETERMINISTA"


_ESTADO_A = re.compile(
    r"^(?:PON|PONER|PONGA|DEJA|DEJAR|DEJE|MARCA|MARCAR|MARQUE)\s+(?:COMO\s+)?(IN)?ACTIV[OA]\s+"
    r"(?:A\s+|AL\s+)?(?:CHOFER\s+|CONDUCTOR\s+)?(?P<chofer>.+)$")
_ESTADO_B = re.compile(
    r"^(?:PON|PONER|DEJA|DEJAR|MARCA|MARCAR)\s+(?:A\s+|AL\s+)?(?:CHOFER\s+|CONDUCTOR\s+)?(?P<chofer>.+?)\s+"
    r"(?:COMO\s+)?(IN)?ACTIV[OA]$")
_ESTADO_C = re.compile(
    r"^(DESACTIVA|INACTIVA|ACTIVA|REACTIVA)(?:R)?\s+(?:A\s+|AL\s+)?(?:CHOFER\s+|CONDUCTOR\s+)?(?P<chofer>.+)$")
_TRANSPORTE = re.compile(r"\b(?:REVALIDA|REPROCESA|RELEE|REEXTRAE|VUELVE A LEER)\w*\s+(?:EL\s+)?(?:TRANSPORTE|VIAJE)\s+"
                         r"(?:N[°O]?\s*)?(?P<n>\d{4,15})\b")
_DESTRUCTIVA = re.compile(r"^(?:BORRA|BORRAR|ELIMINA|ELIMINAR|SUPRIME|SUPRIMIR|DESTRUYE)\w*\b(?P<resto>.*)$")
_CAMPOS_DOC = {
    "OBRA": "obra_destino", "CLIENTE": "cliente", "RUT DEL CLIENTE": "rut_cliente", "RUT CLIENTE": "rut_cliente",
    "TRACTO": "patente_tracto",
    "PATENTE": "patente_tracto", "PATENTE DEL TRACTO": "patente_tracto", "RAMPLA": "patente_rampla",
    "PATENTE DE LA RAMPLA": "patente_rampla", "CODIGO CLIENTE": "codigo_cliente",
    "CODIGO DE CLIENTE": "codigo_cliente", "COD DESTINATARIO": "cod_destinatario",
}
_DOCUMENTO = re.compile(
    r"^(?:CORRIGE|CORREGIR|CAMBIA|CAMBIAR)\s+(?:EL|LA)\s+(?P<campo>"
    + "|".join(sorted(_CAMPOS_DOC, key=len, reverse=True))
    + r")\s+DE\s+LA\s+GUIA\s+(?:N[°O]?\s*)?(?P<guia>\d{3,12})\s+(?:A|POR|AL VALOR)\s+(?P<valor>.+)$")
# Lecturas de CATÁLOGO acotadas: las preguntas sobre la operación ("qué
# choferes trabajaron", "estadías pendientes", "qué obras tuvieron más
# viajes") pertenecen a Consultas/Incidencias, nunca a B1 operador.
# Catálogo de CHOFERES (no actividad): registrados / catálogo / activos /
# inactivos / con-sin viajes. "Trabajaron", "hicieron viajes"... sin ninguna
# de estas marcas sigue siendo una consulta sobre viajes (fuera de B1).
_PALABRA_CHOFER = re.compile(r"\b(?:CHOFER(?:ES)?|CONDUCTOR(?:ES)?)\b")
_MARCA_CATALOGO_CHOFERES = re.compile(r"\bREGISTRAD[OA]S?\b|\bCATALOGO\b|\b(?:IN)?ACTIV[OA]S?\b")
_SIN_VIAJES = re.compile(r"\bSIN\s+VIAJES?\b|\bNO\s+(?:TIENEN?|HAN\s+TENIDO|TUVIERON|REGISTRAN)\s+VIAJES?\b")
_CON_VIAJES = re.compile(r"\bCON\s+VIAJES?\b|\b(?:TIENEN?|HAN\s+TENIDO|TUVIERON|REGISTRAN)\s+VIAJES?\b")
_OTRA_ENTIDAD = re.compile(r"\b(?:OBRAS?|CLIENTES?|DESTINOS?|VEHICULOS?|PATENTES?|CAMION(?:ES)?|TRACTOS?|RAMPLAS?|"
                           r"GUIAS?|DECISIONES|REVISIONES|TARJETAS|PLANTAS?)\b")
# Estado de UN chofer concreto ("¿Luis Lara está activo?", "¿está inactivo
# Luis Lara?", "¿cuál es el estado de Luis Lara?"): lectura, nunca una orden.
_ESTADO_ADJ = r"(?:IN)?ACTIV[OA]|(?:DES)?HABILITAD[OA]"
_ESTADO_INDIVIDUAL = (
    re.compile(rf"^(?:EL\s+|LA\s+)?(?:CHOFER\s+|CONDUCTOR(?:A)?\s+)?(?P<chofer>.+?)\s+(?:ESTA|SIGUE|QUEDO)\s+(?:{_ESTADO_ADJ})$"),
    re.compile(rf"^(?:ESTA|SIGUE)\s+(?:{_ESTADO_ADJ})\s+(?:EL\s+|LA\s+)?(?:CHOFER\s+|CONDUCTOR(?:A)?\s+)?(?P<chofer>.+)$"),
    re.compile(r"^CUAL\s+ES\s+EL\s+ESTADO\s+(?:DE\s+|DEL\s+)(?:LA\s+)?(?:CHOFER\s+|CONDUCTOR(?:A)?\s+)?(?P<chofer>.+)$"),
)
# Antigüedad desde la última actividad: "más de N días sin cargar/trabajar/
# viajes" (y "... que no cargan"). N siempre explícito, nunca un valor fijo.
_INACTIVIDAD_CHOFERES = re.compile(
    r"\bMAS\s+DE\s+(?P<n>\d{1,4})\s+DIAS?\s+(?:"
    r"SIN\s+(?:HACER\s+|TENER\s+|REALIZAR\s+|REGISTRAR\s+)?(?:CARGAR|CARGAS?|TRABAJAR|VIAJES?|VIAJAR|ACTIVIDAD|SALIR|MANEJAR)"
    r"|QUE\s+NO\s+(?:CARGAN?|TRABAJAN?|VIAJAN?|SALEN?|MANEJAN?))\b")
# Una "mención" que en realidad es una pregunta general sobre el catálogo.
_MENCION_GENERAL = re.compile(r"\b(?:CHOFERES|CONDUCTORES|CUANTOS|CUANTAS|QUIENES|QUIEN|CUALES|QUE|TODOS|"
                              r"ALGUNO|ALGUN|NINGUNO|NINGUN|HAY)\b")
_VERBO_LECTURA = re.compile(r"^(?:QUE|CUALES|CUANTOS|LISTA|LISTAR|MUESTRA|MUESTRAME|DAME|VER|HAY|QUIENES)\b")
_LECTURA_DECISIONES = re.compile(r"\b(?:DECISIONES|REVISIONES|TARJETAS)\b(?:.*\bGUIA\s+(?:N[°O]?\s*)?(?P<guia>\d{3,12}))?")
_NO_ES_DECISION = re.compile(r"\b(?:ESTADIAS?|INCIDENCIAS?|DEVOLUCION(?:ES)?|VUELTAS?)\b")
# DESTINO de una guía (mismo camino que Revisión: DESTINO_NO_RESUELTO /
# REGISTRAR_DIRECCION). Frases: "el destino de la guía N es X", "la guía N va
# a X", "corrige/cambia/asigna el destino de la guía N a X". Comuna opcional
# sólo si viene explícita ("..., comuna X").
_GUIA = r"GUIA\s+(?:N[°O]?\s*)?(?P<guia>\d{3,12})"
_DESTINO_GUIA = [
    re.compile(r"^(?:EL\s+|LA\s+)?(?:DESTINO|DIRECCION(?:\s+DE\s+ENTREGA)?)\s+(?:DE\s+LA\s+|DE\s+)?" + _GUIA
               + r"\s*(?:ES|SERA|DEBE\s+SER|DEBERIA\s+SER|CORRESPONDE\s+A|:)\s*(?P<dir>.+)$"),
    re.compile(r"^(?:LA\s+)?" + _GUIA + r"\s+(?:VA|IBA|FUE|SE\s+ENTREGA|SE\s+ENTREGO|SE\s+DESPACHA|SE\s+DESPACHO)\s+"
               r"(?:A|EN|HACIA)\s+(?P<dir>.+)$"),
    re.compile(r"^(?:CORRIGE|CORREGIR|CAMBIA|CAMBIAR|ASIGNA|ASIGNAR|REGISTRA|REGISTRAR|PON|PONER)\s+(?:EL\s+|LA\s+)?"
               r"(?:DESTINO|DIRECCION(?:\s+DE\s+ENTREGA)?)\s+(?:DE\s+LA\s+|DE\s+|A\s+LA\s+)?" + _GUIA
               + r"\s*(?:A|POR|COMO|EN|:)\s*(?P<dir>.+)$"),
]
# MISMO VIAJE FÍSICO: afirmación humana explícita de que 2+ guías son un
# solo viaje ("las guías A y B pertenecen al mismo viaje", "son del mismo
# viaje", "junta las guías A y B en un solo viaje"). Nunca una pregunta ni
# una negación.
_MISMO_VIAJE = re.compile(
    r"\bGUIAS\b.*\b(?:PERTENECEN|SON|CORRESPONDEN|VAN|IBAN|FUERON|ESTAN|JUNTA|JUNTAR|AGRUPA|AGRUPAR|UNE|UNIR)\b"
    r".*\b(?:(?:AL|DEL|EL|EN\s+EL|A\s+UN|EN\s+UN|UN)\s+(?:MISMO|SOLO|UNICO)\s+(?:VIAJE|REPARTO))\b"
    r"|\b(?:JUNTA|JUNTAR|AGRUPA|AGRUPAR|UNE|UNIR)\s+LAS\s+GUIAS\b.*\b(?:VIAJE|REPARTO)\b")
# OBRA de una guía: "la obra de la guía N es X", "la guía N pertenece a la
# obra X", "cambia/corrige/asigna la obra de la guía N a X". Va antes que
# DOCUMENTO_CORREGIR_CAMPO y que la asociación chofer↔vehículo (que leía
# "OBRA DE LA GUÍA N" como nombre de chofer).
_OBRA_GUIA = [
    re.compile(r"^(?:LA\s+)?OBRA\s+(?:DE\s+LA\s+|DE\s+)?" + _GUIA
               + r"\s*(?:ES|SERA|DEBE\s+SER|DEBERIA\s+SER|CORRESPONDE\s+A|:)\s*(?:LA\s+OBRA\s+)?(?P<obra>.+)$"),
    re.compile(r"^(?:LA\s+)?" + _GUIA + r"\s+(?:PERTENECE\s+A|CORRESPONDE\s+A|ES\s+DE)\s+LA\s+OBRA\s*:?\s*(?P<obra>.+)$"),
    re.compile(r"^(?:CORRIGE|CORREGIR|CAMBIA|CAMBIAR|ASIGNA|ASIGNAR)\s+(?:LA\s+)?OBRA\s+(?:DE\s+LA\s+|DE\s+|A\s+LA\s+)?"
               + _GUIA + r"\s*(?:A|POR|COMO|:)\s*(?:LA\s+OBRA\s+)?(?P<obra>.+)$"),
]
# COORDENADA de un destino existente, dada por un humano: "la coordenada del
# destino X es LAT, LON", "el destino X está en LAT, LON", "confirma la
# coordenada LAT, LON para el destino X", "confirma la coordenada del destino
# X: LAT, LON". Decimales con punto; el signo lo valida la capa (Chile).
_COORD = r"(?P<lat>-?\s?\d{1,2}\.\d+)\s*[,;/]?\s*(?P<lon>-?\s?\d{1,3}\.\d+)"
_VERBO_COORD = r"(?:CONFIRMA|CONFIRMAR|ASIGNA|ASIGNAR|REGISTRA|REGISTRAR|FIJA|FIJAR|PON|PONER)"
_COORDENADA_DESTINO = [
    re.compile(r"^(?:LA\s+|LAS\s+)?(?:COORDENADAS?|UBICACION)\s+(?:DEL\s+DESTINO\s+|DE\s+)(?P<destino>.+?)\s*"
               r"(?:\s(?:ES|SON)|:)\s*(?:LA\s+)?" + _COORD + r"$"),
    re.compile(r"^(?:EL\s+)?DESTINO\s+(?P<destino>.+?)\s+(?:ESTA|QUEDA|SE\s+UBICA)\s+EN\s+"
               r"(?:LAS?\s+COORDENADAS?\s+)?" + _COORD + r"$"),
    re.compile(r"^" + _VERBO_COORD + r"\s+(?:LA\s+|LAS\s+)?COORDENADAS?\s+" + _COORD
               + r"\s+(?:PARA|AL|DEL|EN)\s+(?:EL\s+)?DESTINO\s+(?P<destino>.+)$"),
    re.compile(r"^" + _VERBO_COORD + r"\s+(?:LA\s+|LAS\s+)?COORDENADAS?\s+(?:DEL\s+DESTINO\s+|DE\s+)"
               r"(?P<destino>.+?)(?:\s+(?:EN|A|COMO)|\s*:)\s*" + _COORD + r"$"),
]
_NEGACION_MISMO_VIAJE = re.compile(r"\bNO\s+(?:PERTENECEN|SON|CORRESPONDEN|VAN|IBAN|FUERON|ESTAN|ES)\b")
_NUMERO_GUIA = re.compile(r"\b\d{5,9}\b")
_COMUNA_EXPLICITA = re.compile(r"^(?P<dir>.+?)\s*,?\s+COMUNA\s+(?:DE\s+)?(?P<comuna>[A-Z ]+)$")
_LECTURA_OBRAS = re.compile(r"^(?:BUSCA|BUSCAR|BUSCAME|MUESTRA|MUESTRAME)\s+LA\s+OBRA\b\s*(?P<nombre>.*)$")
# Catálogo de OBRAS (no guías): el cliente es obligatorio al registrar porque
# es la procedencia verificable de la observación. Nunca se infiere desde el
# nombre de la obra ni desde una conversación anterior.
_OBRA_CATALOGO_CORREGIR = re.compile(
    r"^(?:CORRIGE|CORREGIR|CAMBIA|CAMBIAR|ACTUALIZA|ACTUALIZAR)\s+(?:LA\s+)?OBRA\s+"
    r"(?P<actual>.+?)\s+(?:A|POR|COMO)\s+(?P<nueva>.+)$")
_OBRA_CATALOGO_REGISTRAR = re.compile(
    r"^(?:REGISTRA|REGISTRAR|CREA|CREAR)\s+(?:LA\s+)?OBRA\s+(?P<obra>.+?)"
    r"(?:\s+(?:PARA|DEL|DE)\s+(?:EL\s+)?CLIENTE\s+(?P<cliente>.+))?$")
ACCION_INVESTIGAR_REVISION = "INVESTIGAR_REVISION"
_GUIA_INVESTIGACION = re.compile(r"\bGUIA\s+(?:N[°O]?\s*)?(?P<guia>\d{3,12})\b")
_VERBO_INVESTIGAR = re.compile(r"\b(?:INVESTIGA(?:R)?|BUSCA(?:R)?|AVERIGUA(?:R)?)\b")
# Corregir obra o destino con el resultado de la investigación
# inmediatamente anterior: "corrige el nombre de la obra de la guía N usando
# el nombre completo que acabas de identificar", "corrige el destino de la
# guía N usando la dirección que acabas de identificar". Va antes que la
# investigación y que la asignación explícita ("... A <valor>").
ACCION_DESDE_INVESTIGACION = "CORRECCION_DESDE_INVESTIGACION_PREVIA"
ACCION_OBRA_DESDE_INVESTIGACION = ACCION_DESDE_INVESTIGACION  # compatibilidad
_VERBO_CORREGIR = re.compile(
    r"^(?:CORRIGE|CORREGIR|CAMBIA|CAMBIAR|ACTUALIZA|ACTUALIZAR|ASIGNA|ASIGNAR|APLICA|APLICAR|"
    r"REEMPLAZA|REEMPLAZAR|USA|USAR|REGISTRA|REGISTRAR)\b")
_MENCION_OBRA = re.compile(r"\bOBRA\b")
_MENCION_DESTINO = re.compile(r"\b(?:DESTINO|DIRECCION)\b")
_REFERENCIA_INVESTIGACION = re.compile(
    r"\b(?:ACABAS?\s+DE\s+(?:IDENTIFICAR|ENCONTRAR|INVESTIGAR|PROPONER|OBTENER|DETERMINAR)"
    r"|(?:QUE|LO\s+QUE)\s+(?:IDENTIFICASTE|ENCONTRASTE|PROPUSISTE|INVESTIGASTE|DETERMINASTE)"
    r"|PROPUESTA\s+(?:ANTERIOR|DE\s+LA\s+INVESTIGACION|QUE\s+(?:ME\s+)?DISTE))\b")
# Una investigación sólo es "inmediatamente anterior" mientras es reciente.
VIGENCIA_INVESTIGACION = timedelta(minutes=30)
_NIVELES_PROPUESTA_REUTILIZABLE = {"PROPUESTA_RESOLUBLE", "DOCUMENTAL_CONVERGENTE"}


def _intencion_desde_investigacion(plano: str) -> Intencion | None:
    obra, destino = bool(_MENCION_OBRA.search(plano)), bool(_MENCION_DESTINO.search(plano))
    if not (_VERBO_CORREGIR.match(plano) and (obra or destino) and _REFERENCIA_INVESTIGACION.search(plano)):
        return None
    guia = _GUIA_INVESTIGACION.search(plano)
    # Nombra obra Y destino a la vez: no se adivina cuál corregir.
    campo = "" if obra and destino else "obra_destino" if obra else "despachar_a_crudo"
    return Intencion(ACCION_DESDE_INVESTIGACION,
                     {"numero_guia": guia.group("guia") if guia else "", "campo": campo})


# Resolver el destino con una CONFIRMACIÓN HUMANA previa de otra guía del mismo
# contexto: "resuelve el destino de la guía N con el destino ya confirmado".
# Nunca búsqueda externa; ver `atlas_core.destino_confirmacion_previa`.
ACCION_DESTINO_CONFIRMADO_PREVIO = "DESTINO_DESDE_CONFIRMACION_PREVIA"
_VERBO_DESTINO_PREVIO = re.compile(
    r"^(?:RESUELVE|RESOLVER|CORRIGE|CORREGIR|ASIGNA|ASIGNAR|USA|USAR|APLICA|APLICAR|COMPLETA|COMPLETAR|"
    r"REGISTRA|REGISTRAR|PROPON|PROPONE|PROPONER)\b")
_REFERENCIA_CONFIRMACION_PREVIA = re.compile(
    r"\b(?:YA\s+)?CONFIRMAD[OA]S?\b|\bCONFIRMACION\s+(?:HUMANA|PREVIA|ANTERIOR)\b|\bEVIDENCIA\s+INTERNA\b")


def _intencion_destino_confirmado_previo(plano: str) -> Intencion | None:
    guia = _GUIA_INVESTIGACION.search(plano)
    if not (guia and _VERBO_DESTINO_PREVIO.match(plano) and _MENCION_DESTINO.search(plano)
            and not _MENCION_OBRA.search(plano.replace("MISMA OBRA", ""))
            and _REFERENCIA_CONFIRMACION_PREVIA.search(plano)):
        return None
    return Intencion(ACCION_DESTINO_CONFIRMADO_PREVIO, {"numero_guia": guia.group("guia")})


def _intencion_investigar_revision(plano: str) -> Intencion | None:
    """Reconoce investigación consultiva; nunca es una acción del catálogo.
    Sólo un verbo de investigación o un pedido explícito de "nombre/dirección
    completa" la activan: mencionar el destino ("el destino de la guía N es
    X", "¿cuál es el destino de la guía N?") nunca es investigar."""
    pide_nombre = bool(re.search(r"\bNOMBRE\s+COMPLETO\b.*\bOBRA\b|\bOBRA\b.*\bNOMBRE\s+COMPLETO\b", plano))
    pide_direccion_completa = bool(re.search(r"\bDIRECCION\s+COMPLETA\b", plano))
    pide_direccion = pide_direccion_completa or bool(re.search(r"\bDESTINO\b", plano))
    guia = _GUIA_INVESTIGACION.search(plano)
    investigacion = bool(_VERBO_INVESTIGAR.search(plano)) or pide_nombre or pide_direccion_completa
    # "busca la obra X" sigue siendo la consulta de catálogo ya existente.
    if not investigacion or (not guia and not re.search(r"\bESTA\s+(?:OBRA|DIRECCION)\b", plano)):
        return None
    if pide_nombre and pide_direccion:
        campos = ("obra_destino", "despachar_a_crudo")
    elif pide_nombre or (re.search(r"\bOBRA\b", plano) and not pide_direccion):
        campos = ("obra_destino",)
    elif pide_direccion and not re.search(r"\bOBRA\b", plano):
        campos = ("despachar_a_crudo",)
    else:
        campos = ("obra_destino", "despachar_a_crudo")
    return Intencion(ACCION_INVESTIGAR_REVISION,
                     {"numero_guia": guia.group("guia") if guia else "", "campos": campos})


def _consulta_catalogo_choferes(plano: str) -> dict[str, str] | None:
    """Parámetros de CHOFER_CONSULTAR si la pregunta es sobre el CATÁLOGO de
    choferes; None si no (p. ej. "¿cuántos choferes trabajaron?", que se
    responde sobre viajes)."""
    sin_viajes = bool(_SIN_VIAJES.search(plano))
    con_viajes = not sin_viajes and bool(_CON_VIAJES.search(plano))
    if not (_MARCA_CATALOGO_CHOFERES.search(plano) or sin_viajes or con_viajes) or _OTRA_ENTIDAD.search(plano):
        return None
    if not _PALABRA_CHOFER.search(plano) and not _MARCA_CATALOGO_CHOFERES.search(plano):
        return None  # "¿cuántos tienen viajes?" sin decir de quién: no se asume
    parametros = {
        "estado": "INACTIVO" if re.search(r"\bINACTIV", plano) else "ACTIVO" if re.search(r"\bACTIV", plano) else "TODOS",
    }
    if sin_viajes or con_viajes:
        parametros["viajes"] = "SIN" if sin_viajes else "CON"
        parametros.update(_periodo_documental(plano))
    return parametros


def _periodo_documental(plano: str) -> dict[str, str]:
    """Mismo intérprete de período que las consultas sobre viajes."""
    from datetime import date
    from atlas_core.consultas_atlas import resolver_periodo
    from atlas_core.interpretador_consultas import _filtros_periodo

    filtros = _filtros_periodo(plano)
    if "fecha_desde" in filtros:
        return {"fecha_desde": filtros["fecha_desde"], "fecha_hasta": filtros["fecha_hasta"]}
    if "periodo" in filtros:
        dias = int(filtros["dias"]) if filtros.get("dias") else None
        desde, hasta = resolver_periodo(filtros["periodo"], hoy=date.today(), dias=dias)
        return {"fecha_desde": desde.isoformat(), "fecha_hasta": hasta.isoformat()}
    return {}


def interpretar_determinista(texto: str) -> Intencion | None:
    """Sólo patrones de alta certeza; ante la duda devuelve None."""
    from atlas_core.operaciones_conversacionales import _interpretar
    original, plano = _limpio(texto)
    if not plano:
        return None
    m = _DESTRUCTIVA.match(plano)
    if m:
        resto = m.group("resto")
        accion = ("EVIDENCIA_ELIMINAR" if re.search(r"EVIDENCIA|FOTO|IMAGEN|DOCUMENTO", resto)
                  else "HISTORIAL_ELIMINAR" if re.search(r"HISTORIAL|AUDITORIA|REGISTRO", resto) else "ENTIDAD_ELIMINAR")
        return Intencion(accion)
    for patron in (_ESTADO_A, _ESTADO_B, _ESTADO_C):
        m = patron.match(plano)
        if m:
            activo = m.group(1) in {"ACTIVA", "REACTIVA"} if patron is _ESTADO_C else m.group(1) is None
            return Intencion("CHOFER_CAMBIAR_ESTADO", {"activo": activo},
                             {"chofer": original[m.start("chofer"):m.end("chofer")]})
    m = _TRANSPORTE.search(plano)
    if m:
        return Intencion("TRANSPORTE_REVALIDAR", {"numero_transporte": m.group("n")})
    reutilizacion = _intencion_desde_investigacion(plano)
    if reutilizacion is not None:
        return reutilizacion
    confirmado_previo = _intencion_destino_confirmado_previo(plano)
    if confirmado_previo is not None:
        return confirmado_previo
    investigacion = _intencion_investigar_revision(plano)
    if investigacion is not None:
        return investigacion
    es_pregunta = str(texto or "").strip().endswith("?") or str(texto or "").strip().startswith("¿")
    if not es_pregunta and _MISMO_VIAJE.search(plano) and not _NEGACION_MISMO_VIAJE.search(plano):
        guias = list(dict.fromkeys(_NUMERO_GUIA.findall(plano)))
        if len(guias) >= 2:
            return Intencion("VIAJE_AGRUPAR_GUIAS", {"guias": guias})
    if not es_pregunta:
        for patron in _COORDENADA_DESTINO:
            m = patron.match(plano)
            if m:
                return Intencion("DESTINO_CONFIRMAR_COORDENADA",
                                 {"latitud": float(m.group("lat").replace(" ", "")),
                                  "longitud": float(m.group("lon").replace(" ", ""))},
                                 {"destino": original[m.start("destino"):m.end("destino")].strip(" ,:")})
        for patron in _OBRA_GUIA:
            m = patron.match(plano)
            if m:
                return Intencion("DOCUMENTO_ASIGNAR_OBRA", {"numero_guia": m.group("guia")},
                                 {"obra": original[m.start("obra"):m.end("obra")].strip(" ,:")})
        m = _OBRA_CATALOGO_CORREGIR.match(plano)
        if m and "GUIA" not in m.group("actual"):
            return Intencion("OBRA_CORREGIR", {
                "nombre_canonico": original[m.start("nueva"):m.end("nueva")].strip(" ,:")},
                {"obra": original[m.start("actual"):m.end("actual")].strip(" ,:")})
        m = _OBRA_CATALOGO_REGISTRAR.match(plano)
        if m:
            menciones = {}
            if m.group("cliente"):
                menciones["cliente"] = original[m.start("cliente"):m.end("cliente")].strip(" ,:")
            return Intencion("OBRA_REGISTRAR", {
                "nombre_obra": original[m.start("obra"):m.end("obra")].strip(" ,:")}, menciones)
    for patron in _DESTINO_GUIA:
        m = patron.match(plano)
        if m:
            direccion = original[m.start("dir"):m.end("dir")].strip(" ,")
            parametros = {"accion_decision": "REGISTRAR_DIRECCION"}
            comuna = _COMUNA_EXPLICITA.match(_plano(direccion))
            if comuna:
                parametros["comuna_manual"] = direccion[comuna.start("comuna"):comuna.end("comuna")].strip()
                direccion = direccion[:comuna.end("dir")].strip(" ,")
            parametros["direccion_manual"] = direccion
            return Intencion("DECISION_APLICAR", parametros, {"guia_destino": m.group("guia")})
    m = _DOCUMENTO.match(plano)
    if m:
        return Intencion("DOCUMENTO_CORREGIR_CAMPO", {
            "numero_guia": m.group("guia"), "campo": _CAMPOS_DOC[m.group("campo")],
            "valor": original[m.start("valor"):m.end("valor")].strip()})
    m = _LECTURA_OBRAS.match(plano)
    if m:
        nombre = original[m.start("nombre"):m.end("nombre")].strip()
        return Intencion("OBRA_CONSULTAR", {"nombre": nombre} if nombre else {})
    if _VERBO_LECTURA.match(plano) or str(texto or "").strip().endswith("?"):
        m = _INACTIVIDAD_CHOFERES.search(plano)
        if m and not (_OTRA_ENTIDAD.search(plano) and not _PALABRA_CHOFER.search(plano)):
            return Intencion("CHOFER_CONSULTAR", {"dias_sin_actividad": int(m.group("n")),
                                                  "detalle": not re.match(r"^CUANT[OA]S\b", plano)})
        for patron in _ESTADO_INDIVIDUAL:
            m = patron.match(plano)
            if m and not _MENCION_GENERAL.search(m.group("chofer")):
                return Intencion("CHOFER_CONSULTAR", {},
                                 {"chofer": original[m.start("chofer"):m.end("chofer")].strip(" ,:")})
        consulta_choferes = _consulta_catalogo_choferes(plano)
        if consulta_choferes is not None:
            return Intencion("CHOFER_CONSULTAR", consulta_choferes)
        m = _LECTURA_DECISIONES.search(plano)
        if m and not _NO_ES_DECISION.search(plano):
            return Intencion("DECISION_CONSULTAR", {"numero_guia": m.group("guia")} if m.group("guia") else {})
        return None
    asociacion = _interpretar(texto)
    if asociacion:
        tipo, chofer, patente = asociacion
        return Intencion("CHOFER_ASIGNAR_VEHICULO", {"patente": patente}, {"chofer": chofer},
                         tipo_vehiculo_declarado=tipo)
    return None


# --------------------------------------------------------------- modelo (opcional)


class ProveedorInterpretacionAcciones(Protocol):
    """Traduce texto a {accion, parametros, menciones}. Recibe el contrato
    público para elegir; su salida SIEMPRE se valida después."""

    def interpretar(self, texto: str, contrato: list[dict]) -> Mapping[str, object] | None: ...


class ErrorContratoInterpretacion(ValueError):
    pass


# mención -> parámetro de la acción que resuelve (nunca se pasa cruda).
_MENCIONES_PERMITIDAS = {"chofer": "chofer", "guia_destino": "decision_id", "obra": "obra_id",
                         "destino": "destino_id", "cliente": "cliente_id"}
_SOSPECHOSO = re.compile(
    r"(^[A-Za-z]:[\\/])|(\.\.[\\/])|(^[\\/])|(\\\\)|[;|&`$<>{}]|"
    r"\b(?:rm|del|rmdir|powershell|cmd|bash|sh|python|py|pip|import|exec|eval|subprocess|os\.system|"
    r"open|drop|select|insert|update|delete|curl|wget)\b\s*[\-(/\\*.]|\w+\.\w+\s*\(|\.(?:py|ps1|bat|exe|sh|json|csv)\b",
    re.I,
)


def _guardia_valor(nombre: str, valor: object) -> None:
    valores = valor if isinstance(valor, list) else [valor]
    for v in valores:
        if isinstance(v, bool) or isinstance(v, (int, float)):
            continue
        if not isinstance(v, str):
            raise ErrorContratoInterpretacion(f"{nombre}: tipo de valor no permitido")
        if _SOSPECHOSO.search(v):
            raise ErrorContratoInterpretacion(f"{nombre}: el valor parece una ruta, comando o código")


def validar_intencion(intencion: Intencion) -> Intencion:
    """Contrato común (determinista o modelo) ANTES de llegar al ejecutor."""
    definicion = ACCIONES.get(intencion.accion)
    if definicion is None:
        raise ErrorContratoInterpretacion("acción fuera del catálogo canónico")
    esquema = _esquema(definicion)
    fuera = sorted(set(intencion.parametros) - set(esquema))
    if fuera:
        raise ErrorContratoInterpretacion(f"parámetros fuera del esquema: {', '.join(fuera)}")
    if set(intencion.menciones) - set(_MENCIONES_PERMITIDAS):
        raise ErrorContratoInterpretacion("mención no permitida")
    for mencion in intencion.menciones:
        if _MENCIONES_PERMITIDAS[mencion] not in esquema:
            raise ErrorContratoInterpretacion(f"la acción no admite la mención {mencion}")
    for nombre, valor in {**intencion.parametros, **intencion.menciones}.items():
        _guardia_valor(nombre, valor)
    return intencion


def intencion_desde_modelo(propuesta: object) -> Intencion:
    if not isinstance(propuesta, Mapping):
        raise ErrorContratoInterpretacion("la propuesta del modelo no es un objeto")
    if set(propuesta) - {"accion", "parametros", "menciones"}:
        raise ErrorContratoInterpretacion("la propuesta del modelo trae claves fuera del contrato")
    accion = propuesta.get("accion")
    parametros = propuesta.get("parametros") or {}
    menciones = propuesta.get("menciones") or {}
    if not isinstance(accion, str) or not isinstance(parametros, Mapping) or not isinstance(menciones, Mapping):
        raise ErrorContratoInterpretacion("propuesta del modelo con tipos inválidos")
    if not all(isinstance(v, str) for v in menciones.values()):
        raise ErrorContratoInterpretacion("menciones deben ser texto")
    return validar_intencion(Intencion(accion.strip().upper(), dict(parametros), dict(menciones), fuente="MODELO"))


# --------------------------------------------------------------- resolución de entidades


def _candidatos_chofer(choferes: Mapping[str, dict], mencion: str) -> list[dict]:
    from atlas_core.catalogos import rut_canonico_de_registro_chofer
    from atlas_core.convergencia_identidad_conocida import _candidatos_contextuales_chofer
    return [{"chofer": clave, "nombre": str(r.get("nombre", "")), "rut": rut_canonico_de_registro_chofer(clave, r) or "",
             "activo": r.get("activo", True) is True}
            for clave, r in _candidatos_contextuales_chofer(choferes, mencion)]


def resolver_chofer(choferes: Mapping[str, dict], mencion: str, *, incluir_inactivos: bool) -> dict:
    """{'estado': RESUELTO|AMBIGUO|DESCONOCIDO, 'chofer', 'nombre', 'candidatos'}"""
    from atlas_core.catalogos import normalizar_rut
    from atlas_core.convergencia_identidad_conocida import resolver_identidad_nominal_fuerte_chofer
    from atlas_core.validadores import EstadoValidacion, validar_rut_chileno
    vista = {k: ({**r, "activo": True} if incluir_inactivos else r) for k, r in choferes.items() if isinstance(r, dict)}
    if validar_rut_chileno(mencion).estado == EstadoValidacion.VALIDO:
        buscado = normalizar_rut(mencion)
        claves = [k for k, r in vista.items() if r.get("activo", True) is True
                  and buscado in {normalizar_rut(k), normalizar_rut(str(r.get("rut", "")))}]
        if len(claves) == 1:
            return {"estado": "RESUELTO", "chofer": claves[0], "nombre": str(vista[claves[0]].get("nombre", ""))}
    identidad = resolver_identidad_nominal_fuerte_chofer(nombre_documental=mencion, rut_documental="", choferes=vista)
    if identidad.resultado == "RESUELTO" and identidad.identificador:
        return {"estado": "RESUELTO", "chofer": identidad.identificador, "nombre": identidad.nombre_canonico or ""}
    candidatos = _candidatos_chofer(vista, mencion)
    for c in candidatos:
        c["activo"] = choferes.get(c["chofer"], {}).get("activo", True) is True
    return {"estado": "AMBIGUO" if len(candidatos) > 1 else "DESCONOCIDO", "candidatos": candidatos}


def resolver_decision_destino(decisiones: list[Mapping[str, object]], guia: str) -> tuple[str, str]:
    """(decision_id, "") si la guía tiene EXACTAMENTE una revisión de destino
    pendiente que admite REGISTRAR_DIRECCION (misma tarjeta que Revisión);
    si no, ("", mensaje de aclaración). Nunca crea ni adivina una decisión."""
    candidatas = [
        d for d in decisiones
        if str((d.get("documento") or {}).get("numero_guia", "")).strip() == guia
        and d.get("tipo") == "DESTINO_NO_RESUELTO" and d.get("estado", "PENDIENTE") == "PENDIENTE"
        and "REGISTRAR_DIRECCION" in (d.get("acciones_permitidas") or [])
    ]
    if len(candidatas) == 1:
        return str(candidatas[0]["decision_id"]), ""
    if len(candidatas) > 1:
        archivos = ", ".join(str((d.get("documento") or {}).get("archivo", "")) for d in candidatas)
        return "", (f"La guía {guia} tiene más de una revisión de destino pendiente ({archivos}); "
                    "resuélvela desde Revisión de Atlas.")
    return "", (f"La guía {guia} no tiene una revisión de destino pendiente en la bandeja. Si el destino "
                "de un viaje ya calculado está mal, usa «Corregir destino» en la Logística del viaje.")


def resolver_obra(obras: list, mencion: str) -> dict:
    """{'estado': RESUELTO|AMBIGUO|DESCONOCIDO, 'obra_id', 'nombre', 'candidatos'}.
    Sólo coincidencia exacta normalizada con el nombre canónico o un alias de
    una obra vigente; nunca crea obra ni adivina entre varias."""
    from atlas_core.catalogo_obras_destinos import normalizar_nombre_obra
    clave = normalizar_nombre_obra(mencion)
    vigentes = [o for o in obras if o.estado_vigencia == "ACTIVO" and o.estado not in {"RECHAZADA", "INACTIVA"}]
    exactas = [o for o in vigentes
               if clave and clave in {normalizar_nombre_obra(x) for x in (o.nombre_canonico, *o.aliases_documentales)}]
    if len(exactas) == 1:
        return {"estado": "RESUELTO", "obra_id": exactas[0].obra_id, "nombre": exactas[0].nombre_canonico}
    parecidas = exactas or [o for o in vigentes if clave and (clave in normalizar_nombre_obra(o.nombre_canonico)
                                                              or normalizar_nombre_obra(o.nombre_canonico) in clave)]
    return {"estado": "AMBIGUO" if len(exactas) > 1 else "DESCONOCIDO",
            "candidatos": [{"obra_id": o.obra_id, "nombre": o.nombre_canonico} for o in parecidas[:10]]}


def resolver_cliente(clientes: list, mencion: str) -> dict:
    """Resuelve sólo identidad canónica/alias activa; nunca crea clientes."""
    from atlas_core.catalogo_clientes import normalizar_nombre_cliente
    clave = normalizar_nombre_cliente(mencion)
    activos = [c for c in clientes if c.estado_vigencia == "ACTIVO"]
    exactos = [c for c in activos if clave and clave in {
        normalizar_nombre_cliente(x) for x in (c.razon_social, c.nombre_comercial, *c.aliases) if x}]
    parecidos = exactos or [c for c in activos if clave and (
        clave in normalizar_nombre_cliente(c.razon_social)
        or normalizar_nombre_cliente(c.razon_social) in clave)]
    if len(exactos) == 1:
        return {"estado": "RESUELTO", "cliente_id": exactos[0].cliente_id, "nombre": exactos[0].razon_social}
    return {"estado": "AMBIGUO" if len(exactos) > 1 else "DESCONOCIDO",
            "candidatos": [{"nombre": c.razon_social} for c in parecidos[:10]]}


def resolver_destino(destinos: list, mencion: str) -> dict:
    """{'estado': RESUELTO|AMBIGUO|DESCONOCIDO, 'destino_id', 'direccion', 'candidatos'}.
    Sólo coincidencia exacta normalizada con dirección, nombre o alias de un
    destino ACTIVO existente; nunca crea destinos ni elige entre varios."""
    from atlas_core.catalogo_destinos import normalizar_nombre_destino
    clave = normalizar_nombre_destino(mencion)
    activos = [d for d in destinos if d.estado_vigencia == "ACTIVO"]
    exactos = [d for d in activos if clave and clave in {
        normalizar_nombre_destino(t) for t in (d.direccion, d.nombre_destino, *d.aliases) if t}]
    if len(exactos) == 1:
        return {"estado": "RESUELTO", "destino_id": exactos[0].destino_id, "direccion": exactos[0].direccion}
    parecidos = exactos or [d for d in activos if clave and clave in normalizar_nombre_destino(d.direccion or "")]
    return {"estado": "AMBIGUO" if len(exactos) > 1 else "DESCONOCIDO",
            "candidatos": [{"destino_id": d.destino_id, "direccion": d.direccion or d.nombre_destino,
                            "comuna": d.comuna} for d in parecidos[:10]]}


# --------------------------------------------------------------- formato


def _peso_legible(valor: object) -> str:
    texto = str(valor or "").strip()
    return f"{int(texto):,} kg".replace(",", ".") if texto.isdigit() else "peso no disponible"


def _km_legible(valor: object) -> str:
    try:
        return f"{float(str(valor)):.0f} km"
    except ValueError:
        return "ruta no disponible"


def _describir_preview(preview: Mapping[str, object]) -> str:
    accion, entidad = preview.get("accion"), preview.get("entidad") or {}
    actual, propuesto = preview.get("valor_actual"), preview.get("valor_propuesto") or {}
    if accion == "CHOFER_ASIGNAR_VEHICULO":
        texto = (f"Asociar {propuesto.get('tipo')} {propuesto.get('patente')} al chofer "
                 f"{entidad.get('chofer')} (RUT {propuesto.get('rut_chofer')}).")
    elif accion == "CHOFER_CAMBIAR_ESTADO":
        estado = "ACTIVO" if propuesto.get("activo") else "INACTIVO"
        texto = f"Dejar al chofer {entidad.get('nombre')} como {estado}."
    elif accion == "DECISION_APLICAR" and propuesto.get("accion") == "REGISTRAR_DIRECCION":
        documento = entidad.get("documento") or {}
        comuna = f", comuna {propuesto['comuna_manual']}" if propuesto.get("comuna_manual") else ""
        texto = (f"Registrar el destino de la guía {documento.get('numero_guia')} (transporte "
                 f"{documento.get('numero_transporte')}): leído {(actual or {}).get('valor_documental')!r} -> "
                 f"{propuesto.get('direccion_manual')!r}{comuna}. Se geocodifica, se recalcula la ruta del viaje "
                 "y se cierra la revisión de destino.")
    elif accion == "VIAJE_AGRUPAR_GUIAS":
        unico = propuesto.get("viaje_unico") or {}
        partes_viajes = "; ".join(
            f"transporte {v.get('numero_transporte')} (guía {', '.join(v.get('guias') or [])})"
            for v in (actual or {}).get("viajes") or [])
        texto = (f"Agrupar en UN solo viaje Atlas: {partes_viajes}. Viaje resultante con transporte principal "
                 f"{unico.get('numero_transporte_principal')} y transportes AZA "
                 f"{' + '.join(unico.get('transportes_aza') or [])}; cada guía conserva su número de transporte.")
        cargas = unico.get("cargas") or []
        entregas = unico.get("entregas") or []
        if cargas:
            texto += " CARGAS: " + "; ".join(
                f"transporte {c['numero_transporte']} en {' / '.join(c['plantas']) or 'planta no disponible'}"
                f"{' (' + ', '.join(c['horas_planta']) + ')' if c['horas_planta'] else ''}: "
                + ", ".join(f"guía {g['numero_guia']} {_peso_legible(g['peso_kg'])}" for g in c["guias"])
                for c in cargas) + "."
        if entregas:
            texto += f" {len(entregas)} ENTREGA(S): " + "; ".join(
                f"{i}) guía {', '.join(e['guias'])} -> {e['destino'] or 'destino no disponible'}"
                f"{' (' + e['localidad'] + ')' if e['localidad'] else ''}"
                f"{', ' + _km_legible(e['distancia_km']) if e['distancia_km'] else ''}"
                for i, e in enumerate(entregas, 1)) + "."
        if unico.get("estado_resultante"):
            motivos = unico.get("motivos_revision") or []
            texto += (f" Peso total {_peso_legible(unico.get('peso_total_kg'))}. Estado resultante: "
                      f"{unico['estado_resultante']}{' (' + ', '.join(motivos) + ')' if motivos else ''}.")
    elif accion == "DESTINO_CONFIRMAR_COORDENADA":
        texto = (f"Confirmar la coordenada del destino {entidad.get('direccion')!r}: "
                 f"{propuesto.get('latitud')}, {propuesto.get('longitud')}.")
        # sólo destino, coordenada y consecuencias operacionales
        return " ".join([texto, *(str(c) for c in preview.get("consecuencias") or [])])
    elif accion == "DOCUMENTO_ASIGNAR_OBRA":
        texto = (f"Asignar la obra de la guía {entidad.get('numero_guia')} (transporte "
                 f"{entidad.get('numero_transporte')}): actual {(actual or {}).get('obra_destino')!r} -> "
                 f"{propuesto.get('obra_destino')!r} (obra existente, obra_id {propuesto.get('obra_id')}).")
    elif accion == "DOCUMENTO_CORREGIR_CAMPO":
        texto = (f"Corregir {entidad.get('campo')} de la guía {entidad.get('numero_guia')}: "
                 f"{(actual or {}).get(entidad.get('campo'))!r} -> {propuesto.get(entidad.get('campo'))!r}.")
    else:
        texto = f"{accion}: {entidad} -> {propuesto}."
    afectados = preview.get("afectados") or {}
    partes = [texto]
    if isinstance(afectados, Mapping):
        if "total_guias" in afectados:
            partes.append(f"Afecta {afectados['total_guias']} guía(s) y {afectados.get('total_decisiones', 0)} "
                          "decisión(es) pendiente(s).")
        if afectados.get("decisiones_obsoletas"):
            partes.append(f"Retirará {len(afectados['decisiones_obsoletas'])} decisión(es) obsoleta(s).")
    partes.extend(str(c) for c in preview.get("consecuencias") or [])
    return " ".join(partes)


def _fecha_legible(iso: object) -> str:
    texto = str(iso or "")
    return f"{texto[8:10]}-{texto[5:7]}-{texto[:4]}" if len(texto) == 10 else texto


def _choferes_publicos(choferes: list[Mapping[str, object]]) -> list[dict[str, object]]:
    """Sólo datos operacionales: nunca la clave interna del catálogo. El RUT
    se muestra sólo para distinguir a dos choferes con el mismo nombre."""
    repetidos = {n for n in (str(c.get("nombre", "")) for c in choferes)
                 if sum(str(c.get("nombre", "")) == n for c in choferes) > 1}
    publicos = []
    for c in choferes:
        vista = {"nombre": str(c.get("nombre", "")), "activo": c.get("activo") is True}
        if "con_viajes" in c:
            vista["con_viajes"] = c.get("con_viajes") is True
        for campo in ("ultimo_viaje", "dias_sin_actividad"):
            if campo in c:
                vista[campo] = c[campo]
        if vista["nombre"] in repetidos and c.get("rut"):
            vista["rut"] = str(c["rut"])
        publicos.append(vista)
    return publicos


def _resultado_lectura_publico(accion: str, resultado: Mapping[str, object]) -> Mapping[str, object]:
    if accion != "CHOFER_CONSULTAR":
        return resultado
    publico = {**{k: v for k, v in resultado.items() if k not in {"choferes", "sin_viajes_registrados"}},
               "choferes": _choferes_publicos(list(resultado.get("choferes") or []))}
    if "sin_viajes_registrados" in resultado:
        publico["sin_viajes_registrados"] = _choferes_publicos(list(resultado["sin_viajes_registrados"] or []))
    return publico


def _describir_inactividad_choferes(resultado: Mapping[str, object]) -> str:
    dias, total = resultado.get("dias"), int(resultado.get("total", 0) or 0)
    choferes = _choferes_publicos(list(resultado.get("choferes") or []))
    sin_registro = _choferes_publicos(list(resultado.get("sin_viajes_registrados") or []))
    texto = (f"{total} chofer{'es' if total != 1 else ''} activo{'s' if total != 1 else ''} "
             f"lleva{'n' if total != 1 else ''} más de {dias} días sin cargar "
             f"(al {_fecha_legible(resultado.get('fecha_referencia'))}).")
    if resultado.get("detalle") and choferes:
        texto += " Chofer | último viaje | días sin cargar: " + "; ".join(
            f"{c['nombre']} | {_fecha_legible(c['ultimo_viaje'])} | {c['dias_sin_actividad']}" for c in choferes) + "."
    if sin_registro:
        k = len(sin_registro)
        texto += (f" Además, {k} chofer{'es' if k != 1 else ''} activo{'s' if k != 1 else ''} "
                  f"no tiene{'n' if k != 1 else ''} viajes registrados")
        texto += (": " + "; ".join(c["nombre"] for c in sin_registro) + " (sin viajes registrados)."
                  if resultado.get("detalle") else ".")
    return texto


def _describir_catalogo_choferes(resultado: Mapping[str, object]) -> str:
    if resultado.get("modo") == "INACTIVIDAD":
        return _describir_inactividad_choferes(resultado)
    if resultado.get("chofer_individual"):
        chofer = (resultado.get("choferes") or [{}])[0]
        return f"{chofer.get('nombre', '')} está {'ACTIVO' if chofer.get('activo') else 'INACTIVO'}."
    resumen = resultado.get("resumen") or {}
    periodo = resultado.get("periodo") or {}
    en_periodo = (f" entre el {_fecha_legible(periodo.get('desde'))} y el {_fecha_legible(periodo.get('hasta'))}"
                  if periodo else "")
    estado, viajes = resultado.get("estado", "TODOS"), resultado.get("viajes", "TODOS")
    if estado == "TODOS" and viajes == "TODOS":
        activos, inactivos = int(resumen.get("activos", 0)), int(resumen.get("inactivos", 0))
        return (f"{resumen.get('registrados', 0)} choferes registrados en el catálogo: "
                f"{activos} activo{'s' if activos != 1 else ''} y {inactivos} inactivo{'s' if inactivos != 1 else ''}; "
                f"{resumen.get('con_viajes', 0)} con viajes y {resumen.get('sin_viajes', 0)} sin viajes{en_periodo}.")
    partes = []
    if estado != "TODOS":
        partes.append("activos" if estado == "ACTIVO" else "inactivos")
    if viajes != "TODOS":
        partes.append(("con" if viajes == "CON" else "sin") + f" viajes{en_periodo}")
    total = int(resultado.get("total", 0) or 0)
    descripcion = f"chofer(es) del catálogo {' y '.join(partes)}"
    if not total:
        return f"0 {descripcion}."
    nombres = "; ".join(
        c["nombre"] + (f" (RUT {c['rut']})" if c.get("rut") else "")
        for c in _choferes_publicos(list(resultado.get("choferes") or [])))
    return f"{total} {descripcion} (de {resumen.get('registrados', 0)} registrados): {nombres}."


def _presentacion_chofer_estado(preview: Mapping[str, object]) -> dict[str, object]:
    """Preview/resultado de activar-inactivar un chofer sin claves internas."""
    entidad = preview.get("entidad") or {}
    afectados = preview.get("afectados") or {}

    def legible(valor: object) -> str:
        return "ACTIVO" if (valor or {}).get("activo") else "INACTIVO"

    return {"tipo": "chofer_estado", "chofer": str(entidad.get("nombre", "")),
            "antes": legible(preview.get("valor_actual")), "despues": legible(preview.get("valor_propuesto")),
            "guias_afectadas": int(afectados.get("total_guias", 0) or 0) if isinstance(afectados, Mapping) else 0,
            "decisiones_afectadas": int(afectados.get("total_decisiones", 0) or 0) if isinstance(afectados, Mapping) else 0,
            "consecuencias": [str(c) for c in preview.get("consecuencias") or []]}


def _preview_chofer_estado_publico(presentacion: Mapping[str, object]) -> dict[str, object]:
    """Mismo contrato que Desktop ya consume (entidad / valor_actual /
    valor_propuesto / afectados), sin ninguna clave interna del catálogo."""
    return {"entidad": {"nombre": presentacion["chofer"]},
            "valor_actual": {"activo": presentacion["antes"] == "ACTIVO"},
            "valor_propuesto": {"activo": presentacion["despues"] == "ACTIVO"},
            "afectados": {"total_guias": presentacion["guias_afectadas"],
                          "total_decisiones": presentacion["decisiones_afectadas"]},
            "consecuencias": list(presentacion["consecuencias"]), "chofer": presentacion["chofer"]}


def _resultado_chofer_estado_publico(presentacion: Mapping[str, object], *, reconciliada: bool) -> dict[str, object]:
    return {"estado": "APLICADA", "entidad": {"nombre": presentacion["chofer"]}, "chofer": presentacion["chofer"],
            "antes": {"activo": presentacion["antes"] == "ACTIVO"},
            "despues": {"activo": presentacion["despues"] == "ACTIVO"},
            "bandeja_reconciliada": reconciliada}


def _mensaje_chofer_estado(presentacion: Mapping[str, object]) -> str:
    return (f"Dejar al chofer {presentacion['chofer']} como {presentacion['despues']} "
            f"(hoy {presentacion['antes']}). No se borra el chofer ni se modifican sus viajes, RUT, alias ni "
            f"vehículos. Guías relacionadas: {presentacion['guias_afectadas']}; decisiones pendientes: "
            f"{presentacion['decisiones_afectadas']}. " + " ".join(presentacion["consecuencias"]))


def _describir_lectura(accion: str, resultado: Mapping[str, object]) -> str:
    if accion == "CHOFER_CONSULTAR":
        return _describir_catalogo_choferes(resultado)
    if accion == "DECISION_CONSULTAR":
        decisiones = resultado.get("decisiones") or []
        return (f"{resultado.get('total', 0)} decisión(es) pendiente(s): "
                + "; ".join(f"{d['tipo']} guía {(d.get('documento') or {}).get('numero_guia')}" for d in decisiones)
                if decisiones else "No hay decisiones pendientes.")
    if accion == "OBRA_CONSULTAR":
        obras = resultado.get("obras") or []
        return (f"{resultado.get('total', 0)} obra(s): " + "; ".join(f"{o['nombre']} ({o['estado']})" for o in obras)
                if obras else "No encontré obras con ese nombre.")
    return str(resultado)


def _describir_resultado(resultado: Mapping[str, object]) -> str:
    partes = [f"Aplicado: {resultado.get('accion')}. Antes: {resultado.get('antes')}. Después: {resultado.get('despues')}."]
    reconciliacion = resultado.get("reconciliacion") or {}
    if reconciliacion:
        partes.append("Bandeja reconciliada." if reconciliacion.get("ejecutado")
                      else f"Bandeja no reconciliada ({reconciliacion.get('motivo')}).")
    if resultado.get("decisiones_retiradas"):
        partes.append(f"Decisiones retiradas: {len(resultado['decisiones_retiradas'])}.")
    revalidacion = resultado.get("revalidacion") or {}
    if revalidacion.get("focal"):
        partes.append("Revalidación focal ejecutada.")
    if (revalidacion.get("reporte") or {}).get("regenerado"):
        partes.append("Reporte de viajes regenerado.")
    return " ".join(partes)


# --------------------------------------------------------------- investigación previa


def registro_investigacion_obra(numero_guia: str, campos: tuple, resultado: Mapping | None,
                                creado_en: str) -> dict:
    """Resultado ESTRUCTURADO de una investigación (de sus expedientes, nunca
    del texto mostrado) para que la conversación pueda reutilizarlo.
    estado: PROPUESTA | SIN_PROPUESTA | AMBIGUA | FALLIDA | NO_SOLICITADA."""
    registro = {"numero_guia": str(numero_guia), "campo": "obra_destino", "creado_en": creado_en,
                "estado": "FALLIDA", "valor_documental": "", "propuesta_publicada": "",
                "nivel_evidencia": "", "evidencia_relevante": "", "fuentes": []}
    if "obra_destino" not in tuple(campos or ()):
        return {**registro, "estado": "NO_SOLICITADA"}
    if resultado is None:
        return registro
    registro["numero_transporte"] = str(resultado.get("numero_transporte") or "")
    expedientes = [e for e in resultado.get("expedientes") or []
                   if isinstance(e, Mapping) and e.get("CAMPO") == "obra_destino"]
    for expediente in expedientes:
        valor = str((expediente.get("HECHOS_DOCUMENTALES") or {}).get("valor_extraido") or "")
        if valor and not registro["valor_documental"]:
            registro["valor_documental"] = valor
    propuestas = [e for e in expedientes
                  if str(e.get("PROPUESTA") or "").strip()
                  and e.get("ACCION_RECOMENDADA") == "PROPONER_A_HUMANO"
                  and e.get("NIVEL_EVIDENCIA") in _NIVELES_PROPUESTA_REUTILIZABLE
                  and (e.get("EVALUACION_CANDIDATOS_EXTERNOS") or {}).get("estado") in (None, "PROPUESTA_RESOLUBLE")]
    if not propuestas:
        sin_busqueda = (resultado.get("BUSQUEDA_EXTERNA") or {}).get("estado") in {"FALLIDA", "NO_DISPONIBLE"}
        return {**registro, "estado": "FALLIDA" if sin_busqueda or not expedientes else "SIN_PROPUESTA"}
    distintas: list[str] = []
    for expediente in propuestas:
        nombre = str(expediente["PROPUESTA"]).strip()
        if not any(misma_identidad(nombre, previa) for previa in distintas):
            distintas.append(nombre)
    if len(distintas) != 1:
        return {**registro, "estado": "AMBIGUA"}
    elegido = propuestas[0]
    evaluacion = elegido.get("EVALUACION_CANDIDATOS_EXTERNOS") or {}
    fuentes: list[str] = []
    for evidencia in elegido.get("EVIDENCIA_EXTERNA") or []:
        referencias = (evidencia.get("referencias_fuente") or []) if isinstance(evidencia, Mapping) else []
        for referencia in referencias:
            if str(referencia).startswith("http") and referencia not in fuentes:
                fuentes.append(str(referencia))
    return {**registro, "estado": "PROPUESTA", "propuesta_publicada": distintas[0],
            "nivel_evidencia": str(elegido.get("NIVEL_EVIDENCIA") or ""),
            "evidencia_relevante": str((elegido.get("PREVIEW_OPERACIONAL") or {}).get("evidencia_relevante")
                                       or evaluacion.get("razon") or "")[:300],
            "fuentes": fuentes[:5]}


def _numero_calle(texto: object) -> str:
    """Número de calle del texto (primer token con dígitos), '' si no hay."""
    m = re.search(r"\b(\d{1,6}[A-Z]?)\b", str(texto or "").upper())
    return m.group(1) if m else ""


def registro_investigacion_destino(numero_guia: str, campos: tuple, resultado: Mapping | None,
                                   creado_en: str) -> dict:
    """Propuesta ESTRUCTURADA de dirección operacional de una investigación.

    Reutiliza el veredicto de `evaluar_candidatos` (dos fuentes públicas
    independientes verificadas, calle y comuna compatibles con el documento,
    vínculo con la obra/cliente de la guía; nunca propiedad ni titularidad)
    y además exige aquí, sin excepción: un número de calle publicado
    literalmente por TODAS las fuentes del candidato (nunca inferido), que no
    contradiga el número documental, y una sola dirección.
    estado: PROPUESTA | SIN_PROPUESTA | NUMERO_NO_SUSTENTADO | CONTRADICCION |
    AMBIGUA | FALLIDA | NO_SOLICITADA."""
    registro = {"numero_guia": str(numero_guia), "campo": "despachar_a_crudo", "creado_en": creado_en,
                "estado": "FALLIDA", "valor_documental": "", "propuesta_publicada": "", "calle": "",
                "numero": "", "comuna": "", "nivel_evidencia": "", "evidencia_relevante": "",
                "fuentes": [], "dominios": []}
    if "despachar_a_crudo" not in tuple(campos or ()):
        return {**registro, "estado": "NO_SOLICITADA"}
    if resultado is None:
        return registro
    expedientes = [e for e in resultado.get("expedientes") or []
                   if isinstance(e, Mapping) and e.get("CAMPO") == "despachar_a_crudo"]
    for expediente in expedientes:
        hechos = expediente.get("HECHOS_DOCUMENTALES") or {}
        valor = str(hechos.get("valor_extraido") or hechos.get("destino_original") or "")
        if valor and not registro["valor_documental"]:
            registro["valor_documental"] = valor
    propuestas = [e for e in expedientes
                  if str(e.get("PROPUESTA") or "").strip()
                  and e.get("ACCION_RECOMENDADA") == "PROPONER_A_HUMANO"
                  and e.get("NIVEL_EVIDENCIA") in _NIVELES_PROPUESTA_REUTILIZABLE
                  and (e.get("EVALUACION_CANDIDATOS_EXTERNOS") or {}).get("estado") == "PROPUESTA_RESOLUBLE"
                  and isinstance((e.get("EVALUACION_CANDIDATOS_EXTERNOS") or {}).get("propuesta"), Mapping)]
    if not propuestas:
        sin_busqueda = (resultado.get("BUSQUEDA_EXTERNA") or {}).get("estado") in {"FALLIDA", "NO_DISPONIBLE"}
        return {**registro, "estado": "FALLIDA" if sin_busqueda or not expedientes else "SIN_PROPUESTA"}
    candidatas: list[dict] = []
    for expediente in propuestas:
        evaluacion = expediente["EVALUACION_CANDIDATOS_EXTERNOS"]
        ganador = evaluacion["propuesta"]
        if any(v == "CONTRADICE" for v in (ganador.get("comparaciones") or {}).values()):
            return {**registro, "estado": "CONTRADICCION"}
        fuentes = [f for f in ganador.get("fuentes") or []
                   if isinstance(f, Mapping) and f.get("verificacion") == "VERIFICADA"]
        numeros = {_numero_calle(f.get("numero")) for f in fuentes}
        if not fuentes or len(numeros) != 1 or "" in numeros:
            return {**registro, "estado": "NUMERO_NO_SUSTENTADO"}
        numero = next(iter(numeros))
        documental = _numero_calle(evaluacion.get("numero_documental"))
        if documental and documental != numero:
            return {**registro, "estado": "CONTRADICCION"}
        patron = fuentes[0]
        candidatas.append({
            "calle": " ".join(str(patron.get("direccion") or "").split()),
            "numero": numero, "comuna": " ".join(str(patron.get("comuna") or "").split()),
            "nivel_evidencia": str(expediente.get("NIVEL_EVIDENCIA") or ""),
            "evidencia_relevante": str(evaluacion.get("razon") or "")[:300],
            "fuentes": [str(f.get("url")) for f in fuentes if str(f.get("url") or "").startswith("http")][:5],
            "dominios": [str(d) for d in ganador.get("fuentes_independientes") or []][:5],
        })
    claves = {(clave_identidad(c["calle"]), c["numero"], clave_identidad(c["comuna"])) for c in candidatas}
    if len(claves) != 1:
        return {**registro, "estado": "AMBIGUA"}
    elegida = candidatas[0]
    if not elegida["calle"] or not elegida["comuna"]:
        return {**registro, "estado": "SIN_PROPUESTA"}
    return {**registro, **elegida, "estado": "PROPUESTA",
            "propuesta_publicada": f"{elegida['calle']} {elegida['numero']}, {elegida['comuna']}"}


def _obra_por_identidad(obras: list, nombre: str) -> list:
    """Obras vigentes cuyo nombre canónico (o, si ninguna, un alias) es la
    misma identidad que `nombre`. Nunca fuzzy."""
    vigentes = [o for o in obras if o.estado_vigencia == "ACTIVO" and o.estado not in {"RECHAZADA", "INACTIVA"}]
    por_nombre = [o for o in vigentes if misma_identidad(o.nombre_canonico, nombre)]
    return por_nombre or [o for o in vigentes if any(misma_identidad(a, nombre) for a in o.aliases_documentales)]


_MOTIVO_SIN_CONFIRMACION_PREVIA = {
    "SIN_CONFIRMACION_COMPATIBLE": ("no encontré un destino confirmado por una persona para otra guía del mismo "
                                    "cliente y la misma obra cuyo destino en la guía diga lo mismo"),
    "CONFIRMACIONES_INCOMPATIBLES": "hay más de un destino confirmado posible y no elijo entre ellos",
    "IDENTIDAD_OBJETIVO_INSUFICIENTE": "no pude identificar sin ambigüedad el documento de esa guía",
}

_MOTIVO_NO_REUTILIZABLE = {
    "FALLIDA": "la investigación anterior no se completó, así que no hay propuesta que aplicar",
    "SIN_PROPUESTA": "la investigación anterior no encontró evidencia suficiente para proponer un valor",
    "AMBIGUA": "la investigación anterior encontró más de un valor posible y no elijo entre ellos",
    "CONTRADICCION": "la evidencia encontrada contradice lo que dice la guía",
    "NUMERO_NO_SUSTENTADO": ("las fuentes sólo sustentan la calle y la comuna; no completo el número "
                             "de calle sin evidencia"),
    "NO_SOLICITADA": "la investigación anterior no fue sobre ese dato",
}

# Presentación por campo: etiqueta visible, clave del preview (Desktop la
# rotula), consecuencias operacionales y frase de cierre.
_PRESENTACION_CAMPO = {
    "obra_destino": {
        "etiqueta": "Obra", "clave": "obra_destino",
        "respaldo": "Se usa la obra ya registrada en Atlas; el texto leído en la guía se conserva como respaldo.",
        "consecuencias": ["Se usa la obra ya registrada en Atlas; no se crea una obra nueva.",
                          "El texto leído en la guía se conserva como respaldo.",
                          "Atlas revisará la guía y su viaje."],
        "aplicado": "queda con la obra",
    },
    "despachar_a_crudo": {
        "etiqueta": "Destino", "clave": "destino",
        "respaldo": ("Se registra como destino operacional de la guía, se ubica en el mapa y se recalcula la "
                     "ruta del viaje; el texto leído en la guía se conserva como respaldo."),
        "consecuencias": ["Se registra el destino operacional y se cierra la revisión de destino pendiente.",
                          "Se ubica la dirección en el mapa y se recalcula la ruta del viaje.",
                          "El texto leído en la guía se conserva como respaldo."],
        "aplicado": "queda con el destino",
    },
}


def _campo_presentacion(presentacion: Mapping[str, str]) -> dict:
    return _PRESENTACION_CAMPO[presentacion.get("campo") or "obra_destino"]


def _mensaje_preview(presentacion: Mapping[str, str]) -> str:
    campo = _campo_presentacion(presentacion)
    etiqueta = campo["etiqueta"]
    evidencia = f"Evidencia: {presentacion['evidencia']}\n" if presentacion.get("evidencia") else ""
    return (f"Guía: {presentacion['numero_guia']}\n"
            f"{etiqueta} actual: {presentacion['antes'] or 'sin dato'}\n"
            f"{etiqueta} {'propuesta' if etiqueta == 'Obra' else 'propuesto'}: {presentacion['despues']}\n"
            f"{evidencia}{campo['respaldo']} ¿Confirmas? (sí / no)")


def _preview_publico(presentacion: Mapping[str, str], preview: Mapping[str, object]) -> dict:
    """Preview visible sin IDs, tokens, códigos ni nombres de acciones."""
    campo = _campo_presentacion(presentacion)
    obsoletas = (preview.get("afectados") or {}).get("decisiones_obsoletas") or []
    publico = {
        "entidad": {"numero_guia": presentacion["numero_guia"]},
        "valor_actual": {campo["clave"]: presentacion["antes"]},
        "valor_propuesto": {campo["clave"]: presentacion["despues"]},
        "afectados": {"total_guias": 1,
                      "total_decisiones": max(len(obsoletas), 1 if campo["clave"] == "destino" else 0)},
        "consecuencias": list(campo["consecuencias"]),
    }
    if presentacion.get("evidencia"):
        publico["evidencia"] = presentacion["evidencia"]
    return publico


def _presentacion_catalogo_obra(preview: Mapping[str, object]) -> dict[str, str]:
    """Vista humana de una mutación de obra, sin IDs, tokens ni parámetros."""
    accion = str(preview.get("accion") or "")
    actual = preview.get("valor_actual") or {}
    propuesto = preview.get("valor_propuesto") or {}
    if accion == "OBRA_CORREGIR":
        return {"tipo": "obra_catalogo", "operacion": "CORREGIR",
                "antes": str(actual.get("nombre_canonico") or "sin dato"),
                "despues": str(propuesto.get("nombre_canonico") or "")}
    return {"tipo": "obra_catalogo", "operacion": "REGISTRAR", "antes": "no existe",
            "despues": str(propuesto.get("nombre_obra") or ""),
            "cliente": str(propuesto.get("cliente") or "")}


def _preview_catalogo_obra_publico(presentacion: Mapping[str, str]) -> dict:
    publico = {"entidad": {"tipo": "obra"},
               "valor_actual": {"nombre": presentacion["antes"]},
               "valor_propuesto": {"nombre": presentacion["despues"]},
               "revalidacion": "focal del catálogo de obras y conciliación de bandeja"}
    if presentacion.get("cliente"):
        publico["valor_propuesto"]["cliente"] = presentacion["cliente"]
    return publico


def _mensaje_preview_catalogo_obra(presentacion: Mapping[str, str]) -> str:
    if presentacion["operacion"] == "REGISTRAR":
        return (f"Obra actual: no existe.\nObra propuesta a crear: {presentacion['despues']}\n"
                f"Cliente explícito: {presentacion.get('cliente') or 'sin dato'}.\n"
                "Se creará sólo esta obra observada; no se crearán relaciones, destinos ni clientes. "
                "¿Confirmas? (sí / no)")
    return (f"Obra actual: {presentacion['antes']}\nCambio propuesto: {presentacion['despues']}\n"
            "La equivalencia del nombre actual se conserva como alias; no se alteran cliente ni relaciones. "
            "¿Confirmas? (sí / no)")


def _evidencia_visible(registro: Mapping[str, object]) -> str:
    """Evidencia operacional comprensible: razón + dominios, sin scores ni códigos."""
    razon = str(registro.get("evidencia_relevante") or "").strip().rstrip(".")
    dominios = [str(d) for d in registro.get("dominios") or [] if d]
    partes = [razon] if razon else []
    if dominios:
        partes.append("fuentes: " + ", ".join(dominios))
    return "; ".join(partes) + ("." if partes else "")


# --------------------------------------------------------------- operador


class OperadorB1:
    """Estado conversacional del preview pendiente + puente a la capa."""

    def __init__(self, raiz_atlas: str | Path, *, usuario: str = "JAVIER",
                 proveedor: ProveedorInterpretacionAcciones | None = None,
                 capa: CapaAccionesOperacionales | None = None, reloj=lambda: datetime.now(timezone.utc)):
        if not _ID.fullmatch(str(usuario or "")):
            raise ValueError("usuario inválido")
        self.raiz = Path(raiz_atlas)
        self.usuario = usuario
        self.proveedor = proveedor
        self.reloj = reloj
        self.capa = capa or CapaAccionesOperacionales(self.raiz, reloj=reloj)
        self._actual = self.raiz / "operacion" / "actual"
        self._ruta = self._actual / NOMBRE_ESTADO

    # ------------------------------------------------------------ estado

    def _leer(self) -> dict:
        import json
        try:
            datos = json.loads(self._ruta.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"schema_version": 1, "conversaciones": {}}
        if datos.get("schema_version") != 1:
            raise ValueError("estado conversacional con versión desconocida")
        return datos

    def pendiente(self, conversacion_id: str) -> dict | None:
        return (self._leer().get("conversaciones", {}).get(conversacion_id) or {}).get("pendiente")

    def _fijar(self, estado: dict, conversacion_id: str, clave: str, valor: dict | None) -> None:
        """Fija/borra una sola clave de la conversación sin tocar las demás."""
        conversaciones = estado.setdefault("conversaciones", {})
        conversacion = dict(conversaciones.get(conversacion_id) or {})
        if valor is None:
            conversacion.pop(clave, None)
        else:
            conversacion[clave] = valor
        if conversacion:
            conversaciones[conversacion_id] = conversacion
        else:
            conversaciones.pop(conversacion_id, None)
        escribir_json_atomico(self._ruta, estado)

    def _fijar_pendiente(self, estado: dict, conversacion_id: str, pendiente: dict | None) -> None:
        self._fijar(estado, conversacion_id, "pendiente", pendiente)

    def _olvidar_investigacion(self, estado: dict, conversacion_id: str) -> None:
        if "investigacion" in (estado.get("conversaciones", {}).get(conversacion_id) or {}):
            self._fijar(estado, conversacion_id, "investigacion", None)

    def investigacion_previa(self, conversacion_id: str) -> dict | None:
        return (self._leer().get("conversaciones", {}).get(conversacion_id) or {}).get("investigacion")

    # ------------------------------------------------------------ entrada

    def atender(self, conversacion_id: str, texto: str) -> dict:
        if not _ID.fullmatch(str(conversacion_id or "")):
            return {"estado": "RECHAZADA", "mensaje": "conversación inválida"}
        try:
            with bloqueo_sesion(self._actual, "b1_operador_conversaciones"):
                estado = self._leer()
                if es_confirmacion(texto):
                    self._olvidar_investigacion(estado, conversacion_id)
                    return self._confirmar(estado, conversacion_id)
                if es_cancelacion(texto):
                    self._olvidar_investigacion(estado, conversacion_id)
                    tenia = (estado.get("conversaciones", {}).get(conversacion_id) or {}).get("pendiente")
                    self._fijar_pendiente(estado, conversacion_id, None)
                    return {"estado": "CANCELADA" if tenia else "SIN_PREVIEW_PENDIENTE",
                            "mensaje": "Operación pendiente descartada." if tenia else "No había nada pendiente."}
                return self._instruccion(estado, conversacion_id, texto)
        except SesionOcupadaError:
            return {"estado": "RECHAZADA", "mensaje": "Otra operación de esta conversación está en curso."}

    def _interpretar(self, texto: str) -> Intencion | None:
        intencion = interpretar_determinista(texto)
        if intencion is not None:
            if intencion.accion in {ACCION_INVESTIGAR_REVISION, ACCION_DESDE_INVESTIGACION,
                                    ACCION_DESTINO_CONFIRMADO_PREVIO}:
                return intencion
            return validar_intencion(intencion)
        if self.proveedor is None:
            return None
        from atlas_core.acciones_operacionales import catalogo_acciones
        propuesta = self.proveedor.interpretar(str(texto), catalogo_acciones())
        return None if propuesta is None else intencion_desde_modelo(propuesta)

    def _instruccion(self, estado: dict, conversacion_id: str, texto: str) -> dict:
        try:
            intencion = self._interpretar(texto)
        except ErrorContratoInterpretacion as error:
            self._olvidar_investigacion(estado, conversacion_id)
            return {"estado": "RECHAZADA", "codigo": "CONTRATO_INTERPRETACION", "mensaje": str(error)}
        if intencion is None or intencion.accion not in {ACCION_INVESTIGAR_REVISION, ACCION_DESDE_INVESTIGACION}:
            # Sólo la investigación INMEDIATAMENTE anterior es reutilizable:
            # cualquier otra instrucción la deja sin efecto.
            self._olvidar_investigacion(estado, conversacion_id)
        if intencion is None:
            return {"estado": "NO_INTERPRETADA", "mensaje": (
                "No reconocí una instrucción operacional. Puedo: asociar vehículo a chofer, activar/inactivar un "
                "chofer, corregir un campo o la obra de una guía, o consultar choferes, obras y decisiones.")}
        if intencion.accion == ACCION_INVESTIGAR_REVISION:
            return self._investigar_revision(intencion, estado, conversacion_id)
        if intencion.accion == ACCION_DESDE_INVESTIGACION:
            return self._desde_investigacion(estado, conversacion_id, intencion, texto)
        if intencion.accion == ACCION_DESTINO_CONFIRMADO_PREVIO:
            return self._destino_confirmado_previo(estado, conversacion_id, intencion, texto)
        definicion = ACCIONES[intencion.accion]
        if definicion.riesgo != LECTURA:
            # Toda instrucción operacional nueva invalida el pendiente anterior.
            self._fijar_pendiente(estado, conversacion_id, None)
        parametros = dict(intencion.parametros)
        if "chofer" in intencion.menciones:
            resolucion = resolver_chofer(self.capa._ctx.choferes(), intencion.menciones["chofer"],
                                         incluir_inactivos=intencion.accion in {"CHOFER_CAMBIAR_ESTADO", "CHOFER_CONSULTAR"})
            if resolucion["estado"] != "RESUELTO":
                # Nunca una acción ejecutable ambigua ni claves internas: sólo
                # nombre (y RUT real, si lo hay) para que el humano precise.
                candidatos = [{"nombre": c["nombre"], "activo": c["activo"], **({"rut": c["rut"]} if c["rut"] else {})}
                              for c in resolucion.get("candidatos") or []]
                mensaje = ("¿A cuál chofer te refieres? " + "; ".join(
                               c["nombre"] + (f" (RUT {c['rut']})" if c.get("rut") else "") for c in candidatos)
                           + ". Repite la orden con el nombre completo o el RUT."
                           if candidatos else f"No encontré un chofer que coincida con «{intencion.menciones['chofer']}».")
                return {"estado": "ACLARACION_REQUERIDA", "accion": intencion.accion, "candidatos": candidatos,
                        "mensaje": mensaje}
            parametros["chofer"] = resolucion["chofer"]
        if "guia_destino" in intencion.menciones:
            guia = intencion.menciones["guia_destino"]
            decision_id, aclaracion = resolver_decision_destino(self.capa._ctx.decisiones(), guia)
            if aclaracion:
                return {"estado": "ACLARACION_REQUERIDA", "accion": intencion.accion, "candidatos": [],
                        "mensaje": aclaracion}
            parametros["decision_id"] = decision_id
        if "obra" in intencion.menciones:
            mencion = intencion.menciones["obra"]
            resolucion = resolver_obra(self.capa._ctx.catalogo_obras().listar_obras(), mencion)
            if resolucion["estado"] != "RESUELTO":
                candidatos = resolucion["candidatos"]
                listado = "; ".join(str(c["nombre"]) for c in candidatos)
                mensaje = (f"«{mencion}» coincide con más de una obra: {listado}. Indica cuál."
                           if resolucion["estado"] == "AMBIGUO" else
                           f"No encontré una obra existente llamada «{mencion}»"
                           + (f". ¿Te refieres a alguna de estas? {listado}" if candidatos else "")
                           + ". No creo obras nuevas desde aquí; repite la orden con el nombre exacto.")
                candidatos_publicos = ([{"nombre": c["nombre"]} for c in candidatos]
                                       if intencion.accion == "OBRA_CORREGIR" else candidatos)
                return {"estado": "ACLARACION_REQUERIDA", "accion": intencion.accion,
                        "candidatos": candidatos_publicos, "mensaje": mensaje}
            parametros["obra_id"] = resolucion["obra_id"]
            if intencion.accion == "OBRA_CORREGIR":
                # La corrección conserva la equivalencia canónica existente.
                parametros["aliases"] = [resolucion["nombre"]]
        if intencion.accion == "OBRA_REGISTRAR" and "cliente" not in intencion.menciones:
            return {"estado": "ACLARACION_REQUERIDA", "accion": intencion.accion, "candidatos": [],
                    "mensaje": "Para registrar una obra indica el cliente existente de forma explícita; no lo infiero."}
        if "cliente" in intencion.menciones:
            from atlas_core.catalogo_clientes import CatalogoClientes
            mencion = intencion.menciones["cliente"]
            resolucion = resolver_cliente(CatalogoClientes(self.capa._ctx.archivos["clientes"]).listar(), mencion)
            if resolucion["estado"] != "RESUELTO":
                candidatos = resolucion.get("candidatos") or []
                listado = "; ".join(str(c["nombre"]) for c in candidatos)
                if resolucion["estado"] == "AMBIGUO":
                    mensaje = f"Cliente ambiguo: {listado}. Indica cuál."
                else:
                    mensaje = (f"No encontré un cliente existente llamado {mencion!r}"
                               + (f". ¿Te refieres a alguno de estos? {listado}" if candidatos else "")
                               + ". No crearé un cliente desde B1.")
                candidatos_publicos = ([{"nombre": c["nombre"]} for c in candidatos]
                                       if intencion.accion == "OBRA_CORREGIR" else candidatos)
                return {"estado": "ACLARACION_REQUERIDA", "accion": intencion.accion, "candidatos": candidatos_publicos,
                        "mensaje": mensaje}
            parametros["cliente_id"] = resolucion["cliente_id"]
        if "destino" in intencion.menciones:
            mencion = intencion.menciones["destino"]
            resolucion = resolver_destino(self.capa._ctx.catalogo_destinos().listar(), mencion)
            if resolucion["estado"] != "RESUELTO":
                candidatos = resolucion["candidatos"]
                listado = "; ".join(f"{c['direccion']}{' (' + c['comuna'] + ')' if c['comuna'] else ''}"
                                    for c in candidatos)
                mensaje = (f"«{mencion}» coincide con más de un destino: {listado}. Indica cuál."
                           if resolucion["estado"] == "AMBIGUO" else
                           f"No encontré un destino existente «{mencion}»"
                           + (f". ¿Te refieres a alguno de estos? {listado}" if candidatos else "")
                           + ". No creo destinos desde aquí; repite la orden con la dirección exacta.")
                return {"estado": "ACLARACION_REQUERIDA", "accion": intencion.accion, "candidatos": candidatos,
                        "mensaje": mensaje}
            parametros["destino_id"] = resolucion["destino_id"]
        return self._previsualizar(estado, conversacion_id, intencion, parametros, texto)

    def _investigar_revision(self, intencion: Intencion, estado: dict | None = None,
                             conversacion_id: str = "") -> dict:
        """Investiga en modo lectura: no crea preview ni altera el pendiente.
        Deja en la conversación sólo su resultado estructurado (reutilizable)."""
        numero_guia = str(intencion.parametros.get("numero_guia") or "")
        campos = tuple(intencion.parametros.get("campos") or ())
        if not numero_guia:
            return {"estado": "ACLARACION_REQUERIDA", "accion": ACCION_INVESTIGAR_REVISION,
                    "mensaje": "Indica el número de guía que quieres investigar."}

        def registrar(resultado: Mapping | None) -> None:
            if estado is not None and conversacion_id:
                creado_en = self.reloj().isoformat()
                self._fijar(estado, conversacion_id, "investigacion", {
                    "numero_guia": numero_guia, "creado_en": creado_en,
                    "obra": registro_investigacion_obra(numero_guia, campos, resultado, creado_en),
                    "destino": registro_investigacion_destino(numero_guia, campos, resultado, creado_en)})

        from atlas_core.atlas_ia.investigacion_revision import investigar_revision
        try:
            resultado = investigar_revision(numero_guia, raiz_atlas=self.raiz,
                                             campos_solicitados=campos,
                                             permitir_ocr_nuevo=False)
        except (OSError, ValueError) as error:
            registrar(None)
            return {"estado": "INVESTIGACION_NO_DISPONIBLE", "accion": ACCION_INVESTIGAR_REVISION,
                    "mensaje": f"No pude investigar la guía {numero_guia}: {error}"}
        registrar(resultado)
        etiquetas = {"obra_destino": "obra", "despachar_a_crudo": "dirección de destino"}
        # "No se pudo buscar" no es "no hay evidencia": se informa aparte y en
        # lenguaje operacional (el detalle técnico queda sólo en el expediente).
        sin_busqueda = (resultado.get("BUSQUEDA_EXTERNA") or {}).get("estado") in {"FALLIDA", "NO_DISPONIBLE"}
        busqueda_externa = "NO_DISPONIBLE" if sin_busqueda else "DISPONIBLE"
        propuestas: dict[str, dict[str, str]] = {}
        for expediente in resultado.get("expedientes") or []:
            campo = str(expediente.get("CAMPO") or "")
            if campo not in campos or campo in propuestas:
                continue
            preview = expediente.get("PREVIEW_OPERACIONAL") or {}
            evaluacion = expediente.get("EVALUACION_CANDIDATOS_EXTERNOS") or {}
            propuesta = str(preview.get("valor_propuesto") or expediente.get("PROPUESTA") or "").strip()
            evidencia = str(preview.get("evidencia_relevante") or evaluacion.get("razon")
                            or expediente.get("RAZON_ABSTENCION") or "Evidencia insuficiente para proponer.")
            if sin_busqueda and not propuesta:
                evidencia = "No se pudieron consultar fuentes públicas: la búsqueda externa no está disponible."
            propuestas[etiquetas[campo]] = {
                "valor_actual": str(preview.get("valor_actual") or
                                     (expediente.get("HECHOS_DOCUMENTALES") or {}).get("valor_extraido") or ""),
                "valor_propuesto": propuesta or "Sin propuesta suficiente",
                "evidencia_relevante": evidencia,
                "consecuencia_operacional": str(preview.get("consecuencia_operacional") or
                    ("No se aplicará ningún cambio sin confirmación humana." if propuesta else
                     "Atlas se abstiene: no hay evidencia suficiente para cambiar el dato.")),
            }
        if sin_busqueda and not any(p["valor_propuesto"] != "Sin propuesta suficiente" for p in propuestas.values()):
            return {"estado": "RESULTADO_INVESTIGACION", "accion": ACCION_INVESTIGAR_REVISION,
                    "propuestas": propuestas, "busqueda_externa": busqueda_externa, "mensaje": (
                        f"Investigación de guía {numero_guia}, sin cambios: no pude consultar fuentes públicas "
                        "porque la búsqueda externa no está disponible en este momento. Intenta de nuevo más tarde.")}
        if not propuestas:
            return {"estado": "RESULTADO_INVESTIGACION", "accion": ACCION_INVESTIGAR_REVISION,
                    "propuestas": {}, "busqueda_externa": busqueda_externa, "mensaje": (
                        f"Investigación de guía {numero_guia}, sin cambios: no encontré evidencia reutilizable "
                        "para los datos solicitados.")}
        resumen = "; ".join(
            f"{etiqueta}: actual {dato['valor_actual']!r}; propuesta {dato['valor_propuesto']!r}."
            for etiqueta, dato in propuestas.items())
        return {"estado": "RESULTADO_INVESTIGACION", "accion": ACCION_INVESTIGAR_REVISION,
                "propuestas": propuestas, "busqueda_externa": busqueda_externa,
                "mensaje": f"Investigación de guía {numero_guia}, sin cambios: {resumen}"}

    def _desde_investigacion(self, estado: dict, conversacion_id: str, intencion: Intencion,
                             texto: str) -> dict:
        """Convierte la propuesta ESTRUCTURADA (obra o destino) de la
        investigación anterior de esta conversación en un preview del
        mecanismo controlado existente. Nunca relee texto libre, nunca crea
        entidades y nunca aplica sin confirmación."""
        self._fijar_pendiente(estado, conversacion_id, None)
        campo = str(intencion.parametros.get("campo") or "")

        def rechazo(motivo: str) -> dict:
            return {"estado": "RECHAZADA", "accion": ACCION_DESDE_INVESTIGACION, "mensaje": motivo}

        if not campo:
            return rechazo("Indica si quieres corregir la obra o el destino; no aplico las dos cosas a la vez.")
        dato = "obra" if campo == "obra_destino" else "destino"
        previa = (estado.get("conversaciones", {}).get(conversacion_id) or {}).get("investigacion")
        try:
            vigente = bool(previa) and (
                self.reloj() - datetime.fromisoformat(previa["creado_en"]) <= VIGENCIA_INVESTIGACION)
        except (KeyError, TypeError, ValueError):
            vigente = False
        if not vigente:
            return rechazo(f"No tengo una investigación reciente de {dato} en esta conversación para reutilizar. "
                           f"Pide primero: «Investiga {'la obra' if dato == 'obra' else 'el destino'} de la guía N».")
        guia = str(intencion.parametros.get("numero_guia") or "") or previa["numero_guia"]
        if guia != previa["numero_guia"]:
            return rechazo(f"La investigación anterior fue de la guía {previa['numero_guia']}, no de la guía {guia}; "
                           "no reutilizo una propuesta de otra guía.")
        registro = previa.get(dato) or {}
        if registro.get("estado") != "PROPUESTA":
            motivo = _MOTIVO_NO_REUTILIZABLE.get(registro.get("estado"), _MOTIVO_NO_REUTILIZABLE["FALLIDA"])
            return rechazo(f"No hice cambios en la guía {guia}: {motivo}.")
        if dato == "obra":
            return self._obra_desde_registro(estado, conversacion_id, guia, registro, texto, rechazo)
        return self._destino_desde_registro(estado, conversacion_id, guia, registro, texto, rechazo)

    def _destino_desde_registro(self, estado: dict, conversacion_id: str, guia: str, previa: dict,
                                texto: str, rechazo) -> dict:
        """Destino: misma tarjeta y misma acción que Revisión (DESTINO_NO_RESUELTO
        -> REGISTRAR_DIRECCION vía DECISION_APLICAR); geocodifica, recalcula la
        ruta y cierra la revisión sólo tras confirmación."""
        decision_id, aclaracion = resolver_decision_destino(self.capa._ctx.decisiones(), guia)
        if aclaracion:
            return rechazo(f"No hice cambios: {aclaracion}")
        referencia = (f"{str(texto)[:120]} | Investigación B1 previa, guía {guia}: documental "
                      f"{previa.get('valor_documental')!r}; propuesta {previa['propuesta_publicada']!r}; nivel "
                      f"{previa.get('nivel_evidencia')}; evidencia: {previa.get('evidencia_relevante')}; fuentes: "
                      f"{', '.join(previa.get('fuentes') or []) or 'sin URL'}")[:500]
        return self._preview_destino(
            estado, conversacion_id, guia, decision_id, rechazo, referencia=referencia,
            direccion=f"{previa['calle']} {previa['numero']}".upper(), comuna=previa["comuna"].upper(),
            antes=str(previa.get("valor_documental") or ""), evidencia=_evidencia_visible(previa),
            accion_origen=ACCION_DESDE_INVESTIGACION)

    def _destino_confirmado_previo(self, estado: dict, conversacion_id: str, intencion: Intencion,
                                   texto: str) -> dict:
        """Propone el destino de la guía con la dirección que un HUMANO ya
        confirmó para otra guía del mismo cliente, obra y destino documental
        (`destino_confirmacion_previa`). Sin búsqueda externa; nunca inventa
        número; aplica sólo tras preview + confirmación."""
        import csv
        import json
        from atlas_core.destino_confirmacion_previa import proponer_destino_por_confirmacion_humana
        from atlas_core.geografia.cl import RUTA_DATASET
        self._fijar_pendiente(estado, conversacion_id, None)
        guia = str(intencion.parametros.get("numero_guia") or "")

        def rechazo(motivo: str) -> dict:
            return {"estado": "RECHAZADA", "accion": ACCION_DESTINO_CONFIRMADO_PREVIO, "mensaje": motivo}

        decisiones = self.capa._ctx.decisiones()
        decision_id, aclaracion = resolver_decision_destino(decisiones, guia)
        if aclaracion:
            return rechazo(f"No hice cambios: {aclaracion}")
        decision = next(d for d in decisiones if str(d.get("decision_id")) == decision_id)
        archivos = self.capa._ctx.archivos
        with archivos["dataset"].open(encoding="utf-8-sig", newline="") as flujo:
            filas = list(csv.DictReader(flujo, delimiter=";"))
        try:
            aplicaciones = json.loads(archivos["ledger_decisiones"].read_text(encoding="utf-8")).get("aplicaciones", [])
        except (OSError, ValueError):
            aplicaciones = []
        try:
            comunas = [str(c["nombre_comuna"]) for c in json.loads(RUTA_DATASET.read_text(encoding="utf-8"))]
        except (OSError, ValueError, KeyError):
            comunas = []
        resultado = proponer_destino_por_confirmacion_humana(
            decision=decision, filas=filas, aplicaciones=aplicaciones,
            obras=self.capa._ctx.catalogo_obras().listar_obras(), comunas=comunas)
        if resultado["estado"] != "PROPUESTA":
            return rechazo(f"No hice cambios en la guía {guia}: "
                           + _MOTIVO_SIN_CONFIRMACION_PREVIA.get(resultado["motivo"],
                                                                 _MOTIVO_SIN_CONFIRMACION_PREVIA["SIN_CONFIRMACION_COMPATIBLE"])
                           + ".")
        evidencia = resultado["evidencias"][-1]
        documental = str(decision.get("valor_documental") or "")
        referencia = (f"DESTINO_DESDE_CONFIRMACION_HUMANA_PREVIA: guia {evidencia['numero_guia']} "
                      f"({evidencia['archivo']}) confirmada por {evidencia['actor']} el {evidencia['fecha']}; "
                      f"documental previo {evidencia['valor_documental_anterior']!r} -> "
                      f"{evidencia['direccion_manual']!r}, {evidencia['comuna_manual']}; documental objetivo "
                      f"{documental!r}; sin numero de calle inventado | {str(texto)[:100]}")[:500]
        fecha = evidencia["fecha"][:10]
        fecha_visible = "-".join(reversed(fecha.split("-"))) if fecha else "una fecha anterior"
        evidencia_visible = (f"Destino confirmado en Revisión el {fecha_visible} para la guía "
                             f"{evidencia['numero_guia']}, del mismo cliente y la misma obra, cuya guía decía el "
                             "mismo destino." + ("" if resultado["numero"] else
                                                 " Sin número de calle: ninguna evidencia lo trae."))
        return self._preview_destino(
            estado, conversacion_id, guia, decision_id, rechazo, referencia=referencia,
            direccion=resultado["direccion"], comuna=resultado["comuna"], antes=documental,
            evidencia=evidencia_visible, accion_origen=ACCION_DESTINO_CONFIRMADO_PREVIO)

    def _preview_destino(self, estado: dict, conversacion_id: str, guia: str, decision_id: str, rechazo, *,
                         referencia: str, direccion: str, comuna: str, antes: str, evidencia: str,
                         accion_origen: str) -> dict:
        """Preview de REGISTRAR_DIRECCION (DECISION_APLICAR) con presentación limpia."""
        parametros = {"decision_id": decision_id, "accion_decision": "REGISTRAR_DIRECCION",
                      "direccion_manual": direccion, "comuna_manual": comuna}
        preview = self.capa.previsualizar("DECISION_APLICAR", parametros, actor=ACTOR_B1, origen=ORIGEN_B1,
                                          referencia=referencia)
        if preview.get("estado") == "SIN_CAMBIOS":
            return {"estado": "SIN_CAMBIOS", "accion": accion_origen,
                    "mensaje": f"La guía {guia} ya tiene ese destino; no hay nada que confirmar."}
        if preview.get("estado") != "PREVIEW" or preview.get("riesgo") == SENSIBLE:
            return rechazo(f"No hice cambios en la guía {guia}: la corrección no se puede preparar ahora"
                           + (f" ({preview['mensaje']})." if preview.get("mensaje") else "."))
        presentacion = {"campo": "despachar_a_crudo", "numero_guia": guia,
                        "antes": antes or str((preview.get("valor_actual") or {}).get("valor_documental") or ""),
                        "despues": f"{direccion}, {comuna}", "evidencia": evidencia}
        self._fijar_pendiente(estado, conversacion_id, {
            "token": preview["token"], "accion": "DECISION_APLICAR", "parametros": parametros,
            "referencia": referencia, "creado_en": self.reloj().isoformat(), "presentacion": presentacion})
        return {"estado": "PREVIEW_PENDIENTE", "accion": "DECISION_APLICAR",
                "preview": _preview_publico(presentacion, preview),
                "mensaje": _mensaje_preview(presentacion)}

    def _obra_desde_registro(self, estado: dict, conversacion_id: str, guia: str, previa: dict,
                             texto: str, rechazo) -> dict:
        propuesta = previa["propuesta_publicada"]
        coincidencias = _obra_por_identidad(self.capa._ctx.catalogo_obras().listar_obras(), propuesta)
        if not coincidencias:
            return rechazo(f"No hice cambios en la guía {guia}: la obra propuesta «{nombre_visible(propuesta)}» "
                           "no está registrada en Atlas y no creo obras desde aquí.")
        if len(coincidencias) > 1:
            return rechazo(f"No hice cambios en la guía {guia}: «{nombre_visible(propuesta)}» coincide con más de "
                           "una obra registrada y no elijo entre ellas.")
        obra = coincidencias[0]
        referencia = (f"{str(texto)[:120]} | Investigación B1 previa, guía {guia}: documental "
                      f"{previa.get('valor_documental')!r}; propuesta publicada {propuesta!r}; nivel "
                      f"{previa.get('nivel_evidencia')}; evidencia: {previa.get('evidencia_relevante')}; fuentes: "
                      f"{', '.join(previa.get('fuentes') or []) or 'sin URL'}")[:500]
        # La evidencia viaja también como parámetro: queda en el ledger junto al documental.
        parametros = {"numero_guia": guia, "obra_id": obra.obra_id, "referencia": referencia}
        preview = self.capa.previsualizar("DOCUMENTO_ASIGNAR_OBRA", parametros, actor=ACTOR_B1, origen=ORIGEN_B1,
                                          referencia=referencia)
        if preview.get("estado") == "SIN_CAMBIOS":
            return {"estado": "SIN_CAMBIOS", "accion": ACCION_DESDE_INVESTIGACION,
                    "mensaje": f"La guía {guia} ya tiene la obra {nombre_visible(obra.nombre_canonico)}; "
                               "no hay nada que confirmar."}
        if preview.get("estado") != "PREVIEW" or preview.get("riesgo") == SENSIBLE:
            return rechazo(f"No hice cambios en la guía {guia}: la corrección no se puede preparar ahora"
                           + (f" ({preview['mensaje']})." if preview.get("mensaje") else "."))
        presentacion = {"campo": "obra_destino", "numero_guia": guia,
                        "antes": str((preview.get("valor_actual") or {}).get("obra_destino") or ""),
                        "despues": nombre_visible(obra.nombre_canonico)}
        self._fijar_pendiente(estado, conversacion_id, {
            "token": preview["token"], "accion": "DOCUMENTO_ASIGNAR_OBRA", "parametros": parametros,
            "referencia": referencia, "creado_en": self.reloj().isoformat(), "presentacion": presentacion})
        return {"estado": "PREVIEW_PENDIENTE", "accion": "DOCUMENTO_ASIGNAR_OBRA",
                "preview": _preview_publico(presentacion, preview),
                "mensaje": _mensaje_preview(presentacion)}

    def _previsualizar(self, estado: dict, conversacion_id: str, intencion: Intencion, parametros: dict,
                       texto: str) -> dict:
        preview = self.capa.previsualizar(intencion.accion, parametros, actor=ACTOR_B1, origen=ORIGEN_B1,
                                          referencia=str(texto)[:500])
        if preview.get("estado") == "RECHAZADA":
            return {"estado": "RECHAZADA", "accion": intencion.accion, "codigo": preview.get("codigo"),
                    "mensaje": preview.get("mensaje")}
        if preview.get("estado") == "RESULTADO":
            return {"estado": "RESULTADO_LECTURA", "accion": intencion.accion,
                    "resultado": _resultado_lectura_publico(intencion.accion, preview["resultado"]),
                    "mensaje": _describir_lectura(intencion.accion, preview["resultado"])}
        if (intencion.tipo_vehiculo_declarado
                and (preview.get("valor_propuesto") or {}).get("tipo") not in (None, intencion.tipo_vehiculo_declarado)):
            return {"estado": "ACLARACION_REQUERIDA", "accion": intencion.accion, "mensaje": (
                f"Dijiste {intencion.tipo_vehiculo_declarado}, pero {parametros.get('patente')} es "
                f"{preview['valor_propuesto']['tipo']} en el catálogo. Revisa la patente.")}
        publico = {k: v for k, v in preview.items() if k != "token"}
        if intencion.accion in {"OBRA_REGISTRAR", "OBRA_CORREGIR"} and preview.get("estado") != "SIN_CAMBIOS":
            presentacion = _presentacion_catalogo_obra(preview)
            self._fijar_pendiente(estado, conversacion_id, {
                "token": preview["token"], "accion": intencion.accion, "parametros": parametros,
                "referencia": str(texto)[:500], "creado_en": self.reloj().isoformat(),
                "presentacion": presentacion})
            return {"estado": "PREVIEW_PENDIENTE", "accion": intencion.accion,
                    "preview": _preview_catalogo_obra_publico(presentacion),
                    "mensaje": _mensaje_preview_catalogo_obra(presentacion)}
        if intencion.accion == "CHOFER_CAMBIAR_ESTADO":
            presentacion = _presentacion_chofer_estado(preview)
            visible = _preview_chofer_estado_publico(presentacion)
            if preview.get("estado") == "SIN_CAMBIOS":
                return {"estado": "SIN_CAMBIOS", "accion": intencion.accion, "preview": visible,
                        "mensaje": f"El chofer {presentacion['chofer']} ya está {presentacion['antes']}; "
                                   "no hay nada que confirmar."}
            self._fijar_pendiente(estado, conversacion_id, {
                "token": preview["token"], "accion": intencion.accion, "parametros": parametros,
                "referencia": str(texto)[:500], "creado_en": self.reloj().isoformat(),
                "presentacion": presentacion})
            return {"estado": "PREVIEW_PENDIENTE", "accion": intencion.accion, "preview": visible,
                    "mensaje": _mensaje_chofer_estado(presentacion) + " ¿Confirmas? (sí / no)"}
        if preview.get("estado") == "SIN_CAMBIOS":
            mensaje = "Eso ya está así; no hay nada que confirmar."
            if intencion.accion == "VIAJE_AGRUPAR_GUIAS":
                unico = (preview.get("valor_propuesto") or {}).get("viaje_unico") or {}
                mensaje = (f"Las guías {', '.join((preview.get('entidad') or {}).get('guias') or [])} ya pertenecen "
                           f"al mismo viaje (transporte principal {unico.get('numero_transporte_principal')}); "
                           "no hay nada que confirmar.")
            return {"estado": "SIN_CAMBIOS", "accion": intencion.accion, "preview": publico, "mensaje": mensaje}
        if preview.get("riesgo") == SENSIBLE:
            return {"estado": "REQUIERE_AUTORIZACION_SENSIBLE", "accion": intencion.accion, "preview": publico,
                    "mensaje": ("Esta operación es SENSIBLE (" + _describir_preview(preview) + ") y requiere "
                                "autorización sensible explícita de un humano; B1 no la ejecuta como operación normal.")}
        self._fijar_pendiente(estado, conversacion_id, {
            "token": preview["token"], "accion": intencion.accion, "parametros": parametros,
            "referencia": str(texto)[:500], "creado_en": self.reloj().isoformat()})
        return {"estado": "PREVIEW_PENDIENTE", "accion": intencion.accion, "preview": publico,
                "mensaje": _describir_preview(preview) + " ¿Confirmas? (sí / no)"}

    def _confirmar(self, estado: dict, conversacion_id: str) -> dict:
        pendiente = (estado.get("conversaciones", {}).get(conversacion_id) or {}).get("pendiente")
        if not pendiente:
            return {"estado": "SIN_PREVIEW_PENDIENTE", "mensaje": "No hay ninguna operación pendiente de confirmar."}
        resultado = self.capa.ejecutar(pendiente["token"], actor=ACTOR_B1, origen=ORIGEN_B1,
                                       confirmado_por=self.usuario, accion_esperada=pendiente["accion"])
        estado_capa = resultado.get("estado")
        presentacion = pendiente.get("presentacion")
        if estado_capa == "APLICADA":
            self._fijar_pendiente(estado, conversacion_id, None)
            if presentacion:
                if presentacion.get("tipo") == "chofer_estado":
                    reconciliada = bool((resultado.get("reconciliacion") or {}).get("ejecutado"))
                    return {"estado": "EJECUTADA", "accion": pendiente["accion"],
                            "resultado": _resultado_chofer_estado_publico(presentacion, reconciliada=reconciliada),
                            "mensaje": f"Listo: el chofer {presentacion['chofer']} quedó {presentacion['despues']}."
                                       + (" Bandeja reconciliada." if reconciliada else "")}
                if presentacion.get("tipo") == "obra_catalogo":
                    resultado_visible = {"estado": "APLICADA", "obra": {"nombre": presentacion["despues"]},
                                         "revalidacion": "focal del catálogo y conciliación ejecutadas"}
                    verbo = "creada" if presentacion["operacion"] == "REGISTRAR" else "corregida"
                    return {"estado": "EJECUTADA", "accion": pendiente["accion"], "resultado": resultado_visible,
                            "mensaje": f"Obra {verbo}: {presentacion['despues']}."}
                campo = _campo_presentacion(presentacion)
                visible = {**resultado, "antes": {campo["clave"]: presentacion["antes"]},
                           "despues": {campo["clave"]: presentacion["despues"]}}
                return {"estado": "EJECUTADA", "accion": pendiente["accion"], "resultado": visible,
                        "mensaje": f"Aplicado: la guía {presentacion['numero_guia']} {campo['aplicado']} "
                                   f"{presentacion['despues']}."}
            return {"estado": "EJECUTADA", "accion": pendiente["accion"], "resultado": resultado,
                    "mensaje": _describir_resultado(resultado)}
        if estado_capa == "PREVIEW_OBSOLETO" or resultado.get("codigo") in {"PREVIEW_EXPIRADO", "TOKEN_DESCONOCIDO"}:
            nuevo = resultado.get("preview_nuevo") or self.capa.previsualizar(
                pendiente["accion"], pendiente["parametros"], actor=ACTOR_B1, origen=ORIGEN_B1,
                referencia=pendiente.get("referencia", ""))
            motivo = "cambió la información" if estado_capa == "PREVIEW_OBSOLETO" else "la propuesta expiró"
            if nuevo.get("estado") != "PREVIEW":
                self._fijar_pendiente(estado, conversacion_id, None)
                return {"estado": "PREVIEW_RENOVADO", "accion": pendiente["accion"], "ejecutado": False,
                        "mensaje": f"No ejecuté nada: {motivo} y ya no hay cambio que confirmar "
                                   f"({nuevo.get('estado')}: {nuevo.get('mensaje', 'sin cambios')})."}
            if presentacion:
                if presentacion.get("tipo") == "chofer_estado":
                    presentacion = _presentacion_chofer_estado(nuevo)
                    self._fijar_pendiente(estado, conversacion_id, {**pendiente, "token": nuevo["token"],
                                                                   "creado_en": self.reloj().isoformat(),
                                                                   "presentacion": presentacion})
                    return {"estado": "PREVIEW_RENOVADO", "accion": pendiente["accion"], "ejecutado": False,
                            "preview": _preview_chofer_estado_publico(presentacion),
                            "mensaje": f"No ejecuté nada: {motivo}. " + _mensaje_chofer_estado(presentacion)
                                       + " ¿Confirmas? (sí / no)"}
                if presentacion.get("tipo") == "obra_catalogo":
                    presentacion = _presentacion_catalogo_obra(nuevo)
                    self._fijar_pendiente(estado, conversacion_id, {**pendiente, "token": nuevo["token"],
                                                                   "creado_en": self.reloj().isoformat(),
                                                                   "presentacion": presentacion})
                    return {"estado": "PREVIEW_RENOVADO", "accion": pendiente["accion"], "ejecutado": False,
                            "preview": _preview_catalogo_obra_publico(presentacion),
                            "mensaje": f"No ejecuté nada: {motivo}. " + _mensaje_preview_catalogo_obra(presentacion)}
                if (presentacion.get("campo") or "obra_destino") == "obra_destino":
                    presentacion = {**presentacion,
                                    "antes": str((nuevo.get("valor_actual") or {}).get("obra_destino") or "")}
                self._fijar_pendiente(estado, conversacion_id, {**pendiente, "token": nuevo["token"],
                                                               "creado_en": self.reloj().isoformat(),
                                                               "presentacion": presentacion})
                return {"estado": "PREVIEW_RENOVADO", "accion": pendiente["accion"], "ejecutado": False,
                        "preview": _preview_publico(presentacion, nuevo),
                        "mensaje": f"No ejecuté nada: {motivo}. " + _mensaje_preview(presentacion)}
            self._fijar_pendiente(estado, conversacion_id, {**pendiente, "token": nuevo["token"],
                                                           "creado_en": self.reloj().isoformat()})
            return {"estado": "PREVIEW_RENOVADO", "accion": pendiente["accion"], "ejecutado": False,
                    "preview": {k: v for k, v in nuevo.items() if k != "token"},
                    "mensaje": f"No ejecuté nada: {motivo}. Propuesta vigente: {_describir_preview(nuevo)} "
                               "¿Confirmas? (sí / no)"}
        self._fijar_pendiente(estado, conversacion_id, None)
        if estado_capa == "SIN_CAMBIOS":
            return {"estado": "SIN_CAMBIOS", "accion": pendiente["accion"], "mensaje": "Ya estaba aplicado."}
        return {"estado": "RECHAZADA" if estado_capa == "RECHAZADA" else "FALLIDA", "accion": pendiente["accion"],
                "codigo": resultado.get("codigo"), "mensaje": resultado.get("mensaje")}
