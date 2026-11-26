"""Asociación manual de un envío Mobile desde Desktop (casos reales 492295 y
492263, 26/11/2026): la guía debe quedar DENTRO del viaje elegido, no sólo el
envío marcado como asociado. Copias sintéticas en tmp_path; nunca G:."""
from __future__ import annotations

import csv
import json

import pytest

import resolver_envio_mobile as resolver_mod
from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from tests.test_acciones_operacionales import COLUMNAS, _EscritorDisponible, _fila, entorno  # noqa: F401

ENVIO = "49bfa2fd-4013-4da2-b1fa-2e1621b970bc"
ARCHIVO = f"mobile/{ENVIO}/original.jpg"


def _filas(e):
    with e["dataset"].open(encoding="utf-8-sig", newline="") as archivo:
        return {f["archivo"]: f for f in csv.DictReader(archivo, delimiter=";")}


def _escribir(e, filas):
    with e["dataset"].open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _envio(e, envio_id=ENVIO, **extra):
    carpeta = e["raiz"] / "operacion" / "mobile" / "envios" / envio_id
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "original.jpg").write_bytes(b"foto-original")
    registro = {"schema_version": 1, "envio_id": envio_id, "estado": "REQUIERE_REVISION",
                "foto_original": "original.jpg", "imagen_mime": "image/jpeg", "observacion": "Carga en versalles",
                "datos_ocr": {"numero_guia": "500003"}, "resultado_asociacion": {"candidatos": []}, **extra}
    (carpeta / "envio.json").write_text(json.dumps(registro), encoding="utf-8")
    return carpeta


def _capa(e):
    return CapaAccionesOperacionales(e["raiz"], fabrica_escritor=lambda: _EscritorDisponible())


@pytest.fixture
def con_envio(entorno):  # noqa: F811
    filas = list(_filas(entorno).values())
    filas.append(_fila("500003", archivo=ARCHIVO, numero_transporte="No encontrado"))
    _escribir(entorno, filas)
    entorno["carpeta"] = _envio(entorno)
    return entorno


def test_asociacion_manual_incorpora_la_guia_al_viaje_por_el_canal_oficial(con_envio):
    e = con_envio
    capa = _capa(e)
    r = resolver_mod.resolver(e["raiz"], ENVIO, "0000900001", capa=capa)
    assert r["ok"] and r["documento_incorporado"] and r["correccion_documental"]["antes"] == "No encontrado"
    filas = _filas(e)
    assert filas[ARCHIVO]["numero_transporte"] == "0000900001"
    assert {f["numero_transporte"] for f in filas.values()} == {"0000900001"}  # ningún viaje nuevo
    registro = json.loads((e["carpeta"] / "envio.json").read_text(encoding="utf-8"))
    assert registro["estado"] == "ASOCIADO" and registro["observacion"] == "Carga en versalles"
    assert registro["resultado_asociacion"]["estado"] == "ASOCIADO_MANUALMENTE"
    assert (e["carpeta"] / "original.jpg").read_bytes() == b"foto-original"
    [auditoria] = capa.auditoria()
    assert auditoria["accion"] == "DOCUMENTO_CORREGIR_CAMPO" and auditoria["confirmado_por"] == "JAVIER_DESKTOP"
    ledger = json.loads((e["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))["aplicaciones"]
    [asiento] = [a for a in ledger if a.get("campo") == "numero_transporte"]
    assert asiento["valor_corregido"] == "0000900001" and asiento["documento"]["archivo"] == ARCHIVO


def test_guia_de_otro_viaje_no_se_mueve_y_el_envio_sigue_pendiente(con_envio):
    e = con_envio
    filas = list(_filas(e).values())
    for f in filas:
        if f["archivo"] == ARCHIVO:
            f["numero_transporte"] = "0000900002"
    filas.append(_fila("500004", numero_transporte="0000900001"))
    _escribir(e, filas)
    antes = e["dataset"].read_bytes()
    with pytest.raises(ValueError, match="ya pertenece al transporte 0000900002"):
        resolver_mod.resolver(e["raiz"], ENVIO, "0000900001", capa=_capa(e))
    assert e["dataset"].read_bytes() == antes
    assert json.loads((e["carpeta"] / "envio.json").read_text(encoding="utf-8"))["estado"] == "REQUIERE_REVISION"


def test_correccion_rechazada_deja_el_envio_pendiente(con_envio, monkeypatch):
    e = con_envio

    class CapaRechaza:
        def previsualizar(self, *a, **k):
            return {"estado": "RECHAZADA", "mensaje": "campo fijado por decisión humana"}

    with pytest.raises(ValueError, match="fijado por decisión humana"):
        resolver_mod.resolver(e["raiz"], ENVIO, "0000900001", capa=CapaRechaza())
    assert _filas(e)[ARCHIVO]["numero_transporte"] == "No encontrado"
    assert json.loads((e["carpeta"] / "envio.json").read_text(encoding="utf-8"))["estado"] == "REQUIERE_REVISION"


def test_envio_sin_documento_conserva_la_asociacion_de_observacion(entorno):  # noqa: F811
    carpeta = _envio(entorno, "2d8e88d3-e4d6-4109-9008-496e126751e6")
    antes = entorno["dataset"].read_bytes()

    class SinCapa:
        def previsualizar(self, *a, **k):
            raise AssertionError("sin documento no se corrige nada")

    r = resolver_mod.resolver(entorno["raiz"], "2d8e88d3-e4d6-4109-9008-496e126751e6", "0000900001", capa=SinCapa())
    assert r["ok"] and not r["documento_incorporado"]
    assert entorno["dataset"].read_bytes() == antes
    assert json.loads((carpeta / "envio.json").read_text(encoding="utf-8"))["estado"] == "ASOCIADO"


def test_transporte_inexistente_se_rechaza_sin_tocar_nada(con_envio):
    e = con_envio
    antes = e["dataset"].read_bytes()
    with pytest.raises(ValueError, match="no existe"):
        resolver_mod.resolver(e["raiz"], ENVIO, "0000999999", capa=_capa(e))
    assert e["dataset"].read_bytes() == antes
