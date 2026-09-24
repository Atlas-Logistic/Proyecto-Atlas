"""CLI del bloque REVALIDACIÓN POR TRANSPORTE -- revalida los documentos
ya persistidos de UN `numero_transporte` reextrayéndolos contra su imagen
original (mismo pipeline real, nunca un segundo motor OCR). Por defecto
corre en modo dry-run (no escribe nada); requiere `--ejecutar` explícito
para persistir cambios y disparar la reconciliación canónica
(`revalidar_y_regenerar_reporte`). Mecanismo genérico para cualquier
transporte -- nunca un script puntual para un caso."""
import argparse
import json

from atlas_core.reprocesamiento_reparador import revalidar_documentos_por_transporte


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raiz-atlas", required=True)
    parser.add_argument("--numero-transporte", required=True)
    parser.add_argument("--ejecutar", action="store_true", help="Persiste los cambios (sin esto: dry-run)")
    args = parser.parse_args()

    resultado = revalidar_documentos_por_transporte(
        raiz_atlas=args.raiz_atlas, numero_transporte=args.numero_transporte, dry_run=not args.ejecutar,
    )
    print(json.dumps(resultado, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
