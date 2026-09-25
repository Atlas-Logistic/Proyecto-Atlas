"""Bloque ORIENTACIÓN DOCUMENTAL -- normaliza fotos giradas 90°/180°/270°
ANTES del OCR definitivo y deja una versión operacional persistida.

Caso real 480603/480604 (transporte 0000360179): fotos apaisadas sin EXIF
de orientación. PaddleOCR lee bien cada línea (rota solo los recortes
altos), pero TODA la geometría queda girada: el extractor asume "a la
derecha"/"debajo" y empareja cada etiqueta con el valor equivocado (guía
ausente, RUT CHOFER tomado como RUT del cliente, DESPACHAR A vacío o
contaminado con "TIPO DE DOCUMENTO", fecha de llegada como emisión).

Punto de intervención: `procesamiento_masivo.procesar_archivo`, el único
lugar por el que pasa TODA imagen antes del OCR (Desktop, Mobile, páginas
PDF rasterizadas y reparadores). No depende de EXIF (ya lo aplica la
lectura de siempre) ni de las dimensiones: decide sólo con lo que el
propio OCR devuelve (geometría de las líneas, confianza y etiquetas
genéricas de guía), y la primera lectura es la misma que el pipeline
necesita igual, así que un documento derecho no cuesta ninguna lectura
extra.
- Lectura original LEGIBLE (texto horizontal, buena confianza, etiquetas
  reconocidas): ángulo 0, sin lecturas extra, sin copia.
- Mayoría de líneas VERTICALES: se evalúan 90° y 270°.
- Texto horizontal pero ilegible (típico de 180°: PaddleOCR no invierte
  líneas): se evalúa 180°.
- Lectura escasa o mixta: se evalúan las tres rotaciones.
Se acepta una rotación sólo si deja el documento legible y ninguna otra
queda cerca (margen de etiquetas); si no, abstención: se conserva la
imagen original y nunca se adivina.

Persistencia (con `directorio_persistencia`, en operación real
``<raiz_atlas>/operacion/evidencia_orientada``): el original NUNCA se
toca. Por cada contenido (SHA-256 del original) queda un registro
``<sha256>.json`` con la decisión auditable y, sólo si se corrigió, la
versión operacional ``<sha16>-<nombre>.orientada_<angulo>.png`` (PNG sin
pérdida, rotación exacta por transposición, sin EXIF, marcada con un
chunk de texto ``atlas_orientacion``). Idempotencia: reprocesar el mismo
contenido reutiliza el registro (ninguna lectura de detección, ninguna
rotación nueva) y una imagen que ya es una versión normalizada nunca se
vuelve a girar.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import statistics
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

ALGORITMO = "ORIENTACION_DOCUMENTAL_V2"
METODO = "GEOMETRIA_OCR"
# Chunk tEXt de la versión normalizada: la reconoce aunque se copie fuera
# del directorio de persistencia (idempotencia sin depender de la ruta).
CLAVE_MARCA_PNG = "atlas_orientacion"

CORREGIDA = "CORREGIDA"
SIN_ROTACION = "SIN_ROTACION"
YA_NORMALIZADA = "YA_NORMALIZADA"
ABSTENCION_AMBIGUA = "ABSTENCION_AMBIGUA"
SIN_CANDIDATO_CLARO = "SIN_CANDIDATO_CLARO"
SIN_TEXTO = "SIN_TEXTO"
NORMALIZADA_CORRUPTA = "NORMALIZADA_CORRUPTA"

# Etiquetas genéricas de una guía de despacho chilena (no de un emisor ni
# de un documento en particular).
ANCLAS_DOCUMENTO = (
    "GUIA", "DESPACHO", "SENOR", "SEÑOR", "R.U.T", "RUT", "DESPACHAR",
    "TRANSPORTE", "FECHA", "EMISION", "EMISIÓN", "CHOFER", "OBRA", "DESTINO",
)

MIN_BLOQUES_EVALUABLES = 8
UMBRAL_VERTICAL = 0.6
UMBRAL_HORIZONTAL = 0.4
CONFIANZA_MINIMA_LEGIBLE = 0.85
ANCLAS_MINIMAS_LEGIBLE = 3
# Una segunda rotación legible a menos de este margen de etiquetas de la
# mejor vuelve ambigua la decisión.
MARGEN_ANCLAS_AMBIGUEDAD = 3
# 180° parte de una lectura horizontal: debe mejorarla con claridad.
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
        shutil.rmtree(self.directorio_temporal, ignore_errors=True)


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


def es_legible(metricas: MetricasOrientacion, *, minimo_evaluables: int = 1) -> bool:
    """Texto horizontal, confianza buena y etiquetas de guía reconocidas."""
    return (
        metricas.evaluables >= minimo_evaluables
        and metricas.fraccion_vertical <= UMBRAL_HORIZONTAL
        and metricas.confianza >= CONFIANZA_MINIMA_LEGIBLE
        and metricas.anclas >= ANCLAS_MINIMAS_LEGIBLE
    )


def _angulos_a_evaluar(original: MetricasOrientacion) -> tuple[int, ...]:
    if original.fraccion_vertical >= UMBRAL_VERTICAL:
        return (90, 270)  # 180° no vuelve horizontal un texto vertical
    if original.fraccion_vertical <= UMBRAL_HORIZONTAL and original.evaluables >= MIN_BLOQUES_EVALUABLES:
        return (180,)  # 90°/270° volverían vertical un texto horizontal
    return (90, 180, 270)


def elegir_rotacion(
    original: MetricasOrientacion, candidatos: dict[int, MetricasOrientacion],
) -> tuple[int | None, str, str]:
    """(ángulo | None, resultado, criterio). None = abstención."""
    legibles = sorted(
        ((a, m) for a, m in candidatos.items() if es_legible(m, minimo_evaluables=MIN_BLOQUES_EVALUABLES)),
        key=lambda c: (c[1].anclas, c[1].confianza), reverse=True,
    )
    if not legibles:
        return None, SIN_CANDIDATO_CLARO, "ninguna rotación deja el documento legible"
    angulo, mejor = legibles[0]
    if len(legibles) > 1 and legibles[1][1].anclas > mejor.anclas - MARGEN_ANCLAS_AMBIGUEDAD:
        return None, ABSTENCION_AMBIGUA, (
            f"{angulo}° y {legibles[1][0]}° legibles con margen de etiquetas "
            f"< {MARGEN_ANCLAS_AMBIGUEDAD}"
        )
    if original.fraccion_vertical <= UMBRAL_HORIZONTAL and not (
        mejor.anclas >= original.anclas + MEJORA_ANCLAS_180
        and mejor.confianza >= original.confianza + MEJORA_CONFIANZA_180
    ):
        return None, SIN_CANDIDATO_CLARO, "la rotación no mejora con claridad una lectura ya horizontal"
    return angulo, CORREGIDA, (
        f"única rotación legible: {mejor.anclas} etiquetas, confianza {mejor.confianza:.3f}, "
        f"texto horizontal {1 - mejor.fraccion_vertical:.0%}"
    )


# ------------------------------------------------------------------ imagen

def _es_imagen_rasterizable(ruta: Path) -> bool:
    try:
        from PIL import Image

        with Image.open(ruta) as imagen:
            imagen.verify()
        return True
    except Exception:
        return False


def marca_normalizada(ruta: Path) -> dict | None:
    """Marca `atlas_orientacion` de una versión normalizada, o None."""
    try:
        from PIL import Image

        with Image.open(ruta) as imagen:
            texto = (getattr(imagen, "text", None) or {}).get(CLAVE_MARCA_PNG)
        return json.loads(texto) if texto else None
    except Exception:
        return None


_TRANSPOSICION = {90: "ROTATE_90", 180: "ROTATE_180", 270: "ROTATE_270"}


def _rotar_a_archivo(ruta: Path, angulo: int, destino: Path, marca: dict | None = None) -> Path:
    """Copia girada `angulo` grados antihorario, en el MISMO espacio de
    píxeles que ya usa la lectura de siempre (EXIF aplicado) y sin EXIF,
    para que texto, bloques y lecturas focales compartan coordenadas.
    Transposición exacta + PNG: ninguna pérdida ni recompresión."""
    from PIL import Image, ImageOps, PngImagePlugin

    info = PngImagePlugin.PngInfo()
    if marca is not None:
        info.add_text(CLAVE_MARCA_PNG, json.dumps(marca, sort_keys=True))
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(f".{destino.name}.tmp")
    with Image.open(ruta) as imagen:
        girada = ImageOps.exif_transpose(imagen).convert("RGB").transpose(
            getattr(Image.Transpose, _TRANSPOSICION[angulo])
        )
        girada.save(temporal, format="PNG", pnginfo=info)
    os.replace(temporal, destino)
    return destino


def sha256_archivo(ruta: Path) -> str:
    digest = hashlib.sha256()
    with Path(ruta).open("rb") as flujo:
        for bloque in iter(lambda: flujo.read(1024 * 1024), b""):
            digest.update(bloque)
    return digest.hexdigest()


# ------------------------------------------------------------ persistencia

def directorio_orientacion_para_raiz(raiz_atlas: str | Path) -> Path:
    """``<raiz_atlas>/operacion/evidencia_orientada`` -- hermana de
    ``evidencia_pdf``/``trazas_ocr``, fuera del snapshot ``actual``."""
    return Path(raiz_atlas) / "operacion" / "evidencia_orientada"


def _ruta_registro(directorio: Path, sha: str) -> Path:
    return directorio / f"{sha}.json"


def leer_registro(directorio: str | Path, sha: str) -> dict | None:
    try:
        contenido = json.loads(_ruta_registro(Path(directorio), sha).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return contenido if isinstance(contenido, dict) and contenido.get("sha256_original") == sha else None


def _escribir_registro(directorio: Path, registro: dict) -> None:
    from atlas_core.almacenamiento_portable import escribir_json_atomico

    escribir_json_atomico(_ruta_registro(directorio, registro["sha256_original"]), registro)


def version_normalizada_verificada(directorio: str | Path, registro: dict) -> Path | None:
    """Ruta de la versión normalizada del registro si existe y su SHA-256
    coincide; None si no corresponde, falta o está alterada."""
    version = registro.get("version_normalizada") if registro.get("resultado") == CORREGIDA else None
    if not isinstance(version, dict):
        return None
    ruta = Path(directorio) / Path(str(version.get("archivo", ""))).name
    if not ruta.is_file() or sha256_archivo(ruta) != version.get("sha256"):
        return None
    return ruta


def ruta_operacional(raiz_atlas: str | Path, ruta_original: str | Path) -> Path:
    """Versión que debe mostrarse/usarse operacionalmente para un original:
    la normalizada verificada si existe, si no el propio original."""
    ruta_original = Path(ruta_original)
    directorio = directorio_orientacion_para_raiz(raiz_atlas)
    registro = leer_registro(directorio, sha256_archivo(ruta_original)) if directorio.is_dir() else None
    normalizada = version_normalizada_verificada(directorio, registro) if registro else None
    return normalizada or ruta_original


def _nombre_normalizado(ruta: Path, sha: str, angulo: int) -> str:
    base = re.sub(r"[^\w.-]", "_", ruta.stem)[:60] or "documento"
    return f"{sha[:16]}-{base}.orientada_{angulo}.png"


# ---------------------------------------------------------------- decisión

def normalizar_orientacion(
    ruta: Path, leer_bloques: Callable[[Path], list], *,
    directorio_persistencia: str | Path | None = None,
    referencia: str | None = None,
    reloj: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> ResultadoOrientacion:
    """Decide el ángulo de corrección de `ruta` (ver docstring del módulo).

    Devuelve la ruta que debe leer el OCR y, si ya se leyeron, los bloques
    de esa ruta (para no repetir la lectura). Sin `directorio_persistencia`
    la copia girada vive en un directorio temporal que el llamador debe
    `limpiar()`; con él, queda persistida junto a su registro auditable."""
    ruta = Path(ruta)
    if not _es_imagen_rasterizable(ruta):
        return ResultadoOrientacion(ruta_ocr=ruta, angulo_correccion=0, bloques=None)

    marca = marca_normalizada(ruta)
    if marca is not None:
        # Ya es una versión normalizada por Atlas: nunca una segunda rotación.
        return ResultadoOrientacion(ruta_ocr=ruta, angulo_correccion=0, bloques=None, diagnostico={
            "algoritmo": ALGORITMO, "metodo": METODO, "resultado": YA_NORMALIZADA,
            "angulo_correccion": 0, "sha256_original": marca.get("sha256_original"),
        })

    directorio = Path(directorio_persistencia) if directorio_persistencia is not None else None
    sha = sha256_archivo(ruta) if directorio is not None else None
    if directorio is not None:
        previo = leer_registro(directorio, sha)
        if previo is not None and previo.get("algoritmo") == ALGORITMO:
            return _reutilizar_registro(ruta, directorio, previo, referencia)

    bloques_original = leer_bloques(ruta)
    original = medir_orientacion(bloques_original)
    diagnostico: dict[str, Any] = {"algoritmo": ALGORITMO, "metodo": METODO, "original": original.como_dict()}

    def _cerrar(resultado: ResultadoOrientacion) -> ResultadoOrientacion:
        if directorio is not None:
            registro = _construir_registro(ruta, sha, referencia, resultado, reloj)
            _escribir_registro(directorio, registro)
            resultado.diagnostico = _diagnostico_desde_registro(registro)
        return resultado

    if es_legible(original):
        # El caso normal: sin lecturas extra, sin copia. Sin persistencia no
        # hay nada que auditar (comportamiento previo intacto).
        derecho = ResultadoOrientacion(ruta_ocr=ruta, angulo_correccion=0, bloques=bloques_original)
        if directorio is None:
            return derecho
        derecho.diagnostico = {**diagnostico, "angulo_correccion": 0, "resultado": SIN_ROTACION,
                               "criterio": "lectura original legible y horizontal"}
        return _cerrar(derecho)
    if not bloques_original:
        return _cerrar(ResultadoOrientacion(
            ruta_ocr=ruta, angulo_correccion=0, bloques=bloques_original,
            diagnostico={**diagnostico, "angulo_correccion": 0, "resultado": SIN_TEXTO,
                         "criterio": "el OCR no encontró texto: no hay evidencia de orientación"},
        ))

    temporal = Path(tempfile.mkdtemp(prefix="atlas_orientacion_"))
    candidatos: dict[int, tuple[Path, list, MetricasOrientacion]] = {}
    for angulo in _angulos_a_evaluar(original):
        ruta_girada = _rotar_a_archivo(ruta, angulo, temporal / f"{ruta.stem}.orientada_{angulo}.png")
        bloques = leer_bloques(ruta_girada)
        candidatos[angulo] = (ruta_girada, bloques, medir_orientacion(bloques))
    angulo, resultado, criterio = elegir_rotacion(original, {a: c[2] for a, c in candidatos.items()})
    diagnostico.update(
        candidatos={str(a): c[2].como_dict() for a, c in candidatos.items()},
        resultado=resultado, criterio=criterio, angulo_correccion=angulo or 0,
    )
    if angulo is None:
        shutil.rmtree(temporal, ignore_errors=True)
        return _cerrar(ResultadoOrientacion(
            ruta_ocr=ruta, angulo_correccion=0, bloques=bloques_original, diagnostico=diagnostico,
        ))

    ruta_girada, bloques, _ = candidatos[angulo]
    if directorio is None:
        return ResultadoOrientacion(
            ruta_ocr=ruta_girada, angulo_correccion=angulo, bloques=bloques,
            diagnostico=diagnostico, directorio_temporal=temporal,
        )
    persistida = _rotar_a_archivo(
        ruta, angulo, directorio / _nombre_normalizado(ruta, sha, angulo),
        marca={"sha256_original": sha, "angulo_correccion": angulo, "algoritmo": ALGORITMO},
    )
    shutil.rmtree(temporal, ignore_errors=True)
    return _cerrar(ResultadoOrientacion(
        ruta_ocr=persistida, angulo_correccion=angulo, bloques=bloques, diagnostico=diagnostico,
    ))


def _construir_registro(
    ruta: Path, sha: str, referencia: str | None, resultado: ResultadoOrientacion,
    reloj: Callable[[], datetime],
) -> dict:
    diagnostico = resultado.diagnostico
    angulo = resultado.angulo_correccion
    decidido = diagnostico.get("resultado") in (CORREGIDA, SIN_ROTACION)
    version = None
    if angulo:
        version = {"archivo": resultado.ruta_ocr.name, "sha256": sha256_archivo(resultado.ruta_ocr)}
    return {
        "algoritmo": ALGORITMO,
        "metodo": METODO,
        "sha256_original": sha,
        "nombre_original": ruta.name,
        "referencias": [referencia or ruta.name],
        "resultado": diagnostico.get("resultado"),
        # Giro que TENÍA el documento respecto de derecho (horario) = giro
        # antihorario que se le aplicó para corregirlo. None si se abstuvo.
        "orientacion_detectada_grados_horario": angulo if decidido else None,
        "rotacion_aplicada_grados_antihorario": angulo,
        "criterio": diagnostico.get("criterio", ""),
        "evidencia": {"original": diagnostico.get("original"), "candidatos": diagnostico.get("candidatos", {})},
        "version_normalizada": version,
        "registrado_utc": reloj().astimezone(timezone.utc).isoformat(),
    }


def _diagnostico_desde_registro(registro: dict, **extra: Any) -> dict:
    return {
        "algoritmo": registro.get("algoritmo"), "metodo": registro.get("metodo"),
        "resultado": registro.get("resultado"), "criterio": registro.get("criterio", ""),
        "angulo_correccion": int(registro.get("rotacion_aplicada_grados_antihorario") or 0),
        "orientacion_detectada_grados_horario": registro.get("orientacion_detectada_grados_horario"),
        "original": (registro.get("evidencia") or {}).get("original"),
        "candidatos": (registro.get("evidencia") or {}).get("candidatos", {}),
        "sha256_original": registro.get("sha256_original"),
        "version_normalizada": registro.get("version_normalizada"),
        **extra,
    }


def _reutilizar_registro(ruta: Path, directorio: Path, registro: dict, referencia: str | None) -> ResultadoOrientacion:
    """Mismo contenido ya decidido: sin lecturas de detección ni rotación nueva."""
    referencia = referencia or ruta.name
    if referencia not in registro.get("referencias", []):
        registro["referencias"] = [*registro.get("referencias", []), referencia]
        _escribir_registro(directorio, registro)
    angulo = int(registro.get("rotacion_aplicada_grados_antihorario") or 0)
    if registro.get("resultado") != CORREGIDA or not angulo:
        return ResultadoOrientacion(
            ruta_ocr=ruta, angulo_correccion=0, bloques=None,
            diagnostico=_diagnostico_desde_registro(registro, reutilizado=True),
        )
    normalizada = version_normalizada_verificada(directorio, registro)
    if normalizada is None:
        version = registro.get("version_normalizada") or {}
        destino = directorio / Path(str(version.get("archivo", ""))).name
        if destino.name and not destino.exists():
            # Falta (nunca alterada): se regenera con la misma transposición
            # determinista desde el original, que nunca se toca.
            normalizada = _rotar_a_archivo(ruta, angulo, destino, marca={
                "sha256_original": registro["sha256_original"], "angulo_correccion": angulo, "algoritmo": ALGORITMO,
            })
            registro["version_normalizada"] = {"archivo": destino.name, "sha256": sha256_archivo(destino)}
            _escribir_registro(directorio, registro)
        else:
            # Existe pero no coincide con su hash: nunca se usa ni se reescribe.
            return ResultadoOrientacion(
                ruta_ocr=ruta, angulo_correccion=0, bloques=None,
                diagnostico=_diagnostico_desde_registro(
                    registro, reutilizado=True, resultado=NORMALIZADA_CORRUPTA, angulo_correccion=0,
                ),
            )
    return ResultadoOrientacion(
        ruta_ocr=normalizada, angulo_correccion=angulo, bloques=None,
        diagnostico=_diagnostico_desde_registro(registro, reutilizado=True),
    )
