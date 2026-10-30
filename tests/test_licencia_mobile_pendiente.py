"""Licencia enviada desde Mobile -> ficha del chofer (PENDIENTE_EXTRACCION).

Sólo datos sintéticos en tmp_path; Cloud se simula parcheando `_json` y
`_descargar` del consumidor.
"""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from atlas_core import cloud_fichas_documentos as consumidor
from atlas_core.fichas_choferes import (
    fichas_por_referencia, inicializar_almacen, leer_almacen, registrar_licencia_chofer,
    registrar_licencia_mobile_pendiente, ruta_almacen,
)

CATALOGO = {'123456785': {'nombre': 'ANA TEST', 'activo': True},
            '111111111': {'nombre': 'SIN FICHA TEST', 'activo': True}}
JPEG = b'\xff\xd8\xff\xe0licencia original desde el celular'


def _raiz(tmp_path, catalogo=CATALOGO):
    catalogos = tmp_path / 'catalogos_privados'; catalogos.mkdir()
    (catalogos / 'choferes.json').write_text(json.dumps({'123456785': catalogo['123456785']}), encoding='utf-8')
    (tmp_path / 'operacion' / 'actual').mkdir(parents=True)
    inicializar_almacen(tmp_path, empresa='MBT', actor='TEST')
    # Segundo chofer vigente en el catálogo, pero sin ficha digital.
    (catalogos / 'choferes.json').write_text(json.dumps(catalogo), encoding='utf-8')
    return tmp_path


def _registrar(raiz, **cambios):
    argumentos = dict(empresa='MBT', referencia_catalogo='123456785', contenido=JPEG, mime_type='image/jpeg',
                      sha256=hashlib.sha256(JPEG).hexdigest(), origen_documento_id='dfm_1',
                      recibido_en='2026-10-29T20:00:00Z', comprobar=lambda: None, actor='MOBILE:123456785')
    argumentos.update(cambios)
    return registrar_licencia_mobile_pendiente(raiz, **argumentos)


def _ficha(raiz):
    return fichas_por_referencia(leer_almacen(raiz, empresa='MBT'))['123456785']


def test_original_queda_pendiente_sin_clase_ni_vencimiento_con_auditoria(tmp_path):
    raiz = _raiz(tmp_path)
    resultado = _registrar(raiz)
    assert resultado['ok'] and not resultado['idempotente']
    ficha = _ficha(raiz)
    assert resultado['ficha_id'] == ficha['ficha_id']
    [doc] = ficha['documentos']
    assert doc['estado_revision'] == 'PENDIENTE_EXTRACCION' and doc['origen'] == 'MOBILE'
    assert 'clase' not in doc and 'vencimiento' not in doc and 'reemplazado_por' not in doc
    assert doc['origen_documento_id'] == 'dfm_1' and doc['recibido_en'] == '2026-10-29T20:00:00Z'
    assert doc['archivo'] == f"archivos/choferes/{ficha['ficha_id']}/{doc['documento_id']}.jpg"
    assert (ruta_almacen(raiz, 'MBT').parent / doc['archivo']).read_bytes() == JPEG
    assert ficha['historial'][-1]['accion'] == 'LICENCIA_RECIBIDA_MOBILE'
    manifiesto = json.loads((Path(resultado['respaldo']) / 'manifest.json').read_text(encoding='utf-8'))
    assert manifiesto['operacion'] == 'LICENCIA_RECIBIDA_MOBILE' and manifiesto['origen_documento_id'] == 'dfm_1'


def test_idempotente_por_documento_cloud(tmp_path):
    raiz = _raiz(tmp_path)
    primero = _registrar(raiz)
    revision = leer_almacen(raiz, empresa='MBT')['revision']
    segundo = _registrar(raiz)
    assert segundo['idempotente'] and segundo['documento_id'] == primero['documento_id']
    assert leer_almacen(raiz, empresa='MBT')['revision'] == revision
    assert len(_ficha(raiz)['documentos']) == 1


def test_no_reemplaza_la_licencia_vigente_y_la_oficina_puede_reemplazarla_despues(tmp_path):
    raiz = _raiz(tmp_path)
    ficha_id = _ficha(raiz)['ficha_id']
    pdf = tmp_path / 'vigente.pdf'; pdf.write_bytes(b'%PDF-1.4\nvigente ficticia')
    vigente = registrar_licencia_chofer(raiz, empresa='MBT', ficha_id=ficha_id, referencia_catalogo='123456785',
                                        vencimiento='2027-06-30', clase='A5', archivo_origen=pdf)
    _registrar(raiz)
    documentos = _ficha(raiz)['documentos']
    assert [d.get('reemplazado_por') for d in documentos] == [None, None]
    assert documentos[0]['documento_id'] == vigente['documento_id'] and documentos[0]['clase'] == 'A5'
    nueva = tmp_path / 'nueva.pdf'; nueva.write_bytes(b'%PDF-1.4\nnueva ficticia')
    registrar_licencia_chofer(raiz, empresa='MBT', ficha_id=ficha_id, referencia_catalogo='123456785',
                              vencimiento='2028-06-30', clase='A5', archivo_origen=nueva)
    documentos = _ficha(raiz)['documentos']
    assert all(d.get('reemplazado_por') == documentos[-1]['documento_id'] for d in documentos[:2])
    assert (ruta_almacen(raiz, 'MBT').parent / documentos[1]['archivo']).read_bytes() == JPEG


@pytest.mark.parametrize('cambios,motivo', [
    ({'referencia_catalogo': '999999999'}, 'no es un chofer vigente'),
    ({'referencia_catalogo': '111111111'}, 'no tiene ficha digital'),
    ({'sha256': '0' * 64}, 'huella'),
    ({'mime_type': 'application/pdf'}, 'no corresponde'),
    ({'mime_type': 'image/webp'}, 'no corresponde'),
])
def test_rechazos_no_escriben_nada(tmp_path, cambios, motivo):
    raiz = _raiz(tmp_path)
    antes = ruta_almacen(raiz, 'MBT').read_bytes()
    with pytest.raises(ValueError, match=motivo):
        _registrar(raiz, **cambios)
    assert ruta_almacen(raiz, 'MBT').read_bytes() == antes
    assert not (ruta_almacen(raiz, 'MBT').parent / 'archivos').exists()


def test_lease_perdido_no_publica(tmp_path):
    raiz = _raiz(tmp_path)
    antes = ruta_almacen(raiz, 'MBT').read_bytes()

    def perdido():
        raise PermissionError('lease perdido')
    with pytest.raises(PermissionError):
        _registrar(raiz, comprobar=perdido)
    assert ruta_almacen(raiz, 'MBT').read_bytes() == antes


class CloudFalso:
    def __init__(self, documentos, *, falla_confirmar=False):
        self.documentos = documentos
        self.falla_confirmar = falla_confirmar
        self.confirmados = []

    def json(self, base_url, ruta, token, *, method='GET', body=None, timeout):
        if ruta.endswith('/pendientes'):
            return {'documentos': [{k: d[k] for k in ('documento_id', 'titular', 'tipo')} for d in self.documentos]}
        documento_id = ruta.split('/')[-2]
        doc = next(d for d in self.documentos if d['documento_id'] == documento_id)
        if ruta.endswith('/lease'):
            return {**doc, 'lease_token': f'lt-{documento_id}', 'descarga_url': f'https://cloud.test/{documento_id}'}
        if ruta.endswith('/confirmar'):
            if self.falla_confirmar:
                raise consumidor.ErrorSincronizacionCloudMobile('caida')
            assert body == {'lease_token': f'lt-{documento_id}', 'resultado': 'PENDIENTE_EXTRACCION'}
            self.confirmados.append(documento_id)
            return {'estado': 'COMPLETADO'}
        raise AssertionError(ruta)

    def descargar(self, url, *, esperado_bytes, timeout):
        doc = next(d for d in self.documentos if url.endswith(d['documento_id']))
        assert esperado_bytes == len(doc['contenido'])
        return doc['contenido']


def _doc_cloud(documento_id, chofer_id, contenido=JPEG):
    return {'documento_id': documento_id, 'titular': 'CHOFER', 'tipo': 'LICENCIA_CONDUCIR', 'chofer_id': chofer_id,
            'mime_type': 'image/jpeg', 'bytes': len(contenido), 'sha256': hashlib.sha256(contenido).hexdigest(),
            'recibido_en': '2026-10-29T20:00:00Z', 'contenido': contenido}


def _sincronizar(raiz, cloud, puede_continuar=lambda: True):
    with patch.object(consumidor, '_json', cloud.json), patch.object(consumidor, '_descargar', cloud.descargar):
        return consumidor.sincronizar_licencias_cloud(base_url='https://cloud.test', token_motor='t', consumidor='JAVO',
                                                      raiz=raiz, timeout=1, puede_continuar=puede_continuar)


def test_consumidor_confirma_solo_lo_escrito_y_deja_reintentable_lo_no_vinculable(tmp_path):
    raiz = _raiz(tmp_path)
    cloud = CloudFalso([_doc_cloud('dfm_ok', '123456785'), _doc_cloud('dfm_sin_ficha', '111111111', JPEG + b'2')])
    resumen = _sincronizar(raiz, cloud)
    assert cloud.confirmados == ['dfm_ok']
    assert [i['documento_id'] for i in resumen['incorporados']] == ['dfm_ok']
    assert [s['documento_id'] for s in resumen['sin_vincular']] == ['dfm_sin_ficha']
    assert _ficha(raiz)['documentos'][0]['origen_documento_id'] == 'dfm_ok'


def test_confirmacion_caida_se_reconfirma_sin_duplicar(tmp_path):
    raiz = _raiz(tmp_path)
    cloud = CloudFalso([_doc_cloud('dfm_ok', '123456785')], falla_confirmar=True)
    assert _sincronizar(raiz, cloud)['errores']
    cloud.falla_confirmar = False
    resumen = _sincronizar(raiz, cloud)
    assert cloud.confirmados == ['dfm_ok'] and resumen['incorporados'][0]['idempotente']
    assert len(_ficha(raiz)['documentos']) == 1


def test_hash_descargado_distinto_no_escribe_ni_confirma(tmp_path):
    raiz = _raiz(tmp_path)
    doc = _doc_cloud('dfm_ok', '123456785')
    doc['sha256'] = '0' * 64
    cloud = CloudFalso([doc])
    assert _sincronizar(raiz, cloud)['errores'] and cloud.confirmados == []
    assert _ficha(raiz)['documentos'] == []


def test_pull_invoca_licencias_tras_las_guias_y_un_fallo_no_altera_su_resultado(tmp_path):
    from sincronizar_mobile_cloud import ejecutar_pull_con_escritor
    class Escritor:
        vigente = True
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def adquirir(self): return True

    argumentos = dict(base_url='https://cloud.test', token_motor='t', consumidor='JAVO',
                      repositorio=NS(raiz_atlas=tmp_path), timeout=1, procesar=False, dataset=None,
                      carpeta_catalogos=None, fabrica_escritor=lambda **_: Escritor())
    with patch('sincronizar_mobile_cloud.sincronizar_envios_cloud', return_value={'confirmados': ['e1']}), \
         patch('atlas_core.exclusividad_equipo.recuperar_bloqueos_huerfanos'), \
         patch('sincronizar_mobile_cloud.publicar_asignaciones_cloud', return_value={'publicadas': 1}) as asignaciones, \
         patch('sincronizar_mobile_cloud.sincronizar_licencias_cloud', return_value={'incorporados': []}) as licencias:
        resultado = ejecutar_pull_con_escritor(**argumentos)
    assert resultado == {'confirmados': ['e1'], 'licencias_mobile': {'incorporados': []},
                         'asignaciones_vehiculo': {'publicadas': 1}}
    assert licencias.call_args.kwargs['raiz'] == tmp_path and licencias.call_args.kwargs['puede_continuar']()
    assert asignaciones.call_args.kwargs['raiz'] == tmp_path and asignaciones.call_args.kwargs['puede_continuar']()
    with patch('sincronizar_mobile_cloud.sincronizar_envios_cloud', return_value={'confirmados': ['e1']}), \
         patch('atlas_core.exclusividad_equipo.recuperar_bloqueos_huerfanos'), \
         patch('sincronizar_mobile_cloud.publicar_asignaciones_cloud', side_effect=OSError('Cloud')), \
         patch('sincronizar_mobile_cloud.sincronizar_licencias_cloud', side_effect=OSError('Drive')):
        resultado = ejecutar_pull_con_escritor(**argumentos)
    assert resultado == {'confirmados': ['e1'], 'licencias_mobile': {'error': 'Drive'},
                         'asignaciones_vehiculo': {'error': 'Cloud'}}
