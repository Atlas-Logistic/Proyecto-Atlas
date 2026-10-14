"""Registro durable POR CICLO del PULL Cloud.

La tarea programada redirige la salida a un único log que cada ciclo
sobrescribe: un ciclo que muere a mitad de un OCR pierde su evidencia en
cuanto arranca el siguiente. Este módulo deja, además, un archivo por
ciclo en almacenamiento local del PC (nunca en la raíz Atlas):

- línea `INICIO` (pid, proceso padre, argumentos);
- copia de todo lo que el proceso escribe en stdout/stderr;
- volcado de `faulthandler` ante una caída nativa;
- línea `FIN` con el código de salida, o `EXCEPCION` con la traza.

Un archivo SIN línea final prueba una terminación externa (el proceso no
alcanzó a ejecutar Python). Todo es best-effort: un fallo del registro
nunca impide ni altera el PULL.
"""
from __future__ import annotations

import faulthandler
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable, TextIO

RETENCION_DIAS = 14
PREFIJO = "pull_"


def directorio_ciclos() -> Path:
    override = os.environ.get("ATLAS_PULL_LOG_DIR", "").strip()
    if override:
        return Path(override)
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local")
    return base / "Atlas" / "logs" / "pull_ciclos"


class _Duplicador:
    """Escribe en el flujo original y en el archivo del ciclo."""

    def __init__(self, original: TextIO, archivo: TextIO) -> None:
        self._original = original
        self._archivo = archivo

    def write(self, texto: str) -> int:
        try:
            self._archivo.write(texto)
            self._archivo.flush()
        except (OSError, ValueError):
            pass
        return self._original.write(texto)

    def flush(self) -> None:
        try:
            self._archivo.flush()
        except (OSError, ValueError):
            pass
        self._original.flush()

    def __getattr__(self, nombre):
        return getattr(self._original, nombre)


def _limpiar_antiguos(directorio: Path, *, ahora: float) -> None:
    limite = ahora - RETENCION_DIAS * 86400
    for ruta in directorio.glob(f"{PREFIJO}*.log"):
        try:
            if ruta.stat().st_mtime < limite:
                ruta.unlink()
        except OSError:
            pass


def _linea(archivo: TextIO, evento: str, **datos) -> None:
    try:
        archivo.write(f"\n### {evento} {json.dumps({'en': datetime.now().isoformat(timespec='seconds'), **datos}, ensure_ascii=True)}\n")
        archivo.flush()
    except (OSError, ValueError):
        pass


def ejecutar_con_registro_de_ciclo(principal: Callable[[], None], *, directorio: Path | None = None) -> None:
    """Ejecuta `principal` registrando el ciclo; propaga su salida intacta."""
    archivo: TextIO | None = None
    originales = (sys.stdout, sys.stderr)
    try:
        directorio = directorio or directorio_ciclos()
        directorio.mkdir(parents=True, exist_ok=True)
        _limpiar_antiguos(directorio, ahora=time.time())
        nombre = f"{PREFIJO}{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.getpid()}.log"
        archivo = open(directorio / nombre, "a", encoding="utf-8", errors="replace")
        _linea(archivo, "INICIO", pid=os.getpid(), ppid=os.getppid(), argv=sys.argv[1:])
        faulthandler.enable(file=archivo, all_threads=True)
        sys.stdout = _Duplicador(originales[0], archivo)
        sys.stderr = _Duplicador(originales[1], archivo)
    except OSError:
        archivo = None

    codigo: int | str | None = 0
    try:
        principal()
    except SystemExit as salida:
        codigo = salida.code if salida.code is not None else 0
        raise
    except BaseException as error:
        if archivo is not None:
            _linea(archivo, "EXCEPCION", tipo=type(error).__name__,
                   traza="".join(traceback.format_exception(type(error), error, error.__traceback__)))
        codigo = None
        raise
    finally:
        sys.stdout, sys.stderr = originales
        if archivo is not None:
            if codigo is not None:
                _linea(archivo, "FIN", codigo=codigo)
            try:
                faulthandler.disable()
                archivo.close()
            except (OSError, ValueError):
                pass
