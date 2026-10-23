import csv
from datetime import date
import pytest
import atlas_core.interpretador_consultas as interprete
from atlas_core.consultas_atlas import ConsultaAtlas, ejecutar_consulta_atlas, ordenar_viajes_por_fecha
from atlas_core.cli_consulta_atlas import _respuesta_a_dict
from atlas_core.responder_consulta_atlas import responder_consulta_atlas
from atlas_core.soporte_consultas import soporte_semantico


def filas(chofer):
    return [dict(viaje_id=ident, numero_transporte=transporte, fecha=fecha, choferes=chofer, numeros_guia='1 | 2')
            for ident, transporte, fecha in [
                ('v4','104','02-01-2031'), ('v2b','102','31-12-2030'),
                ('v3','103','01-01-2031'), ('v1','101','30-12-2030'),
                ('v2a','102','31-12-2030'), ('viejo','099','29-12-2030'),
                ('futuro','105','03-01-2031'), ('sin','106',''), ('mal','107','31-02-2031')]]

@pytest.mark.parametrize('chofer,mencion', [('ANA TORRES','torres'), ('PEDRO SOTO','soto')])
@pytest.mark.parametrize('periodo', ['del 30/12/2030 al 02/01/2031', 'entre 30/12/2030 y 02/01/2031'])
def test_cualquier_chofer_periodo_y_soporte_cronologico(tmp_path, chofer, mencion, periodo):
    ruta=tmp_path/'viajes.csv'
    with ruta.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(filas(chofer)[0]),delimiter=';')
        w.writeheader();w.writerows(filas('ANA TORRES')+filas('PEDRO SOTO'))
    r=responder_consulta_atlas('cuantos viajes tiene '+mencion+' '+periodo,ruta_viajes=ruta)
    assert r.estado=='OK'
    resultado=r.resultado
    assert resultado.resultado==resultado.total_coincidencias==len(resultado.viajes_soporte)==5
    assert [v['viaje_id'] for v in resultado.viajes_soporte]==['v1','v2a','v2b','v3','v4']
    assert all(v['choferes']==chofer for v in resultado.viajes_soporte)
    assert resultado.consulta_interpretada.filtros=={'chofer':chofer,'fecha_desde':'2030-12-30','fecha_hasta':'2031-01-02'}
    serializado=_respuesta_a_dict(r)['resultado']
    assert [v['numero_transporte'] for v in serializado['viajes_soporte']]==[f[1] for f in serializado['soporte']['filas']]

@pytest.mark.parametrize('chofer,mencion', [('ANA TORRES','torres'), ('PEDRO SOTO','soto')])
def test_sin_anio_usa_politica_compartida(tmp_path,monkeypatch,chofer,mencion):
    class Hoy(date):
        @classmethod
        def today(cls): return cls(2031,1,15)
    monkeypatch.setattr(interprete,'date',Hoy)
    ruta=tmp_path/'viajes.csv'
    with ruta.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(filas(chofer)[0]),delimiter=';');w.writeheader();w.writerows(filas(chofer))
    r=responder_consulta_atlas('cuantos viajes tiene '+mencion+' del 01/01 al 02/01',ruta_viajes=ruta)
    assert r.resultado.resultado==2
    assert [v['fecha'] for v in r.resultado.viajes_soporte]==['01-01-2031','02-01-2031']


def test_sin_periodo_conserva_miembros_total_y_datos_identifica_fechas_invalidas():
    originales=filas('ANA TORRES')
    copia=[dict(v) for v in originales]
    r=ejecutar_consulta_atlas(ConsultaAtlas(metrica='COUNT_VIAJES',filtros={'chofer':'ANA TORRES'}), originales)
    assert originales==copia
    assert r.resultado==r.total_coincidencias==len(r.viajes_soporte)==9
    assert {id(v) for v in originales}=={id(v) for v in r.viajes_soporte}
    assert [v['viaje_id'] for v in r.viajes_soporte]==['viejo','v1','v2a','v2b','v3','v4','futuro','sin','mal']
    soporte=soporte_semantico(r)
    assert [v[0] for v in soporte['filas']][-2:]==['Sin fecha','Fecha no interpretable: 31-02-2031']
    assert [v['viaje_id'] for v in ordenar_viajes_por_fecha(list(reversed(originales)))]==[v['viaje_id'] for v in r.viajes_soporte]

@pytest.mark.parametrize('orden',['ASC','DESC'])
def test_listado_reutiliza_orden_y_soporte_ascendente(orden):
    originales=filas('ANA TORRES')
    r=ejecutar_consulta_atlas(ConsultaAtlas(metrica='LISTAR_VIAJES',orden=orden),originales)
    assert len(r.viajes_soporte)==len(r.resultado)==r.total_coincidencias==9
    assert [v['viaje_id'] for v in r.viajes_soporte]==['viejo','v1','v2a','v2b','v3','v4','futuro','sin','mal']
    assert [v['viaje_id'] for v in r.resultado][-2:]==['sin','mal']
