"""Bloque CATALOGOS V2 -- CLI invocado por Desktop (IPC `atlas:cargar-
fichas-catalogos`, mismo patrón ya usado para `consultar_atlas.py`:
Desktop hace `spawn('py', ['-3', '-u', ...])` y lee la salida
estándar). Imprime UN solo objeto JSON a stdout -- read-only, sin B1,
sin red (ver `atlas_core.catalogo_fichas`)."""
from __future__ import annotations

import argparse
import json
import sys

from atlas_core.catalogo_fichas import construir_snapshot_fichas


def _expediente(argumentos: argparse.Namespace) -> int:
    from atlas_core.expediente_digital import (
        ErrorExpedienteDigital, empresa_del_proceso, preparar_alertas_vencimiento, revisar_documento_pendiente,
        vista_expediente_desktop,
    )
    empresa = empresa_del_proceso()
    try:
        if argumentos.expediente_revision_documento:
            try:
                propuesta = json.loads(argumentos.expediente_revision_propuesta or "{}")
            except ValueError as error:
                raise ErrorExpedienteDigital("propuesta de revisión ilegible") from error
            if not isinstance(propuesta, dict):
                raise ErrorExpedienteDigital("propuesta de revisión ilegible")
            # Vista previa: misma evaluación que la confirmación, sin escribir.
            resultado = revisar_documento_pendiente(argumentos.raiz_atlas, empresa=empresa,
                                                    referencia=argumentos.expediente_referencia or "",
                                                    documento_id=argumentos.expediente_revision_documento,
                                                    propuesta=propuesta)
        elif argumentos.expediente_alertas:
            resultado = {"empresa": empresa, "alertas": preparar_alertas_vencimiento(argumentos.raiz_atlas, empresa=empresa)}
        else:
            resultado = vista_expediente_desktop(argumentos.raiz_atlas, empresa=empresa,
                                                 entidad=argumentos.expediente_entidad,
                                                 referencia=argumentos.expediente_referencia or "")
    except ErrorExpedienteDigital as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(resultado, ensure_ascii=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Snapshot de fichas de Catálogos (choferes/clientes/obras/vehículos), sólo lectura.")
    parser.add_argument("--raiz-atlas", required=True, help="Raíz real de Atlas (contiene catalogos_privados/ y operacion/actual/)")
    # Expediente digital: también sólo lectura; usa este mismo canal de consulta de Desktop.
    parser.add_argument("--expediente-entidad", choices=("CHOFER", "VEHICULO"))
    parser.add_argument("--expediente-referencia")
    parser.add_argument("--expediente-alertas", action="store_true")
    parser.add_argument("--expediente-revision-documento")
    parser.add_argument("--expediente-revision-propuesta")
    argumentos = parser.parse_args(argv)
    if argumentos.expediente_alertas or argumentos.expediente_entidad or argumentos.expediente_revision_documento:
        return _expediente(argumentos)
    snapshot = construir_snapshot_fichas(raiz_atlas=argumentos.raiz_atlas)
    # Bloque CATALOGOS V2 -- ensure_ascii=True a propósito, mismo
    # criterio ya usado por cli_consulta_atlas.py: Desktop lee stdout
    # de este proceso vía spawn/pipe, cuya codificación de consola en
    # Windows no siempre es UTF-8 -- escapar a \uXXXX evita corromper
    # tildes/Ñ en vez de depender de la codificación del pipe.
    print(json.dumps(snapshot, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
