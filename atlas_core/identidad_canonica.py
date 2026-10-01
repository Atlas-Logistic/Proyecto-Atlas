"""Identidad canónica operacional (gemelo Python de Desktop
src/identidad_canonica.js -- mismas equivalencias, mismos resultados).

Tres niveles que nunca se mezclan: texto documental (evidencia, intacto),
nombre canónico (publicado/confirmado) y nombre VISIBLE (canónico con la
forma societaria abreviada de Atlas: LTDA, S.A., SpA, EIRL). Sólo
equivalencias societarias seguras; nunca fuzzy: SpA != LTDA, S.A. != LTDA.
"""
from __future__ import annotations

import re
import unicodedata

# Límite de token: inicio/fin, espacio o coma (lookarounds de ancho fijo).
_ANTES = r"(?<![^\s,])"
_DESPUES = r"(?![^\s,])"

# Orden importa: formas largas antes que sus sub-palabras. visible=None:
# equivalencia sólo de identidad, la presentación conserva el texto.
_FORMAS = (
    ("EIRL", "EIRL", r"EMPRESA\s+INDIVIDUAL\s+DE\s+RESPONSABILIDAD\s+LIMITADA|E\.\s?I\.\s?R\.\s?L\.?|EIRL"),
    ("SPA", "SpA", r"SOCIEDAD\s+POR\s+ACCIONES|S\.\s?P\.\s?A\.?|SPA"),
    ("SA", "S.A.", r"SOCIEDAD\s+AN[OÓ]NIMA|S\.\s?A\.?|SA"),
    ("LTDA", "LTDA", r"LIMITADA|LTDA\.?"),
    ("CIA", None, r"COMPA[ÑN][IÍ]A|C[IÍ]A\.?"),
)
FORMAS_SOCIETARIAS = tuple(
    (clave, visible,
     re.compile(f"{_ANTES}(?:{patron}){_DESPUES}", re.IGNORECASE),
     re.compile(rf"\s*,\s*(?=(?:{patron}){_DESPUES})", re.IGNORECASE))
    for clave, visible, patron in _FORMAS
)


def clave_identidad(valor: object) -> str:
    """Mayúsculas/tildes/puntos/comas/espacios y variantes societarias
    seguras no crean identidades distintas."""
    texto = unicodedata.normalize("NFC", "" if valor is None else str(valor))
    for clave, _visible, regex, _coma in FORMAS_SOCIETARIAS:
        texto = regex.sub(f" {clave} ", texto)
    texto = "".join(c for c in unicodedata.normalize("NFD", texto) if not unicodedata.combining(c)).upper()
    return " ".join(re.findall(r"[A-Z0-9]+", texto))


def misma_identidad(a: object, b: object) -> bool:
    clave = clave_identidad(a)
    return bool(clave) and clave == clave_identidad(b)


def nombre_visible(valor: object) -> str:
    """Sólo abrevia la forma societaria y limpia espacios/coma societaria."""
    texto = " ".join(unicodedata.normalize("NFC", "" if valor is None else str(valor)).split())
    for _clave, visible, regex, coma in FORMAS_SOCIETARIAS:
        if visible:
            texto = regex.sub(visible, coma.sub(" ", texto))
    return " ".join(texto.split())
