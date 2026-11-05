import argparse, json
from pathlib import Path
from atlas_core.revision_mobile import registrar

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--raiz-atlas', type=Path, required=True)
    p.add_argument('--envio-id', required=True)
    p.add_argument('--sha256', required=True)
    p.add_argument('--accion', choices=['DESCARTAR','REVERTIR'], required=True)
    p.add_argument('--supervisor', required=True)
    a = p.parse_args()
    print(json.dumps(registrar(a.raiz_atlas, a.envio_id, a.sha256, a.accion, a.supervisor)))
if __name__ == '__main__': main()
