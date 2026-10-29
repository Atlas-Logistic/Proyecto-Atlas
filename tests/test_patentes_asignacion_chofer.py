"""Patentes intercambiadas o incompletas resueltas por la asignación
chofer->vehículo CONFIRMADA -- caso real 482559 (Mobile, 2026-10-20): el OCR
dejó el carro asignado en el campo del tracto y no encontró el carro. Datos
sintéticos: ningún chofer ni patente real."""
from __future__ import annotations

import json

import pytest

from atlas_core.catalogo_vehiculos import cargar_catalogo_vehiculos
from atlas_core.convergencia_identidad_conocida import (
    RESULTADO_ABSTENCION, RESULTADO_NO_APLICA_VARIABLE, RESULTADO_RESUELTO, RESULTADO_SIN_CAMBIOS,
    RESULTADO_SIN_EVIDENCIA, reconciliar_patentes_por_asignacion_chofer,
)
from atlas_core.procesamiento_masivo import procesar_archivo
from tests.test_patentes_p4 import _bloque, _datos_lineales, _preparar_mocks

RUT = "12.345.678-5"
TRACTO, CARRO, AJENA = "AB1234", "CD5678", "EF9012"


def _vehiculo(patente, tipo, rut="123456785", estado="CONFIRMADO"):
    evidencia = {"tipo": "CONFIRMACION_HUMANA", "identificador_fuente": "TEST", "referencia_hash": "",
                 "campos_observados": {"patente": patente, "tipo": tipo, "rut_chofer_asociado": rut},
                 "fecha": "2026-01-01T00:00:00+00:00", "actor_proceso": "TEST", "resultado": "SOPORTA"}
    return {"vehiculo_id": patente, "patente_canonica": patente, "tipo": tipo, "estado_calidad": estado,
            "estado_vigencia": "ACTIVO", "aliases": [], "evidencias": [evidencia],
            "procedencia": "CONFIRMACION_HUMANA", "confirmado_por": "TEST",
            "fecha_confirmacion": "2026-01-01T00:00:00+00:00", "observaciones": "",
            "fecha_creacion": "2026-01-01T00:00:00+00:00", "fecha_modificacion": "2026-01-01T00:00:00+00:00"}


def _choferes(**extra):
    return {"123456785": {"nombre": "LUIS REYES", "rut": "12345678-5", "aliases": [], "activo": True, **extra}}


def _catalogos(tmp_path, vehiculos, choferes=None):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir(exist_ok=True)
    (carpeta / "vehiculos.json").write_text(json.dumps({"version": 1, "vehiculos": vehiculos}), encoding="utf-8")
    (carpeta / "choferes.json").write_text(json.dumps(choferes or _choferes()), encoding="utf-8")
    return carpeta


def _reconciliar(tmp_path, tracto, carro, *, vehiculos=None, choferes=None, rut=RUT, nombre="LUIS REYES"):
    carpeta = _catalogos(tmp_path, vehiculos if vehiculos is not None
                         else [_vehiculo(TRACTO, "TRACTO"), _vehiculo(CARRO, "CARRO"), _vehiculo(AJENA, "CARRO", rut="")],
                         choferes)
    return reconciliar_patentes_por_asignacion_chofer(
        nombre_documental=nombre, rut_documental=rut, patente_tracto=tracto, patente_carro=carro,
        choferes=choferes or _choferes(),
        vehiculos=cargar_catalogo_vehiculos(carpeta / "vehiculos.json").homologables(),
    )


# ------------------------------------------------------------ regla


def test_patentes_intercambiadas_se_reubican(tmp_path):
    r = _reconciliar(tmp_path, CARRO, TRACTO)
    assert (r.resultado, r.patente_tracto, r.patente_carro) == (RESULTADO_RESUELTO, TRACTO, CARRO)


@pytest.mark.parametrize("tracto,carro", [(CARRO, "No encontrado"), (TRACTO, "No encontrado"), ("No encontrado", CARRO)])
def test_una_patente_ausente_se_completa_desde_la_asignacion(tmp_path, tracto, carro):
    r = _reconciliar(tmp_path, tracto, carro)
    assert (r.resultado, r.patente_tracto, r.patente_carro) == (RESULTADO_RESUELTO, TRACTO, CARRO)


def test_asignacion_ambigua_se_abstiene(tmp_path):
    vehiculos = [_vehiculo(TRACTO, "TRACTO"), _vehiculo("GH3456", "TRACTO"), _vehiculo(CARRO, "CARRO")]
    assert _reconciliar(tmp_path, CARRO, "No encontrado", vehiculos=vehiculos).resultado == RESULTADO_ABSTENCION


def test_asignacion_variable_no_aplica(tmp_path):
    r = _reconciliar(tmp_path, CARRO, "No encontrado", choferes=_choferes(asignacion_variable=True))
    assert r.resultado == RESULTADO_NO_APLICA_VARIABLE


def test_sin_carro_asignado_se_abstiene(tmp_path):
    r = _reconciliar(tmp_path, CARRO, "No encontrado", vehiculos=[_vehiculo(TRACTO, "TRACTO")])
    assert r.resultado != RESULTADO_RESUELTO and r.patente_tracto is None


def test_vehiculo_no_confirmado_no_cuenta_como_asignacion(tmp_path):
    vehiculos = [_vehiculo(TRACTO, "TRACTO"), _vehiculo(CARRO, "CARRO", estado="CANDIDATO")]
    assert _reconciliar(tmp_path, CARRO, "No encontrado", vehiculos=vehiculos).resultado != RESULTADO_RESUELTO


def test_evidencia_contradictoria_otra_patente_se_abstiene(tmp_path):
    r = _reconciliar(tmp_path, TRACTO, AJENA)
    assert r.resultado == RESULTADO_ABSTENCION and AJENA in r.explicacion


def test_evidencia_contradictoria_rut_distinto_se_abstiene(tmp_path):
    assert _reconciliar(tmp_path, CARRO, "No encontrado", rut="11.111.111-1").resultado == RESULTADO_ABSTENCION


def test_sin_rut_documental_se_abstiene(tmp_path):
    assert _reconciliar(tmp_path, CARRO, "No encontrado", rut="No encontrado").resultado == RESULTADO_ABSTENCION


def test_lectura_que_no_es_patente_se_abstiene(tmp_path):
    assert _reconciliar(tmp_path, "CD567", "No encontrado").resultado == RESULTADO_ABSTENCION


def test_sin_ninguna_patente_leida_no_inventa(tmp_path):
    assert _reconciliar(tmp_path, "No encontrado", "No encontrado").resultado == RESULTADO_SIN_EVIDENCIA


def test_lectura_correcta_no_cambia(tmp_path):
    assert _reconciliar(tmp_path, TRACTO, CARRO).resultado == RESULTADO_SIN_CAMBIOS


# ------------------------------------------------------------ extracción real


def _procesar(tmp_path, monkeypatch, valor_patente):
    carpeta = _catalogos(tmp_path, [_vehiculo(TRACTO, "TRACTO"), _vehiculo(CARRO, "CARRO"),
                                    _vehiculo(AJENA, "TRACTO", rut="")])
    bloques = [
        _bloque("RETIRA", 20, 20, 60),
        _bloque("PATENTE", 20, 50, 70), _bloque(valor_patente, 120, 50, 70),
        _bloque("FECHA LLEGADA", 20, 80, 120),
    ]
    _preparar_mocks(monkeypatch, bloques, _datos_lineales(chofer="LUIS REYES", **{"RUT del chofer": RUT}))
    return procesar_archivo(tmp_path / "guia.jpg", carpeta_catalogos=carpeta)


def test_regresion_482559_carro_leido_como_tracto_y_carro_ausente(tmp_path, monkeypatch):
    resultado = _procesar(tmp_path, monkeypatch, CARRO)

    assert (resultado["patente_tracto"], resultado["patente_rampla"]) == (TRACTO, CARRO)
    assert "PATENTE_SIN_HOMOLOGAR" not in resultado["motivos_revision_documento"]
    assert "ASIGNACION_CHOFER_VEHICULO" in resultado["metodos_recuperacion_documento"]
    metricas = json.loads(resultado["metricas_procesamiento_json"])
    # Integración CASA+OFICINA: la reclasificación por asignación vigente
    # (CASA, 482953/482772/482902) devuelve primero el carro a su campo; la
    # lectura OCR original queda en `reclasificacion_patentes` y esta traza
    # recibe ese valor ya reclasificado para completar el tracto ausente.
    assert metricas["reclasificacion_patentes"]["tracto_leido"] == CARRO
    assert metricas["reclasificacion_patentes"]["carro_leido"] == "No encontrado"
    traza = metricas["patentes_por_asignacion_chofer"]
    assert traza["resultado"] == RESULTADO_RESUELTO
    assert traza["valor_ocr"] == {"patente_tracto": "No encontrado", "patente_rampla": CARRO}
    assert traza["valor_aplicado"] == {"patente_tracto": TRACTO, "patente_rampla": CARRO}


def test_patente_de_otro_vehiculo_conserva_lectura_y_revision(tmp_path, monkeypatch):
    resultado = _procesar(tmp_path, monkeypatch, AJENA)

    assert resultado["patente_tracto"] == AJENA  # nunca se reemplaza un vehículo distinto
    assert resultado["patente_rampla"] == "No encontrado"
    assert "ASIGNACION_CHOFER_VEHICULO" not in resultado["metodos_recuperacion_documento"]
    traza = json.loads(resultado["metricas_procesamiento_json"])["patentes_por_asignacion_chofer"]
    assert traza["resultado"] == RESULTADO_ABSTENCION and traza["valor_aplicado"] is None
