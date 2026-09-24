"""CLI del bloque REPROCESAMIENTO_REPARADOR -- reparación focal de un
lote de ingesta ya persistido. Por defecto corre en modo dry-run (no
escribe nada); requiere `--ejecutar` explícito para persistir cambios y
disparar la reconciliación canónica (`revalidar_y_regenerar_reporte`)."""
import argparse
import json

from atlas_core.reprocesamiento_reparador import reprocesar_lote_reparador


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raiz-atlas", required=True)
    parser.add_argument("--lote", default=None, help="Nombre del manifiesto; por defecto el más reciente")
    parser.add_argument("--ejecutar", action="store_true", help="Persiste los cambios (sin esto: dry-run)")
    args = parser.parse_args()

    resultado = reprocesar_lote_reparador(
        raiz_atlas=args.raiz_atlas, nombre_lote=args.lote, dry_run=not args.ejecutar,
    )
    print(json.dumps(resultado, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
