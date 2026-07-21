"""Lectura de texto desde imágenes con EasyOCR."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Tuple, Union

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

try:
    import easyocr
except ImportError as exc:  # pragma: no cover - depende del entorno
    raise SystemExit(
        "EasyOCR no está instalado. Ejecute: pip install -r requirements.txt"
    ) from exc


PuntoOCR = Tuple[float, float]
BoundingBoxOCR = Tuple[PuntoOCR, PuntoOCR, PuntoOCR, PuntoOCR]


@dataclass(frozen=True)
class BloqueOCR:
    """Resultado OCR individual con geometría y confianza estables."""

    texto: str
    bounding_box: BoundingBoxOCR
    confianza: float


def crear_lector_ocr() -> Any:
    """Crea un lector EasyOCR que puede compartirse entre imágenes."""
    return easyocr.Reader(["es", "en"], gpu=False)


def leer_texto_imagen(
    ruta_imagen: Union[str, Path], lector: Any = None
) -> List[str]:
    """Lee el texto contenido en una imagen usando EasyOCR."""
    ruta = Path(ruta_imagen)
    if not ruta.exists():
        raise FileNotFoundError(f"La imagen no existe: {ruta}")
    if not ruta.is_file():
        raise IsADirectoryError(f"La ruta de imagen no es un archivo: {ruta}")

    try:
        with Image.open(ruta) as imagen:
            imagen_orientada = ImageOps.exif_transpose(imagen)
            arreglo_imagen = np.asarray(imagen_orientada.convert("RGB"))
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"No se pudo abrir la imagen: {ruta}") from exc

    # Se crea el lector de OCR con soporte para español e inglés.
    if lector is None:
        lector = crear_lector_ocr()

    # Se extrae el texto de la imagen y se filtran los resultados vacíos.
    resultados = lector.readtext(arreglo_imagen, detail=0, paragraph=True)
    return [texto for texto in resultados if texto.strip()]


def leer_bloques_imagen(
    ruta_imagen: Union[str, Path], lector: Any = None
) -> List[BloqueOCR]:
    """Lee bloques OCR sin perder coordenadas ni confianza."""
    ruta = Path(ruta_imagen)
    if not ruta.exists():
        raise FileNotFoundError(f"La imagen no existe: {ruta}")
    if not ruta.is_file():
        raise IsADirectoryError(f"La ruta de imagen no es un archivo: {ruta}")

    try:
        with Image.open(ruta) as imagen:
            imagen_orientada = ImageOps.exif_transpose(imagen)
            arreglo_imagen = np.asarray(imagen_orientada.convert("RGB"))
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"No se pudo abrir la imagen: {ruta}") from exc

    if lector is None:
        lector = crear_lector_ocr()

    resultados = lector.readtext(arreglo_imagen, detail=1, paragraph=False)
    bloques: List[BloqueOCR] = []
    for bounding_box, texto, confianza in resultados:
        if not str(texto).strip():
            continue
        puntos = tuple(
            (float(coordenada[0]), float(coordenada[1]))
            for coordenada in bounding_box
        )
        if len(puntos) != 4:
            raise ValueError("EasyOCR devolvió un bounding box con formato inválido")
        bloques.append(
            BloqueOCR(
                texto=str(texto),
                bounding_box=puntos,  # type: ignore[arg-type]
                confianza=float(confianza),
            )
        )
    return bloques
