"""Reconcilia proyecciones persistidas con la lógica vigente, sin OCR."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from atlas_core.reconciliacion_estado_derivado import reconciliar_estado_derivado


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raiz-atlas", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(reconciliar_estado_derivado(raiz_atlas=args.raiz_atlas), ensure_ascii=False))


if __name__ == "__main__":
    main()
