"""Bandeja tras corregir el transporte: cada tarjeta depende de su condición.

Caso real 482580 (23/10): corregir `numero_transporte` retiraba la tarjeta
CLIENTE_AUSENTE -- la red de seguridad quitaba toda tarjeta del archivo con el
transporte anterior DESPUÉS de la reconciliación, que ya no la republicaba --
aunque el cliente seguía ausente. Caso 482661: VEHICULO_DESCONOCIDO (J56468)
sólo reaparecía con la acción siguiente.
"""
import csv
import json

import pytest

from test_acciones_operacionales import _bandeja, _fila, _sin_mantenimiento_real, _vehiculo, entorno  # noqa: F401
from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.decisiones_pendientes import detectar_decision_cliente_ausente, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    reconciliar_bandeja_decisiones,
    regenerar_decisiones_vehiculo_faltantes_sin_ocr,
)

T_NUEVO = "0000365023"


def _dataset(entorno, filas):
    with entorno["dataset"].open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _publicar(entorno, tarjetas):
    """Bandeja en su estado estable de producción: publicada y ya reconciliada."""
    generar_artefacto(ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["cat"], decisiones=tarjetas)
    reconciliar_bandeja_decisiones(raiz_atlas=entorno["raiz"])


def _tarjetas(entorno, archivo):
    return sorted(
        (d["tipo"], d["documento"]["numero_transporte"], d.get("campo"), d.get("valor_documental"))
        for d in _bandeja(entorno)["decisiones"] if d["documento"]["archivo"] == archivo
    )


def _corregir(capa, guia, campo, valor):
    p = capa.previsualizar("DOCUMENTO_CORREGIR_CAMPO", {"numero_guia": guia, "campo": campo, "valor": valor},
                           actor="JAVIER")
    assert p["estado"] == "PREVIEW", p
    r = capa.ejecutar(p["token"], actor="JAVIER", confirmado_por="JAVIER")
    assert r["estado"] == "APLICADA", r
    return r


@pytest.fixture
def caso_482580(entorno, monkeypatch):
    _sin_mantenimiento_real(monkeypatch)
    fila = _fila("482580", numero_transporte="No encontrado", cliente="No encontrado",
                 motivos_revision_documento="CLIENTE_AUSENTE", indicador_revision="REVISAR",
                 estado_documental="REQUIERE_REVISION", estado_operacional="REQUIERE_REVISION")
    _dataset(entorno, [fila, _fila("500002")])
    tarjeta = detectar_decision_cliente_ausente(archivo="482580.jpeg", fila=fila)
    _publicar(entorno, [tarjeta])
    return tarjeta


def test_482580_transporte_corregido_conserva_cliente_ausente_con_el_transporte_nuevo(entorno, caso_482580):
    capa = CapaAccionesOperacionales(entorno["raiz"])
    r = _corregir(capa, "482580", "numero_transporte", T_NUEVO)
    assert _tarjetas(entorno, "482580.jpeg") == [("CLIENTE_AUSENTE", T_NUEVO, "cliente", "")]
    assert caso_482580["decision_id"] in r["retiradas_por_red_de_seguridad"]  # la del transporte viejo


def test_482580_cliente_ausente_se_cierra_solo_al_resolver_el_cliente(entorno, caso_482580):
    capa = CapaAccionesOperacionales(entorno["raiz"])
    _corregir(capa, "482580", "numero_transporte", T_NUEVO)
    _corregir(capa, "482580", "peso_kg", "27974")  # campo ajeno: sin efecto en la tarjeta
    assert _tarjetas(entorno, "482580.jpeg") == [("CLIENTE_AUSENTE", T_NUEVO, "cliente", "")]
    _corregir(capa, "482580", "cliente", "CLIENTE UNO SA")
    assert _tarjetas(entorno, "482580.jpeg") == []


def test_482580_corregir_otro_campo_no_recrea_la_tarjeta(entorno, caso_482580):
    capa = CapaAccionesOperacionales(entorno["raiz"])
    antes = _bandeja(entorno)["decisiones"]
    r = _corregir(capa, "482580", "peso_kg", "27974")
    assert _bandeja(entorno)["decisiones"] == antes
    assert (r["decisiones_retiradas"], r["decisiones_nuevas"]) == ([], [])


@pytest.fixture
def caso_482661(entorno, monkeypatch):
    _sin_mantenimiento_real(monkeypatch)
    vehiculos = json.loads((entorno["cat"] / "vehiculos.json").read_text(encoding="utf-8"))
    vehiculos["vehiculos"].append(_vehiculo("JF6468", tipo="CARRO"))
    (entorno["cat"] / "vehiculos.json").write_text(json.dumps(vehiculos), encoding="utf-8")
    fila = _fila("482661", numero_transporte="0000363214", cliente="No encontrado", patente_rampla="J56468",
                 motivos_revision_documento="PATENTE_SIN_HOMOLOGAR | CLIENTE_AUSENTE", indicador_revision="REVISAR",
                 estado_documental="REQUIERE_REVISION", estado_operacional="REQUIERE_REVISION")
    _dataset(entorno, [fila, _fila("500002")])
    tarjetas = regenerar_decisiones_vehiculo_faltantes_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["cat"],
        decisiones_pendientes=[detectar_decision_cliente_ausente(archivo="482661.jpeg", fila=fila)],
    )
    _publicar(entorno, tarjetas)
    assert [t[0] for t in _tarjetas(entorno, "482661.jpeg")] == ["CLIENTE_AUSENTE", "VEHICULO_DESCONOCIDO"]


def test_482661_transporte_corregido_conserva_ambas_tarjetas_sin_duplicar(entorno, caso_482661):
    capa = CapaAccionesOperacionales(entorno["raiz"])
    _corregir(capa, "482661", "numero_transporte", "0000365214")
    assert _tarjetas(entorno, "482661.jpeg") == [
        ("CLIENTE_AUSENTE", "0000365214", "cliente", ""),
        ("VEHICULO_DESCONOCIDO", "0000365214", "patente_rampla", "J56468"),
    ]


def test_482661_cliente_resuelto_cierra_solo_cliente_ausente(entorno, caso_482661):
    capa = CapaAccionesOperacionales(entorno["raiz"])
    _corregir(capa, "482661", "numero_transporte", "0000365214")
    vehiculo = [d["decision_id"] for d in _bandeja(entorno)["decisiones"] if d["tipo"] == "VEHICULO_DESCONOCIDO"]
    _corregir(capa, "482661", "cliente", "CLIENTE UNO SA")
    assert _tarjetas(entorno, "482661.jpeg") == [("VEHICULO_DESCONOCIDO", "0000365214", "patente_rampla", "J56468")]
    # la tarjeta vigente no se recrea por corregir un campo ajeno
    assert [d["decision_id"] for d in _bandeja(entorno)["decisiones"] if d["tipo"] == "VEHICULO_DESCONOCIDO"] == vehiculo


def test_482661_corregir_la_patente_cierra_su_tarjeta(entorno, caso_482661):
    capa = CapaAccionesOperacionales(entorno["raiz"])
    _corregir(capa, "482661", "patente_rampla", "JF6468")
    assert [t[0] for t in _tarjetas(entorno, "482661.jpeg")] == ["CLIENTE_AUSENTE"]
