"""Confirmación humana de una licencia ya registrada (`confirmar_licencia_chofer`).

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
    confirmar_licencia_chofer, fichas_por_referencia, inicializar_almacen, leer_almacen,
    registrar_licencia_mobile_pendiente, ruta_almacen,
)
from atlas_core.validadores import _digito_verificador

RAIZ_MOTOR = Path(__file__).resolve().parent.parent
REF = '123456785'
RUT = '12.345.678-5'
OTRO_RUT = f'15.432.876-{_digito_verificador("15432876")}'
FRENTE = b'\xff\xd8\xff\xe0frente ficticio'
REVERSO = b'\x89PNG\r\n\x1a\nreverso ficticio'
UNICA = b'\xff\xd8\xff\xe0licencia antigua ficticia'
sha = lambda b: hashlib.sha256(b).hexdigest()


class OCRFalso:
    def __init__(self, lineas):
        self.lineas = lineas

    def leer_texto(self, ruta):
        return self.lineas


def _raiz(tmp_path):
    catalogos = tmp_path / 'catalogos_privados'; catalogos.mkdir()
    (catalogos / 'choferes.json').write_text(json.dumps({
        REF: {'nombre': 'ANA TEST', 'activo': True, 'aliases': ['ANITA TEST']},
        '111111111': {'nombre': 'OTRO CHOFER', 'activo': True},
    }), encoding='utf-8')
    (tmp_path / 'operacion' / 'actual').mkdir(parents=True)
    inicializar_almacen(tmp_path, empresa='MBT', actor='TEST')
    return tmp_path


def _recibir(raiz, *, dos_caras=True, origen='dfm_1'):
    comun = dict(empresa='MBT', referencia_catalogo=REF, origen_documento_id=origen,
                 recibido_en='2026-11-02T12:00:00Z', comprobar=lambda: None)
    if dos_caras:
        caras = [{'cara': 'FRENTE', 'contenido': FRENTE, 'mime_type': 'image/jpeg', 'sha256': sha(FRENTE)},
                 {'cara': 'REVERSO', 'contenido': REVERSO, 'mime_type': 'image/png', 'sha256': sha(REVERSO)}]
        r = registrar_licencia_mobile_pendiente(raiz, caras=caras, **comun)
    else:
        r = registrar_licencia_mobile_pendiente(raiz, contenido=UNICA, mime_type='image/jpeg', sha256=sha(UNICA),
                                                **comun)
    # Lectura OCR parcial ficticia (RUT y clase), igual que en producción.
    extraer_licencias_pendientes(raiz, comprobar=lambda: None,
                                 fabrica_ocr=lambda: OCRFalso([f'RUN {RUT}', 'A4 Ley19495']))
    return _doc(raiz, r['documento_id'])


def _ficha(raiz):
    return fichas_por_referencia(leer_almacen(raiz, empresa='MBT'))[REF]


def _doc(raiz, documento_id):
    return next(d for d in _ficha(raiz)['documentos'] if d['documento_id'] == documento_id)


def _confirmar(raiz, doc, **cambios):
    argumentos = dict(empresa='MBT', ficha_id=_ficha(raiz)['ficha_id'], referencia_catalogo=REF,
                      documento_id=doc['documento_id'], sha256=doc['sha256'], rut='12345678-5',
                      nombre='Ana María Test Soto', clase='a4', vencimiento='2028-05-07', autor='Javier',
                      confirmacion_humana=True)
    argumentos.update(cambios)
    return confirmar_licencia_chofer(raiz, **argumentos)


# ---------------------------------------------------------------- confirmación


def test_confirma_el_mismo_documento_de_dos_caras_y_conserva_ocr_y_fotos(tmp_path):
    raiz = _raiz(tmp_path)
    doc = _recibir(raiz)
    catalogo = (raiz / 'catalogos_privados' / 'choferes.json').read_bytes()
    extraccion = copy.deepcopy(doc['extraccion_automatica'])
    resultado = _confirmar(raiz, doc)
    assert resultado['modificado'] and resultado['accion'] == 'LICENCIA_CONFIRMADA'
    ficha = _ficha(raiz)
    [confirmado] = ficha['documentos']  # una sola licencia lógica: no se creó otra
    assert confirmado['documento_id'] == doc['documento_id'] and not confirmado.get('reemplazado_por')
    assert confirmado['estado_revision'] == 'CONFIRMADA'
    assert (confirmado['clase'], confirmado['vencimiento']) == ('A4', '2028-05-07')
    assert confirmado['titular'] == {'rut': '12.345.678-5', 'nombre': 'ANA MARIA TEST SOTO'}
    assert confirmado['extraccion_automatica'] == extraccion  # OCR original íntegro
    assert confirmado['caras'] == doc['caras'] and confirmado['sha256'] == doc['sha256']
    carpeta = ruta_almacen(raiz, 'MBT').parent
    assert [(carpeta / c['archivo']).read_bytes() for c in confirmado['caras']] == [FRENTE, REVERSO]
    assert (raiz / 'catalogos_privados' / 'choferes.json').read_bytes() == catalogo
    # Auditoría: autor, fecha, anteriores, nuevos y diferencias con la lectura OCR.
    confirmacion = confirmado['confirmacion_humana']
    assert confirmacion['autor'] == 'Javier' and confirmacion['actor'] == 'DESKTOP' and confirmacion['fecha']
    # Clases como lista (`clases`) además del texto `clase`; sin clases previas, lista vacía.
    assert confirmacion['anteriores'] == {**dict.fromkeys(('rut', 'nombre', 'clase', 'vencimiento')), 'clases': []}
    assert confirmacion['valores'] == {'rut': '12.345.678-5', 'nombre': 'ANA MARIA TEST SOTO',
                                       'clase': 'A4', 'clases': ['A4'], 'vencimiento': '2028-05-07'}
    assert confirmacion['estado_revision_anterior'] == 'PENDIENTE_EXTRACCION'
    assert confirmacion['distintos_de_ocr'] == ['nombre', 'vencimiento']
    assert ficha['historial'][-1] == {'accion': 'LICENCIA_CONFIRMADA', 'actor': 'DESKTOP', 'autor': 'Javier',
                                      'fecha': confirmacion['fecha'], 'documento_id': doc['documento_id'],
                                      'campos': ['clases', 'nombre', 'rut', 'vencimiento']}
    manifiesto = json.loads((Path(resultado['respaldo']) / 'manifest.json').read_text(encoding='utf-8'))
    assert manifiesto['operacion'] == 'LICENCIA_CONFIRMADA' and manifiesto['autor'] == 'Javier'


def test_correccion_posterior_conserva_la_confirmacion_previa_y_repetir_no_escribe(tmp_path):
    raiz = _raiz(tmp_path)
    doc = _recibir(raiz)
    _confirmar(raiz, doc)
    primera = _doc(raiz, doc['documento_id'])['confirmacion_humana']
    resultado = _confirmar(raiz, doc, vencimiento='2029-05-07', autor='Supervisor')
    assert resultado['accion'] == 'LICENCIA_CORREGIDA'
    corregido = _doc(raiz, doc['documento_id'])
    assert corregido['vencimiento'] == '2029-05-07' and corregido['confirmaciones_anteriores'] == [primera]
    assert corregido['confirmacion_humana']['anteriores']['vencimiento'] == '2028-05-07'
    assert _ficha(raiz)['historial'][-1]['campos'] == ['vencimiento']
    revision = leer_almacen(raiz, empresa='MBT')['revision']
    assert not _confirmar(raiz, doc, vencimiento='2029-05-07')['modificado']
    assert leer_almacen(raiz, empresa='MBT')['revision'] == revision


def test_licencia_antigua_de_una_imagen_se_confirma_sin_volverse_de_dos_caras(tmp_path):
    raiz = _raiz(tmp_path)
    doc = _recibir(raiz, dos_caras=False)
    _confirmar(raiz, doc, nombre='Anita Test')  # alias del catálogo
    confirmado = _doc(raiz, doc['documento_id'])
    assert confirmado['estado_revision'] == 'CONFIRMADA' and 'caras' not in confirmado and 'formato' not in confirmado
    assert (ruta_almacen(raiz, 'MBT').parent / confirmado['archivo']).read_bytes() == UNICA


def test_licencia_confirmada_ya_no_es_extraida_por_ocr(tmp_path):
    raiz = _raiz(tmp_path)
    doc = _recibir(raiz)
    _confirmar(raiz, doc)
    llamadas = []
    assert extraer_licencias_pendientes(raiz, comprobar=lambda: None,
                                        fabrica_ocr=lambda: llamadas.append(1))['pendientes'] == 0
    assert not llamadas


# ---------------------------------------------------------------- rechazos


@pytest.mark.parametrize('cambios,motivo', [
    ({'confirmacion_humana': False}, 'confirmación explícita'),
    ({'confirmacion_humana': 'si'}, 'confirmación explícita'),
    ({'autor': ' '}, 'quién confirma'),
    ({'rut': '12.345.678-9'}, 'RUT de la licencia no es válido'),
    ({'rut': OTRO_RUT}, 'no corresponde al chofer'),
    ({'nombre': 'OTRA PERSONA'}, 'nombre de la licencia no coincide'),
    ({'nombre': 'ANA'}, 'nombre completo'),
    ({'nombre': 'ANA TEST 123'}, 'nombre completo'),
    ({'clase': 'clase 4'}, 'clase de licencia'),
    ({'vencimiento': '07/05/2028'}, 'AAAA-MM-DD'),
    ({'vencimiento': '2028-02-30'}, 'no es válida'),
    ({'sha256': '0' * 64}, 'cambió desde que se revisó'),
    ({'documento_id': 'no-existe'}, 'no pertenece a esta ficha'),
    ({'referencia_catalogo': '111111111'}, 'identidad de la ficha cambió'),
])
def test_datos_invalidos_o_incoherentes_no_escriben_nada(tmp_path, cambios, motivo):
    raiz = _raiz(tmp_path)
    doc = _recibir(raiz)
    antes = ruta_almacen(raiz, 'MBT').read_bytes()
    with pytest.raises(ValueError, match=motivo):
        _confirmar(raiz, doc, **cambios)
    assert ruta_almacen(raiz, 'MBT').read_bytes() == antes


def test_licencia_reemplazada_no_se_confirma(tmp_path):
    raiz = _raiz(tmp_path)
    doc = _recibir(raiz)
    datos = leer_almacen(raiz, empresa='MBT')
    fichas_por_referencia(datos)[REF]['documentos'][0]['reemplazado_por'] = 'otra'
    ruta_almacen(raiz, 'MBT').write_text(json.dumps(datos), encoding='utf-8')
    antes = ruta_almacen(raiz, 'MBT').read_bytes()
    with pytest.raises(ValueError, match='reemplazada'):
        _confirmar(raiz, doc)
    assert ruta_almacen(raiz, 'MBT').read_bytes() == antes


def test_chofer_sin_rut_confirmado_en_catalogo_no_se_confirma(tmp_path):
    raiz = _raiz(tmp_path)
    catalogo = raiz / 'catalogos_privados' / 'choferes.json'
    datos = json.loads(catalogo.read_text(encoding='utf-8'))
    datos['PENDIENTE00000007'] = {'nombre': 'SIN RUT TEST', 'activo': True}  # clave temporal, nunca un RUT
    catalogo.write_text(json.dumps(datos), encoding='utf-8')
    inicializar_almacen(raiz, empresa='MBT', actor='TEST')
    r = registrar_licencia_mobile_pendiente(raiz, empresa='MBT', referencia_catalogo='PENDIENTE00000007',
                                            origen_documento_id='dfm_sin_rut', recibido_en='2026-11-02T12:00:00Z',
                                            comprobar=lambda: None, contenido=UNICA, mime_type='image/jpeg',
                                            sha256=sha(UNICA))
    ficha = fichas_por_referencia(leer_almacen(raiz, empresa='MBT'))['PENDIENTE00000007']
    antes = ruta_almacen(raiz, 'MBT').read_bytes()
    with pytest.raises(ValueError, match='no tiene RUT confirmado'):
        confirmar_licencia_chofer(raiz, empresa='MBT', ficha_id=ficha['ficha_id'],
                                  referencia_catalogo='PENDIENTE00000007', documento_id=r['documento_id'],
                                  sha256=sha(UNICA), rut=RUT, nombre='SIN RUT TEST', clase='B',
                                  vencimiento='2028-01-01', autor='Javier', confirmacion_humana=True)
    assert ruta_almacen(raiz, 'MBT').read_bytes() == antes
    assert json.loads(catalogo.read_text(encoding='utf-8'))['PENDIENTE00000007'] == {'nombre': 'SIN RUT TEST',
                                                                                     'activo': True}


# ---------------------------------------------------------------- canal Desktop


def test_canal_oficial_desktop_exige_la_marca_de_confirmacion(tmp_path):
    assert 'confirmar_licencia_chofer.py' in ESCRITORES
    raiz = _raiz(tmp_path)
    doc = _recibir(raiz)
    base = [sys.executable, '-B', str(RAIZ_MOTOR / 'confirmar_licencia_chofer.py'), '--raiz-atlas', str(raiz),
            '--ficha-id', _ficha(raiz)['ficha_id'], '--referencia-catalogo', REF,
            '--documento-id', doc['documento_id'], '--sha256', doc['sha256'], '--rut', RUT,
            '--nombre', 'ANA TEST', '--clase', 'A4', '--vencimiento', '2028-05-07', '--autor', 'Javier']
    antes = ruta_almacen(raiz, 'MBT').read_bytes()
    sin_marca = subprocess.run(base, cwd=RAIZ_MOTOR, capture_output=True, text=True)
    assert sin_marca.returncode != 0 and 'confirmación explícita' in sin_marca.stderr
    assert ruta_almacen(raiz, 'MBT').read_bytes() == antes
    con_marca = subprocess.run(base + ['--confirmo-revision-humana'], cwd=RAIZ_MOTOR, capture_output=True, text=True)
    assert con_marca.returncode == 0, con_marca.stderr
    salida = json.loads(con_marca.stdout)
    assert salida['ok'] and salida['accion'] == 'LICENCIA_CONFIRMADA'
    assert _doc(raiz, doc['documento_id'])['estado_revision'] == 'CONFIRMADA'

def test_canal_desktop_confirma_sin_retomar_el_bloqueo_y_conserva_la_licencia(tmp_path):
    raiz = _raiz(tmp_path)
    doc = _recibir(raiz)
    ficha = _ficha(raiz)
    carpeta = ruta_almacen(raiz, 'MBT').parent
    fotos = [(carpeta / c['archivo']).read_bytes() for c in doc['caras']]
    args = [str(RAIZ_MOTOR / 'confirmar_licencia_chofer.py'), '--raiz-atlas', str(raiz),
            '--ficha-id', ficha['ficha_id'], '--referencia-catalogo', REF,
            '--documento-id', doc['documento_id'], '--sha256', doc['sha256'], '--rut', RUT,
            '--nombre', 'ANA TEST', '--clase', 'A4', '--vencimiento', '2028-05-07',
            '--autor', 'Javier', '--confirmo-revision-humana']
    solicitud = {'accion': 'script', 'raiz': str(raiz), 'argumentos': args, 'entrada': None}
    proceso = subprocess.run([sys.executable, '-I', '-X', 'utf8', '-B', '-u', str(RAIZ_MOTOR / 'desktop_operacion_cli.py')],
                             input=json.dumps(solicitud), capture_output=True, text=True, cwd=RAIZ_MOTOR)
    assert proceso.returncode == 0, proceso.stderr
    assert json.loads(json.loads(proceso.stdout)['salida'])['ok']
    [actual] = _ficha(raiz)['documentos']
    assert actual['documento_id'] == doc['documento_id']
    assert actual['extraccion_automatica'] == doc['extraccion_automatica']
    assert actual['confirmacion_humana']['autor'] == 'Javier'
    assert [(carpeta / c['archivo']).read_bytes() for c in actual['caras']] == fotos


def test_reutilizar_sesion_rechaza_otra_raiz(tmp_path):
    from atlas_core.desktop_operacion import sesion
    raiz = tmp_path / 'uno'; raiz.mkdir()
    otra = tmp_path / 'dos'; otra.mkdir()
    with sesion(raiz):
        with pytest.raises(PermissionError, match='ra.z no coincide'):
            with sesion(otra, reutilizar=True):
                pytest.fail('No debe aceptar otra raiz')


def test_reutilizar_sesion_comprueba_vigencia(tmp_path):
    from atlas_core import desktop_operacion as modulo
    def perdida():
        raise PermissionError('lease perdido')
    token = modulo._sesion_actual.set((tmp_path.resolve(), perdida))
    try:
        with pytest.raises(PermissionError, match='lease perdido'):
            with modulo.sesion(tmp_path, reutilizar=True):
                pytest.fail('No debe omitir la vigencia')
    finally:
        modulo._sesion_actual.reset(token)


def test_canal_desktop_rechaza_huella_distinta_sin_escribir(tmp_path):
    raiz = _raiz(tmp_path)
    doc = _recibir(raiz)
    archivo = ruta_almacen(raiz, 'MBT')
    antes = archivo.read_bytes()
    args = [str(RAIZ_MOTOR / 'confirmar_licencia_chofer.py'), '--raiz-atlas', str(raiz),
            '--ficha-id', _ficha(raiz)['ficha_id'], '--referencia-catalogo', REF,
            '--documento-id', doc['documento_id'], '--sha256', '0' * 64, '--rut', RUT,
            '--nombre', 'ANA TEST', '--clase', 'A4', '--vencimiento', '2028-05-07',
            '--autor', 'Javier', '--confirmo-revision-humana']
    solicitud = {'accion': 'script', 'raiz': str(raiz), 'argumentos': args}
    proceso = subprocess.run([sys.executable, '-I', '-X', 'utf8', '-B', '-u', str(RAIZ_MOTOR / 'desktop_operacion_cli.py')],
                             input=json.dumps(solicitud), capture_output=True, text=True, cwd=RAIZ_MOTOR)
    assert proceso.returncode != 0
    assert 'recargue la ficha' in proceso.stderr
    assert archivo.read_bytes() == antes
