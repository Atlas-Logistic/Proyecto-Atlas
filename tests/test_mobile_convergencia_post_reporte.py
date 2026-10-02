"""Bloque CONVERGENCIA MOBILE POST-REPORTE -- caso real 475222 (envío
6bcf5dcd, transporte 0000361953, 2026-10-02).

Secuencia real: el runner Mobile procesó la guía con `indicador_revision=
REVISAR` (OBRA_DESTINO_SIN_CORROBORAR) -> envío REQUIERE_REVISION; la batería
de `revalidar_y_regenerar_reporte` resolvió la fila (viaje CONFIRMADO) pero
el estado del envío se había derivado ANTES y quedaba en revisión hasta que
alguien pulsaba "Refrescar datos" en Desktop (`reconciliar_estado_derivado`).

Estas pruebas recorren `procesar_y_revalidar_envio_mobile` completo (sólo el
OCR y la resolución de la batería se simulan con los datos reales del caso)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

import atlas_core.mobile as mobile_mod
import atlas_core.revalidacion_documental as revalidacion_mod
from atlas_core.almacenamiento_portable import escribir_estado_operacion, leer_estado_operacion
from atlas_core.decisiones_pendientes import generar_artefacto
from atlas_core.mobile import RepositorioEnviosMobile
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.reporte_viajes import _sha256_archivo, generar_reporte_viajes

FIXTURE = Path(__file__).parent / "fixtures" / "mobile_475222"
ENVIO_ID = "6bcf5dcd-4b99-4016-a35b-23d10259c074"
TRANSPORTE = "0000361953"


def _catalogos_minimos(ruta: Path) -> Path:
    ruta.mkdir(parents=True, exist_ok=True)
    contenidos = {
        "clientes.json": {"version_formato": 1, "clientes": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "plantas.json": {"version_formato": 1, "plantas": []},
        "telemetria_cache.json": {},
        "evidencia_entidades.json": {},
        "verificacion_externa_cache.json": {},
    }
    for nombre, contenido in contenidos.items():
        (ruta / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    return ruta


def _escribir_dataset(dataset: Path, filas: list[dict[str, str]]) -> None:
    dataset.parent.mkdir(parents=True, exist_ok=True)
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";", extrasaction="ignore")
        escritor.writeheader()
        escritor.writerows([{c: fila.get(c, "") for c in COLUMNAS} for fila in filas])


def _leer_dataset(dataset: Path) -> list[dict[str, str]]:
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _fila_resuelta() -> dict[str, str]:
    return json.loads((FIXTURE / "fila_dataset_resuelta.json").read_text(encoding="utf-8"))


def _fila_recien_procesada() -> dict[str, str]:
    """La misma fila tal como la escribió el OCR (antes de la batería)."""
    fila = _fila_resuelta()
    fila.update(
        indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION",
        estado_operacional="REQUIERE_REVISION", motivos_revision_documento="OBRA_DESTINO_SIN_CORROBORAR",
    )
    return fila


@pytest.fixture()
def escenario(tmp_path: Path, monkeypatch):
    catalogos = _catalogos_minimos(tmp_path / "catalogos_privados")
    dataset = tmp_path / "operacion" / "actual" / "analisis_completo_guias.csv"
    # Operación vigente previa (otro viaje ya publicado), como en G:.
    previa = {c: "" for c in COLUMNAS}
    previa.update(
        archivo="475201.jpg", numero_guia="475201", numero_transporte="0000361852",
        estado_procesamiento="OK", indicador_revision="OK", estado_documental="OK",
        estado_operacional="OK", estado_ruta="RUTA_CALCULADA",
    )
    _escribir_dataset(dataset, [previa])
    reporte_previo = tmp_path / "reportes" / "reporte_previo"
    generar_reporte_viajes(
        dataset, reporte_previo, carpeta_catalogos=catalogos,
        ruta_ledger=dataset.parent / "decisiones_aplicadas.json",
    )
    escribir_estado_operacion(
        reporte_vigente=reporte_previo, dataset_operacional=dataset,
        dataset_sha256=_sha256_archivo(dataset), raiz=tmp_path,
    )
    repo = RepositorioEnviosMobile(raiz_atlas=tmp_path)
    carpeta = repo.raiz / ENVIO_ID
    carpeta.mkdir(parents=True)
    (carpeta / "original.jpg").write_bytes(b"foto")
    registro_real = json.loads((FIXTURE / "envio.json").read_text(encoding="utf-8"))
    recibido = {k: v for k, v in registro_real.items() if k not in ("datos_ocr", "resultado_asociacion", "procesado_en")}
    recibido.update(estado="RECIBIDO", archivo_dataset="")
    repo.guardar(ENVIO_ID, recibido)

    def procesar_envio_mobile_real_475222(repositorio, envio_id, *, dataset=None, carpeta_catalogos=None):
        # Lo que dejó el runner a las 14:34:32: fila REVISAR + envío en revisión.
        _escribir_dataset(dataset, [*_leer_dataset(dataset), _fila_recien_procesada()])
        generar_artefacto(
            ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[],
            ruta_salida=dataset.parent / "decisiones_pendientes.json",
        )
        registro = repositorio.cargar(envio_id)
        registro.update(
            estado=registro_real["estado"],  # REQUIERE_REVISION
            datos_ocr=registro_real["datos_ocr"],
            resultado_asociacion=registro_real["resultado_asociacion"],
            archivo_dataset=registro_real["archivo_dataset"], error="",
        )
        repositorio.guardar(envio_id, registro)
        return registro

    reconciliador_real = revalidacion_mod.revalidar_y_regenerar_reporte
    llamadas_reporte: list[str] = []

    def bateria_que_resuelve_la_obra(*, raiz_atlas, nombre_carpeta_reporte, **kwargs):
        # La batería real (14:34:40-14:36:04) dejó la fila OK / RUTA_CALCULADA.
        llamadas_reporte.append(nombre_carpeta_reporte)
        filas = [
            _fila_resuelta() if f.get("archivo") == f"mobile/{ENVIO_ID}/original.jpg" else f
            for f in _leer_dataset(dataset)
        ]
        _escribir_dataset(dataset, filas)
        return reconciliador_real(raiz_atlas=raiz_atlas, nombre_carpeta_reporte=nombre_carpeta_reporte, **kwargs)

    monkeypatch.setattr(mobile_mod, "procesar_envio_mobile", procesar_envio_mobile_real_475222)
    monkeypatch.setattr(revalidacion_mod, "revalidar_y_regenerar_reporte", bateria_que_resuelve_la_obra)
    return {"raiz": tmp_path, "repo": repo, "dataset": dataset, "catalogos": catalogos, "llamadas_reporte": llamadas_reporte}


def _viajes_vigentes(raiz: Path) -> list[dict[str, str]]:
    estado = leer_estado_operacion(raiz=raiz)
    with (raiz / estado["reporte_vigente"] / "viajes.csv").open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def test_475222_envio_converge_a_asociado_sin_refresco_manual(escenario) -> None:
    repo, raiz = escenario["repo"], escenario["raiz"]

    salida = mobile_mod.procesar_y_revalidar_envio_mobile(
        repo, ENVIO_ID, dataset=escenario["dataset"], carpeta_catalogos=escenario["catalogos"],
    )

    assert salida == {"procesamiento_ok": True, "reconciliacion_ok": True}
    registro = repo.cargar(ENVIO_ID)
    # Antes del fix quedaba REQUIERE_REVISION hasta "Refrescar datos".
    assert registro["estado"] == "ASOCIADO"
    assert registro["resultado_asociacion"]["estado"] == "SIN_ASOCIACION"
    assert registro["reconciliacion_reporte"]["estado"] == "OK"
    # El mismo pase dejó el viaje publicado: nada pendiente para Desktop.
    viajes = [v for v in _viajes_vigentes(raiz) if v["numero_transporte"] == TRANSPORTE]
    assert [v["estado"] for v in viajes] == ["CONFIRMADO"]
    pendientes_desktop = [r for r in repo.historial() if r.get("estado") == "REQUIERE_REVISION"]
    assert pendientes_desktop == []
    # Sin datos nuevos tras converger: un solo reporte, nunca un bucle.
    assert len(escenario["llamadas_reporte"]) == 1


def test_convergencia_que_escribe_el_dataset_publica_un_segundo_reporte_automatico(escenario, monkeypatch) -> None:
    """La convergencia post-reporte genera datos nuevos (respaldo de lote
    corrige un transporte en el dataset): el reporte recién publicado quedó
    viejo y debe regenerarse solo, UNA vez, en el mismo pase."""
    repo, raiz, dataset = escenario["repo"], escenario["raiz"], escenario["dataset"]
    revalidar_real = mobile_mod.revalidar_asociacion_mobile_sin_ocr
    llamadas: list[int] = []

    def revalidar_con_respaldo_de_lote(repositorio, *, dataset):
        resultado = revalidar_real(repositorio, dataset=dataset)
        llamadas.append(1)
        if len(llamadas) == 2:  # la pasada POST-reporte
            hermana = {c: "" for c in COLUMNAS}
            hermana.update(
                archivo="mobile/hermana-lote/original.jpg", numero_guia="475223", numero_transporte="0000361954",
                estado_procesamiento="OK", indicador_revision="OK", estado_documental="OK", estado_operacional="OK",
            )
            _escribir_dataset(dataset, [*_leer_dataset(dataset), hermana])
        return resultado

    monkeypatch.setattr(mobile_mod, "revalidar_asociacion_mobile_sin_ocr", revalidar_con_respaldo_de_lote)

    salida = mobile_mod.procesar_y_revalidar_envio_mobile(
        repo, ENVIO_ID, dataset=dataset, carpeta_catalogos=escenario["catalogos"],
    )

    assert salida["reconciliacion_ok"] is True
    assert len(llamadas) == 2  # pre-reporte + post-reporte; nunca una tercera
    assert len(escenario["llamadas_reporte"]) == 2  # segunda actualización automática, acotada
    transportes = {v["numero_transporte"] for v in _viajes_vigentes(raiz)}
    assert {TRANSPORTE, "0000361954"} <= transportes
    assert repo.cargar(ENVIO_ID)["estado"] == "ASOCIADO"


def test_fallo_del_reporte_no_dispara_convergencia_ni_segundo_reporte(escenario, monkeypatch) -> None:
    llamadas: list[int] = []
    monkeypatch.setattr(
        mobile_mod, "revalidar_asociacion_mobile_sin_ocr",
        lambda repositorio, *, dataset: llamadas.append(1) or {"revisados": 0, "actualizados": []},
    )

    def reporte_roto(**_kwargs):
        raise RuntimeError("dataset ocupado (simulado)")

    monkeypatch.setattr(revalidacion_mod, "revalidar_y_regenerar_reporte", reporte_roto)

    salida = mobile_mod.procesar_y_revalidar_envio_mobile(
        escenario["repo"], ENVIO_ID, dataset=escenario["dataset"], carpeta_catalogos=escenario["catalogos"],
    )

    assert salida["reconciliacion_ok"] is False  # el runner lo reintenta como siempre
    assert len(llamadas) == 1


def test_fixture_475222_refleja_el_caso_real() -> None:
    registro = json.loads((FIXTURE / "envio.json").read_text(encoding="utf-8"))
    fila = _fila_resuelta()
    assert registro["envio_id"] == ENVIO_ID
    assert registro["datos_ocr"]["indicador_revision"] == "REVISAR"
    assert registro["datos_ocr"]["motivos_revision_documento"] == "OBRA_DESTINO_SIN_CORROBORAR"
    assert fila["numero_transporte"] == TRANSPORTE and fila["indicador_revision"] == "OK"
