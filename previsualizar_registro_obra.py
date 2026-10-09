"""CLI de sólo lectura usado por Atlas Desktop: vista previa del registro
completo de una obra nueva (obra + destino) antes de aplicar REGISTRAR.
Nunca escribe nada -- ver `atlas_core.registro_obra_destino`."""
import argparse
import json

from atlas_core.registro_obra_destino import ErrorRegistroObraDestino, previsualizar_registro_obra_destino


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raiz-atlas", required=True)
    parser.add_argument("--decision-id", required=True)
    parser.add_argument("--nombre-obra-manual")
    args = parser.parse_args()
    try:
        resultado = previsualizar_registro_obra_destino(
            raiz_atlas=args.raiz_atlas, decision_id=args.decision_id,
            nombre_obra_manual=args.nombre_obra_manual,
        )
    except (ErrorRegistroObraDestino, OSError, ValueError) as error:
        resultado = {"ok": False, "error": str(error)}
    # Salida ASCII JSON, mismo contrato que `aplicar_decision_pendiente.py`.
    print(json.dumps(resultado, ensure_ascii=True))


if __name__ == "__main__":
    main()
