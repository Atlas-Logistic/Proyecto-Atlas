"""Snapshot inmutable de clientes, destinos canónicos y plantas."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from atlas_core.inteligencia.contrato_multicampo import (
    congelar_profundo,
    descongelar,
)
from atlas_core.inteligencia.motor import normalizar
from atlas_core.inteligencia.normalizacion_geografica import (
    normalizar_region_chile,
)


def normalizar_texto_destino(valor: object) -> str:
    return " ".join(normalizar(valor).split())


def region_canonica(valor: object) -> str:
    resultado = normalizar_region_chile(valor)
    return (
        resultado.canonico
        if resultado.reconocido
        else normalizar_texto_destino(valor)
    )


@dataclass(frozen=True)
class InstantaneaCatalogoDestinos:
    destinos: Mapping[str, Mapping[str, Any]]
    clientes: Mapping[str, Mapping[str, Any]]
    plantas: Mapping[str, Mapping[str, Any]]
    sha256: str
    version: str
    cantidad_destinos: int
    cantidad_clientes: int
    cantidad_plantas: int
    ids_invalidos: tuple[str, ...]
    fecha_creacion: datetime | None = None


def _lista(
    catalogo: Mapping[str, Any] | Iterable[Mapping[str, Any]],
    clave: str,
) -> list[Mapping[str, Any]]:
    contenido: Any = catalogo.get(clave, ()) if isinstance(
        catalogo, Mapping
    ) else catalogo
    if isinstance(contenido, (str, bytes, Mapping)) or not isinstance(
        contenido, Iterable
    ):
        raise TypeError(f"el catálogo {clave} debe contener una lista")
    return [r for r in contenido if isinstance(r, Mapping)]


def _congelar_por_id(
    registros: Iterable[dict[str, Any]], campo_id: str, invalidos: list[str]
) -> Mapping[str, Mapping[str, Any]]:
    copia: dict[str, Mapping[str, Any]] = {}
    for registro in sorted(
        registros,
        key=lambda item: (str(item[campo_id]), repr(sorted(item.items()))),
    ):
        identificador = str(registro[campo_id]).strip()
        if not identificador or identificador in copia:
            invalidos.append(identificador)
            identificador = f"INVALIDO:{len(copia)}:{identificador}"
        congelado = congelar_profundo(registro)
        if not isinstance(congelado, Mapping):
            raise TypeError("el registro congelado debe ser mapping")
        copia[identificador] = congelado
    return MappingProxyType(copia)


def crear_snapshot_catalogo_destinos(
    catalogo_destinos: Mapping[str, Any] | Iterable[Mapping[str, Any]],
    catalogo_clientes: Mapping[str, Any] | Iterable[Mapping[str, Any]],
    catalogo_plantas: Mapping[str, Any] | Iterable[Mapping[str, Any]],
    *,
    fecha_creacion: datetime | None = None,
) -> InstantaneaCatalogoDestinos:
    invalidos: list[str] = []
    destinos = _congelar_por_id(
        ({
            "destino_id": str(r.get("destino_id", "")).strip(),
            "cliente_id": str(r.get("cliente_id", "")).strip(),
            "nombre_destino": str(r.get("nombre_destino", "")).strip(),
            "direccion": str(r.get("direccion", "")).strip(),
            "comuna": str(r.get("comuna", "")).strip().upper(),
            "region": region_canonica(r.get("region", "")),
            "pais": str(r.get("pais", "CHILE")).strip().upper(),
            "aliases": tuple(
                str(a).strip() for a in r.get("aliases", ()) if str(a).strip()
            ),
            "estado_calidad": str(
                r.get("estado_calidad", "PENDIENTE")
            ).strip().upper(),
            "estado_vigencia": str(
                r.get("estado_vigencia", "ACTIVO")
            ).strip().upper(),
            "origen": "catalogo_destinos_maestros",
        } for r in _lista(catalogo_destinos, "destinos")),
        "destino_id",
        invalidos,
    )
    clientes = _congelar_por_id(
        ({
            "cliente_id": str(r.get("cliente_id", "")).strip(),
            "razon_social": str(r.get("razon_social", "")).strip(),
            "nombre_comercial": str(r.get("nombre_comercial", "")).strip(),
            "rut": str(r.get("rut", "")).strip(),
            "aliases": tuple(
                str(a).strip() for a in r.get("aliases", ()) if str(a).strip()
            ),
        } for r in _lista(catalogo_clientes, "clientes")),
        "cliente_id",
        invalidos,
    )
    plantas = _congelar_por_id(
        ({
            "planta_id": str(r.get("planta_id", "")).strip(),
            "nombre": str(r.get("nombre", "")).strip(),
            "direccion": str(r.get("direccion", "")).strip(),
            "comuna": str(r.get("comuna", "")).strip().upper(),
            "region": region_canonica(r.get("region", "")),
            "estado_calidad": str(
                r.get("estado_calidad", "PENDIENTE")
            ).strip().upper(),
            "estado_vigencia": str(
                r.get("estado_vigencia", "ACTIVA")
            ).strip().upper(),
            "origen": "catalogo_plantas",
        } for r in _lista(catalogo_plantas, "plantas")),
        "planta_id",
        invalidos,
    )
    serializable = {
        "destinos": {
            k: descongelar(v) for k, v in sorted(destinos.items())
        },
        "clientes": {
            k: descongelar(v) for k, v in sorted(clientes.items())
        },
        "plantas": {
            k: descongelar(v) for k, v in sorted(plantas.items())
        },
    }
    canonico = json.dumps(
        serializable,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    huella = hashlib.sha256(canonico).hexdigest()
    return InstantaneaCatalogoDestinos(
        destinos,
        clientes,
        plantas,
        huella,
        f"destinos-sha256:{huella}",
        len(destinos),
        len(clientes),
        len(plantas),
        tuple(sorted(set(invalidos))),
        fecha_creacion,
    )
