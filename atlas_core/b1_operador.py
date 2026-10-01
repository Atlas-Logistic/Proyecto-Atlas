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
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Protocol

from atlas_core.acciones_operacionales import (
    ACCIONES, DESTRUCTIVA, LECTURA, ORIGEN_B1, SENSIBLE, CapaAccionesOperacionales, _esquema,
)
from atlas_core.almacenamiento_portable import SesionOcupadaError, bloqueo_sesion, escribir_json_atomico

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
_LECTURA_CHOFERES = re.compile(r"\b(?:CHOFERES|CONDUCTORES)\b.*\b(?:IN)?ACTIV[OA]S?\b"
                               r"|\b(?:IN)?ACTIV[OA]S?\b.*\b(?:CHOFERES|CONDUCTORES)\b")
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
ACCION_INVESTIGAR_REVISION = "INVESTIGAR_REVISION"
_GUIA_INVESTIGACION = re.compile(r"\bGUIA\s+(?:N[°O]?\s*)?(?P<guia>\d{3,12})\b")
_VERBO_INVESTIGAR = re.compile(r"\b(?:INVESTIGA(?:R)?|BUSCA(?:R)?|AVERIGUA(?:R)?)\b")


def _intencion_investigar_revision(plano: str) -> Intencion | None:
    """Reconoce investigación consultiva; nunca es una acción del catálogo."""
    pide_nombre = bool(re.search(r"\bNOMBRE\s+COMPLETO\b.*\bOBRA\b|\bOBRA\b.*\bNOMBRE\s+COMPLETO\b", plano))
    pide_direccion = bool(re.search(r"\bDIRECCION\s+COMPLETA\b|\bDESTINO\b", plano))
    guia = _GUIA_INVESTIGACION.search(plano)
    investigacion = bool(_VERBO_INVESTIGAR.search(plano)) or pide_nombre or pide_direccion
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
        if _LECTURA_CHOFERES.search(plano):
            estado = "INACTIVO" if re.search(r"\bINACTIV", plano) else "ACTIVO"
            return Intencion("CHOFER_CONSULTAR", {"estado": estado})
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
                         "destino": "destino_id"}
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
        texto = f"Dejar al chofer {entidad.get('nombre')} ({entidad.get('id')}) como {estado}."
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


def _describir_lectura(accion: str, resultado: Mapping[str, object]) -> str:
    if accion == "CHOFER_CONSULTAR":
        choferes = resultado.get("choferes") or []
        if not choferes:
            return "No hay choferes con ese estado."
        return f"{len(choferes)} chofer(es): " + "; ".join(
            f"{c['nombre']} ({c['rut'] or c['chofer_id']}, {'activo' if c['activo'] else 'inactivo'})" for c in choferes)
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

    def _fijar_pendiente(self, estado: dict, conversacion_id: str, pendiente: dict | None) -> None:
        conversaciones = estado.setdefault("conversaciones", {})
        if pendiente is None:
            conversaciones.pop(conversacion_id, None)
        else:
            conversaciones[conversacion_id] = {"pendiente": pendiente}
        escribir_json_atomico(self._ruta, estado)

    # ------------------------------------------------------------ entrada

    def atender(self, conversacion_id: str, texto: str) -> dict:
        if not _ID.fullmatch(str(conversacion_id or "")):
            return {"estado": "RECHAZADA", "mensaje": "conversación inválida"}
        try:
            with bloqueo_sesion(self._actual, "b1_operador_conversaciones"):
                estado = self._leer()
                if es_confirmacion(texto):
                    return self._confirmar(estado, conversacion_id)
                if es_cancelacion(texto):
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
            if intencion.accion == ACCION_INVESTIGAR_REVISION:
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
            return {"estado": "RECHAZADA", "codigo": "CONTRATO_INTERPRETACION", "mensaje": str(error)}
        if intencion is None:
            return {"estado": "NO_INTERPRETADA", "mensaje": (
                "No reconocí una instrucción operacional. Puedo: asociar vehículo a chofer, activar/inactivar un "
                "chofer, corregir un campo o la obra de una guía, o consultar choferes, obras y decisiones.")}
        if intencion.accion == ACCION_INVESTIGAR_REVISION:
            return self._investigar_revision(intencion)
        definicion = ACCIONES[intencion.accion]
        if definicion.riesgo != LECTURA:
            # Toda instrucción operacional nueva invalida el pendiente anterior.
            self._fijar_pendiente(estado, conversacion_id, None)
        parametros = dict(intencion.parametros)
        if "chofer" in intencion.menciones:
            resolucion = resolver_chofer(self.capa._ctx.choferes(), intencion.menciones["chofer"],
                                         incluir_inactivos=intencion.accion == "CHOFER_CAMBIAR_ESTADO")
            if resolucion["estado"] != "RESUELTO":
                candidatos = resolucion.get("candidatos") or []
                mensaje = ("¿A cuál chofer te refieres? " + "; ".join(f"{c['nombre']} (RUT {c['rut'] or c['chofer']})"
                                                                      for c in candidatos)
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
                listado = "; ".join(f"{c['nombre']} (obra_id {c['obra_id']})" for c in candidatos)
                mensaje = (f"«{mencion}» coincide con más de una obra: {listado}. Indica cuál."
                           if resolucion["estado"] == "AMBIGUO" else
                           f"No encontré una obra existente llamada «{mencion}»"
                           + (f". ¿Te refieres a alguna de estas? {listado}" if candidatos else "")
                           + ". No creo obras nuevas desde aquí; repite la orden con el nombre exacto.")
                return {"estado": "ACLARACION_REQUERIDA", "accion": intencion.accion, "candidatos": candidatos,
                        "mensaje": mensaje}
            parametros["obra_id"] = resolucion["obra_id"]
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

    def _investigar_revision(self, intencion: Intencion) -> dict:
        """Investiga en modo lectura: no crea preview ni altera el pendiente."""
        numero_guia = str(intencion.parametros.get("numero_guia") or "")
        campos = tuple(intencion.parametros.get("campos") or ())
        if not numero_guia:
            return {"estado": "ACLARACION_REQUERIDA", "accion": ACCION_INVESTIGAR_REVISION,
                    "mensaje": "Indica el número de guía que quieres investigar."}
        from atlas_core.atlas_ia.investigacion_revision import investigar_revision
        try:
            resultado = investigar_revision(numero_guia, raiz_atlas=self.raiz,
                                             campos_solicitados=campos,
                                             permitir_ocr_nuevo=False)
        except (OSError, ValueError) as error:
            return {"estado": "INVESTIGACION_NO_DISPONIBLE", "accion": ACCION_INVESTIGAR_REVISION,
                    "mensaje": f"No pude investigar la guía {numero_guia}: {error}"}
        etiquetas = {"obra_destino": "obra", "despachar_a_crudo": "dirección de destino"}
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
            propuestas[etiquetas[campo]] = {
                "valor_actual": str(preview.get("valor_actual") or
                                     (expediente.get("HECHOS_DOCUMENTALES") or {}).get("valor_extraido") or ""),
                "valor_propuesto": propuesta or "Sin propuesta suficiente",
                "evidencia_relevante": evidencia,
                "consecuencia_operacional": str(preview.get("consecuencia_operacional") or
                    ("No se aplicará ningún cambio sin confirmación humana." if propuesta else
                     "Atlas se abstiene: no hay evidencia suficiente para cambiar el dato.")),
            }
        if not propuestas:
            return {"estado": "RESULTADO_INVESTIGACION", "accion": ACCION_INVESTIGAR_REVISION,
                    "propuestas": {}, "mensaje": (
                        f"Investigación de guía {numero_guia}, sin cambios: no encontré evidencia reutilizable "
                        "para los datos solicitados.")}
        resumen = "; ".join(
            f"{etiqueta}: actual {dato['valor_actual']!r}; propuesta {dato['valor_propuesto']!r}."
            for etiqueta, dato in propuestas.items())
        return {"estado": "RESULTADO_INVESTIGACION", "accion": ACCION_INVESTIGAR_REVISION,
                "propuestas": propuestas,
                "mensaje": f"Investigación de guía {numero_guia}, sin cambios: {resumen}"}

    def _previsualizar(self, estado: dict, conversacion_id: str, intencion: Intencion, parametros: dict,
                       texto: str) -> dict:
        preview = self.capa.previsualizar(intencion.accion, parametros, actor=ACTOR_B1, origen=ORIGEN_B1,
                                          referencia=str(texto)[:500])
        if preview.get("estado") == "RECHAZADA":
            return {"estado": "RECHAZADA", "accion": intencion.accion, "codigo": preview.get("codigo"),
                    "mensaje": preview.get("mensaje")}
        if preview.get("estado") == "RESULTADO":
            return {"estado": "RESULTADO_LECTURA", "accion": intencion.accion, "resultado": preview["resultado"],
                    "mensaje": _describir_lectura(intencion.accion, preview["resultado"])}
        if (intencion.tipo_vehiculo_declarado
                and (preview.get("valor_propuesto") or {}).get("tipo") not in (None, intencion.tipo_vehiculo_declarado)):
            return {"estado": "ACLARACION_REQUERIDA", "accion": intencion.accion, "mensaje": (
                f"Dijiste {intencion.tipo_vehiculo_declarado}, pero {parametros.get('patente')} es "
                f"{preview['valor_propuesto']['tipo']} en el catálogo. Revisa la patente.")}
        publico = {k: v for k, v in preview.items() if k != "token"}
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
        if estado_capa == "APLICADA":
            self._fijar_pendiente(estado, conversacion_id, None)
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
