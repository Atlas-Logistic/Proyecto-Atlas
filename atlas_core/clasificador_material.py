"""Clasificación determinista del tipo de material transportado."""

from __future__ import annotations

import re
import unicodedata
from enum import Enum


class TipoCarga(str, Enum):
    """Tipos de carga reconocidos por Atlas."""

    BARRAS = "BARRAS"
    ROLLOS = "ROLLOS"
    ANGULOS = "ANGULOS"
    MIXTO = "MIXTO"
    NO_DETERMINADO = "NO DETERMINADO"


_TERMINOS_BARRAS = (
    "B HORMIGON",
    "BARRA HORMIGON",
    "BARRAS HORMIGON",
    "BARRA PARA HORMIGON",
    "BARRAS PARA HORMIGON",
    "BARRA",
    "BARRAS",
    "PERFIL",
    "PERFILES",
)

_TERMINOS_ROLLOS = (
    "ROLLO HORMIGON",
    "ROLLOS HORMIGON",
    "ROLLO",
    "ROLLOS",
    "ALAMBRON",
    "BOBINA",
    "BOBINAS",
)

# Bloque ORIGEN OPERACIONAL V2 -- categoría propia, nunca confundida con
# "PERFIL"/"PERFILES" (que sí cuenta como BARRAS): un ángulo es su propio
# producto real, distinto de una barra de hormigón, y la evidencia
# operacional confirmada por Javier depende de distinguirlos (ver
# `atlas_core.rutas.origen_evidencia`).
_TERMINOS_ANGULOS = (
    "ANGULO",
    "ANGULOS",
)


def normalizar_texto(valor: object) -> str:
    """
    Convierte un valor a texto mayúsculo y elimina tildes,
    signos y espacios duplicados.
    """

    texto = "" if valor is None else str(valor)

    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(
        caracter
        for caracter in texto
        if unicodedata.category(caracter) != "Mn"
    )

    texto = texto.upper()
    texto = re.sub(r"[^A-Z0-9]+", " ", texto)

    return re.sub(r"\s+", " ", texto).strip()


def clasificar_material(descripcion: object) -> TipoCarga:
    """
    Clasifica una descripción de material.

    Reglas:
    - Si aparece más de una categoría a la vez: MIXTO.
    - Si aparece sólo una categoría (barras, rollos o ángulos): esa.
    - Si no hay evidencia suficiente: NO DETERMINADO.
    """

    texto = normalizar_texto(descripcion)

    contiene_barras = any(
        termino in texto
        for termino in _TERMINOS_BARRAS
    )

    contiene_rollos = any(
        termino in texto
        for termino in _TERMINOS_ROLLOS
    )

    contiene_angulos = any(
        termino in texto
        for termino in _TERMINOS_ANGULOS
    )

    if sum((contiene_barras, contiene_rollos, contiene_angulos)) > 1:
        return TipoCarga.MIXTO

    if contiene_barras:
        return TipoCarga.BARRAS

    if contiene_rollos:
        return TipoCarga.ROLLOS

    if contiene_angulos:
        return TipoCarga.ANGULOS

    return TipoCarga.NO_DETERMINADO