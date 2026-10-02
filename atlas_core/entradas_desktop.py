"""Bloque RECUPERACIÓN DE ENTRADAS DESKTOP -- caso real 475193 (lote
20261002_125747): Desktop copió la imagen a `operacion/entradas/<lote>/` y
escribió `_snapshot_antes.json`, pero se cerró antes de lanzar
`analizar_guias_masivo.py`. Al reabrir nadie retomaba esa entrada: no había
OCR, fila, error ni viaje -- sólo la imagen preservada.

Señales que deja el flujo normal de Desktop (`atlas:procesar-imagenes`):
  1. copia las imágenes a `entradas/<lote>/`;
  2. escribe `_snapshot_antes.json` (sólo tras copiar TODAS);
  3. `procesar_carpeta` escribe `manifiestos_ingesta/<lote>.json` ANTES
     de cualquier OCR, y luego las filas del dataset.

Una entrada NUNCA INICIADA es exactamente "2 hecho, 3 no empezó": snapshot
válido, sin manifiesto y ninguno de sus documentos en el dataset. Cualquier
otra combinación (manifiesto sin filas, copia sin snapshot, filas parciales)
es un estado ambiguo que no se retoma solo."""
from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Callable

from atlas_core.almacenamiento_portable import SesionOcupadaError, bloqueo_sesion
from atlas_core.ingesta_pdf import separar_identificador_pagina_pdf
from atlas_core.procesamiento_masivo import descubrir_archivos

NUNCA_INICIADA = "NUNCA_INICIADA"
PROCESADA = "PROCESADA"
INICIADA_SIN_RESULTADO = "INICIADA_SIN_RESULTADO"
COPIA_INCOMPLETA = "COPIA_INCOMPLETA"
PARCIAL_SIN_MANIFIESTO = "PARCIAL_SIN_MANIFIESTO"
RECIENTE = "RECIENTE"
VACIA = "VACIA"

RETOMADA = "RETOMADA"
OCUPADA = "OCUPADA"

NOMBRE_SNAPSHOT = "_snapshot_antes.json"
# Un drop en curso en OTRA instancia de Desktop escribe el manifiesto
# segundos después del snapshot; 5 min deja margen holgado sin depender
# de que nadie vuelva a mirar (la recuperación corre al arrancar).
EDAD_MINIMA_SEGUNDOS = 300


def _carpeta_entradas(raiz_atlas: Path) -> Path:
    return raiz_atlas / "operacion" / "entradas"


def _ruta_manifiesto(raiz_atlas: Path, lote: str) -> Path:
    return raiz_atlas / "operacion" / "actual" / "manifiestos_ingesta" / f"{lote}.json"


def _documentos_en_dataset(raiz_atlas: Path) -> set[str]:
    """`archivo` de cada fila, con las páginas PDF reducidas a su PDF."""
    dataset = raiz_atlas / "operacion" / "actual" / "analisis_completo_guias.csv"
    if not dataset.is_file():
        return set()
    with dataset.open("r", newline="", encoding="utf-8-sig") as archivo:
        return {
            separar_identificador_pagina_pdf(str(fila.get("archivo", "")))[0]
            for fila in csv.DictReader(archivo, delimiter=";")
            if fila.get("archivo")
        }


def _snapshot_valido(carpeta: Path) -> bool:
    try:
        json.loads((carpeta / NOMBRE_SNAPSHOT).read_text(encoding="utf-8"))
        return True
    except (OSError, ValueError):
        return False


def _clasificar_lote(
    raiz_atlas: Path, carpeta: Path, documentos: set[str], *, ahora: float, edad_minima_segundos: float,
) -> dict[str, object]:
    archivos = [ruta.relative_to(carpeta).as_posix() for ruta in descubrir_archivos(carpeta)]
    en_dataset = [nombre for nombre in archivos if nombre in documentos]
    salida: dict[str, object] = {
        "lote": carpeta.name, "archivos": archivos, "en_dataset": len(en_dataset),
    }
    if not archivos:
        return {**salida, "estado": VACIA}
    if _ruta_manifiesto(raiz_atlas, carpeta.name).is_file():
        estado = PROCESADA if len(en_dataset) == len(archivos) else INICIADA_SIN_RESULTADO
        return {**salida, "estado": estado}
    if not _snapshot_valido(carpeta):
        return {**salida, "estado": COPIA_INCOMPLETA}
    if en_dataset:
        # Lote histórico (anterior a los manifiestos) o algo parcial: nunca
        # se reingresa a ciegas.
        estado = PROCESADA if len(en_dataset) == len(archivos) else PARCIAL_SIN_MANIFIESTO
        return {**salida, "estado": estado}
    ultima_escritura = max(
        ruta.stat().st_mtime for ruta in [carpeta / NOMBRE_SNAPSHOT, *(carpeta / a for a in archivos)]
    )
    if ahora - ultima_escritura < edad_minima_segundos:
        return {**salida, "estado": RECIENTE}
    return {**salida, "estado": NUNCA_INICIADA}


def clasificar_entradas_desktop(
    raiz_atlas: str | Path, *, ahora: float | None = None,
    edad_minima_segundos: float = EDAD_MINIMA_SEGUNDOS, lote: str | None = None,
) -> list[dict[str, object]]:
    """Sólo lectura: estado de cada lote de `operacion/entradas`."""
    raiz = Path(raiz_atlas)
    carpeta_entradas = _carpeta_entradas(raiz)
    if not carpeta_entradas.is_dir():
        return []
    instante = time.time() if ahora is None else ahora
    documentos = _documentos_en_dataset(raiz)
    carpetas = (
        [carpeta_entradas / lote] if lote is not None
        else sorted(c for c in carpeta_entradas.iterdir() if c.is_dir())
    )
    return [
        _clasificar_lote(raiz, carpeta, documentos, ahora=instante, edad_minima_segundos=edad_minima_segundos)
        for carpeta in carpetas
        if carpeta.is_dir() and carpeta.parent == carpeta_entradas
    ]


def entradas_para_retomar(raiz_atlas: str | Path, **kwargs) -> list[str]:
    return [str(c["lote"]) for c in clasificar_entradas_desktop(raiz_atlas, **kwargs) if c["estado"] == NUNCA_INICIADA]


def retomar_entrada_desktop(
    raiz_atlas: str | Path, lote: str, *, ejecutar: Callable[[Path], object],
    ahora: float | None = None, edad_minima_segundos: float = EDAD_MINIMA_SEGUNDOS,
) -> dict[str, object]:
    """Retoma UNA entrada nunca iniciada con el flujo normal (`ejecutar`
    recibe la carpeta del lote, la misma que Desktop habría procesado).

    Lock por lote + reclasificación DENTRO del lock: dos arranques
    simultáneos nunca procesan el mismo lote (el segundo ve el manifiesto
    que el primero escribió, o el lock ocupado). Si el procesamiento se
    interrumpe después de escribir el manifiesto, el lote pasa a
    INICIADA_SIN_RESULTADO y ya no se retoma solo."""
    raiz = Path(raiz_atlas)
    nombre = str(lote)
    if not nombre or Path(nombre).name != nombre or nombre in (".", ".."):
        return {"lote": nombre, "estado": "LOTE_INVALIDO", "retomada": False}
    carpeta_entradas = _carpeta_entradas(raiz)
    try:
        with bloqueo_sesion(carpeta_entradas, f"retomar_entrada_{nombre}"):
            clasificacion = clasificar_entradas_desktop(
                raiz, ahora=ahora, edad_minima_segundos=edad_minima_segundos, lote=nombre,
            )
            if not clasificacion or clasificacion[0]["estado"] != NUNCA_INICIADA:
                estado = clasificacion[0]["estado"] if clasificacion else "LOTE_INEXISTENTE"
                return {"lote": nombre, "estado": estado, "retomada": False}
            ejecutar(carpeta_entradas / nombre)
            return {**clasificacion[0], "estado": RETOMADA, "retomada": True}
    except SesionOcupadaError:
        return {"lote": nombre, "estado": OCUPADA, "retomada": False}
