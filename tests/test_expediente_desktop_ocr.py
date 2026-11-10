import io
import json
from pathlib import Path

import pytest
from PIL import Image

from atlas_core.desktop_operacion import ejecutar_script, sesion
from atlas_core.expediente_digital import consultar_expediente, leer_expediente, registrar_documento
from tests.fixtures_pdf_sinteticos import construir_pdf, pagina_escaneada
from tests.test_expediente_digital_base import PATENTE, RELOJ, _catalogos


class OCR:
    def __init__(self, lineas):
        self.lineas = lineas
        self.rutas = []
        self.cerrado = False

    def leer_texto(self, ruta):
        self.rutas.append(Path(ruta).suffix)
        return self.lineas

    def cerrar(self):
        self.cerrado = True


@pytest.fixture
def raiz(tmp_path):
    _catalogos(tmp_path / "catalogos_privados", "ANA", vehiculos=(PATENTE, "ZZ1234"))
    return tmp_path


def ejecutar_alta(raiz, archivo, monkeypatch, lineas, tipo="SOAP"):
    import atlas_core.ocr_provider as proveedor
    ocr = OCR(lineas)
    monkeypatch.setattr(proveedor, "crear_proveedor_ocr", lambda: ocr)
    with sesion(raiz):
        salida = ejecutar_script(["registrar_expediente_digital.py", "--raiz-atlas", str(raiz), "--entidad", "VEHICULO",
                                  "--referencia", PATENTE, "--tipo", tipo, "--archivo", str(archivo)])
    return json.loads(salida), ocr


@pytest.mark.parametrize("formato", ["jpg", "png", "pdf"])
@pytest.mark.parametrize("tipo", ["SOAP", "REVISION_TECNICA", "PERMISO_CIRCULACION", "CERTIFICADO_EMISION_GASES",
                                 "POLIZA_RESPONSABILIDAD_CIVIL", "POLIZA_ROBO"])
def test_alta_desktop_ocr_custodia_y_consulta(raiz, monkeypatch, formato, tipo):
    archivo = raiz / ("entrada." + formato)
    if formato == "pdf":
        contenido = construir_pdf([pagina_escaneada("documento sintetico")])
    else:
        salida = io.BytesIO()
        Image.new("RGB", (30, 30), "white").save(salida, format="JPEG" if formato == "jpg" else "PNG")
        contenido = salida.getvalue()
    archivo.write_bytes(contenido)
    previo = registrar_documento(raiz, empresa="MBT", entidad="VEHICULO", referencia=PATENTE, tipo=tipo,
                                 fecha_vencimiento="2026-12-31", actor="TEST", reloj=RELOJ)
    doc, ocr = ejecutar_alta(raiz, archivo, monkeypatch, ["PATENTE KN5439", "FECHA DE EMISION: 01/10/2026",
        "VENCIMIENTO: 30/09/2027", "ASEGURADORA: COMPANIA EJEMPLO", "POLIZA: ABC123",
        "COBERTURAS: RESPONSABILIDAD CIVIL Y ROBO"], tipo=tipo)
    assert ocr.cerrado and ocr.rutas == ([".png"] if formato == "pdf" else ["." + formato])
    assert not doc["pendiente_revision"] and doc["fecha_vencimiento"] == "2027-09-30"
    campos = doc["extraccion_automatica"]["campos"]
    assert campos["patente"]["valor"] == PATENTE and campos["numero_poliza"]["valor"] == "ABC123"
    assert campos["coberturas"]["valor"] == ["POLIZA_RESPONSABILIDAD_CIVIL", "POLIZA_ROBO"]
    assert (raiz / "fichas_digitales" / "MBT" / doc["archivo"]).read_bytes() == contenido == archivo.read_bytes()
    consulta = consultar_expediente(raiz, empresa="MBT", entidad="VEHICULO", referencia=PATENTE)
    assert consulta["documentos"][0]["documento_id"] == doc["documento_id"]
    assert consulta["historico"][0]["documento_id"] == previo["documento_id"]


@pytest.mark.parametrize("lineas", [
    ["PATENTE KN5439", "VENCE: 30/09/2027", "VENCE: 31/03/2027", "POLIZA: ABC123"],
    ["PATENTE ZZ1234", "VENCE: 30/09/2027", "POLIZA: ABC123"],
])
def test_dato_ambiguo_no_reemplaza_documento_anterior(raiz, monkeypatch, lineas):
    previo = registrar_documento(raiz, empresa="MBT", entidad="VEHICULO", referencia=PATENTE, tipo="SOAP",
                                 fecha_vencimiento="2027-03-31", actor="TEST", reloj=RELOJ)
    archivo = raiz / "foto.jpg"
    Image.new("RGB", (30, 30), "white").save(archivo)
    doc, _ = ejecutar_alta(raiz, archivo, monkeypatch, lineas)
    assert doc["pendiente_revision"]
    assert doc["extraccion_automatica"]["campos"]["numero_poliza"]["valor"] == "ABC123"
    vista = consultar_expediente(raiz, empresa="MBT", entidad="VEHICULO", referencia=PATENTE)
    assert {d["documento_id"] for d in vista["documentos"]} == {previo["documento_id"], doc["documento_id"]}
    assert next(d for d in vista["documentos"] if d["documento_id"] == doc["documento_id"])["estado_vencimiento"] == "PENDIENTE_REVISION"
    assert len(leer_expediente(raiz, empresa="MBT")["historial"]) >= 3


def test_error_ocr_conserva_original_pendiente_y_anterior(raiz, monkeypatch):
    import atlas_core.ocr_provider as proveedor
    previo = registrar_documento(raiz, empresa="MBT", entidad="VEHICULO", referencia=PATENTE, tipo="SOAP",
                                 fecha_vencimiento="2027-03-31", actor="TEST", reloj=RELOJ)
    archivo = raiz / "foto.png"
    Image.new("RGB", (30, 30), "white").save(archivo)
    def fallar():
        raise RuntimeError("OCR no disponible")
    monkeypatch.setattr(proveedor, "crear_proveedor_ocr", fallar)
    with sesion(raiz):
        salida = ejecutar_script(["registrar_expediente_digital.py", "--raiz-atlas", str(raiz), "--entidad", "VEHICULO",
                                  "--referencia", PATENTE, "--tipo", "SOAP", "--archivo", str(archivo)])
    doc = json.loads(salida)
    assert doc["pendiente_revision"] and doc["extraccion_automatica"]["motivo"] == "ERROR_OCR"
    assert all(c["estado"] == "PENDIENTE_REVISION" for c in doc["extraccion_automatica"]["campos"].values())
    assert (raiz / "fichas_digitales" / "MBT" / doc["archivo"]).read_bytes() == archivo.read_bytes()
    assert next(d for d in leer_expediente(raiz, empresa="MBT")["documentos"]
                if d["documento_id"] == previo["documento_id"])["estado"] == "ACTIVO"
