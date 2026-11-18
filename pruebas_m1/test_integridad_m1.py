"""Pruebas sintéticas sin red ni datos de Atlas. Ejecutar sólo este archivo."""
import copy
import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from pruebas_m1.integridad import Bloqueado, cargar_json_seguro, digest, envios_posteriores, validar


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    def negar(*args, **kwargs):
        raise PermissionError('red deshabilitada en arnés sintético')
    monkeypatch.setattr(socket.socket, 'connect', negar)
    monkeypatch.setattr(socket.socket, 'connect_ex', negar)
    monkeypatch.setattr(socket, 'create_connection', negar)


@pytest.fixture
def generacion():
    archivos = {'operacion/actual/dataset.csv': b'guia-1;documento-1',
                'originales/documento-1.jpg': b'imagen-ficticia',
                'reportes/g1/viajes.csv': b'viaje-1;guia-1',
                'catalogos/plantas.json': b'{"planta":"p1"}'}
    decisiones = [
        {'id':'H1','tipo':'HUMANA','confirmante':'persona-ficticia','campo':'folio','valor':'1'},
        {'id':'H2','tipo':'HUMANA','confirmante':'persona-ficticia','campo':'destino','valor':'p1'},
        {'id':'A1','tipo':'AUTOMATICA','confirmante':None,'campo':'peso','valor':'5'},
        {'id':'P1','tipo':'PROPUESTA','confirmante':None,'campo':'origen','valor':'p1'},
    ]
    snap = {'empresa':'empresa-a','generacion':'G1','archivos':archivos,
            'documentos':['documento-1'], 'decisiones':decisiones, 'reporte':'reportes/g1/viajes.csv'}
    esperado = {'empresa':'empresa-a','generacion':'G1',
                'archivos':{k:digest(v) for k,v in archivos.items()}, 'documentos':['documento-1'],
                'decisiones':{d['id']:copy.deepcopy(d) for d in decisiones}, 'reporte':'reportes/g1/viajes.csv'}
    return snap, esperado


def test_integridad_y_reportes_fuera_de_custodia(generacion):
    snap, oracle = generacion
    validar(snap, oracle)
    del snap['archivos']['reportes/g1/viajes.csv']
    with pytest.raises(Bloqueado, match='ARCHIVO_AUSENTE'):
        validar(snap, oracle)


def test_original_ausente_alterado_y_generacion_inconsistente(generacion):
    snap, oracle = generacion
    snap['archivos']['originales/documento-1.jpg'] = b'otro'
    with pytest.raises(Bloqueado): validar(snap, oracle)
    snap['generacion'] = 'G0'
    with pytest.raises(Bloqueado, match='GENERACION'): validar(snap, oracle)


@pytest.mark.parametrize('cambio', ['perdida','duplicada','confirmacion_fabricada','confirmante_cambiado'])
def test_decisiones_protegidas(generacion, cambio):
    snap, oracle = generacion
    if cambio == 'perdida': snap['decisiones'].pop(0)
    if cambio == 'duplicada': snap['decisiones'].append(copy.deepcopy(snap['decisiones'][0]))
    if cambio == 'confirmacion_fabricada': snap['decisiones'][3]['tipo'] = 'HUMANA'; snap['decisiones'][3]['confirmante'] = 'inventado'
    if cambio == 'confirmante_cambiado': snap['decisiones'][0]['confirmante'] = 'inventado'
    with pytest.raises(Bloqueado): validar(snap, oracle)


def test_envio_confirmado_posterior_y_conflicto():
    e1 = {'empresa':'a','envio':'E1','documento':'D1','sha256':'111','estado':'COMPLETADO'}
    e2 = {'empresa':'a','envio':'E2','documento':'D2','sha256':'222','estado':'COMPLETADO'}
    pendientes = envios_posteriores([e1], [e1,e2])
    assert pendientes == [dict(e2, recuperacion='PENDIENTE')]
    with pytest.raises(Bloqueado, match='CONFLICTIVO'):
        envios_posteriores([e1], [dict(e1,sha256='distinto')])
    with pytest.raises(Bloqueado, match='IDENTIDAD'):
        envios_posteriores([], [dict(e2,sha256='')])


def test_aislamiento_lectura(tmp_path):
    recinto = tmp_path / 'recinto'; recinto.mkdir()
    externo = tmp_path / 'externo.json'; externo.write_text('{}', encoding='utf-8')
    with pytest.raises(Bloqueado, match='RUTA_FUERA'):
        cargar_json_seguro(recinto, '../externo.json')
    with pytest.raises(PermissionError): socket.socket().connect(('127.0.0.1', 1))


@pytest.mark.parametrize('corte,lotes', [(1,[50]), (2,[50,50]), (3,[50,50,1])])
def test_corte_proceso_real_custodia(corte, lotes):
    # Sólo datos ficticios, directorio temporal propio y entorno filtrado.
    with tempfile.TemporaryDirectory(prefix='m1-sintetico-') as temporal:
        root = Path(temporal).resolve()
        (root/'perfil'/'cache').mkdir(parents=True)
        (root/'datos'/'operacion'/'actual').mkdir(parents=True)
        viejo, nuevo = b'G0', b'G1'
        rutas = [f'operacion/actual/{i:03}.json' for i in range(101)]
        for rel in rutas: (root/'datos'/rel).write_bytes(nuevo)
        cloud = {'version':0,'lotes':[], 'objetos':{digest(viejo):viejo.hex()},
                 'archivos':{r:digest(viejo) for r in rutas}}
        (root/'cloud.json').write_text(json.dumps(cloud), encoding='utf-8')
        repo = Path(__file__).resolve().parents[1]
        env = {k:v for k,v in os.environ.items() if k.upper() in ('SYSTEMROOT','WINDIR','PATH','PATHEXT','COMSPEC')}
        env.update({'M1_RECINTO':str(root), 'M1_CORTE':str(corte), 'LOCALAPPDATA':str(root/'perfil'),
                    'APPDATA':str(root/'perfil'), 'USERPROFILE':str(root/'perfil'), 'TEMP':str(root), 'TMP':str(root),
                    'PYTHONPATH':str(repo), 'PYTHONDONTWRITEBYTECODE':'1'})
        child = subprocess.run([sys.executable, str(repo/'pruebas_m1'/'corte_hijo.py')],
                               cwd=root, env=env, capture_output=True, text=True, timeout=30)
        assert child.returncode == 73, (child.stdout, child.stderr)
        actual = json.loads((root/'cloud.json').read_text(encoding='utf-8'))
        assert actual['lotes'] == lotes and actual['version'] == corte
        hashes = set(actual['archivos'].values())
        if corte < 3:
            assert hashes == {digest(viejo),digest(nuevo)}  # Marca intermedia observable.
            archivos = {r:bytes.fromhex(actual['objetos'][h]) for r,h in actual['archivos'].items()}
            esperado = {'empresa':'a','generacion':'G1','archivos':{r:digest(nuevo) for r in rutas}, 'documentos':[], 'decisiones':{}, 'reporte':rutas[0]}
            snapshot = {'empresa':'a','generacion':'G1','archivos':archivos,'documentos':[], 'decisiones':[], 'reporte':rutas[0]}
            with pytest.raises(Bloqueado, match='ALTERADO'):
                validar(snapshot, esperado)
        else:
            assert hashes == {digest(nuevo)}




def test_restauracion_sintetica_completa_y_rechazo_previo(generacion):
    from pruebas_m1.integridad import restaurar_sintetico
    snap, oracle = generacion
    with tempfile.TemporaryDirectory(prefix='m1-sintetico-') as tmp:
        root = Path(tmp)
        dañado = copy.deepcopy(snap)
        dañado['archivos'].pop('originales/documento-1.jpg')
        with pytest.raises(Bloqueado): restaurar_sintetico(root, dañado, oracle)
        assert list(root.iterdir()) == []
        restaurar_sintetico(root, snap, oracle)
        assert all(digest((root / rel).read_bytes()) == sha for rel, sha in oracle['archivos'].items())


def test_empresa_equivocada_bloqueada(generacion):
    snap, oracle = generacion
    snap['empresa'] = 'empresa-b'
    with pytest.raises(Bloqueado, match='EMPRESA'): validar(snap, oracle)
