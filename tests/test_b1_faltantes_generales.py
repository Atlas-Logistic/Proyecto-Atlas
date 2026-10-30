"""Consultas generales de datos faltantes ("qué viajes tienen campos
faltantes"): sin campo nombrado, el viaje cumple si le falta al menos uno de
los campos del catálogo, con la misma regla de ausencia de `ausente`. La
respuesta consolida por viaje, conserva `resultado.faltantes` v1 y no altera
las consultas específicas. `viajes.csv` sintético."""
from __future__ import annotations

import csv
import json

import pytest

from atlas_core.cli_consulta_atlas import _respuesta_a_dict
from atlas_core.consultas_atlas import ConsultaAtlas, METRICA_LISTAR_VIAJES, validar_consulta
from atlas_core.interpretador_consultas import (
    CAMPOS_FALTANTE_GENERAL, FILTRO_AUSENTE_ALGUNO, construir_catalogos_consulta, interpretar_consulta_determinista,
)
from atlas_core.responder_consulta_atlas import (
    ESTADO_AMBIGUA, ESTADO_NO_INTERPRETABLE, ESTADO_OK, responder_consulta_atlas,
)

COLUMNAS = ("viaje_id", "numero_transporte", "fecha", "estado", "numeros_guia", "clientes", "obras_destino",
            "choferes", "ruts_chofer", "patentes_tracto", "patentes_rampla", "materiales", "tipos_carga",
            "peso_total_viaje_kg", "direccion_entrega", "localidad_entrega", "region_entrega",
            "planta_origen_nombre", "documentos_operacionales", "evidencias_documentos")


def _doc(guia, **campos):
    doc = {"numero_guia": guia, "archivo": f"{guia}.jpg", "descripcion_material": "BARRA 12MM", "peso_kg": "1000",
           "cliente": "CLIENTE A", "obra_destino": "OBRA A", "chofer": "PATRICK ORTIZ", "fecha": "30-09-2026",
           "direccion_entrega": "AV. CARRASCAL 5060", "rut_chofer": "12345678-9", "localidad_entrega": "Quinta Normal",
           "region_entrega": "Metropolitana", "patente_tracto": "XF3629", "tipo_carga": "BARRAS",
           "planta_origen_nombre": "PLANTA A", "numero_transporte": "0000000001"}
    doc.update(campos)
    return doc


def _viaje(vid, docs, **overrides):
    fila = {
        "viaje_id": vid, "numero_transporte": f"00000{vid[1:]:0>5}", "fecha": "30-09-2026", "estado": "CONFIRMADO",
        "numeros_guia": " | ".join(d["numero_guia"] for d in docs), "clientes": "CLIENTE A",
        "obras_destino": "OBRA A", "choferes": "PATRICK ORTIZ", "ruts_chofer": "12345678-9",
        "patentes_tracto": "XF3629", "patentes_rampla": "JK1234",
        "materiales": " | ".join(d["descripcion_material"] for d in docs if d["descripcion_material"]),
        "tipos_carga": "BARRAS", "peso_total_viaje_kg": "1000", "direccion_entrega": "AV. CARRASCAL 5060",
        "localidad_entrega": "Quinta Normal", "region_entrega": "Metropolitana", "planta_origen_nombre": "PLANTA A",
        "documentos_operacionales": json.dumps(docs), "evidencias_documentos": json.dumps(docs),
    }
    fila.update(overrides)
    return fila


@pytest.fixture
def ruta(tmp_path):
    filas = [
        # Sin material en su única guía.
        _viaje("v1", [_doc("100", descripcion_material="")]),
        # Dos guías: la 201 sin material y sin peso; además falta la comuna del viaje.
        _viaje("v2", [_doc("200"), _doc("201", descripcion_material="NO DETERMINADO", peso_kg="0")],
               localidad_entrega=""),
        # Sin chofer (dato de guía en la fila documental).
        _viaje("v3", [_doc("300", chofer="", rut_chofer="")], choferes="", ruts_chofer=""),
        # Sin fecha: campo sin operación B1.
        _viaje("v4", [_doc("400", fecha="")], fecha=""),
        # Sólo le falta la rampla: un camión rígido no la lleva, no es faltante general.
        _viaje("v5", [_doc("500")], patentes_rampla=""),
        # Completos.
        _viaje("v6", [_doc("600")]),
        _viaje("v7", [_doc("700"), _doc("701")]),
    ]
    destino = tmp_path / "viajes.csv"
    with destino.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)
    return destino


def _responder(pregunta, ruta):
    return responder_consulta_atlas(pregunta, ruta_viajes=ruta)


def _ids(respuesta):
    return [v["viaje_id"] for v in respuesta.resultado.viajes_soporte]


PREGUNTAS_GENERALES = (
    "qué viajes tienen campos faltantes",
    "qué viajes les falta información",
    "qué viajes tienen campos vacíos",
    "Qué viajes tienen datos faltantes?",
    "a qué viajes les faltan algunos datos",
    "qué viajes tienen información incompleta",
    "qué viajes están incompletos",
    "viajes con información pendiente de completar",
    "muéstrame los viajes con campos sin completar",
    "qué viajes no tienen toda la información",
    "qué viajes tienen campos en blanco",
    "a qué viajes les fata informacion",
    "qué viajes tienen datos que faltan",
)


@pytest.mark.parametrize("pregunta", PREGUNTAS_GENERALES)
def test_consultas_generales_listan_los_viajes_con_algun_faltante(pregunta, ruta):
    respuesta = _responder(pregunta, ruta)
    assert respuesta.estado == ESTADO_OK, respuesta.texto_respuesta
    filtros = respuesta.resultado.consulta_interpretada.filtros
    assert filtros == {FILTRO_AUSENTE_ALGUNO: ",".join(CAMPOS_FALTANTE_GENERAL)}
    # Nunca todos los viajes: los completos y el que sólo no tiene rampla quedan fuera.
    assert _ids(respuesta) == ["v1", "v2", "v3", "v4"]
    assert "4 viajes" in respuesta.texto_respuesta


def test_cuantos_cuenta_viajes_sin_duplicar(ruta):
    respuesta = _responder("cuántos viajes tienen datos incompletos", ruta)
    assert respuesta.resultado.resultado == 4
    assert respuesta.texto_respuesta.startswith("4 viajes (con algún dato faltante).")


def test_rampla_no_es_faltante_general_pero_sigue_consultable(ruta):
    assert "patente_rampla" not in CAMPOS_FALTANTE_GENERAL
    assert _ids(_responder("qué viajes sin rampla", ruta)) == ["v5"]
    assert "patente de rampla" in _responder("qué viajes tienen campos faltantes", ruta).texto_respuesta


def test_contrato_faltantes_v1_por_guia_y_campo_realmente_ausente(ruta):
    salida = _respuesta_a_dict(_responder("qué viajes tienen campos faltantes", ruta))
    contrato = salida["resultado"]["faltantes"]
    assert contrato["version"] == 1
    pares = sorted((i["viaje_id"], i["campo"], i["numero_guia"], i["nivel"]) for i in contrato["items"])
    assert pares == [
        ("v1", "material", "100", "GUIA"),
        ("v2", "comuna", None, "VIAJE"),
        ("v2", "material", "201", "GUIA"),
        ("v2", "peso", "201", "GUIA"),
        ("v3", "chofer", "300", "GUIA"),
        ("v3", "rut", "300", "GUIA"),
        ("v4", "fecha", "400", "GUIA"),
    ]
    # La guía 200 del viaje v2 tiene todo: nunca se atribuye un faltante a todas las guías.
    assert all(i["numero_guia"] != "200" for i in contrato["items"])


def test_correccion_solo_con_operacion_compatible(ruta):
    items = _respuesta_a_dict(_responder("qué viajes les falta información", ruta))["resultado"]["faltantes"]["items"]
    por_campo = {(i["viaje_id"], i["campo"]): i for i in items}
    assert por_campo[("v1", "material")]["correccion_habilitada"] is True
    assert por_campo[("v3", "chofer")]["operaciones"][0]["accion"] == "DOCUMENTO_CORREGIR_CHOFER_OPERACIONAL"
    for clave in (("v4", "fecha"), ("v2", "comuna"), ("v3", "rut")):
        assert por_campo[clave]["correccion_habilitada"] is False
        assert por_campo[clave]["limitacion"]
    assert not any(i["correccion_habilitada"] and not any(o["habilitada"] for o in i["operaciones"]) for i in items)


def test_soporte_una_fila_por_viaje_con_todos_sus_faltantes(ruta):
    soporte = _respuesta_a_dict(_responder("qué viajes tienen campos faltantes", ruta))["resultado"]["soporte"]
    assert soporte["columnas"][-1] == "Datos faltantes"
    assert soporte["resumen"] == "4 viajes con datos faltantes"
    faltantes = {fila[1]: fila[-1] for fila in soporte["filas"]}
    assert faltantes["0000000002"] == "material, comuna, peso"
    assert faltantes["0000000003"] == "RUT, chofer"
    assert len(soporte["filas"]) == 4


def test_texto_separa_guias_dato_del_viaje_y_revisiones(ruta):
    texto = _responder("qué viajes tienen campos faltantes", ruta).texto_respuesta
    assert "7 faltantes: 6 en guías y 1 sólo en el dato consolidado del viaje" in texto
    assert "No incluye revisiones operacionales pendientes" in texto


@pytest.mark.parametrize("pregunta, viajes, filtros", (
    ("muéstrame los viajes sin material", ["v1", "v2"], {"ausente": "material"}),
    ("a qué viajes les falta información del material", ["v1", "v2"], {"ausente": "material"}),
    ("cuantos viajes no tienen peso", ["v2"], {"ausente": "peso"}),
    ("cuantos viajes sin fecha", ["v4"], {"ausente": "fecha"}),
    ("cuantos viajes hay", ["v1", "v2", "v3", "v4", "v5", "v6", "v7"], {}),
))
def test_consultas_especificas_sin_cambios(pregunta, viajes, filtros, ruta):
    respuesta = _responder(pregunta, ruta)
    assert respuesta.resultado.consulta_interpretada.filtros == filtros
    assert sorted(_ids(respuesta)) == viajes
    assert "algún dato faltante" not in respuesta.texto_respuesta


@pytest.mark.parametrize("pregunta", (
    "qué viajes tienen campos faltantes por revisar",
    "qué viajes tienen datos pendientes",
    "qué viajes tienen pendientes",
    "viajes con información incompleta en revisión",
))
def test_ambiguo_entre_faltantes_y_revisiones_pide_aclaracion(pregunta, ruta):
    respuesta = _responder(pregunta, ruta)
    assert respuesta.estado == ESTADO_AMBIGUA
    assert respuesta.resultado is None
    assert "revisiones operacionales pendientes" in respuesta.texto_respuesta
    assert respuesta.opciones_aclaracion == (
        "qué viajes tienen datos faltantes", "muéstrame los viajes con revisión pendiente",
    )


def test_las_opciones_de_aclaracion_no_son_ambiguas(ruta):
    assert _responder("qué viajes tienen datos faltantes", ruta).estado == ESTADO_OK


def test_revision_sin_faltantes_conserva_su_consulta(ruta):
    respuesta = _responder("cuántos viajes requieren revisión", ruta)
    assert respuesta.resultado.consulta_interpretada.filtros == {"estado": "REQUIERE_REVISION"}


def test_condicion_desconocida_sigue_sin_aplicarse(ruta):
    for pregunta in ("a qué viajes les falta información del color", "a qué viajes les falta el color"):
        respuesta = _responder(pregunta, ruta)
        assert respuesta.estado == ESTADO_NO_INTERPRETABLE
        assert "No pude aplicar la condición" in respuesta.texto_respuesta


def test_faltantes_generales_por_guia_se_consultan_por_viaje(ruta):
    respuesta = _responder("qué guías tienen campos faltantes", ruta)
    assert respuesta.estado == ESTADO_NO_INTERPRETABLE
    assert "por viaje" in respuesta.texto_respuesta


def test_compone_con_periodo_sin_perder_el_filtro(ruta):
    viajes = [_viaje("v9", [_doc("900")])]
    consulta, _ = interpretar_consulta_determinista(
        "cuántos viajes con datos faltantes hubo el 30-09-2026", catalogos=construir_catalogos_consulta(viajes),
    )
    assert consulta.filtros[FILTRO_AUSENTE_ALGUNO] == ",".join(CAMPOS_FALTANTE_GENERAL)
    assert consulta.filtros.get("fecha_desde") == "2026-09-30"


def test_validador_acepta_el_filtro_y_rechaza_campos_desconocidos():
    validar_consulta(ConsultaAtlas(metrica=METRICA_LISTAR_VIAJES, filtros={FILTRO_AUSENTE_ALGUNO: "material,peso"}))
    with pytest.raises(ValueError):
        validar_consulta(ConsultaAtlas(metrica=METRICA_LISTAR_VIAJES, filtros={FILTRO_AUSENTE_ALGUNO: "color"}))


def test_incompleto_tecnico_no_es_faltante_general(ruta):
    for pregunta in ("viajes incompletos técnicos", "cuántos viajes están incompletos técnicamente"):
        consulta, _ = interpretar_consulta_determinista(pregunta, catalogos=construir_catalogos_consulta([]))
        assert FILTRO_AUSENTE_ALGUNO not in consulta.filtros
