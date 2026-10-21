import json,os,socket,subprocess,sys
from pathlib import Path
import pytest
from atlas_core import exclusividad_equipo as e

pytestmark=pytest.mark.skipif(os.name!='nt',reason='Mutex de Windows')

def test_politica_solo_en_equipo_y_raiz_aprobados(tmp_path,monkeypatch):
    c={'modo_escritor':'equipo_unico','habilitada':True,'autorizada':True,'equipo':socket.gethostname(),'machine_guid':e.identidad_equipo(),'raiz':str(tmp_path)}
    archivo=tmp_path/'politica.json'; archivo.write_text(json.dumps(c)); monkeypatch.setenv('ATLAS_OPERACION_CONFIG',str(archivo))
    assert e.politica_equipo_unico(tmp_path)
    assert e.politica_equipo_unico(tmp_path/'otra') is None
    c['equipo']='OTRO-PC'; archivo.write_text(json.dumps(c))
    with pytest.raises(PermissionError): e.politica_equipo_unico(tmp_path)

def test_mutex_excluye_otro_proceso_y_se_libera(tmp_path):
    codigo='import sys; sys.path.insert(0,sys.argv[1]); from atlas_core.exclusividad_equipo import EscritorEquipoUnico; e=EscritorEquipoUnico(sys.argv[2],verificar=lambda:None); print(int(e.adquirir()),flush=True); e.cerrar()'
    args=[sys.executable,'-I','-B','-c',codigo,str(Path(__file__).resolve().parents[1]),str(tmp_path)]
    with e.EscritorEquipoUnico(tmp_path,verificar=lambda:None) as escritor:
        assert escritor.adquirir()
        assert subprocess.check_output(args,text=True).strip()=='0'
    assert subprocess.check_output(args,text=True).strip()=='1'

def test_pull_activo_impide_adquirir_y_no_crea_datos(tmp_path):
    def ocupado(): raise PermissionError('PULL activo')
    with e.EscritorEquipoUnico(tmp_path,verificar=ocupado) as escritor:
        with pytest.raises(PermissionError,match='PULL activo'): escritor.adquirir()
    assert list(tmp_path.iterdir())==[]

def test_mutex_no_queda_huerfano_si_muere_proceso(tmp_path):
    codigo='import sys,time; sys.path.insert(0,sys.argv[1]); from atlas_core.exclusividad_equipo import EscritorEquipoUnico; e=EscritorEquipoUnico(sys.argv[2],verificar=lambda:None); print(int(e.adquirir()),flush=True); time.sleep(60)'
    p=subprocess.Popen([sys.executable,'-I','-B','-c',codigo,str(Path(__file__).resolve().parents[1]),str(tmp_path)],stdout=subprocess.PIPE,text=True)
    try: assert p.stdout.readline().strip()=='1'
    finally: p.kill(); p.wait(timeout=5)
    with e.EscritorEquipoUnico(tmp_path,verificar=lambda:None) as escritor: assert escritor.adquirir()

def test_recuperacion_solo_pid_muerto_del_mismo_equipo(tmp_path):
    actual=tmp_path/'operacion'/'actual'; actual.mkdir(parents=True)
    p=subprocess.Popen([sys.executable,'-c','pass']); p.wait(timeout=10)
    for nombre,pid,host in [('muerto',p.pid,socket.gethostname()),('vivo',os.getpid(),socket.gethostname()),('remoto',p.pid,'OTRO-PC')]:
        (actual/('.atlas_lock_'+nombre)).write_text(json.dumps({'pid':pid,'host':host}))
    with e.EscritorEquipoUnico(tmp_path,verificar=lambda:None) as escritor:
        with pytest.raises(PermissionError): escritor.recuperar_bloqueos_huerfanos()
        assert escritor.adquirir()
        assert escritor.recuperar_bloqueos_huerfanos()==['.atlas_lock_muerto']
    assert {p.name for p in actual.iterdir()}=={'.atlas_lock_vivo','.atlas_lock_remoto'}
