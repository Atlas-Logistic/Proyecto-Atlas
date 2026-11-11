"""P0 — B1 nunca guarda un tracto como rampla ni una rampla como tracto.

Caso real 484396 (transporte 0000369573, SALOMÓN PIZARRO): desde la tarjeta de
rampla, «la patente es TG8925» se aplicó como rampla aunque TG8925 es el tracto
confirmado y asignado a ese chofer. El canal oficial (DOCUMENTO_CORREGIR_CAMPO)
rechaza ahora una patente que el catálogo confirma inequívocamente como el otro
tipo, explica el campo que corresponde y no mueve nada. Sólo fixtures
sintéticas: nunca G: ni datos productivos.
"""
from __future__ import annotations

import csv
import hashlib
import json
from types import SimpleNamespace

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales, TIPO_LEDGER_CORRECCION
from atlas_core.b1_operador import OperadorB1
from atlas_core.decisiones_pendientes import crear_decision, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS
from tests.test_acciones_operacionales import RUT_ACTIVO, _fila, _vehiculo, entorno  # noqa: F401 -- fixture compartida

GUIA = "500001"          # fila del fixture compartido: tracto KN5439 (TRACTO confirmado)
TRACTO = "KN5439"
CARRO = "JF9575"


def _sha(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _catalogo(entorno, *vehiculos):
    (entorno["cat"] / "vehiculos.json").write_text(
        json.dumps({"version": 1, "vehiculos": list(vehiculos)}), encoding="utf-8")


def _asignado(vehiculo, rut):
    vehiculo["evidencias"].append({
        "tipo": "CONFIRMACION_HUMANA", "identificador_fuente": "ASIGNACION_TEST", "referencia_hash": "",
        "campos_observados": {"patente": vehiculo["patente_canonica"], "tipo": vehiculo["tipo"],
                              "observacion": "", "rut_chofer_asociado": rut},
        "fecha": "2026-02-01T00:00:00+00:00", "actor_proceso": "TEST", "resultado": "SOPORTA"})
    return vehiculo


def _filas(entorno):
    with entorno["dataset"].open(encoding="utf-8-sig", newline="") as archivo:
        return {f["numero_guia"]: f for f in csv.DictReader(archivo, delimiter=";")}


def _escribir(entorno, filas):
    with entorno["dataset"].open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _preview(entorno, campo, valor, guia=GUIA):
    capa = CapaAccionesOperacionales(entorno["raiz"])
    return capa.previsualizar("DOCUMENTO_CORREGIR_CAMPO", {"numero_guia": guia, "campo": campo, "valor": valor},
                              actor="B1", origen="B1")


@pytest.fixture
def con_carro(entorno):
    _catalogo(entorno, _asignado(_vehiculo(TRACTO), RUT_ACTIVO), _asignado(_vehiculo(CARRO, "CARRO"), RUT_ACTIVO))
    return entorno


# ------------------------------------------------------------ ambos sentidos

def test_tracto_confirmado_no_se_guarda_como_rampla(con_carro):
    antes = _sha(con_carro["dataset"])
    r = _preview(con_carro, "patente_rampla", TRACTO)
    assert r["estado"] == "RECHAZADA", r
    assert r["codigo"] == "PATENTE_DE_OTRO_TIPO"
    assert f"{TRACTO} está confirmada como tracto" in r["mensaje"]
    assert "corresponde al campo tracto, no a rampla" in r["mensaje"]
    assert "LUIS REYES" in r["mensaje"]          # asignación vigente informada
    assert "No se corrigió nada" in r["mensaje"]
    assert _sha(con_carro["dataset"]) == antes


def test_rampla_confirmada_no_se_guarda_como_tracto(con_carro):
    antes = _sha(con_carro["dataset"])
    r = _preview(con_carro, "patente_tracto", CARRO)
    assert r["estado"] == "RECHAZADA", r
    assert r["codigo"] == "PATENTE_DE_OTRO_TIPO"
    assert f"{CARRO} está confirmada como rampla" in r["mensaje"]
    assert "corresponde al campo rampla, no a tracto" in r["mensaje"]
    assert _sha(con_carro["dataset"]) == antes


def test_minusculas_y_espacios_no_esquivan_la_validacion(con_carro):
    r = _preview(con_carro, "PATENTE_RAMPLA", " kn5439 ")
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "PATENTE_DE_OTRO_TIPO", r


def test_repetir_una_patente_ya_mal_ubicada_explica_el_tipo_en_vez_de_sin_cambios(con_carro):
    """484396: la rampla ya quedó con el tracto; repetir la orden decía «Sin
    cambios». Ahora explica qué campo corresponde y tampoco escribe."""
    filas = list(_filas(con_carro).values())
    for fila in filas:
        if fila["numero_guia"] == GUIA:
            fila["patente_rampla"] = TRACTO
    _escribir(con_carro, filas)
    antes = _sha(con_carro["dataset"])
    r = _preview(con_carro, "patente_rampla", TRACTO)
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "PATENTE_DE_OTRO_TIPO", r
    assert _sha(con_carro["dataset"]) == antes
    assert _filas(con_carro)[GUIA]["patente_rampla"] == TRACTO   # nada se corrige solo


# ------------------------------------------------------------ correcciones legítimas y auditoría

def test_rampla_confirmada_en_su_campo_se_aplica_con_auditoria(con_carro):
    capa = CapaAccionesOperacionales(con_carro["raiz"])
    p = capa.previsualizar("DOCUMENTO_CORREGIR_CAMPO",
                           {"numero_guia": GUIA, "campo": "patente_rampla", "valor": CARRO}, actor="B1", origen="B1")
    assert p["estado"] == "PREVIEW", p
    r = capa.ejecutar(p["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    assert r["estado"] == "APLICADA", r
    assert _filas(con_carro)[GUIA]["patente_rampla"] == CARRO
    ledger = json.loads((con_carro["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    correccion = [a for a in ledger["aplicaciones"]
                  if a.get("tipo") == TIPO_LEDGER_CORRECCION and a.get("campo") == "patente_rampla"]
    assert len(correccion) == 1
    assert correccion[0]["valor_corregido"] == CARRO and correccion[0]["confirmado_por"] == "JAVIER"


def test_otro_tracto_confirmado_en_el_campo_tracto_se_previsualiza(entorno):
    _catalogo(entorno, _vehiculo(TRACTO), _vehiculo("TG8925"))
    assert _preview(entorno, "patente_tracto", "TG8925")["estado"] == "PREVIEW"


def test_patente_desconocida_no_se_bloquea(con_carro):
    assert _preview(con_carro, "patente_rampla", "JC4173")["estado"] == "PREVIEW"
    assert _preview(con_carro, "patente_tracto", "ZZ9999")["estado"] == "PREVIEW"


def test_patente_no_confirmada_del_otro_tipo_no_es_inequivoca(entorno):
    candidato = _vehiculo("PP1234")
    candidato["estado_calidad"] = "CANDIDATO"
    _catalogo(entorno, _vehiculo(TRACTO), candidato)
    assert _preview(entorno, "patente_rampla", "PP1234")["estado"] == "PREVIEW"


def test_patente_inactiva_no_es_inequivoca(entorno):
    inactivo = _vehiculo("PP1234")
    inactivo["estado_vigencia"] = "INACTIVO"
    _catalogo(entorno, _vehiculo(TRACTO), inactivo)
    assert _preview(entorno, "patente_rampla", "PP1234")["estado"] == "PREVIEW"


def test_camion_rigido_queda_fuera_de_alcance(entorno):
    _catalogo(entorno, _vehiculo(TRACTO), _vehiculo("RR1234", "CAMION_RIGIDO"))
    assert _preview(entorno, "patente_rampla", "RR1234")["estado"] == "PREVIEW"


def test_alias_confirmado_del_otro_tipo_tambien_se_bloquea(entorno):
    carro = _vehiculo(CARRO, "CARRO")
    carro["aliases"] = ["JF9557"]
    carro["evidencias"].append({
        "tipo": "CONFIRMACION_HUMANA", "identificador_fuente": "ALIAS_TEST", "referencia_hash": "",
        "campos_observados": {"patente": CARRO, "tipo": "CARRO", "alias": "JF9557", "observacion": ""},
        "fecha": "2026-01-02T00:00:00+00:00", "actor_proceso": "TEST", "resultado": "SOPORTA"})
    _catalogo(entorno, _vehiculo(TRACTO), carro)
    r = _preview(entorno, "patente_tracto", "JF9557")
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "PATENTE_DE_OTRO_TIPO", r


def test_otros_campos_no_consultan_el_tipo_de_vehiculo(con_carro):
    assert _preview(con_carro, "obra_destino", TRACTO)["estado"] == "PREVIEW"


# ------------------------------------------------------------ ambigüedad

def test_patente_confirmada_con_ambos_tipos_pide_revision(con_carro, monkeypatch):
    """El catálogo válido no lo permite (unicidad de patentes/aliases); si
    datos inconsistentes lo produjeran, no se elige: se pide revisión."""
    import atlas_core.catalogo_vehiculos as cv
    from atlas_core.catalogo_vehiculos import cargar_catalogo_vehiculos as original

    def doble(fuente):
        cargado = original(fuente)
        vehiculos = list(cargado.vehiculos)
        base = next(v for v in vehiculos if v.patente_canonica == CARRO)
        vehiculos.append(SimpleNamespace(**{**base.__dict__, "vehiculo_id": "otro", "patente_canonica": "OTRA00",
                                            "tipo": "TRACTO", "aliases": (CARRO,)}))
        return SimpleNamespace(vehiculos=tuple(vehiculos))

    monkeypatch.setattr(cv, "cargar_catalogo_vehiculos", doble)
    antes = _sha(con_carro["dataset"])
    r = _preview(con_carro, "patente_rampla", CARRO)
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "TIPO_VEHICULO_AMBIGUO", r
    assert "Requiere revisión" in r["mensaje"]
    assert _sha(con_carro["dataset"]) == antes


def test_catalogo_ilegible_conserva_el_comportamiento_anterior(entorno):
    (entorno["cat"] / "vehiculos.json").write_text("{no es json", encoding="utf-8")
    assert _preview(entorno, "patente_rampla", TRACTO)["estado"] == "PREVIEW"


# ------------------------------------------------------------ B1 desde la tarjeta de rampla (484396)

def test_b1_desde_tarjeta_de_rampla_no_aplica_el_tracto(con_carro):
    tarjeta = crear_decision(
        tipo="VEHICULO_DESCONOCIDO", entidad="VEHICULO", archivo=f"{GUIA}.jpeg", numero_guia=GUIA,
        numero_transporte="0000900001", campo="patente_rampla", valor_documental="JF5595",
        valor_normalizado="JF5595", identidad_resuelta=None, candidatos=(), motivos=("PRUEBA",),
        evidencias=(), acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"))
    generar_artefacto(ruta_dataset=con_carro["dataset"], carpeta_catalogos=con_carro["cat"],
                      decisiones=[con_carro["decision"], tarjeta])
    antes = _sha(con_carro["dataset"])
    b1 = OperadorB1(con_carro["raiz"], usuario="JAVIER_DESKTOP")
    respuesta = b1.atender(f"revision-{tarjeta['decision_id']}",
                           f"@revision:{tarjeta['decision_id']} la patente es {TRACTO}")
    assert respuesta["estado"] != "PREVIEW_PENDIENTE", respuesta
    assert "corresponde al campo tracto" in respuesta.get("mensaje", ""), respuesta
    assert _sha(con_carro["dataset"]) == antes
    pendientes = {d["decision_id"] for d in json.loads(
        (con_carro["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]}
    assert tarjeta["decision_id"] in pendientes   # la tarjeta sigue abierta para el humano
