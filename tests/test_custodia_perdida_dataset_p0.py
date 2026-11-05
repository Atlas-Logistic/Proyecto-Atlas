import hashlib
from pathlib import Path
from types import SimpleNamespace
import pytest
from atlas_core.estado_confirmado import CustodiaEstado, EstadoNoVerificado

REL = 'operacion/actual/analisis_completo_guias.csv'

def csv(*ids):
    return ('archivo;numero_guia;numero_transporte\n' + ''.join(f'{i};{i};T{i}\n' for i in ids)).encode()

class Cliente:
    def __init__(self, data): self.data = data
    def manifiesto(self): return {'version': 1, 'archivos': [[REL, hashlib.sha256(self.data).hexdigest(), 1]]}
    def descargar(self, sha): return self.data
    def conocidos(self, consultas): return [False] * len(consultas)

def test_alineacion_no_elimina_fila_confirmada_ni_toca_otras(tmp_path):
    local = csv('base', '484133', *map(str, range(6)))
    remoto = csv('base', *map(str, range(6)))
    ruta = tmp_path / 'raiz' / REL
    ruta.parent.mkdir(parents=True)
    ruta.write_bytes(local)
    c = CustodiaEstado(tmp_path / 'raiz', Cliente(remoto), carpeta_local=tmp_path / 'cache')
    with pytest.raises(EstadoNoVerificado, match='eliminaria'):
        c.alinear(SimpleNamespace(marca={'version': 1}))
    assert ruta.read_bytes() == local

def test_alineacion_permite_cloud_mas_completo(tmp_path):
    ruta = tmp_path / 'raiz' / REL
    ruta.parent.mkdir(parents=True)
    ruta.write_bytes(csv('base'))
    remoto = csv('base', 'nuevo')
    c = CustodiaEstado(tmp_path / 'raiz', Cliente(remoto), carpeta_local=tmp_path / 'cache')
    c.alinear(SimpleNamespace(marca={'version': 1}))
    assert ruta.read_bytes() == remoto

def test_dataset_ambiguo_no_se_sustituye(tmp_path):
    ruta = tmp_path / 'raiz' / REL
    ruta.parent.mkdir(parents=True)
    ruta.write_bytes(csv('duplicado', 'duplicado'))
    c = CustodiaEstado(tmp_path / 'raiz', Cliente(csv('base')), carpeta_local=tmp_path / 'cache')
    with pytest.raises(EstadoNoVerificado, match='duplicada'):
        c.alinear(SimpleNamespace(marca={'version': 1}))

def test_dataset_no_confia_en_cache_con_igual_tamano_y_fecha(tmp_path):
    import os
    ruta = tmp_path / 'raiz' / REL
    ruta.parent.mkdir(parents=True)
    ruta.write_bytes(csv('aaaa'))
    c = CustodiaEstado(tmp_path / 'raiz', Cliente(csv('aaaa')), carpeta_local=tmp_path / 'cache')
    inicial = c._huellas_locales([REL])[REL]
    stat = ruta.stat()
    ruta.write_bytes(csv('bbbb'))
    os.utime(ruta, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert c._huellas_locales([REL])[REL] != inicial
