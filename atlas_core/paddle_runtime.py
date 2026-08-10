"""Runtime portable de PaddleOCR (Bloque M2).

Resuelve, crea y valida un venv aislado para PaddleOCR sin depender de
ninguna ruta específica de un PC ni de un usuario de Windows. Ubicación por
defecto: %LOCALAPPDATA%\\Atlas\\runtime\\paddleocr — nunca dentro del venv
principal de Atlas, nunca en el repositorio.

No reinstala si el runtime ya existe y coincide con las versiones fijadas
(PADDLEOCR_VERSION, PADDLEPADDLE_VERSION). No modifica drivers del sistema.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Versiones fijadas y conocidas (las mismas validadas en los bloques
# OCR-EVAL / M1). Cambiarlas aquí invalida cualquier runtime existente
# (deja de coincidir con ARCHIVO_VERSION) y fuerza una recreación limpia.
PADDLEOCR_VERSION = "3.7.0"
PADDLEPADDLE_VERSION = "3.3.1"
INDICE_PADDLE_GPU_CUDA118 = "https://www.paddlepaddle.org.cn/packages/stable/cu118/"

ARCHIVO_VERSION = ".version"
TIMEOUT_VENV_SEG = 300
TIMEOUT_INSTALL_SEG = 1800

VARIABLE_ENTORNO_OVERRIDE = "ATLAS_PADDLE_RUNTIME"


def ruta_runtime_paddle() -> Path:
    """Ubicación portable del runtime aislado.

    Prioridad:
    1. Variable de entorno ATLAS_PADDLE_RUNTIME — override explícito, pensado
       para desarrollo/CI, nunca requerido en un PC nuevo.
    2. %LOCALAPPDATA%\\Atlas\\runtime\\paddleocr — no depende del nombre de
       usuario (la variable de entorno ya resuelve eso), no depende de
       Desktop, no depende de ninguna ruta de este repositorio.
    """
    override = os.environ.get(VARIABLE_ENTORNO_OVERRIDE)
    if override:
        return Path(override)
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / "Atlas" / "runtime" / "paddleocr"


def python_runtime(ruta_runtime: Path) -> Path:
    return ruta_runtime / "Scripts" / "python.exe"


def _version_esperada() -> str:
    return f"{PADDLEOCR_VERSION}+{PADDLEPADDLE_VERSION}"


def runtime_valido(ruta_runtime: Path) -> bool:
    """True si el runtime existe y coincide con las versiones fijadas
    actuales — sin ejecutar nada, solo leyendo un marcador de versión."""
    python = python_runtime(ruta_runtime)
    marcador = ruta_runtime / ARCHIVO_VERSION
    if not python.exists() or not marcador.exists():
        return False
    try:
        return marcador.read_text(encoding="utf-8").strip() == _version_esperada()
    except OSError:
        return False


def _gpu_nvidia_disponible() -> bool:
    # Import diferido: evita un ciclo de imports entre ocr_provider y
    # paddle_runtime (ambos se necesitan mutuamente para device/versión).
    from atlas_core.ocr_provider import _gpu_nvidia_disponible as _detectar

    return _detectar()


def asegurar_runtime_paddle(forzar: bool = False) -> Path | None:
    """Crea (si hace falta) y valida el runtime aislado de PaddleOCR.

    Devuelve la ruta a su python.exe si quedó utilizable, o None si no se
    pudo preparar — en ese caso el llamador debe caer a EasyOCR. No
    reinstala si el runtime ya es válido (salvo forzar=True). No toca
    drivers ni CUDA del sistema; solo instala paquetes Python en un venv
    propio.
    """
    ruta_runtime = ruta_runtime_paddle()
    if not forzar and runtime_valido(ruta_runtime):
        logger.info("Runtime PaddleOCR ya existe y es válido: %s", ruta_runtime)
        return python_runtime(ruta_runtime)

    try:
        ruta_runtime.mkdir(parents=True, exist_ok=True)
        logger.warning(
            "Creando/actualizando runtime PaddleOCR en %s (primera vez o versión desactualizada)…",
            ruta_runtime,
        )
        subprocess.run(
            [sys.executable, "-m", "venv", str(ruta_runtime)],
            check=True, timeout=TIMEOUT_VENV_SEG, capture_output=True, text=True,
        )
        python = python_runtime(ruta_runtime)
        gpu = _gpu_nvidia_disponible()
        if gpu:
            paquete_paddle = [f"paddlepaddle-gpu=={PADDLEPADDLE_VERSION}", "-i", INDICE_PADDLE_GPU_CUDA118]
        else:
            paquete_paddle = [f"paddlepaddle=={PADDLEPADDLE_VERSION}"]
        subprocess.run(
            [str(python), "-m", "pip", "install", *paquete_paddle],
            check=True, timeout=TIMEOUT_INSTALL_SEG, capture_output=True, text=True,
        )
        subprocess.run(
            [str(python), "-m", "pip", "install", f"paddleocr=={PADDLEOCR_VERSION}", "psutil"],
            check=True, timeout=TIMEOUT_INSTALL_SEG, capture_output=True, text=True,
        )
        (ruta_runtime / ARCHIVO_VERSION).write_text(_version_esperada(), encoding="utf-8")
        logger.info("Runtime PaddleOCR listo en %s (GPU=%s)", ruta_runtime, gpu)
        return python
    except Exception as exc:  # instalación fallida nunca debe tumbar Atlas
        logger.warning(
            "No se pudo preparar el runtime de PaddleOCR (%s: %s); Atlas usará EasyOCR.",
            type(exc).__name__, exc,
        )
        return None
