"""Corte de un proceso sobre CustodiaEstado, con Cloud falsa persistente."""
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import socket
def negar_red(*args, **kwargs):
    raise PermissionError('red deshabilitada en hijo sintetico')
socket.socket.connect = negar_red
socket.socket.connect_ex = negar_red
socket.create_connection = negar_red

# No se importa Atlas hasta comprobar los argumentos, perfil y directorio aislados.
root = Path(os.environ['M1_RECINTO']).resolve(strict=True)
assert root.name.startswith('m1-sintetico-') and root.is_dir()
assert Path(os.environ['LOCALAPPDATA']).resolve().is_relative_to(root)
assert not any('TOKEN' in k.upper() and v for k, v in os.environ.items())
from atlas_core.estado_confirmado import CustodiaEstado

class Cloud:
    def __init__(self):
        self.path = root / 'cloud.json'
        self.data = json.loads(self.path.read_text(encoding='utf-8'))
    def faltantes(self, huellas):
        return [h for h in huellas if h not in self.data['objetos']]
    def subir(self, sha, datos, lease_token):
        assert lease_token == 'lease-ficticio' and hashlib.sha256(datos).hexdigest() == sha
        self.data['objetos'][sha] = datos.hex()
    def confirmar(self, token, version, archivos):
        assert token == 'lease-ficticio' and version == self.data['version']
        assert all(sha in self.data['objetos'] for _, sha in archivos)
        self.data['version'] += 1
        self.data['archivos'].update(dict(archivos))
        self.data['lotes'].append(len(archivos))
        self.path.write_text(json.dumps(self.data), encoding='utf-8')
        # Corte abrupto luego de persistir, antes de responder al Motor.
        if self.data['version'] == int(os.environ['M1_CORTE']):
            os._exit(73)
        return self.data['version']

cliente = Cloud()
c = CustodiaEstado(root / 'datos', cliente, carpeta_local=root / 'perfil' / 'cache')
lease = SimpleNamespace(lease_token='lease-ficticio')
rels = [f'operacion/actual/{i:03}.json' for i in range(101)]
c._confirmar_rutas(lease, rels)
