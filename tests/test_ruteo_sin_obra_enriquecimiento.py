"""Regresión del flujo completo (afb6257): sin obra leída, el enriquecimiento
logístico debe correr y recibir los destinos confirmados del cliente.

`destinos_relacion_ruteo` quedó definido sólo dentro del bloque que corre con
obra leída; sin obra (caso 482402) el ingreso lanzaba UnboundLocalError, el
`try` lo absorbía y el documento perdía planta, destino y ruta en silencio.
"""
from __future__ import annotations

import json
import logging
from unittest.mock import Mock

import pytest

from atlas_core import procesamiento_masivo
from atlas_core.procesamiento_masivo import procesar_archivo

FECHA = "2026-10-16T00:00:00+00:00"


@pytest.fixture
def catalogos(tmp_path):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir()
    cliente = {"cliente_id": "cliente-matco", "razon_social": "ARMACERO MATCO SA", "nombre_normalizado": "ARMACERO MATCO",
               "nombre_comercial": "", "rut": "78170790-2", "aliases": [], "estado_calidad": "CONFIRMADO",
               "estado_vigencia": "ACTIVO", "fuente": "TEST", "observacion": "", "fecha_creacion": FECHA,
               "fecha_modificacion": FECHA}
    destino = {"destino_id": "d-santa-isabel", "cliente_id": "cliente-matco", "nombre_destino": "SANTA ISABEL 585",
               "nombre_normalizado": "SANTA ISABEL 585", "codigo_destino": "", "direccion": "SANTA ISABEL 585, LAMPA, CHILE",
               "comuna": "LAMPA", "region": "RM", "pais": "CHILE", "latitud": -33.31, "longitud": -70.73, "aliases": [],
               "estado_calidad": "CONFIRMADO", "estado_vigencia": "ACTIVO", "fuente": "TEST", "observacion": "",
               "fecha_creacion": FECHA, "fecha_modificacion": FECHA}
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": [cliente]},
        "destinos_maestros.json": {"version_formato": 1, "destinos": [destino]},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "plantas.json": {"version_formato": 1, "plantas": []},
    }.items():
        (carpeta / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    return carpeta


@pytest.mark.parametrize("obra", ["No encontrado", "OBRA LEIDA QUE EL CATALOGO NO CONOCE"])
def test_enriquecimiento_logistico_corre_con_o_sin_obra(tmp_path, monkeypatch, caplog, catalogos, obra):
    datos = {"número de guía": "482402", "número de transporte": "0000364552", "cliente": "ARMACERO MATCO SA",
             "obra destino": obra, "chofer": "RENE GARCIA", "RUT del cliente": "78.170.790-2",
             "RUT del chofer": "9.708.225-1", "patente del tracto": "AL1879", "patente del carro": "JK2501"}
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen",
                        Mock(return_value=["DESPACHAR A : SANTA ISABSL SB5 SANTIAGO LAMPA"]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", Mock(return_value=datos))
    llamadas = []

    def resolver(*args, **kwargs):
        llamadas.append(kwargs)
        return {campo: "" for campo in procesamiento_masivo.CAMPOS_ENTREGA_DOCUMENTO}

    monkeypatch.setattr(procesamiento_masivo, "resolver_entrega_documento", resolver)
    with caplog.at_level(logging.WARNING, logger="atlas_core.procesamiento_masivo"):
        procesar_archivo(tmp_path / "guia.jpg", carpeta_catalogos=catalogos)

    assert not [r for r in caplog.records if "Enriquecimiento logístico omitido" in r.getMessage()]
    assert len(llamadas) == 1
    destinos = [d.destino_id for d in llamadas[0]["destinos_relacion_confirmada"]]
    # Sin obra: respaldo por cliente. Con una obra leída (sin relación), el
    # respaldo por cliente no aplica: nunca se mezcla con una obra real.
    assert destinos == (["d-santa-isabel"] if obra == "No encontrado" else [])
