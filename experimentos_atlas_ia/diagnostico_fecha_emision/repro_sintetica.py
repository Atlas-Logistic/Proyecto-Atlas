"""Reproducción sintética del fallo de fecha con etiqueta compacta (sin OCR, sin datos privados).

RapidOCR (camino Mobile/PULL) puede entregar "FECHA DEEMISION" sin espacio. Con
otra fecha distinta en el pie (llegada), el extractor elige esa otra fecha y la
red geométrica se abstiene. Separando la etiqueta, ambas reglas aciertan.

Ejecutar desde la raíz de Motor:
    python -I -B experimentos_atlas_ia/diagnostico_fecha_emision/repro_sintetica.py

Base del diagnóstico: ddcebf4. Salida esperada mientras el defecto exista:
    lineal compacta=02-01-2030  separada=01-01-2030
    geometrica compacta={}  separada=01-01-2030
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from atlas_core.extractor import _extraer_fecha_geometrico  # noqa: E402
from atlas_core.ocr import BloqueOCR  # noqa: E402
from atlas_core.ocr_manual import separar_etiqueta  # noqa: E402
from atlas_core.procesamiento_masivo import extraer_fecha  # noqa: E402

EMISION, LLEGADA = "01-01-2030", "02-01-2030"

# (texto, x0, y0, x1, y1): misma disposición relativa que la guía observada.
# La fecha de salida no aparece (tapada en el original) y "LLEGADA" queda
# separada de "FECHA", como entregó el OCR.
LINEAS = [
    ("FECHA DEEMISION", 346, 1021, 707, 1076),
    (EMISION, 846, 1036, 1116, 1090),
    ("SENOR(ES)", 346, 1080, 600, 1125),
    ("CLIENTE SINTETICO SA", 846, 1085, 1300, 1130),
    ("FECHA", 1836, 2791, 1977, 2841),
    ("FECHA SALIDA", 280, 2812, 568, 2864),
    ("LLEGADA", 1836, 2837, 2023, 2881),
    (LLEGADA, 2081, 2818, 2319, 2860),
]


def _bloques(transformar):
    return [
        BloqueOCR(texto=transformar(t), bounding_box=((x0, y0), (x1, y0), (x1, y1), (x0, y1)), confianza=0.95)
        for t, x0, y0, x1, y1 in LINEAS
    ]


def main():
    identidad = lambda t: t  # noqa: E731
    textos = {n: [transformar(t) for t, *_ in LINEAS] for n, transformar in (("compacta", identidad), ("separada", separar_etiqueta))}
    geo = {n: _extraer_fecha_geometrico(_bloques(f)).get("valor", {}) for n, f in (("compacta", identidad), ("separada", separar_etiqueta))}
    print(f"lineal compacta={extraer_fecha(textos['compacta'])}  separada={extraer_fecha(textos['separada'])}")
    print(f"geometrica compacta={geo['compacta']}  separada={geo['separada']}")


if __name__ == "__main__":
    main()
