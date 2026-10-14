from pathlib import Path
import tempfile

import numpy as np
from PIL import Image, ImageEnhance, ImageOps

from atlas_core.rapidocr_adapter import adaptar_bloques_rapidocr, segmentar_delimitador_inicial
from atlas_core import rapidocr_worker
from atlas_core.extractor import extraer_datos
from atlas_core.validadores import validar_rut_chileno


def test_adaptador_conserva_original_y_segmenta_solo_delimitador_inicial():
    bloques = adaptar_bloques_rapidocr([
        [[[1, 2], [3, 2], [3, 4], [1, 4]], "：17576134-9", 0.93],
        [[[0, 0], [1, 0], [1, 1], [0, 1]], "MATERIAL: BARRA", 0.8],
        [[], "sin caja", 0.1],
    ])

    assert len(bloques) == 2
    assert bloques[0].texto_original == "：17576134-9"
    assert bloques[0].texto == "17576134-9"
    assert bloques[0].a_bloque_atlas().bounding_box[0] == (1.0, 2.0)
    assert segmentar_delimitador_inicial("MATERIAL: BARRA") == "MATERIAL: BARRA"


def test_worker_transpone_exif_antes_de_enviar_a_rapidocr(tmp_path: Path):
    ruta = tmp_path / "orientada.jpg"
    imagen = Image.new("RGB", (3, 2), "white")
    exif = Image.Exif()
    exif[274] = 6
    imagen.save(ruta, exif=exif)
    vistas = []

    class Engine:
        def __call__(self, array, use_cls=True):
            vistas.append((array.shape, use_cls))
            return ([[[[0, 0], [1, 0], [1, 1], [0, 1]], "OK", 0.9]], [0, 0, 0])

    bloques = rapidocr_worker._bloques(Engine(), str(ruta), Image, ImageOps, np)

    # EXIF=6: 3x2 cruda pasa a 2x3 documental; sin clasificador de ángulo
    # por línea (caso real 482179: giraba 180° el número de transporte).
    assert vistas == [((3, 2, 3), False)]
    assert bloques[0][1] == "OK"


def test_worker_focal_tampoco_usa_clasificador_de_angulo(tmp_path: Path):
    ruta = tmp_path / "doc.png"
    Image.new("RGB", (40, 20), "white").save(ruta)
    llamadas = []

    class Engine:
        def __call__(self, array, use_cls=True):
            llamadas.append(use_cls)
            return ([[[[0, 0], [1, 0], [1, 1], [0, 1]], "0000363997", 0.9]], [0, 0, 0])

    resultado = rapidocr_worker._focal(Engine(), str(ruta), [5, 5, 30, 15], Image, ImageEnhance, ImageOps, np)

    assert llamadas == [False] * 4
    assert [l["texto"] for l in resultado["lecturas"]] == ["0000363997"] * 4


def test_delimitador_rapidocr_llega_al_extractor_y_validador_canonicos():
    bloques = adaptar_bloques_rapidocr([
        [[[0, 0], [1, 0], [1, 1], [0, 1]], "RUT CHOFER", 0.9],
        [[[2, 0], [3, 0], [3, 1], [2, 1]], "：17576134-9", 0.9],
    ])
    with tempfile.TemporaryDirectory() as carpeta:
        datos = extraer_datos([bloque.texto for bloque in bloques], Path(carpeta))

    assert datos["RUT del chofer"] == "17576134-9"
    assert validar_rut_chileno(datos["RUT del chofer"]).estado.value == "VALIDO"
