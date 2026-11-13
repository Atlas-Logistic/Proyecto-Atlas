"""Licencias con varias clases (p. ej. A2 y A5), sólo en raíces sintéticas.

Cada clase se guarda como valor individual normalizado en `clases`; `clase` queda como texto legible para
lectores anteriores. «A2-A5» nunca se interpreta como rango. Las licencias antiguas de una clase siguen
funcionando igual.
"""
import json
import subprocess
import sys

import pytest

from atlas_core.extraccion_licencias import extraer_licencias_pendientes
from atlas_core.fichas_choferes import (
    clases_de_licencia, confirmar_licencia_chofer, leer_almacen, normalizar_clases_licencia,
    registrar_licencia_mobile_pendiente, ruta_almacen,
)
from tests.test_confirmar_licencia_chofer import (
    FRENTE, REF, REVERSO, RAIZ_MOTOR, RUT, OCRFalso, _confirmar, _doc, _ficha, _raiz, sha,
)


def _recibir_con(raiz, lineas, origen='dfm_clases'):
    caras = [{'cara': 'FRENTE', 'contenido': FRENTE, 'mime_type': 'image/jpeg', 'sha256': sha(FRENTE)},
             {'cara': 'REVERSO', 'contenido': REVERSO, 'mime_type': 'image/png', 'sha256': sha(REVERSO)}]
    r = registrar_licencia_mobile_pendiente(raiz, caras=caras, empresa='MBT', referencia_catalogo=REF, origen_documento_id=origen,
                                            recibido_en='2026-11-13T12:00:00Z', comprobar=lambda: None)
    extraer_licencias_pendientes(raiz, comprobar=lambda: None, fabrica_ocr=lambda: OCRFalso(lineas))
    return _doc(raiz, r['documento_id'])


@pytest.mark.parametrize('entrada,esperado', [
    ('A2', ['A2']), ('a5, a2', ['A2', 'A5']), (['A5', 'A2', 'A2'], ['A2', 'A5']), ('A2 y B', ['A2', 'B']), ('B;C', ['B', 'C']),
])
def test_normalizacion_en_valores_individuales_y_orden_canonico(entrada, esperado):
    assert normalizar_clases_licencia(entrada) == esperado


@pytest.mark.parametrize('entrada', ['A2-A5', 'A2–A5', 'A2/A5', '', 'ZZ9', ['A2', 'A2-A5'], []])
def test_rangos_y_valores_invalidos_se_rechazan(entrada):
    with pytest.raises(ValueError):
        normalizar_clases_licencia(entrada)


def test_ocr_reconoce_varias_clases_sin_inventar_intermedias_ni_registrarlas_solas(tmp_path):
    raiz = _raiz(tmp_path)
    doc = _recibir_con(raiz, [f'RUN {RUT}', 'CLASE A2-A5', 'VENCIMIENTO 30/06/2030'])
    campo = doc['extraccion_automatica']['campos']['clase']
    assert campo['valor'] is None and campo['motivo'] == 'VARIAS_CLASES'
    assert campo['valores'] == ['A2', 'A5'], 'cada clase leída, sin A3 ni A4'
    assert doc['estado_revision'] == 'PENDIENTE_EXTRACCION' and not doc.get('clase') and not doc.get('clases')


def test_confirmar_varias_clases_persiste_lista_texto_y_auditoria(tmp_path):
    raiz = _raiz(tmp_path)
    doc = _recibir_con(raiz, [f'RUN {RUT}', 'CLASE A2 A5'])
    original = json.dumps(doc['extraccion_automatica'], sort_keys=True)
    resultado = _confirmar(raiz, doc, clase=['A5', 'A2'])
    assert resultado['accion'] == 'LICENCIA_CONFIRMADA'
    confirmado = _doc(raiz, doc['documento_id'])
    assert confirmado['clases'] == ['A2', 'A5'] and confirmado['clase'] == 'A2, A5'
    assert clases_de_licencia(confirmado) == ['A2', 'A5']
    c = confirmado['confirmacion_humana']
    assert c['valores']['clases'] == ['A2', 'A5'] and c['anteriores']['clases'] == []
    assert 'clases' not in c['distintos_de_ocr'], 'coinciden con las clases reconocidas por el OCR'
    assert 'clases' in _ficha(raiz)['historial'][-1]['campos']
    assert json.dumps(confirmado['extraccion_automatica'], sort_keys=True) == original, 'lectura OCR intacta'
    # Reapertura: misma confirmación, sin escribir.
    revision = leer_almacen(raiz, empresa='MBT')['revision']
    assert not _confirmar(raiz, doc, clase='A2, A5')['modificado']
    assert leer_almacen(raiz, empresa='MBT')['revision'] == revision


def test_correccion_humana_de_clases_conserva_la_anterior(tmp_path):
    raiz = _raiz(tmp_path)
    doc = _recibir_con(raiz, [f'RUN {RUT}', 'CLASE A2 A5'])
    _confirmar(raiz, doc, clase=['A2', 'A5'])
    resultado = _confirmar(raiz, doc, clase='A2', autor='Supervisor')
    assert resultado['accion'] == 'LICENCIA_CORREGIDA'
    corregido = _doc(raiz, doc['documento_id'])
    assert corregido['clases'] == ['A2'] and corregido['clase'] == 'A2'
    assert corregido['confirmacion_humana']['anteriores']['clases'] == ['A2', 'A5']
    assert corregido['confirmaciones_anteriores'][0]['valores']['clases'] == ['A2', 'A5']
    assert 'clases' in corregido['confirmacion_humana']['distintos_de_ocr']


def test_rango_no_escribe_nada(tmp_path):
    raiz = _raiz(tmp_path)
    doc = _recibir_con(raiz, [f'RUN {RUT}', 'CLASE A2 A5'])
    antes = ruta_almacen(raiz, 'MBT').read_bytes()
    with pytest.raises(ValueError, match='no se interpreta como rango'):
        _confirmar(raiz, doc, clase='A2-A5')
    assert ruta_almacen(raiz, 'MBT').read_bytes() == antes


def test_licencia_antigua_de_una_clase_sigue_igual_y_no_reescribe(tmp_path):
    raiz = _raiz(tmp_path)
    doc = _recibir_con(raiz, [f'RUN {RUT}', 'A4 Ley19495'])
    _confirmar(raiz, doc)  # clase única «a4», como antes
    # Simula una licencia confirmada antes de este cambio (sin `clases`).
    ruta = ruta_almacen(raiz, 'MBT')
    datos = json.loads(ruta.read_text(encoding='utf-8'))
    for ficha in datos['choferes']:
        for d in ficha['documentos']:
            if d['documento_id'] == doc['documento_id']:
                d.pop('clases', None)
    ruta.write_text(json.dumps(datos), encoding='utf-8')
    antiguo = _doc(raiz, doc['documento_id'])
    assert 'clases' not in antiguo and antiguo['clase'] == 'A4' and clases_de_licencia(antiguo) == ['A4']
    assert not _confirmar(raiz, doc)['modificado'], 'reconfirmar la misma clase no escribe'


def _cli(raiz, doc, *clases):
    return [sys.executable, '-B', str(RAIZ_MOTOR / 'confirmar_licencia_chofer.py'), '--raiz-atlas', str(raiz),
            '--ficha-id', _ficha(raiz)['ficha_id'], '--referencia-catalogo', REF, '--documento-id', doc['documento_id'],
            '--sha256', doc['sha256'], '--rut', RUT, '--nombre', 'ANA TEST', *clases, '--vencimiento', '2030-06-30',
            '--autor', 'Javier', '--confirmo-revision-humana']


def test_cli_acepta_clases_y_rechaza_mezclar_o_rangos(tmp_path):
    raiz = _raiz(tmp_path)
    doc = _recibir_con(raiz, [f'RUN {RUT}', 'CLASE A2 A5'])
    antes = ruta_almacen(raiz, 'MBT').read_bytes()
    ambos = subprocess.run(_cli(raiz, doc, '--clase', 'A2', '--clases', 'A2,A5'), cwd=RAIZ_MOTOR, capture_output=True, text=True)
    assert ambos.returncode != 0 and ruta_almacen(raiz, 'MBT').read_bytes() == antes
    rango = subprocess.run(_cli(raiz, doc, '--clase', 'A2-A5'), cwd=RAIZ_MOTOR, capture_output=True, text=True)
    assert rango.returncode != 0 and 'rango' in rango.stderr and ruta_almacen(raiz, 'MBT').read_bytes() == antes
    ok = subprocess.run(_cli(raiz, doc, '--clases', 'A2,A5'), cwd=RAIZ_MOTOR, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr
    assert _doc(raiz, doc['documento_id'])['clases'] == ['A2', 'A5']


def test_clase_unica_por_cli_como_antes(tmp_path):
    raiz = _raiz(tmp_path)
    doc = _recibir_con(raiz, [f'RUN {RUT}', 'A4 Ley19495'])
    ok = subprocess.run(_cli(raiz, doc, '--clase', 'A4'), cwd=RAIZ_MOTOR, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr
    d = _doc(raiz, doc['documento_id'])
    assert (d['clase'], d['clases']) == ('A4', ['A4'])
