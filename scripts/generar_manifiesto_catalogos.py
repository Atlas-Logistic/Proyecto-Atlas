"""Genera un manifiesto determinista y sin datos personales de una fuente privada."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from atlas_core.fuente_catalogos import ARCHIVOS_REQUERIDOS, validar_fuente_catalogos


def sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def crear_manifiesto(carpeta: Path) -> dict[str, object]:
    estado = validar_fuente_catalogos(carpeta)
    choferes = json.loads((carpeta / "choferes.json").read_text(encoding="utf-8"))
    clientes = json.loads((carpeta / "clientes.json").read_text(encoding="utf-8"))["clientes"]
    empresas = json.loads((carpeta / "empresas.json").read_text(encoding="utf-8"))
    destinos = json.loads(
        (carpeta / "destinos_maestros.json").read_text(encoding="utf-8")
    )["destinos"]
    ruts_clientes = {
        "".join(c for c in str(registro.get("rut", "")).upper() if c.isdigit() or c == "K")
        for registro in clientes if registro.get("rut")
    }
    ruts_empresas = set(empresas)
    return {
        "esquema": "atlas-catalogos-manifiesto-v1",
        "fecha": "2026-07-29",
        "archivos": [
            {
                "nombre": nombre,
                "sha256": sha256(carpeta / nombre),
                "registros": estado.conteos[nombre],
                "precedencia": {
                    "choferes.json": 1, "clientes.json": 1,
                    "destinos_maestros.json": 1, "empresas.json": 2,
                    "vehiculos.json": 1, "plantas.json": 1, "rutas.json": 1,
                }[nombre],
            }
            for nombre in sorted(ARCHIVOS_REQUERIDOS)
        ],
        "conteos": {
            "choferes_total": len(choferes),
            "choferes_activos": sum(r.get("activo") is True for r in choferes.values()),
            "choferes_inactivos": sum(r.get("activo") is False for r in choferes.values()),
            "aliases_choferes": sum(len(r.get("aliases", [])) for r in choferes.values()),
            "clientes_confirmados_activos": sum(
                r.get("estado_calidad") == "CONFIRMADO"
                and r.get("estado_vigencia") == "ACTIVO" for r in clientes
            ),
            "empresas": len(empresas),
            "destinos_total": len(destinos),
            "destinos_activos": sum(r.get("estado_vigencia") == "ACTIVO" for r in destinos),
            "destinos_confirmados": sum(r.get("estado_calidad") == "CONFIRMADO" for r in destinos),
            "destinos_pendientes": sum(r.get("estado_calidad") == "PENDIENTE" for r in destinos),
            "vehiculos": estado.conteos["vehiculos.json"],
            "plantas": estado.conteos["plantas.json"],
            "rutas": estado.conteos["rutas.json"],
        },
        "relaciones": {
            "empresas_relacionadas_por_rut_con_clientes": len(ruts_empresas & ruts_clientes),
            "empresas_sin_cliente_por_rut": len(ruts_empresas - ruts_clientes),
            "clientes_sin_empresa_por_rut": len(ruts_clientes - ruts_empresas),
        },
        "conflictos": {
            "identificadores_duplicados": 0,
            "promociones_automaticas_ground_truth": 0,
            "texto_ocr_promovido": 0,
        },
        "reglas": {
            "choferes": "solo activos; umbral 0.85; margen 0.05; original ante duda",
            "clientes": "solo CONFIRMADO y ACTIVO como candidatos productivos",
            "empresas": "relacionar por RUT; no mezclar sin identidad estable",
            "destinos": "activo no implica confirmado; Ground Truth no se promueve",
            "archivos_solo_lectura": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("carpeta", type=Path)
    parser.add_argument("--salida", type=Path, required=True)
    args = parser.parse_args()
    contenido = json.dumps(
        crear_manifiesto(args.carpeta), ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    args.salida.write_text(contenido, encoding="utf-8")
    print(sha256(args.salida))


if __name__ == "__main__":
    main()
