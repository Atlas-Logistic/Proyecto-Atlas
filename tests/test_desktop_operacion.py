import pytest
from atlas_core import desktop_operacion as d

class Lease:
    vigente=True
    def __init__(self,adquiere=True): self.adquiere=adquiere; self.cerrado=False
    def __enter__(self): return self
    def __exit__(self,*args): self.cerrado=True
    def adquirir(self): return self.adquiere
    def renovar(self): return self.vigente

@pytest.mark.parametrize('lease',[None,Lease(False)])
def test_sin_credencial_o_escritor_ocupado_no_escribe(tmp_path,monkeypatch,lease):
    monkeypatch.setattr(d,'compartida',lambda _:True)
    with pytest.raises(PermissionError):
        with d.sesion(tmp_path,fabrica=lambda:lease): pytest.fail('No debe entrar')
    assert list(tmp_path.iterdir()) == []

def test_lease_abarca_escrituras_y_se_libera(tmp_path,monkeypatch):
    monkeypatch.setattr(d,'compartida',lambda _:True)
    lease=Lease()
    with d.sesion(tmp_path,fabrica=lambda:lease) as comprobar:
        comprobar(); (tmp_path/'sintetico.json').write_text('{}')
        assert not lease.cerrado
        lease.vigente=False
        with pytest.raises(PermissionError): (tmp_path/'no_debe_existir').write_text('x')
    assert lease.cerrado
    assert not (tmp_path/'no_debe_existir').exists()

def test_raiz_local_independiente_pull_y_lock_entre_procesos(tmp_path):
    from atlas_core.almacenamiento_portable import SesionOcupadaError
    def prohibido(): pytest.fail('No requiere red ni PULL para raíz local')
    with d.sesion(tmp_path,fabrica=prohibido):
        with pytest.raises(SesionOcupadaError):
            with d.sesion(tmp_path,fabrica=prohibido): pass

def test_no_se_puede_ejecutar_pull_ni_script_arbitrario(tmp_path):
    for script in ['sincronizar_mobile_cloud.py','../inventado.py']:
        with pytest.raises(PermissionError):
            d.ejecutar({'raiz':str(tmp_path),'accion':'script','argumentos':[script]})
    assert list(tmp_path.iterdir()) == []

def test_escritura_de_script_fuera_raiz_se_deniega(tmp_path,monkeypatch):
    # temp es una raíz permitida por necesidad de las bibliotecas. Sustituir
    # el directorio temporal por uno propio permite probar el límite.
    temporal=tmp_path/'temp'; temporal.mkdir()
    raiz=tmp_path/'datos'; raiz.mkdir()
    monkeypatch.setattr(d.tempfile,'gettempdir',lambda:str(temporal))
    with d.sesion(raiz):
        with pytest.raises(PermissionError): (tmp_path/'fuera.json').write_text('x')

def test_nombres_repetidos_se_rechazan_antes_de_copiar(tmp_path):
    a=tmp_path/'a'; b=tmp_path/'b'; a.mkdir(); b.mkdir()
    (a/'guia.pdf').write_bytes(b'%PDF'); (b/'guia.pdf').write_bytes(b'%PDF-otro')
    with pytest.raises(ValueError,match='mismo nombre'):
        d.ingresar(tmp_path,[a/'guia.pdf',b/'guia.pdf'],lambda:None)
    assert not (tmp_path/'operacion').exists()

def test_guia_existente_por_numero_no_se_copia_ni_reprocesa(tmp_path,monkeypatch):
    import csv
    monkeypatch.setattr('atlas_core.fuente_catalogos.validar_fuente_catalogos',lambda *a,**kw:None)
    actual=tmp_path/'operacion'/'actual'; actual.mkdir(parents=True)
    with (actual/'analisis_completo_guias.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=['numero_guia','numero_transporte'],delimiter=';'); w.writeheader(); w.writerow({'numero_guia':'482553','numero_transporte':'T1'})
    original=tmp_path/'482553.jpeg'; original.write_bytes(b'original inalterado')
    r=d.ingresar(tmp_path,[original],lambda:None)
    assert r['cantidad']==0 and r['existentes'][0]['numero_guia']=='482553'
    assert not (tmp_path/'operacion'/'entradas').exists()
    assert original.read_bytes()==b'original inalterado'

class LeaseOcupado(Lease):
    """Ocupado por otro titular (409) durante `ocupado_intentos` intentos."""
    def __init__(self,ocupado_intentos,ocupado=True):
        super().__init__(); self.pendientes=ocupado_intentos; self.marca=ocupado; self.intentos=0; self.ocupado=False
    def adquirir(self):
        self.intentos+=1
        if self.pendientes: self.pendientes-=1; self.ocupado=self.marca; return False
        self.ocupado=False; return True

def _reloj_simulado(monkeypatch):
    ahora=[0.0]
    monkeypatch.setattr(d,'_reloj',lambda:ahora[0])
    monkeypatch.setattr(d,'_dormir',lambda s:ahora.__setitem__(0,ahora[0]+s))
    return ahora

def test_escritor_ocupado_por_pull_espera_y_luego_escribe(tmp_path,monkeypatch):
    monkeypatch.setattr(d,'compartida',lambda _:True); ahora=_reloj_simulado(monkeypatch)
    lease=LeaseOcupado(7)  # ~35 s de un ciclo PULL
    with d.sesion(tmp_path,fabrica=lambda:lease) as comprobar:
        comprobar(); (tmp_path/'sintetico.json').write_text('{}')
    assert lease.intentos==8 and ahora[0]==35 and lease.cerrado

def test_escritor_ocupado_mas_alla_de_la_espera_no_escribe(tmp_path,monkeypatch):
    monkeypatch.setattr(d,'compartida',lambda _:True); ahora=_reloj_simulado(monkeypatch)
    lease=LeaseOcupado(10**6)
    with pytest.raises(PermissionError,match='Escritor ocupado por otro proceso Atlas'):
        with d.sesion(tmp_path,fabrica=lambda:lease): pytest.fail('No debe entrar')
    assert ahora[0]==d.ESPERA_ESCRITOR_OCUPADO_SEGUNDOS and list(tmp_path.iterdir())==[]

def test_exclusividad_no_verificable_no_se_reintenta(tmp_path,monkeypatch):
    monkeypatch.setattr(d,'compartida',lambda _:True); ahora=_reloj_simulado(monkeypatch)
    lease=LeaseOcupado(10**6,ocupado=False)  # Cloud caído o credencial inválida
    with pytest.raises(PermissionError,match='exclusividad no verificable'):
        with d.sesion(tmp_path,fabrica=lambda:lease): pytest.fail('No debe entrar')
    assert lease.intentos==1 and ahora[0]==0 and list(tmp_path.iterdir())==[]
