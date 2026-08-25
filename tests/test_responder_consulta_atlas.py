"""Bloque CONSULTAS ATLAS V1 -- orquestador de extremo a extremo (Bloque
9/11/13/14/18/21 del ticket). `viajes.csv` sintético propio."""
from __future__ import annotations

import csv

from atlas_core.consultas_atlas import ConsultaAtlas
from atlas_core.proveedor_interpretacion_consultas import (
    ProveedorInterpretacionConsultaSimulado,
    RespuestaSimuladaInterpretacion,
)
from atlas_core.responder_consulta_atlas import (
    ESTADO_AMBIGUA,
    ESTADO_NO_INTERPRETABLE,
    ESTADO_OK,
    ESTADO_SIN_RESULTADOS,
    responder_consulta_atlas,
)

COLUMNAS = (
    "viaje_id", "numero_transporte", "fecha", "estado", "numeros_guia", "clientes",
    "obras_destino", "choferes", "patentes_tracto", "patentes_rampla", "materiales",
    "tipos_carga", "peso_total_viaje_kg", "distancia_km", "duracion_min",
    "direccion_entrega", "localidad_entrega",
)


def _escribir_viajes(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _fila(**overrides):
    base = {c: "" for c in COLUMNAS}
    base.update({
        "viaje_id": "v1", "numero_transporte": "T1", "fecha": "18-08-2026", "estado": "CONFIRMADO",
        "numeros_guia": "1", "clientes": "CLIENTE A", "obras_destino": "OBRA A",
        "choferes": "JUAN PEREZ", "patentes_tracto": "AA1111", "materiales": "ROLLO HORMIGON",
        "tipos_carga": "ROLLOS", "peso_total_viaje_kg": "1000", "distancia_km": "10.0",
        "duracion_min": "20.0", "direccion_entrega": "CALLE FALSA 123", "localidad_entrega": "MAIPU",
    })
    base.update(overrides)
    return base


def test_pregunta_valida_devuelve_ok_con_soporte(tmp_path):
    ruta = tmp_path / "viajes.csv"
    _escribir_viajes(ruta, [_fila(numero_transporte="T1"), _fila(numero_transporte="T2", choferes="PEDRO GOMEZ")])
    r = responder_consulta_atlas("¿Cuántos viajes hizo Juan Perez?", ruta_viajes=ruta)
    assert r.estado == ESTADO_OK
    assert "1 viaje" in r.texto_respuesta
    assert r.resultado is not None
    assert len(r.resultado.viajes_soporte) == 1


def test_sin_resultados_no_es_error(tmp_path):
    ruta = tmp_path / "viajes.csv"
    # "BARRAS" debe existir en ALGUNA fila para que el intérprete lo
    # reconozca como valor real de tipo_carga (nunca inventa un valor
    # que el dataset no tenga) -- la combinación consultada (Juan Perez
    # + barras) sigue sin ninguna coincidencia real.
    _escribir_viajes(ruta, [
        _fila(numero_transporte="T1", choferes="JUAN PEREZ", tipos_carga="ROLLOS"),
        _fila(numero_transporte="T2", choferes="PEDRO GOMEZ", tipos_carga="BARRAS"),
    ])
    r = responder_consulta_atlas("¿Cuántos viajes hizo Juan Perez con barras?", ruta_viajes=ruta)
    assert r.estado == ESTADO_SIN_RESULTADOS
    assert "No encontré" in r.texto_respuesta


def test_ambiguedad_devuelve_opciones_de_aclaracion(tmp_path):
    ruta = tmp_path / "viajes.csv"
    _escribir_viajes(ruta, [
        _fila(numero_transporte="T1", choferes="JUAN PEREZ"),
        _fila(numero_transporte="T2", choferes="JUAN GOMEZ"),
    ])
    r = responder_consulta_atlas("¿Cuántos viajes hizo Juan?", ruta_viajes=ruta)
    assert r.estado == ESTADO_AMBIGUA
    assert set(r.opciones_aclaracion) == {"JUAN PEREZ", "JUAN GOMEZ"}
    assert "¿Cuál quieres consultar?" in r.texto_respuesta


def test_no_interpretable_sin_b1_no_inventa_respuesta(tmp_path):
    ruta = tmp_path / "viajes.csv"
    _escribir_viajes(ruta, [_fila()])
    r = responder_consulta_atlas("Hola, ¿cómo estás?", ruta_viajes=ruta)
    assert r.estado == ESTADO_NO_INTERPRETABLE
    assert r.resultado is None


def test_nombre_no_reconocido_nunca_responde_sobre_todos_los_viajes(tmp_path):
    ruta = tmp_path / "viajes.csv"
    _escribir_viajes(ruta, [_fila(numero_transporte="T1"), _fila(numero_transporte="T2")])
    r = responder_consulta_atlas("¿Cuántos viajes hizo Lazcano?", ruta_viajes=ruta)
    assert r.estado == ESTADO_NO_INTERPRETABLE
    assert "Lazcano" in r.texto_respuesta


def test_toneladas_se_formatean_desde_peso_kg(tmp_path):
    ruta = tmp_path / "viajes.csv"
    _escribir_viajes(ruta, [_fila(peso_total_viaje_kg="1500")])
    r = responder_consulta_atlas("¿Cuántas toneladas transportó Juan Perez?", ruta_viajes=ruta)
    assert r.estado == ESTADO_OK
    assert "1.5 toneladas" in r.texto_respuesta


# --- Bloque 21: B1 sólo se invoca cuando el camino rápido no basta ---

def test_no_invoca_b1_si_la_consulta_es_determinista(tmp_path):
    ruta = tmp_path / "viajes.csv"
    _escribir_viajes(ruta, [_fila()])
    proveedor = ProveedorInterpretacionConsultaSimulado(respuestas_por_pregunta={})
    responder_consulta_atlas("¿Cuántos viajes hizo Juan Perez?", ruta_viajes=ruta, proveedor_interpretacion=proveedor)
    assert proveedor.preguntas_recibidas == []


def test_invoca_b1_solo_cuando_el_camino_rapido_no_reconoce_nada(tmp_path):
    ruta = tmp_path / "viajes.csv"
    _escribir_viajes(ruta, [_fila(choferes="JUAN PEREZ")])
    pregunta = "dime algo sobre el transporte de Juan"
    proveedor = ProveedorInterpretacionConsultaSimulado(respuestas_por_pregunta={
        pregunta: RespuestaSimuladaInterpretacion(
            consulta=ConsultaAtlas(metrica="COUNT_VIAJES", filtros={"chofer": "JUAN PEREZ"}),
        ),
    })
    r = responder_consulta_atlas(pregunta, ruta_viajes=ruta, proveedor_interpretacion=proveedor)
    assert proveedor.preguntas_recibidas == [pregunta]
    assert r.estado == ESTADO_OK
    assert r.resultado.resultado == 1


def test_b1_no_puede_producir_metrica_invalida(tmp_path):
    """Bloque 20 -- toda salida de B1 pasa por el mismo validador que la
    ruta determinística; una métrica inventada se rechaza."""
    ruta = tmp_path / "viajes.csv"
    _escribir_viajes(ruta, [_fila()])
    pregunta = "algo raro"
    proveedor = ProveedorInterpretacionConsultaSimulado(respuestas_por_pregunta={
        pregunta: RespuestaSimuladaInterpretacion(consulta=ConsultaAtlas(metrica="CALCULA_LO_QUE_SEA")),
    })
    from atlas_core.responder_consulta_atlas import ESTADO_CONSULTA_INVALIDA
    r = responder_consulta_atlas(pregunta, ruta_viajes=ruta, proveedor_interpretacion=proveedor)
    assert r.estado == ESTADO_CONSULTA_INVALIDA


def test_b1_abstencion_no_inventa_consulta(tmp_path):
    ruta = tmp_path / "viajes.csv"
    _escribir_viajes(ruta, [_fila()])
    pregunta = "algo sin sentido operacional"
    proveedor = ProveedorInterpretacionConsultaSimulado(
        respuestas_por_pregunta={pregunta: RespuestaSimuladaInterpretacion(consulta=None)}
    )
    r = responder_consulta_atlas(pregunta, ruta_viajes=ruta, proveedor_interpretacion=proveedor)
    assert r.estado == ESTADO_NO_INTERPRETABLE
