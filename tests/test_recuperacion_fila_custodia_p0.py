import csv, hashlib, json
from types import SimpleNamespace
import pytest
from atlas_core import estado_confirmado as ec
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.recuperacion_fila_custodia import recuperar_fila, _filas

def row(archivo, guia, transporte):
    r = dict.fromkeys(COLUMNAS, '')
    r.update(archivo=archivo, numero_guia=guia, numero_transporte=transporte, chofer='RODRIGO', estado_procesamiento='OK')
    return r

def put(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w=csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=';'); w.writeheader(); w.writerows(rows)

def test_recupera_una_y_conserva_seis_idempotente(tmp_path):
    raiz = tmp_path / 'raiz'; dataset = raiz / 'operacion/actual/analisis_completo_guias.csv'
    envio = 'abc'; archivo = 'mobile/abc/original.jpg'
    source = tmp_path / 'cuarentena.csv'; fila = row(archivo, '484133', '0000368927')
    posteriores = [row(f'posterior{i}', str(i), f'T{i}') for i in range(6)]
    put(source, [fila]); put(dataset, posteriores)
    carpeta = raiz / 'operacion/mobile/envios/abc'; carpeta.mkdir(parents=True)
    (carpeta / 'original.jpg').write_bytes(b'original')
    (carpeta / 'envio.json').write_text(json.dumps({'envio_id': envio, 'foto_original': 'original.jpg', 'imagen_sha256': hashlib.sha256(b'original').hexdigest(), 'datos_ocr': {'numero_guia': '484133', 'numero_transporte': '0000368927'}}), encoding='utf-8')
    custodia = ec.CustodiaEstado(raiz, None, carpeta_local=tmp_path / "cache"); lease = SimpleNamespace(vigente=True, custodia=custodia)
    ec._activas.append(custodia)
    try:
        args = dict(raiz=raiz, origen=source, envio_id=envio, guia='484133', transporte='0000368927', lease=lease)
        assert recuperar_fila(**args)['estado'] == 'INSERTADA'
        assert _filas(dataset) == posteriores + [fila]
        assert recuperar_fila(**args)['estado'] == 'YA_PRESENTE'
        assert _filas(dataset) == posteriores + [fila]
        audit = json.loads((raiz / 'operacion/actual/recuperaciones/abc.json').read_text(encoding='utf-8'))
        assert audit['estado'] == 'INSERTADA'
    finally: ec._activas.remove(custodia)

def test_rechaza_sin_lease(tmp_path):
    with pytest.raises(ValueError, match='Lease'):
        recuperar_fila(raiz=tmp_path, origen=tmp_path/'nada', envio_id='abc', guia='1', transporte='2', lease=SimpleNamespace(vigente=False, custodia=None))

def test_confirmacion_cloud_y_reentrada(tmp_path, monkeypatch):
    from unittest.mock import patch
    from test_estado_confirmado import CloudFalsa, Equipo
    cloud = CloudFalsa(); equipo = Equipo(tmp_path, 'casa', cloud)
    dataset = equipo.archivo('operacion/actual/analisis_completo_guias.csv')
    source = tmp_path / 'cuarentena.csv'; fila = row('mobile/abc/original.jpg', '484133', '0000368927')
    posteriores = [row(f'posterior{i}', str(i), f'T{i}') for i in range(6)]
    put(source, [fila]); put(dataset, posteriores)
    carpeta = equipo.raiz / 'operacion/mobile/envios/abc'; carpeta.mkdir(parents=True)
    original = b'original'; (carpeta/'original.jpg').write_bytes(original)
    (carpeta/'envio.json').write_text(json.dumps({'envio_id':'abc','foto_original':'original.jpg', 'imagen_sha256':hashlib.sha256(original).hexdigest(), 'datos_ocr':{'numero_guia':'484133','numero_transporte':'0000368927'}}), encoding='utf-8')
    with patch('atlas_core.escritor_operativo._json', side_effect=cloud.json), patch.object(ec.ClienteEstado, '_crudo', lambda c,h,**kw: cloud.crudo(c,h,**kw)):
        with equipo.lease() as lease:
            assert lease.adquirir()
            lease.custodia.sembrar(lease)
            args=dict(raiz=equipo.raiz, origen=source, envio_id='abc', guia='484133', transporte='0000368927', lease=lease)
            assert recuperar_fila(**args)['estado'] == 'INSERTADA'
        vigentes = cloud._vigentes()
        assert vigentes['operacion/actual/analisis_completo_guias.csv'][0] == ec.sha256_archivo(dataset)
        assert vigentes['operacion/actual/recuperaciones/abc.json'][0] == ec.sha256_archivo(equipo.raiz/'operacion/actual/recuperaciones/abc.json')
        with equipo.lease() as lease:
            assert lease.adquirir(), lease.motivo
            args['lease'] = lease
            assert recuperar_fila(**args)['estado'] == 'YA_PRESENTE'
        assert _filas(dataset) == posteriores + [fila]

def test_reanuda_si_falla_auditoria_despues_del_dataset(tmp_path, monkeypatch):
    import atlas_core.recuperacion_fila_custodia as recovery
    raiz = tmp_path/'raiz'; dataset=raiz/'operacion/actual/analisis_completo_guias.csv'
    fila=row('mobile/abc/original.jpg','484133','0000368927'); source=tmp_path/'origen.csv'
    put(source,[fila]); put(dataset,[row('otro','1','T1')])
    carpeta=raiz/'operacion/mobile/envios/abc'; carpeta.mkdir(parents=True)
    (carpeta/'original.jpg').write_bytes(b'original')
    (carpeta/'envio.json').write_text(json.dumps({'envio_id':'abc','foto_original':'original.jpg','imagen_sha256':hashlib.sha256(b'original').hexdigest(),'datos_ocr':{'numero_guia':'484133','numero_transporte':'0000368927'}}),encoding='utf-8')
    c=ec.CustodiaEstado(raiz,None,carpeta_local=tmp_path/'cache'); lease=SimpleNamespace(vigente=True,custodia=c)
    args=dict(raiz=raiz,origen=source,envio_id='abc',guia='484133',transporte='0000368927',lease=lease)
    real=recovery.escribir_json_atomico; llamadas=[]
    def falla_segunda(path, data):
        llamadas.append(data['estado'])
        if len(llamadas)==2: raise OSError('interrupcion')
        return real(path,data)
    ec._activas.append(c)
    try:
        monkeypatch.setattr(recovery,'escribir_json_atomico',falla_segunda)
        with pytest.raises(OSError): recovery.recuperar_fila(**args)
        assert len(_filas(dataset)) == 2
        monkeypatch.setattr(recovery,'escribir_json_atomico',real)
        assert recovery.recuperar_fila(**args)['estado']=='YA_PRESENTE'
        assert len(_filas(dataset)) == 2
        assert json.loads((raiz/'operacion/actual/recuperaciones/abc.json').read_text(encoding='utf-8'))['estado']=='INSERTADA'
    finally: ec._activas.remove(c)

def test_reintento_confirma_journal_si_cloud_falla(tmp_path):
    from unittest.mock import patch
    from test_estado_confirmado import CloudFalsa, Equipo
    from atlas_core.escritor_operativo import ErrorEscritorOperativo
    cloud=CloudFalsa(); equipo=Equipo(tmp_path,'casa',cloud)
    dataset=equipo.archivo('operacion/actual/analisis_completo_guias.csv'); source=tmp_path/'fuente.csv'
    fila=row('mobile/abc/original.jpg','484133','0000368927'); put(source,[fila]); put(dataset,[row('otro','1','T1')])
    carpeta=equipo.raiz/'operacion/mobile/envios/abc'; carpeta.mkdir(parents=True)
    (carpeta/'original.jpg').write_bytes(b'original')
    (carpeta/'envio.json').write_text(json.dumps({'envio_id':'abc','foto_original':'original.jpg','imagen_sha256':hashlib.sha256(b'original').hexdigest(),'datos_ocr':{'numero_guia':'484133','numero_transporte':'0000368927'}}),encoding='utf-8')
    falla={'activa':False}
    def json_falla(*args,**kw):
        if falla['activa'] and args[1].endswith('/estado/confirmar'): raise ErrorEscritorOperativo('interrupcion')
        return cloud.json(*args,**kw)
    with patch('atlas_core.escritor_operativo._json',side_effect=json_falla), patch.object(ec.ClienteEstado,'_crudo',lambda c,h,**kw:cloud.crudo(c,h,**kw)):
        with equipo.lease() as lease:
            assert lease.adquirir(); lease.custodia.sembrar(lease)
            args=dict(raiz=equipo.raiz,origen=source,envio_id='abc',guia='484133',transporte='0000368927',lease=lease)
            recuperar_fila(**args); falla['activa']=True
        assert (equipo.local/'pendiente.json').exists()
        falla['activa']=False
        with equipo.lease() as lease:
            assert lease.adquirir(), lease.motivo
            assert lease.custodia.resumen['pendiente_confirmado'] >= 2
            args['lease']=lease
            assert recuperar_fila(**args)['estado']=='YA_PRESENTE'
        assert cloud._vigentes()['operacion/actual/analisis_completo_guias.csv'][0] == ec.sha256_archivo(dataset)
        assert len(_filas(dataset)) == 2
