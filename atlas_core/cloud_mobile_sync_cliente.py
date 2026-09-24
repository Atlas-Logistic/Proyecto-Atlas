"""Pull HTTPS Cloud->Motor, aislado del receptor LAN y sin OCR/routing.

El Motor conserva la copia local con `RepositorioEnviosMobile.recibir()` y
sólo entonces confirma Cloud. Un lease vencido deja el envío reintentable.
"""
from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from atlas_core.mobile import MAX_IMAGEN_BYTES, MIME_PERMITIDOS, ErrorEnvioMobile, RepositorioEnviosMobile


class ErrorSincronizacionCloudMobile(RuntimeError):
    pass


def _url(base_url: str, ruta: str) -> str:
    url = base_url.rstrip("/") + ruta
    if urllib.parse.urlparse(url).scheme != "https":
        raise ErrorSincronizacionCloudMobile("Cloud Motor requiere HTTPS saliente")
    return url


def _request(url: str, token: str, *, method: str = "GET", body: bytes | None = None) -> urllib.request.Request:
    return urllib.request.Request(url, method=method, data=body, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
        "User-Agent": "Atlas-Motor-Cloud/1.0",
    })


def _json(base_url: str, ruta: str, token: str, *, method: str = "GET", body: dict | None = None, timeout: float) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    try:
        with urllib.request.urlopen(_request(_url(base_url, ruta), token, method=method, body=data), timeout=timeout) as response:
            return json.loads(response.read())
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise ErrorSincronizacionCloudMobile(f"Cloud Motor {method} {ruta}: {error}") from error


def _descargar(url: str, *, esperado_bytes: int, timeout: float) -> bytes:
    if urllib.parse.urlparse(url).scheme != "https":
        raise ErrorSincronizacionCloudMobile("URL temporal de descarga no HTTPS")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="GET", headers={"User-Agent": "Atlas-Motor-Cloud/1.0"}), timeout=timeout) as response:
            declarado = response.headers.get("Content-Length")
            if declarado is not None and int(declarado) != esperado_bytes:
                raise ErrorSincronizacionCloudMobile("tamaño declarado por Cloud no coincide")
            contenido = response.read(MAX_IMAGEN_BYTES + 1)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        raise ErrorSincronizacionCloudMobile(f"no se pudo descargar documento Cloud: {error}") from error
    if len(contenido) != esperado_bytes or len(contenido) > MAX_IMAGEN_BYTES:
        raise ErrorSincronizacionCloudMobile("tamaño descargado no coincide")
    return contenido


def sincronizar_envios_cloud(
    *, base_url: str, token_motor: str, consumidor: str, repositorio: RepositorioEnviosMobile,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Ejecuta listado, lease, descarga, verificación, persistencia y confirmación.

    Nunca confirma Cloud cuando la descarga, hash/tamaño o persistencia local
    falla. No procesa OCR ni toca el receptor/PWA LAN.
    """
    resumen: dict[str, Any] = {"encontrados": 0, "leaseados": [], "persistidos": [], "confirmados": [], "fallidos": {}}
    pendientes = _json(base_url, "/api/motor/envios/pendientes", token_motor, timeout=timeout).get("envios", [])
    resumen["encontrados"] = len(pendientes)
    for pendiente in pendientes:
        envio_id = str(pendiente.get("envio_id", ""))
        if not envio_id:
            continue
        try:
            lease = _json(base_url, f"/api/motor/envios/{urllib.parse.quote(envio_id, safe='')}/lease", token_motor, method="POST", body={"consumidor": consumidor}, timeout=timeout)
            resumen["leaseados"].append(envio_id)
            mime = str(lease.get("imagen_mime", ""))
            esperado = int(lease.get("imagen_bytes", -1))
            sha = str(lease.get("imagen_sha256", ""))
            if mime not in MIME_PERMITIDOS or esperado <= 0 or esperado > MAX_IMAGEN_BYTES or len(sha) != 64:
                raise ErrorSincronizacionCloudMobile("metadata Cloud inválida")
            imagen = _descargar(str(lease.get("descarga_url", "")), esperado_bytes=esperado, timeout=timeout)
            if len(imagen) != esperado:
                raise ErrorSincronizacionCloudMobile("tamaño descargado no coincide")
            if hashlib.sha256(imagen).hexdigest() != sha:
                raise ErrorSincronizacionCloudMobile("SHA-256 descargado no coincide")
            metadata = {
                "empresa_id": lease["empresa_id"], "documento_id": lease["documento_id"], "chofer_id": lease["chofer_id"],
                "observacion": lease.get("observacion", ""), "capturado_en": lease.get("capturado_en", ""),
                "tipo_novedad": lease.get("tipo_novedad", ""), "guia_firmada_correo": bool(lease.get("guia_firmada_correo")),
                "planta_origen_informada": lease.get("planta_origen_informada", ""), "lote_id": lease.get("lote_id", ""),
                # Bloque MOBILE CONTRATO V2 -- un Worker v1 no los envía:
                # `recibir` los completa compatibles (GUIA, [tipo_novedad]).
                "tipos_novedad": lease.get("tipos_novedad"), "rol_documento": lease.get("rol_documento"),
                "evidencia_de_envio_id": lease.get("evidencia_de_envio_id"),
            }
            repositorio.recibir(envio_id=envio_id, imagen=imagen, mime=mime, metadata=metadata)
            resumen["persistidos"].append(envio_id)
            _json(base_url, f"/api/motor/envios/{urllib.parse.quote(envio_id, safe='')}/confirmar", token_motor, method="POST", body={"lease_token": lease["lease_token"]}, timeout=timeout)
            resumen["confirmados"].append(envio_id)
        except (ErrorSincronizacionCloudMobile, ErrorEnvioMobile, KeyError, TypeError, ValueError) as error:
            resumen["fallidos"][envio_id] = str(error)
    return resumen
