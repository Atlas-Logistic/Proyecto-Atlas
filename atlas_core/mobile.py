"""Ingreso Mobile durable, idempotente y conectado al pipeline real de Atlas."""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico
from atlas_core.procesamiento_masivo import (
    COLUMNAS, escalar_resultado_ia_en_memoria, procesar_archivo,
)

ESTADOS = ("RECIBIDO", "PROCESANDO", "ASOCIADO", "REQUIERE_REVISION", "ERROR")
TIPOS_NOVEDAD = (
    "", "ESPERA_AUTORIZACION_ESTADIA", "TIENE_ESTADIA", "DEVOLUCION_TOTAL",
    "DEVOLUCION_PARCIAL", "DOBLE_VUELTA",
)
MIME_PERMITIDOS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_IMAGEN_BYTES = 15 * 1024 * 1024
_ID_SEGURO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")


class ErrorEnvioMobile(ValueError):
    pass


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"pbkdf2_sha256$200000${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verificar_password(password: str, codificado: str) -> bool:
    try:
        algoritmo, iteraciones, salt_b64, digest_b64 = codificado.split("$", 3)
        if algoritmo != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_b64)
        esperado = base64.urlsafe_b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iteraciones))
        return hmac.compare_digest(actual, esperado)
    except (ValueError, TypeError):
        return False


class AutenticadorMobile:
    def __init__(self, usuarios: Mapping[str, Mapping[str, str]], secreto: str, *, ttl: int = 86400) -> None:
        if len(secreto) < 24:
            raise ValueError("El secreto Mobile debe tener al menos 24 caracteres.")
        self.usuarios = {str(k): dict(v) for k, v in usuarios.items()}
        self.secreto = secreto.encode()
        self.ttl = ttl

    def login(self, usuario: str, password: str) -> dict[str, str] | None:
        cuenta = self.usuarios.get(usuario)
        if not cuenta or not verificar_password(password, cuenta.get("password_hash", "")):
            return None
        ahora = int(datetime.now(timezone.utc).timestamp())
        payload = {"sub": cuenta["chofer_id"], "usuario": usuario, "exp": ahora + self.ttl}
        cuerpo = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
        firma = base64.urlsafe_b64encode(hmac.new(self.secreto, cuerpo.encode(), hashlib.sha256).digest()).decode().rstrip("=")
        return {"token": f"{cuerpo}.{firma}", "chofer_id": cuenta["chofer_id"]}

    def autenticar(self, token: str) -> dict[str, str] | None:
        try:
            cuerpo, firma = token.split(".", 1)
            esperada = base64.urlsafe_b64encode(hmac.new(self.secreto, cuerpo.encode(), hashlib.sha256).digest()).decode().rstrip("=")
            if not hmac.compare_digest(firma, esperada):
                return None
            payload = json.loads(base64.urlsafe_b64decode(cuerpo + "=" * (-len(cuerpo) % 4)))
            if int(payload["exp"]) < int(datetime.now(timezone.utc).timestamp()):
                return None
            return {"chofer_id": str(payload["sub"]), "usuario": str(payload["usuario"])}
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None


@dataclass
class RepositorioEnviosMobile:
    raiz_atlas: Path

    @property
    def raiz(self) -> Path:
        return self.raiz_atlas / "operacion" / "mobile" / "envios"

    def recibir(self, *, envio_id: str, imagen: bytes, mime: str, metadata: Mapping[str, object]) -> tuple[dict, bool]:
        if not _ID_SEGURO.fullmatch(envio_id):
            raise ErrorEnvioMobile("envio_id inválido")
        if mime not in MIME_PERMITIDOS:
            raise ErrorEnvioMobile("tipo de imagen no permitido")
        if not imagen or len(imagen) > MAX_IMAGEN_BYTES:
            raise ErrorEnvioMobile("imagen vacía o demasiado grande")
        tipo = str(metadata.get("tipo_novedad", ""))
        if tipo not in TIPOS_NOVEDAD:
            raise ErrorEnvioMobile("tipo_novedad inválido")
        directorio = self.raiz / envio_id
        registro_path = directorio / "envio.json"
        with bloqueo_sesion(self.raiz, f"mobile_{envio_id}", tiempo_expiracion_segundos=300):
            if registro_path.is_file():
                return json.loads(registro_path.read_text(encoding="utf-8")), False
            directorio.mkdir(parents=True, exist_ok=True)
            extension = MIME_PERMITIDOS[mime]
            temporal = directorio / f".original{extension}.tmp"
            original = directorio / f"original{extension}"
            with temporal.open("xb") as archivo:
                archivo.write(imagen)
                archivo.flush()
                os.fsync(archivo.fileno())
            os.replace(temporal, original)
            registro = {
                "schema_version": 1, "envio_id": envio_id, "estado": "RECIBIDO",
                "foto_original": original.name, "imagen_mime": mime,
                "imagen_sha256": hashlib.sha256(imagen).hexdigest(),
                "recibido_en": datetime.now(timezone.utc).isoformat(),
                **dict(metadata), "resultado_asociacion": None, "error": "",
            }
            escribir_json_atomico(registro_path, registro)
            return registro, True

    def cargar(self, envio_id: str) -> dict:
        return json.loads((self.raiz / envio_id / "envio.json").read_text(encoding="utf-8"))

    def guardar(self, envio_id: str, registro: Mapping[str, object]) -> None:
        escribir_json_atomico(self.raiz / envio_id / "envio.json", dict(registro))

    def pendientes(self) -> list[dict]:
        salida = []
        if not self.raiz.is_dir():
            return salida
        for ruta in self.raiz.glob("*/envio.json"):
            try:
                registro = json.loads(ruta.read_text(encoding="utf-8"))
                if registro.get("estado") == "REQUIERE_REVISION":
                    salida.append(registro)
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(salida, key=lambda r: r.get("recibido_en", ""))


def asociar_documento(datos: Mapping[str, object], filas: list[dict[str, str]]) -> dict[str, object]:
    guia = str(datos.get("numero_guia", "")).strip()
    transporte = str(datos.get("numero_transporte", "")).strip()
    candidatas = [f for f in filas if guia not in ("", "No encontrado") and f.get("numero_guia") == guia]
    if not candidatas and transporte not in ("", "No encontrado"):
        candidatas = [f for f in filas if f.get("numero_transporte") == transporte]
    transportes = sorted({f.get("numero_transporte", "") for f in candidatas if f.get("numero_transporte")})
    if len(transportes) == 1:
        return {"estado": "ASOCIADO_AUTOMATICAMENTE", "numero_transporte": transportes[0], "numero_guia": guia, "candidatos": transportes, "motivo": "Coincidencia exacta determinista de guía/transporte."}
    return {
        "estado": "PROPUESTA_REQUIERE_REVISION" if transportes else "SIN_ASOCIACION",
        "numero_transporte": "", "numero_guia": guia, "candidatos": transportes,
        "motivo": "Múltiples transportes compatibles." if transportes else "Sin coincidencia inequívoca en la operación vigente.",
    }


def procesar_envio_mobile(
    repositorio: RepositorioEnviosMobile, envio_id: str, *,
    procesador: Callable[[Path], Mapping[str, object]] | None = None,
    dataset: Path | None = None,
) -> dict:
    registro = repositorio.cargar(envio_id)
    registro["estado"] = "PROCESANDO"
    repositorio.guardar(envio_id, registro)
    try:
        imagen = repositorio.raiz / envio_id / registro["foto_original"]
        datos = dict((procesador or procesar_archivo)(imagen))
        filas: list[dict[str, str]] = []
        if dataset and dataset.is_file():
            with dataset.open(encoding="utf-8-sig", newline="") as archivo:
                filas = list(csv.DictReader(archivo, delimiter=";"))
        datos, resumen_ia = escalar_resultado_ia_en_memoria(datos, filas)
        asociacion = asociar_documento(datos, filas)
        registro.update({
            "estado": "ASOCIADO" if asociacion["estado"] == "ASOCIADO_AUTOMATICAMENTE" else "REQUIERE_REVISION",
            "datos_ocr": datos, "resultado_asociacion": asociacion,
            "atlas_ia": resumen_ia,
            "procesado_en": datetime.now(timezone.utc).isoformat(), "error": "",
        })
    except Exception as error:
        registro.update({"estado": "ERROR", "error": f"{type(error).__name__}: {error}"})
    repositorio.guardar(envio_id, registro)
    return registro
