from __future__ import annotations

import csv
import json

import pytest

from atlas_core.credibilidad_campos import evaluar_credibilidad_material, valor_publicable
from atlas_core.reporte_viajes import generar_reporte_viajes
from tests.test_reporte_viajes import _escribir_csv, _fila, _leer_csv, RELOJ
from tests.test_material_confirmado_publicacion import guia, espia_reporte, _preview, _ejecutar, LARGO  # noqa: F401
from tests.test_b1_material_faltante import sin_material  # noqa: F401
from tests.test_acciones_operacionales import entorno  # noqa: F401

MATERIAL = 'BARRAS DE ACERO 12 MM LARGO 6 METROS, ROLLOS DE ACERO 8 MM CALIDAD A630, MALLAS DE ACERO 15 X 15'


def asiento(fila, valor, **cambios):
    entrada = {'tipo': 'CORRECCION_DOCUMENTAL_OPERADOR', 'accion': 'CORREGIR_CAMPO',
               'campo': 'descripcion_material', 'actor': 'B1', 'confirmado_por': 'JAVIER',
               'documento': {'archivo': fila['archivo'], 'numero_guia': fila['numero_guia']},
               'valor_corregido': valor, 'decision_id': 'ACCION_OPERACIONAL:sintetico'}
    entrada.update(cambios)
    return entrada


def reporte(tmp_path, fila, aplicaciones, *, ledger_externo=False):
    tmp_path.mkdir(parents=True, exist_ok=True)
    origen = tmp_path / 'entrada.csv'
    salida = tmp_path / 'reporte'
    _escribir_csv(origen, [fila])
    ledger = tmp_path / ('externo.json' if ledger_externo else 'decisiones_aplicadas.json')
    ledger.write_text(json.dumps({'aplicaciones': aplicaciones}), encoding='utf-8')
    original = tmp_path / 'original.jpg'
    original.write_bytes(b'original sintetico')
    ocr = tmp_path / 'ocr.json'
    ocr.write_text('{"lineas": ["OCR sintetico"]}', encoding='utf-8')
    auditoria = tmp_path / 'acciones_operacionales.json'
    auditoria.write_text('{"auditoria": []}', encoding='utf-8')
    protegidos = {p: p.read_bytes() for p in (origen, ledger, original, ocr, auditoria)}
    generar_reporte_viajes(origen, salida, carpeta_catalogos=tmp_path / 'catalogos',
                          ruta_ledger=ledger, reloj=RELOJ)
    assert all(p.read_bytes() == contenido for p, contenido in protegidos.items())
    viaje = _leer_csv(salida / 'viajes.csv')[0]
    documento = json.loads(viaje['documentos_operacionales'])[0]
    evidencia = json.loads(viaje['evidencias_documentos'])[0]
    assert evidencia == fila
    assert documento['cliente'] == fila['cliente']
    assert documento['obra_destino'] == fila['obra_destino']
    assert documento['peso_kg'] == fila['peso_kg']
    assert viaje['tipos_carga'] == fila['tipo_carga']
    return viaje, documento


@pytest.mark.parametrize('valor', [MATERIAL, LARGO, 'ACERO TOTAL VALOR NETO PESO 12 MM'])
def test_confirmado_publica_valor_integro(tmp_path, valor):
    fila = _fila(descripcion_material=valor)
    viaje, documento = reporte(tmp_path, fila, [asiento(fila, valor)], ledger_externo=True)
    assert viaje['materiales'] == documento['descripcion_material'] == valor


@pytest.mark.parametrize('caso', ['ocr', 'propuesta', 'rechazo', 'fallo', 'otro_documento', 'valor_distinto', 'no_humano'])
def test_sin_confirmacion_vigente_aplica_heuristica_original(tmp_path, caso):
    fila = _fila(descripcion_material=MATERIAL)
    entrada = asiento(fila, MATERIAL)
    aplicaciones = []
    if caso == 'otro_documento':
        aplicaciones = [asiento(fila, MATERIAL, documento={'archivo': 'otro.jpg', 'numero_guia': fila['numero_guia']})]
    elif caso == 'valor_distinto':
        aplicaciones = [asiento(fila, 'OTRO MATERIAL')]
    elif caso == 'no_humano':
        aplicaciones = [asiento(fila, MATERIAL, confirmado_por='ATLAS_AUTOMATICO')]
    elif caso in ('propuesta', 'rechazo', 'fallo'):
        # El canal oficial no asienta en el ledger propuestas, rechazos ni fallos.
        aplicaciones = []
    viaje, documento = reporte(tmp_path, fila, aplicaciones)
    esperado = valor_publicable(MATERIAL, evaluar_credibilidad_material)
    assert esperado == 'NO DETERMINADO'
    assert viaje['materiales'] == documento['descripcion_material'] == esperado


def test_ultima_correccion_reemplaza_anterior(tmp_path):
    fila = _fila(descripcion_material=MATERIAL)
    viaje, documento = reporte(tmp_path, fila, [asiento(fila, LARGO), asiento(fila, MATERIAL)])
    assert viaje['materiales'] == documento['descripcion_material'] == MATERIAL


def test_reporte_real_en_el_canal_antes_de_auditoria(guia, monkeypatch):
    import atlas_core.reporte_viajes as modulo
    original = modulo.generar_reporte_viajes
    capturas = []
    def generar(dataset, salida, *args, **kwargs):
        registro = dataset.parent / 'acciones_operacionales.json'
        antes = json.loads(registro.read_text(encoding='utf-8')) if registro.exists() else {}
        resultado = original(dataset, salida, *args, **kwargs)
        viajes = _leer_csv(salida / 'viajes.csv')
        despues = json.loads(registro.read_text(encoding='utf-8')) if registro.exists() else {}
        assert antes == despues
        capturas.append((antes, viajes))
        return resultado
    monkeypatch.setattr(modulo, 'generar_reporte_viajes', generar)
    token = _preview(guia['b1'].capa, LARGO)
    resultado = _ejecutar(guia['b1'].capa, token)
    assert resultado['estado'] == 'APLICADA'
    assert resultado['revalidacion']['reporte']['regenerado']
    [(antes, viajes)] = capturas
    assert not any(a.get('token') == token and a.get('resultado') == 'APLICADA' for a in antes.get('auditoria', []))
    documentos = [d for v in viajes for d in json.loads(v['documentos_operacionales'])]
    assert next(d for d in documentos if d['archivo'] == '500001.jpeg')['descripcion_material'] == LARGO


def test_solo_cambia_material_en_reporte(tmp_path):
    fila = _fila(descripcion_material=MATERIAL)
    sin, doc_sin = reporte(tmp_path / 'sin', fila, [])
    con, doc_con = reporte(tmp_path / 'con', fila, [asiento(fila, MATERIAL)])
    assert {k: v for k, v in sin.items() if k not in {'materiales', 'documentos_operacionales'}} == {
        k: v for k, v in con.items() if k not in {'materiales', 'documentos_operacionales'}}
    assert {k: v for k, v in doc_sin.items() if k != 'descripcion_material'} == {
        k: v for k, v in doc_con.items() if k != 'descripcion_material'}
