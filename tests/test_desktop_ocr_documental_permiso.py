from pathlib import Path
import os
import pytest
from atlas_core import desktop_operacion as d

@pytest.mark.parametrize('script,permitido',[('registrar_expediente_digital.py',True),('corregir_fechas_documento.py',False)])
def test_permiso_worker_ocr_limitado_al_registro(tmp_path, monkeypatch, script, permitido):
    runtime=tmp_path/'python.exe'; runtime.write_bytes(b'')
    monkeypatch.setattr(d,'RUNTIME_RAPIDOCR_MANUAL',runtime)
    monkeypatch.setenv('ATLAS_OCR_PROVIDER','rapidocr')
    worker=(d.RAIZ_CODIGO/'atlas_core'/'rapidocr_worker.py').resolve()
    def cli(args, entrada=None):
        correcto=(None,[str(runtime.resolve()),str(worker)])
        otro=(None,[str(runtime.resolve()),str(worker)+'-otro'])
        assert d._es_worker_ocr_permitido(correcto) is permitido
        assert not d._es_worker_ocr_permitido(otro)
        return '{}'
    monkeypatch.setattr(d,'_cli',cli)
    monkeypatch.setattr('atlas_core.aislamiento_empresas.exigir_raiz_de_proceso',lambda raiz:None)
    assert d.ejecutar({'accion':'script','raiz':str(tmp_path),'argumentos':[script]})['ok']

def test_registro_respeta_runtime_configurado(tmp_path, monkeypatch):
    runtime = tmp_path / 'python.exe'
    runtime.write_bytes(b'')
    monkeypatch.setenv('ATLAS_OCR_PROVIDER', 'rapidocr')
    monkeypatch.setenv('ATLAS_RAPIDOCR_PYTHON', str(runtime))
    monkeypatch.setattr(d, 'RUNTIME_RAPIDOCR_MANUAL', tmp_path / 'ausente' / 'python.exe')
    monkeypatch.setattr('atlas_core.aislamiento_empresas.exigir_raiz_de_proceso', lambda raiz: None)
    worker = (d.RAIZ_CODIGO / 'atlas_core' / 'rapidocr_worker.py').resolve()
    def cli(args, entrada=None):
        assert d._es_worker_ocr_permitido((None, [str(runtime), str(worker)]))
        return '{}'
    monkeypatch.setattr(d, '_cli', cli)
    assert d.ejecutar({'accion': 'script', 'raiz': str(tmp_path), 'argumentos': ['registrar_expediente_digital.py']})['ok']
