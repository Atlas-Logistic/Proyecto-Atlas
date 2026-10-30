"""Contrato de faltantes por guía para las consultas de ausencia.

Para cada viaje que cumple un filtro `ausente`, identifica la guía y el campo
que falta, la operación B1 existente que lo corrige y la referencia al
documento original. No cambia qué viajes coinciden ni cuántos son: se calcula
sobre `viajes_soporte` ya resuelto por el ejecutor.

Sólo reutiliza lo que el reporte ya trae: `documentos_operacionales` (campos
de guía que el ejecutor evalúa por documento), `evidencias_documentos` (fila
documental por guía para los demás campos) y `documento.archivo`, resuelto con
`evidencia_documental.resolver_ruta_evidencia`. Nunca asocia una guía con una
fotografía por cercanía ni atribuye un faltante a todas las guías del viaje:
si la evidencia no basta, lo declara y deshabilita la corrección.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping

from atlas_core.consultas_atlas import (
    _CAMPO_DOCUMENTO, _documentos_viaje, _valor_ausente, _valores_multivalor,
)

VERSION_CONTRATO = 1
NIVEL_GUIA = "GUIA"
NIVEL_VIAJE = "VIAJE"

# Campo de la fila documental por guía (`evidencias_documentos`) para los
# campos que el ejecutor evalúa a nivel de viaje.
_CAMPO_EVIDENCIA = {
    "chofer": "chofer", "rut": "rut_chofer", "fecha": "fecha", "destino": "direccion_entrega",
    "comuna": "localidad_entrega", "region": "region_entrega", "patente_tracto": "patente_tracto",
    "patente_rampla": "patente_rampla", "tipo_carga": "tipo_carga", "origen": "planta_origen_nombre",
    "numero_transporte": "numero_transporte",
}

# Operaciones B1 existentes por campo. `instruccion` es una frase que
# `b1_operador.interpretar_determinista` ya convierte en `accion` (lo
# verifican las pruebas); `{valor}` lo completa la persona.
_OPERACIONES = {
    "material": (
        {"accion": "DOCUMENTO_CORREGIR_CAMPO", "campo": "descripcion_material",
         "instruccion": "El material de la guía {guia} es {valor}", "requiere_valor": True,
         "requiere_documento": False},
        {"accion": "DOCUMENTO_RECUPERAR_MATERIAL",
         "instruccion": "Recupera el material de la guía {guia}", "requiere_valor": False,
         "requiere_documento": True},
    ),
    "peso": ({"accion": "DOCUMENTO_CORREGIR_CAMPO", "campo": "peso_kg",
              "instruccion": "El peso de la guía {guia} es {valor}", "requiere_valor": True,
              "requiere_documento": False},),
    "cliente": ({"accion": "DOCUMENTO_CORREGIR_CAMPO", "campo": "cliente",
                 "instruccion": "Corrige el cliente de la guía {guia} a {valor}", "requiere_valor": True,
                 "requiere_documento": False},),
    "obra": ({"accion": "DOCUMENTO_ASIGNAR_OBRA",
              "instruccion": "La obra de la guía {guia} es {valor}", "requiere_valor": True,
              "requiere_documento": False},),
    "chofer": ({"accion": "DOCUMENTO_CORREGIR_CHOFER_OPERACIONAL",
                "instruccion": "El chofer de la guía {guia} es {valor}", "requiere_valor": True,
                "requiere_documento": False},),
    "destino": ({"accion": "DOCUMENTO_CORREGIR_DESTINO_OPERACIONAL",
                 "instruccion": "El destino de la guía {guia} es {valor}", "requiere_valor": True,
                 "requiere_documento": False},),
    "patente_tracto": ({"accion": "DOCUMENTO_CORREGIR_CAMPO", "campo": "patente_tracto",
                        "instruccion": "Corrige el tracto de la guía {guia} a {valor}", "requiere_valor": True,
                        "requiere_documento": False},),
    "patente_rampla": ({"accion": "DOCUMENTO_CORREGIR_CAMPO", "campo": "patente_rampla",
                        "instruccion": "Corrige la rampla de la guía {guia} a {valor}", "requiere_valor": True,
                        "requiere_documento": False},),
}

# Mismo formato de folio que acepta B1 (`b1_operador._GUIA`).
_GUIA_IDENTIFICABLE = re.compile(r"\d{3,12}")


def _evidencias_viaje(viaje: Mapping[str, str]) -> list[Mapping[str, object]]:
    crudo = str(viaje.get("evidencias_documentos", "") or "").strip()
    if not crudo:
        return []
    try:
        evidencias = json.loads(crudo)
    except json.JSONDecodeError:
        return []
    return [e for e in evidencias if isinstance(e, Mapping)] if isinstance(evidencias, list) else []


def _documentos_para(viaje: Mapping[str, str], campo: str) -> tuple[str, list[Mapping[str, object]]]:
    if campo in _CAMPO_DOCUMENTO:
        return _CAMPO_DOCUMENTO[campo], _documentos_viaje(viaje)
    return _CAMPO_EVIDENCIA.get(campo, ""), (_evidencias_viaje(viaje) if campo in _CAMPO_EVIDENCIA else [])


def _texto(valor: object) -> str:
    return str(valor if valor is not None else "").strip()


class _Referencias:
    """Resuelve cada `archivo` una sola vez por consulta."""

    def __init__(self, raiz_atlas: str | Path | None):
        self._raiz = raiz_atlas
        self._cache: dict[str, dict[str, object]] = {}

    def __call__(self, archivo: str) -> dict[str, object]:
        if not archivo:
            return {"archivo": None, "disponible": False, "estado": "SIN_REFERENCIA",
                    "motivo": "El reporte no asocia un documento original a esta guía."}
        if self._raiz is None:
            return {"archivo": archivo, "disponible": None, "estado": "NO_VERIFICADA",
                    "motivo": "No se indicó la raíz Atlas; no se verificó el documento original."}
        if archivo not in self._cache:
            from atlas_core.evidencia_documental import resolver_ruta_evidencia
            try:
                evidencia = resolver_ruta_evidencia(self._raiz, archivo)
            except OSError as error:
                self._cache[archivo] = {"archivo": archivo, "disponible": False, "estado": "NO_VERIFICADA",
                                        "motivo": f"No se pudo verificar el documento original: {error}"}
            else:
                referencia = {"archivo": archivo, "disponible": evidencia.ruta is not None,
                              "estado": evidencia.ubicacion,
                              "ruta": str(evidencia.ruta) if evidencia.ruta is not None else None}
                if evidencia.ruta is None:
                    referencia["motivo"] = "El documento original no está disponible."
                self._cache[archivo] = referencia
        return dict(self._cache[archivo])


def _operaciones(campo: str, guia: str, archivo: str, motivo_guia: str | None,
                 referencia: Mapping[str, object]) -> list[dict[str, object]]:
    salida = []
    for definicion in _OPERACIONES.get(campo, ()):
        motivo = motivo_guia
        if motivo is None and definicion["requiere_documento"] and referencia.get("disponible") is not True:
            motivo = "Requiere el documento original, que no está disponible."
        parametros = {"numero_guia": guia}
        if "campo" in definicion:
            parametros["campo"] = definicion["campo"]
        if archivo:
            parametros["archivo"] = archivo
        instruccion = definicion["instruccion"].replace("{guia}", guia) if motivo is None else None
        salida.append({
            "accion": definicion["accion"], "parametros": parametros, "instruccion": instruccion,
            "requiere_valor": definicion["requiere_valor"], "habilitada": motivo is None,
            **({"motivo": motivo} if motivo else {}),
        })
    return salida


def _item_viaje(viaje, campo, clave, limitacion):
    return {
        "viaje_id": _texto(viaje.get("viaje_id")), "numero_transporte": _texto(viaje.get("numero_transporte")),
        "campo": campo, "campo_documental": clave or None, "nivel": NIVEL_VIAJE, "numero_guia": None,
        "guia_identificable": False, "valor_actual": None,
        "referencia_documental": {"archivo": None, "disponible": False, "estado": "SIN_GUIA_IDENTIFICADA",
                                  "motivo": "No hay una guía identificada para este faltante."},
        "operaciones": [], "correccion_habilitada": False, "limitacion": limitacion,
    }


def construir_faltantes(
    campos: Iterable[str], viajes_soporte: Iterable[Mapping[str, str]], *,
    todos_los_viajes: Iterable[Mapping[str, str]], raiz_atlas: str | Path | None = None,
) -> tuple[dict[str, object], ...]:
    """Un elemento por guía afectada y campo; o uno por viaje cuando la
    evidencia no permite identificar la guía. `todos_los_viajes` sirve para
    detectar folios repetidos en el reporte (B1 no podría corregirlos sin
    ambigüedad)."""
    folios = Counter(
        _texto(d.get("numero_guia")) for v in todos_los_viajes for d in _documentos_viaje(v)
    )
    referencias = _Referencias(raiz_atlas)
    items: list[dict[str, object]] = []
    for viaje in viajes_soporte:
        for campo in campos:
            clave, documentos = _documentos_para(viaje, campo)
            guias_viaje = _valores_multivalor(viaje, "numeros_guia")
            if not documentos:
                if len(guias_viaje) == 1 and campo in _CAMPO_DOCUMENTO:
                    # Sin detalle por documento, la única guía del viaje es
                    # la única que puede carecer del dato.
                    documentos = [{"numero_guia": guias_viaje[0], clave: ""}]
                else:
                    items.append(_item_viaje(viaje, campo, clave, (
                        f"El viaje tiene {len(guias_viaje)} guías y el reporte no trae el detalle por guía de "
                        f"«{campo}»: no se puede identificar cuál lo tiene ausente."
                        if len(guias_viaje) > 1 else
                        f"El reporte no trae el detalle por guía de «{campo}» para este viaje.")))
                    continue
            afectados = [d for d in documentos if _valor_ausente(campo, d.get(clave))]
            if not afectados:
                items.append(_item_viaje(viaje, campo, clave, (
                    f"Las guías del viaje traen «{campo}», pero falta en el dato consolidado del viaje: "
                    "no corresponde a una guía concreta.")))
                continue
            for documento in afectados:
                guia = _texto(documento.get("numero_guia"))
                archivo = _texto(documento.get("archivo"))
                identificable = bool(_GUIA_IDENTIFICABLE.fullmatch(guia))
                motivo_guia = None
                if not identificable:
                    motivo_guia = f"La guía no tiene un número identificable («{guia or 'vacío'}»)."
                elif folios.get(guia, 0) > 1:
                    motivo_guia = f"El folio {guia} aparece en {folios[guia]} documentos del reporte."
                referencia = referencias(archivo)
                operaciones = _operaciones(campo, guia, archivo, motivo_guia, referencia)
                limitacion = motivo_guia
                if limitacion is None and not operaciones:
                    limitacion = f"No existe una operación de corrección para «{campo}» desde B1."
                items.append({
                    "viaje_id": _texto(viaje.get("viaje_id")),
                    "numero_transporte": _texto(viaje.get("numero_transporte")),
                    "campo": campo, "campo_documental": clave, "nivel": NIVEL_GUIA,
                    "numero_guia": guia or None, "guia_identificable": identificable,
                    "valor_actual": _texto(documento.get(clave)),
                    "referencia_documental": referencia, "operaciones": operaciones,
                    "correccion_habilitada": any(o["habilitada"] for o in operaciones),
                    "limitacion": limitacion,
                })
    return tuple(items)
