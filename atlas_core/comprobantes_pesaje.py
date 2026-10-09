"""Clasificación y extracción conservadora de comprobantes de pesaje AZA.

Un comprobante es evidencia de una guía, no una guía ni un viaje.  Este
módulo sólo reconoce la pareja de encabezados estable del formato AZA; una
mera mención de "peso" nunca basta para cambiar el flujo documental.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable


TIPO_DOCUMENTAL_COMPROBANTE_PESAJE = "COMPROBANTE_PESAJE"


def _normalizar(valor: object) -> str:
    texto = unicodedata.normalize("NFD", str(valor or ""))
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", texto).strip().upper()


def es_comprobante_pesaje_aza(textos: Iterable[str]) -> bool:
    """Reconoce sólo el encabezado doble del comprobante AZA."""
    conjunto = "\n".join(_normalizar(t) for t in textos)
    return "CERTIFICADO DE PESOS" in conjunto and "COMPROBANTE DE PESAJE" in conjunto


def _valor(texto: str, etiqueta: str, patron: str) -> str:
    hallazgo = re.search(etiqueta + r"\s*[:.]?\s*(" + patron + r")", texto)
    return hallazgo.group(1).strip() if hallazgo else "No encontrado"


def extraer_comprobante_pesaje_aza(textos: Iterable[str]) -> dict[str, str] | None:
    """Extrae los campos impresos sin inferir ni completar valores ausentes."""
    lineas = [_normalizar(t) for t in textos if str(t or "").strip()]
    if not es_comprobante_pesaje_aza(lineas):
        return None
    texto = "\n".join(lineas)
    numero = _valor(texto, r"NRO\.?\s*DOCUMENTO", r"\d{4,}")
    fecha = _valor(texto, r"EMISION", r"\d{2}[./-]\d{2}[./-]\d{4}")
    planta = _valor(texto, r"UNIDAD", r"[^\n]+")
    patente = _valor(texto, r"PATENTE", r"[A-Z0-9-]{5,10}")
    rut = _valor(texto, r"RUT\.?\s*CONDUCTOR", r"[0-9.]{7,12}-?[0-9K]")
    chofer = _valor(texto, r"NOMBRE\s+CONDUCTOR", r"[A-Z ]{4,}")
    bruto = _valor(texto, r"PESO\s+BRUTO", r"[0-9.]+")
    if bruto == "No encontrado":
        bruto = _valor(texto, r"", r"[0-9.]+(?=\s*KG\s*BRUTO)")
    tara = _valor(texto, r"(?:PESO\s+)?TARA", r"[0-9.]+")
    if tara == "No encontrado":
        tara = _valor(texto, r"", r"[0-9.]+(?=\s*KG\s*TARA)")
    neto = _valor(texto, r"PESO\s+NETO", r"[0-9.]+")
    def kg(valor: str) -> str:
        return valor.replace(".", "") if valor != "No encontrado" else valor
    return {
        "numero": numero, "fecha": fecha, "planta": planta,
        "patente": patente, "chofer": chofer, "rut_chofer": rut,
        "peso_bruto_kg": kg(bruto), "tara_kg": kg(tara), "peso_neto_kg": kg(neto),
    }


def tickets_pesaje_para_desktop(asociaciones: Iterable[dict]) -> list[dict]:
    """Proyección de sólo lectura para la futura sección Desktop.

    Lee el registro de evidencias existente y no depende de que el ticket
    haya creado una fila operacional. El consumidor visual puede mostrar esta
    lista bajo el título ``Tickets de pesaje`` sin alterar viajes ni estados.
    """
    tickets: list[dict] = []
    for asociacion in asociaciones:
        evidencia = asociacion.get("evidencia") or {}
        if evidencia.get("tipo_documental") != TIPO_DOCUMENTAL_COMPROBANTE_PESAJE:
            continue
        tickets.append({
            "archivo": evidencia.get("archivo", ""),
            "numero_guia": (asociacion.get("documento") or {}).get("numero_guia", ""),
            "numero_transporte": (asociacion.get("documento") or {}).get("numero_transporte", ""),
            "campos": evidencia.get("comprobante_pesaje") or {},
            "motivo_asociacion": asociacion.get("motivo", ""),
        })
    return tickets
