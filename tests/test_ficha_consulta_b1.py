"""Ficha integral de consulta B1: solo lectura, ausentes y conflictos explícitos."""
import csv
import json

import pytest

from atlas_core.b1_operador import OperadorB1
from atlas_core.ficha_consulta_b1 import construir_ficha, interpretar_consulta_ficha
from tests.test_acciones_operacionales import entorno  # noqa: F401 -- fixture

COLUMNAS_DATASET = ["archivo", "numero_guia", "numero_transporte", "fecha", "chofer", "rut_chofer", "cliente",
                    "obra_destino", "patente_tracto", "patente_rampla", "descripcion_material", "tipo_carga",
                    "peso_kg", "hora_entrada_aza", "hora_salida_aza", "direccion_entrega", "despachar_a_crudo",
                    "localidad_entrega", "planta_origen_nombre", "estado_operacional"]


def fila(archivo, guia, **extra):
    base = {"archivo": archivo, "numero_guia": guia, "numero_transporte": "0000372894", "fecha": "26-11-2026",
            "chofer": "SALOMON PIZARRO", "rut_chofer": "18091588-5", "cliente": "TORRES OCARANZA LTDA",
            "obra_destino": "TORRES OCARANZA LTDA QUILICURA", "patente_tracto": "TG8925", "patente_rampla": "JF9575",
            "descripcion_material": "B HORMIGON 32MM 12M", "tipo_carga": "BARRAS", "peso_kg": "1000",
            "hora_entrada_aza": "07:12", "hora_salida_aza": "07:40", "direccion_entrega": "CERRO SAN LUIS 9890",
            "despachar_a_crudo": "CERRO SAN LUIS 9890 QUILICURA", "localidad_entrega": "Quilicura",
            "planta_origen_nombre": "AZA COLINA", "estado_operacional": "OK"}
    base.update(extra)
    return base


def viaje(transporte, filas, **extra):
    guias = [f["numero_guia"] for f in filas]
    base = {"viaje_id": f"v-{transporte}-{guias[0]}", "numero_transporte": transporte, "fecha": filas[0]["fecha"],
            "estado": "CONFIRMADO", "cantidad_documentos": str(len(filas)),
            "documentos": " | ".join(f["archivo"] for f in filas), "numeros_guia": " | ".join(guias),
            "clientes": filas[0]["cliente"], "choferes": filas[0]["chofer"], "ruts_chofer": filas[0]["rut_chofer"],
            "patentes_tracto": filas[0]["patente_tracto"], "patentes_rampla": filas[0]["patente_rampla"],
            "planta_origen_nombre": "AZA COLINA", "hora_entrada_aza": filas[0]["hora_entrada_aza"],
            "hora_salida_aza": filas[0]["hora_salida_aza"],
            "peso_total_viaje_kg": str(sum(int(f["peso_kg"]) for f in filas)),
            "localidad_entrega": "QUILICURA", "direccion_entrega": "CERRO SAN LUIS 9890",
            "evidencias_documentos": json.dumps(filas),
            "entregas": json.dumps([{"localidad_entrega": "QUILICURA", "destino_operacional": "CERRO SAN LUIS 9890",
                                     "numeros_guia": guias, "clientes": [filas[0]["cliente"]]}])}
    base.update(extra)
    return base


def campo(campos, nombre):
    return next(c for c in campos if c["campo"] == nombre)


@pytest.mark.parametrize("texto,esperado", [
    ("Datos de la guía 492295", ("GUIA", "492295")),
    ("Datos del viaje 0000372894", ("VIAJE", "0000372894")),
    ("Datos del transporte 0000372894", ("TRANSPORTE", "0000372894")),
    ("¿Muéstrame los datos completos de la guía N° 492296?", ("GUIA", "492296")),
    ("ficha del transporte nro 372894", ("TRANSPORTE", "372894")),
    ("Corrige la guía 492295: material X", None),
    ("cuántos viajes hizo el transporte 372894", None),
    ("datos de la guía 492295 y 492296", None),
    ("datos de la guía 492295 cambia el peso a 10", None),
])
def test_interpreta_solo_pedidos_de_ficha(texto, esperado):
    assert interpretar_consulta_ficha(texto) == esperado


def test_transporte_con_dos_guias_conflicto_y_ausentes_explicitos():
    a = fila("mobile/a/original.jpg", "492295", hora_entrada_aza="12:00", hora_salida_aza="No encontrado")
    b = fila("mobile/b/original.jpg", "492296", localidad_entrega="", direccion_entrega="",
             despachar_a_crudo="CERRO SAN LUIS 989O OUILICURA")
    v = viaje("0000372894", [a, b], hora_entrada_aza="", hora_salida_aza="07:40",
              evidencias_documentos=json.dumps([a, b]))
    r = construir_ficha("TRANSPORTE", "0000372894", filas=[a, b], viajes=[v])
    assert r["estado"] == "FICHA" and r["solo_lectura"] is True
    assert "preview" not in r and r["ficha"]["edicion"]["disponible"] is False
    guias = r["ficha"]["guias"]
    assert [g["documento"]["numero_guia"] for g in guias] == ["492295", "492296"]
    assert guias[0]["original"]["archivo"] == "mobile/a/original.jpg"
    # Ausente: explícito, nunca rellenado con otra guía.
    salida = campo(guias[0]["campos"], "hora_salida_aza")
    assert salida["estado"] == "AUSENTE" and salida["valor"] is None
    # Comuna sin extracción: la entrega del reporte la informa, con su fuente.
    comuna = campo(guias[1]["campos"], "localidad_entrega")
    assert comuna["estado"] == "OK" and comuna["valor"] == "QUILICURA"
    assert [x["fuente"] for x in comuna["valores"]] == ["REPORTE_DESKTOP"]
    assert campo(guias[1]["campos"], "direccion_entrega")["estado"] == "AUSENTE"
    # Consolidado: la hora de entrada difiere entre guías -> conflicto con origen.
    consolidado = r["ficha"]["viajes"][0]
    entrada = campo(consolidado["campos"], "hora_entrada_aza")
    assert entrada["estado"] == "CONFLICTO" and entrada["nivel"] == "VIAJE"
    assert {(x["fuente"], x["valor"]) for x in entrada["valores"]} == {("GUIA 492295", "12:00"),
                                                                      ("GUIA 492296", "07:12")}
    assert campo(consolidado["campos"], "hora_salida_aza")["ausente_en"] == ["492295"]
    assert campo(consolidado["campos"], "peso_total_viaje_kg")["estado"] == "OK"
    assert consolidado["entregas"][0]["comuna"] == "QUILICURA"
    obligatorios = {"localidad_entrega", "direccion_entrega", "cliente", "obra_destino", "descripcion_material",
                    "peso_kg", "fecha", "chofer", "patente_tracto", "patente_rampla", "planta_origen_nombre",
                    "hora_entrada_aza", "hora_salida_aza"}
    assert obligatorios <= {c["campo"] for c in guias[0]["campos"]}
    assert all(c["nivel"] == "GUIA" for g in guias for c in g["campos"])


def test_guia_sola_consolida_con_todas_las_guias_del_viaje():
    a = fila("a", "492295", hora_entrada_aza="12:00")
    b = fila("b", "492296")
    r = construir_ficha("GUIA", "492295", filas=[a, b], viajes=[viaje("0000372894", [a, b])])
    assert [g["documento"]["numero_guia"] for g in r["ficha"]["guias"]] == ["492295"]
    assert campo(r["ficha"]["viajes"][0]["campos"], "hora_entrada_aza")["estado"] == "CONFLICTO"
    assert r["ficha"]["viajes"][0]["numeros_guia"] == ["492295", "492296"]


def test_extraccion_contra_reporte_y_formato_no_es_conflicto():
    a = fila("a", "1", peso_kg="1500", rut_chofer="18.091.588-5", patente_tracto="TG-8925")
    reporte = dict(a, peso_kg="1000", rut_chofer="18091588-5", patente_tracto="TG8925")
    r = construir_ficha("GUIA", "1", filas=[a], viajes=[viaje("9", [a], evidencias_documentos=json.dumps([reporte]))])
    peso = campo(r["ficha"]["guias"][0]["campos"], "peso_kg")
    assert peso["estado"] == "CONFLICTO"
    assert {(x["fuente"], x["valor"]) for x in peso["valores"]} == {("EXTRACCION", "1500"), ("REPORTE_DESKTOP", "1000")}
    assert campo(r["ficha"]["guias"][0]["campos"], "rut_chofer")["estado"] == "OK"
    assert campo(r["ficha"]["guias"][0]["campos"], "patente_tracto")["estado"] == "OK"


def test_peso_total_distinto_de_la_suma_es_conflicto():
    a, b = fila("a", "1", peso_kg="1000"), fila("b", "2", peso_kg="500")
    r = construir_ficha("VIAJE", "9", filas=[a, b], viajes=[viaje("9", [a, b], peso_total_viaje_kg="1000")])
    total = campo(r["ficha"]["viajes"][0]["campos"], "peso_total_viaje_kg")
    assert total["estado"] == "CONFLICTO"
    assert ("SUMA_GUIAS", "1500") in {(x["fuente"], x["valor"]) for x in total["valores"]}


def test_viaje_de_cinco_guias_y_viaje_por_numero_de_guia():
    filas = [fila(f"d{i}", str(483935 + i), numero_transporte="0000368327", peso_kg=str(100 * (i + 1)))
             for i in (3, 0, 4, 1, 2)]
    v = viaje("0000368327", filas)
    r = construir_ficha("VIAJE", "0000368327", filas=filas, viajes=[v])
    assert [g["documento"]["numero_guia"] for g in r["ficha"]["guias"]] == [str(483935 + i) for i in range(5)]
    assert campo(r["ficha"]["viajes"][0]["campos"], "peso_total_viaje_kg")["valor"] == "1500"
    # «viaje <guía>»: el viaje que contiene esa guía, con todas sus guías.
    r2 = construir_ficha("VIAJE", "483937", filas=filas, viajes=[v])
    assert len(r2["ficha"]["guias"]) == 5


def test_transporte_en_dos_viajes_y_guia_sin_viaje():
    a, b = fila("a", "1", numero_transporte="77"), fila("b", "2", numero_transporte="77", fecha="27-11-2026")
    c = fila("c", "3", numero_transporte="77")
    r = construir_ficha("TRANSPORTE", "0000000077", filas=[a, b, c], viajes=[viaje("77", [a]), viaje("77", [b])])
    assert [g["viaje_indice"] for g in r["ficha"]["guias"]] == [0, 1, None]
    assert len(r["ficha"]["viajes"]) == 2
    assert any("2 viajes" in x for x in r["ficha"]["avisos"])
    assert any("no tienen viaje" in x for x in r["ficha"]["avisos"])


def test_documento_del_reporte_sin_fila_en_la_extraccion():
    a, b = fila("a", "1"), fila("b", "2")
    r = construir_ficha("VIAJE", "0000372894", filas=[a], viajes=[viaje("0000372894", [a, b])])
    sin_extraccion = [g for g in r["ficha"]["guias"] if not g["en_extraccion"]]
    assert [g["documento"]["numero_guia"] for g in sin_extraccion] == ["2"]
    assert {v["fuente"] for c in sin_extraccion[0]["campos"] for v in c["valores"]} == {"REPORTE_DESKTOP"}


def test_no_encontrado():
    r = construir_ficha("GUIA", "999", filas=[fila("a", "1")], viajes=[])
    assert r["estado"] == "RESULTADO_LECTURA" and r["ficha"] is None and "No encontré la guía 999" in r["mensaje"]


def escribir_raiz(entorno, filas, viajes):
    with (entorno["actual"] / "analisis_completo_guias.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS_DATASET, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)
    columnas = sorted({k for v in viajes for k in v})
    with (entorno["actual"] / "viajes.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas, delimiter=";")
        w.writeheader()
        w.writerows(viajes)


@pytest.mark.parametrize("derivar", [False, True])
def test_operador_consultar_devuelve_ficha_sin_escribir(entorno, derivar):  # noqa: F811
    a, b = fila("a", "492295", hora_entrada_aza="12:00"), fila("b", "492296")
    escribir_raiz(entorno, [a, b], [viaje("0000372894", [a, b])])
    antes = {p: p.read_bytes() for p in entorno["raiz"].rglob("*") if p.is_file()}
    r = OperadorB1(entorno["raiz"]).consultar("Datos del transporte 0000372894", derivar_operacionales=derivar)
    assert r["estado"] == "FICHA" and len(r["ficha"]["guias"]) == 2
    assert {p: p.read_bytes() for p in entorno["raiz"].rglob("*") if p.is_file()} == antes


def test_operador_atender_devuelve_ficha_sin_tocar_la_conversacion(entorno):  # noqa: F811
    a = fila("a", "492295")
    escribir_raiz(entorno, [a], [viaje("0000372894", [a])])
    antes = {p: p.read_bytes() for p in entorno["raiz"].rglob("*") if p.is_file()}
    r = OperadorB1(entorno["raiz"]).atender("conv-1", "Datos de la guía 492295")
    assert r["estado"] == "FICHA" and "preview" not in r
    assert {p: p.read_bytes() for p in entorno["raiz"].rglob("*") if p.is_file()} == antes
