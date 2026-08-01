"""Instantánea inmutable de clientes canónicos y empresas legado opcionales."""

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


@dataclass(frozen=True)
class InstantaneaCatalogoClientes:
    registros: Mapping[str, Mapping[str, Any]]
    sha256: str
    version: str
    cantidad_registros: int
    ids_invalidos: tuple[str, ...]
    fecha_creacion: datetime | None = None


def _registros_clientes(
    catalogo: Mapping[str, Any] | Iterable[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    if isinstance(catalogo, Mapping):
        registros = catalogo.get("clientes", ())
    else:
        registros = catalogo
    if isinstance(registros, (str, bytes, Mapping)) or not isinstance(
        registros, Iterable
    ):
        raise TypeError("el catálogo de clientes debe contener una lista")
    return [registro for registro in registros if isinstance(registro, Mapping)]


def _normalizar_cliente(registro: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "cliente_id": str(registro.get("cliente_id", "")).strip(),
        "razon_social": str(registro.get("razon_social", "")).strip(),
        "nombre_comercial": str(registro.get("nombre_comercial", "")).strip(),
        "rut": str(registro.get("rut", "")).strip(),
        "aliases": tuple(
            str(alias).strip()
            for alias in registro.get("aliases", ())
            if str(alias).strip()
        ),
        "estado_calidad": str(
            registro.get("estado_calidad", "PENDIENTE")
        ).strip().upper(),
        "estado_vigencia": str(
            registro.get("estado_vigencia", "ACTIVO")
        ).strip().upper(),
        "origen": "catalogo_clientes",
    }


def _empresas_por_rut(
    catalogo_empresas: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Mapping[str, Any]]:
    return {
        str(rut): registro
        for rut, registro in (catalogo_empresas or {}).items()
        if isinstance(registro, Mapping)
    }


def crear_snapshot_catalogo_clientes(
    catalogo_clientes: Mapping[str, Any] | Iterable[Mapping[str, Any]],
    catalogo_empresas: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    fecha_creacion: datetime | None = None,
) -> InstantaneaCatalogoClientes:
    """Copia clientes y usa empresas solo como relación/fallback por RUT."""
    normalizados = [
        _normalizar_cliente(registro)
        for registro in _registros_clientes(catalogo_clientes)
    ]
    empresas = _empresas_por_rut(catalogo_empresas)
    rut_clientes = {
        registro["rut"].replace(".", "").replace("-", "").upper()
        for registro in normalizados
        if registro["rut"]
    }
    for registro in normalizados:
        rut_limpio = registro["rut"].replace(".", "").replace("-", "").upper()
        empresa = empresas.get(rut_limpio)
        if empresa:
            nombre_empresa = str(empresa.get("nombre", "")).strip()
            if nombre_empresa and nombre_empresa not in registro["aliases"]:
                registro["aliases"] = (*registro["aliases"], nombre_empresa)
            registro["relacion_empresa_rut"] = rut_limpio
    for rut, empresa in sorted(empresas.items()):
        rut_limpio = rut.replace(".", "").replace("-", "").upper()
        if rut_limpio in rut_clientes:
            continue
        nombre = str(empresa.get("nombre", "")).strip()
        if not nombre:
            continue
        normalizados.append({
            "cliente_id": f"empresa:{rut_limpio}",
            "razon_social": nombre,
            "nombre_comercial": "",
            "rut": rut_limpio,
            "aliases": (),
            "estado_calidad": "LEGADO",
            "estado_vigencia": "ACTIVO",
            "origen": "catalogo_empresas",
            "relacion_empresa_rut": rut_limpio,
        })

    copia: dict[str, Mapping[str, Any]] = {}
    invalidos: list[str] = []
    for registro in sorted(
        normalizados,
        key=lambda item: (item["cliente_id"], item["razon_social"]),
    ):
        identificador = registro["cliente_id"]
        if not identificador or identificador in copia:
            invalidos.append(identificador)
            identificador = f"INVALIDO:{len(copia)}:{identificador}"
        congelado = congelar_profundo(registro)
        if not isinstance(congelado, Mapping):
            raise TypeError("el registro congelado debe ser mapping")
        copia[identificador] = congelado

    serializable = {
        identificador: descongelar(copia[identificador])
        for identificador in sorted(copia)
    }
    canonico = json.dumps(
        serializable,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    huella = hashlib.sha256(canonico).hexdigest()
    return InstantaneaCatalogoClientes(
        MappingProxyType(copia),
        huella,
        f"clientes-sha256:{huella}",
        len(copia),
        tuple(sorted(set(invalidos))),
        fecha_creacion,
    )
