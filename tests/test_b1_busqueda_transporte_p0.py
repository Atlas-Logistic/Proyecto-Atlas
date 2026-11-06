from __future__ import annotations
import csv
import json
import subprocess
import sys
from pathlib import Path
import pytest
from atlas_core.responder_consulta_atlas import responder_consulta_atlas
from atlas_core.b1_operador import interpretar_determinista

TRANSPORTE = '0000369009'

def fila(guia='', fecha='05-11-2026', patente='BKYK63', viaje_id='v1'):
    return {'viaje_id': viaje_id, 'numero_transporte': TRANSPORTE, 'transportes_aza': TRANSPORTE,
            'fecha': fecha, 'estado': 'INCOMPLETO_TECNICO', 'numeros_guia': guia,
            'choferes': 'LEANDRO TOLEDO', 'patentes_tracto': patente,
            'documentos_operacionales': json.dumps([{'archivo':'mobile/caso/original.jpg', 'numero_guia':guia}])}

def reporte(tmp_path, filas):
    path = tmp_path / 'viajes.csv'
    with path.open('w', encoding='utf8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]), delimiter=';')
        w.writeheader(); w.writerows(filas)
    return path

@pytest.mark.parametrize('pregunta', [
    'viaje 0000369009', 'busca el viaje 0000369009', 'busca el transporte 0000369009',
    'transporte 0000369009', 'numero de transporte 0000369009', 'muestrame el viaje del transporte 0000369009',
    'viaje 0000369009 fecha 05-11-2026 patente BKYK63',
])
@pytest.mark.parametrize('guia', ['', '484001'])
def test_busqueda_por_transporte_con_y_sin_guia(tmp_path, pregunta, guia):
    p = reporte(tmp_path, [fila(guia), {**fila('484002', viaje_id='otro'), 'numero_transporte':'0000369010', 'transportes_aza':'0000369010'}])
    assert interpretar_determinista(pregunta) is None  # reader delegates to existing travel query
    r = responder_consulta_atlas(pregunta, ruta_viajes=p)
    assert r.estado == 'OK' and r.resultado.total_coincidencias == 1
    assert r.resultado.consulta_interpretada.filtros['numero_transporte'] == TRANSPORTE
    assert r.resultado.viajes_soporte[0]['numeros_guia'] == guia
    if not guia: assert 'documento sin n\u00famero de gu\u00eda disponible' in r.texto_respuesta


def test_no_existe_no_devuelve_universo(tmp_path):
    p = reporte(tmp_path, [fila()])
    r = responder_consulta_atlas('viaje 0000369999', ruta_viajes=p)
    assert r.estado == 'SIN_RESULTADOS' and r.resultado.total_coincidencias == 0


def test_ambiguo_opciones_son_consultas_que_desambiguaran(tmp_path):
    p = reporte(tmp_path, [fila('', '05-11-2026', 'BKYK63'), fila('484001', '06-11-2026', 'ABCD12', 'v2')])
    r = responder_consulta_atlas('transporte 0000369009', ruta_viajes=p)
    assert r.estado == 'AMBIGUA' and len(r.opciones_aclaracion) == 2
    for opcion in r.opciones_aclaracion:
        assert responder_consulta_atlas(opcion, ruta_viajes=p).resultado.total_coincidencias == 1


def test_ambiguo_no_finge_desambiguar_si_faltan_identificadores(tmp_path):
    p = reporte(tmp_path, [fila(), fila(viaje_id='v2')])
    r = responder_consulta_atlas('transporte 0000369009', ruta_viajes=p)
    assert r.estado == 'AMBIGUA' and not r.opciones_aclaracion


def test_cli_mismo_contrato_desktop(tmp_path):
    p = reporte(tmp_path, [fila()])
    cmd = [sys.executable, 'consultar_atlas.py', 'viaje 0000369009', '--viajes', str(p)]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf8')
    r = json.loads(out.stdout)
    assert r['estado'] == 'OK' and r['resultado']['viajes_soporte'][0]['numero_transporte'] == TRANSPORTE
    assert r['resultado']['viajes_soporte'][0]['numeros_guia'] == ''


def test_orden_no_es_interceptada_como_consulta():
    from atlas_core.interpretador_consultas import busqueda_transporte_explicita
    assert busqueda_transporte_explicita('corrige la guia del transporte 0000369009') is None
