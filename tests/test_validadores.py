import json

from atlas_core.modelos import EstadoValidacion, FuenteCampo
from atlas_core.validadores import validar_rut_chileno


def test_rut_valido_con_puntos_y_guion():
    campo = validar_rut_chileno("12.345.678-5")

    assert campo.estado is EstadoValidacion.VALIDO
    assert campo.valor == "12.345.678-5"
    assert campo.requiere_revision is False


def test_rut_valido_sin_puntos():
    campo = validar_rut_chileno("12345678-5")

    assert campo.estado is EstadoValidacion.VALIDO
    assert campo.valor == "12.345.678-5"


def test_rut_valido_con_k_minuscula():
    campo = validar_rut_chileno("1.000.005-k")

    assert campo.estado is EstadoValidacion.VALIDO
    assert campo.valor == "1.000.005-K"


def test_normaliza_y_conserva_valor_original():
    campo = validar_rut_chileno(" 12345678 - 5 ", fuente=FuenteCampo.OCR)

    assert campo.valor == "12.345.678-5"
    assert campo.valor_original == " 12345678 - 5 "
    assert campo.fuente is FuenteCampo.OCR


def test_rut_valido_con_grupos_separados_por_espacios():
    campo = validar_rut_chileno("12 345 678-5")

    assert campo.estado is EstadoValidacion.VALIDO
    assert campo.valor == "12.345.678-5"


def test_rut_valido_puede_requerir_revision_humana():
    campo = validar_rut_chileno("12.345.678-5", revision_humana=True)

    assert campo.estado is EstadoValidacion.VALIDO
    assert campo.requiere_revision is True


def test_digito_verificador_incorrecto():
    campo = validar_rut_chileno("12.345.678-4")

    assert campo.estado is EstadoValidacion.INVALIDO
    assert campo.valor == "12.345.678-4"
    assert campo.requiere_revision is True
    assert "dígito verificador" in campo.advertencias[0]


def test_no_corrige_letras_ambiguas_de_ocr():
    campo = validar_rut_chileno("12.345.67B-5")

    assert campo.estado is EstadoValidacion.INVALIDO
    assert campo.valor == "12.345.67B-5"
    assert campo.valor_original is None


def test_rechaza_puntos_repetidos():
    campo = validar_rut_chileno("12..345.678-5")

    assert campo.estado is EstadoValidacion.INVALIDO


def test_rechaza_separadores_mezclados():
    campo = validar_rut_chileno("12.345 678-5")

    assert campo.estado is EstadoValidacion.INVALIDO


def test_rechaza_mas_de_un_guion():
    campo = validar_rut_chileno("12.345.678--5")

    assert campo.estado is EstadoValidacion.INVALIDO


def test_none_y_texto_vacio_son_ausentes():
    for valor in (None, "", "   "):
        campo = validar_rut_chileno(valor)
        assert campo.valor is None
        assert campo.estado is EstadoValidacion.AUSENTE
        assert campo.requiere_revision is True


def test_entero_rechazado_como_rut_completo():
    campo = validar_rut_chileno(123456785)

    assert campo.estado is EstadoValidacion.INVALIDO
    assert campo.valor == 123456785
    assert "texto" in campo.advertencias[0]


def test_conserva_fuente_y_confianza_recibidas():
    campo = validar_rut_chileno(
        "12.345.678-5",
        nombre="RUT del cliente",
        fuente=FuenteCampo.OCR,
        confianza=0.73,
    )

    assert campo.nombre == "RUT del cliente"
    assert campo.fuente is FuenteCampo.OCR
    assert campo.confianza == 0.73


def test_campo_resultante_se_serializa():
    campo = validar_rut_chileno("12.345.678-5")
    serializado = campo.a_diccionario()

    assert serializado["estado"] == "VALIDO"
    assert serializado["fuente"] == "EXTRACCION"
    assert json.dumps(serializado, ensure_ascii=False)
