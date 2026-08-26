from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

from atlas_core.mobile import (
    MAX_IMAGEN_BYTES, AutenticadorMobile, ErrorEnvioMobile, RepositorioEnviosMobile,
    asociar_documento, hash_password, procesar_envio_mobile,
)
from servidor_mobile import crear_servidor


def _auth() -> AutenticadorMobile:
    return AutenticadorMobile(
        {"carlos": {"chofer_id": "chofer-1", "password_hash": hash_password("secreto")}},
        "secreto-de-prueba-mobile-123456789",
    )


def _multipart(campos: dict[str, str], imagen: bytes, mime: str = "image/jpeg") -> tuple[bytes, str]:
    boundary = "atlas-test-boundary"
    partes = []
    for nombre, valor in campos.items():
        partes.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{nombre}\"\r\n\r\n{valor}\r\n".encode())
    partes.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"imagen\"; filename=\"malicioso.exe\"\r\nContent-Type: {mime}\r\n\r\n".encode()
        + imagen + b"\r\n"
    )
    partes.append(f"--{boundary}--\r\n".encode())
    return b"".join(partes), f"multipart/form-data; boundary={boundary}"


def test_recepcion_http_valida_e_idempotente(tmp_path: Path) -> None:
    servidor = crear_servidor("127.0.0.1", 0, raiz=tmp_path, autenticador=_auth(), procesar=False)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True); hilo.start()
    try:
        login = urllib.request.Request(
            f"http://127.0.0.1:{servidor.server_port}/api/mobile/login",
            data=json.dumps({"usuario": "carlos", "password": "secreto"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        token = json.load(urllib.request.urlopen(login))["token"]
        envio_id = str(uuid.uuid4())
        cuerpo, tipo = _multipart({
            "envio_id": envio_id, "schema_version": "1",
            "capturado_en": "2026-08-20T18:00:00Z",
            "tipo_novedad": "DEVOLUCION_PARCIAL", "guia_firmada_correo": "true",
            "planta_origen_informada": "AZA_COLINA",
        }, b"foto-original")
        solicitud = lambda: urllib.request.Request(
            f"http://127.0.0.1:{servidor.server_port}/api/mobile/envios",
            data=cuerpo, headers={"Content-Type": tipo, "Authorization": f"Bearer {token}"}, method="POST",
        )
        primera = json.load(urllib.request.urlopen(solicitud()))
        segunda = json.load(urllib.request.urlopen(solicitud()))
        assert primera["resultado"] == "ACEPTADO" and not primera["duplicado"]
        assert segunda["duplicado"]
        registro = servidor.repositorio.cargar(envio_id)  # type: ignore[attr-defined]
        assert registro["tipo_novedad"] == "DEVOLUCION_PARCIAL"
        assert registro["guia_firmada_correo"] is True
        assert (tmp_path / "operacion/mobile/envios" / envio_id / "original.jpg").read_bytes() == b"foto-original"
        assert len(list((tmp_path / "operacion/mobile/envios").iterdir())) == 1
    finally:
        servidor.shutdown(); servidor.server_close()


@pytest.mark.parametrize("caso", ("tipo", "grande"))
def test_archivo_invalido_o_grande_se_rechaza(tmp_path: Path, caso: str) -> None:
    mime = "application/pdf" if caso == "tipo" else "image/jpeg"
    # Bloque MOBILE ENVÍO REAL: el límite subió (evidencia real: una
    # foto HEIC de alta resolución lo superaba) -- se calcula contra la
    # constante real en vez de un número hardcodeado, para que este test
    # no se rompa (ni deje de probar nada) si el límite vuelve a cambiar.
    contenido = b"x" if caso == "tipo" else b"x" * (MAX_IMAGEN_BYTES + 1)
    with pytest.raises(ErrorEnvioMobile):
        RepositorioEnviosMobile(tmp_path).recibir(
            envio_id=str(uuid.uuid4()), imagen=contenido, mime=mime,
            metadata={"tipo_novedad": "", "guia_firmada_correo": False, "planta_origen_informada": "AZA_COLINA"},
        )


def test_pipeline_real_adaptado_asocia_guia_inequivoca(tmp_path: Path) -> None:
    repo = RepositorioEnviosMobile(tmp_path)
    envio_id = str(uuid.uuid4())
    repo.recibir(
        envio_id=envio_id, imagen=b"foto", mime="image/jpeg",
        metadata={"chofer_id": "c1", "tipo_novedad": "TIENE_ESTADIA", "guia_firmada_correo": True, "planta_origen_informada": "AZA_COLINA"},
    )
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    dataset.parent.mkdir(parents=True)
    dataset.write_text("numero_guia;numero_transporte\n464265;0000351135\n", encoding="utf-8-sig")
    registro = procesar_envio_mobile(
        repo, envio_id, dataset=dataset,
        procesador=lambda ruta: {"numero_guia": "464265", "numero_transporte": "0000351135"},
    )
    assert registro["estado"] == "ASOCIADO"
    assert registro["atlas_ia"]["llamadas"] == 0
    assert registro["resultado_asociacion"]["numero_transporte"] == "0000351135"
    assert registro["tipo_novedad"] == "TIENE_ESTADIA" and registro["guia_firmada_correo"] is True


def test_ambigua_o_sin_asociacion_va_a_bandeja(tmp_path: Path) -> None:
    repo = RepositorioEnviosMobile(tmp_path)
    envio_id = str(uuid.uuid4())
    repo.recibir(
        envio_id=envio_id, imagen=b"foto", mime="image/jpeg",
        metadata={"chofer_id": "c1", "tipo_novedad": "DOBLE_VUELTA", "guia_firmada_correo": False, "planta_origen_informada": "AZA_COLINA"},
    )
    registro = procesar_envio_mobile(
        repo, envio_id, procesador=lambda ruta: {"numero_guia": "No encontrado", "numero_transporte": "No encontrado"},
    )
    assert registro["estado"] == "REQUIERE_REVISION"
    assert repo.pendientes()[0]["envio_id"] == envio_id
    assert registro["tipo_novedad"] == "DOBLE_VUELTA"
