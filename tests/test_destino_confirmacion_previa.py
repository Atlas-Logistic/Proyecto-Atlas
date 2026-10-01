"""Destino de una guía desde una CONFIRMACIÓN HUMANA previa de otra guía del
mismo cliente/obra/destino documental. Nunca búsqueda externa, nunca número
inventado; aplica sólo por preview + confirmación (DECISION_APLICAR /
REGISTRAR_DIRECCION). Datos sintéticos; nunca G:."""
from __future__ import annotations

import csv
import hashlib
import json
from types import SimpleNamespace

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.aplicacion_decisiones import ErrorAplicacionDecision, aplicar_decision_obra
from atlas_core.b1_operador import ACCION_DESTINO_CONFIRMADO_PREVIO, OperadorB1, interpretar_determinista
from atlas_core.decisiones_pendientes import detectar_decision_destino_no_resuelto
from atlas_core.destino_confirmacion_previa import proponer_destino_por_confirmacion_humana
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion, ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado
from tests.test_destino_no_resuelto_r6 import _cliente_dict, _entorno, _fila_csv, _leer_csv, _obra_dict, _publicar

COMUNAS = ["LAS CONDES", "VITACURA", "LO BARNECHEA", "COLINA"]
DOC = "AV. CAM. EL ROBLE LAS CONDES LAS CO"
CALLE, COMUNA = "AV. CAM. EL ROBLE", "LAS CONDES"
OBRAS = [SimpleNamespace(obra_id="o1", nombre_canonico="CONSTRUCTORA ALFA LIMITADA",
                         aliases_documentales=("CONSTRUCTORA AL",)),
         SimpleNamespace(obra_id="o2", nombre_canonico="OTRA OBRA SPA", aliases_documentales=())]


def _fila(guia, archivo, *, cliente="CLIENTE UNO SA", rut="76.111.111-6", obra="CONSTRUCTORA AL", destino=DOC):
    return {"numero_guia": guia, "archivo": archivo, "cliente": cliente, "rut_cliente": rut,
            "obra_destino": obra, "despachar_a_crudo": destino}


def _aplicacion(guia, archivo, *, calle=CALLE, comuna=COMUNA, anterior=DOC, actor="JAVIER_DESKTOP",
                fecha="2026-09-28T22:00:00+00:00"):
    return {"decision_id": f"d-{guia}", "tipo": "DESTINO_NO_RESUELTO", "accion": "REGISTRAR_DIRECCION",
            "actor": actor, "fecha": fecha, "documento": {"numero_guia": guia, "archivo": archivo},
            "direccion_manual": calle, "comuna_manual": comuna, "valor_documental_anterior": anterior}


def _decision(guia="200", archivo="mobile/b/original.jpg", documental=DOC):
    return {"decision_id": "objetivo", "tipo": "DESTINO_NO_RESUELTO", "valor_documental": documental,
            "documento": {"numero_guia": guia, "archivo": archivo}}


def _proponer(filas, aplicaciones, decision=None):
    return proponer_destino_por_confirmacion_humana(decision=decision or _decision(), filas=filas,
                                                    aplicaciones=aplicaciones, obras=OBRAS, comunas=COMUNAS)


def _base(**objetivo):
    objetivo.setdefault("obra", "CONSTRUCTORA ALFA LIMITADA")
    return [_fila("100", "mobile/a/original.jpg", destino=CALLE), _fila("200", "mobile/b/original.jpg", **objetivo)]


# ------------------------------------------------------------ reglas


def test_misma_identidad_calle_y_comuna_con_confirmacion_humana_propone_sin_numero():
    r = _proponer(_base(), [_aplicacion("100", "mobile/a/original.jpg")])
    assert r["estado"] == "PROPUESTA", r
    assert (r["direccion"], r["comuna"], r["numero"]) == (CALLE, COMUNA, "")
    assert not any(c.isdigit() for c in r["direccion"])  # nunca inventa número
    assert r["evidencias"][0]["numero_guia"] == "100" and r["evidencias"][0]["actor"] == "JAVIER_DESKTOP"


def test_forma_documental_corta_vs_canonica_de_la_misma_obra_funciona():
    # objetivo con nombre canónico, previa con el alias documental corto (fixture _base)
    assert _proponer(_base(), [_aplicacion("100", "mobile/a/original.jpg")])["estado"] == "PROPUESTA"


@pytest.mark.parametrize("cambio, motivo", [
    ({"rut": "77.222.222-2"}, "CLIENTE_INCOMPATIBLE"),
    ({"obra": "OTRA OBRA SPA"}, "OBRA_INCOMPATIBLE"),
    ({"destino": "AV. LOS ALAMOS LAS CONDES"}, "CALLE_INCOMPATIBLE"),
    ({"destino": "AV. CAM. EL ROBLE VITACURA"}, "COMUNA_INCOMPATIBLE"),
])
def test_contexto_incompatible_se_abstiene(cambio, motivo):
    documental = cambio.get("destino", DOC)
    r = _proponer(_base(**cambio), [_aplicacion("100", "mobile/a/original.jpg")], _decision(documental=documental))
    assert r["estado"] == "ABSTENCION"
    assert {d["motivo"] for d in r["descartes"]} == {motivo}


def test_numero_nunca_se_hereda_ni_se_descarta():
    # la confirmación trae número y el documento objetivo no lo dice -> no se hereda
    con_numero = _aplicacion("100", "mobile/a/original.jpg", calle=f"{CALLE} 120")
    filas = [_fila("100", "mobile/a/original.jpg", destino=f"{CALLE} 120"), _base()[1]]
    r = _proponer(filas, [con_numero])
    assert r["estado"] == "ABSTENCION" and r["descartes"][0]["motivo"] == "NUMERO_NO_SUSTENTADO"
    # el documento objetivo trae un número que la confirmación no respalda
    r = _proponer(_base(destino="AV. CAM. EL ROBLE 55 LAS CONDES"), [_aplicacion("100", "mobile/a/original.jpg")],
                  _decision(documental="AV. CAM. EL ROBLE 55 LAS CONDES"))
    assert r["estado"] == "ABSTENCION" and r["descartes"][0]["motivo"] == "NUMERO_DOCUMENTAL_SIN_CONFIRMAR"
    # mismo número en confirmación y documento -> se propone ese número, literal
    filas = [_fila("100", "mobile/a/original.jpg", destino=f"{CALLE} 120"),
             _fila("200", "mobile/b/original.jpg", destino="AV. CAM. EL ROBLE 120 LAS CONDES")]
    r = _proponer(filas, [_aplicacion("100", "mobile/a/original.jpg", calle=f"{CALLE} 120",
                                      anterior="AV. CAM. EL ROBLE 120 LAS CONDES")],
                  _decision(documental="AV. CAM. EL ROBLE 120 LAS CONDES"))
    assert r["estado"] == "PROPUESTA" and r["numero"] == "120"


def test_dos_confirmaciones_humanas_incompatibles_se_abstiene():
    filas = _base() + [_fila("300", "mobile/c/original.jpg", destino="AV. CAM. EL")]
    r = _proponer(filas, [_aplicacion("100", "mobile/a/original.jpg"),
                          _aplicacion("300", "mobile/c/original.jpg", calle="AV. CAM. EL")])
    assert r["estado"] == "ABSTENCION" and r["motivo"] == "CONFIRMACIONES_INCOMPATIBLES"


def test_evidencia_no_humana_no_basta():
    r = _proponer(_base(), [_aplicacion("100", "mobile/a/original.jpg", actor="ATLAS_EVIDENCIA_EXTERNA_R19")])
    assert r["estado"] == "ABSTENCION" and r["descartes"][0]["motivo"] == "NO_ES_DECISION_HUMANA"


def test_confirmacion_no_vigente_no_basta():
    filas = _base()
    filas[0]["despachar_a_crudo"] = "OTRA CALLE 9"  # la guía previa ya no usa esa dirección
    r = _proponer(filas, [_aplicacion("100", "mobile/a/original.jpg")])
    assert r["estado"] == "ABSTENCION" and r["descartes"][0]["motivo"] == "CONFIRMACION_NO_VIGENTE"


def test_otro_destino_confirmado_de_la_misma_obra_no_invalida_este():
    filas = _base() + [_fila("400", "mobile/d/original.jpg", destino="SAN ANDRES 0100")]
    otra = _aplicacion("400", "mobile/d/original.jpg", calle="SAN ANDRES 0100", comuna="VITACURA",
                       anterior="SAN ANDRES 0100 VITACURA VITACURA")
    r = _proponer(filas, [otra, _aplicacion("100", "mobile/a/original.jpg")])
    assert r["estado"] == "PROPUESTA" and r["direccion"] == CALLE
    assert {"numero_guia": "400", "motivo": "CALLE_INCOMPATIBLE"} in r["descartes"]


def test_identidad_objetivo_ambigua_se_abstiene():
    filas = _base() + [_fila("200", "mobile/b/original.jpg")]
    assert _proponer(filas, [_aplicacion("100", "mobile/a/original.jpg")])["motivo"] == "IDENTIDAD_OBJETIVO_INSUFICIENTE"


# ------------------------------------------------------------ B1 + mecanismo controlado

GUIA, PREVIA = "472037", "472099"
ARCHIVO, ARCHIVO_PREVIO = "mobile/aaaa-objetivo/original.jpg", "mobile/bbbb-previa/original.jpg"
ORDEN = f"Resuelve el destino de la guía {GUIA} con el destino ya confirmado"


def _proveedor():
    candidato = CandidatoGeocodificacion(Coordenadas(-70.55, -33.40), "Av. Camino El Roble, Las Condes, RM, Chile",
                                         0.9, "Las Condes", "Metropolitana",
                                         codigo_pais="CL", codigo_unidad="13114", codigo_contexto="13")
    geo = ResultadoGeocodificacion(EstadoRuta.REQUIERE_REVISION, (candidato,), "")
    return ProveedorRutasSimulado(geocodificaciones={f"{CALLE} Las Condes, Chile": geo, f"{CALLE}, Chile": geo},
                                  resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 20.0, 30.0, "SINTETICO"))


@pytest.fixture
def b1(tmp_path):
    objetivo = _fila_csv(archivo=ARCHIVO, despachar_a_crudo=DOC)
    previa = _fila_csv(archivo=ARCHIVO_PREVIO, numero_guia=PREVIA, numero_transporte="0000354099",
                       despachar_a_crudo=CALLE, estado_ruta="RUTA_CALCULADA", motivo_ruta="",
                       indicador_revision="OK", estado_documental="OK", estado_operacional="OK")
    entorno = _entorno(tmp_path, filas_csv=[previa, objetivo], clientes=[_cliente_dict()], obras=[_obra_dict()])
    decision = detectar_decision_destino_no_resuelto(archivo=ARCHIVO, fila=objetivo)
    assert decision is not None and decision["documento"]["archivo"] == ARCHIVO
    _publicar(entorno, decision)
    (entorno["actual"] / "decisiones_aplicadas.json").write_text(json.dumps({"schema_version": 1, "aplicaciones": [
        _aplicacion(PREVIA, ARCHIVO_PREVIO)]}), encoding="utf-8")
    operador = OperadorB1(entorno["raiz"], capa=CapaAccionesOperacionales(entorno["raiz"], proveedor_rutas=_proveedor()))
    operador.entorno, operador.decision = entorno, decision
    return operador


def _sha(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def test_intencion():
    assert interpretar_determinista(ORDEN).accion == ACCION_DESTINO_CONFIRMADO_PREVIO
    assert interpretar_determinista(f"El destino de la guía {GUIA} es {CALLE}").accion == "DECISION_APLICAR"
    assert interpretar_determinista(f"¿Cuál es el destino de la guía {GUIA}?") is None


def test_preview_limpio_no_escribe(b1):
    actual = b1.entorno["actual"]
    antes = {n: _sha(actual / n) for n in ("analisis_completo_guias.csv", "decisiones_aplicadas.json",
                                           "decisiones_pendientes.json")}
    r = b1.atender("c", ORDEN)
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert r["mensaje"].startswith(f"Guía: {GUIA}\nDestino actual: {DOC}\nDestino propuesto: {CALLE}, {COMUNA}\n")
    assert f"para la guía {PREVIA}" in r["mensaje"] and "Sin número de calle" in r["mensaje"]
    visible = json.dumps({"m": r["mensaje"], "p": r["preview"]}, ensure_ascii=False)
    for ruido in ("decision_id", "token", "DECISION_APLICAR", "REGISTRAR_DIRECCION", "JAVIER_DESKTOP",
                  ARCHIVO, ARCHIVO_PREVIO, b1.decision["decision_id"]):
        assert ruido not in visible, ruido
    assert {n: _sha(actual / n) for n in antes} == antes


def test_confirmacion_modifica_solo_la_guia_objetivo_y_audita_procedencia(b1):
    dataset = b1.entorno["dataset"]
    previa_antes = next(f for f in _leer_csv(dataset) if f["archivo"] == ARCHIVO_PREVIO)
    b1.atender("c", ORDEN)
    e = b1.atender("c", "sí")
    assert e["estado"] == "EJECUTADA", e
    filas = {f["archivo"]: f for f in _leer_csv(dataset)}
    assert filas[ARCHIVO]["despachar_a_crudo"] == CALLE  # sin número
    assert filas[ARCHIVO_PREVIO] == previa_antes  # la guía de la evidencia no se toca
    ledger = json.loads((b1.entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    nueva = ledger["aplicaciones"][-1]
    assert nueva["documento"]["archivo"] == ARCHIVO and nueva["valor_documental_anterior"] == DOC
    assert (nueva["direccion_manual"], nueva["comuna_manual"]) == (CALLE, COMUNA)
    auditoria = json.dumps(json.loads((b1.entorno["actual"] / "acciones_operacionales.json").read_text(encoding="utf-8")),
                           ensure_ascii=False)
    assert "DESTINO_DESDE_CONFIRMACION_HUMANA_PREVIA" in auditoria
    assert f"guia {PREVIA}" in auditoria and "JAVIER_DESKTOP" in auditoria and ARCHIVO_PREVIO in auditoria


def test_sin_confirmacion_compatible_rechaza_sin_escribir(b1):
    (b1.entorno["actual"] / "decisiones_aplicadas.json").write_text(json.dumps({"schema_version": 1, "aplicaciones": [
        _aplicacion(PREVIA, ARCHIVO_PREVIO, actor="ATLAS_AUTOMATICO")]}), encoding="utf-8")
    sha = _sha(b1.entorno["dataset"])
    r = b1.atender("c", ORDEN)
    assert r["estado"] == "RECHAZADA" and "no encontré un destino confirmado" in r["mensaje"]
    assert b1.pendiente("c") is None and _sha(b1.entorno["dataset"]) == sha


# ------------------------------------------------------------ identidad de fila al registrar dirección


def test_registrar_direccion_usa_la_fila_del_documento_no_la_primera_de_la_guia(tmp_path):
    """Dos filas con la misma guía (dos documentos): se modifica sólo la del
    archivo de la decisión; sin archivo y con varias filas se abstiene."""
    otra = _fila_csv(archivo="mobile/cccc-otra/original.jpg", despachar_a_crudo="OTRA 1")
    objetivo = _fila_csv(archivo=ARCHIVO, despachar_a_crudo=DOC)
    entorno = _entorno(tmp_path, filas_csv=[otra, objetivo], clientes=[_cliente_dict()], obras=[_obra_dict()])
    decision = detectar_decision_destino_no_resuelto(archivo=ARCHIVO, fila=objetivo)
    _publicar(entorno, decision)
    aplicar_decision_obra(raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
                          accion="REGISTRAR_DIRECCION", direccion_manual=CALLE, comuna_manual=COMUNA,
                          proveedor_rutas=_proveedor(), proveedor_rutas_fallback=_proveedor())
    filas = {f["archivo"]: f for f in _leer_csv(entorno["dataset"])}
    assert filas[ARCHIVO]["despachar_a_crudo"] == CALLE
    assert filas["mobile/cccc-otra/original.jpg"]["despachar_a_crudo"] == "OTRA 1"


def test_registrar_direccion_ambiguo_no_escribe(tmp_path):
    otra = _fila_csv(archivo="mobile/cccc-otra/original.jpg", despachar_a_crudo="OTRA 1")
    objetivo = _fila_csv(archivo=ARCHIVO, despachar_a_crudo=DOC)
    entorno = _entorno(tmp_path, filas_csv=[otra, objetivo], clientes=[_cliente_dict()], obras=[_obra_dict()])
    decision = detectar_decision_destino_no_resuelto(archivo=ARCHIVO, fila=objetivo)
    decision["documento"]["archivo"] = ""  # identidad insuficiente: sólo la guía
    _publicar(entorno, decision)
    sha = _sha(entorno["dataset"])
    with pytest.raises(ErrorAplicacionDecision):
        aplicar_decision_obra(raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
                              accion="REGISTRAR_DIRECCION", direccion_manual=CALLE, comuna_manual=COMUNA,
                              proveedor_rutas=_proveedor(), proveedor_rutas_fallback=_proveedor())
    assert _sha(entorno["dataset"]) == sha
