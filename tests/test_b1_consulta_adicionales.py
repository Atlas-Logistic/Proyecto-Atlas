"""Consultas de adicionales y observaciones operacionales por el intérprete único.

Datos sintéticos que reproducen las formas reales de las notas (Mobile y
líneas canónicas de B1) del 25/11/2026: guía 485318 «Viaje con retiro de
material en Versalles fuera de aza» (sin monto registrado)."""
import csv
import json

import pytest

from atlas_core.responder_consulta_atlas import responder_consulta_atlas
from atlas_core.soporte_consultas import soporte_semantico


@pytest.fixture
def fuente(tmp_path):
    raiz = tmp_path / 'Atlas'; actual = raiz / 'operacion' / 'actual'; actual.mkdir(parents=True)
    ruta = tmp_path / 'viajes.csv'
    filas = [{'viaje_id': 'v1', 'numero_transporte': 't1', 'fecha': '01-10-2026', 'numeros_guia': '1 | 2'},
             {'viaje_id': 'v2', 'numero_transporte': 't2', 'fecha': '02-10-2026', 'numeros_guia': '3'},
             {'viaje_id': 'v3', 'numero_transporte': 't3', 'fecha': '03-10-2026', 'numeros_guia': '4'}]
    with ruta.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=filas[0].keys(), delimiter=';'); w.writeheader(); w.writerows(filas)

    def event(id, trans, nota):
        return {'estado': 'ACTIVO', 'tipo_evento': 'OBSERVACION_OPERACIONAL', 'naturaleza': 'MARCA_VIAJE',
                'viaje_id': id, 'numero_transporte': trans, 'nota': nota}
    eventos = [event('v1', 't1', 'ESTE VIAJE TIENE ADICIONAL DE $30.000 POR RETIRO'),
               event('v1', 't1', 'ESTE VIAJE TIENE ADICIONAL DE 30 mil'),
               event('v2', 't2', 'VIAJE CON ADICIONAL DE 15 lucas'), event('v3', 't3', 'ADICIONAL DE 45000 PESOS')]

    def guardar(ev):
        (actual / 'eventos_operacionales.json').write_text(json.dumps({'schema_version': 1, 'eventos': ev}), encoding='utf-8')
    guardar(eventos)
    return raiz, ruta, eventos, guardar


def preguntar(fuente, pregunta):
    raiz, ruta, *_ = fuente
    return responder_consulta_atlas(pregunta, ruta_viajes=ruta, raiz_atlas=raiz)


def ids(r):
    return sorted(v['viaje_id'] for v in r.resultado.viajes_soporte)


@pytest.mark.parametrize('monto', ['$30.000', '30000', '30 mil', '30 lucas'])
def test_equivalentes_cuentan_viaje_unico(fuente, monto):
    r = preguntar(fuente, 'Cuantos viajes tienen adicional de ' + monto + '?')
    assert r.estado == 'OK' and r.resultado.resultado == 1 and ids(r) == ['v1']


def test_listado_y_comparaciones(fuente):
    assert ids(preguntar(fuente, 'Lista los viajes con adicional superior a 30 mil')) == ['v3']
    r = preguntar(fuente, 'Cuantos viajes tienen adicional menor que 30 lucas')
    assert r.resultado.resultado == 1 and ids(r) == ['v2']


@pytest.mark.parametrize('nota', ['ADICIONAL DE 30000 POR GUIA', 'ADICIONAL DE 30000 Y ADICIONAL DE 15000',
                                  'ADICIONAL SIN MONTO', 'ADICIONAL DE 30000 O 45000'])
def test_nota_ambigua_en_viaje_confirmado_se_informa_sin_sumarla(fuente, nota):
    raiz, ruta, eventos, guardar = fuente
    eventos.append(dict(eventos[0], nota=nota)); guardar(eventos)
    r = preguntar(fuente, 'Cuantos viajes tienen adicional de 30000')
    assert r.estado == 'OK' and r.resultado.resultado == 1
    assert 'otra observación de adicional sin monto' in r.texto_respuesta
    assert preguntar(fuente, 'cuanto suman los adicionales').resultado.resultado == 30000 + 15000 + 45000


def test_nota_ambigua_en_otro_viaje_queda_pendiente_y_no_bloquea(fuente):
    raiz, ruta, eventos, guardar = fuente
    eventos[2]['nota'] = 'Adicional 30 mil carga en versalles'; guardar(eventos)
    r = preguntar(fuente, 'Cuantos viajes tienen adicional de 30000')
    assert r.resultado.resultado == 1 and ids(r) == ['v1']
    assert 'Además, 1 viaje tiene un adicional pendiente' in r.texto_respuesta and 'declarado $30.000' in r.texto_respuesta
    r = preguntar(fuente, 'viajes con adicional')
    assert r.resultado.consulta_interpretada.metrica == 'LISTAR_VIAJES' and ids(r) == ['v1', 'v2', 'v3']
    assert 'Con monto confirmado: 2' in r.texto_respuesta and 'pendientes de confirmar monto: 1' in r.texto_respuesta
    assert ids(preguntar(fuente, 'viajes con adicional pendiente')) == ['v2']
    assert ids(preguntar(fuente, 'viajes con adicional confirmado')) == ['v1', 'v3']
    r = preguntar(fuente, 'cuánto suman los adicionales')
    assert r.resultado.resultado == 75000 and 'Total de adicionales confirmados: $75.000 en 2 viajes' in r.texto_respuesta


def test_filtros_no_entendidos_no_se_omiten(fuente):
    for pregunta in ('Cuantos viajes tienen adicional de 30000 de Patrick', 'cuantos viajes con retiro en zapallar',
                     'cuantos viajes con zapallo'):
        r = preguntar(fuente, pregunta)
        assert r.resultado is None and r.estado == 'NO_INTERPRETABLE', pregunta


def test_fuente_ausente_y_vinculo_roto_se_informa(fuente):
    raiz, ruta, eventos, guardar = fuente
    r = responder_consulta_atlas('Cuantos viajes tienen adicional de 30000', ruta_viajes=ruta)
    assert r.resultado is None and r.estado == 'FUENTE_NO_DISPONIBLE'
    eventos[0]['viaje_id'] = 'otro'; guardar(eventos)
    r = preguntar(fuente, 'Cuantos viajes tienen adicional de 30000')
    assert r.resultado.resultado == 1  # la otra observación de v1 sí está vinculada
    assert '1 observación con adicional no se pudo vincular' in r.texto_respuesta


def test_archivo_corrupto_no_se_interpreta_como_cero(fuente):
    raiz, *_ = fuente
    (raiz / 'operacion/actual/eventos_operacionales.json').write_text('{', encoding='utf-8')
    r = preguntar(fuente, 'Cuantos viajes tienen adicional de 30000')
    assert r.resultado is None and r.estado == 'FUENTE_NO_DISPONIBLE'
    # Otras consultas no dependen de las observaciones.
    assert preguntar(fuente, 'cuantos viajes hay').resultado.resultado == 3


def test_duplicado_en_reporte_cuenta_una_vez(fuente):
    raiz, ruta, _, _ = fuente
    with ruta.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f, delimiter=';'); fields = reader.fieldnames; filas = list(reader)
    with ruta.open('a', encoding='utf-8', newline='') as f:
        csv.DictWriter(f, fieldnames=fields, delimiter=';').writerow(filas[0])
    assert preguntar(fuente, 'Cuantos viajes tienen un adicional de $30.000').resultado.resultado == 1


def test_13_confirmados_y_observaciones_ambiguas_sin_inferir(tmp_path):
    raiz = tmp_path / 'Atlas'; actual = raiz / 'operacion' / 'actual'; actual.mkdir(parents=True)
    viajes = [{'viaje_id': f'v{i}', 'numero_transporte': f't{i}', 'numeros_guia': str(100 + i)} for i in range(15)]
    ruta = tmp_path / 'viajes.csv'
    with ruta.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(viajes[0]), delimiter=';'); w.writeheader(); w.writerows(viajes)

    def evento(i, nota, eid):
        return {'evento_id': eid, 'estado': 'ACTIVO', 'tipo_evento': 'OBSERVACION_OPERACIONAL', 'naturaleza': 'MARCA_VIAJE',
                'viaje_id': f'v{i}', 'numero_transporte': f't{i}', 'nota': nota}
    eventos = [evento(i, 'ESTE VIAJE TIENE ADICIONAL DE $30.000 POR RETIRO', f'c{i}') for i in range(13)]
    eventos += [evento(0, 'ADICIONAL DE 30000 O 45000', 'a1'), evento(0, 'ADICIONAL SIN MONTO', 'a2'),
                evento(13, 'ADICIONAL DE 30000 POR GUIA', 'a3'), evento(13, 'ADICIONAL DE 30000 Y ADICIONAL DE 15000', 'a4')]
    eventos += [eventos[0], eventos[-1]]
    (actual / 'eventos_operacionales.json').write_text(json.dumps({'schema_version': 1, 'eventos': eventos}), encoding='utf-8')
    r = responder_consulta_atlas('Cuantos viajes tienen adicional de $30.000', ruta_viajes=ruta, raiz_atlas=raiz)
    assert r.resultado.resultado == 13 and len({v['viaje_id'] for v in r.resultado.viajes_soporte}) == 13
    assert 'Además, 1 viaje tiene un adicional pendiente de confirmar monto que no se incluye: guía 113' in r.texto_respuesta
    r = responder_consulta_atlas('cuanto suman los adicionales', ruta_viajes=ruta, raiz_atlas=raiz)
    assert r.resultado.resultado == 13 * 30000


def test_eventos_con_misma_identidad_y_contenido_distinto_no_cuentan(fuente):
    raiz, ruta, eventos, guardar = fuente
    eventos[0]['evento_id'] = 'e1'
    eventos.append(dict(eventos[0], nota='ADICIONAL DE 45000'))
    guardar(eventos)
    assert preguntar(fuente, 'Cuantos viajes tienen adicional de 30000').resultado is None


# --- Casos reales 25/11/2026: Versalles y guía 485318 -----------------------

@pytest.fixture
def operacion(tmp_path):
    raiz = tmp_path / 'Atlas'; actual = raiz / 'operacion' / 'actual'; actual.mkdir(parents=True)
    filas = [
        ('a', '0000365295', '482741', '21-10-2026', 'RENÉ GARCÍA', 'AZA'),
        ('b', '0000370150', '484638', '12-11-2026', 'RODRIGO NAHUELÑIR', 'AZA'),
        ('c', '0000370247', '84685', '12-11-2026', 'JOSE LAZCANO', 'AZA'),
        ('d', '0000371421', '485193', '19-11-2026', 'SALOMÓN PIZARRO', 'AZA'),
        ('e', '0000371709', '485318', '20-11-2026', 'SALOMÓN PIZARRO', 'AZA'),
        ('f', '0000370428', '484771', '13-11-2026', 'RODRIGO NAHUELÑIR', 'AZA'),
        ('g', '0000365998', '483043', '23-10-2026', 'LUIS VARAS', 'AZA'),
        ('h', '0000369487', '488237', '09-11-2026', 'LUIS VARAS', 'AZA'),
        ('i', '0000369999', '488999', '20-11-2026', 'SALOMÓN PIZARRO', 'AZA'),
    ]
    ruta = tmp_path / 'viajes.csv'
    with ruta.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['viaje_id', 'numero_transporte', 'numeros_guia', 'fecha', 'choferes', 'clientes', 'direccion_entrega'])
        for fila in filas:
            w.writerow([*fila, 'AV SIEMPRE VIVA 123'])
    transportes = {x[0]: x[1] for x in filas}
    notas = {
        'a': ('ESTE VIAJE TIENE ADICIONAL DE $30.000 POR RETIRO DE MATERIALES FUERA DE AZA', 'MOBILE:1'),
        'b': ('Adicional 30.000 carga en versalle', 'MOBILE:2'),
        'c': ('Se cargó en. El Versalles ..adisional', 'MOBILE:3'),
        'd': ('Retiro de material en Versalles ,fuera de Aza', 'MOBILE:4'),
        'e': ('Viaje con retiro  de material en Versalles fuera de aza', 'MOBILE:4'),
        'f': ('15 mil adicional x segunda vuelta', 'MOBILE:2'),
        'g': ('ESTE VIAJE TIENE ADICIONAL DE $15.000 POR SEGUNDA VUELTA DEL VIERNES 23/10/2026', 'ACCION_OPERACIONAL:B1'),
        'h': ('Viaje de Aza renca a Aza colina', 'MOBILE:5'),
    }
    eventos = [{'evento_id': f'e-{vid}', 'estado': 'ACTIVO', 'tipo_evento': 'OBSERVACION_OPERACIONAL',
                'naturaleza': 'MARCA_VIAJE', 'viaje_id': vid, 'numero_transporte': transportes[vid],
                'nota': nota, 'procedencias': [{'origen': origen}]} for vid, (nota, origen) in notas.items()]
    eventos.append(dict(eventos[0], evento_id='anulado', viaje_id='i', numero_transporte='0000369999', estado='ANULADO'))
    (actual / 'eventos_operacionales.json').write_text(json.dumps({'schema_version': 1, 'eventos': eventos}), encoding='utf-8')
    return raiz, ruta


def consultar(operacion, pregunta):
    raiz, ruta = operacion
    return responder_consulta_atlas(pregunta, ruta_viajes=ruta, raiz_atlas=raiz)


def guias(r):
    return {v['numeros_guia'] for v in r.resultado.viajes_soporte}


@pytest.mark.parametrize('pregunta', ['Viajes con adicional.', 'viajes con adicional', '¿Qué viajes tienen adicional?',
                                      'muéstrame los viajes con adicionales', 'lista los viajes que tienen un adicional'])
def test_viajes_con_adicional_lista_confirmados_y_pendientes(operacion, pregunta):
    r = consultar(operacion, pregunta)
    assert r.estado == 'OK' and r.resultado.consulta_interpretada.metrica == 'LISTAR_VIAJES'
    assert guias(r) == {'482741', '483043', '484638', '484771', '84685', '485193', '485318'}
    assert 'Con monto confirmado: 2 (total $45.000); pendientes de confirmar monto: 5' in r.texto_respuesta
    assert 'guía 485318 (20-11-2026, SALOMÓN PIZARRO)' in r.texto_respuesta


@pytest.mark.parametrize('pregunta', ['Viajes con adicional por ir a Versalles', 'viajes con adicional por retiro en versalles',
                                      'viajes con adicional por cargar en Versalles', 'viajes con adicional de Versalles'])
def test_adicional_por_motivo_versalles(operacion, pregunta):
    r = consultar(operacion, pregunta)
    assert r.resultado.consulta_interpretada.filtros == {'adicional': 'CUALQUIERA', 'observacion': 'VERSALLES'}
    assert guias(r) == {'484638', '84685', '485193', '485318'}
    assert 'pendientes de confirmar monto: 4' in r.texto_respuesta and 'declarado $30.000' in r.texto_respuesta


@pytest.mark.parametrize('pregunta,metrica', [
    ('Viajes con retiro en Versalles', 'LISTAR_VIAJES'), ('cuantos viajes con retiro en versalles', 'COUNT_VIAJES'),
    ('viajes con retiro de materiales en Versalles', 'LISTAR_VIAJES'), ('viajes que cargaron en versalles', 'LISTAR_VIAJES'),
    ('viajes con observación que diga Versalles', 'LISTAR_VIAJES')])
def test_retiro_en_versalles_filtra_y_nunca_devuelve_todo(operacion, pregunta, metrica):
    r = consultar(operacion, pregunta)
    assert r.resultado.consulta_interpretada.metrica == metrica
    assert r.resultado.consulta_interpretada.filtros == {'observacion': 'VERSALLES'}
    assert guias(r) == {'484638', '84685', '485193', '485318'} and r.resultado.total_coincidencias == 4


def test_filtros_combinados_chofer_fecha_y_motivo(operacion):
    r = consultar(operacion, 'viajes con adicional por retiro en Versalles de Salomón Pizarro del 20-11-2026')
    assert guias(r) == {'485318'} and r.resultado.consulta_interpretada.filtros['chofer'] == 'SALOMÓN PIZARRO'
    r = consultar(operacion, 'cuantos viajes con retiro fuera de AZA de Salomón Pizarro en noviembre')
    assert r.resultado.resultado == 2  # 485193 y 485318; el anulado no cuenta
    r = consultar(operacion, 'cuanto suman los adicionales de Rodrigo Nahuelñir')
    assert r.resultado.resultado == 0 and 'Total de adicionales confirmados: $0' in r.texto_respuesta
    assert 'guía 484638 (12-11-2026, RODRIGO NAHUELÑIR, declarado $30.000)' in r.texto_respuesta
    assert 'guía 484771 (13-11-2026, RODRIGO NAHUELÑIR, declarado $15.000)' in r.texto_respuesta


def test_adicional_por_segunda_vuelta_y_suma_sin_duplicar(operacion):
    r = consultar(operacion, 'viajes con adicional por segunda vuelta')
    assert guias(r) == {'483043', '484771'}
    r = consultar(operacion, 'cuánto suman los adicionales')
    assert r.resultado.resultado == 45000 and r.resultado.consulta_interpretada.metrica == 'SUM_ADICIONAL'
    r = consultar(operacion, 'total de adicionales por chofer')
    assert {f['grupo']: f['valor'] for f in r.resultado.resultado} == {
        'RENÉ GARCÍA': 30000.0, 'LUIS VARAS': 15000.0, 'RODRIGO NAHUELÑIR': 0.0, 'JOSE LAZCANO': 0.0, 'SALOMÓN PIZARRO': 0.0}


def test_guia_485318_figura_como_pendiente_de_monto_y_no_como_confirmada(operacion):
    r = consultar(operacion, 'viajes con adicional de 30.000')
    assert guias(r) == {'482741'}
    assert 'guía 485318 (20-11-2026, SALOMÓN PIZARRO)' in r.texto_respuesta.split('Además,')[1]
    soporte = soporte_semantico(consultar(operacion, 'viajes con adicional pendiente').resultado)
    fila = next(f for f in soporte['filas'] if f[2] == '485318')
    assert soporte['columnas'][-4:] == ['Adicional', 'Monto', 'Origen', 'Observación']
    assert fila[-4:-1] == ['Pendiente de confirmar monto', 'Sin monto', 'Mobile']
    assert 'Versalles' in fila[-1]


@pytest.mark.parametrize('pregunta', ['viajes con retiro en Marte', 'cuantos viajes con retiro en marte',
                                      'viajes con adicional por ir a Marte', 'cuantos viajes con zapallo',
                                      'viajes del martes'])
def test_sin_coincidencias_nunca_responde_con_el_total(operacion, pregunta):
    r = consultar(operacion, pregunta)
    assert r.resultado is None and r.estado == 'NO_INTERPRETABLE', (pregunta, r.texto_respuesta)


def test_combinacion_sin_coincidencias_es_cero_no_total(operacion):
    r = consultar(operacion, 'viajes con adicional por retiro en Versalles de René García')
    assert r.estado == 'SIN_RESULTADOS' and r.resultado.total_coincidencias == 0
    assert 'No encontré viajes con adicional' in r.texto_respuesta


def test_monto_aprobado_por_persona_confirma(operacion):
    raiz, _ = operacion
    ruta = raiz / 'operacion/actual/eventos_operacionales.json'
    documento = json.loads(ruta.read_text(encoding='utf-8'))
    for e in documento['eventos']:
        if e['viaje_id'] == 'e':
            e['monto_aprobado'] = 30000
    ruta.write_text(json.dumps(documento), encoding='utf-8')
    r = consultar(operacion, 'viajes con adicional de 30 mil')
    assert guias(r) == {'482741', '485318'}

def test_soporte_entrega_observacion_completa_sin_recorte():
    from atlas_core.soporte_consultas import _soporte_observaciones
    observacion = 'Texto de observación ' * 20 + 'final íntegro'
    soporte = _soporte_observaciones([{'_observaciones_texto': observacion}])
    assert soporte['filas'][0][-1] == observacion
