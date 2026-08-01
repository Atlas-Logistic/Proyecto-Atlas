"""Resolver aislado del Motor Multicampo 1F."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType
from typing import Iterable, Mapping

from atlas_core.inteligencia.contrato_multicampo import EstadoResolucion
from atlas_core.inteligencia.politica_confianza_documento import (
    POLITICA_CONFIANZA_DOCUMENTO_V1,
    PoliticaConfianzaDocumento,
)


_CONTEXTOS_GUIA = {"GUIA", "GUIA DESPACHO", "GUIA DE DESPACHO"}
_CONTEXTOS_TRANSPORTE = {"TRANSPORTE", "NUMERO TRANSPORTE", "N TRANSPORTE"}
_CONTEXTOS_FECHA = {"FECHA", "FECHA EMISION", "FECHA DE EMISION"}
_COMPETIDORES = {
    "FACTURA", "ORDEN COMPRA", "OC", "RUT", "TOTAL", "MONTO", "TELEFONO",
    "PEDIDO", "FECHA SALIDA", "FECHA LLEGADA",
}


@dataclass(frozen=True)
class CandidatoDocumento:
    valor_original: str
    contexto: str = ""
    documento_id: str = ""
    calidad: float = 1.0
    alterado_ocr: bool = False
    fuente: str = "OCR"

    def __post_init__(self) -> None:
        if not 0 <= self.calidad <= 1:
            raise ValueError("calidad fuera de rango")


@dataclass(frozen=True)
class ResultadoResolucionDocumento:
    numero_guia_original: str
    numero_transporte_original: str
    fecha_original: str
    numero_guia_canonico: str | None
    numero_transporte_canonico: str | None
    fecha_canonica: str | None
    estado_resolucion: EstadoResolucion
    confianza: float
    razones: tuple[str, ...]
    contradicciones: tuple[str, ...]
    requiere_revision: bool
    fuentes: Mapping[str, str]

    def __post_init__(self) -> None:
        if not 0 <= self.confianza <= 1:
            raise ValueError("confianza fuera de rango")
        object.__setattr__(self, "razones", tuple(self.razones))
        object.__setattr__(self, "contradicciones", tuple(self.contradicciones))
        object.__setattr__(self, "fuentes", MappingProxyType(dict(self.fuentes)))


def resolver_guia_transporte_fecha(
    numero_guia: object = "",
    numero_transporte: object = "",
    fecha: object = "",
    *,
    candidatos_guia: Iterable[CandidatoDocumento | Mapping[str, object]] = (),
    candidatos_transporte: Iterable[CandidatoDocumento | Mapping[str, object]] = (),
    candidatos_fecha: Iterable[CandidatoDocumento | Mapping[str, object]] = (),
    fecha_archivo: object = "",
    fecha_referencia: date | None = None,
    politica: PoliticaConfianzaDocumento = POLITICA_CONFIANZA_DOCUMENTO_V1,
) -> ResultadoResolucionDocumento:
    originales = (
        _original(numero_guia),
        _original(numero_transporte),
        _original(fecha),
    )
    referencia = fecha_referencia or date.today()
    guias = _candidatos(numero_guia, candidatos_guia)
    transportes = _candidatos(numero_transporte, candidatos_transporte)
    fechas = _candidatos(fecha, candidatos_fecha)
    razones: list[str] = []
    contradicciones: list[str] = []
    fuentes: dict[str, str] = {}
    documentos = {
        candidato.documento_id
        for candidato in (*guias, *transportes, *fechas)
        if candidato.documento_id
    }

    guia, estado_guia, confianza_guia = _resolver_numerico(
        guias, _normalizar_guia, _CONTEXTOS_GUIA, politica, "GUIA",
    )
    transporte, estado_transporte, confianza_transporte = _resolver_numerico(
        transportes, _normalizar_transporte, _CONTEXTOS_TRANSPORTE,
        politica, "TRANSPORTE",
    )
    fecha_canonica, estado_fecha, confianza_fecha, fuente_fecha = _resolver_fecha(
        fechas, fecha_archivo, referencia, politica,
    )

    for campo, valor, estado, confianza, fuente in (
        ("GUIA", guia, estado_guia, confianza_guia, "OCR"),
        ("TRANSPORTE", transporte, estado_transporte, confianza_transporte, "OCR"),
        ("FECHA", fecha_canonica, estado_fecha, confianza_fecha, fuente_fecha),
    ):
        if valor is not None:
            fuentes[campo.lower()] = fuente
        razones.append(f"{campo}_{estado}")
        if estado in {"AMBIGUO", "ALTERADO_OCR", "BAJA_CALIDAD", "AUXILIAR_ARCHIVO"}:
            contradicciones.append(f"{campo}_{estado}")

    if guia and transporte and guia == transporte:
        contradicciones.append("GUIA_IGUAL_A_TRANSPORTE")
        guia = transporte = None
    if len(documentos) > 1:
        contradicciones.append("MULTIPLES_DOCUMENTOS_VISIBLES")
        guia = transporte = fecha_canonica = None

    estados = (estado_guia, estado_transporte, estado_fecha)
    if contradicciones or any(e in {"AMBIGUO", "ALTERADO_OCR", "BAJA_CALIDAD", "AUXILIAR_ARCHIVO"} for e in estados):
        estado = EstadoResolucion.REQUIERE_REVISION
    elif all(e == "CONFIRMADO" for e in estados):
        estado = EstadoResolucion.CONFIRMADO
    elif any(e == "CONFIRMADO" for e in estados):
        estado = EstadoResolucion.PROPUESTO
    else:
        estado = EstadoResolucion.NO_RESUELTO
    confianzas = [
        confianza for valor, confianza in (
            (guia, confianza_guia),
            (transporte, confianza_transporte),
            (fecha_canonica, confianza_fecha),
        ) if valor is not None
    ]
    confianza = min(confianzas) if confianzas else 0.0
    return ResultadoResolucionDocumento(
        numero_guia_original=originales[0],
        numero_transporte_original=originales[1],
        fecha_original=originales[2],
        numero_guia_canonico=guia,
        numero_transporte_canonico=transporte,
        fecha_canonica=fecha_canonica,
        estado_resolucion=estado,
        confianza=confianza,
        razones=tuple(razones),
        contradicciones=tuple(contradicciones),
        requiere_revision=estado is not EstadoResolucion.CONFIRMADO,
        fuentes=fuentes,
    )


def _resolver_numerico(candidatos, normalizador, contextos, politica, campo):
    validos: list[tuple[str, CandidatoDocumento]] = []
    for candidato in candidatos:
        contexto = _contexto(candidato.contexto)
        valor = normalizador(candidato.valor_original, politica)
        if valor is None or contexto in _COMPETIDORES:
            continue
        if contexto and contexto not in contextos:
            continue
        validos.append((valor, candidato))
    valores = {valor for valor, _ in validos}
    if not valores:
        return None, "AUSENTE", 0.0
    if len(valores) > 1 or len({c.documento_id for _, c in validos if c.documento_id}) > 1:
        return None, "AMBIGUO", 0.0
    valor = next(iter(valores))
    relevantes = [c for v, c in validos if v == valor]
    calidad = min(c.calidad for c in relevantes)
    if any(c.alterado_ocr for c in relevantes):
        return valor, "ALTERADO_OCR", min(calidad, 0.65)
    if calidad < politica.calidad_minima_confirmacion:
        return valor, "BAJA_CALIDAD", calidad
    return valor, "CONFIRMADO", calidad


def _resolver_fecha(candidatos, fecha_archivo, referencia, politica):
    validos: list[tuple[str, CandidatoDocumento]] = []
    for candidato in candidatos:
        contexto = _contexto(candidato.contexto)
        if contexto in _COMPETIDORES or (contexto and contexto not in _CONTEXTOS_FECHA):
            continue
        valor = _normalizar_fecha(
            candidato.valor_original, referencia, politica.anio_minimo
        )
        if valor:
            validos.append((valor, candidato))
    valores = {valor for valor, _ in validos}
    if len(valores) > 1:
        return None, "AMBIGUO", 0.0, "OCR"
    if len(valores) == 1:
        valor = next(iter(valores))
        relevantes = [c for v, c in validos if v == valor]
        calidad = min(c.calidad for c in relevantes)
        if any(c.alterado_ocr for c in relevantes):
            return valor, "ALTERADO_OCR", min(calidad, 0.65), "OCR"
        if calidad < politica.calidad_minima_confirmacion:
            return valor, "BAJA_CALIDAD", calidad, "OCR"
        return valor, "CONFIRMADO", calidad, "OCR"
    auxiliar = _normalizar_fecha(fecha_archivo, referencia, politica.anio_minimo)
    if auxiliar:
        return auxiliar, "AUXILIAR_ARCHIVO", 0.35, "METADATO_ARCHIVO"
    return None, "AUSENTE", 0.0, "OCR"


def _normalizar_guia(valor, politica):
    texto = str(valor).strip()
    if not re.fullmatch(r"\d+", texto):
        return None
    return texto if politica.longitud_minima_guia <= len(texto) <= politica.longitud_maxima_guia else None


def _normalizar_transporte(valor, politica):
    texto = str(valor).strip()
    if not re.fullmatch(r"\d+(?:[\s-]\d+)*", texto):
        return None
    digitos = re.sub(r"[\s-]", "", texto)
    return digitos if len(digitos) == politica.longitud_transporte else None


def _normalizar_fecha(valor, referencia, anio_minimo):
    texto = str(valor or "").strip()
    coincidencia = re.fullmatch(r"(\d{1,2})[./\-\s](\d{1,2})[./\-\s](\d{2}|\d{4})", texto)
    if not coincidencia:
        return None
    dia, mes, anio = (int(p) for p in coincidencia.groups())
    if anio < 100:
        anio += 2000
    try:
        resultado = date(anio, mes, dia)
    except ValueError:
        return None
    if resultado.year < anio_minimo or resultado > referencia:
        return None
    return resultado.strftime("%d-%m-%Y")


def _candidatos(directo, adicionales):
    resultado = []
    if _original(directo).strip():
        resultado.append(CandidatoDocumento(_original(directo)))
    resultado.extend(
        item if isinstance(item, CandidatoDocumento) else CandidatoDocumento(**item)
        for item in adicionales
    )
    return tuple(resultado)


def _contexto(valor):
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", str(valor).upper()).split())


def _original(valor):
    return "" if valor is None else str(valor)
