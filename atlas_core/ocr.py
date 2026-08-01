"""Lectura de texto desde imágenes con EasyOCR."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Tuple, Union

import numpy as np
from PIL import Image, ImageEnhance, ImageOps, UnidentifiedImageError

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


def _leer_transporte_focal(
    ruta_imagen: Union[str, Path],
    caja: Tuple[float, float, float, float],
    lector: Any = None,
) -> dict[str, Any]:
    """Ejecuta cuatro variantes OCR sobre un recorte calculado desde una caja."""
    ruta = Path(ruta_imagen)
    if not ruta.exists():
        raise FileNotFoundError(f"La imagen no existe: {ruta}")
    if not ruta.is_file():
        raise IsADirectoryError(f"La ruta de imagen no es un archivo: {ruta}")

    try:
        with Image.open(ruta) as imagen:
            orientada = ImageOps.exif_transpose(imagen).convert("RGB")
            x1, y1, x2, y2 = (float(valor) for valor in caja)
            if not (x1 < x2 and y1 < y2):
                raise ValueError("La caja focal no tiene dimensiones válidas")
            ancho = x2 - x1
            alto = y2 - y1
            margen_x = max(4, round(ancho * 0.12))
            margen_y = max(4, round(alto * 0.35))
            recorte = (
                max(0, int(x1) - margen_x),
                max(0, int(y1) - margen_y),
                min(orientada.width, int(x2 + 0.999) + margen_x),
                min(orientada.height, int(y2 + 0.999) + margen_y),
            )
            if recorte[0] >= recorte[2] or recorte[1] >= recorte[3]:
                raise ValueError("El recorte focal quedó fuera de la imagen")
            original = orientada.crop(recorte)
            gris = ImageOps.grayscale(original)
            ampliada = original.resize(
                (original.width * 2, original.height * 2), Image.Resampling.LANCZOS
            )
            ampliada_contraste = ImageEnhance.Contrast(
                ImageOps.grayscale(ampliada)
            ).enhance(1.35)
            variantes = (
                ("original", original),
                ("grises", gris),
                ("ampliada_2x", ampliada),
                ("ampliada_2x_contraste", ampliada_contraste),
            )
            arreglos = [(nombre, np.asarray(variante)) for nombre, variante in variantes]
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"No se pudo abrir la imagen: {ruta}") from exc

    if lector is None:
        lector = crear_lector_ocr()

    def _extraer_texto_desde_resultados(resultados: Any) -> tuple[str, float | None]:
        segmentos = []
        confianzas = []
        for resultado in resultados:
            if isinstance(resultado, (list, tuple)) and len(resultado) >= 3:
                texto_resultado = str(resultado[1]).strip()
                confianza = resultado[2]
                if isinstance(confianza, (int, float)):
                    confianzas.append(float(confianza))
            else:
                texto_resultado = str(resultado).strip()
            if texto_resultado:
                segmentos.append(texto_resultado)
        texto = " ".join(segmentos)
        return texto, (min(confianzas) if confianzas else None)

    lecturas = []
    comparacion = {}
    evaluacion = {}
    for nombre, arreglo in arreglos:
        resultados = lector.readtext(
            arreglo,
            detail=1,
            paragraph=False,
            allowlist="0123456789OoDdQqIl| .-",
        )
        texto, confianza = _extraer_texto_desde_resultados(resultados)
        lecturas.append(
            {
                "variante": nombre,
                "texto": texto,
                "confianza": confianza,
                "relectura": False,
            }
        )

        texto_relectura = ""
        confianza_relectura = None
        if texto.strip():
            relectura_resultados = lector.readtext(
                arreglo,
                detail=1,
                paragraph=True,
                allowlist="0123456789OoDdQqIl| .-",
            )
            texto_relectura, confianza_relectura = _extraer_texto_desde_resultados(
                relectura_resultados
            )
            if texto_relectura and texto_relectura != texto:
                lecturas.append(
                    {
                        "variante": f"{nombre}_relectura",
                        "texto": texto_relectura,
                        "confianza": confianza_relectura,
                        "relectura": True,
                    }
                )

        coincide = texto == texto_relectura
        longitud_principal = len(texto.strip())
        longitud_relectura = len(texto_relectura.strip())
        calidad_principal = bool(texto.strip())
        calidad_relectura = bool(texto_relectura.strip())
        umbral_degradacion = max(4, longitud_principal // 2)
        conflicto_relevante = (
            calidad_principal
            and calidad_relectura
            and not coincide
            and texto_relectura != texto
            and longitud_relectura >= umbral_degradacion
            and longitud_relectura >= longitud_principal - 2
        )
        if not calidad_principal:
            motivo = "sin-lectura-principal"
            incluir_consenso = False
        elif not calidad_relectura:
            motivo = "sin-relectura"
            incluir_consenso = False
        elif coincide:
            motivo = "relectura-identica"
            incluir_consenso = False
        elif longitud_relectura < longitud_principal and longitud_relectura <= umbral_degradacion:
            motivo = "relectura-degradada"
            incluir_consenso = False
        elif conflicto_relevante:
            motivo = "conflicto-relevante"
            incluir_consenso = True
        else:
            motivo = "relectura-no-util"
            incluir_consenso = False

        comparacion[nombre] = {
            "principal": texto,
            "relectura": texto_relectura,
            "coincide": coincide,
            "candidatos": [texto, texto_relectura],
        }
        evaluacion[nombre] = {
            "incluir_en_consenso": incluir_consenso,
            "conflicto_relevante": conflicto_relevante,
            "motivo": motivo,
            "longitud_principal": longitud_principal,
            "longitud_relectura": longitud_relectura,
        }

    return {
        "recorte": recorte,
        "lecturas": lecturas,
        "comparacion": comparacion,
        "evaluacion": evaluacion,
    }
