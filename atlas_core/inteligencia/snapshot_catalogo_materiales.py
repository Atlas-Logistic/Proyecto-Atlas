"""Instantánea opcional e inmutable de materiales; Atlas no posee catálogo productivo."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from atlas_core.inteligencia.contrato_multicampo import congelar_profundo, descongelar


@dataclass(frozen=True)
class InstantaneaCatalogoMateriales:
    registros: Mapping[str, Mapping[str, Any]]
    sha256: str
    version: str
    cantidad_registros: int
    ids_invalidos: tuple[str, ...]


def crear_snapshot_catalogo_materiales(
    catalogo: Mapping[str, Any] | Iterable[Mapping[str, Any]] = (),
) -> InstantaneaCatalogoMateriales:
    registros = catalogo.get("materiales", ()) if isinstance(catalogo, Mapping) else catalogo
    if isinstance(registros, (str, bytes, Mapping)) or not isinstance(registros, Iterable):
        raise TypeError("el catálogo de materiales debe contener una lista")
    copia: dict[str, Mapping[str, Any]] = {}
    invalidos: list[str] = []
    for posicion, item in enumerate(registros):
        if not isinstance(item, Mapping):
            continue
        identificador = str(item.get("material_id", "")).strip()
        normalizado = {
            "material_id": identificador,
            "descripcion_oficial": str(item.get("descripcion_oficial", "")).strip(),
            "familia_material": str(item.get("familia_material", "")).strip(),
            "tipo_carga": str(item.get("tipo_carga", "")).strip().upper(),
            "aliases": tuple(str(x).strip() for x in item.get("aliases", ()) if str(x).strip()),
            "abreviaciones": tuple(str(x).strip() for x in item.get("abreviaciones", ()) if str(x).strip()),
            "estado_calidad": str(item.get("estado_calidad", "PENDIENTE")).upper(),
            "estado_vigencia": str(item.get("estado_vigencia", "ACTIVO")).upper(),
        }
        clave = identificador
        if not clave or clave in copia:
            invalidos.append(clave)
            clave = f"INVALIDO:{posicion}:{clave}"
        copia[clave] = congelar_profundo(normalizado)
    serializable = {k: descongelar(copia[k]) for k in sorted(copia)}
    canonico = json.dumps(serializable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    huella = hashlib.sha256(canonico).hexdigest()
    return InstantaneaCatalogoMateriales(
        MappingProxyType(copia), huella, f"materiales-sha256:{huella}",
        len(copia), tuple(sorted(set(invalidos))),
    )
