"""Pull Cloud->Motor de los documentos de ficha enviados desde Mobile.

Mismo patrón que los envíos de guías: pendientes -> lease -> descarga
firmada verificada por tamaño y SHA-256 -> escritura en la ficha -> sólo
entonces confirmar a Cloud. Corre dentro del ciclo PULL, bajo su lease de
escritor (`puede_continuar`), y nunca hace OCR ni completa clase o
vencimiento.

- Licencia de conducir: queda PENDIENTE_EXTRACCION en la ficha del chofer
  y se confirma como tal. Si el chofer no tiene ficha (o falta la base de
  fichas) no se confirma: el lease vence y se reintenta en el próximo ciclo.
- SOAP, revisión técnica y permiso de circulación (Cloud sólo los entrega a
  un Motor que los declara en `tipos`): van a la ficha del vehículo o quedan
  pendientes de clasificación (`fichas_vehiculos`), y se confirman como
  RECIBIDO_PENDIENTE_REVISION, nunca como licencia ni como revisados.
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
from atlas_core.fichas_vehiculos import TIPOS_VEHICULO, registrar_documento_vehiculo_mobile

logger = logging.getLogger(__name__)

RUTA_FICHAS = "/api/motor/fichas/documentos"
RESULTADO_VEHICULO = "RECIBIDO_PENDIENTE_REVISION"


def _descargar_unico(lease: dict, timeout: float) -> dict:
    contenido = _descargar(lease["descarga_url"], esperado_bytes=int(lease["bytes"]), timeout=timeout)
    if hashlib.sha256(contenido).hexdigest() != lease["sha256"]:
        raise ErrorSincronizacionCloudMobile("hash descargado no coincide")
    return {"contenido": contenido, "mime_type": lease["mime_type"], "sha256": lease["sha256"]}


def sincronizar_licencias_cloud(
    *, base_url: str, token_motor: str, consumidor: str, raiz: str | Path, timeout: float,
    puede_continuar: Callable[[], bool], empresa: str = EMPRESA_ACTUAL,
) -> dict:
    resumen: dict = {"encontrados": 0, "incorporados": [], "vehiculos": [], "sin_vincular": [], "errores": []}

    def comprobar() -> None:
        if not puede_continuar():
            raise PermissionError("Lease PULL perdido: recepción de documentos de ficha detenida.")

    # Este Motor incorpora la licencia de frente y reverso y los documentos de
    # vehículo: lo declara para que Cloud se los entregue (a un Motor anterior
    # nunca se los entrega).
    tipos = ",".join(TIPOS_VEHICULO)
    pendientes = _json(base_url, f"{RUTA_FICHAS}/pendientes?formatos={FORMATO_FRENTE_REVERSO}&tipos={tipos}",
                       token_motor, timeout=timeout).get("documentos", [])
    resumen["encontrados"] = len(pendientes)
    for pendiente in pendientes:
        if not puede_continuar():
            resumen["detenido_por_escritor"] = True
            break
        documento_id = str(pendiente.get("documento_id", ""))
        es_licencia = pendiente.get("titular") == "CHOFER" and pendiente.get("tipo") == "LICENCIA_CONDUCIR"
        es_vehiculo = pendiente.get("titular") == "VEHICULO" and pendiente.get("tipo") in TIPOS_VEHICULO
        if not (es_licencia or es_vehiculo):
            continue
        ruta = f"{RUTA_FICHAS}/{urllib.parse.quote(documento_id, safe='')}"
        try:
            lease = _json(base_url, f"{ruta}/lease", token_motor, method="POST",
                          body={"consumidor": consumidor, "formatos": [FORMATO_FRENTE_REVERSO],
                                "tipos": list(TIPOS_VEHICULO)}, timeout=timeout)
            if es_vehiculo:
                if lease.get("titular") != "VEHICULO" or lease.get("tipo") != pendiente.get("tipo") \
                        or lease.get("formato", "UNICA") != "UNICA":
                    raise ErrorSincronizacionCloudMobile("lease de vehículo inesperado")
                originales = _descargar_unico(lease, timeout)
            elif lease.get("formato") == FORMATO_FRENTE_REVERSO:
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
                originales = _descargar_unico(lease, timeout)
        except (ErrorSincronizacionCloudMobile, KeyError, ValueError, TypeError) as error:
            logger.warning("Documento de ficha Mobile %s no descargado: %s", documento_id, error)
            resumen["errores"].append({"documento_id": documento_id, "error": str(error)})
            continue
        try:
            if es_vehiculo:
                resultado = registrar_documento_vehiculo_mobile(
                    raiz, empresa=empresa, origen_documento_id=documento_id, chofer_id=lease["chofer_id"],
                    tipo=lease["tipo"], patente_cloud=lease.get("patente", ""),
                    recibido_en=lease.get("recibido_en") or lease.get("enviado_en"), comprobar=comprobar,
                    actor=f"MOBILE:{lease['chofer_id']}", **originales,
                )
            else:
                resultado = registrar_licencia_mobile_pendiente(
                    raiz, empresa=empresa, referencia_catalogo=lease["chofer_id"], origen_documento_id=documento_id,
                    recibido_en=lease.get("recibido_en") or lease.get("enviado_en"), comprobar=comprobar,
                    actor=f"MOBILE:{lease['chofer_id']}", **originales,
                )
        except (ValueError, OSError) as error:
            logger.warning("Documento de ficha Mobile %s sin incorporar: %s", documento_id, error)
            resumen["sin_vincular"].append({"documento_id": documento_id, "motivo": str(error)})
            continue
        try:
            _json(base_url, f"{ruta}/confirmar", token_motor, method="POST",
                  body={"lease_token": lease["lease_token"],
                        "resultado": RESULTADO_VEHICULO if es_vehiculo else ESTADO_PENDIENTE_EXTRACCION},
                  timeout=timeout)
        except ErrorSincronizacionCloudMobile as error:
            # Ya está en la ficha: el próximo ciclo lo reconoce por
            # origen_documento_id y sólo vuelve a confirmar.
            resumen["errores"].append({"documento_id": documento_id, "error": str(error)})
            continue
        if es_vehiculo:
            resumen["vehiculos"].append({"documento_id": documento_id, "tipo": lease["tipo"],
                                         "documento_ficha_id": resultado["documento_id"],
                                         "patente": resultado["patente"], "motivo": resultado["motivo"],
                                         "duplicado": resultado["duplicado"], "idempotente": resultado["idempotente"]})
        else:
            resumen["incorporados"].append({"documento_id": documento_id, "ficha_id": resultado["ficha_id"],
                                            "documento_ficha_id": resultado["documento_id"],
                                            "idempotente": resultado["idempotente"]})
    return resumen
