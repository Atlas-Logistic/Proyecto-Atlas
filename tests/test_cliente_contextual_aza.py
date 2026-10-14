"""Resolución de cliente AZA desde evidencia ya extraída; no invoca OCR real."""
from __future__ import annotations

import json
from unittest.mock import Mock

from atlas_core import procesamiento_masivo
from atlas_core.procesamiento_masivo import procesar_archivo


def _cliente_confirmado(nombre: str, rut: str, cliente_id: str = "cliente-prueba") -> dict[str, object]:
    return {
        "cliente_id": cliente_id, "razon_social": nombre,
        "nombre_normalizado": nombre, "nombre_comercial": "", "rut": rut,
        "aliases": [], "estado_calidad": "CONFIRMADO", "estado_vigencia": "ACTIVO",
        "fuente": "TEST", "observacion": "", "fecha_creacion": "2026-01-01T00:00:00+00:00",
        "fecha_modificacion": "2026-01-01T00:00:00+00:00",
    }


def _datos(cliente: str, rut: str) -> dict[str, str]:
    return {
        "número de guía": "900001", "número de transporte": "0000900001", "fecha": "01-01-2026",
        "cliente": cliente, "obra destino": "OBRA DE PRUEBA", "chofer": "CHOFER PRUEBA",
        "RUT del cliente": rut, "RUT del chofer": "No encontrado",
        "patente del tracto": "AB1234", "patente del carro": "CD5678",
        "despachar a": "DIRECCION DE PRUEBA 123", "peso": "1000",
    }


def _preparar(monkeypatch, datos: dict[str, str]) -> None:
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["FECHA DE EMISION 01-01-2026"]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", Mock(return_value=datos))


def test_procesamiento_corrige_nombre_con_catalogo_clientes_sin_empresas_legacy(tmp_path, monkeypatch):
    catalogos = tmp_path / "catalogos"
    catalogos.mkdir()
    (catalogos / "clientes.json").write_text(json.dumps({"version_formato": 1, "clientes": [
        _cliente_confirmado("CONSTRUCTORA ALFA NORTE LTDA", "50234350-5"),
    ]}), encoding="utf-8")
    _preparar(monkeypatch, _datos("CONSTRVCTORA ALPA NORTF ILTDA", "50.234.350-5"))

    resultado = procesar_archivo(tmp_path / "guia.jpg", carpeta_catalogos=catalogos)

    assert resultado["cliente"] == "CONSTRUCTORA ALFA NORTE LTDA"
    assert "CATALOGO_RUT_CLIENTE" in resultado["metodos_recuperacion_documento"]
    assert "FUZZY" in resultado["metodos_recuperacion_documento"]


def test_procesamiento_no_corrige_si_nombre_es_ambiguo_aun_con_rut(tmp_path, monkeypatch):
    catalogos = tmp_path / "catalogos"
    catalogos.mkdir()
    (catalogos / "clientes.json").write_text(json.dumps({"version_formato": 1, "clientes": [
        _cliente_confirmado("COMERCIAL ALFA SPA", "50234350-5", "cliente-rut"),
        _cliente_confirmado("CONSTRUCTORA ALFA NORTE LTDA", "93772000-9", "cliente-nombre"),
    ]}), encoding="utf-8")
    _preparar(monkeypatch, _datos("CONSTRUCTORA ALPA NORTE LTDA", "50.234.350-5"))

    resultado = procesar_archivo(tmp_path / "guia.jpg", carpeta_catalogos=catalogos)

    assert resultado["cliente"] != "CONSTRUCTORA ALFA NORTE LTDA"
    assert "FUZZY" not in resultado["metodos_recuperacion_documento"]
