"""Contrato de la evidencia OCR lateral y no intrusiva."""

from __future__ import annotations

import json
from unittest.mock import Mock

from atlas_core import procesamiento_masivo
from atlas_core.ocr import BloqueOCR
from atlas_core.procesamiento_masivo import procesar_archivo
from atlas_core.trazabilidad_ocr import (
    VERSION_SCHEMA_TRAZA_OCR,
    construir_traza_ocr,
    persistir_traza_ocr,
    ruta_traza_ocr,
)


def _datos_completos() -> dict[str, str]:
    return {
        "número de guía": "123456",
        "número de transporte": "0000123456",
        "cliente": "CLIENTE PRUEBA",
        "obra destino": "OBRA PRUEBA",
        "chofer": "CHOFER PRUEBA",
        "RUT del cliente": "76.000.000-0",
        "RUT del chofer": "11.111.111-1",
        "patente del tracto": "AB1234",
        "patente del carro": "CD5678",
        "hora de entrada": "No encontrado",
        "hora de salida": "No encontrado",
        "peso": "No encontrado",
    }


def _configurar_ocr_simple(monkeypatch, datos: dict[str, str]) -> None:
    monkeypatch.setattr(
        procesamiento_masivo,
        "leer_texto_imagen",
        Mock(return_value=["GUIA DE DESPACHO", "MATERIAL DE PRUEBA"]),
    )
    monkeypatch.setattr(
        procesamiento_masivo,
        "leer_bloques_imagen",
        Mock(return_value=[
            BloqueOCR("GUIA DE DESPACHO", ((1, 2), (9, 2), (9, 5), (1, 5)), 0.97)
        ]),
    )
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", Mock(return_value=datos))


def test_documento_normal_genera_sidecar_con_evidencia_disponible(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    _configurar_ocr_simple(monkeypatch, _datos_completos())

    resultado = procesar_archivo(
        ruta,
        directorio_trazas_ocr=tmp_path / "trazas_ocr",
        referencia_imagen_traza="lote_a/guia.jpg",
    )

    sidecar = ruta_traza_ocr(tmp_path / "trazas_ocr", "lote_a/guia.jpg")
    contenido = json.loads(sidecar.read_text(encoding="utf-8"))
    assert resultado["numero_guia"] == "123456"
    assert contenido["schema_version"] == VERSION_SCHEMA_TRAZA_OCR
    assert contenido["imagen"]["referencia"] == "lote_a/guia.jpg"
    assert contenido["ocr"]["lineas"] == ["GUIA DE DESPACHO", "MATERIAL DE PRUEBA"]
    assert contenido["ocr"]["bloques"] == [{
        "texto": "GUIA DE DESPACHO",
        "bounding_box": [[1, 2], [9, 2], [9, 5], [1, 5]],
        "confianza": 0.97,
    }]
    assert contenido["ocr"]["estado_bloques"] == "DISPONIBLES"
    assert contenido["identificadores_extraidos"] == {
        "numero_guia": "123456",
        "numero_transporte": "0000123456",
    }


def test_traza_preserva_bloques_coordenadas_y_confianza_cuando_existen(tmp_path):
    bloque = BloqueOCR("OBRA DESTINO", ((10, 20), (90, 20), (90, 35), (10, 35)), 0.91)
    ruta = persistir_traza_ocr(
        directorio=tmp_path,
        referencia_imagen="subcarpeta/guia.jpg",
        textos=["OBRA DESTINO"],
        bloques=[bloque],
    )

    contenido = json.loads(ruta.read_text(encoding="utf-8"))
    assert contenido["ocr"]["bloques"] == [{
        "texto": "OBRA DESTINO",
        "bounding_box": [[10, 20], [90, 20], [90, 35], [10, 35]],
        "confianza": 0.91,
    }]
    assert contenido["ocr"]["estado_bloques"] == "DISPONIBLES"


def test_traza_sin_confianza_no_falla():
    class BloqueSinConfianza:
        texto = "SIN CONFIANZA"
        bounding_box = ((1, 1), (2, 1), (2, 2), (1, 2))

    traza = construir_traza_ocr(
        referencia_imagen="guia.jpg", textos=[], bloques=[BloqueSinConfianza()]
    )

    assert traza["ocr"]["bloques"][0]["confianza"] is None
    assert traza["ocr"]["estado_bloques"] == "DISPONIBLES"


def test_traza_guarda_configuracion_del_backend_si_esta_disponible():
    class ProveedorConConfiguracion:
        device = "cpu"
        version = "9.9-prueba"

    traza = construir_traza_ocr(
        referencia_imagen="guia.jpg",
        textos=[],
        bloques=[],
        proveedor=ProveedorConConfiguracion(),
    )

    assert traza["ocr"]["backend"]["nombre"].endswith("ProveedorConConfiguracion")
    assert traza["ocr"]["backend"]["version"] == "9.9-prueba"
    assert traza["ocr"]["backend"]["configuracion"] == {"device": "cpu"}


def test_traza_expresa_ausencia_de_version_y_configuracion_sin_inventarlas():
    traza = construir_traza_ocr(referencia_imagen="guia.jpg", textos=[], bloques=[])

    assert traza["ocr"]["backend"]["version"] is None
    assert traza["ocr"]["backend"]["configuracion"] is None


def test_traza_no_dispara_lectura_de_bloques_solo_por_auditoria(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    _configurar_ocr_simple(monkeypatch, _datos_completos())
    leer_bloques = procesamiento_masivo.leer_bloques_imagen
    monkeypatch.setattr(procesamiento_masivo, "extraer_fecha", lambda *_args, **_kwargs: "01-01-2026")

    procesar_archivo(
        ruta,
        directorio_trazas_ocr=tmp_path / "trazas_ocr",
        referencia_imagen_traza="guia.jpg",
    )

    leer_bloques.assert_not_called()
    contenido = json.loads(
        ruta_traza_ocr(tmp_path / "trazas_ocr", "guia.jpg").read_text(encoding="utf-8")
    )
    assert contenido["ocr"]["bloques"] is None
    assert contenido["ocr"]["estado_bloques"] == "NO_SOLICITADOS"


def test_traza_distingue_bloques_solicitados_pero_no_disponibles(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    datos = _datos_completos()
    datos["RUT del chofer"] = "No encontrado"  # activa la lectura ya existente
    _configurar_ocr_simple(monkeypatch, datos)
    monkeypatch.setattr(
        procesamiento_masivo,
        "leer_bloques_imagen",
        Mock(side_effect=OSError("backend de bloques no disponible")),
    )

    resultado = procesar_archivo(
        ruta,
        directorio_trazas_ocr=tmp_path / "trazas_ocr",
        referencia_imagen_traza="guia.jpg",
    )

    contenido = json.loads(
        ruta_traza_ocr(tmp_path / "trazas_ocr", "guia.jpg").read_text(encoding="utf-8")
    )
    assert resultado["numero_guia"] == "123456"
    assert contenido["ocr"]["bloques"] is None
    assert contenido["ocr"]["estado_bloques"] == "NO_DISPONIBLES"


def test_ubicacion_canonica_de_trazas_esta_fuera_de_operacion_actual(tmp_path):
    salida_canonica = tmp_path / "operacion" / "actual" / "analisis_completo_guias.csv"
    salida_local = tmp_path / "salida_local" / "analisis.csv"

    assert procesamiento_masivo._directorio_trazas_ocr_para_salida(salida_canonica) == (
        tmp_path / "operacion" / "trazas_ocr"
    )
    assert procesamiento_masivo._directorio_trazas_ocr_para_salida(salida_local) == (
        tmp_path / "salida_local" / "trazas_ocr"
    )


def test_documento_historico_sin_sidecar_no_activa_lecturas_ni_falla(tmp_path, monkeypatch):
    ruta = tmp_path / "guia_historica.jpg"
    _configurar_ocr_simple(monkeypatch, _datos_completos())

    resultado = procesar_archivo(ruta)

    assert resultado["numero_guia"] == "123456"
    assert not list(tmp_path.glob("*.json"))


def test_fallo_al_escribir_sidecar_no_altera_extraccion(tmp_path, monkeypatch, caplog):
    ruta = tmp_path / "guia.jpg"
    _configurar_ocr_simple(monkeypatch, _datos_completos())
    monkeypatch.setattr(
        procesamiento_masivo,
        "persistir_traza_ocr",
        Mock(side_effect=OSError("medio sin espacio")),
    )

    resultado = procesar_archivo(
        ruta,
        directorio_trazas_ocr=tmp_path / "trazas_ocr",
        referencia_imagen_traza="guia.jpg",
    )

    assert resultado["numero_guia"] == "123456"
    assert "Traza OCR no persistida" in caplog.text


def test_sidecar_no_duplica_imagen_ni_base64(tmp_path):
    referencia = "lote/guia.jpg"
    primera = persistir_traza_ocr(
        directorio=tmp_path,
        referencia_imagen=referencia,
        textos=["primera lectura"],
        bloques=[],
    )
    segunda = persistir_traza_ocr(
        directorio=tmp_path,
        referencia_imagen=referencia,
        textos=["lectura actualizada"],
        bloques=[],
    )

    archivos = list(tmp_path.glob("*.json"))
    serializado = primera.read_text(encoding="utf-8")
    assert primera == segunda
    assert archivos == [primera]
    assert "lectura actualizada" in serializado
    assert "base64" not in serializado.lower()
    assert "data:" not in serializado.lower()


def test_nombre_lateral_no_colisiona_con_mismo_nombre_en_otro_directorio(tmp_path):
    primera = ruta_traza_ocr(tmp_path, "lote_a/guia.jpg")
    segunda = ruta_traza_ocr(tmp_path, "lote_b/guia.jpg")

    assert primera != segunda
    assert primera.name.startswith("guia--")


def test_traza_no_cambia_campos_finales_extraidos(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    _configurar_ocr_simple(monkeypatch, _datos_completos())
    sin_traza = procesar_archivo(ruta)
    _configurar_ocr_simple(monkeypatch, _datos_completos())
    con_traza = procesar_archivo(
        ruta,
        directorio_trazas_ocr=tmp_path / "trazas_ocr",
        referencia_imagen_traza="guia.jpg",
    )

    # El cronometraje es por naturaleza variable entre dos ejecuciones;
    # ninguna columna documental/operacional cambia por la traza lateral.
    assert {k: v for k, v in con_traza.items() if k != "metricas_procesamiento_json"} == {
        k: v for k, v in sin_traza.items() if k != "metricas_procesamiento_json"
    }
