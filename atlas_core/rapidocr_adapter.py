"""Adaptación no operacional de bloques RapidOCR al contrato OCR de Atlas.

RapidOCR se ejecuta fuera del proceso principal. Este módulo sólo conserva la
evidencia recibida, elimina un delimitador tipográfico inicial y convierte las
cajas ya orientadas a ``BloqueOCR``. No extrae campos ni valida documentos.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable

from atlas_core.ocr import BloqueOCR


_DELIMITADOR_INICIAL = re.compile(r"^\s*[:：]\s*")


@dataclass(frozen=True)
class BloqueRapidOCR:
    """Evidencia completa de un bloque en referencia EXIF normalizada."""

    texto_original: str
    texto: str
    bounding_box: tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]
    confianza: float
    exif_normalizado: bool = True

    def a_bloque_atlas(self) -> BloqueOCR:
        return BloqueOCR(self.texto, self.bounding_box, self.confianza)


def segmentar_delimitador_inicial(texto: object) -> str:
    """Separa únicamente ``:``/``：`` inicial de un valor documental.

    No cambia letras, números, espacios internos ni signos posteriores. El
    original se conserva en ``BloqueRapidOCR.texto_original`` para auditoría.
    """
    original = str(texto or "")
    segmentado = _DELIMITADOR_INICIAL.sub("", original)
    return segmentado if segmentado else original


def adaptar_bloques_rapidocr(filas: Iterable[object]) -> list[BloqueRapidOCR]:
    """Convierte la forma pública de RapidOCR 1.x a evidencia tipada.

    Cada fila válida es ``[bbox_de_cuatro_puntos, texto, confianza]``. Las
    filas incompletas se omiten, igual que los otros proveedores al convertir
    respuestas de workers: no inventan una geometría.
    """
    adaptados: list[BloqueRapidOCR] = []
    for fila in filas:
        if not isinstance(fila, (list, tuple)) or len(fila) < 3:
            continue
        bbox, texto, confianza = fila[0], fila[1], fila[2]
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        try:
            puntos = tuple((float(punto[0]), float(punto[1])) for punto in bbox)
            if len(puntos) != 4:
                continue
            original = str(texto or "")
            if not original.strip():
                continue
            adaptados.append(BloqueRapidOCR(
                texto_original=original,
                texto=segmentar_delimitador_inicial(original),
                bounding_box=puntos,  # type: ignore[arg-type]
                confianza=float(confianza),
            ))
        except (TypeError, ValueError, IndexError):
            continue
    return adaptados


def filas_resultado_rapidocr(resultado: Any) -> list[object]:
    """Obtiene las filas OCR, tolerando ``(filas, tiempos)`` de RapidOCR 1.x."""
    if isinstance(resultado, tuple) and len(resultado) == 2:
        resultado = resultado[0]
    return list(resultado or []) if isinstance(resultado, (list, tuple)) else []
