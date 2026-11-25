import json

import pytest

from atlas_core.alertas_fecha import alerta_fecha, actualizar_alertas


def fila(fecha='24-11-2020', recepcion='2026-11-24T15:40:24Z'):
    return {'archivo': 'sintetico.jpg', 'numero_guia': '700001', 'fecha': fecha,
            'metricas_procesamiento_json': json.dumps({'fecha_recepcion_utc': recepcion})}


def decision(**cambios):
    return {'tipo': 'CORRECCION_DOCUMENTAL_OPERADOR', 'campo': 'fecha',
            'actor': 'B1', 'confirmado_por': 'JAVIER', 'valor_corregido': '24-11-2020',
            'documento': {'archivo': 'sintetico.jpg'}, **cambios}


def test_solo_alerta_no_cambia_fecha_ni_infiere_anio():
    original = fila()
    copia = dict(original)
    alerta = alerta_fecha(original)
    assert alerta['fecha_documental'] == '24-11-2020'
    assert alerta['diferencia_dias'] == 2191
    assert original == copia


@pytest.mark.parametrize('dato', [fila('24-11-2026'), fila(recepcion='2026-11-24'),
                                    fila('fecha invalida'), fila(recepcion='')])
def test_no_alerta_sin_diferencia_ni_recepcion_valida(dato):
    assert alerta_fecha(dato) is None


def test_solo_confirmacion_humana_de_misma_fecha_y_archivo_suprime_alerta():
    assert alerta_fecha(fila(), [decision()]) is None
    for cambio in ({'actor': 'B1', 'confirmado_por': 'ATLAS_AUTOMATICO'},
                   {'actor': 'ATLAS_AUTOMATICO', 'confirmado_por': ''},
                   {'campo': 'cliente'}, {'valor_corregido': '24-11-2026'},
                   {'documento': {'archivo': 'otro.jpg'}}):
        assert alerta_fecha(fila(), [decision(**cambio)]) is not None


def test_bandeja_idempotente_sin_alterar_otras_guias():
    otra = {'tipo': 'OTRA', 'documento': {'archivo': 'ajena.jpg', 'numero_guia': '700002'}}
    pendientes = actualizar_alertas([fila()], [otra], [])
    assert len(pendientes) == 2
    assert pendientes[1]['tipo'] == 'FECHA_SOSPECHOSA'
    assert actualizar_alertas([fila()], pendientes, []) == pendientes
    assert actualizar_alertas([fila()], pendientes, [decision()]) == [otra]
    assert actualizar_alertas([fila()], pendientes, [], guias_objetivo={'700002'}) == pendientes


def test_no_elige_documentos_o_guias_ambiguos():
    assert actualizar_alertas([fila(), fila()], [], []) == []


def test_reconciliacion_publica_alerta_de_una_guia_focal(tmp_path):
    import csv
    from atlas_core.procesamiento_masivo import COLUMNAS
    from atlas_core.revalidacion_documental import reconciliar_bandeja_decisiones

    raiz = tmp_path / 'atlas'
    actual = raiz / 'operacion' / 'actual'
    cat = raiz / 'catalogos_privados'
    actual.mkdir(parents=True)
    cat.mkdir()
    dataset = actual / 'analisis_completo_guias.csv'
    r = {c: '' for c in COLUMNAS}
    r.update(fila(), estado_procesamiento='OK')
    with dataset.open('w', encoding='utf-8-sig', newline='') as f:
        escritor = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=';')
        escritor.writeheader()
        escritor.writerow(r)
    (actual / 'decisiones_aplicadas.json').write_text('{"aplicaciones": []}', encoding='utf-8')
    reconciliar_bandeja_decisiones(raiz_atlas=raiz, guias_objetivo={'700001'})
    bandeja = json.loads((actual / 'decisiones_pendientes.json').read_text(encoding='utf-8'))
    assert [d['tipo'] for d in bandeja['decisiones'] if d['tipo'] == 'FECHA_SOSPECHOSA'] == ['FECHA_SOSPECHOSA']
