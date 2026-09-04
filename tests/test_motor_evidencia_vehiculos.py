"""Bloque VEHÍCULO E1 -- Motor de Evidencia de Vehículos.

Primera capa de razonamiento determinista (nunca IA generativa/LLM) que
combina señales ya existentes -- catálogo, historial documental del
dataset, confirmaciones humanas ya registradas, corrección OCR
ya calibrada -- para explicar (nunca autocorregir) una patente
documental que no homologa. Produce siempre uno de tres resultados:
RESUELTO_AUTOMATICAMENTE (informativo, nunca escribe nada por sí solo),
SUGERENCIA_HUMANA, ABSTENCION.

Caso real que motivó este bloque -- Carlos Simón: el chofer confirmó
directamente a Javier que su rampla es JD8659; ningún documento del
dataset la leyó jamás correctamente por OCR (JD6659/JD0659), mientras
que JE8659 (un error sistemático repetido por UN SOLO mandante/
transporte) sí aparece leída "correctamente" tres veces. La regla
"repetición no equivale a independencia" existe exactamente para que
Atlas no confunda esas tres repeticiones con tres verificaciones
reales."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone

import pytest

from atlas_core.catalogo_vehiculos import TipoVehiculo, cargar_catalogo_vehiculos, confirmar_vehiculo
from atlas_core.decisiones_pendientes import (
    RESULTADO_ABSTENCION,
    RESULTADO_RESUELTO_AUTOMATICAMENTE,
    RESULTADO_SUGERENCIA_HUMANA,
    crear_decision,
    enriquecer_decisiones_vehiculo,
    evaluar_evidencia_patente,
)
from atlas_core.procesamiento_masivo import COLUMNAS

RUT_SIMON = "15489424-1"
RUT_ORTIZ = "18626166-6"
FECHA = "05-08-2026"


def _fila(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "1.jpeg", "estado_procesamiento": "OK", "numero_guia": "1",
        "numero_transporte": "T-1", "fecha": FECHA, "chofer": "CHOFER PRUEBA",
        "rut_chofer": RUT_SIMON, "patente_tracto": "AB1234", "patente_rampla": "CD5678",
    })
    fila.update(overrides)
    return fila


def _confirmar(ruta, patente, tipo, *, rut_chofer_asociado=""):
    return confirmar_vehiculo(
        ruta, patente=patente, tipo=tipo, actor="JAVIER_MBT",
        fuente_decision="TEST", fecha=datetime.now(timezone.utc),
        rut_chofer_asociado=rut_chofer_asociado,
    )


def _catalogo(tmp_path):
    ruta = tmp_path / "vehiculos.json"
    ruta.write_text(json.dumps({"version": 1, "vehiculos": []}), encoding="utf-8")
    return ruta


def test_relacion_historica_aislada_frena_registrar_sin_autocorregir(tmp_path):
    ruta = _catalogo(tmp_path)
    _confirmar(ruta, "TZWR86", TipoVehiculo.TRACTO)
    _confirmar(ruta, "JH5478", TipoVehiculo.CARRO)
    decision = crear_decision(
        tipo="VEHICULO_DESCONOCIDO", entidad="VEHICULO", archivo="464367.jpeg",
        numero_guia="464367", numero_transporte="T-NUEVO", campo="patente_tracto",
        valor_documental="T2MN86", valor_normalizado="T2MN86", identidad_resuelta=None,
        candidatos=(), motivos=("SIN_VEHICULO_CONFIRMADO_COMPATIBLE",),
        evidencias=(), acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        tipo_vehiculo_propuesto="TRACTO",
    )
    salida = enriquecer_decisiones_vehiculo(
        decisiones=[decision], filas=[_fila(numero_guia="464367", numero_transporte="T-NUEVO", rut_chofer="15.925.888-2")],
        vehiculos=cargar_catalogo_vehiculos(ruta).homologables(),
        relaciones_historicas=[{
            "numero_guia": "463630", "numero_transporte": "T-ANTERIOR", "rut_chofer": "15925888-2",
            "patente_tracto": "TZWR86", "patente_rampla": "JH5478",
        }],
    )[0]
    assert salida["evaluacion_evidencia"]["resultado"] == RESULTADO_SUGERENCIA_HUMANA
    assert [c["patente"] for c in salida["candidatos"]] == ["TZWR86"]
    assert "REGISTRAR" not in salida["acciones_permitidas"]
    assert "USAR_PATENTE_EXISTENTE" in salida["acciones_permitidas"]


# ============================================================
# 1/2/3 -- Carlos Simón, los tres casos reales
# ============================================================


def test_simon_rampla_jd6659_resuelve_a_jd8659_confirmacion_humana(tmp_path):
    """464264: OCR=JD6659, candidata=JD8659 (confirmada directamente
    para este chofer) -- RESUELTO_AUTOMATICAMENTE."""
    ruta = _catalogo(tmp_path)
    _confirmar(ruta, "JE8659", TipoVehiculo.CARRO)  # error sistemático de un mandante, ya en catálogo
    _confirmar(ruta, "JD8659", TipoVehiculo.CARRO, rut_chofer_asociado=RUT_SIMON)  # ground truth del chofer
    vehiculos = cargar_catalogo_vehiculos(ruta).homologables()
    filas = [
        _fila(numero_guia="1", numero_transporte="T-1", patente_rampla="JD6659"),  # el propio documento
        _fila(numero_guia="2", numero_transporte="T-1", patente_tracto="VP8521"),  # mismo transporte (hermano)
        _fila(numero_guia="3", numero_transporte="T-2", patente_rampla="JE8659"),  # otro mandante, error repetido
    ]
    resultado = evaluar_evidencia_patente(
        campo="patente_rampla", valor_documental="JD6659", rut_chofer=RUT_SIMON,
        tipo_esperado="CARRO", numero_transporte_actual="T-1", filas=filas, vehiculos=vehiculos,
    )
    assert resultado["resultado"] == RESULTADO_RESUELTO_AUTOMATICAMENTE
    assert resultado["candidatos"][0]["patente"] == "JD8659"
    assert "CONFIRMACION_HUMANA_ASOCIADA_AL_CHOFER" in resultado["candidatos"][0]["evidencias"]
    # JE8659 sigue apareciendo como candidata real (nunca se oculta),
    # simplemente en un nivel de evidencia menor.
    patentes = [c["patente"] for c in resultado["candidatos"]]
    assert "JE8659" in patentes
    assert resultado["candidatos"][0]["nivel"] == "CONFIRMACION_HUMANA"


def test_simon_rampla_jd0659_resuelve_a_jd8659_confirmacion_humana(tmp_path):
    """464265 rampla: mismo patrón que 464264, distinto valor OCR."""
    ruta = _catalogo(tmp_path)
    _confirmar(ruta, "JE8659", TipoVehiculo.CARRO)
    _confirmar(ruta, "JD8659", TipoVehiculo.CARRO, rut_chofer_asociado=RUT_SIMON)
    vehiculos = cargar_catalogo_vehiculos(ruta).homologables()
    filas = [
        _fila(numero_guia="1", numero_transporte="T-1", patente_rampla="JD0659"),
        _fila(numero_guia="2", numero_transporte="T-2", patente_rampla="JE8659"),
    ]
    resultado = evaluar_evidencia_patente(
        campo="patente_rampla", valor_documental="JD0659", rut_chofer=RUT_SIMON,
        tipo_esperado="CARRO", numero_transporte_actual="T-1", filas=filas, vehiculos=vehiculos,
    )
    assert resultado["resultado"] == RESULTADO_RESUELTO_AUTOMATICAMENTE
    assert resultado["candidatos"][0]["patente"] == "JD8659"


def test_simon_tracto_vp6521_sugiere_vp8521_sin_confirmacion_directa(tmp_path):
    """464265 tracto: VP8521 sólo tiene evidencia documental (cruzada
    entre transportes), nunca una confirmación humana directamente
    asociada al RUT -- SUGERENCIA_HUMANA, no RESUELTO_AUTOMATICAMENTE
    (más conservador: Atlas no reclama certeza que no tiene)."""
    ruta = _catalogo(tmp_path)
    _confirmar(ruta, "VP8521", TipoVehiculo.TRACTO)  # sin rut_chofer_asociado
    vehiculos = cargar_catalogo_vehiculos(ruta).homologables()
    filas = [
        _fila(numero_guia="1", numero_transporte="T-1", patente_tracto="VP6521"),
        _fila(numero_guia="2", numero_transporte="T-2", patente_tracto="VP8521"),
    ]
    resultado = evaluar_evidencia_patente(
        campo="patente_tracto", valor_documental="VP6521", rut_chofer=RUT_SIMON,
        tipo_esperado="TRACTO", numero_transporte_actual="T-1", filas=filas, vehiculos=vehiculos,
    )
    assert resultado["resultado"] == RESULTADO_SUGERENCIA_HUMANA
    assert resultado["candidatos"][0]["patente"] == "VP8521"
    assert resultado["candidatos"][0]["nivel"] == "DOCUMENTAL_INDEPENDIENTE"


# ============================================================
# 4 -- Ortiz, control negativo obligatorio
# ============================================================


def test_ortiz_xf3662_nunca_se_autocorrige_a_xf3629(tmp_path):
    """Guía 464036: único candidato circunstancial (mismo chofer, 1
    transporte, sin confirmación humana) -- debe quedar como
    SUGERENCIA_HUMANA débil o ABSTENCION, NUNCA RESUELTO_AUTOMATICAMENTE."""
    ruta = _catalogo(tmp_path)
    _confirmar(ruta, "XF3629", TipoVehiculo.CAMION_RIGIDO)  # sin rut_chofer_asociado
    vehiculos = cargar_catalogo_vehiculos(ruta).homologables()
    filas = [
        _fila(numero_guia="1", numero_transporte="T-1", rut_chofer=RUT_ORTIZ, patente_tracto="XF3662"),
        _fila(numero_guia="2", numero_transporte="T-2", rut_chofer=RUT_ORTIZ, patente_tracto="XF3629"),
    ]
    resultado = evaluar_evidencia_patente(
        campo="patente_tracto", valor_documental="XF3662", rut_chofer=RUT_ORTIZ,
        tipo_esperado=None,  # tipo no determinado sin confirmación -- caso real
        numero_transporte_actual="T-1", filas=filas, vehiculos=vehiculos,
    )
    assert resultado["resultado"] != RESULTADO_RESUELTO_AUTOMATICAMENTE
    assert resultado["resultado"] == RESULTADO_SUGERENCIA_HUMANA
    assert "TIPO_NO_DETERMINADO_SIN_CONFIRMACION" in resultado["candidatos"][0]["conflictos"]


# ============================================================
# 5 -- dos candidatas igualmente fuertes
# ============================================================


def test_dos_candidatas_igualmente_fuertes_nunca_elige_arbitrariamente(tmp_path):
    ruta = _catalogo(tmp_path)
    _confirmar(ruta, "AA1111", TipoVehiculo.CARRO)
    _confirmar(ruta, "BB2222", TipoVehiculo.CARRO)
    vehiculos = cargar_catalogo_vehiculos(ruta).homologables()
    filas = [
        _fila(numero_guia="1", numero_transporte="T-1", patente_rampla="ZZ0000"),
        _fila(numero_guia="2", numero_transporte="T-2", patente_rampla="AA1111"),
        _fila(numero_guia="3", numero_transporte="T-3", patente_rampla="BB2222"),
    ]
    resultado = evaluar_evidencia_patente(
        campo="patente_rampla", valor_documental="ZZ0000", rut_chofer=RUT_SIMON,
        tipo_esperado="CARRO", numero_transporte_actual="T-1", filas=filas, vehiculos=vehiculos,
    )
    assert resultado["resultado"] == RESULTADO_SUGERENCIA_HUMANA
    assert {c["patente"] for c in resultado["candidatos"]} == {"AA1111", "BB2222"}


# ============================================================
# 6 -- tipo incorrecto no gana
# ============================================================


def test_candidato_de_tipo_incorrecto_no_gana(tmp_path):
    ruta = _catalogo(tmp_path)
    _confirmar(ruta, "XX9999", TipoVehiculo.TRACTO)  # tipo distinto al esperado (CARRO)
    vehiculos = cargar_catalogo_vehiculos(ruta).homologables()
    filas = [
        _fila(numero_guia="1", numero_transporte="T-1", patente_rampla="ZZ0000"),
        _fila(numero_guia="2", numero_transporte="T-2", patente_rampla="XX9999"),
    ]
    resultado = evaluar_evidencia_patente(
        campo="patente_rampla", valor_documental="ZZ0000", rut_chofer=RUT_SIMON,
        tipo_esperado="CARRO", numero_transporte_actual="T-1", filas=filas, vehiculos=vehiculos,
    )
    assert resultado["resultado"] == RESULTADO_ABSTENCION
    assert resultado["candidatos"] == []


# ============================================================
# 7/8 -- repetición vs independencia
# ============================================================


def test_mismo_string_repetido_por_mismo_transporte_no_multiplica_evidencia(tmp_path):
    """3 documentos del MISMO transporte repitiendo el mismo valor
    cuentan como 1 sola corroboración -- nunca 3."""
    ruta = _catalogo(tmp_path)
    _confirmar(ruta, "JE8659", TipoVehiculo.CARRO)
    vehiculos = cargar_catalogo_vehiculos(ruta).homologables()
    filas = [
        _fila(numero_guia="1", numero_transporte="T-1", patente_rampla="JD6659"),
        _fila(numero_guia="2", numero_transporte="T-2", patente_rampla="JE8659"),
        _fila(numero_guia="3", numero_transporte="T-2", patente_rampla="JE8659"),
        _fila(numero_guia="4", numero_transporte="T-2", patente_rampla="JE8659"),
    ]
    resultado = evaluar_evidencia_patente(
        campo="patente_rampla", valor_documental="JD6659", rut_chofer=RUT_SIMON,
        tipo_esperado="CARRO", numero_transporte_actual="T-1", filas=filas, vehiculos=vehiculos,
    )
    candidato = resultado["candidatos"][0]
    assert candidato["patente"] == "JE8659"
    assert candidato["transportes_independientes"] == 1  # no 3
    assert len(candidato["guias"]) == 3  # las 3 guías siguen auditables, sólo no se cuentan como 3 fuentes


def test_fuentes_independientes_si_se_distinguen(tmp_path):
    """3 documentos de 3 transportes DISTINTOS sí cuentan como 3
    corroboraciones independientes."""
    ruta = _catalogo(tmp_path)
    _confirmar(ruta, "JE8659", TipoVehiculo.CARRO)
    vehiculos = cargar_catalogo_vehiculos(ruta).homologables()
    filas = [
        _fila(numero_guia="1", numero_transporte="T-1", patente_rampla="JD6659"),
        _fila(numero_guia="2", numero_transporte="T-2", patente_rampla="JE8659"),
        _fila(numero_guia="3", numero_transporte="T-3", patente_rampla="JE8659"),
        _fila(numero_guia="4", numero_transporte="T-4", patente_rampla="JE8659"),
    ]
    resultado = evaluar_evidencia_patente(
        campo="patente_rampla", valor_documental="JD6659", rut_chofer=RUT_SIMON,
        tipo_esperado="CARRO", numero_transporte_actual="T-1", filas=filas, vehiculos=vehiculos,
    )
    assert resultado["candidatos"][0]["transportes_independientes"] == 3


# ============================================================
# 9 -- confirmación humana tiene precedencia
# ============================================================


def test_confirmacion_humana_tiene_precedencia_sobre_documental_mas_corroborado(tmp_path):
    """Incluso si la evidencia documental de una candidata es más
    numerosa (más transportes independientes), la confirmación humana
    directa gana -- exactamente el control crítico real."""
    ruta = _catalogo(tmp_path)
    _confirmar(ruta, "JE8659", TipoVehiculo.CARRO)  # 3 transportes independientes reales
    _confirmar(ruta, "JD8659", TipoVehiculo.CARRO, rut_chofer_asociado=RUT_SIMON)  # 0 transportes, sólo confirmación humana
    vehiculos = cargar_catalogo_vehiculos(ruta).homologables()
    filas = [
        _fila(numero_guia="1", numero_transporte="T-1", patente_rampla="JD6659"),
        _fila(numero_guia="2", numero_transporte="T-2", patente_rampla="JE8659"),
        _fila(numero_guia="3", numero_transporte="T-3", patente_rampla="JE8659"),
        _fila(numero_guia="4", numero_transporte="T-4", patente_rampla="JE8659"),
    ]
    resultado = evaluar_evidencia_patente(
        campo="patente_rampla", valor_documental="JD6659", rut_chofer=RUT_SIMON,
        tipo_esperado="CARRO", numero_transporte_actual="T-1", filas=filas, vehiculos=vehiculos,
    )
    assert resultado["resultado"] == RESULTADO_RESUELTO_AUTOMATICAMENTE
    assert resultado["candidatos"][0]["patente"] == "JD8659"  # gana pese a 0 corroboración documental


# ============================================================
# 10 -- valor OCR original permanece auditable
# ============================================================


def test_valor_ocr_original_permanece_auditable_en_candidatos_y_conflictos(tmp_path):
    ruta = _catalogo(tmp_path)
    _confirmar(ruta, "JD8659", TipoVehiculo.CARRO, rut_chofer_asociado=RUT_SIMON)
    vehiculos = cargar_catalogo_vehiculos(ruta).homologables()
    filas = [_fila(numero_guia="1", numero_transporte="T-1", patente_rampla="JD6659")]
    resultado = evaluar_evidencia_patente(
        campo="patente_rampla", valor_documental="JD6659", rut_chofer=RUT_SIMON,
        tipo_esperado="CARRO", numero_transporte_actual="T-1", filas=filas, vehiculos=vehiculos,
    )
    candidato = resultado["candidatos"][0]
    assert "OCR_ACTUAL_DIFIERE" in candidato["conflictos"]
    assert "JD6659" in candidato["razon_legible"]  # el valor leído queda explícito en la explicación
    assert "JD6659" in resultado["explicacion"] or "JD8659" in resultado["explicacion"]


# ============================================================
# Abstención / sin evidencia
# ============================================================


def test_sin_ninguna_evidencia_es_abstencion(tmp_path):
    ruta = _catalogo(tmp_path)
    vehiculos = cargar_catalogo_vehiculos(ruta).homologables()
    filas = [_fila(numero_guia="1", numero_transporte="T-1", patente_rampla="ZZ0000")]
    resultado = evaluar_evidencia_patente(
        campo="patente_rampla", valor_documental="ZZ0000", rut_chofer=RUT_SIMON,
        tipo_esperado="CARRO", numero_transporte_actual="T-1", filas=filas, vehiculos=vehiculos,
    )
    assert resultado["resultado"] == RESULTADO_ABSTENCION
    assert resultado["candidatos"] == []


# ============================================================
# 11 -- formato de RUT inconsistente no fragmenta evidencia (FASE 7,
# control real encontrado en el dataset vigente: el RUT de Carlos Simón
# aparece "15489424-1" en algunos documentos y "15.489.424-1" en otros --
# ambas formas deben tratarse como el mismo chofer, nunca como dos)
# ============================================================


def test_rut_con_y_sin_puntos_se_trata_como_el_mismo_chofer(tmp_path):
    ruta = _catalogo(tmp_path)
    _confirmar(ruta, "JD8659", TipoVehiculo.CARRO, rut_chofer_asociado="15.489.424-1")  # con puntos
    vehiculos = cargar_catalogo_vehiculos(ruta).homologables()
    filas = [
        _fila(numero_guia="1", numero_transporte="T-1", rut_chofer="15489424-1", patente_rampla="JD6659"),  # sin puntos
        _fila(numero_guia="2", numero_transporte="T-2", rut_chofer="15.489.424-1", patente_rampla="JE8659"),  # con puntos
    ]
    resultado = evaluar_evidencia_patente(
        campo="patente_rampla", valor_documental="JD6659", rut_chofer="15489424-1",
        tipo_esperado="CARRO", numero_transporte_actual="T-1", filas=filas, vehiculos=vehiculos,
    )
    assert resultado["resultado"] == RESULTADO_RESUELTO_AUTOMATICAMENTE
    assert resultado["candidatos"][0]["patente"] == "JD8659"
    assert "CONFIRMACION_HUMANA_ASOCIADA_AL_CHOFER" in resultado["candidatos"][0]["evidencias"]


def test_sin_rut_o_sin_valor_documental_es_abstencion():
    resultado = evaluar_evidencia_patente(
        campo="patente_rampla", valor_documental="", rut_chofer="", tipo_esperado=None,
        numero_transporte_actual="T-1", filas=[], vehiculos=[],
    )
    assert resultado["resultado"] == RESULTADO_ABSTENCION
