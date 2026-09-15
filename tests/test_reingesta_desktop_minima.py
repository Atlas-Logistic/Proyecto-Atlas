"""Gate Desktop mínimo: no reingesta una guía ya presente por identidad completa."""
from __future__ import annotations

import csv
import json

from atlas_core import procesamiento_masivo
from atlas_core.deduplicacion_ingesta import (
    ClasificacionDuplicado,
    EvidenciaIngesta,
    clasificar_ingesta,
    sha256_binario,
)
from atlas_core.gestor_viajes import agrupar_viajes
from atlas_core.procesamiento_masivo import COLUMNAS, procesar_carpeta


def _fila(*, archivo, guia, transporte):
    fila = {columna: "" for columna in COLUMNAS}
    fila.update({
        "archivo": archivo, "estado_procesamiento": "OK", "numero_guia": guia,
        "numero_transporte": transporte, "tipo_carga": "BARRAS",
        "indicador_revision": "OK", "estado_documental": "OK",
    })
    return fila


def _escribir_dataset(ruta, filas):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerows(filas)


def _leer_dataset(ruta):
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _crear(raiz, nombre, contenido):
    ruta = raiz / nombre
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(contenido)
    return ruta


def _procesador_por_identidad(identidades):
    def procesador(ruta):
        guia, transporte = identidades[ruta.name]
        return {"numero_guia": guia, "numero_transporte": transporte, "tipo_carga": "BARRAS"}
    return procesador


def test_misma_guia_y_transporte_con_bytes_distintos_es_reingesta_y_no_agrega_fila(tmp_path):
    entrada, salida = tmp_path / "lote", tmp_path / "operacion" / "actual.csv"
    _escribir_dataset(salida, [_fila(archivo="mobile/previa.jpg", guia="472623", transporte="0000355433")])
    _crear(entrada, "nueva.jpeg", b"bytes-distintos-de-mobile")

    resumen = procesar_carpeta(
        entrada, salida, procesador=_procesador_por_identidad({"nueva.jpeg": ("472623", "0000355433")})
    )

    assert resumen["reingestas_omitidas"] == 1
    assert len(_leer_dataset(salida)) == 1
    assert resumen["decisiones_pendientes"] == []


def test_misma_guia_con_transporte_distinto_no_se_deduplica(tmp_path):
    entrada, salida = tmp_path / "lote", tmp_path / "resultado.csv"
    _escribir_dataset(salida, [_fila(archivo="previa.jpg", guia="472623", transporte="0000355433")])
    _crear(entrada, "contradiccion.jpeg", b"otro")

    resumen = procesar_carpeta(
        entrada, salida, procesador=_procesador_por_identidad({"contradiccion.jpeg": ("472623", "0000355999")})
    )

    assert resumen["reingestas_omitidas"] == 0
    assert len(_leer_dataset(salida)) == 2


def test_guia_distinta_mismo_transporte_es_guia_hermana_y_no_se_deduplica(tmp_path):
    entrada, salida = tmp_path / "lote", tmp_path / "resultado.csv"
    _escribir_dataset(salida, [_fila(archivo="previa.jpg", guia="472623", transporte="0000355433")])
    _crear(entrada, "hermana.jpeg", b"otro")

    resumen = procesar_carpeta(
        entrada, salida, procesador=_procesador_por_identidad({"hermana.jpeg": ("472624", "0000355433")})
    )

    assert resumen["reingestas_omitidas"] == 0
    assert len(_leer_dataset(salida)) == 2


def test_mismo_hash_exacto_sigue_clasificado_por_nucleo_puro():
    contenido = b"mismo binario"
    previa = EvidenciaIngesta("uno", "uno.jpeg", sha256_binario(contenido))
    entrante = EvidenciaIngesta("dos", "dos.jpeg", sha256_binario(contenido))

    assert clasificar_ingesta(entrante, [previa]) is ClasificacionDuplicado.DUPLICADO_EXACTO


def test_campos_ausentes_no_se_deduplican_automaticamente(tmp_path):
    entrada, salida = tmp_path / "lote", tmp_path / "resultado.csv"
    _escribir_dataset(salida, [_fila(archivo="previa.jpg", guia="472623", transporte="0000355433")])
    _crear(entrada, "incompleta.jpeg", b"otro")

    resumen = procesar_carpeta(
        entrada, salida, procesador=_procesador_por_identidad({"incompleta.jpeg": ("No encontrado", "0000355433")})
    )

    assert resumen["reingestas_omitidas"] == 0
    assert len(_leer_dataset(salida)) == 2


def test_472623_y_472624_reingestadas_no_agregan_filas_ni_tarjetas_y_viaje_permanece(tmp_path, monkeypatch):
    entrada, salida = tmp_path / "20260914_164800", tmp_path / "operacion" / "actual.csv"
    previas = [
        _fila(archivo="mobile/472623.jpg", guia="472623", transporte="0000355433"),
        _fila(archivo="mobile/472624.jpg", guia="472624", transporte="0000355433"),
    ]
    _escribir_dataset(salida, previas)
    _crear(entrada, "472623.jpeg", b"desktop-472623-distinto")
    _crear(entrada, "472624.jpeg", b"desktop-472624-distinto")
    viajes_antes, _ = agrupar_viajes(previas)

    def procesar_falso(ruta, **kwargs):
        kwargs["recolector_decisiones"]([{"decision_id": f"no-publicar-{ruta.stem}"}])
        return {
            "numero_guia": ruta.stem, "numero_transporte": "0000355433", "tipo_carga": "BARRAS",
        }

    monkeypatch.setattr(procesamiento_masivo, "procesar_archivo", procesar_falso)
    resumen = procesar_carpeta(
        entrada, salida, lector_ocr=object(), carpeta_catalogos=tmp_path,
        proveedor_rutas=object(), orquestador_ia=object(),
    )
    finales = _leer_dataset(salida)
    viajes_despues, _ = agrupar_viajes(finales)
    manifiesto = json.loads((salida.parent / "manifiestos_ingesta" / "20260914_164800.json").read_text(encoding="utf-8"))

    assert resumen["reingestas_omitidas"] == 2
    assert len(finales) == 2
    assert resumen["decisiones_pendientes"] == []
    assert [(v.numero_transporte, v.numeros_guia) for v in viajes_despues] == [(v.numero_transporte, v.numeros_guia) for v in viajes_antes]
    assert {e["nombre_archivo"] for e in manifiesto["seleccion"]} == {"472623.jpeg", "472624.jpeg"}
    assert all(e["sha256"] for e in manifiesto["seleccion"])
