import hashlib, json
import pytest
from atlas_core.revision_mobile import registrar

def test_descarte_persistencia_reversion(tmp_path):
    eid='envio-1'; imagen=b'original sintetico'; sha=hashlib.sha256(imagen).hexdigest()
    d=tmp_path/'operacion'/'mobile'/'envios'/eid; d.mkdir(parents=True)
    (d/'original.jpg').write_bytes(imagen)
    envio={'envio_id':eid,'estado':'REQUIERE_REVISION','foto_original':'original.jpg','imagen_sha256':sha,'rol_documento':'GUIA','datos_ocr':{'numero_guia':'No encontrado'}}
    ruta=d/'envio.json'; ruta.write_text(json.dumps(envio),encoding='utf8'); antes=ruta.read_bytes()
    registrar(tmp_path,eid,sha,'DESCARTAR','Supervisor')
    ledger=tmp_path/'operacion'/'actual'/'revision_mobile'/(eid+'.json')
    assert json.loads(ledger.read_text(encoding='utf8'))['eventos'][-1]['accion']=='DESCARTAR'
    # Reescritura/revalidación del envío no toca la decisión.
    ruta.write_bytes(antes)
    assert json.loads(ledger.read_text(encoding='utf8'))['eventos'][-1]['accion']=='DESCARTAR'
    registrar(tmp_path,eid,sha,'REVERTIR','Supervisor')
    assert [x['accion'] for x in json.loads(ledger.read_text(encoding='utf8'))['eventos']]==['DESCARTAR','REVERTIR']
    assert ruta.read_bytes()==antes and (d/'original.jpg').read_bytes()==imagen
    with pytest.raises(ValueError): registrar(tmp_path,eid,sha,'REVERTIR','Supervisor')
    with pytest.raises(ValueError): registrar(tmp_path,eid,'0'*64,'DESCARTAR','Supervisor')
    with pytest.raises(ValueError): registrar(tmp_path,eid,sha,'DESCARTAR',' ')

def test_canal_oficial_escribe_y_revierte(tmp_path):
    from atlas_core.desktop_operacion import ejecutar
    eid='envio-2'; imagen=b'original'; sha=hashlib.sha256(imagen).hexdigest()
    d=tmp_path/'operacion'/'mobile'/'envios'/eid; d.mkdir(parents=True)
    (d/'original.jpg').write_bytes(imagen)
    (d/'envio.json').write_text(json.dumps({'envio_id':eid,'estado':'REQUIERE_REVISION','foto_original':'original.jpg','imagen_sha256':sha}),encoding='utf8')
    def acc(accion):
        r=ejecutar({'raiz':str(tmp_path),'accion':'script','argumentos':['revision_mobile_cli.py','--raiz-atlas',str(tmp_path),'--envio-id',eid,'--sha256',sha,'--accion',accion,'--supervisor','Supervisor']})
        assert json.loads(r['salida'])['ok']
    acc('DESCARTAR'); acc('REVERTIR')
    registro=json.loads((tmp_path/'operacion'/'actual'/'revision_mobile'/(eid+'.json')).read_text(encoding='utf8'))
    assert [e['accion'] for e in registro['eventos']]==['DESCARTAR','REVERTIR']
