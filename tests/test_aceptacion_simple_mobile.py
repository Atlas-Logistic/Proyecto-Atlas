"""Aceptación simple (contrato 2) de documentos Mobile en su almacén de fichas, sólo en raíces sintéticas."""
import pytest

from atlas_core import escritor_operativo
from atlas_core.expediente_digital import (ErrorExpedienteDigital, PERSONA_NO_DECLARADA, resolver_documento_pendiente,
                                           revisar_documento_pendiente)
from tests.test_expediente_digital_base import RELOJ
from tests.test_identificacion_patentes import TRACTO, _recibir, _ubicar, raiz  # noqa: F401

EQUIPO = "pc-12345678-1234-4234-8234-123456789abc"


@pytest.fixture(autouse=True)
def equipo(tmp_path, monkeypatch):
    ruta = tmp_path / "local" / "escritor_operativo_id.txt"
    ruta.parent.mkdir(parents=True)
    ruta.write_text(EQUIPO, encoding="utf-8")
    monkeypatch.delenv("ATLAS_ESCRITOR_ID", raising=False)
    monkeypatch.setattr(escritor_operativo, "ruta_identidad_escritor", lambda: ruta)


def test_mobile_sin_revisor_con_fechas_y_confirmacion_del_original(raiz):  # noqa: F811
    documento_id, _ = _recibir(raiz, 'aceptacion-simple')
    _, doc = _ubicar(raiz, documento_id)
    propuesta = {'tipo': 'SOAP', 'patente': TRACTO, 'fecha_emision': '2026-09-30', 'fecha_vencimiento': '2027-09-30'}
    vista = revisar_documento_pendiente(raiz, empresa='MBT', referencia=TRACTO, documento_id=documento_id,
                                        propuesta=propuesta, reloj=RELOJ)
    assert vista['contrato_aceptacion'] == 2 and vista['puede_confirmar']
    assert {'fecha_emision', 'fecha_vencimiento'} <= set(vista['editables'])
    base = dict(empresa='MBT', referencia=TRACTO, documento_id=documento_id, sha256=doc['sha256'], decision='CONFIRMAR',
                autor='', revisor_no_declarado=True, confirmacion_humana=True, propuesta=propuesta,
                clave_consecuencia=vista['consecuencia']['clave'], reloj=RELOJ)
    with pytest.raises(ErrorExpedienteDigital, match='aparecen en el original'):
        resolver_documento_pendiente(raiz, **base)
    _, intacto = _ubicar(raiz, documento_id)
    assert intacto['estado_revision'] == 'PENDIENTE_EXTRACCION' and not intacto.get('revision_humana')
    resolver_documento_pendiente(raiz, **base, confirmo_original=True)
    _, resultado = _ubicar(raiz, documento_id)
    rh = resultado['revision_humana']
    assert resultado['estado_revision'] == 'CONFIRMADO_HUMANO'
    assert (resultado['vencimiento'], resultado['emision']) == ('2027-09-30', '2026-09-30')
    assert rh['autor'] is None and rh['persona'] == PERSONA_NO_DECLARADA and rh['equipo']['id'] == EQUIPO
    assert set(rh['datos_completados']) == {'tipo', 'patente'} and rh['confirmo_original'] is True
    assert rh['fechas']['fecha_vencimiento']['origen'] == 'HUMANO'
    assert resultado['fechas_confirmadas']['fecha_vencimiento']['valor'] == '2027-09-30'
    assert resultado['clasificacion_humana']['persona'] == PERSONA_NO_DECLARADA
    assert resultado['historial'][-1]['persona'] == PERSONA_NO_DECLARADA


def test_mobile_rechazo_sin_revisor(raiz):  # noqa: F811
    documento_id, _ = _recibir(raiz, 'rechazo-simple')
    _, doc = _ubicar(raiz, documento_id)
    resolver_documento_pendiente(raiz, empresa='MBT', referencia=TRACTO, documento_id=documento_id, sha256=doc['sha256'],
                                 decision='RECHAZAR', motivo='No corresponde', autor='', revisor_no_declarado=True,
                                 confirmacion_humana=True, reloj=RELOJ)
    _, resultado = _ubicar(raiz, documento_id)
    assert resultado['rechazo']['persona'] == PERSONA_NO_DECLARADA and resultado['rechazo']['autor'] is None
    assert (raiz / 'fichas_digitales' / 'MBT' / resultado['archivo']).is_file()
