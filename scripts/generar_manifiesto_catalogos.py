"""Genera un manifiesto determinista y sin datos personales de una fuente privada."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atlas_core.catalogos import _normalizar_nombre_chofer
from atlas_core.fuente_catalogos import ARCHIVOS_REQUERIDOS, validar_fuente_catalogos


def sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def metricas_choferes(choferes: dict[str, dict[str, object]]) -> dict[str, int]:
    """Separa alias almacenados de canónicos y variantes usadas por fuzzy."""
    registros = list(choferes.values())
    activos = [r for r in registros if r.get("activo") is True]
    aliases = [
        str(alias).strip()
        for registro in registros
        for alias in registro.get("aliases", [])
        if str(alias).strip()
    ]
    aliases_activos = [
        str(alias).strip()
        for registro in activos
        for alias in registro.get("aliases", [])
        if str(alias).strip()
    ]
    canonicos_activos = {
        _normalizar_nombre_chofer(str(registro.get("nombre", "")))
        for registro in activos
        if str(registro.get("nombre", "")).strip()
    }
    aliases_activos_normalizados = {
        _normalizar_nombre_chofer(alias) for alias in aliases_activos
    }
    variantes_activas = [
        str(variante).strip()
        for registro in activos
        for variante in [registro.get("nombre", ""), *registro.get("aliases", [])]
        if str(variante).strip()
    ]
    valores_almacenados = [
        str(registro.get("nombre", "")).strip() for registro in registros
        if str(registro.get("nombre", "")).strip()
    ] + aliases
    return {
        "choferes_total": len(registros),
        "choferes_activos": len(activos),
        "choferes_inactivos": len(registros) - len(activos),
        "nombres_canonicos": sum(
            bool(str(registro.get("nombre", "")).strip()) for registro in registros
        ),
        "aliases_explicitos_total": len(aliases),
        "aliases_explicitos_unicos_literal": len(set(aliases)),
        "aliases_explicitos_unicos_normalizados": len(
            {_normalizar_nombre_chofer(alias) for alias in aliases}
        ),
        "aliases_explicitos_colisiones_normalizadas": len(aliases) - len(
            {_normalizar_nombre_chofer(alias) for alias in aliases}
        ),
        "aliases_normalizados_que_coinciden_con_canonico_activo": len(
            aliases_activos_normalizados & canonicos_activos
        ),
        "aliases_explicitos_inactivos": len(aliases) - len(aliases_activos),
        "aliases_explicitos_vacios": sum(
            not str(alias).strip()
            for registro in registros for alias in registro.get("aliases", [])
        ),
        "registros_sin_alias_explicitos": sum(
            not any(str(alias).strip() for alias in registro.get("aliases", []))
            for registro in registros
        ),
        "variantes_normalizadas_generadas": sum(
            _normalizar_nombre_chofer(valor) != valor.upper()
            for valor in valores_almacenados
        ),
        "variantes_fuzzy_activas_total": len(variantes_activas),
        "variantes_fuzzy_activas_unicas_normalizadas": len(
            {_normalizar_nombre_chofer(valor) for valor in variantes_activas}
        ),
        "aliases_utilizables_fuzzy_unicos_normalizados": len(
            aliases_activos_normalizados - canonicos_activos
        ),
        "identidades_chofer_pendientes": sum(
            str(identidad).upper().startswith("PENDIENTE") for identidad in choferes
        ),
    }


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
        "esquema": "atlas-catalogos-manifiesto-v2",
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
            **metricas_choferes(choferes),
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
            "contrato_alias_choferes": (
                "alias explicito = valor no vacio almacenado en aliases; nombres "
                "canonicos y variantes normalizadas se cuentan por separado"
            ),
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
