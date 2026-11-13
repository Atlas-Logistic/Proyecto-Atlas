"""Confirmación humana de una licencia ya registrada, desde Desktop."""
import argparse
import json

from atlas_core.fichas_choferes import EMPRESA_ACTUAL, confirmar_licencia_chofer


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--raiz-atlas', required=True)
    parser.add_argument('--ficha-id', required=True)
    parser.add_argument('--referencia-catalogo', required=True)
    parser.add_argument('--documento-id', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--rut', required=True)
    parser.add_argument('--nombre', required=True)
    # Una clase (--clase A2) o varias, cada una individual (--clases A2,A5). «A2-A5» no se interpreta como rango.
    clases = parser.add_mutually_exclusive_group(required=True)
    clases.add_argument('--clase')
    clases.add_argument('--clases', help='Clases separadas por coma, p. ej. A2,A5')
    parser.add_argument('--vencimiento', required=True)
    parser.add_argument('--autor', required=True)
    parser.add_argument('--confirmo-revision-humana', action='store_true',
                        help='Obligatorio: la persona revisó la licencia y confirma estos datos')
    args = parser.parse_args()
    print(json.dumps(confirmar_licencia_chofer(
        args.raiz_atlas, empresa=EMPRESA_ACTUAL, ficha_id=args.ficha_id,
        referencia_catalogo=args.referencia_catalogo, documento_id=args.documento_id, sha256=args.sha256,
        rut=args.rut, nombre=args.nombre, clase=args.clases if args.clases is not None else args.clase, vencimiento=args.vencimiento,
        autor=args.autor, confirmacion_humana=args.confirmo_revision_humana, actor='DESKTOP',
    ), ensure_ascii=True))
