import csv, json
import pytest
from atlas_core.responder_consulta_atlas import responder_consulta_atlas

@pytest.fixture
def fuente(tmp_path):
    raiz=tmp_path/'Atlas'; actual=raiz/'operacion'/'actual'; actual.mkdir(parents=True)
    ruta=tmp_path/'viajes.csv'
    filas=[{'viaje_id':'v1','numero_transporte':'t1','fecha':'01-10-2026','numeros_guia':'1 | 2'}, {'viaje_id':'v2','numero_transporte':'t2','fecha':'02-10-2026','numeros_guia':'3'}, {'viaje_id':'v3','numero_transporte':'t3','fecha':'03-10-2026','numeros_guia':'4'}]
    with ruta.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=filas[0].keys(),delimiter=';'); w.writeheader(); w.writerows(filas)
    def event(id,trans,nota):return {'estado':'ACTIVO','tipo_evento':'OBSERVACION_OPERACIONAL','naturaleza':'MARCA_VIAJE','viaje_id':id,'numero_transporte':trans,'nota':nota}
    eventos=[event('v1','t1','ESTE VIAJE TIENE ADICIONAL DE $30.000 POR RETIRO'),event('v1','t1','ESTE VIAJE TIENE ADICIONAL DE 30 mil'),event('v2','t2','VIAJE CON ADICIONAL DE 15 lucas'),event('v3','t3','ADICIONAL DE 45000 PESOS')]
    def guardar(ev): (actual/'eventos_operacionales.json').write_text(json.dumps({'schema_version':1,'eventos':ev}),encoding='utf-8')
    guardar(eventos)
    return raiz,ruta,eventos,guardar

@pytest.mark.parametrize('monto',['$30.000','30000','30 mil','30 lucas'])
def test_equivalentes_cuentan_viaje_unico(fuente,monto):
    raiz,ruta,*_=fuente
    r=responder_consulta_atlas('Cuantos viajes tienen adicional de '+monto+'?',ruta_viajes=ruta,raiz_atlas=raiz)
    assert r.estado=='OK' and r.resultado.resultado==1 and len(r.resultado.viajes_soporte)==1
    assert r.resultado.viajes_soporte[0]['viaje_id']=='v1'

def test_listado_y_comparaciones(fuente):
    raiz,ruta,*_=fuente
    r=responder_consulta_atlas('Lista los viajes con adicional superior a 30 mil',ruta_viajes=ruta,raiz_atlas=raiz)
    assert [v['viaje_id'] for v in r.resultado.viajes_soporte]==['v3']
    r=responder_consulta_atlas('Cuantos viajes tienen adicional menor que 30 lucas',ruta_viajes=ruta,raiz_atlas=raiz)
    assert r.resultado.resultado==1 and r.resultado.viajes_soporte[0]['viaje_id']=='v2'

@pytest.mark.parametrize('nota',['ADICIONAL DE 30000 POR GUIA','ADICIONAL DE 30000 Y ADICIONAL DE 15000','ADICIONAL SIN MONTO','NO TIENE ADICIONAL DE 30000'])
def test_nota_ambigua_no_da_conteo(fuente,nota):
    raiz,ruta,eventos,guardar=fuente; eventos.append(dict(eventos[0],nota=nota)); guardar(eventos)
    r=responder_consulta_atlas('Cuantos viajes tienen adicional de 30000',ruta_viajes=ruta,raiz_atlas=raiz)
    assert r.resultado is None and r.estado=='NO_INTERPRETABLE'

def test_filtros_no_entendidos_no_se_omiten(fuente):
    raiz,ruta,*_=fuente
    r=responder_consulta_atlas('Cuantos viajes tienen adicional de 30000 de Patrick',ruta_viajes=ruta,raiz_atlas=raiz)
    assert r.resultado is None and r.estado=='NO_INTERPRETABLE'

def test_fuente_ausente_y_vinculo_ambiguo(fuente):
    raiz,ruta,eventos,guardar=fuente
    assert responder_consulta_atlas('Cuantos viajes tienen adicional de 30000',ruta_viajes=ruta).resultado is None
    eventos[0]['viaje_id']='otro'; guardar(eventos)
    assert responder_consulta_atlas('Cuantos viajes tienen adicional de 30000',ruta_viajes=ruta,raiz_atlas=raiz).resultado is None


def test_archivo_corrupto_no_se_interpreta_como_cero(fuente):
    raiz,ruta,_,_=fuente
    (raiz/'operacion/actual/eventos_operacionales.json').write_text('{',encoding='utf-8')
    r=responder_consulta_atlas('Cuantos viajes tienen adicional de 30000',ruta_viajes=ruta,raiz_atlas=raiz)
    assert r.resultado is None and r.estado=='NO_INTERPRETABLE'

def test_nota_con_otro_importe_no_inventa(fuente):
    raiz,ruta,eventos,guardar=fuente; eventos[0]['nota']='ADICIONAL DE 30000 O 45000'; guardar(eventos)
    assert responder_consulta_atlas('Cuantos viajes tienen adicional de 30000',ruta_viajes=ruta,raiz_atlas=raiz).resultado is None


def test_duplicado_en_reporte_cuenta_una_vez(fuente):
    raiz,ruta,_,_=fuente
    with ruta.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f,delimiter=';'); fields=reader.fieldnames; filas=list(reader)
    with ruta.open('a',encoding='utf-8',newline='') as f:
        csv.DictWriter(f,fieldnames=fields,delimiter=';').writerow(filas[0])
    r=responder_consulta_atlas('Cuantos viajes tienen un adicional de $30.000',ruta_viajes=ruta,raiz_atlas=raiz)
    assert r.resultado.resultado==1
