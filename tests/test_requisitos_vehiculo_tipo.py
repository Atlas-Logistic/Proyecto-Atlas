import json
from datetime import date

import pytest

from atlas_core.catalogo_vehiculos import TipoVehiculo
from atlas_core.expediente_digital import consultar_expediente, documentos_ausentes, vista_expediente_desktop
from tests.test_identificacion_patentes import raiz, TRACTO, CARRO, RIGIDO, SOLO
from tests.test_motor_evidencia_vehiculos import _confirmar

TODOS = {"SOAP", "POLIZA_RESPONSABILIDAD_CIVIL", "SEGURO_CARGA", "REVISION_TECNICA",
         "PERMISO_CIRCULACION", "CERTIFICADO_EMISION_GASES"}

@pytest.mark.parametrize(('patente','esperados'), [(TRACTO,TODOS), (RIGIDO,TODOS),
    (CARRO,TODOS-{'SOAP','CERTIFICADO_EMISION_GASES'})])
def test_aplicabilidad_en_expediente_y_lista_general(raiz, patente, esperados):
    vista = vista_expediente_desktop(raiz, empresa='MBT', entidad='VEHICULO', referencia=patente)
    assert set(vista['requisitos_aplicables']) == esperados
    assert {x['tipo'] for x in vista['ausentes']} == esperados
    assert 'POLIZA_ROBO' not in esperados
    general = documentos_ausentes(raiz, empresa='MBT')
    assert {x['tipo'] for x in general if x['referencia_catalogo'] == vista['referencia_catalogo']} == esperados


def test_tipo_no_confirmado_no_inventa_faltantes(raiz):
    ruta=raiz/'catalogos_privados'/'vehiculos.json'
    datos=json.loads(ruta.read_text(encoding='utf-8'))
    v=next(x for x in datos['vehiculos'] if x['patente_canonica']==CARRO)
    v.update(estado_calidad='CANDIDATO',confirmado_por='',fecha_confirmacion='')
    ruta.write_text(json.dumps(datos),encoding='utf-8')
    vista=consultar_expediente(raiz,empresa='MBT',entidad='VEHICULO',referencia=CARRO)
    assert vista['tipo_vehiculo_estado']=='INCIERTO'
    assert vista['tipo_vehiculo'] is None and vista['ausentes']==[] and vista['requisitos_aplicables']==[]
    assert not any(x['referencia_catalogo']==vista['referencia_catalogo'] for x in documentos_ausentes(raiz,empresa='MBT'))


def test_chofer_contiene_siete_y_rampla_no_exige_soap_ni_gases(raiz):
    vista=vista_expediente_desktop(raiz,empresa='MBT',entidad='CHOFER',referencia=SOLO)
    req={x['tipo']:x for x in vista['requisitos_documentales']}
    assert set(req)==TODOS|{'LICENCIA_CONDUCIR'}
    assert req['LICENCIA_CONDUCIR']['ambito']=='CHOFER'
    assert req['SEGURO_CARGA']['ambito']=='COBERTURA'
    assert req['SOAP']['vehiculos'][0]['tipo_vehiculo']=='TRACTO'
    # La segunda asignación es explícita y distinta del tracto.
    from atlas_core.catalogo_vehiculos import asociar_chofer_a_vehiculo_confirmado
    from datetime import datetime, timezone
    asociar_chofer_a_vehiculo_confirmado(raiz/'catalogos_privados'/'vehiculos.json',patente=CARRO,
        actor='TEST',fuente_decision='TEST',rut_chofer_asociado=SOLO,fecha=datetime.now(timezone.utc))
    vista=vista_expediente_desktop(raiz,empresa='MBT',entidad='CHOFER',referencia=SOLO)
    req={x['tipo']:x for x in vista['requisitos_documentales']}
    for t in ('SOAP','CERTIFICADO_EMISION_GASES'):
        assert {x['tipo_vehiculo']:x['estado'] for x in req[t]['vehiculos']}=={'TRACTO':'FALTANTE','CARRO':'NO_APLICA'}
    for t in ('REVISION_TECNICA','PERMISO_CIRCULACION','POLIZA_RESPONSABILIDAD_CIVIL','SEGURO_CARGA'):
        assert {x['tipo_vehiculo']:x['estado'] for x in req[t]['vehiculos']}=={'TRACTO':'FALTANTE','CARRO':'FALTANTE'}


def test_consulta_no_altera_fichas_ni_documentos(raiz):
    from tests.test_identificacion_patentes import _recibir
    from atlas_core.fichas_choferes import ruta_almacen
    doc, original = _recibir(raiz, 'preservar-original')
    fichas=ruta_almacen(raiz,'MBT')
    antes=fichas.read_bytes()
    archivo=next(d['archivo'] for v in json.loads(antes)['vehiculos'] for d in v['documentos'] if d['documento_id']==doc)
    ruta=fichas.parent/archivo
    consultar_expediente(raiz,empresa='MBT',entidad='VEHICULO',referencia=TRACTO)
    consultar_expediente(raiz,empresa='MBT',entidad='CHOFER',referencia=SOLO)
    assert fichas.read_bytes()==antes and ruta.read_bytes()==original


def test_sin_catalogo_vehiculos_licencia_no_falla(tmp_path):
    from tests.test_licencia_extraccion_automatica import _raiz, _ficha, REF
    raiz=_raiz(tmp_path)
    vista=consultar_expediente(raiz,empresa='MBT',entidad='CHOFER',referencia=REF)
    assert len(vista['requisitos_documentales'])==7
    assert all(r['estado']=='SIN_ASIGNACION' for r in vista['requisitos_documentales'] if r['tipo']!='LICENCIA_CONDUCIR')


def test_poliza_no_se_proyecta_a_otro_vehiculo(raiz):
    from datetime import datetime, timezone
    from atlas_core.catalogo_vehiculos import asociar_chofer_a_vehiculo_confirmado
    from atlas_core.expediente_digital import registrar_documento_vehiculo_desktop
    from tests.test_expediente_doble_cobertura import OCR
    asociar_chofer_a_vehiculo_confirmado(raiz/'catalogos_privados'/'vehiculos.json', patente=CARRO,
        actor='TEST', fuente_decision='TEST', rut_chofer_asociado=SOLO, fecha=datetime.now(timezone.utc))
    original=b'\xff\xd8\xff\xe0poliza sintetica'
    doc=registrar_documento_vehiculo_desktop(raiz,empresa='MBT',referencia=TRACTO,
        tipo='POLIZA_RESPONSABILIDAD_CIVIL',contenido=original,mime_type='image/jpeg',
        fabrica_ocr=lambda: OCR(TRACTO, 'COBERTURA: RESPONSABILIDAD CIVIL', '30/09/2030'))
    assert not doc['pendiente_revision']
    vista=consultar_expediente(raiz,empresa='MBT',entidad='CHOFER',referencia=SOLO)
    requisito=next(r for r in vista['requisitos_documentales'] if r['tipo']=='POLIZA_RESPONSABILIDAD_CIVIL')
    assert {v['patente']:v['estado'] for v in requisito['vehiculos']}=={TRACTO:'PRESENTE',CARRO:'FALTANTE'}
    assert (raiz/'fichas_digitales'/'MBT'/doc['archivo']).read_bytes()==original


def test_tipo_contradictorio_no_produce_faltantes(raiz):
    ruta=raiz/'catalogos_privados'/'vehiculos.json'
    datos=json.loads(ruta.read_text(encoding='utf-8'))
    vehiculo=next(v for v in datos['vehiculos'] if v['patente_canonica']==CARRO)
    evidencia=dict(vehiculo['evidencias'][0])
    evidencia['resultado']='CONTRADICE'
    evidencia['campos_observados']={**evidencia['campos_observados'],'tipo':'TRACTO'}
    vehiculo['evidencias'].append(evidencia)
    ruta.write_text(json.dumps(datos),encoding='utf-8')
    vista=consultar_expediente(raiz,empresa='MBT',entidad='VEHICULO',referencia=CARRO)
    assert vista['tipo_vehiculo_estado']=='INCIERTO' and vista['ausentes']==[]


def test_contrato_cli_entrega_requisitos_y_asignaciones(raiz, capsys):
    from atlas_core.cli_fichas_catalogos import main
    assert main(['--raiz-atlas',str(raiz),'--expediente-entidad','CHOFER',
                 '--expediente-referencia',SOLO])==0
    salida=json.loads(capsys.readouterr().out)
    assert len(salida['requisitos_documentales'])==7
    assert salida['asignaciones_requisitos']['tracto']['patente']==TRACTO
    assert {r['ambito'] for r in salida['requisitos_documentales']}=={'CHOFER','VEHICULO','COBERTURA'}
