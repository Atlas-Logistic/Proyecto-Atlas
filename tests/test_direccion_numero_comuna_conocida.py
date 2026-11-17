import pytest

from atlas_core.catalogo_destinos import direccion_confirmada_coincide, separar_numero_comuna


@pytest.mark.parametrize("calle,documental,comuna", [
    ("VISTA CLARA 2351", "VISTA CLARA 2351CERRILLOS", "CERRILLOS"),
    ("GALVARINO 8501", "GALVARINO8501QUILICURA", "QUILICURA"),
    ("SANTA ISABEL 585", "SANTA ISABEL585 SANTIAGO LAMPA", "LAMPA"),
])
def test_direccion_conocida_con_formato_ocr(calle, documental, comuna):
    assert direccion_confirmada_coincide(calle, documental, comuna_confirmada=comuna)


@pytest.mark.parametrize("documental,comuna", [
    ("VISTA CLARA 23510CERRILLOS", "CERRILLOS"),
    ("VISTA CLARA 2351CERRILLOS", "MAIPU"),
    ("VISTA CLARA 2351CERRILLOSXYZ", "CERRILLOS"),
    ("VISTA CLARA 2351B", "CERRILLOS"),
])
def test_no_inventa_coincidencia(documental, comuna):
    assert not direccion_confirmada_coincide("VISTA CLARA 2351", documental, comuna_confirmada=comuna)


def test_no_separa_sufijo_desconocido_ni_cambia_numero():
    assert separar_numero_comuna("VISTA CLARA 2351CERRILLOS") == "VISTA CLARA 2351 CERRILLOS"
    assert separar_numero_comuna("VISTA CLARA 2351CERRILLOSXYZ") == "VISTA CLARA 2351CERRILLOSXYZ"


def test_confirmacion_posterior_prevalece_y_no_afecta_otra_guia():
    from atlas_core.destino_operacional import proyectar_destino

    fila = {"archivo": "a.jpg", "numero_guia": "484907",
            "despachar_a_crudo": "VISTA CLARA 2351CERRILLOS",
            "direccion_entrega": "VISTA CLARA 2351", "localidad_entrega": "CERRILLOS"}
    otra = {**fila, "archivo": "b.jpg", "numero_guia": "483576"}
    documento = {"archivo": "a.jpg", "numero_guia": "484907"}
    ledger = {"aplicaciones": [
        {"tipo": "DESTINO_OPERACIONAL_DOCUMENTO", "documento": documento,
         "destino_operacional": {"direccion": "VISTA CLARA 2351", "comuna": "CERRILLOS"}},
        {"tipo": "DESTINO_OPERACIONAL_DOCUMENTO", "documento": documento,
         "destino_operacional": {"direccion": "OTRA CALLE 100", "comuna": "RENCA"}},
    ]}
    assert direccion_confirmada_coincide("VISTA CLARA 2351", fila["despachar_a_crudo"], comuna_confirmada="CERRILLOS")
    proyectada = proyectar_destino(fila, ledger)
    assert (proyectada["direccion_entrega"], proyectada["localidad_entrega"]) == ("OTRA CALLE 100", "RENCA")
    assert proyectada["despachar_a_crudo"] == fila["despachar_a_crudo"]
    assert proyectar_destino(otra, ledger) == otra
