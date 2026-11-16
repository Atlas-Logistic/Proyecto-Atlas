"""Publicación Motor -> Cloud de la asignación vigente confirmada de vehículo.

Sincronización interna: Cloud la usa sólo para vincular a la patente correcta
los documentos de vehículo que envía un chofer desde Mobile, sin mostrársela.
Motor es la única autoridad y usa la misma regla que la ficha Desktop
(`fichas_choferes.asignaciones_de_chofer`): confirmaciones humanas del
catálogo de vehículos, nunca OCR ni viajes históricos. Se publican el tracto
y la rampla CONFIRMADOS (un conflicto no se publica) de choferes activos del
catálogo, cada uno por su rol: los tractos en `asignaciones` (contrato de
siempre, que un Cloud anterior sigue entendiendo) y las ramplas en `ramplas`
(un Cloud anterior las ignora). Lo que no se publica, Cloud lo revoca.

Si el catálogo de choferes o de vehículos no se puede leer no se publica
nada: un catálogo ausente nunca debe revocar todas las asignaciones.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

from atlas_core.catalogo_vehiculos import (
    CatalogoVehiculosAusenteError, CatalogoVehiculosCorruptoError, VehiculoDuplicadoError,
    VersionCatalogoVehiculosDesconocidaError, cargar_catalogo_vehiculos,
)
from atlas_core.catalogos import rut_canonico_de_registro_chofer
from atlas_core.cloud_mobile_sync_cliente import _json
from atlas_core.fichas_choferes import asignaciones_de_chofer

logger = logging.getLogger(__name__)

RUTA_ASIGNACIONES = "/api/motor/asignaciones/vehiculos"
_ERRORES_CATALOGO = (
    CatalogoVehiculosAusenteError, CatalogoVehiculosCorruptoError, VersionCatalogoVehiculosDesconocidaError,
    VehiculoDuplicadoError, OSError, ValueError,
)


def asignaciones_publicables(raiz: str | Path) -> list[dict[str, str]]:
    """Tractos: `[{chofer_id, patente}]` ordenado. `chofer_id` es la clave del
    catálogo de choferes, la misma que lleva el token Mobile. Lanza si un
    catálogo no se puede leer."""
    return asignaciones_publicables_por_rol(raiz)["tracto"]


def asignaciones_publicables_por_rol(raiz: str | Path) -> dict[str, list[dict[str, str]]]:
    """`{"tracto": [...], "rampla": [...]}`, cada lista `[{chofer_id, patente}]`
    ordenada, sólo con asignaciones CONFIRMADAS. Lanza si un catálogo no se
    puede leer."""
    carpeta = Path(raiz) / "catalogos_privados"
    # Lectura estricta: `cargar_catalogo_json` devuelve {} ante un archivo
    # ilegible, lo que aquí revocaría todas las asignaciones en Cloud.
    choferes = json.loads((carpeta / "choferes.json").read_text(encoding="utf-8-sig"))
    if not isinstance(choferes, dict) or not choferes:
        raise ValueError("catálogo de choferes vacío o inválido")
    vehiculos = cargar_catalogo_vehiculos(carpeta / "vehiculos.json").homologables()
    publicables: dict[str, list[dict[str, str]]] = {"tracto": [], "rampla": []}
    for chofer_id, registro in sorted(choferes.items()):
        if not isinstance(registro, dict) or not registro.get("activo", True):
            continue
        rut = rut_canonico_de_registro_chofer(str(chofer_id), registro)
        if not rut:
            continue
        asignacion = asignaciones_de_chofer(rut, vehiculos)
        for rol, lista in publicables.items():
            if asignacion[rol]["estado"] == "CONFIRMADO":
                lista.append({"chofer_id": str(chofer_id), "patente": asignacion[rol]["patente"]})
    return publicables


def publicar_asignaciones_cloud(
    *, base_url: str, token_motor: str, raiz: str | Path, timeout: float, puede_continuar: Callable[[], bool],
) -> dict:
    try:
        por_rol = asignaciones_publicables_por_rol(raiz)
    except _ERRORES_CATALOGO as error:
        logger.warning("Asignaciones de vehículo no publicadas: %s", error)
        return {"publicadas": None, "error": f"catálogo no disponible: {error}"}
    if not puede_continuar():
        return {"publicadas": None, "detenido_por_escritor": True}
    respuesta = _json(base_url, RUTA_ASIGNACIONES, token_motor, method="POST",
                      body={"asignaciones": por_rol["tracto"], "ramplas": por_rol["rampla"]}, timeout=timeout)
    # Un Cloud anterior no informa `ramplas`: las ignora (None = no publicadas).
    return {"publicadas": respuesta.get("asignaciones"), "ramplas_publicadas": respuesta.get("ramplas"),
            "cambios": respuesta.get("cambios")}
