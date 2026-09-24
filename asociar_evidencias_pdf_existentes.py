"""Asocia como evidencia adicional las páginas PDF de un lote Desktop YA
ingresado cuya guía+transporte ya existía (reingesta omitida), sin OCR ni
reingesta. Mismas validaciones y mismo registro que la ingesta actual (ver
`atlas_core.procesamiento_masivo.asociar_evidencias_pdf_de_lote`).

Por defecto es una SIMULACIÓN (no escribe nada); `--aplicar` registra.
Nunca modifica el dataset, filas, viajes, estados ni fechas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from atlas_core.almacenamiento_portable import resolver_raiz_atlas
from atlas_core.procesamiento_masivo import asociar_evidencias_pdf_de_lote


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raiz-atlas", type=Path)
    parser.add_argument("--lote", required=True, help="Carpeta de operacion/entradas (p. ej. 20260923_152801)")
    parser.add_argument("--aplicar", action="store_true", help="Registra la asociación (sin esto: simulación)")
    args = parser.parse_args()
    resultado = asociar_evidencias_pdf_de_lote(
        raiz_atlas=resolver_raiz_atlas(args.raiz_atlas), lote=args.lote, aplicar=args.aplicar,
    )
    print(json.dumps(resultado, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
