import csv
import json
from types import SimpleNamespace as NS

import pytest

from atlas_core import convergencia_destino_confirmado as modulo
from atlas_core.procesamiento_masivo import COLUMNAS


@pytest.fixture
def catalogo(monkeypatch):
    cliente = NS(cliente_id='cliente', razon_social='ACEROS COX COMERCIAL SA', rut='77004250-K',
                 aliases=(), estado_calidad='CONFIRMADO', estado_vigencia='ACTIVO')
    obra = NS(obra_id='obra', cliente_id='cliente', nombre_canonico=cliente.razon_social,
              aliases_documentales=(), estado='CONFIRMADA', estado_vigencia='ACTIVO')
    destino = NS(destino_id='destino', direccion='CAMINO LO RUIZ 2901', comuna='RENCA', region='RM')
    estado = NS(cliente=cliente, obras=[obra], destinos=[destino])
    monkeypatch.setattr(modulo, 'CatalogoClientes', lambda *a, **k: NS(listar=lambda: [cliente]))
    monkeypatch.setattr(modulo, 'CatalogoObrasDestinos', lambda *a, **k: NS(
        listar_obras=lambda: estado.obras, listar_destinos_confirmados_para_obra=lambda **k: estado.destinos))
    return estado


def fila(**cambios):
    f = dict.fromkeys(COLUMNAS, '')
    f.update(archivo='prueba.jpg', numero_guia='800001', numero_transporte='900001',
             cliente='ACEROS COX COMERCIAL SA', rut_cliente='77.004.250-K',
             obra_destino='ACEROS COX COMERCIAL SA', despachar_a_crudo='CAMINO LO RUIZ 290I SANTIAGO RENCA',
             estado_ruta='REQUIERE_REVISION', motivo_ruta='DESTINO_CONTRADICE_CATALOGO_CONFIRMADO',
             motivos_revision_documento='MATERIAL_AUSENTE | CHOFER_SIN_CORROBORAR',
             metricas_procesamiento_json='{}', patente_tracto='ABCD12', rut_chofer='12345678-5')
    f.update(cambios)
    return f


def resolver(f, **kwargs):
    return modulo.resolver_destino_confirmado(f, carpeta_catalogos='catalogos', **kwargs)


def test_290i_converge_con_numero_confirmado(catalogo):
    assert resolver(fila())[1].destino_id == 'destino'


def test_rut_no_es_direccion_pero_traza_propia_corrobora(catalogo):
    f = fila(obra_destino='No encontrado', despachar_a_crudo='7814310-K')
    assert resolver(f) is None
    assert resolver(f, lineas=['ACEROS COX COMERCIAL SA', 'CAMINO LO RUIZ 2901'])[1].comuna == 'RENCA'


def test_espacio_ocr_en_obra_con_destino_confirmado(catalogo):
    catalogo.cliente.razon_social = catalogo.obras[0].nombre_canonico = 'COMERCIAL A Y B LTDA'
    catalogo.destinos[0].direccion = 'LA ESTERA 525'
    catalogo.destinos[0].comuna = 'LAMPA'
    catalogo.obras[0].evidencias = [NS(resultado='SOPORTA', campos_observados={
        'comuna_documental': 'SANTIAGO', 'comuna_operacional_confirmada': 'LAMPA'})]
    f = fila(cliente='COMERCIAL A Y B LTDA', obra_destino='COMERCIAL A YB LTDA',
             despachar_a_crudo='LA ESTERA 525 SANTIAGO')
    assert resolver(f)[1].comuna == 'LAMPA'
    assert resolver({**f, 'despachar_a_crudo': ''}) is None
    catalogo.obras[0].evidencias = []
    assert resolver(f) is None


def test_degradacion_requiere_codigos_obra_rut_y_testigo(catalogo):
    catalogo.cliente.razon_social = catalogo.obras[0].nombre_canonico = 'AMERICAN SCREW CHILE SPA'
    catalogo.destinos[0].direccion = 'CAMINO A MELIPILLA 10800 SANTIAGO MAIPU'
    catalogo.destinos[0].comuna = 'MAIPU'
    f = fila(cliente='AMERICAN SCREW CHILE SPA', obra_destino='No encontrado',
             despachar_a_crudo='CAETNO ALILLA1080OSTIGO PO')
    testigo = {**f, 'obra_destino': 'AMERICAN SCREW CHILE SPA',
               'despachar_a_crudo': catalogo.destinos[0].direccion,
               'codigo_cliente': '0001000197', 'cod_destinatario': '0002001587'}
    ls = ['AMERICAN SCAE# CHILE SPA', '0001000197', '0002001587']
    assert resolver(f, lineas=ls, filas=[testigo]) is not None
    assert resolver(f, lineas=ls) is None
    assert resolver(f, lineas=ls[:-1], filas=[testigo]) is None
    assert resolver(f, lineas=ls[1:], filas=[testigo]) is None
    assert resolver(f, lineas=ls, filas=[{**testigo, 'rut_cliente': 'otro'}]) is None


@pytest.mark.parametrize('direccion', ['CAMINO LO RUIZ 2902 RENCA', 'OTRA CALLE 2901 RENCA',
                                       'CAMINO LO RUIZ 29010 RENCA', 'CAMINO LO RUIZ 2901 TEMUCO',
                                       'CAMINO LO RUIZ 290I TEMUCO'])
def test_direccion_legitima_distinta_no_se_pisa(catalogo, direccion):
    assert resolver(fila(despachar_a_crudo=direccion), lineas=['CAMINO LO RUIZ 2901']) is None


@pytest.mark.parametrize('campo,valor', [('rut_cliente', ''), ('rut_cliente', '12345678-5'),
                                       ('cliente', 'OTRO CLIENTE'), ('obra_destino', 'OTRA OBRA')])
def test_no_cierra_por_coincidencia_nominal(catalogo, campo, valor):
    assert resolver(fila(**{campo: valor})) is None


def test_ambiguedad_y_catalogo_inactivo_se_abstienen(catalogo):
    # Ambigüedad real: mismo texto, coordenadas a >1 km (26/10/2026: un
    # duplicado idéntico de la misma dirección ya no es ambigüedad).
    catalogo.destinos[0].latitud, catalogo.destinos[0].longitud = -33.4025, -70.6865
    catalogo.destinos.append(NS(**{**vars(catalogo.destinos[0]), 'destino_id': 'otro', 'latitud': -33.4125}))
    assert resolver(fila()) is None
    catalogo.destinos.pop()
    catalogo.obras[0].estado_vigencia = 'INACTIVO'
    assert resolver(fila()) is None


def entorno(tmp_path, fs):
    actual = tmp_path / 'operacion' / 'actual'
    actual.mkdir(parents=True)
    p = actual / 'analisis_completo_guias.csv'
    with p.open('w', encoding='utf-8-sig', newline='') as archivo:
        w = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=';'); w.writeheader(); w.writerows(fs)
    return p


def test_revalidacion_focal_preserva_otros_dominios_e_idempotencia(catalogo, tmp_path):
    originales = [fila(), fila(numero_guia='800002')]
    p = entorno(tmp_path, originales)
    kwargs = dict(ruta_dataset=p, carpeta_catalogos=tmp_path / 'catalogos_privados', guias_objetivo={'800001'})
    assert modulo.revalidar_destinos_confirmados_convergentes(**kwargs)['guias_actualizadas'] == ['800001']
    despues = list(csv.DictReader(p.open(encoding='utf-8-sig'), delimiter=';'))
    assert despues[1] == originales[1]
    for k in ('patente_tracto', 'rut_chofer', 'motivos_revision_documento'):
        assert despues[0][k] == originales[0][k]
    evidencia = json.loads(despues[0]['metricas_procesamiento_json'])['convergencia_destino_confirmado']
    assert evidencia['direccion_documental_original'] == originales[0]['despachar_a_crudo']
    datos = p.read_bytes()
    assert modulo.revalidar_destinos_confirmados_convergentes(**kwargs)['guias_actualizadas'] == []
    assert p.read_bytes() == datos


def test_decision_humana_bloquea_revalidacion(catalogo, tmp_path):
    f = fila(); p = entorno(tmp_path, [f])
    (p.parent / 'decisiones_aplicadas.json').write_text(json.dumps({'aplicaciones': [
        {'documento': {'numero_guia': f['numero_guia']}, 'campo': 'despachar_a_crudo'}]}))
    antes = p.read_bytes()
    assert modulo.revalidar_destinos_confirmados_convergentes(
        ruta_dataset=p, carpeta_catalogos=tmp_path / 'catalogos_privados')['guias_actualizadas'] == []
    assert p.read_bytes() == antes


def test_evidencia_rechazada_por_b1_no_se_promueve(catalogo, tmp_path):
    f = fila(resultado_atlas_ia_json=json.dumps([{
        'dominio': 'DESTINO', 'campo': 'despachar_a_crudo', 'estado': 'BLOQUEADO_POR_VALIDACION',
        'validacion': {'aceptada': False}, 'hipotesis': {'valor_propuesto': 'CAMINO LO RUIZ 2901'},
    }]))
    p = entorno(tmp_path, [f]); antes = p.read_bytes()
    assert modulo.revalidar_destinos_confirmados_convergentes(
        ruta_dataset=p, carpeta_catalogos=tmp_path / 'catalogos_privados')['guias_actualizadas'] == []
    assert p.read_bytes() == antes


def test_traza_de_otro_archivo_no_es_evidencia(catalogo, tmp_path):
    from atlas_core.trazabilidad_ocr import ruta_traza_ocr
    f = fila(obra_destino='No encontrado', despachar_a_crudo='7814310-K')
    p = entorno(tmp_path, [f]); trazas = tmp_path / 'trazas'; trazas.mkdir()
    ruta_traza_ocr(trazas, f['archivo']).write_text(json.dumps({
        'imagen': {'referencia': 'otra.jpg'},
        'ocr': {'lineas': ['ACEROS COX COMERCIAL SA', 'CAMINO LO RUIZ 2901']},
    }))
    assert modulo.revalidar_destinos_confirmados_convergentes(
        ruta_dataset=p, carpeta_catalogos=tmp_path / 'catalogos_privados', directorio_trazas=trazas)['guias_actualizadas'] == []


def test_filtro_solo_destino_obra_y_con_catalogo_vigente(catalogo, tmp_path):
    p = entorno(tmp_path, [fila()])
    modulo.revalidar_destinos_confirmados_convergentes(ruta_dataset=p, carpeta_catalogos=tmp_path / 'catalogos_privados')
    ds = [dict(tipo=t, documento={'numero_guia': '800001'}) for t in
          ('DESTINO_NO_RESUELTO', 'OBRA_DESCONOCIDA', 'VEHICULO_DESCONOCIDO', 'CHOFER_CANDIDATO')]
    manual = {**ds[0], 'evidencias': [{'origen_pregunta': 'CORRECCION_MANUAL_LOGISTICA'}]}
    kwargs = dict(ruta_dataset=p, carpeta_catalogos=tmp_path / 'catalogos_privados')
    assert modulo.retirar_decisiones_destino_convergente([*ds, manual], **kwargs) == [*ds[2:], manual]
    catalogo.obras[0].estado_vigencia = 'INACTIVO'
    assert modulo.retirar_decisiones_destino_convergente(ds, **kwargs) == ds


def test_duplicado_identico_de_la_misma_direccion_no_es_ambiguedad(catalogo):
    """CAMINO LO RUIZ 2901 confirmado dos veces (con y sin ", RENCA, CHILE")."""
    copia = NS(**{**vars(catalogo.destinos[0]), 'destino_id': 'otro', 'direccion': 'CAMINO LO RUIZ 2901, RENCA, CHILE'})
    catalogo.destinos.append(copia)
    assert resolver(fila()) is not None
