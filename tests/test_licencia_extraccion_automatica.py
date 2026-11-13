"""Licencia adjuntada en Desktop: original conservado, lectura automática y
registro sin confirmación humana sólo de los datos confiables.

Sólo datos ficticios en tmp_path (fuera de una unidad compartida: la sesión
oficial corre sin lease, igual que las demás pruebas de fichas). El OCR se
simula; los PDF se construyen a mano (`fixtures_pdf_sinteticos`).
"""
import hashlib
import json
import subprocess
import sys
import uuid
from datetime import date
from pathlib import Path

import pytest

from atlas_core.desktop_operacion import ESCRITORES
from atlas_core.extraccion_licencias import (
    EXTRAIDO, evaluar_registro_automatico, extraer_campos_licencia, extraer_licencias_pendientes,
)
from atlas_core.fichas_choferes import (
    ESTADO_REGISTRO_AUTOMATICO, confirmar_licencia_chofer, fichas_por_referencia, inicializar_almacen,
    leer_almacen, registrar_licencia_chofer, registrar_licencia_mobile_pendiente, ruta_almacen,
)
from atlas_core.validadores import _digito_verificador
from registrar_licencia_chofer import adjuntar_automatica
from tests.fixtures_pdf_sinteticos import construir_pdf, pagina_escaneada, pagina_texto

RAIZ_MOTOR = Path(__file__).resolve().parent.parent
REF = '123456785'
RUT = '12.345.678-5'
OTRO_RUT = f'15.432.876-{_digito_verificador("15432876")}'
HOY = date(2026, 11, 12)
LINEAS_LICENCIA = ['REPUBLICA DE CHILE', 'LICENCIA DE CONDUCTOR', 'APELLIDOS', 'TEST SOTO', 'NOMBRES', 'ANA MARIA',
                   f'RUN {RUT}', 'CLASE A4', 'FECHA DE CONTROL', '15/03/2029', 'FECHA ULTIMO CONTROL 15/03/2023']
sha = lambda b: hashlib.sha256(b).hexdigest()


class OCRFalso:
    def __init__(self, lineas):
        self.lineas, self.leidas, self.cerrado = lineas, [], False

    def leer_texto(self, ruta):
        self.leidas.append(Path(ruta).suffix.lower())
        return self.lineas

    def cerrar(self):
        self.cerrado = True


def _raiz(tmp_path):
    raiz = tmp_path / 'raiz'
    catalogos = raiz / 'catalogos_privados'; catalogos.mkdir(parents=True)
    (catalogos / 'choferes.json').write_text(json.dumps({
        REF: {'nombre': 'ANA TEST', 'activo': True, 'aliases': ['ANA MARIA TEST SOTO']},
        '111111111': {'nombre': 'OTRO CHOFER', 'activo': True},
    }), encoding='utf-8')
    (raiz / 'operacion' / 'actual').mkdir(parents=True)
    inicializar_almacen(raiz, empresa='MBT', actor='TEST')
    return raiz


def _ficha(raiz):
    return fichas_por_referencia(leer_almacen(raiz, empresa='MBT'))[REF]


def _doc(raiz, documento_id):
    return next(d for d in _ficha(raiz)['documentos'] if d['documento_id'] == documento_id)


def _archivo(tmp_path, nombre, contenido):
    ruta = tmp_path / 'entrada' / nombre
    ruta.parent.mkdir(exist_ok=True)
    ruta.write_bytes(contenido)
    return ruta


def _pdf_texto(tmp_path, lineas=LINEAS_LICENCIA, nombre='licencia.pdf'):
    return _archivo(tmp_path, nombre, construir_pdf([pagina_texto(*lineas)]))


def _adjuntar(raiz, archivo):
    return adjuntar_automatica(raiz, empresa='MBT', ficha_id=_ficha(raiz)['ficha_id'], referencia_catalogo=REF,
                               archivo=archivo)


def _licencia_confirmada(raiz, tmp_path, vencimiento='2027-01-31', clase='A2'):
    r = registrar_licencia_chofer(raiz, empresa='MBT', ficha_id=_ficha(raiz)['ficha_id'], referencia_catalogo=REF,
                                  vencimiento=vencimiento, clase=clase,
                                  archivo_origen=_archivo(tmp_path, f'anterior-{uuid.uuid4().hex}.pdf', b'%PDF-1.4 anterior'))
    return r['documento_id']


def _pull(raiz, ocr):
    return extraer_licencias_pendientes(raiz, comprobar=lambda: None, fabrica_ocr=lambda: ocr, hoy=HOY)


# ---------------------------------------------------------------- PDF con texto: registro inmediato


def test_pdf_con_texto_se_registra_solo_sin_confirmacion_humana(tmp_path):
    raiz = _raiz(tmp_path)
    archivo = _pdf_texto(tmp_path)
    resultado = _adjuntar(raiz, archivo)
    assert resultado['ok'] and resultado['estado'] == 'REGISTRADA' and resultado['vencimiento'] == '2029-03-15'
    assert resultado['registrados'] == ['clase', 'nombre', 'rut', 'vencimiento'] and resultado['por_completar'] == []
    doc = _doc(raiz, resultado['documento_id'])
    assert doc['vencimiento'] == '2029-03-15' and doc['clase'] == 'A4'
    assert doc['titular'] == {'rut': '12.345.678-5', 'nombre': 'ANA MARIA TEST SOTO'}
    assert doc['estado_revision'] == ESTADO_REGISTRO_AUTOMATICO and doc['origen'] == 'DESKTOP'
    registro = doc['registro_automatico']
    assert registro['procedencia'] == 'EXTRACCION_AUTOMATICA' and registro['confirmado_por_humano'] is False
    assert registro['sha256'] == doc['sha256'] == sha(archivo.read_bytes())
    assert 'confirmacion_humana' not in doc
    extraccion = doc['extraccion_automatica']
    assert extraccion['confirmado_por_humano'] is False and extraccion['archivos'][0]['paginas'] == ['TEXTO_EMBEBIDO']
    # Original conservado tal cual, dentro de la empresa.
    guardado = ruta_almacen(raiz, 'MBT').parent / doc['archivo']
    assert guardado.read_bytes() == archivo.read_bytes() and guardado.suffix == '.pdf'
    acciones = [h['accion'] for h in _ficha(raiz)['historial'] if h.get('documento_id') == doc['documento_id']]
    assert acciones == ['LICENCIA_ADJUNTADA_DESKTOP', 'LICENCIA_EXTRACCION_AUTOMATICA', 'LICENCIA_REGISTRADA_AUTOMATICA']


def test_renovacion_reemplaza_la_anterior_y_la_conserva(tmp_path):
    raiz = _raiz(tmp_path)
    anterior = _licencia_confirmada(raiz, tmp_path, vencimiento='2027-01-31')
    resultado = _adjuntar(raiz, _pdf_texto(tmp_path))
    assert resultado['estado'] == 'REGISTRADA' and resultado['reemplazados'] == 1
    previo = _doc(raiz, anterior)
    assert previo['reemplazado_por'] == resultado['documento_id']
    assert previo['vencimiento'] == '2027-01-31' and previo['clase'] == 'A2'  # sus datos no cambian
    assert _doc(raiz, resultado['documento_id'])['reemplaza_documentos'] == [anterior]


def test_no_deja_atras_una_licencia_que_vence_despues(tmp_path):
    raiz = _raiz(tmp_path)
    vigente = _licencia_confirmada(raiz, tmp_path, vencimiento='2031-06-30', clase='A5')
    antes = _doc(raiz, vigente)
    resultado = _adjuntar(raiz, _pdf_texto(tmp_path))
    assert resultado['estado'] == 'POR_COMPLETAR' and resultado['vencimiento'] is None
    doc = _doc(raiz, resultado['documento_id'])
    assert doc['estado_revision'] == 'PENDIENTE_EXTRACCION' and 'vencimiento' not in doc
    assert doc['extraccion_automatica']['registro']['motivo'] == 'VENCE_ANTES_QUE_LA_REGISTRADA'
    assert _doc(raiz, vigente) == antes


def test_clase_ilegible_registra_vencimiento_y_deja_la_clase_por_completar(tmp_path):
    raiz = _raiz(tmp_path)
    lineas = [l for l in LINEAS_LICENCIA if not l.startswith('CLASE')]
    resultado = _adjuntar(raiz, _pdf_texto(tmp_path, lineas))
    assert resultado['estado'] == 'REGISTRADA' and resultado['por_completar'] == ['clase']
    doc = _doc(raiz, resultado['documento_id'])
    assert doc['vencimiento'] == '2029-03-15' and 'clase' not in doc
    assert doc['registro_automatico']['pendientes'] == {'clase': 'NO_ENCONTRADO'}


def test_vencimiento_ambiguo_no_registra_nada(tmp_path):
    raiz = _raiz(tmp_path)
    lineas = LINEAS_LICENCIA + ['VENCIMIENTO 20/04/2030']  # dos fechas de control distintas
    resultado = _adjuntar(raiz, _pdf_texto(tmp_path, lineas))
    assert resultado['estado'] == 'POR_COMPLETAR' and 'vencimiento' in resultado['por_completar']
    doc = _doc(raiz, resultado['documento_id'])
    assert doc['estado_revision'] == 'PENDIENTE_EXTRACCION'
    assert not {'vencimiento', 'clase', 'titular', 'registro_automatico'} & set(doc)
    assert doc['extraccion_automatica']['campos']['vencimiento']['motivo'] == 'CONTRADICCION'


def test_vencimiento_fuera_de_rango_no_se_registra(tmp_path):
    raiz = _raiz(tmp_path)
    lineas = [l if l != '15/03/2029' else '15/03/2099' for l in LINEAS_LICENCIA]
    resultado = _adjuntar(raiz, _pdf_texto(tmp_path, lineas))
    assert resultado['estado'] == 'POR_COMPLETAR'
    assert _doc(raiz, resultado['documento_id'])['extraccion_automatica']['registro']['pendientes']['vencimiento'] \
        == 'FUERA_DE_RANGO'


@pytest.mark.parametrize('cambio', [
    lambda l: l.replace(RUT, OTRO_RUT),  # licencia de otra persona
    lambda l: l.replace('TEST SOTO', 'PEREZ ROJAS'),  # nombre que no es el del chofer
], ids=['otro-rut', 'otro-nombre'])
def test_identidad_que_no_coincide_bloquea_todo_el_registro(tmp_path, cambio):
    raiz = _raiz(tmp_path)
    vigente = _licencia_confirmada(raiz, tmp_path)
    resultado = _adjuntar(raiz, _pdf_texto(tmp_path, [cambio(l) for l in LINEAS_LICENCIA]))
    assert resultado['estado'] == 'POR_COMPLETAR'
    doc = _doc(raiz, resultado['documento_id'])
    assert doc['extraccion_automatica']['registro']['motivo'] == 'IDENTIDAD_NO_COINCIDE'
    assert 'vencimiento' not in doc and 'reemplazado_por' not in _doc(raiz, vigente)


def test_sin_rut_legible_basta_el_nombre_del_catalogo(tmp_path):
    raiz = _raiz(tmp_path)
    resultado = _adjuntar(raiz, _pdf_texto(tmp_path, [l for l in LINEAS_LICENCIA if not l.startswith('RUN')]))
    assert resultado['estado'] == 'REGISTRADA' and resultado['por_completar'] == ['rut']
    assert _doc(raiz, resultado['documento_id'])['titular'] == {'nombre': 'ANA MARIA TEST SOTO'}


# ---------------------------------------------------------------- OCR: lo lee el ciclo PULL


@pytest.mark.parametrize('nombre,contenido,extension', [
    ('licencia.pdf', construir_pdf([pagina_escaneada('LICENCIA')]), '.png'),  # PDF escaneado: se rasteriza
    ('licencia.jpg', b'\xff\xd8\xff\xe0foto de la licencia', '.jpg'),
], ids=['pdf-escaneado', 'foto'])
def test_lo_que_necesita_ocr_queda_para_el_ciclo_pull_y_se_registra_ahi(tmp_path, nombre, contenido, extension):
    raiz = _raiz(tmp_path)
    resultado = _adjuntar(raiz, _archivo(tmp_path, nombre, contenido))
    assert resultado['estado'] == 'LECTURA_PENDIENTE' and resultado['por_completar'] == []
    doc = _doc(raiz, resultado['documento_id'])
    assert doc['estado_revision'] == 'PENDIENTE_EXTRACCION' and 'extraccion_automatica' not in doc
    ocr = OCRFalso(LINEAS_LICENCIA)
    resumen = _pull(raiz, ocr)
    assert ocr.leidas == [extension] and ocr.cerrado
    assert resumen['extraidas'][0]['registro']['registrada'] is True
    doc = _doc(raiz, resultado['documento_id'])
    assert doc['estado_revision'] == ESTADO_REGISTRO_AUTOMATICO and doc['vencimiento'] == '2029-03-15'
    assert doc['registro_automatico']['actor'] == 'MOTOR_OCR'
    assert _pull(raiz, OCRFalso([]))['pendientes'] == 0  # una sola vez


def test_lectura_desktop_sin_ocr_no_escribe_y_avisa_diferida(tmp_path):
    raiz = _raiz(tmp_path)
    resultado = _adjuntar(raiz, _archivo(tmp_path, 'licencia.png', b'\x89PNG\r\n\x1a\nfoto'))
    antes = ruta_almacen(raiz, 'MBT').read_bytes()
    lectura = extraer_licencias_pendientes(raiz, comprobar=lambda: None, fabrica_ocr=None,
                                           documento_id=resultado['documento_id'], permitir_ocr=False)
    assert lectura['diferidas'] == [resultado['documento_id']] and lectura['extraidas'] == []
    assert ruta_almacen(raiz, 'MBT').read_bytes() == antes


def test_pdf_con_demasiadas_paginas_no_se_lee_y_queda_para_una_persona(tmp_path):
    raiz = _raiz(tmp_path)
    pdf = construir_pdf([pagina_texto(*LINEAS_LICENCIA) for _ in range(5)])
    resultado = _adjuntar(raiz, _archivo(tmp_path, 'muchas.pdf', pdf))
    assert resultado['estado'] == 'LECTURA_PENDIENTE'
    resumen = _pull(raiz, OCRFalso(LINEAS_LICENCIA))
    assert 'páginas' in resumen['errores'][0]['error']
    assert _doc(raiz, resultado['documento_id'])['estado_revision'] == 'PENDIENTE_EXTRACCION'


# ---------------------------------------------------------------- Mobile y confirmación humana intactas


def test_licencia_mobile_completa_sigue_esperando_confirmacion_humana(tmp_path):
    raiz = _raiz(tmp_path)
    foto = b'\xff\xd8\xff\xe0licencia mobile'
    recibido = registrar_licencia_mobile_pendiente(
        raiz, empresa='MBT', referencia_catalogo=REF, origen_documento_id='dfm_1', recibido_en='2026-11-02T12:00:00Z',
        comprobar=lambda: None, contenido=foto, mime_type='image/jpeg', sha256=sha(foto))
    resumen = _pull(raiz, OCRFalso(LINEAS_LICENCIA))
    assert resumen['extraidas'][0]['estado'] == 'COMPLETA' and 'registro' not in resumen['extraidas'][0]
    doc = _doc(raiz, recibido['documento_id'])
    assert doc['estado_revision'] == 'PENDIENTE_EXTRACCION'
    assert not {'vencimiento', 'clase', 'registro_automatico'} & set(doc) and 'registro' not in doc['extraccion_automatica']


def test_una_persona_corrige_lo_registrado_y_queda_la_diferencia(tmp_path):
    raiz = _raiz(tmp_path)
    resultado = _adjuntar(raiz, _pdf_texto(tmp_path))
    doc = _doc(raiz, resultado['documento_id'])
    confirmar_licencia_chofer(raiz, empresa='MBT', ficha_id=_ficha(raiz)['ficha_id'], referencia_catalogo=REF,
                              documento_id=doc['documento_id'], sha256=doc['sha256'], rut=RUT,
                              nombre='ANA MARIA TEST SOTO', clase='A5', vencimiento='2029-03-15',
                              autor='Javier', confirmacion_humana=True)
    doc = _doc(raiz, resultado['documento_id'])
    assert doc['estado_revision'] == 'CONFIRMADA' and doc['clase'] == 'A5'
    assert doc['confirmacion_humana']['estado_revision_anterior'] == ESTADO_REGISTRO_AUTOMATICO
    assert doc['confirmacion_humana']['distintos_de_ocr'] == ['clases']  # se compara la lista de clases
    assert doc['registro_automatico']['campos'] == ['clase', 'nombre', 'rut', 'vencimiento']  # la lectura queda


def test_una_licencia_confirmada_no_se_vuelve_a_leer(tmp_path):
    raiz = _raiz(tmp_path)
    resultado = _adjuntar(raiz, _pdf_texto(tmp_path))
    antes = ruta_almacen(raiz, 'MBT').read_bytes()
    assert _pull(raiz, OCRFalso(['CLASE B', 'FECHA DE CONTROL 01/01/2030']))['pendientes'] == 0
    assert ruta_almacen(raiz, 'MBT').read_bytes() == antes and _doc(raiz, resultado['documento_id'])['clase'] == 'A4'


def test_el_expediente_la_ve_vigente_y_no_confirmada_por_una_persona(tmp_path):
    from atlas_core.expediente_digital import _documento_de_ficha
    raiz = _raiz(tmp_path)
    doc = _doc(raiz, _adjuntar(raiz, _pdf_texto(tmp_path))['documento_id'])
    vista = _documento_de_ficha(doc, 'CHOFER', [REF], 'FICHA_CHOFER')
    assert vista['fecha_vencimiento'] == '2029-03-15' and vista['pendiente_revision'] is False
    assert vista['confirmado_por_humano'] is False


# ---------------------------------------------------------------- regla pura


def test_regla_exige_rut_del_catalogo_cuando_el_catalogo_lo_tiene():
    campos = extraer_campos_licencia({'UNICA': LINEAS_LICENCIA})
    assert campos['rut']['estado'] == EXTRAIDO
    comun = dict(registros_catalogo=[{'nombre': 'ANA TEST'}], vigentes=[], hoy=HOY)
    assert evaluar_registro_automatico(campos, ruts_catalogo=['123456785'], **comun)['registrar'] is True
    # Sin RUT en el catálogo, un RUT leído no se puede verificar: no se registra solo.
    assert evaluar_registro_automatico(campos, ruts_catalogo=[], **comun)['motivo'] == 'IDENTIDAD_NO_VERIFICADA'


# ---------------------------------------------------------------- CLI


def test_cli_automatica_entrega_solo_json_y_modo_manual_intacto(tmp_path):
    raiz = _raiz(tmp_path)
    assert 'registrar_licencia_chofer.py' in ESCRITORES
    base = [sys.executable, str(RAIZ_MOTOR / 'registrar_licencia_chofer.py'), '--raiz-atlas', str(raiz),
            '--ficha-id', _ficha(raiz)['ficha_id'], '--referencia-catalogo', REF, '--archivo', str(_pdf_texto(tmp_path))]
    salida = subprocess.run([*base, '--automatica'], cwd=RAIZ_MOTOR, capture_output=True, text=True, check=True)
    resultado = json.loads(salida.stdout)
    assert resultado['estado'] == 'REGISTRADA' and resultado['vencimiento'] == '2029-03-15'
    sin_datos = subprocess.run(base, cwd=RAIZ_MOTOR, capture_output=True, text=True)
    con_datos = subprocess.run([*base, '--automatica', '--clase', 'B'], cwd=RAIZ_MOTOR, capture_output=True, text=True)
    assert sin_datos.returncode == 2 and '--vencimiento' in sin_datos.stderr
    assert con_datos.returncode == 2 and '--automatica' in con_datos.stderr


@pytest.mark.parametrize('nombre,contenido,estado', [
    ('licencia.pdf', None, 'REGISTRADA'),
    ('licencia.jpg', b'\xff\xd8\xff\xe0foto de la licencia', 'LECTURA_PENDIENTE'),
], ids=['pdf-texto', 'foto'])
def test_canal_oficial_desktop_adjunta_y_lee_sin_procesos_ajenos(tmp_path, nombre, contenido, estado):
    """El mismo camino que usa Desktop: desktop_operacion_cli (auditoría de
    escrituras y procesos activa). La lectura de PDF no lanza procesos."""
    raiz = _raiz(tmp_path)
    archivo = _pdf_texto(tmp_path) if contenido is None else _archivo(tmp_path, nombre, contenido)
    args = [str(RAIZ_MOTOR / 'registrar_licencia_chofer.py'), '--raiz-atlas', str(raiz), '--automatica',
            '--ficha-id', _ficha(raiz)['ficha_id'], '--referencia-catalogo', REF, '--archivo', str(archivo)]
    solicitud = {'accion': 'script', 'raiz': str(raiz), 'argumentos': args, 'entrada': None}
    proceso = subprocess.run([sys.executable, '-I', '-X', 'utf8', '-B', '-u', str(RAIZ_MOTOR / 'desktop_operacion_cli.py')],
                             input=json.dumps(solicitud), capture_output=True, text=True, cwd=RAIZ_MOTOR)
    assert proceso.returncode == 0, proceso.stderr
    resultado = json.loads(json.loads(proceso.stdout)['salida'])
    assert resultado['ok'] and resultado['estado'] == estado
    doc = _doc(raiz, resultado['documento_id'])
    assert (ruta_almacen(raiz, 'MBT').parent / doc['archivo']).read_bytes() == archivo.read_bytes()


# ---------------------------------------------------------------- frente real: fecha antes del rótulo

# Orden real del OCR del frente actual (sintético): la fecha de cada control
# aparece ANTES de su rótulo y un rótulo viene cortado ("ULTMO").
FRENTE_ACTUAL = ['LICENCIADECONDUCTOR', 'A4 Ley19495', f'RUN {RUT}', '09/08/2024', 'FECHA ULTMOCONTROL',
                 '09/08/2028', 'FECHADECONTROL']


def test_par_de_fechas_de_control_da_el_vencimiento_solo_si_se_pide():
    sin = extraer_campos_licencia({'FRENTE': FRENTE_ACTUAL})
    con = extraer_campos_licencia({'FRENTE': FRENTE_ACTUAL}, inferir_vencimiento_por_controles=True)
    assert sin['vencimiento']['estado'] != EXTRAIDO
    assert con['vencimiento']['valor'] == '2028-08-09' and con['vencimiento']['metodo'] == 'PAR_FECHAS_CONTROL'


@pytest.mark.parametrize('lineas', [
    ['01/02/1980'] + FRENTE_ACTUAL,  # tres fechas (nacimiento u otra): ambiguo
    [l if l != '09/08/2028' else '09/08/2040' for l in FRENTE_ACTUAL],  # 16 años entre controles
    [l for l in FRENTE_ACTUAL if 'ULTMO' not in l],  # sin rótulo de último control
], ids=['tres-fechas', 'intervalo-imposible', 'sin-rotulo'])
def test_par_de_fechas_ambiguo_no_infiere(lineas):
    campo = extraer_campos_licencia({'FRENTE': lineas}, inferir_vencimiento_por_controles=True)['vencimiento']
    assert campo['estado'] != EXTRAIDO and 'metodo' not in campo


def test_foto_del_frente_actual_se_registra_en_pull_y_mobile_no_infiere(tmp_path):
    raiz = _raiz(tmp_path)
    desktop = _adjuntar(raiz, _archivo(tmp_path, 'frente.jpg', b'\xff\xd8\xff\xe0frente actual'))
    foto = b'\xff\xd8\xff\xe0frente mobile'
    mobile = registrar_licencia_mobile_pendiente(
        raiz, empresa='MBT', referencia_catalogo=REF, origen_documento_id='dfm_2', recibido_en='2026-11-02T12:00:00Z',
        comprobar=lambda: None, contenido=foto, mime_type='image/jpeg', sha256=sha(foto))
    _pull(raiz, OCRFalso(FRENTE_ACTUAL))
    doc = _doc(raiz, desktop['documento_id'])
    assert doc['estado_revision'] == ESTADO_REGISTRO_AUTOMATICO and doc['vencimiento'] == '2028-08-09' and doc['clase'] == 'A4'
    assert doc['registro_automatico']['pendientes'] == {'nombre': 'NO_ENCONTRADO'}
    propuesta = _doc(raiz, mobile['documento_id'])['extraccion_automatica']['campos']['vencimiento']
    assert propuesta['estado'] != EXTRAIDO and 'metodo' not in propuesta
