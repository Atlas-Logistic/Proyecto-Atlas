"""Aceptación simple de documentos pendientes (contrato 2), sólo en raíces sintéticas.

Desktop puede aceptar sin nombre de revisor (persona no declarada, canal y equipo verificable si existe),
corregir emisión y vencimiento aunque el OCR los haya leído y completar tipo, patente, inicio o reemplazado
con la confirmación explícita del original. La vista previa y su clave siguen siendo obligatorias.
"""
from __future__ import annotations

import pytest

from atlas_core import escritor_operativo
from atlas_core.expediente_digital import (ErrorExpedienteDigital, PERSONA_DECLARADA, PERSONA_NO_DECLARADA,
                                           resolver_documento_pendiente, revisar_documento_pendiente,
                                           verificar_originales)
from atlas_core.correccion_fechas_documentales import ORIGEN_PERSONA, _origenes
from tests.test_expediente_digital_base import PATENTE, RELOJ
from tests.test_renovacion_documental import alta, soap
from tests.test_resolucion_documento_vehiculo import (almacen, documento_en, eventos, raiz, revisar,  # noqa: F401
                                                      resolver)

EQUIPO = "pc-12345678-1234-4234-8234-123456789abc"


@pytest.fixture(autouse=True)
def equipo(tmp_path, monkeypatch):
    """Identidad del escritor operativo de la instalación (sintética, en tmp)."""
    ruta = tmp_path / "local" / "escritor_operativo_id.txt"
    ruta.parent.mkdir(parents=True)
    ruta.write_text(EQUIPO, encoding="utf-8")
    monkeypatch.delenv("ATLAS_ESCRITOR_ID", raising=False)
    monkeypatch.setattr(escritor_operativo, "ruta_identidad_escritor", lambda: ruta)
    return ruta


def sin_nombre(raiz, documento, propuesta=None, **extra):  # noqa: F811
    return resolver(raiz, documento, propuesta=propuesta, autor="", revisor_no_declarado=True, **extra)


def test_vista_previa_informa_el_contrato_y_precarga_solo_lo_leido(raiz):  # noqa: F811
    pendiente = alta(raiz, soap("01/11/2026", "31/10/2027", "XX"), contenido=b"precarga")
    vista = revisar(raiz, pendiente)
    assert vista["contrato_aceptacion"] == 2
    assert vista["precarga"] == {"fecha_emision": "", "fecha_vencimiento": "2027-10-31"}
    assert {"fecha_emision", "fecha_vencimiento", "patente"} <= set(vista["editables"]) and "tipo" not in vista["editables"]
    assert "patente" in vista["confirmacion_original"] and "tipo" not in vista["confirmacion_original"]
    assert "reemplaza" in vista["confirmacion_original"]


def test_acepta_sin_revisor_con_fechas_corregidas_y_auditoria_completa(raiz):  # noqa: F811
    pendiente = alta(raiz, soap("01/11/2026", "31/10/2027", "XX"), contenido=b"corrige")
    propuesta = {"patente": PATENTE, "fecha_emision": "2026-10-25", "fecha_vencimiento": "2027-11-15"}
    assert revisar(raiz, pendiente, propuesta)["consecuencia"]["accion"] == "ACTIVAR"
    aceptado = sin_nombre(raiz, pendiente, propuesta, confirmo_original=True)
    assert (aceptado["fecha_emision"], aceptado["fecha_vencimiento"], aceptado["pendiente_revision"]) == ("2026-10-25", "2027-11-15", False)
    rh = aceptado["revision_humana"]
    assert rh["autor"] is None and rh["persona"] == PERSONA_NO_DECLARADA and rh["canal"] == "DESKTOP"
    assert rh["equipo"] == {"id": EQUIPO, "fuente": "ESCRITOR_OPERATIVO", "verificable": True}
    assert rh["fechas"]["fecha_vencimiento"] == {"ocr": "2027-10-31", "valor": "2027-11-15", "origen": "HUMANO"}
    assert rh["fechas"]["fecha_emision"]["origen"] == "HUMANO"
    assert rh["correccion_ocr"] == {"fecha_vencimiento": {"antes": "2027-10-31", "despues": "2027-11-15"}}
    assert rh["datos_completados"] == ["patente"] and rh["confirmo_original"] is True
    # La lectura automática del original se conserva tal cual (no se reescribe con lo corregido).
    assert documento_en(raiz, pendiente["documento_id"])["extraccion_automatica"]["campos"]["vencimiento"]["valor"] == "2027-10-31"
    # Lo corregido figura como confirmado por una persona, nunca como resultado del OCR.
    doc = documento_en(raiz, pendiente["documento_id"])
    assert _origenes("EXPEDIENTE", doc, {"fecha_emision": "2026-10-25", "fecha_vencimiento": "2027-11-15"}) == {
        "fecha_emision": ORIGEN_PERSONA, "fecha_vencimiento": ORIGEN_PERSONA}
    evento, = eventos(raiz, "DOCUMENTO_REVISION_CONFIRMADA")
    assert evento["autor"] is None and evento["persona"] == PERSONA_NO_DECLARADA and evento["equipo"]["id"] == EQUIPO
    assert evento["correccion_ocr"]["fecha_vencimiento"]["despues"] == "2027-11-15"
    assert {o["documento_id"]: o["estado"] for o in verificar_originales(raiz, empresa="MBT")}[pendiente["documento_id"]] == "INTEGRO"


def test_fecha_leida_aceptada_sin_cambios_queda_como_ocr(raiz):  # noqa: F811
    pendiente = alta(raiz, soap("01/11/2026", "31/10/2027", "XX"), contenido=b"ocr")
    aceptado = sin_nombre(raiz, pendiente, {"patente": PATENTE}, confirmo_original=True)
    assert aceptado["revision_humana"]["fechas"]["fecha_vencimiento"]["origen"] == "OCR"
    assert aceptado["revision_humana"]["correccion_ocr"] == {} and "fechas_confirmadas" not in aceptado


def test_sin_confirmar_el_original_no_acepta_datos_completados(raiz):  # noqa: F811
    pendiente = alta(raiz, soap("01/11/2026", "31/10/2027", "XX"), contenido=b"sin-confirmar")
    antes = almacen(raiz)
    with pytest.raises(ErrorExpedienteDigital, match="aparecen en el original: patente"):
        sin_nombre(raiz, pendiente, {"patente": PATENTE})
    assert almacen(raiz) == antes and documento_en(raiz, pendiente["documento_id"])["pendiente_revision"]


def test_sin_datos_completados_no_hace_falta_confirmar_el_original(raiz):  # noqa: F811
    from tests.test_resolucion_documento_vehiculo import SOAP_TITULO
    pendiente = alta(raiz, SOAP_TITULO, contenido=b"solo-fechas")
    vista = revisar(raiz, pendiente)
    assert "VENCIMIENTO_NO_LEIDO" in vista["motivos"] and vista["precarga"]["fecha_vencimiento"] == ""
    aceptado = sin_nombre(raiz, pendiente, {"fecha_vencimiento": "2027-11-30"})
    assert aceptado["fecha_vencimiento"] == "2027-11-30" and aceptado["revision_humana"]["datos_completados"] == []
    assert aceptado["revision_humana"]["fechas"]["fecha_vencimiento"] == {"ocr": "", "valor": "2027-11-30", "origen": "HUMANO"}
    assert aceptado["revision_humana"]["correccion_ocr"] == {}


@pytest.mark.parametrize("extra,mensaje", [
    ({"autor": "", "revisor_no_declarado": False}, "indique quién revisó"),
    ({"autor": "Javier", "revisor_no_declarado": True}, "no ambos"),
    ({"autor": "", "revisor_no_declarado": True, "actor": "MOTOR"}, "sólo el canal Desktop"),
])
def test_autoria_explicita_y_solo_desde_desktop(raiz, extra, mensaje):  # noqa: F811
    pendiente = alta(raiz, soap("01/11/2026", "31/10/2027", "XX"), contenido=b"autoria")
    clave = revisar(raiz, pendiente, {"patente": PATENTE})["consecuencia"]["clave"]
    with pytest.raises(ErrorExpedienteDigital, match=mensaje):
        resolver_documento_pendiente(raiz, empresa="MBT", referencia=PATENTE, documento_id=pendiente["documento_id"],
                                     sha256=pendiente["sha256"], decision="CONFIRMAR", confirmacion_humana=True,
                                     propuesta={"patente": PATENTE}, clave_consecuencia=clave, confirmo_original=True,
                                     reloj=RELOJ, **extra)


def test_revisor_declarado_conserva_el_contrato_anterior(raiz):  # noqa: F811
    pendiente = alta(raiz, soap("01/11/2026", "31/10/2027", "XX"), contenido=b"declarado")
    aceptado = resolver(raiz, pendiente, propuesta={"patente": PATENTE})  # autor «Javier Revisor», sin confirmo_original
    assert aceptado["revision_humana"]["autor"] == "Javier Revisor"
    assert aceptado["revision_humana"]["persona"] == PERSONA_DECLARADA and "equipo" not in aceptado["revision_humana"]


def test_equipo_no_disponible_no_se_inventa_ni_se_crea(raiz, equipo):  # noqa: F811
    equipo.unlink()
    pendiente = alta(raiz, soap("01/11/2026", "31/10/2027", "XX"), contenido=b"sin-equipo")
    aceptado = sin_nombre(raiz, pendiente, {"patente": PATENTE}, confirmo_original=True)
    assert aceptado["revision_humana"]["equipo"] is None and not equipo.exists()


def test_override_de_entorno_queda_como_no_verificable(raiz, monkeypatch):  # noqa: F811
    monkeypatch.setenv("ATLAS_ESCRITOR_ID", "soporte-1")
    pendiente = alta(raiz, soap("01/11/2026", "31/10/2027", "XX"), contenido=b"override")
    aceptado = sin_nombre(raiz, pendiente, {"patente": PATENTE}, confirmo_original=True)
    assert aceptado["revision_humana"]["equipo"] == {"id": "soporte-1", "fuente": "OVERRIDE_ENTORNO", "verificable": False}


def test_validaciones_se_mantienen_con_fechas_corregidas(raiz):  # noqa: F811
    pendiente = alta(raiz, soap("01/11/2026", "31/10/2027", "XX"), contenido=b"validaciones")
    previa = revisar(raiz, pendiente, {"patente": PATENTE, "fecha_emision": "2028-01-01", "fecha_vencimiento": "2027-11-15"})
    assert previa["consecuencia"]["motivo"] == "FECHAS_NO_VALIDAS" and not previa["puede_confirmar"]
    assert revisar(raiz, pendiente, {"patente": "ZZ1234"})["consecuencia"]["motivo"] == "PATENTE_NO_CORRESPONDE"
    assert revisar(raiz, pendiente, {"tipo": "PERMISO_CIRCULACION", "patente": PATENTE})["consecuencia"]["motivo"] == "CONTRADICE_LECTURA"


def test_clave_de_otra_propuesta_no_acepta(raiz):  # noqa: F811
    """Concurrencia/consistencia: la clave sólo vale para la propuesta exacta de la vista previa."""
    pendiente = alta(raiz, soap("01/11/2026", "31/10/2027", "XX"), contenido=b"clave")
    clave = revisar(raiz, pendiente, {"patente": PATENTE})["consecuencia"]["clave"]
    with pytest.raises(ErrorExpedienteDigital, match="consecuencia cambió"):
        sin_nombre(raiz, pendiente, {"patente": PATENTE, "fecha_vencimiento": "2027-12-31"}, clave=clave, confirmo_original=True)
    assert documento_en(raiz, pendiente["documento_id"])["pendiente_revision"]


def test_rechazo_sin_revisor_exige_motivo_y_conserva_original(raiz):  # noqa: F811
    pendiente = alta(raiz, soap("01/11/2026", "31/10/2027", "XX"), contenido=b"rechazo")
    with pytest.raises(ErrorExpedienteDigital):
        sin_nombre(raiz, pendiente, decision="RECHAZAR")
    rechazado = sin_nombre(raiz, pendiente, decision="RECHAZAR", motivo="No corresponde")
    assert rechazado["estado"] == "ANULADO" and rechazado["rechazo"]["persona"] == PERSONA_NO_DECLARADA
    assert rechazado["rechazo"]["autor"] is None and rechazado["rechazo"]["equipo"]["id"] == EQUIPO
    assert {o["documento_id"]: o["estado"] for o in verificar_originales(raiz, empresa="MBT")}[pendiente["documento_id"]] == "INTEGRO"
