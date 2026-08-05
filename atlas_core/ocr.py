"""Lectura de texto desde imágenes con EasyOCR."""

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Iterable, List, Tuple, Union

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, UnidentifiedImageError

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


def _normalizar_etiqueta_ocr(texto: object) -> str:
    normalizado = str(texto or "").upper().replace("Ñ", "N")
    return "".join(caracter for caracter in normalizado if caracter.isalnum())


def _rut_chileno_canonico(texto: object) -> str | None:
    limpio = "".join(
        caracter for caracter in str(texto or "").upper()
        if caracter.isdigit() or caracter == "K"
    )
    if len(limpio) not in {8, 9} or not limpio[:-1].isdigit():
        return None
    base, digito = limpio[:-1], limpio[-1]
    suma = 0
    factor = 2
    for caracter in reversed(base):
        suma += int(caracter) * factor
        factor = factor + 1 if factor < 7 else 2
    resto = 11 - suma % 11
    esperado = "0" if resto == 11 else "K" if resto == 10 else str(resto)
    return f"{base}-{digito}" if digito == esperado else None


def _consensuar_rut_cliente_focal(lecturas: Iterable[object]) -> dict[str, object]:
    """Acepta solo un RUT válido repetido y abstiene ante cualquier conflicto."""
    candidatos = []
    patron = re.compile(
        r"(?<!\d)(?:\d{7,8}|\d{1,3}(?:[.\s]+\d{3}){2})\s*-\s*[\dKk](?!\w)"
    )
    for lectura in lecturas:
        encontrados = {
            candidato
            for coincidencia in patron.findall(str(lectura or ""))
            if (candidato := _rut_chileno_canonico(coincidencia)) is not None
        }
        candidatos.extend(sorted(encontrados))
    unicos = sorted(set(candidatos))
    if len(unicos) > 1:
        return {"valor": None, "motivo": "conflicto-ruts-validos", "candidatos": unicos}
    if not unicos or candidatos.count(unicos[0]) < 2:
        return {
            "valor": None,
            "motivo": "sin-consenso-suficiente",
            "candidatos": unicos,
        }
    return {"valor": unicos[0], "motivo": "consenso-modulo-11", "candidatos": unicos}


def _localizar_fila_rut_cliente(
    bloques: Iterable[BloqueOCR], ancho: int, alto: int
) -> tuple[float, float, float, float] | None:
    bloques_lista = list(bloques)
    senores = [
        bloque for bloque in bloques_lista
        if "SENOR" in _normalizar_etiqueta_ocr(bloque.texto)
    ]
    etiquetas_rut = [
        bloque for bloque in bloques_lista
        if _normalizar_etiqueta_ocr(bloque.texto) == "RUT"
    ]
    pares = []
    for senor in senores:
        sx = min(punto[0] for punto in senor.bounding_box)
        sy = min(punto[1] for punto in senor.bounding_box)
        sh = max(punto[1] for punto in senor.bounding_box) - sy
        for rut in etiquetas_rut:
            rx1 = min(punto[0] for punto in rut.bounding_box)
            rx2 = max(punto[0] for punto in rut.bounding_box)
            ry1 = min(punto[1] for punto in rut.bounding_box)
            ry2 = max(punto[1] for punto in rut.bounding_box)
            distancia_y = ry1 - sy
            if 0 <= distancia_y <= max(100.0, sh * 5) and abs(rx1 - sx) <= 140:
                pares.append((distancia_y, rut, rx2, ry1, ry2))
    if not pares:
        return None
    _, _, rx2, ry1, ry2 = min(pares, key=lambda item: item[0])
    altura = max(ry2 - ry1, 12.0)
    x1 = max(0.0, rx2 + ancho * 0.035)
    x2 = min(float(ancho), max(x1 + 120.0, ancho * 0.60))
    y1 = max(0.0, ry1 - altura * 0.65)
    y2 = min(float(alto), ry2 + altura * 0.85)
    return x1, y1, x2, y2


def _leer_rut_cliente_focal(
    ruta_imagen: Union[str, Path],
    bloques: Iterable[BloqueOCR],
    lector: Any = None,
) -> dict[str, object]:
    """Relee únicamente la fila de RUT asociada a SEÑOR(ES)."""
    ruta = Path(ruta_imagen)
    if not ruta.exists():
        raise FileNotFoundError(f"La imagen no existe: {ruta}")
    if not ruta.is_file():
        raise IsADirectoryError(f"La ruta de imagen no es un archivo: {ruta}")
    try:
        with Image.open(ruta) as imagen:
            orientada = ImageOps.exif_transpose(imagen).convert("RGB")
            caja = _localizar_fila_rut_cliente(bloques, orientada.width, orientada.height)
            if caja is None:
                return {"valor": None, "motivo": "fila-rut-cliente-no-localizada", "lecturas": []}
            x1, y1, x2, y2 = caja
            recorte = orientada.crop((int(x1), int(y1), int(x2), int(y2)))
            ampliada = recorte.resize(
                (recorte.width * 3, recorte.height * 3), Image.Resampling.LANCZOS
            )
            gris = ImageOps.grayscale(ampliada)
            contraste = ImageEnhance.Contrast(gris).enhance(1.6)
            umbral = gris.point(lambda valor: 255 if valor >= 175 else 0)
            variantes = (
                ("ampliada_3x", ampliada),
                ("grises_3x", gris),
                ("contraste_3x", contraste),
                ("umbral_3x", umbral),
            )
            arreglos = [(nombre, np.asarray(variante)) for nombre, variante in variantes]
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"No se pudo abrir la imagen: {ruta}") from exc
    if lector is None:
        lector = crear_lector_ocr()
    lecturas = []
    for nombre, arreglo in arreglos:
        resultados = lector.readtext(
            arreglo,
            detail=0,
            paragraph=False,
            allowlist="0123456789Kk.- ",
        )
        texto = " ".join(str(resultado).strip() for resultado in resultados).strip()
        lecturas.append({"variante": nombre, "texto": texto})
    consenso = _consensuar_rut_cliente_focal(
        lectura["texto"] for lectura in lecturas
    )
    return {**consenso, "lecturas": lecturas, "recorte": tuple(round(v) for v in caja)}


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


def leer_encabezado_origen_focal(
    ruta_imagen: Union[str, Path], lector: Any = None, *, grados_adicionales: int = 0
) -> List[str]:
    """Relee el encabezado del emisor sin interpretar ni completar su contenido.

    ``grados_adicionales`` gira la imagen (sentido antihorario, vía
    ``Image.rotate``) antes de recortar el encabezado. Existe exclusivamente
    para compensar fotografías cuya orientación real no queda reflejada en su
    metadato EXIF; no reinterpreta ni corrige el contenido leído, solo cambia
    el encuadre desde el que se recorta.
    """
    ruta = Path(ruta_imagen)
    if grados_adicionales % 360 not in (0, 90, 180, 270):
        raise ValueError("grados_adicionales debe ser 0, 90, 180 o 270")
    try:
        with Image.open(ruta) as imagen:
            gris = ImageOps.exif_transpose(imagen).convert("L")
            if grados_adicionales % 360:
                gris = gris.rotate(grados_adicionales, expand=True)
            ancho, alto = gris.size
            recorte = gris.crop((
                int(ancho * 0.07), int(alto * 0.10),
                int(ancho * 0.62), int(alto * 0.24),
            )).resize((int(ancho * 1.65), int(alto * 0.42)))
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"No se pudo abrir la imagen: {ruta}") from exc
    if lector is None:
        lector = crear_lector_ocr()
    variantes = (
        recorte,
        ImageEnhance.Contrast(recorte).enhance(2.2),
        ImageEnhance.Contrast(recorte.filter(ImageFilter.SHARPEN)).enhance(2.5),
    )
    lecturas = []
    for variante in variantes:
        resultados = lector.readtext(
            np.asarray(variante), detail=0, paragraph=False
        )
        lecturas.append(" ".join(str(valor).strip() for valor in resultados))
    return lecturas


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
