"""Concurrencia legítima durante el procesamiento Mobile.

Caso real c4211f4c (05-10-2026): OCR y extracción terminaron, pero al
escribir el dataset otra sesión sostenía `revalidacion_dataset`. Antes, el
`except Exception` general persistía ERROR y PULL nunca lo reintentaba. Un
`SesionOcupadaError` ahora deja el envío en su estado previo (RECIBIDO),
sin nada publicado, y se relanza para que PULL lo omita y lo reintente.
"""
from __future__ import annotations

import csv
import json
import uuid
from pathlib import Path

import pytest

from atlas_core import cloud_mobile_sync_cliente as cloud
from atlas_core import mobile
from atlas_core.almacenamiento_portable import SesionOcupadaError
from atlas_core.mobile import RepositorioEnviosMobile, procesar_envio_mobile
from atlas_core.procesamiento_masivo import COLUMNAS

DATOS = {"numero_guia": "555111", "numero_transporte": "0000999888", "chofer": "PEREZ JUAN", "indicador_revision": "OK"}


def _preparar(tmp_path: Path):
    repo = RepositorioEnviosMobile(tmp_path / "mobile")
    envio_id = str(uuid.uuid4())
    repo.recibir(
        envio_id=envio_id, imagen=b"foto-original", mime="image/jpeg",
        metadata={"chofer_id": "c1", "tipo_novedad": "", "guia_firmada_correo": False,
                  "planta_origen_informada": "AZA_COLINA"},
    )
    dataset = tmp_path / "operacion" / "actual" / "analisis_completo_guias.csv"
    dataset.parent.mkdir(parents=True)
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";").writeheader()
    return repo, envio_id, dataset


def _lock_ajeno(dataset: Path) -> Path:
    """Lock vigente de OTRA sesión (mismo formato que `bloqueo_sesion`)."""
    ruta = dataset.parent / f".atlas_lock_{mobile.NOMBRE_LOCK_DATASET_OPERACIONAL}"
    ruta.write_text(json.dumps({"pid": 1, "host": "otra-sesion", "adquirido_en": 0}), encoding="utf-8")
    return ruta


def _filas(dataset: Path) -> list[dict[str, str]]:
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


class _Procesador:
    """Doble del OCR/extracción: cuenta cuántas veces se leyó la imagen."""

    def __init__(self, datos=DATOS, error: Exception | None = None):
        self.llamadas = 0
        self._datos = datos
        self._error = error

    def __call__(self, ruta: Path):
        self.llamadas += 1
        if self._error is not None:
            raise self._error
        return dict(self._datos)


def test_lock_ocupado_al_guardar_no_deja_error_y_queda_reintentable(tmp_path):
    repo, envio_id, dataset = _preparar(tmp_path)
    antes = repo.cargar(envio_id)
    _lock_ajeno(dataset)
    procesador = _Procesador()

    with pytest.raises(SesionOcupadaError):
        procesar_envio_mobile(repo, envio_id, dataset=dataset, procesador=procesador)

    assert procesador.llamadas == 1  # el OCR/extracción sí corrió
    despues = repo.cargar(envio_id)
    assert despues["estado"] == "RECIBIDO"
    assert despues["error"] == antes["error"]
    for campo in ("imagen_sha256", "foto_original", "chofer_id", "planta_origen_informada", "capturado_en"):
        assert despues.get(campo) == antes.get(campo)
    assert "datos_ocr" not in despues
    assert not despues.get("resultado_asociacion")
    assert despues["reintento_por_bloqueo"]["intentos"] == 1
    assert "SesionOcupadaError" in despues["reintento_por_bloqueo"]["ultimo_error"]
    assert (repo.raiz / envio_id / "original.jpg").read_bytes() == b"foto-original"
    # Nada parcial publicado.
    assert _filas(dataset) == []
    assert not (dataset.parent / "decisiones_pendientes.json").exists()
    assert not (dataset.parent / "eventos_operacionales.json").exists()


def test_siguiente_intento_con_lock_libre_procesa_exactamente_una_vez(tmp_path):
    repo, envio_id, dataset = _preparar(tmp_path)
    lock = _lock_ajeno(dataset)
    procesador = _Procesador()
    with pytest.raises(SesionOcupadaError):
        procesar_envio_mobile(repo, envio_id, dataset=dataset, procesador=procesador)
    lock.unlink()

    registro = procesar_envio_mobile(repo, envio_id, dataset=dataset, procesador=procesador)

    assert registro["estado"] == "ASOCIADO"
    assert procesador.llamadas == 2
    filas = _filas(dataset)
    assert [f["archivo"] for f in filas] == [f"mobile/{envio_id}/original.jpg"]
    assert filas[0]["numero_guia"] == "555111"
    # Un intento posterior ya no toca el envío ni duplica.
    registro_2 = procesar_envio_mobile(repo, envio_id, dataset=dataset, procesador=procesador)
    assert len(_filas(dataset)) == 1
    assert registro_2["estado"] == "ASOCIADO"


def test_varios_bloqueos_consecutivos_son_idempotentes(tmp_path):
    repo, envio_id, dataset = _preparar(tmp_path)
    lock = _lock_ajeno(dataset)
    procesador = _Procesador()
    for _ in range(3):
        with pytest.raises(SesionOcupadaError):
            procesar_envio_mobile(repo, envio_id, dataset=dataset, procesador=procesador)
    registro = repo.cargar(envio_id)
    assert registro["estado"] == "RECIBIDO"
    assert registro["reintento_por_bloqueo"]["intentos"] == 3
    assert _filas(dataset) == []
    lock.unlink()
    procesar_envio_mobile(repo, envio_id, dataset=dataset, procesador=procesador)
    assert len(_filas(dataset)) == 1


def test_reintento_tras_bloqueo_posterior_a_escribir_la_fila_no_duplica(tmp_path):
    """Si el bloqueo llega después de escribir la fila (p. ej. bandeja), el
    reintento reconoce el identificador y nunca agrega una segunda fila."""
    repo, envio_id, dataset = _preparar(tmp_path)
    procesador = _Procesador()
    original = mobile._estado_final_mobile
    llamadas = {"n": 0}

    def _bloquea_una_vez(*args, **kwargs):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            raise SesionOcupadaError("lock de bandeja ocupado")
        return original(*args, **kwargs)

    mobile._estado_final_mobile = _bloquea_una_vez
    try:
        with pytest.raises(SesionOcupadaError):
            procesar_envio_mobile(repo, envio_id, dataset=dataset, procesador=procesador)
        assert repo.cargar(envio_id)["estado"] == "RECIBIDO"
        assert len(_filas(dataset)) == 1
        registro = procesar_envio_mobile(repo, envio_id, dataset=dataset, procesador=procesador)
    finally:
        mobile._estado_final_mobile = original
    assert registro["estado"] != "ERROR"
    assert len(_filas(dataset)) == 1


def test_error_funcional_real_sigue_terminando_en_error(tmp_path):
    repo, envio_id, dataset = _preparar(tmp_path)
    registro = procesar_envio_mobile(
        repo, envio_id, dataset=dataset, procesador=_Procesador(error=ValueError("imagen corrupta")),
    )
    assert registro["estado"] == "ERROR"
    assert registro["error"] == "ValueError: imagen corrupta"
    assert repo.cargar(envio_id)["estado"] == "ERROR"
    assert "reintento_por_bloqueo" not in registro


def test_dataset_mobile_admite_campo_evidencia_mayor_al_limite_csv_y_lo_conserva(tmp_path):
    repo, envio_id, dataset = _preparar(tmp_path)
    evidencia_grande = "E" * (131072 + 1)
    fila_existente = {columna: "" for columna in COLUMNAS}
    fila_existente.update({
        "archivo": "evidencia-preexistente.jpeg",
        "numero_guia": "555110",
        "numero_transporte": "0000999887",
        "resultado_atlas_ia_json": evidencia_grande,
    })
    with dataset.open("a", newline="", encoding="utf-8-sig") as archivo:
        csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";").writerow(fila_existente)

    registro = procesar_envio_mobile(repo, envio_id, dataset=dataset, procesador=_Procesador())

    assert registro["estado"] == "ASOCIADO"
    filas = mobile._filas_dataset(dataset)
    assert len(filas) == 2
    assert filas[0]["resultado_atlas_ia_json"] == evidencia_grande
    assert filas[1]["archivo"] == f"mobile/{envio_id}/original.jpg"


def test_error_csv_distinto_del_limite_no_se_oculta(tmp_path, monkeypatch):
    repo, envio_id, dataset = _preparar(tmp_path)

    def _lector_corrupto(_archivo):
        raise csv.Error("CSV malformado")

    monkeypatch.setattr(mobile, "_lector_dataset_mobile", _lector_corrupto)
    registro = procesar_envio_mobile(repo, envio_id, dataset=dataset, procesador=_Procesador())

    assert registro["estado"] == "ERROR"
    assert registro["error"] == "Error: CSV malformado"


def test_pull_omite_por_bloqueo_y_procesa_en_la_pasada_siguiente(tmp_path, monkeypatch):
    repo, envio_id, dataset = _preparar(tmp_path)
    procesador = _Procesador()
    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
    monkeypatch.setattr(mobile, "procesar_archivo", lambda ruta, **kw: procesador(ruta))
    monkeypatch.setattr(mobile, "_revalidar_asociacion_diagnosticable", lambda *a, **k: None)
    monkeypatch.setattr(mobile, "_regenerar_reporte_tras_envio_mobile", lambda *a, **k: True)
    monkeypatch.setattr(mobile, "_converger_envios_tras_reporte", lambda *a, **k: True)
    monkeypatch.setattr(mobile, "_sincronizar_contrato_v2", lambda *a, **k: None)
    lock = _lock_ajeno(dataset)

    primera = cloud.procesar_envios_recibidos(repo, dataset=dataset, carpeta_catalogos=None)
    assert primera["omitidos_por_bloqueo"] == [envio_id]
    assert primera["errores_procesamiento"] == {}
    assert repo.cargar(envio_id)["estado"] == "RECIBIDO"

    lock.unlink()
    segunda = cloud.procesar_envios_recibidos(repo, dataset=dataset, carpeta_catalogos=None)
    assert segunda["procesados"] == [envio_id]
    tercera = cloud.procesar_envios_recibidos(repo, dataset=dataset, carpeta_catalogos=None)
    assert tercera["procesados"] == []
    assert len(_filas(dataset)) == 1
    assert procesador.llamadas == 2
