"""Confirma manualmente la asociación de un envío Mobile pendiente."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from atlas_core.almacenamiento_portable import bloqueo_sesion, leer_estado_operacion, resolver_raiz_atlas
from atlas_core.mobile import TIEMPO_EXPIRACION_LOCK_ENVIO_SEGUNDOS, RepositorioEnviosMobile


def resolver(raiz: Path, envio_id: str, numero_transporte: str) -> dict:
    repo = RepositorioEnviosMobile(raiz)
    estado = leer_estado_operacion(raiz=raiz) or {}
    dataset = raiz / estado.get("dataset_operacional", "operacion/actual/analisis_completo_guias.csv")
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        existentes = {fila.get("numero_transporte", "") for fila in csv.DictReader(archivo, delimiter=";")}
    if numero_transporte not in existentes:
        raise ValueError("El transporte indicado no existe en la operación vigente.")
    # Bloque CONSISTENCIA OPERACIONAL -- lock por envío: esta confirmación
    # manual compite por el MISMO envio.json que `procesar_envio_mobile`/
    # un reproceso podrían estar tocando concurrentemente. Se relee fresco
    # DENTRO del lock -- nunca se decide sobre una copia obsoleta.
    with bloqueo_sesion(
        repo.raiz, f"mobile_{envio_id}", tiempo_expiracion_segundos=TIEMPO_EXPIRACION_LOCK_ENVIO_SEGUNDOS,
    ):
        registro = repo.cargar(envio_id)
        if registro.get("estado") != "REQUIERE_REVISION":
            raise ValueError("El envío ya no está pendiente de revisión.")
        registro["estado"] = "ASOCIADO"
        registro["resultado_asociacion"] = {
            "estado": "ASOCIADO_MANUALMENTE", "numero_transporte": numero_transporte,
            "numero_guia": str((registro.get("datos_ocr") or {}).get("numero_guia", "")),
            "candidatos": (registro.get("resultado_asociacion") or {}).get("candidatos", []),
            "motivo": "Confirmado por supervisor en Atlas Desktop.",
        }
        registro["asociado_manualmente_en"] = datetime.now(timezone.utc).isoformat()
        repo.guardar(envio_id, registro)
    return {"ok": True, "envio_id": envio_id, "numero_transporte": numero_transporte}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raiz-atlas", type=Path, required=True)
    parser.add_argument("--envio-id", required=True)
    parser.add_argument("--numero-transporte", required=True)
    args = parser.parse_args()
    print(json.dumps(resolver(resolver_raiz_atlas(args.raiz_atlas), args.envio_id, args.numero_transporte)))


if __name__ == "__main__":
    main()
