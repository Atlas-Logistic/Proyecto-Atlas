import json
import pytest
import atlas_core.mobile as m
from atlas_core import registro_eventos_operacionales as reo
from tests.test_mobile_contrato_v2 import operacion, _recibir, _publicar_reporte, _asegurar_transportes
from atlas_core.acciones_operacionales import CapaAccionesOperacionales

NT='0000900001'

def recibir(repo,texto,**extra):
    eid=_recibir(repo,observacion=texto,**extra)
    d=repo.cargar(eid);d.update(estado='ASOCIADO',resultado_asociacion={'estado':'ASOCIADO','numero_transporte':NT});repo.guardar(eid,d)
    return eid

def libre(repo):
    return next(x for x in reo.leer_eventos_operacionales(raiz=repo.raiz_atlas)['eventos'] if x['tipo_evento']=='OBSERVACION_OPERACIONAL')

def test_regresion_pipeline_observacion_sin_incidencia(operacion):
    repo,_=operacion;eid=recibir(repo,'Buenas tarde tiene adisional ese viaje guia 483025.')
    m._sincronizar_contrato_v2(repo,eid,dataset=None)
    assert libre(repo)['nota']=='Buenas tarde tiene adisional ese viaje guia 483025.'
    assert libre(repo)['procedencias'][0]['referencia']=='ENVIO_MOBILE:'+eid
    assert repo.cargar(eid)['tipos_novedad']==[]

def test_acumula_textos_multilinea_y_procedencias_sin_pisar_b1(operacion):
    repo,_=operacion
    reo.registrar_evento(raiz=repo.raiz_atlas,tipo_evento='OBSERVACION_OPERACIONAL',numero_transporte=NT,nota='ADMINISTRACION B1',origen='B1')
    ids=[recibir(repo,'Primer cliente\nReparto'),recibir(repo,'Segundo cliente'),recibir(repo,'Primer cliente\nReparto')]
    originales={i:repo.cargar(i)['observacion'] for i in ids}
    m.registrar_observaciones_canonicas_mobile(repo)
    nota=libre(repo)['nota']
    assert nota.startswith('ADMINISTRACION B1\n')
    assert nota.count('Primer cliente\nReparto')==1 and 'Segundo cliente' in nota
    assert len(libre(repo)['procedencias'])==4
    antes=(repo.raiz_atlas/'operacion/actual/eventos_operacionales.json').read_bytes()
    assert m.registrar_observaciones_canonicas_mobile(repo)==[]
    assert (repo.raiz_atlas/'operacion/actual/eventos_operacionales.json').read_bytes()==antes
    assert {i:repo.cargar(i)['observacion'] for i in ids}==originales

def test_b1_posterior_conserva_observacion_del_chofer(operacion):
    repo,dataset=operacion;_asegurar_transportes(dataset,NT)
    eid=recibir(repo,'Texto ORIGINAL del chofer')
    m.registrar_observaciones_canonicas_mobile(repo)
    c=CapaAccionesOperacionales(repo.raiz_atlas)
    p=c.previsualizar('VIAJE_AGREGAR_OBSERVACION',{'guias':['100001'],'texto':'NOTA ADMINISTRATIVA'},actor='TEST')
    assert p['estado']=='PREVIEW',p
    r=c.ejecutar(p['token'],actor='TEST',confirmado_por='TEST')
    assert r['estado']=='APLICADA',r
    assert libre(repo)['nota']=='Texto ORIGINAL del chofer\nNOTA ADMINISTRATIVA'
    assert repo.cargar(eid)['observacion']=='Texto ORIGINAL del chofer'

@pytest.mark.parametrize('estado,asociacion,reportes,proyecta',[
 ('ASOCIADO',{'estado':'SIN_ASOCIACION','numero_transporte':''},1,True),
 ('REQUIERE_REVISION',{'estado':'SIN_ASOCIACION','numero_transporte':''},1,True),
 ('REQUIERE_REVISION',{'estado':'PROPUESTA_REQUIERE_REVISION','numero_transporte':NT},1,False),
 ('ASOCIADO',{'estado':'SIN_ASOCIACION','numero_transporte':''},0,False),
 ('ASOCIADO',{'estado':'SIN_ASOCIACION','numero_transporte':''},2,False),
 ('REQUIERE_REVISION',{'estado':'ASOCIADO','numero_transporte':'999999'},1,False),
])
def test_misma_prueba_de_vinculo_sin_adivinar(operacion,estado,asociacion,reportes,proyecta):
    repo,_=operacion;eid=recibir(repo,'Texto')
    d=repo.cargar(eid);d.update(estado=estado,resultado_asociacion=asociacion);repo.guardar(eid,d)
    if reportes:_publicar_reporte(repo.raiz_atlas,[(NT,[eid])]+([('0000900002',[eid])] if reportes==2 else []))
    antes=repo.cargar(eid)
    assert bool(m.registrar_observaciones_canonicas_mobile(repo))==proyecta
    if not proyecta:assert repo.cargar(eid)==antes

def test_nota_libre_independiente_de_incidencia_y_su_nota_manual(operacion):
    repo,_=operacion;eid=recibir(repo,'Texto del chofer',tipo_novedad='DEVOLUCION_TOTAL')
    reo.registrar_evento(raiz=repo.raiz_atlas,tipo_evento='DEVOLUCION_TOTAL',numero_transporte=NT,nota='Nota administrativa de devolucion',origen='DESKTOP')
    m.registrar_eventos_canonicos_mobile(repo);m.registrar_observaciones_canonicas_mobile(repo)
    eventos=reo.leer_eventos_operacionales(raiz=repo.raiz_atlas)['eventos']
    assert next(e for e in eventos if e['tipo_evento']=='DEVOLUCION_TOTAL')['nota']=='Nota administrativa de devolucion'
    assert libre(repo)['nota']=='Texto del chofer'

def test_no_reactiva_anulado_ni_proyecta_evidencia_firmada(operacion):
    repo,_=operacion;eid=recibir(repo,'No reaparecer')
    reo.registrar_evento(raiz=repo.raiz_atlas,tipo_evento='OBSERVACION_OPERACIONAL',numero_transporte=NT,nota='Texto anulado',origen='TEST')
    reo.anular_evento(raiz=repo.raiz_atlas,tipo_evento='OBSERVACION_OPERACIONAL',numero_transporte=NT,origen='TEST')
    assert m.registrar_observaciones_canonicas_mobile(repo)==[]
    assert libre(repo)['estado']=='ANULADO'
    d=repo.cargar(eid);d['rol_documento']='EVIDENCIA_FIRMADA';repo.guardar(eid,d)
    assert m.registrar_observaciones_canonicas_mobile(repo)==[]

def test_fallo_entre_evento_y_marca_reintenta_sin_duplicar(operacion,monkeypatch):
    repo,_=operacion;eid=recibir(repo,'Un solo texto')
    guardar=repo.guardar
    def falla(*a,**k):raise OSError('simulado')
    monkeypatch.setattr(repo,'guardar',falla)
    with pytest.raises(OSError):m.registrar_observaciones_canonicas_mobile(repo)
    monkeypatch.setattr(repo,'guardar',guardar)
    m.registrar_observaciones_canonicas_mobile(repo)
    assert libre(repo)['nota']=='Un solo texto'
    assert len(libre(repo)['procedencias'])==1

def test_alcance_explicito_de_recuperacion(operacion):
    repo,_=operacion;uno=recibir(repo,'Autorizado');otro=recibir(repo,'Fuera del alcance')
    previo=repo.cargar(otro)
    m.registrar_observaciones_canonicas_mobile(repo,envios_objetivo={uno})
    assert libre(repo)['nota']=='Autorizado'
    assert repo.cargar(otro)==previo
