"""Tests del worker aislado de PaddleOCR (`atlas_core/paddleocr_worker.py`).

El módulo se importa aquí directamente -- sus imports de `paddleocr` están
deliberadamente diferidos dentro de `_cargar_dependencias()` (nunca a nivel
de módulo), así que importarlo no requiere el runtime aislado. `Image`,
`ImageEnhance`, `ImageOps` y `np` se pasan siempre como parámetros
(inyección de dependencias) -- usamos aquí las reales (Pillow/numpy ya son
dependencias del entorno principal) para poder probar la lógica sin
depender de PaddleOCR real, que sólo existe en el runtime aislado.

Bloque P1: regresión del bug real donde `PaddleOCR.predict()` rechazaba
siempre las variantes en escala de grises (array 2D sin canal de color)
con `ValueError: not enough values to unpack (expected 3, got 2)`,
inactivando en silencio la relectura focal (fecha/transporte ya
publicados, corroboración de fecha nueva) en producción.
"""
from PIL import Image, ImageEnhance, ImageOps
import numpy as np
import pytest

from atlas_core.paddleocr_worker import (
    _a_array_rgb,
    _ejecutar_focal,
    _recortar_variantes,
)


def _crear_imagen_prueba(ruta, ancho=200, alto=200):
    """Imagen RGB sintética simple -- no necesita texto real: los tests de
    este archivo usan un doble de OCR, nunca PaddleOCR real."""
    imagen = Image.new("RGB", (ancho, alto), color=(230, 230, 230))
    imagen.save(ruta)
    return ruta


class _OCRFalso:
    """Doble de `PaddleOCR`: sólo expone `.predict()`, registra la forma
    de cada array recibido, y devuelve una página vacía válida (misma
    forma que `_paginas_a_bloques` espera)."""

    def __init__(self, fallar_en_2d=False):
        self.llamadas = []
        self._fallar_en_2d = fallar_en_2d

    def predict(self, arreglo):
        self.llamadas.append(
            {"shape": arreglo.shape, "ndim": arreglo.ndim, "dtype": str(arreglo.dtype)}
        )
        if self._fallar_en_2d and arreglo.ndim != 3:
            # Reproduce exactamente el error real de PaddleOCR.predict()
            # ante un array sin canal de color.
            raise ValueError("not enough values to unpack (expected 3, got 2)")
        return [{"rec_texts": ["23-06-2025"], "rec_scores": [0.9], "rec_polys": []}]


# ---- _a_array_rgb: normalización de canales, no-op visual ----


def test_a_array_rgb_convierte_grayscale_2d_a_3_canales():
    gris = Image.new("L", (10, 8), color=128)
    assert np.asarray(gris).ndim == 2  # confirma la forma del bug real antes de normalizar

    arreglo = _a_array_rgb(gris, np)

    assert arreglo.ndim == 3
    assert arreglo.shape == (8, 10, 3)
    assert arreglo.dtype == np.uint8


def test_a_array_rgb_grayscale_replica_canal_r_g_b_identicos():
    gris = Image.new("L", (5, 5), color=77)

    arreglo = _a_array_rgb(gris, np)

    assert np.array_equal(arreglo[:, :, 0], arreglo[:, :, 1])
    assert np.array_equal(arreglo[:, :, 1], arreglo[:, :, 2])
    assert (arreglo[:, :, 0] == 77).all()


def test_a_array_rgb_no_altera_variante_ya_rgb():
    rgb = Image.new("RGB", (6, 4), color=(10, 20, 30))

    arreglo = _a_array_rgb(rgb, np)

    assert arreglo.shape == (4, 6, 3)
    assert (arreglo[:, :, 0] == 10).all()
    assert (arreglo[:, :, 1] == 20).all()
    assert (arreglo[:, :, 2] == 30).all()


# ---- _recortar_variantes: confirma cuáles variantes salen en escala de grises ----


def test_recortar_variantes_grises_y_contraste_son_2d_antes_de_normalizar(tmp_path):
    """Reproduce la precondición exacta del bug real: dos de las cuatro
    variantes ("grises", "ampliada_2x_contraste") son modo "L" (2D) tal
    como las produce `_recortar_variantes` -- la normalización ocurre
    después, en `_a_array_rgb`/`_ejecutar_focal`, nunca aquí."""
    ruta = _crear_imagen_prueba(tmp_path / "guia.jpg")

    _, variantes = _recortar_variantes(Image, ImageEnhance, ImageOps, str(ruta), (50, 50, 150, 80))
    por_nombre = dict(variantes)

    assert set(por_nombre) == {"original", "grises", "ampliada_2x", "ampliada_2x_contraste"}
    assert por_nombre["original"].mode == "RGB"
    assert por_nombre["ampliada_2x"].mode == "RGB"
    assert por_nombre["grises"].mode == "L"
    assert por_nombre["ampliada_2x_contraste"].mode == "L"
    assert np.asarray(por_nombre["grises"]).ndim == 2
    assert np.asarray(por_nombre["ampliada_2x_contraste"]).ndim == 2


def test_recortar_variantes_caja_invalida_lanza_value_error(tmp_path):
    ruta = _crear_imagen_prueba(tmp_path / "guia.jpg")

    with pytest.raises(ValueError):
        _recortar_variantes(Image, ImageEnhance, ImageOps, str(ruta), (100, 100, 50, 50))


# ---- _ejecutar_focal: regresión real del bug P1 ----


def test_ejecutar_focal_todas_las_variantes_llegan_con_canal_de_color(tmp_path):
    """Regresión central: antes del fix, 2 de las 4 llamadas a
    `ocr.predict()` recibían un array 2D -- con el doble configurado para
    fallar exactamente como PaddleOCR real ante eso, esta prueba habría
    fallado antes del fix y pasa después."""
    ruta = _crear_imagen_prueba(tmp_path / "guia.jpg")
    ocr = _OCRFalso(fallar_en_2d=True)

    resultado = _ejecutar_focal(ocr, str(ruta), (50, 50, 150, 80), Image, ImageEnhance, ImageOps, np)

    assert len(ocr.llamadas) == 4
    for llamada in ocr.llamadas:
        assert llamada["ndim"] == 3
        assert llamada["shape"][-1] == 3
    assert [l["variante"] for l in resultado["lecturas"]] == [
        "original", "grises", "ampliada_2x", "ampliada_2x_contraste",
    ]


def test_ejecutar_focal_preserva_protocolo_de_resultado(tmp_path):
    """El formato de `resultado` (recorte + lecturas con variante/texto/
    confianza) no cambia por el fix -- mismo contrato ya consumido por
    `PaddleOCRProvider.leer_focal()` (protocolo JSON/IPC del worker)."""
    ruta = _crear_imagen_prueba(tmp_path / "guia.jpg")
    ocr = _OCRFalso()

    resultado = _ejecutar_focal(ocr, str(ruta), (50, 50, 150, 80), Image, ImageEnhance, ImageOps, np)

    assert set(resultado) == {"recorte", "lecturas"}
    assert len(resultado["recorte"]) == 4
    for lectura in resultado["lecturas"]:
        assert set(lectura) == {"variante", "texto", "confianza"}
        assert lectura["texto"] == "23-06-2025"
        assert lectura["confianza"] == pytest.approx(0.9)


def test_ejecutar_focal_propaga_excepcion_real_de_ocr_sin_convertirla_en_exito(tmp_path):
    """Un fallo genuino de OCR (no relacionado con el formato de canales)
    debe seguir propagándose -- nunca convertirse en un resultado
    silenciosamente vacío o falsamente exitoso. El try/except que lo
    captura y lo reporta como error JSON vive en `main()`, no aquí."""
    ruta = _crear_imagen_prueba(tmp_path / "guia.jpg")

    class _OCRQueFalla:
        def predict(self, arreglo):
            raise RuntimeError("fallo real de inferencia, no relacionado con canales")

    with pytest.raises(RuntimeError, match="fallo real de inferencia"):
        _ejecutar_focal(_OCRQueFalla(), str(ruta), (50, 50, 150, 80), Image, ImageEnhance, ImageOps, np)


def test_worker_module_importable_sin_paddleocr_instalado():
    """El módulo nunca debe importar `paddleocr`/`PIL`/`numpy` a nivel de
    módulo (sólo dentro de `_cargar_dependencias()`) -- si este test
    importa el módulo sin fallar, la separación del runtime aislado sigue
    intacta."""
    import atlas_core.paddleocr_worker as worker

    assert hasattr(worker, "_ejecutar_focal")
    assert hasattr(worker, "_a_array_rgb")
    assert hasattr(worker, "main")
