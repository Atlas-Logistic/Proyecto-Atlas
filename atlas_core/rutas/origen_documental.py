"""Resolución de planta de origen por evidencia documental (Bloque PLANTA-P1).

Adaptado de ``_resolver_origen_documental`` (rama remota no fusionada
``origin/feature-cobertura-origen-fase1``, commit ``2c5c764``, validado con
9 guías reales: cobertura 7/9, los 2 casos restantes correctamente sin
origen por desenfoque/omisión de OCR -- 0 falsos positivos conocidos) para
operar sobre el texto OCR de página completa que ya produce el proveedor
activo.

Diferencia deliberada con el original: el original releía un recorte focal
del encabezado con EasyOCR (``lector.readtext()`` directo, igual que otros
focales ya migrados en bloques anteriores -- API no soportada por
PaddleOCR) y exigía consenso entre 2 de 3 variantes de esa relectura, para
compensar el ruido de una imagen pequeña/recortada. Con PaddleOCR el
encabezado del emisor ya se lee, con confianza alta, dentro del texto de
página completa que `procesar_archivo` obtiene igual — no hace falta una
relectura focal aparte. Por eso esta versión trabaja directamente sobre
`textos` (la misma lista que ya usa el resto del extractor) y no requiere
consenso entre variantes; conserva intacta la exigencia de planta única
sin ambigüedad, que es la que evita los falsos positivos.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable


def _normalizar(texto: object) -> str:
    valor = unicodedata.normalize("NFD", str(texto or ""))
    return "".join(c for c in valor if unicodedata.category(c) != "Mn").upper()


def _distancia_token(a: str, b: str) -> int:
    """Distancia de edición (Levenshtein), acotada: tokens de largo muy
    distinto nunca se consideran la misma palabra con ruido OCR."""
    if abs(len(a) - len(b)) > 1:
        return 99
    anterior = list(range(len(b) + 1))
    for indice_a, caracter_a in enumerate(a, 1):
        actual = [indice_a]
        for indice_b, caracter_b in enumerate(b, 1):
            actual.append(min(
                actual[-1] + 1,
                anterior[indice_b] + 1,
                anterior[indice_b - 1] + (caracter_a != caracter_b),
            ))
        anterior = actual
    return anterior[-1]


def _tokens_encabezado_origen(texto: str) -> list[str]:
    """Recorta los tokens al encabezado del emisor, antes del directorio de
    sucursales. El encabezado de una guía AZA suele continuar con un listado
    fijo de sucursales ("Sucursal <ciudad>...") impreso como información de
    contacto, no como planta de despacho. Si esas ciudades también existen
    como plantas confirmadas en el catálogo (p. ej. "Sucursal Colina"),
    comparar contra el texto completo genera una segunda coincidencia y
    anula el voto de la planta real. Se conserva únicamente el tramo
    anterior a la primera mención tolerante a ruido OCR de "SUCURSAL"."""
    tokens_completos = re.findall(r"[A-Z0-9]+", _normalizar(texto))
    limite = next(
        (
            indice for indice, token in enumerate(tokens_completos)
            if _distancia_token(token, "SUCURSAL") <= 1
        ),
        len(tokens_completos),
    )
    return tokens_completos[:limite]


def resolver_origen_documental(
    textos: Iterable[str], plantas: Iterable[object]
) -> object | None:
    """`plantas`: objetos con `nombre`, `estado_calidad`, `estado_vigencia`
    (p. ej. `atlas_core.catalogo_plantas.Planta`). Devuelve el objeto planta
    si exactamente una coincide sin ambigüedad con el encabezado (cortado
    antes de "SUCURSAL"); `None` si no hay ninguna o hay más de una —
    nunca infiere por descarte ni por cercanía a otro campo."""
    texto_completo = "\n".join(str(t) for t in textos)
    tokens = _tokens_encabezado_origen(texto_completo)
    if not tokens:
        return None
    coincidencias = []
    for planta in plantas:
        if str(getattr(planta, "estado_vigencia", "")).upper() not in {"ACTIVA", "ACTIVO"}:
            continue
        if str(getattr(planta, "estado_calidad", "")).upper() not in {
            "CONFIRMADA", "CONFIRMADO", "CONFIRMADO_DOCUMENTAL",
        }:
            continue
        nombre = str(getattr(planta, "nombre", "")).strip()
        nombre_tokens = re.findall(r"[A-Z0-9]+", _normalizar(nombre))
        if nombre_tokens and all(
            any(_distancia_token(observado, esperado) <= 1 for observado in tokens)
            for esperado in nombre_tokens
        ):
            coincidencias.append(planta)
    if len(coincidencias) == 1:
        return coincidencias[0]
    return None
