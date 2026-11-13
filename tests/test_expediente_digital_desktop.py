"""Canales de Desktop para el expediente digital -- sólo fixtures sintéticas."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from atlas_core.cli_fichas_catalogos import main
from atlas_core.desktop_operacion import ESCRITORES
from atlas_core.expediente_digital import empresa_del_proceso, estado_expediente, leer_expediente, registrar_documento, vista_expediente_desktop
from tests.test_expediente_digital_base import CLAVE, HOY, PATENTE, RELOJ, RUT, _catalogos, _ficha, _ficha_chofer

MOTOR = Path(__file__).resolve().parent.parent


@pytest.fixture
def raiz(tmp_path):
    _catalogos(tmp_path / "catalogos_privados", "ANA")
    return tmp_path


def _soap(raiz, vencimiento="2027-03-31"):
    return registrar_documento(raiz, empresa="MBT", entidad="VEHICULO", referencia=PATENTE, tipo="SOAP",
                               fecha_vencimiento=vencimiento, actor="T", reloj=RELOJ)


def _ficha_soap(raiz, vencimiento):
    _ficha(raiz, "MBT", vehiculos=[{"patente": PATENTE, "historial": [], "documentos": [
        {"documento_id": "f-soap", "tipo": "SOAP", "vencimiento": vencimiento, "archivo": "archivos/v/s.pdf"}]}])


def test_renovacion_mas_reciente_en_ficha_prevalece(raiz):
    _soap(raiz, "2026-11-20")
    _ficha_soap(raiz, "2027-12-01")
    assert [(d["documento_id"], d["fuente"]) for d in estado_expediente(raiz, empresa="MBT", hoy=HOY)] == [
        ("f-soap", "FICHA_VEHICULO")]


@pytest.mark.parametrize("vencimiento_ficha", ["2026-11-20", "2026-01-01"])
def test_ficha_no_mas_reciente_no_desplaza_al_expediente(raiz, vencimiento_ficha):
    _soap(raiz, "2026-11-20")
    _ficha_soap(raiz, vencimiento_ficha)
    assert [d["fuente"] for d in estado_expediente(raiz, empresa="MBT", hoy=HOY)] == ["EXPEDIENTE"]


def test_licencia_de_ficha_visible_y_no_registrable(raiz):
    fichas = _ficha(raiz, "MBT", choferes=[_ficha_chofer([CLAVE], [
        {"documento_id": "lic", "tipo": "LICENCIA_CONDUCIR", "vencimiento": "2026-11-20", "archivo": "archivos/c/l.pdf"}])])
    antes = fichas.read_bytes()
    vista = vista_expediente_desktop(raiz, empresa="MBT", entidad="CHOFER", referencia=RUT, hoy=HOY)
    assert [(d["documento_id"], d["fuente"]) for d in vista["documentos"]] == [("lic", "FICHA_CHOFER")]
    assert vista["ausentes"] == [] and [a["documento_id"] for a in vista["alertas"]] == ["lic"]
    assert "LICENCIA_CONDUCIR" not in {t["tipo"] for t in vista["tipos_registrables"]}
    assert fichas.read_bytes() == antes and leer_expediente(raiz, empresa="MBT")["expedientes"] == []


def test_vista_vehiculo_ofrece_sus_tipos_y_filtra_alertas_ajenas(raiz):
    registrar_documento(raiz, empresa="MBT", entidad="CHOFER", referencia=RUT, tipo="LICENCIA_CONDUCIR",
                        fecha_vencimiento="2026-11-20", actor="T", reloj=RELOJ)
    vista = vista_expediente_desktop(raiz, empresa="MBT", entidad="VEHICULO", referencia=PATENTE, hoy=HOY)
    assert {t["tipo"] for t in vista["tipos_registrables"]} == {"SOAP", "REVISION_TECNICA", "PERMISO_CIRCULACION", "SEGURO_CARGA", "CERTIFICADO_EMISION_GASES", "POLIZA_RESPONSABILIDAD_CIVIL", "POLIZA_ROBO"}
    assert vista["alertas"] == []


def test_cli_consulta_no_escribe_y_devuelve_empresa(raiz, capsys):
    assert main(["--raiz-atlas", str(raiz), "--expediente-entidad", "VEHICULO", "--expediente-referencia", PATENTE]) == 0
    salida = json.loads(capsys.readouterr().out)
    # Tracto: sus cinco requisitos (la responsabilidad civil sí; el seguro de carga corresponde a la rampla).
    assert (salida["empresa"], salida["existe"]) == ("MBT", False)
    assert {a["tipo"] for a in salida["ausentes"]} == {"SOAP", "REVISION_TECNICA", "PERMISO_CIRCULACION",
                                                      "CERTIFICADO_EMISION_GASES", "POLIZA_RESPONSABILIDAD_CIVIL"}
    assert not (raiz / "fichas_digitales").exists()


def test_cli_alertas(raiz, capsys):
    _soap(raiz, "2020-01-01")
    assert main(["--raiz-atlas", str(raiz), "--expediente-alertas"]) == 0
    salida = json.loads(capsys.readouterr().out)
    assert [(a["tipo"], a["nivel"]) for a in salida["alertas"]] == [("SOAP", "VENCIDO")] and salida["empresa"] == "MBT"


def test_cli_identidad_inexistente_informa_el_motivo(raiz, capsys):
    assert main(["--raiz-atlas", str(raiz), "--expediente-entidad", "VEHICULO", "--expediente-referencia", "ZZ9999"]) == 1
    assert "no existe" in capsys.readouterr().err


def test_empresa_del_proceso_es_codigo_de_almacen(monkeypatch):
    monkeypatch.setattr("atlas_core.fichas_choferes.EMPRESA_ACTUAL", "transportes-norte")
    assert empresa_del_proceso() == "TRANSPORTES-NORTE"


def test_escritor_admitido_en_canal_operacional():
    assert "registrar_expediente_digital.py" in ESCRITORES


def _escritor(raiz, tipo, archivo, *extra):
    return subprocess.run([sys.executable, "-B", str(MOTOR / "registrar_expediente_digital.py"), "--raiz-atlas", str(raiz),
                           "--entidad", "VEHICULO", "--referencia", PATENTE, "--tipo", tipo, "--archivo", str(archivo), *extra],
                          cwd=MOTOR, capture_output=True, text=True, encoding="utf-8", check=False)


def test_escritor_custodia_el_original(raiz):
    origen = raiz / "soap.pdf"
    origen.write_bytes(b"%PDF-1.4 sintetico")
    r = _escritor(raiz, "SOAP", origen, "--fecha-emision", "2026-01-01", "--fecha-vencimiento", "2027-01-01")
    assert r.returncode == 0, r.stderr
    documento = json.loads(r.stdout)
    guardado = raiz / "fichas_digitales" / "MBT" / documento["archivo"]
    assert (documento["actor"], guardado.read_bytes()) == ("DESKTOP", origen.read_bytes())
    assert origen.exists()


def test_escritor_rechaza_licencia_y_archivo_falso(raiz):
    origen = raiz / "x.pdf"
    origen.write_bytes(b"no es pdf")
    assert "licencia" in _escritor(raiz, "LICENCIA_CONDUCIR", origen).stderr.lower()
    r = _escritor(raiz, "SOAP", origen, "--fecha-vencimiento", "2027-01-01")
    assert r.returncode != 0 and not (raiz / "fichas_digitales").exists()
