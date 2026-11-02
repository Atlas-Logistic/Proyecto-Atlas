"""Clasificación humana de la imagen única de una licencia como ANVERSO
(`clasificar_anverso_licencia_chofer`).

Sólo datos ficticios en tmp_path (fuera de una unidad compartida: la sesión
oficial corre sin lease, igual que las demás pruebas de fichas).
"""
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from atlas_core.desktop_operacion import ESCRITORES
from atlas_core.extraccion_licencias import extraer_licencias_pendientes
from atlas_core.fichas_choferes import (
    clasificar_anverso_licencia_chofer, confirmar_licencia_chofer, fichas_por_referencia, inicializar_almacen,
    leer_almacen, registrar_licencia_mobile_pendiente, ruta_almacen,
)

RAIZ_MOTOR = Path(__file__).resolve().parent.parent
REF = '123456785'
RUT = '12.345.678-5'
UNICA = b'\xff\xd8\xff\xe0licencia antigua ficticia'
OTRA_UNICA = b'\xff\xd8\xff\xe0otra licencia antigua ficticia'
FRENTE = b'\xff\xd8\xff\xe0frente ficticio'
REVERSO = b'\x89PNG\r\n\x1a\nreverso ficticio'
sha = lambda b: hashlib.sha256(b).hexdigest()


class OCRFalso:
    def leer_texto(self, ruta):
        return [f'RUN {RUT}', 'A4 Ley19495']


def _raiz(tmp_path):
    catalogos = tmp_path / 'catalogos_privados'; catalogos.mkdir()
    (catalogos / 'choferes.json').write_text(json.dumps({
        REF: {'nombre': 'ANA TEST', 'activo': True},
        '111111111': {'nombre': 'OTRO CHOFER', 'activo': True},
    }), encoding='utf-8')
    (tmp_path / 'operacion' / 'actual').mkdir(parents=True)
    inicializar_almacen(tmp_path, empresa='MBT', actor='TEST')
    return tmp_path


def _recibir(raiz, contenido=UNICA, origen='dfm_1', dos_caras=False):
    comun = dict(empresa='MBT', referencia_catalogo=REF, origen_documento_id=origen,
                 recibido_en='2026-10-30T14:35:07Z', comprobar=lambda: None)
    if dos_caras:
        caras = [{'cara': 'FRENTE', 'contenido': FRENTE, 'mime_type': 'image/jpeg', 'sha256': sha(FRENTE)},
                 {'cara': 'REVERSO', 'contenido': REVERSO, 'mime_type': 'image/png', 'sha256': sha(REVERSO)}]
        r = registrar_licencia_mobile_pendiente(raiz, caras=caras, **comun)
    else:
        r = registrar_licencia_mobile_pendiente(raiz, contenido=contenido, mime_type='image/jpeg',
                                                sha256=sha(contenido), **comun)
    extraer_licencias_pendientes(raiz, comprobar=lambda: None, fabrica_ocr=lambda: OCRFalso())
    return _doc(raiz, r['documento_id'])


def _ficha(raiz):
    return fichas_por_referencia(leer_almacen(raiz, empresa='MBT'))[REF]


def _doc(raiz, documento_id):
    return next(d for d in _ficha(raiz)['documentos'] if d['documento_id'] == documento_id)


def _confirmada(raiz):
    """Como la de Retamal: una imagen (formato histórico) y datos confirmados."""
    doc = _recibir(raiz)
    confirmar_licencia_chofer(raiz, empresa='MBT', ficha_id=_ficha(raiz)['ficha_id'], referencia_catalogo=REF,
                              documento_id=doc['documento_id'], sha256=doc['sha256'], rut=RUT, nombre='ANA TEST',
                              clase='A4', vencimiento='2028-05-07', autor='Javier', confirmacion_humana=True)
    return _doc(raiz, doc['documento_id'])


def _clasificar(raiz, doc, **cambios):
    argumentos = dict(empresa='MBT', ficha_id=_ficha(raiz)['ficha_id'], referencia_catalogo=REF,
                      documento_id=doc['documento_id'], sha256=doc['sha256'], autor='Javier Abreu',
                      confirmacion_humana=True)
    argumentos.update(cambios)
    return clasificar_anverso_licencia_chofer(raiz, **argumentos)


def test_clasifica_el_anverso_sin_tocar_datos_confirmados_ni_el_original(tmp_path):
    raiz = _raiz(tmp_path)
    doc = _confirmada(raiz)
    carpeta = ruta_almacen(raiz, 'MBT').parent
    original = (carpeta / doc['archivo']).read_bytes()
    historial_previo = copy.deepcopy(_ficha(raiz)['historial'])
    resultado = _clasificar(raiz, doc)
    assert resultado['ok'] and resultado['modificado'] and resultado['cara'] == 'FRENTE'
    [actual] = _ficha(raiz)['documentos']  # no se creó otra licencia
    clasificacion = actual.pop('clasificacion_cara')
    assert actual == doc  # formato histórico, archivo, datos, OCR y confirmación intactos
    assert 'formato' not in actual and 'caras' not in actual  # sigue siendo de una imagen; sin reverso
    assert clasificacion['cara'] == 'FRENTE' and clasificacion['sha256'] == doc['sha256'] == sha(UNICA)
    assert clasificacion['archivo'] == doc['archivo']
    assert clasificacion['autor'] == 'Javier Abreu' and clasificacion['actor'] == 'DESKTOP'
    assert clasificacion['confirmacion_humana'] is True and clasificacion['fecha']
    assert (carpeta / doc['archivo']).read_bytes() == original
    historial = _ficha(raiz)['historial']
    assert historial[:-1] == historial_previo
    assert {k: historial[-1][k] for k in ('accion', 'autor', 'documento_id', 'sha256')} == {
        'accion': 'LICENCIA_ANVERSO_CLASIFICADO', 'autor': 'Javier Abreu',
        'documento_id': doc['documento_id'], 'sha256': doc['sha256']}
    manifiesto = json.loads((Path(resultado['respaldo']) / 'manifest.json').read_text(encoding='utf-8'))
    assert manifiesto['operacion'] == 'LICENCIA_ANVERSO_CLASIFICADO' and manifiesto['sha256'] == doc['sha256']
    assert (Path(resultado['respaldo']) / 'fichas_documentales.json').is_file()


def test_repetir_es_idempotente_y_no_escribe(tmp_path):
    raiz = _raiz(tmp_path)
    doc = _confirmada(raiz)
    _clasificar(raiz, doc)
    antes = ruta_almacen(raiz, 'MBT').read_bytes()
    otra_vez = _clasificar(raiz, doc, autor='Otra Persona')
    assert otra_vez['ok'] and not otra_vez['modificado'] and otra_vez['cara'] == 'FRENTE'
    assert ruta_almacen(raiz, 'MBT').read_bytes() == antes


def test_solo_cambia_la_licencia_indicada(tmp_path):
    raiz = _raiz(tmp_path)
    primera = _recibir(raiz)
    segunda = _recibir(raiz, contenido=OTRA_UNICA, origen='dfm_2')
    _clasificar(raiz, segunda)
    assert _doc(raiz, primera['documento_id']) == primera
    assert 'clasificacion_cara' in _doc(raiz, segunda['documento_id'])


@pytest.mark.parametrize('cambios, motivo', [
    ({'confirmacion_humana': False}, 'confirmación explícita'),
    ({'autor': ' '}, 'Indique quién'),
    ({'sha256': '0' * 64}, 'recargue la ficha'),
    ({'sha256': 'no-es-huella'}, 'recargue la ficha'),
    ({'documento_id': 'otro'}, 'no pertenece a esta ficha'),
    ({'referencia_catalogo': '111111111'}, 'identidad de la ficha'),
    ({'referencia_catalogo': '999999999'}, 'chofer vigente'),
])
def test_datos_invalidos_no_escriben_nada(tmp_path, cambios, motivo):
    raiz = _raiz(tmp_path)
    doc = _confirmada(raiz)
    antes = ruta_almacen(raiz, 'MBT').read_bytes()
    with pytest.raises(ValueError, match=motivo):
        _clasificar(raiz, doc, **cambios)
    assert ruta_almacen(raiz, 'MBT').read_bytes() == antes


def test_licencia_de_dos_caras_no_se_clasifica(tmp_path):
    raiz = _raiz(tmp_path)
    doc = _recibir(raiz, dos_caras=True)
    antes = ruta_almacen(raiz, 'MBT').read_bytes()
    with pytest.raises(ValueError, match='una sola imagen'):
        _clasificar(raiz, doc)
    assert ruta_almacen(raiz, 'MBT').read_bytes() == antes


def test_original_alterado_no_se_clasifica(tmp_path):
    raiz = _raiz(tmp_path)
    doc = _confirmada(raiz)
    (ruta_almacen(raiz, 'MBT').parent / doc['archivo']).write_bytes(b'\xff\xd8\xff\xe0otra imagen')
    antes = ruta_almacen(raiz, 'MBT').read_bytes()
    with pytest.raises(ValueError, match='no coincide con la huella'):
        _clasificar(raiz, doc)
    assert ruta_almacen(raiz, 'MBT').read_bytes() == antes


def test_licencia_reemplazada_no_se_clasifica(tmp_path):
    raiz = _raiz(tmp_path)
    doc = _confirmada(raiz)
    ruta = ruta_almacen(raiz, 'MBT')
    datos = json.loads(ruta.read_text(encoding='utf-8'))
    fichas_por_referencia(datos)[REF]['documentos'][0]['reemplazado_por'] = 'otra-licencia'
    ruta.write_text(json.dumps(datos), encoding='utf-8')
    antes = ruta.read_bytes()
    with pytest.raises(ValueError, match='reemplazada'):
        _clasificar(raiz, doc)
    assert ruta.read_bytes() == antes


def test_esquema_rechaza_una_clasificacion_incoherente(tmp_path):
    raiz = _raiz(tmp_path)
    doc = _confirmada(raiz)
    _clasificar(raiz, doc)
    ruta = ruta_almacen(raiz, 'MBT')
    datos = json.loads(ruta.read_text(encoding='utf-8'))
    for cambio in ({'cara': 'REVERSO'}, {'sha256': '0' * 64}, {'confirmacion_humana': False}):
        alterado = copy.deepcopy(datos)
        fichas_por_referencia(alterado)[REF]['documentos'][0]['clasificacion_cara'].update(cambio)
        ruta.write_text(json.dumps(alterado), encoding='utf-8')
        with pytest.raises(ValueError, match='Clasificación de cara'):
            leer_almacen(raiz, empresa='MBT')


def test_canal_oficial_desktop_exige_la_marca_y_conserva_la_licencia(tmp_path):
    assert 'clasificar_anverso_licencia.py' in ESCRITORES
    raiz = _raiz(tmp_path)
    doc = _confirmada(raiz)
    args = [str(RAIZ_MOTOR / 'clasificar_anverso_licencia.py'), '--raiz-atlas', str(raiz),
            '--ficha-id', _ficha(raiz)['ficha_id'], '--referencia-catalogo', REF,
            '--documento-id', doc['documento_id'], '--sha256', doc['sha256'], '--autor', 'Javier Abreu']
    antes = ruta_almacen(raiz, 'MBT').read_bytes()

    def por_canal(argumentos):
        solicitud = {'accion': 'script', 'raiz': str(raiz), 'argumentos': argumentos, 'entrada': None}
        return subprocess.run([sys.executable, '-I', '-X', 'utf8', '-B', '-u', str(RAIZ_MOTOR / 'desktop_operacion_cli.py')],
                              input=json.dumps(solicitud), capture_output=True, text=True, encoding='utf-8',
                              cwd=RAIZ_MOTOR)

    sin_marca = por_canal(args)
    assert sin_marca.returncode != 0 and 'confirmación explícita' in sin_marca.stderr
    assert ruta_almacen(raiz, 'MBT').read_bytes() == antes
    con_marca = por_canal(args + ['--confirmo-revision-humana'])
    assert con_marca.returncode == 0, con_marca.stderr
    assert json.loads(json.loads(con_marca.stdout)['salida'])['modificado'] is True
    actual = _doc(raiz, doc['documento_id'])
    assert actual['clasificacion_cara']['cara'] == 'FRENTE'
    assert actual['estado_revision'] == 'CONFIRMADA' and actual['confirmacion_humana'] == doc['confirmacion_humana']
