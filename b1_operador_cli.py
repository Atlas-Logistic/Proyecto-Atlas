"""CLI estrecho de B1 OPERADOR: un turno de conversación.

    b1_operador_cli.py --raiz-atlas R --conversacion ID --texto "Pizarro usa JF9575"
    b1_operador_cli.py --raiz-atlas R --conversacion ID --texto "sí"

El estado del preview pendiente vive en el Motor (por conversación); el
llamador sólo reenvía texto. Salida JSON ASCII (mismo criterio que los
demás CLIs usados por Desktop)."""
import argparse
import json

from atlas_core.almacenamiento_portable import resolver_raiz_atlas
from atlas_core.b1_operador import OperadorB1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raiz-atlas")
    parser.add_argument("--conversacion", required=True)
    parser.add_argument("--texto", required=True)
    parser.add_argument("--usuario", default="JAVIER")
    args = parser.parse_args(argv)
    operador = OperadorB1(resolver_raiz_atlas(args.raiz_atlas), usuario=args.usuario)
    respuesta = operador.atender(args.conversacion, args.texto)
    print(json.dumps(respuesta, ensure_ascii=True, default=str))
    return 1 if respuesta.get("estado") in {"RECHAZADA", "FALLIDA"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
