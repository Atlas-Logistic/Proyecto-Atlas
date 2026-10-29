import csv
import json
import pytest
from atlas_core.b1_operador import OperadorB1
from tests.test_acciones_operacionales import entorno


def preparar(entorno):
    decisiones = [
        {'decision_id': 'a', 'estado': 'PENDIENTE', 'documento': {'numero_guia': '100'}},
        {'decision_id': 'b', 'estado': 'PENDIENTE', 'documento': {'numero_guia': '101'}},
        {'decision_id': 'c', 'estado': 'RESUELTA', 'documento': {'numero_guia': '200'}},
        {'decision_id': 'd', 'documento': {'numero_guia': '100'}},
    ]
    (entorno['actual'] / 'decisiones_pendientes.json').write_text(json.dumps({'decisiones': decisiones}), encoding='utf-8')
    with (entorno['actual'] / 'viajes.csv').open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['viaje_id', 'numero_transporte', 'numeros_guia', 'documentos', 'fecha'], delimiter=';')
        w.writeheader()
        w.writerows([{'viaje_id': '1', 'numero_transporte': '123', 'numeros_guia': '100 | 101'},
                     {'viaje_id': '2', 'numero_transporte': '456', 'numeros_guia': '200'},
                     {'viaje_id': '3', 'numero_transporte': '789', 'numeros_guia': '300'}])


@pytest.mark.parametrize('pregunta,accion,total', [
    ('Cuántos viajes tienen revisión', 'VIAJES_CON_REVISION', 1),
    ('Cuántas revisiones pendientes hay', 'REVISIONES_PENDIENTES', 3),
    ('Muéstrame los viajes con revisión pendiente', 'VIAJES_CON_REVISION', 1),
])
def test_consultas_revisiones(entorno, pregunta, accion, total):
    preparar(entorno)
    b1 = OperadorB1(entorno['raiz'])
    antes = {p: p.read_bytes() for p in entorno['raiz'].rglob('*') if p.is_file()}
    r = b1.consultar(pregunta)
    assert r['estado'] == 'RESULTADO_LECTURA' and r['accion'] == accion
    assert r['resultado']['total_revisiones' if accion == 'REVISIONES_PENDIENTES' else 'total_viajes'] == total
    if accion == 'VIAJES_CON_REVISION':
        # Viajes afectados, revisiones pendientes y total del reporte, por separado.
        assert (r['resultado']['total_revisiones'], r['resultado']['viajes_reporte']) == (3, 3)
        assert r['mensaje'].startswith('1 viaje con revisiones pendientes (3 revisiones pendientes; 3 viajes')
    if pregunta.startswith('Muéstrame'):
        assert r['tablas'][0]['filas'] == [['123', '100 | 101', '']]
    assert {p: p.read_bytes() for p in entorno['raiz'].rglob('*') if p.is_file()} == antes


def test_asociacion_incompleta_y_fuentes_no_disponibles(entorno):
    preparar(entorno)
    ruta = entorno['actual'] / 'decisiones_pendientes.json'
    datos = json.loads(ruta.read_text(encoding='utf-8'))
    datos['decisiones'].append({'documento': {'numero_guia': '999'}})
    ruta.write_text(json.dumps(datos), encoding='utf-8')
    b1 = OperadorB1(entorno['raiz'])
    r = b1.consultar('Cuántos viajes tienen revisión')
    assert r['resultado']['revisiones_sin_viaje'] == 1
    assert 'no se pudieron asociar' in r['mensaje'] or 'no se pudo asociar' in r['mensaje']
    ruta.unlink()
    assert b1.consultar('Cuántas revisiones pendientes hay')['estado'] == 'RECHAZADA'


def test_lee_viajes_del_reporte_vigente(entorno, monkeypatch):
    preparar(entorno)
    reporte = entorno['raiz'] / 'reportes' / 'reporte_x'
    reporte.mkdir(parents=True)
    (entorno['actual'] / 'viajes.csv').replace(reporte / 'viajes.csv')
    from atlas_core import consulta_revisiones_b1
    monkeypatch.setattr(consulta_revisiones_b1, 'leer_estado_operacion',
                        lambda raiz: {'reporte_vigente': 'reportes/reporte_x'})
    r = OperadorB1(entorno['raiz']).consultar('Muéstrame los viajes con revisión pendiente')
    assert r['estado'] == 'RESULTADO_LECTURA' and r['resultado']['total_viajes'] == 1
    assert r['tablas'][0]['filas'] == [['123', '100 | 101', '']]


def test_no_intercepta_otras_consultas():
    from atlas_core.consulta_revisiones_b1 import _modo
    assert _modo('cuántos viajes tienen revisión este mes') is None
    assert _modo('corrige la revisión de la guía 500001') is None
