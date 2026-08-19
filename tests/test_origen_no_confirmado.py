"""Bloque ORIGEN D1 -- confirmación humana AUDITABLE de planta de origen.

Cubre: detección conservadora de `ORIGEN_NO_CONFIRMADO` (nunca para
telemetría demasiado escasa), aplicación de `CONFIRMAR_PLANTA`/
`SELECCIONAR_OTRA_PLANTA`/`NO_PUEDO_DETERMINAR`, precedencia
`CONFIRMACION_HUMANA` en la consolidación de viaje, protección contra
sobrescritura por revalidación de telemetría, y el caso real que motivó
el bloque: GPS con evidencia fuerte para DOS plantas, confirmación humana
que elige la que la evidencia GPS por sí sola no habría sugerido primero.
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas_core.aplicacion_decisiones import (
    DecisionObsoletaError,
    ErrorAplicacionDecision,
    aplicar_decision_obra,
)
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.decisiones_pendientes import (
    crear_decision,
    detectar_decision_origen_no_confirmado,
    generar_artefacto,
)
from atlas_core.gestor_viajes import Viaje, _documento_desde_fila, _resolver_origen_viaje
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    _leer_filas,
    detectar_decisiones_origen_sin_ocr,
    revalidar_telemetria_sin_ocr,
)
from atlas_core.telemetria.proveedor import ProveedorTelemetriaSoloCache
from atlas_core.telemetria.repositorio import RepositorioTelemetria
from atlas_core.telemetria.servicio import ServicioTelemetria

COORD_COLINA = (-33.137558, -70.665977)
# Deliberadamente >50 km de COORD_COLINA (más que
# RADIO_CANDIDATO_ORIGEN_SUGERIDO_KM) para que los escenarios de UNA sola
# estadía GPS (sin nombre de planta en el texto) generen exactamente un
# candidato por cercanía, y el conflicto nombrado (que sí identifica ambas
# plantas por texto, independiente de la distancia) siga probando ambas.
COORD_RENCA = (-33.750000, -70.900000)
FECHA = "10-08-2026"


def _fila_csv(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "464900.jpeg", "estado_procesamiento": "OK", "numero_guia": "464900",
        "numero_transporte": "0000000900", "fecha": FECHA, "chofer": "CHOFER PRUEBA",
        "cliente": "CLIENTE PRUEBA", "obra_destino": "OBRA PRUEBA",
        "patente_tracto": "AB1234", "patente_rampla": "No encontrado",
        "descripcion_material": "MATERIAL", "tipo_carga": "OTRO",
        "indicador_revision": "REVISAR", "motivos_revision_documento": "",
        "hora_entrada_aza": "08:00", "hora_salida_aza": "09:00",
        "estado_ruta": "ORIGEN_NO_DETERMINADO", "motivo_ruta": "",
        "planta_origen_id": "", "planta_origen_nombre": "",
        "origen_determinado_por": "", "evidencia_origen": "",
        "distancia_km": "", "estado_entrega": "", "despachar_a_crudo": "",
        "proveedor_telemetria": "onelogis", "estado_telemetria": "SELECCIONADO",
        "origen_gps": "", "motivo_origen_gps": "",
        "latitud_estadia_gps": "", "longitud_estadia_gps": "", "duracion_estadia_gps_min": "",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _leer_csv(ruta):
    with ruta.open("r", newline="", encoding="utf-8-sig") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _entorno(tmp_path, *, filas_csv=None):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True)
    catalogos.mkdir(parents=True)
    actual.mkdir(parents=True)
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []},
        "empresas.json": {},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")

    catalogo_plantas = CatalogoPlantas(catalogos / "plantas.json")
    planta_colina = catalogo_plantas.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        direccion="AV EJEMPLO 1", comuna="COLINA", region="RM",
        latitud=COORD_COLINA[0], longitud=COORD_COLINA[1], estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    planta_renca = catalogo_plantas.crear(
        nombre="AZA RENCA", pais="CHILE", fuente="TEST",
        direccion="AV EJEMPLO 2", comuna="RENCA", region="RM",
        latitud=COORD_RENCA[0], longitud=COORD_RENCA[1], estado_calidad=EstadoCalidad.CONFIRMADA,
    )

    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, filas_csv or [_fila_csv()])

    return {
        "raiz": raiz, "catalogos": catalogos, "actual": actual, "dataset": dataset,
        "planta_colina": planta_colina, "planta_renca": planta_renca,
    }


def _publicar_decision(entorno, decision):
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )


# ============================================================
# Detección (pura, sin filesystem más allá de lo mínimo)
# ============================================================


def test_genera_decision_con_candidato_gps_estadia(tmp_path):
    """Patrón real 464717/464892: detención real, sin planta identificada
    automáticamente, pero con una planta CONFIRMADA cerca."""
    catalogo = CatalogoPlantas(tmp_path / "plantas.json")
    colina = catalogo.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        latitud=COORD_COLINA[0], longitud=COORD_COLINA[1], estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    fila = _fila_csv(
        motivo_origen_gps="DETENCION_REAL_FUERA_DE_TODA_GEOCERCA;duracion_min=287.7;trips=t1|t2",
        latitud_estadia_gps=str(COORD_COLINA[0] + 0.05), longitud_estadia_gps=str(COORD_COLINA[1] + 0.05),
        duracion_estadia_gps_min="287.7",
    )
    decision = detectar_decision_origen_no_confirmado(archivo="464900.jpeg", fila=fila, plantas=[colina])
    assert decision is not None
    assert decision["tipo"] == "ORIGEN_NO_CONFIRMADO"
    assert len(decision["candidatos"]) == 1
    assert decision["candidatos"][0]["planta_nombre"] == "AZA COLINA"
    assert decision["motivos"] == ["ORIGEN_GPS_ESTADIA_SIN_PLANTA"]
    assert set(decision["acciones_permitidas"]) == {
        "CONFIRMAR_PLANTA", "SELECCIONAR_OTRA_PLANTA", "NO_PUEDO_DETERMINAR", "POSPONER",
    }


def test_genera_decision_con_ambas_plantas_en_conflicto(tmp_path):
    """Patrón real 464730: conflicto real entre dos plantas, ninguna se
    fuerza como sugerida única."""
    catalogo = CatalogoPlantas(tmp_path / "plantas.json")
    colina = catalogo.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        latitud=COORD_COLINA[0], longitud=COORD_COLINA[1], estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    renca = catalogo.crear(
        nombre="AZA RENCA", pais="CHILE", fuente="TEST",
        latitud=COORD_RENCA[0], longitud=COORD_RENCA[1], estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    fila = _fila_csv(
        motivo_origen_gps="CONFLICTO_REAL_EN_VENTANA(AZA_COLINA:score=0.1366,solape=0.0%;AZA_RENCA:score=0.0,solape=0.0%)",
    )
    decision = detectar_decision_origen_no_confirmado(archivo="464900.jpeg", fila=fila, plantas=[colina, renca])
    assert decision is not None
    nombres = {c["planta_nombre"] for c in decision["candidatos"]}
    assert nombres == {"AZA COLINA", "AZA RENCA"}
    assert decision["motivos"] == ["ORIGEN_GPS_CONFLICTO"]


def test_no_genera_decision_sin_evidencia_suficiente(tmp_path):
    """Patrón real 464479/464529: telemetría demasiado escasa -- ni
    conflicto nombrado ni coordenada de estadía que ofrecer."""
    catalogo = CatalogoPlantas(tmp_path / "plantas.json")
    colina = catalogo.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        latitud=COORD_COLINA[0], longitud=COORD_COLINA[1], estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    for motivo in ("NINGUN_PUNTO_DENTRO_DE_GEOCERCA", "SIN_HISTORICO", "SIN_TRIPS_EN_VENTANA_TEMPORAL", ""):
        fila = _fila_csv(motivo_origen_gps=motivo)
        assert detectar_decision_origen_no_confirmado(archivo="x", fila=fila, plantas=[colina]) is None


def test_no_genera_decision_si_ya_tiene_origen(tmp_path):
    catalogo = CatalogoPlantas(tmp_path / "plantas.json")
    colina = catalogo.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        latitud=COORD_COLINA[0], longitud=COORD_COLINA[1], estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    fila = _fila_csv(
        planta_origen_id="ya-existe", planta_origen_nombre="AZA COLINA",
        motivo_origen_gps="CONFLICTO_REAL_EN_VENTANA(AZA_COLINA:score=1.0,solape=100.0%)",
    )
    assert detectar_decision_origen_no_confirmado(archivo="x", fila=fila, plantas=[colina]) is None


def test_no_genera_decision_si_estado_ruta_no_es_origen_no_determinado(tmp_path):
    catalogo = CatalogoPlantas(tmp_path / "plantas.json")
    colina = catalogo.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        latitud=COORD_COLINA[0], longitud=COORD_COLINA[1], estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    fila = _fila_csv(
        estado_ruta="MULTIPLES_UBICACIONES_DISPERSAS",
        motivo_origen_gps="CONFLICTO_REAL_EN_VENTANA(AZA_COLINA:score=1.0,solape=100.0%)",
    )
    assert detectar_decision_origen_no_confirmado(archivo="x", fila=fila, plantas=[colina]) is None


def test_estadia_lejos_de_toda_planta_no_genera_candidatos(tmp_path):
    catalogo = CatalogoPlantas(tmp_path / "plantas.json")
    colina = catalogo.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        latitud=COORD_COLINA[0], longitud=COORD_COLINA[1], estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    fila = _fila_csv(
        motivo_origen_gps="DETENCION_REAL_FUERA_DE_TODA_GEOCERCA;duracion_min=50.0;trips=t1",
        latitud_estadia_gps="-53.0", longitud_estadia_gps="-70.9",  # Patagonia, a cientos de km
        duracion_estadia_gps_min="50.0",
    )
    assert detectar_decision_origen_no_confirmado(archivo="x", fila=fila, plantas=[colina]) is None


def test_planta_inactiva_no_se_ofrece_como_candidata(tmp_path):
    catalogo = CatalogoPlantas(tmp_path / "plantas.json")
    colina = catalogo.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        latitud=COORD_COLINA[0], longitud=COORD_COLINA[1], estado_calidad=EstadoCalidad.PENDIENTE,
    )
    fila = _fila_csv(
        motivo_origen_gps="DETENCION_REAL_FUERA_DE_TODA_GEOCERCA;duracion_min=50.0;trips=t1",
        latitud_estadia_gps=str(COORD_COLINA[0]), longitud_estadia_gps=str(COORD_COLINA[1]),
        duracion_estadia_gps_min="50.0",
    )
    assert detectar_decision_origen_no_confirmado(archivo="x", fila=fila, plantas=[colina]) is None


# ============================================================
# Aplicación: CONFIRMAR_PLANTA / SELECCIONAR_OTRA_PLANTA / NO_PUEDO_DETERMINAR
# ============================================================


def _decision_estadia(entorno):
    fila = _fila_csv(
        motivo_origen_gps="DETENCION_REAL_FUERA_DE_TODA_GEOCERCA;duracion_min=287.7;trips=t1",
        latitud_estadia_gps=str(COORD_COLINA[0]), longitud_estadia_gps=str(COORD_COLINA[1]),
        duracion_estadia_gps_min="287.7",
    )
    _escribir_csv(entorno["dataset"], [fila])
    decision = detectar_decision_origen_no_confirmado(
        archivo="464900.jpeg", fila=fila, plantas=[entorno["planta_colina"], entorno["planta_renca"]],
    )
    _publicar_decision(entorno, decision)
    return decision


def _decision_conflicto(entorno):
    fila = _fila_csv(
        motivo_origen_gps="CONFLICTO_REAL_EN_VENTANA(AZA_COLINA:score=0.14,solape=0.0%;AZA_RENCA:score=0.0,solape=0.0%)",
    )
    _escribir_csv(entorno["dataset"], [fila])
    decision = detectar_decision_origen_no_confirmado(
        archivo="464900.jpeg", fila=fila, plantas=[entorno["planta_colina"], entorno["planta_renca"]],
    )
    _publicar_decision(entorno, decision)
    return decision


def test_confirmar_planta_escribe_confirmacion_humana(tmp_path):
    entorno = _entorno(tmp_path)
    decision = _decision_estadia(entorno)

    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"], accion="CONFIRMAR_PLANTA",
    )
    assert resultado["ok"] is True
    assert resultado["planta_id"] == entorno["planta_colina"].planta_id

    fila = _leer_csv(entorno["dataset"])[0]
    assert fila["planta_origen_id"] == entorno["planta_colina"].planta_id
    assert fila["planta_origen_nombre"] == "AZA COLINA"
    assert fila["origen_determinado_por"] == "CONFIRMACION_HUMANA"
    assert decision["decision_id"] in fila["evidencia_origen"]
    # La evidencia GPS original nunca se borra.
    assert fila["motivo_origen_gps"].startswith("DETENCION_REAL_FUERA_DE_TODA_GEOCERCA")


def test_confirmar_planta_falla_si_hay_mas_de_un_candidato(tmp_path):
    entorno = _entorno(tmp_path)
    decision = _decision_conflicto(entorno)
    with pytest.raises(ErrorAplicacionDecision):
        aplicar_decision_obra(raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"], accion="CONFIRMAR_PLANTA")


def test_seleccionar_otra_planta_permite_elegir_candidato_distinto_al_sugerido(tmp_path):
    """Control crítico (464730): GPS con evidencia fuerte para ambas
    plantas -- un humano puede elegir CUALQUIERA de las dos, nunca se
    fuerza una por sobre la otra."""
    entorno = _entorno(tmp_path)
    decision = _decision_conflicto(entorno)

    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="SELECCIONAR_OTRA_PLANTA", planta_id_elegida=entorno["planta_renca"].planta_id,
    )
    assert resultado["ok"] is True
    assert resultado["planta_id"] == entorno["planta_renca"].planta_id

    fila = _leer_csv(entorno["dataset"])[0]
    assert fila["planta_origen_nombre"] == "AZA RENCA"
    assert fila["origen_determinado_por"] == "CONFIRMACION_HUMANA"
    # La evidencia de conflicto (ambas plantas) sigue íntegra.
    assert "AZA_COLINA" in fila["motivo_origen_gps"] and "AZA_RENCA" in fila["motivo_origen_gps"]


def test_seleccionar_otra_planta_sin_planta_id_falla(tmp_path):
    entorno = _entorno(tmp_path)
    decision = _decision_conflicto(entorno)
    with pytest.raises(ErrorAplicacionDecision):
        aplicar_decision_obra(
            raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"], accion="SELECCIONAR_OTRA_PLANTA",
        )


def test_no_puedo_determinar_no_escribe_origen_pero_queda_terminal(tmp_path):
    entorno = _entorno(tmp_path)
    decision = _decision_conflicto(entorno)

    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"], accion="NO_PUEDO_DETERMINAR",
    )
    assert resultado["ok"] is True

    fila = _leer_csv(entorno["dataset"])[0]
    assert fila["planta_origen_id"] == ""
    assert fila["origen_determinado_por"] == ""  # nunca inventa origen

    # La misma evidencia (misma decision_id) no vuelve a generarse: queda
    # terminal en el ledger, filtrada por generar_artefacto.
    nueva = detectar_decision_origen_no_confirmado(
        archivo="464900.jpeg", fila=fila, plantas=[entorno["planta_colina"], entorno["planta_renca"]],
    )
    assert nueva["decision_id"] == decision["decision_id"]  # misma evidencia -> mismo id
    bandeja = generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[nueva], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    assert bandeja["decisiones"] == []  # filtrada por el ledger -- no se vuelve a preguntar


def test_ledger_conserva_evidencia_y_valor_anterior(tmp_path):
    entorno = _entorno(tmp_path)
    decision = _decision_estadia(entorno)
    aplicar_decision_obra(raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"], accion="CONFIRMAR_PLANTA")

    ledger = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    aplicacion = ledger["aplicaciones"][0]
    assert aplicacion["accion"] == "CONFIRMAR_PLANTA"
    assert aplicacion["planta_id"] == entorno["planta_colina"].planta_id
    assert aplicacion["evidencia_previa"] == decision["evidencias"]
    assert aplicacion["valor_anterior"] == {
        "planta_origen_id": "", "planta_origen_nombre": "",
        "origen_determinado_por": "", "evidencia_origen": "",
    }
    assert aplicacion["actor"]


def test_dataset_obsoleto_rechaza_aplicacion(tmp_path):
    entorno = _entorno(tmp_path)
    decision = _decision_estadia(entorno)
    (entorno["dataset"]).write_text("cambio externo no relacionado", encoding="utf-8")
    with pytest.raises(DecisionObsoletaError):
        aplicar_decision_obra(raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"], accion="CONFIRMAR_PLANTA")


def test_idempotencia_no_duplica(tmp_path):
    entorno = _entorno(tmp_path)
    decision = _decision_estadia(entorno)
    primera = aplicar_decision_obra(raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"], accion="CONFIRMAR_PLANTA")
    segunda = aplicar_decision_obra(raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"], accion="CONFIRMAR_PLANTA")
    assert primera["idempotente"] is False
    assert segunda["idempotente"] is True
    ledger = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    assert len(ledger["aplicaciones"]) == 1


def test_no_modifica_campos_documentales(tmp_path):
    entorno = _entorno(tmp_path)
    fila_original = _fila_csv(
        motivo_origen_gps="DETENCION_REAL_FUERA_DE_TODA_GEOCERCA;duracion_min=287.7;trips=t1",
        latitud_estadia_gps=str(COORD_COLINA[0]), longitud_estadia_gps=str(COORD_COLINA[1]),
        duracion_estadia_gps_min="287.7",
    )
    _escribir_csv(entorno["dataset"], [fila_original])
    decision = detectar_decision_origen_no_confirmado(
        archivo="464900.jpeg", fila=fila_original, plantas=[entorno["planta_colina"], entorno["planta_renca"]],
    )
    _publicar_decision(entorno, decision)
    aplicar_decision_obra(raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"], accion="CONFIRMAR_PLANTA")

    fila = _leer_csv(entorno["dataset"])[0]
    for campo in (
        "numero_guia", "numero_transporte", "fecha", "chofer", "cliente", "obra_destino",
        "patente_tracto", "patente_rampla", "descripcion_material", "tipo_carga",
        "hora_entrada_aza", "hora_salida_aza", "despachar_a_crudo",
    ):
        assert fila[campo] == fila_original[campo], campo


def test_regeneracion_de_reporte_conserva_la_planta(tmp_path):
    entorno = _entorno(tmp_path)
    decision = _decision_estadia(entorno)
    resultado = aplicar_decision_obra(raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"], accion="CONFIRMAR_PLANTA")
    assert resultado.get("reporte_regenerado") is True

    estado = json.loads((entorno["actual"] / "estado_operacion.json").read_text(encoding="utf-8"))
    reporte_ruta = entorno["raiz"] / estado["reporte_vigente"]
    with (reporte_ruta / "viajes.csv").open(encoding="utf-8-sig") as f:
        viajes = list(csv.DictReader(f, delimiter=";"))
    viaje = next(v for v in viajes if v["numero_transporte"] == "0000000900")
    assert viaje["planta_origen_nombre"] == "AZA COLINA"
    assert viaje["origen_determinado_por"] == "CONFIRMACION_HUMANA"


# ============================================================
# Precedencia en consolidación de viaje + protección contra sobrescritura
# ============================================================


def test_confirmacion_humana_gana_sobre_gps_en_consolidacion():
    """Control crítico conceptual (464730): un documento con
    CONFIRMACION_HUMANA a Renca debe ganarle a un documento hermano del
    mismo viaje con TELEMETRIA_GPS apuntando a Colina."""
    fila_confirmada = _fila_csv(
        numero_guia="1", planta_origen_id="renca-id", planta_origen_nombre="AZA RENCA",
        origen_determinado_por="CONFIRMACION_HUMANA", evidencia_origen="DECISION_HUMANA:abc",
    )
    fila_gps = _fila_csv(
        numero_guia="2", planta_origen_id="colina-id", planta_origen_nombre="AZA COLINA",
        origen_determinado_por="TELEMETRIA_GPS", evidencia_origen="GEOCERCA_PLANTA",
    )
    documentos = [
        _documento_desde_fila(fila_confirmada, normalizador_chofer=None),
        _documento_desde_fila(fila_gps, normalizador_chofer=None),
    ]
    viaje = Viaje(viaje_id="v1", numero_transporte="0000000900", fecha=FECHA, documentos=documentos)
    assert viaje.planta_origen_nombre == "AZA RENCA"
    assert viaje.origen_determinado_por == "CONFIRMACION_HUMANA"


def test_documento_multiple_confirmacion_humana_de_uno_gana_sobre_gps_del_otro():
    """Igual al anterior pero verificando explícitamente vía
    `_resolver_origen_viaje` (la función de bajo nivel) y sin conflicto."""
    fila_confirmada = _fila_csv(
        numero_guia="1", planta_origen_id="renca-id", planta_origen_nombre="AZA RENCA",
        origen_determinado_por="CONFIRMACION_HUMANA",
    )
    fila_documento = _fila_csv(
        numero_guia="2", planta_origen_id="colina-id", planta_origen_nombre="AZA COLINA",
        origen_determinado_por="DOCUMENTO",
    )
    documentos = [
        _documento_desde_fila(fila_confirmada, normalizador_chofer=None),
        _documento_desde_fila(fila_documento, normalizador_chofer=None),
    ]
    planta_id, planta_nombre, fuente, _, conflicto = _resolver_origen_viaje(documentos)
    assert not conflicto
    assert planta_nombre == "AZA RENCA"
    assert fuente == "CONFIRMACION_HUMANA"


def test_revalidar_telemetria_no_pisa_confirmacion_humana(tmp_path):
    """CRÍTICO: aunque exista telemetría cacheada que apuntaría a OTRA
    planta, una fila con CONFIRMACION_HUMANA nunca se toca."""
    entorno = _entorno(tmp_path)
    fila = _fila_csv(
        estado_telemetria="",  # deliberadamente vacío -- sin este guard,
        planta_origen_id=entorno["planta_renca"].planta_id,      # el guard de estado_telemetria
        planta_origen_nombre="AZA RENCA",                        # NO bastaría para protegerla.
        origen_determinado_por="CONFIRMACION_HUMANA",
        evidencia_origen="DECISION_HUMANA:xyz",
    )
    _escribir_csv(entorno["dataset"], [fila])

    from atlas_core.telemetria.modelos import ViajeTelemetria
    repo = RepositorioTelemetria(entorno["catalogos"] / "telemetria_cache.json")
    repo.guardar_viajes(
        "onelogis", "AB1234", __import__("datetime").date(2026, 8, 10), __import__("datetime").date(2026, 8, 10),
        (ViajeTelemetria("t1", "AB1234", "2026-08-10 07:40:00", "2026-08-10 07:50:00", 1.0),),
    )
    servicio = ServicioTelemetria(ProveedorTelemetriaSoloCache(nombre="onelogis"), repo)

    resultado = revalidar_telemetria_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        servicio_telemetria=servicio,
    )
    assert resultado["guias_actualizadas"] == []

    fila_final = _leer_csv(entorno["dataset"])[0]
    assert fila_final["planta_origen_nombre"] == "AZA RENCA"
    assert fila_final["origen_determinado_por"] == "CONFIRMACION_HUMANA"
    assert fila_final["estado_telemetria"] == ""  # tampoco se tocó nada más


# ============================================================
# Escaneo del dataset completo (detectar_decisiones_origen_sin_ocr)
# ============================================================


def test_deteccion_de_dataset_completo_omite_evidencia_insuficiente(tmp_path):
    entorno = _entorno(tmp_path)
    fila_con_evidencia = _fila_csv(
        numero_guia="1",
        motivo_origen_gps="DETENCION_REAL_FUERA_DE_TODA_GEOCERCA;duracion_min=287.7;trips=t1",
        latitud_estadia_gps=str(COORD_COLINA[0]), longitud_estadia_gps=str(COORD_COLINA[1]),
        duracion_estadia_gps_min="287.7",
    )
    fila_sin_evidencia = _fila_csv(numero_guia="2", motivo_origen_gps="NINGUN_PUNTO_DENTRO_DE_GEOCERCA")
    fila_ya_resuelta = _fila_csv(
        numero_guia="3", planta_origen_id="x", planta_origen_nombre="AZA COLINA",
        origen_determinado_por="TELEMETRIA_GPS", estado_ruta="RUTA_CALCULADA",
    )
    _escribir_csv(entorno["dataset"], [fila_con_evidencia, fila_sin_evidencia, fila_ya_resuelta])

    candidatas = detectar_decisiones_origen_sin_ocr(raiz_atlas=entorno["raiz"])
    assert len(candidatas) == 1
    assert candidatas[0]["documento"]["numero_guia"] == "1"


# ============================================================
# CLI (aplicar_decision_pendiente.py) -- lo que Desktop invoca en vivo
# ============================================================


def _ejecutar_cli(raiz, decision_id, accion, planta_id_elegida=None):
    script = Path(__file__).resolve().parents[1] / "aplicar_decision_pendiente.py"
    argumentos = [sys.executable, str(script), "--raiz-atlas", str(raiz), "--decision-id", decision_id, "--accion", accion]
    if planta_id_elegida:
        argumentos += ["--planta-id-elegida", planta_id_elegida]
    proceso = subprocess.run(argumentos, cwd=script.parent, capture_output=True, check=True)
    return json.loads(proceso.stdout.decode("ascii"))


def test_cli_confirmar_planta_de_punta_a_punta(tmp_path):
    entorno = _entorno(tmp_path)
    decision = _decision_estadia(entorno)
    respuesta = _ejecutar_cli(entorno["raiz"], decision["decision_id"], "CONFIRMAR_PLANTA")
    assert respuesta["ok"] is True
    assert respuesta["planta_id"] == entorno["planta_colina"].planta_id
    fila = _leer_csv(entorno["dataset"])[0]
    assert fila["origen_determinado_por"] == "CONFIRMACION_HUMANA"


def test_cli_seleccionar_otra_planta_de_punta_a_punta(tmp_path):
    """Mismo camino que usaría un click real en Desktop -- el CLI recibe
    `--planta-id-elegida` y lo reenvía a `aplicar_decision_obra`."""
    entorno = _entorno(tmp_path)
    decision = _decision_conflicto(entorno)
    respuesta = _ejecutar_cli(entorno["raiz"], decision["decision_id"], "SELECCIONAR_OTRA_PLANTA", entorno["planta_renca"].planta_id)
    assert respuesta["ok"] is True
    assert respuesta["planta_id"] == entorno["planta_renca"].planta_id
    fila = _leer_csv(entorno["dataset"])[0]
    assert fila["planta_origen_nombre"] == "AZA RENCA"
    assert fila["origen_determinado_por"] == "CONFIRMACION_HUMANA"


def test_cli_no_puedo_determinar_de_punta_a_punta(tmp_path):
    entorno = _entorno(tmp_path)
    decision = _decision_conflicto(entorno)
    respuesta = _ejecutar_cli(entorno["raiz"], decision["decision_id"], "NO_PUEDO_DETERMINAR")
    assert respuesta["ok"] is True
    fila = _leer_csv(entorno["dataset"])[0]
    assert fila["planta_origen_id"] == ""
