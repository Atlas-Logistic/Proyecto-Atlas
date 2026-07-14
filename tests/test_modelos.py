import json

import pytest

from atlas_core.modelos import (
    CampoProcesado,
    EstadoValidacion,
    FuenteCampo,
    ResultadoDocumento,
)


def test_campo_valido_no_requiere_revision():
    campo = CampoProcesado(
        nombre="numero_documento",
        valor="ABC-123",
        fuente=FuenteCampo.EXTRACCION,
        estado=EstadoValidacion.VALIDO,
        confianza=0.95,
    )

    assert campo.requiere_revision is False


def test_campo_ausente_requiere_revision():
    campo = CampoProcesado(nombre="destino")

    assert campo.valor is None
    assert campo.estado is EstadoValidacion.AUSENTE
    assert campo.requiere_revision is True


def test_campo_invalido_conserva_advertencias():
    campo = CampoProcesado(
        nombre="identificador_transportista",
        valor="texto incompleto",
        fuente=FuenteCampo.VALIDACION,
        estado=EstadoValidacion.INVALIDO,
        confianza=0.2,
        advertencias=["Formato inválido", "Falta el dígito de control"],
    )

    assert campo.requiere_revision is True
    assert campo.advertencias == [
        "Formato inválido",
        "Falta el dígito de control",
    ]


def test_campo_enriquecido_conserva_valor_original():
    campo = CampoProcesado(
        nombre="transportista",
        valor="TRANSPORTISTA EJEMPLO SPA",
        valor_original="TRANSP0RTISTA EJEMPL0",
        fuente=FuenteCampo.CATALOGO,
        estado=EstadoValidacion.ENRIQUECIDO,
        confianza=1.0,
    )

    assert campo.valor_original == "TRANSP0RTISTA EJEMPL0"
    assert campo.requiere_revision is False


def test_serializacion_a_diccionario_es_compatible_con_json():
    campo = CampoProcesado(
        nombre="patente",
        valor="ABCD12",
        fuente=FuenteCampo.OCR,
        estado=EstadoValidacion.PENDIENTE_CONFIRMACION,
        confianza=0.65,
        revision_humana=True,
        advertencias=["Lectura poco nítida"],
        valor_original="ABCDI2",
    )
    resultado = ResultadoDocumento(
        textos_ocr=["Texto original"],
        campos={"patente": campo},
        advertencias=["Documento inclinado"],
    )

    serializado = resultado.a_diccionario()

    assert serializado["campos"]["patente"]["fuente"] == "OCR"
    assert serializado["campos"]["patente"]["estado"] == "PENDIENTE_CONFIRMACION"
    assert serializado["campos"]["patente"]["valor_original"] == "ABCDI2"
    assert serializado["campos"]["patente"]["advertencias"] == [
        "Lectura poco nítida"
    ]
    json.dumps(serializado, ensure_ascii=False)


def test_resultado_general_con_y_sin_revision_pendiente():
    valido = CampoProcesado(
        nombre="peso",
        valor="1200",
        fuente=FuenteCampo.VALIDACION,
        estado=EstadoValidacion.VALIDO,
        confianza=0.9,
    )
    sin_revision = ResultadoDocumento(campos={"peso": valido})
    con_error = ResultadoDocumento(campos={"peso": valido}, errores=["Error no fatal"])

    assert sin_revision.requiere_revision is False
    assert con_error.requiere_revision is True
    assert sin_revision.a_diccionario()["perfil"] == "generico"
    assert sin_revision.a_diccionario()["version_formato"] == "1.0"


def test_valor_ausente_no_puede_declararse_valido():
    with pytest.raises(ValueError, match="sin valor"):
        CampoProcesado(
            nombre="campo",
            valor=None,
            estado=EstadoValidacion.VALIDO,
            confianza=1.0,
        )


def test_confianza_debe_estar_entre_cero_y_uno():
    with pytest.raises(ValueError, match="entre 0 y 1"):
        CampoProcesado(nombre="campo", confianza=1.1)
