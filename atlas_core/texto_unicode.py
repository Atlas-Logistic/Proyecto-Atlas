"""Saneamiento de texto Unicode INVÁLIDO antes de escribir UTF-8.

Caso real 474823: un texto con un surrogate suelto (``'\\udc8d'``) rompió
la escritura del dataset (``UnicodeEncodeError: surrogates not allowed``)
en medio de una aplicación de decisiones. Un surrogate suelto no es un
carácter: es un residuo de una decodificación defectuosa (p. ej.
``surrogateescape`` sobre bytes no decodificables, o un ``\\udcXX`` en JSON).

Regla: se reemplaza ÚNICAMENTE cada surrogate suelto por U+FFFD (el
carácter de reemplazo estándar), dejando intacto todo texto Unicode
válido (acentos, Ñ, etc.). Nunca silencioso: cada reemplazo se registra
con su ubicación para que quede trazabilidad del dato degradado.
"""
from __future__ import annotations

import logging
import re

_LOGGER = logging.getLogger(__name__)
REEMPLAZO = "�"
_SURROGATE = re.compile("[\ud800-\udfff]")


def contiene_unicode_invalido(texto: str) -> bool:
    return bool(_SURROGATE.search(texto))


def sanear_texto(texto: str, *, ubicacion: str = "") -> str:
    """Devuelve `texto` con cada surrogate suelto reemplazado por U+FFFD."""
    if not isinstance(texto, str) or not _SURROGATE.search(texto):
        return texto
    saneado, cantidad = _SURROGATE.subn(REEMPLAZO, texto)
    _LOGGER.warning(
        "Texto Unicode inválido saneado (%d surrogate(s) -> U+FFFD)%s: %s",
        cantidad, f" en {ubicacion}" if ubicacion else "", ascii(texto)[:200],
    )
    return saneado


def sanear_filas_csv(filas: list[dict[str, str]]) -> list[str]:
    """Sanea en el lugar cada valor de texto de `filas`; devuelve las
    ubicaciones ("guia=<n> archivo=<a> columna=<c>") saneadas."""
    ubicaciones: list[str] = []
    for fila in filas:
        for columna, valor in fila.items():
            if isinstance(valor, str) and _SURROGATE.search(valor):
                ubicacion = (f"guia={fila.get('numero_guia', '')} archivo={fila.get('archivo', '')} "
                             f"columna={columna}")
                fila[columna] = sanear_texto(valor, ubicacion=ubicacion)
                ubicaciones.append(ubicacion)
    return ubicaciones
