"""Bloque MOBILE ENVÍO REAL -- POST /api/mobile/envios devolvía 400 real.

Causa confirmada con evidencia (log de diagnóstico agregado en
`servidor_mobile.py`, nunca imprime password/token/binario): la cámara
del iPhone captura en HEIC/HEIF por defecto y el backend sólo acepta
jpeg/png/webp (MIME_PERMITIDOS, igual que el resto del pipeline OCR ya
usa para Desktop). El fix es del lado del celular (convierte a JPEG
antes de subir, ver Atlas-Conductores-Mobile) -- el backend
INTENCIONALMENTE sigue rechazando HEIC (nunca se tocó Core/OCR ni se
agregó una dependencia nueva de decodificación); estas pruebas fijan
esa frontera para que no se rompa sin darse cuenta.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from atlas_core.mobile import AutenticadorMobile, hash_password
from servidor_mobile import crear_servidor


def _auth() -> AutenticadorMobile:
    return AutenticadorMobile(
        {"javier": {"chofer_id": "chofer-1", "password_hash": hash_password("secreto")}},
        "secreto-de-prueba-envio-real-123456",
    )


def _multipart(campos: dict[str, str], imagen: bytes, mime: str) -> tuple[bytes, str]:
    boundary = "atlas-test-boundary"
    partes = []
    for nombre, valor in campos.items():
        partes.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{nombre}\"\r\n\r\n{valor}\r\n".encode())
    partes.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"imagen\"; filename=\"foto.heic\"\r\nContent-Type: {mime}\r\n\r\n".encode()
        + imagen + b"\r\n"
    )
    partes.append(f"--{boundary}--\r\n".encode())
    return b"".join(partes), f"multipart/form-data; boundary={boundary}"


def _token(servidor) -> str:
    login = urllib.request.Request(
        f"http://127.0.0.1:{servidor.server_port}/api/mobile/login",
        data=json.dumps({"usuario": "javier", "password": "secreto"}).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    return json.load(urllib.request.urlopen(login))["token"]


def test_heic_real_devuelve_400_con_motivo_exacto_tipo_no_permitido(tmp_path: Path) -> None:
    # Reproduce el 400 real del iPhone con un payload equivalente (sin
    # inventar el resultado): mismo contrato multipart, imagen_mime
    # HEIC -- exactamente lo que la cámara del iPhone manda por
    # defecto, según confirmó el log de diagnóstico.
    servidor = crear_servidor("127.0.0.1", 0, raiz=tmp_path, autenticador=_auth(), procesar=False)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True); hilo.start()
    try:
        token = _token(servidor)
        cuerpo, tipo = _multipart(
            {"envio_id": str(uuid.uuid4()), "schema_version": "1", "capturado_en": "2026-08-25T18:00:00Z"},
            b"contenido-heic-simulado", mime="image/heic",
        )
        solicitud = urllib.request.Request(
            f"http://127.0.0.1:{servidor.server_port}/api/mobile/envios",
            data=cuerpo, headers={"Content-Type": tipo, "Authorization": f"Bearer {token}"}, method="POST",
        )
        try:
            urllib.request.urlopen(solicitud)
            assert False, "un HEIC real debe seguir siendo rechazado por el backend (400)"
        except urllib.error.HTTPError as error:
            assert error.code == 400
            cuerpo_error = json.loads(error.read())
            assert cuerpo_error["error"] == "tipo de imagen no permitido"
    finally:
        servidor.shutdown(); servidor.server_close()


def test_jpeg_real_sigue_aceptandose_sin_regresion(tmp_path: Path) -> None:
    # El fix es del lado del celular -- el backend, para JPEG (lo que la
    # app ahora sube siempre), tiene que seguir funcionando exactamente
    # igual que antes de agregar el log de diagnóstico.
    servidor = crear_servidor("127.0.0.1", 0, raiz=tmp_path, autenticador=_auth(), procesar=False)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True); hilo.start()
    try:
        token = _token(servidor)
        envio_id = str(uuid.uuid4())
        cuerpo, tipo = _multipart(
            {"envio_id": envio_id, "schema_version": "1", "capturado_en": "2026-08-25T18:00:00Z"},
            b"contenido-jpeg-simulado", mime="image/jpeg",
        )
        solicitud = urllib.request.Request(
            f"http://127.0.0.1:{servidor.server_port}/api/mobile/envios",
            data=cuerpo, headers={"Content-Type": tipo, "Authorization": f"Bearer {token}"}, method="POST",
        )
        respuesta = json.load(urllib.request.urlopen(solicitud))
        assert respuesta["resultado"] == "ACEPTADO"
        assert respuesta["envio_id"] == envio_id
        assert not respuesta["duplicado"]
    finally:
        servidor.shutdown(); servidor.server_close()


def test_foto_grande_realista_de_iphone_ya_no_vuelve_400(tmp_path: Path) -> None:
    # Bloque MOBILE ENVÍO REAL (2do round): causa real confirmada con
    # log de diagnóstico -- "payload vacío o demasiado grande", no el
    # MIME. Una foto de ~20 MB (realista para un iPhone moderno de alta
    # resolución) superaba el límite viejo de 16 MiB; con el nuevo
    # límite (30 MiB en servidor_mobile.MAX_PAYLOAD_BYTES) debe pasar.
    servidor = crear_servidor("127.0.0.1", 0, raiz=tmp_path, autenticador=_auth(), procesar=False)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True); hilo.start()
    try:
        token = _token(servidor)
        envio_id = str(uuid.uuid4())
        contenido_20mb = b"x" * (20 * 1024 * 1024)
        cuerpo, tipo = _multipart(
            {"envio_id": envio_id, "schema_version": "1", "capturado_en": "2026-08-25T18:00:00Z"},
            contenido_20mb, mime="image/jpeg",
        )
        solicitud = urllib.request.Request(
            f"http://127.0.0.1:{servidor.server_port}/api/mobile/envios",
            data=cuerpo, headers={"Content-Type": tipo, "Authorization": f"Bearer {token}"}, method="POST",
        )
        respuesta = json.load(urllib.request.urlopen(solicitud))
        assert respuesta["resultado"] == "ACEPTADO"
    finally:
        servidor.shutdown(); servidor.server_close()
