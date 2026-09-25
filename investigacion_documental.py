"""Cuarentena reversible EN_INVESTIGACION de un documento (ver
atlas_core/investigacion_documental.py). `listar` es read-only.

  python investigacion_documental.py --raiz-atlas X poner --archivo A --actor Y --motivo M --referencia R
  python investigacion_documental.py --raiz-atlas X levantar --archivo A --actor Y --motivo M
  python investigacion_documental.py --raiz-atlas X listar
"""
from __future__ import annotations

import argparse
import json

from atlas_core.almacenamiento_portable import resolver_raiz_atlas
from atlas_core.investigacion_documental import (
    archivos_en_investigacion, leer_registro, levantar_investigacion, poner_en_investigacion,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raiz-atlas", required=True)
    sub = parser.add_subparsers(dest="comando", required=True)
    poner = sub.add_parser("poner")
    levantar = sub.add_parser("levantar")
    for p in (poner, levantar):
        p.add_argument("--archivo", required=True)
        p.add_argument("--actor", required=True)
        p.add_argument("--motivo", required=True)
    poner.add_argument("--referencia", default="")
    sub.add_parser("listar")
    args = parser.parse_args()
    raiz = resolver_raiz_atlas(args.raiz_atlas)
    if args.comando == "poner":
        resultado = poner_en_investigacion(
            raiz_atlas=raiz, archivo=args.archivo, actor=args.actor, motivo=args.motivo,
            referencia_investigacion=args.referencia,
        )
    elif args.comando == "levantar":
        resultado = levantar_investigacion(raiz_atlas=raiz, archivo=args.archivo, actor=args.actor, motivo=args.motivo)
    else:
        registros = leer_registro(raiz)["registros"]
        resultado = {
            "activos_vigentes": sorted(archivos_en_investigacion(raiz)),
            "registros": [{k: v for k, v in r.items() if k != "decisiones_retenidas"}
                          | {"decisiones_retenidas": [d.get("decision_id") for d in r.get("decisiones_retenidas", [])]}
                          for r in registros],
        }
    print(json.dumps(resultado, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
