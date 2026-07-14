from unittest.mock import Mock

import numpy as np
import pytest
from PIL import Image

from atlas_core import ocr


def preparar_lector(monkeypatch, resultados=None):
    lector = Mock()
    lector.readtext.return_value = resultados or []
    monkeypatch.setattr(ocr.easyocr, "Reader", Mock(return_value=lector))
    return lector


def test_abre_nombre_unicode_y_entrega_arreglo_rgb(tmp_path, monkeypatch):
    ruta = tmp_path / "[Prueba] guía logística ñ 01.jpeg"
    Image.new("L", (4, 3), color=128).save(ruta)
    lector = preparar_lector(monkeypatch, [" texto ", ""])

    assert ocr.leer_texto_imagen(str(ruta)) == [" texto "]

    imagen_ocr = lector.readtext.call_args.args[0]
    assert isinstance(imagen_ocr, np.ndarray)
    assert imagen_ocr is not None
    assert imagen_ocr.shape == (3, 4, 3)
    assert lector.readtext.call_args.kwargs == {"detail": 0, "paragraph": True}


def test_aplica_orientacion_exif_antes_del_ocr(tmp_path, monkeypatch):
    ruta = tmp_path / "foto (teléfono).png"
    Image.new("RGB", (2, 3), color="red").save(ruta)
    lector = preparar_lector(monkeypatch)
    imagen_orientada = Image.new("RGB", (3, 2), color="blue")
    exif_transpose = Mock(return_value=imagen_orientada)
    monkeypatch.setattr(ocr.ImageOps, "exif_transpose", exif_transpose)

    ocr.leer_texto_imagen(ruta)

    exif_transpose.assert_called_once()
    imagen_ocr = lector.readtext.call_args.args[0]
    assert imagen_ocr.shape == (2, 3, 3)
    assert np.all(imagen_ocr == np.array([0, 0, 255]))


def test_archivo_inexistente_incluye_ruta(tmp_path):
    ruta = tmp_path / "imagen inexistente.jpg"

    with pytest.raises(FileNotFoundError, match="imagen inexistente\\.jpg"):
        ocr.leer_texto_imagen(ruta)


def test_ruta_que_no_es_archivo_incluye_ruta(tmp_path):
    with pytest.raises(IsADirectoryError, match=tmp_path.name):
        ocr.leer_texto_imagen(tmp_path)


def test_archivo_invalido_incluye_ruta(tmp_path):
    ruta = tmp_path / "imagen inválida.jpg"
    ruta.write_text("esto no es una imagen", encoding="utf-8")

    with pytest.raises(ValueError, match="imagen inválida\\.jpg"):
        ocr.leer_texto_imagen(ruta)
