"""Alta controlada de licencia de chofer desde Desktop."""
import argparse
import json

from atlas_core.fichas_choferes import EMPRESA_ACTUAL, registrar_licencia_chofer


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--raiz-atlas', required=True)
    parser.add_argument('--ficha-id', required=True)
    parser.add_argument('--referencia-catalogo', required=True)
    parser.add_argument('--vencimiento', required=True)
    parser.add_argument('--clase', required=True)
    parser.add_argument('--archivo', required=True)
    args = parser.parse_args()
    print(json.dumps(registrar_licencia_chofer(
        args.raiz_atlas, empresa=EMPRESA_ACTUAL, ficha_id=args.ficha_id,
        referencia_catalogo=args.referencia_catalogo, vencimiento=args.vencimiento,
        clase=args.clase, archivo_origen=args.archivo, actor='DESKTOP',
    ), ensure_ascii=True))
