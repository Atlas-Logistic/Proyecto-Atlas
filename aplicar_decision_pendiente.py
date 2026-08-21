"""CLI estrecho usado por Atlas Desktop para aplicar decisiones R3.3/R3.4."""
import argparse
import json
from atlas_core.aplicacion_decisiones import ErrorAplicacionDecision, aplicar_decision_obra

def main():
    # Bloque ORIGEN D1: 3 acciones nuevas de ORIGEN_NO_CONFIRMADO se suman a
    # las ya soportadas; --planta-id-elegida sólo es obligatorio para
    # SELECCIONAR_OTRA_PLANTA (aplicar_decision_obra ya valida eso).
    # Bloque VEHÍCULO D1/E1: USAR_PATENTE_EXISTENTE/SELECCIONAR_OTRA_PATENTE
    # -- --patente-elegida sólo es obligatorio para la segunda;
    # --motivo-rechazo es opcional y sólo se usa con NO_REGISTRAR.
    # MOTOR DE EVIDENCIA FASE 3: CONFIRMAR_ALIAS/RECHAZAR -- primera
    # aplicación real de ALIAS_CANDIDATO (antes sin backend); reutilizan
    # REGISTRAR/NO_REGISTRAR/POSPONER ya existentes para CLIENTE_DESCONOCIDO.
    # Bloque R6 A/B/E: REGISTRAR_DIRECCION se suma a las ya soportadas;
    # --direccion-manual sólo es obligatorio para esa acción (aplicar_
    # decision_obra ya valida eso).
    parser=argparse.ArgumentParser(); parser.add_argument("--raiz-atlas",required=True); parser.add_argument("--decision-id",required=True); parser.add_argument("--accion",choices=("REGISTRAR","NO_REGISTRAR","CONFIRMAR","NO_CONFIRMAR","POSPONER","CONFIRMAR_PLANTA","SELECCIONAR_OTRA_PLANTA","NO_PUEDO_DETERMINAR","USAR_PATENTE_EXISTENTE","SELECCIONAR_OTRA_PATENTE","CONFIRMAR_ALIAS","RECHAZAR","REGISTRAR_DIRECCION"),required=True); parser.add_argument("--tipo-vehiculo",choices=("TRACTO","CARRO","CAMION_RIGIDO")); parser.add_argument("--planta-id-elegida"); parser.add_argument("--patente-elegida"); parser.add_argument("--motivo-rechazo"); parser.add_argument("--direccion-manual")
    args=parser.parse_args()
    try:
        resultado=aplicar_decision_obra(raiz_atlas=args.raiz_atlas,decision_id=args.decision_id,accion=args.accion,tipo_vehiculo=args.tipo_vehiculo,planta_id_elegida=args.planta_id_elegida,patente_elegida=args.patente_elegida,motivo_rechazo=args.motivo_rechazo,direccion_manual=args.direccion_manual)
    except ErrorAplicacionDecision as error:
        resultado={"ok":False,"error":str(error)}
    # Salida ASCII JSON: evita que la consola Windows recodifique los
    # mensajes UTF-8 antes de que Desktop haga JSON.parse. Los escapes JSON
    # se reconstruyen como Unicode correcto en la UI.
    print(json.dumps(resultado, ensure_ascii=True))

if __name__ == "__main__": main()
