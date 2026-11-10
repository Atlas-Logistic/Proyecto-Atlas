"""Extracción automática del vencimiento de documentos de vehículo (`extraccion_vencimientos_vehiculos`).

Sólo datos sintéticos en tmp_path; el OCR se simula con un proveedor que
devuelve las líneas de cada archivo (misma interfaz `leer_texto`). Los textos
"reales" reproducen el orden de lectura de RapidOCR sobre un SOAP, una revisión
técnica y un permiso de circulación reales, con los datos personales cambiados.
"""
from __future__ import annotations

import copy
import hashlib

import pytest

from atlas_core import extraccion_vencimientos_vehiculos as modulo
from atlas_core.extraccion_vencimientos_vehiculos import extraer_vencimiento, extraer_vencimientos_vehiculos
from atlas_core.fichas_choferes import leer_almacen, ruta_almacen
from atlas_core.identificacion_patentes import identificar_patentes_documentos
from tests.test_identificacion_patentes import JPEG, OCRFalso, TRACTO, _recibir, _ubicar, raiz  # noqa: F401

sha = lambda b: hashlib.sha256(b).hexdigest()

SOAP_REAL = [
    "ORIGINAL ASEGURADO", "POLIZA N°11111111", "HDI", "INSCRIPCION R.V.M", "CERTIFICADO SEGURO OBLIGATORIO ACCIDENTES",
    "BPHR67", "PERSONALES ELECTRONICO LEY 18.490", "TIPO DEVEHICULO", "TRACTOCAMiON Transporte de Carga)", "MARCA",
    "MACK", "PROPIETARIO", "PROPIETARIO SINTETICO", "MODELO", "ANO", "CH613", "RUT", "1998", "RIGE DESDE", "HASTA",
    "12345678-5", "01/10/2026", "NUMERO DEMOTOR", "30/09/2027", "PRIMA", "E74277R1937", "$25.690.-",
    "quedado estampada la denuncia en una unidad de Carabinerosdonde se identifique la fechahora",
]
REVISION_REAL = [
    "REVISIONESTECNICASUVTSA", "FECHA", "CALETERA GRAL VELASQUEZ7319 CERRILLOS", "25 SEPTIEMBRE2026", "PLACA PATENTE",
    "PLANTAA-1303", "BPHR67", "CERTIFICADODEREVISIONTECNICAN°A1303000000586742", "PROPIETARIO SINTETICO",
    "RUT 12345678-5", "EMISION DE", "1-Sistema de Direccion", "A", "CONTAMINANTE", "NORMA EMISION:SELLO VERDE",
    "ANO VEHiCULO", "1998", "REVISION TECNICA VALIDA HASTA:", "RESULTADO:", "FIRMAELECTRONICAAVANZADA", "ESTECNICA",
    "FIRMANTE SINTETICO", "25MARZO2027", "APROBADO", "25/09/202612:09:11", "OBSERVACIONES:",
]
PERMISO_REAL = [
    "COMPROBANTEDE PAGO DE PERMISO DECIRCULACION", "No", "055531", "MUNICIPALIDAD", "LAMPA", "FECHA", "PLACAGNICA",
    "05/10/2026", "BP-HR67-6", "R.U.T.", "012345678-5", "TASACION", "PERMISO PACADO", "VENCE:30/09/2027", "TOTAL",
    "PACO EN CUOTAS", "53,737", "107,474", "CUOTA2", "TOTALA PAGAR", "PERMISO DE CIRCULACION",
    "VENCIMIENTO:30/09/2027", "PERIODO", "ANO 2026", "PERMISO DE CIRCULACION", "VENCIMIENTO:30/09/2027",
]


# ---------------------------------------------------------------- lectura pura


@pytest.mark.parametrize("tipo,lineas,valor,excluidas", [
    ("SOAP", SOAP_REAL, "2027-09-30", {"2026-10-01"}),
    ("REVISION_TECNICA", REVISION_REAL, "2027-03-25", {"2026-09-25"}),
    ("PERMISO_CIRCULACION", PERMISO_REAL, "2027-09-30", {"2026-10-05"}),
])
def test_documentos_reales_distinguen_vencimiento_de_emision_pago_e_inspeccion(tipo, lineas, valor, excluidas):
    campo = extraer_vencimiento(tipo, lineas)
    assert (campo["valor"], campo["estado"], campo["motivo"]) == (valor, "EXTRAIDO", "")
    assert campo["evidencia"]
    assert {f["valor"] for f in campo["otras_fechas"]} == excluidas
    assert campo["referencias"] == sorted(excluidas)


def test_revision_tecnica_excluye_la_marca_horaria_de_emision():
    campo = extraer_vencimiento("REVISION_TECNICA", REVISION_REAL)
    assert {"valor": "2026-09-25", "rol": "MARCA_HORARIA", "texto": "25/09/202612:09:11"} in campo["otras_fechas"]
    assert campo["evidencia"] == [{"rotulo": "VALIDA HASTA", "texto": "REVISION TECNICA VALIDA HASTA: / 25MARZO2027"}]


def test_soap_toma_el_par_desde_hasta_en_orden():
    campo = extraer_vencimiento("SOAP", SOAP_REAL)
    assert campo["evidencia"] == [{"rotulo": "HASTA", "texto": "HASTA / 30/09/2027", "par_desde": "2026-10-01"}]


@pytest.mark.parametrize("tipo,lineas,valor", [
    ("SOAP", ["VIGENCIA DESDE 01/10/2026 HASTA 30/09/2027", "FECHA EMISION 28/09/2026"], "2027-09-30"),
    ("SOAP", ["RIGE DESDE: 1 DE OCTUBRE DE 2026 HASTA: 30 DE SEPTIEMBRE DE 2027"], "2027-09-30"),
    ("REVISION_TECNICA", ["FECHA REVISION 10-04-2026", "PROXIMA REVISION 10-10-2026"], "2026-10-10"),
    ("PERMISO_CIRCULACION", ["FECHA DE PAGO 31.03.2026", "FECHA DE VENCIMIENTO 31.03.2027",
                             "VENCIMIENTO CUOTA 2 31/08/2026"], "2027-03-31"),
])
def test_rotulo_en_la_misma_linea_y_formatos(tipo, lineas, valor):
    assert extraer_vencimiento(tipo, lineas)["valor"] == valor


def test_vencimiento_de_cuota_no_es_vencimiento_del_permiso():
    campo = extraer_vencimiento("PERMISO_CIRCULACION", ["VENCIMIENTO CUOTA 2: 31/08/2026"])
    assert campo["motivo"] == "NO_ENCONTRADO"
    assert campo["otras_fechas"][0]["rol"] == "PLAZO_CUOTA"


@pytest.mark.parametrize("tipo,lineas,motivo", [
    # Ambiguas
    ("PERMISO_CIRCULACION", ["VENCE: 30/09/2027", "VENCIMIENTO: 31/03/2027"], "VARIAS_FECHAS"),
    ("REVISION_TECNICA", ["VALIDA HASTA:", "25/03/2027", "25/04/2027"], "VARIAS_FECHAS"),
    ("SOAP", ["RIGE DESDE", "HASTA", "01/10/2026", "30/09/2027", "15/10/2027"], "VARIAS_FECHAS"),
    ("SOAP", ["RIGE DESDE", "HASTA", "30/09/2027"], "PAR_DESDE_HASTA_INCOMPLETO"),
    # Ilegibles
    ("PERMISO_CIRCULACION", ["VENCE: 30/09/27"], "ILEGIBLE"),
    ("PERMISO_CIRCULACION", ["VENCE: 31/02/2027"], "ILEGIBLE"),
    ("REVISION_TECNICA", ["VALIDA HASTA:", "APROBADO"], "ILEGIBLE"),
    ("SOAP", ["POLIZA 123", "PRIMA $25.690"], "NO_ENCONTRADO"),
    # Sin rótulo de vencimiento: una fecha suelta nunca se toma.
    ("SOAP", ["CERTIFICADO SOAP", "30/09/2027"], "NO_ENCONTRADO"),
    # Contradictorias
    ("SOAP", ["RIGE DESDE", "HASTA", "30/09/2027", "01/10/2026"], "FECHAS_CONTRADICTORIAS"),
    ("PERMISO_CIRCULACION", ["FECHA DE PAGO 05/10/2026", "VENCE: 30/09/2026"], "FECHAS_CONTRADICTORIAS"),
    ("REVISION_TECNICA", ["FECHA", "25 SEPTIEMBRE 2026", "VALIDA HASTA: 25/03/2030"], "PLAZO_IMPROBABLE"),
])
def test_abstencion_ante_fechas_ambiguas_ilegibles_o_contradictorias(tipo, lineas, motivo):
    campo = extraer_vencimiento(tipo, lineas)
    assert (campo["valor"], campo["estado"], campo["motivo"]) == (None, "PENDIENTE_REVISION", motivo)


def test_hasta_sin_desde_solo_cuenta_en_soap():
    # En la revisión técnica "HASTA" suelto no es rótulo de vigencia.
    assert extraer_vencimiento("REVISION_TECNICA", ["HASTA 30/09/2027"])["motivo"] == "NO_ENCONTRADO"
    assert extraer_vencimiento("SOAP", ["HASTA 30/09/2027"])["valor"] == "2027-09-30"


# ---------------------------------------------------------------- ciclo PULL


def _extraer(raiz, ocr, comprobar=lambda: None):
    return extraer_vencimientos_vehiculos(raiz, comprobar=comprobar, fabrica_ocr=lambda: ocr)


def _documentos(raiz):
    """Tres documentos reales (anonimizados) ya asociados a TRACTO por patente."""
    textos, ids = {}, {}
    for origen, tipo, lineas in (("soap", "SOAP", SOAP_REAL), ("rt", "REVISION_TECNICA", REVISION_REAL),
                                 ("permiso", "PERMISO_CIRCULACION", PERMISO_REAL)):
        documento_id, contenido = _recibir(raiz, origen, tipo=tipo)
        textos[contenido], ids[tipo] = lineas, documento_id
    identificar_patentes_documentos(raiz, comprobar=lambda: None, fabrica_ocr=lambda: OCRFalso(textos))
    return textos, ids


VENCIMIENTOS_REALES = {"SOAP": "2027-09-30", "REVISION_TECNICA": "2027-03-25", "PERMISO_CIRCULACION": "2027-09-30"}


def test_extrae_y_registra_vencimiento_automatico_sin_confirmacion_humana_y_conserva_lo_demas(raiz):
    textos, ids = _documentos(raiz)
    antes = {t: copy.deepcopy(_ubicar(raiz, i)) for t, i in ids.items()}
    ocr = OCRFalso(textos)
    resumen = _extraer(raiz, ocr)
    assert ocr.cerrado and resumen["pendientes"] == 3 and not resumen["errores"]
    assert {(e["tipo"], e["vencimiento"], e["estado"], e["patente"]) for e in resumen["extraidos"]} == {
        (t, v, "EXTRAIDO", TRACTO) for t, v in VENCIMIENTOS_REALES.items()}
    assert {(e["tipo"], e["vencimiento"], e["patente"]) for e in resumen["activados"]} == {
        (t, v, TRACTO) for t, v in VENCIMIENTOS_REALES.items()}
    datos = leer_almacen(raiz, empresa="MBT")
    for tipo, documento_id in ids.items():
        patente, documento = _ubicar(raiz, documento_id)
        patente_antes, previo = antes[tipo]
        assert patente == patente_antes == TRACTO
        extraccion = documento.pop("extraccion_automatica")
        registro = documento.pop("vencimiento_registro")
        assert documento.pop("vencimiento") == VENCIMIENTOS_REALES[tipo]
        assert documento.pop("estado_revision") == "VENCIMIENTO_OCR_AUTOMATICO"
        assert previo.pop("estado_revision") == "PENDIENTE_EXTRACCION" and "vencimiento" not in previo
        # El tipo seleccionado queda como dato informado; el operativo lo acredita el título leído.
        assert documento.pop("tipo_informado") == previo["tipo"] == documento["tipo"] == tipo
        tipo_ocr = extraccion["campos"]["tipo_documental"]
        assert (tipo_ocr["valor"], tipo_ocr["estado"], tipo_ocr["candidatos"]) == (tipo, "EXTRAIDO", [tipo])
        assert tipo_ocr["evidencia"] and extraccion["regla"] == tipo
        assert documento == previo  # asociación, patente, sha256, archivo, origen e historial intactos
        assert registro["procedencia"] == "OCR_AUTOMATICO" and registro["confirmado_por_humano"] is False
        assert registro["actor"] == "MOTOR_OCR" and registro["sha256"] == documento["sha256"]
        assert registro["evidencia"] == extraccion["campos"]["vencimiento"]["evidencia"]
        assert not {"confirmacion_humana", "revision_humana", "confirmado_por", "autor"} & (set(registro) | set(documento))
        assert extraccion["confirmado_por_humano"] is False and extraccion["procedencia"] == "AUTOMATICA_OCR"
        assert extraccion["actor"] == "MOTOR_OCR" and extraccion["estado"] == "COMPLETA"
        assert extraccion["archivos"] == [{"archivo": documento["archivo"], "sha256": documento["sha256"]}]
        assert extraccion["campos"]["vencimiento"]["evidencia"]
        ruta = ruta_almacen(raiz, "MBT").parent / documento["archivo"]
        assert sha(ruta.read_bytes()) == documento["sha256"]
    ficha = next(v for v in datos["vehiculos"] if v["patente"] == TRACTO)
    eventos = [h for h in ficha["historial"] if h["accion"] == "DOCUMENTO_VEHICULO_EXTRACCION_VENCIMIENTO"]
    assert len(eventos) == 3 and all(e["actor"] == "MOTOR_OCR" for e in eventos)
    activados = [h for h in ficha["historial"] if h["accion"] == "DOCUMENTO_VEHICULO_VENCIMIENTO_AUTOMATICO"]
    assert len(activados) == 3 and all(h["procedencia"] == "OCR_AUTOMATICO" and h["confirmado_por_humano"] is False
                                       for h in activados)
    respaldos = [r.read_text(encoding="utf-8") for r in (raiz / "respaldos" / "fichas_choferes").glob("*/manifest.json")]
    assert sum("EXTRACCION_VENCIMIENTO" in r for r in respaldos) == 3
    assert sum("ACTIVACION_VENCIMIENTO_AUTOMATICO" in r for r in respaldos) == 3


def test_una_sola_lectura_por_version(raiz):
    textos, _ = _documentos(raiz)
    _extraer(raiz, OCRFalso(textos))
    revision = leer_almacen(raiz, empresa="MBT")["revision"]
    segundo = OCRFalso(textos)
    assert _extraer(raiz, segundo) == {"pendientes": 0, "extraidos": [], "errores": [], "activados": []}
    assert segundo.leidas == [] and leer_almacen(raiz, empresa="MBT")["revision"] == revision


# ------------------------------------------- vencimiento operativo automático


def _solo_extraccion_previa(raiz, textos):
    """Estado de producción tras b673268: lecturas EXTRAIDO sin vencimiento operativo."""
    original = modulo.activar_vencimientos_extraidos
    modulo.activar_vencimientos_extraidos = lambda *a, **k: {"activados": [], "errores": []}
    try:
        _extraer(raiz, OCRFalso(textos))
    finally:
        modulo.activar_vencimientos_extraidos = original


def test_reconcilia_propuestas_existentes_sin_ocr_ni_tocar_originales(raiz):
    textos, ids = _documentos(raiz)
    _solo_extraccion_previa(raiz, textos)
    antes = {t: copy.deepcopy(_ubicar(raiz, i)[1]) for t, i in ids.items()}
    assert all("vencimiento" not in d for d in antes.values())
    ocr = OCRFalso({})  # cualquier lectura fallaría
    resumen = _extraer(raiz, ocr)
    assert ocr.leidas == [] and resumen["pendientes"] == 0 and not resumen["errores"]
    assert {(a["tipo"], a["vencimiento"]) for a in resumen["activados"]} == set(VENCIMIENTOS_REALES.items())
    for tipo, documento_id in ids.items():
        patente, documento = _ubicar(raiz, documento_id)
        assert patente == TRACTO and documento["vencimiento"] == VENCIMIENTOS_REALES[tipo]
        for clave in ("archivo", "sha256", "asociacion", "identificacion_patente", "extraccion_automatica", "procedencia"):
            assert documento[clave] == antes[tipo][clave]
        assert sha((ruta_almacen(raiz, "MBT").parent / documento["archivo"]).read_bytes()) == documento["sha256"]


@pytest.mark.parametrize("lineas,motivo", [
    (["VENCE: 30/09/2027", "VENCIMIENTO: 31/03/2027"], "VARIAS_FECHAS"),           # ambigua
    (["VENCE: 30/09/27"], "ILEGIBLE"),                                               # ilegible
    (["FECHA DE PAGO 05/10/2026", "VENCE: 30/09/2026"], "FECHAS_CONTRADICTORIAS"),   # contradictoria
    (["FECHA", "05/10/2026", "VENCE: 30/09/2030"], "PLAZO_IMPROBABLE"),             # improbable
])
def test_abstencion_no_registra_vencimiento_y_queda_pendiente(raiz, lineas, motivo):
    documento_id, contenido = _recibir(raiz, "dudoso", tipo="PERMISO_CIRCULACION")
    # Con el tipo acreditado, la abstención se debe sólo a las fechas.
    resumen = _extraer(raiz, OCRFalso({contenido: ["PERMISO DE CIRCULACION", *lineas]}))
    _, documento = _ubicar(raiz, documento_id)
    assert documento["tipo"] == "PERMISO_CIRCULACION"
    assert documento["extraccion_automatica"]["campos"]["vencimiento"]["motivo"] == motivo
    assert resumen["activados"] == [] and "vencimiento" not in documento and "vencimiento_registro" not in documento
    assert documento["estado_revision"] == "PENDIENTE_EXTRACCION"
    assert documento["extraccion_automatica"]["campos"]["vencimiento"]["estado"] == "PENDIENTE_REVISION"


def test_documento_por_clasificar_no_recibe_vencimiento_operativo(raiz):
    documento_id, contenido = _recibir(raiz, "sin-patente-2", tipo="SOAP", patente="")
    resumen = _extraer(raiz, OCRFalso({contenido: SOAP_REAL}))
    patente, documento = _ubicar(raiz, documento_id)
    assert patente is None and resumen["activados"] == [] and "vencimiento" not in documento


def test_lectura_alterada_o_de_otro_original_no_se_activa(raiz):
    textos, ids = _documentos(raiz)
    _solo_extraccion_previa(raiz, textos)
    import json
    ruta = ruta_almacen(raiz, "MBT")
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    for d in datos["vehiculos"][0]["documentos"]:
        if d["documento_id"] == ids["SOAP"]:
            d["extraccion_automatica"]["archivos"][0]["sha256"] = "0" * 64
        if d["documento_id"] == ids["PERMISO_CIRCULACION"]:
            d["extraccion_automatica"]["campos"]["vencimiento"]["evidencia"] = []
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    _, rt = _ubicar(raiz, ids["REVISION_TECNICA"])
    (ruta.parent / rt["archivo"]).write_bytes(JPEG("alterado"))
    resumen = _extraer(raiz, OCRFalso({}))
    assert resumen["activados"] == [] and [e["documento_id"] for e in resumen["errores"]] == [ids["REVISION_TECNICA"]]
    assert all("vencimiento" not in _ubicar(raiz, i)[1] for i in ids.values())


@pytest.mark.parametrize("cambios", [
    {"vencimiento": "2027-01-01"},
    {"estado_revision": "CONFIRMADA", "vencimiento": "2027-01-01"},
    {"confirmacion_humana": {"autor": "JAVIER"}},
    {"revision_humana": {"autor": "JAVIER"}},
])
def test_fecha_confirmada_por_una_persona_nunca_se_sobrescribe(raiz, cambios):
    textos, ids = _documentos(raiz)
    _solo_extraccion_previa(raiz, textos)
    _editar_documento(raiz, ids["SOAP"], **cambios)
    antes = copy.deepcopy(_ubicar(raiz, ids["SOAP"]))
    resumen = _extraer(raiz, OCRFalso({}))
    assert _ubicar(raiz, ids["SOAP"]) == antes
    assert "SOAP" not in {a["tipo"] for a in resumen["activados"]} and len(resumen["activados"]) == 2


def test_confirmacion_humana_entre_lectura_y_activacion_gana(raiz, monkeypatch):
    textos, ids = _documentos(raiz)
    _solo_extraccion_previa(raiz, textos)
    activar = modulo._activar

    def con_persona(raiz_, ruta, empresa, documento_id, actor, comprobar):
        if documento_id == ids["SOAP"]:
            _editar_documento(raiz, documento_id, vencimiento="2027-01-01", estado_revision="CONFIRMADA")
        return activar(raiz_, ruta, empresa, documento_id, actor, comprobar)

    monkeypatch.setattr(modulo, "_activar", con_persona)
    resumen = _extraer(raiz, OCRFalso({}))
    _, soap = _ubicar(raiz, ids["SOAP"])
    assert soap["vencimiento"] == "2027-01-01" and soap["estado_revision"] == "CONFIRMADA"
    assert "vencimiento_registro" not in soap and len(resumen["activados"]) == 2


def test_vencimiento_automatico_no_se_relee_ni_se_reactiva(raiz, monkeypatch):
    textos, ids = _documentos(raiz)
    _extraer(raiz, OCRFalso(textos))
    revision = leer_almacen(raiz, empresa="MBT")["revision"]
    monkeypatch.setattr(modulo, "VERSION_EXTRACCION", 2)  # ni siquiera una versión nueva relee
    segundo = OCRFalso(textos)
    resumen = _extraer(raiz, segundo)
    assert segundo.leidas == [] and resumen["activados"] == []
    assert leer_almacen(raiz, empresa="MBT")["revision"] == revision


def test_abstencion_queda_pendiente_y_se_reintenta_una_vez_con_otra_version(raiz, monkeypatch):
    documento_id, contenido = _recibir(raiz, "ambiguo", tipo="PERMISO_CIRCULACION")
    _extraer(raiz, OCRFalso({contenido: ["PERMISO DE CIRCULACION", "VENCE: 30/09/2027", "VENCIMIENTO: 31/03/2027"]}))
    _, documento = _ubicar(raiz, documento_id)
    campo = documento["extraccion_automatica"]["campos"]["vencimiento"]
    assert (campo["estado"], campo["motivo"], campo["observados"]) == (
        "PENDIENTE_REVISION", "VARIAS_FECHAS", ["2027-03-31", "2027-09-30"])
    assert documento["extraccion_automatica"]["estado"] == "SIN_DATOS"
    assert _extraer(raiz, OCRFalso({}))["pendientes"] == 0
    monkeypatch.setattr(modulo, "VERSION_EXTRACCION", modulo.VERSION_EXTRACCION + 1)
    _extraer(raiz, OCRFalso({contenido: ["PERMISO DE CIRCULACION", "VENCE: 30/09/2027"]}))
    _, documento = _ubicar(raiz, documento_id)
    assert documento["extraccion_automatica"]["campos"]["vencimiento"]["valor"] == "2027-09-30"
    assert documento["extracciones_anteriores"][0]["campos"]["vencimiento"]["motivo"] == "VARIAS_FECHAS"


def _editar_documento(raiz, documento_id, **cambios):
    ruta = ruta_almacen(raiz, "MBT")
    import json
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    for lista in [v["documentos"] for v in datos.get("vehiculos", [])] + [datos.get("documentos_vehiculo_pendientes", [])]:
        for d in lista:
            if d["documento_id"] == documento_id:
                d.update(cambios)
    ruta.write_text(json.dumps(datos), encoding="utf-8")


@pytest.mark.parametrize("cambios", [
    {"vencimiento": "2027-01-01"},
    {"estado_revision": "VIGENTE"},
    {"confirmacion_humana": {"autor": "JAVIER"}},
])
def test_dato_confirmado_por_una_persona_nunca_se_reprocesa(raiz, cambios):
    textos, ids = _documentos(raiz)
    _editar_documento(raiz, ids["SOAP"], **cambios)
    antes = copy.deepcopy(_ubicar(raiz, ids["SOAP"]))
    _extraer(raiz, OCRFalso(textos))
    assert _ubicar(raiz, ids["SOAP"]) == antes


def test_confirmacion_humana_entre_ocr_y_escritura_no_se_sobrescribe(raiz):
    textos, ids = _documentos(raiz)

    class OCRConPersona(OCRFalso):
        def leer_texto(self, ruta):
            _editar_documento(raiz, ids["SOAP"], vencimiento="2027-01-01", estado_revision="VIGENTE")
            return super().leer_texto(ruta)

    resumen = _extraer(raiz, OCRConPersona(textos))
    _, documento = _ubicar(raiz, ids["SOAP"])
    assert documento["vencimiento"] == "2027-01-01" and "extraccion_automatica" not in documento
    assert "SOAP" not in {e["tipo"] for e in resumen["extraidos"]}


def test_original_alterado_o_error_ocr_no_registra_nada(raiz):
    documento_id, contenido = _recibir(raiz, "alterado", tipo="SOAP")
    _, documento = _ubicar(raiz, documento_id)
    (ruta_almacen(raiz, "MBT").parent / documento["archivo"]).write_bytes(JPEG("otro"))
    resumen = _extraer(raiz, OCRFalso({}))
    assert resumen["errores"] and "huella" in resumen["errores"][0]["error"]
    otro_id, otro = _recibir(raiz, "falla", tipo="REVISION_TECNICA")
    resumen = _extraer(raiz, OCRFalso({otro: RuntimeError("worker caído")}))
    assert [e["documento_id"] for e in resumen["errores"]] == [documento_id, otro_id]
    assert "extraccion_automatica" not in _ubicar(raiz, documento_id)[1]
    assert "extraccion_automatica" not in _ubicar(raiz, otro_id)[1]


def test_pdf_queda_pendiente_sin_ocr(raiz):
    contenido = b"%PDF-1.4 sintetico"
    documento_id, _ = _recibir(raiz, "pdf", tipo="SOAP", contenido=contenido, mime="application/pdf")
    ocr = OCRFalso({})
    _extraer(raiz, ocr)
    campo = _ubicar(raiz, documento_id)[1]["extraccion_automatica"]["campos"]["vencimiento"]
    assert campo["motivo"] == "FORMATO_SIN_OCR" and ocr.leidas == []


def test_documento_por_clasificar_registra_el_historial_en_el_documento(raiz):
    documento_id, contenido = _recibir(raiz, "sin-patente", tipo="SOAP", patente="")
    _extraer(raiz, OCRFalso({contenido: SOAP_REAL}))
    patente, documento = _ubicar(raiz, documento_id)
    assert patente is None and documento["extraccion_automatica"]["campos"]["vencimiento"]["valor"] == "2027-09-30"
    assert documento["historial"][-1]["accion"] == "DOCUMENTO_VEHICULO_EXTRACCION_VENCIMIENTO"


def test_lease_perdido_detiene_sin_escribir(raiz):
    textos, ids = _documentos(raiz)
    revision = leer_almacen(raiz, empresa="MBT")["revision"]

    def comprobar():
        raise PermissionError("lease")

    with pytest.raises(PermissionError):
        _extraer(raiz, OCRFalso(textos), comprobar=comprobar)
    assert leer_almacen(raiz, empresa="MBT")["revision"] == revision
