"""Casos de revisión Mobile, exclusivamente en raíces sintéticas."""
import pytest

from atlas_core.expediente_digital import ErrorExpedienteDigital, revisar_documento_pendiente, resolver_documento_pendiente, registrar_documento
from atlas_core.identificacion_patentes import _por_identificar
from tests.test_expediente_digital_base import RELOJ
from tests.test_identificacion_patentes import TRACTO, _recibir, _ubicar, raiz  # noqa: F401


def test_confirma_documento_asociado_en_fichas(raiz):
    documento_id, _ = _recibir(raiz, 'revision-asociada')
    _, doc = _ubicar(raiz, documento_id)
    propuesta = {'tipo': 'SOAP', 'patente': TRACTO, 'fecha_vencimiento': '2027-09-30'}
    vista = revisar_documento_pendiente(raiz, empresa='MBT', referencia=TRACTO, documento_id=documento_id,
                                       propuesta=propuesta, reloj=RELOJ)
    assert vista['puede_confirmar']
    resolver_documento_pendiente(raiz, empresa='MBT', referencia=TRACTO, documento_id=documento_id,
                                sha256=doc['sha256'], decision='CONFIRMAR', autor='Revisor', confirmacion_humana=True,
                                propuesta=propuesta, clave_consecuencia=vista['consecuencia']['clave'], reloj=RELOJ)
    _, resultado = _ubicar(raiz, documento_id)
    assert resultado['estado_revision'] == 'CONFIRMADO_HUMANO'
    assert resultado['vencimiento'] == '2027-09-30'
    assert resultado['revision_humana']['autor'] == 'Revisor'


def test_rechazo_sin_clasificar_conserva_original_y_no_se_reidentifica(raiz):
    documento_id, _ = _recibir(raiz, 'revision-sin-clasificar', patente='')
    _, doc = _ubicar(raiz, documento_id)
    resolver_documento_pendiente(raiz, empresa='MBT', referencia='SIN_CLASIFICAR', documento_id=documento_id,
                                sha256=doc['sha256'], decision='RECHAZAR', motivo='Documento incorrecto',
                                autor='Revisor', confirmacion_humana=True, reloj=RELOJ)
    _, resultado = _ubicar(raiz, documento_id)
    assert resultado['rechazo']['motivo'] == 'Documento incorrecto'
    assert not _por_identificar(resultado)
    assert (raiz / 'fichas_digitales' / 'MBT' / resultado['archivo']).is_file()


def test_confirmacion_sin_clasificar_asocia_patente_confirmada(raiz):
    documento_id, _ = _recibir(raiz, 'revision-sin-patente', patente='')
    _, doc = _ubicar(raiz, documento_id)
    propuesta = {'tipo': 'SOAP', 'patente': TRACTO, 'fecha_vencimiento': '2027-09-30'}
    vista = revisar_documento_pendiente(raiz, empresa='MBT', referencia='SIN_CLASIFICAR', documento_id=documento_id,
                                       propuesta=propuesta, reloj=RELOJ)
    resolver_documento_pendiente(raiz, empresa='MBT', referencia='SIN_CLASIFICAR', documento_id=documento_id,
                                sha256=doc['sha256'], decision='CONFIRMAR', autor='Revisor', confirmacion_humana=True,
                                propuesta=propuesta, clave_consecuencia=vista['consecuencia']['clave'], reloj=RELOJ)
    patente, _ = _ubicar(raiz, documento_id)
    assert patente == TRACTO


def test_anterior_de_expediente_bloquea_reemplazo_cruzado(raiz):
    anterior = registrar_documento(raiz, empresa='MBT', entidad='VEHICULO', referencia=TRACTO, tipo='SOAP',
                                   fecha_vencimiento='2027-03-31', actor='TEST', reloj=RELOJ)
    documento_id, _ = _recibir(raiz, 'renovacion-cruzada')
    propuesta = {'tipo': 'SOAP', 'patente': TRACTO, 'fecha_vencimiento': '2027-09-30'}
    vista = revisar_documento_pendiente(raiz, empresa='MBT', referencia=TRACTO, documento_id=documento_id,
                                       propuesta=propuesta, reloj=RELOJ)
    assert vista['consecuencia']['motivo'] == 'RENOVACION_ENTRE_ALMACENES'
    assert not vista['puede_confirmar']
    assert anterior['documento_id'] in vista['consecuencia']['documentos']


def test_cambio_catalogo_invalida_vista(raiz):
    documento_id, _ = _recibir(raiz, 'vista-obsoleta')
    _, doc = _ubicar(raiz, documento_id)
    propuesta = {'tipo': 'SOAP', 'patente': TRACTO, 'fecha_vencimiento': '2027-09-30'}
    vista = revisar_documento_pendiente(raiz, empresa='MBT', referencia=TRACTO, documento_id=documento_id,
                                       propuesta=propuesta, reloj=RELOJ)
    ruta = raiz / 'catalogos_privados' / 'vehiculos.json'
    ruta.write_text(ruta.read_text(encoding='utf8') + ' ', encoding='utf8')
    with pytest.raises(ErrorExpedienteDigital, match='consecuencia cambió'):
        resolver_documento_pendiente(raiz, empresa='MBT', referencia=TRACTO, documento_id=documento_id,
                                    sha256=doc['sha256'], decision='CONFIRMAR', autor='Revisor', confirmacion_humana=True,
                                    propuesta=propuesta, clave_consecuencia=vista['consecuencia']['clave'], reloj=RELOJ)


def test_vista_previa_y_cancelacion_no_modifican_almacen(raiz):
    from atlas_core.fichas_choferes import ruta_almacen
    documento_id, _ = _recibir(raiz, 'cancelacion')
    ruta = ruta_almacen(raiz, 'MBT')
    antes = ruta.read_bytes()
    revisar_documento_pendiente(raiz, empresa='MBT', referencia=TRACTO, documento_id=documento_id,
                               propuesta={}, reloj=RELOJ)
    assert ruta.read_bytes() == antes


def test_original_alterado_impide_resolver(raiz):
    documento_id, _ = _recibir(raiz, 'original-alterado')
    _, doc = _ubicar(raiz, documento_id)
    propuesta = {'tipo': 'SOAP', 'patente': TRACTO, 'fecha_vencimiento': '2027-09-30'}
    vista = revisar_documento_pendiente(raiz, empresa='MBT', referencia=TRACTO, documento_id=documento_id,
                                       propuesta=propuesta, reloj=RELOJ)
    (raiz / 'fichas_digitales' / 'MBT' / doc['archivo']).write_bytes(b'alterado')
    with pytest.raises(ErrorExpedienteDigital, match='original'):
        resolver_documento_pendiente(raiz, empresa='MBT', referencia=TRACTO, documento_id=documento_id,
            sha256=doc['sha256'], decision='CONFIRMAR', autor='Revisor', confirmacion_humana=True,
            propuesta=propuesta, clave_consecuencia=vista['consecuencia']['clave'], reloj=RELOJ)
    assert _ubicar(raiz, documento_id)[1]['estado_revision'] == 'PENDIENTE_EXTRACCION'


def test_reingreso_mismos_bytes_no_elude_rechazo(raiz):
    documento_id, contenido = _recibir(raiz, 'rechazo-original')
    _, doc = _ubicar(raiz, documento_id)
    resolver_documento_pendiente(raiz, empresa='MBT', referencia=TRACTO, documento_id=documento_id,
        sha256=doc['sha256'], decision='RECHAZAR', motivo='Original incorrecto', autor='Revisor',
        confirmacion_humana=True, reloj=RELOJ)
    nuevo_id, _ = _recibir(raiz, 'otro-origen', patente='', contenido=contenido)
    with pytest.raises(ErrorExpedienteDigital, match='decisión humana'):
        revisar_documento_pendiente(raiz, empresa='MBT', referencia='SIN_CLASIFICAR',
                                    documento_id=nuevo_id, propuesta={}, reloj=RELOJ)
    assert _ubicar(raiz, documento_id)[1]['rechazo']['motivo'] == 'Original incorrecto'


def test_mismo_origen_con_otros_bytes_conserva_idempotencia_existente(raiz):
    anterior, _ = _recibir(raiz, 'mismo-origen')
    repetido, _ = _recibir(raiz, 'mismo-origen', contenido=b'\xff\xd8\xff\xe0otros')
    assert repetido == anterior



def test_escritura_expediente_concurrente_no_pasa_durante_confirmacion(raiz, monkeypatch):
    import threading
    from atlas_core import expediente_digital as exp, extraccion_vencimientos_vehiculos as ext
    from atlas_core.almacenamiento_portable import SesionOcupadaError
    documento_id, _ = _recibir(raiz, 'concurrencia')
    _, doc = _ubicar(raiz, documento_id)
    propuesta = {'tipo': 'SOAP', 'patente': TRACTO, 'fecha_vencimiento': '2027-09-30'}
    vista = revisar_documento_pendiente(raiz, empresa='MBT', referencia=TRACTO, documento_id=documento_id,
                                       propuesta=propuesta, reloj=RELOJ)
    comprobado = threading.Event()
    continuar = threading.Event()
    resultados = []
    escribir = ext._escribir
    def pausada(*args, **kwargs):
        comprobar = args[-1]
        def pausa():
            comprobar()
            comprobado.set()
            assert continuar.wait(5)
        return escribir(*args[:-1], pausa, **kwargs)
    monkeypatch.setattr(ext, '_escribir', pausada)
    def confirmar():
        try:
            resolver_documento_pendiente(raiz, empresa='MBT', referencia=TRACTO, documento_id=documento_id,
                sha256=doc['sha256'], decision='CONFIRMAR', autor='Revisor', confirmacion_humana=True,
                propuesta=propuesta, clave_consecuencia=vista['consecuencia']['clave'], reloj=RELOJ)
        except Exception as e:
            resultados.append(e)
    hilo = threading.Thread(target=confirmar)
    hilo.start()
    try:
        assert comprobado.wait(5)
        with pytest.raises(SesionOcupadaError):
            with exp._mutacion(raiz, 'MBT') as datos:
                exp._evento(datos, 'TEST_CONCURRENCIA', 'TEST', '2026-11-12T00:00:00Z')
    finally:
        continuar.set()
        hilo.join(5)
    assert not hilo.is_alive()
    assert not resultados


@pytest.mark.parametrize('recurso', ['expediente', 'catalogo'])
def test_recurso_ocupado_aborta_sin_escribir_y_libera_fichas(raiz, recurso):
    from atlas_core.almacenamiento_portable import bloqueo_sesion, SesionOcupadaError
    from atlas_core.expediente_digital import ruta_almacen_expediente
    from atlas_core.fichas_choferes import ruta_almacen
    documento_id, _ = _recibir(raiz, 'recurso-' + recurso)
    _, doc = _ubicar(raiz, documento_id)
    propuesta = {'tipo': 'SOAP', 'patente': TRACTO, 'fecha_vencimiento': '2027-09-30'}
    vista = revisar_documento_pendiente(raiz, empresa='MBT', referencia=TRACTO, documento_id=documento_id,
                                       propuesta=propuesta, reloj=RELOJ)
    ruta = ruta_almacen(raiz, 'MBT')
    antes = ruta.read_bytes()
    directorio, nombre = ((ruta_almacen_expediente(raiz, 'MBT').parent, 'expediente_documentos')
                           if recurso == 'expediente' else (raiz / 'catalogos_privados', 'catalogo_vehiculos'))
    with bloqueo_sesion(directorio, nombre):
        with pytest.raises(SesionOcupadaError):
            resolver_documento_pendiente(raiz, empresa='MBT', referencia=TRACTO, documento_id=documento_id,
                sha256=doc['sha256'], decision='CONFIRMAR', autor='Revisor', confirmacion_humana=True,
                propuesta=propuesta, clave_consecuencia=vista['consecuencia']['clave'], reloj=RELOJ)
    assert ruta.read_bytes() == antes
    with bloqueo_sesion(raiz / 'operacion' / 'actual', 'fichas_choferes_MBT'):
        pass


def test_confirmacion_previa_bloquea_revision_de_copia_reingresada(raiz):
    documento_id, contenido = _recibir(raiz, 'confirmado-original')
    _, doc = _ubicar(raiz, documento_id)
    propuesta = {'tipo': 'SOAP', 'patente': TRACTO, 'fecha_vencimiento': '2027-09-30'}
    vista = revisar_documento_pendiente(raiz, empresa='MBT', referencia=TRACTO, documento_id=documento_id,
                                       propuesta=propuesta, reloj=RELOJ)
    resolver_documento_pendiente(raiz, empresa='MBT', referencia=TRACTO, documento_id=documento_id,
        sha256=doc['sha256'], decision='CONFIRMAR', autor='Revisor', confirmacion_humana=True,
        propuesta=propuesta, clave_consecuencia=vista['consecuencia']['clave'], reloj=RELOJ)
    nuevo, _ = _recibir(raiz, 'confirmado-copia', patente='', contenido=contenido)
    with pytest.raises(ErrorExpedienteDigital, match='decisión humana'):
        revisar_documento_pendiente(raiz, empresa='MBT', referencia='SIN_CLASIFICAR',
                                    documento_id=nuevo, propuesta={}, reloj=RELOJ)
    assert _ubicar(raiz, documento_id)[1]['revision_humana']['autor'] == 'Revisor'


def test_sin_clasificar_no_admite_referencia_de_vehiculo(raiz):
    documento_id, _ = _recibir(raiz, 'identidad-sin-clasificar', patente='')
    with pytest.raises(ErrorExpedienteDigital, match='no pertenece'):
        revisar_documento_pendiente(raiz, empresa='MBT', referencia=TRACTO,
                                    documento_id=documento_id, propuesta={}, reloj=RELOJ)
