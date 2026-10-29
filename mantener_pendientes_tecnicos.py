"""Comando focal de mantenimiento; --solo-plan nunca escribe ni hace red.

--tarea-programada (tarea de este PC, cada 10 min): sin trabajo elegible no
toma el escritor ni escribe; con una acción de B1 o una decisión humana en
curso, o con el escritor ocupado (p. ej. PULL), omite la pasada sin esperar.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from atlas_core.almacenamiento_portable import resolver_raiz_atlas
from atlas_core.mantenimiento_pendientes_tecnicos import mantener_pendientes_tecnicos

# Mismo vencimiento que `bloqueo_sesion`: un lock más viejo es huérfano.
_VIGENCIA_LOCK_SEGUNDOS = 6 * 3600
_LOCKS_OPERACION_HUMANA = (".atlas_lock_acciones_operacionales", ".atlas_lock_b1_operador_conversaciones",
                           ".atlas_lock_aplicar_decision_obra")


def _operacion_humana_en_curso(raiz: Path) -> str:
    actual = raiz / "operacion" / "actual"
    for nombre in _LOCKS_OPERACION_HUMANA:
        try:
            if time.time() - (actual / nombre).stat().st_mtime <= _VIGENCIA_LOCK_SEGUNDOS:
                return nombre
        except OSError:
            continue
    return ""


def _escritor(raiz: Path):
    """El mismo escritor que PULL y Desktop: equipo único o lease Cloud."""
    from atlas_core.escritor_operativo import lease_desde_entorno
    from atlas_core.exclusividad_equipo import EscritorEquipoUnico, politica_equipo_unico
    return EscritorEquipoUnico(raiz) if politica_equipo_unico(raiz) else lease_desde_entorno(raiz=raiz)


def pasada_programada(raiz: Path, *, fabrica_escritor=_escritor) -> dict[str, object]:
    plan = mantener_pendientes_tecnicos(raiz_atlas=raiz, solo_plan=True)
    if not plan.get("elegibles"):
        return {"ejecutado": False, "motivo": "SIN_ELEGIBLES", "elegibles": []}
    en_curso = _operacion_humana_en_curso(raiz)
    if en_curso:
        return {"ejecutado": False, "motivo": "OPERACION_HUMANA_EN_CURSO", "lock": en_curso}
    escritor = fabrica_escritor(raiz)
    if escritor is None:
        return {"ejecutado": False, "motivo": "SIN_ESCRITOR_CONFIGURADO"}
    with escritor:
        if not escritor.adquirir() or not escritor.vigente:
            return {"ejecutado": False, "motivo": "ESCRITOR_OCUPADO"}
        return mantener_pendientes_tecnicos(raiz_atlas=raiz)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raiz-atlas", required=True)
    parser.add_argument("--solo-plan", action="store_true")
    parser.add_argument("--tarea-programada", action="store_true")
    args = parser.parse_args()
    raiz = resolver_raiz_atlas(args.raiz_atlas)
    inicio = time.monotonic()
    if args.tarea_programada:
        resultado = pasada_programada(Path(raiz))
    else:
        resultado = mantener_pendientes_tecnicos(raiz_atlas=raiz, solo_plan=args.solo_plan)
    resultado = {"fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "duracion_s": round(time.monotonic() - inicio, 2), **resultado}
    print(json.dumps(resultado, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
