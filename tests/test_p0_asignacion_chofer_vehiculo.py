"""Bloque P0 FINAL -- ASIGNACIÓN OPERACIONAL CHOFER -> VEHÍCULO. Casos
reales 473442 (LUIS REYES/KN5439) y 473546 (SALOMÓN PIZARRO). Tests
puramente sintéticos, nunca tocan G:."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone

from atlas_core.catalogo_vehiculos import TipoVehiculo, cargar_catalogo_vehiculos, confirmar_vehiculo
from atlas_core.convergencia_identidad_conocida import (
    RESULTADO_ABSTENCION,
    RESULTADO_NO_APLICA_VARIABLE,
    RESULTADO_RESUELTO,
    RESULTADO_SIN_EVIDENCIA,
    resolver_patente_operacional_canonica_por_chofer,
)
from atlas_core.decisiones_pendientes import crear_decision, regenerar_decisiones_persistidas
from atlas_core.procesamiento_masivo import COLUMNAS

RUT_LUIS_REYES = "7814310K"  # mismo identificador real usado como clave en choferes.json


def _choferes(*, variable=False):
    return {
        RUT_LUIS_REYES: {"nombre": "LUIS REYES", "activo": True, "aliases": [], "asignacion_variable": variable},
    }


def _catalogos_vacios(tmp_path):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir()
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "choferes.json": _choferes(),
    }.items():
        (carpeta / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    return carpeta


def _confirmar(carpeta, patente, *, rut_chofer_asociado=""):
    return confirmar_vehiculo(
        carpeta / "vehiculos.json", patente=patente, tipo=TipoVehiculo.TRACTO,
        actor="JAVIER_MBT", fuente_decision="ASIGNACION_MBT", fecha=datetime.now(timezone.utc),
        rut_chofer_asociado=rut_chofer_asociado,
    )


def _fila(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "473442.jpeg", "numero_guia": "473442", "chofer": "LUIS REYES",
        "rut_chofer": "7.814.310-K", "patente_tracto": "KW5439",
        "motivos_revision_documento": "", "indicador_revision": "OK", "estado_documental": "OK",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _vehiculos(carpeta):
    return list(cargar_catalogo_vehiculos(carpeta / "vehiculos.json").homologables())


# --- 1. Chofer conocido + única asignación fija -> patente determinada ---

def test_chofer_conocido_asignacion_fija_unica_determina_patente(tmp_path):
    carpeta = _catalogos_vacios(tmp_path)
    _confirmar(carpeta, "KN5439", rut_chofer_asociado="7814310-K")
    resultado = resolver_patente_operacional_canonica_por_chofer(
        nombre_documental="LUIS REYES", rut_documental="7.814.310-K",
        choferes=_choferes(), vehiculos=_vehiculos(carpeta),
    )
    assert resultado.resultado == RESULTADO_RESUELTO
    assert resultado.patente == "KN5439"


# --- 2. OCR patente distinta -> conserva evidencia, no genera revisión ---

def test_ocr_distinto_retira_decision_pero_conserva_valor_documental(tmp_path):
    carpeta = _catalogos_vacios(tmp_path)
    _confirmar(carpeta, "KN5439", rut_chofer_asociado="7814310-K")
    dataset = tmp_path / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [_fila(patente_tracto="KW5439")])  # OCR distinto de la canónica

    decision = crear_decision(
        tipo="VEHICULO_DESCONOCIDO", entidad="VEHICULO", archivo="473442.jpeg", numero_guia="473442",
        numero_transporte="No encontrado", campo="patente_tracto", valor_documental="KW5439",
        valor_normalizado="KW5439", identidad_resuelta=None, candidatos=[],
        motivos=("SIN_VEHICULO_CONFIRMADO_COMPATIBLE",), evidencias=(),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        tipo_resolucion="REQUIERE_CONFIRMACION_HUMANA", tipo_vehiculo_propuesto=None,
    )
    restantes = regenerar_decisiones_persistidas(
        decisiones=[decision], carpeta_catalogos=carpeta, ruta_dataset=dataset,
    )
    assert restantes == []  # la pregunta se retira

    from atlas_core.revalidacion_documental import _leer_filas
    filas_tras = _leer_filas(dataset)
    assert filas_tras[0]["patente_tracto"] == "KW5439"  # el OCR documental NUNCA se sobrescribe


# --- 3. Asignación variable -> la regla no aplica ---

def test_asignacion_variable_no_aplica_la_regla(tmp_path):
    carpeta = _catalogos_vacios(tmp_path)
    _confirmar(carpeta, "KN5439", rut_chofer_asociado="7814310-K")
    resultado = resolver_patente_operacional_canonica_por_chofer(
        nombre_documental="LUIS REYES", rut_documental="7.814.310-K",
        choferes=_choferes(variable=True), vehiculos=_vehiculos(carpeta),
    )
    assert resultado.resultado == RESULTADO_NO_APLICA_VARIABLE
    assert resultado.patente is None


def test_asignacion_variable_no_retira_la_tarjeta(tmp_path):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir()
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "choferes.json": _choferes(variable=True),
    }.items():
        (carpeta / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    _confirmar(carpeta, "KN5439", rut_chofer_asociado="7814310-K")
    dataset = tmp_path / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [_fila(patente_tracto="KW5439")])

    decision = crear_decision(
        tipo="VEHICULO_DESCONOCIDO", entidad="VEHICULO", archivo="473442.jpeg", numero_guia="473442",
        numero_transporte="No encontrado", campo="patente_tracto", valor_documental="KW5439",
        valor_normalizado="KW5439", identidad_resuelta=None, candidatos=[],
        motivos=("SIN_VEHICULO_CONFIRMADO_COMPATIBLE",), evidencias=(),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        tipo_resolucion="REQUIERE_CONFIRMACION_HUMANA", tipo_vehiculo_propuesto=None,
    )
    restantes = regenerar_decisiones_persistidas(
        decisiones=[decision], carpeta_catalogos=carpeta, ruta_dataset=dataset,
    )
    assert len(restantes) == 1  # asignación variable -- la pregunta sigue viva


# --- 4. Múltiples asignaciones vigentes -> abstención ---

def test_multiples_asignaciones_vigentes_abstencion(tmp_path):
    carpeta = _catalogos_vacios(tmp_path)
    _confirmar(carpeta, "KN5439", rut_chofer_asociado="7814310-K")
    _confirmar(carpeta, "AB1234", rut_chofer_asociado="7814310-K")
    resultado = resolver_patente_operacional_canonica_por_chofer(
        nombre_documental="LUIS REYES", rut_documental="7.814.310-K",
        choferes=_choferes(), vehiculos=_vehiculos(carpeta),
    )
    assert resultado.resultado == RESULTADO_ABSTENCION
    assert resultado.patente is None


# --- 5. Chofer ambiguo -> abstención ---

def test_chofer_ambiguo_abstencion(tmp_path):
    carpeta = _catalogos_vacios(tmp_path)
    _confirmar(carpeta, "KN5439", rut_chofer_asociado="7814310-K")
    choferes_ambiguos = {
        "1": {"nombre": "LUIS REYES", "activo": True},
        "2": {"nombre": "LUIS REYES", "activo": True},
    }
    resultado = resolver_patente_operacional_canonica_por_chofer(
        nombre_documental="LUIS REYES", rut_documental="No encontrado",
        choferes=choferes_ambiguos, vehiculos=_vehiculos(carpeta),
    )
    assert resultado.resultado == RESULTADO_ABSTENCION
    assert resultado.patente is None


# --- Sin asignación en catálogo -> reporta el hueco, nunca inventa ---

def test_sin_asignacion_en_catalogo_no_inventa(tmp_path):
    carpeta = _catalogos_vacios(tmp_path)
    _confirmar(carpeta, "KN5439")  # confirmado, pero SIN rut_chofer_asociado -- caso real de hoy
    resultado = resolver_patente_operacional_canonica_por_chofer(
        nombre_documental="LUIS REYES", rut_documental="7.814.310-K",
        choferes=_choferes(), vehiculos=_vehiculos(carpeta),
    )
    assert resultado.resultado == RESULTADO_SIN_EVIDENCIA
    assert resultado.patente is None
    assert "rut_chofer_asociado" in resultado.explicacion


def test_rampla_sin_asociacion_explicita_no_se_resuelve(tmp_path):
    """JF7595/JF9575 no se transforman en rampla canónica sin una
    relación explícita; el OCR ni el historial crean esa relación."""
    carpeta = _catalogos_vacios(tmp_path)
    confirmar_vehiculo(
        carpeta / "vehiculos.json", patente="JF7595", tipo=TipoVehiculo.CARRO,
        actor="JAVIER_MBT", fuente_decision="TEST", fecha=datetime.now(timezone.utc),
    )
    resultado = resolver_patente_operacional_canonica_por_chofer(
        nombre_documental="LUIS REYES", rut_documental="7.814.310-K",
        choferes=_choferes(), vehiculos=_vehiculos(carpeta), tipo_esperado="CARRO",
    )
    assert resultado.resultado == RESULTADO_SIN_EVIDENCIA
    assert resultado.patente is None


# --- 6. Cambio futuro de catálogo -> la nueva asignación pasa a ser autoridad ---

def test_cambio_de_catalogo_la_nueva_asignacion_es_autoridad(tmp_path):
    carpeta = _catalogos_vacios(tmp_path)
    _confirmar(carpeta, "KN5439", rut_chofer_asociado="7814310-K")
    primero = resolver_patente_operacional_canonica_por_chofer(
        nombre_documental="LUIS REYES", rut_documental="7.814.310-K",
        choferes=_choferes(), vehiculos=_vehiculos(carpeta),
    )
    assert primero.resultado == RESULTADO_RESUELTO and primero.patente == "KN5439"

    # MBT cambió la asignación: Javier retira la vigencia de la vieja y
    # confirma la nueva -- exactamente el flujo que el contrato pide
    # ("cuando MBT cambie una asignación, Javier actualizará Atlas").
    contenido = json.loads((carpeta / "vehiculos.json").read_text(encoding="utf-8"))
    for v in contenido["vehiculos"]:
        if v["patente_canonica"] == "KN5439":
            v["estado_vigencia"] = "INACTIVO"
    (carpeta / "vehiculos.json").write_text(json.dumps(contenido), encoding="utf-8")
    _confirmar(carpeta, "ZZ9999", rut_chofer_asociado="7814310-K")

    segundo = resolver_patente_operacional_canonica_por_chofer(
        nombre_documental="LUIS REYES", rut_documental="7.814.310-K",
        choferes=_choferes(), vehiculos=_vehiculos(carpeta),
    )
    assert segundo.resultado == RESULTADO_RESUELTO
    assert segundo.patente == "ZZ9999"
