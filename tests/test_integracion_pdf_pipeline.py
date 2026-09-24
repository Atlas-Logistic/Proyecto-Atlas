import csv

from PIL import Image

from atlas_core.procesamiento_masivo import procesar_carpeta
from tests.fixtures_pdf_sinteticos import construir_pdf, pagina_texto


def _pdf(ruta, paginas=3):
    ruta.write_bytes(construir_pdf([pagina_texto(f"GUIA PDF {numero + 1}") for numero in range(paginas)]))


def test_pdf_multipagina_entra_como_tres_imagenes_ocr_y_es_idempotente(tmp_path):
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    _pdf(entrada / "lote.pdf")
    salida = tmp_path / "salida.csv"
    vistas = []

    def procesador(ruta):
        vistas.append(ruta)
        assert ruta.suffix == ".png"
        return {"numero_guia": f"G{len(vistas)}", "numero_transporte": f"T{len(vistas)}"}

    primero = procesar_carpeta(entrada, salida, procesador=procesador, cada=1)
    assert primero["procesados"] == 3
    assert len(vistas) == 3
    with salida.open(encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo, delimiter=";"))
    assert [fila["archivo"] for fila in filas] == [
        "lote.pdf::pagina=0001", "lote.pdf::pagina=0002", "lote.pdf::pagina=0003",
    ]
    artefactos = list((tmp_path / "artefactos_pdf").glob("*.png"))
    assert len(artefactos) == 3
    assert len(list((tmp_path / "artefactos_pdf").glob("*manifiesto.json"))) == 1

    segundo = procesar_carpeta(entrada, salida, procesador=procesador, cada=1)
    assert segundo["omitidos"] == 3
    assert len(vistas) == 3
    assert len(list((tmp_path / "artefactos_pdf").glob("*.png"))) == 3


def test_imagen_normal_no_se_rasteriza(tmp_path):
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    Image.new("RGB", (10, 10), "white").save(entrada / "control.jpg")
    salida = tmp_path / "salida.csv"
    vistas = []

    procesar_carpeta(entrada, salida, procesador=lambda ruta: (vistas.append(ruta) or {"numero_guia": "G", "numero_transporte": "T"}))
    assert vistas == [entrada / "control.jpg"]
    assert not (tmp_path / "artefactos_pdf").exists()
