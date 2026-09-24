"""Perfilador local, opt-in y sin cambios de reglas para una decisión scratch.

Sólo acepta una raíz que el operador ya copió fuera de producción. Mide el
backend completo (aplicar -> revalidar -> opcionalmente reconciliar) y deja
JSON para comparar corridas. No usa G ni realiza llamadas propias: cualquier
proveedor es exactamente el que reciba el flujo normal.
"""
from __future__ import annotations

import argparse
import cProfile
import json
import pstats
import time
from collections import defaultdict
from pathlib import Path


def _resumen_profiler(perfil: cProfile.Profile, limite: int = 40) -> list[dict[str, object]]:
    estadisticas = pstats.Stats(perfil).stats
    filas = []
    for (archivo, linea, nombre), (llamadas, _primitivas, tiempo_prop, tiempo_acum, _llamadores) in estadisticas.items():
        if "atlas_core" not in archivo and "urllib" not in archivo and "http" not in archivo and "socket" not in archivo:
            continue
        filas.append({
            "funcion": f"{Path(archivo).name}:{linea}:{nombre}", "llamadas": llamadas,
            "tiempo_propio_ms": round(tiempo_prop * 1000, 1), "tiempo_acumulado_ms": round(tiempo_acum * 1000, 1),
        })
    return sorted(filas, key=lambda fila: float(fila["tiempo_acumulado_ms"]), reverse=True)[:limite]


def perfilar_aplicacion_scratch(*, raiz_atlas: Path, decision_id: str, accion: str,
                                direccion_manual: str | None = None, comuna_manual: str | None = None,
                                reconciliar_despues: bool = False, proveedor_rutas: object = None) -> dict[str, object]:
    """Ejecuta UNA decisión contra una copia scratch y devuelve tiempos JSON.

    Los tiempos de revalidación y reconciliación se toman además de sus
    retornos canónicos (`tiempos_ms`), de modo que el perfil no altera la
    semántica ni depende de logs de texto.
    """
    from atlas_core.aplicacion_decisiones import aplicar_decision_obra
    from atlas_core.reconciliacion_estado_derivado import reconciliar_estado_derivado

    perfil = cProfile.Profile()
    inicio = time.perf_counter()
    perfil.enable()
    resultado = aplicar_decision_obra(
        raiz_atlas=raiz_atlas, decision_id=decision_id, accion=accion,
        direccion_manual=direccion_manual, comuna_manual=comuna_manual,
        proveedor_rutas=proveedor_rutas,
    )
    aplicar_ms = round((time.perf_counter() - inicio) * 1000, 1)
    reconciliacion = None
    reconciliar_ms = 0.0
    if reconciliar_despues:
        inicio_reconciliar = time.perf_counter()
        reconciliacion = reconciliar_estado_derivado(raiz_atlas=raiz_atlas, proveedor_rutas=proveedor_rutas)
        reconciliar_ms = round((time.perf_counter() - inicio_reconciliar) * 1000, 1)
    perfil.disable()
    total_ms = round((time.perf_counter() - inicio) * 1000, 1)

    revalidacion = resultado.get("revalidacion") if isinstance(resultado, dict) else None
    tiempos_revalidacion = revalidacion.get("tiempos_ms", {}) if isinstance(revalidacion, dict) else {}
    tiempos_reconciliacion = reconciliacion.get("tiempos_ms", {}) if isinstance(reconciliacion, dict) else {}
    etapas = [
        {"etapa": "aplicar_decision_backend", "llamadas": 1, "tiempo_ms": aplicar_ms},
        {"etapa": "revalidar_y_regenerar_reporte", "llamadas": int(bool(revalidacion)),
         "tiempo_ms": float(tiempos_revalidacion.get("total_ms", 0.0))},
        {"etapa": "reconciliar_estado_derivado", "llamadas": int(reconciliar_despues), "tiempo_ms": reconciliar_ms},
    ]
    return {
        "raiz_scratch": str(raiz_atlas), "decision_id": decision_id, "accion": accion,
        "total_backend_ms": total_ms, "etapas": etapas,
        "revalidacion_tiempos_ms": tiempos_revalidacion,
        "reconciliacion_tiempos_ms": tiempos_reconciliacion,
        "reconciliacion_duracion_bateria_ms": (reconciliacion or {}).get("duracion_bateria_completa_ms"),
        "funciones_lentas": _resumen_profiler(perfil),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Perfila una decisión sólo en una copia scratch de Atlas.")
    parser.add_argument("--raiz-scratch", required=True, type=Path)
    parser.add_argument("--decision-id", required=True)
    parser.add_argument("--accion", required=True)
    parser.add_argument("--direccion-manual")
    parser.add_argument("--comuna-manual")
    parser.add_argument("--reconciliar-despues", action="store_true")
    parser.add_argument("--salida", type=Path)
    args = parser.parse_args()
    resultado = perfilar_aplicacion_scratch(
        raiz_atlas=args.raiz_scratch, decision_id=args.decision_id, accion=args.accion,
        direccion_manual=args.direccion_manual, comuna_manual=args.comuna_manual,
        reconciliar_despues=args.reconciliar_despues,
    )
    texto = json.dumps(resultado, ensure_ascii=False, indent=2) + "\n"
    if args.salida:
        args.salida.write_text(texto, encoding="utf-8")
    print(texto, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
