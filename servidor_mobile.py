"""Servidor HTTP mínimo para Atlas Conductores Mobile (stdlib, sin cloud)."""

from __future__ import annotations

import argparse
import json
import os
import ssl
from concurrent.futures import ThreadPoolExecutor
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from atlas_core.almacenamiento_portable import leer_estado_operacion, resolver_raiz_atlas
from atlas_core.fuente_catalogos import ErrorFuenteCatalogos, validar_fuente_catalogos
from atlas_core.mobile import AutenticadorMobile, ErrorEnvioMobile, RepositorioEnviosMobile, procesar_envio_mobile


def _multipart(handler: BaseHTTPRequestHandler) -> tuple[dict[str, str], bytes, str]:
    largo = int(handler.headers.get("Content-Length", "0"))
    if largo <= 0 or largo > 16 * 1024 * 1024:
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
                registro, nuevo = repositorio.recibir(
                    envio_id=campos.get("envio_id", ""), imagen=imagen, mime=mime,
                    metadata={
                        "chofer_id": identidad["chofer_id"], "usuario": identidad["usuario"],
                        "capturado_en": campos.get("capturado_en", ""),
                        "tipo_novedad": campos.get("tipo_novedad", ""),
                        "guia_firmada_correo": campos.get("guia_firmada_correo") == "true",
                    },
                )
                if nuevo and procesar:
                    ejecutor.submit(
                        procesar_envio_mobile, repositorio, registro["envio_id"],
                        dataset=dataset, carpeta_catalogos=carpeta_catalogos,
                    )
                self._json(202, {"resultado": "ACEPTADO", "envio_id": registro["envio_id"], "estado": registro["estado"], "duplicado": not nuevo})
            except ErrorEnvioMobile as error:
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
