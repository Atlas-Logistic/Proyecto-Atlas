"""Clasificación humana, desde Desktop, de la imagen única de una licencia como anverso."""
import argparse
import json

from atlas_core.fichas_choferes import EMPRESA_ACTUAL, clasificar_anverso_licencia_chofer


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--raiz-atlas', required=True)
    parser.add_argument('--ficha-id', required=True)
    parser.add_argument('--referencia-catalogo', required=True)
    parser.add_argument('--documento-id', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--autor', required=True)
    parser.add_argument('--confirmo-revision-humana', action='store_true',
                        help='Obligatorio: la persona vio la imagen y confirma que es el anverso')
    args = parser.parse_args()
    print(json.dumps(clasificar_anverso_licencia_chofer(
        args.raiz_atlas, empresa=EMPRESA_ACTUAL, ficha_id=args.ficha_id,
        referencia_catalogo=args.referencia_catalogo, documento_id=args.documento_id, sha256=args.sha256,
        autor=args.autor, confirmacion_humana=args.confirmo_revision_humana, actor='DESKTOP',
    ), ensure_ascii=True))
