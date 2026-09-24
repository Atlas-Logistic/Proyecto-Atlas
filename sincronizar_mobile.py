"""CLI del Bloque MOBILE SINCRONIZACIÓN PULL V1.

El PC de Atlas (Motor de Javier) INICIA la conexión hacia el receptor
central Mobile -- nunca al revés; el receptor central nunca entra a este
PC, nunca abre un puerto doméstico. Lista lo que el receptor central
todavía tiene pendiente de este consumidor, descarga y verifica por hash
lo que falta, lo aterriza localmente de forma idempotente (mismo
`RepositorioEnviosMobile.recibir()` que ya usa una subida LAN directa), y
-- salvo `--sin-procesar` -- dispara el procesamiento Mobile existente
(OCR/B1/reporte) para cualquier envío local que siga en `RECIBIDO`.

Pensado para correr periódicamente (cron/Programador de tareas) o a mano,
SIEMPRE desde el PC de Atlas -- el receptor central nunca ejecuta nada de
lo que este script hace, sólo responde lecturas + una confirmación.
"""
from __future__ import annotations

import argparse
import json
import os
import socket

from atlas_core.almacenamiento_portable import leer_estado_operacion, resolver_raiz_atlas
from atlas_core.fuente_catalogos import ErrorFuenteCatalogos, validar_fuente_catalogos
from atlas_core.mobile import RepositorioEnviosMobile
from atlas_core.mobile_sync_cliente import sincronizar_envios_pendientes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="URL del receptor central Mobile, p. ej. https://mobile.dttacgroup.cl")
    parser.add_argument("--token", default=os.environ.get("ATLAS_MOBILE_SYNC_TOKEN", ""), help="Por defecto lee ATLAS_MOBILE_SYNC_TOKEN")
    parser.add_argument("--raiz-atlas", default=None)
    parser.add_argument("--consumidor", default=socket.gethostname(), help="Identificador de este PC para diagnóstico (por defecto, el hostname)")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--sin-procesar", action="store_true", help="Sólo sincroniza (aterriza localmente); no dispara OCR/B1/reporte")
    args = parser.parse_args()

    if not args.token:
        parser.error("Falta --token (o la variable de entorno ATLAS_MOBILE_SYNC_TOKEN)")

    raiz = resolver_raiz_atlas(args.raiz_atlas)
    repositorio = RepositorioEnviosMobile(raiz)

    # Mismo criterio que `servidor_mobile.crear_servidor` -- nunca una
    # resolución paralela de dataset/catálogos.
    estado = leer_estado_operacion(raiz=raiz) or {}
    dataset = raiz / estado.get("dataset_operacional", "operacion/actual/analisis_completo_guias.csv")
    try:
        carpeta_catalogos = validar_fuente_catalogos(None, permitir_sin_catalogos=True).ruta
    except ErrorFuenteCatalogos:
        carpeta_catalogos = None

    resultado = sincronizar_envios_pendientes(
        base_url=args.base_url, token=args.token, repositorio=repositorio,
        dataset=dataset, carpeta_catalogos=carpeta_catalogos,
        procesar=not args.sin_procesar, timeout=args.timeout, consumidor=args.consumidor,
    )
    print(json.dumps(resultado, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
