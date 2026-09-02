"""Servidor HTTP mínimo para Atlas Conductores Mobile (stdlib, sin cloud)."""

from __future__ import annotations

import argparse
import json
import os
import ssl
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from atlas_core.almacenamiento_portable import bloqueo_sesion, leer_estado_operacion, resolver_raiz_atlas
from atlas_core.fuente_catalogos import ErrorFuenteCatalogos, validar_fuente_catalogos
from atlas_core.mobile import (
    TIEMPO_EXPIRACION_LOCK_ENVIO_SEGUNDOS,
    AutenticadorMobile, ErrorEnvioMobile, RepositorioEnviosMobile,
    procesar_envio_mobile, revalidar_asociacion_mobile_sin_ocr,
)
from atlas_core.revalidacion_documental import revalidar_y_regenerar_reporte


MAX_PAYLOAD_BYTES = 30 * 1024 * 1024  # ver atlas_core.mobile.MAX_IMAGEN_BYTES -- mismo motivo/margen.


def _multipart(handler: BaseHTTPRequestHandler) -> tuple[dict[str, str], bytes, str]:
    largo = int(handler.headers.get("Content-Length", "0"))
    if largo <= 0 or largo > MAX_PAYLOAD_BYTES:
        # Bloque MOBILE ENVÍO REAL (fix puntual, 2do round): evidencia
        # real (log de diagnóstico) confirmó que el 400 real del iPhone
        # era "payload vacío o demasiado grande", no el MIME -- una foto
        # HEIC de alta resolución (iPhone moderno) supera fácilmente los
        # 16 MiB que tenía este límite. Se sube a 30 MiB (mismo límite
        # que ya usa RepositorioEnviosMobile.recibir) y además el
        # celular ahora recomprime/redimensiona antes de subir (ver
        # Atlas-Conductores-Mobile/src/camera.js) -- doble margen.
        _log_envio_debug(f"400 -- Content-Length={largo} (límite {MAX_PAYLOAD_BYTES})")
        raise ErrorEnvioMobile("payload vacío o demasiado grande")
    tipo = handler.headers.get("Content-Type", "")
    if not tipo.startswith("multipart/form-data;"):
        raise ErrorEnvioMobile("se requiere multipart/form-data")
    mensaje = BytesParser(policy=default).parsebytes(
        f"Content-Type: {tipo}\r\nMIME-Version: 1.0\r\n\r\n".encode() + handler.rfile.read(largo)
    )
    campos: dict[str, str] = {}
    imagen = b""
    mime = ""
    for parte in mensaje.iter_parts():
        nombre = parte.get_param("name", header="content-disposition")
        contenido = parte.get_payload(decode=True) or b""
        if nombre == "imagen":
            imagen, mime = contenido, parte.get_content_type()
        elif nombre:
            campos[nombre] = contenido.decode("utf-8")
    return campos, imagen, mime


# Bloque MOBILE ENVÍO REAL (fix puntual): log de diagnóstico TEMPORAL y
# seguro -- timestamp, envio_id, chofer_id, content-type, nombres de
# campo recibidos, tamaño/mime de la imagen, y el motivo exacto de un
# 400. NUNCA token completo, password ni contenido binario.
def _log_envio_debug(mensaje: str) -> None:
    ahora = datetime.now(timezone.utc).isoformat()
    print(f"[{ahora}] [mobile-envio-debug] {mensaje}")


# Bloque ASOCIACIÓN MOBILE V2 (Sección 4 -- Multiguía; Sección 7 --
# reevaluación): procesa el envío nuevo y, en el MISMO worker (el
# ejecutor sigue siendo de 1 hilo -- nunca se agrega concurrencia/cola
# nueva), reintenta la asociación de cualquier otro envío que hubiera
# quedado SIN_ASOCIACION/PROPUESTA_REQUIERE_REVISION. Es el mecanismo
# real por el que, en una tanda con Doc A y Doc B del mismo transporte,
# Doc A (que se procesó primero, sin nada todavía con qué asociarse)
# termina asociado igual que Doc B apenas éste se persiste -- sin volver
# a correr OCR, sin recrear ningún envío.
#
# Bloque MOBILE -> DESKTOP (fix real, caso real 472623/472624): causa
# raíz confirmada -- ni `procesar_envio_mobile` ni `revalidar_asociacion_
# mobile_sin_ocr` regeneran nunca el reporte/`estado_operacion.json` que
# Desktop realmente lee; la fila ya queda bien escrita en el dataset,
# pero Desktop seguía mostrando un reporte viejo hasta que algún proceso
# EXTERNO (sin relación con Mobile) volviera a reconciliar. Se cierra
# reusando el reconciliador general YA EXISTENTE (`revalidar_y_
# regenerar_reporte`, el mismo que usa el resto de Atlas tras cualquier
# mutación real de datos -- nunca un segundo reconciliador paralelo).
def _procesar_y_revalidar(repositorio: RepositorioEnviosMobile, envio_id: str, *, dataset: Path, carpeta_catalogos) -> None:
    procesar_envio_mobile(repositorio, envio_id, dataset=dataset, carpeta_catalogos=carpeta_catalogos)
    if dataset:
        _revalidar_asociacion_diagnosticable(repositorio, envio_id, dataset=dataset)
    # Hallazgo Codex #2 -- antes, un fallo de la línea de arriba (excepción
    # no capturada) cortaba la cadena acá mismo y esta llamada nunca
    # corría: el documento ya podía estar correctamente persistido (el
    # paso de arriba sólo revalida, nunca reescribe la fila del dataset)
    # y aun así quedaba invisible en Desktop porque el reporte jamás se
    # intentaba regenerar. Ahora corre SIEMPRE, incluso si la revalidación
    # de asociación falló -- con lo que el documento ya dejó persistido.
    _regenerar_reporte_tras_envio_mobile(repositorio, envio_id)


def _revalidar_asociacion_diagnosticable(repositorio: RepositorioEnviosMobile, envio_id: str, *, dataset: Path) -> None:
    """Envoltorio de `revalidar_asociacion_mobile_sin_ocr` que nunca deja
    que un fallo ahí (p. ej. catálogo ilegible) se propague y corte la
    cadena de `_procesar_y_revalidar` antes de la reconciliación del
    reporte -- el documento de este envío ya quedó persistido por
    `procesar_envio_mobile` (paso anterior); esta revalidación es sólo un
    refinamiento posterior sin OCR, no una condición para que el reporte
    se regenere. El fallo se registra diagnosticable en un campo APARTE
    (`revalidacion_asociacion_post_ocr`) del envío que se estaba
    procesando -- nunca en `estado`/`error` (que siguen describiendo
    únicamente el resultado de procesar el documento), y nunca duplica ni
    reprocesa nada."""
    try:
        revalidar_asociacion_mobile_sin_ocr(repositorio, dataset=dataset)
    except Exception as error:  # nunca debe impedir la reconciliación del reporte que sigue.
        _log_envio_debug(
            f"envio_id={envio_id!r} ERROR revalidando asociación post-OCR: {type(error).__name__}: {error}"
        )
        try:
            # Bloque CONSISTENCIA OPERACIONAL -- lock por envío: este
            # registro diagnóstico compite por el MISMO envio.json que
            # `procesar_envio_mobile`/un reproceso podrían estar tocando
            # concurrentemente; nunca se escribe a ciegas encima.
            with bloqueo_sesion(
                repositorio.raiz, f"mobile_{envio_id}",
                tiempo_expiracion_segundos=TIEMPO_EXPIRACION_LOCK_ENVIO_SEGUNDOS,
            ):
                registro = repositorio.cargar(envio_id)
                registro["revalidacion_asociacion_post_ocr"] = {
                    "estado": "ERROR",
                    "error": f"{type(error).__name__}: {error}",
                    "intentado_en": datetime.now(timezone.utc).isoformat(),
                }
                repositorio.guardar(envio_id, registro)
        except Exception:
            pass  # el registro del intento es best-effort; nunca debe volver a cortar el flujo.


def _regenerar_reporte_tras_envio_mobile(repositorio: RepositorioEnviosMobile, envio_id: str) -> None:
    """Corre SIEMPRE en el mismo worker de 1 hilo en segundo plano --
    el 202 de `do_POST` ya se respondió mucho antes de que este código
    exista; nunca bloquea la subida esperando OCR/B1/reporte.
    `revalidar_y_regenerar_reporte` ya es idempotente por diseño (sólo
    reescribe el reporte si algo cambió de verdad) -- no hace falta
    ninguna lógica nueva de idempotencia acá, sólo invocarlo.

    Un fallo acá (p. ej. catálogos ilegibles, proveedor de rutas caído)
    NUNCA debe borrar ni duplicar el envío ya procesado -- se captura y
    se registra en un campo APARTE (`reconciliacion_reporte`), nunca en
    `estado`/`error` (que siguen describiendo únicamente el resultado
    de procesar el DOCUMENTO, no el de reconciliar el reporte) -- queda
    diagnosticable en el propio envio.json sin adivinar."""
    sello = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    intento: dict[str, object] = {"intentado_en": datetime.now(timezone.utc).isoformat()}
    try:
        resultado = revalidar_y_regenerar_reporte(
            raiz_atlas=repositorio.raiz_atlas, nombre_carpeta_reporte=f"reporte_mobile_{sello}",
        )
        intento.update({
            "estado": "OK",
            "reporte_regenerado": bool(resultado.get("reporte_regenerado")),
            "reporte_vigente": resultado.get("reporte_vigente"),
        })
        _log_envio_debug(
            f"envio_id={envio_id!r} reconciliación de reporte OK -- "
            f"reporte_regenerado={resultado.get('reporte_regenerado')!r}"
        )
    except Exception as error:  # nunca debe perder/duplicar el envío ya procesado.
        intento.update({"estado": "ERROR", "error": f"{type(error).__name__}: {error}"})
        _log_envio_debug(f"envio_id={envio_id!r} ERROR reconciliando reporte: {type(error).__name__}: {error}")
    # Bloque CONSISTENCIA OPERACIONAL -- mismo lock por envío que el
    # resto de escritores de este envio.json.
    with bloqueo_sesion(
        repositorio.raiz, f"mobile_{envio_id}",
        tiempo_expiracion_segundos=TIEMPO_EXPIRACION_LOCK_ENVIO_SEGUNDOS,
    ):
        registro = repositorio.cargar(envio_id)
        registro["reconciliacion_reporte"] = intento
        repositorio.guardar(envio_id, registro)


def crear_servidor(host: str, puerto: int, *, raiz: Path, autenticador: AutenticadorMobile, procesar: bool = True, origen_permitido: str = "*") -> ThreadingHTTPServer:
    repositorio = RepositorioEnviosMobile(raiz)
    ejecutor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="atlas-mobile")
    estado = leer_estado_operacion(raiz=raiz) or {}
    dataset = raiz / estado.get("dataset_operacional", "operacion/actual/analisis_completo_guias.csv")
    # Bloque GUÍAS MÓVILES V1 (Sección 2): misma fuente de catálogos que ya
    # usa Desktop/analizar_guias_masivo.py (ATLAS_CATALOGOS_DIR) -- nunca
    # una configuración paralela para Mobile. Sin catálogos configurados,
    # se procesa igual que antes (sólo OCR, se abstiene del resto), nunca
    # se rompe el servidor.
    try:
        carpeta_catalogos = validar_fuente_catalogos(None, permitir_sin_catalogos=True).ruta
    except ErrorFuenteCatalogos:
        carpeta_catalogos = None

    class Handler(BaseHTTPRequestHandler):
        def _json(self, codigo: int, contenido: object) -> None:
            cuerpo = json.dumps(contenido, ensure_ascii=False).encode()
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Access-Control-Allow-Origin", origen_permitido)
            self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(cuerpo)

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", origen_permitido)
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.end_headers()

        def do_POST(self) -> None:
            ruta = urlparse(self.path).path
            if ruta == "/api/mobile/login":
                try:
                    largo = int(self.headers.get("Content-Length", "0"))
                    datos = json.loads(self.rfile.read(largo))
                    sesion = autenticador.login(str(datos.get("usuario", "")), str(datos.get("password", "")))
                except (ValueError, json.JSONDecodeError):
                    sesion = None
                self._json(200 if sesion else 401, sesion or {"error": "credenciales_invalidas"})
                return
            if ruta != "/api/mobile/envios":
                self._json(404, {"error": "ruta_no_encontrada"}); return
            cabecera = self.headers.get("Authorization", "")
            identidad = autenticador.autenticar(cabecera[7:] if cabecera.startswith("Bearer ") else "")
            if not identidad:
                self._json(401, {"error": "token_invalido"}); return
            try:
                campos, imagen, mime = _multipart(self)
                _log_envio_debug(
                    f"POST /api/mobile/envios envio_id={campos.get('envio_id', '')!r} "
                    f"chofer_id={identidad['chofer_id']!r} content-type_header={self.headers.get('Content-Type', '')!r} "
                    f"campos_recibidos={sorted(campos.keys())} imagen_mime={mime!r} imagen_bytes={len(imagen)}"
                )
                registro, nuevo = repositorio.recibir(
                    envio_id=campos.get("envio_id", ""), imagen=imagen, mime=mime,
                    metadata={
                        "chofer_id": identidad["chofer_id"], "usuario": identidad["usuario"],
                        "capturado_en": campos.get("capturado_en", ""),
                        "tipo_novedad": campos.get("tipo_novedad", ""),
                        "guia_firmada_correo": campos.get("guia_firmada_correo") == "true",
                        # Bloque MOBILE V1 -- planta de origen informada
                        # por el chofer (evidencia, no verdad absoluta;
                        # ver atlas_core.mobile.PLANTAS_ORIGEN_MOBILE).
                        "planta_origen_informada": campos.get("planta_origen_informada", ""),
                        # Bloque MOBILE MULTIGUÍA V1 -- identificador
                        # administrativo de TANDA (varias fotos capturadas
                        # juntas antes de "Enviar N guías", ver
                        # Atlas-Conductores-Mobile/src/app.js). Puramente
                        # informativo/trazabilidad -- NUNCA se usa para
                        # agrupar/consolidar viajes (eso sigue siendo
                        # exclusivamente numero_transporte, ver
                        # atlas_core.gestor_viajes). Ausente en envíos
                        # Mobile V1 históricos (una sola foto, sin tanda) --
                        # `repositorio.recibir` ya tolera cualquier
                        # metadata ausente/nueva sin cambios.
                        "lote_id": campos.get("lote_id", ""),
                    },
                )
                if nuevo and procesar:
                    ejecutor.submit(
                        _procesar_y_revalidar, repositorio, registro["envio_id"],
                        dataset=dataset, carpeta_catalogos=carpeta_catalogos,
                    )
                _log_envio_debug(f"envio_id={registro['envio_id']!r} ACEPTADO (nuevo={nuevo}, estado={registro['estado']!r})")
                self._json(202, {"resultado": "ACEPTADO", "envio_id": registro["envio_id"], "estado": registro["estado"], "duplicado": not nuevo})
            except ErrorEnvioMobile as error:
                _log_envio_debug(f"400 -- motivo exacto: {error}")
                self._json(400, {"error": str(error)})

        def log_message(self, formato: str, *args: object) -> None:
            print(f"mobile {self.address_string()} {formato % args}")

    servidor = ThreadingHTTPServer((host, puerto), Handler)
    servidor.repositorio = repositorio  # type: ignore[attr-defined]
    servidor.ejecutor = ejecutor  # type: ignore[attr-defined]
    return servidor


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--puerto", type=int, default=8765)
    parser.add_argument("--raiz-atlas", type=Path)
    parser.add_argument("--usuarios", type=Path)
    parser.add_argument("--cert", type=Path, help="Certificado TLS PEM para prueba desde iPhone")
    parser.add_argument("--key", type=Path, help="Clave privada TLS PEM")
    args = parser.parse_args()
    raiz = resolver_raiz_atlas(args.raiz_atlas)
    usuarios_path = args.usuarios or (raiz / "catalogos_privados" / "usuarios_mobile.json")
    usuarios = json.loads(usuarios_path.read_text(encoding="utf-8"))["usuarios"]
    secreto = os.environ.get("ATLAS_MOBILE_TOKEN_SECRET", "")
    servidor = crear_servidor(
        args.host, args.puerto, raiz=raiz, autenticador=AutenticadorMobile(usuarios, secreto),
        origen_permitido=os.environ.get("ATLAS_MOBILE_ALLOWED_ORIGIN", "*"),
    )
    esquema = "http"
    if args.cert or args.key:
        if not (args.cert and args.key):
            parser.error("--cert y --key deben indicarse juntos")
        contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        contexto.load_cert_chain(args.cert, args.key)
        servidor.socket = contexto.wrap_socket(servidor.socket, server_side=True)
        esquema = "https"
    print(f"Atlas Mobile escuchando en {esquema}://{args.host}:{servidor.server_port}")
    servidor.serve_forever()


if __name__ == "__main__":
    main()
