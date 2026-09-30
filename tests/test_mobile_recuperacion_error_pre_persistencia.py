import csv
import json
import uuid
from pathlib import Path
import pytest

import atlas_core.mobile as mobile
from atlas_core.mobile import ErrorEnvioMobile, RepositorioEnviosMobile, recuperar_envio_mobile_error_pre_persistencia
from atlas_core.procesamiento_masivo import COLUMNAS
from recuperar_envio_mobile_error import ejecutar_recuperacion_con_escritor


def _dataset(ruta: Path, filas: list[dict[str, str]] | None = None) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas or [])


def _envio_error(tmp_path: Path) -> tuple[RepositorioEnviosMobile, str, Path]:
    repo = RepositorioEnviosMobile(tmp_path)
    envio_id = str(uuid.uuid4())
    repo.recibir(
        envio_id=envio_id, imagen=b"foto original", mime="image/jpeg",
        metadata={
            "empresa_id": "empresa", "documento_id": "documento", "chofer_id": "chofer",
            "capturado_en": "2026-09-30T10:00:00Z", "tipo_novedad": "",
            "guia_firmada_correo": False, "planta_origen_informada": "AZA_COLINA",
        },
    )
    registro = repo.cargar(envio_id)
    registro.update({"estado": "ERROR", "error": "timeout Paddle anterior"})
    repo.guardar(envio_id, registro)
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset(dataset)
    return repo, envio_id, dataset


def test_recupera_error_pre_persistencia_por_flujo_normal_y_conserva_traza(tmp_path, monkeypatch):
    repo, envio_id, dataset = _envio_error(tmp_path)
    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
    monkeypatch.setattr(
        mobile, "procesar_archivo",
        lambda *_args, **_kwargs: {"numero_guia": "900001", "numero_transporte": "0000900000", "cliente": "CLIENTE"},
    )

    resultado = recuperar_envio_mobile_error_pre_persistencia(
        repo, envio_id, dataset=dataset, puede_escribir=lambda: True,
    )

    assert resultado["estado"] != "ERROR"
    traza = resultado["recuperacion_error_pre_persistencia"]
    assert traza["estado"] == "COMPLETADA"
    assert traza["error_anterior"] == "timeout Paddle anterior"
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo, delimiter=";"))
    assert [fila["archivo"] for fila in filas] == [f"mobile/{envio_id}/original.jpg"]


def test_recuperacion_rechaza_envio_que_ya_tiene_fila_documental(tmp_path):
    repo, envio_id, dataset = _envio_error(tmp_path)
    fila = {columna: "" for columna in COLUMNAS}
    fila["archivo"] = f"mobile/{envio_id}/original.jpg"
    _dataset(dataset, [fila])

    with pytest.raises(ErrorEnvioMobile, match="ya tiene una fila documental"):
        recuperar_envio_mobile_error_pre_persistencia(repo, envio_id, dataset=dataset, puede_escribir=lambda: True)

    registro = repo.cargar(envio_id)
    assert registro["estado"] == "ERROR"
    assert "recuperacion_error_pre_persistencia" not in registro


def test_recuperacion_rechaza_foto_cuyo_hash_no_coincide(tmp_path):
    repo, envio_id, dataset = _envio_error(tmp_path)
    (repo.raiz / envio_id / "original.jpg").write_bytes(b"foto alterada")

    with pytest.raises(ErrorEnvioMobile, match="SHA-256"):
        recuperar_envio_mobile_error_pre_persistencia(repo, envio_id, dataset=dataset, puede_escribir=lambda: True)

    assert repo.cargar(envio_id)["estado"] == "ERROR"


def test_recuperacion_requiere_guardia_de_escritor_vigente(tmp_path):
    repo, envio_id, dataset = _envio_error(tmp_path)

    with pytest.raises(ErrorEnvioMobile, match="lease global de escritor"):
        recuperar_envio_mobile_error_pre_persistencia(repo, envio_id, dataset=dataset)

    assert repo.cargar(envio_id)["estado"] == "ERROR"


class _EscritorNoAdquirido:
    vigente = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def adquirir(self):
        return False


def test_cli_no_recupera_si_no_adquiere_el_lease_global(tmp_path):
    repo, envio_id, dataset = _envio_error(tmp_path)
    resultado = ejecutar_recuperacion_con_escritor(
        base_url="https://cloud.test", token_motor="t", envio_id=envio_id,
        repositorio=repo, dataset=dataset, carpeta_catalogos=None,
        fabrica_escritor=lambda **_kwargs: _EscritorNoAdquirido(),
    )

    assert resultado == {"escritor_operativo": "NO_ADQUIRIDO", "envio_id": envio_id}
    assert repo.cargar(envio_id)["estado"] == "ERROR"
