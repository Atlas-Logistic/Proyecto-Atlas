"""Identificación OCR de la patente de documentos de vehículo (`identificacion_patentes`).

Sólo datos sintéticos en tmp_path; el OCR se simula con un proveedor que
devuelve las líneas de cada archivo (misma interfaz `leer_texto`). Los
documentos llegan por la recepción real (`fichas_vehiculos`).
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas_core import identificacion_patentes as modulo
from atlas_core.catalogo_vehiculos import TipoVehiculo, asociar_chofer_a_vehiculo_confirmado, cargar_catalogo_vehiculos
from atlas_core.fichas_choferes import inicializar_almacen, leer_almacen, ruta_almacen
from atlas_core.fichas_vehiculos import PENDIENTES, registrar_documento_vehiculo_mobile
from atlas_core.identificacion_patentes import identificar_patente, identificar_patentes_documentos
from tests.test_motor_evidencia_vehiculos import _catalogo, _confirmar

SOLO, COMBO = "97082251", "180915885"
TRACTO, OTRO_TRACTO, CARRO, RIGIDO = "BPHR67", "DDKL45", "JF9575", "KXTZ21"
sha = lambda b: hashlib.sha256(b).hexdigest()
JPEG = lambda texto: b"\xff\xd8\xff\xe0" + texto.encode()


class OCRFalso:
    def __init__(self, textos):
        self.textos, self.leidas, self.cerrado = textos, [], False

    def leer_texto(self, ruta):
        contenido = Path(ruta).read_bytes()
        self.leidas.append(contenido)
        valor = self.textos[contenido]
        if isinstance(valor, Exception):
            raise valor
        return valor

    def cerrar(self):
        self.cerrado = True


@pytest.fixture
def raiz(tmp_path):
    carpeta = tmp_path / "catalogos_privados"; carpeta.mkdir()
    ruta = _catalogo(carpeta)
    for patente, tipo in ((TRACTO, TipoVehiculo.TRACTO), (OTRO_TRACTO, TipoVehiculo.TRACTO),
                          (CARRO, TipoVehiculo.CARRO), (RIGIDO, TipoVehiculo.CAMION_RIGIDO)):
        _confirmar(ruta, patente, tipo)
    for patente, rut in ((TRACTO, SOLO), (OTRO_TRACTO, COMBO), (CARRO, COMBO)):
        asociar_chofer_a_vehiculo_confirmado(ruta, patente=patente, actor="JAVIER", fuente_decision="TEST",
                                             rut_chofer_asociado=rut, fecha=datetime(2026, 10, 1, tzinfo=timezone.utc))
    (carpeta / "choferes.json").write_text(json.dumps({SOLO: {"nombre": "SOLO SINTETICO", "activo": True},
                                                       COMBO: {"nombre": "COMBO SINTETICO", "activo": True}}), encoding="utf-8")
    (tmp_path / "operacion" / "actual").mkdir(parents=True)
    inicializar_almacen(tmp_path, empresa="MBT", actor="TEST")
    return tmp_path


def _recibir(raiz, origen, *, chofer=SOLO, patente=TRACTO, tipo="SOAP", contenido=None, mime="image/jpeg"):
    contenido = JPEG(origen) if contenido is None else contenido
    r = registrar_documento_vehiculo_mobile(
        raiz, empresa="MBT", origen_documento_id=origen, chofer_id=chofer, tipo=tipo, patente_cloud=patente,
        recibido_en="2026-11-02T13:00:00Z", contenido=contenido, mime_type=mime, sha256=sha(contenido),
        comprobar=lambda: None)
    return r["documento_id"], contenido


def _identificar(raiz, ocr, comprobar=lambda: None):
    return identificar_patentes_documentos(raiz, comprobar=comprobar, fabrica_ocr=lambda: ocr)


def _ubicar(raiz, documento_id):
    datos = leer_almacen(raiz, empresa="MBT")
    for v in datos.get("vehiculos", []):
        for d in v["documentos"]:
            if d["documento_id"] == documento_id:
                return v["patente"], d
    return None, next(d for d in datos.get(PENDIENTES, []) if d["documento_id"] == documento_id)


def _catalogo_cargado(raiz):
    return cargar_catalogo_vehiculos(raiz / "catalogos_privados" / "vehiculos.json")


# ---------------------------------------------------------------- lectura pura


@pytest.mark.parametrize("lineas,patente,motivo", [
    (["SEGURO OBLIGATORIO", f"PATENTE: BP HR 67", "VIGENCIA HASTA 31-03-2027"], TRACTO, ""),
    (["CERTIFICADO DE REVISION TECNICA", "PPU JF.95-75"], CARRO, ""),
    (["PERMISO DE CIRCULACION 2026", "PLACA PATENTE", "KXTZ.21-K"], RIGIDO, ""),
    (["PATENTE BPHR67", "REMOLQUE JF9575"], None, "VARIAS_PATENTES"),
    (["PATENTE BPHK67"], None, "LECTURA_DUDOSA"),
    (["PATENTE ZZXY99"], None, "PATENTE_DESCONOCIDA"),
    (["PATENTE BPHR67", "PATENTE ZZXY99"], None, "VARIAS_PATENTES"),
    (["MARZO DE 2026", "HORA 12:30", "FOLIO AB 12 34", "RUT 12.345.678-5"], None, "PATENTE_NO_ENCONTRADA"),
])
def test_lectura_de_patente_solo_decide_ante_una_patente_conocida_e_inequivoca(raiz, lineas, patente, motivo):
    decision = identificar_patente(lineas, _catalogo_cargado(raiz))
    assert (decision["patente"], decision["motivo"]) == (patente, motivo)


def test_lectura_dudosa_y_varias_patentes_conservan_candidatos(raiz):
    dudosa = identificar_patente(["PATENTE BPHK67"], _catalogo_cargado(raiz))
    assert dudosa["dudosas"] == {"BPHK67": [TRACTO]} and dudosa["candidatos"] == [TRACTO]
    varias = identificar_patente(["PATENTE BPHR67", "REMOLQUE JF9575"], _catalogo_cargado(raiz))
    assert varias["candidatos"] == [TRACTO, CARRO] and varias["evidencia"] == ["PATENTE BPHR67", "REMOLQUE JF9575"]


# ---------------------------------------------------------------- tracto, rampla y rígido


def test_tracto_confirmado_por_su_patente_documental(raiz):
    documento_id, contenido = _recibir(raiz, "dfv_1")  # recepción: tracto único por asignación
    ocr = OCRFalso({contenido: ["SOAP", "PATENTE BPHR67"]})
    resumen = _identificar(raiz, ocr)
    assert [a["patente"] for a in resumen["asociados"]] == [TRACTO] and ocr.cerrado
    patente, doc = _ubicar(raiz, documento_id)
    assert patente == TRACTO
    assert doc["asociacion"]["metodo"] == "PATENTE_DOCUMENTAL" and doc["asociacion"]["tipo_vehiculo"] == "TRACTO"
    assert doc["asociacion"]["coincide_con_patente_cloud"] is True
    assert [a["metodo"] for a in doc["asociaciones_anteriores"]] == ["ASIGNACION_CONFIRMADA"]
    identificacion = doc["identificacion_patente"]
    assert identificacion["confirmado_por_humano"] is False and identificacion["evidencia"] == ["PATENTE BPHR67"]
    assert doc["estado_revision"] == "PENDIENTE_EXTRACCION" and "vencimiento" not in doc
    assert (ruta_almacen(raiz, "MBT").parent / doc["archivo"]).read_bytes() == contenido


def test_documento_de_la_rampla_va_a_la_rampla_aunque_cloud_fijara_el_tracto(raiz):
    documento_id, contenido = _recibir(raiz, "dfv_rt", chofer=COMBO, patente=OTRO_TRACTO, tipo="REVISION_TECNICA")
    assert _ubicar(raiz, documento_id)[0] is None  # recepción: tracto + carro -> por clasificar
    _identificar(raiz, OCRFalso({contenido: ["REVISION TECNICA", "PPU JF.95-75"]}))
    patente, doc = _ubicar(raiz, documento_id)
    assert patente == CARRO and doc["asociacion"]["tipo_vehiculo"] == "CARRO"
    assert doc["asociacion"]["coincide_con_patente_cloud"] is False
    assert doc["clasificacion_anterior"]["motivo"] == "TRACTO_Y_CARRO" and "clasificacion" not in doc
    assert leer_almacen(raiz, empresa="MBT")[PENDIENTES] == []


def test_documento_asociado_al_tracto_por_asignacion_se_reasigna_a_su_patente_real(raiz):
    documento_id, contenido = _recibir(raiz, "dfv_rampla", tipo="PERMISO_CIRCULACION")
    _identificar(raiz, OCRFalso({contenido: ["PERMISO DE CIRCULACION", "PATENTE JF9575"]}))
    patente, doc = _ubicar(raiz, documento_id)
    assert patente == CARRO
    datos = leer_almacen(raiz, empresa="MBT")
    tracto = next(v for v in datos["vehiculos"] if v["patente"] == TRACTO)
    assert tracto["documentos"] == [] and tracto["historial"][-1]["accion"] == "DOCUMENTO_VEHICULO_REASIGNADO_POR_PATENTE"


def test_camion_rigido_se_distingue_por_su_tipo(raiz):
    documento_id, contenido = _recibir(raiz, "dfv_rigido")
    _identificar(raiz, OCRFalso({contenido: ["PATENTE KXTZ21"]}))
    patente, doc = _ubicar(raiz, documento_id)
    assert (patente, doc["asociacion"]["tipo_vehiculo"]) == (RIGIDO, "CAMION_RIGIDO")


# ---------------------------------------------------------------- abstención


@pytest.mark.parametrize("lineas,motivo,candidatos", [
    (["PATENTE BPHR67", "REMOLQUE JF9575"], "VARIAS_PATENTES", [TRACTO, CARRO]),
    (["PATENTE BPHK67"], "LECTURA_DUDOSA", [TRACTO]),
    (["PATENTE ZZXY99"], "PATENTE_DESCONOCIDA", [TRACTO]),
    (["SEGURO OBLIGATORIO"], "PATENTE_NO_ENCONTRADA", [TRACTO]),
])
def test_sin_patente_inequivoca_queda_por_clasificar_con_evidencia(raiz, lineas, motivo, candidatos):
    documento_id, contenido = _recibir(raiz, "dfv_amb")  # estaba en el tracto sólo por asignación
    resumen = _identificar(raiz, OCRFalso({contenido: lineas}))
    assert [p["motivo"] for p in resumen["por_clasificar"]] == [motivo]
    patente, doc = _ubicar(raiz, documento_id)
    assert patente is None and "asociacion" not in doc
    assert doc["asociacion_anterior"]["metodo"] == "ASIGNACION_CONFIRMADA"
    assert doc["clasificacion"] == {"estado": "PENDIENTE_CLASIFICACION", "motivo": motivo, "patente_cloud": TRACTO,
                                    "candidatos": candidatos, "motivo_asignacion": "ASIGNACION_CONFIRMADA"}
    assert doc["identificacion_patente"]["motivo"] == motivo
    assert (ruta_almacen(raiz, "MBT").parent / doc["archivo"]).read_bytes() == contenido  # original en su lugar


def test_pendiente_previo_sin_patente_legible_sigue_pendiente_con_sus_candidatos(raiz):
    documento_id, contenido = _recibir(raiz, "dfv_combo", chofer=COMBO, patente=OTRO_TRACTO)
    _identificar(raiz, OCRFalso({contenido: ["PATENTE BPHK67"]}))
    patente, doc = _ubicar(raiz, documento_id)
    assert patente is None
    assert doc["clasificacion"]["motivo"] == "LECTURA_DUDOSA"
    assert doc["clasificacion"]["motivo_asignacion"] == "TRACTO_Y_CARRO"
    assert doc["clasificacion"]["candidatos"] == sorted({TRACTO, OTRO_TRACTO, CARRO})


# ---------------------------------------------------------------- idempotencia y resguardos


def test_cada_documento_se_lee_una_sola_vez(raiz):
    _, contenido = _recibir(raiz, "dfv_1")
    _identificar(raiz, OCRFalso({contenido: ["PATENTE ZZXY99"]}))
    revision = leer_almacen(raiz, empresa="MBT")["revision"]
    llamadas = []
    resumen = identificar_patentes_documentos(raiz, comprobar=lambda: None, fabrica_ocr=lambda: llamadas.append(1))
    assert resumen["pendientes"] == 0 and not llamadas
    assert leer_almacen(raiz, empresa="MBT")["revision"] == revision


def test_documentos_nuevos_y_pendientes_previos_en_la_misma_pasada(raiz):
    previo, c1 = _recibir(raiz, "dfv_previo", chofer=COMBO, patente=OTRO_TRACTO)
    nuevo, c2 = _recibir(raiz, "dfv_nuevo", tipo="REVISION_TECNICA")
    resumen = _identificar(raiz, OCRFalso({c1: ["PATENTE DDKL45"], c2: ["PATENTE BPHR67"]}))
    assert sorted(a["patente"] for a in resumen["asociados"]) == sorted([OTRO_TRACTO, TRACTO])
    assert _ubicar(raiz, previo)[0] == OTRO_TRACTO and _ubicar(raiz, nuevo)[0] == TRACTO


def test_clasificacion_humana_nunca_se_reevalua(raiz):
    documento_id, contenido = _recibir(raiz, "dfv_humano", chofer=COMBO, patente=OTRO_TRACTO)
    datos = leer_almacen(raiz, empresa="MBT")
    datos[PENDIENTES][0]["clasificacion_humana"] = {"autor": "Javier", "patente": CARRO}
    ruta_almacen(raiz, "MBT").write_text(json.dumps(datos), encoding="utf-8")
    llamadas = []
    assert identificar_patentes_documentos(raiz, comprobar=lambda: None,
                                           fabrica_ocr=lambda: llamadas.append(1))["pendientes"] == 0
    assert not llamadas and "identificacion_patente" not in _ubicar(raiz, documento_id)[1]


def test_pdf_y_error_de_ocr_quedan_por_clasificar_sin_repetir(raiz):
    pdf_id, _ = _recibir(raiz, "dfv_pdf", contenido=b"%PDF-1.4 permiso", mime="application/pdf",
                         tipo="PERMISO_CIRCULACION")
    falla_id, contenido = _recibir(raiz, "dfv_falla", tipo="REVISION_TECNICA")
    ocr = OCRFalso({contenido: RuntimeError("OCR caído")})
    _identificar(raiz, ocr)
    assert ocr.leidas == [contenido]  # el PDF no pasa por OCR
    assert _ubicar(raiz, pdf_id)[1]["clasificacion"]["motivo"] == "FORMATO_SIN_OCR"
    assert _ubicar(raiz, falla_id)[1]["clasificacion"]["motivo"] == "ERROR_OCR"
    llamadas = []
    assert identificar_patentes_documentos(raiz, comprobar=lambda: None,
                                           fabrica_ocr=lambda: llamadas.append(1))["pendientes"] == 0


def test_original_alterado_no_se_decide_y_se_reintenta(raiz):
    documento_id, contenido = _recibir(raiz, "dfv_1")
    _, doc = _ubicar(raiz, documento_id)
    (ruta_almacen(raiz, "MBT").parent / doc["archivo"]).write_bytes(contenido + b"alterado")
    antes = ruta_almacen(raiz, "MBT").read_bytes()
    resumen = _identificar(raiz, OCRFalso({}))
    assert "huella" in resumen["errores"][0]["error"] and ruta_almacen(raiz, "MBT").read_bytes() == antes


def test_lease_perdido_no_publica(raiz):
    _, contenido = _recibir(raiz, "dfv_1")
    antes = ruta_almacen(raiz, "MBT").read_bytes()

    def perdido():
        raise PermissionError("lease perdido")

    with pytest.raises(PermissionError):
        _identificar(raiz, OCRFalso({contenido: ["PATENTE BPHR67"]}), comprobar=perdido)
    assert ruta_almacen(raiz, "MBT").read_bytes() == antes


def test_catalogo_y_asignaciones_no_se_modifican(raiz):
    _, contenido = _recibir(raiz, "dfv_1")
    catalogos = {p.name: p.read_bytes() for p in (raiz / "catalogos_privados").iterdir()}
    _identificar(raiz, OCRFalso({contenido: ["PATENTE JF9575"]}))
    assert {p.name: p.read_bytes() for p in (raiz / "catalogos_privados").iterdir()} == catalogos
