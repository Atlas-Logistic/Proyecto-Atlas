"""Recupera explícitamente un envío Mobile ERROR previo a persistencia.

Uso controlado, siempre bajo el lease global de escritor:
  python recuperar_envio_mobile_error.py --envio-id <uuid> --raiz-atlas <dir>
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from atlas_core.almacenamiento_portable import leer_estado_operacion, resolver_raiz_atlas
from atlas_core.escritor_operativo import LeaseEscritorOperativo
from atlas_core.fuente_catalogos import ErrorFuenteCatalogos, validar_fuente_catalogos
from atlas_core.mobile import RepositorioEnviosMobile, recuperar_envio_mobile_error_pre_persistencia


URL_CLOUD_POR_DEFECTO = "https://atlas-mobile-cloud-receiver.1986jaar.workers.dev"


def ejecutar_recuperacion_con_escritor(
    *, base_url: str, token_motor: str, envio_id: str, repositorio: RepositorioEnviosMobile,
    dataset: Path, carpeta_catalogos: str | Path | None, timeout: float = 30.0,
    fabrica_escritor=LeaseEscritorOperativo,
) -> dict:
    """No inicia una recuperación si no posee el escritor global vigente."""
    with fabrica_escritor(base_url=base_url, token_motor=token_motor, timeout=timeout) as escritor:
        if not escritor.adquirir() or not escritor.vigente:
            return {"escritor_operativo": "NO_ADQUIRIDO", "envio_id": envio_id}
        resultado = recuperar_envio_mobile_error_pre_persistencia(
            repositorio, envio_id, dataset=dataset, carpeta_catalogos=carpeta_catalogos,
            puede_escribir=lambda: escritor.vigente,
        )
        return {"escritor_operativo": "ADQUIRIDO", "envio_id": envio_id, "resultado": resultado}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--envio-id", required=True)
    parser.add_argument("--raiz-atlas", required=True)
    parser.add_argument("--base-url", default=os.environ.get("ATLAS_CLOUD_MOBILE_URL", URL_CLOUD_POR_DEFECTO))
    parser.add_argument("--token", default=os.environ.get("ATLAS_CLOUD_MOTOR_TOKEN", ""))
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    if not args.token:
        parser.error("Falta --token (o la variable de entorno ATLAS_CLOUD_MOTOR_TOKEN)")

    raiz = resolver_raiz_atlas(args.raiz_atlas)
    estado = leer_estado_operacion(raiz=raiz) or {}
    dataset = raiz / estado.get("dataset_operacional", "operacion/actual/analisis_completo_guias.csv")
    try:
        carpeta_catalogos = validar_fuente_catalogos(None, permitir_sin_catalogos=True).ruta
    except ErrorFuenteCatalogos:
        carpeta_catalogos = None
    resultado = ejecutar_recuperacion_con_escritor(
        base_url=args.base_url, token_motor=args.token, envio_id=args.envio_id,
        repositorio=RepositorioEnviosMobile(raiz), dataset=dataset,
        carpeta_catalogos=carpeta_catalogos, timeout=args.timeout,
    )
    print(json.dumps(resultado, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
