"""Corrección de origen determinada, solo con datos sintéticos."""
import json
import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.b1_operador import OperadorB1
from tests.test_acciones_operacionales import _EscritorDisponible
from tests import test_origen_no_confirmado as origen
from tests.test_b1_campos_documentales import _filas, _huellas


@pytest.fixture
def entorno(tmp_path):
    e = origen._entorno(tmp_path)
    fila = origen._fila_csv(planta_origen_id=e['planta_colina'].planta_id,
        planta_origen_nombre='AZA COLINA', origen_determinado_por='DOCUMENTO',
        evidencia_origen='ENCABEZADO', distancia_km='33', estado_ruta='RUTA_CALCULADA',
        motivo_origen_gps='evidencia sintetica')
    origen._escribir_csv(e['dataset'], [fila])
    (e['catalogos'] / 'choferes.json').write_text('{}', encoding='utf-8')
    (e['catalogos'] / 'rutas.json').write_text('{"rutas": []}', encoding='utf-8')
    (e['actual'] / 'decisiones_aplicadas.json').write_text('{"schema_version":1,"aplicaciones":[]}', encoding='utf-8')
    e['capa'] = CapaAccionesOperacionales(e['raiz'], fabrica_escritor=lambda: _EscritorDisponible())
    e['b1'] = OperadorB1(e['raiz'], capa=e['capa'])
    return e


def test_preview_confirmacion_auditoria_y_ruta_invalidada(entorno, monkeypatch):
    from atlas_core import revalidacion_documental as r
    e = entorno
    llamadas = []
    monkeypatch.setattr(r, 'revalidar_ruta_sin_destino_calculado_sin_ocr',
                        lambda **kw: llamadas.append(kw['guias_objetivo']) or {})
    antes = _huellas(e['raiz'])
    preview = e['b1'].atender('p', 'La planta de origen de la guía 464900 es Renca')
    assert preview['estado'] == 'PREVIEW_PENDIENTE', preview
    assert 'Empresa: mbt' in preview['mensaje'] and 'AZA COLINA' in preview['mensaje']
    assert 'AZA RENCA' in preview['mensaje'] and 'ruta' in preview['mensaje']
    assert _huellas(e['raiz']) == antes
    resultado = e['b1'].atender('p', 'sí')
    assert resultado['estado'] == 'EJECUTADA', resultado
    fila = _filas(e['dataset'])['464900.jpeg']
    assert fila['planta_origen_nombre'] == 'AZA RENCA'
    assert fila['distancia_km'] == '' and fila['origen_determinado_por'] == 'CONFIRMACION_HUMANA'
    assert fila['motivo_origen_gps'] == 'evidencia sintetica'
    assert llamadas == [{'464900'}]
    ledger = json.loads((e['actual'] / 'decisiones_aplicadas.json').read_text(encoding='utf-8'))['aplicaciones']
    [entrada] = [a for a in ledger if a.get('tipo') == 'CORRECCION_ORIGEN_OPERACIONAL']
    assert entrada['confirmado_por'] == 'JAVIER' and entrada['evidencia_anterior'] == 'ENCABEZADO'
    assert e['capa'].auditoria()[-1]['resultado'] == 'APLICADA'


@pytest.mark.parametrize('conflicto', ['evento', 'duplicada', 'agrupacion', 'eventos_ilegibles', 'agrupaciones_invalidas'])
def test_bloquea_inconsistencias(entorno, conflicto):
    e = entorno
    fila = list(_filas(e['dataset']).values())[0]
    if conflicto == 'duplicada':
        origen._escribir_csv(e['dataset'], [fila, origen._fila_csv(archivo='otra.jpeg')])
    elif conflicto == 'evento':
        (e['actual'] / 'eventos_operacionales.json').write_text(json.dumps({'eventos': [
            {'estado': 'ACTIVO', 'numero_transporte': fila['numero_transporte'], 'tipo_evento': 'DOBLE_VUELTA',
             'vinculo_completo': False, 'numeros_guia': []}]}), encoding='utf-8')
    elif conflicto == 'agrupacion':
        (e['actual'] / 'agrupaciones_viaje.json').write_text(json.dumps({'schema_version': 1, 'agrupaciones': [
            {'estado': 'ACTIVA', 'transportes': [fila['numero_transporte'], '0000000901']}]}), encoding='utf-8')
    elif conflicto == 'eventos_ilegibles':
        (e['actual'] / 'eventos_operacionales.json').write_text('{"eventos": "invalido"}', encoding='utf-8')
    else:
        (e['actual'] / 'agrupaciones_viaje.json').write_text('{"schema_version":1,"agrupaciones":null}', encoding='utf-8')
    antes = _huellas(e['raiz'])
    r = e['b1'].atender('p', 'La planta de origen de la guía 464900 es Renca')
    assert r['estado'] == 'ACLARACION_REQUERIDA', r
    assert _huellas(e['raiz']) == antes


def test_requiere_confirmacion_humana(entorno):
    e = entorno
    p = e['capa'].previsualizar('DOCUMENTO_CORREGIR_PLANTA_ORIGEN',
        {'numero_guia': '464900', 'planta_id': e['planta_renca'].planta_id}, actor='B1')
    assert p['estado'] == 'PREVIEW'
    antes = _huellas(e['raiz'])
    r = e['capa'].ejecutar(p['token'], actor='B1', confirmado_por='ATLAS_AUTOMATICO')
    assert r['codigo'] == 'CONFIRMACION_REQUERIDA'
    assert _huellas(e['raiz']) == antes


def test_evento_agregado_tras_preview_bloquea_confirmacion(entorno):
    e = entorno
    p = e['capa'].previsualizar('DOCUMENTO_CORREGIR_PLANTA_ORIGEN',
        {'numero_guia': '464900', 'planta_id': e['planta_renca'].planta_id}, actor='B1')
    (e['actual'] / 'eventos_operacionales.json').write_text(json.dumps({'eventos': [
        {'estado': 'ACTIVO', 'numero_transporte': '0000000900', 'numeros_guia': ['999999']}]}), encoding='utf-8')
    antes = _huellas(e['raiz'])
    r = e['capa'].ejecutar(p['token'], actor='B1', confirmado_por='JAVIER')
    assert r['codigo'] == 'PRECONDICION_FALLIDA'
    assert _huellas(e['raiz']) == antes


def test_error_de_recalculo_restaura_dataset_y_ledger(entorno, monkeypatch):
    from atlas_core import revalidacion_documental as r
    e = entorno
    def falla(**kw):
        raise ValueError('fallo sintetico de ruta')
    monkeypatch.setattr(r, 'revalidar_ruta_sin_destino_calculado_sin_ocr', falla)
    p = e['capa'].previsualizar('DOCUMENTO_CORREGIR_PLANTA_ORIGEN',
        {'numero_guia': '464900', 'planta_id': e['planta_renca'].planta_id}, actor='B1')
    antes = _huellas(e['raiz'])
    resultado = e['capa'].ejecutar(p['token'], actor='B1', confirmado_por='JAVIER')
    assert resultado['estado'] == 'FALLIDA' and resultado['respaldo_restaurado']
    assert _huellas(e['raiz']) == antes


def test_corte_durante_publicacion_bloquea_lectura_y_muestra_traza(entorno, monkeypatch):
    from atlas_core import revalidacion_documental as r
    from atlas_core.acciones_operacionales import publicacion_documental_incompleta
    e = entorno
    def cortar(**kw):
        raise KeyboardInterrupt()
    monkeypatch.setattr(r, 'revalidar_ruta_sin_destino_calculado_sin_ocr', cortar)
    p = e['capa'].previsualizar('DOCUMENTO_CORREGIR_PLANTA_ORIGEN',
        {'numero_guia': '464900', 'planta_id': e['planta_renca'].planta_id}, actor='B1')
    with pytest.raises(KeyboardInterrupt):
        e['capa'].ejecutar(p['token'], actor='B1', confirmado_por='JAVIER')
    assert publicacion_documental_incompleta(e['raiz'])
    inspeccion = e['capa'].inspeccionar_publicacion_interrumpida(p['token'])
    assert inspeccion['estado'] == 'INTERRUMPIDA' and inspeccion['entradas_ledger'] == 1


def test_si_reporte_falla_no_se_publica_como_operacion_completa(entorno, monkeypatch):
    from atlas_core import revalidacion_documental as r
    from atlas_core.acciones_operacionales import publicacion_documental_incompleta
    e = entorno
    monkeypatch.setattr(r, 'revalidar_ruta_sin_destino_calculado_sin_ocr', lambda **kw: {})
    monkeypatch.setattr(e['capa'], '_regenerar_reporte', lambda: {'regenerado': False, 'error': 'sintetico'})
    p = e['capa'].previsualizar('DOCUMENTO_CORREGIR_PLANTA_ORIGEN',
        {'numero_guia': '464900', 'planta_id': e['planta_renca'].planta_id}, actor='B1')
    resultado = e['capa'].ejecutar(p['token'], actor='B1', confirmado_por='JAVIER')
    assert resultado['codigo'] == 'PUBLICACION_INCOMPLETA'
    assert publicacion_documental_incompleta(e['raiz'])


def test_error_de_bandeja_bloquea_antes_de_publicar_reporte(entorno, monkeypatch):
    from atlas_core import revalidacion_documental as r
    from atlas_core.acciones_operacionales import publicacion_documental_incompleta
    e = entorno
    monkeypatch.setattr(r, 'revalidar_ruta_sin_destino_calculado_sin_ocr', lambda **kw: {})
    monkeypatch.setattr(e['capa'], '_reconciliar', lambda **kw: {'ejecutado': False, 'motivo': 'ERROR_RECONCILIACION'})
    reportes = []
    monkeypatch.setattr(e['capa'], '_regenerar_reporte', lambda: reportes.append(True))
    p = e['capa'].previsualizar('DOCUMENTO_CORREGIR_PLANTA_ORIGEN',
        {'numero_guia': '464900', 'planta_id': e['planta_renca'].planta_id}, actor='B1')
    resultado = e['capa'].ejecutar(p['token'], actor='B1', confirmado_por='JAVIER')
    assert resultado['codigo'] == 'PUBLICACION_INCOMPLETA' and not reportes
    assert publicacion_documental_incompleta(e['raiz'])


def test_recorrido_real_sin_destino_deja_ruta_pendiente_y_original_intacto(entorno):
    from atlas_core.rutas.proveedor import ProveedorRutasSimulado
    e = entorno
    original = e['raiz'] / 'documento-sintetico.jpg'
    original.write_bytes(b'foto y lectura simuladas intactas')
    e['capa'] = CapaAccionesOperacionales(e['raiz'], proveedor_rutas=ProveedorRutasSimulado(),
                                         fabrica_escritor=lambda: _EscritorDisponible())
    p = e['capa'].previsualizar('DOCUMENTO_CORREGIR_PLANTA_ORIGEN',
        {'numero_guia': '464900', 'planta_id': e['planta_renca'].planta_id}, actor='B1')
    resultado = e['capa'].ejecutar(p['token'], actor='B1', confirmado_por='JAVIER')
    assert resultado['estado'] == 'APLICADA', resultado
    fila = _filas(e['dataset'])['464900.jpeg']
    assert fila['planta_origen_nombre'] == 'AZA RENCA'
    assert not fila['distancia_km'] and fila['estado_ruta'] != 'RUTA_CALCULADA'
    assert original.read_bytes() == b'foto y lectura simuladas intactas'


def test_sin_escritor_no_hay_escrituras(entorno):
    e = entorno
    e['capa'] = CapaAccionesOperacionales(e['raiz'], fabrica_escritor=lambda: None)
    p = e['capa'].previsualizar('DOCUMENTO_CORREGIR_PLANTA_ORIGEN',
        {'numero_guia': '464900', 'planta_id': e['planta_renca'].planta_id}, actor='B1')
    antes = _huellas(e['raiz'])
    r = e['capa'].ejecutar(p['token'], actor='B1', confirmado_por='JAVIER')
    assert r['codigo'] == 'ESCRITOR_NO_DISPONIBLE' and _huellas(e['raiz']) == antes


def test_empresa_cruzada_y_planta_ajena_son_rechazadas(entorno, monkeypatch):
    e = entorno
    parametros = {'numero_guia': '464900', 'planta_id': e['planta_renca'].planta_id}
    antes = _huellas(e['raiz'])
    monkeypatch.setenv('ATLAS_EMPRESA_ID', 'otra-empresa')
    r = e['capa'].previsualizar('DOCUMENTO_CORREGIR_PLANTA_ORIGEN', parametros, actor='B1')
    assert r['codigo'] == 'EMPRESA_INCOMPATIBLE'
    monkeypatch.delenv('ATLAS_EMPRESA_ID')
    r = e['capa'].previsualizar('DOCUMENTO_CORREGIR_PLANTA_ORIGEN',
        {**parametros, 'planta_id': 'planta-no-existente'}, actor='B1')
    assert r['codigo'] == 'ENTIDAD_NO_ENCONTRADA' and _huellas(e['raiz']) == antes


def test_b1_cancelar_no_escribe(entorno):
    e = entorno
    antes = _huellas(e['raiz'])
    assert e['b1'].atender('p', 'La planta de origen de la guía 464900 es Renca')['estado'] == 'PREVIEW_PENDIENTE'
    assert e['b1'].atender('p', 'no')['estado'] == 'CANCELADA'
    assert _huellas(e['raiz']) == antes


def test_intenta_ruta_con_la_nueva_planta_sin_reutilizar_distancia(entorno):
    from atlas_core.rutas.modelos import Coordenadas, EstadoRuta, CandidatoGeocodificacion, ResultadoGeocodificacion
    from atlas_core.rutas.proveedor import ProveedorRutasSimulado
    e = entorno
    fila = list(_filas(e['dataset']).values())[0]
    fila['despachar_a_crudo'] = 'AV EJEMPLO 123 QUILICURA'
    origen._escribir_csv(e['dataset'], [fila])
    class Proveedor(ProveedorRutasSimulado):
        origenes = None
        def geocodificar(self, direccion):
            self.llamadas_geocodificacion += 1
            return ResultadoGeocodificacion(EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(Coordenadas(-70.7, -33.4),
                    'AV EJEMPLO 123 QUILICURA CHILE', 0.99, localidad='QUILICURA', region='RM'),), '')
        def calcular_ruta(self, origen, destino, perfil):
            self.origenes = (self.origenes or []) + [origen]
            return super().calcular_ruta(origen, destino, perfil)
    proveedor = Proveedor()
    e['capa'] = CapaAccionesOperacionales(e['raiz'], proveedor_rutas=proveedor,
                                         fabrica_escritor=lambda: _EscritorDisponible())
    p = e['capa'].previsualizar('DOCUMENTO_CORREGIR_PLANTA_ORIGEN',
        {'numero_guia': '464900', 'planta_id': e['planta_renca'].planta_id}, actor='B1')
    resultado = e['capa'].ejecutar(p['token'], actor='B1', confirmado_por='JAVIER')
    assert resultado['estado'] == 'APLICADA', resultado
    fila = _filas(e['dataset'])['464900.jpeg']
    assert proveedor.llamadas_geocodificacion > 0
    assert proveedor.llamadas_ruta > 0
    assert Coordenadas(-70.9, -33.75) in proveedor.origenes
    assert fila['distancia_km'] == '12.5' and fila['estado_ruta'] == 'RUTA_CALCULADA'


# --- Viaje de varias guías, eventos, tarjetas y reporte (Claude Code) -------------

def _dos_guias(e, **extra):
    fila = list(_filas(e['dataset']).values())[0]
    hermana = origen._fila_csv(archivo='464901.jpeg', numero_guia='464901',
        planta_origen_id=e['planta_colina'].planta_id, planta_origen_nombre='AZA COLINA',
        origen_determinado_por='DOCUMENTO_HERMANO_MISMO_TRANSPORTE', evidencia_origen='MISMO_TRANSPORTE=0000000900',
        distancia_km='35', estado_ruta='RUTA_CALCULADA', **extra)
    otro_viaje = origen._fila_csv(archivo='464950.jpeg', numero_guia='464950', numero_transporte='0000000950',
        planta_origen_id=e['planta_colina'].planta_id, planta_origen_nombre='AZA COLINA',
        origen_determinado_por='TELEMETRIA_GPS', distancia_km='20', estado_ruta='RUTA_CALCULADA')
    origen._escribir_csv(e['dataset'], [fila, hermana, otro_viaje])
    return fila, hermana, otro_viaje


def test_viaje_de_varias_guias_cambia_completo_y_no_toca_otro_viaje(entorno, monkeypatch):
    from atlas_core import revalidacion_documental as r
    e = entorno
    _, _, otro = _dos_guias(e)
    llamadas = []
    monkeypatch.setattr(r, 'revalidar_ruta_sin_destino_calculado_sin_ocr',
                        lambda **kw: llamadas.append(kw['guias_objetivo']) or {})
    antes = _huellas(e['raiz'])
    preview = e['b1'].atender('p', 'La planta de origen de la guía 464901 es Renca')
    assert preview['estado'] == 'PREVIEW_PENDIENTE', preview
    assert '2 guías (464900, 464901)' in preview['mensaje']
    assert 'Guía 464900: AZA COLINA → AZA RENCA' in preview['mensaje'] and '(33 km)' in preview['mensaje']
    assert 'Guía 464901: AZA COLINA → AZA RENCA' in preview['mensaje'] and '(35 km)' in preview['mensaje']
    assert preview['preview']['afectados']['total_guias'] == 2
    assert _huellas(e['raiz']) == antes
    assert e['b1'].atender('p', 'sí')['estado'] == 'EJECUTADA'
    filas = _filas(e['dataset'])
    for archivo in ('464900.jpeg', '464901.jpeg'):
        assert filas[archivo]['planta_origen_nombre'] == 'AZA RENCA'
        assert filas[archivo]['origen_determinado_por'] == 'CONFIRMACION_HUMANA'
        assert filas[archivo]['distancia_km'] == ''
    assert filas['464950.jpeg'] == otro
    assert llamadas == [{'464900', '464901'}]
    ledger = json.loads((e['actual'] / 'decisiones_aplicadas.json').read_text(encoding='utf-8'))['aplicaciones']
    [entrada] = [a for a in ledger if a.get('tipo') == 'CORRECCION_ORIGEN_OPERACIONAL']
    assert entrada['documento']['numero_guia'] == '464901'
    previos = {d['numero_guia']: d for d in entrada['documentos_viaje']}
    assert previos['464901']['origen_determinado_por'] == 'DOCUMENTO_HERMANO_MISMO_TRANSPORTE'
    assert previos['464901']['evidencia_origen'] == 'MISMO_TRANSPORTE=0000000900'
    assert previos['464900']['distancia_km'] == '33' and previos['464901']['distancia_km'] == '35'


# El destino confirmado ya no bloquea: ver tests/test_b1_origen_destino_confirmado.py


def test_revision_de_origen_pendiente_en_el_viaje_bloquea_la_via_directa(entorno):
    from atlas_core.decisiones_pendientes import detectar_decision_origen_no_confirmado
    e = entorno
    fila = list(_filas(e['dataset']).values())[0]
    pendiente = origen._fila_csv(archivo='464901.jpeg', numero_guia='464901',
        motivo_origen_gps='DETENCION_REAL_FUERA_DE_TODA_GEOCERCA;duracion_min=287.7;trips=t1|t2',
        latitud_estadia_gps=str(origen.COORD_COLINA[0] + 0.01), longitud_estadia_gps=str(origen.COORD_COLINA[1] + 0.01),
        duracion_estadia_gps_min='287.7')
    origen._escribir_csv(e['dataset'], [fila, pendiente])
    decision = detectar_decision_origen_no_confirmado(archivo='464901.jpeg', fila=pendiente,
                                                      plantas=[e['planta_colina'], e['planta_renca']])
    assert decision is not None
    origen._publicar_decision(e, decision)
    antes = _huellas(e['raiz'])
    r = e['capa'].previsualizar('DOCUMENTO_CORREGIR_PLANTA_ORIGEN',
        {'numero_guia': '464900', 'planta_id': e['planta_renca'].planta_id}, actor='B1')
    assert r['codigo'] == 'PRECONDICION_FALLIDA' and 'revisión de origen pendiente' in r['mensaje'], r
    assert _huellas(e['raiz']) == antes


@pytest.mark.parametrize('transporte', ['No encontrado', ''])
def test_transporte_no_valido_no_agrupa_documentos_sueltos(entorno, transporte):
    e = entorno
    fila = list(_filas(e['dataset']).values())[0]
    fila['numero_transporte'] = transporte
    otra = origen._fila_csv(archivo='464960.jpeg', numero_guia='464960', numero_transporte=transporte,
                            planta_origen_id=e['planta_colina'].planta_id, planta_origen_nombre='AZA COLINA')
    origen._escribir_csv(e['dataset'], [fila, otra])
    antes = _huellas(e['raiz'])
    r = e['capa'].previsualizar('DOCUMENTO_CORREGIR_PLANTA_ORIGEN',
        {'numero_guia': '464900', 'planta_id': e['planta_renca'].planta_id}, actor='B1')
    assert r['codigo'] == 'PRECONDICION_FALLIDA' and 'transporte' in r['mensaje'], r
    assert _huellas(e['raiz']) == antes


def test_eventos_consistentes_se_conservan_y_se_informan(entorno, monkeypatch):
    from atlas_core import revalidacion_documental as r
    e = entorno
    monkeypatch.setattr(r, 'revalidar_ruta_sin_destino_calculado_sin_ocr', lambda **kw: {})
    eventos = e['actual'] / 'eventos_operacionales.json'
    eventos.write_text(json.dumps({'eventos': [
        {'estado': 'ACTIVO', 'numero_transporte': '0000000900', 'tipo_evento': 'TIENE_ESTADIA',
         'numeros_guia': ['464900'], 'vinculo_completo': True},
        {'estado': 'ANULADO', 'numero_transporte': '0000000900', 'tipo_evento': 'DOBLE_VUELTA',
         'vinculo_completo': False}]}), encoding='utf-8')
    contenido = eventos.read_bytes()
    preview = e['b1'].atender('p', 'La planta de origen de la guía 464900 es Renca')
    assert preview['estado'] == 'PREVIEW_PENDIENTE', preview
    assert 'Se conservan los eventos del viaje: TIENE_ESTADIA.' in preview['mensaje']
    assert e['b1'].atender('p', 'sí')['estado'] == 'EJECUTADA'
    assert eventos.read_bytes() == contenido


def test_origen_confirmado_antes_por_persona_se_advierte(entorno):
    e = entorno
    fila = list(_filas(e['dataset']).values())[0]
    fila.update(origen_determinado_por='CONFIRMACION_HUMANA', evidencia_origen='DECISION_HUMANA:abc')
    origen._escribir_csv(e['dataset'], [fila])
    p = e['capa'].previsualizar('DOCUMENTO_CORREGIR_PLANTA_ORIGEN',
        {'numero_guia': '464900', 'planta_id': e['planta_renca'].planta_id}, actor='B1')
    assert p['estado'] == 'PREVIEW'
    assert any('confirmado antes por una persona en la guía 464900' in c for c in p['consecuencias'])


def test_misma_planta_ya_confirmada_no_requiere_cambios(entorno):
    e = entorno
    fila = list(_filas(e['dataset']).values())[0]
    fila.update(origen_determinado_por='CONFIRMACION_HUMANA')
    origen._escribir_csv(e['dataset'], [fila])
    r = e['b1'].atender('p', 'La planta de origen de la guía 464900 es Colina')
    assert r['estado'] == 'SIN_CAMBIOS', r


def test_hermana_cambiada_tras_preview_bloquea_confirmacion(entorno):
    e = entorno
    _dos_guias(e)
    p = e['capa'].previsualizar('DOCUMENTO_CORREGIR_PLANTA_ORIGEN',
        {'numero_guia': '464900', 'planta_id': e['planta_renca'].planta_id}, actor='B1')
    filas = list(_filas(e['dataset']).values())
    filas[1]['distancia_km'] = '36'
    origen._escribir_csv(e['dataset'], filas)
    antes = _huellas(e['raiz'])
    r = e['capa'].ejecutar(p['token'], actor='B1', confirmado_por='JAVIER')
    assert r['estado'] != 'APLICADA' and _huellas(e['raiz']) == antes, r


def test_recorrido_completo_publica_el_nuevo_origen_en_el_reporte(entorno):
    import csv
    from atlas_core.rutas.proveedor import ProveedorRutasSimulado
    e = entorno
    _dos_guias(e)
    e['capa'] = CapaAccionesOperacionales(e['raiz'], proveedor_rutas=ProveedorRutasSimulado(),
                                         fabrica_escritor=lambda: _EscritorDisponible())
    p = e['capa'].previsualizar('DOCUMENTO_CORREGIR_PLANTA_ORIGEN',
        {'numero_guia': '464900', 'planta_id': e['planta_renca'].planta_id}, actor='B1')
    resultado = e['capa'].ejecutar(p['token'], actor='B1', confirmado_por='JAVIER')
    assert resultado['estado'] == 'APLICADA', resultado
    estado = json.loads((e['actual'] / 'estado_operacion.json').read_text(encoding='utf-8-sig'))
    with (e['raiz'] / estado['reporte_vigente'] / 'viajes.csv').open(encoding='utf-8-sig', newline='') as f:
        viajes = {v['numero_transporte']: v for v in csv.DictReader(f, delimiter=';')}
    assert viajes['0000000900']['planta_origen_nombre'] == 'AZA RENCA'
    assert viajes['0000000950']['planta_origen_nombre'] == 'AZA COLINA'
    bandeja = e['actual'] / 'decisiones_pendientes.json'
    pendientes = json.loads(bandeja.read_text(encoding='utf-8')).get('decisiones', []) if bandeja.exists() else []
    assert not [d for d in pendientes if d.get('tipo') == 'ORIGEN_NO_CONFIRMADO']
    assert e['capa'].auditoria()[-1]['resultado'] == 'APLICADA'
