"""Bloque CONSULTAS ATLAS V1 -- orquestador de extremo a extremo (Bloque
9/11/13/14/18/21 del ticket). `viajes.csv` sintético propio."""
from __future__ import annotations

import csv
import json

from atlas_core.consultas_atlas import DOMINIO_INCIDENCIAS_DOCUMENTALES, ConsultaAtlas
from atlas_core.proveedor_interpretacion_consultas import (
    ProveedorInterpretacionConsultaSimulado,
    RespuestaSimuladaInterpretacion,
)
from atlas_core.responder_consulta_atlas import (
    ESTADO_AMBIGUA,
    ESTADO_FUENTE_NO_DISPONIBLE,
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


# --- Bloque B1 V2 -- Bloque 6/7: la consulta determinística válida pero
# semánticamente incompatible se descarta y escala a B1 en vez de
# ejecutarse tal cual (el bug real: "22 viajes" para una pregunta de km) ---

def test_pregunta_de_kms_plural_se_resuelve_determinista_sin_gastar_b1(tmp_path):
    """Bloque 10/17 -- "kms" (plural) ya está en el vocabulario: se
    resuelve determinísticamente, sin gastar una llamada a B1."""
    ruta = tmp_path / "viajes.csv"
    _escribir_viajes(ruta, [_fila(choferes="JUAN PEREZ", distancia_km="12.5")])
    pregunta = "cuantos kms hizo juan perez"
    proveedor = ProveedorInterpretacionConsultaSimulado(respuestas_por_pregunta={})
    r = responder_consulta_atlas(pregunta, ruta_viajes=ruta, proveedor_interpretacion=proveedor)
    assert proveedor.preguntas_recibidas == []
    assert "12.5 km calculados" in r.texto_respuesta


def test_semantica_incompatible_fuerza_b1_en_vez_de_responder_viajes(tmp_path):
    """Bloque 7 -- un nombre propio no reconocido (aquí "Retamal", ajeno
    al catálogo de esta fixture) cede a B1 (ya lo hacía en V1); si B1
    identifica bien la métrica de distancia, la respuesta final usa esa
    métrica corregida, nunca COUNT_VIAJES."""
    ruta = tmp_path / "viajes.csv"
    _escribir_viajes(ruta, [_fila(choferes="JUAN PEREZ", distancia_km="12.5")])
    pregunta = "¿Cuántos km recorrió Retamal?"
    proveedor = ProveedorInterpretacionConsultaSimulado(respuestas_por_pregunta={
        pregunta: RespuestaSimuladaInterpretacion(
            consulta=ConsultaAtlas(metrica="SUM_KM", filtros={"chofer": "JUAN PEREZ"}),
        ),
    })
    r = responder_consulta_atlas(pregunta, ruta_viajes=ruta, proveedor_interpretacion=proveedor)
    assert proveedor.preguntas_recibidas == [pregunta]
    assert r.estado == ESTADO_OK
    assert "12.5 km calculados" in r.texto_respuesta


def test_b1_tampoco_puede_producir_consulta_semanticamente_incompatible(tmp_path):
    """Bloque 6/7 -- el validador semántico se aplica también a la
    salida de B1, no sólo a la del determinístico: si B1 devuelve
    COUNT_VIAJES para una pregunta de km, nunca se ejecuta tal cual."""
    ruta = tmp_path / "viajes.csv"
    _escribir_viajes(ruta, [_fila(choferes="JUAN PEREZ")])
    pregunta = "¿Cuántos km recorrió Retamal?"
    proveedor = ProveedorInterpretacionConsultaSimulado(respuestas_por_pregunta={
        pregunta: RespuestaSimuladaInterpretacion(
            consulta=ConsultaAtlas(metrica="COUNT_VIAJES", filtros={"chofer": "JUAN PEREZ"}),
        ),
    })
    r = responder_consulta_atlas(pregunta, ruta_viajes=ruta, proveedor_interpretacion=proveedor)
    assert r.estado == ESTADO_NO_INTERPRETABLE
    assert "Retamal" in r.texto_respuesta


# --- Bloque B1 V2 -- Caso real C: COUNT_DISTINCT_CHOFER, nunca viajes ---

def test_cuantos_choferes_trabajaron_cuenta_personas_no_viajes(tmp_path):
    ruta = tmp_path / "viajes.csv"
    _escribir_viajes(ruta, [
        _fila(numero_transporte="T1", choferes="JUAN PEREZ"),
        _fila(numero_transporte="T2", choferes="JUAN PEREZ"),
        _fila(numero_transporte="T3", choferes="PEDRO GOMEZ"),
    ])
    r = responder_consulta_atlas("¿Cuántos choferes trabajaron este mes?", ruta_viajes=ruta)
    assert r.estado == ESTADO_OK
    assert r.resultado.resultado == 2
    assert "2 choferes" in r.texto_respuesta
    assert "viaje" not in r.texto_respuesta.split("(")[0]  # nunca "N viajes" en el cuerpo principal


# --- Bloque B1 V2 -- dominio INCIDENCIAS_DOCUMENTALES: repositorio
# canónico real, nunca contando viajes REVISAR (Bloque 4.A/9) ---

def _escribir_incidencias(ruta, registros):
    ruta.write_text(json.dumps({"version_formato": 1, "incidencias": registros}), encoding="utf-8")


def _incidencia(**overrides):
    base = {
        "incidencia_id": "abc", "contexto": "CLIENTE X", "numero_guia": "1", "numero_transporte": "T1",
        "campo": "obra_destino", "valor_documental": "X", "valor_canonico": "Y",
        "tipo_incidencia": "OBRA_DOCUMENTAL_INCONSISTENTE", "evidencia": [], "fecha_deteccion": "2026-08-01T00:00:00+00:00",
        "estado": "DETECTADA", "fuente_resolucion": "", "actor": "", "decision_id": "",
    }
    base.update(overrides)
    return base


def test_cuantas_incidencias_documentales_hay_lee_repositorio_canonico(tmp_path):
    ruta_viajes = tmp_path / "viajes.csv"
    _escribir_viajes(ruta_viajes, [_fila(estado="REQUIERE_REVISION")] * 22)  # nunca 22 viajes
    ruta_incidencias = tmp_path / "incidencias_documentales.json"
    _escribir_incidencias(ruta_incidencias, [_incidencia(numero_guia="1"), _incidencia(numero_guia="2")])
    r = responder_consulta_atlas(
        "¿Cuántas incidencias documentales hay?", ruta_viajes=ruta_viajes, ruta_incidencias=ruta_incidencias,
    )
    assert r.estado == ESTADO_OK
    assert r.resultado.consulta_interpretada.dominio == DOMINIO_INCIDENCIAS_DOCUMENTALES
    assert "2 incidencias documentales registradas" in r.texto_respuesta
    assert "22" not in r.texto_respuesta


def test_incidencias_con_archivo_ausente_es_cero_real(tmp_path):
    """`ruta_incidencias` SÍ se indicó (raíz Atlas resuelta), pero el
    archivo todavía no existe -- eso es cero real (mismo criterio que
    `src/incidencias_documentales.js`: "archivo ausente no es error")."""
    ruta_viajes = tmp_path / "viajes.csv"
    _escribir_viajes(ruta_viajes, [_fila()])
    ruta_incidencias_inexistente = tmp_path / "no_existe" / "incidencias_documentales.json"
    r = responder_consulta_atlas(
        "¿Cuántas incidencias documentales hay?", ruta_viajes=ruta_viajes, ruta_incidencias=ruta_incidencias_inexistente,
    )
    assert r.estado == ESTADO_SIN_RESULTADOS
    assert r.resultado.resultado == 0


# --- Bloque B1 V2.1 (regresión "3 -> 0 sin cambio real de datos") --
# nunca afirmar "0 incidencias" con la misma confianza cuando la fuente
# ni siquiera se indicó (Desktop sin raíz resuelta o desactualizado) ---

def test_incidencias_sin_ruta_indicada_nunca_afirma_cero_con_confianza(tmp_path):
    ruta_viajes = tmp_path / "viajes.csv"
    _escribir_viajes(ruta_viajes, [_fila()])
    r = responder_consulta_atlas("¿Cuántas incidencias documentales hay?", ruta_viajes=ruta_viajes, ruta_incidencias=None)
    assert r.estado == ESTADO_FUENTE_NO_DISPONIBLE
    assert r.resultado is None
    assert "0" not in r.texto_respuesta
    assert "no significa que no existan" in r.texto_respuesta


# --- Bloque UNIVERSAL V1 -- dominio EVENTOS de extremo a extremo ---

def _escribir_envio(raiz_atlas, envio_id, registro):
    directorio = raiz_atlas / "operacion" / "mobile" / "envios" / envio_id
    directorio.mkdir(parents=True, exist_ok=True)
    (directorio / "envio.json").write_text(json.dumps(registro), encoding="utf-8")


def test_cuantas_estadias_tuvo_retamal_de_extremo_a_extremo(tmp_path):
    ruta_viajes = tmp_path / "viajes.csv"
    _escribir_viajes(ruta_viajes, [
        _fila(numero_transporte="T1", choferes="CRISTOPHER RETAMAL"),
        _fila(numero_transporte="T2", choferes="CRISTOPHER RETAMAL"),
        _fila(numero_transporte="T3", choferes="PEDRO GOMEZ"),
    ])
    _escribir_envio(tmp_path, "e1", {
        "envio_id": "e1", "tipo_novedad": "TIENE_ESTADIA",
        "resultado_asociacion": {"numero_transporte": "T1"}, "recibido_en": "2026-08-20T10:00:00+00:00",
    })
    _escribir_envio(tmp_path, "e2", {
        "envio_id": "e2", "tipo_novedad": "TIENE_ESTADIA",
        "resultado_asociacion": {"numero_transporte": "T2"}, "recibido_en": "2026-08-21T10:00:00+00:00",
    })
    _escribir_envio(tmp_path, "e3", {
        "envio_id": "e3", "tipo_novedad": "DOBLE_VUELTA",
        "resultado_asociacion": {"numero_transporte": "T3"}, "recibido_en": "2026-08-21T10:00:00+00:00",
    })
    r = responder_consulta_atlas(
        "¿Cuántas estadías tuvo Retamal?", ruta_viajes=ruta_viajes, raiz_atlas=tmp_path,
    )
    assert r.estado == ESTADO_OK
    assert r.resultado.resultado == 2
    assert "CRISTOPHER RETAMAL tuvo 2 estadías" in r.texto_respuesta


def test_eventos_sin_raiz_atlas_nunca_afirma_cero_con_confianza(tmp_path):
    ruta_viajes = tmp_path / "viajes.csv"
    _escribir_viajes(ruta_viajes, [_fila()])
    r = responder_consulta_atlas("¿Cuántas estadías tuvo Juan Perez?", ruta_viajes=ruta_viajes, raiz_atlas=None)
    assert r.estado == ESTADO_FUENTE_NO_DISPONIBLE
    assert r.resultado is None
    assert "no significa que no existan" in r.texto_respuesta


def test_eventos_sin_envios_es_cero_real_no_fuente_no_disponible(tmp_path):
    ruta_viajes = tmp_path / "viajes.csv"
    _escribir_viajes(ruta_viajes, [_fila(choferes="JUAN PEREZ")])
    r = responder_consulta_atlas("¿Cuántas estadías tuvo Juan Perez?", ruta_viajes=ruta_viajes, raiz_atlas=tmp_path)
    assert r.estado == ESTADO_SIN_RESULTADOS
    assert r.resultado.resultado == 0


# --- Bloque UNIVERSAL V1 -- RELACIÓN de extremo a extremo ---

def test_que_patentes_ha_usado_retamal_de_extremo_a_extremo(tmp_path):
    ruta_viajes = tmp_path / "viajes.csv"
    _escribir_viajes(ruta_viajes, [_fila(choferes="CRISTOPHER RETAMAL", patentes_tracto="BPHR67")])
    r = responder_consulta_atlas("¿Qué patentes ha usado Retamal?", ruta_viajes=ruta_viajes)
    assert r.estado == ESTADO_OK
    assert r.resultado.resultado == ("BPHR67",)
    assert "BPHR67" in r.texto_respuesta
