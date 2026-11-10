from datetime import date
import json

import pytest

from atlas_core.expediente_digital import (
    anular_documento, consultar_expediente, leer_expediente, preparar_alertas_vencimiento,
    registrar_documento_vehiculo_desktop,
)
from atlas_core.extraccion_vencimientos_vehiculos import extraer_vencimientos_vehiculos
from atlas_core.identificacion_patentes import identificar_patentes_documentos
from atlas_core.fichas_choferes import ruta_almacen
from tests.test_expediente_digital_base import PATENTE, RELOJ, _catalogos
from tests.test_identificacion_patentes import TRACTO, _recibir, raiz as raiz_mobile

RC, ROBO = "POLIZA_RESPONSABILIDAD_CIVIL", "POLIZA_ROBO"
JPEG = b"\xff\xd8\xff\xe0foto-sintetica"


class OCR:
    def __init__(self, patente, cobertura, vencimiento="30/09/2027"):
        self.lineas = [f"PATENTE {patente}", f"VENCIMIENTO: {vencimiento}", cobertura]

    def leer_texto(self, ruta):
        return self.lineas


@pytest.fixture
def raiz(tmp_path):
    _catalogos(tmp_path / "catalogos_privados", "ANA")
    return tmp_path


def registrar(raiz, cobertura, *, empresa="MBT", tipo=RC, vencimiento="30/09/2027", patente=PATENTE):
    return registrar_documento_vehiculo_desktop(
        raiz, empresa=empresa, referencia=PATENTE, tipo=tipo, contenido=JPEG, mime_type="image/jpeg", reloj=RELOJ,
        fabrica_ocr=lambda: OCR(patente, cobertura, vencimiento))


def consulta(raiz, empresa="MBT", hoy=date(2026, 11, 9), patente=PATENTE):
    return consultar_expediente(raiz, empresa=empresa, entidad="VEHICULO", referencia=patente, hoy=hoy)


def faltantes(vista):
    return {a["tipo"]: a["pendiente_revision"] for a in vista["ausentes"] if a["tipo"] in (RC, ROBO)}


@pytest.mark.parametrize("texto,cubiertas,ausentes", [
    ("COBERTURA: RESPONSABILIDAD CIVIL", [RC], {ROBO: False}),
    ("COBERTURA: ROBO", [ROBO], {RC: False}),
    ("COBERTURAS: RESPONSABILIDAD CIVIL Y ROBO", [RC, ROBO], {}),
    ("COBERTURA: RESPONSABILIDAD CIVIL Y ROBO EXCLUIDO", [], {RC: True, ROBO: True}),
])
def test_cobertura_por_evidencia_sin_duplicar_original(raiz, texto, cubiertas, ausentes):
    doc = registrar(raiz, texto)
    vista = consulta(raiz)
    assert len(vista["documentos"]) == 1
    assert vista["documentos"][0]["tipos_cubiertos"] == cubiertas
    assert faltantes(vista) == ausentes
    assert len(list((raiz / "fichas_digitales" / "MBT" / "archivos" / "expediente").rglob("*.jpg"))) == 1
    assert (raiz / "fichas_digitales" / "MBT" / doc["archivo"]).read_bytes() == JPEG


def test_reemplazo_conserva_historial_y_ajusta_ambas_coberturas(raiz):
    primera = registrar(raiz, "COBERTURAS: RESPONSABILIDAD CIVIL Y ROBO")
    ambigua = registrar(raiz, "COBERTURA: RESPONSABILIDAD CIVIL Y ROBO EXCLUIDO")
    assert ambigua["pendiente_revision"]
    assert not faltantes(consulta(raiz))
    nueva = registrar(raiz, "COBERTURA: RESPONSABILIDAD CIVIL")
    vista = consulta(raiz)
    assert faltantes(vista) == {ROBO: True}  # el intento ambiguo permanece pendiente
    assert [d["documento_id"] for d in vista["historico"]] == [primera["documento_id"]]
    assert any(d["documento_id"] == nueva["documento_id"] and d["tipos_cubiertos"] == [RC] for d in vista["documentos"])
    assert (raiz / "fichas_digitales" / "MBT" / primera["archivo"]).read_bytes() == JPEG


def test_vencimiento_y_aislamiento_multiempresa(raiz):
    doc = registrar(raiz, "COBERTURAS: RESPONSABILIDAD CIVIL Y ROBO")
    assert faltantes(consulta(raiz, empresa="OTRA")) == {RC: False, ROBO: False}
    vista = consulta(raiz, hoy=date(2027, 10, 1))
    assert faltantes(vista) == {RC: False, ROBO: False}
    assert vista["documentos"][0]["estado_vencimiento"] == "VENCIDO"
    alerta = preparar_alertas_vencimiento(raiz, empresa="MBT", hoy=date(2027, 10, 1))
    assert len(alerta) == 1 and alerta[0]["documento_id"] == doc["documento_id"]
    assert alerta[0]["tipos_cubiertos"] == [RC, ROBO]
    assert leer_expediente(raiz, empresa="OTRA")["documentos"] == []


def test_anulacion_retira_ambas_coberturas_sin_borrar_el_original(raiz):
    doc = registrar(raiz, "COBERTURAS: RESPONSABILIDAD CIVIL Y ROBO")
    anular_documento(raiz, empresa="MBT", documento_id=doc["documento_id"], actor="TEST", motivo="Anulada", reloj=RELOJ)
    vista = consulta(raiz)
    assert faltantes(vista) == {RC: False, ROBO: False}
    assert vista["historico"][0]["documento_id"] == doc["documento_id"]
    assert (raiz / "fichas_digitales" / "MBT" / doc["archivo"]).read_bytes() == JPEG


def test_separadas_acreditan_solo_su_cobertura(raiz):
    registrar(raiz, "COBERTURA: RESPONSABILIDAD CIVIL", tipo=RC)
    registrar(raiz, "COBERTURA: ROBO", tipo=ROBO)
    vista = consulta(raiz)
    assert len(vista["documentos"]) == 2 and not faltantes(vista)
    assert {tuple(d["tipos_cubiertos"]) for d in vista["documentos"]} == {(RC,), (ROBO,)}


def test_patente_dudosa_no_acredita_coberturas(raiz):
    registrar(raiz, "COBERTURAS: RESPONSABILIDAD CIVIL Y ROBO", patente="ZZ1234")
    vista = consulta(raiz)
    assert vista["documentos"][0]["tipos_cubiertos"] == []
    assert faltantes(vista) == {RC: True, ROBO: True}


def test_cobertura_mobile_usa_patente_y_original_del_flujo_existente(raiz_mobile):
    documento_id, _ = _recibir(raiz_mobile, "doble", tipo=RC)
    def proveedor():
        return OCR(TRACTO, "COBERTURAS: RESPONSABILIDAD CIVIL Y ROBO")
    identificar_patentes_documentos(raiz_mobile, comprobar=lambda: None, fabrica_ocr=proveedor)
    extraer_vencimientos_vehiculos(raiz_mobile, comprobar=lambda: None, fabrica_ocr=proveedor)
    vista = consulta(raiz_mobile, patente=TRACTO)
    doc = next(d for d in vista["documentos"] if d["documento_id"] == documento_id)
    assert doc["tipos_cubiertos"] == [RC, ROBO] and not faltantes(vista)
    # Un vínculo adulterado no acredita ningún requisito.
    ruta = ruta_almacen(raiz_mobile, "MBT")
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    ficha = next(v for v in datos["vehiculos"] if v["patente"] == TRACTO)
    ficha["documentos"][0]["asociacion"]["patente"] = "ZZ1234"
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    assert faltantes(consulta(raiz_mobile, patente=TRACTO)) == {RC: True, ROBO: True}
