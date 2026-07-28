"""CLI segura para generar una bandeja de revisión de destinos."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from atlas_core.inteligencia.revision_destinos import (
    ConfiguracionRevisionDestinos,
    ProveedorRespuestasCongeladas,
    ejecutar_archivo,
)
from atlas_core.inteligencia.verificacion_destinos import (
    VerificadorDestinosOpenRouteService,
)


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entrada", type=Path, required=True)
    parser.add_argument("--salida", type=Path, required=True)
    parser.add_argument("--permitir-consultas", action="store_true")
    parser.add_argument("--max-consultas", type=int, default=0)
    parser.add_argument("--usar-cache", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--solo-cache", action="store_true")
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument(
        "--proveedor", choices=("ninguno", "ors", "respuestas-congeladas"),
        default="ninguno",
    )
    parser.add_argument("--respuestas-congeladas", type=Path)
    parser.add_argument("--fecha-evaluacion")
    return parser


def main(argv=None) -> int:
    args = construir_parser().parse_args(argv)
    configuracion = ConfiguracionRevisionDestinos(
        permitir_consultas=args.permitir_consultas,
        max_consultas=args.max_consultas,
        usar_cache=args.usar_cache,
        solo_cache=args.solo_cache,
        timeout=args.timeout,
        proveedor=args.proveedor,
    )
    proveedor = None
    if args.proveedor == "respuestas-congeladas":
        if args.respuestas_congeladas is None:
            raise SystemExit("--respuestas-congeladas es obligatorio")
        proveedor = ProveedorRespuestasCongeladas(args.respuestas_congeladas)
    elif args.proveedor == "ors":
        if not args.permitir_consultas or args.max_consultas <= 0 or args.solo_cache:
            raise SystemExit("ORS requiere autorización, máximo positivo y no solo-cache")
        proveedor = VerificadorDestinosOpenRouteService(
            api_key=os.getenv("OPENROUTESERVICE_API_KEY", ""),
            timeout=args.timeout,
            limite_consultas=args.max_consultas,
            usar_cache=args.usar_cache,
        )
    fecha = (
        datetime.fromisoformat(args.fecha_evaluacion)
        if args.fecha_evaluacion else None
    )
    resultado = ejecutar_archivo(
        args.entrada, args.salida, configuracion=configuracion,
        proveedor=proveedor, fecha_evaluacion=fecha,
    )
    print(json.dumps(dict(resultado.resumen), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
