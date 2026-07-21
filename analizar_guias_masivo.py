"""CLI para procesar masivamente guías de despacho."""

import argparse
import re
from datetime import date
from pathlib import Path

from atlas_core.procesamiento_masivo import procesar_carpeta


def fecha_iso(valor: str) -> date:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor) is None:
        raise argparse.ArgumentTypeError(
            f"fecha inválida: {valor!r}; use el formato YYYY-MM-DD"
        )
    try:
        return date.fromisoformat(valor)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"fecha inexistente o inválida: {valor!r}"
        ) from error


def crear_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Procesa recursivamente una carpeta de guías y genera un CSV."
    )
    parser.add_argument("carpeta", type=Path, help="Carpeta que contiene las guías")
    parser.add_argument(
        "--salida",
        type=Path,
        default=Path("output/analisis_guias.csv"),
        help="Ruta del CSV de salida",
    )
    parser.add_argument(
        "--reprocesar",
        action="store_true",
        help="Procesa incluso archivos ya presentes en el CSV",
    )
    parser.add_argument(
        "--fecha-desde",
        type=fecha_iso,
        help="Límite inferior inclusivo para fechas (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--fecha-hasta",
        type=fecha_iso,
        help="Límite superior inclusivo para fechas (YYYY-MM-DD)",
    )
    return parser


def main() -> None:
    parser = crear_parser()
    argumentos = parser.parse_args()
    if (
        argumentos.fecha_desde is not None
        and argumentos.fecha_hasta is not None
        and argumentos.fecha_desde > argumentos.fecha_hasta
    ):
        parser.error("--fecha-desde no puede ser posterior a --fecha-hasta")
    resumen = procesar_carpeta(
        argumentos.carpeta,
        argumentos.salida,
        reprocesar=argumentos.reprocesar,
        fecha_desde=argumentos.fecha_desde,
        fecha_hasta=argumentos.fecha_hasta,
    )
    print("\nResumen final")
    print(f"Total encontrados: {resumen['encontrados']}")
    print(f"Procesados: {resumen['procesados']}")
    print(f"Omitidos: {resumen['omitidos']}")
    print(f"Errores: {resumen['errores']}")
    print(f"Barras: {resumen['barras']}")
    print(f"Rollos: {resumen['rollos']}")
    print(f"Mixtos: {resumen['mixtos']}")
    print(f"No determinados: {resumen['no_determinados']}")
    print(f"Tiempo total: {resumen['tiempo_total_segundos']:.2f} segundos")
    print(
        "Promedio por archivo: "
        f"{resumen['promedio_segundos_archivo']:.2f} segundos"
    )


if __name__ == "__main__":
    main()
