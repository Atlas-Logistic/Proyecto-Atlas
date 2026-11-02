"""Extracción OCR de la licencia Mobile (`atlas_core.extraccion_licencias`).

Sólo datos sintéticos en tmp_path; el OCR se simula con un proveedor que
devuelve las líneas de cada imagen (misma interfaz `leer_texto`).
"""
import hashlib
import json
from pathlib import Path

import pytest

from atlas_core.extraccion_licencias import extraer_campos_licencia, extraer_licencias_pendientes
from atlas_core.fichas_choferes import (
    fichas_por_referencia, inicializar_almacen, leer_almacen,
    registrar_licencia_mobile_pendiente, ruta_almacen,
)
from atlas_core.validadores import _digito_verificador, validar_rut_chileno

RUT = '12.345.678-5'
OTRO_RUT = f'15.432.876-{_digito_verificador("15432876")}'
FRENTE = b'\xff\xd8\xff\xe0frente de la licencia'
REVERSO = b'\x89PNG\r\n\x1a\nreverso de la licencia'
UNICA = b'\xff\xd8\xff\xe0licencia antigua de una imagen'
sha = lambda b: hashlib.sha256(b).hexdigest()

LINEAS_FRENTE = ['REPÚBLICA DE CHILE', 'LICENCIA DE CONDUCTOR', 'Apellidos', 'TEST SOTO', 'Nombres', 'ANA MARÍA',
                 f'RUN: {RUT}', 'FECHA DE NACIMIENTO 01/02/1980']
LINEAS_REVERSO = ['CLASE A4', 'FECHA DE CONTROL', '15/03/2029', 'FECHA ULTIMO CONTROL 15/03/2023']


class OCRFalso:
    def __init__(self, textos):
        self.textos, self.leidas, self.cerrado = textos, [], False

    def leer_texto(self, ruta):
        contenido = Path(ruta).read_bytes()
        self.leidas.append(contenido)
        if isinstance(self.textos.get(contenido), Exception):
            raise self.textos[contenido]
        return self.textos[contenido]

    def cerrar(self):
        self.cerrado = True


def _raiz(tmp_path):
    catalogos = tmp_path / 'catalogos_privados'; catalogos.mkdir()
    (catalogos / 'choferes.json').write_text(json.dumps({'123456785': {'nombre': 'ANA TEST', 'activo': True}}),
                                             encoding='utf-8')
    (tmp_path / 'operacion' / 'actual').mkdir(parents=True)
    inicializar_almacen(tmp_path, empresa='MBT', actor='TEST')
    return tmp_path


def _recibir(raiz, origen='dfm_1', *, dos_caras=True, contenido=UNICA, mime='image/jpeg'):
    comun = dict(empresa='MBT', referencia_catalogo='123456785', origen_documento_id=origen,
                 recibido_en='2026-11-02T12:00:00Z', comprobar=lambda: None)
    if dos_caras:
        caras = [{'cara': 'FRENTE', 'contenido': FRENTE, 'mime_type': 'image/jpeg', 'sha256': sha(FRENTE)},
                 {'cara': 'REVERSO', 'contenido': REVERSO, 'mime_type': 'image/png', 'sha256': sha(REVERSO)}]
        return registrar_licencia_mobile_pendiente(raiz, caras=caras, **comun)
    return registrar_licencia_mobile_pendiente(raiz, contenido=contenido, mime_type=mime, sha256=sha(contenido),
                                               **comun)


def _extraer(raiz, ocr, comprobar=lambda: None):
    return extraer_licencias_pendientes(raiz, comprobar=comprobar, fabrica_ocr=lambda: ocr)


def _documento(raiz, documento_id):
    ficha = fichas_por_referencia(leer_almacen(raiz, empresa='MBT'))['123456785']
    return next(d for d in ficha['documentos'] if d['documento_id'] == documento_id), ficha


def _campos(frente, reverso=(), **opciones):
    caras = {'FRENTE': frente}
    if reverso:
        caras['REVERSO'] = reverso
    return extraer_campos_licencia(caras, **opciones)


# ---------------------------------------------------------------- ambas caras


def test_dos_caras_se_extraen_como_un_documento_sin_confirmar_nada(tmp_path):
    raiz = _raiz(tmp_path)
    recibido = _recibir(raiz)
    catalogo = (raiz / 'catalogos_privados' / 'choferes.json').read_bytes()
    ocr = OCRFalso({FRENTE: LINEAS_FRENTE, REVERSO: LINEAS_REVERSO})
    resumen = _extraer(raiz, ocr)
    assert resumen['pendientes'] == 1 and not resumen['errores']
    assert resumen['extraidas'][0]['estado'] == 'COMPLETA' and ocr.cerrado
    doc, ficha = _documento(raiz, recibido['documento_id'])
    extraccion = doc['extraccion_automatica']
    campos = extraccion['campos']
    assert campos['nombre']['valor'] == 'ANA MARIA TEST SOTO' and campos['nombre']['caras'] == ['FRENTE']
    assert campos['rut']['valor'] == validar_rut_chileno(RUT).valor
    assert campos['clase']['valor'] == 'A4' and campos['clase']['caras'] == ['REVERSO']
    assert campos['vencimiento']['valor'] == '2029-03-15'  # el próximo control, nunca el último
    assert all(c['estado'] == 'EXTRAIDO' and not c['motivo'] for c in campos.values())
    assert [a['cara'] for a in extraccion['archivos']] == ['FRENTE', 'REVERSO']
    # Nada confirmado: sigue pendiente, sin clase/vencimiento del documento.
    assert extraccion['confirmado_por_humano'] is False
    assert doc['estado_revision'] == 'PENDIENTE_EXTRACCION' and 'clase' not in doc and 'vencimiento' not in doc
    # Originales y catálogo intactos; auditoría y respaldo.
    carpeta = ruta_almacen(raiz, 'MBT').parent
    assert [(carpeta / c['archivo']).read_bytes() for c in doc['caras']] == [FRENTE, REVERSO]
    assert (raiz / 'catalogos_privados' / 'choferes.json').read_bytes() == catalogo
    assert ficha['historial'][-1]['accion'] == 'LICENCIA_EXTRACCION_AUTOMATICA'
    respaldos = list((raiz / 'respaldos' / 'fichas_choferes').glob('*/manifest.json'))
    assert any(json.loads(p.read_text(encoding='utf-8'))['operacion'] == 'LICENCIA_EXTRACCION_AUTOMATICA'
               for p in respaldos)


def test_cada_documento_se_extrae_una_sola_vez(tmp_path):
    raiz = _raiz(tmp_path)
    _recibir(raiz)
    _extraer(raiz, OCRFalso({FRENTE: LINEAS_FRENTE, REVERSO: LINEAS_REVERSO}))
    revision = leer_almacen(raiz, empresa='MBT')['revision']
    llamadas = []
    resumen = extraer_licencias_pendientes(raiz, comprobar=lambda: None, fabrica_ocr=lambda: llamadas.append(1))
    assert resumen == {'pendientes': 0, 'extraidas': [], 'errores': []} and not llamadas  # sin cargar OCR
    assert leer_almacen(raiz, empresa='MBT')['revision'] == revision


# ---------------------------------------------------------------- ilegibles


def test_campos_ilegibles_quedan_pendientes_sin_inventarse():
    campos = _campos(['APELLIDOS', 'TEST SOTO', 'NOMBRES', 'AN4 M@RIA', 'RUN 12.345.678-9'],
                     ['CLASE', 'FECHA DE CONTROL 31/02/2029'])
    assert campos['rut'] == {'valor': None, 'estado': 'PENDIENTE_REVISION', 'motivo': 'ILEGIBLE',
                             'caras': [], 'observados': ['12.345.678-9']}  # dígito verificador incorrecto
    assert (campos['vencimiento']['motivo'], campos['vencimiento']['valor']) == ('ILEGIBLE', None)
    assert (campos['clase']['motivo'], campos['nombre']['motivo']) == ('NO_ENCONTRADO', 'ILEGIBLE')


def test_rotulo_unico_de_apellidos_y_nombres_no_se_separa():
    campos = _campos(['APELLIDOS Y NOMBRES', 'TEST SOTO ANA MARIA', f'RUN {RUT}'])
    assert campos['nombre']['estado'] == 'PENDIENTE_REVISION' and campos['rut']['estado'] == 'EXTRAIDO'


def test_fecha_sin_rotulo_de_vencimiento_no_se_toma_como_vencimiento():
    campos = _campos(['FECHA DE NACIMIENTO 01/02/1980', 'FECHA ULTIMO CONTROL 15/03/2023'])
    assert campos['vencimiento']['motivo'] == 'NO_ENCONTRADO'


def test_sin_texto_legible_todo_queda_pendiente(tmp_path):
    raiz = _raiz(tmp_path)
    recibido = _recibir(raiz)
    resumen = _extraer(raiz, OCRFalso({FRENTE: [], REVERSO: ['@@@']}))
    assert resumen['extraidas'][0]['estado'] == 'SIN_DATOS'
    assert resumen['extraidas'][0]['pendientes'] == dict.fromkeys(('nombre', 'rut', 'clase', 'vencimiento'),
                                                                  'NO_ENCONTRADO')
    doc, _ = _documento(raiz, recibido['documento_id'])
    assert doc['estado_revision'] == 'PENDIENTE_EXTRACCION'


# ---------------------------------------------------------------- contradicciones


def test_caras_que_se_contradicen_dejan_el_dato_pendiente():
    campos = _campos(LINEAS_FRENTE + ['CLASE A2'], [f'RUN {OTRO_RUT}', 'CLASE A4', 'FECHA DE CONTROL 15/03/2030'])
    assert campos['rut']['motivo'] == 'CONTRADICCION' and campos['rut']['valor'] is None
    assert campos['rut']['observados'] == sorted({validar_rut_chileno(RUT).valor, validar_rut_chileno(OTRO_RUT).valor})
    assert campos['clase']['motivo'] == 'VARIAS_CLASES' and campos['clase']['observados'] == ['A2', 'A4']
    assert campos['nombre']['estado'] == 'EXTRAIDO'


def test_vencimientos_distintos_entre_caras_son_contradiccion():
    campos = _campos(['FECHA DE CONTROL 15/03/2029'], ['VENCIMIENTO 15/03/2030'])
    assert campos['vencimiento']['motivo'] == 'CONTRADICCION'
    assert campos['vencimiento']['observados'] == ['2029-03-15', '2030-03-15']


def test_rut_distinto_del_catalogo_no_toca_la_identidad_confirmada(tmp_path):
    raiz = _raiz(tmp_path)
    recibido = _recibir(raiz)
    catalogo = (raiz / 'catalogos_privados' / 'choferes.json').read_bytes()
    frente = [l if not l.startswith('RUN') else f'RUN {OTRO_RUT}' for l in LINEAS_FRENTE]
    _extraer(raiz, OCRFalso({FRENTE: frente, REVERSO: LINEAS_REVERSO}))
    doc, ficha = _documento(raiz, recibido['documento_id'])
    rut = doc['extraccion_automatica']['campos']['rut']
    assert (rut['valor'], rut['motivo']) == (None, 'CONTRADICE_CATALOGO')
    assert rut['observados'] == [validar_rut_chileno(OTRO_RUT).valor]
    assert (raiz / 'catalogos_privados' / 'choferes.json').read_bytes() == catalogo
    assert ficha['referencias_catalogo'] == ['123456785']


# ---------------------------------------------------------------- licencia antigua de una cara


def test_licencia_antigua_de_una_imagen_se_extrae_como_cara_unica(tmp_path):
    raiz = _raiz(tmp_path)
    recibido = _recibir(raiz, dos_caras=False)
    ocr = OCRFalso({UNICA: LINEAS_FRENTE + LINEAS_REVERSO})
    _extraer(raiz, ocr)
    doc, _ = _documento(raiz, recibido['documento_id'])
    extraccion = doc['extraccion_automatica']
    assert ocr.leidas == [UNICA] and [a['cara'] for a in extraccion['archivos']] == ['UNICA']
    assert extraccion['estado'] == 'COMPLETA' and extraccion['campos']['rut']['caras'] == ['UNICA']
    assert 'formato' not in doc and 'caras' not in doc  # sigue siendo de una imagen


def test_licencia_antigua_en_pdf_queda_pendiente_sin_ocr(tmp_path):
    raiz = _raiz(tmp_path)
    pdf = b'%PDF-1.4 licencia antigua'
    recibido = _recibir(raiz, dos_caras=False, contenido=pdf, mime='application/pdf')
    llamadas = []
    resumen = extraer_licencias_pendientes(raiz, comprobar=lambda: None, fabrica_ocr=lambda: llamadas.append(1))
    assert not llamadas and resumen['extraidas'][0]['estado'] == 'SIN_DATOS'
    doc, _ = _documento(raiz, recibido['documento_id'])
    assert {c['motivo'] for c in doc['extraccion_automatica']['campos'].values()} == {'FORMATO_SIN_OCR'}


# ---------------------------------------------------------------- resguardos


def test_original_alterado_o_ocr_fallido_no_escribe_y_se_reintenta(tmp_path):
    raiz = _raiz(tmp_path)
    recibido = _recibir(raiz)
    _, ficha = _documento(raiz, recibido['documento_id'])
    antes = ruta_almacen(raiz, 'MBT').read_bytes()
    resumen = _extraer(raiz, OCRFalso({FRENTE: LINEAS_FRENTE, REVERSO: RuntimeError('OCR caído')}))
    assert resumen['errores'][0]['error'] == 'OCR caído' and ruta_almacen(raiz, 'MBT').read_bytes() == antes
    reverso = ruta_almacen(raiz, 'MBT').parent / f"archivos/choferes/{ficha['ficha_id']}/{recibido['documento_id']}-reverso.png"
    reverso.write_bytes(REVERSO + b'alterado')
    resumen = _extraer(raiz, OCRFalso({FRENTE: LINEAS_FRENTE}))
    assert 'huella' in resumen['errores'][0]['error'] and ruta_almacen(raiz, 'MBT').read_bytes() == antes


def test_lease_perdido_no_publica(tmp_path):
    raiz = _raiz(tmp_path)
    _recibir(raiz)
    antes = ruta_almacen(raiz, 'MBT').read_bytes()

    def perdido():
        raise PermissionError('Lease PULL perdido')

    with pytest.raises(PermissionError):
        _extraer(raiz, OCRFalso({FRENTE: LINEAS_FRENTE, REVERSO: LINEAS_REVERSO}), comprobar=perdido)
    assert ruta_almacen(raiz, 'MBT').read_bytes() == antes


def test_licencia_registrada_por_una_persona_no_se_procesa(tmp_path):
    raiz = _raiz(tmp_path)
    datos = leer_almacen(raiz, empresa='MBT')
    fichas_por_referencia(datos)['123456785']['documentos'].append({
        'documento_id': 'humana-1', 'tipo': 'LICENCIA_CONDUCIR', 'clase': 'A4', 'vencimiento': '2030-01-01',
        'archivo': 'archivos/choferes/x/humana-1.jpg', 'sha256': sha(UNICA)})
    ruta_almacen(raiz, 'MBT').write_text(json.dumps(datos), encoding='utf-8')
    llamadas = []
    resumen = extraer_licencias_pendientes(raiz, comprobar=lambda: None, fabrica_ocr=lambda: llamadas.append(1))
    assert resumen['pendientes'] == 0 and not llamadas
    assert 'extraccion_automatica' not in fichas_por_referencia(leer_almacen(raiz, empresa='MBT'))['123456785']['documentos'][0]


# ---------------------------------------------------------------- licencia real sin rótulos legibles
# Distribución del OCR real (frente antiguo fotografiado de lado): se leen los
# valores pero casi ningún rótulo, y los que se leen pierden espacios. Datos
# personales ficticios.

LINEAS_SIN_ROTULOS = ['LICENCIA DE CONDUCTOR', 'REPUBLICADECHHLE', 'SOTO PEREZ', 'JUAN ANDRE', 'MAIPU', RUT, 'CD',
                      'A4 Ley19495', 'FECHAULTIMO CONTROL', '19/06/2023', '07/05/2028']


def test_clase_profesional_junto_a_su_ley_se_extrae_sin_rotulo_clase():
    campos = _campos(LINEAS_SIN_ROTULOS)
    assert (campos['clase']['estado'], campos['clase']['valor']) == ('EXTRAIDO', 'A4')
    assert campos['rut']['estado'] == 'EXTRAIDO'


def test_sin_rotulos_nombre_y_vencimiento_no_se_deducen_por_posicion():
    campos = _campos(LINEAS_SIN_ROTULOS)
    # Sin APELLIDOS/NOMBRES no se sabe qué línea es cuál; la fecha sin rótulo
    # de próximo control no se toma por estar después del último control.
    assert (campos['nombre']['motivo'], campos['vencimiento']['motivo']) == ('NO_ENCONTRADO', 'NO_ENCONTRADO')
    assert campos['nombre']['valor'] is None and campos['vencimiento']['valor'] is None


def test_rotulos_con_espacios_perdidos_por_el_ocr():
    campos = _campos(['FECHAULTIMO CONTROL 19/06/2023', 'FECHACONTROL', '07/05/2028'])
    assert (campos['vencimiento']['estado'], campos['vencimiento']['valor']) == ('EXTRAIDO', '2028-05-07')


def test_ley_19495_solo_respalda_clases_profesionales():
    assert _campos(['B Ley19495'])['clase']['motivo'] == 'NO_ENCONTRADO'
    assert _campos(['XA4 LEY 19495'])['clase']['motivo'] == 'NO_ENCONTRADO'
    campos = _campos(['A4 Ley 19.495', 'CLASE A2'])
    assert campos['clase']['motivo'] == 'VARIAS_CLASES' and campos['clase']['observados'] == ['A2', 'A4']


# ---------------------------------------------------------------- re-extracción controlada


def test_extraccion_incompleta_de_version_anterior_se_reextrae_una_vez(tmp_path, monkeypatch):
    from atlas_core import extraccion_licencias as modulo
    raiz = _raiz(tmp_path)
    recibido = _recibir(raiz, dos_caras=False)
    monkeypatch.setattr(modulo, 'VERSION_EXTRACCION', 1)
    _extraer(raiz, OCRFalso({UNICA: ['RUN ' + RUT]}))  # extractor anterior: sólo el RUT
    previa, _ = _documento(raiz, recibido['documento_id'])
    assert previa['extraccion_automatica']['estado'] == 'PARCIAL'
    monkeypatch.setattr(modulo, 'VERSION_EXTRACCION', 2)
    ocr = OCRFalso({UNICA: LINEAS_SIN_ROTULOS})
    resumen = _extraer(raiz, ocr)
    assert resumen['pendientes'] == 1 and ocr.leidas == [UNICA]
    doc, ficha = _documento(raiz, recibido['documento_id'])
    assert doc['extraccion_automatica']['version'] == 2
    assert doc['extraccion_automatica']['campos']['clase']['valor'] == 'A4'
    assert doc['extracciones_anteriores'] == [previa['extraccion_automatica']]  # se conserva intacta
    assert ficha['historial'][-1]['version_anterior'] == 1 and ficha['historial'][-1]['estado_anterior'] == 'PARCIAL'
    assert doc['estado_revision'] == 'PENDIENTE_EXTRACCION' and 'clase' not in doc
    assert doc['extraccion_automatica']['confirmado_por_humano'] is False
    # Misma versión: nunca otra vez.
    llamadas = []
    assert extraer_licencias_pendientes(raiz, comprobar=lambda: None,
                                        fabrica_ocr=lambda: llamadas.append(1))['pendientes'] == 0
    assert not llamadas


def test_extraccion_completa_no_se_reextrae_al_subir_version(tmp_path, monkeypatch):
    from atlas_core import extraccion_licencias as modulo
    raiz = _raiz(tmp_path)
    _recibir(raiz)
    monkeypatch.setattr(modulo, 'VERSION_EXTRACCION', 1)
    _extraer(raiz, OCRFalso({FRENTE: LINEAS_FRENTE, REVERSO: LINEAS_REVERSO}))
    monkeypatch.setattr(modulo, 'VERSION_EXTRACCION', 2)
    llamadas = []
    assert extraer_licencias_pendientes(raiz, comprobar=lambda: None,
                                        fabrica_ocr=lambda: llamadas.append(1))['pendientes'] == 0
    assert not llamadas
