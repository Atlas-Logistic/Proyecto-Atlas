"""Publicación Motor -> Cloud de las plantas de origen de la empresa.

Mobile ofrece al chofer las plantas que Cloud recibe aquí (GET
/api/mobile/plantas) y envía el ``planta_id`` elegido; Motor lo valida
contra el mismo catálogo (`atlas_core.mobile.validar_planta_origen_mobile`).
La empresa la fija el token de Motor, nunca el cuerpo.

Se publica la lista COMPLETA de plantas CONFIRMADAS y ACTIVAS; lo que no se
publica, Cloud lo desactiva (nunca lo borra: una guía capturada antes de la
desactivación se sigue aceptando).

MBT no publica: conserva los códigos AZA_COLINA / AZA_RENCA que Cloud le
ofrece y acepta como siempre. Un catálogo ausente o ilegible no publica
nada, porque una lista vacía desactivaría todas las plantas en Cloud.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Callable

from atlas_core.aislamiento_empresas import EMPRESA_MBT, empresa_de_raiz
from atlas_core.catalogo_plantas import CatalogoPlantas, ErrorCatalogoPlantas, EstadoCalidad, EstadoVigencia
from atlas_core.cloud_mobile_sync_cliente import ErrorSincronizacionCloudMobile, _json

logger = logging.getLogger(__name__)

RUTA_PLANTAS = "/api/motor/plantas"
# Mismo patrón que el Worker (ID_SEGURO) y mismos límites.
_ID_CLOUD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
MAX_NOMBRE = 80
MAX_PLANTAS = 50


class CatalogoPlantasNoPublicable(ValueError):
    pass


def plantas_publicables(raiz: str | Path) -> list[dict[str, str]]:
    """`[{planta_id, nombre}]` de plantas confirmadas y activas, por nombre.

    Lanza `CatalogoPlantasNoPublicable` si el catálogo no existe, no se puede
    leer o no cabe en el contrato de Cloud: nunca se publica algo parcial."""
    ruta = Path(raiz) / "catalogos_privados" / "plantas.json"
    if not ruta.is_file():
        raise CatalogoPlantasNoPublicable("catálogo de plantas ausente")
    try:
        plantas = CatalogoPlantas(ruta).listar()
    except (ErrorCatalogoPlantas, OSError, ValueError) as error:
        raise CatalogoPlantasNoPublicable(f"catálogo de plantas ilegible: {error}") from error
    publicables = []
    for planta in plantas:
        if planta.estado_calidad != EstadoCalidad.CONFIRMADA.value or planta.estado_vigencia != EstadoVigencia.ACTIVA.value:
            continue
        nombre = " ".join(str(planta.nombre).split())
        if not _ID_CLOUD.match(planta.planta_id) or not nombre or len(nombre) > MAX_NOMBRE or _CONTROL.search(nombre):
            raise CatalogoPlantasNoPublicable(f"planta {planta.planta_id!r} fuera del contrato Cloud")
        publicables.append({"planta_id": planta.planta_id, "nombre": nombre})
    if len(publicables) > MAX_PLANTAS:
        raise CatalogoPlantasNoPublicable(f"más de {MAX_PLANTAS} plantas activas")
    return sorted(publicables, key=lambda p: (p["nombre"].casefold(), p["planta_id"]))


def publicar_plantas_cloud(
    *, base_url: str, token_motor: str, raiz: str | Path, timeout: float, puede_continuar: Callable[[], bool],
) -> dict:
    if empresa_de_raiz(raiz) == EMPRESA_MBT:
        return {"publicadas": None, "omitido": "MBT usa los códigos AZA_COLINA/AZA_RENCA"}
    try:
        plantas = plantas_publicables(raiz)
    except CatalogoPlantasNoPublicable as error:
        logger.warning("Plantas no publicadas: %s", error)
        return {"publicadas": None, "error": str(error)}
    if not puede_continuar():
        return {"publicadas": None, "detenido_por_escritor": True}
    try:
        respuesta = _json(base_url, RUTA_PLANTAS, token_motor, method="POST", body={"plantas": plantas}, timeout=timeout)
    except ErrorSincronizacionCloudMobile as error:
        # Cloud anterior (404) o fallo de red: se reintenta en el próximo ciclo.
        logger.warning("Plantas no publicadas: %s", error)
        return {"publicadas": None, "error": str(error)}
    return {"publicadas": respuesta.get("plantas"), "cambios": respuesta.get("cambios")}
