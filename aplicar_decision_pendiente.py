"""CLI estrecho usado por Atlas Desktop para aplicar decisiones R3.3/R3.4."""
import argparse
import json
from atlas_core.aplicacion_decisiones import DecisionObsoletaError, ErrorAplicacionDecision, aplicar_decision_obra

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
    # decision_obra ya valida eso). Bloque REGISTRO_DIRECCION CONTEXTO:
    # --comuna-manual es SIEMPRE opcional para REGISTRAR_DIRECCION --
    # Atlas intenta resolverla sola (destino confirmado previo/nombre de
    # obra) antes de pedirla; sólo viaja cuando Desktop mostró el campo
    # separado "Comuna/localidad" y el humano la escribió. Bloque R9: REGISTRAR_CLIENTE_MANUAL,
    # con --razon-social-manual (obligatorio para esa acción) y
    # --rut-manual (opcional).
    parser=argparse.ArgumentParser(); parser.add_argument("--raiz-atlas",required=True); parser.add_argument("--decision-id",required=True); parser.add_argument("--accion",choices=("REGISTRAR","NO_REGISTRAR","CONFIRMAR","NO_CONFIRMAR","POSPONER","CONFIRMAR_PLANTA","SELECCIONAR_OTRA_PLANTA","NO_PUEDO_DETERMINAR","USAR_PATENTE_EXISTENTE","SELECCIONAR_OTRA_PATENTE","CONFIRMAR_ALIAS","RECHAZAR","REGISTRAR_DIRECCION","REGISTRAR_CLIENTE_MANUAL"),required=True); parser.add_argument("--tipo-vehiculo",choices=("TRACTO","CARRO","CAMION_RIGIDO")); parser.add_argument("--planta-id-elegida"); parser.add_argument("--patente-elegida"); parser.add_argument("--motivo-rechazo"); parser.add_argument("--direccion-manual"); parser.add_argument("--comuna-manual"); parser.add_argument("--razon-social-manual"); parser.add_argument("--rut-manual")
    args=parser.parse_args()
    argumentos=dict(raiz_atlas=args.raiz_atlas,decision_id=args.decision_id,accion=args.accion,tipo_vehiculo=args.tipo_vehiculo,planta_id_elegida=args.planta_id_elegida,patente_elegida=args.patente_elegida,motivo_rechazo=args.motivo_rechazo,direccion_manual=args.direccion_manual,comuna_manual=args.comuna_manual,razon_social_manual=args.razon_social_manual,rut_manual=args.rut_manual)
    try:
        resultado=aplicar_decision_obra(**argumentos)
    except DecisionObsoletaError as error:
        # Bloque R11: `aplicar_decision_obra` ya se autorepara para el caso
        # más común (el dataset cambió por un motivo ajeno a ESTA decisión
        # -- ver su propio bloque R11). Si aun así queda obsoleta de
        # verdad, se reconcilia la bandeja completa aquí (fuera de su lock,
        # única vez que es seguro llamar `reconciliar_bandeja_decisiones`
        # -- reutiliza enriquecimiento vehículo/cliente/obra y auto-
        # resolución ya existentes, sin mecanismo paralelo) y se reintenta
        # UNA vez -- el usuario nunca queda atrapado reintentando una
        # tarjeta muerta a mano.
        try:
            from atlas_core.revalidacion_documental import reconciliar_bandeja_decisiones
            reconciliar_bandeja_decisiones(raiz_atlas=args.raiz_atlas)
            resultado=aplicar_decision_obra(**argumentos)
        except ErrorAplicacionDecision as error_reintento:
            resultado={"ok":False,"error":str(error_reintento)}
        except Exception:
            resultado={"ok":False,"error":str(error)}
    except ErrorAplicacionDecision as error:
        resultado={"ok":False,"error":str(error)}
    # Salida ASCII JSON: evita que la consola Windows recodifique los
    # mensajes UTF-8 antes de que Desktop haga JSON.parse. Los escapes JSON
    # se reconstruyen como Unicode correcto en la UI.
    print(json.dumps(resultado, ensure_ascii=True))

if __name__ == "__main__": main()
