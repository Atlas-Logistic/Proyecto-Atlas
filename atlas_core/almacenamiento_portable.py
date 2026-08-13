"""Resolución centralizada de la raíz de datos operativos portables de Atlas.

INFRAESTRUCTURA S2 / S2.1 -- decisión permanente de arquitectura:

    código = GitHub; estado operativo portable = raíz Atlas sincronizada
    por Drive; secretos = almacenamiento local seguro (variables de
    entorno), nunca Drive ni Git.

Este módulo es el ÚNICO lugar que debe conocer CÓMO se resuelve esa raíz.
El resto de Atlas solo pide subcarpetas (`ruta_catalogos_privados()`,
`ruta_cache(...)`, etc.) y nunca construye la ruta a mano ni asume una
letra de unidad o un usuario de Windows concreto.

Orden de resolución (funciona igual en casa y en oficina, sin importar
el usuario de Windows, la letra de unidad de Drive ni dónde esté
clonado el repo):

1. Argumento explícito `override` (para CLIs y tests).
2. Variable de entorno ``ATLAS_DATA_DIR``.
3. Autodetección de SOLO LECTURA de una carpeta ``Atlas`` dentro de
   Google Drive -- nunca crea, mueve ni borra nada durante la
   autodetección; si no encuentra evidencia real en el filesystem
   devuelve ``None`` en lugar de inventar una ruta.
4. Fallback local relativo al directorio de trabajo (uso de
   desarrollo/tests; nunca escribe en el Drive real).

Los tests deben aislar este módulo del entorno real (ver
``tests/conftest.py``): sin eso, un ATLAS_DATA_DIR heredado del shell o
una autodetección real de Drive en la máquina de desarrollo podría
hacer que las pruebas escriban fuera de ``tmp_path``.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import tempfile
import time
from pathlib import Path
from typing import Iterator

VARIABLE_ENTORNO = "ATLAS_DATA_DIR"
NOMBRE_RAIZ_ATLAS = "Atlas"
NOMBRES_CARPETA_MI_UNIDAD = ("Mi unidad", "My Drive")

# Fallback de desarrollo/tests -- relativo al cwd, igual de "local y
# regenerable" que el histórico `Path("output")`/`Path("catalogos")` de
# Atlas antes de S2. Nunca representa una ruta de Drive real.
FALLBACK_LOCAL = Path(".atlas_local")

# C: es casi siempre el disco de sistema en Windows; Drive for Desktop
# monta "Mi unidad"/"My Drive" en otra letra (histéricamente D:-Z:).
_LETRAS_UNIDAD = "DEFGHIJKLMNOPQRSTUVWXYZ"


def autodetectar_raiz_drive() -> Path | None:
    """Busca ``<unidad>:\\{Mi unidad|My Drive}\\Atlas`` en este PC.

    Puramente de lectura: solo confirma que la carpeta ya existe en el
    filesystem. Nunca crea, mueve ni borra nada. Devuelve ``None`` si no
    hay evidencia real -- nunca "inventa" una ruta de Drive.
    """
    candidatos: list[Path] = []
    for letra in _LETRAS_UNIDAD:
        base = Path(f"{letra}:/")
        try:
            if not base.exists():
                continue
        except OSError:
            continue
        for nombre in NOMBRES_CARPETA_MI_UNIDAD:
            candidato = base / nombre / NOMBRE_RAIZ_ATLAS
            if candidato.is_dir():
                candidatos.append(candidato)
    # Compatibilidad con el cliente de escritorio antiguo de Google
    # Drive (sincronización directa a una carpeta bajo el perfil).
    perfil = os.environ.get("USERPROFILE") or str(Path.home())
    for nombre in ("Google Drive", "GoogleDrive"):
        candidato = Path(perfil) / nombre / NOMBRE_RAIZ_ATLAS
        if candidato.is_dir():
            candidatos.append(candidato)
    return candidatos[0] if candidatos else None


def resolver_raiz_atlas(override: str | Path | None = None) -> Path:
    """Resuelve la raíz portable de datos operativos de Atlas.

    Ver el orden de prioridad documentado en el módulo. Nunca crea la
    carpeta -- solo calcula la ruta; quien escribe es responsable de
    crear subcarpetas con ``mkdir(parents=True, exist_ok=True)``.
    """
    if override not in (None, ""):
        return Path(override).expanduser()
    valor_env = os.environ.get(VARIABLE_ENTORNO)
    if valor_env:
        return Path(valor_env).expanduser()
    detectada = autodetectar_raiz_drive()
    if detectada is not None:
        return detectada
    return FALLBACK_LOCAL


def ruta_operacion(subcarpeta: str = "", *, raiz: Path | None = None) -> Path:
    base = (raiz if raiz is not None else resolver_raiz_atlas()) / "operacion"
    return (base / subcarpeta) if subcarpeta else base


def ruta_catalogos_privados(*, raiz: Path | None = None) -> Path:
    return (raiz if raiz is not None else resolver_raiz_atlas()) / "catalogos_privados"


def ruta_cache(subcarpeta: str, *, raiz: Path | None = None) -> Path:
    return (raiz if raiz is not None else resolver_raiz_atlas()) / "cache" / subcarpeta


def ruta_reportes(subcarpeta: str = "actual", *, raiz: Path | None = None) -> Path:
    return (raiz if raiz is not None else resolver_raiz_atlas()) / "reportes" / subcarpeta


def ruta_respaldos(*, raiz: Path | None = None) -> Path:
    return (raiz if raiz is not None else resolver_raiz_atlas()) / "respaldos"


def ruta_datos_privados(subcarpeta: str = "", *, raiz: Path | None = None) -> Path:
    base = (raiz if raiz is not None else resolver_raiz_atlas()) / "datos_privados"
    return (base / subcarpeta) if subcarpeta else base


def ruta_coordinacion(*, raiz: Path | None = None) -> Path:
    return (raiz if raiz is not None else resolver_raiz_atlas()) / "coordinacion"


def escribir_json_atomico(ruta: str | Path, contenido: object) -> None:
    """Escribe JSON vía temp-file + ``os.replace``.

    Mismo patrón ya usado por ``RepositorioRutas``/``RepositorioTelemetria``
    -- nunca deja un archivo truncado si el proceso muere a mitad de
    escritura; ``os.replace`` es una operación atómica a nivel de
    filesystem.
    """
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=ruta.parent,
            prefix=f".{ruta.name}.", suffix=".tmp", delete=False,
        ) as archivo:
            temporal = Path(archivo.name)
            json.dump(contenido, archivo, ensure_ascii=False, indent=2)
            archivo.write("\n")
            archivo.flush()
            os.fsync(archivo.fileno())
        os.replace(temporal, ruta)
    except OSError:
        if temporal is not None:
            temporal.unlink(missing_ok=True)
        raise


class SesionOcupadaError(RuntimeError):
    """Otra sesión de Atlas ya sostiene el bloqueo para esta operación."""


@contextlib.contextmanager
def bloqueo_sesion(
    directorio: str | Path,
    nombre: str,
    *,
    tiempo_expiracion_segundos: float = 6 * 3600,
) -> Iterator[None]:
    """Lock simple basado en archivo -- evita que dos Atlas se pisen.

    No es infraestructura distribuida: crea ``<directorio>/.atlas_lock_<nombre>``
    con ``open(..., "x")`` (falla si ya existe). Si el lock existente es
    más viejo que ``tiempo_expiracion_segundos`` se trata como huérfano
    (un proceso anterior murió sin liberarlo) y se reemplaza en vez de
    bloquear para siempre.
    """
    directorio = Path(directorio)
    directorio.mkdir(parents=True, exist_ok=True)
    ruta_lock = directorio / f".atlas_lock_{nombre}"
    _adquirir(ruta_lock, tiempo_expiracion_segundos)
    try:
        yield
    finally:
        ruta_lock.unlink(missing_ok=True)


def _adquirir(ruta_lock: Path, tiempo_expiracion_segundos: float) -> None:
    info = json.dumps(
        {"pid": os.getpid(), "host": socket.gethostname(), "adquirido_en": time.time()}
    )
    try:
        with open(ruta_lock, "x", encoding="utf-8") as archivo:
            archivo.write(info)
        return
    except FileExistsError:
        pass
    try:
        edad = time.time() - ruta_lock.stat().st_mtime
    except OSError:
        edad = float("inf")
    if edad <= tiempo_expiracion_segundos:
        raise SesionOcupadaError(
            f"Bloqueo activo en {ruta_lock} (edad {edad:.0f}s); "
            "otra sesión de Atlas puede estar escribiendo la misma operación."
        )
    # Lock huérfano (más viejo que el umbral): un proceso anterior murió
    # sin liberarlo. Se reemplaza en vez de bloquear para siempre.
    ruta_lock.unlink(missing_ok=True)
    with open(ruta_lock, "x", encoding="utf-8") as archivo:
        archivo.write(info)
