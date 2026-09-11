"""Persistencia best-effort de evidencia OCR por documento.

La traza vive fuera del CSV operacional: conserva la lectura que ya hizo el
motor durante el procesamiento, sin pedir una segunda lectura ni copiar la
imagen.  Su contrato es deliberadamente simple para que soporte y futuros
consumidores (por ejemplo B1) puedan inspeccionarla sin depender del flujo de
extracción.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import re
from typing import Iterable, Mapping, Sequence

from atlas_core.almacenamiento_portable import escribir_json_atomico


VERSION_SCHEMA_TRAZA_OCR = 2
ESTADO_BLOQUES_DISPONIBLES = "DISPONIBLES"
ESTADO_BLOQUES_NO_SOLICITADOS = "NO_SOLICITADOS"
ESTADO_BLOQUES_NO_DISPONIBLES = "NO_DISPONIBLES"
ESTADOS_BLOQUES = frozenset({
    ESTADO_BLOQUES_DISPONIBLES,
    ESTADO_BLOQUES_NO_SOLICITADOS,
    ESTADO_BLOQUES_NO_DISPONIBLES,
})
_VALORES_AUSENTES = {"", "No encontrado"}


def ruta_traza_ocr(directorio: str | Path, referencia_imagen: str) -> Path:
    """Devuelve una ruta estable, legible y sin colisiones por nombre.

    ``referencia_imagen`` debe ser la ruta relativa al lote cuando se procesa
    una carpeta.  El hash evita que ``a/guia.jpg`` y ``b/guia.jpg`` compartan
    sidecar, a la vez que una segunda ejecución del mismo documento reemplaza
    atómicamente su evidencia en vez de acumular duplicados.
    """
    referencia_normalizada = str(referencia_imagen).replace("\\", "/")
    nombre = Path(referencia_normalizada).stem or "documento"
    nombre_seguro = re.sub(r"[^A-Za-z0-9_-]+", "-", nombre).strip("-") or "documento"
    sufijo = sha256(referencia_normalizada.encode("utf-8")).hexdigest()[:16]
    return Path(directorio) / f"{nombre_seguro}--{sufijo}.json"


def _valor_identificador(valor: object) -> str | None:
    texto = str(valor or "").strip()
    return texto if texto not in _VALORES_AUSENTES else None


def _serializar_bloque(bloque: object) -> dict[str, object]:
    """Convierte el contrato ``BloqueOCR`` a JSON sin asumir un backend."""
    caja = getattr(bloque, "bounding_box", None)
    return {
        "texto": str(getattr(bloque, "texto", "")),
        "bounding_box": [list(punto) for punto in caja] if caja is not None else None,
        "confianza": getattr(bloque, "confianza", None),
    }


def construir_traza_ocr(
    *,
    referencia_imagen: str,
    textos: Iterable[object],
    bloques: Sequence[object] | None,
    estado_bloques: str | None = None,
    proveedor: object = None,
    identificadores: Mapping[str, object] | None = None,
    procesado_en: datetime | None = None,
) -> dict[str, object]:
    """Construye el sidecar con evidencia disponible, sin leer OCR de nuevo."""
    version_backend = None
    if proveedor is not None:
        for atributo in ("version", "backend_version"):
            candidato = getattr(proveedor, atributo, None)
            if isinstance(candidato, (str, int, float, bool)):
                version_backend = candidato
                break
    configuracion = {
        atributo: getattr(proveedor, atributo)
        for atributo in ("device", "configuracion")
        if proveedor is not None
        and isinstance(getattr(proveedor, atributo, None), (str, int, float, bool))
    }
    backend: dict[str, object] = {
        "nombre": (
            f"{type(proveedor).__module__}.{type(proveedor).__name__}"
            if proveedor is not None
            else "atlas_core.ocr.EasyOCRDirecto"
        ),
        # ``null`` expresa honestamente que el runtime no expuso ese dato;
        # no se infiere una versión a partir de paquetes ni se hace trabajo
        # adicional sólo para la traza.
        "version": version_backend,
        "configuracion": configuracion or None,
    }
    estado_efectivo = estado_bloques or (
        ESTADO_BLOQUES_NO_SOLICITADOS
        if bloques is None
        else ESTADO_BLOQUES_DISPONIBLES
    )
    if estado_efectivo not in ESTADOS_BLOQUES:
        raise ValueError(f"estado_bloques no reconocido: {estado_efectivo!r}")
    if bloques is not None and estado_efectivo != ESTADO_BLOQUES_DISPONIBLES:
        raise ValueError("bloques presentes requieren estado_bloques=DISPONIBLES")

    identificadores_serializados = {
        clave: valor
        for clave, original in (identificadores or {}).items()
        if (valor := _valor_identificador(original)) is not None
    }
    marca_tiempo = procesado_en or datetime.now(timezone.utc)
    return {
        "schema_version": VERSION_SCHEMA_TRAZA_OCR,
        "procesado_en_utc": marca_tiempo.astimezone(timezone.utc).isoformat(),
        "imagen": {
            "referencia": str(referencia_imagen).replace("\\", "/"),
            "nombre_archivo": Path(referencia_imagen).name,
        },
        "ocr": {
            "backend": backend,
            "lineas": [str(texto) for texto in textos],
            # ``estado_bloques`` distingue si null significa que no se
            # solicitó geometría o que la solicitud no pudo entregar un
            # resultado. Una lista vacía significa lectura disponible sin
            # bloques detectados.
            "bloques": None if bloques is None else [_serializar_bloque(b) for b in bloques],
            "estado_bloques": estado_efectivo,
        },
        "identificadores_extraidos": identificadores_serializados,
    }


def persistir_traza_ocr(
    *,
    directorio: str | Path,
    referencia_imagen: str,
    textos: Iterable[object],
    bloques: Sequence[object] | None,
    estado_bloques: str | None = None,
    proveedor: object = None,
    identificadores: Mapping[str, object] | None = None,
    procesado_en: datetime | None = None,
) -> Path:
    """Escribe o reemplaza de forma atómica la traza de un documento."""
    ruta = ruta_traza_ocr(directorio, referencia_imagen)
    escribir_json_atomico(
        ruta,
        construir_traza_ocr(
            referencia_imagen=referencia_imagen,
            textos=textos,
            bloques=bloques,
            estado_bloques=estado_bloques,
            proveedor=proveedor,
            identificadores=identificadores,
            procesado_en=procesado_en,
        ),
    )
    return ruta
