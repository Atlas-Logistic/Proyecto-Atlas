"""Coberturas de pólizas confirmadas por una persona en el original (Desktop), sólo con datos sintéticos.

Caso que lo origina: póliza de responsabilidad civil de un camión rígido adjuntada desde Desktop cuyo OCR
falló por completo. La persona ve el original y confirma tipo, fechas y coberturas; una misma póliza puede
acreditar responsabilidad civil y seguro de carga sin duplicar el original. Las coberturas leídas por OCR
no se pueden quitar; las agregadas quedan con procedencia HUMANO, autoría y confirmación del original.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from atlas_core import escritor_operativo
from atlas_core.expediente_digital import (ErrorExpedienteDigital, leer_expediente, registrar_documento,
                                           registrar_documento_vehiculo_desktop, resolver_documento_pendiente,
                                           revisar_documento_pendiente, ruta_almacen_expediente,
                                           verificar_originales, vista_expediente_desktop)
from atlas_core.renovacion_documental import decidir_renovacion, relacionado
from tests.test_identificacion_patentes import RIGIDO, TRACTO, raiz  # noqa: F401

RC, CARGA, ROBO = "POLIZA_RESPONSABILIDAD_CIVIL", "SEGURO_CARGA", "POLIZA_ROBO"
RELOJ = lambda: datetime(2026, 11, 24, 15, tzinfo=timezone.utc)  # noqa: E731
EQUIPO = "pc-12345678-1234-4234-8234-123456789abc"


@pytest.fixture(autouse=True)
def equipo(tmp_path, monkeypatch):
    ruta = tmp_path / "local" / "escritor_operativo_id.txt"
    ruta.parent.mkdir(parents=True)
    ruta.write_text(EQUIPO, encoding="utf-8")
    monkeypatch.delenv("ATLAS_ESCRITOR_ID", raising=False)
    monkeypatch.setattr(escritor_operativo, "ruta_identidad_escritor", lambda: ruta)


class OCRCaido:
    def leer_texto(self, ruta):
        raise RuntimeError("worker OCR no disponible")


class OCR:
    def __init__(self, lineas):
        self.lineas = lineas

    def leer_texto(self, ruta):
        return self.lineas


SINTETICA = b"\xff\xd8\xff\xe0 poliza rc sintetica"


def adjuntar(raiz, contenido=SINTETICA, fabrica=OCRCaido, patente=RIGIDO, tipo=RC):  # noqa: F811
    return registrar_documento_vehiculo_desktop(raiz, empresa="MBT", referencia=patente, tipo=tipo, contenido=contenido,
                                                mime_type="application/pdf" if contenido.startswith(b"%PDF") else "image/jpeg",
                                                fabrica_ocr=fabrica, reloj=RELOJ)


def revisar(raiz, doc, propuesta, patente=RIGIDO):  # noqa: F811
    return revisar_documento_pendiente(raiz, empresa="MBT", referencia=patente, documento_id=doc["documento_id"],
                                       propuesta=propuesta, reloj=RELOJ)


def aceptar(raiz, doc, propuesta, patente=RIGIDO, **extra):  # noqa: F811
    vista = revisar(raiz, doc, propuesta, patente)
    datos = {"autor": "", "revisor_no_declarado": True, "confirmo_original": True, **extra}
    return resolver_documento_pendiente(raiz, empresa="MBT", referencia=patente, documento_id=doc["documento_id"],
                                        sha256=doc["sha256"], decision="CONFIRMAR", confirmacion_humana=True,
                                        propuesta=propuesta, clave_consecuencia=vista["consecuencia"]["clave"],
                                        reloj=RELOJ, **datos)


COMPLETA = {"tipo": RC, "patente": RIGIDO, "fecha_emision": "2026-11-01", "fecha_vencimiento": "2027-11-01",
            "coberturas": [RC, CARGA]}


def requisitos(raiz, patente=RIGIDO):  # noqa: F811
    vista = vista_expediente_desktop(raiz, empresa="MBT", entidad="VEHICULO", referencia=patente)
    return vista, {a["tipo"] for a in vista["ausentes"]}


def test_poliza_sin_ocr_se_completa_con_coberturas_confirmadas_y_acredita_ambos_requisitos(raiz):  # noqa: F811
    contenido = SINTETICA
    doc = adjuntar(raiz, contenido)
    assert doc["pendiente_revision"] and doc["tipo"] == "DOCUMENTO_VEHICULO_PENDIENTE"
    _, ausentes = requisitos(raiz)
    assert {RC, CARGA} <= ausentes

    vista = revisar(raiz, doc, None)
    assert "LECTURA_FALLIDA" in vista["motivos"] and vista["leido"]["coberturas"] == []
    assert vista["coberturas_confirmables"] == [RC, CARGA, ROBO] and "coberturas" in vista["confirmacion_original"]
    assert revisar(raiz, doc, {**COMPLETA, "coberturas": []})["consecuencia"]["motivo"] == "COBERTURAS_SIN_EVIDENCIA"
    previa = revisar(raiz, doc, COMPLETA)
    assert previa["puede_confirmar"] and previa["consecuencia"]["accion"] == "ACTIVAR"

    aceptado = aceptar(raiz, doc, COMPLETA)
    rh = aceptado["revision_humana"]
    assert aceptado["tipo"] == RC and not aceptado["pendiente_revision"] and aceptado["confirmado_por_humano"]
    assert rh["coberturas"] == [RC, CARGA] and rh["coberturas_ocr"] == []
    assert rh["procedencia_coberturas"] == {RC: "HUMANO", CARGA: "HUMANO"}
    assert "coberturas" in rh["datos_completados"] and rh["confirmo_original"] is True
    assert rh["persona"] == "NO_DECLARADA" and rh["equipo"]["id"] == EQUIPO
    evento = [e for e in leer_expediente(raiz, empresa="MBT")["historial"] if e["operacion"] == "DOCUMENTO_REVISION_CONFIRMADA"][-1]
    assert evento["coberturas"] == [RC, CARGA] and evento["procedencia_coberturas"] == {RC: "HUMANO", CARGA: "HUMANO"}
    # La OCR fallida se conserva tal cual: lo extraído y lo confirmado quedan separados.
    assert aceptado["extraccion_automatica"]["campos"]["coberturas"]["motivo"] == "ERROR_OCR"

    vista, ausentes = requisitos(raiz)
    assert not {RC, CARGA} & ausentes
    poliza = next(d for d in vista["documentos"] if d["documento_id"] == doc["documento_id"])
    assert poliza["tipos_cubiertos"] == [RC, CARGA] and poliza["procedencia_coberturas"] == {RC: "HUMANO", CARGA: "HUMANO"}
    # Un solo original custodiado, íntegro, sin copias por cobertura.
    assert len([d for d in vista["documentos"] if d.get("sha256") == doc["sha256"]]) == 1
    carpeta = ruta_almacen_expediente(raiz, "MBT").parent
    assert len(list((carpeta / "archivos" / "expediente").rglob("*.*"))) == 1
    assert hashlib.sha256((carpeta / doc["archivo"]).read_bytes()).hexdigest() == hashlib.sha256(contenido).hexdigest()
    assert {o["estado"] for o in verificar_originales(raiz, empresa="MBT")} == {"INTEGRO"}


def test_agregar_coberturas_sin_revisor_exige_confirmar_el_original(raiz):  # noqa: F811
    doc = adjuntar(raiz)
    antes = ruta_almacen_expediente(raiz, "MBT").read_bytes()
    with pytest.raises(ErrorExpedienteDigital, match="coberturas"):
        aceptar(raiz, doc, COMPLETA, confirmo_original=False)
    assert ruta_almacen_expediente(raiz, "MBT").read_bytes() == antes
    # Con revisor declarado vale su nombre (contrato anterior), igual queda la procedencia humana.
    aceptado = aceptar(raiz, doc, COMPLETA, autor="Javier", revisor_no_declarado=False, confirmo_original=False)
    assert aceptado["revision_humana"]["autor"] == "Javier"
    assert aceptado["revision_humana"]["procedencia_coberturas"] == {RC: "HUMANO", CARGA: "HUMANO"}


LEIDA_RC = ["POLIZA DE RESPONSABILIDAD CIVIL", "PATENTE " + RIGIDO, "VENCIMIENTO: 30/09/2027", "COBERTURA: RESPONSABILIDAD CIVIL"]


def test_lo_leido_por_ocr_queda_fijo_y_lo_agregado_se_distingue(raiz):  # noqa: F811
    # Lee tipo, patente y cobertura pero no el vencimiento: queda pendiente para la persona.
    doc = adjuntar(raiz, b"\xff\xd8\xff\xe0 rc leida", fabrica=lambda: OCR([x for x in LEIDA_RC if "VENCIMIENTO" not in x]))
    assert doc["tipo"] == RC and doc["pendiente_revision"]
    vista = revisar(raiz, doc, None)
    assert vista["leido"]["coberturas"] == [RC] and vista["motivos"] == ["VENCIMIENTO_NO_LEIDO"]
    fechas = {"fecha_vencimiento": "2027-09-30"}
    consecuencia = revisar(raiz, doc, {**fechas, "coberturas": [CARGA]})["consecuencia"]
    assert (consecuencia["accion"], consecuencia["motivo"], consecuencia["campo"]) == ("BLOQUEADO", "CONTRADICE_LECTURA", "coberturas")
    aceptado = aceptar(raiz, doc, {**fechas, "coberturas": [RC, CARGA]})
    assert aceptado["revision_humana"]["procedencia_coberturas"] == {RC: "OCR", CARGA: "HUMANO"}
    assert aceptado["revision_humana"]["coberturas_ocr"] == [RC]
    poliza = next(d for d in requisitos(raiz)[0]["documentos"] if d["documento_id"] == doc["documento_id"])
    assert poliza["procedencia_coberturas"] == {RC: "OCR", CARGA: "HUMANO"}


@pytest.mark.parametrize("propuesta,motivo", [
    ({**COMPLETA, "coberturas": ["SOAP"]}, "COBERTURA_NO_ADMITIDA"),
    ({**COMPLETA, "coberturas": "POLIZA_RESPONSABILIDAD_CIVIL"}, "COBERTURA_NO_ADMITIDA"),
    ({**COMPLETA, "coberturas": [CARGA]}, "COBERTURA_DEL_TIPO_AUSENTE"),
    ({**COMPLETA, "tipo": "SOAP"}, "COBERTURAS_NO_APLICAN"),
])
def test_coberturas_indicadas_se_validan(raiz, propuesta, motivo):  # noqa: F811
    doc = adjuntar(raiz)
    consecuencia = revisar(raiz, doc, propuesta)["consecuencia"]
    assert (consecuencia["accion"], consecuencia["motivo"]) == ("BLOQUEADO", motivo)


def test_seguro_de_carga_aparte_se_conserva_y_ambos_acreditan(raiz):  # noqa: F811
    aparte = registrar_documento(raiz, empresa="MBT", entidad="VEHICULO", referencia=RIGIDO, tipo=CARGA, actor="DESKTOP",
                                 fecha_vencimiento="2027-11-23", contenido=b"%PDF-1.4 seguro carga aparte",
                                 mime_type="application/pdf", reloj=RELOJ)
    doc = adjuntar(raiz)
    previa = revisar(raiz, doc, COMPLETA)
    assert previa["consecuencia"]["accion"] == "ACTIVAR" and previa["consecuencia"]["documentos"] == []
    aceptar(raiz, doc, COMPLETA)
    estados = {d["documento_id"]: d["estado"] for d in leer_expediente(raiz, empresa="MBT")["documentos"]}
    assert estados == {aparte["documento_id"]: "ACTIVO", doc["documento_id"]: "ACTIVO"}
    assert not {RC, CARGA} & requisitos(raiz)[1]


def test_renovacion_que_pierde_una_cobertura_confirmada_queda_pendiente(raiz):  # noqa: F811
    doc = adjuntar(raiz)
    aceptar(raiz, doc, COMPLETA)
    nueva = adjuntar(raiz, b"\xff\xd8\xff\xe0 renovacion solo rc",
                     fabrica=lambda: OCR([x.replace("30/09/2027", "30/12/2028") for x in LEIDA_RC]))
    assert nueva["pendiente_revision"] and nueva["posible_reemplazo"]["motivo"] == "COBERTURAS_REDUCIDAS"
    # Si la persona confirma que la renovación también cubre la carga, reemplaza sin perder cobertura.
    reemplazo = aceptar(raiz, nueva, {"coberturas": [RC, CARGA]})
    assert reemplazo["revision_humana"]["decision"] == "REEMPLAZAR"
    assert reemplazo["revision_humana"]["reemplaza"] == [doc["documento_id"]]


def test_regla_pura_seguro_de_carga_aparte_no_se_relaciona():
    nuevo = {"tipo": RC, "tipo_informado": RC, "vencimiento": "2027-11-01", "coberturas": [RC, CARGA]}
    aparte = {"documento_id": "c", "tipo": CARGA, "vencimiento": "2027-01-01", "coberturas": [], "origenes": ["c"]}
    poliza = {"documento_id": "p", "tipo": RC, "vencimiento": "2027-01-01", "coberturas": [RC, CARGA], "origenes": ["p"]}
    assert not relacionado(nuevo, aparte) and relacionado(nuevo, poliza)
    hoy = RELOJ().date()
    assert decidir_renovacion(nuevo, [aparte], hoy)["accion"] == "ACTIVAR"
    assert decidir_renovacion(nuevo, [aparte, poliza], hoy) == {"accion": "REEMPLAZAR", "motivo": "", "documentos": ["p"], "fecha": ""}
    solo_rc = {**nuevo, "coberturas": [RC]}
    assert decidir_renovacion(solo_rc, [poliza], hoy)["motivo"] == "COBERTURAS_REDUCIDAS"
