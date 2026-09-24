"""Ingesta de PDFs de entrada para el pipeline documental canónico.

Cada página de un PDF se materializa como PNG técnico (derivado trazable) y
entra al MISMO `procesar_archivo` que ya usan las imágenes. Si la página trae
texto embebido utilizable, ese texto (con su geometría, en el espacio de
píxeles del PNG) se guarda en un sidecar y `ProveedorPaginaPdf` lo entrega a
través del contrato `ProveedorOCR` -- `leer_texto`/`leer_bloques` -- en vez
de leer OCR. Las lecturas focales (recortes) siguen yendo al OCR real sobre
el PNG. Nunca hay un segundo pipeline de extracción: sólo cambia la fuente
de las líneas/bloques que consume el extractor existente.

El PDF de origen nunca se mueve ni modifica; el manifiesto enlaza el
original, su SHA-256, cada página, su método (TEXTO_EMBEBIDO/OCR) y sus
artefactos técnicos.

Motor PDF: pypdfium2 (PDFium; BSD-3/Apache-2.0). Sus binarios oficiales se
compilan sin V8 ni XFA: no hay motor JavaScript que ejecutar.

Seguridad: sólo se renderiza la página y se lee su texto. Nunca se ejecuta
JavaScript, ni se extraen adjuntos, ni se siguen enlaces/acciones.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any


EXTENSIONES_ENTRADA_OCR = frozenset({".jpg", ".jpeg", ".png", ".pdf"})
_DIGITOS_HASH_ARTEFACTO = 16

MIME_JPEG = "image/jpeg"
MIME_PNG = "image/png"
MIME_PDF = "application/pdf"
# Tipos de documento de entrada reconocidos por su FIRMA (bytes reales),
# nunca sólo por extensión. Mismo vocabulario MIME que el contrato Mobile
# (`atlas_core.mobile.MIME_PERMITIDOS`) y el futuro contrato cloud.
MIME_DOCUMENTO_ENTRADA = (MIME_JPEG, MIME_PNG, MIME_PDF)

# Mismo límite de tamaño por documento que ya aplica la recepción Mobile
# (`atlas_core.mobile.MAX_IMAGEN_BYTES`, 28 MiB) -- no se importa de allí
# para no crear un ciclo mobile -> procesamiento_masivo -> ingesta_pdf; una
# prueba verifica que ambos valores sigan iguales.
MAX_BYTES_PDF = 28 * 1024 * 1024
# Límites NUEVOS (no existía ninguno aplicable a PDF): protegen contra un
# PDF de miles de páginas o con una página gigante (bomba de píxeles al
# renderizar). Holgados frente a guías reales (carta/A4 a 200 dpi ≈ 3,7 Mpx).
MAX_PAGINAS_PDF = 200
MAX_PIXELES_PAGINA = 40_000_000

METODO_TEXTO_EMBEBIDO = "TEXTO_EMBEBIDO"
METODO_OCR = "OCR"

# ===================================================================
# HEURÍSTICAS DE TEXTO PDF -- VALORES PROVISIONALES
#
# Elegidos sin haber visto PDFs digitales reales de AZA (las pruebas
# automáticas usan sólo PDFs sintéticos). DEBEN validarse con una muestra
# controlada de PDFs reales antes de considerarlos definitivos. Único
# lugar donde viven; `_clasificar_texto_pagina` y `_segmentos_texto_pagina`
# sólo los leen. Cambiar un valor cambia qué páginas evitan el OCR -- no
# afecta imágenes JPG/PNG ni páginas que ya se procesaron (el método usado
# queda registrado en el manifiesto de cada PDF).
#
# Una página usa su texto embebido (METODO_TEXTO_EMBEBIDO) sólo si pasa
# las tres primeras reglas; si no, va al OCR de Atlas (METODO_OCR).
# ===================================================================
# Mínimo de caracteres alfanuméricos VISIBLES. Por debajo, la página se
# considera escaneada (o casi vacía) y va al OCR.
MIN_CARACTERES_TEXTO_UTIL = 20
# Máxima proporción de caracteres ilegibles (U+FFFD, uso privado, sin
# asignar) entre los no-espacio visibles: fuentes sin mapa Unicode
# producen texto "basura" aunque visualmente la página se lea bien.
MAX_PROPORCION_CARACTERES_ILEGIBLES = 0.05
# Máxima proporción de texto invisible (modo de render 3 / opacidad 0).
# Sobre este valor se asume la capa OCR oculta de un escáner, de calidad
# desconocida, y Atlas prefiere su propio OCR sobre la imagen.
MAX_PROPORCION_TEXTO_INVISIBLE = 0.10
# Segmentación (no decide el método): dentro de una misma línea PDF, un
# hueco horizontal mayor que esta fracción de la altura de la línea separa
# segmentos -- imita cómo el OCR entrega "etiqueta" y "valor" distantes
# como cajas distintas.
FACTOR_HUECO_SEGMENTO_PDF = 1.0
_VERSION_MANIFIESTO = 2
_VERSION_TEXTO_PAGINA = 1


@dataclass(frozen=True)
class PaginaPdfRasterizada:
    """Una página PDF que puede entrar al pipeline como documento independiente."""

    pagina: int
    ruta_imagen: Path
    sha256_imagen: str
    metodo: str = METODO_OCR
    motivo_metodo: str = ""
    ruta_texto: Path | None = None


@dataclass(frozen=True)
class ErrorRasterizacionPdf:
    """Fallo técnico auditable de un PDF completo o de una página."""

    pagina: int | None
    tipo: str
    mensaje: str


@dataclass(frozen=True)
class ResultadoRasterizacionPdf:
    """Resultado completo, incluso cuando el PDF no pudo producir páginas."""

    ruta_pdf: Path
    referencia_original: str
    sha256_original: str
    paginas_declaradas: int
    paginas: tuple[PaginaPdfRasterizada, ...]
    errores: tuple[ErrorRasterizacionPdf, ...]
    ruta_manifiesto: Path

    @property
    def procesable(self) -> bool:
        return bool(self.paginas)


def es_archivo_entrada_ocr(ruta: str | Path) -> bool:
    """Indica si una entrada puede llegar al OCR tras preparar PDFs si aplica."""
    return Path(ruta).suffix.lower() in EXTENSIONES_ENTRADA_OCR


def detectar_mime_documento(ruta: str | Path) -> str | None:
    """MIME real por firma de bytes (JPEG/PNG/PDF), o None si no es ninguno.

    PDF: la especificación admite basura antes de `%PDF-` dentro del primer
    KiB, por eso se busca ahí y no sólo en el byte 0."""
    try:
        with Path(ruta).open("rb") as archivo:
            cabecera = archivo.read(1024)
    except OSError:
        return None
    if cabecera.startswith(b"\xff\xd8\xff"):
        return MIME_JPEG
    if cabecera.startswith(b"\x89PNG\r\n\x1a\n"):
        return MIME_PNG
    if b"%PDF-" in cabecera:
        return MIME_PDF
    return None


def _sha256(ruta: Path) -> str:
    digest = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            digest.update(bloque)
    return digest.hexdigest()


def _nombre_seguro(nombre: str) -> str:
    limpio = re.sub(r"[^A-Za-z0-9._-]+", "_", nombre).strip("._")
    return limpio or "documento"


def _escribir_json_si_cambio(ruta: Path, contenido: dict[str, Any]) -> None:
    serializado = json.dumps(contenido, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if ruta.is_file() and ruta.read_text(encoding="utf-8") == serializado:
        return
    temporal = ruta.with_name(ruta.name + ".tmp")
    temporal.write_text(serializado, encoding="utf-8")
    os.replace(temporal, ruta)


def _rasterizar_pagina(documento: Any, indice_cero: int, destino: Path, dpi: int) -> None:
    pagina = documento[indice_cero]
    try:
        # `get_size()` ya es el tamaño VISIBLE (con /Rotate aplicado), el
        # mismo que se renderiza.
        ancho_pt, alto_pt = pagina.get_size()
        ancho = ancho_pt * dpi / 72
        alto = alto_pt * dpi / 72
        if ancho * alto > MAX_PIXELES_PAGINA:
            raise ValueError(
                f"PaginaDemasiadoGrande: {ancho:.0f}x{alto:.0f} px supera {MAX_PIXELES_PAGINA} px"
            )
        imagen = pagina.render(scale=dpi / 72).to_pil()
        # Escritura atómica: una interrupción nunca deja un PNG truncado que un
        # reintento reutilizaría como si fuera válido.
        temporal = destino.with_name(destino.name + ".tmp")
        imagen.save(temporal, format="PNG")
        os.replace(temporal, destino)
    finally:
        pagina.close()


_CARACTER_ILEGIBLE = chr(0xFFFD)


def _es_ilegible(caracter: str) -> bool:
    return caracter == _CARACTER_ILEGIBLE or unicodedata.category(caracter) in {"Co", "Cn", "Cs"}


@dataclass(frozen=True)
class _CaracterPdf:
    """Un carácter del texto de una página tal como lo entrega PDFium."""

    caracter: str
    generado: bool  # espacio/salto que PDFium infiere; no existe en el PDF
    invisible: bool  # modo de render 3 u opacidad de relleno 0
    sin_mapa_unicode: bool  # la fuente no permite saber qué carácter es
    caja: tuple[float, float, float, float] | None  # (izq, abajo, der, arriba), espacio PDF


def _caracteres_pagina(pagina: Any) -> list[_CaracterPdf]:
    """Todos los caracteres de la página, en el orden de PDFium. Usa la API
    de bajo nivel sólo para lo que la de alto nivel no expone (modo de
    render, opacidad y error de mapa Unicode por carácter)."""
    import ctypes

    import pypdfium2.raw as pdfium_c

    textpage = pagina.get_textpage()
    try:
        salida: list[_CaracterPdf] = []
        for indice in range(textpage.count_chars()):
            codigo = pdfium_c.FPDFText_GetUnicode(textpage.raw, indice)
            generado = bool(pdfium_c.FPDFText_IsGenerated(textpage.raw, indice))
            objeto = pdfium_c.FPDFText_GetTextObject(textpage.raw, indice)
            invisible = False
            if objeto:
                if pdfium_c.FPDFTextObj_GetTextRenderMode(objeto) == pdfium_c.FPDF_TEXTRENDERMODE_INVISIBLE:
                    invisible = True
                else:
                    r, g, b, a = (ctypes.c_uint() for _ in range(4))
                    if pdfium_c.FPDFPageObj_GetFillColor(
                        objeto, ctypes.byref(r), ctypes.byref(g), ctypes.byref(b), ctypes.byref(a),
                    ) and a.value == 0:
                        invisible = True
            salida.append(_CaracterPdf(
                caracter=chr(codigo) if 0 < codigo < 0x110000 else _CARACTER_ILEGIBLE,
                generado=generado,
                invisible=invisible,
                sin_mapa_unicode=bool(pdfium_c.FPDFText_HasUnicodeMapError(textpage.raw, indice)),
                caja=None if generado else tuple(textpage.get_charbox(indice, loose=True)),
            ))
        return salida
    finally:
        textpage.close()


def _clasificar_texto_pagina(caracteres: list[_CaracterPdf]) -> tuple[bool, str]:
    """¿El texto embebido de la página es utilizable en vez de OCR?

    Sí sólo si hay al menos `MIN_CARACTERES_TEXTO_UTIL` caracteres
    alfanuméricos VISIBLES, casi ninguno ilegible (fuente sin mapa Unicode ->
    U+FFFD / uso privado) y casi nada de texto invisible (modo de render 3:
    la capa OCR oculta de un escáner, de calidad desconocida -- ante esa
    duda Atlas prefiere su propio OCR sobre la imagen). Los caracteres que
    PDFium genera (espacios/saltos inferidos) no cuentan: no están en el PDF."""
    reales = [c for c in caracteres if not c.generado]
    invisibles = sum(1 for c in reales if c.invisible)
    visibles = [c for c in reales if not c.invisible]
    if reales and invisibles / len(reales) > MAX_PROPORCION_TEXTO_INVISIBLE:
        return False, "texto_invisible_capa_ocr"
    alfanumericos = sum(1 for c in visibles if c.caracter.isalnum() and not c.sin_mapa_unicode)
    if alfanumericos < MIN_CARACTERES_TEXTO_UTIL:
        return False, "sin_texto_embebido_suficiente"
    no_espacio = [c for c in visibles if not c.caracter.isspace()]
    ilegibles = sum(1 for c in no_espacio if c.sin_mapa_unicode or _es_ilegible(c.caracter))
    if no_espacio and ilegibles / len(no_espacio) > MAX_PROPORCION_CARACTERES_ILEGIBLES:
        return False, "texto_embebido_ilegible"
    return True, "texto_embebido_utilizable"


def _transformador_a_pixeles(pagina: Any, dpi: int):
    """Función (x, y) en espacio PDF -> (x, y) en píxeles del PNG técnico:
    origen arriba-izquierda del cropbox, /Rotate aplicado (horario) y
    escala `dpi/72` -- la misma geometría que produce el render."""
    izquierda, abajo, derecha, arriba = pagina.get_cropbox()
    ancho, alto = derecha - izquierda, arriba - abajo
    rotacion = pagina.get_rotation() % 360
    escala = dpi / 72

    def transformar(x: float, y: float) -> tuple[float, float]:
        u, v = x - izquierda, arriba - y  # sin rotar, origen arriba-izquierda
        if rotacion == 90:
            u, v = alto - v, u
        elif rotacion == 180:
            u, v = ancho - u, alto - v
        elif rotacion == 270:
            u, v = v, ancho - u
        return u * escala, v * escala

    return transformar


def _segmentos_texto_pagina(pagina: Any, caracteres: list[_CaracterPdf], dpi: int) -> list[dict[str, Any]]:
    """Segmentos de texto con caja en píxeles del PNG técnico (misma
    rotación y escala que el render), en orden de lectura.

    PDFium entrega caracteres, no palabras: una palabra es una corrida de
    caracteres visibles no-espacio en la misma línea; una línea se corta en
    un salto (generado por PDFium o real) o si cambia la línea base. Dentro
    de una línea, `FACTOR_HUECO_SEGMENTO_PDF` separa segmentos igual que
    antes."""
    transformar = _transformador_a_pixeles(pagina, dpi)
    lineas: list[list[list[_CaracterPdf]]] = []  # línea -> palabras -> caracteres
    palabra: list[_CaracterPdf] = []
    linea: list[list[_CaracterPdf]] = []

    def cerrar_palabra() -> None:
        nonlocal palabra
        if palabra:
            linea.append(palabra)
        palabra = []

    def cerrar_linea() -> None:
        nonlocal linea
        cerrar_palabra()
        if linea:
            lineas.append(linea)
        linea = []

    for caracter in caracteres:
        if caracter.caracter in "\r\n":
            cerrar_linea()
            continue
        if caracter.caracter.isspace() or caracter.caja is None or caracter.invisible:
            cerrar_palabra()
            continue
        referencia = palabra[-1] if palabra else (linea[-1][-1] if linea else None)
        if referencia is not None and referencia.caja is not None:
            alto_ref = max(referencia.caja[3] - referencia.caja[1], 1.0)
            if abs(caracter.caja[1] - referencia.caja[1]) > alto_ref / 2:
                cerrar_linea()
        palabra.append(caracter)
    cerrar_linea()

    def caja_de(chars: list[_CaracterPdf]) -> tuple[float, float, float, float]:
        return (
            min(c.caja[0] for c in chars), min(c.caja[1] for c in chars),
            max(c.caja[2] for c in chars), max(c.caja[3] for c in chars),
        )

    segmentos: list[dict[str, Any]] = []
    for palabras in lineas:
        grupo: list[list[_CaracterPdf]] = []

        def cerrar_grupo() -> None:
            if not grupo:
                return
            izq, abajo, der, arriba = caja_de([c for p in grupo for c in p])
            esquinas = [transformar(x, y) for x, y in ((izq, abajo), (der, abajo), (der, arriba), (izq, arriba))]
            x0, x1 = min(e[0] for e in esquinas), max(e[0] for e in esquinas)
            y0, y1 = min(e[1] for e in esquinas), max(e[1] for e in esquinas)
            texto = unicodedata.normalize("NFC", " ".join("".join(c.caracter for c in p) for p in grupo))
            segmentos.append({"texto": texto, "caja": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]})
            grupo.clear()

        for actual in palabras:
            if grupo:
                previa = caja_de(grupo[-1])
                siguiente = caja_de(actual)
                alto = max(previa[3] - previa[1], 1.0)
                if siguiente[0] - previa[2] > FACTOR_HUECO_SEGMENTO_PDF * alto:
                    cerrar_grupo()
            grupo.append(actual)
        cerrar_grupo()
    return sorted(segmentos, key=lambda s: (round(s["caja"][0][1], 1), s["caja"][0][0]))


def _paginas_segun_pdfium_crudo(datos: bytes) -> int | None:
    """Número de páginas con la API de bajo nivel de PDFium (que sí abre un
    PDF sin páginas), o None si tampoco puede abrirlo."""
    import pypdfium2.raw as pdfium_c

    documento = pdfium_c.FPDF_LoadMemDocument(datos, len(datos), None)
    if not documento:
        return None
    try:
        return pdfium_c.FPDF_GetPageCount(documento)
    finally:
        pdfium_c.FPDF_CloseDocument(documento)


def rasterizar_pdf(
    ruta_pdf: str | Path,
    directorio_artefactos: str | Path,
    *,
    referencia_original: str | None = None,
    dpi: int = 200,
) -> ResultadoRasterizacionPdf:
    """Genera PNGs técnicos deterministas, sidecars de texto embebido y un
    manifiesto de trazabilidad.

    Nunca lanza por el contenido del archivo: un archivo que no es PDF por
    firma, vacío, demasiado grande, cifrado, corrupto o sin páginas retorna
    un resultado no procesable con manifiesto auditable. Los errores de una
    página se registran y no impiden procesar las demás.
    """
    origen = Path(ruta_pdf)
    if dpi <= 0:
        raise ValueError("dpi debe ser mayor que cero")
    if not origen.is_file():
        raise FileNotFoundError(f"No existe el PDF de entrada: {origen}")

    destino = Path(directorio_artefactos)
    destino.mkdir(parents=True, exist_ok=True)
    sha_original = _sha256(origen)
    tamano = origen.stat().st_size
    prefijo = f"{_nombre_seguro(origen.stem)}--{sha_original[:_DIGITOS_HASH_ARTEFACTO]}"
    manifiesto = destino / f"{prefijo}--manifiesto.json"
    referencia = referencia_original or origen.name
    paginas: list[PaginaPdfRasterizada] = []
    errores: list[ErrorRasterizacionPdf] = []
    paginas_declaradas = 0
    mime_detectado = detectar_mime_documento(origen)

    documento = None
    if tamano == 0:
        errores.append(ErrorRasterizacionPdf(None, "PdfVacio", "El archivo está vacío (0 bytes)."))
    elif mime_detectado != MIME_PDF:
        errores.append(ErrorRasterizacionPdf(
            None, "ArchivoNoEsPdf", f"La firma del archivo no corresponde a un PDF (detectado: {mime_detectado or 'desconocido'})."
        ))
    elif tamano > MAX_BYTES_PDF:
        errores.append(ErrorRasterizacionPdf(
            None, "PdfDemasiadoGrande", f"{tamano} bytes supera el límite de {MAX_BYTES_PDF} bytes."
        ))
    else:
        import pypdfium2 as pdfium
        import pypdfium2.raw as pdfium_c

        try:
            documento = pdfium.PdfDocument(origen)
        except pdfium.PdfiumError as error:
            # El código de error de PDFium es global y puede quedar "rancio"
            # de un documento anterior: "cifrado" exige además que el archivo
            # declare /Encrypt.
            datos = origen.read_bytes()
            if getattr(error, "err_code", None) == pdfium_c.FPDF_ERR_PASSWORD and b"/Encrypt" in datos:
                # Cifrado con contraseña de apertura: Atlas nunca intenta
                # adivinarla ni forzarla. (Un PDF sólo con contraseña de
                # permisos se abre y lee normalmente.)
                errores.append(ErrorRasterizacionPdf(None, "PdfCifrado", "El PDF está protegido con contraseña."))
            elif _paginas_segun_pdfium_crudo(datos) == 0:
                # pypdfium2 rechaza abrir un PDF bien formado sin páginas.
                errores.append(ErrorRasterizacionPdf(None, "PdfSinPaginas", "El PDF no contiene páginas."))
            else:
                errores.append(ErrorRasterizacionPdf(None, "PdfInvalido", f"PDFium no pudo abrir el documento: {error}"))
        except Exception as error:
            errores.append(ErrorRasterizacionPdf(None, type(error).__name__, str(error)))

    if documento is not None:
        try:
            paginas_declaradas = len(documento)
            if paginas_declaradas < 1:
                errores.append(ErrorRasterizacionPdf(None, "PdfSinPaginas", "El PDF no contiene páginas."))
            elif paginas_declaradas > MAX_PAGINAS_PDF:
                errores.append(ErrorRasterizacionPdf(
                    None, "PdfDemasiadasPaginas", f"{paginas_declaradas} páginas supera el límite de {MAX_PAGINAS_PDF}."
                ))
            else:
                for indice_cero in range(paginas_declaradas):
                    numero_pagina = indice_cero + 1
                    imagen = destino / f"{prefijo}--p{numero_pagina:04d}.png"
                    try:
                        if not imagen.is_file():
                            _rasterizar_pagina(documento, indice_cero, imagen, dpi)
                        pagina_pdf = documento[indice_cero]
                        try:
                            caracteres = _caracteres_pagina(pagina_pdf)
                            utilizable, motivo = _clasificar_texto_pagina(caracteres)
                            ruta_texto = None
                            if utilizable:
                                ruta_texto = destino / f"{prefijo}--p{numero_pagina:04d}--texto.json"
                                _escribir_json_si_cambio(ruta_texto, {
                                    "version": _VERSION_TEXTO_PAGINA,
                                    "original_pdf": {"referencia": referencia, "sha256": sha_original},
                                    "pagina": numero_pagina,
                                    "dpi": dpi,
                                    "segmentos": _segmentos_texto_pagina(pagina_pdf, caracteres, dpi),
                                })
                        finally:
                            pagina_pdf.close()
                        paginas.append(PaginaPdfRasterizada(
                            numero_pagina, imagen, _sha256(imagen),
                            metodo=METODO_TEXTO_EMBEBIDO if utilizable else METODO_OCR,
                            motivo_metodo=motivo, ruta_texto=ruta_texto,
                        ))
                    except Exception as error:  # una página dañada no corta las demás
                        errores.append(ErrorRasterizacionPdf(numero_pagina, type(error).__name__, str(error)))
        finally:
            documento.close()

    contenido = {
        "version": _VERSION_MANIFIESTO,
        "original_pdf": {
            "referencia": referencia, "sha256": sha_original,
            "mime_detectado": mime_detectado, "bytes": tamano,
        },
        "paginas_declaradas": paginas_declaradas,
        "paginas": [
            {
                "pagina": item.pagina,
                "imagen_tecnica": item.ruta_imagen.name,
                "sha256_imagen": item.sha256_imagen,
                "metodo": item.metodo,
                "motivo_metodo": item.motivo_metodo,
                "texto_embebido": item.ruta_texto.name if item.ruta_texto else None,
                "identificador_documento": identificador_pagina_pdf(referencia, item.pagina),
            }
            for item in paginas
        ],
        "errores": [
            {"pagina": item.pagina, "tipo": item.tipo, "mensaje": item.mensaje}
            for item in errores
        ],
    }
    _escribir_json_si_cambio(manifiesto, contenido)
    return ResultadoRasterizacionPdf(
        ruta_pdf=origen,
        referencia_original=referencia,
        sha256_original=sha_original,
        paginas_declaradas=paginas_declaradas,
        paginas=tuple(paginas),
        errores=tuple(errores),
        ruta_manifiesto=manifiesto,
    )


def directorio_evidencia_pdf_para_dataset(ruta_csv: str | Path) -> Path:
    """Carpeta de derivados PDF (PNG/manifiestos) para un dataset dado:
    ``operacion/evidencia_pdf`` en la operación real (fuera del snapshot
    ``actual``); junto al CSV en cualquier otra salida (pruebas/lotes)."""
    ruta = Path(ruta_csv)
    if ruta.parent.name == "actual" and ruta.parent.parent.name == "operacion":
        return ruta.parent.parent / "evidencia_pdf"
    return ruta.parent / "artefactos_pdf"


# Evidencia ADICIONAL: una página PDF cuya guía+transporte ya existe en el
# dataset no crea fila ni viaje nuevos (deduplicación de reingesta intacta),
# pero tampoco queda huérfana: se asocia al documento existente en este
# registro aditivo, junto a los manifiestos. Nunca reemplaza la evidencia
# original del documento (su `archivo` en el dataset no cambia).
NOMBRE_REGISTRO_EVIDENCIAS_ADICIONALES = "evidencias_adicionales.json"
MOTIVO_EVIDENCIA_REINGESTA = "REINGESTA_MISMA_GUIA_TRANSPORTE"
# Guía firmada enviada desde Atlas Mobile (rol EVIDENCIA_FIRMADA): asociada
# automáticamente (guía de referencia inequívoca) o por decisión explícita
# de una persona en Desktop.
MOTIVO_EVIDENCIA_FIRMADA_MOBILE = "EVIDENCIA_FIRMADA_MOBILE"
MOTIVO_EVIDENCIA_FIRMADA_MOBILE_MANUAL = "EVIDENCIA_FIRMADA_MOBILE_MANUAL"


def construir_asociacion_evidencia_mobile(
    *, documento: dict[str, str], envio: dict[str, Any], motivo: str, asociado_por: str = "",
) -> dict[str, Any]:
    """Registro de evidencia adicional para una foto Mobile (mismo archivo
    y mismo formato de registro que las páginas PDF). `evidencia.archivo`
    es `mobile/<envio_id>/<foto>`, que ya resuelven los resolvers Python y
    Desktop; trazabilidad de quién/cuándo/qué envío."""
    envio_id = str(envio["envio_id"])
    return {
        "documento": {
            "archivo": documento["archivo"],
            "numero_guia": documento["numero_guia"],
            "numero_transporte": documento["numero_transporte"],
        },
        "evidencia": {
            "archivo": f"mobile/{envio_id}/{envio['foto_original']}",
            "tipo": "FOTO_MOBILE",
            "sha256_imagen": str(envio.get("imagen_sha256", "")),
            "imagen_mime": str(envio.get("imagen_mime", "")),
            "envio_id": envio_id,
            "lote_id": str(envio.get("lote_id", "")),
            "chofer_id": str(envio.get("chofer_id", "")),
            "usuario": str(envio.get("usuario", "")),
            "capturado_en": str(envio.get("capturado_en", "")),
            "recibido_en": str(envio.get("recibido_en", "")),
            "evidencia_de_envio_id": str(envio.get("evidencia_de_envio_id", "")),
        },
        "motivo": motivo,
        **({"asociado_por": asociado_por} if asociado_por else {}),
    }


def leer_evidencias_adicionales(directorio: str | Path) -> list[dict[str, Any]]:
    ruta = Path(directorio) / NOMBRE_REGISTRO_EVIDENCIAS_ADICIONALES
    try:
        contenido = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    asociaciones = contenido.get("asociaciones") if isinstance(contenido, dict) else None
    return [a for a in asociaciones if isinstance(a, dict)] if isinstance(asociaciones, list) else []


def construir_asociacion_evidencia_adicional(
    *,
    documento: dict[str, str],
    identificador: str,
    ruta_original: str | Path,
    pagina: int,
    imagen_tecnica: str,
    sha256_imagen: str,
    metodo: str,
    lote: str,
) -> dict[str, Any]:
    """Registro de asociación (sin fecha de asociación): el MISMO para la
    reingesta en vivo y para la asociación retroactiva desde manifiestos."""
    referencia, _ = separar_identificador_pagina_pdf(identificador)
    return {
        "documento": {
            "archivo": documento["archivo"],
            "numero_guia": documento["numero_guia"],
            "numero_transporte": documento["numero_transporte"],
        },
        "evidencia": {
            "archivo": identificador,
            "referencia_original": referencia,
            "pagina": pagina,
            "sha256_original": _sha256(Path(ruta_original)),
            "imagen_tecnica": imagen_tecnica,
            "sha256_imagen": sha256_imagen,
            "metodo": metodo,
            "lote": lote,
        },
        "motivo": MOTIVO_EVIDENCIA_REINGESTA,
    }


def _huella_evidencia(evidencia: dict[str, Any]) -> tuple[object, object]:
    """(SHA-256 del contenido, página): PDF -> SHA del original + página;
    foto Mobile (sin PDF) -> SHA de la imagen, sin página."""
    return (evidencia.get("sha256_original") or evidencia.get("sha256_imagen"), evidencia.get("pagina"))


def _misma_asociacion(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Clave de idempotencia: (documento.archivo, SHA-256 del contenido,
    página). Reenviar el mismo archivo -- con otro nombre, lote o envío --
    nunca agrega otra asociación al mismo documento."""
    return (
        a.get("documento", {}).get("archivo") == b["documento"]["archivo"]
        and _huella_evidencia(a.get("evidencia", {})) == _huella_evidencia(b["evidencia"])
    )


def evidencia_adicional_ya_registrada(directorio: str | Path, asociacion: dict[str, Any]) -> bool:
    return any(_misma_asociacion(e, asociacion) for e in leer_evidencias_adicionales(directorio))


def registrar_evidencia_adicional(directorio: str | Path, asociacion: dict[str, Any]) -> bool:
    """Agrega `asociacion` (ver `construir_asociacion_evidencia_adicional`)
    al registro, con su fecha. Idempotente: reingresar el mismo PDF -- con
    cualquier nombre o en otro lote -- no agrega nada. Devuelve True sólo si
    creó una asociación nueva."""
    from datetime import datetime, timezone

    from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico

    carpeta = Path(directorio)
    carpeta.mkdir(parents=True, exist_ok=True)
    with bloqueo_sesion(carpeta, "evidencias_adicionales"):
        asociaciones = leer_evidencias_adicionales(carpeta)
        if any(_misma_asociacion(e, asociacion) for e in asociaciones):
            return False
        asociaciones.append({**asociacion, "asociado_en_utc": datetime.now(timezone.utc).isoformat()})
        escribir_json_atomico(
            carpeta / NOMBRE_REGISTRO_EVIDENCIAS_ADICIONALES,
            {"schema_version": 1, "asociaciones": asociaciones},
        )
    return True


_SUFIJO_PAGINA = re.compile(r"::pagina=(\d{4,})$")


def identificador_pagina_pdf(referencia: str, pagina: int) -> str:
    """Identificador persistido en la columna `archivo` del dataset para una
    página de PDF: `<referencia del PDF>::pagina=0001`."""
    return f"{referencia}::pagina={pagina:04d}"


def separar_identificador_pagina_pdf(identificador: str) -> tuple[str, int | None]:
    """Inverso de `identificador_pagina_pdf`: (referencia del original,
    número de página) -- página None si no es una página de PDF."""
    coincidencia = _SUFIJO_PAGINA.search(identificador)
    if not coincidencia:
        return identificador, None
    return identificador[: coincidencia.start()], int(coincidencia.group(1))


def leer_manifiestos_pdf(directorio: str | Path, referencia: str) -> list[dict[str, Any]]:
    """Manifiestos legibles de `directorio` cuyo original es `referencia`.
    Puede haber más de uno si el mismo nombre llegó con contenido distinto
    (sha256 distinto); el llamador decide cómo desambiguar."""
    salida = []
    carpeta = Path(directorio)
    if not carpeta.is_dir():
        return salida
    for ruta in sorted(carpeta.glob("*--manifiesto.json")):
        try:
            contenido = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(contenido, dict) and contenido.get("original_pdf", {}).get("referencia") == referencia:
            salida.append(contenido)
    return salida


PAGINA_OK = ""
PAGINA_NO_EN_MANIFIESTO = "PAGINA_NO_EN_MANIFIESTO"
PNG_FALTANTE = "PNG_FALTANTE"
PNG_CORRUPTO = "PNG_CORRUPTO"
TEXTO_FALTANTE = "TEXTO_EMBEBIDO_FALTANTE"
TEXTO_CORRUPTO = "TEXTO_EMBEBIDO_CORRUPTO"


def verificar_pagina_derivada(
    directorio: str | Path, manifiesto: dict[str, Any], pagina: int,
) -> tuple[Path | None, Path | None, str]:
    """(png, sidecar_texto, motivo) de UNA página según el manifiesto.

    Exactamente esa página (nunca otra del mismo PDF). El PNG debe existir
    y su SHA-256 coincidir con el registrado; si la página se procesó con
    texto embebido, su sidecar debe existir, ser JSON válido y pertenecer a
    esa página y a ese original. Motivo "" = todo verificado. Un manifiesto
    v1 (sin `metodo`) corresponde a una página que se procesó por OCR."""
    carpeta = Path(directorio)
    entrada = next(
        (p for p in manifiesto.get("paginas", []) if isinstance(p, dict) and p.get("pagina") == pagina), None,
    )
    if entrada is None:
        return None, None, PAGINA_NO_EN_MANIFIESTO
    png = carpeta / Path(str(entrada.get("imagen_tecnica", ""))).name
    if not png.is_file():
        return None, None, PNG_FALTANTE
    if _sha256(png) != entrada.get("sha256_imagen"):
        return None, None, PNG_CORRUPTO
    if entrada.get("metodo", METODO_OCR) != METODO_TEXTO_EMBEBIDO:
        return png, None, PAGINA_OK
    texto = carpeta / Path(str(entrada.get("texto_embebido") or "")).name
    if not entrada.get("texto_embebido") or not texto.is_file():
        return png, None, TEXTO_FALTANTE
    try:
        contenido = json.loads(texto.read_text(encoding="utf-8"))
        valido = (
            contenido.get("pagina") == pagina
            and contenido.get("original_pdf", {}).get("sha256") == manifiesto.get("original_pdf", {}).get("sha256")
            and isinstance(contenido.get("segmentos"), list)
        )
    except (OSError, ValueError, AttributeError):
        valido = False
    if not valido:
        return png, None, TEXTO_CORRUPTO
    return png, texto, PAGINA_OK


def proveedor_para_documento(
    *, ruta_texto_pdf: str | Path | None, proveedor: Any, lector_ocr: Any,
) -> tuple[Any, Any]:
    """(proveedor, lector_ocr) que `procesar_archivo` debe usar para un
    documento. Sin sidecar de texto: exactamente los recibidos (imágenes y
    páginas OCR no cambian). Con sidecar: `ProveedorPaginaPdf` sobre el
    proveedor OCR recibido (o EasyOCR con `lector_ocr` para las lecturas
    focales), y `lector_ocr=None` para que `procesar_archivo` use el
    proveedor. Único punto donde se decide -- lo usan la ingesta y los
    reparadores por igual."""
    if ruta_texto_pdf is None:
        return proveedor, lector_ocr
    if proveedor is None:
        from atlas_core.ocr_provider import EasyOCRProvider

        proveedor = EasyOCRProvider(lector_ocr)
    return ProveedorPaginaPdf(proveedor, Path(ruta_texto_pdf)), None


class ProveedorPaginaPdf:
    """Adaptador del contrato `ProveedorOCR` para una página PDF con texto
    embebido utilizable: `leer_texto`/`leer_bloques` salen del sidecar (sin
    OCR); `leer_focal` y cualquier otra lectura se delegan al proveedor OCR
    real sobre el PNG técnico. Así el extractor canónico recibe el mismo
    formato de entrada sin importar el origen."""

    def __init__(self, proveedor_ocr: Any, ruta_texto: Path) -> None:
        self._proveedor = proveedor_ocr
        self.ruta_texto = Path(ruta_texto)
        contenido = json.loads(self.ruta_texto.read_text(encoding="utf-8"))
        self._segmentos = contenido["segmentos"]
        self.configuracion = f"{METODO_TEXTO_EMBEBIDO}:{self.ruta_texto.name}"

    def leer_texto(self, ruta_imagen: str | Path) -> list[str]:
        return [segmento["texto"] for segmento in self._segmentos]

    def leer_bloques(self, ruta_imagen: str | Path) -> list[Any]:
        from atlas_core.ocr import BloqueOCR

        return [
            BloqueOCR(
                texto=segmento["texto"],
                bounding_box=tuple(tuple(punto) for punto in segmento["caja"]),
                confianza=1.0,
            )
            for segmento in self._segmentos
        ]

    def leer_focal(self, ruta_imagen: str | Path, caja: Any, allowlist: str) -> dict[str, Any]:
        return self._proveedor.leer_focal(ruta_imagen, caja, allowlist=allowlist)

    def __getattr__(self, nombre: str) -> Any:
        return getattr(self._proveedor, nombre)
