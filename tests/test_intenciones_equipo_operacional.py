"""Integración sintética con la acción oficial de error documental de equipo."""
import json

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.intenciones_equipo_operacional import interpretar_error_equipo
from tests.test_acciones_operacionales import entorno  # noqa: F401
from tests.test_errores_documentales_aza import varas, _filas, _ejecutar  # noqa: F401


def intencion(guia='482816'):
    return interpretar_error_equipo(f'Confirma el error documental de AZA de la guía {guia} y usa el equipo vigente')


def preparar(e, guia='482816'):
    capa = CapaAccionesOperacionales(e['raiz'])
    i = intencion(guia)
    return capa, capa.previsualizar(i.accion, i.parametros, actor='B1', origen='B1')


def chofer(e):
    r = _ejecutar(CapaAccionesOperacionales(e['raiz']), 'DOCUMENTO_CORREGIR_CHOFER_OPERACIONAL',
                  {'numero_guia': '482816', 'chofer': '142938162', 'confirmar_discrepancia_rut': True})
    assert r['estado'] == 'APLICADA'


@pytest.mark.parametrize('frase', [
    'La patente del camión de la guía 482816 es AL1876',
    'El chofer de la guía 482816 es René García',
    'Las guías 482816 y 482740 pertenecen al mismo viaje',
    'Separa la guía 482816 del viaje',
    'No confirmes el error documental de AZA de la guía 482816 y usa el equipo vigente',
    'Confirma el error documental de AZA de la guía 482816 y usa el equipo vigente y cambia la patente',
    '¿Confirma el error documental de AZA de la guía 482816 y usa el equipo vigente?',
])
def test_no_confunde_otros_tipos_de_accion(frase):
    assert interpretar_error_equipo(frase) is None


def test_canal_oficial_preview_confirmacion_respaldo_y_auditoria(varas):
    chofer(varas)
    antes = _filas(varas)
    catalogo = (varas['cat'] / 'vehiculos.json').read_bytes()
    original = varas['raiz'] / '482816.jpeg'
    original.write_bytes(b'original sintetico')
    ocr = varas['raiz'] / 'ocr-sintetico.json'
    ocr.write_bytes(b'{"ocr":"sintetico"}')
    capa, p = preparar(varas)
    assert p['estado'] == 'PREVIEW', p
    assert _filas(varas) == antes
    r = capa.ejecutar(p['token'], actor='B1', origen='B1', confirmado_por='JAVIER')
    assert r['estado'] == 'APLICADA', r
    assert r['respaldo']
    assert any(a['token'] == p['token'] and a['resultado'] == 'APLICADA' for a in capa.auditoria())
    despues = _filas(varas)
    for guia in antes:
        for campo in ('archivo', 'numero_guia', 'numero_transporte', 'patente_tracto', 'patente_rampla', 'chofer', 'rut_chofer'):
            assert despues[guia][campo] == antes[guia][campo]
    assert (varas['cat'] / 'vehiculos.json').read_bytes() == catalogo
    assert original.read_bytes() == b'original sintetico' and ocr.read_bytes() == b'{"ocr":"sintetico"}'


def test_sin_confirmar_o_rechazada_no_hay_aplicacion(varas):
    chofer(varas)
    capa, p = preparar(varas)
    assert p['estado'] == 'PREVIEW'
    antes = (varas['actual'] / 'decisiones_aplicadas.json').read_bytes()
    r = capa.ejecutar(p['token'], actor='B1', origen='B1', confirmado_por='')
    assert r['estado'] != 'APLICADA'
    assert (varas['actual'] / 'decisiones_aplicadas.json').read_bytes() == antes


def test_guia_inexistente_rechazada(varas):
    _, p = preparar(varas, '999999')
    assert p['estado'] == 'RECHAZADA'


def test_conflicto_cambia_asignacion_entre_preview_y_confirmacion(varas):
    chofer(varas)
    capa, p = preparar(varas)
    assert p['estado'] == 'PREVIEW', p
    ruta = varas['cat'] / 'vehiculos.json'
    catalogo = json.loads(ruta.read_text(encoding='utf-8'))
    catalogo['vehiculos'] = [v for v in catalogo['vehiculos'] if v['patente_canonica'] != 'JB8529']
    ruta.write_text(json.dumps(catalogo), encoding='utf-8')
    r = capa.ejecutar(p['token'], actor='B1', origen='B1', confirmado_por='JAVIER')
    assert r['estado'] != 'APLICADA', r


def test_otro_espacio_operativo_no_se_modifica(varas, tmp_path):
    import shutil
    chofer(varas)
    otra_raiz = tmp_path / 'empresa_distinta'
    shutil.copytree(varas['raiz'], otra_raiz)
    antes = {p.relative_to(otra_raiz): p.read_bytes() for p in otra_raiz.rglob('*') if p.is_file()}
    capa, p = preparar(varas)
    assert p['estado'] == 'PREVIEW', p
    r = capa.ejecutar(p['token'], actor='B1', origen='B1', confirmado_por='JAVIER')
    assert r['estado'] == 'APLICADA', r
    assert {p.relative_to(otra_raiz): p.read_bytes() for p in otra_raiz.rglob('*') if p.is_file()} == antes
