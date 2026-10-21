import csv,json
import pytest
from pathlib import Path
from test_aplicacion_decisiones_r33 import _entorno
from atlas_core.decisiones_pendientes import crear_decision,generar_artefacto
from atlas_core.aplicacion_decisiones import aplicar_decision_obra
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import _leer_filas,_escribir_filas_completas,revalidar_y_regenerar_reporte
from atlas_core.alcance_revalidacion import alcance_guias,calcular_guias_afectadas


def preparar(tmp_path):
    raiz,catalogos,actual,cliente,_=_entorno(tmp_path)
    dataset=actual/'analisis_completo_guias.csv'
    base=_leer_filas(dataset)[0]
    objetivo={**base,'archivo':'482553.jpeg','numero_guia':'482553','numero_transporte':'0000365008'}
    hermana={**objetivo,'archivo':'482554.jpeg','numero_guia':'482554','obra_destino':'OTRA OBRA DEL VIAJE'}
    obra={**objetivo,'archivo':'482555.jpeg','numero_guia':'482555','numero_transporte':'0000360003'}
    sigro={**base,'archivo':'482673.jpeg','numero_guia':'482673','numero_transporte':'0000360001',
           'cliente':'SIGRO','obra_destino':'OBRA SIGRO','direccion_entrega':'Irarrázaval 5497',
           'localidad_entrega':'Ñuñoa','estado_ruta':'RUTA_CALCULADA','distancia_km':'12.35',
           'duracion_min':'40','indicador_revision':'OK','estado_documental':'OK','estado_operacional':'OK',
           'motivos_revision_documento':'','descripcion_material':'SIN DATO'}
    oko={**sigro,'archivo':'482188.jpeg','numero_guia':'482188','numero_transporte':'0000360002',
         'cliente':'OKO CONSTRUCTORA','obra_destino':'OBRA OKO','direccion_entrega':'DESTINO PREVIAMENTE ASOCIADO',
         'motivos_revision_documento':'MOTIVO_AJENO_CONSERVADO','observacion':'no se debe revisar'}
    oko.pop('observacion')
    filas=[objetivo,hermana,obra,sigro,oko]
    _escribir_filas_completas(dataset,filas)
    decision=crear_decision(tipo='OBRA_DESCONOCIDA',entidad='OBRA',archivo='482553.jpeg',numero_guia='482553',
        numero_transporte='0000365008',campo='obra_destino',valor_documental='OBRA NUEVA',valor_normalizado='OBRA NUEVA',
        identidad_resuelta=None,candidatos=(),motivos=('OBRA_NO_EXISTE_PARA_CLIENTE',),
        evidencias=({'tipo':'CLIENTE_RESUELTO','entidad_id':cliente.cliente_id},),
        acciones_permitidas=('REGISTRAR','NO_REGISTRAR','POSPONER'),
        contexto={'cliente_id':cliente.cliente_id,'cliente_canonico':cliente.razon_social})
    ajenas=[]
    for fila in [sigro,oko]:
        ajenas.append(crear_decision(tipo='DESTINO_NO_RESUELTO',entidad='DESTINO',archivo=fila['archivo'],
            numero_guia=fila['numero_guia'],numero_transporte=fila['numero_transporte'],campo='direccion_entrega',
            valor_documental=fila['direccion_entrega'],valor_normalizado=fila['direccion_entrega'],identidad_resuelta=None,
            candidatos=(),motivos=('REVISION_AJENA',),evidencias=(),acciones_permitidas=('REGISTRAR_DIRECCION','POSPONER'),contexto={}))
    generar_artefacto(ruta_dataset=dataset,carpeta_catalogos=catalogos,decisiones=[decision,*ajenas],ruta_salida=actual/'decisiones_pendientes.json')
    return raiz,actual,decision,ajenas


def filas_por_guia(actual):return {f['numero_guia']:f for f in _leer_filas(actual/'analisis_completo_guias.csv')}


def test_aplicar_482553_preserva_filas_y_tarjetas_sigro_y_oko(tmp_path):
    raiz,actual,decision,ajenas=preparar(tmp_path)
    antes=filas_por_guia(actual)
    resultado=aplicar_decision_obra(raiz_atlas=raiz,decision_id=decision['decision_id'],accion='REGISTRAR')
    despues=filas_por_guia(actual)
    assert resultado['ok'] and resultado['revalidacion']['alcance']=='FOCAL'
    assert set(resultado['guias_afectadas'])=={'482553','482554','482555'}
    for numero in ['482673','482188']:assert despues[numero]==antes[numero]
    # El viaje completo y la misma obra de otro viaje sí pasan por convergencia.
    assert set(resultado['revalidacion']['indicadores_documentales']['guias_actualizadas'])=={'482553','482554','482555'}
    for numero in ['482553','482554','482555']:assert despues[numero]['estado_documental']
    pendientes=json.loads((actual/'decisiones_pendientes.json').read_text(encoding='utf8'))['decisiones']
    assert [d for d in pendientes if d['documento']['numero_guia'] in {'482673','482188'}]==ajenas
    ledger=json.loads((actual/'decisiones_aplicadas.json').read_text(encoding='utf8'))['aplicaciones']
    assert {x['documento']['numero_guia'] for x in ledger}=={'482553'}


def test_scope_vacio_no_es_global_y_no_se_filtra_hash_de_dataset(tmp_path):
    raiz,actual,decision,_=preparar(tmp_path);dataset=actual/'analisis_completo_guias.csv';antes=dataset.read_bytes()
    from atlas_core.revalidacion_documental import _huella_contenido_dataset
    huella=_huella_contenido_dataset(dataset)
    with alcance_guias(dataset,set()):
        assert _leer_filas(dataset)==[]
        assert _huella_contenido_dataset(dataset)==huella
        _escribir_filas_completas(dataset,[])
    assert dataset.read_bytes()==antes


def test_escritura_focal_no_puede_colar_fila_ajena(tmp_path):
    raiz,actual,_,_=preparar(tmp_path);dataset=actual/'analisis_completo_guias.csv';filas=_leer_filas(dataset);antes=dataset.read_bytes()
    with alcance_guias(dataset,{'482553'}):
        with pytest.raises(ValueError,match='fuera de alcance'):_escribir_filas_completas(dataset,filas)
    assert dataset.read_bytes()==antes


def test_mantenimiento_global_explicitamente_sigue_disponible(tmp_path):
    raiz,actual,_,_=preparar(tmp_path);antes=filas_por_guia(actual)
    resultado=revalidar_y_regenerar_reporte(raiz_atlas=raiz,nombre_carpeta_reporte='global_prueba')
    assert resultado['alcance']=='GLOBAL'
    assert filas_por_guia(actual)['482188']!=antes['482188']  # fixture sensible a la bateria anterior


def test_obsolescencia_no_amplia_scope(tmp_path):
    raiz,actual,decision,ajenas=preparar(tmp_path);dataset=actual/'analisis_completo_guias.csv'
    filas=_leer_filas(dataset);filas[-1]['duracion_min']='41';_escribir_filas_completas(dataset,filas)
    antes=filas_por_guia(actual)
    resultado=aplicar_decision_obra(raiz_atlas=raiz,decision_id=decision['decision_id'],accion='REGISTRAR')
    assert resultado['ok']
    for n in ['482673','482188']:assert filas_por_guia(actual)[n]==antes[n]

def test_canal_controlado_desktop_no_altera_ajenas(tmp_path):
    from atlas_core.desktop_operacion import ejecutar
    raiz,actual,decision,ajenas=preparar(tmp_path);antes=filas_por_guia(actual)
    r=ejecutar({'raiz':str(raiz),'accion':'script','argumentos':['aplicar_decision_pendiente.py','--raiz-atlas',str(raiz),'--decision-id',decision['decision_id'],'--accion','REGISTRAR']})
    assert r['ok'] and json.loads(r['salida'])['ok']
    for n in ['482673','482188']:assert filas_por_guia(actual)[n]==antes[n]


def test_lote_real_tambien_respeta_alcance_en_cierre(tmp_path):
    from atlas_core.aplicacion_multiple import aplicar_decisiones_multiples
    raiz,actual,decision,ajenas=preparar(tmp_path);antes=filas_por_guia(actual)
    resultado=aplicar_decisiones_multiples(raiz_atlas=raiz,solicitudes=[{'decision_id':decision['decision_id'],'accion':'REGISTRAR'}])
    assert resultado.total_aplicadas==1
    for n in ['482673','482188']:assert filas_por_guia(actual)[n]==antes[n]
    pendientes=json.loads((actual/'decisiones_pendientes.json').read_text(encoding='utf8'))['decisiones']
    assert [d for d in pendientes if d['documento']['numero_guia'] in {'482673','482188'}]==ajenas

def test_entidad_obra_no_cruza_cliente_y_placeholder_no_identifica_viaje(tmp_path):
    raiz,actual,decision,_=preparar(tmp_path);dataset=actual/'analisis_completo_guias.csv'
    filas=_leer_filas(dataset)
    filas[0]['numero_transporte']='No encontrado'
    filas[1]['numero_transporte']='No encontrado'
    filas[2]['cliente']='OTRO CLIENTE'  # mismo nombre de obra no es identidad global
    _escribir_filas_completas(dataset,filas)
    assert calcular_guias_afectadas(raiz,decision)=={'482553'}


def test_scope_anidado_nunca_se_amplia_y_se_restaura_tras_error(tmp_path):
    from atlas_core.alcance_revalidacion import guias_en_alcance
    raiz,actual,_,_=preparar(tmp_path);dataset=actual/'analisis_completo_guias.csv'
    with pytest.raises(RuntimeError):
        with alcance_guias(dataset,{'482553'}):
            with alcance_guias(dataset,None):assert guias_en_alcance(dataset)=={'482553'}
            with alcance_guias(dataset,{'482673'}):assert guias_en_alcance(dataset)==set()
            assert guias_en_alcance(dataset)=={'482553'}
            raise RuntimeError('simulado')
    assert guias_en_alcance(dataset) is None


def test_reporte_conserva_viajes_ajenos(tmp_path):
    from atlas_core.reporte_viajes import generar_reporte_viajes
    raiz,actual,decision,_=preparar(tmp_path);dataset=actual/'analisis_completo_guias.csv'
    from datetime import datetime,timezone
    reloj=lambda:datetime(2026,10,21,tzinfo=timezone.utc)
    antes=raiz/'reportes/antes';generar_reporte_viajes(dataset,antes,carpeta_catalogos=raiz/'catalogos_privados',reloj=reloj)
    r=aplicar_decision_obra(raiz_atlas=raiz,decision_id=decision['decision_id'],accion='REGISTRAR',reloj=reloj)
    despues=Path(r['revalidacion']['reporte_vigente'])
    def viajes(folder):
        with (folder/'viajes.csv').open(encoding='utf-8-sig',newline='') as f:return {v['numero_transporte']:v for v in csv.DictReader(f,delimiter=';')}
    a,b=viajes(antes),viajes(despues)
    for t in ['0000360001','0000360002']:assert a[t]==b[t]

def test_evidencia_historica_se_consulta_sin_revalidar_donantes(tmp_path):
    from test_blindaje_historial_cliente_origen import _entorno as entorno_historial,_historial_colina,_fila_csv
    from atlas_core.revalidacion_documental import revalidar_origen_por_historial_de_cliente_sin_ocr
    donantes=_historial_colina(3)
    objetivo=_fila_csv(numero_guia='TARGET',numero_transporte='TARGET-T',obra_destino='OBRA DISTINTA',tipo_carga='NO DETERMINADO')
    raiz,catalogos,actual,dataset,colina,_=entorno_historial(tmp_path,[*donantes,objetivo])
    filas=_leer_filas(dataset)
    for fila in filas[:-1]:fila.update(planta_origen_id=colina.planta_id,planta_origen_nombre='AZA COLINA',origen_determinado_por='TELEMETRIA_GPS')
    _escribir_filas_completas(dataset,filas);antes=filas_por_guia(actual)
    with alcance_guias(dataset,{'TARGET'}):
        r=revalidar_origen_por_historial_de_cliente_sin_ocr(ruta_dataset=dataset,carpeta_catalogos=catalogos)
    assert r['guias_actualizadas']==['TARGET']
    despues=filas_por_guia(actual)
    assert despues['TARGET']['planta_origen_id']==colina.planta_id
    for n in antes.keys()-{'TARGET'}:assert antes[n]==despues[n]

def test_cambio_de_carro_no_revalida_otros_viajes_del_mismo_tracto(tmp_path):
    raiz,actual,decision,_=preparar(tmp_path);dataset=actual/'analisis_completo_guias.csv'
    filas=_leer_filas(dataset)
    for fila in filas:fila.update(patente_tracto='AA1111',patente_rampla='YY1111')
    filas[0]['patente_rampla']='ZZ9999'
    filas[2]['patente_rampla']='ZZ9999'
    _escribir_filas_completas(dataset,filas)
    decision={**decision,'tipo':'VEHICULO_DESCONOCIDO','campo':'patente_rampla'}
    assert calcular_guias_afectadas(raiz,decision)=={'482553','482554','482555'}


def test_rechazo_no_incluye_otros_viajes_por_entidad_sin_cambio(tmp_path):
    raiz,actual,decision,_=preparar(tmp_path)
    assert calcular_guias_afectadas(raiz,decision,accion='NO_REGISTRAR')=={'482553','482554'}
