"""Migración explícita (primero simulación) del registro operacional Atlas."""
from __future__ import annotations
import argparse, json
from atlas_core.registro_relaciones_operacionales import migrar_reportes_historicos

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--raiz", required=True)
    p.add_argument("--empresa", default="oficina")
    p.add_argument("--aplicar", action="store_true", help="Escribe sólo si ningún reporte es ilegible.")
    a = p.parse_args()
    print(json.dumps(migrar_reportes_historicos(a.raiz, empresa_id=a.empresa, aplicar=a.aplicar), ensure_ascii=False, indent=2))
