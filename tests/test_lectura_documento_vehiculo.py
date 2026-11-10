import hashlib

import pytest

from atlas_core.lectura_documento_vehiculo import extraer_campos_adicionales, leer_texto_documento
from atlas_core.identificacion_patentes import identificar_patentes_documentos
from atlas_core.extraccion_vencimientos_vehiculos import extraer_vencimientos_vehiculos
from tests.fixtures_pdf_sinteticos import construir_pdf, pagina_escaneada
from tests.test_identificacion_patentes import TRACTO, _recibir, _ubicar, raiz  # noqa: F401


class OCR:
    def __init__(self):
        self.rutas = []

    def leer_texto(self, ruta):
        self.rutas.append(ruta.suffix)
        return ["PATENTE BPHR67", "FECHA DE EMISION: 01/10/2026", "VENCIMIENTO: 30/09/2027",
                "ASEGURADORA: COMPANIA EJEMPLO", "POLIZA: ABC123"]


@pytest.mark.parametrize("tipo", ["SOAP", "REVISION_TECNICA", "PERMISO_CIRCULACION",
                                 "CERTIFICADO_EMISION_GASES", "POLIZA_RESPONSABILIDAD_CIVIL", "POLIZA_ROBO"])
@pytest.mark.parametrize("formato", ["imagen", "pdf"])
def test_lectura_mobile_reutiliza_ocr_y_conserva_original(raiz, tipo, formato):
    contenido = (b"\xff\xd8\xff\xe0imagen" if formato == "imagen" else
                 construir_pdf([pagina_escaneada("documento sintetico")]))
    doc_id, _ = _recibir(raiz, formato + tipo, tipo=tipo, contenido=contenido,
                         mime="image/jpeg" if formato == "imagen" else "application/pdf")
    ocr = OCR()
    identificar_patentes_documentos(raiz, comprobar=lambda: None, fabrica_ocr=lambda: ocr)
    extraer_vencimientos_vehiculos(raiz, comprobar=lambda: None, fabrica_ocr=lambda: ocr)
    patente, documento = _ubicar(raiz, doc_id)
    assert patente == TRACTO
    campos = documento["extraccion_automatica"]["campos"]
    assert [campos[k]["valor"] for k in ("emision", "vencimiento", "aseguradora", "numero_poliza")] == [
        "2026-10-01", "2027-09-30", "COMPANIA EJEMPLO", "ABC123"]
    assert campos["coberturas"]["estado"] == "PENDIENTE_REVISION"
    original = raiz / "fichas_digitales" / "MBT" / documento["archivo"]
    assert hashlib.sha256(original.read_bytes()).hexdigest() == documento["sha256"]
    assert ocr.rutas == ([".jpg", ".jpg"] if formato == "imagen" else [".png", ".png"])
    assert not list(original.parent.glob(".ocr-vehiculo-*"))


def test_valores_ambiguos_no_se_inventan():
    campos = extraer_campos_adicionales(["POLIZA: ABC123", "POLIZA: DEF456", "FECHA DE EMISION: 30/02/2026"])
    assert campos["numero_poliza"]["valor"] is None
    assert campos["numero_poliza"]["motivo"] == "VARIOS_VALORES"
    assert campos["emision"]["valor"] is None


def test_cobertura_conjunta_y_exclusion():
    linea = "COBERTURAS: RESPONSABILIDAD CIVIL Y ROBO"
    assert extraer_campos_adicionales([linea])["coberturas"]["valor"] == [
        "POLIZA_RESPONSABILIDAD_CIVIL", "POLIZA_ROBO"]
    assert extraer_campos_adicionales([linea, "EXCLUSION ROBO"])["coberturas"]["valor"] is None


def test_pdf_multipagina_y_fallo_no_produce_lectura_parcial(tmp_path):
    ruta = tmp_path / "documento.pdf"
    ruta.write_bytes(construir_pdf([pagina_escaneada("pagina uno"), pagina_escaneada("pagina dos")]))
    ocr = OCR()
    assert len(leer_texto_documento(ruta, lambda: ocr)) == 10
    assert ocr.rutas == [".png", ".png"]

    class Falla(OCR):
        def leer_texto(self, ruta):
            if self.rutas:
                raise RuntimeError("fallo OCR")
            return super().leer_texto(ruta)

    falla = Falla()
    with pytest.raises(RuntimeError, match="fallo OCR"):
        leer_texto_documento(ruta, lambda: falla)
    assert not list(tmp_path.glob(".ocr-vehiculo-*"))
