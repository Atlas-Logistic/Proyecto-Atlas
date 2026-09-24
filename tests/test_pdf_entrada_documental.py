"""PDF como documento de ENTRADA (no generación de informes).

Todo sintético en `tmp_path` -- nunca guías reales ni G:\\. Cubre: firma
real vs extensión, texto embebido vs escaneado (y capa OCR invisible), PDF
mixto y multipágina, tildes/ñ, corrupto/vacío/cifrado, contenido activo,
convergencia al `procesar_archivo` canónico, idempotencia y reanudación
tras interrupción, y que JPG/PNG sigan exactamente igual."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from atlas_core import ingesta_pdf
from atlas_core.ingesta_pdf import (
    MAX_BYTES_PDF, METODO_OCR, METODO_TEXTO_EMBEBIDO, MIME_JPEG, MIME_PDF, MIME_PNG,
    ProveedorPaginaPdf, detectar_mime_documento, rasterizar_pdf, separar_identificador_pagina_pdf,
)
from atlas_core.mobile import MAX_IMAGEN_BYTES
from atlas_core.procesamiento_masivo import procesar_carpeta
from tests.fixtures_pdf_sinteticos import (
    PaginaSintetica, construir_pdf, jpeg_escaneado, pagina_escaneada, pagina_texto,
)

TEXTO_GUIA = [
    "GUIA DE DESPACHO ELECTRONICA",
    "N° {guia}",
    "SEÑOR(ES): CONSTRUCTORA ÑUÑOA LIMITADA",
    "DESPACHAR A: AVENIDA JOSÉ MIGUEL CARRERA 1234, PEÑALOLÉN",
]


# ------------------------------------------------------------ fixtures

@pytest.fixture(autouse=True)
def _sin_atlas_ia_por_red(monkeypatch):
    """`procesar_carpeta` crea el orquestador B1 real si hay GROQ_API_KEY;
    estas pruebas nunca deben enviar nada a un servicio externo."""
    monkeypatch.setenv("ATLAS_IA_B1_OPERACIONAL", "0")


def _pagina_guia(guia: str, **extra) -> PaginaSintetica:
    return pagina_texto(*(linea.format(guia=guia) for linea in TEXTO_GUIA), **extra)


def _pdf(ruta: Path, paginas: list[tuple[str, str]], **opciones) -> Path:
    """paginas: [("texto"|"escaneada"|"escaneada_capa", guia), ...]"""
    construidas = [
        _pagina_guia(guia) if tipo == "texto"
        else pagina_escaneada(
            f"GUIA {guia}",
            capa_invisible="N° 999999 CAPA OCR INVISIBLE DEL ESCANER" if tipo == "escaneada_capa" else None,
        )
        for tipo, guia in paginas
    ]
    ruta.write_bytes(construir_pdf(construidas, **opciones))
    return ruta


def _filas(ruta_csv: Path) -> list[dict[str, str]]:
    with ruta_csv.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _procesador_registrador(vistas: list[Path]):
    def procesador(ruta: Path) -> dict[str, str]:
        vistas.append(ruta)
        return {"numero_guia": f"G{len(vistas)}", "numero_transporte": f"T{len(vistas)}"}
    return procesador


class OCRFalso:
    """Proveedor OCR de prueba: registra qué imágenes se leyeron por OCR."""

    def __init__(self) -> None:
        self.leer_texto_llamadas: list[Path] = []

    def leer_texto(self, ruta_imagen):
        self.leer_texto_llamadas.append(Path(ruta_imagen))
        return ["GUIA DE DESPACHO ELECTRONICA", "N° 500001"]

    def leer_bloques(self, ruta_imagen):
        return []

    def leer_focal(self, ruta_imagen, caja, allowlist):
        return {"recorte": None, "lecturas": []}


# ------------------------------------------------------------ firma / MIME

def test_detecta_tipo_real_por_firma_no_por_extension(tmp_path: Path) -> None:
    jpg = tmp_path / "a.jpg"; Image.new("RGB", (5, 5)).save(jpg, format="JPEG")
    png = tmp_path / "b.png"; Image.new("RGB", (5, 5)).save(png, format="PNG")
    pdf_disfrazado = _pdf(tmp_path / "c.jpg", [("texto", "1")])
    falso_pdf = tmp_path / "d.pdf"; falso_pdf.write_text("hola, no soy un PDF", encoding="utf-8")
    assert detectar_mime_documento(jpg) == MIME_JPEG
    assert detectar_mime_documento(png) == MIME_PNG
    assert detectar_mime_documento(pdf_disfrazado) == MIME_PDF
    assert detectar_mime_documento(falso_pdf) is None


def test_limite_de_tamano_pdf_es_el_mismo_que_mobile() -> None:
    assert MAX_BYTES_PDF == MAX_IMAGEN_BYTES


# ------------------------------------------------------------ texto embebido vs escaneado

def test_pdf_una_pagina_con_texto_embebido_usa_el_texto_y_conserva_tildes(tmp_path: Path) -> None:
    original = _pdf(tmp_path / "guia.pdf", [("texto", "472623")])
    bytes_originales = original.read_bytes()
    resultado = rasterizar_pdf(original, tmp_path / "art")

    (pagina,) = resultado.paginas
    assert pagina.metodo == METODO_TEXTO_EMBEBIDO
    assert original.read_bytes() == bytes_originales
    proveedor = ProveedorPaginaPdf(OCRFalso(), pagina.ruta_texto)
    lineas = proveedor.leer_texto(pagina.ruta_imagen)
    assert "N° 472623" in lineas
    assert "SEÑOR(ES): CONSTRUCTORA ÑUÑOA LIMITADA" in lineas
    assert any("JOSÉ MIGUEL CARRERA" in linea and "PEÑALOLÉN" in linea for linea in lineas)
    # Las cajas están en píxeles del PNG técnico (200 dpi), dentro de la imagen.
    ancho, alto = Image.open(pagina.ruta_imagen).size
    for bloque in proveedor.leer_bloques(pagina.ruta_imagen):
        (x0, y0), _, (x1, y1), _ = bloque.bounding_box
        assert 0 <= x0 < x1 <= ancho and 0 <= y0 < y1 <= alto


def test_pdf_armado_desde_fotos_multipagina_va_entero_a_ocr(tmp_path: Path) -> None:
    """Uso real actual: fotos de guías convertidas a PDF (p. ej. iLovePDF) --
    páginas que son sólo imagen. Se arma con el escritor PDF de Pillow."""
    fotos = [Image.open(io.BytesIO(jpeg_escaneado(f"GUIA {n}", (1200, 1600)))) for n in (1, 2)]
    ruta = tmp_path / "fotos.pdf"
    fotos[0].save(ruta, format="PDF", save_all=True, append_images=fotos[1:], resolution=150)
    resultado = rasterizar_pdf(ruta, tmp_path / "art")
    assert [p.metodo for p in resultado.paginas] == [METODO_OCR, METODO_OCR]
    assert all(Image.open(p.ruta_imagen).size[0] > 1000 for p in resultado.paginas)


def test_pdf_una_pagina_escaneada_va_a_ocr(tmp_path: Path) -> None:
    resultado = rasterizar_pdf(_pdf(tmp_path / "scan.pdf", [("escaneada", "1")]), tmp_path / "art")
    (pagina,) = resultado.paginas
    assert pagina.metodo == METODO_OCR and pagina.ruta_texto is None
    assert pagina.motivo_metodo == "sin_texto_embebido_suficiente"


def test_escaneo_con_capa_ocr_invisible_prefiere_ocr_de_atlas(tmp_path: Path) -> None:
    resultado = rasterizar_pdf(_pdf(tmp_path / "scan.pdf", [("escaneada_capa", "1")]), tmp_path / "art")
    assert resultado.paginas[0].metodo == METODO_OCR
    assert resultado.paginas[0].motivo_metodo == "texto_invisible_capa_ocr"


def test_texto_de_pagina_rotada_queda_dentro_del_png(tmp_path: Path) -> None:
    ruta = tmp_path / "rotada.pdf"
    ruta.write_bytes(construir_pdf([_pagina_guia("472623", rotacion=90)]))
    (pagina,) = rasterizar_pdf(ruta, tmp_path / "art").paginas
    ancho, alto = Image.open(pagina.ruta_imagen).size
    assert ancho > alto  # A4 rotado 90°
    for bloque in ProveedorPaginaPdf(OCRFalso(), pagina.ruta_texto).leer_bloques(pagina.ruta_imagen):
        (x0, y0), _, (x1, y1), _ = bloque.bounding_box
        assert 0 <= x0 < x1 <= ancho and 0 <= y0 < y1 <= alto


# ------------------------------------------------------------ multipágina / mixto (pipeline real)

@pytest.mark.parametrize("tipos, metodos", [
    (["texto", "texto", "texto"], [METODO_TEXTO_EMBEBIDO] * 3),
    (["escaneada", "escaneada"], [METODO_OCR] * 2),
    (["texto", "escaneada", "texto"], [METODO_TEXTO_EMBEBIDO, METODO_OCR, METODO_TEXTO_EMBEBIDO]),
])
def test_multipagina_y_mixto_una_fila_por_pagina_con_metodo_por_pagina(tmp_path, tipos, metodos) -> None:
    entrada = tmp_path / "entrada"; entrada.mkdir()
    _pdf(entrada / "lote.pdf", [(tipo, str(472600 + i)) for i, tipo in enumerate(tipos)])
    ocr = OCRFalso()

    resumen = procesar_carpeta(entrada, tmp_path / "salida.csv", proveedor=ocr, cada=1)

    filas = _filas(tmp_path / "salida.csv")
    assert resumen["procesados"] == len(tipos) and resumen["errores"] == 0
    assert [f["archivo"] for f in filas] == [f"lote.pdf::pagina={i:04d}" for i in range(1, len(tipos) + 1)]
    # Convergencia: el MISMO extractor canónico lee la guía desde el texto
    # embebido; sólo las páginas OCR pasan por `leer_texto` del OCR.
    for i, (fila, metodo) in enumerate(zip(filas, metodos)):
        esperado = str(472600 + i) if metodo == METODO_TEXTO_EMBEBIDO else "500001"
        assert fila["numero_guia"] == esperado, fila["archivo"]
    assert len(ocr.leer_texto_llamadas) == metodos.count(METODO_OCR)

    (manifiesto,) = (tmp_path / "artefactos_pdf").glob("*--manifiesto.json")
    contenido = json.loads(manifiesto.read_text(encoding="utf-8"))
    assert [p["metodo"] for p in contenido["paginas"]] == metodos
    assert [p["identificador_documento"] for p in contenido["paginas"]] == [f["archivo"] for f in filas]
    assert contenido["original_pdf"]["mime_detectado"] == MIME_PDF


def test_traza_ocr_registra_que_la_fuente_fue_texto_embebido(tmp_path: Path) -> None:
    entrada = tmp_path / "entrada"; entrada.mkdir()
    _pdf(entrada / "guia.pdf", [("texto", "472623")])
    procesar_carpeta(entrada, tmp_path / "salida.csv", proveedor=OCRFalso(), cada=1)
    (traza,) = [r for r in tmp_path.rglob("*.json") if "traza" in r.parent.name]
    contenido = json.loads(traza.read_text(encoding="utf-8"))
    assert contenido["imagen"]["referencia"] == "guia.pdf::pagina=0001"
    assert contenido["ocr"]["backend"]["nombre"].endswith("ProveedorPaginaPdf")
    assert contenido["ocr"]["backend"]["configuracion"]["configuracion"].startswith(f"{METODO_TEXTO_EMBEBIDO}:")
    assert "SEÑOR(ES): CONSTRUCTORA ÑUÑOA LIMITADA" in contenido["ocr"]["lineas"]


def test_identificador_de_pagina_es_reversible() -> None:
    assert separar_identificador_pagina_pdf("a/b.pdf::pagina=0012") == ("a/b.pdf", 12)
    assert separar_identificador_pagina_pdf("a/b.jpg") == ("a/b.jpg", None)


# ------------------------------------------------------------ inválidos

@pytest.mark.parametrize("nombre, contenido, tipo_error", [
    ("vacio.pdf", b"", "PdfVacio"),
    ("falso.pdf", "Guía ñandú -- texto plano, no un PDF".encode("utf-8"), "ArchivoNoEsPdf"),
    ("corrupto.pdf", b"%PDF-1.7\n\x00\x01 basura sin estructura", None),
    ("sin_paginas.pdf", construir_pdf([]), "PdfSinPaginas"),
    # Sin tabla xref: PDFium no lo repara (PyMuPDF sí lo hacía) -> inválido.
    ("sin_paginas_sin_xref.pdf",
     b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
     b"trailer<</Root 1 0 R>>\n%%EOF", "PdfInvalido"),
])
def test_pdf_invalido_queda_como_fila_error_auditable_sin_romper_el_lote(tmp_path, nombre, contenido, tipo_error) -> None:
    entrada = tmp_path / "entrada"; entrada.mkdir()
    (entrada / nombre).write_bytes(contenido)
    Image.new("RGB", (10, 10), "white").save(entrada / "control.jpg")
    vistas: list[Path] = []

    resumen = procesar_carpeta(entrada, tmp_path / "salida.csv", procesador=_procesador_registrador(vistas), cada=1)

    filas = {f["archivo"]: f for f in _filas(tmp_path / "salida.csv")}
    assert filas["control.jpg"]["estado_procesamiento"] == "OK"
    assert filas[nombre]["estado_procesamiento"] == "ERROR"
    assert filas[nombre]["error"].startswith("ErrorEntradaDocumento:")
    if tipo_error:
        assert tipo_error in filas[nombre]["error"]
    assert resumen["errores"] == 1 and vistas == [entrada / "control.jpg"]


def test_pdf_cifrado_no_se_intenta_abrir_ni_adivinar(tmp_path: Path) -> None:
    entrada = tmp_path / "entrada"; entrada.mkdir()
    _pdf(entrada / "cifrado.pdf", [("texto", "1")], contrasena_usuario="secreta", contrasena_propietario="duena")
    procesar_carpeta(entrada, tmp_path / "salida.csv", procesador=_procesador_registrador([]), cada=1)
    (fila,) = _filas(tmp_path / "salida.csv")
    assert fila["archivo"] == "cifrado.pdf" and fila["estado_procesamiento"] == "ERROR"
    assert "PdfCifrado" in fila["error"]


def test_pdf_solo_con_restricciones_de_permisos_se_lee_normalmente(tmp_path: Path) -> None:
    ruta = _pdf(tmp_path / "permisos.pdf", [("texto", "1")], contrasena_propietario="duena", permisos=-64)
    assert rasterizar_pdf(ruta, tmp_path / "art").paginas[0].metodo == METODO_TEXTO_EMBEBIDO


def test_pdf_real_con_extension_jpg_se_procesa_como_pdf(tmp_path: Path) -> None:
    entrada = tmp_path / "entrada"; entrada.mkdir()
    _pdf(entrada / "foto.jpg", [("texto", "472623"), ("escaneada", "2")])
    vistas: list[Path] = []
    procesar_carpeta(entrada, tmp_path / "salida.csv", procesador=_procesador_registrador(vistas), cada=1)
    assert [f["archivo"] for f in _filas(tmp_path / "salida.csv")] == ["foto.jpg::pagina=0001", "foto.jpg::pagina=0002"]
    assert all(ruta.suffix == ".png" for ruta in vistas)


def test_limites_de_paginas_y_pixeles(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ingesta_pdf, "MAX_PAGINAS_PDF", 2)
    muchas = rasterizar_pdf(_pdf(tmp_path / "muchas.pdf", [("texto", "1")] * 3), tmp_path / "art")
    assert not muchas.procesable and muchas.errores[0].tipo == "PdfDemasiadasPaginas"

    ruta = tmp_path / "gigante.pdf"
    ruta.write_bytes(construir_pdf([PaginaSintetica(ancho=14000, alto=14000)]))
    gigante = rasterizar_pdf(ruta, tmp_path / "art")
    assert not gigante.procesable
    assert gigante.errores[0].pagina == 1 and "PaginaDemasiadoGrande" in gigante.errores[0].mensaje


def test_contenido_activo_no_se_ejecuta_ni_se_extraen_adjuntos(tmp_path: Path) -> None:
    ruta = tmp_path / "activo.pdf"
    ruta.write_bytes(construir_pdf(
        [_pagina_guia("472623", enlace_uri="http://x")],
        javascript_apertura="app.launchURL('http://x')",
        adjunto=("malicioso.exe", b"MZ contenido adjunto"),
    ))

    resultado = rasterizar_pdf(ruta, tmp_path / "art")

    assert resultado.paginas[0].metodo == METODO_TEXTO_EMBEBIDO
    artefactos = sorted(p.name for p in (tmp_path / "art").iterdir())
    assert all(n.endswith((".png", ".json")) for n in artefactos)
    assert not any("malicioso" in n for n in artefactos)


# ------------------------------------------------------------ idempotencia / interrupción

def test_reprocesar_el_mismo_pdf_no_duplica_filas_ni_artefactos(tmp_path: Path) -> None:
    entrada = tmp_path / "entrada"; entrada.mkdir()
    _pdf(entrada / "lote.pdf", [("texto", "472601"), ("escaneada", "2")])
    salida = tmp_path / "salida.csv"
    procesar_carpeta(entrada, salida, proveedor=OCRFalso(), cada=1)
    artefactos = sorted(p.name for p in (tmp_path / "artefactos_pdf").iterdir())
    manifiesto = next((tmp_path / "artefactos_pdf").glob("*manifiesto.json")).read_bytes()

    segundo = procesar_carpeta(entrada, salida, proveedor=OCRFalso(), cada=1)

    assert segundo["omitidos"] == 2 and segundo["procesados"] == 0
    assert len(_filas(salida)) == 2
    assert sorted(p.name for p in (tmp_path / "artefactos_pdf").iterdir()) == artefactos
    assert next((tmp_path / "artefactos_pdf").glob("*manifiesto.json")).read_bytes() == manifiesto


def test_misma_guia_en_otro_pdf_no_se_reingesta(tmp_path: Path) -> None:
    """Reutiliza el gate existente guía+transporte (`clasificar_reingesta_
    documental`): el mismo documento llegado como otro archivo no duplica."""
    entrada = tmp_path / "entrada"; entrada.mkdir()
    _pdf(entrada / "a.pdf", [("texto", "472623")])
    salida = tmp_path / "salida.csv"
    fijo = lambda ruta: {"numero_guia": "472623", "numero_transporte": "0000351135"}  # noqa: E731
    procesar_carpeta(entrada, salida, procesador=fijo, cada=1)
    (entrada / "b.pdf").write_bytes((entrada / "a.pdf").read_bytes() + b"\n% copia\n")
    segundo = procesar_carpeta(entrada, salida, procesador=fijo, cada=1)
    assert segundo["reingestas_omitidas"] == 1
    assert [f["archivo"] for f in _filas(salida)] == ["a.pdf::pagina=0001"]


def test_interrupcion_a_mitad_de_pdf_reanuda_sin_duplicar(tmp_path: Path) -> None:
    entrada = tmp_path / "entrada"; entrada.mkdir()
    _pdf(entrada / "lote.pdf", [("texto", "1"), ("texto", "2"), ("texto", "3")])
    salida = tmp_path / "salida.csv"
    vistas: list[Path] = []
    base = _procesador_registrador(vistas)

    def con_corte(ruta: Path):
        if len(vistas) == 1:
            raise KeyboardInterrupt  # corte real del proceso, no un error por documento
        return base(ruta)

    with pytest.raises(KeyboardInterrupt):
        procesar_carpeta(entrada, salida, procesador=con_corte, cada=1)
    assert [f["archivo"] for f in _filas(salida)] == ["lote.pdf::pagina=0001"]

    procesar_carpeta(entrada, salida, procesador=base, cada=1)
    archivos = [f["archivo"] for f in _filas(salida)]
    assert archivos == ["lote.pdf::pagina=0001", "lote.pdf::pagina=0002", "lote.pdf::pagina=0003"]


def test_png_tecnico_truncado_por_corte_no_se_reutiliza(tmp_path: Path, monkeypatch) -> None:
    ruta = _pdf(tmp_path / "x.pdf", [("texto", "1")])
    real = ingesta_pdf._rasterizar_pagina

    def cortado(documento, indice, destino, dpi):
        (destino.with_name(destino.name + ".tmp")).write_bytes(b"\x89PNG truncado")
        raise KeyboardInterrupt

    monkeypatch.setattr(ingesta_pdf, "_rasterizar_pagina", cortado)
    with pytest.raises(KeyboardInterrupt):
        rasterizar_pdf(ruta, tmp_path / "art")
    assert not list((tmp_path / "art").glob("*.png"))

    monkeypatch.setattr(ingesta_pdf, "_rasterizar_pagina", real)
    (pagina,) = rasterizar_pdf(ruta, tmp_path / "art").paginas
    Image.open(pagina.ruta_imagen).verify()


# ------------------------------------------------------------ compatibilidad imágenes

def test_jpg_y_png_siguen_el_camino_de_siempre(tmp_path: Path) -> None:
    entrada = tmp_path / "entrada"; entrada.mkdir()
    Image.new("RGB", (10, 10), "white").save(entrada / "a.jpg")
    Image.new("RGB", (10, 10), "black").save(entrada / "b.png")
    vistas: list[Path] = []
    procesar_carpeta(entrada, tmp_path / "salida.csv", procesador=_procesador_registrador(vistas), cada=1)
    assert vistas == [entrada / "a.jpg", entrada / "b.png"]
    assert [f["archivo"] for f in _filas(tmp_path / "salida.csv")] == ["a.jpg", "b.png"]
    assert not (tmp_path / "artefactos_pdf").exists() or not any((tmp_path / "artefactos_pdf").iterdir())
