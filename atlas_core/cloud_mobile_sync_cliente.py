"""Pull HTTPS Cloud->Motor, aislado del receptor LAN y sin OCR/routing.

El Motor conserva la copia local con `RepositorioEnviosMobile.recibir()` y
sólo entonces confirma Cloud. Un lease vencido deja el envío reintentable.

Mobile 24/7 -- con `procesar=True`, tras el PULL procesa (OCR/B1/reporte)
todo envío local todavía `RECIBIDO` con el MISMO punto de entrada que el
flujo LAN (`procesar_y_revalidar_envio_mobile`), bajo el mismo lock por
envío: idempotente aunque el PC se apague a mitad o corran dos PCs.

Recepción intercalada -- la recepción (lease, descarga, `recibir()`) no
espera al OCR: los envíos aterrizados esperan en cola con su lease vivo
(máx. `MAX_LEASES_EN_COLA`) y antes de cada OCR se recibe lo nuevo. La
confirmación sigue ocurriendo sólo tras RECONCILIADO.
"""
from __future__ import annotations

import hashlib
import json
import time
import logging
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from atlas_core.mobile import (
    MAX_IMAGEN_BYTES, MIME_PERMITIDOS, ErrorEnvioMobile, RepositorioEnviosMobile,
    procesar_y_revalidar_envio_mobile, reconciliar_bandeja_diferida_mobile,
)
from atlas_core.almacenamiento_portable import SesionOcupadaError

logger = logging.getLogger(__name__)

# Tope de envíos con lease Cloud vivo esperando OCR en una corrida: acota
# latidos y llamadas al Worker; el resto sigue PENDIENTE en Cloud.
MAX_LEASES_EN_COLA = 20


def crear_proveedor_ocr(preferido: str = "paddleocr"):
    """Import diferido, coherente con el punto de extensión Mobile testeable."""
    from atlas_core.mobile import crear_proveedor_ocr as crear
    return crear(preferido)


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
    proveedor_ocr_preferido: str = "paddleocr", max_leases_en_cola: int = MAX_LEASES_EN_COLA,
) -> dict[str, Any]:
    """Sincroniza una corrida Cloud y garantiza el cierre de su OCR aislado."""
    compartido: dict[str, object | None] = {"proveedor": None}
    try:
        return _sincronizar_envios_cloud_impl(
            base_url=base_url, token_motor=token_motor, consumidor=consumidor, repositorio=repositorio,
            timeout=timeout, procesar=procesar, dataset=dataset, carpeta_catalogos=carpeta_catalogos,
            lease_heartbeat_segundos=lease_heartbeat_segundos, puede_continuar=puede_continuar,
            proveedor_compartido=compartido, proveedor_ocr_preferido=proveedor_ocr_preferido,
            max_leases_en_cola=max_leases_en_cola,
        )
    finally:
        cerrar = getattr(compartido["proveedor"], "cerrar", None)
        if callable(cerrar):
            cerrar()


@dataclass
class _ColaRecepcion:
    """Estado de recepción de UNA corrida: envíos aterrizados que esperan
    OCR con su lease Cloud vivo (orden FIFO de Cloud) y los ya vistos o
    intentados, para no pedir dos leases del mismo envío en la corrida."""
    leases: dict[str, tuple[str, LeaseMotor]] = field(default_factory=dict)
    vistos: set[str] = field(default_factory=set)
    intentados: set[str] = field(default_factory=set)


def _sincronizar_envios_cloud_impl(
    *, base_url: str, token_motor: str, consumidor: str, repositorio: RepositorioEnviosMobile,
    timeout: float, procesar: bool, dataset: Path | None, carpeta_catalogos: str | Path | None,
    lease_heartbeat_segundos: float, puede_continuar: Callable[[], bool] | None,
    proveedor_compartido: dict[str, object | None], proveedor_ocr_preferido: str,
    max_leases_en_cola: int,
) -> dict[str, Any]:
    """Ejecuta listado, lease, descarga, verificación, persistencia y confirmación.

    Nunca confirma Cloud hasta que el documento y la reconciliación requerida
    terminaron. RECEPCIÓN INTERCALADA: cada envío aterriza y espera en una
    cola local con su lease renovado; ANTES de cada OCR se vuelve a recibir
    lo nuevo de Cloud. Un OCR lento retiene a lo sumo un documento, no la
    recepción del resto. No toca el receptor/PWA LAN fuera de la
    orquestación Mobile ya existente.
    """
    resumen: dict[str, Any] = {
        "encontrados": 0, "leaseados": [], "persistidos": [], "confirmados": [],
        "fallidos": {}, "procesados": [], "omitidos_por_bloqueo": [],
        "errores_procesamiento": {},
        "detenido_por_escritor": False,
        "reconciliacion_bandeja": None,
        "errores_recepcion": [],
        "omitidos_error_persistido": [],
        "ocr_documentos": [],
    }
    proveedor_ocr = proveedor_compartido["proveedor"]

    def obtener_proveedor_ocr():
        nonlocal proveedor_ocr
        if proveedor_ocr is None:
            proveedor_ocr = crear_proveedor_ocr(proveedor_ocr_preferido)
            proveedor_compartido["proveedor"] = proveedor_ocr
            logger.info(
                "PULL Cloud: proveedor OCR efectivo=%s preferencia=%s",
                type(proveedor_ocr).__name__, proveedor_ocr_preferido,
            )
        return proveedor_ocr
    if not _puede_continuar(puede_continuar):
        resumen["detenido_por_escritor"] = True
        return resumen
    cola = _ColaRecepcion()

    def recibir(*, intercalada: bool) -> None:
        try:
            _recibir_pendientes_cloud(
                base_url=base_url, token_motor=token_motor, consumidor=consumidor, repositorio=repositorio,
                timeout=timeout, procesar=procesar, lease_heartbeat_segundos=lease_heartbeat_segundos,
                puede_continuar=puede_continuar, cola=cola, resumen=resumen,
                max_leases_en_cola=max_leases_en_cola,
            )
        except ErrorSincronizacionCloudMobile as error:
            # La primera ronda conserva el contrato previo (Cloud caído o
            # no HTTPS corta la corrida). Una ronda intercalada que falla
            # sólo se salta: la cola local sigue procesándose.
            if not intercalada:
                raise
            resumen["errores_recepcion"].append(str(error))

    try:
        recibir(intercalada=False)
        if not procesar:
            return resumen
        atendidos: set[str] = set()
        locales: list[str] | None = None
        primera_ronda = True
        while True:
            if not _puede_continuar(puede_continuar):
                resumen["detenido_por_escritor"] = True
                break
            if not primera_ronda:
                recibir(intercalada=True)
            primera_ronda = False
            if cola.leases:
                envio_id = next(iter(cola.leases))
                lease_token, lease_activo = cola.leases.pop(envio_id)
                atendidos.add(envio_id)
                try:
                    _procesar_y_confirmar_cloud(
                        repositorio, envio_id, lease_token=lease_token, lease_activo=lease_activo,
                        base_url=base_url, token_motor=token_motor, timeout=timeout, dataset=dataset,
                        carpeta_catalogos=carpeta_catalogos, puede_continuar=puede_continuar,
                        obtener_proveedor_ocr=obtener_proveedor_ocr, resumen=resumen,
                    )
                finally:
                    lease_activo.cerrar()
                continue
            # Cola Cloud vacía: recuperación local de RECIBIDO/PROCESANDO
            # (corridas interrumpidas, `--sin-procesar` previos, LAN), un
            # envío por vuelta para seguir recibiendo entre OCR. La foto del
            # historial se toma una vez: recorrer G: entre OCR es caro.
            if locales is None:
                locales = [
                    str(registro.get("envio_id", "")) for registro in repositorio.historial()
                    if registro.get("estado") in ("RECIBIDO", "PROCESANDO")
                ]
            locales = [envio_id for envio_id in locales if envio_id not in atendidos]
            if not locales:
                break
            envio_id = locales.pop(0)
            atendidos.add(envio_id)
            local = _procesar_recibido_local(
                repositorio, envio_id, dataset=dataset, carpeta_catalogos=carpeta_catalogos,
                obtener_proveedor_ocr=obtener_proveedor_ocr,
            )
            _sumar_recuperacion_local(resumen, local)
    finally:
        # Lo que quede en cola (escritor perdido, excepción) nunca se
        # confirma: el lease vence y Cloud lo vuelve a ofrecer.
        for _token, lease_activo in cola.leases.values():
            lease_activo.cerrar()
        cola.leases.clear()
    # P0 BLOQUEO MOBILE -- la reconciliación global de la bandeja corre UNA
    # vez, DESPUÉS de cerrar y confirmar cada envío de esta pasada; lo que
    # quede PENDIENTE (fallo, escritor perdido, interrupción) lo retoma la
    # pasada siguiente.
    if dataset and _puede_continuar(puede_continuar):
        resumen["reconciliacion_bandeja"] = reconciliar_bandeja_diferida_mobile(
            repositorio, raiz_atlas=Path(dataset).parent.parent.parent,
        )
    return resumen


def _recibir_pendientes_cloud(
    *, base_url: str, token_motor: str, consumidor: str, repositorio: RepositorioEnviosMobile,
    timeout: float, procesar: bool, lease_heartbeat_segundos: float,
    puede_continuar: Callable[[], bool] | None, cola: _ColaRecepcion, resumen: dict[str, Any],
    max_leases_en_cola: int,
) -> None:
    """Una ronda de recepción, sin OCR: lease, descarga verificada,
    `recibir()` y checkpoint ATERRIZADO. Con `procesar` el envío queda en
    cola con su lease vivo; sin `procesar` el lease se suelta sin confirmar
    (comportamiento previo de `--sin-procesar`)."""
    if procesar and len(cola.leases) >= max_leases_en_cola:
        return
    pendientes = _json(base_url, "/api/motor/envios/pendientes", token_motor, timeout=timeout).get("envios", [])
    for pendiente in pendientes:
        envio_id = str(pendiente.get("envio_id", ""))
        if not envio_id or envio_id in cola.vistos:
            continue
        if procesar and len(cola.leases) >= max_leases_en_cola:
            break  # el resto sigue PENDIENTE en Cloud para la próxima ronda
        if not _puede_continuar(puede_continuar):
            resumen["detenido_por_escritor"] = True
            break
        cola.vistos.add(envio_id)
        resumen["encontrados"] += 1
        if _error_persistido_local(repositorio, envio_id, pendiente):
            # ERROR funcional ya persistido con este MISMO documento: nunca
            # se confirma ni se reprocesa solo. Sin lease, descarga ni
            # escritura en G:; sigue PENDIENTE en Cloud y vuelve al flujo
            # normal en cuanto una recuperación explícita lo saque de ERROR.
            resumen["omitidos_error_persistido"].append(envio_id)
            if procesar:
                resumen["errores_procesamiento"][envio_id] = "ERROR funcional persistido"
            continue
        lease_activo: LeaseMotor | None = None
        en_cola = False
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
            checkpoint = (repositorio.cargar(envio_id).get("cloud_procesamiento") or {}).get("estado")
            if checkpoint == "RECONCILIADO":
                # Ya procesado en una corrida cuya confirmación no llegó:
                # se confirma aquí, sin OCR ni esperar turno en la cola.
                if not _puede_continuar(puede_continuar):
                    resumen["detenido_por_escritor"] = True
                    continue
                _confirmar_cloud(
                    base_url=base_url, token_motor=token_motor, envio_id=envio_id,
                    lease_token=lease_token, lease_activo=lease_activo, timeout=timeout, resumen=resumen,
                )
                continue
            cola.leases[envio_id] = (lease_token, lease_activo)
            en_cola = True
        except (ErrorSincronizacionCloudMobile, ErrorEnvioMobile, KeyError, TypeError, ValueError) as error:
            resumen["fallidos"][envio_id] = str(error)
        finally:
            if lease_activo is not None and not en_cola:
                lease_activo.cerrar()


def _procesar_y_confirmar_cloud(
    repositorio: RepositorioEnviosMobile, envio_id: str, *, lease_token: str, lease_activo: LeaseMotor,
    base_url: str, token_motor: str, timeout: float, dataset: Path | None,
    carpeta_catalogos: str | Path | None, puede_continuar: Callable[[], bool] | None,
    obtener_proveedor_ocr: Callable[[], object], resumen: dict[str, Any],
) -> None:
    try:
        resultado = _procesar_envio_cloud(
            repositorio, envio_id, dataset=dataset, carpeta_catalogos=carpeta_catalogos,
            obtener_proveedor_ocr=obtener_proveedor_ocr,
        )
        _sumar_resultado_procesamiento(resumen, envio_id, resultado)
        if not resultado.get("completado"):
            return
        if not _puede_continuar(puede_continuar):
            resumen["detenido_por_escritor"] = True
            return
        _marcar_reconciliado_cloud(repositorio, envio_id)
        _confirmar_cloud(
            base_url=base_url, token_motor=token_motor, envio_id=envio_id,
            lease_token=lease_token, lease_activo=lease_activo, timeout=timeout, resumen=resumen,
        )
    except (ErrorSincronizacionCloudMobile, ErrorEnvioMobile, KeyError, TypeError, ValueError) as error:
        resumen["fallidos"][envio_id] = str(error)


def _confirmar_cloud(
    *, base_url: str, token_motor: str, envio_id: str, lease_token: str, lease_activo: LeaseMotor,
    timeout: float, resumen: dict[str, Any],
) -> None:
    """Confirma sólo con el token del propio lease y sólo si Cloud acaba de
    aceptar su renovación; un lease perdido nunca se da por bueno."""
    if not lease_activo.vigente or not lease_activo.renovar():
        resumen["fallidos"][envio_id] = "lease Cloud perdido antes de confirmar"
        return
    _json(base_url, f"/api/motor/envios/{urllib.parse.quote(envio_id, safe='')}/confirmar", token_motor, method="POST", body={"lease_token": lease_token}, timeout=timeout)
    resumen["confirmados"].append(envio_id)


def _puede_continuar(guardia: Callable[[], bool] | None) -> bool:
    return guardia is None or bool(guardia())


def procesar_envios_recibidos(
    repositorio: RepositorioEnviosMobile, *, dataset: Path | None, carpeta_catalogos: str | Path | None,
    proveedor_ocr: object | None = None,
    obtener_proveedor_ocr: Callable[[], object] | None = None,
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
        local = _procesar_recibido_local(
            repositorio, str(registro.get("envio_id", "")), dataset=dataset, carpeta_catalogos=carpeta_catalogos,
            proveedor_ocr=proveedor_ocr, obtener_proveedor_ocr=obtener_proveedor_ocr,
        )
        for clave in ("procesados", "omitidos_por_bloqueo"):
            resultado[clave].extend(local[clave])
        resultado["errores_procesamiento"].update(local["errores_procesamiento"])
    return resultado


def _procesar_recibido_local(
    repositorio: RepositorioEnviosMobile, envio_id: str, *, dataset: Path | None,
    carpeta_catalogos: str | Path | None,
    proveedor_ocr: object | None = None,
    obtener_proveedor_ocr: Callable[[], object] | None = None,
) -> dict[str, Any]:
    """Recuperación local de UN envío, sin confirmación Cloud. Un fallo
    aislado nunca corta la corrida."""
    resultado: dict[str, Any] = {"procesados": [], "omitidos_por_bloqueo": [], "errores_procesamiento": {}}
    try:
        salida = _procesar_envio_cloud(
            repositorio, envio_id, dataset=dataset, carpeta_catalogos=carpeta_catalogos,
            proveedor_ocr=proveedor_ocr, obtener_proveedor_ocr=obtener_proveedor_ocr,
        )
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


def _error_persistido_local(repositorio: RepositorioEnviosMobile, envio_id: str, pendiente: dict) -> bool:
    """Envío ya aterrizado en ERROR con el mismo SHA-256 que anuncia Cloud.

    Sin SHA en el listado, sin registro local legible o con otro documento,
    no se omite: sigue el camino normal (conservador)."""
    sha_cloud = str(pendiente.get("imagen_sha256") or "")
    if len(sha_cloud) != 64:
        return False
    try:
        registro = repositorio.cargar(envio_id)
    except (OSError, ValueError, KeyError):
        return False
    return registro.get("estado") == "ERROR" and registro.get("imagen_sha256") == sha_cloud


def _marcar_aterrizado_cloud(repositorio: RepositorioEnviosMobile, envio_id: str, lease: dict) -> None:
    registro = repositorio.cargar(envio_id)
    previo = dict(registro.get("cloud_procesamiento") or {})
    checkpoint = dict(previo)
    checkpoint.update({
        "estado": checkpoint.get("estado") or "ATERRIZADO",
        "documento_id": lease.get("documento_id", ""),
        "imagen_sha256": lease.get("imagen_sha256", ""),
    })
    if checkpoint == previo:
        return  # reentrega del mismo envío: no reescribir envio.json en G:
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
    proveedor_ocr: object | None = None,
    obtener_proveedor_ocr: Callable[[], object] | None = None,
) -> dict[str, object]:
    registro = repositorio.cargar(envio_id)
    if registro.get("estado") == "ERROR":
        return {"completado": False, "error": "ERROR funcional persistido"}
    proveedor_documento = None
    inicio_documento = None
    try:
        argumentos_procesamiento: dict[str, object] = {
            "dataset": dataset,
            "carpeta_catalogos": carpeta_catalogos,
            # P0 BLOQUEO MOBILE: el consumidor PULL siempre difiere la
            # reconciliación global de la bandeja al final de su pasada.
            "diferir_reconciliacion_bandeja": True,
        }
        # Sólo RECIBIDO/PROCESANDO repite OCR. Un envío ya asociado sólo
        # revalida/reconcilia y no debe cargar PaddleOCR.
        if registro.get("estado") in ("RECIBIDO", "PROCESANDO"):
            if proveedor_ocr is None and obtener_proveedor_ocr is not None:
                proveedor_ocr = obtener_proveedor_ocr()
            if proveedor_ocr is not None:
                proveedor_documento = proveedor_ocr
                inicio_documento = time.monotonic()
                argumentos_procesamiento["proveedor_ocr"] = proveedor_ocr
        salida = procesar_y_revalidar_envio_mobile(repositorio, envio_id, **argumentos_procesamiento)
    except SesionOcupadaError:
        resultado: dict[str, object] = {"completado": False, "bloqueado": True}
    except Exception as error:
        resultado = {"completado": False, "error": f"{type(error).__name__}: {error}"}
    else:
        if not salida.get("procesamiento_ok"):
            resultado = {"completado": False, "error": "procesamiento operacional no terminado"}
        elif not salida.get("reconciliacion_ok"):
            resultado = {"completado": False, "error": "reconciliación operacional no terminada"}
        else:
            resultado = {"completado": True}
    if proveedor_documento is not None and inicio_documento is not None:
        efectivo = getattr(proveedor_documento, "proveedor_efectivo_documento", None)
        proveedor_efectivo = efectivo() if callable(efectivo) else type(proveedor_documento).__name__
        segundos = round(time.monotonic() - inicio_documento, 3)
        resultado.update(proveedor_ocr_efectivo=proveedor_efectivo, tiempo_documento_segundos=segundos)
        logger.info("PULL Cloud OCR documento=%s proveedor_efectivo=%s tiempo_segundos=%.3f",
                    envio_id, proveedor_efectivo, segundos)
    return resultado


def _sumar_resultado_procesamiento(resumen: dict[str, Any], envio_id: str, resultado: dict[str, object]) -> None:
    if "proveedor_ocr_efectivo" in resultado:
        resumen["ocr_documentos"].append({
            "envio_id": envio_id,
            "proveedor_efectivo": resultado["proveedor_ocr_efectivo"],
            "tiempo_documento_segundos": resultado.get("tiempo_documento_segundos"),
        })
    if resultado.get("completado") and not resultado.get("ya_reconciliado"):
        resumen["procesados"].append(envio_id)
    elif resultado.get("bloqueado"):
        resumen["omitidos_por_bloqueo"].append(envio_id)
    elif resultado.get("error"):
        resumen["errores_procesamiento"][envio_id] = str(resultado["error"])


def _sumar_recuperacion_local(resumen: dict[str, Any], recuperacion: dict[str, Any]) -> None:
    for clave in ("procesados", "omitidos_por_bloqueo"):
        for envio_id in recuperacion[clave]:
            if envio_id not in resumen[clave]:
                resumen[clave].append(envio_id)
    resumen["errores_procesamiento"].update(recuperacion["errores_procesamiento"])
