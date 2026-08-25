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
from atlas_core.decisiones_pendientes import generar_artefacto
from atlas_core.procesamiento_masivo import (
    COLUMNAS, _escribir_filas, escalar_resultado_ia_en_memoria, procesar_archivo,
)

ESTADOS = ("RECIBIDO", "PROCESANDO", "ASOCIADO", "REQUIERE_REVISION", "ERROR")
TIPOS_NOVEDAD = (
    "", "ESPERA_AUTORIZACION_ESTADIA", "TIENE_ESTADIA", "DEVOLUCION_TOTAL",
    "DEVOLUCION_PARCIAL", "DOBLE_VUELTA",
)
MIME_PERMITIDOS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
# Bloque MOBILE ENVÍO REAL (fix puntual, 2do round): evidencia real (log
# de diagnóstico) confirmó que el 400 real del iPhone era por tamaño, no
# por MIME -- una foto HEIC de alta resolución (iPhone moderno) supera
# fácilmente los 15 MiB que tenía este límite. Sube a 28 MiB (mismo
# espíritu que servidor_mobile.MAX_PAYLOAD_BYTES=30 MiB, con margen para
# el resto del multipart). El celular además ahora recomprime/
# redimensiona antes de subir (ver Atlas-Conductores-Mobile/src/camera.js).
MAX_IMAGEN_BYTES = 28 * 1024 * 1024
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
    # Bloque GUÍAS MÓVILES V1 (Sección 9): si ya existe una fila con el
    # MISMO número de guía en el dataset, este documento ya está
    # representado -- nunca se le agrega una fila nueva (evita duplicar el
    # viaje si la misma foto llega por Mobile y luego se carga a mano en
    # Desktop). Reutiliza el mismo mecanismo de coincidencia por número de
    # guía que ya usa esta función, no una estrategia paralela.
    candidatas_por_guia = [f for f in filas if guia not in ("", "No encontrado") and f.get("numero_guia") == guia]
    candidatas = candidatas_por_guia
    if not candidatas and transporte not in ("", "No encontrado"):
        candidatas = [f for f in filas if f.get("numero_transporte") == transporte]
    transportes = sorted({f.get("numero_transporte", "") for f in candidatas if f.get("numero_transporte")})
    documento_ya_existe = bool(candidatas_por_guia)
    if len(transportes) == 1:
        return {"estado": "ASOCIADO_AUTOMATICAMENTE", "numero_transporte": transportes[0], "numero_guia": guia, "candidatos": transportes, "motivo": "Coincidencia exacta determinista de guía/transporte.", "documento_ya_existe": documento_ya_existe}
    return {
        "estado": "PROPUESTA_REQUIERE_REVISION" if transportes else "SIN_ASOCIACION",
        "numero_transporte": "", "numero_guia": guia, "candidatos": transportes,
        "motivo": "Múltiples transportes compatibles." if transportes else "Sin coincidencia inequívoca en la operación vigente.",
        "documento_ya_existe": documento_ya_existe,
    }


def _captura_ilegible(datos: Mapping[str, object]) -> bool:
    """Sección 10: una foto borrosa/cortada/ilegible no debe confundirse
    con una Incidencia Documental (dato humano erróneo). Reutiliza los dos
    campos ancla que ya extrae el Core (`numero_guia`/`numero_transporte`)
    -- si el OCR no pudo leer NINGUNO de los dos, es un problema de
    captura, no de contenido. No inventa un motor de calidad de imagen
    nuevo."""
    guia = str(datos.get("numero_guia", "")).strip()
    transporte = str(datos.get("numero_transporte", "")).strip()
    return guia in ("", "No encontrado") and transporte in ("", "No encontrado")


def procesar_envio_mobile(
    repositorio: RepositorioEnviosMobile, envio_id: str, *,
    procesador: Callable[[Path], Mapping[str, object]] | None = None,
    dataset: Path | None = None,
    carpeta_catalogos: str | Path | None = None,
    orquestador_ia: object = None,
) -> dict:
    """Procesa un envío Mobile reutilizando el MISMO Core que Desktop.

    Bloque GUÍAS MÓVILES V1 (Sección 2): OCR, catálogos, decisiones y B1
    son exactamente `procesar_archivo`/`escalar_resultado_ia_en_memoria`
    -- las mismas funciones que ya usa el lote de Desktop
    (`procesar_carpeta`). La única diferencia con Desktop es de
    orquestación: aquí se procesa un solo archivo a la vez (llega uno por
    vez desde el teléfono) en vez de una carpeta completa.
    """
    registro = repositorio.cargar(envio_id)
    registro["estado"] = "PROCESANDO"
    repositorio.guardar(envio_id, registro)
    try:
        imagen = repositorio.raiz / envio_id / registro["foto_original"]
        identificador = f"mobile/{envio_id}/{registro['foto_original']}"
        decisiones_nuevas: list[dict[str, object]] = []
        if procesador is not None:
            datos = dict(procesador(imagen))
        else:
            argumentos: dict[str, object] = {}
            if carpeta_catalogos is not None:
                argumentos["carpeta_catalogos"] = carpeta_catalogos
                argumentos["recolector_decisiones"] = decisiones_nuevas.extend
            datos = dict(procesar_archivo(imagen, **argumentos))

        filas: list[dict[str, str]] = []
        encabezado_compatible = True
        if dataset and dataset.is_file():
            with dataset.open(encoding="utf-8-sig", newline="") as archivo:
                lector = csv.DictReader(archivo, delimiter=";")
                filas = list(lector)
                if lector.fieldnames and list(lector.fieldnames) != COLUMNAS:
                    # Dataset de esquema reducido (p. ej. fixtures de
                    # prueba): se sigue usando para la asociación por
                    # guía/transporte, pero nunca se le escribe una fila
                    # con el esquema completo encima.
                    encabezado_compatible = False

        datos, resumen_ia = escalar_resultado_ia_en_memoria(
            datos, filas, orquestador_ia=orquestador_ia, carpeta_catalogos=carpeta_catalogos,
        )
        asociacion = asociar_documento(datos, filas)
        captura_ilegible = _captura_ilegible(datos)

        archivo_dataset = ""
        if (
            dataset and encabezado_compatible and not captura_ilegible
            and not asociacion.get("documento_ya_existe")
            and identificador not in {f.get("archivo", "") for f in filas}
        ):
            # Sección 12: la guía se persiste en el MISMO dataset que usa
            # Desktop -- pasa a existir como fila real y puede aparecer en
            # Viajes sin que nadie tenga que reprocesarla a mano.
            fila = {columna: str(datos.get(columna, "")) for columna in COLUMNAS}
            fila.update(
                archivo=identificador,
                estado_procesamiento=str(datos.get("estado_procesamiento") or "OK"),
                error="",
            )
            _escribir_filas(dataset, [fila])
            archivo_dataset = identificador

        if dataset and dataset.is_file() and carpeta_catalogos is not None:
            # Sección 8: las decisiones que este documento haya generado
            # también deben quedar en la MISMA bandeja de Revisión de Atlas
            # que usa Desktop -- se fusionan con las que ya estuvieran
            # pendientes (nunca se pisan) y se reusa el mismo
            # deduplicador/ledger de `generar_artefacto` (nunca un segundo
            # camino de publicación para Mobile).
            previas: list[dict[str, object]] = []
            ruta_artefacto = Path(dataset).parent / "decisiones_pendientes.json"
            try:
                previas = list(json.loads(ruta_artefacto.read_text(encoding="utf-8")).get("decisiones", []))
            except (OSError, json.JSONDecodeError):
                pass
            generar_artefacto(
                ruta_dataset=dataset, carpeta_catalogos=carpeta_catalogos,
                decisiones=previas + decisiones_nuevas,
            )

        if captura_ilegible:
            estado_final = "REQUIERE_REVISION"
        elif asociacion["estado"] == "PROPUESTA_REQUIERE_REVISION":
            estado_final = "REQUIERE_REVISION"
        elif str(datos.get("indicador_revision", "")).strip().casefold() == "revisar":
            # Sección 7/11: el propio Core ya marcó esta guía para
            # revisión (regla existente, p. ej. chofer sin corroborar o
            # dato documental incoherente) -- Mobile no inventa una regla
            # especial, sólo respeta la señal que Desktop también respeta.
            estado_final = "REQUIERE_REVISION"
        else:
            estado_final = "ASOCIADO"

        registro.update({
            "estado": estado_final,
            "datos_ocr": datos, "resultado_asociacion": asociacion,
            "atlas_ia": resumen_ia,
            "problema_captura": captura_ilegible,
            "archivo_dataset": archivo_dataset,
            "procesado_en": datetime.now(timezone.utc).isoformat(), "error": "",
        })
    except Exception as error:
        registro.update({"estado": "ERROR", "error": f"{type(error).__name__}: {error}"})
    repositorio.guardar(envio_id, registro)
    return registro
