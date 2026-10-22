import pytest
import sys

# Solo procesos de ensayo; no modifica el Motor ni runtimes existentes.
def _no_instalar(evento,args):
    if evento == 'subprocess.Popen':
        cmd=args[1]
        texto=cmd if isinstance(cmd,str) else ' '.join(map(str,cmd))
        if 'pip' in texto.lower() and 'install' in texto.lower():
            raise PermissionError('Ensayo aislado: instalacion de dependencias prohibida')
sys.addaudithook(_no_instalar)

@pytest.fixture(autouse=True)
def sin_ocr_real(monkeypatch):
    from atlas_core import mobile,cloud_mobile_sync_cliente
    monkeypatch.setattr(mobile,'crear_proveedor_ocr',lambda *a,**kw:object())
    monkeypatch.setattr(cloud_mobile_sync_cliente,'crear_proveedor_ocr',lambda *a,**kw:object())
