"""Servidor HTTP mínimo para Atlas Conductores Mobile (stdlib, sin cloud)."""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from atlas_core.catalogos import cargar_catalogo_json
from atlas_core.fuente_catalogos import ErrorFuenteCatalogos, validar_fuente_catalogos
from atlas_core.mobile import (
    AutenticadorMobile, AutenticadorSincronizacionMobile, ErrorEnvioMobile, RepositorioEnviosMobile,
    procesar_y_revalidar_envio_mobile,
)
from atlas_core.almacenamiento_portable import leer_estado_operacion, resolver_raiz_atlas


MAX_PAYLOAD_BYTES = 30 * 1024 * 1024  # ver atlas_core.mobile.MAX_IMAGEN_BYTES -- mismo motivo/margen.


def _descartar_cuerpo(handler: BaseHTTPRequestHandler) -> None:
    """Consume y descarta el body de la solicitud sin parsearlo.

    Bloque MOBILE COLA V2 -- cuando la autenticación falla ANTES de leer el
    multipart (401 `token_invalido`), responder sin drenar el body deja al
    cliente/proxy escribiendo una foto de varios MB contra un socket que el
    servidor ya no lee -> `stdlib http.server` cierra la conexión y el
    cliente ve un `ECONNRESET` en vez del 401 (evidencia real: primer
    Viaje A, el proxy dev-server ni siquiera podía leer el 401). Drenar el
    body deja la conexión en un estado consumible y el 401 llega limpio.
    No cambia el contrato ni la autenticación: sólo vacía bytes que igual
    se iban a ignorar. Tolera un Content-Length ausente/no numérico."""
    try:
        restante = int(handler.headers.get("Content-Length", "0") or "0")
    except (TypeError, ValueError):
        return
    if restante <= 0 or restante > MAX_PAYLOAD_BYTES:
        return
    while restante > 0:
        trozo = handler.rfile.read(min(restante, 65536))
        if not trozo:
            break
        restante -= len(trozo)


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
            # Bloque MOBILE OBSERVACIÓN DEL CHOFER V1 -- con texto libre
            # (`observacion`) un byte no UTF-8 es posible; responde 400 en
            # vez de dejar escapar la excepción y cortar la conexión.
            try:
                campos[nombre] = contenido.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ErrorEnvioMobile(f"campo {nombre} no es UTF-8 válido") from error
    return campos, imagen, mime


# Bloque MOBILE ENVÍO REAL (fix puntual): log de diagnóstico TEMPORAL y
# seguro -- timestamp, envio_id, chofer_id, content-type, nombres de
# campo recibidos, tamaño/mime de la imagen, y el motivo exacto de un
# 400. NUNCA token completo, password ni contenido binario.
def _log_envio_debug(mensaje: str) -> None:
    ahora = datetime.now(timezone.utc).isoformat()
    print(f"[{ahora}] [mobile-envio-debug] {mensaje}")


# Bloque MOBILE SINCRONIZACIÓN PULL V1 -- la orquestación "qué pasa
# después de recibir un envío" (procesar + revalidar asociación +
# reconciliar reporte, caso real 472623/472624) se movió a
# `atlas_core.mobile.procesar_y_revalidar_envio_mobile` para que el
# consumidor PULL local la reutilice tal cual -- nunca una segunda
# implementación paralela. Este archivo sólo la invoca.
#
# Rutas nuevas, SOLO activas si el llamador de `crear_servidor` pasa
# `autenticador_sync` (en `main()`, sólo si `ATLAS_MOBILE_SYNC_TOKEN` está
# configurado) -- sin eso, se comportan exactamente como cualquier ruta no
# reconocida (404), igual que antes de este bloque: el modo LAN existente
# (login/envíos de chofer) no cambia en nada si nadie configura el
# secreto de sincronización. El PC de Atlas (nunca el receptor) es quien
# iniciacada solicitud -- estas rutas son sólo lectura + una confirmación
# idempotente, nunca ejecutan nada que el cliente mande (nunca hay un
# "comando remoto" -- ver Sección DISEÑO del bloque).
_RUTA_SYNC_PENDIENTES = "/api/mobile/sync/pendientes"
_RUTA_SYNC_IMAGEN = re.compile(r"^/api/mobile/sync/envios/([A-Za-z0-9][A-Za-z0-9._-]{7,127})/imagen$")
_RUTA_SYNC_CONFIRMAR = re.compile(r"^/api/mobile/sync/envios/([A-Za-z0-9][A-Za-z0-9._-]{7,127})/confirmar$")


def _nombre_canonico_chofer(carpeta_catalogos: object, chofer_id: str) -> str:
    """Nombre del chofer en `choferes.json` (clave = `chofer_id`), o "" si
    no hay catálogo o el chofer no está (p. ej. cuentas de prueba). Se lee
    en cada login para que un chofer recién catalogado aparezca sin
    reiniciar el servidor; nunca lanza."""
    if not carpeta_catalogos:
        return ""
    registro = cargar_catalogo_json(Path(carpeta_catalogos) / "choferes.json").get(str(chofer_id))
    nombre = registro.get("nombre") if isinstance(registro, dict) else None
    return nombre.strip() if isinstance(nombre, str) else ""


def crear_servidor(
    host: str, puerto: int, *, raiz: Path, autenticador: AutenticadorMobile,
    autenticador_sync: AutenticadorSincronizacionMobile | None = None,
    procesar: bool = True, origen_permitido: str = "*",
) -> ThreadingHTTPServer:
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
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()

        # Bloque MOBILE SINCRONIZACIÓN PULL V1 -- credencial DISTINTA de
        # la del chofer (`AutenticadorMobile.autenticar`, arriba); ver
        # `AutenticadorSincronizacionMobile` en atlas_core/mobile.py.
        def _autorizado_sync(self) -> bool:
            if autenticador_sync is None:
                return False
            cabecera = self.headers.get("Authorization", "")
            token = cabecera[7:] if cabecera.startswith("Bearer ") else ""
            return autenticador_sync.autenticar(token)

        def do_GET(self) -> None:
            ruta = urlparse(self.path).path

            if ruta == _RUTA_SYNC_PENDIENTES:
                if not self._autorizado_sync():
                    self._json(401, {"error": "token_sync_invalido"}); return
                self._json(200, {"envios": repositorio.listar_pendientes_sincronizacion()})
                return

            coincidencia = _RUTA_SYNC_IMAGEN.fullmatch(ruta)
            if coincidencia:
                if not self._autorizado_sync():
                    self._json(401, {"error": "token_sync_invalido"}); return
                envio_id = coincidencia.group(1)
                try:
                    registro = repositorio.cargar(envio_id)
                    contenido = repositorio.ruta_imagen(envio_id).read_bytes()
                except (ErrorEnvioMobile, OSError, json.JSONDecodeError):
                    self._json(404, {"error": "envio_no_encontrado"}); return
                self.send_response(200)
                self.send_header("Content-Type", str(registro.get("imagen_mime", "application/octet-stream")))
                self.send_header("Content-Length", str(len(contenido)))
                self.send_header("Access-Control-Allow-Origin", origen_permitido)
                self.end_headers()
                self.wfile.write(contenido)
                return

            self._json(404, {"error": "ruta_no_encontrada"})

        def do_POST(self) -> None:
            ruta = urlparse(self.path).path

            coincidencia = _RUTA_SYNC_CONFIRMAR.fullmatch(ruta)
            if coincidencia:
                if not self._autorizado_sync():
                    _descartar_cuerpo(self)
                    self._json(401, {"error": "token_sync_invalido"}); return
                envio_id = coincidencia.group(1)
                try:
                    largo = int(self.headers.get("Content-Length", "0") or "0")
                except ValueError:
                    largo = 0
                cuerpo_bruto = self.rfile.read(largo) if 0 < largo <= MAX_PAYLOAD_BYTES else b""
                try:
                    datos = json.loads(cuerpo_bruto) if cuerpo_bruto else {}
                except json.JSONDecodeError:
                    datos = {}
                consumidor = str(datos.get("consumidor", "")).strip() or self.address_string()
                try:
                    registro = repositorio.marcar_sincronizado(envio_id, consumidor=consumidor)
                except (ErrorEnvioMobile, OSError, json.JSONDecodeError):
                    self._json(404, {"error": "envio_no_encontrado"}); return
                self._json(200, {"resultado": "OK", "envio_id": envio_id, "sincronizacion": registro["sincronizacion"]})
                return

            if ruta == "/api/mobile/login":
                try:
                    largo = int(self.headers.get("Content-Length", "0"))
                    datos = json.loads(self.rfile.read(largo))
                    sesion = autenticador.login(str(datos.get("usuario", "")), str(datos.get("password", "")))
                except (ValueError, json.JSONDecodeError):
                    sesion = None
                if sesion:
                    # Nombre canónico del chofer para el saludo de la app
                    # (sólo presentación; la autenticación no cambia).
                    sesion = {**sesion, "nombre_chofer": _nombre_canonico_chofer(carpeta_catalogos, sesion["chofer_id"])}
                self._json(200 if sesion else 401, sesion or {"error": "credenciales_invalidas"})
                return
            if ruta != "/api/mobile/envios":
                self._json(404, {"error": "ruta_no_encontrada"}); return
            cabecera = self.headers.get("Authorization", "")
            identidad = autenticador.autenticar(cabecera[7:] if cabecera.startswith("Bearer ") else "")
            if not identidad:
                # Bloque MOBILE COLA V2 -- drenar el body ANTES de responder
                # el 401: si no, el cliente sigue subiendo la foto contra un
                # socket que ya no se lee y ve un ECONNRESET en vez del 401
                # (ver _descartar_cuerpo).
                _descartar_cuerpo(self)
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
                        # Bloque MOBILE OBSERVACIÓN DEL CHOFER V1 -- texto
                        # libre opcional del ENVÍO (misma en cada foto de
                        # la tanda). Ausente en clientes anteriores ->
                        # `recibir` lo guarda como "". Validado/normalizado
                        # en `atlas_core.mobile.normalizar_observacion_mobile`.
                        "observacion": campos.get("observacion"),
                        # Bloque MOBILE CONTRATO V2 -- opcionales; un cliente v1
                        # no los manda y `recibir` los completa compatibles.
                        "tipos_novedad": campos.get("tipos_novedad"),
                        "rol_documento": campos.get("rol_documento"),
                        "evidencia_de_envio_id": campos.get("evidencia_de_envio_id"),
                    },
                )
                if nuevo and procesar:
                    ejecutor.submit(
                        procesar_y_revalidar_envio_mobile, repositorio, registro["envio_id"],
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
    # Bloque MOBILE SINCRONIZACIÓN PULL V1 -- secreto SEPARADO del de
    # login de chofer (ver AutenticadorSincronizacionMobile). Sin
    # configurar (piloto LAN actual, sin receptor central todavía), las
    # rutas /api/mobile/sync/* quedan simplemente inexistentes (404) --
    # cero cambio de comportamiento para el modo LAN existente.
    secreto_sync = os.environ.get("ATLAS_MOBILE_SYNC_TOKEN", "")
    autenticador_sync = AutenticadorSincronizacionMobile(secreto_sync) if secreto_sync else None
    servidor = crear_servidor(
        args.host, args.puerto, raiz=raiz, autenticador=AutenticadorMobile(usuarios, secreto),
        autenticador_sync=autenticador_sync,
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
