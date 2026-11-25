import hashlib
import json
import pytest
from atlas_core.expediente_digital import ErrorExpedienteDigital, registrar_documento, leer_expediente
from tests.test_expediente_digital_base import _catalogos, _ficha
from tests.test_renovacion_documental import alta

@pytest.fixture
def root(tmp_path):
    _catalogos(tmp_path / 'catalogos_privados', 'SINTETICO', vehiculos=('KN5439','ZZ1234'))
    return tmp_path

def test_ocr_duplicado_no_reprocesa_ni_altera_original(root):
    first = alta(root, ['DOCUMENTO SINTETICO'], contenido=b'unico')
    before = (root/'fichas_digitales/MBT/expediente_documentos.json').read_bytes()
    original = root/'fichas_digitales/MBT'/first['archivo']
    with pytest.raises(ErrorExpedienteDigital, match='ya está registrado'):
        alta(root, ['SOAP'], tipo='REVISION_TECNICA', contenido=b'unico')
    assert (root/'fichas_digitales/MBT/expediente_documentos.json').read_bytes() == before
    assert hashlib.sha256(original.read_bytes()).hexdigest() == first['sha256']
    assert len(leer_expediente(root, empresa='MBT')['documentos']) == 1

def test_duplicado_en_ficha_mobile_no_crea_expediente(root):
    content = b'%PDF-1.4 sintetico'
    _ficha(root, 'MBT', vehiculos=[{'patente':'KN5439','historial':[], 'documentos':[{'tipo':'SOAP','sha256':hashlib.sha256(content).hexdigest()}]}])
    with pytest.raises(ErrorExpedienteDigital, match='ya está registrado'):
        registrar_documento(root,empresa='MBT',entidad='VEHICULO',referencia='KN5439',tipo='SEGURO_CARGA',actor='TEST',fecha_vencimiento='2027-12-31',contenido=content,mime_type='application/pdf',rechazar_duplicado=True)
    assert leer_expediente(root,empresa='MBT')['documentos'] == []

def test_archivo_en_otro_vehiculo_se_permite(root):
    content = b'%PDF-1.4 sintetico'
    d=dict(empresa='MBT',entidad='VEHICULO',tipo='SEGURO_CARGA',actor='TEST',fecha_vencimiento='2027-12-31',contenido=content,mime_type='application/pdf',rechazar_duplicado=True)
    registrar_documento(root,referencia='KN5439',**d)
    registrar_documento(root,referencia='ZZ1234',**d)
    assert len(leer_expediente(root,empresa='MBT')['documentos'])==2
