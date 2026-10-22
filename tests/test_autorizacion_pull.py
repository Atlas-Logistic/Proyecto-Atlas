"""Gates sinteticos y revocacion durante una pasada, sin Cloud/OCR/datos reales."""
from datetime import datetime, timezone
import json
from unittest.mock import patch

import pytest

from atlas_core.autorizacion_pull import validar_autorizacion, autorizacion_vigente
from atlas_core.cloud_mobile_sync_cliente import _procesar_y_confirmar_cloud
from atlas_core.escritor_operativo import LeaseEscritorOperativo, ErrorEscritorOperativo
from sincronizar_mobile_cloud import ejecutar_pull_con_escritor
from tests.test_sincronizar_mobile_cloud_escritor import EscritorFalso


@pytest.fixture
def gate(tmp_path):
    a = tmp_path / 'auth.json'; c = tmp_path / 'config.json'
    a.write_text(json.dumps(dict(schema_version=1, modo='persistente', autor='Javier',
        exclusividad_verificada=True, habilitada=True, revocada=False, machine_guid='casa')))
    c.write_text(json.dumps(dict(modo_escritor='lease_cloud', autorizada=True,
        habilitada=True, machine_guid='casa')))
    return a, c


def test_persistente_sigue_valida_despues_del_vencimiento_anterior(gate):
    a, c = gate
    for fecha in [datetime(2026,10,24,tzinfo=timezone.utc), datetime(2035,1,1,tzinfo=timezone.utc)]:
        assert validar_autorizacion(a,c,ahora=fecha,equipo='casa')
    with pytest.raises(ValueError,match='otro equipo'):
        validar_autorizacion(a,c,equipo='oficina')


@pytest.mark.parametrize('cambio', [{'revocada':True},{'habilitada':False},{'modo':'desconocido'},
    {'vence_utc':'2099-01-01T00:00:00Z'},{'machine_guid':'oficina'},{'autor':'otro'},
    {'exclusividad_verificada':False}])
def test_gate_falla_cerrado(gate,cambio):
    a,c=gate; data=json.loads(a.read_text());data.update(cambio);a.write_text(json.dumps(data))
    with patch('atlas_core.autorizacion_pull.identidad_equipo',return_value='casa'):
        assert not autorizacion_vigente(a,c)


@pytest.mark.parametrize('tipo',['borrado','json_invalido','config_invalida'])
def test_ausencia_o_configuracion_invalida(gate,tipo):
    a,c=gate
    if tipo=='borrado':a.unlink()
    elif tipo=='json_invalido':a.write_text('{')
    else:c.write_text('{}')
    with patch('atlas_core.autorizacion_pull.identidad_equipo',return_value='casa'):
        assert not autorizacion_vigente(a,c)


def test_temporal_expirada_no_se_convierte_en_persistente(gate):
    a,c=gate;a.write_text(json.dumps(dict(autor='Javier',exclusividad_verificada=True,vence_utc='2000-01-01T00:00:00Z')))
    assert not autorizacion_vigente(a,c)


@pytest.mark.parametrize('revocar',['gate','config'])
def test_revocacion_en_ciclo_bloquea_escritura_y_confirmacion(gate,tmp_path,monkeypatch,revocar):
    a,c=gate;monkeypatch.setenv('ATLAS_PULL_AUTORIZACION',str(a));monkeypatch.setenv('ATLAS_OPERACION_CONFIG',str(c))
    raiz=tmp_path/'operacion';raiz.mkdir();escritor=EscritorFalso(adquirido=True)
    repo=type('Repo',(),{'raiz_atlas':raiz})()
    def procesar(**kw):
        assert kw['puede_continuar']()
        archivo=a if revocar=='gate' else c;data=json.loads(archivo.read_text());data['habilitada']=False;archivo.write_text(json.dumps(data))
        assert not kw['puede_continuar']() # mismo callback usado antes del ACK normal
        (raiz/'publicacion.json').write_text('{}')
    with patch('atlas_core.autorizacion_pull.identidad_equipo',return_value='casa'), patch('sincronizar_mobile_cloud.sincronizar_envios_cloud',side_effect=procesar):
        with pytest.raises(PermissionError):
            ejecutar_pull_con_escritor(base_url='https://cloud.test',token_motor='sintetico',consumidor='casa',
                repositorio=repo,timeout=1,procesar=True,dataset=None,carpeta_catalogos=None,
                fabrica_escritor=lambda **kw:escritor)
    assert escritor.cerrado and not (raiz/'publicacion.json').exists()


def test_credencial_revocada_invalida_lease_temporal():
    lease=LeaseEscritorOperativo(base_url='https://cloud.test',token_motor='sintetico',
        heartbeat_segundos=0,margen_relevo_segundos=0)
    with patch('atlas_core.escritor_operativo._json',side_effect=ErrorEscritorOperativo('HTTP 401')):
        assert not lease.adquirir()
    lease.lease_token='lease-sintetico'
    with patch('atlas_core.escritor_operativo._json',side_effect=ErrorEscritorOperativo('HTTP 401')):
        assert not lease.renovar() and not lease.vigente


def test_revocacion_antes_de_ack_normal_no_confirma(gate):
    a,c=gate
    def procesar(*args,**kwargs):
        data=json.loads(a.read_text());data['revocada']=True;a.write_text(json.dumps(data))
        return {'completado':True}
    resumen={'detenido_por_escritor':False}
    with patch('atlas_core.autorizacion_pull.identidad_equipo',return_value='casa'), \
         patch('atlas_core.cloud_mobile_sync_cliente._procesar_envio_cloud',side_effect=procesar), \
         patch('atlas_core.cloud_mobile_sync_cliente._sumar_resultado_procesamiento'), \
         patch('atlas_core.cloud_mobile_sync_cliente._confirmar_cloud') as confirmar:
        _procesar_y_confirmar_cloud(None,'sintetico',lease_token='t',lease_activo=None,
            base_url='https://cloud.test',token_motor='t',timeout=1,dataset=None,carpeta_catalogos=None,
            puede_continuar=lambda:autorizacion_vigente(a,c),obtener_proveedor_ocr=lambda:None,resumen=resumen)
    assert resumen['detenido_por_escritor'] and not confirmar.called
