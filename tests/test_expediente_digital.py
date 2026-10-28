"""Expediente digital etapa 1 -- sólo fixtures sintéticas."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timezone

import pytest

from atlas_core.expediente_digital import (
    ErrorExpedienteDigital, documentos_por_atender, estado_expediente, leer_expediente, registrar_documento,
    ruta_almacen_expediente,
)
from tests.test_acciones_operacionales import entorno  # noqa: F401 -- fixture compartida

HOY = date(2026, 10, 28)
RELOJ = lambda: datetime(2026, 10, 28, 12, tzinfo=timezone.utc)  # noqa: E731


def _reg(e, **extra):
    datos = {"empresa": "MBT", "entidad": "VEHICULO", "referencia": "KN5439", "tipo": "SOAP",
             "fecha_vencimiento": "2027-03-31", "actor": "TEST", "reloj": RELOJ, **extra}
    return registrar_documento(e["raiz"], **datos)


def _sha(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def test_lectura_sin_almacen_no_crea_nada(entorno):
    assert leer_expediente(entorno["raiz"], empresa="MBT")["documentos"] == []
    assert not ruta_almacen_expediente(entorno["raiz"], "MBT").exists()


def test_registra_referencias_de_catalogo_sin_duplicar_identidades(entorno):
    catalogos = {p.name: _sha(p) for p in entorno["cat"].iterdir()}
    vehiculo = _reg(entorno, archivo="archivos/vehiculos/kn5439_soap.pdf")
    chofer = _reg(entorno, entidad="CHOFER", referencia="12.345.678-5", tipo="LICENCIA_CONDUCIR",
                  fecha_vencimiento="2026-11-10")
    assert vehiculo["referencia_catalogo"] == "KN5439" and chofer["referencia_catalogo"] == "123456785"
    datos = leer_expediente(entorno["raiz"], empresa="MBT")
    assert datos["empresa"] == "MBT" and datos["revision"] == 2 and len(datos["documentos"]) == 2
    assert not {"nombre", "rut", "patente_canonica"} & set(datos["documentos"][0])
    assert {p.name: _sha(p) for p in entorno["cat"].iterdir()} == catalogos  # catálogos intactos


@pytest.mark.parametrize("extra, mensaje", [
    ({"referencia": "ZZ9999"}, "vehículo no existe"),
    ({"entidad": "CHOFER", "referencia": "99999999-9", "tipo": "LICENCIA_CONDUCIR"}, "chofer no existe"),
    ({"tipo": "LICENCIA_CONDUCIR"}, "no admitido"),
    ({"entidad": "CHOFER", "referencia": "123456785", "tipo": "SOAP"}, "no admitido"),
    ({"fecha_vencimiento": "31-03-2027"}, "AAAA-MM-DD"),
    ({"fecha_vencimiento": "2027-02-30"}, "AAAA-MM-DD"),
    ({"archivo": "C:/otro/soap.pdf"}, "archivos/"),
    ({"archivo": "archivos/../../catalogos_privados/choferes.json"}, "archivos/"),
    ({"empresa": "../OTRA"}, "Empresa"),
    ({"actor": ""}, "actor"),
])
def test_rechaza_datos_invalidos_sin_escribir(entorno, extra, mensaje):
    with pytest.raises(ErrorExpedienteDigital, match=mensaje):
        _reg(entorno, **extra)
    assert not ruta_almacen_expediente(entorno["raiz"], "MBT").exists()


def test_reemplazo_conserva_historial(entorno):
    primero = _reg(entorno, fecha_vencimiento="2026-10-01")
    segundo = _reg(entorno, fecha_vencimiento="2027-10-01")
    documentos = {d["documento_id"]: d for d in leer_expediente(entorno["raiz"], empresa="MBT")["documentos"]}
    assert documentos[primero["documento_id"]]["reemplazado_por"] == segundo["documento_id"]
    vista = estado_expediente(entorno["raiz"], empresa="MBT", hoy=HOY)
    assert [d["documento_id"] for d in vista] == [segundo["documento_id"]]


def test_estado_de_vencimiento_es_derivado(entorno):
    _reg(entorno, tipo="SOAP", fecha_vencimiento="2026-10-27")
    _reg(entorno, tipo="REVISION_TECNICA", fecha_vencimiento="2026-11-27")
    _reg(entorno, tipo="PERMISO_CIRCULACION", fecha_vencimiento="2026-11-28")
    antes = _sha(ruta_almacen_expediente(entorno["raiz"], "MBT"))
    vista = {d["tipo"]: d for d in estado_expediente(entorno["raiz"], empresa="MBT", hoy=HOY)}
    assert (vista["SOAP"]["estado_vencimiento"], vista["SOAP"]["dias_para_vencer"]) == ("VENCIDO", -1)
    assert (vista["REVISION_TECNICA"]["estado_vencimiento"], vista["REVISION_TECNICA"]["dias_para_vencer"]) == (
        "POR_VENCER", 30)
    assert vista["PERMISO_CIRCULACION"]["estado_vencimiento"] == "VIGENTE"
    assert [d["tipo"] for d in documentos_por_atender(entorno["raiz"], empresa="MBT", hoy=HOY)] == [
        "SOAP", "REVISION_TECNICA"]
    assert _sha(ruta_almacen_expediente(entorno["raiz"], "MBT")) == antes  # la vista no escribe
    assert "estado_vencimiento" not in json.dumps(leer_expediente(entorno["raiz"], empresa="MBT"))


def test_incluye_licencias_de_fichas_sin_modificarlas(entorno):
    fichas = entorno["raiz"] / "fichas_digitales" / "MBT" / "fichas_documentales.json"
    fichas.parent.mkdir(parents=True)
    fichas.write_text(json.dumps({"version": 2, "empresa": "MBT", "revision": 1, "choferes": [{
        "ficha_id": str(uuid.uuid4()), "referencias_catalogo": ["123456785"], "complementarios": {},
        "historial": [], "documentos": [{"documento_id": "lic-1", "tipo": "LICENCIA_CONDUCIR",
                                         "vencimiento": "2026-11-05", "archivo": "archivos/choferes/x/lic-1.pdf"}],
    }]}), encoding="utf-8")
    antes = _sha(fichas)
    vista = estado_expediente(entorno["raiz"], empresa="MBT", hoy=HOY)
    assert [(d["documento_id"], d["fuente"], d["estado_vencimiento"]) for d in vista] == [
        ("lic-1", "FICHA_CHOFER", "POR_VENCER")]
    assert _sha(fichas) == antes
    # Una licencia registrada en el expediente prevalece: no se cuenta dos veces.
    _reg(entorno, entidad="CHOFER", referencia="123456785", tipo="LICENCIA_CONDUCIR", fecha_vencimiento="2030-01-01")
    vista = estado_expediente(entorno["raiz"], empresa="MBT", hoy=HOY)
    assert [(d["fuente"], d["estado_vencimiento"]) for d in vista] == [("EXPEDIENTE", "VIGENTE")]


def test_empresas_separadas(entorno):
    _reg(entorno)
    _reg(entorno, empresa="OTRA_EMPRESA")
    assert len(leer_expediente(entorno["raiz"], empresa="MBT")["documentos"]) == 1
    assert len(leer_expediente(entorno["raiz"], empresa="OTRA_EMPRESA")["documentos"]) == 1
    ruta = ruta_almacen_expediente(entorno["raiz"], "MBT")
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["empresa"] = "OTRA_EMPRESA"
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    with pytest.raises(ErrorExpedienteDigital, match="incompatible"):
        leer_expediente(entorno["raiz"], empresa="MBT")
