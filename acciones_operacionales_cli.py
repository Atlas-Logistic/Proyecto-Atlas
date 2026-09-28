"""CLI estrecho de la capa canónica de acciones operacionales.

    catalogo                                   -> acciones, riesgo y parámetros
    previsualizar --accion A --parametros JSON -> preview (o resultado LECTURA)
    ejecutar --token T --confirmado-por X      -> ejecuta ESE preview
    auditoria                                  -> registro append-only

Nunca acepta rutas ni comandos: la raíz se resuelve igual que el resto de
Atlas (`--raiz-atlas` o autodetección) y las acciones son las del registro
tipado de `atlas_core.acciones_operacionales`. Salida JSON ASCII (mismo
criterio que aplicar_decision_pendiente.py)."""
import argparse
import json

from atlas_core.acciones_operacionales import CapaAccionesOperacionales, catalogo_acciones
from atlas_core.almacenamiento_portable import resolver_raiz_atlas


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raiz-atlas")
    sub = parser.add_subparsers(dest="modo", required=True)
    sub.add_parser("catalogo")
    prev = sub.add_parser("previsualizar")
    prev.add_argument("--accion", required=True)
    prev.add_argument("--parametros", default="{}")
    prev.add_argument("--actor", required=True)
    prev.add_argument("--origen", default="HUMANO", choices=("HUMANO", "B1", "SISTEMA"))
    prev.add_argument("--referencia", default="")
    eje = sub.add_parser("ejecutar")
    eje.add_argument("--token", required=True)
    eje.add_argument("--actor", required=True)
    eje.add_argument("--confirmado-por", default="")
    eje.add_argument("--origen", default="HUMANO", choices=("HUMANO", "B1", "SISTEMA"))
    eje.add_argument("--autorizacion-sensible", action="store_true")
    eje.add_argument("--accion-esperada")
    sub.add_parser("auditoria")
    args = parser.parse_args(argv)

    if args.modo == "catalogo":
        resultado = {"acciones": catalogo_acciones()}
    else:
        capa = CapaAccionesOperacionales(resolver_raiz_atlas(args.raiz_atlas))
        if args.modo == "previsualizar":
            try:
                parametros = json.loads(args.parametros)
            except json.JSONDecodeError:
                parametros = None
                resultado = {"estado": "RECHAZADA", "codigo": "PARAMETRO_INVALIDO", "mensaje": "parámetros no son JSON"}
            if parametros is not None:
                resultado = capa.previsualizar(args.accion, parametros, actor=args.actor, origen=args.origen,
                                               referencia=args.referencia)
        elif args.modo == "ejecutar":
            resultado = capa.ejecutar(args.token, actor=args.actor, confirmado_por=args.confirmado_por,
                                      origen=args.origen, autorizacion_sensible=args.autorizacion_sensible,
                                      accion_esperada=args.accion_esperada)
        else:
            resultado = {"auditoria": capa.auditoria()}
    print(json.dumps(resultado, ensure_ascii=True, default=str))
    return 0 if resultado.get("estado") not in ("RECHAZADA", "FALLIDA") else 1


if __name__ == "__main__":
    raise SystemExit(main())
