"""Pull HTTPS Cloud->Motor, aislado del receptor LAN y sin OCR/routing.

El Motor conserva la copia local con `RepositorioEnviosMobile.recibir()` y
sólo entonces confirma Cloud. Un lease vencido deja el envío reintentable.

Mobile 24/7 -- con `procesar=True`, tras el PULL procesa (OCR/B1/reporte)
todo envío local todavía `RECIBIDO` con el MISMO punto de entrada que el
flujo LAN (`procesar_y_revalidar_envio_mobile`), bajo el mismo lock por
envío: idempotente aunque el PC se apague a mitad o corran dos PCs.
"""
from __future__ import annotations

import hashlib
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from atlas_core.mobile import (
    MAX_IMAGEN_BYTES, MIME_PERMITIDOS, ErrorEnvioMobile, RepositorioEnviosMobile, procesar_y_revalidar_envio_mobile,
    reconciliar_bandeja_diferida_mobile,
)
from atlas_core.almacenamiento_portable import SesionOcupadaError


class ErrorSincronizacionCloudMobile(RuntimeError):
    pass


class LeaseMotor:
    """Renueva el lease mientras una fase local potencialmente larga corre.

    El lease sigue siendo por envío. Esta clase no coordina PCs: sólo evita
    confirmar un token que Cloud ya declaró vencido.
    """

    def __init__(self, *, base_url: str, token_motor: str, envio_id: str,
                 lease_token: str, timeout: float, intervalo_segundos: float) -> None:
        self.base_url = base_url
        self.token_motor = token_motor
        self.envio_id = envio_id
        self.lease_token = lease_token
        self.timeout = timeout
        self.intervalo_segundos = intervalo_segundos
        self._detener = threading.Event()
        self._perdido = threading.Event()
        self._hilo: threading.Thread | None = None

    @property
    def vigente(self) -> bool:
        return not self._perdido.is_set()

    def renovar(self) -> bool:
        if self._perdido.is_set():
            return False
        try:
            _json(
                self.base_url,
                f"/api/motor/envios/{urllib.parse.quote(self.envio_id, safe='')}/lease/renovar",
                self.token_motor,
                method="POST", body={"lease_token": self.lease_token}, timeout=self.timeout,
            )
            return True
        except ErrorSincronizacionCloudMobile:
            self._perdido.set()
            return False

    def iniciar(self) -> None:
        if self.intervalo_segundos <= 0:
            return

        def latir() -> None:
            while not self._detener.wait(self.intervalo_segundos):
                if not self.renovar():
                    return

        self._hilo = threading.Thread(target=latir, name=f"atlas-lease-{self.envio_id}", daemon=True)
        self._hilo.start()

    def cerrar(self) -> None:
        self._detener.set()
        if self._hilo is not None:
            self._hilo.join(timeout=self.timeout + 1)


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
    timeout: float = 30.0, procesar: bool = False, dataset: Path | None = None,
    carpeta_catalogos: str | Path | None = None, lease_heartbeat_segundos: float = 60.0,
    puede_continuar: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Ejecuta listado, lease, descarga, verificación, persistencia y confirmación.

    Nunca confirma Cloud hasta que el documento y la reconciliación requerida
    terminaron. No procesa OCR ni toca el receptor/PWA LAN fuera de la
    orquestación Mobile ya existente.
    """
    resumen: dict[str, Any] = {
        "encontrados": 0, "leaseados": [], "persistidos": [], "confirmados": [],
        "fallidos": {}, "procesados": [], "omitidos_por_bloqueo": [],
        "errores_procesamiento": {},
        "detenido_por_escritor": False,
        "reconciliacion_bandeja": None,
    }
    if not _puede_continuar(puede_continuar):
        resumen["detenido_por_escritor"] = True
        return resumen
    pendientes = _json(base_url, "/api/motor/envios/pendientes", token_motor, timeout=timeout).get("envios", [])
    resumen["encontrados"] = len(pendientes)
    for pendiente in pendientes:
        if not _puede_continuar(puede_continuar):
            resumen["detenido_por_escritor"] = True
            break
        envio_id = str(pendiente.get("envio_id", ""))
        if not envio_id:
            continue
        lease_activo: LeaseMotor | None = None
        try:
            lease = _json(base_url, f"/api/motor/envios/{urllib.parse.quote(envio_id, safe='')}/lease", token_motor, method="POST", body={"consumidor": consumidor}, timeout=timeout)
            resumen["leaseados"].append(envio_id)
            lease_token = str(lease.get("lease_token", ""))
            if not lease_token:
                raise ErrorSincronizacionCloudMobile("lease Cloud sin token")
            lease_activo = LeaseMotor(
                base_url=base_url, token_motor=token_motor, envio_id=envio_id,
                lease_token=lease_token, timeout=timeout, intervalo_segundos=lease_heartbeat_segundos,
            )
            lease_activo.iniciar()
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
            if not _puede_continuar(puede_continuar):
                resumen["detenido_por_escritor"] = True
                continue
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
            _marcar_aterrizado_cloud(repositorio, envio_id, lease)
            if not procesar:
                continue
            if not _puede_continuar(puede_continuar):
                resumen["detenido_por_escritor"] = True
                continue
            checkpoint = (repositorio.cargar(envio_id).get("cloud_procesamiento") or {}).get("estado")
            resultado = (
                {"completado": True, "ya_reconciliado": True}
                if checkpoint == "RECONCILIADO"
                else _procesar_envio_cloud(
                    repositorio, envio_id, dataset=dataset, carpeta_catalogos=carpeta_catalogos,
                )
            )
            _sumar_resultado_procesamiento(resumen, envio_id, resultado)
            if not resultado.get("completado"):
                continue
            if not _puede_continuar(puede_continuar):
                resumen["detenido_por_escritor"] = True
                continue
            _marcar_reconciliado_cloud(repositorio, envio_id)
            if not lease_activo.vigente or not lease_activo.renovar():
                resumen["fallidos"][envio_id] = "lease Cloud perdido antes de confirmar"
                continue
            _json(base_url, f"/api/motor/envios/{urllib.parse.quote(envio_id, safe='')}/confirmar", token_motor, method="POST", body={"lease_token": lease_token}, timeout=timeout)
            resumen["confirmados"].append(envio_id)
        except (ErrorSincronizacionCloudMobile, ErrorEnvioMobile, KeyError, TypeError, ValueError) as error:
            resumen["fallidos"][envio_id] = str(error)
        finally:
            if lease_activo is not None:
                lease_activo.cerrar()
    if procesar and _puede_continuar(puede_continuar):
        _sumar_recuperacion_local(resumen, repositorio, dataset=dataset, carpeta_catalogos=carpeta_catalogos)
    elif procesar:
        resumen["detenido_por_escritor"] = True
    # P0 BLOQUEO MOBILE -- la reconciliación global de la bandeja corre UNA
    # vez, DESPUÉS de cerrar y confirmar cada envío de esta pasada; lo que
    # quede PENDIENTE (fallo, escritor perdido, interrupción) lo retoma la
    # pasada siguiente.
    if procesar and dataset and _puede_continuar(puede_continuar):
        resumen["reconciliacion_bandeja"] = reconciliar_bandeja_diferida_mobile(
            repositorio, raiz_atlas=Path(dataset).parent.parent.parent,
        )
    return resumen


def _puede_continuar(guardia: Callable[[], bool] | None) -> bool:
    return guardia is None or bool(guardia())


def procesar_envios_recibidos(
    repositorio: RepositorioEnviosMobile, *, dataset: Path | None, carpeta_catalogos: str | Path | None,
) -> dict[str, Any]:
    """Misma pasada que el cliente LAN (`mobile_sync_cliente`): todo envío
    local en RECIBIDO -- de esta corrida o de una anterior interrumpida --
    pasa por `procesar_y_revalidar_envio_mobile`. Un envío ya procesado no
    está en RECIBIDO y nunca se reprocesa; uno tomado por otro consumidor
    (lock `mobile_<id>`) se omite en esta pasada. Un fallo aislado nunca
    corta el resto (la recepción ya quedó a salvo)."""
    resultado: dict[str, Any] = {"procesados": [], "omitidos_por_bloqueo": [], "errores_procesamiento": {}}
    for registro in repositorio.historial():
        if registro.get("estado") not in ("RECIBIDO", "PROCESANDO"):
            continue
        envio_id = str(registro.get("envio_id", ""))
        try:
            salida = _procesar_envio_cloud(repositorio, envio_id, dataset=dataset, carpeta_catalogos=carpeta_catalogos)
            if salida.get("completado"):
                resultado["procesados"].append(envio_id)
            elif salida.get("bloqueado"):
                resultado["omitidos_por_bloqueo"].append(envio_id)
            elif salida.get("error"):
                resultado["errores_procesamiento"][envio_id] = str(salida["error"])
        except SesionOcupadaError:
            resultado["omitidos_por_bloqueo"].append(envio_id)
        except Exception as error:  # nunca corta el resto del procesamiento
            resultado["errores_procesamiento"][envio_id] = f"{type(error).__name__}: {error}"
    return resultado


def _marcar_aterrizado_cloud(repositorio: RepositorioEnviosMobile, envio_id: str, lease: dict) -> None:
    registro = repositorio.cargar(envio_id)
    checkpoint = dict(registro.get("cloud_procesamiento") or {})
    checkpoint.update({
        "estado": checkpoint.get("estado") or "ATERRIZADO",
        "documento_id": lease.get("documento_id", ""),
        "imagen_sha256": lease.get("imagen_sha256", ""),
    })
    registro["cloud_procesamiento"] = checkpoint
    repositorio.guardar(envio_id, registro)


def _marcar_reconciliado_cloud(repositorio: RepositorioEnviosMobile, envio_id: str) -> None:
    registro = repositorio.cargar(envio_id)
    checkpoint = dict(registro.get("cloud_procesamiento") or {})
    checkpoint["estado"] = "RECONCILIADO"
    registro["cloud_procesamiento"] = checkpoint
    repositorio.guardar(envio_id, registro)


def _procesar_envio_cloud(
    repositorio: RepositorioEnviosMobile, envio_id: str, *, dataset: Path | None,
    carpeta_catalogos: str | Path | None,
) -> dict[str, object]:
    registro = repositorio.cargar(envio_id)
    if registro.get("estado") == "ERROR":
        return {"completado": False, "error": "ERROR funcional persistido"}
    try:
        salida = procesar_y_revalidar_envio_mobile(
            repositorio, envio_id, dataset=dataset, carpeta_catalogos=carpeta_catalogos,
            diferir_reconciliacion_bandeja=True,
        )
    except SesionOcupadaError:
        return {"completado": False, "bloqueado": True}
    except Exception as error:
        return {"completado": False, "error": f"{type(error).__name__}: {error}"}
    if not salida.get("procesamiento_ok"):
        return {"completado": False, "error": "procesamiento operacional no terminado"}
    if not salida.get("reconciliacion_ok"):
        return {"completado": False, "error": "reconciliación operacional no terminada"}
    return {"completado": True}


def _sumar_resultado_procesamiento(resumen: dict[str, Any], envio_id: str, resultado: dict[str, object]) -> None:
    if resultado.get("completado") and not resultado.get("ya_reconciliado"):
        resumen["procesados"].append(envio_id)
    elif resultado.get("bloqueado"):
        resumen["omitidos_por_bloqueo"].append(envio_id)
    elif resultado.get("error"):
        resumen["errores_procesamiento"][envio_id] = str(resultado["error"])


def _sumar_recuperacion_local(
    resumen: dict[str, Any], repositorio: RepositorioEnviosMobile, *, dataset: Path | None,
    carpeta_catalogos: str | Path | None,
) -> None:
    recuperacion = procesar_envios_recibidos(
        repositorio, dataset=dataset, carpeta_catalogos=carpeta_catalogos,
    )
    for clave in ("procesados", "omitidos_por_bloqueo"):
        for envio_id in recuperacion[clave]:
            if envio_id not in resumen[clave]:
                resumen[clave].append(envio_id)
    resumen["errores_procesamiento"].update(recuperacion["errores_procesamiento"])
