from atlas_core.catalogo_destinos import direccion_confirmada_coincide


def _coincidentes(calles, documental, comuna):
    return [calle for calle in calles if direccion_confirmada_coincide(calle, documental, comuna_confirmada=comuna)]


def test_truncamiento_ocr_menor_se_acepta_solo_con_anclas_completas():
    assert direccion_confirmada_coincide(
        "CALLE D LOTE 27 Y 28 PARQUE INDUSTRIAL",
        "CALLE D LOTE 27 Y 28 PARQUE INDRUST CORONEL",
        comuna_confirmada="CORONEL",
    )


def test_un_token_no_estructural_con_typo_menor_se_acepta():
    assert direccion_confirmada_coincide(
        "AVENIDA NORTE LOTE 41 CENTRO LOGISTICO",
        "AVENIDA NORTE LOTE 41 CENTRO LOGISTICA COMUNA ALFA",
        comuna_confirmada="COMUNA ALFA",
    )


def test_numero_distinto_se_rechaza():
    assert not direccion_confirmada_coincide(
        "CALLE ALFA LOTE 17 PARQUE TECNICO",
        "CALLE ALFA LOTE 18 PARQUE TECNIC COMUNA ALFA",
        comuna_confirmada="COMUNA ALFA",
    )
    # La misma regla cubre una letra intercalada en el maestro: no depende
    # de un alias del token documental.
    assert direccion_confirmada_coincide(
        "CALLE D LOTE 27 Y 28 PARQUE INDRUSTRIAL",
        "CALLE D LOTE 27 Y 28 PARQUE INDRUST CORONEL",
        comuna_confirmada="CORONEL",
    )


def test_numero_adicional_contradictorio_se_rechaza():
    assert not direccion_confirmada_coincide(
        "CALLE D LOTE 27 Y 28 PARQUE INDUSTRIAL",
        "CALLE D LOTE 27 Y 28 PARQUE INDRUST 29 CORONEL",
        comuna_confirmada="CORONEL",
    )


def test_lote_distinto_se_rechaza():
    assert not direccion_confirmada_coincide(
        "CAMINO BETA LOTE 72 AREA INDUSTRIAL",
        "CAMINO BETA LOTE 73 AREA INDUSTRI COMUNA BETA",
        comuna_confirmada="COMUNA BETA",
    )


def test_comuna_distinta_se_rechaza():
    assert not direccion_confirmada_coincide(
        "CALLE GAMMA LOTE 8 PARQUE INDUSTRIAL",
        "CALLE GAMMA LOTE 8 PARQUE INDRUST COMUNA DISTINTA",
        comuna_confirmada="COMUNA GAMMA",
    )


def test_dos_destinos_compatibles_dejan_ambiguedad_para_el_llamador():
    documental = "CALLE DELTA LOTE 5 PARQUE INDUSTRI COMUNA DELTA"
    candidatos = _coincidentes(
        ["CALLE DELTA LOTE 5 PARQUE INDUSTRIAL", "CALLE DELTA LOTE 5 PARQUE INDUSTRIAS"],
        documental, "COMUNA DELTA",
    )
    assert len(candidatos) == 2


def test_misma_obra_no_convierte_direccion_contradictoria_en_coincidencia():
    assert not direccion_confirmada_coincide(
        "CALLE EPSILON LOTE 9 PARQUE INDUSTRIAL",
        "RUTA ZETA LOTE 9 PARQUE INDRUST COMUNA EPSILON",
        comuna_confirmada="COMUNA EPSILON",
    )


def test_prefijo_sin_lote_o_comuna_no_basta():
    assert not direccion_confirmada_coincide(
        "CALLE D 27 PARQUE INDUSTRIAL",
        "CALLE D 27 PARQUE INDRUST CORONEL",
        comuna_confirmada="CORONEL",
    )
    assert not direccion_confirmada_coincide(
        "CALLE D LOTE 27 PARQUE INDUSTRIAL",
        "CALLE D LOTE 27 PARQUE INDRUST CORONEL",
    )


def test_otra_via_documental_impide_tolerancia():
    assert not direccion_confirmada_coincide(
        "CALLE D LOTE 27 Y 28 PARQUE INDUSTRIAL",
        "CALLE D LOTE 27 Y 28 PARQUE INDRUST RUTA ZETA CORONEL",
        comuna_confirmada="CORONEL",
    )


def test_direccion_exacta_se_mantiene_y_la_funcion_no_escribe_catalogos():
    assert direccion_confirmada_coincide(
        "PASAJE OMEGA 120", "PASAJE OMEGA 120 COMUNA OMEGA", comuna_confirmada="COMUNA OMEGA"
    )
