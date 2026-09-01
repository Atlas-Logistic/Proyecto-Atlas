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
from atlas_core.decisiones_pendientes import generar_artefacto, regenerar_decisiones_persistidas
from atlas_core.gestor_viajes import transporte_valido
from atlas_core.ocr_provider import crear_proveedor_ocr
from atlas_core.procesamiento_masivo import (
    COLUMNAS, _escribir_filas, escalar_resultado_ia_en_memoria, procesar_archivo,
)

ESTADOS = ("RECIBIDO", "PROCESANDO", "ASOCIADO", "REQUIERE_REVISION", "ERROR")
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
            previas: list[dict[str, object]] = []
            ruta_artefacto = Path(dataset).parent / "decisiones_pendientes.json"
            try:
                previas = list(json.loads(ruta_artefacto.read_text(encoding="utf-8")).get("decisiones", []))
            except (OSError, json.JSONDecodeError):
                pass
            decisiones_reconciliadas = regenerar_decisiones_persistidas(
                decisiones=previas + decisiones_nuevas,
                carpeta_catalogos=carpeta_catalogos,
                ruta_dataset=dataset,
            )
            generar_artefacto(
                ruta_dataset=dataset, carpeta_catalogos=carpeta_catalogos,
                decisiones=decisiones_reconciliadas,
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
    for registro in repositorio.historial():
        asociacion_previa = registro.get("resultado_asociacion") or {}
        if asociacion_previa.get("estado") not in ("SIN_ASOCIACION", "PROPUESTA_REQUIERE_REVISION"):
            continue  # nada que reevaluar: sin procesar todavía, ya asociado, o en error.
        if registro.get("problema_captura"):
            continue  # sin OCR no hay evidencia nueva que pueda cambiar esto.
        datos = registro.get("datos_ocr") or {}
        if not datos:
            continue
        revisados += 1
        # A diferencia de `procesar_envio_mobile` (que evalúa ANTES de
        # escribir su propia fila), acá `filas` ya incluye la fila que
        # este MISMO documento escribió la primera vez que se procesó --
        # sin excluirla, un documento se "auto-matchearía" por su propia
        # guía y quedaría ASOCIADO_AUTOMATICAMENTE sin ninguna evidencia
        # real nueva (justo lo que Sección 13.2 prohíbe). Se excluye por
        # `archivo`, el mismo identificador que ya usa `procesar_envio_
        # mobile` para saber si una fila es "de este documento".
        identificador_propio = f"mobile/{registro['envio_id']}/{registro.get('foto_original', '')}"
        filas_sin_propia = [f for f in filas if f.get("archivo") != identificador_propio]
        asociacion_nueva = asociar_documento(datos, filas_sin_propia)
        if asociacion_nueva == asociacion_previa:
            continue
        estado_nuevo = _estado_final_mobile(datos, asociacion_nueva, False)
        registro["resultado_asociacion"] = asociacion_nueva
        registro["estado"] = estado_nuevo
        repositorio.guardar(registro["envio_id"], registro)
        actualizados.append(registro["envio_id"])

    return {"revisados": revisados, "actualizados": actualizados}
