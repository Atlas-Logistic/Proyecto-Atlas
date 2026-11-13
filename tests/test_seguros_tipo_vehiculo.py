"""Coberturas por tipo de vehículo (operación MBT): la responsabilidad civil corresponde al tracto, el seguro de
carga a la rampla y el camión rígido lleva ambas. Una póliza sólo acredita al vehículo al que está asociada:
nada se reasigna ni se proyecta a otro vehículo, y los documentos ya adjuntos se conservan."""
import json
from datetime import datetime, timezone

import pytest

from atlas_core.catalogo_vehiculos import asociar_chofer_a_vehiculo_confirmado
from atlas_core.expediente_digital import (consultar_expediente, documentos_ausentes, registrar_documento_vehiculo_desktop,
                                           vista_expediente_desktop)
from tests.test_expediente_doble_cobertura import OCR
from tests.test_identificacion_patentes import CARRO, RIGIDO, SOLO, TRACTO, raiz  # noqa: F401

RC, CARGA, ROBO = 'POLIZA_RESPONSABILIDAD_CIVIL', 'SEGURO_CARGA', 'POLIZA_ROBO'
PROPIOS = {'SOAP', 'REVISION_TECNICA', 'PERMISO_CIRCULACION', 'CERTIFICADO_EMISION_GASES'}
ESPERADOS = {
    TRACTO: PROPIOS | {RC},
    CARRO: {'REVISION_TECNICA', 'PERMISO_CIRCULACION', CARGA},
    RIGIDO: PROPIOS | {RC, CARGA},
}


@pytest.mark.parametrize('patente', [TRACTO, CARRO, RIGIDO])
def test_misma_fuente_en_vehiculo_y_ausentes(raiz, patente):
    vista = vista_expediente_desktop(raiz, empresa='MBT', entidad='VEHICULO', referencia=patente)
    assert set(vista['requisitos_aplicables']) == ESPERADOS[patente]
    assert {a['tipo'] for a in vista['ausentes']} == ESPERADOS[patente]
    assert ROBO not in vista['requisitos_aplicables'], 'robo sigue siendo opcional'
    assert ROBO in {t['tipo'] for t in vista['tipos_registrables']}, 'robo se puede seguir adjuntando'
    general = {a['tipo'] for a in documentos_ausentes(raiz, empresa='MBT') if a['referencia_catalogo'] == vista['referencia_catalogo']}
    assert general == ESPERADOS[patente]


def _asignar(raiz, patente):
    asociar_chofer_a_vehiculo_confirmado(raiz / 'catalogos_privados' / 'vehiculos.json', patente=patente, actor='TEST',
                                         fuente_decision='TEST', rut_chofer_asociado=SOLO, fecha=datetime.now(timezone.utc))


def test_chofer_usa_la_misma_regla_que_cada_vehiculo(raiz):
    _asignar(raiz, CARRO)
    chofer = vista_expediente_desktop(raiz, empresa='MBT', entidad='CHOFER', referencia=SOLO)
    for r in chofer['requisitos_documentales']:
        if r['ambito'] == 'CHOFER':
            continue
        for v in r['vehiculos']:
            propia = vista_expediente_desktop(raiz, empresa='MBT', entidad='VEHICULO', referencia=v['patente'])
            assert (v['estado'] != 'NO_APLICA') == (r['tipo'] in propia['requisitos_aplicables']), (r['tipo'], v['patente'])
    req = {r['tipo']: {v['tipo_vehiculo']: v['estado'] for v in r['vehiculos']} for r in chofer['requisitos_documentales']}
    assert req[RC] == {'TRACTO': 'FALTANTE', 'CARRO': 'NO_APLICA'}
    assert req[CARGA] == {'TRACTO': 'NO_APLICA', 'CARRO': 'FALTANTE'}
    assert len(chofer['requisitos_documentales']) == 7


def test_rc_ya_adjunta_a_una_rampla_se_conserva_y_no_se_reasigna_al_tracto(raiz):
    _asignar(raiz, CARRO)
    original = b'\xff\xd8\xff\xe0poliza rc de la rampla'
    doc = registrar_documento_vehiculo_desktop(raiz, empresa='MBT', referencia=CARRO, tipo=RC, contenido=original,
        mime_type='image/jpeg', fabrica_ocr=lambda: OCR(CARRO, 'COBERTURA: RESPONSABILIDAD CIVIL', '30/09/2030'))
    fichas = raiz / 'fichas_digitales' / 'MBT' / 'fichas_documentales.json'
    almacen_antes = fichas.read_bytes()
    rampla = consultar_expediente(raiz, empresa='MBT', entidad='VEHICULO', referencia=CARRO)
    assert RC not in rampla['requisitos_aplicables']
    assert any(d['documento_id'] == doc['documento_id'] for d in rampla['documentos']), 'el documento sigue en la rampla'
    tracto = consultar_expediente(raiz, empresa='MBT', entidad='VEHICULO', referencia=TRACTO)
    assert RC in {a['tipo'] for a in tracto['ausentes']}, 'la póliza de la rampla no acredita al tracto'
    chofer = consultar_expediente(raiz, empresa='MBT', entidad='CHOFER', referencia=SOLO)
    rc = next(r for r in chofer['requisitos_documentales'] if r['tipo'] == RC)
    assert {v['patente']: v['estado'] for v in rc['vehiculos']} == {TRACTO: 'FALTANTE', CARRO: 'NO_APLICA'}
    assert fichas.read_bytes() == almacen_antes and (fichas.parent / doc['archivo']).read_bytes() == original


def test_rigido_acredita_rc_con_su_propia_poliza_y_sigue_exigiendo_carga(raiz):
    registrar_documento_vehiculo_desktop(raiz, empresa='MBT', referencia=RIGIDO, tipo=RC, contenido=b'\xff\xd8\xff\xe0rc rigido',
        mime_type='image/jpeg', fabrica_ocr=lambda: OCR(RIGIDO, 'COBERTURA: RESPONSABILIDAD CIVIL', '30/09/2030'))
    vista = consultar_expediente(raiz, empresa='MBT', entidad='VEHICULO', referencia=RIGIDO)
    ausentes = {a['tipo'] for a in vista['ausentes']}
    assert RC not in ausentes and CARGA in ausentes


def test_tipo_incierto_sigue_sin_requisitos(raiz):
    ruta = raiz / 'catalogos_privados' / 'vehiculos.json'
    datos = json.loads(ruta.read_text(encoding='utf-8'))
    next(v for v in datos['vehiculos'] if v['patente_canonica'] == TRACTO).update(estado_calidad='CANDIDATO', confirmado_por='', fecha_confirmacion='')
    ruta.write_text(json.dumps(datos), encoding='utf-8')
    vista = consultar_expediente(raiz, empresa='MBT', entidad='VEHICULO', referencia=TRACTO)
    assert vista['tipo_vehiculo_estado'] == 'INCIERTO' and vista['requisitos_aplicables'] == [] and vista['ausentes'] == []
    chofer = consultar_expediente(raiz, empresa='MBT', entidad='CHOFER', referencia=SOLO)
    assert all(v['estado'] == 'TIPO_INCIERTO' for r in chofer['requisitos_documentales'] for v in r['vehiculos'])
