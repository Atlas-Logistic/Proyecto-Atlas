from __future__ import annotations

import csv
from datetime import datetime, timezone

from atlas_core.comandos_incidencias_operacionales import aplicar_lote, previsualizar_lote
from atlas_core.registro_eventos_operacionales import (
    GESTION_APROBADA, GESTION_REPORTADA, consultar_incidencias_operacionales,
    estado_revision_viajes, leer_eventos_operacionales,
)


def _viajes(ruta):
    columnas = ("viaje_id", "numero_transporte", "fecha", "numeros_guia", "choferes", "clientes", "obras_destino")
    with ruta.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=columnas, delimiter=";"); w.writeheader()
        w.writerows((
            {"viaje_id": "v1", "numero_transporte": "T1", "fecha": "10-09-2026", "numeros_guia": "473001 | 473004", "choferes": "JUAN", "clientes": "C1", "obras_destino": "O1"},
            {"viaje_id": "v2", "numero_transporte": "T2", "fecha": "11-09-2026", "numeros_guia": "473010", "choferes": "PEDRO", "clientes": "C2", "obras_destino": "O2"},
        ))


def test_preview_confirma_y_aplica_lote_idempotente_con_trazabilidad(tmp_path):
    ruta = tmp_path / "viajes.csv"; _viajes(ruta)
    acciones = (
        {"accion": "REGISTRAR_INCIDENCIA", "guia": "473001", "tipo": "TIENE_ESTADIA", "estado_gestion": GESTION_REPORTADA, "evidencia": ["GUIA_FIRMADA"]},
        {"accion": "REGISTRAR_INCIDENCIA", "guia": "473010", "tipo": "DOBLE_VUELTA"},
        {"accion": "REGISTRAR_INCIDENCIA", "guia": "999999", "tipo": "DEVOLUCION_PARCIAL"},
    )
    preview = previsualizar_lote(ruta_viajes=ruta, acciones=acciones)
    assert preview["requiere_confirmacion"] and preview["aplicable"]
    assert [a["estado"] for a in preview["acciones"]] == ["RESUELTA", "RESUELTA", "NO_ENCONTRADA"]
    assert aplicar_lote(raiz=tmp_path, ruta_viajes=ruta, acciones=acciones[:2], actor="JAVIER", confirmado=False)["aplicado"] is False
    aplicado = aplicar_lote(raiz=tmp_path, ruta_viajes=ruta, acciones=acciones, actor="JAVIER", confirmado=True)
    assert [r["ok"] for r in aplicado["resultados"]] == [True, True, False]
    eventos = leer_eventos_operacionales(raiz=tmp_path)["eventos"]
    assert len(eventos) == 2 and eventos[0]["numeros_guia"] == ["473001", "473004"]
    assert eventos[0]["estado_gestion"] == GESTION_REPORTADA and eventos[0]["evidencia"] == ["GUIA_FIRMADA"]
    repetir = aplicar_lote(raiz=tmp_path, ruta_viajes=ruta, acciones=acciones[:2], actor="JAVIER", confirmado=True)
    assert len(leer_eventos_operacionales(raiz=tmp_path)["eventos"]) == 2
    assert repetir["aplicado"] is False
    assert [r["estado"] for r in repetir["resultados"]] == ["YA_REGISTRADA", "YA_REGISTRADA"]


def test_gestion_y_revision_negativa_comparten_fuente_consultable(tmp_path):
    ruta = tmp_path / "viajes.csv"; _viajes(ruta)
    alta = ({"accion": "REGISTRAR_INCIDENCIA", "guia": "473001", "tipo": "DEVOLUCION_PARCIAL", "estado_gestion": GESTION_REPORTADA},)
    aplicar_lote(raiz=tmp_path, ruta_viajes=ruta, acciones=alta, actor="JAVIER", confirmado=True)
    cambio = ({"accion": "ACTUALIZAR_GESTION", "guia": "473001", "tipo": "DEVOLUCION_PARCIAL", "estado_gestion": GESTION_APROBADA},)
    aplicar_lote(raiz=tmp_path, ruta_viajes=ruta, acciones=cambio, actor="JAVIER", confirmado=True)
    negativo = ({"accion": "REVISAR_SIN_INCIDENCIA", "guia": "473010"},)
    aplicar_lote(raiz=tmp_path, ruta_viajes=ruta, acciones=negativo, actor="JAVIER", confirmado=True)
    consulta = consultar_incidencias_operacionales(raiz=tmp_path)
    assert consulta["incidencias"][0]["estado_gestion"] == GESTION_APROBADA
    assert consulta["pendientes_gestion"] == []
    assert consulta["revisiones_sin_incidencia"][0]["estado_revision"] == "SIN_INCIDENCIA"
    estados = estado_revision_viajes(raiz=tmp_path, viajes=[{"numero_transporte": "T1"}, {"numero_transporte": "T2"}, {"numero_transporte": "T3"}])
    assert [x["estado_revision_incidencias"] for x in estados] == ["INCIDENCIA_REGISTRADA", "SIN_INCIDENCIA", "NO_REVISADO"]
