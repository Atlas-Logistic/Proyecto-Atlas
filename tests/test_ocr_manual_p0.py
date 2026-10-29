from pathlib import Path
from dataclasses import replace
import pytest
from contextlib import contextmanager
from atlas_core.ocr import BloqueOCR
from atlas_core.rapidocr_adapter import BloqueRapidOCR
from atlas_core.ocr_manual import RapidOCRManualProvider, separar_etiqueta, localizar_fecha_emision, consensuar_fecha
from atlas_core.ocr_provider import RapidOCRProvider, crear_proveedor_ocr
from atlas_core import desktop_operacion as d


def bloque(texto,x=0,y=0,w=100,h=20):
    return BloqueOCR(texto,((x,y),(x+w,y),(x+w,y+h),(x,y+h)),.95)

@pytest.mark.parametrize('texto,esperado', [('GUIADEDESPACHO','GUIA DE DESPACHO'),('GUIA DEDESPACHO','GUIA DE DESPACHO'),('FECHADEEMISIÓN','FECHA DE EMISION'),('FECHASALIDA','FECHA SALIDA'),('N9482722','N9482722'),('GUIA DE','GUIA DE'),('GUIADEDESPACHO 123456','GUIADEDESPACHO 123456')])
def test_solo_separar_etiquetas_exactas(texto,esperado):
    assert separar_etiqueta(texto)==esperado


def test_fecha_en_misma_fila_no_confunde_rut_ni_salida():
    fecha=bloque('21-10-202',150,0,70)
    b=[bloque('FECHA DE EMISION'),fecha,bloque('83.585.400-0',150,26),bloque('FECHA SALIDA',0,200),bloque('21-10-2024',150,200)]
    assert localizar_fecha_emision(b)['texto']=='21-10-202'
    assert localizar_fecha_emision(b+[bloque('20-10-2026',260,0,70)]) is None
    assert localizar_fecha_emision(b[1:]) is None


def lectura(texto,variante,confianza=.90):
    return dict(texto=texto,variante=variante,confianza=confianza)

@pytest.mark.parametrize('lecturas,esperado', [
    ([lectura('21-10-2026','G'),lectura('21-10-2026','B')],'21-10-2026'),
    ([lectura('21-10-2026','G')],None),
    ([lectura('21-10-2026','G'),lectura('21-10-2026','G')],None),
    ([lectura('21-10-2026','G'),lectura('21-10-2026','B',.4)],None),
    ([lectura('21-10-2026','G'),lectura('21-10-2024','B')],None),
    ([lectura('31-02-2026','G'),lectura('31-02-2026','B')],None),
    ([lectura('21-10-202','G'),lectura('21-10-202','B')],None),
])
def test_consenso_fecha_no_inventa_digitos(lecturas,esperado):
    assert consensuar_fecha(lecturas)==esperado


def test_recupera_fecha_sin_otra_lectura_completa_y_conserva_original(monkeypatch):
    p=RapidOCRManualProvider(); llamadas=[]
    def comando(**kw):
        llamadas.append(kw)
        if kw['op']=='bloques':
            return [[b.bounding_box,b.texto,b.confianza] for b in [bloque('FECHADEEMISION'),bloque('21-10-202',150,0,70)]]
        assert kw['op']=='focal_linea'
        return {'recorte':kw['caja'],'lecturas':[lectura('21-10-2026','G'),lectura('21-10-2026','B')]}
    monkeypatch.setattr(p,'_comando',comando)
    assert p.leer_texto('sin-folio-en-nombre.jpeg')==['FECHA DE EMISION','21-10-2026']
    assert p.leer_bloques('sin-folio-en-nombre.jpeg')[1].texto=='21-10-2026'
    assert [c['op'] for c in llamadas]==['bloques','focal_linea']
    assert p.evidencia_ultima[1].texto_original=='21-10-202'
    assert p.evidencia_manual[0]['valor']=='21-10-2026'


def test_fecha_truncada_sin_consenso_es_error_no_fecha_de_salida(monkeypatch):
    p=RapidOCRManualProvider()
    def comando(**kw):
        if kw['op']=='bloques':return [[b.bounding_box,b.texto,b.confianza] for b in [bloque('FECHADEEMISION'),bloque('21-10-202',150,0,70)]]
        return {'lecturas':[lectura('21-10-2026','G')]}
    monkeypatch.setattr(p,'_comando',comando)
    with pytest.raises(ValueError,match='sin consenso'):p.leer_texto('cualquiera.jpeg')


def test_factory_no_cambia_pull(monkeypatch):
    monkeypatch.setattr(RapidOCRProvider,'_asegurar_proceso',lambda self:None)
    monkeypatch.delenv('ATLAS_OCR_MANUAL',raising=False)
    assert type(crear_proveedor_ocr('rapidocr')) is RapidOCRProvider
    monkeypatch.setenv('ATLAS_OCR_MANUAL','1')
    assert type(crear_proveedor_ocr('rapidocr')) is RapidOCRManualProvider


def test_desktop_limita_rapidocr_al_ingreso_y_restaura_entorno(tmp_path, monkeypatch):
    """RapidOCR queda dentro de la invocación manual, nunca en PULL."""
    vistos = []
    @contextmanager
    def sesion_falsa(_raiz):
        yield lambda: None
    def ingreso_falso(_raiz, _archivos, _comprobar):
        import os
        vistos.append((os.environ.get('ATLAS_OCR_PROVIDER'), os.environ.get('ATLAS_RAPIDOCR_PYTHON'), os.environ.get('ATLAS_OCR_MANUAL')))
        return {'ok': True}
    monkeypatch.setattr(d, 'sesion', sesion_falsa)
    monkeypatch.setattr(d, 'ingresar', ingreso_falso)
    # El perfil Atlas de pruebas está aislado (conftest): el runtime manual
    # se simula con un intérprete existente para que pase el permiso del worker.
    runtime = tmp_path / 'runtime' / 'python.exe'
    runtime.parent.mkdir()
    runtime.write_bytes(b'')
    monkeypatch.setattr(d, 'RUNTIME_RAPIDOCR_MANUAL', runtime)
    monkeypatch.delenv('ATLAS_OCR_PROVIDER', raising=False)
    monkeypatch.delenv('ATLAS_RAPIDOCR_PYTHON', raising=False)
    monkeypatch.delenv('ATLAS_OCR_MANUAL', raising=False)
    assert d.ejecutar({'raiz': str(tmp_path), 'accion': 'ingresar', 'archivos': []}) == {'ok': True}
    assert vistos == [('rapidocr', str(d.RUNTIME_RAPIDOCR_MANUAL), '1')]


def test_auditoria_solo_worker_exacto_con_permiso_y_lease(tmp_path):
    py=(tmp_path/'python.exe').resolve(); worker=(d.RAIZ_CODIGO/'atlas_core/rapidocr_worker.py').resolve()
    permiso=d._worker_ocr.set((py,worker)); vivo=[True]
    audit=d._auditoria.set(([tmp_path],lambda:vivo[0]))
    evento=lambda exe,cmd:d._auditar('subprocess.Popen',(str(exe),list(map(str,cmd)),None,None))
    try:
        evento(py,[py,worker])
        for exe,cmd in [(py,[py,'-c','pass']),(py,[py,worker,'extra']),(py,[py,tmp_path/'otro.py']),(tmp_path/'otro.exe',[py,worker])]:
            with pytest.raises(PermissionError):evento(exe,cmd)
        with pytest.raises(PermissionError):evento('taskkill',['taskkill','/PID','123','/T','/F'])
        vivo[0]=False
        with pytest.raises(PermissionError,match='perdido'):evento(py,[py,worker])
        with d.permiso_cierre_worker_ocr(123):
            evento('taskkill',['taskkill','/PID','123','/T','/F'])
            with pytest.raises(PermissionError):evento('taskkill',['taskkill','/PID','456','/T','/F'])
    finally:d._auditoria.reset(audit);d._worker_ocr.reset(permiso)
    audit=d._auditoria.set(([tmp_path],lambda:True))
    try:
        with pytest.raises(PermissionError):evento(py,[py,worker])
    finally:d._auditoria.reset(audit)

def test_formato_auditoria_real_windows_sin_abrir_shell(tmp_path):
    import subprocess
    py=(tmp_path/'ruta con espacios'/'python.exe').resolve(); worker=(d.RAIZ_CODIGO/'atlas_core/rapidocr_worker.py').resolve()
    token=d._worker_ocr.set((py,worker))
    try:
        command=subprocess.list2cmdline([str(py),str(worker)])
        assert d._es_worker_ocr_permitido((None,command,None,None))
        assert not d._es_worker_ocr_permitido((None,command+' extra',None,None))
        assert not d._es_worker_ocr_permitido(('cmd.exe',command,None,None))
        assert not d._es_worker_ocr_permitido((None,'cmd.exe /c '+command,None,None))
    finally:d._worker_ocr.reset(token)


def test_worker_focal_linea_usa_caja_exacta_y_no_redetecta(tmp_path):
    from PIL import Image,ImageEnhance,ImageOps
    import numpy as np
    from atlas_core.rapidocr_worker import _focal
    ruta=tmp_path/'sintetica.png';Image.new('RGB',(120,60),(90,150,200)).save(ruta)
    vistos=[]
    def engine(array,**kwargs):
        vistos.append((array.shape,kwargs))
        return ([['21-10-2026',.95]], [.01])
    res=_focal(engine,str(ruta),[20,15,90,35],Image,ImageEnhance,ImageOps,np,solo_linea=True)
    assert res['recorte']==[20,15,90,35]
    assert len(vistos)==4 and all(s==(20,70,3) and kw=={'use_det':False,'use_cls':False} for s,kw in vistos)
    assert consensuar_fecha(res['lecturas'])=='21-10-2026'
