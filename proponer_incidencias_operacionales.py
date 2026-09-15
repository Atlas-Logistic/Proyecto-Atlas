"""CLI estrecho usado por Atlas Desktop para proponer un lote de
incidencias operacionales a partir de texto libre -- V1.2, última milla
sobre atlas_core.gestion_incidencias_conversacional.proponer_lote_
incidencias (V1.1, ya aprobado, sin cambios).

SOLO LECTURA / PREVIEW: esta llamada NUNCA escribe eventos_operacionales.
json ni ningún otro archivo -- interpreta el texto y arma el preview
(guía, transporte, chofer, cliente, tipo, acción, estado de gestión,
errores/ambiguos) para que un humano lo revise ANTES de confirmar. La
confirmación real vive en `confirmar_incidencias_operacionales.py`, un
CLI SEPARADO que nunca reinterpreta texto (ver su propio docstring)."""
from __future__ import annotations

import argparse
import json
import sys

from atlas_core.gestion_incidencias_conversacional import proponer_lote_incidencias


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("texto")
    parser.add_argument("--raiz-atlas", required=True, help="Raíz de datos Atlas (para eventos_operacionales.json ya existentes).")
    parser.add_argument("--viajes", required=True, help="Ruta a viajes.csv del reporte vigente.")
    args = parser.parse_args(argv)

    try:
        resultado = proponer_lote_incidencias(
            texto=args.texto, raiz=args.raiz_atlas, ruta_viajes=args.viajes,
        )
    except Exception as error:  # nunca deja el proceso sin salida JSON parseable
        # Salida ASCII JSON: evita que la consola Windows recodifique los
        # mensajes UTF-8 antes de que Desktop haga JSON.parse (mismo
        # criterio ya establecido en aplicar_decision_pendiente.py).
        print(json.dumps({"ok": False, "error": f"No se pudo proponer el lote: {error}"}, ensure_ascii=True))
        return 1

    print(json.dumps({"ok": True, **resultado}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
