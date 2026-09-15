"""Replay puro de la evidencia OCR persistida.

Este módulo deliberadamente no conoce imágenes, proveedores OCR, catálogos ni
artefactos operacionales.  Sirve para evaluar, de forma reproducible, las
reglas geométricas que ya usa el extractor sobre bloques previamente
persistidos.  No es un reemplazo de ``procesar_archivo``: no calcula campos
lineales, enriquecimiento ni derivados.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Mapping

from atlas_core.extractor import (
    _extraer_asociaciones_geometricas,
    _extraer_despachar_a_geometrico,
    _extraer_numero_guia_geometrico,
)
from atlas_core.trazabilidad_ocr import (
    ESTADO_BLOQUES_DISPONIBLES,
    VERSION_SCHEMA_TRAZA_OCR,
)


class ErrorReplayTrazaOCR(ValueError):
    """La evidencia lateral no cumple el contrato necesario para un replay."""


def _referencia_normalizada(valor: object) -> str:
    return str(valor or "").replace("\\", "/").strip()


def _numero_finito(valor: object, *, etiqueta: str) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ErrorReplayTrazaOCR(f"{etiqueta} debe ser numérico")
    numero = float(valor)
    if not isfinite(numero):
        raise ErrorReplayTrazaOCR(f"{etiqueta} debe ser finito")
    return numero


def _reconstruir_bloque(crudo: object, indice: int) -> BloqueOCR:
    # Bloque P2 SPAWN/IPC -- import diferido: `atlas_core.ocr` cuesta,
    # medido, varios segundos SOLO en importar (arrastra `easyocr` ->
    # `torch`), aunque `BloqueOCR` en sí es un dataclass sin dependencia
    # real -- este módulo, pese a su nombre, nunca relee imagen ni llama
    # OCR (ver docstring del archivo); sólo reconstruye un valor ya
    # persistido. Ver comentario equivalente en `procesamiento_masivo.py`.
    from atlas_core.ocr import BloqueOCR
    if not isinstance(crudo, Mapping):
        raise ErrorReplayTrazaOCR(f"bloques[{indice}] debe ser un objeto")
    texto = crudo.get("texto")
    if not isinstance(texto, str):
        raise ErrorReplayTrazaOCR(f"bloques[{indice}].texto debe ser texto")
    caja = crudo.get("bounding_box")
    if not isinstance(caja, (list, tuple)) or len(caja) != 4:
        raise ErrorReplayTrazaOCR(f"bloques[{indice}].bounding_box debe tener cuatro puntos")
    puntos: list[tuple[float, float]] = []
    for punto_indice, punto in enumerate(caja):
        if not isinstance(punto, (list, tuple)) or len(punto) != 2:
            raise ErrorReplayTrazaOCR(
                f"bloques[{indice}].bounding_box[{punto_indice}] debe tener dos coordenadas"
            )
        puntos.append((
            _numero_finito(punto[0], etiqueta=f"bloques[{indice}].x{punto_indice}"),
            _numero_finito(punto[1], etiqueta=f"bloques[{indice}].y{punto_indice}"),
        ))
    xs, ys = [p[0] for p in puntos], [p[1] for p in puntos]
    if max(xs) <= min(xs) or max(ys) <= min(ys):
        raise ErrorReplayTrazaOCR(f"bloques[{indice}].bounding_box no delimita área")
    confianza_cruda = crudo.get("confianza")
    confianza = 0.0 if confianza_cruda is None else _numero_finito(
        confianza_cruda, etiqueta=f"bloques[{indice}].confianza"
    )
    return BloqueOCR(texto=texto, bounding_box=tuple(puntos), confianza=confianza)


def reconstruir_bloques_desde_traza(
    traza: Mapping[str, object], *, referencia_esperada: str,
) -> tuple[BloqueOCR, ...]:
    """Valida una traza v2 y reconstruye sus bloques sin leer OCR.

    ``referencia_esperada`` es obligatoria: una traza lateral no contiene el
    hash de su imagen, así que al menos se exige la identidad de ruta relativa
    que el productor registró.  La verificación de hash de la imagen original
    corresponde a la capa de operación, fuera de este módulo puro.
    """
    if not isinstance(traza, Mapping):
        raise ErrorReplayTrazaOCR("la traza debe ser un objeto")
    if traza.get("schema_version") != VERSION_SCHEMA_TRAZA_OCR:
        raise ErrorReplayTrazaOCR("schema_version de traza no compatible")
    imagen = traza.get("imagen")
    ocr = traza.get("ocr")
    if not isinstance(imagen, Mapping) or not isinstance(ocr, Mapping):
        raise ErrorReplayTrazaOCR("la traza requiere objetos imagen y ocr")
    referencia = _referencia_normalizada(imagen.get("referencia"))
    esperada = _referencia_normalizada(referencia_esperada)
    if not referencia or not esperada or referencia != esperada:
        raise ErrorReplayTrazaOCR("referencia de imagen inconsistente")
    if ocr.get("estado_bloques") != ESTADO_BLOQUES_DISPONIBLES:
        raise ErrorReplayTrazaOCR("la traza no tiene bloques OCR disponibles")
    bloques_crudos = ocr.get("bloques")
    if not isinstance(bloques_crudos, list):
        raise ErrorReplayTrazaOCR("bloques debe ser una lista cuando están disponibles")
    return tuple(_reconstruir_bloque(bloque, indice) for indice, bloque in enumerate(bloques_crudos))


def reproducir_extraccion_geometrica_desde_traza(
    traza: Mapping[str, object], *, referencia_esperada: str,
) -> dict[str, object]:
    """Ejecuta las reglas geométricas productivas contra una traza validada.

    No invoca OCR ni efectúa I/O.  La salida separa candidatos finales de la
    evidencia cruda de cada extractor para que la capa que decida una escritura
    pueda aplicar una lista blanca de campos.
    """
    bloques = reconstruir_bloques_desde_traza(traza, referencia_esperada=referencia_esperada)
    asociaciones = _extraer_asociaciones_geometricas(list(bloques))
    despacho = _extraer_despachar_a_geometrico(list(bloques))
    guia = _extraer_numero_guia_geometrico(list(bloques))
    extraccion: dict[str, str] = {}
    for campo in ("cliente", "obra destino"):
        valor = asociaciones.get(campo)
        if valor:
            extraccion[campo] = valor
    if despacho.get("valor"):
        extraccion["despachar_a_crudo"] = str(despacho["valor"])
    if guia.get("valor"):
        extraccion["numero_guia"] = str(guia["valor"])
    return {
        "extraccion": extraccion,
        "diagnostico": {
            "referencia": _referencia_normalizada(referencia_esperada),
            "schema_version": VERSION_SCHEMA_TRAZA_OCR,
            "bloques_reconstruidos": len(bloques),
            "sin_ocr": True,
            "sin_io": True,
            "evidencia": {
                "asociaciones": asociaciones,
                "despachar_a": despacho,
                "numero_guia": guia,
            },
        },
    }
