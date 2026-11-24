"""B1 -- CLIENTE, NÚMERO DE TRANSPORTE y PLANTA DE ORIGEN de una guía en
lenguaje natural, siempre por rutas oficiales existentes:

- CLIENTE: DOCUMENTO_CORREGIR_CAMPO, sólo a un cliente ACTIVO del catálogo
  (razón social canónica); nunca se crea un cliente ni se acepta texto libre.
- TRANSPORTE: DOCUMENTO_CORREGIR_CAMPO con 10 dígitos exactos (ceros
  iniciales intactos, sin rellenar).
- PLANTA DE ORIGEN: la revisión ORIGEN_NO_CONFIRMADO pendiente (DECISION_APLICAR
  con SELECCIONAR_OTRA_PLANTA) y una planta CONFIRMADA y ACTIVA; sin revisión
  pendiente no se cambia un origen ya determinado.

Copias sintéticas en tmp_path; nunca G: ni datos productivos."""
from __future__ import annotations

import csv
import hashlib
import json

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales, TIPO_LEDGER_CORRECCION
from atlas_core.b1_operador import OperadorB1, interpretar_determinista, resolver_planta
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from tests.test_acciones_operacionales import _EscritorDisponible, entorno  # noqa: F401 -- fixture compartida
from tests import test_origen_no_confirmado as origen

AZA, RUT_AZA = "ACEROS AZA SA", "92.176.000-0"


def _filas(ruta):
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return {f["archivo"]: f for f in csv.DictReader(archivo, delimiter=";")}


def _sha(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest() if ruta.exists() else None


def _huellas(raiz):
    actual, cat = raiz / "operacion" / "actual", raiz / "catalogos_privados"
    return {n: _sha(p) for n, p in {
        "dataset": actual / "analisis_completo_guias.csv", "ledger": actual / "decisiones_aplicadas.json",
        "bandeja": actual / "decisiones_pendientes.json", "clientes": cat / "clientes.json",
        "plantas": cat / "plantas.json"}.items()}


def _ledger(raiz):
    ruta = raiz / "operacion" / "actual" / "decisiones_aplicadas.json"
    return json.loads(ruta.read_text(encoding="utf-8"))["aplicaciones"]


# ------------------------------------------------------------ interpretación

@pytest.mark.parametrize(("texto", "campo", "valor"), [
    ("El cliente de la guía 488504 es ACEROS AZA SA", "cliente", "ACEROS AZA SA"),
    ("El transporte de la guía 488504 es 0000371852", "numero_transporte", "0000371852"),
    ("El número de transporte de la guía 488504 es 0000371852", "numero_transporte", "0000371852"),
    ("Corrige el transporte de la guía 488504 a 0000371852", "numero_transporte", "0000371852"),
    ("En la guía 488504, el transporte correcto es 0000 371 852", "numero_transporte", "0000371852"),
    ("El transporte de la guía 488504 es 371852", "numero_transporte", "371852"),  # se valida después, sin rellenar
])
def test_interpreta_cliente_y_transporte_como_correccion_de_campo(texto, campo, valor):
    intencion = interpretar_determinista(texto)
    assert intencion is not None and intencion.accion == "DOCUMENTO_CORREGIR_CAMPO", (texto, intencion)
    assert intencion.parametros["numero_guia"] == "488504"
    assert (intencion.parametros["campo"], intencion.parametros["valor"]) == (campo, valor)


@pytest.mark.parametrize("texto", [
    "La planta de origen de la guía 488504 es Colina",
    "La planta de la guía 488504 es Colina",
    "El origen de la guía 488504 es Colina",
    "Corrige la planta de origen de la guía 488504 a Colina",
    "En la guía 488504, la planta de origen es Colina",
])
def test_interpreta_planta_de_origen_como_revision_de_origen(texto):
    intencion = interpretar_determinista(texto)
    assert intencion is not None and intencion.accion == "DECISION_APLICAR", (texto, intencion)
    assert intencion.parametros == {"accion_decision": "SELECCIONAR_OTRA_PLANTA"}
    assert intencion.menciones == {"guia_origen": "488504", "planta": "COLINA"}


def test_rut_y_codigo_del_cliente_no_se_confunden_con_cliente_ni_transporte():
    for texto in ("El RUT del cliente de la guía 488504 es 92.176.000-0",
                  "El código cliente de la guía 488504 es 12345"):
        intencion = interpretar_determinista(texto)
        assert intencion is None or intencion.parametros.get("campo") not in {"cliente", "numero_transporte"}


# ------------------------------------------------------------ cliente

@pytest.fixture
def con_aza(entorno):  # noqa: F811
    CatalogoClientes(entorno["cat"] / "clientes.json").crear(
        razon_social=AZA, rut=RUT_AZA, fuente="TEST", estado_calidad=EstadoCalidadCliente.CONFIRMADO)
    entorno["b1"] = OperadorB1(entorno["raiz"], capa=CapaAccionesOperacionales(
        entorno["raiz"], fabrica_escritor=lambda: _EscritorDisponible()))
    return entorno


def test_cliente_existente_se_escribe_canonico_con_preview_confirmacion_y_auditoria(con_aza):
    e, b1 = con_aza, con_aza["b1"]
    antes, original = _huellas(e["raiz"]), _filas(e["dataset"])
    r = b1.atender("c", "El cliente de la guía 500001 es Aceros Aza S.A.")
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert r["preview"]["valor_actual"] == {"cliente": "CLIENTE UNO SA"}
    assert r["preview"]["valor_propuesto"] == {"cliente": AZA}
    assert _huellas(e["raiz"]) == antes

    assert b1.atender("c", "sí")["estado"] == "EJECUTADA"
    filas = _filas(e["dataset"])
    assert filas["500001.jpeg"]["cliente"] == AZA
    assert {k: v for k, v in filas["500001.jpeg"].items() if k not in {"cliente", "indicador_revision",
            "estado_documental", "estado_operacional", "motivos_revision_documento"}} == \
        {k: v for k, v in original["500001.jpeg"].items() if k not in {"cliente", "indicador_revision",
         "estado_documental", "estado_operacional", "motivos_revision_documento"}}
    assert filas["500002.jpeg"] == original["500002.jpeg"]
    [asiento] = [a for a in _ledger(e["raiz"]) if a.get("campo") == "cliente"]
    assert asiento["tipo"] == TIPO_LEDGER_CORRECCION and asiento["confirmado_por"] == "JAVIER"
    assert (asiento["valor_documental"], asiento["valor_corregido"]) == ("CLIENTE UNO SA", AZA)
    assert _sha(e["cat"] / "clientes.json") == antes["clientes"]  # ningún cliente nuevo


@pytest.mark.parametrize("texto", ["El cliente de la guía 500001 es CONSTRUCTORA INVENTADA SPA",
                                   "Corrige el cliente de la guía 500001 a ACEROS"])
def test_cliente_inexistente_o_parcial_no_se_inventa(con_aza, texto):
    e, b1 = con_aza, con_aza["b1"]
    antes = _huellas(e["raiz"])
    r = b1.atender("c", texto)
    assert r["estado"] == "ACLARACION_REQUERIDA", r
    assert "no crea clientes" in r["mensaje"] and "No se corrigió nada" in r["mensaje"]
    assert b1.pendiente("c") is None and _huellas(e["raiz"]) == antes


def test_cliente_contradice_rut_de_otro_cliente_se_rechaza(con_aza):
    e, b1 = con_aza, con_aza["b1"]
    filas = list(_filas(e["dataset"]).values())
    filas[0]["rut_cliente"] = "76.111.111-6"  # RUT de CLIENTE UNO SA
    origen._escribir_csv(e["dataset"], filas)
    antes = _huellas(e["raiz"])
    r = b1.atender("c", "El cliente de la guía 500001 es ACEROS AZA SA")
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "CONFLICTO", r
    assert "CLIENTE UNO SA" in r["mensaje"] and _huellas(e["raiz"]) == antes


def test_canal_rechaza_cliente_no_catalogado_o_no_canonico(con_aza):
    capa = CapaAccionesOperacionales(con_aza["raiz"])
    for valor, codigo in (("INVENTADA SPA", "ENTIDAD_NO_ENCONTRADA"), ("Aceros Aza S.A.", "PARAMETRO_INVALIDO")):
        r = capa.previsualizar("DOCUMENTO_CORREGIR_CAMPO", {"numero_guia": "500001", "campo": "cliente",
                                                            "valor": valor}, actor="JAVIER")
        assert r["estado"] == "RECHAZADA" and r["codigo"] == codigo, (valor, r)


# ------------------------------------------------------------ transporte

def test_transporte_con_ceros_iniciales_preview_confirmacion_y_ledger(con_aza):
    e, b1 = con_aza, con_aza["b1"]
    antes, original = _huellas(e["raiz"]), _filas(e["dataset"])
    r = b1.atender("t", "El transporte de la guía 500001 es 0000371852")
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert r["preview"]["valor_actual"] == {"numero_transporte": "0000900001"}
    assert r["preview"]["valor_propuesto"] == {"numero_transporte": "0000371852"}
    assert _huellas(e["raiz"]) == antes

    assert b1.atender("t", "sí")["estado"] == "EJECUTADA"
    filas = _filas(e["dataset"])
    assert filas["500001.jpeg"]["numero_transporte"] == "0000371852"
    assert filas["500002.jpeg"]["numero_transporte"] == original["500002.jpeg"]["numero_transporte"]
    [asiento] = [a for a in _ledger(e["raiz"]) if a.get("campo") == "numero_transporte"]
    assert (asiento["valor_documental"], asiento["valor_corregido"]) == ("0000900001", "0000371852")
    assert [a["confirmado_por"] for a in b1.capa.auditoria()] == ["JAVIER"]


@pytest.mark.parametrize("valor", ["371852", "00000371852", "0000371852X"])
def test_transporte_invalido_no_se_completa_ni_se_recorta(con_aza, valor):
    e, b1 = con_aza, con_aza["b1"]
    antes = _huellas(e["raiz"])
    r = b1.atender("t", f"El transporte de la guía 500001 es {valor}")
    assert r["estado"] == "ACLARACION_REQUERIDA", r
    assert "10 dígitos" in r["mensaje"] and b1.pendiente("t") is None and _huellas(e["raiz"]) == antes


def test_transporte_fijado_por_decision_humana_no_se_pisa(con_aza):
    e, b1 = con_aza, con_aza["b1"]
    (e["actual"] / "decisiones_aplicadas.json").write_text(json.dumps({"schema_version": 1, "aplicaciones": [{
        "decision_id": "x", "tipo": "TRANSPORTE_REVISADO", "accion": "CONFIRMAR", "campo": "numero_transporte",
        "documento": {"archivo": "500001.jpeg", "numero_guia": "500001"}}]}), encoding="utf-8")
    antes = _huellas(e["raiz"])
    r = b1.atender("t", "El transporte de la guía 500001 es 0000371852")
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "CAMPO_FIJADO_POR_DECISION_HUMANA", r
    assert _huellas(e["raiz"]) == antes


# ------------------------------------------------------------ planta de origen

@pytest.fixture
def con_origen(tmp_path):
    e = origen._entorno(tmp_path)
    for nombre, contenido in {"choferes.json": {}, "rutas.json": {"rutas": []}}.items():
        (e["catalogos"] / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    (e["actual"] / "decisiones_aplicadas.json").write_text(
        json.dumps({"schema_version": 1, "aplicaciones": []}), encoding="utf-8")
    e["decision"] = origen._decision_conflicto(e)
    e["b1"] = OperadorB1(e["raiz"], capa=CapaAccionesOperacionales(e["raiz"]))
    return e


def test_resolver_planta_por_nombre_o_comuna_unica_solo_confirmadas(con_origen):
    from atlas_core.catalogo_plantas import CatalogoPlantas
    plantas = CatalogoPlantas(con_origen["catalogos"] / "plantas.json").listar()
    assert resolver_planta(plantas, "Colina")["nombre"] == "AZA COLINA"
    assert resolver_planta(plantas, "aza renca")["nombre"] == "AZA RENCA"
    desconocida = resolver_planta(plantas, "Maipú")
    assert desconocida["estado"] == "DESCONOCIDO"
    assert {c["nombre"] for c in desconocida["candidatos"]} == {"AZA COLINA", "AZA RENCA"}


def test_planta_de_origen_por_revision_pendiente_con_preview_y_confirmacion(con_origen):
    e, b1 = con_origen, con_origen["b1"]
    antes = _huellas(e["raiz"])
    r = b1.atender("p", "La planta de origen de la guía 464900 es Colina")
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert r["preview"]["valor_actual"] == {"planta_origen": ""}
    assert r["preview"]["valor_propuesto"] == {"planta_origen": "AZA COLINA"}
    assert "Planta de origen propuesto: AZA COLINA" in r["mensaje"] and "¿Confirmas?" in r["mensaje"]
    assert "planta_id" not in json.dumps(r["preview"]) and _huellas(e["raiz"]) == antes

    hecha = b1.atender("p", "sí")
    assert hecha["estado"] == "EJECUTADA", hecha
    fila = _filas(e["dataset"])["464900.jpeg"]
    assert (fila["planta_origen_nombre"], fila["origen_determinado_por"]) == ("AZA COLINA", "CONFIRMACION_HUMANA")
    assert e["decision"]["decision_id"] in fila["evidencia_origen"]
    assert "AZA_COLINA" in fila["motivo_origen_gps"] and "AZA_RENCA" in fila["motivo_origen_gps"]  # evidencia intacta
    [registro] = b1.capa.auditoria()
    assert registro["accion"] == "DECISION_APLICAR" and registro["confirmado_por"] == "JAVIER"
    assert _sha(e["catalogos"] / "plantas.json") == antes["plantas"]
    assert b1.atender("p", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"


def test_planta_desde_la_tarjeta_de_origen(con_origen):
    e, b1 = con_origen, con_origen["b1"]
    r = b1.atender("rev", f"@revision:{e['decision']['decision_id']} la planta es AZA RENCA")
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert r["preview"]["valor_propuesto"] == {"planta_origen": "AZA RENCA"}
    assert b1.atender("rev", f"@revision:{e['decision']['decision_id']} sí")["estado"] == "EJECUTADA"
    assert _filas(e["dataset"])["464900.jpeg"]["planta_origen_nombre"] == "AZA RENCA"


def test_planta_inexistente_no_se_inventa(con_origen):
    e, b1 = con_origen, con_origen["b1"]
    antes = _huellas(e["raiz"])
    r = b1.atender("p", "La planta de origen de la guía 464900 es Maipú")
    assert r["estado"] == "ACLARACION_REQUERIDA", r
    assert "AZA COLINA" in r["mensaje"] and "No creo plantas" in r["mensaje"]
    assert b1.pendiente("p") is None and _huellas(e["raiz"]) == antes


def test_sin_revision_de_origen_pendiente_ofrece_correccion_sin_tocar_el_origen(con_origen):
    e, b1 = con_origen, con_origen["b1"]
    fila = origen._fila_csv(archivo="464901.jpeg", numero_guia="464901", numero_transporte="0000000901",
                            planta_origen_id=e["planta_colina"].planta_id, planta_origen_nombre="AZA COLINA",
                            origen_determinado_por="GPS", estado_ruta="RUTA_CALCULADA")
    filas = list(_filas(e["dataset"]).values()) + [fila]
    origen._escribir_csv(e["dataset"], filas)
    antes = _huellas(e["raiz"])
    r = b1.atender("p", "La planta de origen de la guía 464901 es Renca")
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert "AZA COLINA" in r["mensaje"] and "AZA RENCA" in r["mensaje"]
    assert _huellas(e["raiz"]) == antes and b1.capa.auditoria() == []
