"""Revisión humana en Desktop de documentos vehiculares que el OCR dejó pendientes.

La persona completa lo no leído y confirma o rechaza; nunca contradice lo leído con
evidencia, y la consecuencia la decide `renovacion_documental` (la misma regla del
alta). Se conservan original, historial, auditoría y separación por empresa.
Sólo datos sintéticos en tmp_path.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone

import pytest

from atlas_core.expediente_digital import (
    ErrorExpedienteDigital, anular_documento, consultar_expediente, leer_expediente, resolver_documento_pendiente,
    revisar_documento_pendiente, ruta_almacen_expediente, verificar_originales,
)
from tests.test_expediente_digital_base import PATENTE, RELOJ, _catalogos
from tests.test_renovacion_documental import alta, soap

OTRA_PATENTE = "ZZ1234"
SOAP_TITULO = ["CERTIFICADO SEGURO OBLIGATORIO ACCIDENTES", PATENTE, "PERSONALES ELECTRONICO LEY 18.490"]
SIN_TIPO = ["DOCUMENTO SINTETICO", "PATENTE " + PATENTE, "VENCIMIENTO: 30/09/2027"]
RC = ["POLIZA DE RESPONSABILIDAD CIVIL", "PATENTE " + PATENTE, "VENCIMIENTO: 30/09/2027", "COBERTURA: RESPONSABILIDAD CIVIL"]
ROBO = ["POLIZA DE SEGURO CONTRA ROBO", "PATENTE " + PATENTE, "VENCIMIENTO: 30/09/2027", "COBERTURA: ROBO"]
DOBLE = ["COMPANIA DE SEGUROS SINTETICA", "POLIZA N 7788", "PATENTE " + PATENTE, "VENCIMIENTO: 30/09/2028",
         "COBERTURAS: RESPONSABILIDAD CIVIL Y ROBO"]


@pytest.fixture
def raiz(tmp_path):
    _catalogos(tmp_path / "catalogos_privados", "ANA", vehiculos=(PATENTE, OTRA_PATENTE))
    return tmp_path


def revisar(raiz, documento, propuesta=None, empresa="MBT", reloj=RELOJ):
    return revisar_documento_pendiente(raiz, empresa=empresa, referencia=PATENTE,
                                       documento_id=documento["documento_id"], propuesta=propuesta, reloj=reloj)


def resolver(raiz, documento, decision="CONFIRMAR", propuesta=None, *, clave=None, empresa="MBT", reloj=RELOJ, **extra):
    if clave is None and decision == "CONFIRMAR":
        clave = revisar(raiz, documento, propuesta, empresa, reloj)["consecuencia"]["clave"]
    datos = {"sha256": documento["sha256"], "autor": "Javier Revisor", "confirmacion_humana": True, **extra}
    return resolver_documento_pendiente(raiz, empresa=empresa, referencia=PATENTE, documento_id=documento["documento_id"],
                                        decision=decision, propuesta=propuesta, clave_consecuencia=clave or "",
                                        reloj=reloj, **datos)


def almacen(raiz, empresa="MBT"):
    return ruta_almacen_expediente(raiz, empresa).read_bytes()


def documento_en(raiz, documento_id, empresa="MBT"):
    return next(d for d in leer_expediente(raiz, empresa=empresa)["documentos"] if d["documento_id"] == documento_id)


def eventos(raiz, operacion, empresa="MBT"):
    return [e for e in leer_expediente(raiz, empresa=empresa)["historial"] if e["operacion"] == operacion]


# ---------------------------------------------------------------- casos que la persona puede resolver


def test_tipo_no_identificado_se_completa_y_confirma_con_auditoria(raiz):
    pendiente = alta(raiz, SIN_TIPO, tipo="REVISION_TECNICA", contenido=b"sin-tipo")
    assert pendiente["tipo"] == "DOCUMENTO_VEHICULO_PENDIENTE" and pendiente["pendiente_revision"]
    vista = revisar(raiz, pendiente)
    assert vista["motivos"] == ["TIPO_NO_IDENTIFICADO", "VENCIMIENTO_NO_LEIDO"]
    assert {"tipo", "fecha_vencimiento"} <= set(vista["editables"]) and "patente" not in vista["editables"]
    assert vista["leido"]["patente"] == PATENTE and vista["documento"]["tipo_informado"] == "REVISION_TECNICA"
    assert (vista["consecuencia"]["accion"], vista["consecuencia"]["motivo"]) == ("BLOQUEADO", "TIPO_FALTANTE")
    assert not vista["puede_confirmar"]
    propuesta = {"tipo": "REVISION_TECNICA", "fecha_vencimiento": "2027-09-30"}
    previa = revisar(raiz, pendiente, propuesta)
    assert previa["consecuencia"]["accion"] == "ACTIVAR" and previa["puede_confirmar"]

    confirmado = resolver(raiz, pendiente, propuesta=propuesta)
    assert (confirmado["tipo"], confirmado["fecha_vencimiento"], confirmado["pendiente_revision"]) == (
        "REVISION_TECNICA", "2027-09-30", False)
    assert confirmado["confirmado_por_humano"] and confirmado["revision_humana"]["autor"] == "Javier Revisor"
    assert confirmado["revision_humana"]["motivos_revisados"] == ["TIPO_NO_IDENTIFICADO", "VENCIMIENTO_NO_LEIDO"]
    assert confirmado["revision_humana"]["cambios"]["tipo"] == {"antes": "DOCUMENTO_VEHICULO_PENDIENTE",
                                                                "despues": "REVISION_TECNICA"}
    evento, = eventos(raiz, "DOCUMENTO_REVISION_CONFIRMADA")
    assert (evento["actor"], evento["autor"], evento["renovacion"]) == ("DESKTOP", "Javier Revisor", "ACTIVAR")
    consulta = consultar_expediente(raiz, empresa="MBT", entidad="VEHICULO", referencia=PATENTE, hoy=date(2026, 11, 9))
    vigente, = [d for d in consulta["documentos"] if d["documento_id"] == pendiente["documento_id"]]
    assert vigente["estado_vencimiento"] == "VIGENTE"
    assert "REVISION_TECNICA" not in {a["tipo"] for a in consulta["ausentes"]}
    assert any(e["operacion"] == "DOCUMENTO_REVISION_CONFIRMADA" for e in consulta["trazabilidad"])
    # Original intacto: mismo archivo y huella.
    assert confirmado["archivo"] == pendiente["archivo"] and confirmado["sha256"] == pendiente["sha256"]
    assert {o["documento_id"]: o["estado"] for o in verificar_originales(raiz, empresa="MBT")}[pendiente["documento_id"]] == "INTEGRO"


def test_patente_no_leida_se_completa_solo_con_la_del_mismo_vehiculo(raiz):
    pendiente = alta(raiz, soap("01/11/2026", "31/10/2027", "XX"), contenido=b"sin-patente")
    vista = revisar(raiz, pendiente)
    assert vista["motivos"] == ["PATENTE_NO_LEIDA"] and "patente" in vista["editables"]
    assert vista["consecuencia"]["motivo"] == "PATENTE_FALTANTE"
    assert revisar(raiz, pendiente, {"patente": OTRA_PATENTE})["consecuencia"]["motivo"] == "PATENTE_NO_CORRESPONDE"
    assert revisar(raiz, pendiente, {"patente": "AB1234"})["consecuencia"]["motivo"] == "PATENTE_NO_CORRESPONDE"
    assert revisar(raiz, pendiente, {"patente": PATENTE.lower()})["consecuencia"]["accion"] == "ACTIVAR"
    confirmado = resolver(raiz, pendiente, propuesta={"patente": PATENTE})
    assert not confirmado["pendiente_revision"] and confirmado["revision_humana"]["patente"] == PATENTE


def test_tipo_leido_distinto_con_vigente_se_resuelve_con_la_regla_unica(raiz):
    viejo = alta(raiz, soap("01/10/2026", "30/09/2027", PATENTE), contenido=b"viejo")
    nuevo = alta(raiz, soap("01/11/2026", "31/10/2027", PATENTE), tipo="PERMISO_CIRCULACION", contenido=b"nuevo")
    assert nuevo["posible_reemplazo"]["motivo"] == "TIPO_LEIDO_CON_VIGENTE"
    vista = revisar(raiz, nuevo)
    assert vista["motivos"] == ["TIPO_LEIDO_CON_VIGENTE"] and vista["editables"] == ["fecha_emision"]
    assert [a["documento_id"] for a in vista["anteriores"]] == [viejo["documento_id"]]
    assert (vista["consecuencia"]["accion"], vista["consecuencia"]["documentos"]) == ("REEMPLAZAR", [viejo["documento_id"]])
    confirmado = resolver(raiz, nuevo)
    assert not confirmado["pendiente_revision"] and "posible_reemplazo" not in confirmado
    assert confirmado["revision_humana"]["posible_reemplazo_resuelto"]["motivo"] == "TIPO_LEIDO_CON_VIGENTE"
    assert documento_en(raiz, viejo["documento_id"])["estado"] == "REEMPLAZADO"
    assert eventos(raiz, "DOCUMENTO_REVISION_CONFIRMADA")[0]["reemplaza"] == [viejo["documento_id"]]


def test_inicio_ambiguo_se_elige_entre_las_fechas_del_original_y_se_programa(raiz):
    viejo = alta(raiz, soap("01/10/2026", "30/09/2027", PATENTE), contenido=b"viejo")
    nuevo = alta(raiz, SOAP_TITULO + ["INICIO DE VIGENCIA 01/10/2027", "VIGENCIA DESDE 01/11/2027",
                                      "VENCIMIENTO 30/09/2028"], contenido=b"ambiguo")
    vista = revisar(raiz, nuevo)
    assert vista["motivos"] == ["INICIO_AMBIGUO"] and vista["inicios_observados"] == ["2027-10-01", "2027-11-01"]
    assert vista["consecuencia"]["accion"] == "PENDIENTE"  # sin elegir, sigue ambiguo
    # No puede inventar una fecha que adelante el reemplazo del vigente.
    assert revisar(raiz, nuevo, {"inicio_vigencia": "2026-11-01"})["consecuencia"]["motivo"] == "INICIO_NO_OBSERVADO"
    previa = revisar(raiz, nuevo, {"inicio_vigencia": "2027-10-01"})["consecuencia"]
    assert (previa["accion"], previa["fecha"], previa["documentos"]) == ("PROGRAMAR", "2027-10-01", [viejo["documento_id"]])
    programado = resolver(raiz, nuevo, propuesta={"inicio_vigencia": "2027-10-01"})
    assert programado["transicion_programada"]["fecha"] == "2027-10-01" and programado["pendiente_revision"]
    assert documento_en(raiz, viejo["documento_id"])["estado"] == "ACTIVO"  # rige hasta esa fecha
    ver = lambda hoy: consultar_expediente(raiz, empresa="MBT", entidad="VEHICULO", referencia=PATENTE, hoy=hoy)  # noqa: E731
    assert [d["documento_id"] for d in ver(date(2027, 9, 30))["historico"]] == []
    assert [d["documento_id"] for d in ver(date(2027, 10, 1))["documentos"]] == [nuevo["documento_id"]]
    with pytest.raises(ErrorExpedienteDigital, match="ya no está pendiente"):
        revisar(raiz, programado)


def test_varios_anteriores_se_resuelve_eligiendo_cual_reemplaza_sin_perder_coberturas(raiz):
    rc = alta(raiz, RC, tipo="POLIZA_RESPONSABILIDAD_CIVIL", contenido=b"rc")
    robo = alta(raiz, ROBO, tipo="POLIZA_ROBO", contenido=b"robo")
    doble = alta(raiz, DOBLE, tipo="POLIZA_RESPONSABILIDAD_CIVIL", contenido=b"doble")
    assert doble["posible_reemplazo"]["motivo"] == "VARIOS_ANTERIORES"
    vista = revisar(raiz, doble)
    assert vista["leido"]["coberturas"] == ["POLIZA_RESPONSABILIDAD_CIVIL", "POLIZA_ROBO"]
    assert {a["documento_id"] for a in vista["anteriores"]} == {rc["documento_id"], robo["documento_id"]}
    assert vista["consecuencia"]["accion"] == "PENDIENTE"
    assert revisar(raiz, doble, {"reemplaza": "no-existe"})["consecuencia"]["motivo"] == "VINCULO_NO_VERIFICABLE"
    previa = revisar(raiz, doble, {"reemplaza": rc["documento_id"]})["consecuencia"]
    assert (previa["accion"], previa["documentos"]) == ("REEMPLAZAR", [rc["documento_id"]])
    resolver(raiz, doble, propuesta={"reemplaza": rc["documento_id"]})
    estados = {d["documento_id"]: d["estado"] for d in leer_expediente(raiz, empresa="MBT")["documentos"]}
    assert estados == {rc["documento_id"]: "REEMPLAZADO", robo["documento_id"]: "ACTIVO", doble["documento_id"]: "ACTIVO"}
    consulta = consultar_expediente(raiz, empresa="MBT", entidad="VEHICULO", referencia=PATENTE, hoy=date(2026, 11, 9))
    cubierto, = [d for d in consulta["documentos"] if d["documento_id"] == doble["documento_id"]]
    assert cubierto["tipos_cubiertos"] == ["POLIZA_RESPONSABILIDAD_CIVIL", "POLIZA_ROBO"]
    assert not cubierto["pendiente_revision"]


# ---------------------------------------------------------------- casos que deben permanecer pendientes


def test_patente_de_otro_vehiculo_no_se_confirma_y_se_puede_rechazar(raiz):
    pendiente = alta(raiz, soap("01/11/2026", "31/10/2027", OTRA_PATENTE), contenido=b"ajeno")
    vista = revisar(raiz, pendiente, {"patente": PATENTE})
    assert vista["motivos"] == ["PATENTE_DE_OTRO_VEHICULO"] and "patente" not in vista["editables"]
    assert vista["consecuencia"]["motivo"] == "PATENTE_DE_OTRO_VEHICULO" and not vista["puede_confirmar"]
    antes = almacen(raiz)
    with pytest.raises(ErrorExpedienteDigital, match="consecuencia cambió|queda pendiente"):
        resolver(raiz, pendiente, propuesta={"patente": PATENTE})
    assert almacen(raiz) == antes

    rechazado = resolver(raiz, pendiente, "RECHAZAR", motivo="El documento es de otro camión")
    assert rechazado["estado"] == "ANULADO" and rechazado["rechazo"]["autor"] == "Javier Revisor"
    assert rechazado["rechazo"]["motivos_revisados"] == ["PATENTE_DE_OTRO_VEHICULO"]
    evento, = eventos(raiz, "DOCUMENTO_RECHAZADO_EN_REVISION")
    assert (evento["motivo"], evento["autor"]) == ("El documento es de otro camión", "Javier Revisor")
    consulta = consultar_expediente(raiz, empresa="MBT", entidad="VEHICULO", referencia=PATENTE, hoy=date(2026, 11, 9))
    assert [d["documento_id"] for d in consulta["historico"]] == [pendiente["documento_id"]]
    assert {o["documento_id"]: o["estado"] for o in verificar_originales(raiz, empresa="MBT")}[pendiente["documento_id"]] == "INTEGRO"


@pytest.mark.parametrize("vencimiento", ["30/09/2027", "31/08/2027"])
def test_vencimiento_no_posterior_queda_pendiente_aunque_una_persona_confirme(raiz, vencimiento):
    viejo = alta(raiz, soap("01/10/2026", "30/09/2027", PATENTE), contenido=b"viejo")
    dudoso = alta(raiz, soap("01/09/2026", vencimiento, PATENTE), contenido=b"dudoso")
    vista = revisar(raiz, dudoso)
    assert (vista["consecuencia"]["accion"], vista["consecuencia"]["motivo"]) == ("PENDIENTE", "VENCIMIENTO_NO_POSTERIOR")
    antes = almacen(raiz)
    with pytest.raises(ErrorExpedienteDigital, match="queda pendiente por seguridad"):
        resolver(raiz, dudoso, clave=vista["consecuencia"]["clave"])
    assert almacen(raiz) == antes and documento_en(raiz, viejo["documento_id"])["estado"] == "ACTIVO"


def test_poliza_sin_coberturas_leidas_no_se_confirma_ni_con_coberturas_declaradas(raiz):
    pendiente = alta(raiz, ["POLIZA DE SEGURO CONTRA ROBO", "PATENTE " + PATENTE, "VENCIMIENTO: 30/09/2027"],
                     tipo="POLIZA_ROBO", contenido=b"sin-coberturas")
    vista = revisar(raiz, pendiente, {"coberturas": ["POLIZA_ROBO"]})
    assert vista["motivos"] == ["COBERTURAS_NO_LEIDAS"] and "coberturas" not in vista["editables"]
    assert vista["consecuencia"]["motivo"] == "COBERTURAS_SIN_EVIDENCIA" and not vista["puede_confirmar"]


def test_poliza_con_menos_coberturas_no_retira_la_anterior(raiz):
    doble = alta(raiz, DOBLE, tipo="POLIZA_RESPONSABILIDAD_CIVIL", contenido=b"doble")
    solo_robo = alta(raiz, [x.replace("30/09/2027", "30/09/2029") for x in ROBO], tipo="POLIZA_ROBO", contenido=b"robo")
    assert solo_robo["posible_reemplazo"]["motivo"] == "COBERTURAS_REDUCIDAS"
    for propuesta in (None, {"reemplaza": doble["documento_id"]}):
        assert revisar(raiz, solo_robo, propuesta)["consecuencia"]["motivo"] == "COBERTURAS_REDUCIDAS"


@pytest.mark.parametrize("campo,valor", [
    ("tipo", "PERMISO_CIRCULACION"), ("fecha_vencimiento", "2029-12-31"), ("inicio_vigencia", "2026-10-01"),
])
def test_lo_leido_con_evidencia_no_se_contradice(raiz, campo, valor):
    alta(raiz, soap("01/10/2026", "30/09/2027", PATENTE), contenido=b"viejo")
    nuevo = alta(raiz, soap("01/11/2026", "31/10/2027", PATENTE), tipo="PERMISO_CIRCULACION", contenido=b"nuevo")
    consecuencia = revisar(raiz, nuevo, {campo: valor})["consecuencia"]
    assert (consecuencia["accion"], consecuencia["motivo"], consecuencia["campo"]) == ("BLOQUEADO", "CONTRADICE_LECTURA", campo)


@pytest.mark.parametrize("propuesta,motivo", [
    ({"tipo": "REVISION_TECNICA", "fecha_vencimiento": "2027-02-30"}, "FECHAS_NO_VALIDAS"),
    ({"tipo": "REVISION_TECNICA", "fecha_vencimiento": "2027-09-30", "fecha_emision": "2027-01-01"}, "FECHAS_NO_VALIDAS"),
    ({"tipo": "LICENCIA_CONDUCIR", "fecha_vencimiento": "2027-09-30"}, "TIPO_NO_ADMITIDO"),
    ({"tipo": "REVISION_TECNICA"}, "VENCIMIENTO_FALTANTE"),
    ({"tipo": "REVISION_TECNICA", "fecha_vencimiento": "2027-09-30", "inicio_vigencia": "2027-09-30"}, "FECHAS_CONTRADICTORIAS"),
])
def test_datos_completados_se_validan(raiz, propuesta, motivo):
    pendiente = alta(raiz, SIN_TIPO, tipo="REVISION_TECNICA", contenido=b"sin-tipo")
    assert revisar(raiz, pendiente, propuesta)["consecuencia"]["motivo"] == motivo


# ---------------------------------------------------------------- concurrencia, autoría y multiempresa


def test_confirmar_exige_que_la_consecuencia_no_haya_cambiado(raiz):
    viejo = alta(raiz, soap("01/10/2026", "30/09/2027", PATENTE), contenido=b"viejo")
    nuevo = alta(raiz, soap("01/11/2026", "31/10/2027", PATENTE), tipo="PERMISO_CIRCULACION", contenido=b"nuevo")
    clave = revisar(raiz, nuevo)["consecuencia"]["clave"]  # vista previa: reemplaza al viejo
    anular_documento(raiz, empresa="MBT", documento_id=viejo["documento_id"], actor="OTRO", motivo="error", reloj=RELOJ)
    with pytest.raises(ErrorExpedienteDigital, match="consecuencia cambió"):
        resolver(raiz, nuevo, clave=clave)
    assert documento_en(raiz, nuevo["documento_id"])["pendiente_revision"]
    assert revisar(raiz, nuevo)["consecuencia"]["accion"] == "ACTIVAR"


def test_huella_autor_y_confirmacion_humana_son_obligatorios(raiz):
    pendiente = alta(raiz, SIN_TIPO, tipo="REVISION_TECNICA", contenido=b"sin-tipo")
    propuesta = {"tipo": "REVISION_TECNICA", "fecha_vencimiento": "2027-09-30"}
    antes = almacen(raiz)
    with pytest.raises(ErrorExpedienteDigital, match="cambió desde que se abrió"):
        resolver(raiz, pendiente, propuesta=propuesta, sha256="0" * 64)
    with pytest.raises(ErrorExpedienteDigital, match="quién revisó"):
        resolver(raiz, pendiente, propuesta=propuesta, autor="  ")
    with pytest.raises(ErrorExpedienteDigital, match="persona revisó"):
        resolver(raiz, pendiente, propuesta=propuesta, confirmacion_humana=False)
    with pytest.raises(ErrorExpedienteDigital, match="motivo obligatorio"):
        resolver(raiz, pendiente, "RECHAZAR", motivo="")
    assert almacen(raiz) == antes


def test_original_alterado_impide_confirmar(raiz):
    pendiente = alta(raiz, SIN_TIPO, tipo="REVISION_TECNICA", contenido=b"sin-tipo")
    propuesta = {"tipo": "REVISION_TECNICA", "fecha_vencimiento": "2027-09-30"}
    clave = revisar(raiz, pendiente, propuesta)["consecuencia"]["clave"]
    ruta = ruta_almacen_expediente(raiz, "MBT").parent / pendiente["archivo"]
    ruta.write_bytes(b"alterado")
    with pytest.raises(ErrorExpedienteDigital, match="original no está íntegro"):
        resolver(raiz, pendiente, propuesta=propuesta, clave=clave)
    assert hashlib.sha256(ruta.read_bytes()).hexdigest() != pendiente["sha256"]


def test_documento_activo_o_de_otro_vehiculo_no_se_revisa(raiz):
    activo = alta(raiz, soap("01/10/2026", "30/09/2027", PATENTE), contenido=b"activo")
    with pytest.raises(ErrorExpedienteDigital, match="ya no está pendiente"):
        revisar(raiz, activo)
    pendiente = alta(raiz, SIN_TIPO, tipo="REVISION_TECNICA", contenido=b"sin-tipo")
    with pytest.raises(ErrorExpedienteDigital, match="no pertenece a este vehículo"):
        revisar_documento_pendiente(raiz, empresa="MBT", referencia=OTRA_PATENTE,
                                    documento_id=pendiente["documento_id"], reloj=RELOJ)


def test_revision_no_cruza_empresas(raiz):
    ajeno = alta(raiz, SIN_TIPO, tipo="REVISION_TECNICA", empresa="OTRA", contenido=b"otra")
    alta(raiz, SIN_TIPO, tipo="REVISION_TECNICA", contenido=b"propio")
    antes = almacen(raiz, "OTRA")
    with pytest.raises(ErrorExpedienteDigital, match="no existe en esta empresa"):
        revisar(raiz, ajeno)
    with pytest.raises(ErrorExpedienteDigital, match="no existe en esta empresa"):
        resolver(raiz, ajeno, "RECHAZAR", motivo="intento cruzado")
    assert almacen(raiz, "OTRA") == antes
    vista = revisar(raiz, ajeno, empresa="OTRA")
    assert vista["empresa"] == "OTRA" and vista["anteriores"] == []


def test_solo_se_muestran_los_anteriores_del_tipo_en_revision(raiz):
    from tests.test_extraccion_vencimientos_vehiculos import REVISION_REAL
    rt = alta(raiz, [x.replace("BPHR67", PATENTE) for x in REVISION_REAL], tipo="REVISION_TECNICA", contenido=b"rt")
    assert not rt["pendiente_revision"]
    soap_vigente = alta(raiz, soap("01/10/2026", "30/09/2027", PATENTE), contenido=b"soap")
    pendiente = alta(raiz, soap("01/11/2026", "31/10/2027", "XX"), contenido=b"sin-patente")
    assert [a["documento_id"] for a in revisar(raiz, pendiente)["anteriores"]] == [soap_vigente["documento_id"]]
    sin_tipo = alta(raiz, SIN_TIPO, tipo="SOAP", contenido=b"sin-tipo")
    assert [a["documento_id"] for a in revisar(raiz, sin_tipo)["anteriores"]] == [soap_vigente["documento_id"]]
    elegido = revisar(raiz, sin_tipo, {"tipo": "REVISION_TECNICA", "fecha_vencimiento": "2028-09-30"})
    assert [a["documento_id"] for a in elegido["anteriores"]] == [rt["documento_id"]]


def test_vista_previa_no_escribe(raiz):
    pendiente = alta(raiz, SIN_TIPO, tipo="REVISION_TECNICA", contenido=b"sin-tipo")
    antes = almacen(raiz)
    revisar(raiz, pendiente, {"tipo": "REVISION_TECNICA", "fecha_vencimiento": "2027-09-30"})
    assert almacen(raiz) == antes


def test_cli_de_consulta_entrega_la_vista_previa(raiz, monkeypatch, capsys):
    from atlas_core import cli_fichas_catalogos, expediente_digital
    pendiente = alta(raiz, SIN_TIPO, tipo="REVISION_TECNICA", contenido=b"sin-tipo")
    monkeypatch.setattr(expediente_digital, "empresa_del_proceso", lambda: "MBT")
    antes = almacen(raiz)
    codigo = cli_fichas_catalogos.main([
        "--raiz-atlas", str(raiz), "--expediente-referencia", PATENTE,
        "--expediente-revision-documento", pendiente["documento_id"],
        "--expediente-revision-propuesta", json.dumps({"tipo": "REVISION_TECNICA", "fecha_vencimiento": "2027-09-30"})])
    vista = json.loads(capsys.readouterr().out)
    assert codigo == 0 and vista["consecuencia"]["accion"] == "ACTIVAR" and almacen(raiz) == antes
    assert cli_fichas_catalogos.main(["--raiz-atlas", str(raiz), "--expediente-referencia", PATENTE,
                                      "--expediente-revision-documento", pendiente["documento_id"],
                                      "--expediente-revision-propuesta", "[1]"]) == 1


def test_transiciones_cumplidas_se_aplican_antes_de_revisar(raiz):
    alta(raiz, soap("01/10/2026", "30/09/2027", PATENTE), contenido=b"viejo")
    programado = alta(raiz, soap("01/10/2027", "30/09/2028", PATENTE), contenido=b"programado")
    assert programado["transicion_programada"]["fecha"] == "2027-10-01"
    pendiente = alta(raiz, SIN_TIPO, tipo="REVISION_TECNICA", contenido=b"sin-tipo")
    despues = lambda: datetime(2027, 10, 2, 12, tzinfo=timezone.utc)  # noqa: E731
    resolver(raiz, pendiente, propuesta={"tipo": "REVISION_TECNICA", "fecha_vencimiento": "2028-09-30"}, reloj=despues)
    assert eventos(raiz, "DOCUMENTO_REEMPLAZO_PROGRAMADO_APLICADO")


def test_revision_desktop_no_confirma_mientras_fichas_esta_ocupado(raiz):
    from atlas_core.almacenamiento_portable import bloqueo_sesion, SesionOcupadaError
    pendiente = alta(raiz, SIN_TIPO, tipo='REVISION_TECNICA', contenido=b'lock-desktop')
    propuesta = {'tipo': 'REVISION_TECNICA', 'fecha_vencimiento': '2027-09-30'}
    clave = revisar(raiz, pendiente, propuesta)['consecuencia']['clave']
    antes = almacen(raiz)
    with bloqueo_sesion(raiz / 'operacion' / 'actual', 'fichas_choferes_MBT'):
        with pytest.raises(SesionOcupadaError):
            resolver(raiz, pendiente, propuesta=propuesta, clave=clave)
    assert almacen(raiz) == antes
