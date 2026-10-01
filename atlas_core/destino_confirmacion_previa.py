"""Destino de una guía desde una CONFIRMACIÓN HUMANA previa de otra guía.

Una tarjeta DESTINO_NO_RESUELTO puede resolverse con la dirección que un
humano ya registró (REGISTRAR_DIRECCION en el ledger) para OTRA guía del
mismo contexto, sólo si todo converge:

- la confirmación es humana (nunca un actor ATLAS_*), es la vigente para su
  documento y su fila sigue usando esa dirección;
- mismo cliente (RUT; si falta, misma identidad de nombre) y misma obra
  (misma entidad del catálogo -- alias documental corto o nombre canónico --
  o el mismo nombre cuando ninguna resuelve);
- calle y comuna confirmadas presentes en el texto documental de destino de
  la guía objetivo (y en el texto documental que el humano resolvió), sin
  otra comuna en el texto;
- número de calle: sólo si la confirmación lo trae Y el documento objetivo
  dice ese mismo número; si ninguna evidencia lo trae se propone sin número;
  nunca se hereda, aproxima ni inventa;
- una sola dirección posible.

No usa el catálogo de destinos de la obra: que la obra tenga OTRO destino
confirmado no invalida ni sustituye este. Sólo propone; aplicar exige el
preview y la confirmación humana de la capa de acciones (DECISION_APLICAR /
REGISTRAR_DIRECCION). Módulo puro: no lee ni escribe archivos.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Mapping

from atlas_core.identidad_canonica import clave_identidad

_ABREVIATURAS = {
    "AVENIDA": "AV", "AVDA": "AV", "CAMINO": "CAM", "PASAJE": "PJE", "CALLE": "", "GENERAL": "GRAL",
    "PONIENTE": "PTE", "ORIENTE": "OTE", "NORTE": "NTE", "SANTA": "STA", "SANTO": "STO",
}
_ACTORES_AUTOMATICOS = ("ATLAS",)
TIPO_DECISION = "DESTINO_NO_RESUELTO"


def _tokens(texto: object) -> list[str]:
    plano = "".join(c for c in unicodedata.normalize("NFD", str(texto or "").upper())
                    if not unicodedata.combining(c))
    salida = []
    for token in re.findall(r"[A-Z0-9]+", plano):
        token = _ABREVIATURAS.get(token, token)
        if token:
            salida.append(token)
    return salida


def _contiene(secuencia: list[str], buscada: list[str]) -> int:
    """Índice donde `buscada` aparece contigua en `secuencia`, o -1."""
    if not buscada:
        return -1
    for i in range(len(secuencia) - len(buscada) + 1):
        if secuencia[i:i + len(buscada)] == buscada:
            return i
    return -1


def _es_numero(token: str) -> bool:
    return bool(re.fullmatch(r"\d{1,6}[A-Z]?|S N|SN", token)) and any(c.isdigit() for c in token)


def _comunas_mencionadas(texto: str, comunas: Iterable[str]) -> set[str]:
    tokens = _tokens(texto)
    return {" ".join(_tokens(c)) for c in comunas if c and _contiene(tokens, _tokens(c)) >= 0}


def _compatible_con_documental(calle: str, numero: str, comuna: str, documental: str,
                               comunas: Iterable[str]) -> str:
    """'' si la dirección confirmada es la que dice el texto documental; si no, el motivo."""
    doc = _tokens(documental)
    tokens_calle = [t for t in _tokens(calle) if not _es_numero(t)]
    if not tokens_calle or doc[:len(tokens_calle)] != tokens_calle:
        return "CALLE_INCOMPATIBLE"
    resto = doc[len(tokens_calle):]
    tokens_comuna = _tokens(comuna)
    posicion = _contiene(resto, tokens_comuna)
    if posicion < 0:
        return "COMUNA_INCOMPATIBLE"
    otras = _comunas_mencionadas(documental, comunas) - {" ".join(tokens_comuna)}
    # Una comuna que sólo aparece DENTRO de la confirmada (p. ej. un prefijo) no contradice.
    if any(" ".join(tokens_comuna).find(o) < 0 for o in otras):
        return "COMUNA_INCOMPATIBLE"
    numeros_doc = [t for t in resto[:posicion] if _es_numero(t)]
    if numero:
        if numeros_doc != [numero]:
            return "NUMERO_NO_SUSTENTADO"
    elif numeros_doc:
        # El documento trae un número que la confirmación no respalda: no se descarta en silencio.
        return "NUMERO_DOCUMENTAL_SIN_CONFIRMAR"
    return ""


def _es_humana(aplicacion: Mapping) -> bool:
    actor = str(aplicacion.get("actor") or "").strip().upper()
    return bool(actor) and not actor.startswith(_ACTORES_AUTOMATICOS)


def _rut(valor: object) -> str:
    texto = re.sub(r"[^0-9K]", "", str(valor or "").upper())
    return texto if len(texto) >= 7 else ""


def _cliente_compatible(objetivo: Mapping, previa: Mapping) -> bool:
    rut_a, rut_b = _rut(objetivo.get("rut_cliente")), _rut(previa.get("rut_cliente"))
    if rut_a and rut_b:
        return rut_a == rut_b
    clave_a, clave_b = clave_identidad(objetivo.get("cliente")), clave_identidad(previa.get("cliente"))
    return bool(clave_a) and clave_a == clave_b


def _obras_de(nombre: str, obras: Iterable) -> set[str]:
    clave = clave_identidad(nombre)
    if not clave:
        return set()
    return {o.obra_id for o in obras
            if clave in {clave_identidad(x) for x in (o.nombre_canonico, *o.aliases_documentales)}}


def _obra_compatible(objetivo: Mapping, previa: Mapping, obras: Iterable) -> bool:
    obras = list(obras)
    nombre_a, nombre_b = str(objetivo.get("obra_destino") or ""), str(previa.get("obra_destino") or "")
    ids_a, ids_b = _obras_de(nombre_a, obras), _obras_de(nombre_b, obras)
    if ids_a or ids_b:
        return len(ids_a) == 1 and ids_a == ids_b
    clave = clave_identidad(nombre_a)
    return bool(clave) and clave == clave_identidad(nombre_b)


def _misma_fila(fila: Mapping, documento: Mapping) -> bool:
    archivo = str(documento.get("archivo") or "").replace("\\", "/").strip("/")
    return (str(fila.get("numero_guia", "")) == str(documento.get("numero_guia") or "")
            and (not archivo or str(fila.get("archivo", "")).replace("\\", "/").strip("/") == archivo))


def proponer_destino_por_confirmacion_humana(
    *, decision: Mapping, filas: list[Mapping], aplicaciones: list[Mapping], obras: Iterable,
    comunas: Iterable[str],
) -> dict:
    """{'estado': 'PROPUESTA', 'direccion', 'comuna', 'numero', 'evidencias'} o
    {'estado': 'ABSTENCION', 'motivo', 'descartes'}."""
    documento = decision.get("documento") or {}
    candidatas_objetivo = [f for f in filas if _misma_fila(f, documento)]
    if decision.get("tipo") != TIPO_DECISION or len(candidatas_objetivo) != 1:
        return {"estado": "ABSTENCION", "motivo": "IDENTIDAD_OBJETIVO_INSUFICIENTE", "descartes": []}
    objetivo = candidatas_objetivo[0]
    documental = str(decision.get("valor_documental") or objetivo.get("despachar_a_crudo") or "")
    comunas = list(comunas)

    # Sólo la aplicación más reciente de cada documento está vigente.
    vigentes: dict[tuple[str, str], Mapping] = {}
    for aplicacion in aplicaciones:
        doc = aplicacion.get("documento") or {}
        if not isinstance(doc, Mapping) or not doc.get("numero_guia"):
            continue
        if aplicacion.get("tipo") == TIPO_DECISION or aplicacion.get("campo") == "despachar_a_crudo":
            vigentes[(str(doc.get("numero_guia")), str(doc.get("archivo") or ""))] = aplicacion

    propuestas: dict[tuple[str, str, str], list[dict]] = {}
    descartes: list[dict] = []
    for (guia, _archivo), aplicacion in vigentes.items():
        if guia == str(documento.get("numero_guia") or ""):
            continue
        if aplicacion.get("tipo") != TIPO_DECISION or aplicacion.get("accion") != "REGISTRAR_DIRECCION":
            continue
        calle = str(aplicacion.get("direccion_manual") or "").strip()
        comuna = str(aplicacion.get("comuna_manual") or "").strip()
        anterior = str(aplicacion.get("valor_documental_anterior") or "").strip()

        def descartar(motivo: str) -> None:
            descartes.append({"numero_guia": guia, "motivo": motivo})

        if not _es_humana(aplicacion):
            descartar("NO_ES_DECISION_HUMANA")
            continue
        if not (calle and comuna and anterior):
            descartar("CONFIRMACION_INCOMPLETA")
            continue
        filas_previas = [f for f in filas if _misma_fila(f, aplicacion["documento"])]
        if len(filas_previas) != 1:
            descartar("IDENTIDAD_PREVIA_INSUFICIENTE")
            continue
        previa = filas_previas[0]
        if _tokens(previa.get("despachar_a_crudo")) != _tokens(calle):
            descartar("CONFIRMACION_NO_VIGENTE")
            continue
        if not _cliente_compatible(objetivo, previa):
            descartar("CLIENTE_INCOMPATIBLE")
            continue
        if not _obra_compatible(objetivo, previa, obras):
            descartar("OBRA_INCOMPATIBLE")
            continue
        numeros = [t for t in _tokens(calle) if _es_numero(t)]
        numero = numeros[0] if len(numeros) == 1 else ""
        if len(numeros) > 1:
            descartar("NUMERO_AMBIGUO")
            continue
        motivo = (_compatible_con_documental(calle, numero, comuna, documental, comunas)
                  or _compatible_con_documental(calle, numero, comuna, anterior, comunas))
        if motivo:
            descartar(motivo)
            continue
        clave = (" ".join(t for t in _tokens(calle) if not _es_numero(t)), numero, " ".join(_tokens(comuna)))
        propuestas.setdefault(clave, []).append({
            "numero_guia": guia, "archivo": str(aplicacion["documento"].get("archivo") or ""),
            "fecha": str(aplicacion.get("fecha") or ""), "actor": str(aplicacion.get("actor") or ""),
            "valor_documental_anterior": anterior, "direccion_manual": calle, "comuna_manual": comuna,
        })

    if len(propuestas) > 1:
        return {"estado": "ABSTENCION", "motivo": "CONFIRMACIONES_INCOMPATIBLES", "descartes": descartes}
    if not propuestas:
        return {"estado": "ABSTENCION", "motivo": "SIN_CONFIRMACION_COMPATIBLE", "descartes": descartes}
    (_calle, numero, _comuna), evidencias = next(iter(propuestas.items()))
    evidencias.sort(key=lambda e: e["fecha"])
    return {"estado": "PROPUESTA", "direccion": evidencias[-1]["direccion_manual"],
            "comuna": evidencias[-1]["comuna_manual"], "numero": numero, "evidencias": evidencias,
            "descartes": descartes}
