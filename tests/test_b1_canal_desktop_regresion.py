"""Regresion del canal instalado; solo siete viajes sinteticos locales."""
import csv
import json
import pytest
from atlas_core import desktop_operacion as d
from atlas_core.b1_operador import OperadorB1
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.registro_eventos_operacionales import leer_eventos_operacionales, registrar_evento

ORDEN = "Agrega la observaci\u00f3n ESTE VIAJE TIENE ADICIONAL DE $30.000 POR RETIRO FUERA DE AZA a las gu\u00edas " + ", ".join(str(500001+i) for i in range(7))

@pytest.mark.parametrize("compartido", [False, True])
def test_siete_viajes_por_canal_controlado(tmp_path, compartido):
    actual = tmp_path/'operacion'/'actual'
    actual.mkdir(parents=True)
    (tmp_path/'catalogos_privados').mkdir()
    with (actual/'analisis_completo_guias.csv').open('w', newline='', encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=COLUMNAS,delimiter=';'); w.writeheader()
        for i in range(7):
            fila=dict.fromkeys(COLUMNAS,'')
            fila.update(numero_guia=str(500001+i), numero_transporte=str(900001+(i//2 if compartido else i)), archivo=f'{500001+i}.jpeg')
            w.writerow(fila)
    registrar_evento(raiz=tmp_path,tipo_evento='OBSERVACION_OPERACIONAL',numero_transporte='900001',nota='NOTA ORIGINAL MOBILE',origen='MOBILE')
    fuente=(actual/'analisis_completo_guias.csv').read_bytes()
    b1=OperadorB1(tmp_path)
    assert b1.consultar(ORDEN)['estado']=='RECHAZADA'  # comportamiento instalado anterior
    assert b1.consultar(ORDEN,derivar_operacionales=True)=={'estado':'REQUIERE_OPERADOR'}
    assert b1.consultar('s\u00ed',derivar_operacionales=True)=={'estado':'REQUIERE_OPERADOR'}
    assert b1.consultar('no',derivar_operacionales=True)=={'estado':'REQUIERE_OPERADOR'}
    antes=leer_eventos_operacionales(raiz=tmp_path)
    def turno(texto):
        r=d.ejecutar({'raiz':str(tmp_path),'accion':'script','argumentos':['b1_operador_cli.py','--raiz-atlas',str(tmp_path),'--conversacion','regresion7','--texto',texto]})
        return json.loads(r['salida'])
    assert turno(ORDEN)['estado']=='PREVIEW_PENDIENTE'
    assert leer_eventos_operacionales(raiz=tmp_path)==antes
    assert turno('s\u00ed')['estado']=='EJECUTADA'
    eventos=leer_eventos_operacionales(raiz=tmp_path)['eventos']
    assert len(eventos)==(4 if compartido else 7)
    assert all('ADICIONAL DE $30.000' in e['nota'] for e in eventos)
    assert next(e for e in eventos if e['numero_transporte']=='900001')['nota'].startswith('NOTA ORIGINAL MOBILE\n')
    assert (actual/'analisis_completo_guias.csv').read_bytes()==fuente
    from atlas_core.acciones_operacionales import CapaAccionesOperacionales
    assert len(CapaAccionesOperacionales(tmp_path).auditoria())==1
    assert turno(ORDEN)['estado']=='SIN_CAMBIOS'

def test_lease_cloud_es_el_vigente_y_rechazo_no_escribe(tmp_path,monkeypatch):
    from atlas_core import exclusividad_equipo as ex
    config=tmp_path/'perfil.json'
    config.write_text(json.dumps({'modo_escritor':'lease_cloud','raiz':str(tmp_path),'autorizada':True,'habilitada':True}))
    monkeypatch.setenv('ATLAS_OPERACION_CONFIG',str(config))
    assert ex.politica_equipo_unico(tmp_path) is None
    monkeypatch.setattr(d,'compartida',lambda _:True)
    class Lease:
        vigente=False
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def adquirir(self): return False
    before=list(tmp_path.rglob('*'))
    with pytest.raises(PermissionError,match='Escritor ocupado o exclusividad no verificable'):
        with d.sesion(tmp_path,fabrica=Lease): pytest.fail('No debe escribir')
    assert list(tmp_path.rglob('*'))==before


def test_importe_preserva_simbolo_y_no_admite_comandos():
    from atlas_core.b1_operador import interpretar_determinista, validar_intencion, ErrorContratoInterpretacion
    intent=validar_intencion(interpretar_determinista(ORDEN))
    assert '$30.000' in intent.parametros['texto']
    for texto in ['$(comando)', '$env:secreto', '30.000; comando']:
        with pytest.raises(ErrorContratoInterpretacion):
            validar_intencion(interpretar_determinista('Agrega la observacion '+texto+' a las guias 500001'))


@pytest.mark.parametrize('motivo', ['ocupado', 'HTTP 401', 'red no disponible'])
def test_reproduce_error_exclusividad_cloud_sin_escrituras(tmp_path,monkeypatch,motivo):
    from atlas_core import escritor_operativo as eo
    monkeypatch.setattr(d,'compartida',lambda _:True)
    def api(*args,**kw):
        raise eo.ErrorEscritorOperativo(motivo)
    monkeypatch.setattr(eo,'_json',api)
    lease=eo.LeaseEscritorOperativo(base_url='https://sintetico.invalid',token_motor='test',escritor_id='test',heartbeat_segundos=0)
    with pytest.raises(PermissionError,match='Escritor ocupado o exclusividad no verificable'):
        with d.sesion(tmp_path,fabrica=lambda:lease): pytest.fail('No debe entrar')
    assert not list(tmp_path.iterdir())
