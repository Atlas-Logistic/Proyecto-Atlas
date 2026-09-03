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

from atlas_core.almacenamiento_portable import SesionOcupadaError, bloqueo_sesion, escribir_json_atomico
from atlas_core.decisiones_pendientes import (
    NOMBRE_LOCK_DECISIONES_PENDIENTES, _generar_artefacto_sin_lock, regenerar_decisiones_persistidas,
)
from atlas_core.gestor_viajes import transporte_valido
from atlas_core.ocr_provider import crear_proveedor_ocr
from atlas_core.procesamiento_masivo import (
    COLUMNAS, COLUMNAS_PRE_G1C, _escribir_filas, escalar_resultado_ia_en_memoria, procesar_archivo,
)

ESTADOS = (
    "RECIBIDO", "PROCESANDO", "ASOCIADO", "REQUIERE_REVISION", "ERROR",
    # Bloque REPROCESO PERSISTIDO IDEMPOTENTE -- ver
    # `ESTADO_DERIVADOS_PENDIENTES` más abajo: el dataset ya quedó con
    # los datos nuevos de un reproceso, pero decisiones/bandeja todavía
    # no -- nunca "ERROR" (el documento en sí está bien).
    "DATOS_REPROCESADOS_DERIVADOS_PENDIENTES",
)
TIPOS_NOVEDAD = (
    "", "ESPERA_AUTORIZACION_ESTADIA", "TIENE_ESTADIA", "DEVOLUCION_TOTAL",
    "DEVOLUCION_PARCIAL", "DOBLE_VUELTA",
)
# Bloque MOBILE V1 -- selector de planta de origen (COLINA/RENCA) en la
# app del chofer (ver Atlas-Conductores-Mobile/src/sync-core.js,
# PLANTAS_ORIGEN_VALIDAS -- mismos dos códigos, nunca texto libre).
# Igual que `TIPOS_NOVEDAD`, esto es la validación de CONTRATO
# (¿el dato que llegó es uno de los válidos?) -- nunca decide identidad
# operacional por sí sola. La planta que el chofer informa es evidencia
# operacional, NO verdad absoluta (Sección 6 del bloque): se persiste
# en el envío tal cual, nunca sobrescribe `planta_origen_id`/
# `planta_origen_nombre` del dataset (esos siguen viniendo del
# pipeline determinista ya existente -- GPS/documento, ver
# `atlas_core.procesamiento_masivo`/`rutas.origen_documental`). Cruzar
# ambas fuentes y resolver contradicciones queda para un bloque
# posterior, no para este.
PLANTAS_ORIGEN_MOBILE = ("AZA_COLINA", "AZA_RENCA")
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
        # Bloque MOBILE V1 -- a diferencia de tipo_novedad (donde "" es
        # una respuesta válida, "ninguna aplica"), la planta de origen es
        # obligatoria: la propia app ya bloquea el envío sin ella (ver
        # Sección 9 del bloque), y Core nunca confía sólo en esa
        # validación del cliente.
        planta = str(metadata.get("planta_origen_informada", ""))
        if planta not in PLANTAS_ORIGEN_MOBILE:
            raise ErrorEnvioMobile("planta_origen_informada inválida")
        directorio = self.raiz / envio_id
        registro_path = directorio / "envio.json"
        # Bloque CONSISTENCIA OPERACIONAL -- fast path SIN lock: un
        # reintento de red (mismo `envio_id`, ya aceptado -- exactamente
        # lo que hace `sync-core.js` ante un timeout) es el caso COMÚN, y
        # nunca debe contender por `mobile_<envio_id>` con
        # `procesar_envio_mobile`/`reprocesar_envio_mobile_persistido`
        # (que sostienen ese mismo lock toda su duración) ni con las
        # escrituras diagnósticas breves de `servidor_mobile.py` -- antes
        # de este fix, un reintento que llegaba mientras cualquiera de
        # esos tenía el lock tomado recibía `SesionOcupadaError` sin
        # capturar, cortando la conexión HTTP del cliente (caso real:
        # E2E con Mobile real). Sólo la creación de un envío
        # VERDADERAMENTE nuevo necesita el lock -- para excluir dos
        # primeras subidas simultáneas del mismo `envio_id` entre sí.
        if registro_path.is_file():
            return json.loads(registro_path.read_text(encoding="utf-8")), False
        with bloqueo_sesion(self.raiz, f"mobile_{envio_id}", tiempo_expiracion_segundos=300):
            # Revalida DENTRO del lock -- la única carrera real que esto
            # protege es dos creaciones simultáneas del mismo envío.
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

    def historial(self) -> list[dict]:
        """Bloque UNIVERSAL V1 -- TODOS los envíos, cualquier estado
        (mismo criterio de lectura que ya usa `main.js`,
        `atlas:cargar-envios-mobile-historial` -- registro tal cual,
        sin decodificar la foto, que Motor nunca necesita). Read-only,
        base para el dominio EVENTOS (`eventos_operacionales.py`): un
        envío inválido/corrupto se omite, nunca rompe la consulta."""
        salida = []
        if not self.raiz.is_dir():
            return salida
        for ruta in self.raiz.glob("*/envio.json"):
            try:
                salida.append(json.loads(ruta.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(salida, key=lambda r: r.get("recibido_en", ""))


def asociar_documento(datos: Mapping[str, object], filas: list[dict[str, str]]) -> dict[str, object]:
    """Distingue tres conceptos que ANTES de Asociación Mobile V2 se
    confundían bajo un solo resultado/etiqueta (caso real 472593, guía y
    transporte OCR limpios que terminaban en SIN_ASOCIACION):

    1. Transporte LEÍDO por OCR (`datos.get("numero_transporte")`, dato
       crudo -- puede no existir/ser dudoso).
    2. Transporte que EXISTE en la operación vigente (hay OTRA fila en
       `filas` -- otro documento, de este mismo envío o de cualquier
       otro -- con el mismo transporte o la misma guía).
    3. Documento ASOCIADO inequívocamente (`ASOCIADO_AUTOMATICAMENTE`,
       lo único que Desktop debe rotular "Transporte asociado").

    Sección 13.2 del bloque, explícita: transporte leído + NINGUNA
    coincidencia todavía en la operación vigente → nunca inventar una
    asociación sólo porque el texto se lea limpio (eso sería "mismo
    texto → asociación ciega", prohibido en Sección 3). Ser el PRIMER
    documento conocido de un transporte es un estado legítimo, no un
    error -- se resuelve solo, sin intervención humana, en cuanto
    aparece un segundo documento con el mismo transporte (Multiguía,
    Sección 4) vía `revalidar_asociacion_mobile_sin_ocr` (Sección 7),
    nunca reescribiendo esta función para adivinar antes de tiempo.
    """
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
    if len(transportes) > 1:
        return {
            "estado": "PROPUESTA_REQUIERE_REVISION", "numero_transporte": "", "numero_guia": guia,
            "candidatos": transportes, "motivo": "Múltiples transportes compatibles.",
            "documento_ya_existe": documento_ya_existe,
        }

    # Bloque ASOCIACIÓN MOBILE V2 -- el motivo anterior ("Sin coincidencia
    # INEQUÍVOCA en la operación vigente") mezclaba dos situaciones muy
    # distintas bajo el mismo texto: cero coincidencias (este bloque) y
    # varias coincidencias contradictorias (el `if len(transportes) > 1`
    # de arriba) -- literalmente decía lo contrario de lo que pasaba (no
    # hubo NINGUNA coincidencia, ni ambigua ni clara). `transporte_valido`
    # es el MISMO criterio (sólo dígitos, presente) que ya usa
    # `gestor_viajes.agrupar_viajes` para decidir si un transporte es
    # agrupable -- se reutiliza para distinguir, dentro de SIN_ASOCIACION,
    # bucket A (TRANSPORTE_NO_LEIDO) de bucket B (TRANSPORTE_LEIDO_SIN_
    # COINCIDENCIA, Sección 2) -- nunca se inventa un estado nuevo
    # (Sección 2: "no crear estados nuevos si los actuales ya
    # representan correctamente estas situaciones").
    if transporte_valido(transporte):
        motivo = "Transporte leído, pero todavía sin ninguna otra coincidencia en la operación vigente."
    elif transporte:
        motivo = "El número de transporte leído no tiene un formato confiable para asociar."
    else:
        motivo = "El documento no informa número de transporte."
    return {
        "estado": "SIN_ASOCIACION", "numero_transporte": "", "numero_guia": guia, "candidatos": [],
        "motivo": motivo, "documento_ya_existe": documento_ya_existe,
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


def _estado_final_mobile(datos: Mapping[str, object], asociacion: Mapping[str, object], captura_ilegible: bool) -> str:
    """Deriva el `estado` final del envío a partir de la asociación y de
    las mismas señales documentales que ya respeta Desktop. Extraída de
    `procesar_envio_mobile` (Asociación Mobile V2) para que
    `revalidar_asociacion_mobile_sin_ocr` pueda recalcular el estado tras
    una reevaluación sin duplicar esta decisión en dos lugares."""
    if captura_ilegible:
        return "REQUIERE_REVISION"
    if asociacion["estado"] == "PROPUESTA_REQUIERE_REVISION":
        return "REQUIERE_REVISION"
    if str(datos.get("indicador_revision", "")).strip().casefold() == "revisar":
        # Sección 7/11: el propio Core ya marcó esta guía para revisión
        # (regla existente, p. ej. chofer sin corroborar o dato
        # documental incoherente) -- Mobile no inventa una regla
        # especial, sólo respeta la señal que Desktop también respeta.
        return "REQUIERE_REVISION"
    return "ASOCIADO"


# Bloque CONSISTENCIA OPERACIONAL -- lock por envío (misma convención de
# nombre que ya usa `RepositorioEnviosMobile.recibir`, ver más abajo):
# 30 min de expiración -- generoso para OCR/B1/red, pero sin dejar un
# proceso muerto bloqueando reintentos por 6 horas (el default de
# `bloqueo_sesion`).
TIEMPO_EXPIRACION_LOCK_ENVIO_SEGUNDOS = 1800


def procesar_envio_mobile(
    repositorio: RepositorioEnviosMobile, envio_id: str, *,
    procesador: Callable[[Path], Mapping[str, object]] | None = None,
    dataset: Path | None = None,
    carpeta_catalogos: str | Path | None = None,
    orquestador_ia: object = None,
) -> dict:
    """Wrapper PROTEGIDO de `_procesar_envio_mobile_impl` -- adquiere el
    lock POR ENVÍO (`mobile_<envio_id>`) para TODA la operación, incluido
    el OCR/B1/red (Sección "Lock por envío", Bloque CONSISTENCIA
    OPERACIONAL): a diferencia del lock del dataset (alta contención,
    liberado en ventanas breves), este lock es de bajísima contención
    -- sólo compite con OTRA operación sobre ese MISMO envío exacto
    (`reprocesar_envio_mobile_persistido`, `revalidar_asociacion_mobile_
    sin_ocr`) -- así que sostenerlo toda la llamada es simple y correcto:
    dos operaciones sobre el MISMO envío nunca se pisan; envíos distintos
    corren en paralelo sin ninguna contención entre sí (lock distinto por
    `envio_id`)."""
    with bloqueo_sesion(
        repositorio.raiz, f"mobile_{envio_id}",
        tiempo_expiracion_segundos=TIEMPO_EXPIRACION_LOCK_ENVIO_SEGUNDOS,
    ):
        return _procesar_envio_mobile_impl(
            repositorio, envio_id, procesador=procesador, dataset=dataset,
            carpeta_catalogos=carpeta_catalogos, orquestador_ia=orquestador_ia,
        )


def _procesar_envio_mobile_impl(
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

    Implementación real -- sólo se llama desde el wrapper protegido de
    arriba (`procesar_envio_mobile`), que ya sostiene el lock por envío;
    nunca directamente (evita readquirir un lock no reentrante)."""
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
            argumentos["proveedor"] = crear_proveedor_ocr()
            if carpeta_catalogos is not None:
                argumentos["carpeta_catalogos"] = carpeta_catalogos
                argumentos["recolector_decisiones"] = decisiones_nuevas.extend
            # Bloque ORIGEN OPERACIONAL V2 -- la planta que el chofer
            # informó al capturar (Sección 6 de Mobile V1: "evidencia
            # operacional, NO verdad absoluta") ahora SÍ llega al motor de
            # evidencia de origen, para que se fusione con el encabezado
            # documental y la regla de compatibilidad -- ver
            # `atlas_core.rutas.origen_evidencia`. Antes de este bloque
            # nunca se pasaba, así que el encabezado societario siempre
            # ganaba por defecto (causa raíz real del caso 472593).
            planta_informada = str(registro.get("planta_origen_informada", "")).strip()
            if planta_informada:
                argumentos["planta_origen_informada"] = planta_informada
            datos = dict(procesar_archivo(imagen, **argumentos))

        filas: list[dict[str, str]] = []
        encabezado_compatible = True
        # Bloque G1-C -- `COLUMNAS` ganó codigo_pais/codigo_unidad/
        # codigo_contexto; el dataset real todavía no las tiene
        # (`COLUMNAS_PRE_G1C`, sin migración masiva). `_escribir_filas`
        # (más abajo) sólo AGREGA (modo "a", nunca reescribe el
        # encabezado ya en disco) -- si se le dejara escribir directo
        # sobre un archivo con el encabezado viejo, las filas nuevas
        # quedarían con más columnas que el encabezado, corrompiendo el
        # CSV. Se detecta ese caso concreto (nunca cualquier esquema
        # reducido -- eso sigue siendo incompatible de verdad, ver abajo)
        # para forzar una reescritura completa UNA sola vez, en vez de un
        # append a ciegas.
        requiere_migracion_g1c = False
        if dataset and dataset.is_file():
            with dataset.open(encoding="utf-8-sig", newline="") as archivo:
                lector = csv.DictReader(archivo, delimiter=";")
                filas = list(lector)
                encabezado_actual = list(lector.fieldnames or [])
                if encabezado_actual == COLUMNAS_PRE_G1C:
                    requiere_migracion_g1c = True
                elif encabezado_actual and encabezado_actual != COLUMNAS:
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
            # Bloque CONSISTENCIA OPERACIONAL -- el chequeo de duplicado
            # (`filas`, leído ANTES del OCR, arriba) puede haber quedado
            # obsoleto mientras corría el OCR: se revalida por segunda vez
            # contra una lectura FRESCA, ya bajo el lock común del
            # dataset -- nunca un append a ciegas, y el mismo lock excluye
            # cualquier reemplazo completo concurrente (revalidación,
            # reproceso, aplicación de decisión) mientras se agrega esta
            # fila.
            with bloqueo_sesion(dataset.parent, NOMBRE_LOCK_DATASET_OPERACIONAL):
                filas_frescas: list[dict[str, str]] = []
                encabezado_fresco: list[str] = []
                if dataset.is_file():
                    with dataset.open(encoding="utf-8-sig", newline="") as archivo_csv:
                        lector_fresco = csv.DictReader(archivo_csv, delimiter=";")
                        filas_frescas = list(lector_fresco)
                        encabezado_fresco = list(lector_fresco.fieldnames or [])
                if identificador not in {f.get("archivo", "") for f in filas_frescas}:
                    if encabezado_fresco == COLUMNAS_PRE_G1C:
                        # Bloque G1-C -- primer escritor real que toca este
                        # dataset desde que `COLUMNAS` creció: reescritura
                        # completa UNA vez (mismo escritor atómico que ya
                        # usan las revalidaciones `_sin_ocr`), nunca un
                        # append a ciegas sobre un encabezado más corto que
                        # las filas que va a escribir. Filas viejas quedan
                        # con codigo_pais/codigo_unidad/codigo_contexto=""
                        # -- nunca se inventa un valor real para ellas.
                        from atlas_core.revalidacion_documental import _escribir_filas_completas
                        _escribir_filas_completas(dataset, filas_frescas + [fila])
                    else:
                        _escribir_filas(dataset, [fila])
                    archivo_dataset = identificador

        if carpeta_catalogos is not None:
            # Bloque M2-D -- paridad real con Desktop: `analizar_guias_
            # masivo.py` (lote) invoca `detectar_decision_origen_no_
            # confirmado` para cada documento; este camino (un envío
            # Mobile a la vez) nunca lo hacía -- una contradicción/
            # ambigüedad real de origen producida desde Mobile (caso
            # real 472624) podía quedar invisible en Revisión de Atlas
            # para siempre, sin que ningún mecanismo la volviera a
            # detectar. El propio detector ya se abstiene solo (`None`)
            # cuando el origen quedó inequívocamente resuelto -- nunca
            # fabrica una pregunta redundante.
            from atlas_core.catalogo_plantas import CatalogoPlantas
            from atlas_core.decisiones_pendientes import detectar_decision_origen_no_confirmado

            try:
                plantas_catalogo = CatalogoPlantas(Path(carpeta_catalogos) / "plantas.json").listar()
            except (OSError, ValueError):
                plantas_catalogo = []
            decision_origen = detectar_decision_origen_no_confirmado(
                archivo=str(datos.get("archivo") or identificador), fila=datos, plantas=plantas_catalogo,
            )
            if decision_origen is not None:
                decisiones_nuevas.append(decision_origen)

        if dataset and dataset.is_file() and carpeta_catalogos is not None:
            # Sección 8: las decisiones que este documento haya generado
            # también deben quedar en la MISMA bandeja de Revisión de Atlas
            # que usa Desktop -- se fusionan con las que ya estuvieran
            # pendientes (nunca se pisan) y se reusa el mismo
            # deduplicador/ledger de `generar_artefacto` (nunca un segundo
            # camino de publicación para Mobile).
            #
            # Bloque CONSISTENCIA OPERACIONAL -- la secuencia completa
            # (leer bandeja FRESCA -> fusionar -> deduplicar -> publicar)
            # corre bajo `NOMBRE_LOCK_DECISIONES_PENDIENTES`: leer
            # `previas` ANTES de adquirir el lock dejaría la fusión igual
            # de racy que no tener lock -- dos publicaciones concurrentes
            # fusionarían cada una contra una foto vieja y la última en
            # escribir pisaría las decisiones que la otra acababa de
            # agregar. `_generar_artefacto_sin_lock` (nunca el wrapper
            # protegido `generar_artefacto`, que reintentaría adquirir
            # este mismo lock no reentrante) hace la escritura final,
            # todavía dentro de la misma sección crítica.
            ruta_artefacto = Path(dataset).parent / "decisiones_pendientes.json"
            with bloqueo_sesion(ruta_artefacto.parent, NOMBRE_LOCK_DECISIONES_PENDIENTES):
                previas: list[dict[str, object]] = []
                try:
                    previas = list(json.loads(ruta_artefacto.read_text(encoding="utf-8")).get("decisiones", []))
                except (OSError, json.JSONDecodeError):
                    pass
                decisiones_reconciliadas = regenerar_decisiones_persistidas(
                    decisiones=previas + decisiones_nuevas,
                    carpeta_catalogos=carpeta_catalogos,
                    ruta_dataset=dataset,
                )
                _generar_artefacto_sin_lock(
                    ruta_dataset=dataset, carpeta_catalogos=carpeta_catalogos,
                    decisiones=decisiones_reconciliadas, ruta_salida=ruta_artefacto,
                )

        estado_final = _estado_final_mobile(datos, asociacion, captura_ilegible)

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


# Bloque REPROCESO PERSISTIDO IDEMPOTENTE -- causa raíz real (472624):
# `procesar_envio_mobile` es deliberadamente APPEND-ONLY (Sección 12 de
# ese bloque) -- si el `identificador` ya existe en el dataset, nunca
# vuelve a escribir la fila, exactamente lo que evita duplicar un
# documento ya procesado. Pero eso también significa que, hasta este
# bloque, un fix real de extracción/OCR (Motor corregido) nunca podía
# llegar a la fila YA PERSISTIDA de un documento -- quedaba mostrando el
# estado viejo para siempre, sin ningún mecanismo canónico para
# reflejar la corrección. Este es exactamente el modo COMPLEMENTARIO
# (reemplazo explícito, nunca append) que faltaba -- reutiliza el MISMO
# pipeline OCR/extracción/asociación que `procesar_envio_mobile`, nunca
# un segundo camino.
#
# Fases explícitas (Hallazgo Codex -- diagnóstico de hasta dónde llegó
# un reproceso, aun sin transacción distribuida completa): cada una se
# persiste en `registro["reproceso_persistido"]` a medida que se
# alcanza, así que una interrupción entre fases deja rastro recuperable
# de exactamente qué se alcanzó a hacer.
FASE_PREPARADO = "PREPARADO"
FASE_PROCESADO_EN_MEMORIA = "PROCESADO_EN_MEMORIA"
FASE_DATASET_REEMPLAZADO = "DATASET_REEMPLAZADO"
FASE_DERIVADOS_REGENERADOS = "DERIVADOS_REGENERADOS"
FASE_COMPLETADO = "COMPLETADO"
# Estado del ENVÍO (`registro["estado"]`) cuando el dataset ya quedó con
# los datos nuevos pero los derivados (decisiones/bandeja) todavía no --
# nunca "ERROR": el documento en sí está bien: sólo falta que ESTE
# MISMO reproceso (reejecutado) o el reconciliador general
# (`revalidar_y_regenerar_reporte`, para el REPORTE/estado_operación --
# nunca para las decisiones de ESTE documento, ver más abajo) vuelvan a
# correr. Se agrega a `ESTADOS` -- ningún validador existente lo exigía
# antes (no hay una lista cerrada enforced), pero se documenta ahí
# igual, como el resto de los estados posibles.
ESTADO_DERIVADOS_PENDIENTES = "DATOS_REPROCESADOS_DERIVADOS_PENDIENTES"
# Bloque REPROCESO PERSISTIDO IDEMPOTENTE, Sección 4 (revisión Codex) --
# lock COMÚN por recurso, no uno propio por operación: `revalidacion_
# documental.py` YA usa exactamente este nombre (`bloqueo_sesion(ruta.
# parent, "revalidacion_dataset")`) en las 23 revalidaciones `_sin_ocr`
# que hacen lectura+modificación+reemplazo del MISMO
# `analisis_completo_guias.csv` -- reutilizado tal cual (nunca un lock
# nuevo) para que este reproceso quede mutuamente excluido con TODAS
# ellas, alcanzables tanto desde `revalidar_y_regenerar_reporte`
# (servidor_mobile.py, `reconciliar_estado_derivado.py`) como desde las
# llamadas que `aplicar_decision_obra` hace a esas mismas revalidaciones
# Y (ronda 6, microcorrección) desde sus propias 3 escrituras directas,
# que ahora TAMBIÉN adquieren este mismo lock -- ver el docstring de
# `reprocesar_envio_mobile_persistido` y `aplicacion_decisiones.py`.
#
# GAP CERRADO (ronda 6, microcorrección -- antes documentado como
# pendiente): `aplicacion_decisiones.aplicar_decision_obra` hacía 3
# escrituras DIRECTAS de fila (fuera de las revalidaciones `_sin_ocr`)
# bajo ÚNICAMENTE su propio lock ("aplicar_decision_obra") -- ahora
# TAMBIÉN adquiere "revalidacion_dataset" alrededor de cada una de esas
# 3 ventanas de lectura+modificación+reemplazo (liberándolo ANTES de
# llamar a los revalidadores `_sin_ocr` que ella misma invoca -- lock de
# archivo NO reentrante), sin tocar su lock EXTERIOR
# ("aplicar_decision_obra", que sigue protegiendo la transacción lógica
# completa de la feature, siempre por FUERA). GAP RESIDUAL, todavía
# documentado a propósito (evaluado, no corregido -- fuera del alcance
# de "reproceso persistido Mobile"): `reconciliar_estado_derivado`
# envuelve su respaldo/manifest en OTRO lock más
# ("reconciliacion_estado_derivado"), aunque sus escrituras de fila
# reales SÍ pasan por "revalidacion_dataset" igual que todos -- unificar
# ese tercer nombre también sería más consistente, pero no protege
# ninguna escritura directa desprotegida (a diferencia del gap que sí se
# cerró arriba), así que no era bloqueante.
NOMBRE_LOCK_DATASET_OPERACIONAL = "revalidacion_dataset"
# Journal separado del recurso cuyo guardado puede fallar (envio.json,
# Sección 2): un archivo propio, chico, junto al dataset -- vive DENTRO
# del mismo directorio que ya protege `NOMBRE_LOCK_DATASET_OPERACIONAL`.
# Guarda, por `identificador`, exactamente lo que un reproceso ya
# calculó (OCR/B1/asociación/decisiones nuevas) en el momento en que el
# dataset quedó reemplazado -- sobrevive aunque el guardado de
# `envio.json` que sigue falle, y permite que una reejecución posterior
# complete lo que falta SIN repetir OCR ni duplicar decisiones. Se borra
# la entrada de un `identificador` en cuanto ese reproceso completa
# TODAS sus fases -- nunca crece sin límite.
NOMBRE_JOURNAL_REPROCESO_PERSISTIDO = ".reproceso_persistido_journal.json"


def _ruta_journal_reproceso(dataset: Path) -> Path:
    return dataset.parent / NOMBRE_JOURNAL_REPROCESO_PERSISTIDO


def _leer_journal_reproceso(dataset: Path) -> dict[str, dict[str, object]]:
    try:
        contenido = json.loads(_ruta_journal_reproceso(dataset).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return contenido if isinstance(contenido, dict) else {}


def _escribir_entrada_journal_reproceso_sin_lock(
    dataset: Path, identificador: str, entrada: dict[str, object] | None,
) -> None:
    """`entrada=None` retira la entrada -- el reproceso de ese
    identificador ya completó todas sus fases, nada que reanudar.

    Microcorrección (Codex, ronda 7) -- variante "_sin_lock": lectura +
    modificación + reemplazo del journal COMPLETO, SIN adquirir ningún
    lock por su cuenta. Existe para el ÚNICO caller que ya sostiene
    `NOMBRE_LOCK_DATASET_OPERACIONAL` al llamarla (la escritura de la
    entrada nueva dentro de la fase DATASET_REEMPLAZADO, más abajo) --
    reutilizar el wrapper protegido ahí adentro reintentaría adquirir un
    lock de archivo NO reentrante que el propio caller ya tiene tomado,
    fallando en seco (`SesionOcupadaError` contra sí mismo). Cualquier
    otro caller debe usar `_escribir_entrada_journal_reproceso` (el
    wrapper protegido, abajo) -- nunca esta función directamente."""
    journal = _leer_journal_reproceso(dataset)
    if entrada is None:
        journal.pop(identificador, None)
    else:
        journal[identificador] = entrada
    escribir_json_atomico(_ruta_journal_reproceso(dataset), journal)


def _escribir_entrada_journal_reproceso(
    dataset: Path, identificador: str, entrada: dict[str, object] | None,
) -> None:
    """Wrapper PROTEGIDO de `_escribir_entrada_journal_reproceso_sin_lock`
    -- para todo caller que NO sostenga ya el lock común del dataset.

    Microcorrección (Codex, ronda 7 -- bloqueante): el journal es un
    archivo propio con su PROPIO patrón read-modify-write (lee el dict
    completo, modifica UNA clave, reescribe el dict completo) -- antes
    de esta corrección, sólo la escritura de la entrada NUEVA (dentro de
    la fase DATASET_REEMPLAZADO) corría bajo lock; las otras 3
    mutaciones (limpieza short-circuit cuando `envio.json` ya está
    COMPLETADO, limpieza de una entrada huérfana tras un fallo, y la
    limpieza final tras COMPLETADO) escribían el journal SIN ningún
    lock. Eso permitía exactamente la pérdida de actualización que
    reportó Codex: reproceso A lee el journal para borrar su propia
    entrada, reproceso B agrega/actualiza la SUYA mientras tanto, A
    escribe de vuelta su copia (ya obsoleta, sin la entrada de B) --
    la entrada de B desaparece en silencio. Ahora las 4 mutaciones usan
    el MISMO lock común (`NOMBRE_LOCK_DATASET_OPERACIONAL`,
    "revalidacion_dataset") que ya protege el dataset -- nunca un lock
    nuevo -- así que dos mutaciones concurrentes del journal (vengan de
    donde vengan) quedan serializadas exactamente igual que dos
    escrituras concurrentes del dataset: la segunda se entera con
    `SesionOcupadaError`, nunca pisa ni pierde en silencio la de la
    primera."""
    with bloqueo_sesion(dataset.parent, NOMBRE_LOCK_DATASET_OPERACIONAL):
        _escribir_entrada_journal_reproceso_sin_lock(dataset, identificador, entrada)


def _hash_fila(fila: dict[str, str]) -> str:
    return hashlib.sha256(repr(fila).encode("utf-8")).hexdigest()


def _diagnostico_reproceso_persistido(
    *, fase: str, estado: str, error: Exception | None = None,
) -> dict[str, object]:
    diagnostico: dict[str, object] = {
        "fase": fase, "estado": estado,
        "intentado_en": datetime.now(timezone.utc).isoformat(),
    }
    if error is not None:
        diagnostico["error"] = f"{type(error).__name__}: {error}"
    return diagnostico


def reprocesar_envio_mobile_persistido(
    repositorio: RepositorioEnviosMobile, envio_id: str, *,
    dataset: Path, carpeta_catalogos: str | Path | None = None,
    orquestador_ia: object = None,
) -> dict:
    """Wrapper PROTEGIDO de `_reprocesar_envio_mobile_persistido_impl` --
    adquiere el lock POR ENVÍO (`mobile_<envio_id>`, misma convención que
    `procesar_envio_mobile`/`RepositorioEnviosMobile.recibir`) para TODA
    la llamada, incluidas fases OCR/B1 -- Bloque CONSISTENCIA
    OPERACIONAL: dos reprocesos del MISMO envío (o un reproceso y un
    `procesar_envio_mobile`/`revalidar_asociacion_mobile_sin_ocr` sobre
    ese mismo envío) quedan serializados estructuralmente por este lock,
    ANTES incluso de llegar al dataset -- el segundo intento recibe
    `SesionOcupadaError` de inmediato (tratado como cualquier otro fallo
    en fase PREPARADO: nunca toca nada). Reprocesos de envíos DISTINTOS
    usan locks distintos (`envio_id` distinto) -- corren en paralelo sin
    ninguna contención entre sí."""
    with bloqueo_sesion(
        repositorio.raiz, f"mobile_{envio_id}",
        tiempo_expiracion_segundos=TIEMPO_EXPIRACION_LOCK_ENVIO_SEGUNDOS,
    ):
        return _reprocesar_envio_mobile_persistido_impl(
            repositorio, envio_id, dataset=dataset,
            carpeta_catalogos=carpeta_catalogos, orquestador_ia=orquestador_ia,
        )


def _reprocesar_envio_mobile_persistido_impl(
    repositorio: RepositorioEnviosMobile, envio_id: str, *,
    dataset: Path, carpeta_catalogos: str | Path | None = None,
    orquestador_ia: object = None,
) -> dict:
    """Implementación real -- sólo se llama desde el wrapper protegido de
    arriba, que ya sostiene el lock por envío; nunca directamente (evita
    readquirir un lock no reentrante).

    Reprocesa un envío Mobile YA PERSISTIDO y SUSTITUYE su propia fila
    existente en `dataset` -- nunca agrega, nunca decide entre varias.

    La fila se identifica EXCLUSIVAMENTE por el identificador
    persistente del documento (`archivo`, el mismo campo/valor que ya
    usa el guard anti-duplicado de `procesar_envio_mobile`):

    - Ninguna fila con ese `archivo`: se abstiene (`ErrorEnvioMobile`)
      ANTES de tocar nada -- ni siquiera actualiza el `estado` del
      envío. Nunca hace un append silencioso; para eso ya existe
      `procesar_envio_mobile`.
    - Más de una fila con ese `archivo`: aborta (`ErrorEnvioMobile`) --
      es una anomalía del dataset que este modo nunca decide por su
      cuenta cuál conservar.
    - Exactamente una: se reemplaza en el lugar, vía
      `_escribir_filas_completas` (el mismo reescritor atómico completo
      -- temp file + fsync + os.replace -- que ya usan todas las
      revalidaciones `_sin_ocr` de `revalidacion_documental`; nunca un
      segundo escritor de CSV). El número total de filas del dataset se
      preserva siempre.

    Bloque REPROCESO PERSISTIDO IDEMPOTENTE (Hallazgo Codex) -- un
    reproceso fallido NUNCA degrada un envío previamente válido:

    - Fallo ANTES de reemplazar el dataset (lectura del dataset, OCR/B1,
      asociación, o la validación de concurrencia justo antes de
      escribir): el envío se RESTAURA tal cual estaba (mismo
      `estado`/`datos_ocr`/`resultado_asociacion`/etc. capturados al
      inicio) -- nunca queda en `ERROR` genérico ni pierde datos válidos
      de un procesamiento anterior. El intento fallido se registra
      aparte, en `registro["reproceso_persistido"]`
      (`{fase, estado="FALLIDO", error, intentado_en}`), nunca mezclado
      con los campos que describen el documento en sí.
    - Fallo DESPUÉS de reemplazar el dataset (regenerar decisiones/
      artefacto): el reemplazo NUNCA se revierte -- el dataset y
      `datos_ocr`/`resultado_asociacion` del envío quedan con los datos
      NUEVOS del reproceso. `estado` pasa a `ESTADO_DERIVADOS_
      PENDIENTES` (nunca "ERROR" -- el documento está bien, sólo los
      derivados quedaron desactualizados), diagnosticable en
      `reproceso_persistido`.

    Bloque REPROCESO PERSISTIDO IDEMPOTENTE, 5ta ronda (Hallazgo Codex)
    -- journal separado del recurso que puede fallar:

    1) Ventana entre `os.replace` del dataset y el checkpoint de
       `envio.json`: NUNCA se promete atomicidad imposible entre dos
       archivos independientes -- en vez de eso, DENTRO del mismo lock,
       se escribe PRIMERO una entrada de journal
       (`NOMBRE_JOURNAL_REPROCESO_PERSISTIDO`, un archivo propio,
       escritura atómica aparte) con TODO lo que este reproceso ya
       calculó -- `datos_ocr`/`resultado_asociacion`/`decisiones_nuevas`/
       la huella de la fila que está por escribirse -- y SÓLO DESPUÉS se
       reemplaza el dataset (Microcorrección, ronda 6: antes era al
       revés). Si el proceso se interrumpe justo ahí (o el guardado de
       `envio.json` que sigue falla), al REEJECUTAR, la fase PREPARADO
       relee el dataset, ve que la fila YA tiene la huella que el
       journal registró, y SALTA directo a reconciliar `envio.json`
       (autosanando cualquier checkpoint atrasado) y a completar
       `DERIVADOS_REGENERADOS` -- nunca repite OCR, nunca degrada, nunca
       duplica. Ninguno de los dos escritores (journal, dataset) es
       atómico ENTRE SÍ -- cada uno SÍ lo es individualmente (temp file
       + fsync + os.replace / `escribir_json_atomico`), así que una
       excepción en cualquiera de los dos dejaría su propio archivo
       exactamente como estaba, nunca a medio escribir. Por eso el orden
       (journal primero) hace que un fallo del journal implique, con
       certeza, que el dataset TAMPOCO cambió -- pero el `except` que
       envuelve todo esto NUNCA confía ciegamente en ese orden: relee el
       dataset y compara la huella de la fila ya persistida contra la
       que este intento quería escribir (evidencia verificable del
       propio dataset) antes de decidir si el fallo fue "antes" o
       "después" del reemplazo real.
    2) Fallo AL GUARDAR `envio.json` justo después del reemplazo: queda
       en su propio `try/except` explícito -- si el dataset ya cambió
       (verificado por huella, no asumido), JAMÁS se trata como "fallo
       antes de reemplazo" ni se restaura `estado_previo` encima de los
       datos nuevos (el journal, ya escrito antes que el dataset, es la
       evidencia que sobrevive). Se relanza como `ErrorEnvioMobile` con
       el mensaje exacto de qué pasó y qué hacer (reintentar este mismo
       reproceso). Simétricamente, el checkpoint final de `COMPLETADO`
       se persiste ANTES de borrar la entrada del journal -- nunca al
       revés (Microcorrección, ronda 6): si esa persistencia fallara con
       el journal ya borrado, una reejecución no tendría cómo saber que
       ya se había completado y repetiría OCR/B1 sin necesidad. Con el
       orden correcto, si sólo la LIMPIEZA posterior del journal falla
       (best-effort, nunca crítico), una reejecución reconoce -- antes
       de tocar nada -- que `envio.json` YA muestra `COMPLETADO` para
       esa misma huella de fila, y se limita a reintentar la limpieza,
       sin reprocesar absolutamente nada.
    3) Decisiones nuevas después de un fallo de artefacto:
       `decisiones_nuevas` (incluida la de origen, `detectar_decision_
       origen_no_confirmado`) se calcula ANTES de reemplazar el dataset
       y se journaliza junto con lo demás -- una reejecución que
       reanuda desde el journal la vuelve a tener completa, sin
       recalcular nada y sin duplicar (el merge por `decision_id`
       determinista de `regenerar_decisiones_persistidas` ya es
       idempotente, incluso si la fase de derivados se reintenta más de
       una vez). Nunca se afirma que `revalidar_y_regenerar_reporte`
       reconstruye estas decisiones por sí solo -- ese reconciliador
       general reconstruye REPORTE/`estado_operación` a partir del
       dataset ya correcto, no las decisiones de un OCR que nunca llegó
       a persistirse en ningún lado más que este journal.

    Idempotente por diseño: sin cambios reales en el documento/Motor
    entre corridas, dos reprocesos producen la MISMA fila -- una
    segunda corrida no introduce ninguna diferencia nueva en el
    dataset ni en el ledger, y si la corrida anterior se quedó en
    `ESTADO_DERIVADOS_PENDIENTES` (con o sin journal) o incluso ya
    `COMPLETADO` con sólo la limpieza del journal pendiente, una
    reejecución completa exactamente lo que faltaba -- nunca más.

    Concurrencia (Sección 4, revisión Codex -- lock COMÚN por recurso,
    ronda 6: bloqueante, ya cerrado): la lectura + validación de
    coincidencia + reemplazo del dataset, Y el journal que se escribe
    junto, corren bajo `bloqueo_sesion` con
    `NOMBRE_LOCK_DATASET_OPERACIONAL` -- el MISMO nombre que ya usan las
    23 revalidaciones `_sin_ocr` de `revalidacion_documental.py` para
    esta misma operación (lectura+modificación+reemplazo del mismo
    `analisis_completo_guias.csv`), alcanzables desde
    `revalidar_y_regenerar_reporte` (servidor_mobile.py,
    `reconciliar_estado_derivado.py`) y, desde la ronda 6, TAMBIÉN desde
    las 3 escrituras DIRECTAS de `aplicar_decision_obra`
    (`aplicacion_decisiones.py`) -- que ahora adquieren este mismo lock
    común alrededor de cada una de sus 3 ventanas de
    lectura+modificación+reemplazo directo, liberándolo ANTES de llamar
    a los revalidadores `_sin_ocr` que ella misma invoca (que lo
    adquieren por su cuenta -- lock de archivo NO reentrante). Su lock
    EXTERIOR ("aplicar_decision_obra", una transacción lógica más amplia
    que sólo esa feature necesita) no cambió -- sigue siempre por FUERA;
    "revalidacion_dataset" siempre por DENTRO, en ventanas acotadas;
    ningún caller conocido adquiere ese orden al revés. `SesionOcupadaError`
    se trata igual que cualquier otro fallo antes del reemplazo (fase
    `DATASET_REEMPLAZADO`, el envío se restaura, verificado por huella
    igual que cualquier otro fallo de esa fase -- ver punto 1).

    Nunca conoce ninguna guía/cliente/envío concreto -- opera sobre
    CUALQUIER `envio_id` ya persistido que se le pida."""
    registro = repositorio.cargar(envio_id)
    identificador = f"mobile/{envio_id}/{registro['foto_original']}"

    # `bloqueo_sesion`/`escribir_json_atomico` ya se importan a nivel de
    # módulo arriba. `_escribir_filas_completas`/`_leer_filas` sí
    # requieren import perezoso -- evita un ciclo de import a nivel de
    # módulo (`revalidacion_documental` ya importa `RepositorioEnviosMobile`
    # de este mismo archivo).
    #
    # DEUDA MODERADA, documentada a propósito (Sección 6 -- evaluada, no
    # corregida en este bloque): importar un helper "privado" (guión
    # bajo) de otro módulo YA es un patrón existente en el codebase
    # (`aplicacion_decisiones.py` hace exactamente esto mismo). Moverlos
    # a un módulo de almacenamiento compartido (p. ej.
    # `almacenamiento_portable.py`, hoy sin ninguna dependencia interna
    # propia) no es un cambio chico: ambos validan contra `COLUMNAS`
    # (definido en `procesamiento_masivo.py`, con todo el árbol de
    # OCR/extracción detrás) -- moverlos ahí invertiría la arquitectura
    # (un módulo de almacenamiento genérico pasaría a depender del
    # pipeline de procesamiento completo). Se deja así, reusando el
    # patrón ya establecido, en vez de ampliar este diff con un
    # refactor de arquitectura no pedido.
    from atlas_core.revalidacion_documental import _escribir_filas_completas, _leer_filas

    def _validar_coincidencia_unica(filas: list[dict[str, str]]) -> int:
        coincidencias = [indice for indice, fila in enumerate(filas) if fila.get("archivo", "") == identificador]
        if not coincidencias:
            raise ErrorEnvioMobile(
                f"No existe ninguna fila con archivo={identificador!r} en el dataset -- "
                "este modo nunca agrega una fila nueva (usar procesar_envio_mobile para eso)."
            )
        if len(coincidencias) > 1:
            raise ErrorEnvioMobile(
                f"Existen {len(coincidencias)} filas con archivo={identificador!r} en el dataset -- "
                "anomalía preexistente; este modo nunca decide cuál reemplazar."
            )
        return coincidencias[0]

    # FASE PREPARADO -- validación previa, SIN lock (no hay nada que
    # proteger todavía: sólo lectura, y se vuelve a validar bajo lock
    # justo antes de escribir). Ante 0/2+ coincidencias se aborta ANTES
    # de tocar el envío -- ni `estado` ni ningún otro campo cambian, ni
    # siquiera se registra un diagnóstico de reproceso (esa es una
    # precondición inválida, no un intento fallido).
    try:
        filas = _leer_filas(dataset)
    except ValueError as error:
        raise ErrorEnvioMobile(f"El dataset tiene un esquema incompatible: {error}") from error
    indice_fila = _validar_coincidencia_unica(filas)
    # El resto del dataset (todas las filas MENOS la que se va a
    # reemplazar) es el mismo "historial" que vería un documento nuevo
    # -- asociación/B1 evalúan este documento contra sus HERMANOS reales
    # (p. ej. otra guía del mismo transporte), nunca contra su propia
    # fila anterior, que sería un autoemparejamiento sin evidencia real.
    otras_filas = [fila for indice, fila in enumerate(filas) if indice != indice_fila]
    hash_fila_actual = _hash_fila(filas[indice_fila])
    entrada_journal = _leer_journal_reproceso(dataset).get(identificador)
    reanudar_desde_journal = (
        isinstance(entrada_journal, dict) and entrada_journal.get("fila_hash") == hash_fila_actual
    )

    # Microcorrección (Codex, Problema B) -- si `envio.json` YA muestra
    # `COMPLETADO` para esta misma huella de fila (el checkpoint final SÍ
    # se persistió la vez anterior) pero el journal todavía tiene una
    # entrada vigente, lo único que pudo fallar fue la limpieza posterior
    # (best-effort, ver el final de la función) -- no hay absolutamente
    # nada que reprocesar: ni OCR, ni dataset, ni derivados. Se reintenta
    # ÚNICAMENTE esa limpieza y se retorna tal cual, sin tocar nada más.
    diagnostico_previo = registro.get("reproceso_persistido") or {}
    if (
        reanudar_desde_journal
        and diagnostico_previo.get("fase") == FASE_COMPLETADO
        and diagnostico_previo.get("estado") == "COMPLETADO"
    ):
        try:
            _escribir_entrada_journal_reproceso(dataset, identificador, None)
        except Exception:
            pass
        return registro

    # Captura del estado previo relevante -- si el reproceso falla antes
    # de reemplazar el dataset, se restaura EXACTAMENTE así, nunca
    # degradado a un "ERROR" que perdería lo que el envío ya tenía de
    # válido. Se captura DESPUÉS de una posible reconciliación por
    # journal (más abajo) para que, si el checkpoint de `envio.json`
    # venía atrasado respecto de un reemplazo previo ya exitoso, la
    # línea de base a restaurar sea la real -- nunca una más vieja que
    # el propio dataset.
    def _estado_previo_actual() -> dict[str, object]:
        return {
            campo: registro.get(campo) for campo in (
                "estado", "datos_ocr", "resultado_asociacion", "atlas_ia",
                "problema_captura", "archivo_dataset", "procesado_en", "error",
            )
        }

    if reanudar_desde_journal:
        # Hallazgo Codex #1/#3 -- el dataset YA refleja exactamente lo
        # que un intento anterior calculó (misma huella de fila); nunca
        # hace falta repetir OCR/B1/asociación ni recalcular
        # `decisiones_nuevas` -- se reutilizan tal cual desde el
        # journal, y `envio.json` se reconcilia ANTES de seguir (nunca
        # queda mostrando una fase más vieja que la realidad).
        datos = dict(entrada_journal["datos_ocr"])
        asociacion = dict(entrada_journal["resultado_asociacion"])
        resumen_ia = dict(entrada_journal["atlas_ia"])
        captura_ilegible = bool(entrada_journal["problema_captura"])
        decisiones_nuevas: list[dict[str, object]] = list(entrada_journal.get("decisiones_nuevas", []))
        registro.update({
            "datos_ocr": datos, "resultado_asociacion": asociacion,
            "atlas_ia": resumen_ia, "problema_captura": captura_ilegible,
            "archivo_dataset": identificador,
            "procesado_en": str(entrada_journal.get("reemplazado_en") or datetime.now(timezone.utc).isoformat()),
            "error": "",
        })
        registro["reproceso_persistido"] = _diagnostico_reproceso_persistido(
            fase=FASE_DATASET_REEMPLAZADO, estado="REANUDADO_DESDE_JOURNAL",
        )
        repositorio.guardar(envio_id, registro)
        estado_previo = _estado_previo_actual()
    else:
        estado_previo = _estado_previo_actual()
        registro["estado"] = "PROCESANDO"
        registro["reproceso_persistido"] = _diagnostico_reproceso_persistido(
            fase=FASE_PREPARADO, estado="EN_PROGRESO",
        )
        repositorio.guardar(envio_id, registro)

        # FASE PROCESADO_EN_MEMORIA -- OCR/B1/asociación, todavía sin
        # tocar el dataset. `decisiones_nuevas` se completa ACÁ (incluida
        # la de origen) para que el journal, más abajo, ya la tenga
        # entera (Hallazgo Codex #3). Un fallo acá se restaura tal cual
        # (Sección 1).
        try:
            imagen = repositorio.raiz / envio_id / registro["foto_original"]
            decisiones_nuevas = []
            argumentos: dict[str, object] = {"proveedor": crear_proveedor_ocr()}
            if carpeta_catalogos is not None:
                argumentos["carpeta_catalogos"] = carpeta_catalogos
                argumentos["recolector_decisiones"] = decisiones_nuevas.extend
            planta_informada = str(registro.get("planta_origen_informada", "")).strip()
            if planta_informada:
                argumentos["planta_origen_informada"] = planta_informada
            datos = dict(procesar_archivo(imagen, **argumentos))

            datos, resumen_ia = escalar_resultado_ia_en_memoria(
                datos, otras_filas, orquestador_ia=orquestador_ia, carpeta_catalogos=carpeta_catalogos,
            )
            asociacion = asociar_documento(datos, otras_filas)
            captura_ilegible = _captura_ilegible(datos)

            fila_reemplazo = {columna: str(datos.get(columna, "")) for columna in COLUMNAS}
            fila_reemplazo.update(
                archivo=identificador,
                estado_procesamiento=str(datos.get("estado_procesamiento") or "OK"),
                error="",
            )

            if carpeta_catalogos is not None:
                # Mismo bloque M2-D que `procesar_envio_mobile` -- se
                # calcula ACÁ (antes del reemplazo) para que quede
                # journalizado junto con el resto, no perdido si
                # `generar_artefacto` falla después.
                from atlas_core.catalogo_plantas import CatalogoPlantas
                from atlas_core.decisiones_pendientes import detectar_decision_origen_no_confirmado

                try:
                    plantas_catalogo = CatalogoPlantas(Path(carpeta_catalogos) / "plantas.json").listar()
                except (OSError, ValueError):
                    plantas_catalogo = []
                decision_origen = detectar_decision_origen_no_confirmado(
                    archivo=str(datos.get("archivo") or identificador), fila=datos, plantas=plantas_catalogo,
                )
                if decision_origen is not None:
                    decisiones_nuevas.append(decision_origen)
        except Exception as error:
            registro.update(estado_previo)
            registro["reproceso_persistido"] = _diagnostico_reproceso_persistido(
                fase=FASE_PROCESADO_EN_MEMORIA, estado="FALLIDO", error=error,
            )
            repositorio.guardar(envio_id, registro)
            return registro

        registro["reproceso_persistido"] = _diagnostico_reproceso_persistido(
            fase=FASE_PROCESADO_EN_MEMORIA, estado="EN_PROGRESO",
        )
        repositorio.guardar(envio_id, registro)

        # FASE DATASET_REEMPLAZADO -- lectura + validación de coincidencia
        # + reemplazo + journal, TODO bajo el mismo lock COMÚN (Sección
        # 4): se relee el dataset FRESCO (nunca la copia de la fase
        # PREPARADO, que puede haber quedado obsoleta si otro escritor
        # tocó el archivo mientras corría OCR/B1) y se revalida la
        # coincidencia única antes de escribir. Un fallo acá (incluida
        # `SesionOcupadaError` por contención real) TAMPOCO tocó el
        # dataset todavía -- se restaura igual que en la fase anterior.
        try:
            with bloqueo_sesion(dataset.parent, NOMBRE_LOCK_DATASET_OPERACIONAL):
                filas_frescas = _leer_filas(dataset)
                indice_fresco = _validar_coincidencia_unica(filas_frescas)
                # Microcorrección (Codex, Problema A) -- el journal se
                # escribe PRIMERO, con el dataset TODAVÍA sin tocar: si
                # esta escritura falla, el dataset ni se tocó -- sigue
                # siendo correcto restaurar `estado_previo` más abajo. Si
                # el journal SÍ queda escrito pero el reemplazo del
                # dataset que sigue falla, la MISMA garantía de
                # atomicidad (temp file + fsync + os.replace, ambos
                # escritores) dice que el dataset TAMPOCO cambió -- la
                # entrada del journal queda huérfana (inofensiva: no
                # coincidirá con ninguna huella real hasta que un
                # reproceso futuro la sobrescriba o hasta que el `except`
                # de abajo la limpie). Nunca se promete atomicidad ENTRE
                # los dos archivos -- por eso el `except` de abajo NUNCA
                # confía ciegamente en este orden: relee el dataset y
                # verifica por huella.
                #
                # Microcorrección (Codex, ronda 7) -- variante `_sin_lock`
                # acá: ya estamos DENTRO del `with bloqueo_sesion(...)` de
                # arriba (mismo lock común) -- usar el wrapper protegido
                # reintentaría adquirirlo, fallando en seco contra sí
                # mismo (lock no reentrante).
                _escribir_entrada_journal_reproceso_sin_lock(dataset, identificador, {
                    "envio_id": envio_id,
                    "reemplazado_en": datetime.now(timezone.utc).isoformat(),
                    "fila_hash": _hash_fila(fila_reemplazo),
                    "datos_ocr": datos, "resultado_asociacion": asociacion,
                    "atlas_ia": resumen_ia, "problema_captura": captura_ilegible,
                    "decisiones_nuevas": decisiones_nuevas,
                })
                filas_frescas[indice_fresco] = fila_reemplazo
                _escribir_filas_completas(dataset, filas_frescas)
        except Exception as error:
            # Microcorrección (Codex, Problema A) -- verificación por
            # EVIDENCIA, no por confianza ciega en el orden de arriba: se
            # relee el dataset (fuera del lock -- cualquier escritor real
            # concurrente es atómico, así que esta lectura ve la fila
            # completa vieja o completa nueva, nunca a medio escribir) y
            # se compara la huella de la fila ya persistida contra la que
            # este intento quería escribir. Si coinciden, el reemplazo SÍ
            # aterrizó (el fallo fue en otra cosa, típicamente el
            # journal) -- jamás se trata como "antes del reemplazo" ni se
            # restaura `estado_previo` encima de datos ya nuevos.
            try:
                filas_verificacion = _leer_filas(dataset)
                indice_verificacion = next(
                    (i for i, f in enumerate(filas_verificacion) if f.get("archivo", "") == identificador), None,
                )
                dataset_ya_reemplazado = (
                    indice_verificacion is not None
                    and _hash_fila(filas_verificacion[indice_verificacion]) == _hash_fila(fila_reemplazo)
                )
            except Exception:
                dataset_ya_reemplazado = False

            if dataset_ya_reemplazado:
                registro.update({
                    "datos_ocr": datos, "resultado_asociacion": asociacion,
                    "atlas_ia": resumen_ia, "problema_captura": captura_ilegible,
                    "archivo_dataset": identificador,
                    "procesado_en": datetime.now(timezone.utc).isoformat(), "error": "",
                })
                registro["reproceso_persistido"] = _diagnostico_reproceso_persistido(
                    fase=FASE_DATASET_REEMPLAZADO, estado="FALLIDO_JOURNAL", error=error,
                )
                try:
                    repositorio.guardar(envio_id, registro)
                except Exception:
                    pass  # el dataset ya es la evidencia recuperable -- ver el mensaje de abajo
                raise ErrorEnvioMobile(
                    f"El dataset ya se reemplazó correctamente para {identificador!r}, pero no se "
                    f"pudo registrar el journal ({type(error).__name__}: {error}). Sin journal, una "
                    "reejecución no podrá saltar OCR -- pero SÍ revalidará la coincidencia contra el "
                    "dataset ya correcto y volverá a journalizar; reintentar este mismo reproceso."
                ) from error

            # El dataset NO llegó a cambiar (verificado releyéndolo) --
            # cualquier entrada de journal que haya alcanzado a
            # escribirse antes de este fallo (journal OK, pero el
            # reemplazo del dataset después falló) queda huérfana: se
            # limpia en un mejor esfuerzo, nunca crítico.
            try:
                _escribir_entrada_journal_reproceso(dataset, identificador, None)
            except Exception:
                pass
            registro.update(estado_previo)
            registro["reproceso_persistido"] = _diagnostico_reproceso_persistido(
                fase=FASE_DATASET_REEMPLAZADO, estado="FALLIDO", error=error,
            )
            repositorio.guardar(envio_id, registro)
            return registro

        # A partir de acá el dataset YA tiene los datos nuevos, y el
        # journal YA los conserva -- nunca se revierte, pase lo que pase
        # con el guardado de abajo o con los derivados (Sección 2).
        registro.update({
            "datos_ocr": datos, "resultado_asociacion": asociacion,
            "atlas_ia": resumen_ia, "problema_captura": captura_ilegible,
            "archivo_dataset": identificador,
            "procesado_en": datetime.now(timezone.utc).isoformat(), "error": "",
        })
        registro["reproceso_persistido"] = _diagnostico_reproceso_persistido(
            fase=FASE_DATASET_REEMPLAZADO, estado="EN_PROGRESO",
        )
        # Hallazgo Codex #2 -- manejo EXPLÍCITO de este guardado
        # específico: si FALLA, el dataset ya cambió -- jamás se trata
        # como "antes de reemplazo", jamás se restaura `estado_previo`
        # encima de los datos nuevos. El journal (ya escrito arriba) es
        # la evidencia que sobrevive; se relanza un error claro con qué
        # hacer, en vez de dejar una excepción críptica sin contexto.
        try:
            repositorio.guardar(envio_id, registro)
        except Exception as error:
            raise ErrorEnvioMobile(
                f"El dataset ya se reemplazó correctamente para {identificador!r}, pero no se "
                f"pudo actualizar el registro del envío ({type(error).__name__}: {error}). El "
                f"journal ({_ruta_journal_reproceso(dataset)}) conserva el estado completo -- "
                "reintentar este mismo reproceso para converger; nunca tratar esto como si nada "
                "hubiera cambiado."
            ) from error

    # FASE DERIVADOS_REGENERADOS -- decisiones/asociación (mismo bloque
    # M2-D que `procesar_envio_mobile`, nunca un segundo camino), ya sea
    # que vengamos de un reproceso fresco o de reanudar desde el journal.
    # Un fallo acá NUNCA marca el documento como fallo total (Sección 2):
    # los datos nuevos ya persistidos arriba se conservan tal cual, sólo
    # el `estado` pasa a `ESTADO_DERIVADOS_PENDIENTES` -- Y el journal
    # NO se borra, así que una reejecución posterior retoma exactamente
    # acá, sin repetir OCR ni duplicar decisiones (Hallazgo Codex #3).
    try:
        if carpeta_catalogos is not None:
            # Bloque CONSISTENCIA OPERACIONAL -- misma disciplina que
            # `procesar_envio_mobile`: leer `previas` + fusionar +
            # publicar es UNA sección crítica bajo
            # `NOMBRE_LOCK_DECISIONES_PENDIENTES`, nunca una lectura
            # suelta antes del lock.
            ruta_artefacto = Path(dataset).parent / "decisiones_pendientes.json"
            with bloqueo_sesion(ruta_artefacto.parent, NOMBRE_LOCK_DECISIONES_PENDIENTES):
                previas: list[dict[str, object]] = []
                try:
                    previas = list(json.loads(ruta_artefacto.read_text(encoding="utf-8")).get("decisiones", []))
                except (OSError, json.JSONDecodeError):
                    pass
                decisiones_reconciliadas = regenerar_decisiones_persistidas(
                    decisiones=previas + decisiones_nuevas,
                    carpeta_catalogos=carpeta_catalogos,
                    ruta_dataset=dataset,
                )
                _generar_artefacto_sin_lock(
                    ruta_dataset=dataset, carpeta_catalogos=carpeta_catalogos,
                    decisiones=decisiones_reconciliadas, ruta_salida=ruta_artefacto,
                )
    except Exception as error:
        registro["estado"] = ESTADO_DERIVADOS_PENDIENTES
        registro["reproceso_persistido"] = _diagnostico_reproceso_persistido(
            fase=FASE_DERIVADOS_REGENERADOS, estado="FALLIDO", error=error,
        )
        repositorio.guardar(envio_id, registro)
        return registro

    estado_final = _estado_final_mobile(datos, asociacion, captura_ilegible)
    registro["estado"] = estado_final
    registro["reproceso_persistido"] = _diagnostico_reproceso_persistido(
        fase=FASE_COMPLETADO, estado="COMPLETADO",
    )
    # Microcorrección (Codex, Problema B) -- el checkpoint final se
    # persiste PRIMERO; el journal recién se borra DESPUÉS de que
    # `envio.json` YA muestra COMPLETADO en disco (antes era al revés).
    # Si este guardado fallara con el journal ya borrado, una
    # reejecución no tendría forma de saber que ya se completó y
    # repetiría OCR/B1 sin necesidad -- con el orden correcto, el
    # journal sigue vigente y una reejecución reanuda desde ahí (nunca
    # repite OCR, sólo vuelve a regenerar derivados -- ya idempotente --
    # y reintenta este mismo checkpoint).
    try:
        repositorio.guardar(envio_id, registro)
    except Exception as error:
        raise ErrorEnvioMobile(
            f"El dataset y los derivados ya se regeneraron correctamente para {identificador!r}, "
            f"pero no se pudo persistir el checkpoint final del envío "
            f"({type(error).__name__}: {error}). El journal ({_ruta_journal_reproceso(dataset)}) "
            "sigue vigente -- reintentar este mismo reproceso: reanudará sin repetir OCR ni "
            "duplicar decisiones, y sólo entonces se limpiará."
        ) from error

    # Sólo AHORA, con COMPLETADO ya durable, se limpia el journal --
    # best-effort: si ESTA limpieza fallara, una reejecución posterior
    # reconoce (más arriba, antes de la fase PREPARADO) que el envío ya
    # está COMPLETADO con esa misma huella y sólo reintenta la limpieza,
    # sin reprocesar nada.
    try:
        _escribir_entrada_journal_reproceso(dataset, identificador, None)
    except Exception:
        pass

    return registro


def revalidar_asociacion_mobile_sin_ocr(repositorio: RepositorioEnviosMobile, *, dataset: Path) -> dict[str, object]:
    """Bloque ASOCIACIÓN MOBILE V2, Sección 7 -- reevaluación: relee la
    operación vigente (`dataset`, ya persistida) y vuelve a intentar
    `asociar_documento` para los envíos que quedaron SIN_ASOCIACION o
    PROPUESTA_REQUIERE_REVISION, usando el `datos_ocr` YA GUARDADO -- sin
    volver a correr OCR, sin recrear el envío, sin escribir una fila nueva
    en el dataset (la fila de un documento válido ya se escribió, si
    correspondía, la primera vez que se procesó -- ver `procesar_envio_
    mobile`). Mismo patrón que `revalidar_*_sin_ocr` de
    `atlas_core.revalidacion_documental`: sólo actualiza lo que
    corresponde a SU propio motivo (aquí, la asociación), nunca toca
    `datos_ocr` ni otros campos.

    Pensado para la evidencia nueva que aparece con el tiempo: otro
    documento del mismo transporte llega más tarde, o un supervisor
    corrige en Desktop la fila que generaba la ambigüedad -- en ambos
    casos el envío mobile original quedó con una `resultado_asociacion`
    desactualizada hasta que algo vuelve a evaluarla.

    Nunca DEGRADA un envío ya `ASOCIADO_AUTOMATICAMENTE` (conservador:
    una asociación ya resuelta no se revisita) ni uno con
    `problema_captura` (sin más OCR no hay nada nuevo que evaluar -- ver
    `_captura_ilegible`). Devuelve un resumen, mismo criterio que el
    resto de `revalidar_*_sin_ocr`."""
    filas: list[dict[str, str]] = []
    if dataset and dataset.is_file():
        with dataset.open(encoding="utf-8-sig", newline="") as archivo:
            filas = list(csv.DictReader(archivo, delimiter=";"))

    revisados = 0
    actualizados: list[str] = []
    for registro_historial in repositorio.historial():
        asociacion_previa_historial = registro_historial.get("resultado_asociacion") or {}
        if asociacion_previa_historial.get("estado") not in ("SIN_ASOCIACION", "PROPUESTA_REQUIERE_REVISION"):
            continue  # nada que reevaluar: sin procesar todavía, ya asociado, o en error.
        if registro_historial.get("problema_captura"):
            continue  # sin OCR no hay evidencia nueva que pueda cambiar esto.
        if not (registro_historial.get("datos_ocr") or {}):
            continue
        envio_id = registro_historial["envio_id"]
        revisados += 1
        # Bloque CONSISTENCIA OPERACIONAL -- lock POR ENVÍO alrededor de
        # la relectura fresca + decisión + escritura de ESTE envío
        # específico (nunca de todo el barrido: envíos distintos no se
        # bloquean entre sí). Si otra operación (Mobile normal, un
        # reproceso) está tocando este MISMO envío en este instante,
        # `SesionOcupadaError` se trata como "nada que hacer todavía" --
        # el próximo ciclo natural de esta revalidación lo reintenta;
        # nunca se pisa la escritura ajena en curso.
        try:
            with bloqueo_sesion(
                repositorio.raiz, f"mobile_{envio_id}",
                tiempo_expiracion_segundos=TIEMPO_EXPIRACION_LOCK_ENVIO_SEGUNDOS,
            ):
                # Relectura fresca -- `registro_historial` puede haber
                # quedado obsoleta desde que `historial()` lo snapshoteó.
                registro = repositorio.cargar(envio_id)
                asociacion_previa = registro.get("resultado_asociacion") or {}
                if asociacion_previa.get("estado") not in ("SIN_ASOCIACION", "PROPUESTA_REQUIERE_REVISION"):
                    continue  # otra operación ya lo cambió mientras tanto -- ya no aplica.
                if registro.get("problema_captura"):
                    continue
                datos = registro.get("datos_ocr") or {}
                if not datos:
                    continue
                # A diferencia de `procesar_envio_mobile` (que evalúa
                # ANTES de escribir su propia fila), acá `filas` ya
                # incluye la fila que este MISMO documento escribió la
                # primera vez que se procesó -- sin excluirla, un
                # documento se "auto-matchearía" por su propia guía y
                # quedaría ASOCIADO_AUTOMATICAMENTE sin ninguna evidencia
                # real nueva (justo lo que Sección 13.2 prohíbe). Se
                # excluye por `archivo`, el mismo identificador que ya
                # usa `procesar_envio_mobile` para saber si una fila es
                # "de este documento".
                identificador_propio = f"mobile/{envio_id}/{registro.get('foto_original', '')}"
                filas_sin_propia = [f for f in filas if f.get("archivo") != identificador_propio]
                asociacion_nueva = asociar_documento(datos, filas_sin_propia)
                if asociacion_nueva == asociacion_previa:
                    continue
                estado_nuevo = _estado_final_mobile(datos, asociacion_nueva, False)
                registro["resultado_asociacion"] = asociacion_nueva
                registro["estado"] = estado_nuevo
                repositorio.guardar(envio_id, registro)
                actualizados.append(envio_id)
        except SesionOcupadaError:
            continue

    return {"revisados": revisados, "actualizados": actualizados}
