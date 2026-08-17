"""CLI estrecho usado por Atlas Desktop para aplicar decisiones R3.3/R3.4."""
import argparse
import json
from atlas_core.aplicacion_decisiones import ErrorAplicacionDecision, aplicar_decision_obra

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--raiz-atlas",required=True); parser.add_argument("--decision-id",required=True); parser.add_argument("--accion",choices=("REGISTRAR","NO_REGISTRAR","CONFIRMAR","NO_CONFIRMAR","POSPONER"),required=True)
    args=parser.parse_args()
    try:
        resultado=aplicar_decision_obra(raiz_atlas=args.raiz_atlas,decision_id=args.decision_id,accion=args.accion)
    except ErrorAplicacionDecision as error:
        resultado={"ok":False,"error":str(error)}
    print(json.dumps(resultado,ensure_ascii=False))

if __name__ == "__main__": main()
