"""Ingreso real con OCR simulado y batería/bandeja reales sobre raíz sintética."""
import json

import pytest
from atlas_core import mobile
from atlas_core.alcance_revalidacion import alcance_guias, guias_en_alcance
from atlas_core.decisiones_pendientes import generar_artefacto
from atlas_core.revalidacion_documental import _leer_filas, _escribir_filas_completas
from tests.test_decision_alcance_focal_p0 import preparar


@pytest.fixture
def escenario(tmp_path, monkeypatch):
    monkeypatch.setenv('ATLAS_IA_B1_OPERACIONAL', '0')
    raiz, actual, _, ajenas = preparar(tmp_path)
    dataset = actual/'analisis_completo_guias.csv'
    filas = _leer_filas(dataset)
    ajena = next(f for f in filas if f['numero_guia']=='482188')
    ajena.update(despachar_a_crudo='HOLANDA 2040 PROVIDENCIA',
        direccion_entrega='Avenida Nueva Providencia 2040', localidad_entrega='Providencia',
        region_entrega='Metropolitana', distancia_km='25.192700000000002',
        duracion_min='33.486666666666665', proveedor_ruta='openrouteservice',
        estado_ruta='RUTA_CALCULADA', motivo_ruta='',codigo_pais='CL',codigo_unidad='13123',codigo_contexto='13')
    _escribir_filas_completas(dataset,filas)
    repo=mobile.RepositorioEnviosMobile(raiz)
    id='nuevo-ingreso-causal'
    repo.recibir(envio_id=id,imagen=b'foto-sintetica',mime='image/jpeg',metadata={'chofer_id':'TEST','planta_origen_informada':'AZA_COLINA'})
    nuevos=dict(archivo=f'mobile/{id}/original.jpg',numero_guia='900001',numero_transporte='0000990001',
        cliente=ajena['cliente'],obra_destino=ajena['obra_destino'],
        estado_procesamiento='OK',indicador_revision='OK',estado_documental='OK',estado_operacional='OK',
        motivos_revision_documento='',estado_ruta='SIN_CREDENCIAL',motivo_ruta='SIN_CREDENCIAL')
    monkeypatch.setattr(mobile,'procesar_archivo',lambda *a,**kw:dict(nuevos))
    # No proveedor OCR ni HTTP real: ni el propio documento ni otros pueden inferirse de nuevo.
    monkeypatch.setattr(mobile,'crear_proveedor_ocr',lambda *a,**kw:object())
    return raiz,actual,dataset,repo,id,filas


@pytest.mark.parametrize('diferir',[False,True])
@pytest.mark.parametrize('con_tarjetas',[False,True])
def test_ingreso_preserva_482188_campos_tarjetas_ledger_y_ajenas(escenario,diferir,con_tarjetas):
    raiz,actual,dataset,repo,id,antes=escenario
    if not con_tarjetas:
        generar_artefacto(ruta_dataset=dataset,carpeta_catalogos=raiz/'catalogos_privados',decisiones=[])
    tarjetas=json.loads((actual/'decisiones_pendientes.json').read_text())['decisiones']
    ledger=actual/'decisiones_aplicadas.json'
    ledger.write_text(json.dumps({'aplicaciones':[{'decision_id':'confirmacion-ajena','accion':'CONFIRMAR','actor':'HUMANO'}]}))
    ledger_antes=ledger.read_bytes()
    catalogos={p.name:p.read_bytes() for p in (raiz/'catalogos_privados').glob('*.json')}
    salida=mobile.procesar_y_revalidar_envio_mobile(repo,id,dataset=dataset,
        carpeta_catalogos=raiz/'catalogos_privados',diferir_reconciliacion_bandeja=diferir)
    assert salida=={'procesamiento_ok':True,'reconciliacion_ok':True}
    if diferir:
        resultado=mobile.reconciliar_bandeja_diferida_mobile(repo,raiz_atlas=raiz)
        assert resultado['ejecutada'] and resultado['completados']==[id]
    despues=_leer_filas(dataset)
    assert next(f for f in despues if f['numero_guia']=='482188') == next(f for f in antes if f['numero_guia']=='482188')
    assert despues[:len(antes)]==antes
    assert len(despues)==len(antes)+1
    publicadas=json.loads((actual/'decisiones_pendientes.json').read_text())['decisiones']
    assert [d for d in publicadas if d['documento']['numero_guia']!='900001']==tarjetas
    assert ledger.read_bytes()==ledger_antes
    assert {p.name:p.read_bytes() for p in (raiz/'catalogos_privados').glob('*.json')}==catalogos
    estado=json.loads((actual/'estado_operacion.json').read_text())
    assert id in (raiz/estado['reporte_vigente']/'viajes.csv').read_text(encoding='utf-8-sig')


def _registro(repo,id,guia,transporte,*,lote='',**extra):
    repo.recibir(envio_id=id,imagen=b'foto',mime='image/jpeg',metadata={'chofer_id':'c','lote_id':lote,'planta_origen_informada':'AZA_COLINA'})
    r=repo.cargar(id);r.update(estado='REQUIERE_REVISION',datos_ocr={'numero_guia':guia,'numero_transporte':transporte},
        resultado_asociacion={'estado':'SIN_ASOCIACION'},**extra);repo.guardar(id,r)
    return r


def test_asociacion_lote_transitiva_converge_hermanas_sin_escribir_ajena(escenario):
    raiz,actual,dataset,repo,_,filas=escenario
    lider=_registro(repo,'lider-envio','910001','0000990099',lote='lote-explicito')
    _registro(repo,'hermana-envio','910002','No encontrado',lote='lote-explicito')
    ajena=_registro(repo,'ajena-envio','482188','No encontrado')
    filas += [dict(filas[0],archivo='desktop/test.jpg',numero_guia='910000',numero_transporte='0000990099'),
              dict(filas[0],archivo='mobile/lider-envio/original.jpg',numero_guia='910001',numero_transporte='0000990099'),
              dict(filas[0],archivo='mobile/hermana-envio/original.jpg',numero_guia='910002',numero_transporte='No encontrado')]
    _escribir_filas_completas(dataset,filas)
    ruta_ajena=repo.raiz/'ajena-envio/envio.json';bytes_antes=ruta_ajena.read_bytes()
    mobile._revalidar_asociacion_diagnosticable(repo,'lider-envio',dataset=dataset)
    assert repo.cargar('lider-envio')['resultado_asociacion']['numero_transporte']=='0000990099'
    assert repo.cargar('hermana-envio')['resultado_asociacion']['numero_transporte']=='0000990099'
    assert next(f for f in _leer_filas(dataset) if f['numero_guia']=='910002')['numero_transporte']=='0000990099'
    assert ruta_ajena.read_bytes()==bytes_antes
    guias,envios=mobile._alcance_causal_mobile(repo,{'lider-envio'},dataset)
    assert {'910000','910001','910002'} <= guias
    assert '482188' not in guias and 'ajena-envio' not in envios


def test_mismo_transporte_conserva_convergencia_real_de_hermana(escenario):
    raiz,actual,dataset,repo,id,filas=escenario
    # Una hermana del viaje nuevo necesita converger su estado documental.
    hermana=dict(filas[0],archivo='desktop/hermana.jpg',numero_guia='900002',numero_transporte='0000990001',
        indicador_revision='REVISAR',estado_documental='REQUIERE_REVISION',estado_operacional='REQUIERE_REVISION',
        motivos_revision_documento='',obra_destino='',cliente='',estado_ruta='SIN_CREDENCIAL',motivo_ruta='SIN_CREDENCIAL')
    _escribir_filas_completas(dataset,filas+[hermana])
    mobile.procesar_y_revalidar_envio_mobile(repo,id,dataset=dataset,carpeta_catalogos=raiz/'catalogos_privados',diferir_reconciliacion_bandeja=True)
    despues=_leer_filas(dataset)
    assert despues[:len(filas)]==filas
    actual_hermana=next(f for f in despues if f['numero_guia']=='900002')
    assert actual_hermana['estado_documental']=='OK'


def test_sin_guia_no_convierte_vacio_en_global_y_union_diferida_es_focal(escenario):
    raiz,actual,dataset,repo,id,_=escenario
    r=repo.cargar(id);r['reconciliacion_bandeja']=mobile._solicitud_reconciliacion_bandeja(r);repo.guardar(id,r)
    llamadas=[]
    resultado=mobile.reconciliar_bandeja_diferida_mobile(repo,raiz_atlas=raiz,
        reconciliador=lambda **kw:llamadas.append(kw))
    assert llamadas[0]['guias_objetivo']==set()
    assert resultado['completados']==[id]


def test_reenvio_canonico_evidencia_y_placeholders_no_amplian_a_otro_viaje(escenario):
    raiz,actual,dataset,repo,_,filas=escenario
    _registro(repo,'reenvio-envio','','No encontrado',relectura_documento={'archivo_canonico':filas[0]['archivo']})
    _registro(repo,'firmada-envio','','No encontrado',evidencia_de_envio_id='reenvio-envio')
    _registro(repo,'sin-relacion','','No encontrado')
    guias,envios=mobile._alcance_causal_mobile(repo,{'firmada-envio'},dataset)
    assert filas[0]['numero_guia'] in guias
    assert {'reenvio-envio','firmada-envio'} <= envios and 'sin-relacion' not in envios
    assert '482188' not in guias


def test_union_diferida_solo_pendientes_y_no_toda_la_operacion(escenario):
    raiz,actual,dataset,repo,_,_=escenario
    for id,guia,t in [('pendiente-uno','920001','0000990201'),('pendiente-dos','920002','0000990202'),('ajena-sin-pendiente','482188','0000360002')]:
        r=_registro(repo,id,guia,t)
        if id.startswith('pendiente'):
            r['reconciliacion_bandeja']=mobile._solicitud_reconciliacion_bandeja(r);repo.guardar(id,r)
    llamadas=[]
    resultado=mobile.reconciliar_bandeja_diferida_mobile(repo,raiz_atlas=raiz,reconciliador=lambda **kw:llamadas.append(kw))
    assert llamadas[0]['guias_objetivo']=={'920001','920002'}
    assert set(resultado['completados'])=={'pendiente-uno','pendiente-dos'}


def test_identidad_canonica_prevalece_sobre_ocr_historico_de_reenvio(escenario):
    raiz,actual,dataset,repo,_,filas=escenario
    _registro(repo,'canonico-reenvio','482188','0000360002',relectura_documento={'archivo_canonico':filas[0]['archivo']})
    guias,envios=mobile._alcance_causal_mobile(repo,{'canonico-reenvio'},dataset)
    assert filas[0]['numero_guia'] in guias and '482188' not in guias


def test_tarjetas_de_reenvio_canonico_preservan_decisiones_ajenas(escenario):
    raiz,actual,dataset,repo,id,filas=escenario
    ruta=actual/'decisiones_pendientes.json'
    antes=json.loads(ruta.read_text())['decisiones']
    ajenas=[d for d in antes if d['documento']['numero_guia'] != filas[0]['numero_guia']]
    mobile._regenerar_decisiones_de_documento(dataset,archivo=filas[0]['archivo'],carpeta_catalogos=raiz/'catalogos_privados')
    despues=json.loads(ruta.read_text())['decisiones']
    assert [d for d in despues if d['documento']['numero_guia'] != filas[0]['numero_guia']]==ajenas


@pytest.mark.parametrize('diferir',[False,True])
def test_todas_las_entradas_de_ingreso_reciben_alcance_focal(escenario,monkeypatch,diferir):
    from atlas_core import revalidacion_documental as revision
    raiz,actual,dataset,repo,id,_=escenario
    reporte=revision.revalidar_y_regenerar_reporte
    bandeja=revision.reconciliar_bandeja_decisiones
    publicar=mobile.regenerar_decisiones_persistidas
    observadas=[]
    def reporte_focal(**kw):
        assert kw['guias_objetivo'] is not None and '482188' not in kw['guias_objetivo']
        observadas.append('reporte')
        return reporte(**kw)
    def bandeja_focal(**kw):
        alcance=kw.get('guias_objetivo')
        if alcance is None:
            alcance=guias_en_alcance(dataset)
        assert alcance is not None and '482188' not in alcance
        assert guias_en_alcance(dataset) is not None  # tambien limita aplicaciones automaticas anidadas
        observadas.append('bandeja')
        return bandeja(**kw)
    def publicar_focal(**kw):
        assert guias_en_alcance(dataset) is not None
        observadas.append('publicar')
        return publicar(**kw)
    monkeypatch.setattr(revision,'revalidar_y_regenerar_reporte',reporte_focal)
    monkeypatch.setattr(revision,'reconciliar_bandeja_decisiones',bandeja_focal)
    monkeypatch.setattr(mobile,'regenerar_decisiones_persistidas',publicar_focal)
    mobile.procesar_y_revalidar_envio_mobile(repo,id,dataset=dataset,carpeta_catalogos=raiz/'catalogos_privados',diferir_reconciliacion_bandeja=diferir)
    if diferir:
        mobile.reconciliar_bandeja_diferida_mobile(repo,raiz_atlas=raiz)
    assert {'reporte','bandeja','publicar'} <= set(observadas)


def test_contexto_causal_heredado_no_se_amplia_con_hermanas(escenario):
    raiz,actual,dataset,repo,_,filas=escenario
    _registro(repo,'hermana-a','482553','0000365008')
    _registro(repo,'hermana-b','482554','0000365008')
    with alcance_guias(dataset,{'482553'}):
        guias,envios=mobile._alcance_causal_mobile(repo,{'hermana-a'},dataset)
        assert guias=={'482553'} and 'hermana-b' not in envios


def test_tanda_multiviaje_no_revalida_otro_transporte_ya_identificado(escenario):
    raiz,actual,dataset,repo,id,antes=escenario
    r=repo.cargar(id);r['lote_id']='lote-entre-viajes';repo.guardar(id,r)
    _registro(repo,'otro-viaje-identificado','482188','0000360002',lote='lote-entre-viajes')
    ajena=repo.raiz/'otro-viaje-identificado/envio.json';bytes_antes=ajena.read_bytes()
    mobile.procesar_y_revalidar_envio_mobile(repo,id,dataset=dataset,carpeta_catalogos=raiz/'catalogos_privados',diferir_reconciliacion_bandeja=True)
    guias,envios=mobile._alcance_causal_mobile(repo,{id},dataset)
    assert '482188' not in guias and 'otro-viaje-identificado' not in envios
    assert _leer_filas(dataset)[:len(antes)]==antes
    assert ajena.read_bytes()==bytes_antes


@pytest.mark.parametrize('diferir',[False,True])
def test_auto_resolucion_anidada_no_amplia_a_otro_viaje_por_patente(tmp_path,monkeypatch,diferir):
    from tests.test_mobile_guias_v1 import (_recibir,_dataset_con_fila,_catalogos_para_patente_mobile,
        _asignar_tracto,_procesador_con_tarjeta_patente)
    from atlas_core.decisiones_pendientes import crear_decision
    monkeypatch.setenv('ATLAS_IA_B1_OPERACIONAL','0')
    repo,id=_recibir(tmp_path)
    dataset=tmp_path/'operacion/actual/analisis_completo_guias.csv'
    _dataset_con_fila(dataset,dict(archivo='ajena.jpg',numero_guia='888888',numero_transporte='0000888888',
        patente_tracto='1G8925',rut_chofer='18.091.588-5',indicador_revision='REVISAR',
        motivos_revision_documento='PATENTE_SIN_HOMOLOGAR',estado_procesamiento='OK'))
    antes=_leer_filas(dataset)[0]
    catalogos=tmp_path/'catalogos_privados'
    _catalogos_para_patente_mobile(catalogos)
    _asignar_tracto(catalogos,'TG8925','18.091.588-5')
    tarjeta=crear_decision(tipo='VEHICULO_DESCONOCIDO',entidad='VEHICULO',archivo='ajena.jpg',
        numero_guia='888888',numero_transporte='0000888888',campo='patente_tracto',valor_documental='1G8925',
        valor_normalizado='1G8925',identidad_resuelta=None,candidatos=(),motivos=('REVISION_AJENA',),
        evidencias=(),acciones_permitidas=('REGISTRAR','NO_REGISTRAR','POSPONER'),contexto={'nota':'conservar'})
    generar_artefacto(ruta_dataset=dataset,carpeta_catalogos=catalogos,decisiones=[tarjeta])
    _procesador_con_tarjeta_patente(monkeypatch,guia='475252',transporte='0000362011',patente_ocr='1G8925',rut='18.091.588-5')
    mobile.procesar_envio_mobile(repo,id,dataset=dataset,carpeta_catalogos=catalogos,diferir_reconciliacion_bandeja=diferir)
    if diferir:
        mobile.reconciliar_bandeja_diferida_mobile(repo,raiz_atlas=tmp_path)
    despues=_leer_filas(dataset)
    assert despues[0]==antes
    assert len([f for f in despues if f['numero_guia']=='475252'])==1
    tarjetas=json.loads((dataset.parent/'decisiones_pendientes.json').read_text())['decisiones']
    assert next(d for d in tarjetas if d['documento']['numero_guia']=='888888')==tarjeta
    assert not any(d['documento']['numero_guia']=='475252' for d in tarjetas)
    ledger=json.loads((dataset.parent/'decisiones_aplicadas.json').read_text())
    assert {a['documento']['numero_guia'] for a in ledger['aplicaciones']}=={'475252'}
