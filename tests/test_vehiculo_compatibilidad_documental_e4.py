"""Bloque VEHÍCULO E4 -- compatibilidad documental.

Caso real 474708 (guía de Carlos Simón, 26-09-2026): OCR rampla "JE6159",
tracto "BJCH72"; la rampla real, confirmada por un humano, es "JE6359".
El motor elegía "JD8659" (la rampla habitual del chofer con su otro
tracto) por historial, aunque difiere en 3 de 6 caracteres de lo leído, y
además contaba como "decisión humana previa" una resolución automática.

Regla: el historial corrige errores OCR pero nunca impone una patente que
el documento no puede haber querido decir; el contexto del mismo
documento (el otro vehículo) es evidencia; dos candidatas plausibles se
preguntan. Todo sintético en `tmp_path`.
"""
from __future__ import annotations

from atlas_core.catalogo_vehiculos import TipoVehiculo, cargar_catalogo_vehiculos
from atlas_core.decisiones_pendientes import (
    RESULTADO_RESUELTO_AUTOMATICAMENTE, RESULTADO_SUGERENCIA_HUMANA, evaluar_evidencia_patente,
)
from test_desempate_vehiculo_contextual_e3 import RUT_CARLOS, _cat, _confirmar

RUT_OTRO = "17.123.456-7"


def _fila(transporte, rut, tracto, rampla, guia="1"):
    return {"numero_guia": guia, "numero_transporte": transporte, "rut_chofer": rut,
            "patente_tracto": tracto, "patente_rampla": rampla}


def _vehiculos(cat):
    return list(cargar_catalogo_vehiculos(cat / "vehiculos.json").homologables())


def _evaluar(cat, filas, *, valor="JE6159", contexto="BJCH72", decisiones=(), tipo="CARRO"):
    return evaluar_evidencia_patente(
        campo="patente_rampla", valor_documental=valor, rut_chofer=RUT_CARLOS, tipo_esperado=tipo,
        numero_transporte_actual="T-ACTUAL", filas=filas, vehiculos=_vehiculos(cat),
        decisiones_aplicadas=decisiones, patente_contexto=contexto,
    )


def _escenario_474708(tmp_path):
    cat = _cat(tmp_path)
    _confirmar(cat, "JD8659", rut_chofer_asociado=RUT_CARLOS)   # rampla habitual del chofer
    _confirmar(cat, "JE6359")                                   # rampla real de este viaje
    _confirmar(cat, "BJCH72", TipoVehiculo.TRACTO)
    filas = [
        _fila("T-A", RUT_CARLOS, "VP8521", "JD8659"), _fila("T-B", RUT_CARLOS, "VP8521", "JD8659"),
        _fila("T-C", RUT_CARLOS, "VP8521", "JD8659"),
        _fila("T-D", RUT_OTRO, "BJCH72", "JE6359"), _fila("T-E", RUT_OTRO, "BJCH72", "JE6359"),
        _fila("T-ACTUAL", RUT_CARLOS, "BJCH72", "JE6159"),
    ]
    automatica_previa = {
        "tipo": "VEHICULO_DESCONOCIDO", "accion": "SELECCIONAR_OTRA_PATENTE", "actor": "ATLAS_AUTOMATICO",
        "campo": "patente_rampla", "rut_chofer": RUT_CARLOS, "patente_canonica": "JD8659", "tipo_vehiculo": "CARRO",
    }
    return cat, filas, [automatica_previa]


def test_474708_lectura_y_tracto_resuelven_la_rampla_documentalmente_compatible(tmp_path):
    cat, filas, ledger = _escenario_474708(tmp_path)

    resultado = _evaluar(cat, filas, decisiones=ledger)

    assert resultado["resultado"] == RESULTADO_RESUELTO_AUTOMATICAMENTE
    assert resultado["ganadora"] == "JE6359"
    assert resultado["candidatos"][0]["patente"] == "JE6359"
    assert "COMBINACION_VEHICULO_CONOCIDA(2)" in resultado["candidatos"][0]["evidencias"]


def test_resolucion_automatica_previa_no_cuenta_como_decision_humana(tmp_path):
    cat, filas, ledger = _escenario_474708(tmp_path)
    jd = next(c for c in _evaluar(cat, filas, decisiones=ledger)["candidatos"] if c["patente"] == "JD8659")
    assert "DECISION_HUMANA_PREVIA_MISMO_RUT" not in jd["evidencias"]

    humana = [{**ledger[0], "actor": "JAVIER_MBT"}]
    jd = next(c for c in _evaluar(cat, filas, decisiones=humana)["candidatos"] if c["patente"] == "JD8659")
    assert "DECISION_HUMANA_PREVIA_MISMO_RUT" in jd["evidencias"]


def test_historial_fuerte_no_se_impone_a_una_lectura_incompatible(tmp_path):
    """Sin la rampla compatible en el catálogo, sólo queda la del historial
    (a 3 caracteres de lo leído): se pregunta, nunca se asigna."""
    cat = _cat(tmp_path)
    _confirmar(cat, "JD8659", rut_chofer_asociado=RUT_CARLOS)
    filas = [_fila("T-A", RUT_CARLOS, "VP8521", "JD8659"), _fila("T-ACTUAL", RUT_CARLOS, "BJCH72", "JE6159")]

    resultado = _evaluar(cat, filas, contexto="")

    assert resultado["resultado"] == RESULTADO_SUGERENCIA_HUMANA
    assert "compatible con la lectura" in resultado["explicacion"]


def test_error_ocr_de_un_caracter_con_contexto_unico_se_autocorrige(tmp_path):
    """Tolerancia permanente (caso 472477): JD8629 -> JD8659, única
    candidata compatible, confirmada para el chofer."""
    cat = _cat(tmp_path)
    _confirmar(cat, "JD8659", rut_chofer_asociado=RUT_CARLOS)
    _confirmar(cat, "JE8659")
    filas = [_fila("T-A", RUT_CARLOS, "VP8521", "JE8659")]

    resultado = _evaluar(cat, filas, valor="JD8629", contexto="")

    assert resultado["resultado"] == RESULTADO_RESUELTO_AUTOMATICAMENTE
    assert resultado["ganadora"] == "JD8659"


def test_dos_candidatas_plausibles_obligan_a_preguntar(tmp_path):
    cat = _cat(tmp_path)
    _confirmar(cat, "JE6359")
    _confirmar(cat, "JE6158")
    _confirmar(cat, "BJCH72", TipoVehiculo.TRACTO)
    filas = [_fila("T-D", RUT_OTRO, "BJCH72", "JE6359"), _fila("T-E", RUT_OTRO, "BJCH72", "JE6158")]

    resultado = _evaluar(cat, filas)

    assert resultado["resultado"] == RESULTADO_SUGERENCIA_HUMANA
    assert {c["patente"] for c in resultado["candidatos"]} == {"JE6359", "JE6158"}


def test_historial_del_chofer_no_vence_a_una_candidata_mas_cercana_compatible(tmp_path):
    """La rampla del chofer a 1 carácter y otra a 1 carácter con el mismo
    tracto: ambas plausibles -> se pregunta (antes ganaba el historial)."""
    cat = _cat(tmp_path)
    _confirmar(cat, "JE6169", rut_chofer_asociado=RUT_CARLOS)
    _confirmar(cat, "JE6359")
    _confirmar(cat, "BJCH72", TipoVehiculo.TRACTO)
    filas = [_fila("T-A", RUT_CARLOS, "VP8521", "JE6169"), _fila("T-D", RUT_OTRO, "BJCH72", "JE6359")]

    assert _evaluar(cat, filas)["resultado"] == RESULTADO_SUGERENCIA_HUMANA


def test_contexto_sin_tipo_esperado_o_vehiculo_no_confirmado_no_cuenta(tmp_path):
    cat = _cat(tmp_path)
    _confirmar(cat, "JE6359")
    filas = [_fila("T-D", RUT_OTRO, "BJCH72", "JE6359")]  # BJCH72 no está en el catálogo

    resultado = _evaluar(cat, filas)

    assert resultado["resultado"] != RESULTADO_RESUELTO_AUTOMATICAMENTE
