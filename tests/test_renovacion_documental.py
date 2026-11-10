"""Renovaciones documentales seguras: misma regla en Mobile (fichas) y Desktop (expediente).

Reemplazo explícito verificable, renovación implícita inequívoca, vigencia futura
programada, ambigüedad pendiente para siempre, coberturas de póliza y aislamiento
multiempresa. Sólo datos sintéticos en tmp_path.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from atlas_core.expediente_digital import consultar_expediente, leer_expediente, registrar_documento_vehiculo_desktop
from atlas_core.extraccion_vencimientos_vehiculos import extraer_vencimientos_vehiculos
from atlas_core.fichas_choferes import leer_almacen
from atlas_core.renovacion_documental import (
    ACTIVAR, PENDIENTE, PROGRAMAR, REEMPLAZAR, decidir_renovacion, inicio_acreditado,
)
from tests.test_expediente_digital_base import PATENTE, RELOJ, _catalogos
from tests.test_identificacion_patentes import OCRFalso, TRACTO, _recibir, _ubicar, raiz  # noqa: F401

RC, ROBO = "POLIZA_RESPONSABILIDAD_CIVIL", "POLIZA_ROBO"
HOY = date(2026, 11, 10)


def anterior(documento_id, tipo, vencimiento, coberturas=(), origenes=()):
    return {"documento_id": documento_id, "tipo": tipo, "vencimiento": vencimiento,
            "coberturas": list(coberturas), "origenes": list(origenes)}


def nuevo(tipo, vencimiento, **extra):
    return {"tipo": tipo, "tipo_informado": tipo, "vencimiento": vencimiento, "inicio": "", "coberturas": [],
            "reemplaza": "", **extra}


# ---------------------------------------------------------------- decisión pura


def test_sin_anterior_relacionado_se_activa():
    decision = decidir_renovacion(nuevo("SOAP", "2027-09-30"), [anterior("rt", "REVISION_TECNICA", "2027-03-25")], HOY)
    assert decision == {"accion": ACTIVAR, "motivo": "", "documentos": [], "fecha": ""}


@pytest.mark.parametrize("vence_anterior", ["2027-03-31", "2025-03-31"])  # vigente o ya vencido
def test_unico_anterior_con_vencimiento_posterior_se_reemplaza(vence_anterior):
    decision = decidir_renovacion(nuevo("SOAP", "2027-09-30"), [anterior("a", "SOAP", vence_anterior)], HOY)
    assert (decision["accion"], decision["documentos"]) == (REEMPLAZAR, ["a"])


@pytest.mark.parametrize("vencimiento", ["2027-03-31", "2027-01-01"])
def test_vencimiento_igual_o_anterior_es_ambiguo(vencimiento):
    decision = decidir_renovacion(nuevo("SOAP", vencimiento), [anterior("a", "SOAP", "2027-03-31")], HOY)
    assert (decision["accion"], decision["motivo"], decision["documentos"]) == (PENDIENTE, "VENCIMIENTO_NO_POSTERIOR", ["a"])


def test_varios_anteriores_del_mismo_tipo_es_ambiguo():
    decision = decidir_renovacion(nuevo("SOAP", "2028-09-30"),
                                  [anterior("a", "SOAP", "2027-03-31"), anterior("b", "SOAP", "2027-09-30")], HOY)
    assert (decision["accion"], decision["motivo"], decision["documentos"]) == (PENDIENTE, "VARIOS_ANTERIORES", ["a", "b"])


@pytest.mark.parametrize("inicio,accion,fecha", [
    ("2027-10-01", PROGRAMAR, "2027-10-01"), ("2026-11-10", REEMPLAZAR, ""), ("2026-10-01", REEMPLAZAR, ""),
])
def test_vigencia_futura_se_programa_segun_la_fecha_acreditada(inicio, accion, fecha):
    decision = decidir_renovacion(nuevo("SOAP", "2028-09-30", inicio=inicio), [anterior("a", "SOAP", "2027-09-30")], HOY)
    assert (decision["accion"], decision["documentos"], decision["fecha"]) == (accion, ["a"], fecha)


def test_tipo_leido_distinto_con_vigente_es_ambiguo_y_con_vencido_renueva():
    leido = nuevo("REVISION_TECNICA", "2027-04-25", tipo_informado="SOAP")
    assert decidir_renovacion(leido, [anterior("rt", "REVISION_TECNICA", "2027-03-25")], HOY)["motivo"] == "TIPO_LEIDO_CON_VIGENTE"
    decision = decidir_renovacion(leido, [anterior("rt", "REVISION_TECNICA", "2026-03-25")], HOY)
    assert (decision["accion"], decision["documentos"]) == (REEMPLAZAR, ["rt"])


@pytest.mark.parametrize("anteriores,motivo", [
    ([anterior("a", RC, "2027-09-30", [RC, ROBO], ["x"]), anterior("b", RC, "2027-09-30", [RC], ["x"])], "dos con el mismo origen"),
    ([anterior("a", RC, "2027-09-30", [RC], ["otro"])], "origen inexistente"),
    ([anterior("a", "SOAP", "2027-09-30", [], ["x"])], "origen de otro tipo"),
])
def test_vinculo_explicito_no_verificable_queda_pendiente(anteriores, motivo):
    decision = decidir_renovacion(nuevo(RC, "2028-09-30", coberturas=[RC], reemplaza="x"), anteriores, HOY)
    assert (decision["accion"], decision["motivo"]) == (PENDIENTE, "VINCULO_NO_VERIFICABLE"), motivo


def test_vinculo_explicito_verificable_reemplaza_sólo_el_elegido():
    anteriores = [anterior("a", RC, "2027-09-30", [RC], ["x"]), anterior("b", RC, "2027-03-30", [RC], ["y"])]
    leido = nuevo(RC, "2028-09-30", coberturas=[RC], reemplaza="x", tipo_informado=ROBO)
    assert decidir_renovacion(leido, anteriores, HOY) == {"accion": REEMPLAZAR, "motivo": "", "documentos": ["a"], "fecha": ""}


@pytest.mark.parametrize("cubre_anterior,cubre_nuevo,accion,motivo", [
    ([RC, ROBO], [RC], PENDIENTE, "COBERTURAS_REDUCIDAS"),
    ([RC, ROBO], [ROBO], PENDIENTE, "COBERTURAS_REDUCIDAS"),
    ([RC, ROBO], [RC, ROBO], REEMPLAZAR, ""),
    ([RC], [RC, ROBO], REEMPLAZAR, ""),  # ampliación de cobertura
    ([], [RC], REEMPLAZAR, ""),  # anterior sin coberturas leídas: acredita su propio tipo
])
def test_poliza_nunca_retira_una_cobertura_sin_evidencia(cubre_anterior, cubre_nuevo, accion, motivo):
    for reemplaza, origenes in (("", ()), ("x", ("x",))):
        decision = decidir_renovacion(nuevo(RC, "2028-09-30", coberturas=cubre_nuevo, reemplaza=reemplaza),
                                      [anterior("a", RC, "2027-09-30", cubre_anterior, origenes)], HOY)
        assert (decision["accion"], decision["motivo"]) == (accion, motivo)


def test_polizas_separadas_frente_a_una_doble_es_ambiguo():
    decision = decidir_renovacion(nuevo(RC, "2028-09-30", coberturas=[RC, ROBO]),
                                  [anterior("rc", RC, "2027-09-30", [RC]), anterior("robo", ROBO, "2027-09-30", [ROBO])], HOY)
    assert (decision["accion"], decision["motivo"]) == (PENDIENTE, "VARIOS_ANTERIORES")


def test_inicio_acreditado_solo_del_par_desde_hasta():
    assert inicio_acreditado({"evidencia": [{"rotulo": "HASTA", "par_desde": "2026-10-01"}]}) == "2026-10-01"
    assert inicio_acreditado({"evidencia": [{"rotulo": "VENCE"}]}) == ""
    assert inicio_acreditado({"evidencia": [{"rotulo": "HASTA", "par_desde": "31/02/2027"}]}) == ""


# ---------------------------------------------------------------- Mobile (fichas)


def soap(desde, hasta, patente=TRACTO):
    return ["CERTIFICADO SEGURO OBLIGATORIO ACCIDENTES", patente, "PERSONALES ELECTRONICO LEY 18.490",
            "RIGE DESDE", "HASTA", desde, hasta]


def _ciclo(raiz, textos, hoy=HOY):
    from atlas_core.identificacion_patentes import identificar_patentes_documentos
    identificar_patentes_documentos(raiz, comprobar=lambda: None, fabrica_ocr=lambda: OCRFalso(textos))
    return extraer_vencimientos_vehiculos(raiz, comprobar=lambda: None, fabrica_ocr=lambda: OCRFalso(textos), hoy=hoy)


def _historial(raiz, accion):
    ficha = next(v for v in leer_almacen(raiz, empresa="MBT")["vehiculos"] if v["patente"] == TRACTO)
    return [h for h in ficha["historial"] if h["accion"] == accion]


def _vigente(raiz):
    viejo_id, viejo = _recibir(raiz, "soap-2026", tipo="SOAP")
    _ciclo(raiz, {viejo: soap("01/10/2026", "30/09/2027")})
    assert _ubicar(raiz, viejo_id)[1]["vencimiento"] == "2027-09-30"
    return viejo_id


def test_mobile_renovacion_inequivoca_reemplaza_y_conserva_original_e_historial(raiz):
    viejo_id = _vigente(raiz)
    antes = _ubicar(raiz, viejo_id)[1]
    nuevo_id, contenido = _recibir(raiz, "soap-2027", tipo="SOAP")
    resumen = _ciclo(raiz, {contenido: soap("01/11/2026", "31/10/2027")})
    assert [a["documento_id"] for a in resumen["activados"]] == [nuevo_id]
    _, viejo = _ubicar(raiz, viejo_id)
    assert viejo.pop("reemplazado_por") == nuevo_id and viejo == antes  # sólo se marca como reemplazado
    from atlas_core.fichas_choferes import ruta_almacen
    assert (ruta_almacen(raiz, "MBT").parent / viejo["archivo"]).is_file()
    assert [h["documento_id"] for h in _historial(raiz, "DOCUMENTO_VEHICULO_REEMPLAZADO")] == [viejo_id]


def test_mobile_vigencia_futura_conserva_el_anterior_hasta_la_fecha_acreditada(raiz):
    viejo_id = _vigente(raiz)
    nuevo_id, contenido = _recibir(raiz, "soap-futuro", tipo="SOAP")
    resumen = _ciclo(raiz, {contenido: soap("01/10/2027", "30/09/2028")})
    _, documento = _ubicar(raiz, nuevo_id)
    assert resumen["activados"] == [] and "vencimiento" not in documento
    assert documento["transicion_programada"]["fecha"] == "2027-10-01"
    assert documento["transicion_programada"]["reemplaza"] == [viejo_id]
    assert not _ubicar(raiz, viejo_id)[1].get("reemplazado_por")
    revision = leer_almacen(raiz, empresa="MBT")["revision"]
    assert _ciclo(raiz, {}, hoy=date(2027, 9, 30))["activados"] == []
    assert leer_almacen(raiz, empresa="MBT")["revision"] == revision  # sin reescribir la programación
    resumen = _ciclo(raiz, {}, hoy=date(2027, 10, 1))
    assert [a["documento_id"] for a in resumen["activados"]] == [nuevo_id]
    _, documento = _ubicar(raiz, nuevo_id)
    assert documento["vencimiento"] == "2028-09-30" and "transicion_programada" not in documento
    assert _ubicar(raiz, viejo_id)[1]["reemplazado_por"] == nuevo_id
    assert _historial(raiz, "DOCUMENTO_VEHICULO_REEMPLAZADO")[0]["programado_desde"] == "2027-10-01"


def test_mobile_pendiente_por_ambiguedad_nunca_se_activa_al_vencer_el_anterior(raiz):
    viejo_id = _vigente(raiz)
    nuevo_id, contenido = _recibir(raiz, "soap-dudoso", tipo="SOAP")
    _ciclo(raiz, {contenido: soap("01/10/2026", "30/09/2027")})  # mismo vencimiento: no establece sustitución
    _, documento = _ubicar(raiz, nuevo_id)
    assert documento["posible_reemplazo"]["motivo"] == "VENCIMIENTO_NO_POSTERIOR"
    for hoy in (date(2027, 10, 1), date(2029, 1, 1)):
        assert _ciclo(raiz, {}, hoy=hoy)["activados"] == []
    _, documento = _ubicar(raiz, nuevo_id)
    assert "vencimiento" not in documento and not _ubicar(raiz, viejo_id)[1].get("reemplazado_por")
    assert len(_historial(raiz, "DOCUMENTO_VEHICULO_POSIBLE_REEMPLAZO")) == 1


def test_mobile_segunda_renovacion_sobre_una_programada_es_ambigua(raiz):
    _vigente(raiz)
    programada_id, programada = _recibir(raiz, "soap-programada", tipo="SOAP")
    _ciclo(raiz, {programada: soap("01/10/2027", "30/09/2028")})
    otra_id, otra = _recibir(raiz, "soap-otra", tipo="SOAP")
    _ciclo(raiz, {otra: soap("01/11/2026", "31/10/2027")})
    _, documento = _ubicar(raiz, otra_id)
    assert documento["posible_reemplazo"]["motivo"] == "VARIOS_ANTERIORES" and "vencimiento" not in documento


# ---------------------------------------------------------------- Desktop (expediente)


JPEG_DESKTOP = b"\xff\xd8\xff\xe0"


class OCR:
    def __init__(self, lineas):
        self.lineas = lineas

    def leer_texto(self, ruta):
        return self.lineas


@pytest.fixture
def expediente(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("expediente")
    _catalogos(tmp_path / "catalogos_privados", "ANA")
    return tmp_path


def alta(raiz, lineas, *, tipo="SOAP", empresa="MBT", contenido=b"soap"):
    return registrar_documento_vehiculo_desktop(
        raiz, empresa=empresa, referencia=PATENTE, tipo=tipo, contenido=JPEG_DESKTOP + contenido, mime_type="image/jpeg",
        reloj=RELOJ, fabrica_ocr=lambda: OCR(lineas))


def ver(raiz, hoy, empresa="MBT"):
    return consultar_expediente(raiz, empresa=empresa, entidad="VEHICULO", referencia=PATENTE, hoy=hoy)


def test_desktop_misma_regla_vigencia_futura_y_transicion(expediente):
    viejo = alta(expediente, soap("01/10/2026", "30/09/2027", PATENTE), contenido=b"viejo")
    assert not viejo["pendiente_revision"]
    nuevo_doc = alta(expediente, soap("01/10/2027", "30/09/2028", PATENTE), contenido=b"nuevo")
    assert nuevo_doc["pendiente_revision"] and nuevo_doc["transicion_programada"]["fecha"] == "2027-10-01"
    antes = ver(expediente, date(2027, 9, 30))
    vigente = {d["documento_id"]: d["estado_vencimiento"] for d in antes["documentos"]}
    assert vigente[viejo["documento_id"]] == "POR_VENCER" and antes["historico"] == []  # sigue rigiendo
    despues = ver(expediente, date(2027, 10, 1))
    assert [d["documento_id"] for d in despues["documentos"]] == [nuevo_doc["documento_id"]]
    assert [d["documento_id"] for d in despues["historico"]] == [viejo["documento_id"]]
    assert leer_expediente(expediente, empresa="MBT")["documentos"][0]["estado"] == "ACTIVO"  # la consulta no escribe


def test_desktop_pendiente_por_ambiguedad_nunca_se_activa_al_vencer_el_anterior(expediente):
    viejo = alta(expediente, soap("01/10/2026", "30/09/2027", PATENTE), contenido=b"viejo")
    dudoso = alta(expediente, soap("01/09/2026", "31/08/2027", PATENTE), contenido=b"dudoso")
    assert dudoso["posible_reemplazo"]["motivo"] == "VENCIMIENTO_NO_POSTERIOR" and dudoso["pendiente_revision"]
    vista = ver(expediente, date(2028, 1, 1))
    estados = {d["documento_id"]: d["estado_vencimiento"] for d in vista["documentos"]}
    assert estados == {viejo["documento_id"]: "VENCIDO", dudoso["documento_id"]: "PENDIENTE_REVISION"}


@pytest.mark.parametrize("lineas,accion", [
    (soap("01/11/2026", "31/10/2027"), REEMPLAZAR),
    (soap("01/10/2027", "30/09/2028"), PROGRAMAR),
    (soap("01/10/2026", "30/09/2027"), PENDIENTE),
])
def test_desktop_y_mobile_deciden_lo_mismo(expediente, raiz, lineas, accion):
    alta(expediente, soap("01/10/2026", "30/09/2027", PATENTE), contenido=b"base")
    d = alta(expediente, [x.replace(TRACTO, PATENTE) for x in lineas], contenido=b"caso")
    _vigente(raiz)
    nuevo_id, contenido = _recibir(raiz, "caso", tipo="SOAP")
    _ciclo(raiz, {contenido: lineas})
    _, m = _ubicar(raiz, nuevo_id)
    desktop = PENDIENTE if d.get("posible_reemplazo") else PROGRAMAR if d.get("transicion_programada") else \
        REEMPLAZAR if not d["pendiente_revision"] else "?"
    mobile = PENDIENTE if m.get("posible_reemplazo") else PROGRAMAR if m.get("transicion_programada") else \
        REEMPLAZAR if m.get("vencimiento") else "?"
    assert desktop == mobile == accion


def test_desktop_renovacion_no_cruza_empresas(expediente):
    otra = alta(expediente, soap("01/10/2026", "30/09/2027", PATENTE), empresa="OTRA", contenido=b"otra")
    propio = alta(expediente, soap("01/11/2026", "31/10/2027", PATENTE), contenido=b"propio")
    assert not propio["pendiente_revision"] and "posible_reemplazo" not in propio  # sin anterior en MBT: se activa
    assert leer_expediente(expediente, empresa="OTRA")["documentos"][0]["estado"] == "ACTIVO"
    assert [d["documento_id"] for d in ver(expediente, HOY, "OTRA")["documentos"]] == [otra["documento_id"]]
    assert json.dumps(leer_expediente(expediente, empresa="MBT")).count(otra["documento_id"]) == 0
