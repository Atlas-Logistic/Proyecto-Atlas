from atlas_core.inteligencia import EstadoResolucion, resolver_material_tipo_carga


def test_dos_familias_en_lineas_independientes_proponen_mixto_sin_inventar_material():
    resultado = resolver_material_tipo_carga("BARRAS\nBOBINAS")
    assert resultado.tipo_carga_canonico == "MIXTO"
    assert resultado.material_canonico is None
    assert resultado.estado_resolucion is EstadoResolucion.PROPUESTO


def test_otra_seccion_no_se_convierte_en_material():
    resultado = resolver_material_tipo_carga(
        lineas_ocr=[{"valor_original": "BARRAS", "contexto": "OBSERVACIONES"}]
    )
    assert resultado.tipo_carga_canonico is None


def test_taxonomia_restringida_rechaza_valor_inventado():
    resultado = resolver_material_tipo_carga("", "PALLETS")
    assert resultado.tipo_carga_canonico is None


def test_descripcion_multilinea_no_pierde_duplicados_ni_puntuacion():
    texto = "BARRAS: A630-420H, 16 MM\nBARRAS: A630-420H, 16 MM"
    resultado = resolver_material_tipo_carga(texto)
    assert resultado.descripcion_material_original == texto
    assert resultado.lineas_material_originales == tuple(texto.splitlines())


def test_calidad_baja_no_confirma_material():
    catalogo = {"materiales": [{
        "material_id": "M1", "descripcion_oficial": "BARRA ESPECIAL",
        "tipo_carga": "BARRAS", "estado_calidad": "CONFIRMADO",
        "estado_vigencia": "ACTIVO",
    }]}
    resultado = resolver_material_tipo_carga(
        catalogo_materiales=catalogo,
        lineas_ocr=[{"valor_original": "BARRA ESPECIAL", "calidad": 0.4}],
    )
    assert resultado.confianza == 0.0
    assert resultado.estado_resolucion is EstadoResolucion.REQUIERE_REVISION


def test_dos_formas_en_misma_linea_son_contradiccion_no_mixto_seguro():
    resultado = resolver_material_tipo_carga("BARRAS Y BOBINAS")
    assert "DOS_FORMAS_EN_MISMA_LINEA" in resultado.contradicciones
