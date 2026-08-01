"""Instantánea semántica e inmutable del catálogo de choferes."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping

from atlas_core.inteligencia.contrato_multicampo import congelar_profundo, descongelar
from atlas_core.modelos import EstadoValidacion
from atlas_core.validadores import validar_rut_chileno


def _rut_valido(clave: str) -> bool:
    limpio = re.sub(r"[^0-9Kk]", "", clave).upper()
    if len(limpio) < 2:
        return False
    return validar_rut_chileno(
        f"{limpio[:-1]}-{limpio[-1]}"
    ).estado is EstadoValidacion.VALIDO


def _clave_valida(clave: str) -> bool:
    return bool(clave.strip()) and (
        _rut_valido(clave)
        or re.fullmatch(r"PENDIENTE[A-Z0-9_-]+", clave.strip().upper()) is not None
    )


@dataclass(frozen=True)
class InstantaneaCatalogoChoferes:
    registros: Mapping[str, Mapping[str, Any]]
    sha256: str
    version: str
    cantidad_registros: int
    claves_invalidas: tuple[str, ...]
    fecha_creacion: datetime | None = None


def crear_snapshot_catalogo_choferes(
    catalogo: Mapping[str, Mapping[str, Any]],
    *,
    fecha_creacion: datetime | None = None,
) -> InstantaneaCatalogoChoferes:
    copia: dict[str, Mapping[str, Any]] = {}
    invalidas: list[str] = []
    for clave_original in sorted(catalogo, key=str):
        clave = str(clave_original)
        registro = catalogo[clave_original]
        if not isinstance(registro, Mapping):
            invalidas.append(clave)
            continue
        congelado = congelar_profundo(registro)
        if not isinstance(congelado, Mapping):
            raise TypeError("el registro congelado debe ser mapping")
        copia[clave] = congelado
        if not _clave_valida(clave):
            invalidas.append(clave)
    serializable = {clave: descongelar(copia[clave]) for clave in sorted(copia)}
    canonico = json.dumps(
        serializable, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    huella = hashlib.sha256(canonico).hexdigest()
    return InstantaneaCatalogoChoferes(
        MappingProxyType(copia), huella, f"choferes-sha256:{huella}",
        len(copia), tuple(sorted(set(invalidas))), fecha_creacion,
    )
