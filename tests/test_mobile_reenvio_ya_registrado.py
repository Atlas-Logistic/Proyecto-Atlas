"""Bloque REENVÍO YA REGISTRADO -- caso real envío e8c572b1 (guía 475413,
transporte 0000362423, Leandro 06-10).

Un envío Mobile cuyo documento YA existía (`documento_ya_existe`) nunca
escribe fila propia en el dataset. `revalidar_asociacion_mobile_sin_ocr`
buscaba el `indicador_revision` fresco sólo en la fila propia, así que el
duplicado conservaba para siempre el REVISAR de la foto fija de
`datos_ocr`, aunque la fila canónica del mismo documento ya estuviera OK.
Ahora usa la fila canónica, sólo cuando es única e inequívoca.
"""
from __future__ import annotations

import csv
import hashlib
import uuid
from pathlib import Path

from atlas_core.gestor_viajes import agrupar_viajes
from atlas_core.mobile import (
    RepositorioEnviosMobile, _indicador_fila_canonica_de_reenvio, procesar_envio_mobile,
    revalidar_asociacion_mobile_sin_ocr,
)
from atlas_core.procesamiento_masivo import COLUMNAS

GUIA = "475413"
TRANSPORTE = "0000362423"


def _dataset_con_filas(ruta: Path, filas: list[dict[str, str]]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        for fila in filas:
            escritor.writerow({columna: fila.get(columna, "") for columna in COLUMNAS})


def _fila_canonica(indicador: str, *, transporte: str = TRANSPORTE, envio: str = "8fcb1e7f") -> dict[str, str]:
    return {
        "archivo": f"mobile/{envio}/original.jpg", "numero_guia": GUIA,
        "numero_transporte": transporte, "indicador_revision": indicador,
    }


def _reenvio_procesado(tmp_path: Path, dataset: Path, *, transporte_leido: str = TRANSPORTE) -> tuple[RepositorioEnviosMobile, str]:
    repo = RepositorioEnviosMobile(tmp_path)
    envio_id = str(uuid.uuid4())
    repo.recibir(
        envio_id=envio_id, imagen=b"foto", mime="image/jpeg",
        metadata={"chofer_id": "186111370", "tipo_novedad": "DEVOLUCION_TOTAL", "guia_firmada_correo": False, "planta_origen_informada": "AZA_COLINA"},
    )
    procesar_envio_mobile(
        repo, envio_id, dataset=dataset,
        procesador=lambda r: {"numero_guia": GUIA, "numero_transporte": transporte_leido, "indicador_revision": "REVISAR"},
    )
    return repo, envio_id


def _viajes(dataset: Path) -> list:
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        viajes, _sin_transporte = agrupar_viajes(list(csv.DictReader(archivo, delimiter=";")))
    return [v.numero_transporte for v in viajes]


def _huella(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


# A. duplicado sin fila propia + fila canónica única OK -> converge.
def test_reenvio_sin_fila_propia_converge_con_la_fila_canonica_ok(tmp_path: Path) -> None:
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_con_filas(dataset, [_fila_canonica("OK")])
    repo, envio_id = _reenvio_procesado(tmp_path, dataset)
    registro = repo.cargar(envio_id)
    # Estado real previo al fix: asociado, ya existente, sin fila propia, en revisión.
    assert registro["resultado_asociacion"]["estado"] == "ASOCIADO_AUTOMATICAMENTE"
    assert registro["resultado_asociacion"]["documento_ya_existe"] is True
    assert registro["archivo_dataset"] == ""
    assert registro["estado"] == "REQUIERE_REVISION"

    resumen = revalidar_asociacion_mobile_sin_ocr(repo, dataset=dataset)

    assert envio_id in resumen["actualizados"]
    revisado = repo.cargar(envio_id)
    assert revisado["estado"] == "ASOCIADO"
    assert revisado["resultado_asociacion"] == registro["resultado_asociacion"]
    # Historial del envío intacto: la foto fija de OCR no se reescribe.
    assert revisado["datos_ocr"]["indicador_revision"] == "REVISAR"


# B. la fila canónica sigue en REVISAR -> no se fuerza a OK.
def test_reenvio_no_converge_si_la_fila_canonica_sigue_en_revisar(tmp_path: Path) -> None:
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_con_filas(dataset, [_fila_canonica("REVISAR")])
    repo, envio_id = _reenvio_procesado(tmp_path, dataset)

    resumen = revalidar_asociacion_mobile_sin_ocr(repo, dataset=dataset)

    assert envio_id not in resumen["actualizados"]
    assert repo.cargar(envio_id)["estado"] == "REQUIERE_REVISION"


# C. misma guía, transporte distinto -> nunca es candidata.
def test_misma_guia_con_transporte_distinto_no_es_candidata(tmp_path: Path) -> None:
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_con_filas(dataset, [_fila_canonica("OK", transporte="0000362999")])
    repo, envio_id = _reenvio_procesado(tmp_path, dataset)
    # La asociación (por guía) apunta al transporte de la fila, no al leído.
    assert repo.cargar(envio_id)["resultado_asociacion"]["numero_transporte"] == "0000362999"

    resumen = revalidar_asociacion_mobile_sin_ocr(repo, dataset=dataset)

    assert envio_id not in resumen["actualizados"]
    assert repo.cargar(envio_id)["estado"] == "REQUIERE_REVISION"


def test_helper_ignora_filas_de_la_misma_guia_con_otro_transporte() -> None:
    asociacion = {
        "estado": "ASOCIADO_AUTOMATICAMENTE", "numero_guia": GUIA, "numero_transporte": TRANSPORTE,
        "documento_ya_existe": True,
    }
    datos = {"numero_guia": GUIA, "numero_transporte": TRANSPORTE}
    filas = [_fila_canonica("OK"), _fila_canonica("OK", transporte="0000362999", envio="otro")]
    assert _indicador_fila_canonica_de_reenvio(datos, asociacion, filas) == "OK"
    # Sin la fila del transporte leído, la de otro transporte no basta.
    assert _indicador_fila_canonica_de_reenvio(datos, asociacion, filas[1:]) is None


def test_helper_se_abstiene_sin_identificacion_o_sin_documento_existente() -> None:
    filas = [_fila_canonica("OK")]
    base = {
        "estado": "ASOCIADO_AUTOMATICAMENTE", "numero_guia": GUIA, "numero_transporte": TRANSPORTE,
        "documento_ya_existe": True,
    }
    datos = {"numero_guia": GUIA, "numero_transporte": TRANSPORTE}
    assert _indicador_fila_canonica_de_reenvio(datos, {**base, "documento_ya_existe": False}, filas) is None
    assert _indicador_fila_canonica_de_reenvio(datos, {**base, "estado": "SIN_ASOCIACION"}, filas) is None
    assert _indicador_fila_canonica_de_reenvio({**datos, "numero_transporte": "No encontrado"}, base, filas) is None
    assert _indicador_fila_canonica_de_reenvio({**datos, "numero_guia": ""}, base, filas) is None
    assert _indicador_fila_canonica_de_reenvio(datos, base, []) is None


# D. varias filas compatibles -> abstención.
def test_varias_filas_canonicas_compatibles_se_abstiene(tmp_path: Path) -> None:
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_con_filas(dataset, [_fila_canonica("OK", envio="a"), _fila_canonica("OK", envio="b")])
    repo, envio_id = _reenvio_procesado(tmp_path, dataset)

    resumen = revalidar_asociacion_mobile_sin_ocr(repo, dataset=dataset)

    assert envio_id not in resumen["actualizados"]
    assert repo.cargar(envio_id)["estado"] == "REQUIERE_REVISION"


# E. la convergencia no crea fila, viaje ni evento.
def test_convergencia_no_crea_fila_viaje_ni_evento(tmp_path: Path) -> None:
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_con_filas(dataset, [_fila_canonica("OK")])
    repo, envio_id = _reenvio_procesado(tmp_path, dataset)
    huella_antes = _huella(dataset)
    viajes_antes = _viajes(dataset)
    envios_antes = {r["envio_id"] for r in repo.historial()}
    foto = tmp_path / "operacion/mobile/envios" / envio_id / repo.cargar(envio_id)["foto_original"]
    foto_antes = _huella(foto)

    resumen = revalidar_asociacion_mobile_sin_ocr(repo, dataset=dataset)

    assert envio_id in resumen["actualizados"]
    assert _huella(dataset) == huella_antes
    viajes_despues = _viajes(dataset)
    assert viajes_despues == viajes_antes == [TRANSPORTE]
    assert {r["envio_id"] for r in repo.historial()} == envios_antes
    assert _huella(foto) == foto_antes
    assert "eventos_canonicos" not in repo.cargar(envio_id)
    assert not list(tmp_path.rglob("eventos_operacionales.json"))
