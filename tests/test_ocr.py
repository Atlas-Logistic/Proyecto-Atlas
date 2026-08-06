from unittest.mock import Mock

import numpy as np
import pytest
from PIL import Image

from atlas_core import ocr


def test_consenso_rut_cliente_exige_dos_lecturas_validas_iguales():
    resultado = ocr._consensuar_rut_cliente_focal(
        ["93.772.000-9", "93772000-9", "93.772.000"]
    )

    assert resultado["valor"] == "93772000-9"
    assert resultado["motivo"] == "consenso-modulo-11"


def test_consenso_rut_cliente_abstiene_sin_repeticion():
    resultado = ocr._consensuar_rut_cliente_focal(
        ["93.772.000-9", "93.772.000", "ruido"]
    )

    assert resultado["valor"] is None
    assert resultado["motivo"] == "sin-consenso-suficiente"


def test_consenso_rut_cliente_abstiene_ante_conflicto_valido():
    resultado = ocr._consensuar_rut_cliente_focal(
        ["93.772.000-9", "93772000-9", "91.410.000-3"]
    )

    assert resultado["valor"] is None
    assert resultado["motivo"] == "conflicto-ruts-validos"


def test_rut_cliente_focal_usa_fila_asociada_a_senor(tmp_path):
    ruta = tmp_path / "guia.png"
    Image.new("RGB", (900, 1600), color="white").save(ruta)
    bloques = [
        ocr.BloqueOCR(
            "SEÑOR(ES)", ((60, 440), (145, 440), (145, 460), (60, 460)), 0.9
        ),
        ocr.BloqueOCR("R.U.T.", ((65, 470), (110, 470), (110, 490), (65, 490)), 0.9),
        ocr.BloqueOCR("RUT", ((30, 1110), (70, 1110), (70, 1130), (30, 1130)), 0.9),
    ]
    lector = Mock()
    lector.readtext.side_effect = [
        ["93.772.000-9"],
        ["93772000-9"],
        ["93.772.000-9"],
        ["93.772.000"],
    ]

    resultado = ocr._leer_rut_cliente_focal(ruta, bloques, lector=lector)

    assert resultado["valor"] == "93772000-9"
    assert resultado["recorte"][1] < 470 < resultado["recorte"][3]
    assert lector.readtext.call_count == 4
    assert all(
        llamada.kwargs["allowlist"] == "0123456789Kk.- "
        for llamada in lector.readtext.call_args_list
    )


def test_es_etiqueta_rut_tolerante_reconoce_coincidencia_exacta():
    assert ocr._es_etiqueta_rut_tolerante("RUT") is True
    assert ocr._es_etiqueta_rut_tolerante("R.U.T.") is True


def test_es_etiqueta_rut_tolerante_admite_una_sola_confusion_visual():
    """Caso real (guía 464345): "R.U.T." fue leído por EasyOCR como "RuI."
    (T confundida con I). Misma clase de tolerancia determinista ya usada
    en el proyecto para "CARR[O0]" (Calidad de Publicación Operacional) y
    para patentes (`_distancia_patente_ocr`): un solo carácter de
    diferencia sobre una palabra de longitud fija y conocida, no una
    coincidencia difusa."""
    assert ocr._es_etiqueta_rut_tolerante("RuI.") is True
    assert ocr._es_etiqueta_rut_tolerante("RVT") is True
    assert ocr._es_etiqueta_rut_tolerante("R0T") is True


def test_es_etiqueta_rut_tolerante_rechaza_dos_o_mas_diferencias():
    assert ocr._es_etiqueta_rut_tolerante("XYZ") is False
    assert ocr._es_etiqueta_rut_tolerante("RXX") is False


def test_es_etiqueta_rut_tolerante_rechaza_longitud_distinta():
    assert ocr._es_etiqueta_rut_tolerante("RUTA") is False
    assert ocr._es_etiqueta_rut_tolerante("RU") is False
    assert ocr._es_etiqueta_rut_tolerante("") is False


def test_consenso_rut_cliente_acepta_espacio_como_separador_del_digito_verificador():
    """Caso real (guía 464345): en 3 de 4 variantes focales el guion del
    RUT se leyó como espacio ("50.234.350 5"); solo una variante conservó
    un guion, pero con un dígito equivocado ("50.234.150-5"). El separador
    de miles ya toleraba espacio o punto; ahora el separador del dígito
    verificador también tolera espacio, no solo guion."""
    resultado = ocr._consensuar_rut_cliente_focal(
        ["50.234.350 5", "50.234.350 5", "50.234.150-5"]
    )

    assert resultado["valor"] == "50234350-5"
    assert resultado["motivo"] == "consenso-modulo-11"


def test_consenso_rut_cliente_con_guion_sigue_funcionando_igual():
    """El formato con guion, ya cubierto antes de este ajuste, no cambia."""
    resultado = ocr._consensuar_rut_cliente_focal(
        ["93.772.000-9", "93772000-9", "93.772.000"]
    )

    assert resultado["valor"] == "93772000-9"
    assert resultado["motivo"] == "consenso-modulo-11"


def test_rut_cliente_focal_localiza_fila_pese_a_confusion_visual_en_la_etiqueta(tmp_path):
    """Reproduce, con el mismo mecanismo de mockeo que
    test_rut_cliente_focal_usa_fila_asociada_a_senor, el caso real de la
    guía 464345 donde "R.U.T." se lee como "RuI.": antes de esta
    corrección, `_localizar_fila_rut_cliente` exigía la coincidencia
    exacta "RUT" y no encontraba ninguna fila, así que la relectura focal
    abstenía con motivo "fila-rut-cliente-no-localizada" pese a que el RUT
    sí estaba legible en la imagen."""
    ruta = tmp_path / "guia.png"
    Image.new("RGB", (900, 1600), color="white").save(ruta)
    bloques = [
        ocr.BloqueOCR(
            "SEÑOR(ES)", ((60, 440), (145, 440), (145, 460), (60, 460)), 0.9
        ),
        ocr.BloqueOCR("RuI.", ((65, 470), (110, 470), (110, 490), (65, 490)), 0.9),
    ]
    lector = Mock()
    lector.readtext.side_effect = [
        ["50.234.350 5"],
        ["50.234.350 5"],
        ["50.234.150-5"],
        ["50.234.350 5"],
    ]

    resultado = ocr._leer_rut_cliente_focal(ruta, bloques, lector=lector)

    assert resultado["valor"] == "50234350-5"
    assert resultado["motivo"] == "consenso-modulo-11"


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


def test_transporte_focal_recorta_dinamicamente_dentro_de_limites_y_reutiliza_lector(
    tmp_path, monkeypatch
):
    ruta = tmp_path / "imagen.png"
    Image.new("RGB", (100, 60), color="white").save(ruta)
    lector = Mock()
    lector.readtext.side_effect = [["0000348808"]] * 8
    crear = Mock()
    monkeypatch.setattr(ocr, "crear_lector_ocr", crear)

    resultado = ocr._leer_transporte_focal(ruta, (20, 10, 80, 30), lector=lector)

    assert resultado["recorte"] == (13, 3, 87, 37)
    assert [lectura["variante"] for lectura in resultado["lecturas"]][:4] == [
        "original", "grises", "ampliada_2x", "ampliada_2x_contraste"
    ]
    assert [lectura["texto"] for lectura in resultado["lecturas"]][:4] == [
        "0000348808"
    ] * 4
    assert lector.readtext.call_count == 8
    assert [llamada.kwargs["paragraph"] for llamada in lector.readtext.call_args_list[:4]] == [
        False,
        True,
        False,
        True,
    ]
    crear.assert_not_called()


def test_transporte_focal_caja_proxima_al_borde_se_limita_a_imagen(tmp_path):
    ruta = tmp_path / "imagen.png"
    Image.new("RGB", (40, 30), color="white").save(ruta)
    lector = Mock()
    lector.readtext.return_value = []

    resultado = ocr._leer_transporte_focal(ruta, (1, 1, 39, 29), lector=lector)

    assert resultado["recorte"] == (0, 0, 40, 30)
    for llamada in lector.readtext.call_args_list:
        assert llamada.kwargs["detail"] == 1
    assert [llamada.kwargs["paragraph"] for llamada in lector.readtext.call_args_list[:4]] == [
        False,
        False,
        False,
        False,
    ]


@pytest.mark.parametrize(
    "caja",
    [(0, 10, 15, 20), (85, 10, 100, 20), (10, 0, 30, 10), (10, 50, 30, 60)],
)
def test_transporte_focal_limita_recortes_en_cada_borde(tmp_path, caja):
    ruta = tmp_path / "imagen.png"
    Image.new("RGB", (100, 60), color="white").save(ruta)
    lector = Mock()
    lector.readtext.return_value = []

    recorte = ocr._leer_transporte_focal(ruta, caja, lector=lector)["recorte"]

    assert 0 <= recorte[0] < recorte[2] <= 100
    assert 0 <= recorte[1] < recorte[3] <= 60


def test_transporte_focal_sin_resultados_conserva_cuatro_lecturas_vacias(tmp_path):
    ruta = tmp_path / "imagen.png"
    Image.new("RGB", (40, 30), color="white").save(ruta)
    lector = Mock()
    lector.readtext.return_value = []

    resultado = ocr._leer_transporte_focal(ruta, (5, 5, 30, 20), lector=lector)

    assert [lectura["texto"] for lectura in resultado["lecturas"]] == [""] * 4


def test_transporte_focal_compara_relecturas_y_entrega_evidencia_adicional(tmp_path):
    ruta = tmp_path / "imagen.png"
    Image.new("RGB", (40, 30), color="white").save(ruta)
    lector = Mock()
    lector.readtext.side_effect = [
        [([[0, 0], [4, 0], [4, 2], [0, 2]], "0000348808", 0.91)],
        [([[0, 0], [4, 0], [4, 2], [0, 2]], "0000348608", 0.73)],
        [],
        [],
        [],
        [],
        [],
        [],
    ]

    resultado = ocr._leer_transporte_focal(ruta, (5, 5, 30, 20), lector=lector)

    assert resultado["comparacion"]["original"]["coincide"] is False
    assert resultado["comparacion"]["original"]["candidatos"] == [
        "0000348808",
        "0000348608",
    ]
    assert any(lectura["texto"] == "0000348608" for lectura in resultado["lecturas"])


def test_segunda_lectura_util_se_conserva_para_consenso(tmp_path):
    ruta = tmp_path / "imagen.png"
    Image.new("RGB", (40, 30), color="white").save(ruta)
    lector = Mock()
    lector.readtext.side_effect = [
        [([[0, 0], [4, 0], [4, 2], [0, 2]], "0000348808", 0.91)],
        [([[0, 0], [4, 0], [4, 2], [0, 2]], "0000348608", 0.73)],
        [],
        [],
        [],
        [],
        [],
        [],
    ]

    resultado = ocr._leer_transporte_focal(ruta, (5, 5, 30, 20), lector=lector)

    assert resultado["evaluacion"]["original"]["incluir_en_consenso"] is True
    assert resultado["evaluacion"]["original"]["conflicto_relevante"] is True


def test_segunda_lectura_degradada_se_descarta(tmp_path):
    ruta = tmp_path / "imagen.png"
    Image.new("RGB", (40, 30), color="white").save(ruta)
    lector = Mock()
    lector.readtext.side_effect = [
        [([[0, 0], [4, 0], [4, 2], [0, 2]], "0000348808", 0.91)],
        [([[0, 0], [4, 0], [4, 2], [0, 2]], "00003", 0.73)],
        [],
        [],
        [],
        [],
        [],
        [],
    ]

    resultado = ocr._leer_transporte_focal(ruta, (5, 5, 30, 20), lector=lector)

    assert resultado["evaluacion"]["original"]["incluir_en_consenso"] is False
    assert resultado["evaluacion"]["original"]["motivo"] == "relectura-degradada"


def test_segunda_lectura_identica_se_descarta(tmp_path):
    ruta = tmp_path / "imagen.png"
    Image.new("RGB", (40, 30), color="white").save(ruta)
    lector = Mock()
    lector.readtext.side_effect = [
        [([[0, 0], [4, 0], [4, 2], [0, 2]], "0000348808", 0.91)],
        [([[0, 0], [4, 0], [4, 2], [0, 2]], "0000348808", 0.73)],
        [],
        [],
        [],
        [],
        [],
        [],
    ]

    resultado = ocr._leer_transporte_focal(ruta, (5, 5, 30, 20), lector=lector)

    assert resultado["evaluacion"]["original"]["incluir_en_consenso"] is False
    assert resultado["evaluacion"]["original"]["motivo"] == "relectura-identica"


def test_conflicto_entre_lecturas_queda_marcado_para_consenso(tmp_path):
    ruta = tmp_path / "imagen.png"
    Image.new("RGB", (40, 30), color="white").save(ruta)
    lector = Mock()
    lector.readtext.side_effect = [
        [([[0, 0], [4, 0], [4, 2], [0, 2]], "0000348808", 0.91)],
        [([[0, 0], [4, 0], [4, 2], [0, 2]], "0000348608", 0.73)],
        [],
        [],
        [],
        [],
        [],
        [],
    ]

    resultado = ocr._leer_transporte_focal(ruta, (5, 5, 30, 20), lector=lector)

    assert resultado["comparacion"]["original"]["coincide"] is False
    assert resultado["evaluacion"]["original"]["conflicto_relevante"] is True


def test_transporte_focal_rechaza_recorte_vacio(tmp_path):
    ruta = tmp_path / "imagen.png"
    Image.new("RGB", (40, 30), color="white").save(ruta)

    with pytest.raises(ValueError, match="dimensiones válidas"):
        ocr._leer_transporte_focal(ruta, (10, 10, 10, 20), lector=Mock())


def test_encabezado_origen_focal_gira_antes_de_recortar(tmp_path):
    """Reproduce el caso real 464108 (foto apaisada sin EXIF útil): girar la
    imagen antes de recortar cambia el encuadre efectivo del encabezado."""
    ruta = tmp_path / "guia.png"
    Image.new("L", (200, 100), color="white").save(ruta)
    lector = Mock()
    lector.readtext.return_value = []

    ocr.leer_encabezado_origen_focal(ruta, lector=lector, grados_adicionales=0)
    forma_sin_girar = lector.readtext.call_args.args[0].shape

    lector.reset_mock()
    ocr.leer_encabezado_origen_focal(ruta, lector=lector, grados_adicionales=90)
    forma_girada = lector.readtext.call_args.args[0].shape

    assert forma_sin_girar != forma_girada


def test_encabezado_origen_focal_rechaza_grados_invalidos(tmp_path):
    ruta = tmp_path / "guia.png"
    Image.new("L", (100, 100), color="white").save(ruta)

    with pytest.raises(ValueError, match="grados_adicionales"):
        ocr.leer_encabezado_origen_focal(ruta, lector=Mock(), grados_adicionales=45)
