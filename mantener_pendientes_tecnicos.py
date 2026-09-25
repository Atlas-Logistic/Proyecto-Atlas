"""Comando focal de mantenimiento; --solo-plan nunca escribe ni hace red."""
from __future__ import annotations

import argparse
import json

from atlas_core.almacenamiento_portable import resolver_raiz_atlas
from atlas_core.mantenimiento_pendientes_tecnicos import mantener_pendientes_tecnicos


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raiz-atlas", required=True)
    parser.add_argument("--solo-plan", action="store_true")
    args = parser.parse_args()
    resultado = mantener_pendientes_tecnicos(
        raiz_atlas=resolver_raiz_atlas(args.raiz_atlas), solo_plan=args.solo_plan,
    )
    print(json.dumps(resultado, ensure_ascii=False))


if __name__ == "__main__":
    main()
