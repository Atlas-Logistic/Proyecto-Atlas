"""Lectura de texto desde imágenes con EasyOCR."""

from pathlib import Path
from typing import List, Union

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

try:
    import easyocr
except ImportError as exc:  # pragma: no cover - depende del entorno
    raise SystemExit(
        "EasyOCR no está instalado. Ejecute: pip install -r requirements.txt"
    ) from exc


def leer_texto_imagen(ruta_imagen: Union[str, Path]) -> List[str]:
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
    lector = easyocr.Reader(["es", "en"], gpu=False)

    # Se extrae el texto de la imagen y se filtran los resultados vacíos.
    resultados = lector.readtext(arreglo_imagen, detail=0, paragraph=True)
    return [texto for texto in resultados if texto.strip()]
