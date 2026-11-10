"""Tipo documental vehicular por evidencia OCR (P2).

El tipo seleccionado al cargar se conserva como `tipo_informado`; el tipo
operativo sólo lo fija un título o una cobertura leída en el mismo original.
Sin evidencia, o con títulos incompatibles, el documento queda pendiente y no
activa vigencias. Sólo datos sintéticos en tmp_path.
"""
from __future__ import annotations

import json

import pytest

from atlas_core import extraccion_vencimientos_vehiculos as modulo
from atlas_core.expediente_digital import consultar_expediente
from atlas_core.extraccion_vencimientos_vehiculos import extraer_vencimientos_vehiculos
from atlas_core.fichas_choferes import ruta_almacen
from atlas_core.identificacion_patentes import identificar_patentes_documentos
from atlas_core.lectura_documento_vehiculo import TIPO_PENDIENTE, identificar_tipo_documental
from tests.test_extraccion_vencimientos_vehiculos import PERMISO_REAL, REVISION_REAL, SOAP_REAL
from tests.test_identificacion_patentes import OCRFalso, TRACTO, _recibir, _ubicar, raiz  # noqa: F401

GASES_REAL = [
    "PLANTA REVISORA SINTETICA", "CERTIFICADO DE EMISION DE CONTAMINANTES", "PPU BPHR67", "NORMA EMISION: EURO V",
    "RESULTADO: APROBADO", "VALIDO HASTA: 25/03/2027",
]
POLIZA_RC_ROBO = [
    "COMPANIA DE SEGUROS SINTETICA", "POLIZA N° 7788", "PATENTE BPHR67", "VIGENCIA DESDE 01/10/2026", "VENCIMIENTO: 30/09/2027",
    "COBERTURAS: RESPONSABILIDAD CIVIL Y ROBO",
]
POLIZA_ROBO = ["POLIZA DE SEGURO CONTRA ROBO", "PATENTE BPHR67", "VENCIMIENTO: 30/09/2027"]
POLIZA_RC = ["POLIZA DE RESPONSABILIDAD CIVIL", "PATENTE BPHR67", "VENCIMIENTO: 30/09/2027"]


# ---------------------------------------------------------------- lectura pura


@pytest.mark.parametrize("lineas,tipo", [
    (SOAP_REAL, "SOAP"),  # título partido en dos líneas por RapidOCR
    (["SEGURO OBLIGATORIO DE ACCIDENTES PERSONALES", "HASTA 30/09/2027"], "SOAP"),
    (REVISION_REAL, "REVISION_TECNICA"),  # título compacto sin espacios
    (PERMISO_REAL, "PERMISO_CIRCULACION"),
    (GASES_REAL, "CERTIFICADO_EMISION_GASES"),
    (POLIZA_RC, "POLIZA_RESPONSABILIDAD_CIVIL"),
    (POLIZA_ROBO, "POLIZA_ROBO"),
])
def test_seis_tipos_se_reconocen_por_evidencia_del_original(lineas, tipo):
    resultado = identificar_tipo_documental(lineas)
    assert (resultado["valor"], resultado["estado"], resultado["motivo"]) == (tipo, "EXTRAIDO", "")
    assert resultado["candidatos"] == [tipo] and resultado["evidencia"]


def test_poliza_con_responsabilidad_civil_y_robo_es_un_unico_documento():
    resultado = identificar_tipo_documental(POLIZA_RC_ROBO)
    assert resultado["valor"] == "POLIZA_RESPONSABILIDAD_CIVIL" and resultado["estado"] == "EXTRAIDO"
    assert resultado["candidatos"] == ["POLIZA_RESPONSABILIDAD_CIVIL", "POLIZA_ROBO"]


@pytest.mark.parametrize("lineas,motivo", [
    (["PATENTE BPHR67", "VENCE: 30/09/2027"], "NO_ENCONTRADO"),
    (["REVISION TECNICA", "VALIDA HASTA: 25/03/2027"], "NO_ENCONTRADO"),       # mención sin título de certificado
    (["POLIZA N° 7788", "VIGENCIA HASTA 30/09/2027"], "NO_ENCONTRADO"),        # póliza sin cobertura legible
    (["SEGURO OBLIGATORIO ACCIDENTES", "HASTA 30/09/2027"], "NO_ENCONTRADO"),  # título SOAP incompleto
    (["PERMISO DE CIRCULACION", "SOAP", "VENCE: 30/09/2027"], "VARIOS_TIPOS"),
    (["CERTIFICADO DE REVISION TECNICA", "CERTIFICADO DE EMISION DE GASES"], "VARIOS_TIPOS"),
    (["SOAP", "POLIZA DE RESPONSABILIDAD CIVIL"], "VARIOS_TIPOS"),
])
def test_sin_evidencia_o_con_contradicciones_queda_pendiente(lineas, motivo):
    resultado = identificar_tipo_documental(lineas)
    assert (resultado["valor"], resultado["estado"], resultado["motivo"]) == (None, "PENDIENTE_REVISION", motivo)


# ---------------------------------------------------------------- ciclo PULL (Mobile)


def _ciclo(raiz, textos):
    identificar_patentes_documentos(raiz, comprobar=lambda: None, fabrica_ocr=lambda: OCRFalso(textos))
    return extraer_vencimientos_vehiculos(raiz, comprobar=lambda: None, fabrica_ocr=lambda: OCRFalso(textos))


def _texto_con_patente(lineas):
    return ["PATENTE " + TRACTO, *lineas]


@pytest.mark.parametrize("lineas", [
    ["PATENTE " + TRACTO, "RIGE DESDE", "HASTA", "01/10/2026", "30/09/2027"],     # sin título
    ["PATENTE " + TRACTO, "SOAP", "PERMISO DE CIRCULACION", "VENCE: 30/09/2027"],  # títulos incompatibles
])
def test_tipo_seleccionado_no_basta_para_activar_vigencia(raiz, lineas):
    documento_id, contenido = _recibir(raiz, "sin-evidencia", tipo="SOAP")
    resumen = _ciclo(raiz, {contenido: lineas})
    patente, documento = _ubicar(raiz, documento_id)
    assert patente == TRACTO and resumen["activados"] == []
    assert documento["tipo"] == TIPO_PENDIENTE and documento["tipo_informado"] == "SOAP"
    assert "vencimiento" not in documento and documento["estado_revision"] == "PENDIENTE_EXTRACCION"
    extraccion = documento["extraccion_automatica"]
    assert extraccion["estado"] == "SIN_DATOS" and extraccion["regla"] == TIPO_PENDIENTE
    assert extraccion["campos"]["vencimiento"]["motivo"] == "TIPO_PENDIENTE"
    assert extraccion["campos"]["tipo_documental"]["estado"] == "PENDIENTE_REVISION"


def test_tipo_leido_prevalece_sobre_el_informado_y_conserva_ambos(raiz):
    documento_id, contenido = _recibir(raiz, "rt-como-soap", tipo="SOAP")
    resumen = _ciclo(raiz, {contenido: REVISION_REAL})
    _, documento = _ubicar(raiz, documento_id)
    assert documento["tipo"] == "REVISION_TECNICA" and documento["tipo_informado"] == "SOAP"
    assert documento["vencimiento"] == "2027-03-25"  # regla de la revisión técnica, no la del SOAP
    assert [(a["tipo"], a["vencimiento"]) for a in resumen["activados"]] == [("REVISION_TECNICA", "2027-03-25")]
    assert [e["tipo"] for e in resumen["extraidos"]] == ["REVISION_TECNICA"]


def test_relectura_conserva_el_tipo_informado_original(raiz, monkeypatch):
    documento_id, contenido = _recibir(raiz, "relectura", tipo="PERMISO_CIRCULACION")
    _ciclo(raiz, {contenido: _texto_con_patente(["VENCE: 30/09/2027"])})
    assert _ubicar(raiz, documento_id)[1]["tipo"] == TIPO_PENDIENTE
    monkeypatch.setattr(modulo, "VERSION_EXTRACCION", modulo.VERSION_EXTRACCION + 1)
    extraer_vencimientos_vehiculos(raiz, comprobar=lambda: None, fabrica_ocr=lambda: OCRFalso({contenido: PERMISO_REAL}))
    _, documento = _ubicar(raiz, documento_id)
    assert documento["tipo"] == "PERMISO_CIRCULACION" and documento["tipo_informado"] == "PERMISO_CIRCULACION"
    assert documento["vencimiento"] == "2027-09-30"
    assert documento["extracciones_anteriores"][0]["campos"]["tipo_documental"]["motivo"] == "NO_ENCONTRADO"


def _lectura_previa_sin_tipo(raiz, documento_id, contenido):
    """Lectura v2 (antes de exigir evidencia de tipo): vencimiento EXTRAIDO por el tipo seleccionado."""
    ruta = ruta_almacen(raiz, "MBT")
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    for vehiculo in datos["vehiculos"]:
        for d in vehiculo["documentos"]:
            if d["documento_id"] == documento_id:
                d["extraccion_automatica"] = {
                    "version": 2, "fecha": "2026-11-02T13:05:00Z", "actor": "MOTOR_OCR", "procedencia": "AUTOMATICA_OCR",
                    "motor_ocr": "OCRFalso", "confirmado_por_humano": False, "estado": "COMPLETA", "regla": "SOAP",
                    "archivos": [{"archivo": d["archivo"], "sha256": d["sha256"]}],
                    "campos": {"vencimiento": {"valor": "2027-09-30", "estado": "EXTRAIDO", "motivo": "",
                                               "evidencia": [{"rotulo": "HASTA", "texto": "HASTA / 30/09/2027"}]}}}
    ruta.write_text(json.dumps(datos), encoding="utf-8")


def test_lectura_anterior_sin_tipo_no_se_activa_y_se_relee_una_vez(raiz):
    documento_id, contenido = _recibir(raiz, "legado", tipo="SOAP")
    identificar_patentes_documentos(raiz, comprobar=lambda: None,
                                    fabrica_ocr=lambda: OCRFalso({contenido: ["PATENTE " + TRACTO]}))
    _lectura_previa_sin_tipo(raiz, documento_id, contenido)
    assert modulo.activar_vencimientos_extraidos(raiz, comprobar=lambda: None, empresa="MBT")["activados"] == []
    # Se relee con la versión actual: sin título sigue pendiente, con título se activa.
    ocr = OCRFalso({contenido: ["PATENTE " + TRACTO, "RIGE DESDE", "HASTA", "01/10/2026", "30/09/2027"]})
    resumen = extraer_vencimientos_vehiculos(raiz, comprobar=lambda: None, fabrica_ocr=lambda: ocr)
    _, documento = _ubicar(raiz, documento_id)
    assert len(ocr.leidas) == 1 and resumen["activados"] == [] and documento["tipo"] == TIPO_PENDIENTE
    assert documento["extracciones_anteriores"][0]["version"] == 2
    segundo = OCRFalso({contenido: SOAP_REAL})
    extraer_vencimientos_vehiculos(raiz, comprobar=lambda: None, fabrica_ocr=lambda: segundo)
    assert segundo.leidas == []  # una sola relectura por versión


def test_activacion_exige_que_la_evidencia_coincida_con_el_tipo_operativo(raiz):
    documento_id, contenido = _recibir(raiz, "manipulado", tipo="SOAP")
    _ciclo(raiz, {contenido: _texto_con_patente(["RIGE DESDE", "HASTA", "01/10/2026", "30/09/2027"])})
    ruta = ruta_almacen(raiz, "MBT")
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    for vehiculo in datos["vehiculos"]:
        for d in vehiculo["documentos"]:
            if d["documento_id"] == documento_id:
                d["tipo"] = "SOAP"  # tipo restituido sin evidencia
                campos = d["extraccion_automatica"]["campos"]
                campos["vencimiento"] = {"valor": "2027-09-30", "estado": "EXTRAIDO", "motivo": "",
                                         "evidencia": [{"rotulo": "HASTA", "texto": "HASTA / 30/09/2027"}]}
                d["extraccion_automatica"]["estado"] = "COMPLETA"
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    assert modulo.activar_vencimientos_extraidos(raiz, comprobar=lambda: None, empresa="MBT")["activados"] == []


def test_pdf_con_tipo_pendiente_se_reidentifica_por_patente(raiz):
    from atlas_core import identificacion_patentes
    documento_id, _ = _recibir(raiz, "pdf-pendiente", tipo="SOAP", patente="",
                               contenido=b"%PDF-1.4 sintetico", mime="application/pdf")
    _, documento = _ubicar(raiz, documento_id)
    documento = {**documento, "tipo": TIPO_PENDIENTE, "tipo_informado": "SOAP",
                 "identificacion_patente": {"version": 1, "motivo": "FORMATO_SIN_OCR"}}
    assert identificacion_patentes._por_identificar(documento)


# ---------------------------------------------------------------- expediente (Desktop)


def test_expediente_desktop_sin_evidencia_queda_pendiente_y_no_acredita_requisito(tmp_path, monkeypatch):
    from tests.test_expediente_desktop_ocr import PATENTE, _catalogos, ejecutar_alta
    _catalogos(tmp_path / "catalogos_privados", "ANA", vehiculos=(PATENTE, "ZZ1234"))
    archivo = tmp_path / "entrada.jpg"
    archivo.write_bytes(b"\xff\xd8\xff\xe0sin-titulo")
    doc, _ = ejecutar_alta(tmp_path, archivo, monkeypatch,
                           ["PATENTE " + PATENTE, "VIGENCIA DESDE 01/10/2026 HASTA 30/09/2027"], tipo="SOAP")
    assert doc["tipo"] == TIPO_PENDIENTE and doc["tipo_informado"] == "SOAP" and doc["pendiente_revision"]
    assert doc["extraccion_automatica"]["campos"]["vencimiento"]["motivo"] == "TIPO_PENDIENTE"
    consulta = consultar_expediente(tmp_path, empresa="MBT", entidad="VEHICULO", referencia=PATENTE)
    vista = next(d for d in consulta["documentos"] if d["documento_id"] == doc["documento_id"])
    assert vista["estado_vencimiento"] == "PENDIENTE_REVISION"
    soap = [a for a in consulta["ausentes"] if a["tipo"] == "SOAP"]
    assert soap == [] or soap[0]["pendiente_revision"] is True
    assert not any(a["tipo"] == TIPO_PENDIENTE for a in consulta["ausentes"])


def test_expediente_desktop_poliza_doble_es_un_original_que_cubre_ambos(tmp_path, monkeypatch):
    from tests.test_expediente_desktop_ocr import PATENTE, _catalogos, ejecutar_alta
    _catalogos(tmp_path / "catalogos_privados", "ANA", vehiculos=(PATENTE, "ZZ1234"))
    archivo = tmp_path / "poliza.jpg"
    archivo.write_bytes(b"\xff\xd8\xff\xe0poliza-doble")
    lineas = [x.replace("BPHR67", PATENTE) for x in POLIZA_RC_ROBO]
    doc, _ = ejecutar_alta(tmp_path, archivo, monkeypatch, lineas, tipo="POLIZA_ROBO")
    assert doc["tipo"] == "POLIZA_RESPONSABILIDAD_CIVIL" and doc["tipo_informado"] == "POLIZA_ROBO"
    assert not doc["pendiente_revision"] and doc["fecha_vencimiento"] == "2027-09-30"
    consulta = consultar_expediente(tmp_path, empresa="MBT", entidad="VEHICULO", referencia=PATENTE)
    polizas = [d for d in consulta["documentos"] if d["tipo"] in ("POLIZA_RESPONSABILIDAD_CIVIL", "POLIZA_ROBO")]
    assert [d["documento_id"] for d in polizas] == [doc["documento_id"]]
    assert polizas[0]["tipos_cubiertos"] == ["POLIZA_RESPONSABILIDAD_CIVIL", "POLIZA_ROBO"]
    assert not {"POLIZA_RESPONSABILIDAD_CIVIL", "POLIZA_ROBO"} & {a["tipo"] for a in consulta["ausentes"]}


# ------------------------------------------- tipo leído distinto del informado


REVISION_OTRA = [x.replace("25MARZO2027", "25ABRIL2027") for x in REVISION_REAL]


def _rt_vigente(raiz):
    rt_id, rt = _recibir(raiz, "rt-vigente", tipo="REVISION_TECNICA")
    _ciclo(raiz, {rt: REVISION_REAL})
    assert _ubicar(raiz, rt_id)[1]["vencimiento"] == "2027-03-25"
    return rt_id


def test_tipo_leido_con_vigente_del_mismo_tipo_queda_como_posible_reemplazo(raiz):
    from atlas_core.fichas_choferes import leer_almacen
    rt_id = _rt_vigente(raiz)
    antes_rt = _ubicar(raiz, rt_id)[1]
    nuevo_id, nuevo = _recibir(raiz, "rt-como-soap-2", tipo="SOAP")
    resumen = _ciclo(raiz, {nuevo: REVISION_OTRA})
    _, documento = _ubicar(raiz, nuevo_id)
    assert resumen["activados"] == [] and "vencimiento" not in documento
    assert documento["estado_revision"] == "PENDIENTE_EXTRACCION"
    assert (documento["tipo"], documento["tipo_informado"]) == ("REVISION_TECNICA", "SOAP")
    assert documento["extraccion_automatica"]["campos"]["vencimiento"]["valor"] == "2027-04-25"
    assert documento["posible_reemplazo"]["documentos"] == [rt_id]
    assert _ubicar(raiz, rt_id)[1] == antes_rt  # el vigente se conserva intacto
    ficha = next(v for v in leer_almacen(raiz, empresa="MBT")["vehiculos"] if v["patente"] == TRACTO)
    assert [h["vigentes"] for h in ficha["historial"] if h["accion"] == "DOCUMENTO_VEHICULO_POSIBLE_REEMPLAZO"] == [[rt_id]]
    revision = leer_almacen(raiz, empresa="MBT")["revision"]
    extraer_vencimientos_vehiculos(raiz, comprobar=lambda: None, fabrica_ocr=lambda: OCRFalso({}))
    assert leer_almacen(raiz, empresa="MBT")["revision"] == revision  # sin escrituras repetidas


def test_tipo_leido_sin_vigente_del_mismo_tipo_se_activa(raiz):
    from tests.test_extraccion_vencimientos_vehiculos import _editar_documento
    rt_id = _rt_vigente(raiz)
    _editar_documento(raiz, rt_id, vencimiento="2020-03-25")  # vencido
    nuevo_id, nuevo = _recibir(raiz, "rt-como-soap-3", tipo="SOAP")
    resumen = _ciclo(raiz, {nuevo: REVISION_OTRA})
    _, documento = _ubicar(raiz, nuevo_id)
    assert [a["documento_id"] for a in resumen["activados"]] == [nuevo_id]
    assert documento["vencimiento"] == "2027-04-25" and "posible_reemplazo" not in documento


def test_renovacion_con_el_mismo_tipo_informado_no_cambia(raiz):
    rt_id = _rt_vigente(raiz)
    nuevo_id, nuevo = _recibir(raiz, "rt-renovacion", tipo="REVISION_TECNICA")
    resumen = _ciclo(raiz, {nuevo: REVISION_OTRA})
    assert [a["documento_id"] for a in resumen["activados"]] == [nuevo_id]
    assert "posible_reemplazo" not in _ubicar(raiz, nuevo_id)[1]


def test_consulta_del_expediente_expone_tipo_informado_y_posible_reemplazo(raiz):
    rt_id = _rt_vigente(raiz)
    nuevo_id, nuevo = _recibir(raiz, "rt-como-soap-4", tipo="SOAP")
    _ciclo(raiz, {nuevo: REVISION_OTRA})
    from atlas_core.expediente_digital import _documentos_de_fichas
    vistas = {d["documento_id"]: d for d in _documentos_de_fichas(raiz, "MBT", raiz / "catalogos_privados")}
    assert vistas[nuevo_id]["tipo_informado"] == "SOAP" and vistas[nuevo_id]["pendiente_revision"]
    assert vistas[nuevo_id]["posible_reemplazo"]["documentos"] == [rt_id]
    assert "tipo_informado" not in vistas[rt_id] or vistas[rt_id]["tipo_informado"] == "REVISION_TECNICA"


def _alta(tmp_path, monkeypatch, nombre, lineas, tipo):
    from tests.test_expediente_desktop_ocr import PATENTE, ejecutar_alta
    archivo = tmp_path / (nombre + ".jpg")
    archivo.write_bytes(b"\xff\xd8\xff\xe0" + nombre.encode())
    return ejecutar_alta(tmp_path, archivo, monkeypatch, [x.replace("BPHR67", PATENTE) for x in lineas], tipo=tipo)[0]


@pytest.fixture
def expediente(tmp_path):
    from tests.test_expediente_desktop_ocr import PATENTE, _catalogos
    _catalogos(tmp_path / "catalogos_privados", "ANA", vehiculos=(PATENTE, "ZZ1234"))
    return tmp_path


def test_expediente_tipo_leido_con_vigente_conserva_el_anterior(expediente, monkeypatch):
    from atlas_core.expediente_digital import leer_expediente
    soap = _alta(expediente, monkeypatch, "soap", ["SOAP", "PATENTE BPHR67", "VENCIMIENTO: 30/09/2027"], "SOAP")
    assert not soap["pendiente_revision"]
    nuevo = _alta(expediente, monkeypatch, "soap-como-permiso",
                  ["SOAP", "PATENTE BPHR67", "VENCIMIENTO: 30/10/2027"], "PERMISO_CIRCULACION")
    assert (nuevo["tipo"], nuevo["tipo_informado"], nuevo["pendiente_revision"]) == ("SOAP", "PERMISO_CIRCULACION", True)
    assert nuevo["posible_reemplazo"]["documentos"] == [soap["documento_id"]]
    estados = {d["documento_id"]: d["estado"] for d in leer_expediente(expediente, empresa="MBT")["documentos"]}
    assert estados == {soap["documento_id"]: "ACTIVO", nuevo["documento_id"]: "ACTIVO"}


def test_expediente_poliza_vigente_por_cobertura_bloquea_activacion(expediente, monkeypatch):
    poliza = _alta(expediente, monkeypatch, "poliza", POLIZA_RC_ROBO, "POLIZA_RESPONSABILIDAD_CIVIL")
    assert not poliza["pendiente_revision"]
    robo = _alta(expediente, monkeypatch, "robo-como-soap",
                 ["POLIZA DE SEGURO CONTRA ROBO", "PATENTE BPHR67", "VENCIMIENTO: 30/09/2028", "COBERTURA: ROBO"], "SOAP")
    assert (robo["tipo"], robo["pendiente_revision"]) == ("POLIZA_ROBO", True)
    assert robo["posible_reemplazo"]["documentos"] == [poliza["documento_id"]]


def test_expediente_tipo_leido_sin_vigente_se_activa(expediente, monkeypatch):
    nuevo = _alta(expediente, monkeypatch, "solo", ["SOAP", "PATENTE BPHR67", "VENCIMIENTO: 30/09/2027"],
                  "PERMISO_CIRCULACION")
    assert (nuevo["tipo"], nuevo["pendiente_revision"], nuevo["fecha_vencimiento"]) == ("SOAP", False, "2027-09-30")
    assert "posible_reemplazo" not in nuevo
