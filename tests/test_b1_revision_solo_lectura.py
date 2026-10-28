import json
import pytest
from atlas_core.b1_operador import OperadorB1, interpretar_determinista
from tests.test_acciones_operacionales import entorno

PREGUNTA = ('Consulta la revisi\u00f3n de la gu\u00eda 500001. Muestra el cliente, obra, direcci\u00f3n documental, '
            'destino registrado y motivo de la revisi\u00f3n. Comprueba si corresponde a una obra duplicada de otra ya '
            'confirmada. Explica la evidencia y propone la acci\u00f3n disponible, sin aplicar cambios ni confirmar el destino.')

def huellas(raiz):
    return {str(p.relative_to(raiz)):p.read_bytes() for p in raiz.rglob('*') if p.is_file()}

def test_regresion_routing():
    r=interpretar_determinista(PREGUNTA)
    assert r.accion=='DECISION_CONSULTAR'
    assert r.parametros=={'numero_guia':'500001'}

@pytest.mark.parametrize('cantidad',[0,1,2])
def test_revisiones_lectoras_sin_tokens_ni_mutaciones(entorno,cantidad,monkeypatch):
    ruta=entorno['actual']/'decisiones_pendientes.json'
    contenido=json.loads(ruta.read_text(encoding='utf-8-sig'))
    decisiones=[dict(entorno['decision'],decision_id='d'+str(i)) for i in range(cantidad)]
    contenido['decisiones']=decisiones+[dict(entorno['decision'],decision_id='ajena',documento={'numero_guia':'999999'})]
    ruta.write_text(json.dumps(contenido),encoding='utf-8')
    b1=OperadorB1(entorno['raiz'])
    monkeypatch.setattr(b1.capa,'_planificar',lambda *a,**k:pytest.fail('No crear planes operacionales'))
    monkeypatch.setattr(b1.capa,'_construir_preview',lambda *a,**k:pytest.fail('No crear preview/token'))
    monkeypatch.setattr(b1.capa,'ejecutar',lambda *a,**k:pytest.fail('No ejecutar'))
    antes=huellas(entorno['raiz'])
    respuesta=b1.atender('lectura',PREGUNTA)
    assert respuesta['estado']=='RESULTADO_LECTURA'
    assert respuesta['accion']=='DECISION_CONSULTAR'
    assert respuesta['resultado']['total']==cantidad
    assert len(respuesta['resultado']['decisiones'])==cantidad
    assert 'preview' not in respuesta and 'token' not in respuesta
    assert b1.pendiente('lectura') is None
    assert 'no demuestra' in respuesta['mensaje'] or 'ni demuestra' in respuesta['mensaje']
    assert 'No puedo proponer' in respuesta['mensaje']
    assert huellas(entorno['raiz'])==antes
    if cantidad:
        assert 'OBRA_NO_EXISTE_PARA_CLIENTE' in repr(respuesta['tablas'])
        assert 'REGISTRAR' in repr(respuesta['tablas'])


def test_evidencia_incompleta_no_inventa(entorno):
    ruta=entorno['actual']/'decisiones_pendientes.json'
    ruta.write_text(json.dumps({'decisiones':[{'decision_id':'d','tipo':'DESTINO_SIN_CONFIRMAR',
        'documento':{'numero_guia':'500001'}}]}),encoding='utf-8')
    b1=OperadorB1(entorno['raiz'])
    antes=huellas(entorno['raiz'])
    r=b1.consultar(PREGUNTA)
    assert r['estado']=='RESULTADO_LECTURA'
    assert 'No disponible' in repr(r['tablas'])
    assert 'Ninguna disponible' in repr(r['tablas'])
    assert 'no compara obras' in r['mensaje']
    assert huellas(entorno['raiz'])==antes


def test_modificacion_explicita_conservada():
    assert interpretar_determinista('corrige la obra de la guia 500001 a Obra Norte').accion=='DOCUMENTO_ASIGNAR_OBRA'
    assert interpretar_determinista('el destino de la guia 500001 es Calle Uno 123').accion=='DOCUMENTO_CORREGIR_DESTINO_OPERACIONAL'
    assert interpretar_determinista('cuales guias estan pendientes de revision') is None


def test_vinculos_catalogo_existentes_sin_analisis_duplicacion(entorno):
    from tests.test_b1_operador_obra import _obra
    nombre='OBRA VIEJA'
    (entorno['cat']/'obras_destinos.json').write_text(json.dumps({
        'version_formato':1,'obras':[_obra('obra1',nombre,entorno['cliente'].cliente_id)],'relaciones':[]}),encoding='utf-8')
    decision=dict(entorno['decision'],contexto={'obra_canonica':nombre,'cliente_canonico':'CLIENTE UNO SA'})
    (entorno['actual']/'decisiones_pendientes.json').write_text(json.dumps({'decisiones':[decision]}),encoding='utf-8')
    antes=huellas(entorno['raiz'])
    r=OperadorB1(entorno['raiz']).consultar(PREGUNTA)
    assert r['resultado']['decisiones'][0]['obras_vinculadas'][0]['obra_id']=='obra1'
    assert 'OBRA VIEJA (OBSERVADA)' in repr(r['tablas'])
    assert huellas(entorno['raiz'])==antes
