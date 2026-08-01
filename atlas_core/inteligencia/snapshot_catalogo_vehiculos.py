"""Instantánea inmutable y auditable del catálogo de vehículos."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from atlas_core.inteligencia.contrato_multicampo import (
    congelar_profundo,
    descongelar,
)


def normalizar_patente(valor: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(valor or "").upper())


def normalizar_rol_vehiculo(valor: object) -> str:
    texto = unicodedata.normalize("NFKD", str(valor or "").upper())
    texto = "".join(
        caracter for caracter in texto if not unicodedata.combining(caracter)
    )
    limpio = re.sub(r"[^A-Z0-9]", "", texto)
    if limpio in {"CARRO", "RAMPLA", "REMOLQUE", "SEMIRREMOLQUE"}:
        return "RAMPLA"
    if limpio in {"TRACTO", "TRACTOCAMION"}:
        return "TRACTO"
    if limpio in {
        "CAJITA", "CAMION", "CAMIONCAJITA", "CAMIONRIGIDO", "RIGIDO",
    }:
        return "CAMION_CAJITA"
    return limpio or "DESCONOCIDO"


@dataclass(frozen=True)
class InstantaneaCatalogoVehiculos:
    registros: Mapping[str, Mapping[str, Any]]
    sha256: str
    version: str
    cantidad_registros: int
    ids_invalidos: tuple[str, ...]
    fecha_creacion: datetime | None = None


def _iterar_registros(
    catalogo: Mapping[str, Any] | Iterable[Mapping[str, Any]],
) -> list[tuple[str, Mapping[str, Any]]]:
    if isinstance(catalogo, Mapping):
        contenido = catalogo.get("vehiculos", catalogo)
        if isinstance(contenido, Mapping):
            return [
                (str(clave), registro)
                for clave, registro in contenido.items()
                if isinstance(registro, Mapping)
            ]
        catalogo = contenido
    if isinstance(catalogo, (str, bytes, Mapping)) or not isinstance(
        catalogo, Iterable
    ):
        raise TypeError("el catálogo de vehículos debe ser mapping o lista")
    return [
        (str(indice), registro)
        for indice, registro in enumerate(catalogo)
        if isinstance(registro, Mapping)
    ]


def crear_snapshot_catalogo_vehiculos(
    catalogo: Mapping[str, Any] | Iterable[Mapping[str, Any]],
    *,
    fecha_creacion: datetime | None = None,
) -> InstantaneaCatalogoVehiculos:
    copia: dict[str, Mapping[str, Any]] = {}
    invalidos: list[str] = []
    normalizados: list[dict[str, Any]] = []
    for clave, registro in _iterar_registros(catalogo):
        patente = normalizar_patente(registro.get("patente", clave))
        identificador = str(
            registro.get("vehiculo_id", f"vehiculo:{patente}")
        ).strip()
        aliases = tuple(
            normalizar_patente(alias)
            for alias in registro.get("aliases", ())
            if normalizar_patente(alias)
        )
        normalizados.append({
            "vehiculo_id": identificador,
            "patente": patente,
            "tipo": normalizar_rol_vehiculo(
                registro.get("rol", registro.get("tipo", ""))
            ),
            "nombre": str(
                registro.get("nombre", registro.get("descripcion", ""))
            ).strip(),
            "aliases": aliases,
            "aliases_nombre": tuple(
                str(alias).strip()
                for alias in registro.get("aliases_nombre", ())
                if str(alias).strip()
            ),
            "estado_vigencia": str(
                registro.get("estado_vigencia", "ACTIVO")
            ).strip().upper(),
            "estado_calidad": str(
                registro.get("estado_calidad", "CONFIRMADO")
            ).strip().upper(),
            "origen": "catalogo_vehiculos",
        })

    for registro in sorted(
        normalizados,
        key=lambda item: (item["vehiculo_id"], item["patente"]),
    ):
        identificador = registro["vehiculo_id"]
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
    return InstantaneaCatalogoVehiculos(
        MappingProxyType(copia),
        huella,
        f"vehiculos-sha256:{huella}",
        len(copia),
        tuple(sorted(set(invalidos))),
        fecha_creacion,
    )
