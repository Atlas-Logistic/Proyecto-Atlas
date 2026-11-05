"""Modo de publicación del reporte vigente y snapshots explícitos.

``--estado`` informa; ``--rotativo [--conservar N]`` deja de crear un
snapshot permanente por cada cambio (exige registro legible);
``--snapshots`` vuelve al comportamiento anterior; ``--snapshot`` copia el
reporte vigente como snapshot permanente bajo ``reportes/``.
Código de salida: 0 correcto, 2 bloqueado.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from atlas_core.publicacion_reportes import (
    CONSERVAR_DEFECTO, MODO_ROTATIVO, MODO_SNAPSHOTS, configurar, estado_publicacion, snapshot_explicito,
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--raiz", required=True)
    accion = p.add_mutually_exclusive_group(required=True)
    accion.add_argument("--estado", action="store_true")
    accion.add_argument("--rotativo", action="store_true")
    accion.add_argument("--snapshots", action="store_true")
    accion.add_argument("--snapshot", action="store_true", help="Copia permanente del reporte vigente.")
    p.add_argument("--conservar", type=int, default=CONSERVAR_DEFECTO)
    a = p.parse_args(argv)
    try:
        if a.rotativo:
            resultado = configurar(a.raiz, modo=MODO_ROTATIVO, conservar=a.conservar)
        elif a.snapshots:
            resultado = configurar(a.raiz, modo=MODO_SNAPSHOTS, conservar=a.conservar)
        elif a.snapshot:
            destino = snapshot_explicito(a.raiz)
            resultado = {"snapshot": destino.relative_to(Path(a.raiz)).as_posix()}
        else:
            resultado = estado_publicacion(a.raiz)
    except (OSError, ValueError) as error:
        print(json.dumps({"bloqueado": str(error)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
