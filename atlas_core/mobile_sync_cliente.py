"""Bloque MOBILE SINCRONIZACIÓN PULL V1 -- consumidor local.

El PC de Atlas (Motor de Javier) INICIA la comunicación hacia el receptor
central Mobile -- nunca al revés. El receptor central nunca entra al PC de
Javier, nunca abre un puerto doméstico, y no expone ningún endpoint que
ejecute algo que el llamador mande: sólo puede (1) listar envíos que este
consumidor todavía no confirmó, (2) entregar la metadata de uno, (3)
entregar los bytes de su foto, y (4) marcar uno como sincronizado -- las
cuatro operaciones ya descritas en la Sección DISEÑO del bloque, ninguna
inventada de más.

Reutiliza el contrato Mobile existente tal cual (`RepositorioEnviosMobile`,
`envio_id`/`imagen_sha256`/`estado` de `atlas_core.mobile`) -- este módulo
nunca reimplementa idempotencia/atomicidad: aterriza cada envío llamando a
`RepositorioEnviosMobile.recibir()`, exactamente la misma función que ya
usa `servidor_mobile.py` para una subida LAN directa, así que hereda sus
mismas garantías (fast-path sin lock para un `envio_id` ya existente, lock
por envío para una creación realmente nueva, escritura temp-file + fsync +
os.replace). El procesamiento posterior (OCR/B1/reporte) reutiliza
`atlas_core.mobile.procesar_y_revalidar_envio_mobile`, el mismo punto de
entrada que ya usa el modo LAN tras `POST /api/mobile/envios`.

"Recibido por Atlas" para el chofer ya significa, desde antes de este
bloque, que el RECEPTOR (`RepositorioEnviosMobile.recibir()`) guardó
correctamente el envío -- NUNCA que el OCR tuvo éxito. Este módulo no
cambia esa semántica: sólo mueve la copia ya recibida centralmente hacia
la copia local que el Motor puede procesar, y un fallo de OCR posterior
quedó, desde siempre, en un campo aparte (`estado`/`error` del propio
envío) que nunca convierte una sincronización ya exitosa en un fallo de
recepción.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from atlas_core.almacenamiento_portable import SesionOcupadaError
from atlas_core.mobile import (
    MAX_IMAGEN_BYTES, MIME_PERMITIDOS,
    ErrorEnvioMobile, RepositorioEnviosMobile,
    procesar_y_revalidar_envio_mobile,
)

# Campos de metadata que el envío central ya trae y que `recibir()` acepta
# tal cual -- el mismo conjunto que `servidor_mobile.py::do_POST` arma para
# una subida LAN directa (ver ese archivo). Nunca se inventa un campo
# nuevo acá; si el contrato de `recibir()` crece, sólo hay que agregarlo
# a esta lista, un único lugar.
_CAMPOS_METADATA = (
    "chofer_id", "usuario", "capturado_en", "tipo_novedad",
    "guia_firmada_correo", "planta_origen_informada", "lote_id",
    # Bloque MOBILE OBSERVACIÓN DEL CHOFER V1.
    "observacion",
    # Bloque MOBILE CONTRATO V2.
    "tipos_novedad", "rol_documento", "evidencia_de_envio_id",
)


class ErrorSincronizacionMobile(RuntimeError):
    """Error de red/protocolo hablando con el receptor central -- nunca
    de datos ya aterrizados localmente (esos quedan reflejados en el
    resumen de retorno, no como excepción)."""


def _log(mensaje: str) -> None:
    ahora = datetime.now(timezone.utc).isoformat()
    print(f"[{ahora}] [mobile-sync-debug] {mensaje}")


def _solicitud(base_url: str, ruta: str, *, token: str, metodo: str = "GET", cuerpo: bytes | None = None) -> urllib.request.Request:
    return urllib.request.Request(
        base_url.rstrip("/") + ruta,
        data=cuerpo, method=metodo,
        headers={"Authorization": f"Bearer {token}"},
    )


def _listar_pendientes(base_url: str, token: str, timeout: float) -> list[dict]:
    try:
        with urllib.request.urlopen(_solicitud(base_url, "/api/mobile/sync/pendientes", token=token), timeout=timeout) as respuesta:
            datos = json.loads(respuesta.read())
    except urllib.error.HTTPError as error:
        raise ErrorSincronizacionMobile(f"receptor central respondió {error.code} listando pendientes") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ErrorSincronizacionMobile(f"no se pudo contactar al receptor central: {error}") from error
    return list(datos.get("envios", []))


def _descargar_imagen(base_url: str, token: str, envio_id: str, *, timeout: float) -> bytes:
    try:
        with urllib.request.urlopen(
            _solicitud(base_url, f"/api/mobile/sync/envios/{envio_id}/imagen", token=token), timeout=timeout,
        ) as respuesta:
            largo = respuesta.headers.get("Content-Length")
            if largo is not None and int(largo) > MAX_IMAGEN_BYTES:
                raise ErrorSincronizacionMobile(f"envio_id={envio_id!r}: imagen declarada más grande que el máximo permitido")
            contenido = respuesta.read(MAX_IMAGEN_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise ErrorSincronizacionMobile(f"envio_id={envio_id!r}: receptor central respondió {error.code} descargando la imagen") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ErrorSincronizacionMobile(f"envio_id={envio_id!r}: no se pudo descargar la imagen: {error}") from error
    if len(contenido) > MAX_IMAGEN_BYTES:
        raise ErrorSincronizacionMobile(f"envio_id={envio_id!r}: imagen descargada supera el máximo permitido")
    return contenido


def _confirmar(base_url: str, token: str, envio_id: str, *, consumidor: str, timeout: float) -> None:
    cuerpo = json.dumps({"consumidor": consumidor}).encode()
    try:
        urllib.request.urlopen(
            _solicitud(base_url, f"/api/mobile/sync/envios/{envio_id}/confirmar", token=token, metodo="POST", cuerpo=cuerpo),
            timeout=timeout,
        ).read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as error:
        # Best-effort a propósito (ver docstring del módulo): un envío ya
        # aterrizado localmente de forma idempotente NUNCA se revierte ni
        # se reporta como fallido sólo porque la confirmación al central
        # no llegó -- el próximo pull lo va a volver a listar como
        # pendiente y el aterrizaje local, al ser idempotente, es un
        # no-op seguro la segunda vez.
        _log(f"envio_id={envio_id!r} ADVERTENCIA -- no se pudo confirmar al receptor central: {error}")


def sincronizar_envios_pendientes(
    *, base_url: str, token: str, repositorio: RepositorioEnviosMobile,
    dataset: Path | None = None, carpeta_catalogos: str | Path | None = None,
    procesar: bool = True, timeout: float = 30.0, consumidor: str = "",
) -> dict:
    """Ejecuta un ciclo completo de sincronización PULL: lista lo
    pendiente en el receptor central, aterriza localmente lo que todavía
    no existe (verificando hash antes de aceptarlo), confirma lo
    aterrizado, y -- si `procesar=True` -- dispara el procesamiento
    (OCR/B1/reporte) de cualquier envío local todavía en `RECIBIDO`
    (incluidos los aterrizados en corridas anteriores cuyo procesamiento
    hubiera quedado pendiente, p. ej. porque el PC se apagó a mitad).

    Nunca lanza por un fallo AISLADO de un envío individual (hash
    inválido, descarga caída, OCR roto) -- eso queda reflejado en el
    resumen de retorno, para que un solo envío problemático nunca frene
    la sincronización del resto. Sí puede lanzar `ErrorSincronizacionMobile`
    si el receptor central es inalcanzable al LISTAR pendientes -- ahí no
    hay nada más que hacer en esta corrida."""
    resumen: dict[str, object] = {
        "encontrados": 0, "nuevos_sincronizados": [], "ya_existian_localmente": [],
        "fallidos_hash": [], "fallidos_descarga": [], "confirmados": [],
        "procesados": [], "omitidos_por_bloqueo": [], "errores_procesamiento": {},
    }

    pendientes = _listar_pendientes(base_url, token, timeout)
    resumen["encontrados"] = len(pendientes)

    for envio in pendientes:
        envio_id = str(envio.get("envio_id", ""))
        if not envio_id:
            continue
        ruta_local = repositorio.raiz / envio_id / "envio.json"
        if ruta_local.is_file():
            # Bloque IDEMPOTENCIA -- ya existe localmente (llegó por LAN
            # directo, o un pull anterior ya lo aterrizó pero la
            # confirmación no llegó al central, o dos consumidores
            # consultaron casi al mismo tiempo): nunca se vuelve a
            # descargar/crear nada -- sólo se intenta confirmar de nuevo
            # (best-effort) para que el central deje de listarlo.
            resumen["ya_existian_localmente"].append(envio_id)
            _confirmar(base_url, token, envio_id, consumidor=consumidor, timeout=timeout)
            resumen["confirmados"].append(envio_id)
            continue

        mime = str(envio.get("imagen_mime", ""))
        hash_declarado = str(envio.get("imagen_sha256", ""))
        if mime not in MIME_PERMITIDOS or not hash_declarado:
            resumen["fallidos_descarga"].append(envio_id)
            _log(f"envio_id={envio_id!r} metadata incompleta del receptor central (mime/hash) -- se reintentará en el próximo pull")
            continue

        try:
            contenido = _descargar_imagen(base_url, token, envio_id, timeout=timeout)
        except ErrorSincronizacionMobile as error:
            resumen["fallidos_descarga"].append(envio_id)
            _log(str(error) + " -- se reintentará en el próximo pull")
            continue

        # Bloque IDEMPOTENCIA -- "temporal -> verificar -> commit
        # atómico": el hash se verifica ACÁ, sobre bytes todavía sólo en
        # memoria de este proceso, ANTES de tocar disco para nada. Una
        # descarga incompleta/corrupta nunca llega a `recibir()` -- el
        # commit atómico real (temp-file + fsync + os.replace) lo hace
        # `recibir()` mismo, exactamente igual que para una subida LAN.
        if hashlib.sha256(contenido).hexdigest() != hash_declarado:
            resumen["fallidos_hash"].append(envio_id)
            _log(f"envio_id={envio_id!r} hash no coincide tras la descarga -- se descarta, se reintentará en el próximo pull")
            continue

        metadata = {campo: envio.get(campo, "") for campo in _CAMPOS_METADATA}
        try:
            registro, nuevo = repositorio.recibir(envio_id=envio_id, imagen=contenido, mime=mime, metadata=metadata)
        except ErrorEnvioMobile as error:
            resumen["fallidos_descarga"].append(envio_id)
            _log(f"envio_id={envio_id!r} el receptor local rechazó el envío aterrizado: {error}")
            continue

        if nuevo:
            resumen["nuevos_sincronizados"].append(envio_id)
        else:
            # Otro consumidor (p. ej. el otro PC de Javier) ya lo aterrizó
            # entre el chequeo de arriba y este `recibir()` -- carrera
            # real pero inofensiva: `recibir()` ya es idempotente y
            # devolvió el registro existente sin tocar nada.
            resumen["ya_existian_localmente"].append(envio_id)
        _confirmar(base_url, token, envio_id, consumidor=consumidor, timeout=timeout)
        resumen["confirmados"].append(envio_id)

    if procesar:
        # Bloque MULTI-PC -- procesa cualquier envío local todavía
        # RECIBIDO (recién aterrizado en esta corrida, o de una corrida
        # previa cuyo procesamiento no llegó a correr, p. ej. PC apagado
        # a mitad). `procesar_envio_mobile` sostiene el lock por envío
        # (`mobile_<id>`, ver TIEMPO_EXPIRACION_LOCK_ENVIO_SEGUNDOS en
        # atlas_core.mobile) durante TODA la operación -- si otro PC de
        # Javier (u otra corrida de este mismo script) ya está procesando
        # el MISMO envío, `bloqueo_sesion` levanta `SesionOcupadaError` y
        # ese envío particular simplemente se omite en esta pasada, nunca
        # se procesa dos veces. Para el piloto, la recomendación operativa
        # es correr este script desde UN solo PC a la vez (ver docstring
        # del CLI) -- este lock es la red de seguridad, no el mecanismo
        # principal de exclusión.
        for registro in repositorio.historial():
            if registro.get("estado") != "RECIBIDO":
                continue
            envio_id = str(registro.get("envio_id", ""))
            try:
                procesar_y_revalidar_envio_mobile(
                    repositorio, envio_id, dataset=dataset, carpeta_catalogos=carpeta_catalogos,
                )
                resumen["procesados"].append(envio_id)
            except SesionOcupadaError:
                # Bloque MULTI-PC -- otro consumidor (otro PC de Javier, u
                # otra corrida de este mismo script) ya sostiene el lock
                # de ESTE envío -- se omite en esta pasada, nunca se
                # procesa dos veces; el próximo ciclo de sincronización lo
                # vuelve a intentar si sigue en RECIBIDO.
                resumen["omitidos_por_bloqueo"].append(envio_id)
            except Exception as error:  # nunca debe cortar el resto de la sincronización/procesamiento.
                resumen["errores_procesamiento"][envio_id] = f"{type(error).__name__}: {error}"
                _log(f"envio_id={envio_id!r} ERROR procesando (recepción ya estaba a salvo): {type(error).__name__}: {error}")

    return resumen
