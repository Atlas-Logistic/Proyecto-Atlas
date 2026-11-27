"""Edición integral de la ficha B1 por el canal oficial (sintético)."""
import csv
import json

import pytest

from atlas_core import destino_operacional
from atlas_core.b1_operador import OperadorB1, interpretar_determinista
from atlas_core.edicion_ficha_b1 import ErrorLoteFicha, codificar_lote, decodificar_lote
from tests.test_acciones_operacionales import entorno  # noqa: F401 -- fixture

CONV = "ficha-prueba"


def filas(entorno):  # noqa: F811
    with entorno["dataset"].open(encoding="utf-8-sig", newline="") as archivo:
        return {f["numero_guia"]: f for f in csv.DictReader(archivo, delimiter=";")}


def ledger(entorno):  # noqa: F811
    return json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))["aplicaciones"]


def cambio(guia, campo, valor):
    return {"archivo": f"{guia}.jpeg", "numero_guia": guia, "campo": campo, "valor": valor}


@pytest.fixture
def b1(entorno, monkeypatch):  # noqa: F811
    monkeypatch.setattr(destino_operacional, "calcular_ruta_operacional", lambda fila, direccion, comuna, **_: {
        "estado_ruta": destino_operacional.RUTA_CALCULADA, "distancia_km": "9.5", "duracion_min": "12",
        "proveedor_ruta": "PRUEBA", "comuna": comuna})
    return OperadorB1(entorno["raiz"], usuario="JAVIER_DESKTOP")


def test_lote_codifica_y_rechaza_formas_invalidas():
    lote = [cambio("500001", "peso_kg", "12000"), cambio("500001", "localidad_entrega", "ÑUÑOA")]
    assert decodificar_lote(codificar_lote(lote)) == lote
    for malo in ([cambio("500001", "rut_chofer", "1-9")], [cambio("500001", "peso_kg", "")],
                 [cambio("500001", "peso_kg", "1"), cambio("500001", "peso_kg", "2")], []):
        with pytest.raises(ErrorLoteFicha):
            decodificar_lote(codificar_lote(malo))
    with pytest.raises(ErrorLoteFicha):
        decodificar_lote("@ficha-lote:%%%")


def test_consulta_solo_lectura_rechaza_el_lote_y_el_operador_lo_recibe(entorno, b1):  # noqa: F811
    texto = codificar_lote([cambio("500001", "peso_kg", "12000")])
    assert b1.consultar(texto)["estado"] == "RECHAZADA"
    assert b1.consultar(texto, derivar_operacionales=True) == {"estado": "REQUIERE_OPERADOR"}


def test_varios_campos_y_guias_preview_confirmacion_y_auditoria(entorno, b1):  # noqa: F811
    antes = entorno["dataset"].read_bytes()
    texto = codificar_lote([
        cambio("500001", "peso_kg", "12000"), cambio("500001", "hora_entrada_aza", "07:12"),
        cambio("500001", "fecha", "26-11-2026"), cambio("500002", "peso_kg", "8000"),
        cambio("500002", "patente_rampla", "JF9575")])
    preview = b1.atender(CONV, texto)
    assert preview["estado"] == "PREVIEW_PENDIENTE" and preview["accion"] == "FICHA_EDITAR"
    tabla = preview["tablas"][0]
    assert tabla["columnas"] == ["Guía", "Campo", "Valor anterior", "Valor nuevo"]
    assert ["500001", "Peso", "(sin dato)", "12000"] in tabla["filas"]
    assert ["500001", "Hora de entrada", "(sin dato)", "07:12"] in tabla["filas"]
    assert len(tabla["filas"]) == 5
    assert entorno["dataset"].read_bytes() == antes, "el preview no escribe"
    resultado = b1.atender(CONV, "sí")
    assert resultado["estado"] == "EJECUTADA", resultado
    assert resultado["resultado"]["aplicados"] == 5
    f = filas(entorno)
    assert (f["500001"]["peso_kg"], f["500001"]["hora_entrada_aza"], f["500001"]["fecha"]) == ("12000", "07:12", "26-11-2026")
    assert (f["500002"]["peso_kg"], f["500002"]["patente_rampla"]) == ("8000", "JF9575")
    humanas = [a for a in ledger(entorno) if a.get("confirmado_por") == "JAVIER_DESKTOP"]
    assert len(humanas) == 5
    registro = json.loads((entorno["actual"] / "acciones_operacionales.json").read_text(encoding="utf-8"))
    assert sum("ficha" in str(a.get("referencia", "")).lower() for a in registro["auditoria"]) == 5
    assert b1.pendiente(CONV) is None


def test_un_cambio_invalido_rechaza_el_lote_completo(entorno, b1):  # noqa: F811
    antes = entorno["dataset"].read_bytes()
    r = b1.atender(CONV, codificar_lote([cambio("500001", "peso_kg", "12000"), cambio("500002", "hora_salida_aza", "25:99")]))
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "LOTE_CON_ERRORES"
    assert r["tablas"][0]["filas"][0][:2] == ["500002", "Hora de salida"]
    assert b1.pendiente(CONV) is None and entorno["dataset"].read_bytes() == antes
    assert b1.atender(CONV, "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"


def test_cancelar_no_escribe(entorno, b1):  # noqa: F811
    antes = entorno["dataset"].read_bytes()
    assert b1.atender(CONV, codificar_lote([cambio("500001", "peso_kg", "12000")]))["estado"] == "PREVIEW_PENDIENTE"
    assert b1.atender(CONV, "no")["estado"] == "CANCELADA"
    assert entorno["dataset"].read_bytes() == antes


def test_documento_cambiado_desde_la_ficha_no_se_corrige(entorno, b1):  # noqa: F811
    r = b1.atender(CONV, codificar_lote([{**cambio("500001", "peso_kg", "12000"), "numero_guia": "400001"}]))
    assert r["estado"] == "RECHAZADA" and "folio" in r["tablas"][0]["filas"][0][3]


def test_direccion_y_comuna_un_solo_destino_y_comuna_sola_conserva_la_direccion(entorno, b1):  # noqa: F811
    # Sin dirección vigente, la comuna sola no basta.
    r = b1.atender(CONV, codificar_lote([cambio("500001", "localidad_entrega", "PROVIDENCIA")]))
    assert r["estado"] == "RECHAZADA" and "dirección" in r["tablas"][0]["filas"][0][3]
    r = b1.atender(CONV, codificar_lote([cambio("500001", "direccion_entrega", "AV PROVIDENCIA 1234"),
                                         cambio("500001", "localidad_entrega", "PROVIDENCIA")]))
    assert r["estado"] == "PREVIEW_PENDIENTE" and len(r["tablas"][0]["filas"]) == 1
    assert r["tablas"][0]["filas"][0][3] == "AV PROVIDENCIA 1234 · PROVIDENCIA"
    assert b1.atender(CONV, "sí")["estado"] == "EJECUTADA"
    # Ahora sólo la comuna: se conserva la dirección confirmada.
    r = b1.atender(CONV, codificar_lote([cambio("500001", "localidad_entrega", "ÑUÑOA")]))
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert r["tablas"][0]["filas"][0][3] == "AV PROVIDENCIA 1234 · NUNOA"
    assert b1.atender(CONV, "sí")["estado"] == "EJECUTADA"
    destinos = [a for a in ledger(entorno) if a.get("tipo") == destino_operacional.TIPO]
    assert destinos[-1]["destino_operacional"] == {"direccion": "AV PROVIDENCIA 1234", "comuna": "NUNOA"}
    assert destinos[-1]["ruta_operacional"]["estado_ruta"] == destino_operacional.RUTA_CALCULADA
    # Una comuna que no es oficial se rechaza.
    r = b1.atender(CONV, codificar_lote([cambio("500001", "localidad_entrega", "NARNIA")]))
    assert r["estado"] == "RECHAZADA"


def test_folio_general_al_final_del_lote(entorno, b1):  # noqa: F811
    # 500001 tiene una revisión pendiente: su folio no se cambia (protección existente).
    r = b1.atender(CONV, codificar_lote([cambio("500001", "numero_guia", "500008")]))
    assert r["estado"] == "RECHAZADA" and "tarjetas pendientes" in r["tablas"][0]["filas"][0][3]
    r = b1.atender(CONV, codificar_lote([cambio("500002", "numero_guia", "500009"), cambio("500002", "peso_kg", "12000")]))
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert [f[1] for f in r["tablas"][0]["filas"]] == ["Peso", "N° de guía"]
    assert b1.atender(CONV, "sí")["estado"] == "EJECUTADA"
    f = filas(entorno)
    assert "500002" not in f and f["500009"]["peso_kg"] == "12000" and f["500009"]["archivo"] == "500002.jpeg"
    ultima = [a for a in ledger(entorno) if a.get("campo") == "numero_guia"][-1]
    assert (ultima["valor_documental"], ultima["valor_corregido"]) == ("500002", "500009")


def test_folio_general_exige_original_y_documento_exacto(entorno, b1):  # noqa: F811
    from atlas_core.acciones_operacionales import CapaAccionesOperacionales
    capa = CapaAccionesOperacionales(entorno["raiz"])
    sin_declarar = capa.previsualizar("DOCUMENTO_CORREGIR_NUMERO_GUIA", {
        "numero_guia": "500002", "numero_guia_corregido": "500009", "archivo": "500002.jpeg"}, actor="B1", origen="B1")
    assert sin_declarar["estado"] == "RECHAZADA"
    sin_archivo = capa.previsualizar("DOCUMENTO_CORREGIR_NUMERO_GUIA", {
        "numero_guia": "500002", "numero_guia_corregido": "500009", "confirmado_contra_original": True},
        actor="B1", origen="B1")
    assert sin_archivo["estado"] == "RECHAZADA"
    ocupado = capa.previsualizar("DOCUMENTO_CORREGIR_NUMERO_GUIA", {
        "numero_guia": "500002", "numero_guia_corregido": "500001", "archivo": "500002.jpeg",
        "confirmado_contra_original": True}, actor="B1", origen="B1")
    assert ocupado["estado"] == "RECHAZADA" and "otro documento" in ocupado["mensaje"]


def test_chofer_y_obra_se_resuelven_en_el_catalogo(entorno, b1):  # noqa: F811
    r = b1.atender(CONV, codificar_lote([cambio("500001", "chofer", "ANA SOTO")]))
    assert r["estado"] == "RECHAZADA" and "chofer activo" in r["tablas"][0]["filas"][0][3]
    r = b1.atender(CONV, codificar_lote([cambio("500001", "obra_destino", "OBRA INEXISTENTE")]))
    assert r["estado"] == "RECHAZADA" and "registra la obra" in r["tablas"][0]["filas"][0][3]
    r = b1.atender(CONV, codificar_lote([cambio("500001", "planta_origen_nombre", "PLANTA FANTASMA")]))
    assert r["estado"] == "RECHAZADA"


@pytest.mark.parametrize("texto,accion,esperado", [
    ("La comuna de la guía 500001 es Providencia", "DOCUMENTO_CORREGIR_DESTINO_OPERACIONAL", {"comuna": "PROVIDENCIA"}),
    ("La hora de entrada de la guía 500001 es 7:12", "DOCUMENTO_CORREGIR_CAMPO", {"campo": "hora_entrada_aza", "valor": "07:12"}),
    ("Corrige la hora de salida de la guía 500001 a 07.40 hrs", "DOCUMENTO_CORREGIR_CAMPO", {"campo": "hora_salida_aza", "valor": "07:40"}),
    ("El número de la guía 500001 es 500009", "DOCUMENTO_CORREGIR_NUMERO_GUIA",
     {"numero_guia_corregido": "500009", "confirmado_contra_original": True}),
])
def test_lenguaje_natural_de_los_campos_nuevos(texto, accion, esperado):
    intencion = interpretar_determinista(texto)
    assert intencion is not None and intencion.accion == accion
    assert {k: intencion.parametros[k] for k in esperado} == esperado


@pytest.mark.parametrize("texto", [
    "La patente de la rampla de la guía 500001 es JF9575",  # ambigua con el error documental AZA
    "Corrige el número de guía 500001 a 500009 y cambia el material a BARRA",
    "El número de la guía 500001 es 5000091",
    "El número de la guía 500001 es 500009 y el peso 10",
])
def test_lenguaje_natural_no_interpreta_formas_ambiguas_o_compuestas(texto):
    assert interpretar_determinista(texto) is None


def test_comuna_natural_aplica_por_el_canal(entorno, b1):  # noqa: F811
    b1.atender(CONV, codificar_lote([cambio("500001", "direccion_entrega", "AV PROVIDENCIA 1234"),
                                     cambio("500001", "localidad_entrega", "PROVIDENCIA")]))
    b1.atender(CONV, "sí")
    r = b1.atender(CONV, "La comuna de la guía 500001 es Las Condes")
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert b1.atender(CONV, "sí")["estado"] == "EJECUTADA"
    destinos = [a for a in ledger(entorno) if a.get("tipo") == destino_operacional.TIPO]
    assert destinos[-1]["destino_operacional"] == {"direccion": "AV PROVIDENCIA 1234", "comuna": "LAS CONDES"}


def test_ficha_ofrece_edicion_con_opciones(entorno):  # noqa: F811
    ficha = OperadorB1(entorno["raiz"]).consultar("Datos de la guía 500001")["ficha"]
    assert ficha["edicion"]["disponible"] is True
    assert "localidad_entrega" in ficha["edicion"]["campos_editables"]
    assert "tipo_carga" not in ficha["edicion"]["campos_editables"]
    assert "PROVIDENCIA" in ficha["edicion"]["opciones"]["localidad_entrega"]
    assert "LUIS REYES" in ficha["edicion"]["opciones"]["chofer"]
    assert "ANA SOTO" not in ficha["edicion"]["opciones"]["chofer"]
