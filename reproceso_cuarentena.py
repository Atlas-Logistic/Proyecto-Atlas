"""CLI de reproceso aislado; promoción requiere una orden separada."""
from __future__ import annotations
import argparse,json
from atlas_core.reproceso_cuarentena import DocumentoSeleccionado,generar_candidato,promover_candidato
def main():
 p=argparse.ArgumentParser();s=p.add_subparsers(dest="accion",required=True);c=s.add_parser("candidato");c.add_argument("--raiz-atlas",required=True);c.add_argument("--workspace",required=True);c.add_argument("--documento",action="append",required=True);c.add_argument("--cardinalidad",type=int,required=True);c.add_argument("--transporte");q=s.add_parser("promover");q.add_argument("--raiz-atlas",required=True);q.add_argument("--workspace",required=True);a=p.parse_args()
 if a.accion=="candidato":r=generar_candidato(raiz_atlas=a.raiz_atlas,workspace=a.workspace,documentos=[DocumentoSeleccionado(*x.split("=",1)) for x in a.documento],cardinalidad_esperada=a.cardinalidad,transporte_esperado=a.transporte)
 else:r=promover_candidato(raiz_atlas=a.raiz_atlas,workspace=a.workspace)
 print(json.dumps(r,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
