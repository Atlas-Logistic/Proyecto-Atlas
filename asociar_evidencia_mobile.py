"""Guía firmada enviada desde Atlas Mobile (rol EVIDENCIA_FIRMADA).

  --envio-id X --numero-guia G   asociación EXPLÍCITA decidida por una persona
                                 (la guía debe ser exactamente UN documento).
  --reintentar                   reintenta la asociación AUTOMÁTICA de todas
                                 las evidencias pendientes (sólo si es inequívoca).

Nunca crea filas ni viajes, nunca procesa OCR, nunca toca fecha_ingesta."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from atlas_core.almacenamiento_portable import leer_estado_operacion, resolver_raiz_atlas
from atlas_core.mobile import (
    ErrorEnvioMobile, RepositorioEnviosMobile, asociar_evidencia_firmada_mobile_manual,
    reintentar_evidencias_firmadas_pendientes,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raiz-atlas", type=Path)
    parser.add_argument("--envio-id")
    parser.add_argument("--numero-guia")
    parser.add_argument("--actor", default="DESKTOP")
    parser.add_argument("--reintentar", action="store_true")
    args = parser.parse_args()
    raiz = resolver_raiz_atlas(args.raiz_atlas)
    estado = leer_estado_operacion(raiz=raiz) or {}
    dataset = raiz / estado.get("dataset_operacional", "operacion/actual/analisis_completo_guias.csv")
    repositorio = RepositorioEnviosMobile(raiz)
    try:
        if args.reintentar:
            resultado: object = {"ok": True, "resultados": reintentar_evidencias_firmadas_pendientes(repositorio, dataset=dataset)}
        elif args.envio_id and args.numero_guia:
            resultado = {"ok": True, **asociar_evidencia_firmada_mobile_manual(
                repositorio, args.envio_id, dataset=dataset, numero_guia=args.numero_guia, actor=args.actor,
            )}
        else:
            parser.error("use --reintentar o --envio-id junto con --numero-guia")
    except ErrorEnvioMobile as error:
        resultado = {"ok": False, "error": str(error)}
    print(json.dumps(resultado, ensure_ascii=False))


if __name__ == "__main__":
    main()
