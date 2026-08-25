"""CLI estrecho usado por Atlas Desktop para Consultas Atlas V1 -- pregunta
natural sobre la operación real, read-only. Ver atlas_core.cli_consulta_atlas
(interpretación + validación + ejecución determinística)."""
import sys
from atlas_core.cli_consulta_atlas import main

if __name__ == "__main__":
    sys.exit(main())
