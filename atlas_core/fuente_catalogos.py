"""Resolución y validación explícita de la fuente privada de catálogos."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


VARIABLE_CATALOGOS = "ATLAS_CATALOGOS_DIR"
ARCHIVOS_REQUERIDOS = (
    "choferes.json",
    "clientes.json",
    "empresas.json",
    "destinos_maestros.json",
    "vehiculos.json",
    "plantas.json",
    "rutas.json",
)


class ErrorFuenteCatalogos(RuntimeError):
    """La fuente configurada no puede utilizarse de forma segura."""


@dataclass(frozen=True)
class EstadoFuenteCatalogos:
    ruta: Path | None
    modo: str
    conteos: dict[str, int]
    advertencias: tuple[str, ...] = ()


def resolver_fuente_catalogos(
    ruta: str | Path | None = None, *, permitir_sin_catalogos: bool = False
) -> Path | None:
    """Resuelve una ruta explícita o la variable controlada de entorno."""
    valor = ruta if ruta not in (None, "") else os.environ.get(VARIABLE_CATALOGOS)
    if valor in (None, ""):
        if permitir_sin_catalogos:
            return None
        raise ErrorFuenteCatalogos(
            f"Falta la fuente de catálogos. Configure --catalogos o {VARIABLE_CATALOGOS}; "
            "use --sin-catalogos solo para un modo explícito sin catálogos."
        )
    fuente = Path(valor).expanduser().resolve()
    if not fuente.exists():
        raise ErrorFuenteCatalogos(f"La fuente de catálogos no existe: {fuente}")
    if not fuente.is_dir():
        raise ErrorFuenteCatalogos(f"La fuente de catálogos no es una carpeta: {fuente}")
    return fuente


def _leer_json(ruta: Path) -> Any:
    try:
        with ruta.open("r", encoding="utf-8") as archivo:
            return json.load(archivo)
    except json.JSONDecodeError as error:
        raise ErrorFuenteCatalogos(f"JSON inválido en {ruta.name}: {error}") from error


def _registros(nombre: str, contenido: Any) -> list[tuple[str, dict[str, Any]]]:
    if nombre in {"clientes.json", "destinos_maestros.json", "plantas.json", "rutas.json"}:
        clave = {
            "clientes.json": "clientes",
            "destinos_maestros.json": "destinos",
            "plantas.json": "plantas",
            "rutas.json": "rutas",
        }[nombre]
        if not isinstance(contenido, dict) or not isinstance(contenido.get(clave), list):
            raise ErrorFuenteCatalogos(f"Esquema inválido en {nombre}: falta la lista {clave}")
        return [
            (str(registro.get(f"{clave[:-1]}_id", indice)), registro)
            for indice, registro in enumerate(contenido[clave])
            if isinstance(registro, dict)
        ]
    if not isinstance(contenido, dict):
        raise ErrorFuenteCatalogos(f"Esquema inválido en {nombre}: se esperaba un objeto")
    if any(not isinstance(registro, dict) for registro in contenido.values()):
        raise ErrorFuenteCatalogos(f"Esquema inválido en {nombre}: registro no es objeto")
    return [(str(clave), registro) for clave, registro in contenido.items()]


def validar_fuente_catalogos(
    ruta: str | Path | None = None, *, permitir_sin_catalogos: bool = False
) -> EstadoFuenteCatalogos:
    """Valida existencia, esquemas, identidades y estados sin modificar archivos."""
    fuente = resolver_fuente_catalogos(
        ruta, permitir_sin_catalogos=permitir_sin_catalogos
    )
    if fuente is None:
        return EstadoFuenteCatalogos(None, "SIN_CATALOGOS_EXPLICITO", {})

    faltantes = [nombre for nombre in ARCHIVOS_REQUERIDOS if not (fuente / nombre).is_file()]
    if faltantes:
        raise ErrorFuenteCatalogos(
            "Fuente incompleta; faltan: " + ", ".join(sorted(faltantes))
        )

    conteos: dict[str, int] = {}
    for nombre in ARCHIVOS_REQUERIDOS:
        registros = _registros(nombre, _leer_json(fuente / nombre))
        identidades = [identidad.strip().upper() for identidad, _ in registros]
        if any(not identidad for identidad in identidades):
            raise ErrorFuenteCatalogos(f"Identificador vacío en {nombre}")
        if len(identidades) != len(set(identidades)):
            raise ErrorFuenteCatalogos(f"Identificador duplicado en {nombre}")
        for _, registro in registros:
            if "activo" in registro and not isinstance(registro["activo"], bool):
                raise ErrorFuenteCatalogos(f"Estado activo inválido en {nombre}")
            if "estado_vigencia" in registro and registro["estado_vigencia"] not in {
                "ACTIVO", "INACTIVO", "ACTIVA", "INACTIVA"
            }:
                raise ErrorFuenteCatalogos(f"estado_vigencia inválido en {nombre}")
        conteos[nombre] = len(registros)
    return EstadoFuenteCatalogos(fuente, "CATALOGOS_VALIDOS", conteos)
