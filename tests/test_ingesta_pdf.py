import json

from PIL import Image

from atlas_core.ingesta_pdf import es_archivo_entrada_ocr, rasterizar_pdf
from tests.fixtures_pdf_sinteticos import construir_pdf, pagina_texto


def _crear_pdf(ruta, paginas):
    ruta.write_bytes(construir_pdf([pagina_texto(f"PAGINA {numero}") for numero in range(1, paginas + 1)]))


def test_acepta_imagenes_existentes_y_pdf():
    assert es_archivo_entrada_ocr("guia.JPG")
    assert es_archivo_entrada_ocr("guia.jpeg")
    assert es_archivo_entrada_ocr("guia.png")
    assert es_archivo_entrada_ocr("guia.pdf")
    assert not es_archivo_entrada_ocr("guia.tiff")


def test_pdf_una_pagina_preserva_original_y_trazabilidad(tmp_path):
    original = tmp_path / "guia recibida.pdf"
    _crear_pdf(original, 1)
    contenido_original = original.read_bytes()

    resultado = rasterizar_pdf(original, tmp_path / "artefactos", referencia_original="entrada/guia recibida.pdf")

    assert resultado.procesable
    assert [pagina.pagina for pagina in resultado.paginas] == [1]
    assert original.read_bytes() == contenido_original
    assert resultado.paginas[0].ruta_imagen.is_file()
    manifiesto = json.loads(resultado.ruta_manifiesto.read_text(encoding="utf-8"))
    assert manifiesto["original_pdf"]["referencia"] == "entrada/guia recibida.pdf"
    assert manifiesto["version"] == 2
    assert manifiesto["paginas"] == [{
        "pagina": 1,
        "imagen_tecnica": resultado.paginas[0].ruta_imagen.name,
        "sha256_imagen": resultado.paginas[0].sha256_imagen,
        # "PAGINA 1" tiene menos de MIN_CARACTERES_TEXTO_UTIL -> OCR.
        "metodo": "OCR",
        "motivo_metodo": "sin_texto_embebido_suficiente",
        "texto_embebido": None,
        "identificador_documento": "entrada/guia recibida.pdf::pagina=0001",
    }]


def test_pdf_tres_paginas_genera_documentos_tecnicos_en_orden(tmp_path):
    original = tmp_path / "multipagina.pdf"
    _crear_pdf(original, 3)

    resultado = rasterizar_pdf(original, tmp_path / "artefactos")

    assert resultado.paginas_declaradas == 3
    assert [pagina.pagina for pagina in resultado.paginas] == [1, 2, 3]
    assert [pagina.ruta_imagen.name for pagina in resultado.paginas] == [
        f"multipagina--{resultado.sha256_original[:16]}--p0001.png",
        f"multipagina--{resultado.sha256_original[:16]}--p0002.png",
        f"multipagina--{resultado.sha256_original[:16]}--p0003.png",
    ]
    assert all(pagina.ruta_imagen.is_file() for pagina in resultado.paginas)


def test_pdf_corrupto_registra_error_controlado_y_manifiesto(tmp_path):
    original = tmp_path / "corrupto.pdf"
    original.write_bytes(b"no soy un pdf")

    resultado = rasterizar_pdf(original, tmp_path / "artefactos")

    assert not resultado.procesable
    assert resultado.paginas == ()
    assert resultado.errores and resultado.errores[0].pagina is None
    assert json.loads(resultado.ruta_manifiesto.read_text(encoding="utf-8"))["errores"]


def test_fallo_de_una_pagina_no_impide_las_demas(tmp_path, monkeypatch):
    original = tmp_path / "parcial.pdf"
    _crear_pdf(original, 3)

    from atlas_core import ingesta_pdf

    rasterizador_real = ingesta_pdf._rasterizar_pagina

    def rasterizador_con_fallo(documento, indice_cero, destino, dpi):
        if indice_cero == 1:
            raise RuntimeError("página ilegible simulada")
        rasterizador_real(documento, indice_cero, destino, dpi)

    monkeypatch.setattr(ingesta_pdf, "_rasterizar_pagina", rasterizador_con_fallo)
    resultado = rasterizar_pdf(original, tmp_path / "artefactos")

    assert [pagina.pagina for pagina in resultado.paginas] == [1, 3]
    assert [(error.pagina, error.tipo) for error in resultado.errores] == [(2, "RuntimeError")]


def test_reintento_reutiliza_los_mismos_artefactos_sin_colisiones(tmp_path):
    original = tmp_path / "estable.pdf"
    _crear_pdf(original, 3)

    primero = rasterizar_pdf(original, tmp_path / "artefactos")
    segundo = rasterizar_pdf(original, tmp_path / "artefactos")

    assert [pagina.ruta_imagen for pagina in primero.paginas] == [pagina.ruta_imagen for pagina in segundo.paginas]
    assert len(list((tmp_path / "artefactos").glob("*.png"))) == 3
    assert primero.ruta_manifiesto.read_bytes() == segundo.ruta_manifiesto.read_bytes()


def test_rasterizacion_no_modifica_jpg_ni_png_existentes(tmp_path):
    jpg = tmp_path / "control.jpg"
    png = tmp_path / "control.png"
    Image.new("RGB", (10, 10), "white").save(jpg)
    Image.new("RGB", (10, 10), "black").save(png)
    antes = {ruta: ruta.read_bytes() for ruta in (jpg, png)}
    original = tmp_path / "entrada.pdf"
    _crear_pdf(original, 1)

    rasterizar_pdf(original, tmp_path / "artefactos")

    assert {ruta: ruta.read_bytes() for ruta in (jpg, png)} == antes
