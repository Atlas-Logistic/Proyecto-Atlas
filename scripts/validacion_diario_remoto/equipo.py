"""Un equipo de la validación del diario remoto (P0.1/P0.2). SOLO PRUEBA.

Se ejecuta como proceso propio, con su LOCALAPPDATA (identidad de escritor)
y su raíz (su copia de Drive). Exige un Worker local 127.0.0.1: nunca Cloud
productiva.

  equipo.py trabajar <raiz> <guia>  ingesta real (_escribir_filas: append
                                    directo + punto de control) y envío; anuncia
                                    ESCRITO y espera a que lo maten.
  equipo.py turno <raiz>            turno normal: cambia un catálogo.
  equipo.py turno_dataset <raiz> <guia>  turno normal: ingesta una guía.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

DATASET = "operacion/actual/analisis_completo_guias.csv"


def escribir(raiz: Path, rel: str, texto: str) -> None:
    destino = raiz.joinpath(*rel.split("/"))
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(f".{destino.name}.{os.getpid()}.tmp")
    temporal.write_text(texto, encoding="utf-8")
    os.replace(temporal, destino)


def ingestar(raiz: Path, guia: str, archivo: str) -> None:
    from atlas_core.procesamiento_masivo import COLUMNAS, _escribir_filas
    fila = dict.fromkeys(COLUMNAS, "")
    fila.update(archivo=archivo, numero_guia=guia, estado_procesamiento="OK")
    _escribir_filas(raiz.joinpath(*DATASET.split("/")), [fila])


def main() -> int:
    modo, raiz = sys.argv[1], Path(sys.argv[2])
    url = os.environ.get("ATLAS_CLOUD_MOBILE_URL", "")
    if not url.startswith("https://127.0.0.1:"):
        raise SystemExit("validación sólo contra Worker local 127.0.0.1")
    from atlas_core.escritor_operativo import lease_desde_entorno
    lease = lease_desde_entorno(raiz=raiz)
    if modo == "trabajar":
        guia = sys.argv[3]
        if not lease.adquirir():
            print("ERROR " + json.dumps({"motivo": lease.motivo}), flush=True)
            return 2
        ingestar(raiz, guia, f"mobile/env-{guia}/original.jpg")
        escribir(raiz, f"operacion/mobile/envios/env-{guia}/envio.json",
                 json.dumps({"envio_id": f"env-{guia}", "estado": "PROCESADO"}))
        c = lease.custodia
        print("ESCRITO " + json.dumps({
            "escritor_id": lease.escritor_id, "epoca": lease.epoca, "diario": c._diario,
            "sha256": c.manifiesto[c._diario], "version": c.version, "version_base": c._version_turno,
            "rutas": sorted(c.modificadas), "contenido": c.contenido, "pendientes": sorted(c.pendientes)}), flush=True)
        time.sleep(3600)  # el orquestador mata el proceso: sin confirmar ni liberar
        return 0
    if modo in {"turno", "turno_dataset"}:
        with lease:
            if not lease.adquirir():
                print("ERROR " + json.dumps({"motivo": lease.motivo}), flush=True)
                return 2
            if modo == "turno":
                escribir(raiz, "catalogos_privados/vehiculos.json", json.dumps({"vehiculos": ["BBBB22"]}))
            else:
                ingestar(raiz, sys.argv[3], f"local/g-{sys.argv[3]}.jpg")
            resumen = dict(lease.custodia.resumen)
            epoca = lease.epoca
        print("TURNO " + json.dumps({"escritor_id": lease.escritor_id, "epoca": epoca, "resumen": resumen}), flush=True)
        return 0
    raise SystemExit(f"modo desconocido: {modo}")


if __name__ == "__main__":
    raise SystemExit(main())
