"""CLI para generar reportes de viajes compatibles con Atlas Desktop."""

from __future__ import annotations

import argparse
from pathlib import Path

from atlas_core.almacenamiento_portable import escribir_estado_operacion
from atlas_core.aplicacion_decisiones import LEDGER
from atlas_core.reporte_viajes import _sha256_archivo, generar_reporte_viajes
from atlas_core.decisiones_pendientes import NOMBRE_ARTEFACTO


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
    # Bloque CONSISTENCIA OPERACIONAL, Sección 3 -- publicación
    # VERSIONADA: se captura la huella del CSV justo ANTES de generar el
    # reporte y se vuelve a comprobar justo DESPUÉS -- si otra operación
    # real (el servidor Mobile, una decisión aplicada desde Desktop) lo
    # cambió mientras este comando corría, el manifiesto no se publica
    # como vigente con datos que ya quedaron desalineados.
    huella_para_publicar = _sha256_archivo(argumentos.csv) if argumentos.csv.is_file() else None
    manifest = generar_reporte_viajes(
        argumentos.csv,
        argumentos.salida,
        carpeta_catalogos=argumentos.catalogos,
        ruta_ledger=argumentos.csv.parent / LEDGER,
    )
    totales = manifest["totales"]
    print("Reporte de viajes generado")
    print(f"Filas leídas: {totales['filas_leidas']}")
    print(f"Viajes identificados: {totales['viajes']}")
    print(f"  Confirmados: {totales['viajes_confirmados']}")
    print(f"  Requieren revisión: {totales['viajes_requieren_revision']}")
    print(f"Documentos sin transporte: {totales['documentos_sin_transporte']}")
    print(f"Salida: {argumentos.salida}")

    # INFRAESTRUCTURA S2.2: publica/actualiza el manifiesto portable de
    # operación vigente para que Atlas Desktop (o cualquier otro PC con
    # Drive sincronizado) lo descubra sin depender de "la carpeta más
    # reciente". Best-effort y silencioso: si `--salida`/`csv` no viven
    # dentro de la raíz portable (uso local/de desarrollo, comportamiento
    # de siempre), simplemente no se publica nada -- nunca rompe la
    # generación del reporte, que ya terminó con éxito arriba.
    huella_tras_reporte = _sha256_archivo(argumentos.csv) if argumentos.csv.is_file() else None
    if huella_tras_reporte != huella_para_publicar:
        print(
            "(El CSV cambió mientras se generaba el reporte -- no se publica como manifiesto "
            "vigente; el reporte igual quedó escrito en la carpeta de salida.)"
        )
        return
    try:
        ruta_decisiones = argumentos.csv.parent / NOMBRE_ARTEFACTO
        escribir_estado_operacion(
            reporte_vigente=argumentos.salida,
            dataset_operacional=argumentos.csv,
            decisiones_pendientes=(ruta_decisiones if ruta_decisiones.is_file() else None),
            dataset_sha256=huella_para_publicar,
        )
    except OSError as error:
        print(f"(No se pudo publicar el manifiesto de operación vigente: {error})")


if __name__ == "__main__":
    main()
