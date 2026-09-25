"""Bloque ORIENTACIÓN DOCUMENTAL -- normaliza fotos giradas 90°/180°/270°
ANTES del emparejado geométrico etiqueta->valor.

Caso real 480603/480604 (transporte 0000360179): fotos apaisadas sin EXIF
de orientación. PaddleOCR lee bien cada línea (rota solo los recortes
altos), pero TODA la geometría queda girada: el extractor asume "a la
derecha"/"debajo" y empareja cada etiqueta con el valor equivocado (guía
ausente, RUT CHOFER tomado como RUT del cliente, DESPACHAR A vacío o
contaminado con "TIPO DE DOCUMENTO", fecha de llegada como emisión).

No depende de EXIF (ya lo aplica la lectura de siempre): decide sólo con
lo que el propio OCR devuelve.
- La mayoría de los bloques de texto son VERTICALES -> la foto está a
  90°/270°: se evalúan ambas rotaciones y se elige la que deja el texto
  horizontal con más etiquetas conocidas y mejor confianza.
- Horizontal pero lectura débil (poca confianza y casi sin etiquetas) ->
  se prueba 180° y sólo se acepta si mejora con claridad.
- Cualquier otro caso (el normal): ángulo 0, sin lecturas extra, y los
  bloques ya leídos se reutilizan.
Nunca empeora: si ningún candidato es claramente mejor, se conserva la
imagen original.
"""
from __future__ import annotations

import re
import statistics
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

# Etiquetas genéricas de una guía de despacho chilena (no de un emisor ni
# de un documento en particular).
ANCLAS_DOCUMENTO = (
    "GUIA", "DESPACHO", "SENOR", "SEÑOR", "R.U.T", "RUT", "DESPACHAR",
    "TRANSPORTE", "FECHA", "EMISION", "EMISIÓN", "CHOFER", "OBRA", "DESTINO",
)

MIN_BLOQUES_EVALUABLES = 8
UMBRAL_VERTICAL = 0.6
UMBRAL_HORIZONTAL = 0.4
CONFIANZA_DEBIL = 0.9
ANCLAS_DEBILES = 5
CONFIANZA_MINIMA_CANDIDATO = 0.85
ANCLAS_MINIMAS_CANDIDATO = 3
MEJORA_ANCLAS_180 = 3
MEJORA_CONFIANZA_180 = 0.05


@dataclass(frozen=True)
class MetricasOrientacion:
    evaluables: int
    fraccion_vertical: float
    confianza: float
    anclas: int

    def como_dict(self) -> dict[str, float | int]:
        return {
            "evaluables": self.evaluables, "fraccion_vertical": round(self.fraccion_vertical, 3),
            "confianza": round(self.confianza, 3), "anclas": self.anclas,
        }


@dataclass
class ResultadoOrientacion:
    ruta_ocr: Path
    angulo_correccion: int  # grados antihorario aplicados a la imagen (PIL `rotate`)
    bloques: list | None  # bloques ya leídos en `ruta_ocr` (reutilizables), o None
    diagnostico: dict[str, Any] = field(default_factory=dict)
    directorio_temporal: Path | None = None

    def limpiar(self) -> None:
        if self.directorio_temporal is None:
            return
        for archivo in self.directorio_temporal.glob("*"):
            try:
                archivo.unlink()
            except OSError:
                pass
        try:
            self.directorio_temporal.rmdir()
        except OSError:
            pass


def _caja(bloque: Any) -> tuple[float, float] | None:
    puntos = getattr(bloque, "bounding_box", None)
    if not puntos:
        return None
    xs = [float(p[0]) for p in puntos]
    ys = [float(p[1]) for p in puntos]
    return max(xs) - min(xs), max(ys) - min(ys)


def medir_orientacion(bloques: Sequence[Any]) -> MetricasOrientacion:
    """Fracción de bloques de texto verticales, confianza media y etiquetas
    conocidas. Sólo cuentan bloques con >= 4 caracteres alfanuméricos
    (una sigla o un número suelto no dicen nada de la orientación)."""
    evaluables = []
    for bloque in bloques or []:
        caja = _caja(bloque)
        if caja is None or len(re.sub(r"\W", "", str(getattr(bloque, "texto", "")))) < 4:
            continue
        evaluables.append((bloque, caja))
    verticales = sum(1 for _, (ancho, alto) in evaluables if alto > 1.5 * ancho)
    confianzas = [float(getattr(b, "confianza", 0.0) or 0.0) for b, _ in evaluables]
    anclas = sum(
        1 for bloque in bloques or [] for ancla in ANCLAS_DOCUMENTO
        if ancla in str(getattr(bloque, "texto", "")).upper()
    )
    return MetricasOrientacion(
        evaluables=len(evaluables),
        fraccion_vertical=verticales / len(evaluables) if evaluables else 0.0,
        confianza=statistics.mean(confianzas) if confianzas else 0.0,
        anclas=anclas,
    )


def _es_imagen_rasterizable(ruta: Path) -> bool:
    try:
        from PIL import Image

        with Image.open(ruta) as imagen:
            imagen.verify()
        return True
    except Exception:
        return False


def _rotar_a_archivo(ruta: Path, angulo: int, directorio: Path) -> Path:
    """Copia girada `angulo` grados antihorario, en el MISMO espacio de
    píxeles que ya usa la lectura de siempre (EXIF aplicado) y sin EXIF,
    para que texto, bloques y lecturas focales compartan coordenadas."""
    from PIL import Image, ImageOps

    destino = directorio / f"{ruta.stem}.orientada_{angulo}.png"
    with Image.open(ruta) as imagen:
        ImageOps.exif_transpose(imagen).convert("RGB").rotate(angulo, expand=True).save(destino, format="PNG")
    return destino


def _mejor_candidato(candidatos: list[tuple[int, Path, list, MetricasOrientacion]]):
    validos = [
        c for c in candidatos
        if c[3].evaluables >= MIN_BLOQUES_EVALUABLES
        and c[3].fraccion_vertical <= UMBRAL_HORIZONTAL
        and c[3].confianza >= CONFIANZA_MINIMA_CANDIDATO
        and c[3].anclas >= ANCLAS_MINIMAS_CANDIDATO
    ]
    if not validos:
        return None
    validos.sort(key=lambda c: (c[3].anclas, c[3].confianza), reverse=True)
    # Empate exacto entre dos rotaciones: no hay evidencia para elegir.
    if len(validos) > 1 and (validos[0][3].anclas, validos[0][3].confianza) == (validos[1][3].anclas, validos[1][3].confianza):
        return None
    return validos[0]


def normalizar_orientacion(
    ruta: Path, leer_bloques: Callable[[Path], list],
) -> ResultadoOrientacion:
    """Decide el ángulo de corrección de `ruta` (ver docstring del módulo).
    Devuelve la ruta que debe leer el OCR (la original o una copia girada
    en un directorio temporal que el llamador debe `limpiar()`) y los
    bloques de esa ruta, ya leídos, para no repetir la lectura."""
    ruta = Path(ruta)
    if not _es_imagen_rasterizable(ruta):
        return ResultadoOrientacion(ruta_ocr=ruta, angulo_correccion=0, bloques=None)
    bloques_original = leer_bloques(ruta)
    original = medir_orientacion(bloques_original)
    sin_cambio = ResultadoOrientacion(ruta_ocr=ruta, angulo_correccion=0, bloques=bloques_original)
    if original.evaluables < MIN_BLOQUES_EVALUABLES:
        return sin_cambio

    if original.fraccion_vertical >= UMBRAL_VERTICAL:
        angulos = (90, 270)
    elif original.confianza < CONFIANZA_DEBIL and original.anclas < ANCLAS_DEBILES:
        angulos = (180,)
    else:
        return sin_cambio

    directorio = Path(tempfile.mkdtemp(prefix="atlas_orientacion_"))
    candidatos = []
    for angulo in angulos:
        ruta_girada = _rotar_a_archivo(ruta, angulo, directorio)
        bloques = leer_bloques(ruta_girada)
        candidatos.append((angulo, ruta_girada, bloques, medir_orientacion(bloques)))
    elegido = _mejor_candidato(candidatos)
    if elegido is not None and elegido[0] == 180 and not (
        elegido[3].anclas >= original.anclas + MEJORA_ANCLAS_180
        and elegido[3].confianza >= original.confianza + MEJORA_CONFIANZA_180
    ):
        elegido = None
    diagnostico = {
        "metodo": "GEOMETRIA_OCR",
        "original": original.como_dict(),
        "candidatos": {str(a): m.como_dict() for a, _, _, m in candidatos},
    }
    if elegido is None:
        ResultadoOrientacion(ruta_ocr=ruta, angulo_correccion=0, bloques=None, directorio_temporal=directorio).limpiar()
        sin_cambio.diagnostico = {**diagnostico, "angulo_correccion": 0, "resultado": "SIN_CANDIDATO_CLARO"}
        return sin_cambio
    angulo, ruta_girada, bloques, _ = elegido
    return ResultadoOrientacion(
        ruta_ocr=ruta_girada, angulo_correccion=angulo, bloques=bloques,
        diagnostico={**diagnostico, "angulo_correccion": angulo, "resultado": "CORREGIDA"},
        directorio_temporal=directorio,
    )
