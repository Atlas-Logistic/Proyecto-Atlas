import copy
import json
from types import SimpleNamespace as NS

import pytest

from atlas_core.fichas_choferes import (
    preparar_almacen, leer_almacen, ruta_almacen, fichas_por_referencia,
    asignaciones_de_chofer, inicializar_almacen,
)
from atlas_core.catalogo_fichas import construir_ficha_chofer


CATALOGO = {'123456785': {'nombre': 'ANA TEST', 'activo': True, 'aliases': ['ANA ALIAS']},
            'PENDIENTE00000006': {'nombre': 'CHOFER TEMPORAL', 'activo': False}}


def test_uuid_persistente_no_depende_de_nombre_rut_ni_estado():
    base = preparar_almacen(None, CATALOGO, empresa='MBT')
    otro = copy.deepcopy(CATALOGO)
    otro['123456785'].update(nombre='NOMBRE CORREGIDO', rut='11.111.111-1', activo=False)
    assert preparar_almacen(base, otro, empresa='MBT') == base
    assert preparar_almacen(base, otro, empresa='MBT')['revision'] == 1
    assert len({f['ficha_id'] for f in base['choferes']}) == 2
    assert not {'nombre', 'rut', 'activo', 'aliases'} & set(base['choferes'][0])


def test_cambio_de_clave_explicito_conserva_uuid_contacto_documentos_e_historial():
    base = preparar_almacen(None, CATALOGO, empresa='MBT')
    anterior = fichas_por_referencia(base)['PENDIENTE00000006']
    anterior['complementarios']['contacto']['telefono'] = '+56912345678'
    anterior['documentos'].append({'documento_id': 'doc-test', 'tipo': 'LICENCIA_CONDUCIR', 'vencimiento': '2027-01-01'})
    catalogo = {'123456785': CATALOGO['123456785'], '111111111': {'nombre': 'CHOFER TEMPORAL', 'activo': False}}
    with pytest.raises(ValueError, match='vínculo explícito'):
        preparar_almacen(base, catalogo, empresa='MBT')
    nueva = preparar_almacen(base, catalogo, empresa='MBT', vinculos={'PENDIENTE00000006': '111111111'})
    despues = fichas_por_referencia(nueva)['111111111']
    assert despues['ficha_id'] == anterior['ficha_id']
    assert despues['complementarios'] == anterior['complementarios']
    assert despues['documentos'] == anterior['documentos']
    assert despues['historial'][-1]['accion'] == 'VINCULAR_REFERENCIA'
    assert len(nueva['choferes']) == 2
    assert preparar_almacen(nueva, catalogo, empresa='MBT') == nueva


def test_no_fusiona_personas_con_mismo_nombre_ni_dos_referencias_existentes():
    catalogo = {k: {**v, 'nombre': 'MISMO NOMBRE'} for k, v in CATALOGO.items()}
    base = preparar_almacen(None, catalogo, empresa='MBT')
    assert len({f['ficha_id'] for f in base['choferes']}) == 2
    with pytest.raises(ValueError):
        preparar_almacen(base, catalogo, empresa='MBT', vinculos={'123456785': 'PENDIENTE00000006'})


def test_seis_claves_temporales_permanecen_vinculables():
    catalogo = {f'PENDIENTE{i:08d}': {'nombre': f'CHOFER {i}', 'activo': True} for i in range(1, 7)}
    datos = preparar_almacen(None, catalogo, empresa='MBT')
    assert set(fichas_por_referencia(datos)) == set(catalogo)
    assert len({f['ficha_id'] for f in datos['choferes']}) == 6


def test_migracion_v1_conserva_documentos_vehiculos_plazos_y_no_adivina_identidades():
    legacy = {'version': 1, 'empresa': 'MBT', 'plazos_alerta_dias': {'LICENCIA_CONDUCIR': 45},
              'choferes': [{'rut': '12.345.678-5', 'documentos': [{'tipo': 'LICENCIA_CONDUCIR', 'clase': 'A5',
                            'archivo': 'archivos/licencia.pdf', 'vencimiento': '2028-01-01'}]},
                           {'rut': '99.999.999-9', 'documentos': [{'tipo': 'LICENCIA_CONDUCIR'}]}],
              'vehiculos': [{'patente': 'ZZ0001', 'documentos': []}]}
    original = copy.deepcopy(legacy)
    nueva = preparar_almacen(legacy, CATALOGO, empresa='MBT')
    assert legacy == original
    assert nueva['version'] == 2
    assert nueva['vehiculos'] == legacy['vehiculos']
    assert nueva['plazos_alerta_dias'] == legacy['plazos_alerta_dias']
    assert fichas_por_referencia(nueva)['123456785']['documentos'][0]['clase'] == 'A5'
    assert nueva['choferes_legacy_sin_vincular'] == [legacy['choferes'][1]]


def test_empresas_independientes_y_lectura_sin_escrituras(tmp_path):
    assert leer_almacen(tmp_path, empresa='MBT') is None
    assert not (tmp_path / 'fichas_digitales').exists()
    a = preparar_almacen(None, CATALOGO, empresa='MBT')
    b = preparar_almacen(None, CATALOGO, empresa='OTRA')
    assert a['choferes'][0]['ficha_id'] != b['choferes'][0]['ficha_id']
    for empresa, datos in [('MBT', a), ('OTRA', b)]:
        ruta = ruta_almacen(tmp_path, empresa); ruta.parent.mkdir(parents=True)
        ruta.write_text(json.dumps(datos), encoding='utf-8')
        contenido = ruta.read_bytes()
        assert leer_almacen(tmp_path, empresa=empresa) == datos
        assert ruta.read_bytes() == contenido
    ruta_almacen(tmp_path, 'MBT').write_text(json.dumps(b))
    with pytest.raises(ValueError): leer_almacen(tmp_path, empresa='MBT')
    with pytest.raises(ValueError): ruta_almacen(tmp_path, '../OTRA')


@pytest.mark.parametrize('cambio', ['version', 'uuid', 'referencia', 'archivo'])
def test_datos_corruptos_o_ambiguos_se_rechazan(tmp_path, cambio):
    datos = preparar_almacen(None, CATALOGO, empresa='MBT')
    if cambio == 'version': datos['version'] = 99
    if cambio == 'uuid': datos['choferes'][0]['ficha_id'] = 'inventado'
    if cambio == 'referencia': datos['choferes'][1]['referencias_catalogo'] = datos['choferes'][0]['referencias_catalogo'][:]
    if cambio == 'archivo': datos['choferes'][0]['documentos'] = [{'documento_id': 'doc', 'tipo': 'LICENCIA_CONDUCIR', 'archivo': '../OTRA/licencia.pdf'}]
    ruta = ruta_almacen(tmp_path, 'MBT'); ruta.parent.mkdir(parents=True); ruta.write_text(json.dumps(datos))
    with pytest.raises(ValueError): leer_almacen(tmp_path, empresa='MBT')


def vehiculo(patente, tipo, eventos, **kwargs):
    return NS(patente_canonica=patente, tipo=tipo, estado_calidad='CONFIRMADO',
              estado_vigencia=kwargs.get('vigencia', 'ACTIVO'), evidencias=[NS(
                  tipo=e.get('tipo', 'CONFIRMACION_HUMANA'), resultado=e.get('resultado', 'SOPORTA'),
                  fecha=e['fecha'], campos_observados={'rut_chofer_asociado': e['rut']}) for e in eventos])


def test_asignaciones_vigentes_no_salen_del_historial_y_respetan_traspaso():
    vs = [vehiculo('ZZ0001', 'TRACTO', [{'rut': '123456785', 'fecha': '2026-01-01'},
                                     {'rut': '111111111', 'fecha': '2026-02-01'}]),
          vehiculo('ZZ0002', 'CARRO', [{'rut': '123456785', 'fecha': '2026-01-01'}]),
          vehiculo('ZZ0003', 'TRACTO', [{'rut': '123456785', 'fecha': '2026-01-01'}], vigencia='INACTIVO'),
          vehiculo('ZZ0004', 'TRACTO', [{'rut': '123456785', 'fecha': '2026-01-01', 'resultado': 'CONTRADICE'}])]
    a = asignaciones_de_chofer('12.345.678-5', vs)
    assert a['tracto']['estado'] == 'SIN_ASIGNACION'
    assert a['rampla']['patente'] == 'ZZ0002'
    assert asignaciones_de_chofer('111111111', vs)['tracto']['patente'] == 'ZZ0001'


def test_dos_tractos_confirmados_es_conflicto_nunca_el_mas_reciente():
    vs = [vehiculo(p, 'TRACTO', [{'rut': '123456785', 'fecha': '2026-01-01'}]) for p in ('ZZ0001', 'ZZ0002')]
    rol = asignaciones_de_chofer('123456785', vs)['tracto']
    assert rol == {'estado': 'CONFLICTO', 'patente': None, 'candidatos': ['ZZ0001', 'ZZ0002']}


def test_identidad_canonica_no_toma_rut_del_historico_y_acepta_rut_explicito():
    args = dict(identificador='PENDIENTE00000006', filas=[], vehiculos_por_patente={})
    ficha = construir_ficha_chofer(registro_catalogo={'nombre': 'TEST', 'activo': False}, **args)
    assert ficha['rut_catalogo']['valor'] is None
    assert ficha['activo'] is False
    ficha = construir_ficha_chofer(registro_catalogo={'nombre': 'TEST', 'rut': '12.345.678-5'}, **args)
    assert ficha['rut_catalogo']['estado'] == 'CONFIRMADO'


def test_inicializacion_idempotente_solo_crea_almacen_complementario(tmp_path):
    catalogos = tmp_path / 'catalogos_privados'; catalogos.mkdir()
    ruta = catalogos / 'choferes.json'; ruta.write_text(json.dumps(CATALOGO)); contenido = ruta.read_bytes()
    (tmp_path / 'operacion' / 'actual').mkdir(parents=True)
    resultado = inicializar_almacen(tmp_path, empresa='MBT', actor='TEST')
    assert resultado['modificado'] and resultado['fichas'] == 2
    almacen = ruta_almacen(tmp_path, 'MBT'); bytes_antes = almacen.read_bytes()
    assert not inicializar_almacen(tmp_path, empresa='MBT', actor='TEST')['modificado']
    assert almacen.read_bytes() == bytes_antes
    assert ruta.read_bytes() == contenido
