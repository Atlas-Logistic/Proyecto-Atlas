"""Un equipo de la validación del diario remoto (P0.1). SOLO PRUEBA.

Se ejecuta como proceso propio, con su LOCALAPPDATA (identidad de escritor)
y su raíz (su copia de Drive). Exige un Worker local 127.0.0.1: nunca Cloud
productiva.

  equipo.py trabajar <raiz>  escribe datos operacionales, anuncia ESCRITO y
                             espera a que lo maten (pérdida del equipo).
  equipo.py turno <raiz>     turno normal: escribe, confirma y libera.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from pathlib import Path


def escribir(raiz: Path, rel: str, texto: str) -> None:
    destino = raiz.joinpath(*rel.split("/"))
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(f".{destino.name}.{os.getpid()}.tmp")
    temporal.write_text(texto, encoding="utf-8")
    os.replace(temporal, destino)


def main() -> int:
    modo, raiz = sys.argv[1], Path(sys.argv[2])
    url = os.environ.get("ATLAS_CLOUD_MOBILE_URL", "")
    if not url.startswith("https://127.0.0.1:"):
        raise SystemExit("validación sólo contra Worker local 127.0.0.1")
    from atlas_core.escritor_operativo import lease_desde_entorno
    lease = lease_desde_entorno(raiz=raiz)
    if modo == "trabajar":
        if not lease.adquirir():
            print("ERROR " + json.dumps({"motivo": lease.motivo}), flush=True)
            return 2
        dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
        with dataset.open(encoding="utf-8-sig", newline="") as archivo:
            filas = list(csv.reader(archivo, delimiter=";"))
        filas.append(["mobile/env-perdido/original.jpg", "900001", "OK"])
        texto = "\n".join(";".join(f) for f in filas) + "\n"
        escribir(raiz, "operacion/actual/analisis_completo_guias.csv", texto)
        escribir(raiz, "operacion/mobile/envios/env-perdido/envio.json",
                 json.dumps({"envio_id": "env-perdido", "estado": "PROCESADO"}))
        c = lease.custodia
        print("ESCRITO " + json.dumps({
            "escritor_id": lease.escritor_id, "epoca": lease.epoca, "diario": c._diario,
            "sha256": c.manifiesto[c._diario], "version": c.version, "version_base": c._version_turno,
            "rutas": sorted(c.modificadas)}), flush=True)
        time.sleep(3600)  # el orquestador mata el proceso: sin confirmar ni liberar
        return 0
    if modo == "turno":
        with lease:
            if not lease.adquirir():
                print("ERROR " + json.dumps({"motivo": lease.motivo}), flush=True)
                return 2
            escribir(raiz, "catalogos_privados/vehiculos.json", json.dumps({"vehiculos": ["BBBB22"]}))
            resumen = dict(lease.custodia.resumen)
            epoca = lease.epoca
        print("TURNO " + json.dumps({"escritor_id": lease.escritor_id, "epoca": epoca, "resumen": resumen}), flush=True)
        return 0
    raise SystemExit(f"modo desconocido: {modo}")


if __name__ == "__main__":
    raise SystemExit(main())
