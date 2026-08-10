"""CLI para generar reportes de viajes compatibles con Atlas Desktop."""

from __future__ import annotations

import argparse
from pathlib import Path

from atlas_core.reporte_viajes import generar_reporte_viajes


def crear_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Agrupa un CSV masivo Atlas de 15 o 21 columnas y publica "
            "un reporte para Atlas Desktop."
        )
    )
    parser.add_argument("csv", type=Path, help="CSV producido por procesamiento_masivo")
    parser.add_argument("salida", type=Path, help="Directorio nuevo para el reporte")
    parser.add_argument(
        "--catalogos",
        type=Path,
        default=Path("catalogos"),
        help="Carpeta de catálogos (predeterminado: catalogos)",
    )
    return parser


def main() -> None:
    argumentos = crear_parser().parse_args()
    manifest = generar_reporte_viajes(
        argumentos.csv,
        argumentos.salida,
        carpeta_catalogos=argumentos.catalogos,
    )
    totales = manifest["totales"]
    print("Reporte de viajes generado")
    print(f"Filas leídas: {totales['filas_leidas']}")
    print(f"Viajes identificados: {totales['viajes']}")
    print(f"  Confirmados: {totales['viajes_confirmados']}")
    print(f"  Requieren revisión: {totales['viajes_requieren_revision']}")
    print(f"Documentos sin transporte: {totales['documentos_sin_transporte']}")
    print(f"Salida: {argumentos.salida}")


if __name__ == "__main__":
    main()
