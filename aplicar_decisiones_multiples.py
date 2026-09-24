"""CLI estrecho usado por Atlas Desktop para aplicar VARIAS decisiones
R3.3/R3.4 en un solo lote (Bloque P0 REVISIÓN RÁPIDA / APLICACIÓN
MÚLTIPLE). Recibe la lista de solicitudes como JSON por stdin (nunca por
argv -- el número de campos por decisión y la cantidad de decisiones
seleccionadas hacen impracticable una línea de comando)."""
import argparse
import json
import sys

from atlas_core.almacenamiento_portable import SesionOcupadaError
from atlas_core.aplicacion_multiple import aplicar_decisiones_multiples


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raiz-atlas", required=True)
    parser.add_argument("--actor", default="JAVIER_DESKTOP")
    args = parser.parse_args()
    solicitudes = json.loads(sys.stdin.read() or "[]")
    try:
        resultado = aplicar_decisiones_multiples(
            raiz_atlas=args.raiz_atlas, solicitudes=solicitudes, actor=args.actor,
        )
    except SesionOcupadaError:
        # Bloque P0 RECUPERACIÓN TRANSACCIONAL -- caso real 0000359449:
        # `aplicar_decisiones_multiples` ya captura `SesionOcupadaError`
        # POR ÍTEM dentro de su propio lote (ver ese módulo) -- este
        # `except` de acá es para el caso residual de que el lock ya
        # estuviera ocupado ANTES de procesar el primer ítem. Sin esto,
        # Python imprimía un traceback completo por stderr y este CLI no
        # emitía ninguna línea de JSON por stdout -- Desktop no podía
        # parsear nada, y Javier veía un error técnico en vez de un aviso
        # operacional. Nunca oculta errores inesperados: sólo este caso
        # conocido.
        print(json.dumps({
            "resultados": [], "total_solicitadas": len(solicitudes), "total_aplicadas": 0,
            "reconciliacion_ejecutada": False,
            "reconciliacion_motivo": "Otra operación de Atlas está en curso -- ningún ítem del lote se procesó. "
                                      "Vuelve a intentar en unos segundos.",
            "plan_impacto_ejecutado": False, "plan_impacto_guias": 0, "plan_impacto_duracion_ms": 0.0,
        }, ensure_ascii=True))
        return
    # Salida ASCII JSON: mismo motivo que `aplicar_decision_pendiente.py`
    # (evita que la consola Windows recodifique UTF-8 antes de que Desktop
    # haga JSON.parse).
    print(json.dumps(resultado.a_dict(), ensure_ascii=True))


if __name__ == "__main__":
    main()
