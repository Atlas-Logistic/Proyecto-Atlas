import copy
import json
import pytest
from atlas_core.fichas_choferes import (preparar_almacen, preparar_ficha_selectiva,
    inicializar_ficha_selectiva, leer_almacen, fichas_por_referencia, ruta_almacen)

CAT = {'123456785': {'nombre': 'ANA PRUEBA', 'activo': True},
       '111111111': {'nombre': 'OTRA PRUEBA', 'activo': True},
       '116405008': {'nombre': 'TERCERA PRUEBA', 'activo': True}}

def test_selectiva_conserva_otras_fichas_y_es_idempotente(tmp_path):
    cat = tmp_path / 'catalogos_privados'; cat.mkdir()
    (cat / 'choferes.json').write_text(json.dumps(CAT), encoding='utf-8')
    base = preparar_almacen(None, {'111111111': CAT['111111111']}, empresa='MBT')
    ruta = ruta_almacen(tmp_path, 'MBT'); ruta.parent.mkdir(parents=True)
    ruta.write_text(json.dumps(base), encoding='utf-8')
    r = inicializar_ficha_selectiva(tmp_path, empresa='MBT', actor='TEST', referencia='123456785')
    actual = leer_almacen(tmp_path, empresa='MBT')
    assert r['modificado'] and len(actual['choferes']) == 2
    assert actual['choferes'][0] == base['choferes'][0]
    assert '116405008' not in fichas_por_referencia(actual)
    assert fichas_por_referencia(actual)['123456785']['documentos'] == []
    bytes_antes = ruta.read_bytes()
    r2 = inicializar_ficha_selectiva(tmp_path, empresa='MBT', actor='TEST', referencia='123456785')
    assert not r2['modificado'] and r2['ficha_id'] == r['ficha_id'] and ruta.read_bytes() == bytes_antes

def test_sin_almacen_crea_solo_una_y_no_exige_vehiculo():
    datos = preparar_ficha_selectiva(None, CAT, empresa='MBT', referencia='123456785', actor='TEST')
    assert list(fichas_por_referencia(datos)) == ['123456785']

@pytest.mark.parametrize('catalogo,referencia', [
    (CAT, 'NO_EXISTE'),
    ({'123456785': {'nombre': 'ANA', 'activo': False}}, '123456785'),
    ({'PENDIENTE': {'nombre': 'ANA', 'activo': True}}, 'PENDIENTE'),
    ({**CAT, 'OTRA': {'nombre': 'OTRA', 'activo': True, 'rut': '12.345.678-5'}}, '123456785'),
])
def test_rechaza_identidad_invalida_o_ambigua(catalogo, referencia):
    with pytest.raises(ValueError):
        preparar_ficha_selectiva(None, catalogo, empresa='MBT', referencia=referencia, actor='TEST')

def test_huerfana_y_legacy_requieren_revision():
    base = preparar_almacen(None, {'111111111': CAT['111111111']}, empresa='MBT')
    huerfana = copy.deepcopy(base); huerfana['choferes'][0]['referencias_catalogo'] = ['ANTERIOR']
    with pytest.raises(ValueError, match='huerfanas'):
        preparar_ficha_selectiva(huerfana, CAT, empresa='MBT', referencia='123456785', actor='TEST')
    base['choferes_legacy_sin_vincular'] = [{'rut': '12.345.678-5', 'documentos': []}]
    with pytest.raises(ValueError, match='legados'):
        preparar_ficha_selectiva(base, CAT, empresa='MBT', referencia='123456785', actor='TEST')


def test_perdida_del_turno_no_modifica_almacen(tmp_path):
    from atlas_core.fichas_choferes import inicializar_ficha_selectiva_en_turno
    cat = tmp_path / 'catalogos_privados'; cat.mkdir()
    (cat / 'choferes.json').write_text(json.dumps(CAT), encoding='utf-8')
    base = preparar_almacen(None, {'111111111': CAT['111111111']}, empresa='MBT')
    ruta = ruta_almacen(tmp_path, 'MBT'); ruta.parent.mkdir(parents=True)
    ruta.write_text(json.dumps(base), encoding='utf-8')
    anterior = ruta.read_bytes()
    def perder():
        raise PermissionError('turno perdido')
    with pytest.raises(PermissionError, match='turno perdido'):
        inicializar_ficha_selectiva_en_turno(tmp_path, empresa='MBT', actor='TEST',
                                            referencia='123456785', comprobar=perder)
    assert ruta.read_bytes() == anterior
    assert not (tmp_path / 'respaldos').exists()
