from types import SimpleNamespace as N
from atlas_core.catalogo_fichas import _filas_vehiculos_confiables


def vehiculo(p, tipo, rut=None):
    ev = N(tipo='CONFIRMACION_HUMANA', resultado='SOPORTA', campos_observados={'rut_chofer_asociado':rut}) if rut else None
    return N(patente_canonica=p, tipo=tipo, evidencias=[ev] if ev else [])


def decision(valor, canonica, actor='JAVIER_MBT'):
    return {'tipo':'VEHICULO_DESCONOCIDO','decision_id':'d','accion':'SELECCIONAR_OTRA_PATENTE', 'campo':'patente_rampla', 'valor_documental':valor,'patente_canonica':canonica,'actor':actor,'documento':{'numero_guia':'1','numero_transporte':'T'}}


def test_decisiones_identidad_conflicto_y_evidencia_no_muta():
    fila={'numero_guia':'1','numero_transporte':'T','rut_chofer':'12345678-5','patente_rampla':'JD0659','patente_tracto':'VP8521'}
    v={'JD8659':vehiculo('JD8659','CARRO','123456785'),'JE8659':vehiculo('JE8659','CARRO'), 'VP8521':vehiculo('VP8521','TRACTO','123456785')}
    out=_filas_vehiculos_confiables([fila], '123456785', v, [decision('JD0659','JD8659','ATLAS_AUTOMATICO')])[0]
    assert (out['patente_rampla'],out['patente_tracto']) == ('JD8659','VP8521')
    assert fila['patente_rampla']=='JD0659'
    assert _filas_vehiculos_confiables([fila], '123456785', v, [decision('JD0659','JD8659'),decision('JD0659','JE8659')])[0]['patente_rampla']==''
    assert _filas_vehiculos_confiables([fila], '123456785', v, [])[0]['patente_rampla']==''
    assert _filas_vehiculos_confiables([{**fila,'rut_chofer':'99999999-9'}], '123456785', v, [decision('JD0659','JD8659')])[0]['patente_rampla']==''


def test_historico_decision_humana_y_vehiculo_sin_vinculo():
    fila={'numero_guia':'1','numero_transporte':'T','rut_chofer':'12345678-5','patente_rampla':'JD0659'}
    v={'JD8659':vehiculo('JD8659','CARRO'), 'JE8659':vehiculo('JE8659','CARRO')}
    assert _filas_vehiculos_confiables([fila], '123456785', v, [decision('JD0659','JD8659')])[0]['patente_rampla']=='JD8659'
    assert _filas_vehiculos_confiables([{**fila,'patente_rampla':'JE8659'}], '123456785', v, [])[0]['patente_rampla']==''
    assert _filas_vehiculos_confiables([fila], '123456785', v, [decision('JD0659','JD8659','ATLAS_AUTOMATICO')])[0]['patente_rampla']==''
