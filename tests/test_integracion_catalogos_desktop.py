import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

import analizar_guias_masivo
from atlas_core import procesamiento_masivo
from atlas_core.fuente_catalogos import (
    ARCHIVOS_REQUERIDOS,
    ErrorFuenteCatalogos,
    validar_fuente_catalogos,
)


def _catalogos_validos(carpeta: Path) -> Path:
    contenidos = {
        "choferes.json": {},
        "clientes.json": {"clientes": []},
        "empresas.json": {},
        "destinos_maestros.json": {"destinos": []},
        "vehiculos.json": {},
        "plantas.json": {"plantas": []},
        "rutas.json": {"rutas": []},
    }
    carpeta.mkdir(parents=True, exist_ok=True)
    for nombre, contenido in contenidos.items():
        (carpeta / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    return carpeta


def _resumen_vacio():
    return {
        "encontrados": 0,
        "procesados": 0,
        "omitidos": 0,
        "errores": 0,
        "barras": 0,
        "rollos": 0,
        "mixtos": 0,
        "no_determinados": 0,
        "tiempo_total_segundos": 0.0,
        "promedio_segundos_archivo": 0.0,
    }


def test_fuente_explicita_y_variable_entorno(tmp_path, monkeypatch):
    fuente = _catalogos_validos(tmp_path / "privados")
    assert validar_fuente_catalogos(fuente).ruta == fuente.resolve()
    monkeypatch.setenv("ATLAS_CATALOGOS_DIR", str(fuente))
    assert validar_fuente_catalogos().ruta == fuente.resolve()


def test_fuente_inexistente_e_incompleta_fallan(tmp_path, monkeypatch):
    monkeypatch.delenv("ATLAS_CATALOGOS_DIR", raising=False)
    with pytest.raises(ErrorFuenteCatalogos, match="no existe"):
        validar_fuente_catalogos(tmp_path / "ausente")
    (tmp_path / "choferes.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ErrorFuenteCatalogos, match="Fuente incompleta"):
        validar_fuente_catalogos(tmp_path)


def test_plantillas_example_no_son_fuente_productiva(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ATLAS_CATALOGOS_DIR", raising=False)
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir()
    for nombre in ARCHIVOS_REQUERIDOS:
        (carpeta / nombre.replace(".json", ".example.json")).write_text(
            "{}", encoding="utf-8"
        )
    with pytest.raises(ErrorFuenteCatalogos, match="Falta la fuente"):
        validar_fuente_catalogos()


def test_cli_desktop_acepta_catalogos_y_propaga(tmp_path, monkeypatch):
    fuente = _catalogos_validos(tmp_path / "privados")
    procesar = Mock(return_value=_resumen_vacio())
    monkeypatch.setattr(analizar_guias_masivo, "procesar_carpeta", procesar)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "analizar_guias_masivo.py",
            str(tmp_path),
            "--salida",
            str(tmp_path / "salida.csv"),
            "--catalogos",
            str(fuente),
        ],
    )
    analizar_guias_masivo.main()
    assert procesar.call_args.kwargs["carpeta_catalogos"] == fuente.resolve()


def test_catalogos_y_proveedor_compartido_se_propagan_juntos(tmp_path, monkeypatch):
    carpeta = tmp_path / "guias"
    carpeta.mkdir()
    for nombre in ("a.jpg", "b.jpg"):
        (carpeta / nombre).write_bytes(b"imagen")
    proveedor = object()
    crear = Mock(return_value=proveedor)
    procesar = Mock(return_value={"tipo_carga": "NO DETERMINADO"})
    monkeypatch.setattr(procesamiento_masivo, "crear_proveedor_ocr", crear)
    monkeypatch.setattr(procesamiento_masivo, "procesar_archivo", procesar)

    fuente = tmp_path / "catalogos"
    procesamiento_masivo.procesar_carpeta(
        carpeta, tmp_path / "salida.csv", carpeta_catalogos=fuente
    )

    crear.assert_called_once_with()
    assert procesar.call_count == 2
    for llamada in procesar.call_args_list:
        assert llamada.kwargs == {
            "proveedor": proveedor,
            "carpeta_catalogos": fuente,
        }


def test_procesar_archivo_aplica_fuente_explicita(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    ruta.write_bytes(b"imagen")
    fuente = tmp_path / "catalogos"
    proveedor = Mock()
    proveedor.leer_texto.return_value = ["texto"]
    datos = {
        "número de guía": "123456",
        "número de transporte": "0000000001",
        "cliente": "CLIENTE OCR",
        "obra destino": "DESTINO",
        "RUT del cliente": "No encontrado",
        "chofer": "No encontrado",
        "RUT del chofer": "No encontrado",
        "patente del tracto": "AA1111",
        "patente del carro": "BB2222",
        "hora de entrada": "No encontrado",
        "hora de salida": "No encontrado",
        "peso": "No encontrado",
    }
    extraer = Mock(return_value=datos)
    enriquecer = Mock(return_value=datos)
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", extraer)
    monkeypatch.setattr(
        procesamiento_masivo, "enriquecer_datos_con_catalogos", enriquecer
    )
    monkeypatch.setattr(procesamiento_masivo, "extraer_fecha", lambda *a, **k: "01-01-2026")
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_descripcion_material", lambda textos: "BARRAS"
    )

    procesamiento_masivo.procesar_archivo(
        ruta, proveedor=proveedor, carpeta_catalogos=fuente
    )

    extraer.assert_called_once_with(["texto"], fuente)
    enriquecer.assert_called_once_with(datos, ["texto"], fuente)
