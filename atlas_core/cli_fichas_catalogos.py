"""Bloque CATALOGOS V2 -- CLI invocado por Desktop (IPC `atlas:cargar-
fichas-catalogos`, mismo patrón ya usado para `consultar_atlas.py`:
Desktop hace `spawn('py', ['-3', '-u', ...])` y lee la salida
estándar). Imprime UN solo objeto JSON a stdout -- read-only, sin B1,
sin red (ver `atlas_core.catalogo_fichas`)."""
from __future__ import annotations

import argparse
import json
import sys

from atlas_core.catalogo_fichas import construir_snapshot_fichas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Snapshot de fichas de Catálogos (choferes/clientes/obras/vehículos), sólo lectura.")
    parser.add_argument("--raiz-atlas", required=True, help="Raíz real de Atlas (contiene catalogos_privados/ y operacion/actual/)")
    argumentos = parser.parse_args(argv)
    snapshot = construir_snapshot_fichas(raiz_atlas=argumentos.raiz_atlas)
    # Bloque CATALOGOS V2 -- ensure_ascii=True a propósito, mismo
    # criterio ya usado por cli_consulta_atlas.py: Desktop lee stdout
    # de este proceso vía spawn/pipe, cuya codificación de consola en
    # Windows no siempre es UTF-8 -- escapar a \uXXXX evita corromper
    # tildes/Ñ en vez de depender de la codificación del pipe.
    print(json.dumps(snapshot, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
