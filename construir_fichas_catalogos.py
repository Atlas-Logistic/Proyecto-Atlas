"""CLI estrecho usado por Atlas Desktop para Catálogos V2 -- snapshot de
fichas de entidades (choferes/clientes/obras/vehículos), read-only. Ver
atlas_core.cli_fichas_catalogos."""
import sys
from atlas_core.cli_fichas_catalogos import main

if __name__ == "__main__":
    sys.exit(main())
