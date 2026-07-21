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


def test_llamada_tradicional_crea_easyocr_con_configuracion_esperada(
    tmp_path, monkeypatch
):
    ruta = tmp_path / "imagen.png"
    Image.new("RGB", (2, 2), color="white").save(ruta)
    lector = Mock()
    lector.readtext.return_value = ["texto"]
    crear_reader = Mock(return_value=lector)
    monkeypatch.setattr(ocr.easyocr, "Reader", crear_reader)

    assert ocr.leer_texto_imagen(ruta) == ["texto"]

    crear_reader.assert_called_once_with(["es", "en"], gpu=False)
    lector.readtext.assert_called_once()
    assert lector.readtext.call_args.kwargs == {"detail": 0, "paragraph": True}


def test_lector_inyectado_reutiliza_el_objeto_y_no_crea_otro(
    tmp_path, monkeypatch
):
    ruta = tmp_path / "imagen.png"
    Image.new("RGB", (2, 2), color="white").save(ruta)
    lector = Mock()
    lector.readtext.return_value = ["texto"]
    crear_reader = Mock()
    monkeypatch.setattr(ocr.easyocr, "Reader", crear_reader)

    assert ocr.leer_texto_imagen(ruta, lector=lector) == ["texto"]

    crear_reader.assert_not_called()
    lector.readtext.assert_called_once()
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


def test_leer_bloques_usa_detalle_y_sin_parrafos(tmp_path, monkeypatch):
    ruta = tmp_path / "imagen.png"
    Image.new("RGB", (4, 3), color="white").save(ruta)
    lector = preparar_lector(
        monkeypatch,
        [([[0, 0], [4, 0], [4, 2], [0, 2]], "Transporte", 0.91)],
    )

    bloques = ocr.leer_bloques_imagen(ruta)

    assert lector.readtext.call_args.kwargs == {"detail": 1, "paragraph": False}
    assert bloques == [
        ocr.BloqueOCR(
            texto="Transporte",
            bounding_box=((0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (0.0, 2.0)),
            confianza=0.91,
        )
    ]


def test_leer_bloques_filtra_vacios_y_conserva_texto_original(tmp_path, monkeypatch):
    ruta = tmp_path / "imagen.png"
    Image.new("RGB", (2, 2), color="white").save(ruta)
    lector = preparar_lector(
        monkeypatch,
        [
            ([[0, 0], [1, 0], [1, 1], [0, 1]], "  ", 0.2),
            ([[0, 0], [2, 0], [2, 1], [0, 1]], " Texto ", 0.7),
        ],
    )

    bloques = ocr.leer_bloques_imagen(ruta)

    assert [bloque.texto for bloque in bloques] == [" Texto "]
    assert bloques[0].confianza == 0.7


def test_leer_bloques_reutiliza_lector_y_orienta_exif(tmp_path, monkeypatch):
    ruta = tmp_path / "imagen.png"
    Image.new("RGB", (2, 3), color="red").save(ruta)
    lector = Mock()
    lector.readtext.return_value = []
    crear_lector = Mock()
    monkeypatch.setattr(ocr, "crear_lector_ocr", crear_lector)
    imagen_orientada = Image.new("RGB", (3, 2), color="blue")
    exif_transpose = Mock(return_value=imagen_orientada)
    monkeypatch.setattr(ocr.ImageOps, "exif_transpose", exif_transpose)

    assert ocr.leer_bloques_imagen(ruta, lector=lector) == []

    crear_lector.assert_not_called()
    exif_transpose.assert_called_once()
    imagen_ocr = lector.readtext.call_args.args[0]
    assert imagen_ocr.shape == (2, 3, 3)


@pytest.mark.parametrize(
    ("preparar_ruta", "error"),
    [
        (lambda ruta: None, FileNotFoundError),
        (lambda ruta: ruta.mkdir(), IsADirectoryError),
        (lambda ruta: ruta.write_text("no es imagen", encoding="utf-8"), ValueError),
    ],
)
def test_leer_bloques_mantiene_errores_claros(tmp_path, preparar_ruta, error):
    ruta = tmp_path / "entrada.jpg"
    preparar_ruta(ruta)

    with pytest.raises(error):
        ocr.leer_bloques_imagen(ruta)
