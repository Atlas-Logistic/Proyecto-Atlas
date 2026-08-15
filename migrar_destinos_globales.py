import argparse,json
from atlas_core.migracion_destinos_globales import migrar_destinos_globales
def main():
 p=argparse.ArgumentParser();p.add_argument("--destinos",required=True);p.add_argument("--obras-destinos",required=True);p.add_argument("--respaldos",required=True);a=p.parse_args();print(json.dumps(migrar_destinos_globales(ruta_destinos=a.destinos,ruta_obras_destinos=a.obras_destinos,carpeta_respaldos=a.respaldos),ensure_ascii=False,indent=2))
if __name__=="__main__":main()
