"""Contrato de descarte: exclusivamente almacenes y Cloud sintéticos."""
import pytest

from atlas_core.descarte_documento_mobile import decidir
from atlas_core.expediente_digital import ErrorExpedienteDigital, revisar_documento_pendiente, resolver_documento_pendiente
from atlas_core.extraccion_vencimientos_vehiculos import _por_extraer, _activable
from atlas_core.fichas_choferes import ruta_almacen
from atlas_core.identificacion_patentes import _por_identificar
from tests.test_expediente_digital_base import RELOJ
from tests.test_identificacion_patentes import TRACTO, _recibir, _ubicar, raiz  # noqa: F401


def _decision(raiz, documento_id, doc, decision='DESCARTAR', **kwargs):
    args = dict(empresa='MBT', documento_id=documento_id, sha256=doc['sha256'], decision=decision,
                autor='Revisor', actor='TEST', confirmacion_humana=True, comprobar=lambda: None, reloj=RELOJ)
    if decision == 'DESCARTAR':
        args['motivo'] = 'DUPLICADO'
    args.update(kwargs)
    return decidir(raiz, **args)


def _archivos(raiz):
    carpeta = ruta_almacen(raiz, 'MBT').parent
    return {p.relative_to(carpeta): p.read_bytes() for p in carpeta.rglob('*') if p.is_file()}


@pytest.mark.parametrize('motivo', ['DUPLICADO', 'DOCUMENTO_INCORRECTO', 'NO_CORRESPONDE', 'OTRO'])
def test_descarte_conserva_original_y_otros_documentos(raiz, motivo):
    otro, _ = _recibir(raiz, 'otro')
    documento_id, contenido = _recibir(raiz, 'pendiente', patente='')
    _, doc = _ubicar(raiz, documento_id)
    _, anterior_otro = _ubicar(raiz, otro)
    original = raiz / 'fichas_digitales' / 'MBT' / doc['archivo']
    resultado = _decision(raiz, documento_id, doc, motivo=motivo)
    ubicacion, final = _ubicar(raiz, documento_id)
    assert ubicacion is None and final['estado_revision'] == 'RECHAZADO_EN_REVISION'
    assert final['rechazo']['motivo'] == motivo and final['descarte']['id'] == resultado['descarte_id']
    assert final['historial'][-1] == {'accion': 'DOCUMENTO_DESCARTADO', 'decision': 'DESCARTAR',
        'descarte_id': resultado['descarte_id'], 'documento_id': documento_id, 'sha256': doc['sha256'],
        'autor': 'Revisor', 'actor': 'TEST', 'fecha': RELOJ().isoformat(), 'motivo': motivo,
        'persona': 'DECLARADA', 'canal': 'TEST'}
    assert original.read_bytes() == contenido and _ubicar(raiz, otro)[1] == anterior_otro
    assert not _por_identificar(final) and not _por_extraer(final) and not _activable(None, final)


def test_reversion_explicita_a_revision_manual_y_no_reingresa(raiz):
    documento_id, contenido = _recibir(raiz, 'original', patente='')
    _, doc = _ubicar(raiz, documento_id)
    descartado = _decision(raiz, documento_id, doc)
    _, doc = _ubicar(raiz, documento_id)
    with pytest.raises(ErrorExpedienteDigital, match='cambió'):
        _decision(raiz, documento_id, doc, 'REVERTIR', descarte_id='obsoleto')
    _decision(raiz, documento_id, doc, 'REVERTIR', descarte_id=descartado['descarte_id'])
    _, doc = _ubicar(raiz, documento_id)
    assert doc['estado_revision'] == 'PENDIENTE_EXTRACCION' and doc['revision_manual_obligatoria']
    assert [e['accion'] for e in doc['historial'][-2:]] == ['DOCUMENTO_DESCARTADO', 'DOCUMENTO_DESCARTE_REVERTIDO']
    assert not _por_identificar(doc) and not _por_extraer(doc) and not _activable(TRACTO, doc)
    assert _recibir(raiz, 'original', patente='', contenido=contenido)[0] == documento_id
    with pytest.raises(ValueError, match='decisión humana'):
        _recibir(raiz, 'reenvio', contenido=contenido)
    propuesta = {'tipo': 'SOAP', 'patente': TRACTO, 'fecha_vencimiento': '2027-09-30'}
    vista = revisar_documento_pendiente(raiz, empresa='MBT', referencia='SIN_CLASIFICAR',
                                       documento_id=documento_id, propuesta=propuesta, reloj=RELOJ)
    resolver_documento_pendiente(raiz, empresa='MBT', referencia='SIN_CLASIFICAR', documento_id=documento_id,
        sha256=doc['sha256'], decision='CONFIRMAR', autor='Revisor', confirmacion_humana=True,
        propuesta=propuesta, clave_consecuencia=vista['consecuencia']['clave'], reloj=RELOJ)
    assert _ubicar(raiz, documento_id)[0] == TRACTO


@pytest.mark.parametrize('cambios', [dict(confirmacion_humana=False), dict(autor=''), dict(motivo=''),
    dict(motivo='DESCONOCIDO'), dict(sha256='0'*64), dict(comprobar=None)])
def test_rechaza_solicitudes_invalidas_sin_escrituras(raiz, cambios):
    documento_id, _ = _recibir(raiz, 'pendiente', patente='')
    _, doc = _ubicar(raiz, documento_id)
    antes = _archivos(raiz)
    with pytest.raises(ErrorExpedienteDigital):
        _decision(raiz, documento_id, doc, **cambios)
    assert _archivos(raiz) == antes


def test_no_descarta_asignado_ni_original_alterado(raiz):
    asignado, _ = _recibir(raiz, 'asignado')
    _, doc = _ubicar(raiz, asignado)
    with pytest.raises(ErrorExpedienteDigital):
        _decision(raiz, asignado, doc)
    pendiente, _ = _recibir(raiz, 'pendiente', patente='')
    _, doc = _ubicar(raiz, pendiente)
    (ruta_almacen(raiz, 'MBT').parent / doc['archivo']).write_bytes(b'alterado')
    antes = _archivos(raiz)
    with pytest.raises(ErrorExpedienteDigital, match='íntegro'):
        _decision(raiz, pendiente, doc)
    assert _archivos(raiz) == antes


def test_guarda_de_escritor_perdida_no_publica(raiz):
    documento_id, _ = _recibir(raiz, 'pendiente', patente='')
    _, doc = _ubicar(raiz, documento_id)
    ruta = ruta_almacen(raiz, 'MBT')
    antes = ruta.read_bytes()
    llamadas = []
    def comprobar():
        llamadas.append(1)
        if len(llamadas) > 1:
            raise PermissionError('lease perdido')
    with pytest.raises(PermissionError, match='lease perdido'):
        _decision(raiz, documento_id, doc, comprobar=comprobar)
    assert ruta.read_bytes() == antes


def test_pull_simulado_no_reactiva_y_no_confirma_copia_nueva(raiz):
    from tests.test_fichas_vehiculos_mobile import CloudFalso, _doc_cloud, _sincronizar
    from tests.test_identificacion_patentes import SOLO
    documento_id, contenido = _recibir(raiz, 'original', patente='')
    _, doc = _ubicar(raiz, documento_id)
    _decision(raiz, documento_id, doc)
    antes = _archivos(raiz)
    cloud = CloudFalso([_doc_cloud('original', 'SOAP', SOLO, '', contenido),
                        _doc_cloud('nuevo', 'SOAP', SOLO, TRACTO, contenido)])
    resultado = _sincronizar(raiz, cloud)
    assert cloud.confirmados == [('original', 'RECIBIDO_PENDIENTE_REVISION')]
    assert [d['documento_id'] for d in resultado['sin_vincular']] == ['nuevo']
    assert _archivos(raiz) == antes


def test_copia_preexistente_no_elude_descarte_ni_reversion(raiz):
    documento_id, contenido = _recibir(raiz, 'original', patente='')
    copia, _ = _recibir(raiz, 'copia', patente=TRACTO, contenido=contenido)
    _, doc = _ubicar(raiz, documento_id)
    resultado = _decision(raiz, documento_id, doc)
    with pytest.raises(ErrorExpedienteDigital, match='decisión humana'):
        revisar_documento_pendiente(raiz, empresa='MBT', referencia=TRACTO, documento_id=copia, propuesta={}, reloj=RELOJ)
    _, doc = _ubicar(raiz, documento_id)
    _decision(raiz, documento_id, doc, 'REVERTIR', descarte_id=resultado['descarte_id'])
    with pytest.raises(ErrorExpedienteDigital, match='decisión humana'):
        revisar_documento_pendiente(raiz, empresa='MBT', referencia=TRACTO, documento_id=copia, propuesta={}, reloj=RELOJ)


def test_ciclos_documentales_omiten_descarte_y_reversion(raiz):
    from atlas_core.identificacion_patentes import identificar_patentes_documentos
    from atlas_core.extraccion_vencimientos_vehiculos import extraer_vencimientos_vehiculos
    documento_id, _ = _recibir(raiz, 'original', patente='')
    _, doc = _ubicar(raiz, documento_id)
    resultado = _decision(raiz, documento_id, doc)
    def no_ocr():
        raise AssertionError('No debe iniciar OCR para este documento')
    for estado in ('descartado', 'revertido'):
        if estado == 'revertido':
            _, doc = _ubicar(raiz, documento_id)
            _decision(raiz, documento_id, doc, 'REVERTIR', descarte_id=resultado['descarte_id'])
        antes = _archivos(raiz)
        identificacion = identificar_patentes_documentos(raiz, comprobar=lambda: None, fabrica_ocr=no_ocr)
        extraccion = extraer_vencimientos_vehiculos(raiz, comprobar=lambda: None, fabrica_ocr=no_ocr)
        assert identificacion['pendientes'] == extraccion['pendientes'] == 0
        assert not identificacion['errores'] and not extraccion['errores'] and not extraccion['activados']
        assert _archivos(raiz) == antes


def test_desktop_usa_sesion_y_auditoria_sin_nombre(raiz, monkeypatch):
    import json
    from atlas_core import desktop_operacion
    monkeypatch.setenv('ATLAS_ESCRITOR_ID', 'equipo-sintetico')
    documento_id, contenido = _recibir(raiz, 'original', patente='')
    _, doc = _ubicar(raiz, documento_id)
    args = ['resolver_documento_expediente.py', '--raiz-atlas', str(raiz), '--referencia', 'SIN_CLASIFICAR',
            '--documento-id', documento_id, '--sha256', doc['sha256'], '--decision', 'DESCARTAR',
            '--revisor-no-declarado', '--motivo', 'DUPLICADO', '--confirmo-revision-humana']
    antes = _archivos(raiz)
    with pytest.raises(PermissionError, match='sesión'):
        desktop_operacion.ejecutar_script(args)
    assert _archivos(raiz) == antes
    llamadas = []
    token = desktop_operacion._sesion_actual.set((raiz.resolve(), lambda: llamadas.append(True)))
    try:
        salida = json.loads(desktop_operacion.ejecutar_script(args))
    finally:
        desktop_operacion._sesion_actual.reset(token)
    assert salida['ok'] and len(llamadas) >= 2
    _, final = _ubicar(raiz, documento_id)
    auditoria = final['historial'][-1]
    assert auditoria['autor'] is None and auditoria['persona'] == 'NO_DECLARADA'
    assert auditoria['canal'] == 'DESKTOP' and auditoria['equipo']
    assert (ruta_almacen(raiz, 'MBT').parent / final['archivo']).read_bytes() == contenido


def test_persona_no_declarada_no_se_admite_fuera_de_desktop(raiz):
    documento_id, _ = _recibir(raiz, 'original', patente='')
    _, doc = _ubicar(raiz, documento_id)
    with pytest.raises(ErrorExpedienteDigital, match='sólo el canal Desktop'):
        _decision(raiz, documento_id, doc, autor='', revisor_no_declarado=True)
