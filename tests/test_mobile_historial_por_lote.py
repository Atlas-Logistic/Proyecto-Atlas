"""Revalidación Mobile -- una sola lectura completa de `historial()` por
pasada; el respaldo por lote relee sólo los hermanos del envío.

Las pruebas de comportamiento (transitividad, llegada y borrado durante la
pasada) describen lo que ya hacía la relectura completa de `historial()`
y deben pasar igual con la versión acotada."""
from __future__ import annotations

import csv
import shutil
import uuid
from pathlib import Path

from atlas_core.mobile import (
    RepositorioEnviosMobile, procesar_envio_mobile, revalidar_asociacion_mobile_sin_ocr,
)
from atlas_core.procesamiento_masivo import COLUMNAS


def _dataset_con_filas(ruta: Path, filas: list[dict[str, str]]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        for fila in filas:
            escritor.writerow({columna: fila.get(columna, "") for columna in COLUMNAS})


def _recibir(repo: RepositorioEnviosMobile, *, lote_id: str = "") -> str:
    envio_id = str(uuid.uuid4())
    metadata: dict[str, object] = {
        "chofer_id": "c1", "tipo_novedad": "", "guia_firmada_correo": False,
        "planta_origen_informada": "AZA_COLINA",
    }
    if lote_id:
        metadata["lote_id"] = lote_id
    repo.recibir(envio_id=envio_id, imagen=b"foto", mime="image/jpeg", metadata=metadata)
    return envio_id


def _procesar(repo, envio_id, dataset, guia: str, transporte: str) -> dict:
    return procesar_envio_mobile(
        repo, envio_id, dataset=dataset,
        procesador=lambda ruta: {"numero_guia": guia, "numero_transporte": transporte},
    )


class _RepositorioContado(RepositorioEnviosMobile):
    def __init__(self, raiz: Path) -> None:
        super().__init__(raiz)
        self.lecturas_historial = 0
        self.lecturas_cargar = 0

    def historial(self) -> list[dict]:
        self.lecturas_historial += 1
        return super().historial()

    def cargar(self, envio_id: str) -> dict:
        self.lecturas_cargar += 1
        return super().cargar(envio_id)


def test_hermano_que_converge_en_la_misma_pasada_cuenta_para_los_siguientes(tmp_path: Path) -> None:
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_con_filas(dataset, [])
    repo = RepositorioEnviosMobile(tmp_path)
    lote = str(uuid.uuid4())
    # El primero en llegar trae transporte legible, pero la operación
    # todavía no lo conoce -> queda SIN_ASOCIACION, igual que sus hermanos.
    e_lider = _recibir(repo, lote_id=lote)
    e_2 = _recibir(repo, lote_id=lote)
    e_3 = _recibir(repo, lote_id=lote)
    _procesar(repo, e_lider, dataset, "T1", "0000900000")
    _procesar(repo, e_2, dataset, "T2", "No encontrado")
    _procesar(repo, e_3, dataset, "T3", "No encontrado")
    assert repo.cargar(e_lider)["resultado_asociacion"]["estado"] == "SIN_ASOCIACION"

    # Aparece el transporte en la operación: en UNA pasada el líder se
    # asocia y, como se recorre por orden de llegada, sus hermanos lo ven
    # ya resuelto (relectura fresca, no el snapshot inicial).
    _dataset_con_filas(dataset, [
        {"archivo": "desktop/otra.jpg", "numero_guia": "999", "numero_transporte": "0000900000"},
        *[{"archivo": f"mobile/{e}/original.jpg", "numero_guia": g, "numero_transporte": t}
          for e, g, t in ((e_lider, "T1", "0000900000"), (e_2, "T2", "No encontrado"), (e_3, "T3", "No encontrado"))],
    ])
    resultado = revalidar_asociacion_mobile_sin_ocr(repo, dataset=dataset)

    assert set(resultado["actualizados"]) >= {e_lider, e_2, e_3}
    for envio_id in (e_lider, e_2, e_3):
        asociacion = repo.cargar(envio_id)["resultado_asociacion"]
        assert asociacion["estado"] == "ASOCIADO_AUTOMATICAMENTE"
        assert asociacion["numero_transporte"] == "0000900000"


def test_hermano_que_llega_durante_la_pasada_cuenta(tmp_path: Path) -> None:
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_con_filas(dataset, [{"archivo": "desktop/otra.jpg", "numero_guia": "999", "numero_transporte": "0000910000"}])
    repo = RepositorioEnviosMobile(tmp_path)
    lote = str(uuid.uuid4())
    e_falla = _recibir(repo, lote_id=lote)
    _procesar(repo, e_falla, dataset, "L1", "No encontrado")
    e_tardio = _recibir(repo, lote_id=lote)
    _procesar(repo, e_tardio, dataset, "L2", "0000910000")

    class _SnapshotSinTardio(RepositorioEnviosMobile):
        primera = True

        def historial(self) -> list[dict]:
            registros = super().historial()
            if self.primera:  # el snapshot inicial se tomó antes de que llegara
                self.primera = False
                return [r for r in registros if r["envio_id"] != e_tardio]
            return registros

    revalidar_asociacion_mobile_sin_ocr(_SnapshotSinTardio(tmp_path), dataset=dataset)

    asociacion = repo.cargar(e_falla)["resultado_asociacion"]
    assert asociacion["estado"] == "ASOCIADO_AUTOMATICAMENTE"
    assert asociacion["numero_transporte"] == "0000910000"


def test_hermano_borrado_durante_la_pasada_no_cuenta_ni_rompe(tmp_path: Path) -> None:
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_con_filas(dataset, [{"archivo": "desktop/otra.jpg", "numero_guia": "999", "numero_transporte": "0000920000"}])
    repo = RepositorioEnviosMobile(tmp_path)
    lote = str(uuid.uuid4())
    e_falla = _recibir(repo, lote_id=lote)
    _procesar(repo, e_falla, dataset, "D1", "No encontrado")
    e_borrado = _recibir(repo, lote_id=lote)
    _procesar(repo, e_borrado, dataset, "D2", "0000920000")

    class _SnapshotConBorrado(RepositorioEnviosMobile):
        primera = True

        def historial(self) -> list[dict]:
            registros = super().historial()
            if self.primera:  # el hermano desaparece justo después del snapshot
                self.primera = False
                shutil.rmtree(self.raiz / e_borrado)
            return registros

    revalidar_asociacion_mobile_sin_ocr(_SnapshotConBorrado(tmp_path), dataset=dataset)

    assert repo.cargar(e_falla)["resultado_asociacion"]["estado"] == "SIN_ASOCIACION"


def test_una_sola_lectura_completa_del_historial_por_pasada(tmp_path: Path) -> None:
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_con_filas(dataset, [])
    base = RepositorioEnviosMobile(tmp_path)
    # 8 envíos reintentables, cada uno en su propio lote (caso dominante
    # real: 106 de 116 lotes tienen un solo envío) + un lote de 3.
    for i in range(8):
        _procesar(base, _recibir(base, lote_id=str(uuid.uuid4())), dataset, f"S{i}", "No encontrado")
    lote = str(uuid.uuid4())
    for i in range(3):
        _procesar(base, _recibir(base, lote_id=lote), dataset, f"M{i}", "No encontrado")

    repo = _RepositorioContado(tmp_path)
    resultado = revalidar_asociacion_mobile_sin_ocr(repo, dataset=dataset)

    assert resultado["revisados"] == 11
    assert repo.lecturas_historial == 1
    # Una relectura propia por envío revisado + 2 hermanos por cada envío
    # del lote de 3. Antes eran 11 lecturas completas de 11 envíos.
    assert repo.lecturas_cargar == 11 + 3 * 2
