"""Migración explícita (primero simulación) del registro operacional Atlas.

Sin bandera: simula (no escribe). ``--aplicar`` migra por lotes y es
reanudable; ``--verificar`` relee los reportes y marca la migración
verificada sólo si todo calza; ``--activar`` / ``--desactivar`` deciden si el
consumidor usa el registro o vuelve al lector histórico; ``--consolidar``
incorpora al registro base los segmentos del diario de días anteriores y los
retira; ``--estado`` informa (incluye el diario).

Las acciones que escriben el registro (``catalogos_privados``, custodiado por
Cloud) se ejecutan con el MISMO escritor que PULL y Desktop (lease Cloud con
custodia, o política de equipo único): fuera de ese turno la próxima
alineación de PULL revertiría el archivo a la versión confirmada.
``--sin-escritor`` existe sólo para raíces de prueba o copias locales.
Código de salida: 0 correcto, 1 verificación fallida, 2 bloqueado.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from atlas_core.registro_relaciones_operacionales import (
    LOTE_MIGRACION, RegistroRelacionesError, activar_registro, consolidar_diario, desactivar_registro,
    estado_registro, migrar_reportes_historicos, verificar_migracion,
)


def _escritor(raiz: Path):
    """El mismo escritor que PULL y Desktop: equipo único o lease Cloud."""
    from atlas_core.escritor_operativo import lease_desde_entorno
    from atlas_core.exclusividad_equipo import EscritorEquipoUnico, politica_equipo_unico
    return EscritorEquipoUnico(raiz) if politica_equipo_unico(raiz) else lease_desde_entorno(raiz=raiz)


class _SinEscritor(Exception):
    def __init__(self, codigo: str) -> None:
        super().__init__(codigo)
        self.codigo = codigo


def _con_escritor(raiz: str, operacion, *, fabrica, sin_escritor: bool):
    if sin_escritor:
        return operacion()
    escritor = fabrica(Path(raiz))
    if escritor is None:
        raise _SinEscritor("SIN_ESCRITOR_CONFIGURADO")
    with escritor:
        if not escritor.adquirir() or not escritor.vigente:
            raise _SinEscritor("ESCRITOR_OCUPADO")
        return operacion()


def main(argv: list[str] | None = None, *, fabrica_escritor=_escritor) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--raiz", required=True)
    p.add_argument("--empresa", default="oficina")
    accion = p.add_mutually_exclusive_group()
    accion.add_argument("--aplicar", action="store_true", help="Migra por lotes; reanudable e idempotente.")
    accion.add_argument("--verificar", action="store_true", help="Relee reportes; no activa.")
    accion.add_argument("--activar", action="store_true", help="Sólo con migración verificada.")
    accion.add_argument("--desactivar", action="store_true", help="El consumidor vuelve a los históricos.")
    accion.add_argument("--consolidar", action="store_true",
                        help="Incorpora al registro base los segmentos del diario anteriores a --hasta.")
    accion.add_argument("--estado", action="store_true")
    p.add_argument("--hasta", default=None, help="AAAAMMDD exclusivo para --consolidar (defecto: hoy UTC).")
    p.add_argument("--lote", type=int, default=LOTE_MIGRACION)
    p.add_argument("--sin-escritor", action="store_true", help="Sólo raíces de prueba: escribe sin lease ni custodia.")
    a = p.parse_args(argv)
    codigo = 0

    def escribiendo(operacion):
        return _con_escritor(a.raiz, operacion, fabrica=fabrica_escritor, sin_escritor=a.sin_escritor)

    try:
        if a.aplicar:
            resultado = escribiendo(lambda: migrar_reportes_historicos(
                a.raiz, empresa_id=a.empresa, aplicar=True, lote=a.lote))
        elif a.verificar:
            resultado = escribiendo(lambda: verificar_migracion(a.raiz, empresa_id=a.empresa))
            codigo = 0 if resultado["ok"] else 1
        elif a.activar:
            resultado = escribiendo(lambda: activar_registro(a.raiz, empresa_id=a.empresa))
        elif a.desactivar:
            resultado = escribiendo(lambda: desactivar_registro(a.raiz, empresa_id=a.empresa))
        elif a.consolidar:
            resultado = escribiendo(lambda: consolidar_diario(a.raiz, hasta=a.hasta))
        elif a.estado:
            resultado = estado_registro(a.raiz, empresa_id=a.empresa)
        else:
            resultado = migrar_reportes_historicos(a.raiz, empresa_id=a.empresa)
    except (RegistroRelacionesError, _SinEscritor) as error:
        resultado, codigo = {"bloqueado": error.codigo, "detalle": str(error)}, 2
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return codigo


if __name__ == "__main__":
    sys.exit(main())
