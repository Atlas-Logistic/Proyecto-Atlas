import pytest

from atlas_core.inteligencia import (
    CandidatoMaterial, EstadoResolucion, crear_snapshot_catalogo_materiales,
    resolver_material_tipo_carga,
)


CATALOGO = {"materiales": [
    {"material_id": "M1", "descripcion_oficial": "BARRA HORMIGON 16 MM",
     "tipo_carga": "BARRAS", "aliases": ["FIERRO 16"],
     "abreviaciones": ["BH 16"], "estado_calidad": "CONFIRMADO", "estado_vigencia": "ACTIVO"},
    {"material_id": "M2", "descripcion_oficial": "ROLLO HORMIGON 12 MM",
     "tipo_carga": "ROLLOS", "aliases": ["ROLLO 12"],
     "estado_calidad": "CONFIRMADO", "estado_vigencia": "ACTIVO"},
]}


@pytest.mark.parametrize(("texto", "via"), [
    ("BARRA HORMIGON 16 MM", "EXACTO"),
    ("FIERRO 16", "ALIAS"),
    ("BH 16", "ABREVIACION"),
])
def test_material_exacto_alias_y_abreviacion(texto, via):
    resultado = resolver_material_tipo_carga(texto, catalogo_materiales=CATALOGO)
    assert resultado.id_material_canonico == "M1"
    assert resultado.via_decision == via


def test_fuzzy_solo_confirma_con_tipo_fuerte_compatible():
    aislado = resolver_material_tipo_carga("BARRA HORMIGOM 16 MM", catalogo_materiales=CATALOGO)
    assert aislado.material_canonico is None
    compatible = resolver_material_tipo_carga(
        "BARRA HORMIGOM 16 MM", "BARRAS", catalogo_materiales=CATALOGO
    )
    assert compatible.id_material_canonico == "M1"
    assert compatible.via_decision == "FUZZY_MAS_TIPO"


@pytest.mark.parametrize("texto", ["", "MATERIAL", "ACERO", "FIERRO", "PRODUCTO", "9999", "1250 KG", "TM", "16 MM"])
def test_vacios_genericos_codigos_cantidades_peso_unidad_dimension_no_resuelven(texto):
    resultado = resolver_material_tipo_carga(texto, catalogo_materiales=CATALOGO)
    assert resultado.material_canonico is None


def test_inexistente_preserva_original():
    original = "MALLA ESPECIAL ZX-77"
    resultado = resolver_material_tipo_carga(original, catalogo_materiales=CATALOGO)
    assert resultado.descripcion_material_original == original
    assert resultado.material_canonico is None


def test_inactivo_y_duplicado_exigen_revision():
    inactivo = {"materiales": [{**CATALOGO["materiales"][0], "estado_vigencia": "INACTIVO"}]}
    assert resolver_material_tipo_carga(
        "BARRA HORMIGON 16 MM", catalogo_materiales=inactivo
    ).estado_resolucion is EstadoResolucion.REQUIERE_REVISION
    duplicado = {"materiales": [CATALOGO["materiales"][0], {**CATALOGO["materiales"][0], "material_id": "M9"}]}
    assert "MATERIAL_CATALOGO_AMBIGUO" in resolver_material_tipo_carga(
        "BARRA HORMIGON 16 MM", catalogo_materiales=duplicado
    ).contradicciones


def test_dos_materiales_se_conservan_y_forman_resultado_compuesto():
    texto = "BARRA HORMIGON 16 MM\nROLLO HORMIGON 12 MM"
    resultado = resolver_material_tipo_carga(texto, catalogo_materiales=CATALOGO)
    assert resultado.lineas_material_originales == tuple(texto.splitlines())
    assert resultado.ids_materiales_canonicos == ("M1", "M2")
    assert resultado.id_material_canonico is None
    assert resultado.tipo_carga_canonico == "MIXTO"


@pytest.mark.parametrize("texto", ["  barra   hormigón 16 mm  ", "BARRA HORMIGÓN 16 MM"])
def test_puntuacion_espacios_acentos_mayusculas_solo_normalizan_comparacion(texto):
    resultado = resolver_material_tipo_carga(texto, catalogo_materiales=CATALOGO)
    assert resultado.descripcion_material_original == texto
    assert resultado.id_material_canonico == "M1"


def test_tipo_explicito_compatible_y_ausente_derivable():
    assert resolver_material_tipo_carga(
        "BARRA HORMIGON 16 MM", "BARRAS", CATALOGO
    ).tipo_carga_canonico == "BARRAS"
    assert resolver_material_tipo_carga(
        "ROLLO HORMIGON 12 MM", catalogo_materiales=CATALOGO
    ).tipo_carga_canonico == "ROLLOS"


def test_tipo_explicito_contradictorio_exige_revision():
    resultado = resolver_material_tipo_carga(
        "BARRA HORMIGON 16 MM", "ROLLOS", CATALOGO
    )
    assert "TIPO_CARGA_CONTRADICTORIO" in resultado.contradicciones


@pytest.mark.parametrize("texto", ["HORMIGON 16 MM", "PLANA 38X3MM", "MALLA ACMA"])
def test_tipo_no_derivable_sin_forma_explicita(texto):
    assert resolver_material_tipo_carga(texto).tipo_carga_canonico is None


def test_no_usa_cliente_destino_chofer_patente():
    resultado = resolver_material_tipo_carga(
        "", contexto={"cliente": "BARRAS", "destino": "ROLLOS", "chofer": "ACERO", "patente": "ABCD12"}
    )
    assert resultado.material_canonico is None
    assert resultado.tipo_carga_canonico is None
    assert set(resultado.trazabilidad["contexto_ignorado"]) == {"cliente", "destino", "chofer", "patente"}


def test_no_mezcla_lineas_de_documentos_distintos():
    resultado = resolver_material_tipo_carga(
        catalogo_materiales=CATALOGO,
        lineas_ocr=[
            CandidatoMaterial("BARRA HORMIGON 16 MM", documento_id="A"),
            CandidatoMaterial("ROLLO HORMIGON 12 MM", documento_id="B"),
        ],
    )
    assert "MULTIPLES_DOCUMENTOS_VISIBLES" in resultado.contradicciones
    assert resultado.estado_resolucion is EstadoResolucion.REQUIERE_REVISION


def test_snapshot_es_inmutable_y_no_modifica_catalogo():
    catalogo = {"materiales": [dict(CATALOGO["materiales"][0])]}
    snapshot = crear_snapshot_catalogo_materiales(catalogo)
    resolver_material_tipo_carga("FIERRO 16", catalogo_materiales=snapshot)
    assert catalogo["materiales"][0]["descripcion_oficial"] == "BARRA HORMIGON 16 MM"
    with pytest.raises(TypeError):
        snapshot.registros["M1"]["descripcion_oficial"] = "OTRO"
