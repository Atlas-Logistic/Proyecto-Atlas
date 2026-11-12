"""Corrección manual de fechas de emisión y vencimiento de documentos de fichas.

Sólo datos sintéticos en tmp_path (la sesión oficial corre sin lease fuera de
una unidad compartida). Casos: documento sin fecha de emisión, con vencimiento
erróneo leído por OCR, con corrección previa, pendientes que no se corrigen
aquí, y OCR posterior que no sobrescribe lo corregido.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from atlas_core import cli_fichas_catalogos
from atlas_core import extraccion_vencimientos_vehiculos as modulo_vehiculos
from atlas_core.correccion_fechas_documentales import (
    ESTADO_VENCIMIENTO_CORREGIDO, ErrorCorreccionFechas, corregir_fechas_documento, previsualizar_correccion_fechas,
)
from atlas_core.desktop_operacion import ESCRITORES
from atlas_core.expediente_digital import (
    consultar_expediente, estado_expediente, leer_expediente, preparar_alertas_vencimiento, registrar_documento,
    ruta_almacen_expediente,
)
from atlas_core.fichas_choferes import leer_almacen, ruta_almacen
from tests.test_extraccion_vencimientos_vehiculos import (  # noqa: F401
    OCRFalso as OCRVehiculo, _documentos, _extraer, _recibir, _ubicar, raiz,
)
from tests.test_identificacion_patentes import SOLO, TRACTO
from tests.test_licencia_extraccion_automatica import (
    REF, OCRFalso as OCRLicencia, _adjuntar, _doc, _ficha, _licencia_confirmada, _pdf_texto, _pull, _raiz,
)

RAIZ_MOTOR = Path(__file__).resolve().parent.parent
HOY = date(2026, 11, 12)
reloj = lambda: datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)  # noqa: E731
sha = lambda b: hashlib.sha256(b).hexdigest()  # noqa: E731


def _previa(raiz, entidad, referencia, documento_id, **propuesta):
    return previsualizar_correccion_fechas(raiz, empresa="MBT", entidad=entidad, referencia=referencia,
                                           documento_id=documento_id, propuesta=propuesta, reloj=reloj)


def _corregir(raiz, entidad, referencia, documento_id, autor="Javier Prueba", motivo="OCR leyó mal", **propuesta):
    vista = _previa(raiz, entidad, referencia, documento_id, **propuesta)
    assert vista["puede_guardar"], vista["error"]
    return corregir_fechas_documento(raiz, empresa="MBT", entidad=entidad, referencia=referencia,
                                     documento_id=documento_id, sha256=vista["documento"]["sha256"],
                                     propuesta=propuesta, autor=autor, motivo=motivo, clave=vista["clave"],
                                     confirmacion_humana=True, reloj=reloj)


def _bytes_almacen(raiz):
    return ruta_almacen(raiz, "MBT").read_bytes()


def _originales(raiz):
    carpeta = ruta_almacen(raiz, "MBT").parent / "archivos"
    return {p.relative_to(carpeta).as_posix(): sha(p.read_bytes()) for p in carpeta.rglob("*") if p.is_file()}


def _licencia_automatica(tmp_path):
    """Licencia adjuntada en Desktop y registrada sola por OCR: vencimiento 2029-03-15 sin emisión."""
    raiz = _raiz(tmp_path)
    resultado = _adjuntar(raiz, _pdf_texto(tmp_path))
    assert resultado["estado"] == "REGISTRADA"
    return raiz, resultado["documento_id"]


# ---------------------------------------------------------------- vista previa


def test_vista_previa_muestra_actuales_origen_y_vigencia_sin_escribir(tmp_path):
    raiz, documento_id = _licencia_automatica(tmp_path)
    antes, originales = _bytes_almacen(raiz), _originales(raiz)
    vista = _previa(raiz, "CHOFER", REF, documento_id, fecha_vencimiento="2026-11-30", fecha_emision="2020-03-15")
    assert vista["actuales"] == {"fecha_emision": "", "fecha_vencimiento": "2029-03-15"}
    assert vista["origen"] == {"fecha_emision": "SIN_DATO", "fecha_vencimiento": "OCR_AUTOMATICO"}
    assert vista["leido_ocr"]["fecha_vencimiento"] == "2029-03-15"
    assert vista["cambios"] == {"fecha_emision": {"antes": "", "despues": "2020-03-15"},
                                "fecha_vencimiento": {"antes": "2029-03-15", "despues": "2026-11-30"}}
    assert vista["vigencia"]["antes"]["estado"] == "VIGENTE"
    assert vista["vigencia"]["despues"] == {"estado": "POR_VENCER", "dias_para_vencer": 18}
    assert vista["puede_guardar"] and vista["documento"]["fuente"] == "FICHA_CHOFER" and len(vista["clave"]) == 32
    assert _bytes_almacen(raiz) == antes and _originales(raiz) == originales


@pytest.mark.parametrize("propuesta,error", [
    ({"fecha_emision": "2026-11-13"}, "no puede ser futura"),
    ({"fecha_emision": "2029-03-16"}, "no puede ser futura"),
    ({"fecha_vencimiento": "2020-01-01", "fecha_emision": "2021-01-01"}, "posterior al vencimiento"),
    ({"fecha_vencimiento": "0202-03-15"}, "no es plausible"),
    ({"fecha_vencimiento": "2099-03-15"}, "no es plausible"),
    ({"fecha_emision": "1900-01-01"}, "no es plausible"),
    ({"fecha_vencimiento": "2029-03-15"}, "Sin cambios"),
    ({}, "Sin cambios"),
])
def test_fechas_invalidas_o_sin_cambios_no_se_pueden_guardar(tmp_path, propuesta, error):
    raiz, documento_id = _licencia_automatica(tmp_path)
    vista = _previa(raiz, "CHOFER", REF, documento_id, **propuesta)
    assert not vista["puede_guardar"] and error in vista["error"]
    antes = _bytes_almacen(raiz)
    with pytest.raises(ErrorCorreccionFechas, match=error):
        corregir_fechas_documento(raiz, empresa="MBT", entidad="CHOFER", referencia=REF, documento_id=documento_id,
                                  sha256=vista["documento"]["sha256"], propuesta=propuesta, autor="Javier",
                                  clave=vista["clave"], confirmacion_humana=True, reloj=reloj)
    assert _bytes_almacen(raiz) == antes


@pytest.mark.parametrize("valor", ["15/03/2029", "2029-02-30", "mañana", "2029-3-1"])
def test_formato_de_fecha_invalido_se_rechaza(tmp_path, valor):
    raiz, documento_id = _licencia_automatica(tmp_path)
    with pytest.raises(ErrorCorreccionFechas, match="no es válida"):
        _previa(raiz, "CHOFER", REF, documento_id, fecha_vencimiento=valor)


# ---------------------------------------------------------------- licencia (ficha del chofer)


def test_corrige_vencimiento_ocr_y_completa_emision_sin_tocar_lo_demas(tmp_path):
    raiz = _raiz(tmp_path)
    otra = _licencia_confirmada(raiz, tmp_path, vencimiento="2027-01-31")  # la reemplaza la automática
    documento_id = _adjuntar(raiz, _pdf_texto(tmp_path))["documento_id"]
    otra_antes = copy.deepcopy(_doc(raiz, otra))
    assert otra_antes["reemplazado_por"] == documento_id
    with pytest.raises(ErrorCorreccionFechas, match="reemplazado"):
        _previa(raiz, "CHOFER", REF, otra, fecha_vencimiento="2027-02-28")
    previo, originales = copy.deepcopy(_doc(raiz, documento_id)), _originales(raiz)
    resultado = _corregir(raiz, "CHOFER", REF, documento_id, fecha_vencimiento="2029-03-25", fecha_emision="2023-03-15")
    assert resultado["ok"] and resultado["fuente"] == "FICHA_CHOFER"
    assert resultado["fecha_vencimiento"] == "2029-03-25" and resultado["fecha_emision"] == "2023-03-15"
    doc = _doc(raiz, documento_id)
    assert doc["vencimiento"] == "2029-03-25" and doc["emision"] == "2023-03-15"
    # El vencimiento deja de ser automático; la lectura y el registro automático originales se conservan.
    assert previo["estado_revision"] == "VENCIMIENTO_OCR_AUTOMATICO"
    assert doc["estado_revision"] == ESTADO_VENCIMIENTO_CORREGIDO
    assert doc["extraccion_automatica"] == previo["extraccion_automatica"]
    assert doc["registro_automatico"] == previo["registro_automatico"]
    correccion = doc["correcciones_fechas"][-1]
    assert correccion["autor"] == "Javier Prueba" and correccion["confirmacion_humana"] is True
    assert correccion["cambios"]["fecha_vencimiento"] == {"antes": "2029-03-15", "despues": "2029-03-25"}
    assert correccion["sha256"] == doc["sha256"] == previo["sha256"]
    assert doc["fechas_confirmadas"]["fecha_vencimiento"]["valor"] == "2029-03-25"
    for clave in ("vencimiento", "emision", "estado_revision", "correcciones_fechas", "fechas_confirmadas"):
        doc.pop(clave, None); previo.pop(clave, None)
    assert doc == previo  # clase, titular, archivo, huella, origen intactos
    assert _originales(raiz) == originales
    historial = [h for h in _ficha(raiz)["historial"] if h.get("documento_id") == documento_id]
    assert historial[-1]["accion"] == "FECHAS_DOCUMENTO_CORREGIDAS" and historial[-1]["autor"] == "Javier Prueba"
    respaldo = Path(resultado["respaldo"])
    assert json.loads((respaldo / "manifest.json").read_text(encoding="utf-8"))["operacion"] == "FECHAS_DOCUMENTO_CORREGIDAS"
    assert (respaldo / "fichas_documentales.json").is_file()
    assert _doc(raiz, otra) == otra_antes


def test_solo_emision_no_confirma_el_vencimiento_automatico(tmp_path):
    raiz, documento_id = _licencia_automatica(tmp_path)
    _corregir(raiz, "CHOFER", REF, documento_id, fecha_emision="2023-03-15")
    doc = _doc(raiz, documento_id)
    assert doc["emision"] == "2023-03-15" and doc["vencimiento"] == "2029-03-15"
    assert doc["estado_revision"] == "VENCIMIENTO_OCR_AUTOMATICO"  # sigue sin confirmación humana
    assert set(doc["fechas_confirmadas"]) == {"fecha_emision"}
    vista = consultar_expediente(raiz, empresa="MBT", entidad="CHOFER", referencia=REF, hoy=HOY)
    licencia = next(d for d in vista["documentos"] if d["documento_id"] == documento_id)
    assert licencia["fecha_emision"] == "2023-03-15" and licencia["confirmado_por_humano"] is False


def test_correccion_previa_se_conserva_y_una_nueva_la_corrige(tmp_path):
    raiz, documento_id = _licencia_automatica(tmp_path)
    _corregir(raiz, "CHOFER", REF, documento_id, fecha_vencimiento="2029-03-25")
    vista = _previa(raiz, "CHOFER", REF, documento_id, fecha_vencimiento="2029-03-20")
    assert vista["origen"]["fecha_vencimiento"] == "CORRECCION_MANUAL" and vista["correcciones_anteriores"] == 1
    _corregir(raiz, "CHOFER", REF, documento_id, autor="Otra Persona", fecha_vencimiento="2029-03-20")
    doc = _doc(raiz, documento_id)
    assert [c["cambios"]["fecha_vencimiento"] for c in doc["correcciones_fechas"]] == [
        {"antes": "2029-03-15", "despues": "2029-03-25"}, {"antes": "2029-03-25", "despues": "2029-03-20"}]
    assert doc["vencimiento"] == "2029-03-20" and doc["fechas_confirmadas"]["fecha_vencimiento"]["autor"] == "Otra Persona"
    assert doc["correcciones_fechas"][1]["estado_revision_anterior"] == ESTADO_VENCIMIENTO_CORREGIDO


def test_licencia_confirmada_por_persona_tambien_se_corrige(tmp_path):
    raiz = _raiz(tmp_path)
    documento_id = _licencia_confirmada(raiz, tmp_path, vencimiento="2027-01-31")
    estado = _doc(raiz, documento_id).get("estado_revision")
    _corregir(raiz, "CHOFER", REF, documento_id, fecha_vencimiento="2028-01-31", fecha_emision="2022-01-31")
    doc = _doc(raiz, documento_id)
    assert (doc["vencimiento"], doc["emision"], doc.get("estado_revision")) == ("2028-01-31", "2022-01-31", estado)


def test_licencia_pendiente_de_extraccion_se_completa_en_su_revision(tmp_path):
    raiz = _raiz(tmp_path)
    archivo = tmp_path / "foto.jpg"
    archivo.write_bytes(b"\xff\xd8\xff\xe0foto de licencia")
    resultado = _adjuntar(raiz, archivo)  # foto: queda para el ciclo PULL
    assert resultado["estado"] == "LECTURA_PENDIENTE"
    with pytest.raises(ErrorCorreccionFechas, match="pendiente de extracción o de revisión"):
        _previa(raiz, "CHOFER", REF, resultado["documento_id"], fecha_vencimiento="2029-01-01")


def test_documento_de_otra_ficha_o_inexistente_se_rechaza(tmp_path):
    raiz, documento_id = _licencia_automatica(tmp_path)
    with pytest.raises(ErrorCorreccionFechas, match="no pertenece"):
        _previa(raiz, "CHOFER", "111111111", documento_id, fecha_vencimiento="2029-01-01")
    with pytest.raises(ErrorCorreccionFechas, match="no existe"):
        _previa(raiz, "CHOFER", REF, "00000000-0000-4000-8000-000000000000", fecha_vencimiento="2029-01-01")


def test_sin_confirmacion_humana_autor_o_clave_vigente_no_escribe(tmp_path):
    raiz, documento_id = _licencia_automatica(tmp_path)
    vista = _previa(raiz, "CHOFER", REF, documento_id, fecha_vencimiento="2029-03-25")
    base = dict(empresa="MBT", entidad="CHOFER", referencia=REF, documento_id=documento_id,
                sha256=vista["documento"]["sha256"], propuesta={"fecha_vencimiento": "2029-03-25"}, autor="Javier",
                clave=vista["clave"], confirmacion_humana=True, reloj=reloj)
    antes = _bytes_almacen(raiz)
    for cambio, error in (({"confirmacion_humana": False}, "confirmación"), ({"autor": " "}, "quién revisó"),
                          ({"sha256": "0" * 64}, "cambió"), ({"clave": "f" * 32}, "cambiaron"),
                          ({"propuesta": {"fecha_vencimiento": "2029-03-26"}}, "cambiaron")):
        with pytest.raises(ErrorCorreccionFechas, match=error):
            corregir_fechas_documento(raiz, **{**base, **cambio})
    # Otra corrección entre la vista previa y el guardado invalida la clave.
    _corregir(raiz, "CHOFER", REF, documento_id, fecha_emision="2023-03-15")
    with pytest.raises(ErrorCorreccionFechas, match="cambiaron"):
        corregir_fechas_documento(raiz, **base)
    assert _doc(raiz, documento_id)["vencimiento"] == "2029-03-15"
    assert _bytes_almacen(raiz) != antes  # sólo por la corrección de emisión


def test_ocr_posterior_no_sobrescribe_la_licencia_corregida(tmp_path):
    raiz, documento_id = _licencia_automatica(tmp_path)
    _corregir(raiz, "CHOFER", REF, documento_id, fecha_vencimiento="2029-03-25")
    corregido = copy.deepcopy(_doc(raiz, documento_id))
    ocr = OCRLicencia(["LICENCIA DE CONDUCTOR", "FECHA DE CONTROL", "01/01/2030"])
    resumen = _pull(raiz, ocr)
    assert ocr.leidas == [] and not resumen.get("registrados")
    assert _doc(raiz, documento_id) == corregido


# ---------------------------------------------------------------- documentos de vehículo (ficha del vehículo)


def _vehiculo_automatico(raiz):
    textos, ids = _documentos(raiz)
    _extraer(raiz, OCRVehiculo(textos))
    return textos, ids


def test_corrige_vencimiento_ocr_de_soap_y_la_vigencia_y_alertas_lo_siguen(raiz):
    textos, ids = _vehiculo_automatico(raiz)
    soap = ids["SOAP"]
    _, previo = copy.deepcopy(_ubicar(raiz, soap))
    otros = {t: copy.deepcopy(_ubicar(raiz, i)) for t, i in ids.items() if t != "SOAP"}
    originales = _originales(raiz)
    assert not [a for a in preparar_alertas_vencimiento(raiz, empresa="MBT", hoy=HOY) if a["documento_id"] == soap]
    # El OCR leyó 30/09/2027; el original dice 30/11/2026: queda próximo a vencer y genera alerta.
    resultado = _corregir(raiz, "VEHICULO", TRACTO, soap, fecha_vencimiento="2026-11-30", fecha_emision="2025-11-28")
    assert resultado["fuente"] == "FICHA_VEHICULO" and resultado["vigencia"]["estado"] == "POR_VENCER"
    patente, doc = _ubicar(raiz, soap)
    assert patente == TRACTO and doc["vencimiento"] == "2026-11-30" and doc["emision"] == "2025-11-28"
    assert doc["estado_revision"] == ESTADO_VENCIMIENTO_CORREGIDO
    assert doc["vencimiento_registro"] == previo["vencimiento_registro"]  # el registro automático queda como antecedente
    assert doc["extraccion_automatica"] == previo["extraccion_automatica"]
    assert {t: _ubicar(raiz, i) for t, i in ids.items() if t != "SOAP"} == otros
    assert _originales(raiz) == originales
    alertas = [a for a in preparar_alertas_vencimiento(raiz, empresa="MBT", hoy=HOY) if a["documento_id"] == soap]
    assert [(a["nivel"], a["fecha_vencimiento"]) for a in alertas] == [("POR_VENCER", "2026-11-30")]
    vista = next(d for d in estado_expediente(raiz, empresa="MBT", hoy=HOY) if d["documento_id"] == soap)
    assert (vista["fecha_emision"], vista["fecha_vencimiento"], vista["estado_vencimiento"]) == (
        "2025-11-28", "2026-11-30", "POR_VENCER")
    assert vista["confirmado_por_humano"] is True and vista["correccion_fechas"]["autor"] == "Javier Prueba"
    ficha = next(v for v in leer_almacen(raiz, empresa="MBT")["vehiculos"] if v["patente"] == TRACTO)
    assert ficha["historial"][-1]["accion"] == "FECHAS_DOCUMENTO_CORREGIDAS"
    # Corregido a una fecha ya pasada: vencido y con alerta de vencido.
    _corregir(raiz, "VEHICULO", TRACTO, soap, fecha_vencimiento="2026-11-01")
    alertas = [a for a in preparar_alertas_vencimiento(raiz, empresa="MBT", hoy=HOY) if a["documento_id"] == soap]
    assert [a["nivel"] for a in alertas] == ["VENCIDO"]


def test_ocr_posterior_no_relee_ni_sobrescribe_el_documento_vehicular_corregido(raiz, monkeypatch):
    textos, ids = _vehiculo_automatico(raiz)
    _corregir(raiz, "VEHICULO", TRACTO, ids["REVISION_TECNICA"], fecha_vencimiento="2027-03-26")
    corregido = copy.deepcopy(_ubicar(raiz, ids["REVISION_TECNICA"]))
    monkeypatch.setattr(modulo_vehiculos, "VERSION_EXTRACCION", modulo_vehiculos.VERSION_EXTRACCION + 1)
    segundo = OCRVehiculo(textos)
    resumen = _extraer(raiz, segundo)
    assert segundo.leidas == [] and resumen["activados"] == []
    assert _ubicar(raiz, ids["REVISION_TECNICA"]) == corregido


def test_documento_vehicular_pendiente_o_sin_clasificar_no_se_corrige_aqui(raiz):
    pendiente, _ = _recibir(raiz, "soap-sin-leer", tipo="SOAP")  # sin OCR: queda por clasificar
    with pytest.raises(ErrorCorreccionFechas, match="no está asignado|pendiente"):
        _previa(raiz, "VEHICULO", TRACTO, pendiente, fecha_vencimiento="2027-01-01")


def test_poliza_corregida_conserva_sus_coberturas_leidas(raiz):
    from atlas_core.expediente_digital import _vista_coberturas
    documento = {"tipo": "POLIZA_ROBO", "fuente": "FICHA_VEHICULO", "sha256": "a" * 64, "archivo": "archivos/x.pdf",
                 "patente_ficha": TRACTO, "fecha_vencimiento": "2027-05-01", "pendiente_revision": False,
                 "identificacion_patente": {"estado": "ASOCIADA", "evidencia": ["x"], "patente": TRACTO},
                 "asociacion": {"metodo": "PATENTE_DOCUMENTAL", "patente": TRACTO},
                 "vencimiento_registro": {"procedencia": "OCR_AUTOMATICO", "sha256": "a" * 64},
                 "extraccion_automatica": {"procedencia": "AUTOMATICA_OCR", "archivos": [{"sha256": "a" * 64, "archivo": "archivos/x.pdf"}],
                                           "campos": {"vencimiento": {"estado": "EXTRAIDO", "valor": "2027-04-01", "evidencia": ["e"], "motivo": ""},
                                                      "coberturas": {"estado": "EXTRAIDO", "valor": ["POLIZA_ROBO", "POLIZA_RESPONSABILIDAD_CIVIL"],
                                                                     "evidencia": ["c"], "motivo": ""}}}}
    # Sin corrección humana, un vencimiento distinto del leído no acredita coberturas.
    assert _vista_coberturas(documento)["tipos_cubiertos"] == []
    corregido = {**documento, "fechas_confirmadas": {"fecha_vencimiento": {"valor": "2027-05-01", "sha256": "a" * 64}}}
    assert _vista_coberturas(corregido)["tipos_cubiertos"] == ["POLIZA_RESPONSABILIDAD_CIVIL", "POLIZA_ROBO"]
    otro_original = {**documento, "fechas_confirmadas": {"fecha_vencimiento": {"valor": "2027-05-01", "sha256": "b" * 64}}}
    assert _vista_coberturas(otro_original)["tipos_cubiertos"] == []


# ---------------------------------------------------------------- documentos del expediente


def test_documento_del_expediente_se_corrige_con_historial(raiz):
    documento = registrar_documento(raiz, empresa="MBT", entidad="VEHICULO", referencia=TRACTO, tipo="SEGURO_CARGA",
                                    actor="DESKTOP", fecha_vencimiento="2027-06-30", contenido=b"%PDF-1.4 seguro",
                                    mime_type="application/pdf", reloj=reloj)
    original = ruta_almacen_expediente(raiz, "MBT").parent / documento["archivo"]
    huella = sha(original.read_bytes())
    resultado = _corregir(raiz, "VEHICULO", TRACTO, documento["documento_id"], fecha_emision="2026-06-30",
                          fecha_vencimiento="2027-07-31")
    assert resultado["fuente"] == "EXPEDIENTE"
    datos = leer_expediente(raiz, empresa="MBT")
    doc = next(d for d in datos["documentos"] if d["documento_id"] == documento["documento_id"])
    assert (doc["fecha_emision"], doc["fecha_vencimiento"], doc["sha256"]) == ("2026-06-30", "2027-07-31", huella)
    evento = datos["historial"][-1]
    assert evento["operacion"] == "FECHAS_DOCUMENTO_CORREGIDAS" and evento["autor"] == "Javier Prueba"
    assert evento["cambios"]["fecha_vencimiento"] == {"antes": "2027-06-30", "despues": "2027-07-31"}
    assert sha(original.read_bytes()) == huella
    vista = consultar_expediente(raiz, empresa="MBT", entidad="VEHICULO", referencia=TRACTO, hoy=HOY)
    assert any(e["operacion"] == "FECHAS_DOCUMENTO_CORREGIDAS" for e in vista["trazabilidad"])


# ---------------------------------------------------------------- canales de Desktop


def test_cli_de_lectura_entrega_la_vista_previa(tmp_path, capsys):
    raiz, documento_id = _licencia_automatica(tmp_path)
    antes = _bytes_almacen(raiz)
    codigo = cli_fichas_catalogos.main(["--raiz-atlas", str(raiz), "--expediente-entidad", "CHOFER",
                                        "--expediente-referencia", REF, "--expediente-fechas-documento", documento_id,
                                        "--expediente-fechas-propuesta", json.dumps({"fecha_emision": "2023-03-15"})])
    salida = json.loads(capsys.readouterr().out)
    assert codigo == 0 and salida["cambios"] == {"fecha_emision": {"antes": "", "despues": "2023-03-15"}}
    assert _bytes_almacen(raiz) == antes
    codigo = cli_fichas_catalogos.main(["--raiz-atlas", str(raiz), "--expediente-entidad", "CHOFER",
                                        "--expediente-referencia", REF, "--expediente-fechas-documento", documento_id,
                                        "--expediente-fechas-propuesta", "{no es json"])
    assert codigo == 1 and "ilegible" in capsys.readouterr().err


def test_script_de_escritura_es_un_escritor_del_canal_oficial(tmp_path):
    assert "corregir_fechas_documento.py" in ESCRITORES
    raiz, documento_id = _licencia_automatica(tmp_path)
    vista = previsualizar_correccion_fechas(raiz, empresa="MBT", entidad="CHOFER", referencia=REF,
                                            documento_id=documento_id, propuesta={"fecha_emision": "2023-03-15"})
    entorno = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(RAIZ_MOTOR)}
    argumentos = [sys.executable, str(RAIZ_MOTOR / "corregir_fechas_documento.py"), "--raiz-atlas", str(raiz),
                  "--entidad", "CHOFER", "--referencia", REF, "--documento-id", documento_id,
                  "--sha256", vista["documento"]["sha256"], "--propuesta", json.dumps({"fecha_emision": "2023-03-15"}),
                  "--autor", "Javier", "--clave", vista["clave"]]
    sin_confirmar = subprocess.run(argumentos, capture_output=True, encoding="utf-8", env=entorno, cwd=RAIZ_MOTOR)
    assert sin_confirmar.returncode != 0 and "confirmación" in sin_confirmar.stderr
    hecho = subprocess.run([*argumentos, "--confirmo-revision-humana"], capture_output=True, encoding="utf-8", env=entorno,
                           cwd=RAIZ_MOTOR)
    assert hecho.returncode == 0, hecho.stderr
    assert json.loads(hecho.stdout)["fecha_emision"] == "2023-03-15"
    assert _doc(raiz, documento_id)["emision"] == "2023-03-15"
