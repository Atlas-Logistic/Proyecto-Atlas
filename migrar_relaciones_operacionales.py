"""Migración explícita (primero simulación) del registro operacional Atlas.

Sin bandera: simula (no escribe). ``--aplicar`` migra por lotes y es
reanudable; ``--verificar`` relee los reportes y marca la migración
verificada sólo si todo calza; ``--activar`` / ``--desactivar`` deciden si el
consumidor usa el registro o vuelve al lector histórico; ``--estado`` informa.
Código de salida: 0 correcto, 1 verificación fallida, 2 bloqueado.
"""
from __future__ import annotations

import argparse
import json
import sys

from atlas_core.registro_relaciones_operacionales import (
    LOTE_MIGRACION, RegistroRelacionesError, activar_registro, desactivar_registro, estado_registro,
    migrar_reportes_historicos, verificar_migracion,
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--raiz", required=True)
    p.add_argument("--empresa", default="oficina")
    accion = p.add_mutually_exclusive_group()
    accion.add_argument("--aplicar", action="store_true", help="Migra por lotes; reanudable e idempotente.")
    accion.add_argument("--verificar", action="store_true", help="Relee reportes; no activa.")
    accion.add_argument("--activar", action="store_true", help="Sólo con migración verificada.")
    accion.add_argument("--desactivar", action="store_true", help="El consumidor vuelve a los históricos.")
    accion.add_argument("--estado", action="store_true")
    p.add_argument("--lote", type=int, default=LOTE_MIGRACION)
    a = p.parse_args(argv)
    codigo = 0
    try:
        if a.aplicar:
            resultado = migrar_reportes_historicos(a.raiz, empresa_id=a.empresa, aplicar=True, lote=a.lote)
        elif a.verificar:
            resultado = verificar_migracion(a.raiz, empresa_id=a.empresa)
            codigo = 0 if resultado["ok"] else 1
        elif a.activar:
            resultado = activar_registro(a.raiz, empresa_id=a.empresa)
        elif a.desactivar:
            resultado = desactivar_registro(a.raiz, empresa_id=a.empresa)
        elif a.estado:
            resultado = estado_registro(a.raiz, empresa_id=a.empresa)
        else:
            resultado = migrar_reportes_historicos(a.raiz, empresa_id=a.empresa)
    except RegistroRelacionesError as error:
        resultado, codigo = {"bloqueado": error.codigo, "detalle": str(error)}, 2
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return codigo


if __name__ == "__main__":
    sys.exit(main())
