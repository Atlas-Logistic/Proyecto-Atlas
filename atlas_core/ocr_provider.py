"""Abstracción de proveedor OCR (Bloque M1).

El resto de Atlas debe depender de este contrato, no de easyocr.Reader
directamente. Dos implementaciones:

- EasyOCRProvider: envuelve las funciones ya existentes en atlas_core.ocr,
  en el mismo proceso (EasyOCR ya es dependencia del entorno principal).
- PaddleOCRProvider: ejecuta PaddleOCR en un proceso aislado (venv externo,
  fuera del entorno principal) para no mezclar sus dependencias con las de
  Atlas. Habla con ese proceso por un protocolo JSON línea a línea sobre
  stdin/stdout (ver atlas_core/paddleocr_worker.py).

Selección de proveedor: crear_proveedor_ocr() intenta el proveedor
preferido (por defecto PaddleOCR) y cae a EasyOCR si no está disponible o
falla al iniciar — nunca deja a Atlas sin poder leer OCR.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from atlas_core.ocr import (
    BloqueOCR,
    ALLOWLIST_FECHA,
    ALLOWLIST_TRANSPORTE,
    _leer_region_focal,
    crear_lector_ocr,
    leer_bloques_imagen,
    leer_texto_imagen,
)

logger = logging.getLogger(__name__)

# Venv aislado con PaddlePaddle/PaddleOCR (validado en el bloque OCR-EVAL:
# paddlepaddle-gpu==3.3.1 cu118, corre en GPU si hay una NVIDIA compatible y
# también en CPU con el mismo wheel — no se necesita un segundo venv).
RUTA_VENV_PADDLE = Path(r"C:\Users\Jjjc0508\Desktop\Atlas\ocr_eval_gpu_env")
RUTA_PYTHON_PADDLE = RUTA_VENV_PADDLE / "Scripts" / "python.exe"
RUTA_WORKER_PADDLE = Path(__file__).resolve().parent / "paddleocr_worker.py"

TIMEOUT_INICIO_SEG = 120
TIMEOUT_COMANDO_SEG = 180


class ProveedorOCRNoDisponible(RuntimeError):
    """El proveedor no pudo iniciarse o dejó de responder."""


@runtime_checkable
class ProveedorOCR(Protocol):
    """Contrato mínimo que el resto de Atlas puede asumir de cualquier motor OCR."""

    def leer_texto(self, ruta_imagen: str | Path) -> list[str]:
        """Texto completo de la imagen, como lista de bloques/líneas."""
        ...

    def leer_bloques(self, ruta_imagen: str | Path) -> list[BloqueOCR]:
        """Bloques OCR con geometría (bounding_box) y confianza."""
        ...

    def leer_focal(
        self, ruta_imagen: str | Path, caja: tuple[float, float, float, float], allowlist: str
    ) -> dict[str, Any]:
        """Lectura focal de una región: recorte + 4 variantes, mismo formato que
        atlas_core.ocr._leer_region_focal: {"recorte":..., "lecturas": [...]}."""
        ...


class EasyOCRProvider:
    """Envuelve las funciones EasyOCR ya existentes en atlas_core.ocr, sin cambiarlas."""

    def __init__(self, lector: Any = None) -> None:
        self._lector = lector

    def _lector_o_crear(self) -> Any:
        if self._lector is None:
            self._lector = crear_lector_ocr()
        return self._lector

    def leer_texto(self, ruta_imagen: str | Path) -> list[str]:
        return leer_texto_imagen(ruta_imagen, lector=self._lector_o_crear())

    def leer_bloques(self, ruta_imagen: str | Path) -> list[BloqueOCR]:
        return leer_bloques_imagen(ruta_imagen, lector=self._lector_o_crear())

    def leer_focal(
        self, ruta_imagen: str | Path, caja: tuple[float, float, float, float], allowlist: str
    ) -> dict[str, Any]:
        return _leer_region_focal(ruta_imagen, caja, lector=self._lector_o_crear(), allowlist=allowlist)


def _gpu_nvidia_disponible() -> bool:
    """Detección genérica: ¿hay una GPU NVIDIA utilizable? Sin hardcodear ningún modelo."""
    try:
        resultado = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        )
        return resultado.returncode == 0 and bool(resultado.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return False


class PaddleOCRProvider:
    """Ejecuta PaddleOCR en un proceso del venv aislado (nunca en el entorno principal).

    Selecciona GPU si hay una NVIDIA disponible, si no CPU (con el workaround
    enable_mkldnn=False). El proceso worker se mantiene vivo entre llamadas
    para no recargar el modelo en cada imagen.
    """

    def __init__(self, device: str | None = None) -> None:
        self._device = device or ("gpu" if _gpu_nvidia_disponible() else "cpu")
        self._proceso: subprocess.Popen | None = None

    @property
    def device(self) -> str:
        return self._device

    def _asegurar_proceso(self) -> subprocess.Popen:
        if self._proceso is not None and self._proceso.poll() is None:
            return self._proceso

        if not RUTA_PYTHON_PADDLE.exists():
            raise ProveedorOCRNoDisponible(
                f"No se encontró el intérprete del venv aislado de PaddleOCR: {RUTA_PYTHON_PADDLE}"
            )

        proceso = subprocess.Popen(
            [str(RUTA_PYTHON_PADDLE), str(RUTA_WORKER_PADDLE)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        proceso.stdin.write(json.dumps({"device": self._device}) + "\n")
        proceso.stdin.flush()
        linea = proceso.stdout.readline()
        if not linea:
            error = proceso.stderr.read()
            proceso.kill()
            raise ProveedorOCRNoDisponible(f"El worker de PaddleOCR no respondió al iniciar: {error[-2000:]}")
        respuesta = json.loads(linea)
        if not respuesta.get("ok"):
            proceso.kill()
            raise ProveedorOCRNoDisponible(f"El worker de PaddleOCR falló al iniciar: {respuesta}")
        logger.info("PaddleOCRProvider iniciado (device=%s)", respuesta.get("device"))
        self._proceso = proceso
        return proceso

    def _comando(self, **kwargs: Any) -> Any:
        proceso = self._asegurar_proceso()
        try:
            proceso.stdin.write(json.dumps(kwargs) + "\n")
            proceso.stdin.flush()
            linea = proceso.stdout.readline()
        except (BrokenPipeError, OSError) as exc:
            raise ProveedorOCRNoDisponible(f"El proceso worker de PaddleOCR murió: {exc}") from exc
        if not linea:
            error = proceso.stderr.read() if proceso.stderr else ""
            raise ProveedorOCRNoDisponible(f"El worker de PaddleOCR cerró la conexión: {error[-2000:]}")
        respuesta = json.loads(linea)
        if not respuesta.get("ok"):
            raise RuntimeError(f"Error de PaddleOCR procesando {kwargs.get('ruta')}: {respuesta.get('error')}")
        return respuesta["resultado"]

    def leer_texto(self, ruta_imagen: str | Path) -> list[str]:
        resultado = self._comando(op="texto", ruta=str(ruta_imagen))
        return str(resultado).split("\n") if resultado else []

    def leer_bloques(self, ruta_imagen: str | Path) -> list[BloqueOCR]:
        crudos = self._comando(op="bloques", ruta=str(ruta_imagen))
        bloques = []
        for b in crudos:
            bbox = b.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            puntos = tuple((float(p[0]), float(p[1])) for p in bbox)
            conf = b.get("confianza")
            bloques.append(BloqueOCR(texto=str(b.get("texto", "")), bounding_box=puntos, confianza=float(conf) if conf is not None else 0.0))
        return bloques

    def leer_focal(
        self, ruta_imagen: str | Path, caja: tuple[float, float, float, float], allowlist: str
    ) -> dict[str, Any]:
        # allowlist se ignora: PaddleOCR no expone una lista blanca de caracteres
        # equivalente en su API publica; el recorte/margen/variantes son
        # idénticos a EasyOCRProvider, la limitación de caracteres queda del
        # lado de extraer_fecha/consenso, que ya validan el formato resultante.
        del allowlist
        return self._comando(op="focal", ruta=str(ruta_imagen), caja=list(caja))

    def cerrar(self) -> None:
        if self._proceso is not None and self._proceso.poll() is None:
            try:
                self._proceso.stdin.close()
            except OSError:
                pass
            self._proceso.terminate()
        self._proceso = None


def crear_proveedor_ocr(preferido: str = "paddleocr") -> ProveedorOCR:
    """Selecciona el proveedor OCR activo, con fallback conservador a EasyOCR.

    PaddleOCR es el proveedor principal configurable; EasyOCR queda como
    fallback temporal si Paddle no está disponible (venv ausente, worker no
    arranca, etc.) — Atlas nunca se queda sin poder leer OCR por esto.
    """
    if preferido == "easyocr":
        return EasyOCRProvider()

    proveedor = PaddleOCRProvider()
    try:
        proveedor._asegurar_proceso()
    except ProveedorOCRNoDisponible as exc:
        logger.warning("PaddleOCR no disponible, usando EasyOCR como fallback: %s", exc)
        return EasyOCRProvider()
    return proveedor
