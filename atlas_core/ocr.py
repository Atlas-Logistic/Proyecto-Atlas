"""Lectura de texto desde imágenes con EasyOCR."""

from pathlib import Path
from typing import List

try:
    import easyocr
except ImportError as exc:  # pragma: no cover - depende del entorno
    raise SystemExit(
        "EasyOCR no está instalado. Ejecute: pip install -r requirements.txt"
    ) from exc


def leer_texto_imagen(ruta_imagen: Path) -> List[str]:
    """Lee el texto contenido en una imagen usando EasyOCR."""
    # Se crea el lector de OCR con soporte para español e inglés.
    lector = easyocr.Reader(["es", "en"], gpu=False)

    # Se extrae el texto de la imagen y se filtran los resultados vacíos.
    resultados = lector.readtext(str(ruta_imagen), detail=0, paragraph=True)
    return [texto for texto in resultados if texto.strip()]
