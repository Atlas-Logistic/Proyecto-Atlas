"""CLI de sólo lectura productiva: python investigar_revision_b1.py GUIA [--salida JSON]."""
import argparse
import json
from pathlib import Path

from atlas_core.atlas_ia.investigacion_revision import investigar_revision


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("guia")
    parser.add_argument("--raiz-atlas", type=Path)
    parser.add_argument("--salida", type=Path)
    args = parser.parse_args()
    resultado = investigar_revision(args.guia, raiz_atlas=args.raiz_atlas)
    texto = json.dumps(resultado, ensure_ascii=False, indent=2, sort_keys=True)
    if args.salida:
        args.salida.parent.mkdir(parents=True, exist_ok=True)
        args.salida.write_text(texto + "\n", encoding="utf-8")
    else:
        print(texto)


if __name__ == "__main__":
    main()
