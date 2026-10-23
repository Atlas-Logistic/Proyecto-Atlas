import csv
from datetime import date
import pytest
import atlas_core.interpretador_consultas as interprete
from atlas_core.responder_consulta_atlas import responder_consulta_atlas

@pytest.fixture
def viajes(tmp_path, monkeypatch):
    class Hoy(date):
        @classmethod
        def today(cls):
            return cls(2031, 10, 23)
    monkeypatch.setattr(interprete, 'date', Hoy)
    ruta = tmp_path / 'viajes.csv'
    with ruta.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['viaje_id','numero_transporte','fecha','choferes','numeros_guia'], delimiter=';')
        w.writeheader()
        for i, dia in enumerate(['01-10-2031','02-10-2031','08-10-2031','09-10-2031','02-09-2031','02-08-2031']):
            w.writerow(dict(viaje_id=str(i), numero_transporte=str(100+i),fecha=dia,choferes='PATRICIO VILLAGRA MU\u00d1OZ',numeros_guia='1 | 2'))
    return ruta

@pytest.mark.parametrize('periodo', ['del 02/10 al 08/10', 'del 02/10/2031 al 08/10/2031', 'del 02/10 al 08/10/2031', 'entre 02/10/2031 y 08/10/2031', 'desde 02-10-2031 hasta 08-10-2031'])
def test_rango_inclusivo_cuenta_viajes_y_mismo_soporte(viajes, periodo):
    r = responder_consulta_atlas('cuantos viajes tiene villagra '+periodo, ruta_viajes=viajes)
    assert r.estado == 'OK'
    assert r.resultado.resultado == r.resultado.total_coincidencias == len(r.resultado.viajes_soporte) == 2
    assert {v['fecha'] for v in r.resultado.viajes_soporte} == {'02-10-2031','08-10-2031'}
    assert r.resultado.consulta_interpretada.filtros['chofer'] == 'PATRICIO VILLAGRA MU\u00d1OZ'
    assert '2031-10-02 al 2031-10-08' in r.texto_respuesta

@pytest.mark.parametrize('periodo', ['del 08/10 al 02/10', 'del 31/02 al 08/10', 'del 02/10 al xx', 'del 02/xx al 08/xx', 'del 02/10/31 al 08/10/31'])
def test_fecha_invalida_nunca_consulta_historico(viajes, periodo):
    r = responder_consulta_atlas('cuantos viajes tiene villagra '+periodo, ruta_viajes=viajes)
    assert r.resultado is None
    assert r.estado == 'CONSULTA_INVALIDA'

def test_sin_periodo_conserva_historico(viajes):
    r = responder_consulta_atlas('cuantos viajes tiene villagra', ruta_viajes=viajes)
    assert r.resultado.resultado == 6
    assert 'fecha_desde' not in r.resultado.consulta_interpretada.filtros

def test_ingesta_reutiliza_ventana(viajes):
    assert interprete._filtros_periodo_ingesta('INGRESADAS DEL 02/10 AL 08/10') == {'fecha_ingesta_desde':'2031-10-02','fecha_ingesta_hasta':'2031-10-08'}


def test_fecha_puntual_y_rut_no_regresan(viajes):
    r = responder_consulta_atlas('cuantos viajes tiene villagra del 02/10/2031', ruta_viajes=viajes)
    assert r.resultado.resultado == 1
    assert interprete._filtros_periodo('RUT 12.345.678-9') == {}
