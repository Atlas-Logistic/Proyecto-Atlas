"""Pull Cloud->Motor de la licencia de conducir enviada desde Mobile.

Mismo patrón que los envíos de guías: pendientes -> lease -> descarga
firmada verificada por tamaño y SHA-256 -> escritura en la ficha -> sólo
entonces confirmar a Cloud. Corre dentro del ciclo PULL, bajo su lease de
escritor (`puede_continuar`), y nunca hace OCR ni completa clase o
vencimiento: la licencia queda PENDIENTE_EXTRACCION en la ficha.

Si el chofer no tiene ficha (o falta la base de fichas) no se confirma: el
lease vence y el documento se reintenta en el próximo ciclo.
"""
from __future__ import annotations

import hashlib
import logging
import urllib.parse
from pathlib import Path
from typing import Callable

from atlas_core.cloud_mobile_sync_cliente import ErrorSincronizacionCloudMobile, _descargar, _json
from atlas_core.fichas_choferes import (
    EMPRESA_ACTUAL, ESTADO_PENDIENTE_EXTRACCION, FORMATO_FRENTE_REVERSO, registrar_licencia_mobile_pendiente,
)

logger = logging.getLogger(__name__)

RUTA_FICHAS = "/api/motor/fichas/documentos"


def sincronizar_licencias_cloud(
    *, base_url: str, token_motor: str, consumidor: str, raiz: str | Path, timeout: float,
    puede_continuar: Callable[[], bool], empresa: str = EMPRESA_ACTUAL,
) -> dict:
    resumen: dict = {"encontrados": 0, "incorporados": [], "sin_vincular": [], "errores": []}

    def comprobar() -> None:
        if not puede_continuar():
            raise PermissionError("Lease PULL perdido: recepción de licencias detenida.")

    # Este Motor incorpora la licencia de frente y reverso: lo declara para que
    # Cloud se la entregue (a un Motor anterior nunca se la entrega).
    pendientes = _json(base_url, f"{RUTA_FICHAS}/pendientes?formatos={FORMATO_FRENTE_REVERSO}", token_motor,
                       timeout=timeout).get("documentos", [])
    resumen["encontrados"] = len(pendientes)
    for pendiente in pendientes:
        if not puede_continuar():
            resumen["detenido_por_escritor"] = True
            break
        documento_id = str(pendiente.get("documento_id", ""))
        if pendiente.get("titular") != "CHOFER" or pendiente.get("tipo") != "LICENCIA_CONDUCIR":
            continue
        ruta = f"{RUTA_FICHAS}/{urllib.parse.quote(documento_id, safe='')}"
        try:
            lease = _json(base_url, f"{ruta}/lease", token_motor, method="POST",
                          body={"consumidor": consumidor, "formatos": [FORMATO_FRENTE_REVERSO]}, timeout=timeout)
            if lease.get("formato") == FORMATO_FRENTE_REVERSO:
                # Ambas caras completas y verificadas o nada: nunca a medias.
                caras = []
                for cara in lease["caras"]:
                    contenido = _descargar(cara["descarga_url"], esperado_bytes=int(cara["bytes"]), timeout=timeout)
                    if hashlib.sha256(contenido).hexdigest() != cara["sha256"]:
                        raise ErrorSincronizacionCloudMobile(f"hash descargado de {cara['cara']} no coincide")
                    caras.append({"cara": cara["cara"], "contenido": contenido, "mime_type": cara["mime_type"],
                                  "sha256": cara["sha256"]})
                originales = {"caras": caras}
            else:
                contenido = _descargar(lease["descarga_url"], esperado_bytes=int(lease["bytes"]), timeout=timeout)
                if hashlib.sha256(contenido).hexdigest() != lease["sha256"]:
                    raise ErrorSincronizacionCloudMobile("hash descargado no coincide")
                originales = {"contenido": contenido, "mime_type": lease["mime_type"], "sha256": lease["sha256"]}
        except (ErrorSincronizacionCloudMobile, KeyError, ValueError, TypeError) as error:
            logger.warning("Licencia Mobile %s no descargada: %s", documento_id, error)
            resumen["errores"].append({"documento_id": documento_id, "error": str(error)})
            continue
        try:
            resultado = registrar_licencia_mobile_pendiente(
                raiz, empresa=empresa, referencia_catalogo=lease["chofer_id"], origen_documento_id=documento_id,
                recibido_en=lease.get("recibido_en") or lease.get("enviado_en"), comprobar=comprobar,
                actor=f"MOBILE:{lease['chofer_id']}", **originales,
            )
        except ValueError as error:
            logger.warning("Licencia Mobile %s sin vincular: %s", documento_id, error)
            resumen["sin_vincular"].append({"documento_id": documento_id, "motivo": str(error)})
            continue
        try:
            _json(base_url, f"{ruta}/confirmar", token_motor, method="POST",
                  body={"lease_token": lease["lease_token"], "resultado": ESTADO_PENDIENTE_EXTRACCION}, timeout=timeout)
        except ErrorSincronizacionCloudMobile as error:
            # Ya está en la ficha: el próximo ciclo lo reconoce por
            # origen_documento_id y sólo vuelve a confirmar.
            resumen["errores"].append({"documento_id": documento_id, "error": str(error)})
            continue
        resumen["incorporados"].append({"documento_id": documento_id, "ficha_id": resultado["ficha_id"],
                                        "documento_ficha_id": resultado["documento_id"],
                                        "idempotente": resultado["idempotente"]})
    return resumen
