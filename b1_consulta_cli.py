"""Entrada B1 exclusivamente lectora, sin confirmaciones ni persistencia."""
import argparse
import json
from atlas_core.b1_operador import OperadorB1

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raiz-atlas', required=True)
    parser.add_argument('--texto', required=True)
    args = parser.parse_args()
    print(json.dumps(OperadorB1(args.raiz_atlas).consultar(args.texto), ensure_ascii=True))

if __name__ == '__main__':
    main()
