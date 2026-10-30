"""Publicación Motor -> Cloud de la asignación vigente confirmada de vehículo.

Sincronización interna: Cloud la usa sólo para vincular a la patente correcta
los documentos de vehículo que envía un chofer desde Mobile, sin mostrársela.
Motor es la única autoridad y usa la misma regla que la ficha Desktop
(`fichas_choferes.asignaciones_de_chofer`): confirmaciones humanas del
catálogo de vehículos, nunca OCR ni viajes históricos. Se publica sólo el
tracto CONFIRMADO (un conflicto no se publica) de choferes activos del
catálogo; lo que no se publica, Cloud lo revoca.

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
    """`[{chofer_id, patente}]` ordenado. `chofer_id` es la clave del catálogo
    de choferes, la misma que lleva el token Mobile. Lanza si un catálogo no
    se puede leer."""
    carpeta = Path(raiz) / "catalogos_privados"
    # Lectura estricta: `cargar_catalogo_json` devuelve {} ante un archivo
    # ilegible, lo que aquí revocaría todas las asignaciones en Cloud.
    choferes = json.loads((carpeta / "choferes.json").read_text(encoding="utf-8-sig"))
    if not isinstance(choferes, dict) or not choferes:
        raise ValueError("catálogo de choferes vacío o inválido")
    vehiculos = cargar_catalogo_vehiculos(carpeta / "vehiculos.json").homologables()
    publicables = []
    for chofer_id, registro in sorted(choferes.items()):
        if not isinstance(registro, dict) or not registro.get("activo", True):
            continue
        rut = rut_canonico_de_registro_chofer(str(chofer_id), registro)
        if not rut:
            continue
        tracto = asignaciones_de_chofer(rut, vehiculos)["tracto"]
        if tracto["estado"] == "CONFIRMADO":
            publicables.append({"chofer_id": str(chofer_id), "patente": tracto["patente"]})
    return publicables


def publicar_asignaciones_cloud(
    *, base_url: str, token_motor: str, raiz: str | Path, timeout: float, puede_continuar: Callable[[], bool],
) -> dict:
    try:
        asignaciones = asignaciones_publicables(raiz)
    except _ERRORES_CATALOGO as error:
        logger.warning("Asignaciones de vehículo no publicadas: %s", error)
        return {"publicadas": None, "error": f"catálogo no disponible: {error}"}
    if not puede_continuar():
        return {"publicadas": None, "detenido_por_escritor": True}
    respuesta = _json(base_url, RUTA_ASIGNACIONES, token_motor, method="POST",
                      body={"asignaciones": asignaciones}, timeout=timeout)
    return {"publicadas": respuesta.get("asignaciones"), "cambios": respuesta.get("cambios")}
