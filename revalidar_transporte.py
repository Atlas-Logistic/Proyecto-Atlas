"""CLI del bloque REVALIDACIÓN POR TRANSPORTE -- revalida los documentos
ya persistidos de UN `numero_transporte` reextrayéndolos contra su imagen
original (mismo pipeline real, nunca un segundo motor OCR). Por defecto
corre en modo dry-run (no escribe nada); requiere `--ejecutar` explícito
para persistir cambios y disparar la reconciliación canónica
(`revalidar_y_regenerar_reporte`). Mecanismo genérico para cualquier
transporte -- nunca un script puntual para un caso.

Con `--ejecutar` corre SIEMPRE bajo el lease global de escritor, el mismo
que usa el PULL Cloud (`sincronizar_mobile_cloud.py`): si otro proceso lo
posee o Cloud no responde, no escribe nada. Requiere ATLAS_CLOUD_MOTOR_TOKEN
(o --token). El dry-run no escribe y no pide lease.

Si una corrida anterior reescribió el dataset pero no alcanzó a reconciliar
(lease perdido, corte), la siguiente con `--ejecutar` lo completa. Para
completarlo sin OCR ni transporte: `--reconciliar-pendiente`."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from atlas_core.escritor_operativo import LeaseEscritorOperativo
from atlas_core.reprocesamiento_reparador import (
    completar_reconciliacion_pendiente,
    revalidar_documentos_por_transporte,
)

URL_CLOUD_POR_DEFECTO = "https://atlas-mobile-cloud-receiver.1986jaar.workers.dev"


def ejecutar_revalidacion_con_escritor(
    *, base_url: str, token_motor: str, raiz_atlas: str | Path, numero_transporte: str,
    timeout: float = 30.0, fabrica_escritor=LeaseEscritorOperativo,
) -> dict:
    """No inicia una revalidación con escritura sin el escritor global vigente.

    El lease se libera al salir del contexto, también si la revalidación
    falla; los locks de archivo propios de la revalidación no cambian."""
    with fabrica_escritor(base_url=base_url, token_motor=token_motor, timeout=timeout) as escritor:
        if not escritor.adquirir() or not escritor.vigente:
            return {"escritor_operativo": "NO_ADQUIRIDO", "numero_transporte": numero_transporte}
        resultado = revalidar_documentos_por_transporte(
            raiz_atlas=raiz_atlas, numero_transporte=numero_transporte, dry_run=False,
            puede_escribir=lambda: escritor.vigente,
        )
        estado = "PERDIDO" if resultado.get("escritor_operativo_perdido") else "ADQUIRIDO"
        return {"escritor_operativo": estado, **resultado}


def ejecutar_reconciliacion_pendiente_con_escritor(
    *, base_url: str, token_motor: str, raiz_atlas: str | Path, timeout: float = 30.0,
    fabrica_escritor=LeaseEscritorOperativo,
) -> dict:
    """Completa una reconciliación pendiente (sin OCR) bajo el escritor global."""
    with fabrica_escritor(base_url=base_url, token_motor=token_motor, timeout=timeout) as escritor:
        if not escritor.adquirir() or not escritor.vigente:
            return {"escritor_operativo": "NO_ADQUIRIDO"}
        resultado = completar_reconciliacion_pendiente(raiz_atlas=raiz_atlas, puede_escribir=lambda: escritor.vigente)
        estado = "PERDIDO" if resultado.get("escritor_operativo_perdido") else "ADQUIRIDO"
        return {"escritor_operativo": estado, **resultado}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raiz-atlas", required=True)
    parser.add_argument("--numero-transporte")
    parser.add_argument("--ejecutar", action="store_true", help="Persiste los cambios bajo el escritor global (sin esto: dry-run)")
    parser.add_argument("--reconciliar-pendiente", action="store_true",
                        help="Sólo completa una reconciliación pendiente, sin OCR, bajo el escritor global")
    parser.add_argument("--base-url", default=os.environ.get("ATLAS_CLOUD_MOBILE_URL", URL_CLOUD_POR_DEFECTO))
    parser.add_argument("--token", default=os.environ.get("ATLAS_CLOUD_MOTOR_TOKEN", ""), help="Por defecto lee ATLAS_CLOUD_MOTOR_TOKEN")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    if args.reconciliar_pendiente == bool(args.numero_transporte):
        parser.error("indica --numero-transporte o --reconciliar-pendiente (uno de los dos)")
    if args.reconciliar_pendiente and not args.ejecutar:
        parser.error("--reconciliar-pendiente escribe: requiere --ejecutar")

    if not args.ejecutar:
        resultado = revalidar_documentos_por_transporte(
            raiz_atlas=args.raiz_atlas, numero_transporte=args.numero_transporte, dry_run=True,
        )
        print(json.dumps(resultado, ensure_ascii=True, indent=2))
        return

    if not args.token:
        parser.error("--ejecutar requiere --token (o la variable de entorno ATLAS_CLOUD_MOTOR_TOKEN)")
    if args.reconciliar_pendiente:
        resultado = ejecutar_reconciliacion_pendiente_con_escritor(
            base_url=args.base_url, token_motor=args.token, raiz_atlas=args.raiz_atlas, timeout=args.timeout,
        )
    else:
        resultado = ejecutar_revalidacion_con_escritor(
            base_url=args.base_url, token_motor=args.token, raiz_atlas=args.raiz_atlas,
            numero_transporte=args.numero_transporte, timeout=args.timeout,
        )
    print(json.dumps(resultado, ensure_ascii=True, indent=2))
    if resultado["escritor_operativo"] != "ADQUIRIDO":
        sys.exit(3)


if __name__ == "__main__":
    main()
