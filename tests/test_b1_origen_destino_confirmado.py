"""Corregir la planta de origen de un viaje con destino confirmado por una
persona: el destino (dirección, comuna, coordenadas, cliente y obra) se
conserva y sólo la ruta derivada de la planta anterior se invalida y se
recalcula. Solo datos sintéticos."""
import csv
import json

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.b1_operador import OperadorB1
from atlas_core.destino_operacional import proyectar_destino
from atlas_core.rutas.modelos import Coordenadas, EstadoRuta, ResultadoRuta
from atlas_core.rutas.proveedor import ProveedorRutasSimulado
from tests.test_acciones_operacionales import _EscritorDisponible
from tests import test_origen_no_confirmado as origen
from tests.test_b1_campos_documentales import _filas, _huellas
from tests.test_b1_planta_origen_determinada import _dos_guias, entorno  # noqa: F401 -- fixture

LAT, LON = -33.401, -70.602
DECISION = 'ACCION_OPERACIONAL:destino-464901'


class Proveedor(ProveedorRutasSimulado):
    def __init__(self, falla=False):
        super().__init__(resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 21.7, 30.0, ''))
        self.falla, self.rutas, self.geocodificadas = falla, [], []

    def geocodificar(self, direccion):
        self.geocodificadas.append(direccion)
        return super().geocodificar(direccion)

    def calcular_ruta(self, origen_, destino, perfil):
        self.rutas.append((origen_, destino))
        if self.falla:
            return ResultadoRuta(EstadoRuta.PROVEEDOR_NO_DISPONIBLE, motivo='CAIDO')
        return super().calcular_ruta(origen_, destino, perfil)


def _decision(e, *, conservar=False, ruta=None, guia='464901'):
    ruta = ruta if ruta is not None else {
        'estado_ruta': 'RUTA_CALCULADA', 'distancia_km': '33.3', 'duracion_min': '40',
        'proveedor_ruta': 'openrouteservice', 'latitud_entrega': str(LAT), 'longitud_entrega': str(LON),
        'region_entrega': 'RM', 'codigo_pais': 'CL', 'codigo_unidad': '13128', 'codigo_contexto': 'X',
        'comuna': 'RENCA', 'planta_origen_id': e['planta_colina'].planta_id}
    entrada = {'decision_id': DECISION, 'tipo': 'DESTINO_OPERACIONAL_DOCUMENTO',
               'accion': 'CORREGIR_DESTINO_OPERACIONAL', 'actor': 'B1', 'confirmado_por': 'JAVIER',
               'documento': {'archivo': f'{guia}.jpeg', 'numero_guia': guia, 'numero_transporte': '0000000900'},
               'destino_operacional': {'direccion': 'EJEMPLO 123', 'comuna': 'RENCA'},
               'ruta_operacional': ruta}
    if conservar:
        entrada['conservar_estado_operacional'] = True
    (e['actual'] / 'decisiones_aplicadas.json').write_text(
        json.dumps({'schema_version': 1, 'aplicaciones': [entrada]}), encoding='utf-8')
    return entrada


def _capa(e, proveedor):
    e['capa'] = CapaAccionesOperacionales(e['raiz'], proveedor_rutas=proveedor,
                                         proveedor_rutas_fallback=proveedor,
                                         fabrica_escritor=lambda: _EscritorDisponible())
    e['b1'] = OperadorB1(e['raiz'], capa=e['capa'])


def _ledger(e):
    return json.loads((e['actual'] / 'decisiones_aplicadas.json').read_text(encoding='utf-8'))


def _proyectada(e, archivo='464901.jpeg'):
    return proyectar_destino(_filas(e['dataset'])[archivo], _ledger(e))


def _corregir(e, guia='464900', planta=None):
    p = e['capa'].previsualizar('DOCUMENTO_CORREGIR_PLANTA_ORIGEN',
        {'numero_guia': guia, 'planta_id': planta or e['planta_renca'].planta_id}, actor='B1')
    assert p['estado'] == 'PREVIEW', p
    return p, e['capa'].ejecutar(p['token'], actor='B1', confirmado_por='JAVIER')


def test_preview_conserva_destino_y_anuncia_recalculo_sin_escribir(entorno):
    e = entorno
    _dos_guias(e)
    _decision(e)
    _capa(e, Proveedor())
    antes = _huellas(e['raiz'])
    r = e['b1'].atender('p', 'La planta de origen de la guía 464900 es Renca')
    assert r['estado'] == 'PREVIEW_PENDIENTE', r
    assert 'se conserva el destino confirmado EJEMPLO 123, RENCA' in r['mensaje']
    assert 'sin volver a pedir su confirmación' in r['mensaje']
    assert '(33.3 km)' in r['mensaje'] and 'hasta sus mismas coordenadas confirmadas' in r['mensaje']
    assert 'Guía 464900: AZA COLINA → AZA RENCA' in r['mensaje']
    assert _huellas(e['raiz']) == antes
    assert e['b1'].atender('p', 'no')['estado'] == 'CANCELADA'
    assert _huellas(e['raiz']) == antes


def test_confirmar_recalcula_desde_nueva_planta_hacia_coordenadas_confirmadas(entorno):
    e = entorno
    _, _, otro = _dos_guias(e)
    decision = _decision(e)
    proveedor = Proveedor()
    _capa(e, proveedor)
    assert _proyectada(e)['distancia_km'] == '33.3'
    _, r = _corregir(e)
    assert r['estado'] == 'APLICADA', r
    # Ruta pedida desde Renca hacia las MISMAS coordenadas; el destino
    # confirmado nunca se vuelve a geocodificar.
    assert (Coordenadas(-70.9, -33.75), Coordenadas(LON, LAT)) in proveedor.rutas
    assert 'EJEMPLO 123' not in ' '.join(proveedor.geocodificadas)
    vista = _proyectada(e)
    assert vista['planta_origen_nombre'] == 'AZA RENCA'
    assert (vista['direccion_entrega'], vista['localidad_entrega']) == ('EJEMPLO 123', 'RENCA')
    assert (vista['latitud_entrega'], vista['longitud_entrega']) == (str(LAT), str(LON))
    assert vista['codigo_unidad'] == '13128' and vista['region_entrega'] == 'RM'
    assert vista['distancia_km'] == '21.7' and vista['estado_ruta'] == 'RUTA_CALCULADA'
    assert vista['cliente'] == 'CLIENTE PRUEBA' and vista['obra_destino'] == 'OBRA PRUEBA'
    ledger = _ledger(e)['aplicaciones']
    assert ledger[0] == decision  # la decisión humana no se toca
    [correccion] = [a for a in ledger if a.get('tipo') == 'CORRECCION_ORIGEN_OPERACIONAL']
    [registro] = correccion['destinos_confirmados']
    assert registro['decision_id'] == DECISION and registro['ruta_anterior']['distancia_km'] == '33.3'
    assert registro['ruta_nueva']['distancia_km'] == '21.7'
    assert registro['ruta_nueva']['planta_origen_id'] == e['planta_renca'].planta_id
    assert _filas(e['dataset'])['464950.jpeg'] == otro
    metricas = json.loads(_filas(e['dataset'])['464901.jpeg']['metricas_procesamiento_json'])
    assert metricas['recalculo_ruta_origen'][-1]['ruta_anterior']['distancia_km'] == '33.3'


def test_reporte_publica_ruta_nueva_y_no_vuelve_a_pedir_destino(entorno):
    e = entorno
    _dos_guias(e)
    _decision(e)
    _capa(e, Proveedor())
    _, r = _corregir(e)
    assert r['estado'] == 'APLICADA', r
    estado = json.loads((e['actual'] / 'estado_operacion.json').read_text(encoding='utf-8-sig'))
    carpeta = e['raiz'] / estado['reporte_vigente']
    with (carpeta / 'viajes.csv').open(encoding='utf-8-sig', newline='') as f:
        viajes = {v['numero_transporte']: v for v in csv.DictReader(f, delimiter=';')}
    assert viajes['0000000900']['planta_origen_nombre'] == 'AZA RENCA'
    entregas = {g: x for x in json.loads(viajes['0000000900']['entregas']) for g in x['numeros_guia']}
    assert entregas['464901']['distancia_km'] == '21.7' and entregas['464901']['destino_operacional'] == 'EJEMPLO 123'
    assert '33.3' not in viajes['0000000900']['entregas'] + viajes['0000000900']['distancia_km']
    bandeja = e['actual'] / 'decisiones_pendientes.json'
    pendientes = json.loads(bandeja.read_text(encoding='utf-8')).get('decisiones', []) if bandeja.exists() else []
    assert not [d for d in pendientes if str(d.get('tipo', '')).startswith('DESTINO')
                and (d.get('documento') or {}).get('numero_guia') == '464901']


def test_sin_ruta_calculable_queda_pendiente_sin_km_antiguos_y_con_coordenadas(entorno):
    e = entorno
    _dos_guias(e)
    _decision(e)
    _capa(e, Proveedor(falla=True))
    _, r = _corregir(e)
    assert r['estado'] == 'APLICADA', r
    vista = _proyectada(e)
    assert vista['distancia_km'] == '' and vista['duracion_min'] == ''
    assert vista['estado_ruta'] == 'REQUIERE_REVISION'
    assert vista['motivo_ruta'] == 'ORIGEN_MODIFICADO_RUTA_PENDIENTE'
    assert (vista['latitud_entrega'], vista['longitud_entrega']) == (str(LAT), str(LON))
    assert vista['direccion_entrega'] == 'EJEMPLO 123' and vista['estado_operacional'] == 'REQUIERE_REVISION'


def test_volver_a_la_planta_anterior_recalcula_otra_vez(entorno):
    e = entorno
    _dos_guias(e)
    decision = _decision(e)
    proveedor = Proveedor()
    _capa(e, proveedor)
    assert _corregir(e)[1]['estado'] == 'APLICADA'
    proveedor.resultado_ruta = ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 33.3, 40.0, '')
    assert _corregir(e, planta=e['planta_colina'].planta_id)[1]['estado'] == 'APLICADA'
    vista = _proyectada(e)
    assert vista['planta_origen_nombre'] == 'AZA COLINA' and vista['distancia_km'] == '33.3'
    assert proveedor.rutas[-1][1] == Coordenadas(LON, LAT)
    assert _ledger(e)['aplicaciones'][0] == decision


def test_destino_sin_coordenadas_se_calcula_con_la_comuna_confirmada(entorno):
    e = entorno
    _dos_guias(e)
    _decision(e, ruta={'estado_ruta': 'PENDIENTE'})
    proveedor = Proveedor(falla=True)
    _capa(e, proveedor)
    _, r = _corregir(e)
    assert r['estado'] == 'APLICADA', r
    assert 'EJEMPLO 123' in ' '.join(proveedor.geocodificadas)
    vista = _proyectada(e)
    assert vista['distancia_km'] == '' and vista['direccion_entrega'] == 'EJEMPLO 123'
    metricas = json.loads(_filas(e['dataset'])['464901.jpeg']['metricas_procesamiento_json'])
    assert metricas['ruta_operacional_recalculada']['ruta']['planta_origen_id'] == e['planta_renca'].planta_id


def test_conservar_estado_no_publica_km_de_la_planta_anterior(entorno):
    e = entorno
    _dos_guias(e)
    _decision(e, conservar=True, ruta={'estado_ruta': 'PENDIENTE'})
    proveedor = Proveedor()
    _capa(e, proveedor)
    assert _proyectada(e)['distancia_km'] == '35'
    preview, r = _corregir(e)
    assert any('requiriendo comprobación' in c and '(35 km)' in c for c in preview['consecuencias'])
    assert r['estado'] == 'APLICADA', r
    # Sin coordenadas guardadas se recalcula hacia la dirección confirmada
    # (el proveedor simulado no la ubica: queda pendiente, sin km antiguos).
    assert 'EJEMPLO 123' in ' '.join(proveedor.geocodificadas)
    vista = _proyectada(e)
    assert vista['estado_ruta'] == 'REQUIERE_COMPROBACION' and vista['distancia_km'] == ''
    assert vista['motivo_ruta'] == 'ORIGEN_MODIFICADO_RUTA_PENDIENTE'
    assert vista['direccion_entrega'] == 'EJEMPLO 123'


def test_destino_cambiado_tras_preview_no_aplica(entorno):
    e = entorno
    _dos_guias(e)
    _decision(e)
    _capa(e, Proveedor())
    p = e['capa'].previsualizar('DOCUMENTO_CORREGIR_PLANTA_ORIGEN',
        {'numero_guia': '464900', 'planta_id': e['planta_renca'].planta_id}, actor='B1')
    ledger = _ledger(e)
    ledger['aplicaciones'][0]['destino_operacional'] = {'direccion': 'OTRA 9', 'comuna': 'RENCA'}
    (e['actual'] / 'decisiones_aplicadas.json').write_text(json.dumps(ledger), encoding='utf-8')
    antes = _huellas(e['raiz'])
    r = e['capa'].ejecutar(p['token'], actor='B1', confirmado_por='JAVIER')
    assert r['estado'] == 'PREVIEW_OBSOLETO', r
    assert _huellas(e['raiz']) == antes


def test_agrupacion_activa_sigue_bloqueando_con_destino_confirmado(entorno):
    e = entorno
    _dos_guias(e)
    _decision(e)
    (e['actual'] / 'agrupaciones_viaje.json').write_text(json.dumps({'schema_version': 1, 'agrupaciones': [
        {'estado': 'ACTIVA', 'transportes': ['0000000900', '0000000950']}]}), encoding='utf-8')
    _capa(e, Proveedor())
    antes = _huellas(e['raiz'])
    r = e['b1'].atender('p', 'La planta de origen de la guía 464900 es Renca')
    assert r['estado'] == 'ACLARACION_REQUERIDA', r
    assert _huellas(e['raiz']) == antes


# --- Proyección: una ruta sólo vale para la planta de la que salió ------------

def _fila(planta='P1', **extra):
    return {'archivo': 'a.jpeg', 'numero_guia': '1', 'numero_transporte': '9', 'planta_origen_id': planta,
            'distancia_km': '50', 'estado_ruta': 'RUTA_CALCULADA', **extra}


def _ledger_proyeccion(ruta, *posteriores):
    return {'aplicaciones': [{'decision_id': 'D', 'tipo': 'DESTINO_OPERACIONAL_DOCUMENTO',
                              'documento': {'archivo': 'a.jpeg', 'numero_guia': '1', 'numero_transporte': '9'},
                              'destino_operacional': {'direccion': 'X 1', 'comuna': 'RENCA'},
                              'ruta_operacional': ruta}, *posteriores]}


RUTA = {'estado_ruta': 'RUTA_CALCULADA', 'distancia_km': '12', 'comuna': 'RENCA', 'latitud_entrega': '-33',
        'longitud_entrega': '-70'}


def test_ruta_de_otra_planta_no_se_publica():
    assert proyectar_destino(_fila('P1'), _ledger_proyeccion({**RUTA, 'planta_origen_id': 'P1'}))['distancia_km'] == '12'
    vista = proyectar_destino(_fila('P2'), _ledger_proyeccion({**RUTA, 'planta_origen_id': 'P1'}))
    assert vista['distancia_km'] == '' and vista['direccion_entrega'] == 'X 1'


def test_ruta_antigua_sin_planta_vale_hasta_una_correccion_de_origen():
    assert proyectar_destino(_fila(), _ledger_proyeccion(RUTA))['distancia_km'] == '12'
    correccion = {'tipo': 'CORRECCION_ORIGEN_OPERACIONAL', 'documento': {'archivo': 'otro.jpeg'},
                  'documentos_viaje': [{'archivo': 'a.jpeg', 'numero_guia': '1'}]}
    assert proyectar_destino(_fila(), _ledger_proyeccion(RUTA, correccion))['distancia_km'] == ''
    ajena = {'tipo': 'CORRECCION_ORIGEN_OPERACIONAL', 'documento': {'archivo': 'b.jpeg'},
             'documentos_viaje': [{'archivo': 'b.jpeg'}]}
    assert proyectar_destino(_fila(), _ledger_proyeccion(RUTA, ajena))['distancia_km'] == '12'


def test_conservar_estado_sin_correccion_de_origen_no_cambia():
    ledger = _ledger_proyeccion({'estado_ruta': 'PENDIENTE'})
    ledger['aplicaciones'][0]['conservar_estado_operacional'] = True
    vista = proyectar_destino(_fila(), ledger)
    assert vista['distancia_km'] == '50' and vista['estado_ruta'] == 'REQUIERE_COMPROBACION'


@pytest.mark.parametrize('planta_registro', ['P1', ''])
def test_recalculo_aza_previo_sigue_valiendo_con_su_planta(planta_registro):
    ruta = {**RUTA, 'distancia_km': '7'}
    if planta_registro:
        ruta['planta_origen_id'] = planta_registro
    metricas = {'ruta_operacional_recalculada': {'decision_id': 'D', 'direccion': 'X 1', 'comuna': 'RENCA',
                                                 'ruta': ruta}}
    fila = _fila(metricas_procesamiento_json=json.dumps(metricas))
    assert proyectar_destino(fila, _ledger_proyeccion({'estado_ruta': 'PENDIENTE'}))['distancia_km'] == '7'


def test_conservar_estado_tras_correccion_publica_solo_la_ruta_de_la_planta_actual():
    ledger = _ledger_proyeccion({'estado_ruta': 'PENDIENTE'}, {
        'tipo': 'CORRECCION_ORIGEN_OPERACIONAL', 'documento': {'archivo': 'a.jpeg'}, 'documentos_viaje': []})
    ledger['aplicaciones'][0]['conservar_estado_operacional'] = True
    registro = {'decision_id': 'D', 'direccion': 'X 1', 'comuna': 'RENCA',
                'ruta': {**RUTA, 'distancia_km': '8', 'planta_origen_id': 'P2'}}
    fila = _fila('P2', metricas_procesamiento_json=json.dumps({'ruta_operacional_recalculada': registro}))
    vista = proyectar_destino(fila, ledger)
    # La ruta recalculada desde la planta actual ES la comprobación pendiente
    # (recuperación de comunas 25/11): se publica como calculada.
    assert vista['distancia_km'] == '8' and vista['estado_ruta'] == 'RUTA_CALCULADA'
    assert vista['ruta_requiere_comprobacion'] is False
    vista = proyectar_destino({**fila, 'planta_origen_id': 'P3'}, ledger)
    assert vista['distancia_km'] == '' and vista['motivo_ruta'] == 'ORIGEN_MODIFICADO_RUTA_PENDIENTE'
