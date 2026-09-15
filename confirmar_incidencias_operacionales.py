"""CLI estrecho usado por Atlas Desktop para confirmar/aplicar un lote de
incidencias operacionales YA PREVISUALIZADO -- V1.2, última milla sobre
atlas_core.gestion_incidencias_conversacional.confirmar_lote_incidencias
(V1.1, ya aprobado, sin cambios).

CONTRATO DE SEGURIDAD (deliberado, no negociable): este CLI NUNCA recibe
ni interpreta texto libre -- sólo `--acciones`, la lista JSON EXACTA que
`proponer_incidencias_operacionales.py` ya devolvió y que Desktop ya
mostró al humano. Es estructuralmente imposible que este proceso
reinterprete la instrucción y aplique algo distinto de lo que se
previsualizó: no importa `interpretador_incidencias_operacionales` en
absoluto. `confirmar_lote_incidencias` (Motor) igual re-valida cada guía
contra el reporte vigente antes de escribir (nunca aplica una guía
NO_ENCONTRADA/AMBIGUA aunque el JSON de entrada la incluya) e idempotente
por diseño (reintentar el mismo lote nunca duplica)."""
from __future__ import annotations

import argparse
import json
import sys

from atlas_core.gestion_incidencias_conversacional import confirmar_lote_incidencias


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raiz-atlas", required=True)
    parser.add_argument("--viajes", required=True, help="Ruta a viajes.csv del reporte vigente.")
    parser.add_argument(
        "--acciones", required=True,
        help="JSON (lista) con las acciones EXACTAS que devolvió el preview -- nunca texto libre.",
    )
    parser.add_argument("--actor", required=True)
    # Bloque V1.2 -- store_true: ausente equivale a `confirmado=False`, el
    # mismo "sólo preview, nunca escribe" que ya garantiza `aplicar_lote`
    # (Motor) para cualquier caller que no pase esta bandera.
    parser.add_argument("--confirmado", action="store_true")
    args = parser.parse_args(argv)

    try:
        acciones = json.loads(args.acciones)
        if not isinstance(acciones, list):
            raise ValueError("--acciones debe ser una lista JSON de acciones.")
        resultado = confirmar_lote_incidencias(
            raiz=args.raiz_atlas, ruta_viajes=args.viajes, acciones=acciones,
            actor=args.actor, confirmado=args.confirmado,
        )
    except Exception as error:
        print(json.dumps({"ok": False, "error": f"No se pudo confirmar el lote: {error}"}, ensure_ascii=True))
        return 1

    print(json.dumps({"ok": True, **resultado}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
