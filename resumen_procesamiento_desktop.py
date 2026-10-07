"""Resumen de solo lectura para el flujo de imágenes de Atlas Desktop."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from atlas_core.evidencia_documental import leer_registro_relecturas
from atlas_core.ingesta_pdf import directorio_evidencia_pdf_para_dataset, leer_evidencias_adicionales
from atlas_core.investigacion_documental import raiz_desde_actual


# Mismo criterio que `atlas_core.mobile`, `acciones_operacionales` y
# `consultas_atlas`: el dataset operacional conserva evidencia por fila que
# puede superar el límite por defecto de ``csv`` (131072 caracteres); ese
# límite no es una regla de Atlas. Se baja sólo si la plataforma no admite
# ``sys.maxsize``.
def _configurar_limite_campo_csv() -> int:
    limite = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limite)
            return limite
        except OverflowError:
            limite //= 10


LIMITE_CAMPO_CSV = _configurar_limite_campo_csv()


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

    # Un PDF genera filas por página (`<pdf>::pagina=NNNN`); una página de
    # una guía+transporte ya existente no crea fila, pero puede quedar como
    # evidencia adicional del documento existente (ver `atlas_core.
    # ingesta_pdf.registrar_evidencia_adicional`).
    evidencias_adicionales = leer_evidencias_adicionales(
        directorio_evidencia_pdf_para_dataset(argumentos.csv_masivo)
    )

    # Relectura (foto nueva de un documento ya ingresado, ver
    # `procesamiento_masivo.detectar_relectura`): el lote de este arrastre
    # es la carpeta del snapshot.
    raiz_atlas = raiz_desde_actual(Path(argumentos.csv_masivo).parent)
    relecturas = leer_registro_relecturas(raiz_atlas)["documentos"] if raiz_atlas is not None else {}
    lote = snapshot.parent.name

    def relectura_de(archivo: str) -> dict[str, object] | None:
        historial = (relecturas.get(archivo) or {}).get("historial") or []
        entrada = next((h for h in reversed(historial) if h.get("lote") == lote), None)
        if entrada is None:
            return None
        return {
            "resultado": entrada.get("resultado"), "motivo": entrada.get("motivo", ""),
            "campos_cambiados": sorted((entrada.get("cambios") or {}).keys()),
        }

    def viaje_de(archivo: str) -> dict[str, str] | None:
        return next(
            (
                viaje
                for viaje in viajes
                if archivo
                in [d.strip() for d in viaje.get("documentos", "").split("|")]
            ),
            None,
        )

    def resultado_fila(archivo: str, fila: dict[str, str]) -> dict[str, object]:
        transporte = fila.get("numero_transporte", "").strip()
        viaje_encontrado = viaje_de(archivo)
        if not transporte or (
            archivo in archivos_sin_transporte and viaje_encontrado is None
        ):
            return {
                "archivo": archivo,
                "encontrado": True,
                "sin_transporte": True,
                "numero_transporte": transporte,
            }
        return {
            "archivo": archivo,
            "encontrado": True,
            "sin_transporte": False,
            "numero_transporte": transporte,
            "es_nuevo": transporte not in antes,
            "estado": viaje_encontrado.get("estado") if viaje_encontrado else None,
            "numeros_guia": (
                viaje_encontrado.get("numeros_guia") if viaje_encontrado else None
            ),
        }

    resultados = []
    nombres = list(dict.fromkeys(argumentos.archivo))
    for nombre in nombres:
        archivos = sorted(
            archivo
            for archivo in por_archivo
            if archivo == nombre or archivo.startswith(nombre + "::pagina=")
        )
        if archivos:
            for a in archivos:
                resultado = resultado_fila(a, por_archivo[a])
                relectura = relectura_de(a)
                if relectura is not None:
                    resultado["relectura"] = relectura
                resultados.append(resultado)
            continue
        asociadas = [
            e for e in evidencias_adicionales
            if e.get("evidencia", {}).get("referencia_original") == nombre
        ]
        if asociadas:
            for asociacion in asociadas:
                documento = asociacion.get("documento", {})
                resultado = resultado_fila(
                    str(documento.get("archivo", "")),
                    {"numero_transporte": str(documento.get("numero_transporte", ""))},
                )
                resultado.update(
                    archivo=str(asociacion.get("evidencia", {}).get("archivo", nombre)),
                    evidencia_adicional_de=str(documento.get("archivo", "")),
                )
                resultados.append(resultado)
            continue
        resultados.append({"archivo": nombre, "encontrado": False})
    print(json.dumps(resultados, ensure_ascii=False))


def crear_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcomandos = parser.add_subparsers(dest="comando", required=True)
    snapshot = subcomandos.add_parser("snapshot")
    snapshot.add_argument("--csv-masivo", type=Path, required=True)
    snapshot.add_argument("--salida", type=Path, required=True)
    snapshot.set_defaults(func=comando_snapshot)
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
