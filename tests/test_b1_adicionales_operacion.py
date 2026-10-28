import csv,json
import pytest
from atlas_core.b1_operador import OperadorB1, interpretar_determinista
from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.registro_eventos_operacionales import leer_eventos_operacionales, registrar_evento

@pytest.fixture
def raiz(tmp_path):
    raiz=tmp_path/'Atlas'; actual=raiz/'operacion'/'actual'; actual.mkdir(parents=True); (raiz/'catalogos_privados').mkdir()
    with (actual/'analisis_completo_guias.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=COLUMNAS,delimiter=';'); w.writeheader()
        for guia,transporte in [('483082','0000366043'),('483043','0000365998'),('500001','0000900001')]:
            fila={c:'' for c in COLUMNAS}; fila.update(archivo=guia+'.jpg',numero_guia=guia,numero_transporte=transporte); w.writerow(fila)
    registrar_evento(raiz=raiz,tipo_evento='OBSERVACION_OPERACIONAL',numero_transporte='0000366043',nota='NOTA ANTERIOR',origen='TEST')
    return raiz

def eventos(raiz):return leer_eventos_operacionales(raiz=raiz)['eventos']

class Escritor:
    vigente=True
    def adquirir(self): return True
    def cerrar(self): pass

def operador(raiz):
    return OperadorB1(raiz, capa=CapaAccionesOperacionales(raiz, fabrica_escritor=lambda: Escritor()))

ORDEN='Agrega un adicional de $15.000 a cada uno de estos viajes, guias 483082 y 483043'

def test_parser_y_preview_por_viaje_sin_escribir(raiz):
    b=operador(raiz); antes=json.dumps(eventos(raiz),sort_keys=True)
    r=b.atender('c',ORDEN)
    assert r['estado']=='PREVIEW_PENDIENTE',r
    t=r['tablas'][0]; filas={f[0]:f for f in t['filas']}
    assert set(filas)=={'483082','483043'}
    assert filas['483082'][1]=='0000366043' and filas['483043'][1]=='0000365998'
    assert 'NOTA ANTERIOR' in filas['483082'][3]
    assert all('$15.000' in f[4] for f in filas.values())
    assert json.dumps(eventos(raiz),sort_keys=True)==antes
    assert b.atender('c','no')['estado']=='CANCELADA'
    assert json.dumps(eventos(raiz),sort_keys=True)==antes

def test_confirmacion_audita_y_repeticion_es_idempotente(raiz):
    b=operador(raiz); assert b.atender('c',ORDEN)['estado']=='PREVIEW_PENDIENTE'
    assert b.atender('c','si')['estado']=='EJECUTADA'
    por={e['numero_transporte']:e['nota'] for e in eventos(raiz) if e['tipo_evento']=='OBSERVACION_OPERACIONAL'}
    assert por['0000366043']=='NOTA ANTERIOR\nESTE VIAJE TIENE ADICIONAL DE $15.000'
    assert por['0000365998']=='ESTE VIAJE TIENE ADICIONAL DE $15.000'
    assert b.atender('c',ORDEN)['estado']=='SIN_CAMBIOS'

@pytest.mark.parametrize('monto',['15 mil','15000','15 lucas','$15.000'])
def test_equivalencia_evitar_duplicado(raiz,monto):
    registrar_evento(raiz=raiz,tipo_evento='OBSERVACION_OPERACIONAL',numero_transporte='0000365998',nota='VIAJE CON ADICIONAL DE '+monto,origen='TEST')
    r=operador(raiz).atender('c',ORDEN); assert r['estado']=='PREVIEW_PENDIENTE',r
    filas={f[0]:f for f in r['tablas'][0]['filas']}
    assert filas['483043'][2].startswith('Ya la tiene') and filas['483082'][2]=='Se agrega'

def test_referencia_sin_guias_no_inventa_destinatarios(raiz):
    pregunta='Agrega un adicional de $15.000 a cada uno de estos viajes'
    assert interpretar_determinista(pregunta) is None
    assert operador(raiz).atender('c',pregunta)['estado']=='ACLARACION_REQUERIDA'

def test_nota_ambigua_no_permite_cambio(raiz):
    registrar_evento(raiz=raiz,tipo_evento='OBSERVACION_OPERACIONAL',numero_transporte='0000365998',nota='ADICIONAL DE 15 MIL POR GUIA',origen='TEST')
    r=operador(raiz).atender('c',ORDEN); assert r['estado']=='RECHAZADA',r


def test_confirmacion_sin_escritor_no_modifica(raiz):
    b=OperadorB1(raiz, capa=CapaAccionesOperacionales(raiz, fabrica_escritor=lambda: None))
    antes=json.dumps(eventos(raiz),sort_keys=True)
    assert b.atender('c',ORDEN)['estado']=='PREVIEW_PENDIENTE'
    r=b.atender('c','si')
    assert r['estado']!='EJECUTADA'
    assert json.dumps(eventos(raiz),sort_keys=True)==antes
