"""CLI Mobile 24/7 -- PULL desde Atlas Mobile Cloud (Worker + D1 + R2).

Mismo papel que `sincronizar_mobile.py` (receptor LAN), pero contra el
Worker de Cloudflare: el PC de Atlas INICIA la conexión (HTTPS saliente),
toma cada envío pendiente con lease, descarga y verifica hash/tamaño, lo
aterriza con `RepositorioEnviosMobile.recibir()` y sólo entonces confirma a
Cloud. Salvo `--sin-procesar`, dispara el MISMO procesamiento Mobile
(OCR/B1/reporte) para todo envío local todavía en `RECIBIDO`.

Idempotente: un envío ya aterrizado no se duplica, uno ya procesado no se
reprocesa, y un lease vencido (PC apagado a mitad) se retoma en la próxima
corrida. Pensado para el Programador de tareas o a mano, desde UN PC.

  python sincronizar_mobile_cloud.py                      # usa ATLAS_CLOUD_MOTOR_TOKEN
  python sincronizar_mobile_cloud.py --sin-procesar --raiz-atlas <dir>
"""
from __future__ import annotations

import argparse
import json
import os
import socket

from atlas_core.almacenamiento_portable import leer_estado_operacion, resolver_raiz_atlas
from atlas_core.cloud_mobile_sync_cliente import sincronizar_envios_cloud
from atlas_core.fuente_catalogos import ErrorFuenteCatalogos, validar_fuente_catalogos
from atlas_core.mobile import RepositorioEnviosMobile

URL_CLOUD_POR_DEFECTO = "https://atlas-mobile-cloud-receiver.1986jaar.workers.dev"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=os.environ.get("ATLAS_CLOUD_MOBILE_URL", URL_CLOUD_POR_DEFECTO))
    parser.add_argument("--token", default=os.environ.get("ATLAS_CLOUD_MOTOR_TOKEN", ""), help="Por defecto lee ATLAS_CLOUD_MOTOR_TOKEN")
    parser.add_argument("--raiz-atlas", default=None)
    parser.add_argument("--consumidor", default=socket.gethostname(), help="Identificador de este PC (por defecto, el hostname)")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--sin-procesar", action="store_true", help="Sólo sincroniza (aterriza localmente); no dispara OCR/B1/reporte")
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

    resultado = sincronizar_envios_cloud(
        base_url=args.base_url, token_motor=args.token, consumidor=args.consumidor,
        repositorio=RepositorioEnviosMobile(raiz), timeout=args.timeout,
        procesar=not args.sin_procesar, dataset=dataset, carpeta_catalogos=carpeta_catalogos,
    )
    print(json.dumps(resultado, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
