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
    fila.update(archivo=archivo, numero_guia=guia, estado_procesamiento="OK", numero_transporte="0000" + guia,
                fecha="26-11-2026", cliente="CONSTRUCTORA MBTMARCA SA", peso_kg="26000")
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
    if modo == "escritura_larga":
        # P0.3: sin heartbeat, el estado local sigue "vigente" aunque Cloud
        # venza el lease o lo entregue a otro equipo a mitad de la escritura.
        import csv
        import io
        from atlas_core import estado_confirmado as ec
        from atlas_core.procesamiento_masivo import COLUMNAS
        guia = sys.argv[3]
        lease.heartbeat_segundos = 0
        if not lease.adquirir():
            print("ERROR " + json.dumps({"motivo": lease.motivo}), flush=True)
            return 2
        fila = dict.fromkeys(COLUMNAS, "")
        fila.update(archivo=f"mobile/env-{guia}/original.jpg", numero_guia=guia, estado_procesamiento="OK")
        texto = io.StringIO()
        csv.DictWriter(texto, fieldnames=COLUMNAS, delimiter=";").writerow(fila)
        linea = texto.getvalue()
        dataset = raiz.joinpath(*DATASET.split("/"))
        archivo = open(dataset, "a", encoding="utf-8-sig", newline="")
        archivo.write(linea[: len(linea) // 2])
        archivo.flush()
        # Dato derivado del turno sin confirmar (no custodiado).
        escribir(raiz, f"reportes/turno-{guia}/viajes.csv", f"derivado de {guia}\n")
        print("ABIERTO " + json.dumps({"vigente_local": lease.vigente, "escritor_id": lease.escritor_id,
                                       "diario": lease.custodia._diario}), flush=True)
        sys.stdin.readline()  # el orquestador vence el lease y otro equipo lo toma
        vigente_antes = lease.vigente
        archivo.write(linea[len(linea) // 2:])
        archivo.close()
        control = ec.punto_de_control_tras_escritura(dataset)
        catalogo = raiz / "catalogos_privados" / "vehiculos.json"
        antes = catalogo.read_bytes()
        try:
            escribir(raiz, "catalogos_privados/vehiculos.json", json.dumps({"vehiculos": ["VIEJO99"]}))
            rechazo = None
        except Exception as error:  # noqa: BLE001
            rechazo = type(error).__name__
        intacto = catalogo.read_bytes() == antes
        lease.cerrar()
        print("RESULTADO " + json.dumps({"vigente_local_antes": vigente_antes, "punto_de_control": control,
                                         "rechazo_escritura": rechazo, "catalogo_intacto": intacto}), flush=True)
        return 0
    if modo == "turno_pausado":
        from atlas_core.procesamiento_masivo import COLUMNAS  # noqa: F401 - carga previa
        if not lease.adquirir():
            print("ERROR " + json.dumps({"motivo": lease.motivo}), flush=True)
            return 2
        ingestar(raiz, sys.argv[3], f"local/g-{sys.argv[3]}.jpg")
        contenido = dict(lease.custodia.contenido)
        print("PAUSA " + json.dumps({"escritor_id": lease.escritor_id, "contenido": contenido}), flush=True)
        sys.stdin.readline()  # el orquestador hace que "Drive" traiga el archivo del escritor anterior
        try:
            ingestar(raiz, sys.argv[4], f"local/g-{sys.argv[4]}.jpg")
            rechazo = None
        except Exception as error:  # noqa: BLE001
            rechazo = type(error).__name__
        escribir(raiz, "catalogos_privados/vehiculos.json", json.dumps({"vehiculos": ["NUEVO11"]}))
        custodia = lease.custodia
        lease.cerrar()
        print("RESULTADO " + json.dumps({"rechazo_segunda_ingesta": rechazo, "contenido": contenido,
                                         "ajenos_descartados": custodia.ajenos_descartados}), flush=True)
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
