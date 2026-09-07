"""CLI estrecho usado por Atlas Desktop -- sección "Observaciones" del
viaje -- para registrar / anular / listar eventos operacionales
canónicos (estadía, devolución parcial/total, doble vuelta) sobre la
fuente canónica `operacion/actual/eventos_operacionales.json`.

Desktop NUNCA escribe ese JSON directamente: pide la persistencia aquí,
el Motor enriquece con viaje/guías/chofer/patente desde la operación
vigente SÓLO cuando es inequívoco, persiste canónicamente y responde un
ACK. Desktop confirma su UI sólo tras un ACK correcto.

Salida: una línea JSON ASCII (`ensure_ascii=True`) -- mismo criterio que
`aplicar_decision_pendiente.py` / `forzar_correccion_destino.py` para
que la consola de Windows no recodifique nada antes de `JSON.parse`.
"""

from __future__ import annotations

import argparse
import json

from atlas_core.registro_eventos_operacionales import (
    CONTEXTO_EMPRESARIAL_SIN_ASIGNAR,
    anular_evento,
    listar_eventos_por_transporte,
    registrar_evento,
    resolver_enriquecimiento_transporte,
)


def _registrar(args) -> dict:
    enriquecimiento = resolver_enriquecimiento_transporte(
        raiz=args.raiz_atlas, numero_transporte=args.numero_transporte
    )
    resultado = registrar_evento(
        raiz=args.raiz_atlas,
        tipo_evento=args.tipo_evento,
        numero_transporte=args.numero_transporte,
        nota=args.nota or "",
        contexto_empresarial=args.contexto_empresarial,
        origen=args.origen,
        referencia=args.referencia or "",
        enriquecimiento=enriquecimiento,
    )
    resultado["enriquecimiento"] = enriquecimiento
    return resultado


def _anular(args) -> dict:
    return anular_evento(
        raiz=args.raiz_atlas,
        tipo_evento=args.tipo_evento,
        numero_transporte=args.numero_transporte,
        contexto_empresarial=args.contexto_empresarial,
        origen=args.origen,
        referencia=args.referencia or "",
        motivo=args.motivo or "",
    )


def _listar(args) -> dict:
    eventos = listar_eventos_por_transporte(
        raiz=args.raiz_atlas,
        numero_transporte=args.numero_transporte,
        contexto_empresarial=(
            args.contexto_empresarial if args.filtrar_contexto else None
        ),
        incluir_anulados=not args.solo_activos,
    )
    return {"ok": True, "numero_transporte": args.numero_transporte, "eventos": eventos}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="accion", required=True)

    def comunes(p, *, con_nota=False, con_motivo=False):
        p.add_argument("--raiz-atlas", dest="raiz_atlas", required=True)
        p.add_argument("--numero-transporte", dest="numero_transporte", required=True)
        p.add_argument("--tipo-evento", dest="tipo_evento", required=True)
        p.add_argument(
            "--contexto-empresarial",
            dest="contexto_empresarial",
            default=CONTEXTO_EMPRESARIAL_SIN_ASIGNAR,
        )
        p.add_argument("--origen", dest="origen", default="DESKTOP_OBSERVACIONES")
        p.add_argument("--referencia", dest="referencia", default="")
        if con_nota:
            p.add_argument("--nota", dest="nota", default="")
        if con_motivo:
            p.add_argument("--motivo", dest="motivo", default="")

    p_reg = sub.add_parser("registrar")
    comunes(p_reg, con_nota=True)

    p_anu = sub.add_parser("anular")
    comunes(p_anu, con_motivo=True)

    p_lis = sub.add_parser("listar")
    p_lis.add_argument("--raiz-atlas", dest="raiz_atlas", required=True)
    p_lis.add_argument("--numero-transporte", dest="numero_transporte", required=True)
    p_lis.add_argument(
        "--contexto-empresarial",
        dest="contexto_empresarial",
        default=CONTEXTO_EMPRESARIAL_SIN_ASIGNAR,
    )
    p_lis.add_argument("--filtrar-contexto", dest="filtrar_contexto", action="store_true")
    p_lis.add_argument("--solo-activos", dest="solo_activos", action="store_true")

    args = parser.parse_args()
    try:
        if args.accion == "registrar":
            resultado = _registrar(args)
        elif args.accion == "anular":
            resultado = _anular(args)
        else:
            resultado = _listar(args)
    except Exception as error:  # noqa: BLE001 -- el ACK a Desktop nunca debe ser un stacktrace
        resultado = {"ok": False, "error": str(error)}
    print(json.dumps(resultado, ensure_ascii=True))


if __name__ == "__main__":
    main()
