"""Resumen de solo lectura para el flujo de imágenes de Atlas Desktop."""

from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from pathlib import Path


def _leer_csv(
    ruta: Path,
    *,
    obligatorio: bool = False,
    columnas_requeridas: set[str] | None = None,
) -> list[dict[str, str]]:
    if not ruta.exists():
        if obligatorio:
            raise FileNotFoundError(f"No existe el CSV requerido: {ruta}")
        return []
    with ruta.open("r", newline="", encoding="utf-8-sig") as archivo:
        lector = csv.DictReader(archivo, delimiter=";")
        if lector.fieldnames is None:
            raise ValueError(f"El CSV está vacío y no contiene encabezado: {ruta}")
        requeridas = columnas_requeridas or {"archivo", "numero_transporte"}
        faltantes = sorted(requeridas - set(lector.fieldnames))
        if faltantes:
            raise ValueError(
                f"Esquema CSV incompatible en {ruta}; faltan: {', '.join(faltantes)}"
            )
        return list(lector)


def comando_snapshot(argumentos: argparse.Namespace) -> None:
    filas = _leer_csv(argumentos.csv_masivo)
    transportes = sorted(
        {
            fila.get("numero_transporte", "").strip()
            for fila in filas
            if fila.get("numero_transporte", "").strip()
        }
    )
    salida = Path(argumentos.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(
        json.dumps({"transportes_existentes": transportes}, ensure_ascii=False),
        encoding="utf-8",
    )


def comando_existentes(argumentos: argparse.Namespace) -> None:
    filas = _leer_csv(argumentos.csv_masivo)
    existentes = {
        fila.get("archivo", "").strip()
        for fila in filas
        if fila.get("archivo", "").strip()
    }
    nombres = list(dict.fromkeys(argumentos.archivo))
    print(json.dumps(
        {"existentes": [nombre for nombre in nombres if nombre in existentes]},
        ensure_ascii=False,
    ))


def comando_reemplazar(argumentos: argparse.Namespace) -> None:
    ruta_masivo = Path(argumentos.csv_masivo)
    ruta_reprocesado = Path(argumentos.csv_reprocesado)
    filas_masivo = _leer_csv(ruta_masivo, obligatorio=True)
    filas_reprocesadas = _leer_csv(ruta_reprocesado, obligatorio=True)
    with ruta_masivo.open("r", newline="", encoding="utf-8-sig") as archivo:
        columnas_masivo = csv.DictReader(archivo, delimiter=";").fieldnames
    with ruta_reprocesado.open("r", newline="", encoding="utf-8-sig") as archivo:
        columnas_reprocesado = csv.DictReader(archivo, delimiter=";").fieldnames
    if columnas_masivo != columnas_reprocesado or columnas_masivo is None:
        raise ValueError("Los CSV de reprocesamiento tienen esquemas incompatibles")

    nombres = [fila.get("archivo", "").strip() for fila in filas_reprocesadas]
    if any(not nombre for nombre in nombres) or len(nombres) != len(set(nombres)):
        raise ValueError("El reprocesamiento debe entregar un resultado único por archivo")
    reemplazados = set(nombres)
    resultado = [
        fila for fila in filas_masivo
        if fila.get("archivo", "").strip() not in reemplazados
    ] + filas_reprocesadas

    ruta_masivo.parent.mkdir(parents=True, exist_ok=True)
    temporal = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig",
            newline="",
            dir=ruta_masivo.parent,
            prefix=f".{ruta_masivo.name}.",
            suffix=".tmp",
            delete=False,
        ) as archivo:
            temporal = Path(archivo.name)
            escritor = csv.DictWriter(
                archivo, fieldnames=columnas_masivo, delimiter=";"
            )
            escritor.writeheader()
            escritor.writerows(resultado)
            archivo.flush()
            os.fsync(archivo.fileno())
        os.replace(temporal, ruta_masivo)
    finally:
        if temporal is not None and temporal.exists():
            temporal.unlink()
    print(json.dumps({"reemplazados": nombres}, ensure_ascii=False))


def comando_resumen(argumentos: argparse.Namespace) -> None:
    filas_masivo = _leer_csv(argumentos.csv_masivo, obligatorio=True)
    por_archivo: dict[str, dict[str, str]] = {}
    for fila in filas_masivo:
        archivo = fila.get("archivo", "").strip()
        if not archivo:
            continue
        anterior = por_archivo.get(archivo)
        transporte = fila.get("numero_transporte", "").strip()
        transporte_anterior = (
            anterior.get("numero_transporte", "").strip() if anterior else ""
        )
        if anterior is None or (not transporte_anterior and transporte):
            por_archivo[archivo] = fila
    snapshot = Path(argumentos.snapshot)
    if not snapshot.exists():
        raise FileNotFoundError(f"No existe el snapshot requerido: {snapshot}")
    antes = set(
        json.loads(snapshot.read_text(encoding="utf-8")).get(
            "transportes_existentes", []
        )
    )
    reporte = Path(argumentos.reporte)
    viajes = _leer_csv(
        reporte / "viajes.csv",
        obligatorio=True,
        columnas_requeridas={"numero_transporte", "documentos", "estado", "numeros_guia"},
    )
    sin_transporte = _leer_csv(
        reporte / "documentos_sin_transporte.csv", obligatorio=True
    )
    archivos_sin_transporte = {
        fila["archivo"] for fila in sin_transporte if fila.get("archivo", "").strip()
    }

    resultados = []
    nombres = list(dict.fromkeys(argumentos.archivo))
    for nombre in nombres:
        fila = por_archivo.get(nombre)
        if fila is None:
            resultados.append({"archivo": nombre, "encontrado": False})
            continue
        transporte = fila.get("numero_transporte", "").strip()
        viaje_encontrado = next(
            (
                viaje
                for viaje in viajes
                if nombre
                in [d.strip() for d in viaje.get("documentos", "").split("|")]
            ),
            None,
        )
        if not transporte or (
            nombre in archivos_sin_transporte and viaje_encontrado is None
        ):
            resultados.append(
                {
                    "archivo": nombre,
                    "encontrado": True,
                    "sin_transporte": True,
                    "numero_transporte": transporte,
                }
            )
            continue
        resultados.append(
            {
                "archivo": nombre,
                "encontrado": True,
                "sin_transporte": False,
                "numero_transporte": transporte,
                "es_nuevo": transporte not in antes,
                "estado": (
                    viaje_encontrado.get("estado") if viaje_encontrado else None
                ),
                "numeros_guia": (
                    viaje_encontrado.get("numeros_guia")
                    if viaje_encontrado
                    else None
                ),
            }
        )
    print(json.dumps(resultados, ensure_ascii=False))


def crear_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcomandos = parser.add_subparsers(dest="comando", required=True)
    snapshot = subcomandos.add_parser("snapshot")
    snapshot.add_argument("--csv-masivo", type=Path, required=True)
    snapshot.add_argument("--salida", type=Path, required=True)
    snapshot.set_defaults(func=comando_snapshot)
    existentes = subcomandos.add_parser("existentes")
    existentes.add_argument("--csv-masivo", type=Path, required=True)
    existentes.add_argument("--archivo", action="append", required=True)
    existentes.set_defaults(func=comando_existentes)
    reemplazar = subcomandos.add_parser("reemplazar")
    reemplazar.add_argument("--csv-masivo", type=Path, required=True)
    reemplazar.add_argument("--csv-reprocesado", type=Path, required=True)
    reemplazar.set_defaults(func=comando_reemplazar)
    resumen = subcomandos.add_parser("resumen")
    resumen.add_argument("--csv-masivo", type=Path, required=True)
    resumen.add_argument("--reporte", type=Path, required=True)
    resumen.add_argument("--snapshot", type=Path, required=True)
    resumen.add_argument("--archivo", action="append", required=True)
    resumen.set_defaults(func=comando_resumen)
    return parser


def main() -> None:
    argumentos = crear_parser().parse_args()
    argumentos.func(argumentos)


if __name__ == "__main__":
    main()
