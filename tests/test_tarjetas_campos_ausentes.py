"""Caso real 483526 (transporte 0000367059): peso y destino no leídos sin
ninguna tarjeta. Datos sintéticos con la misma forma."""
import pytest

from atlas_core.b1_operador import instruccion_en_revision
from atlas_core.decisiones_pendientes import (
    MOTIVO_DESTINO_DOCUMENTAL_AUSENTE, detectar_decision_destino_no_resuelto,
    detectar_decisiones_peso_no_disponible,
)
from atlas_core.destino_operacional import TIPO, proyectar_destino


def _fila(**cambios):
    fila = {"archivo": "482526.jpeg", "numero_guia": "483526", "numero_transporte": "0000367059",
            "estado_procesamiento": "OK", "peso_kg": "No encontrado", "despachar_a_crudo": "",
            "direccion_entrega": "", "estado_ruta": "", "motivo_ruta": "", "obra_destino": "CLIENTE EJEMPLO LTDA",
            "cliente": "CLIENTE EJEMPLO LTDA", "planta_origen_id": "planta-1", "indicador_revision": "OK",
            "estado_documental": "OK", "estado_operacional": "REQUIERE_REVISION",
            "fecha_ingesta_utc": "2026-10-28T18:44:36.830728+00:00"}
    fila.update(cambios)
    return fila


def test_peso_no_disponible_genera_tarjeta_solo_para_guias_nuevas():
    tarjetas = detectar_decisiones_peso_no_disponible([_fila()])
    assert [(t["tipo"], t["campo"], t["valor_documental"], t["documento"]["numero_guia"]) for t in tarjetas] == [
        ("PESO_NO_DISPONIBLE", "peso_kg", "No encontrado", "483526")]
    assert tarjetas[0]["valor_normalizado"] == ""  # nunca propone un peso
    for cambios in ({"fecha_ingesta_utc": "2026-10-27T23:59:59+00:00"}, {"fecha_ingesta_utc": ""},
                    {"peso_kg": "28048"}, {"estado_procesamiento": "ERROR"},
                    {"numero_guia": "No encontrado"}):
        assert detectar_decisiones_peso_no_disponible([_fila(**cambios)]) == [], cambios


def test_destino_documental_ausente_genera_tarjeta_de_destino():
    tarjeta = detectar_decision_destino_no_resuelto(archivo="482526.jpeg", fila=_fila())
    assert tarjeta["tipo"] == "DESTINO_NO_RESUELTO"
    assert tarjeta["motivos"] == [MOTIVO_DESTINO_DOCUMENTAL_AUSENTE]
    assert tarjeta["campo"] == "despachar_a_crudo" and tarjeta["valor_documental"] == ""


@pytest.mark.parametrize("cambios", [
    {"fecha_ingesta_utc": "2026-10-20T10:00:00+00:00"},  # histórica: fuera del alcance acordado
    {"planta_origen_id": ""},  # sin origen no se pregunta destino
    {"despachar_a_crudo": "VISTA CLARA 2351 CERRILLOS"},  # hay texto: el ruteo decide
    {"estado_ruta": "RUTA_CALCULADA"},
])
def test_destino_ausente_se_abstiene(cambios):
    assert detectar_decision_destino_no_resuelto(archivo="482526.jpeg", fila=_fila(**cambios)) is None


def test_b1_en_las_tarjetas_traduce_a_las_correcciones_existentes():
    peso = detectar_decisiones_peso_no_disponible([_fila()])[0]
    assert instruccion_en_revision(peso, "el peso correcto es 28.048 kg").upper() == (
        "EN LA GUÍA 483526 EL PESO CORRECTO ES 28.048 KG")
    destino = detectar_decision_destino_no_resuelto(archivo="482526.jpeg", fila=_fila())
    assert instruccion_en_revision(destino, "el destino es VISTA CLARA 2351, CERRILLOS") == (
        "El destino de la guía 483526 es VISTA CLARA 2351, CERRILLOS")


def _ledger(ruta):
    return {"aplicaciones": [{"tipo": TIPO, "documento": {"archivo": "482526.jpeg", "numero_guia": "483526"},
                              "destino_operacional": {"direccion": "VISTA CLARA 2351", "comuna": "CERRILLOS"},
                              "ruta_operacional": ruta}]}


RUTA = {"estado_ruta": "RUTA_CALCULADA", "distancia_km": "21.3", "duracion_min": "28", "comuna": "CERRILLOS"}


def test_destino_confirmado_con_ruta_valida_recalcula_estado_operacional():
    proyectada = proyectar_destino(_fila(), _ledger(RUTA))
    assert (proyectada["direccion_entrega"], proyectada["estado_ruta"]) == ("VISTA CLARA 2351", "RUTA_CALCULADA")
    assert proyectada["estado_operacional"] == "OK"


@pytest.mark.parametrize("cambios,ruta", [
    ({}, {"estado_ruta": "PENDIENTE", "motivo": "MULTIPLES_UBICACIONES_DISPERSAS(4)"}),  # ruta aún no resuelta
    ({}, dict(RUTA, comuna="MAIPU")),  # ruta de otra comuna: no se publica
    ({"indicador_revision": "REVISAR", "estado_documental": "REQUIERE_REVISION"}, RUTA),  # otro problema documental
])
def test_destino_confirmado_no_cierra_lo_que_sigue_pendiente(cambios, ruta):
    assert proyectar_destino(_fila(**cambios), _ledger(ruta))["estado_operacional"] == "REQUIERE_REVISION"


def test_sin_destino_confirmado_la_fila_no_cambia():
    fila = _fila()
    assert proyectar_destino(fila, {"aplicaciones": []}) == fila
