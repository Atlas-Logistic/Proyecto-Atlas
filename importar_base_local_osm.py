#!/usr/bin/env python
"""CLI de conveniencia -- importador OFFLINE OSM/PBF -> base local Atlas (RM).

Equivalente a `python -m atlas_core.geografia.importador_osm`. Herramienta
PERIFÉRICA: el Motor en operación nunca la ejecuta ni necesita `osmium`.

Ejemplos:
    python importar_base_local_osm.py --pbf region-metropolitana.osm.pbf --reemplazar
    python importar_base_local_osm.py --pbf muestra.osm --salida /tmp/rm.sqlite --dry-run
"""
from __future__ import annotations

import sys

from atlas_core.geografia.importador_osm import main

if __name__ == "__main__":
    sys.exit(main())
