import json
import pytest
from atlas_core.responder_consulta_atlas import responder_consulta_atlas
from tests.test_b1_consulta_adicionales import fuente

@pytest.mark.parametrize('pregunta,total', [
    ('Cuantos viajes tienen adicional', 3),
    ('Cuantos viajes tienen adicional de 575', 0),
    ('Cuantos viajes tienen adicional de 15000 o 30000', 2),
    ('Cuantos viajes tienen adicional de 10 o 12 o 28', 0),
])
def test_adicionales_dinamicos(fuente, pregunta, total):
    raiz, ruta, *_ = fuente
    r = responder_consulta_atlas(pregunta, ruta_viajes=ruta, raiz_atlas=raiz)
    assert r.resultado.resultado == total


def test_pendientes_tecnicos_son_registro_no_estado(fuente):
    raiz, ruta, *_ = fuente
    archivo = raiz/'operacion/actual/pendientes_tecnicos.json'
    archivo.write_text(json.dumps({'pendientes': [{'numero_guia': '1'}, {'numero_guia': '2'}, {'numero_guia': '4'}, {'numero_guia': '999'}]}), encoding='utf-8')
    r = responder_consulta_atlas('Cuantos viajes tienen pendientes tecnicos', ruta_viajes=ruta, raiz_atlas=raiz)
    assert r.resultado.resultado == 2
    assert '1 pendientes no se pudieron' in r.texto_respuesta
    archivo.write_text(json.dumps({'pendientes': []}), encoding='utf-8')
    r = responder_consulta_atlas('Cuantos viajes tienen pendientes tecnicos', ruta_viajes=ruta, raiz_atlas=raiz)
    assert r.resultado.resultado == 0 and 'no demuestra' in r.texto_respuesta
    archivo.unlink()
    assert responder_consulta_atlas('Cuantos viajes tienen pendientes tecnicos', ruta_viajes=ruta, raiz_atlas=raiz).resultado is None


def test_pendientes_registrados_informan_la_cifra_por_estado_sin_mezclarlas(fuente):
    import csv
    raiz, ruta, *_ = fuente
    with ruta.open(encoding='utf-8-sig', newline='') as f:
        filas = list(csv.DictReader(f, delimiter=';'))
    for i, f in enumerate(filas):
        f['estado'] = 'INCOMPLETO_TECNICO' if i < 2 else 'OK'
    with ruta.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]), delimiter=';'); w.writeheader(); w.writerows(filas)
    (raiz/'operacion/actual/pendientes_tecnicos.json').write_text(json.dumps({'pendientes': [{'numero_guia': '1'}]}), encoding='utf-8')
    r = responder_consulta_atlas('Cuantos viajes tienen pendientes tecnicos', ruta_viajes=ruta, raiz_atlas=raiz)
    assert r.resultado.resultado == 1
    assert '2 viajes del reporte estan en estado INCOMPLETO_TECNICO' in r.texto_respuesta
    # Otra forma de la pregunta sigue contando por estado, como antes.
    r = responder_consulta_atlas('cuantos pendientes tecnicos hay?', ruta_viajes=ruta, raiz_atlas=raiz)
    assert r.resultado.consulta_interpretada.filtros == {'estado': 'INCOMPLETO_TECNICO'} and r.resultado.resultado == 2

def test_combinacion_adicional_chofer_fecha_y_dato_ausente(fuente):
    import csv
    raiz, ruta, *_ = fuente
    with ruta.open(encoding='utf-8-sig', newline='') as f:
        filas = list(csv.DictReader(f, delimiter=';'))
    for i, f in enumerate(filas):
        f['choferes'] = 'LUIS VARAS' if i != 1 else 'OTRO CHOFER'
        f['peso_total_viaje_kg'] = '' if i != 2 else '100'
    with ruta.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]), delimiter=';')
        w.writeheader(); w.writerows(filas)
    r = responder_consulta_atlas('Cuantos viajes de Luis Varas el 01-10-2026 sin peso con adicional de 30000', ruta_viajes=ruta, raiz_atlas=raiz)
    assert r.resultado.resultado == 1
    assert r.resultado.viajes_soporte[0]['viaje_id'] == 'v1'
    r = responder_consulta_atlas('Cuantos viajes de NADIE sin peso con adicional de 30000', ruta_viajes=ruta, raiz_atlas=raiz)
    assert r.resultado is None


def test_guias_sin_direccion_no_usa_valor_consolidado(fuente):
    raiz, ruta, *_ = fuente
    r = responder_consulta_atlas('Cuantas guias no tienen direccion', ruta_viajes=ruta, raiz_atlas=raiz)
    assert r.resultado is None and 'por viaje' in r.texto_respuesta

def test_campo_faltante_no_se_inventa_y_no_determinado_es_ausencia(fuente):
    import csv
    raiz, ruta, *_ = fuente
    r = responder_consulta_atlas('Cuantos viajes no tienen material', ruta_viajes=ruta, raiz_atlas=raiz)
    assert r.resultado is None and r.estado == 'FUENTE_NO_DISPONIBLE'
    with ruta.open(encoding='utf-8-sig', newline='') as f:
        filas = list(csv.DictReader(f, delimiter=';'))
    for f in filas:
        f['materiales'] = 'ACERO'
    filas[0]['materiales'] = 'NO DETERMINADO'
    with ruta.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]), delimiter=';'); w.writeheader(); w.writerows(filas)
    r = responder_consulta_atlas('Cuantos viajes tienen material no determinado', ruta_viajes=ruta, raiz_atlas=raiz)
    assert r.resultado.resultado == 1
