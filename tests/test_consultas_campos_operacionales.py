"""Consultas B1 sobre campos operacionales: presencia/ausencia, entidad
pedida (viajes/guías/transportes), sumas y filtros combinados. Caso real:
"¿Cuántos viajes tienen material ausente?" respondía el total de viajes
porque el filtro se perdía en silencio. `viajes.csv` sintético propio."""
from __future__ import annotations

import csv
import json

import pytest

from atlas_core.consultas_atlas import ConsultaAtlas, ErrorConsultaAtlas, validar_consulta
from atlas_core.responder_consulta_atlas import ESTADO_OK, responder_consulta_atlas

COLUMNAS = (
    "viaje_id", "numero_transporte", "transportes_aza", "fecha", "estado", "numeros_guia", "clientes",
    "obras_destino", "choferes", "ruts_chofer", "patentes_tracto", "patentes_rampla", "materiales",
    "tipos_carga", "peso_total_viaje_kg", "direccion_entrega", "localidad_entrega", "region_entrega",
    "planta_origen_nombre", "documentos_operacionales",
)


def _doc(guia, material="BARRA 12MM", peso="1000", cliente="CLIENTE A"):
    return {"numero_guia": guia, "descripcion_material": material, "peso_kg": peso,
            "cliente": cliente, "obra_destino": "OBRA A", "despachar_a_crudo": "", "archivo": f"{guia}.jpg"}


def _viaje(vid, transporte, docs, **overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "viaje_id": vid, "numero_transporte": transporte, "transportes_aza": transporte,
        "fecha": "30-09-2026", "estado": "CONFIRMADO",
        "numeros_guia": " | ".join(d["numero_guia"] for d in docs),
        "clientes": "CLIENTE A", "obras_destino": "OBRA A", "choferes": "PATRICK ORTIZ",
        "ruts_chofer": "18626166-6", "patentes_tracto": "XF3629",
        "materiales": " | ".join(d["descripcion_material"] for d in docs if d["descripcion_material"]),
        "tipos_carga": "BARRAS", "peso_total_viaje_kg": str(sum(int(d["peso_kg"] or 0) for d in docs)),
        "direccion_entrega": "AV. CARRASCAL 5060", "localidad_entrega": "Quinta Normal",
        "region_entrega": "Metropolitana", "planta_origen_nombre": "AZA COLINA",
        "documentos_operacionales": json.dumps(docs),
    })
    fila.update(overrides)
    return fila


@pytest.fixture
def ruta(tmp_path):
    filas = [
        # Viaje mixto: dos guías, sólo una sin material -> 1 viaje, 1 guía.
        _viaje("v1", "T1", [_doc("100"), _doc("101", material="")]),
        _viaje("v2", "T2", [_doc("200", material="")], choferes="OTRO CHOFER", ruts_chofer="11111111-1",
               localidad_entrega="Quilicura", planta_origen_nombre="AZA RENCA", fecha="01-10-2026"),
        _viaje("v3", "T3", [_doc("300"), _doc("301")], localidad_entrega="QUILICURA",
               obras_destino="CONSTRUMART SA QUILICURA", patentes_rampla="JF9575"),
        _viaje("v4", "T4", [_doc("400")], direccion_entrega="", localidad_entrega="",
               region_entrega="REGIÓN METROPOLITANA"),
    ]
    destino = tmp_path / "viajes.csv"
    with destino.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)
    return destino


def _preguntar(ruta, pregunta):
    respuesta = responder_consulta_atlas(pregunta, ruta_viajes=ruta)
    assert respuesta.estado == ESTADO_OK, respuesta.texto_respuesta
    return respuesta.resultado


def test_cuantos_viajes_con_material_ausente_no_cuenta_el_total(ruta):
    r = _preguntar(ruta, "¿Cuántos viajes tienen material ausente?")
    assert r.consulta_interpretada.filtros == {"ausente": "material"}
    assert r.resultado == 2  # v1 (guía 101) y v2; nunca los 4 viajes


def test_que_guias_no_tienen_material_lista_solo_las_guias_sin_material(ruta):
    r = _preguntar(ruta, "¿Qué guías no tienen material?")
    assert tuple(r.resultado) == ("101", "200")  # nunca la 100 del mismo viaje mixto


def test_guias_sin_material_cuenta_guias_no_viajes(ruta):
    assert _preguntar(ruta, "¿Cuántas guías sin material hay?").resultado == 2


def test_presencia_es_complemento_de_ausencia(ruta):
    con = _preguntar(ruta, "¿Cuántos viajes con destino?").resultado
    sin = _preguntar(ruta, "¿Cuántos viajes sin destino?").resultado
    assert (con, sin) == (3, 1)


def test_cuantos_viajes_hizo_un_chofer(ruta):
    r = _preguntar(ruta, "¿Cuántos viajes hizo Patrick Ortiz?")
    assert r.resultado == 3


def test_viajes_por_rut_con_o_sin_formato(ruta):
    assert _preguntar(ruta, "¿Cuántos viajes hizo el RUT 18.626.166-6?").resultado == 3


def test_que_viajes_fueron_a_una_comuna_prefiere_la_comuna_completa(ruta):
    r = _preguntar(ruta, "¿Qué viajes fueron a Quilicura?")
    assert r.consulta_interpretada.filtros == {"comuna": r.consulta_interpretada.filtros["comuna"]}
    assert {v["viaje_id"] for v in r.resultado} == {"v2", "v3"}  # QUILICURA y Quilicura


def test_kilos_de_un_chofer_suma_peso_sin_doble_conteo(ruta):
    r = _preguntar(ruta, "¿Cuántos kilos llevó Patrick Ortiz?")
    assert r.resultado == 2000 + 2000 + 1000


def test_guias_que_salieron_de_planta_en_fecha(ruta):
    r = _preguntar(ruta, "¿Qué guías salieron de AZA Colina el 30-09-2026?")
    assert r.consulta_interpretada.filtros == {
        "fecha_desde": "2026-09-30", "fecha_hasta": "2026-09-30", "origen": "AZA COLINA",
    }
    assert tuple(r.resultado) == ("100", "101", "300", "301", "400")


def test_transportes_es_entidad_y_no_evidencia_de_cliente(ruta):
    r = _preguntar(ruta, "¿Cuántos transportes hizo Patrick Ortiz?")
    assert r.consulta_interpretada.relacion == "transporte"
    assert r.resultado == 3


def test_region_reune_variantes_de_escritura(ruta):
    assert _preguntar(ruta, "¿Cuántos viajes fueron a la región Metropolitana?").resultado == 4


def test_combinacion_de_filtros(ruta):
    r = _preguntar(ruta, "¿Cuántos viajes sin material hizo Patrick Ortiz?")
    assert r.resultado == 1
    assert _preguntar(ruta, "¿Cuántos viajes con patente rampla?").resultado == 1


def test_validador_rechaza_campo_de_presencia_desconocido():
    with pytest.raises(ErrorConsultaAtlas):
        validar_consulta(ConsultaAtlas(metrica="COUNT_VIAJES", filtros={"ausente": "color"}))
