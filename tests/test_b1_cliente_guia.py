"""B1 -- corrección de CLIENTE dicha como afirmación (caso real 484418: "el
cliente de la guía 484418 es SODIMAC SA" se leía como chofer ↔ patente y
respondía "No encontré un chofer que coincida con CLIENTE DE LA GUÍA
484418"). Reutiliza DOCUMENTO_CORREGIR_CAMPO (campo cliente) con preview,
"sí" y auditoría; la regla general de asociación chofer ↔ vehículo ya no
toma por chofer una referencia a una guía numerada. Sólo fixtures
sintéticas: nunca G: ni datos productivos."""
from __future__ import annotations

import csv
import hashlib
import json

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.b1_operador import OperadorB1, interpretar_determinista
from atlas_core.operaciones_conversacionales import _interpretar
from atlas_core.procesamiento_masivo import COLUMNAS
from tests.test_acciones_operacionales import _EscritorDisponible, entorno  # noqa: F401 -- fixture compartida

CLIENTE = "SODIMAC SA"
INTOCABLES = ("numero_guia", "numero_transporte", "peso_kg", "fecha", "chofer", "rut_chofer", "rut_cliente",
              "patente_tracto", "obra_destino", "despachar_a_crudo", "direccion_entrega", "descripcion_material",
              "archivo")


def _correccion(guia="484418", valor=CLIENTE):
    return {"numero_guia": guia, "campo": "cliente", "valor": valor}


# ------------------------------------------------------------ interpretación

@pytest.mark.parametrize("texto", [
    "el cliente de la guía 484418 es SODIMAC SA",
    "El cliente de la guía 484418 es, SODIMAC SA",
    "El cliente de la guía 484418 es,SODIMAC SA",
    "El cliente de la guía 484418, es SODIMAC SA",
    "El cliente correcto de la guía 484418 es SODIMAC SA",
    "El cliente real de la guia N° 484418 es SODIMAC SA.",
    "cliente de la guía 484418: SODIMAC SA",
    "El cliente de la guía 484418 debe ser SODIMAC SA",
    "El cliente de la guía 484418 debería ser, SODIMAC SA",
    "El cliente de la guía 484418 corresponde a SODIMAC SA",
    "En la guía 484418 el cliente es SODIMAC SA",
    "En la guía 484418, el cliente correcto es, SODIMAC SA",
    "Fija el cliente de la guía 484418 a SODIMAC SA",
    "Corrige el cliente de la guía 484418: SODIMAC SA",
])
def test_afirmaciones_de_cliente_son_correccion_documental(texto):
    intencion = interpretar_determinista(texto)
    assert intencion is not None and intencion.accion == "DOCUMENTO_CORREGIR_CAMPO", (texto, intencion)
    assert intencion.parametros == {**_correccion(), "referencia": " ".join(texto.split())}
    assert intencion.menciones == {}


def test_valor_del_cliente_se_conserva_integro():
    intencion = interpretar_determinista("El cliente de la guía 484418 es, CONSTRUCTORA SANTA ANA, LTDA.")
    assert intencion.parametros["valor"] == "CONSTRUCTORA SANTA ANA, LTDA"


@pytest.mark.parametrize("texto", ["Corrige el cliente de la guía 484418 a SODIMAC SA",
                                   "Cambia el cliente de la guía 484418 por SODIMAC SA"])
def test_frase_canonica_existente_no_cambia(texto):
    intencion = interpretar_determinista(texto)
    assert intencion.accion == "DOCUMENTO_CORREGIR_CAMPO"
    assert intencion.parametros == _correccion()  # mismo resultado de siempre (_DOCUMENTO)


@pytest.mark.parametrize("texto", [
    "El cliente de la guía 484418 es,",
    "El cliente de la guía 484418 es, ",
    "El cliente de la guía 484418 es,,",
    "cliente de la guía 484418:",
    "¿El cliente de la guía 484418 es SODIMAC SA?",
    "¿Qué cliente tiene la guía 484418?",
    "El cliente de la guía 484418",
    "El cliente SODIMAC SA es de la guía 484418",
])
def test_sin_valor_o_pregunta_no_es_correccion_ni_vehiculo(texto):
    intencion = interpretar_determinista(texto)
    assert intencion is None or intencion.accion not in {"DOCUMENTO_CORREGIR_CAMPO", "CHOFER_ASIGNAR_VEHICULO"}, \
        (texto, intencion)


@pytest.mark.parametrize("texto", ["El RUT del cliente de la guía 484418 es 96.792.430-K",
                                   "El código cliente de la guía 484418 es 12345",
                                   "En la guía 484418 el RUT del cliente es 96.792.430-K"])
def test_rut_y_codigo_de_cliente_nunca_se_toman_como_cliente(texto):
    intencion = interpretar_determinista(texto)
    assert intencion is None or intencion.parametros.get("campo") != "cliente", (texto, intencion)
    assert intencion is None or intencion.accion != "CHOFER_ASIGNAR_VEHICULO", (texto, intencion)


# ------------------------------------------------- protección de la asociación

@pytest.mark.parametrize("texto", [
    "El tracto de la guía 484418 es AB1234",
    "La rampla de la guía 484418 es JC4173",
    "La patente de la guía 484418 es AB1234",
    "La fecha de la guía 484418 es 10-11-2026",
    "El transporte de la guía 484418 es 0000369619",
    "El código cliente de la guía 484418 es 12345",
    "La guía N° 484418 usa AB1234",
    "Asocia AB1234 a la guía 484418",
])
def test_referencia_a_guia_numerada_nunca_es_asociacion_chofer_vehiculo(texto):
    assert _interpretar(texto) is None
    intencion = interpretar_determinista(texto)
    assert intencion is None or intencion.accion != "CHOFER_ASIGNAR_VEHICULO", (texto, intencion)


@pytest.mark.parametrize("texto,esperado", [
    ("Pizarro usa JF9575", ("", "PIZARRO", "JF9575")),
    ("Pizarro usa la patente JF9575", ("", "PIZARRO", "JF9575")),
    ("El tracto de Luis Reyes es KN5439", ("TRACTO", "LUIS REYES", "KN5439")),
    ("La rampla de Luis Reyes es JC4173", ("RAMPLA", "LUIS REYES", "JC4173")),
    ("Asocia KN5439 a Luis Reyes", ("", "LUIS REYES", "KN5439")),
    # "guía" sin número no es una referencia a una guía: se conserva como siempre.
    ("Luis Guia usa KN5439", ("", "LUIS GUIA", "KN5439")),
])
def test_asociacion_valida_chofer_vehiculo_se_conserva(texto, esperado):
    assert _interpretar(texto) == esperado
    intencion = interpretar_determinista(texto)
    assert intencion.accion == "CHOFER_ASIGNAR_VEHICULO"
    assert intencion.parametros == {"patente": esperado[2]}
    assert intencion.menciones == {"chofer": esperado[1]}


# ------------------------------------------------------- extremo a extremo

def _filas(entorno):
    with entorno["dataset"].open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _sha(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


@pytest.fixture
def cliente_ilegible(entorno):
    """500001 con cliente mal leído y CLIENTE_SIN_CORROBORAR, como la 484418 real."""
    filas = _filas(entorno)
    for f in filas:
        if f["numero_guia"] == "500001":
            f.update(cliente="1SODTHACSA", rut_cliente="No encontrado", motivos_revision_documento="CLIENTE_SIN_CORROBORAR")
    with entorno["dataset"].open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)
    entorno["b1"] = OperadorB1(entorno["raiz"], usuario="JAVIER", capa=CapaAccionesOperacionales(
        entorno["raiz"], fabrica_escritor=lambda: _EscritorDisponible()))
    return entorno


def test_cliente_con_preview_confirmacion_ledger_y_auditoria(cliente_ilegible):
    e, b1 = cliente_ilegible, cliente_ilegible["b1"]
    texto = "el cliente de la guía 500001 es, SODIMAC SA"
    original = {f["numero_guia"]: f for f in _filas(e)}
    protegidos = {n: _sha(e["actual"] / n) for n in ("analisis_completo_guias.csv", "decisiones_aplicadas.json")}
    catalogos = {p.name: _sha(p) for p in e["cat"].iterdir() if p.is_file()}

    r = b1.atender("conv-cliente", texto)
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert r["accion"] == "DOCUMENTO_CORREGIR_CAMPO"
    assert r["preview"]["valor_actual"] == {"cliente": "1SODTHACSA"}
    assert r["preview"]["valor_propuesto"] == {"cliente": CLIENTE}
    assert "chofer" not in r["mensaje"].lower()
    assert {n: _sha(e["actual"] / n) for n in protegidos} == protegidos  # el preview no escribe

    r = b1.atender("conv-cliente", "sí")
    assert r["estado"] == "EJECUTADA", r
    fila = {f["numero_guia"]: f for f in _filas(e)}["500001"]
    assert fila["cliente"] == CLIENTE
    assert "CLIENTE_SIN_CORROBORAR" not in fila["motivos_revision_documento"]
    for campo in INTOCABLES:
        assert fila[campo] == original["500001"][campo], campo
    otra = {f["numero_guia"]: f for f in _filas(e)}["500002"]
    assert otra == original["500002"]
    ledger = json.loads((e["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))["aplicaciones"]
    [registro] = [a for a in ledger if a.get("campo") == "cliente"]
    assert registro["tipo"] == "CORRECCION_DOCUMENTAL_OPERADOR" and registro["confirmado_por"] == "JAVIER"
    assert registro["valor_corregido"] == CLIENTE and registro["referencia"] == texto
    assert [a["confirmado_por"] for a in b1.capa.auditoria() if a["accion"] == "DOCUMENTO_CORREGIR_CAMPO"] == ["JAVIER"]
    # Ni clientes nuevos ni homologaciones: los catálogos quedan idénticos.
    assert {p.name: _sha(p) for p in e["cat"].iterdir() if p.is_file()} == catalogos


def test_cancelar_no_escribe(cliente_ilegible):
    e, b1 = cliente_ilegible, cliente_ilegible["b1"]
    antes = _sha(e["dataset"])
    assert b1.atender("conv-cliente", "El cliente de la guía 500001 es SODIMAC SA")["estado"] == "PREVIEW_PENDIENTE"
    assert b1.atender("conv-cliente", "no")["estado"] != "EJECUTADA"
    assert _sha(e["dataset"]) == antes


def test_canal_desktop_deriva_la_correccion_de_cliente_al_operador(cliente_ilegible):
    b1 = cliente_ilegible["b1"]
    texto = "El cliente de la guía 500001 es SODIMAC SA"
    assert b1.consultar(texto, derivar_operacionales=True) == {"estado": "REQUIERE_OPERADOR"}
    assert b1.consultar(texto)["estado"] == "RECHAZADA"


def test_frase_de_campo_de_guia_ya_no_responde_chofer_inexistente(cliente_ilegible):
    r = cliente_ilegible["b1"].atender("conv-tracto", "El tracto de la guía 500001 es KN5439")
    assert r.get("accion") != "CHOFER_ASIGNAR_VEHICULO", r
    assert "No encontré un chofer" not in r.get("mensaje", ""), r
