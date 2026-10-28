import pytest
from atlas_core.destino_operacional import proyectar_destino, TIPO

@pytest.mark.parametrize("guia", ["482379", "483298", "483251"])
def test_proyeccion_aislada_por_documento_y_sin_derivados_inventados(guia):
    original = {"archivo": guia + ".jpg", "numero_guia": guia, "numero_transporte": "T1",
                "despachar_a_crudo": "RUTCHOFER OCR", "direccion_entrega": "Anterior",
                "latitud_entrega": "-33", "distancia_km": "19"}
    hermana = {**original, "archivo": "hermana.jpg", "numero_guia": "999999"}
    ledger = {"aplicaciones": [{"tipo": TIPO, "documento": {"archivo": original["archivo"], "numero_guia": guia},
                               "destino_operacional": {"direccion": "Calle Sintética 123", "comuna": "Comuna Sintética"}}]}
    proyectada = proyectar_destino(original, ledger)
    assert proyectada["direccion_entrega"] == "Calle Sintética 123"
    assert proyectada["localidad_entrega"] == "Comuna Sintética"
    assert proyectada["despachar_a_crudo"] == original["despachar_a_crudo"]
    assert proyectada["latitud_entrega"] == proyectada["distancia_km"] == ""
    assert original["direccion_entrega"] == "Anterior"
    assert proyectar_destino(hermana, ledger) == hermana


def test_entrada_incompleta_o_identidad_incompleta_no_proyecta():
    fila = {"archivo": "a.jpg", "numero_guia": "1", "direccion_entrega": "Original"}
    ledger = {"aplicaciones": [{"tipo": TIPO, "documento": {"archivo": "a.jpg", "numero_guia": "1"},
                               "destino_operacional": {"direccion": "Calle 1"}}]}
    assert proyectar_destino(fila, ledger) == fila
    assert proyectar_destino({**fila, "numero_guia": ""}, ledger)["direccion_entrega"] == "Original"



def test_proyeccion_invalida_identidad_territorial_y_estado_de_destino_anterior():
    fila = {"archivo": "a.jpg", "numero_guia": "483251", "despachar_a_crudo": "OCR ORIGINAL",
            "direccion_entrega": "CALLE VIEJA 123", "estado_entrega": "RESUELTO",
            "codigo_pais": "CL", "codigo_unidad": "123", "codigo_contexto": "999",
            "longitud_entrega": "-70", "duracion_min": "25"}
    ledger = {"aplicaciones": [{"tipo": TIPO, "documento": {"archivo": "a.jpg", "numero_guia": "483251"},
               "destino_operacional": {"direccion": "GALVARINO 8501", "comuna": "QUILICURA"}}]}
    salida = proyectar_destino(fila, ledger)
    assert salida["despachar_a_crudo"] == "OCR ORIGINAL"
    assert salida["estado_entrega"] == "NO_INTENTADO"
    assert all(salida[c] == "" for c in ("codigo_pais", "codigo_unidad", "codigo_contexto",
                                           "longitud_entrega", "duracion_min"))
    assert fila["estado_entrega"] == "RESUELTO"
