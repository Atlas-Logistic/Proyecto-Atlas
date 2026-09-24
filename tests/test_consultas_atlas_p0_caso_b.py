"""Bloque P0 CONFIABILIDAD "PREGÚNTALE A ATLAS" -- CASO B. Caso real:
"cuantos pendientes tecnicos hay en las guias ingresadas hoy" respondía
"32 viajes (INCOMPLETO_TECNICO)" -- aplicaba el filtro de ESTADO pero
perdía por completo la restricción "ingresadas hoy".

Causa raíz (investigada antes de tocar código): no existía ningún
timestamp persistente de ingesta (la única fecha disponible era la
documental, `fecha`); y el punto exacto donde se perdía el período era
`interpretador_consultas.py` -- la rama de "pendiente técnico" hacía un
`return` temprano con `filtros={"estado": "INCOMPLETO_TECNICO"}`
hardcodeado, sin llamar nunca al resolutor de período.

Este archivo prueba, en `tmp_path` (nunca G, nunca red, nunca B1 real):
  - `fecha_ingesta_utc` se persiste UNA vez por documento, en
    `procesar_archivo`, y NUNCA se confunde con `fecha` (documental);
  - "ingresadas hoy"/"ingresadas ayer" filtran por ESE timestamp, nunca
    por la fecha del documento;
  - INCOMPLETO_TECNICO + INGESTADO_HOY se componen (AND), nunca se
    pierde ninguno de los dos;
  - "muéstramelos" conserva exactamente el filtro anterior;
  - una consulta sin período sigue exactamente igual que siempre (B6)."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from atlas_core.consultas_atlas import ConsultaAtlas
from atlas_core.procesamiento_masivo import procesar_archivo
from atlas_core.responder_consulta_atlas import ESTADO_OK, responder_consulta_atlas

COLUMNAS = (
    "viaje_id", "numero_transporte", "fecha", "estado", "numeros_guia", "clientes",
    "obras_destino", "choferes", "patentes_tracto", "patentes_rampla", "materiales",
    "tipos_carga", "peso_total_viaje_kg", "distancia_km", "duracion_min",
    "direccion_entrega", "localidad_entrega", "fecha_ingesta",
)


def _escribir_viajes(ruta: Path, filas: list[dict]) -> None:
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _fila(**overrides) -> dict:
    base = {c: "" for c in COLUMNAS}
    base.update({
        "viaje_id": "v1", "numero_transporte": "T1", "fecha": "18-08-2026", "estado": "CONFIRMADO",
        "numeros_guia": "1", "clientes": "CLIENTE A", "obras_destino": "OBRA A",
        "choferes": "JUAN PEREZ", "patentes_tracto": "AA1111", "materiales": "ROLLO HORMIGON",
        "tipos_carga": "ROLLOS", "peso_total_viaje_kg": "1000", "distancia_km": "10.0",
        "duracion_min": "20.0", "direccion_entrega": "CALLE FALSA 123", "localidad_entrega": "MAIPU",
    })
    base.update(overrides)
    return base


_HOY = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)
_AYER = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
_HOY_ISO = _HOY.isoformat()
_AYER_ISO = _AYER.isoformat()


# ==========================================================================
# Persistencia mínima: `fecha_ingesta_utc` nunca se confunde con `fecha`
# ==========================================================================


def test_fecha_ingesta_utc_se_persiste_por_documento_y_difiere_de_fecha_documental(tmp_path, monkeypatch):
    import atlas_core.procesamiento_masivo as procesamiento
    from unittest.mock import Mock

    datos = {
        "número de guía": "900001", "número de transporte": "0000900000",
        "cliente": "CLIENTE X", "obra destino": "OBRA X", "chofer": "JUAN PEREZ",
        "fecha": "01/01/2026",
    }
    monkeypatch.setattr(procesamiento, "leer_texto_imagen", Mock(return_value=["DESPACHAR A CALLE UNO 100"]))
    monkeypatch.setattr(procesamiento, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento, "extraer_datos", Mock(return_value=datos))

    resultado = procesar_archivo(tmp_path / "guia.jpg", proveedor_rutas=object(), reloj=lambda: _HOY)
    assert resultado["fecha_ingesta_utc"] == _HOY.astimezone(timezone.utc).isoformat()
    # Nunca la fecha documental -- son dos campos totalmente distintos.
    assert resultado["fecha_ingesta_utc"] != resultado.get("fecha", "")
    assert resultado["fecha"] != resultado["fecha_ingesta_utc"]


# ==========================================================================
# B1/B2/B3/B4 -- filtra por INGESTA, nunca por fecha documental
# ==========================================================================


def test_b1_documento_antiguo_ingresado_hoy_incompleto_tecnico_incluido(tmp_path):
    ruta = tmp_path / "viajes.csv"
    _escribir_viajes(ruta, [
        # Documental antiguo, pero ingresado HOY -- SÍ pertenece.
        _fila(numero_transporte="T1", fecha="01-01-2026", estado="INCOMPLETO_TECNICO", fecha_ingesta=_HOY_ISO),
    ])
    respuesta = responder_consulta_atlas(
        "cuantos pendientes tecnicos hay en las guias ingresadas hoy", ruta_viajes=ruta,
    )
    assert respuesta.estado == ESTADO_OK
    consulta = respuesta.resultado.consulta_interpretada
    assert consulta.filtros["estado"] == "INCOMPLETO_TECNICO"
    assert consulta.filtros.get("periodo_ingesta") == "HOY"
    assert "periodo" not in consulta.filtros  # nunca se confunde con fecha documental
    assert respuesta.resultado.resultado == 1


def test_b2_documento_de_hoy_ingresado_ayer_excluido(tmp_path):
    ruta = tmp_path / "viajes.csv"
    _escribir_viajes(ruta, [
        # Documental de HOY, pero ingresado AYER -- NO pertenece a "ingresadas hoy".
        _fila(numero_transporte="T1", fecha="21-09-2026", estado="INCOMPLETO_TECNICO", fecha_ingesta=_AYER_ISO),
    ])
    respuesta = responder_consulta_atlas(
        "cuantos pendientes tecnicos hay en las guias ingresadas hoy", ruta_viajes=ruta,
    )
    assert respuesta.resultado.resultado == 0


def test_b3_confirmado_ingresado_hoy_excluido_al_preguntar_pendientes_tecnicos(tmp_path):
    ruta = tmp_path / "viajes.csv"
    _escribir_viajes(ruta, [
        _fila(numero_transporte="T1", estado="CONFIRMADO", fecha_ingesta=_HOY_ISO),
        _fila(numero_transporte="T2", estado="INCOMPLETO_TECNICO", fecha_ingesta=_HOY_ISO),
    ])
    respuesta = responder_consulta_atlas(
        "cuantos pendientes tecnicos hay en las guias ingresadas hoy", ruta_viajes=ruta,
    )
    assert respuesta.resultado.resultado == 1  # sólo T2 -- el estado sigue exigiéndose


def test_b4_incompleto_tecnico_historico_excluido(tmp_path):
    ruta = tmp_path / "viajes.csv"
    _escribir_viajes(ruta, [
        _fila(numero_transporte="T1", estado="INCOMPLETO_TECNICO", fecha_ingesta=_AYER_ISO),
        _fila(numero_transporte="T2", estado="INCOMPLETO_TECNICO", fecha_ingesta=_HOY_ISO),
    ])
    respuesta = responder_consulta_atlas(
        "cuantos pendientes tecnicos hay en las guias ingresadas hoy", ruta_viajes=ruta,
    )
    assert respuesta.resultado.resultado == 1  # sólo T2
    soporte = respuesta.resultado.viajes_soporte
    assert {v["numero_transporte"] for v in soporte} == {"T2"}


# ==========================================================================
# B5 -- "muéstramelos" conserva exactamente estado + período + dominio
# ==========================================================================


def test_b5_muestramelos_conserva_filtros_del_conjunto_anterior(tmp_path):
    ruta = tmp_path / "viajes.csv"
    _escribir_viajes(ruta, [
        _fila(numero_transporte="T1", estado="INCOMPLETO_TECNICO", fecha_ingesta=_HOY_ISO),
        _fila(numero_transporte="T2", estado="INCOMPLETO_TECNICO", fecha_ingesta=_AYER_ISO),
        _fila(numero_transporte="T3", estado="CONFIRMADO", fecha_ingesta=_HOY_ISO),
    ])
    primera = responder_consulta_atlas(
        "cuantos pendientes tecnicos hay en las guias ingresadas hoy", ruta_viajes=ruta,
    )
    assert primera.resultado.resultado == 1

    seguimiento = responder_consulta_atlas(
        "muéstramelos", ruta_viajes=ruta, consulta_anterior=primera.resultado.consulta_interpretada,
    )
    assert seguimiento.estado == ESTADO_OK
    consulta_seguimiento = seguimiento.resultado.consulta_interpretada
    assert consulta_seguimiento.filtros == primera.resultado.consulta_interpretada.filtros
    assert consulta_seguimiento.dominio == primera.resultado.consulta_interpretada.dominio
    assert {v["numero_transporte"] for v in seguimiento.resultado.viajes_soporte} == {"T1"}


def test_b5b_seguimiento_con_contenido_propio_no_hereda_nada(tmp_path):
    """Un texto de seguimiento que SÍ trae contenido propio (otro
    nombre/filtro) nunca hereda el contexto anterior -- se interpreta
    como consulta nueva, de cero."""
    ruta = tmp_path / "viajes.csv"
    _escribir_viajes(ruta, [
        _fila(numero_transporte="T1", estado="INCOMPLETO_TECNICO", fecha_ingesta=_HOY_ISO, choferes="JUAN PEREZ"),
    ])
    primera = responder_consulta_atlas(
        "cuantos pendientes tecnicos hay en las guias ingresadas hoy", ruta_viajes=ruta,
    )
    otra = responder_consulta_atlas(
        "cuantos viajes hizo Juan Perez", ruta_viajes=ruta,
        consulta_anterior=primera.resultado.consulta_interpretada,
    )
    assert otra.resultado.consulta_interpretada.filtros != primera.resultado.consulta_interpretada.filtros


# ==========================================================================
# B6 -- sin período: comportamiento histórico intacto
# ==========================================================================


def test_b6_consulta_sin_periodo_comportamiento_historico_intacto(tmp_path):
    ruta = tmp_path / "viajes.csv"
    _escribir_viajes(ruta, [
        _fila(numero_transporte="T1", estado="INCOMPLETO_TECNICO", fecha_ingesta=_AYER_ISO),
        _fila(numero_transporte="T2", estado="INCOMPLETO_TECNICO", fecha_ingesta=""),
        _fila(numero_transporte="T3", estado="REQUIERE_REVISION", fecha_ingesta=_HOY_ISO),
    ])
    for pregunta in (
        "cuantos pendientes tecnicos hay?",
        "cuántos viajes están pendientes técnicamente?",
        "viajes incompletos técnicos",
    ):
        respuesta = responder_consulta_atlas(pregunta, ruta_viajes=ruta)
        assert respuesta.estado == ESTADO_OK
        assert respuesta.resultado.consulta_interpretada.filtros == {"estado": "INCOMPLETO_TECNICO"}
        assert respuesta.resultado.resultado == 2  # T1 + T2 -- sin filtro de ingesta, comportamiento de siempre
