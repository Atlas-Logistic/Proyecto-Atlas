import json
import pytest
from atlas_core.b1_operador import OperadorB1, interpretar_determinista
from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from tests.test_acciones_operacionales import entorno, _EscritorDisponible
from tests.test_errores_documentales_aza import varas, _filas, _escribir

FRASE = 'Corrige el error documental de la guía 482816: la patente de la rampla es JB8529'

@pytest.fixture
def caso(varas):
    filas = list(_filas(varas).values())
    next(f for f in filas if f['numero_guia'] == '482816')['rut_chofer'] = '14293816-2'
    _escribir(varas, filas)
    varas['b1'] = OperadorB1(varas['raiz'], capa=CapaAccionesOperacionales(
        varas['raiz'], fabrica_escritor=lambda: _EscritorDisponible()))
    return varas

def test_b1_preview_confirmacion_y_conservacion(caso, tmp_path):
    b = caso['b1']; antes = _filas(caso)
    vehiculos = (caso['cat'] / 'vehiculos.json').read_bytes()
    original = caso['raiz'] / 'original-sintetico.jpg'
    ocr = caso['raiz'] / 'ocr-sintetico.json'
    original.write_bytes(b'original sintetico'); ocr.write_bytes(b'ocr sintetico')
    p = b.atender('c', FRASE)
    assert p['estado'] == 'PREVIEW_PENDIENTE', p
    assert all(x in p['mensaje'] for x in ('JC4173', 'JB8529', '482816'))
    assert _filas(caso) == antes
    r = b.atender('c', 'sí')
    assert r['estado'] == 'EJECUTADA', r
    assert r['resultado']['respaldo']
    assert any(a['resultado'] == 'APLICADA' and a['confirmado_por'] == 'JAVIER' for a in b.capa.auditoria())
    despues = _filas(caso)
    for g in antes:
        for c in ('archivo', 'numero_guia', 'patente_tracto', 'patente_rampla', 'rut_chofer'):
            assert despues[g][c] == antes[g][c]
    assert (caso['cat'] / 'vehiculos.json').read_bytes() == vehiculos
    assert original.read_bytes() == b'original sintetico' and ocr.read_bytes() == b'ocr sintetico'
    from atlas_core.equipo_operacional import ResolutorEquipoOperacional
    resolutor = ResolutorEquipoOperacional(carpeta_catalogos=caso['cat'], ruta_ledger=caso['actual'] / 'decisiones_aplicadas.json')
    assert resolutor.discrepancias(despues['482816'])['patente_rampla']['fuente'] == 'CONFIRMACION_ADMINISTRADOR'
    assert resolutor.patente_operacional(despues['482816'], 'patente_rampla') == 'JB8529'
    import csv
    from atlas_core.reporte_viajes import generar_reporte_viajes
    generar_reporte_viajes(caso['dataset'], tmp_path / 'reporte', carpeta_catalogos=caso['cat'])
    with (tmp_path / 'reporte' / 'viajes.csv').open(encoding='utf-8-sig', newline='') as f:
        viajes = list(csv.DictReader(f, delimiter=';'))
    viaje = next(v for v in viajes if v['numero_transporte'] == '0000365294')
    assert 'JB8529' in viaje['patentes_rampla']
    evidencia = {e['numero_guia']: e for e in json.loads(viaje['evidencias_documentos'])}
    assert evidencia['482816']['patente_rampla'] == 'JC4173'

@pytest.mark.parametrize('frase', [
    'La patente de la rampla de la guía 482816 es JB8529',
    'Corrige el error documental de la guía 482816: la patente de la rampla es XX1234',
    'Corrige el error documental de la guía 482816: la patente del tracto es JB8529',
    'Corrige el error documental de la guía 482816: la patente de la rampla es JB8529 y cambia la asignación',
])
def test_ambigua_o_incompatible_no_prepara(caso, frase):
    b = caso['b1']; r = b.atender('c', frase)
    assert r['estado'] != 'PREVIEW_PENDIENTE', r
    assert b.pendiente('c') is None

def test_conflicto_tras_preview(caso):
    b=caso['b1']; assert b.atender('c', FRASE)['estado'] == 'PREVIEW_PENDIENTE'
    ruta=caso['cat'] / 'vehiculos.json'; cat=json.loads(ruta.read_text(encoding='utf-8'))
    cat['vehiculos']=[v for v in cat['vehiculos'] if v['patente_canonica'] != 'JB8529']
    ruta.write_text(json.dumps(cat), encoding='utf-8')
    assert b.atender('c', 'sí')['estado'] != 'EJECUTADA'

def test_confirmante_automatico_rechazado(caso):
    b=OperadorB1(caso['raiz'], usuario='ATLAS_AUTOMATICO', capa=caso['b1'].capa)
    assert b.atender('auto', FRASE)['estado'] == 'PREVIEW_PENDIENTE'
    assert b.atender('auto', 'sí')['estado'] != 'EJECUTADA'

def test_discrepancia_adicional_no_se_confirma(varas):
    from tests.test_intenciones_equipo_operacional import chofer
    chofer(varas)
    b=OperadorB1(varas['raiz'], capa=CapaAccionesOperacionales(varas['raiz'], fabrica_escritor=lambda: _EscritorDisponible()))
    assert b.atender('c', FRASE)['estado'] == 'RECHAZADA'
    assert b.pendiente('c') is None


@pytest.mark.parametrize("texto", [
    "Corrige el error OCR de la guía 482816: la patente de la rampla es JB8529",
    "Corrige el error de OCR de la guía 482816: la patente de la rampla es JB8529",
])
def test_error_ocr_explicito(texto):
    i = interpretar_determinista(texto)
    assert i and i.accion == "DOCUMENTO_CONFIRMAR_ERROR_DOCUMENTAL_AZA"
    assert i.campo_error_equipo == "patente_rampla" and i.patente_error_equipo == "JB8529"
