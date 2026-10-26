"""Inicializa/migra sólo el almacén complementario; no carga archivos."""
import argparse
import json
from atlas_core.fichas_choferes import EMPRESA_ACTUAL, inicializar_almacen


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--raiz-atlas', required=True)
    parser.add_argument('--actor', required=True)
    parser.add_argument('--vinculo', action='append', default=[], help='Clave anterior=actual; explícito, sin matching nominal')
    args = parser.parse_args()
    vinculos = dict(v.split('=', 1) for v in args.vinculo)
    print(json.dumps(inicializar_almacen(args.raiz_atlas, empresa=EMPRESA_ACTUAL,
                                        actor=args.actor, vinculos=vinculos), ensure_ascii=True))
