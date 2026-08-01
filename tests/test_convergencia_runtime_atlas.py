"""Pruebas de convivencia sin acoplar reportes y rutas."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone

import pytest

from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.reporte_viajes import COLUMNAS_OFICIALES, generar_reporte_viajes
from atlas_core.rutas import (
    CalculadorRutas,
    EstadoCalculoRuta,
    ProveedorRutasSimulado,
    SolicitudCalculoRuta,
)
from resumen_procesamiento_desktop import comando_resumen, comando_snapshot


RELOJ = lambda: datetime(2026, 7, 28, 18, 0, tzinfo=timezone.utc)


def _fila(**cambios):
    fila = {columna: "" for columna in COLUMNAS_OFICIALES}
    fila.update(
        archivo="guía ñ.jpg",
        estado_procesamiento="OK",
        numero_guia="000101",
        numero_transporte="00002001",
        fecha="2026-07-28",
        chofer="JOSÉ PÉREZ",
        rut_chofer="12.345.678-5",
        cliente="CLIENTE ÑUBLE",
        obra_destino="DESTINO SINTÉTICO",
        patente_tracto="ABCD12",
        patente_rampla="EFGH34",
        descripcion_material="BARRAS",
        tipo_carga="BARRAS",
        indicador_revision="OK",
    )
    fila.update(cambios)
    return fila


def _escribir_entrada(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(
            archivo, fieldnames=list(COLUMNAS_OFICIALES), delimiter=";"
        )
        escritor.writeheader()
        escritor.writerows(filas)


def _sha256(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _solicitud(planta="AZA Renca"):
    return SolicitudCalculoRuta(
        planta=planta,
        planta_confirmada=True,
        coordenadas_origen={"longitud": -70.70, "latitud": -33.40},
        destino="Destino sintético",
        destino_confirmado=True,
        coordenadas_destino={"longitud": -70.60, "latitud": -33.50},
        proveedor="simulado",
        evidencia={"fuente": "prueba de convergencia"},
    )


def test_flujo_combinado_es_determinista_y_mantiene_reportes(tmp_path, capsys):
    """Cubre CSV 15, BOM, ceros, conflictos, resumen y ruta posterior."""
    filas = [
        _fila(archivo="a.jpg", cliente="CLIENTE UNO"),
        _fila(archivo="b.jpg", numero_guia="000102", cliente="CLIENTE DOS"),
        _fila(
            archivo="sin transporte.jpg",
            numero_guia="000103",
            numero_transporte="",
        ),
    ]
    entrada = tmp_path / "entrada sintética.csv"
    _escribir_entrada(entrada, filas)
    assert entrada.read_bytes().startswith(b"\xef\xbb\xbf")
    assert tuple(COLUMNAS) == COLUMNAS_OFICIALES
    assert len(COLUMNAS) == 15

    hashes_por_ejecucion = []
    for numero in (1, 2):
        salida = tmp_path / f"salida explícita {numero}"
        generar_reporte_viajes(
            entrada,
            salida,
            carpeta_catalogos=tmp_path / "catálogos sintéticos",
            reloj=RELOJ,
        )
        snapshot = tmp_path / f"snapshot {numero}.json"
        comando_snapshot(argparse.Namespace(csv_masivo=entrada, salida=snapshot))
        comando_resumen(
            argparse.Namespace(
                csv_masivo=entrada,
                reporte=salida,
                snapshot=snapshot,
                archivo=["a.jpg", "sin transporte.jpg"],
            )
        )
        resumen = json.loads(capsys.readouterr().out)
        assert resumen[0]["numero_transporte"] == "00002001"
        assert resumen[1]["sin_transporte"] is True

        rutas_antes = {
            nombre: _sha256(salida / nombre)
            for nombre in ("viajes.csv", "documentos_sin_transporte.csv")
        }
        for planta in ("AZA Renca", "AZA Colina"):
            resultado = CalculadorRutas(
                ProveedorRutasSimulado(), reloj=RELOJ
            ).calcular(_solicitud(planta))
            assert resultado.estado == EstadoCalculoRuta.CALCULADA
        rutas_despues = {
            nombre: _sha256(salida / nombre)
            for nombre in rutas_antes
        }
        assert rutas_despues == rutas_antes
        hashes_por_ejecucion.append(rutas_despues)

        with (salida / "viajes.csv").open(
            newline="", encoding="utf-8-sig"
        ) as archivo:
            viaje = next(csv.DictReader(archivo, delimiter=";"))
        assert viaje["numero_transporte"] == "00002001"
        assert "CONFLICTO_CLIENTE" in viaje["motivos_revision"]

    assert hashes_por_ejecucion[0] == hashes_por_ejecucion[1]
    assert {ruta.name for ruta in tmp_path.iterdir()} == {
        "entrada sintética.csv",
        "salida explícita 1",
        "salida explícita 2",
        "snapshot 1.json",
        "snapshot 2.json",
    }


@pytest.mark.parametrize("clave", [None, "CLAVE_SINTETICA_NO_REAL"])
def test_generar_reportes_no_activa_openrouteservice(
    tmp_path, monkeypatch, clave
):
    llamadas = []
    if clave is None:
        monkeypatch.delenv("OPENROUTESERVICE_API_KEY", raising=False)
    else:
        monkeypatch.setenv("OPENROUTESERVICE_API_KEY", clave)
    monkeypatch.setattr(
        "atlas_core.rutas.openrouteservice.urlopen",
        lambda *_args, **_kwargs: llamadas.append(True),
    )
    entrada = tmp_path / "entrada.csv"
    _escribir_entrada(entrada, [_fila()])
    generar_reporte_viajes(
        entrada,
        tmp_path / "salida",
        carpeta_catalogos=tmp_path / "catálogos",
        reloj=RELOJ,
    )
    assert llamadas == []


def test_error_de_rutas_es_aislado_y_no_expone_credenciales(tmp_path):
    entrada = tmp_path / "entrada.csv"
    salida = tmp_path / "salida"
    _escribir_entrada(entrada, [_fila()])
    generar_reporte_viajes(
        entrada,
        salida,
        carpeta_catalogos=tmp_path / "catálogos",
        reloj=RELOJ,
    )
    hashes_antes = {
        ruta.name: _sha256(ruta) for ruta in salida.iterdir() if ruta.is_file()
    }
    class ProveedorQueFalla(ProveedorRutasSimulado):
        def calcular_ruta(self, *_args):
            raise RuntimeError(
                "OPENROUTESERVICE_API_KEY=CLAVE_QUE_NO_DEBE_APARECER"
            )

    proveedor = ProveedorQueFalla()
    resultado = CalculadorRutas(proveedor, reloj=RELOJ).calcular(_solicitud())
    assert resultado.estado == EstadoCalculoRuta.ERROR_PROVEEDOR
    assert "CLAVE_QUE_NO_DEBE_APARECER" not in repr(resultado)
    assert {
        ruta.name: _sha256(ruta) for ruta in salida.iterdir() if ruta.is_file()
    } == hashes_antes
