"""Bloque R1 -- EVIDENCIA VISUAL EN REVISIONES.

La imagen original es evidencia PRIMARIA; el OCR/dato operacional es
evidencia DERIVADA. Este módulo formaliza la relación GUÍA -> imagen
original -> (OCR/dato operacional/motivo de revisión/decisión humana
viven ya en `analisis_completo_guias.csv`/`decisiones_pendientes.json`,
nunca duplicados aquí) usando el identificador ya existente y estable:
``documento.archivo`` (el mismo que ya usa `decisiones_pendientes.json`
y las columnas ``archivo``/``evidencias_documentos`` de Motor).

Auditoría previa (sin la cual este módulo no hubiera sido necesario):
Desktop (`atlas:procesar-imagenes`) YA copia cada imagen arrastrada a
``operacion/entradas/<marca>/<archivo>`` ANTES de procesarla -- Motor
nunca depende de que el archivo siga en la carpeta de origen del
usuario. Mobile (`RepositorioEnviosMobile`) YA persiste cada envío en
``operacion/mobile/envios/<envio_id>/<foto_original>`` del lado
Atlas/Drive, nunca sólo en el teléfono. NINGUNO de los dos flujos
borra la imagen después de procesar -- la evidencia YA permanece
accesible; lo único que faltaba era (a) un punto único para
resolverla dado ``archivo`` y (b) un ciclo de vida hacia adelante que
la retire de la operación activa cuando ya no hace falta, sin
borrarla de inmediato.

Nunca duplica el binario: una imagen que respalda 3 decisiones sigue
siendo UN solo archivo -- las 3 decisiones comparten el mismo
``documento.archivo``, y este módulo resuelve/mueve por `archivo`,
nunca por decisión."""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico, ruta_operacion

UBICACION_ACTIVA_DESKTOP = "ACTIVA_DESKTOP"
UBICACION_ACTIVA_MOBILE = "ACTIVA_MOBILE"
UBICACION_EVIDENCIA_RESUELTA = "EVIDENCIA_RESUELTA"
UBICACION_PURGADA = "PURGADA"
UBICACION_NO_ENCONTRADA = "NO_ENCONTRADA"

NOMBRE_METADATA = "metadata.json"

# Retención simple, deliberadamente una constante (no una interfaz de
# configuración todavía) -- fácil de cambiar después, ver bloque R1.
RETENCION_EVIDENCIA_RESUELTA_DIAS = 30


@dataclass(frozen=True)
class RutaEvidencia:
    archivo: str
    ruta: Path | None
    ubicacion: str


def _prefijo_mobile(archivo: str) -> tuple[str, str] | None:
    """`archivo` con forma ``mobile/<envio_id>/<foto>`` -- mismo
    convenio ya usado por `atlas_core.mobile.procesar_envio_mobile`
    (``identificador = f"mobile/{envio_id}/{foto_original}"``), nunca
    reinventado aquí."""
    partes = archivo.split("/", 2)
    if len(partes) == 3 and partes[0] == "mobile" and partes[1] and partes[2]:
        return partes[1], partes[2]
    return None


def resolver_ruta_evidencia(raiz_atlas: str | Path, archivo: str) -> RutaEvidencia:
    """Único punto de resolución GUÍA -> imagen original. Busca, en
    orden, en las mismas ubicaciones donde Desktop/Mobile YA dejan la
    evidencia (nunca un índice/base de datos nueva): Mobile
    (``operacion/mobile/envios/<envio_id>/<foto>``), evidencia activa
    de Desktop (``operacion/entradas/<marca>/<archivo>``, buscando en
    cualquier lote -- el llamador no necesita saber en cuál quedó) y,
    por último, el depósito de evidencia YA resuelta (Fase B/C de este
    bloque) -- si el binario de ahí ya fue purgado, se distingue
    explícitamente (`PURGADA`) de "nunca existió" (`NO_ENCONTRADA`)."""
    raiz = Path(raiz_atlas)
    archivo = str(archivo or "").strip()
    if not archivo:
        return RutaEvidencia(archivo, None, UBICACION_NO_ENCONTRADA)

    mobile = _prefijo_mobile(archivo)
    if mobile is not None:
        envio_id, foto = mobile
        ruta = raiz / "operacion" / "mobile" / "envios" / envio_id / foto
        if ruta.is_file():
            return RutaEvidencia(archivo, ruta, UBICACION_ACTIVA_MOBILE)
        return RutaEvidencia(archivo, None, UBICACION_NO_ENCONTRADA)

    carpeta_entradas = raiz / "operacion" / "entradas"
    if carpeta_entradas.is_dir():
        for lote in sorted(carpeta_entradas.iterdir()):
            if not lote.is_dir():
                continue
            candidato = lote / archivo
            # Nunca sale de la carpeta del lote (`archivo` viene de un
            # documento ya persistido, no de un input externo, pero se
            # verifica igual -- mismo criterio conservador que el resto
            # de Atlas para rutas relativas).
            try:
                candidato.resolve().relative_to(lote.resolve())
            except ValueError:
                continue
            if candidato.is_file():
                return RutaEvidencia(archivo, candidato, UBICACION_ACTIVA_DESKTOP)

    carpeta_resuelta = ruta_operacion("evidencia_resuelta", raiz=raiz)
    if carpeta_resuelta.is_dir():
        for entrada in carpeta_resuelta.iterdir():
            ruta_metadata = entrada / NOMBRE_METADATA
            if not ruta_metadata.is_file():
                continue
            try:
                metadata = json.loads(ruta_metadata.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if metadata.get("archivo") != archivo:
                continue
            nombre_imagen = str(metadata.get("nombre_imagen", ""))
            ruta_imagen = entrada / nombre_imagen if nombre_imagen else None
            if ruta_imagen is not None and ruta_imagen.is_file():
                return RutaEvidencia(archivo, ruta_imagen, UBICACION_EVIDENCIA_RESUELTA)
            return RutaEvidencia(archivo, None, UBICACION_PURGADA)

    return RutaEvidencia(archivo, None, UBICACION_NO_ENCONTRADA)


def documentos_con_revision_pendiente(decisiones_pendientes: Mapping[str, object]) -> frozenset[str]:
    """`archivo` de cada documento con al menos una decisión con
    ``estado == "PENDIENTE"`` -- la única fuente de verdad de qué
    evidencia sigue siendo necesaria para decidir. Nunca cuenta
    decisiones ya resueltas (POSPONER se persiste igual como
    PENDIENTE en `decisiones_pendientes.json` -- sigue siendo una
    revisión abierta, correctamente conservada aquí)."""
    decisiones = decisiones_pendientes.get("decisiones") if isinstance(decisiones_pendientes, Mapping) else None
    if not isinstance(decisiones, list):
        return frozenset()
    archivos: set[str] = set()
    for decision in decisiones:
        if not isinstance(decision, Mapping) or decision.get("estado") != "PENDIENTE":
            continue
        documento = decision.get("documento")
        archivo = documento.get("archivo") if isinstance(documento, Mapping) else None
        if archivo:
            archivos.add(str(archivo))
    return frozenset(archivos)


def _sha256_archivo(ruta: Path) -> str:
    digest = hashlib.sha256()
    with ruta.open("rb") as flujo:
        for bloque in iter(lambda: flujo.read(1024 * 1024), b""):
            digest.update(bloque)
    return digest.hexdigest()


def _identificador_seguro(archivo: str) -> str:
    """Nombre de carpeta determinista y sin separadores de ruta --
    `archivo` puede traer "/" (caso Mobile), nunca se usa tal cual como
    nombre de carpeta."""
    return hashlib.sha256(archivo.encode("utf-8")).hexdigest()[:32]


def mover_evidencia_resuelta_sin_revision_pendiente(
    raiz_atlas: str | Path, *, decisiones_pendientes: Mapping[str, object],
    reloj=lambda: datetime.now(timezone.utc),
) -> dict[str, object]:
    """Fase B del bloque -- para cada imagen HOY en evidencia ACTIVA de
    Desktop (``operacion/entradas/<marca>/*``) cuyo `archivo` ya NO
    tiene ninguna decisión PENDIENTE (`pending_reviews(documento) ==
    0`, ver `documentos_con_revision_pendiente`), la mueve (nunca
    copia -- Regla "no duplicar") al depósito de evidencia RESUELTA,
    con metadata permanente (hash, fecha de resolución, procedencia).

    Deliberadamente restringido a evidencia de origen Desktop: la de
    Mobile (``operacion/mobile/envios/<envio_id>/``) ya vive del lado
    Atlas/Drive (nunca sólo en el teléfono, ver docstring del módulo) y
    ese mismo directorio es la fuente que usan otras vistas de Desktop
    (p. ej. "Envíos Mobile" -- historial completo, no sólo pendientes);
    moverla de ahí arriesgaría romper ese flujo ya existente sin
    necesidad real. Queda fuera de alcance de este bloque a propósito
    -- ver informe."""
    raiz = Path(raiz_atlas)
    pendientes = documentos_con_revision_pendiente(decisiones_pendientes)
    carpeta_entradas = raiz / "operacion" / "entradas"
    carpeta_resuelta = ruta_operacion("evidencia_resuelta", raiz=raiz)
    movidos: list[str] = []
    if not carpeta_entradas.is_dir():
        return {"movidos": movidos}
    instante = reloj().astimezone(timezone.utc).isoformat()
    with bloqueo_sesion(raiz / "operacion", "evidencia_documental"):
        for lote in sorted(carpeta_entradas.iterdir()):
            if not lote.is_dir():
                continue
            for imagen in sorted(lote.iterdir()):
                if not imagen.is_file() or imagen.name == "_snapshot_antes.json":
                    continue
                archivo = imagen.relative_to(lote).as_posix()
                if archivo in pendientes:
                    continue
                destino = carpeta_resuelta / _identificador_seguro(archivo)
                destino.mkdir(parents=True, exist_ok=True)
                nombre_imagen = imagen.name
                shutil.move(str(imagen), str(destino / nombre_imagen))
                metadata = {
                    "archivo": archivo, "nombre_imagen": nombre_imagen,
                    "hash_sha256": _sha256_archivo(destino / nombre_imagen),
                    "procedencia": "DESKTOP", "lote_origen": lote.name,
                    "fecha_resolucion": instante, "binario_eliminado": False,
                }
                escribir_json_atomico(destino / NOMBRE_METADATA, metadata)
                movidos.append(archivo)
            # Un lote que quedó vacío tras mover toda su evidencia resuelta
            # ya no aporta nada -- se retira (nunca si sigue teniendo
            # imágenes con revisión abierta).
            if lote.is_dir() and not any(lote.iterdir()):
                lote.rmdir()
    return {"movidos": movidos}


def purgar_evidencia_resuelta_vencida(
    raiz_atlas: str | Path, *, decisiones_pendientes: Mapping[str, object],
    retencion_dias: int = RETENCION_EVIDENCIA_RESUELTA_DIAS,
    reloj=lambda: datetime.now(timezone.utc),
) -> dict[str, object]:
    """Fase C del bloque -- elimina SÓLO el binario de imagen de
    entradas en `evidencia_resuelta/` cuya `fecha_resolucion` supera
    `retencion_dias`. Nunca borra `metadata.json` (identificador,
    hash, fecha de resolución y procedencia quedan para siempre --
    las decisiones humanas y la trazabilidad operacional ya viven,
    permanentemente, en `decisiones_aplicadas.json`/el dataset, nunca
    duplicadas aquí). Vuelve a comprobar `documentos_con_revision_
    pendiente` como salvaguarda activa -- nunca purga un `archivo` que,
    por cualquier motivo, haya vuelto a tener una decisión PENDIENTE."""
    raiz = Path(raiz_atlas)
    pendientes = documentos_con_revision_pendiente(decisiones_pendientes)
    carpeta_resuelta = ruta_operacion("evidencia_resuelta", raiz=raiz)
    purgados: list[str] = []
    if not carpeta_resuelta.is_dir():
        return {"purgados": purgados}
    limite = reloj().astimezone(timezone.utc) - timedelta(days=retencion_dias)
    with bloqueo_sesion(raiz / "operacion", "evidencia_documental"):
        for entrada in sorted(carpeta_resuelta.iterdir()):
            ruta_metadata = entrada / NOMBRE_METADATA
            if not ruta_metadata.is_file():
                continue
            try:
                metadata = json.loads(ruta_metadata.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if metadata.get("binario_eliminado"):
                continue
            if metadata.get("archivo") in pendientes:
                continue
            try:
                fecha_resolucion = datetime.fromisoformat(str(metadata.get("fecha_resolucion", "")))
            except ValueError:
                continue
            if fecha_resolucion > limite:
                continue
            nombre_imagen = str(metadata.get("nombre_imagen", ""))
            ruta_imagen = entrada / nombre_imagen if nombre_imagen else None
            if ruta_imagen is not None and ruta_imagen.is_file():
                ruta_imagen.unlink()
            metadata["binario_eliminado"] = True
            metadata["purgado_en"] = reloj().astimezone(timezone.utc).isoformat()
            escribir_json_atomico(ruta_metadata, metadata)
            purgados.append(str(metadata.get("archivo", "")))
    return {"purgados": purgados}
