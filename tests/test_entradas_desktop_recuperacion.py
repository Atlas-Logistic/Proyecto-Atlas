"""Bloque RECUPERACIÓN DE ENTRADAS DESKTOP -- caso real 475193 (lote
20261002_125747): imagen copiada + `_snapshot_antes.json`, Desktop cerrado
antes de `analizar_guias_masivo.py`; al reabrir nadie la retomaba.

`ejecutar` usa el `procesar_carpeta` real (manifiesto + filas reales); sólo
el OCR se reemplaza por un procesador falso."""
from __future__ import annotations

import csv
import json
import os
import time
from pathlib import Path

import pytest

import retomar_entradas_desktop
from atlas_core.entradas_desktop import (
    COPIA_INCOMPLETA, INICIADA_SIN_RESULTADO, NUNCA_INICIADA, OCUPADA, PARCIAL_SIN_MANIFIESTO, PROCESADA,
    RECIENTE, RETOMADA, clasificar_entradas_desktop, entradas_para_retomar, retomar_entrada_desktop,
)
from atlas_core.procesamiento_masivo import COLUMNAS, procesar_carpeta

LOTE = "20261002_125747"
GUIA = "475193.jpeg"
HACE_UNA_HORA = time.time() - 3600


def _raiz(tmp_path: Path) -> Path:
    dataset = tmp_path / "operacion" / "actual" / "analisis_completo_guias.csv"
    dataset.parent.mkdir(parents=True)
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";").writeheader()
    return tmp_path


def _entrada(raiz: Path, lote: str = LOTE, archivos=(GUIA,), *, snapshot: bool = True, antiguedad: float = 3600) -> Path:
    carpeta = raiz / "operacion" / "entradas" / lote
    carpeta.mkdir(parents=True)
    for nombre in archivos:
        (carpeta / nombre).write_bytes(b"jpeg-" + nombre.encode())
    if snapshot:
        (carpeta / "_snapshot_antes.json").write_text(json.dumps({"transportes_existentes": []}), encoding="utf-8")
    instante = time.time() - antiguedad
    for ruta in carpeta.iterdir():
        os.utime(ruta, (instante, instante))
    return carpeta


def _dataset(raiz: Path) -> Path:
    return raiz / "operacion" / "actual" / "analisis_completo_guias.csv"


def _filas(raiz: Path) -> list[dict[str, str]]:
    with _dataset(raiz).open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _manifiesto(raiz: Path, lote: str = LOTE) -> Path:
    return raiz / "operacion" / "actual" / "manifiestos_ingesta" / f"{lote}.json"


def _ejecutor_real(raiz: Path, llamadas: list[Path], *, falla_ocr: bool = False):
    def procesador(ruta: Path):
        if falla_ocr:
            raise RuntimeError("OCR falló (simulado)")
        return {"numero_guia": ruta.stem, "numero_transporte": "0000361830"}

    def ejecutar(carpeta: Path) -> None:
        llamadas.append(carpeta)
        procesar_carpeta(carpeta, _dataset(raiz), procesador=procesador)

    return ejecutar


def test_475193_entrada_nunca_iniciada_se_retoma_con_la_misma_entrada(tmp_path: Path) -> None:
    raiz = _raiz(tmp_path)
    carpeta = _entrada(raiz)
    assert entradas_para_retomar(raiz) == [LOTE]
    llamadas: list[Path] = []

    resultado = retomar_entrada_desktop(raiz, LOTE, ejecutar=_ejecutor_real(raiz, llamadas))

    assert resultado["estado"] == RETOMADA and resultado["archivos"] == [GUIA]
    assert llamadas == [carpeta]  # la MISMA carpeta, nunca una copia
    assert sorted(p.name for p in (raiz / "operacion" / "entradas").iterdir()) == [LOTE]
    manifiesto = json.loads(_manifiesto(raiz).read_text(encoding="utf-8"))
    assert manifiesto["lote"] == LOTE and [s["nombre_archivo"] for s in manifiesto["seleccion"]] == [GUIA]
    assert [f["archivo"] for f in _filas(raiz)] == [GUIA]
    assert clasificar_entradas_desktop(raiz)[0]["estado"] == PROCESADA


def test_dos_arranques_no_duplican(tmp_path: Path) -> None:
    raiz = _raiz(tmp_path)
    _entrada(raiz)
    llamadas: list[Path] = []
    ejecutar = _ejecutor_real(raiz, llamadas)

    primero = retomar_entrada_desktop(raiz, LOTE, ejecutar=ejecutar)
    segundo = retomar_entrada_desktop(raiz, LOTE, ejecutar=ejecutar)

    assert primero["estado"] == RETOMADA
    assert segundo == {"lote": LOTE, "estado": PROCESADA, "retomada": False}
    assert len(llamadas) == 1
    assert len(_filas(raiz)) == 1
    assert entradas_para_retomar(raiz) == []


def test_entrada_ya_procesada_no_se_toca(tmp_path: Path) -> None:
    raiz = _raiz(tmp_path)
    carpeta = _entrada(raiz)
    procesar_carpeta(carpeta, _dataset(raiz), procesador=lambda ruta: {"numero_guia": "475193"})
    llamadas: list[Path] = []

    resultado = retomar_entrada_desktop(raiz, LOTE, ejecutar=_ejecutor_real(raiz, llamadas))

    assert resultado["estado"] == PROCESADA and llamadas == []
    assert len(_filas(raiz)) == 1


def test_guia_ya_presente_en_el_dataset_desde_otro_lote_no_se_reingresa(tmp_path: Path) -> None:
    raiz = _raiz(tmp_path)
    _entrada(raiz, lote="20261002_104201")
    procesar_carpeta(raiz / "operacion" / "entradas" / "20261002_104201", _dataset(raiz),
                     procesador=lambda ruta: {"numero_guia": "475193"})
    _entrada(raiz)  # misma guía, otro lote sin manifiesto
    assert [c["estado"] for c in clasificar_entradas_desktop(raiz)] == [PROCESADA, PROCESADA]
    assert entradas_para_retomar(raiz) == []


def test_procesamiento_interrumpido_tras_manifiesto_no_se_reingresa(tmp_path: Path) -> None:
    raiz = _raiz(tmp_path)
    _entrada(raiz)
    # El flujo normal escribió el manifiesto y se cayó antes de la fila.
    _manifiesto(raiz).parent.mkdir(parents=True)
    _manifiesto(raiz).write_text(json.dumps({"lote": LOTE, "seleccion": []}), encoding="utf-8")
    llamadas: list[Path] = []

    resultado = retomar_entrada_desktop(raiz, LOTE, ejecutar=_ejecutor_real(raiz, llamadas))

    assert resultado["estado"] == INICIADA_SIN_RESULTADO and llamadas == []
    assert _filas(raiz) == []


def test_error_de_ocr_queda_registrado_y_no_se_reintenta_ciegamente(tmp_path: Path) -> None:
    raiz = _raiz(tmp_path)
    _entrada(raiz)
    llamadas: list[Path] = []

    retomar_entrada_desktop(raiz, LOTE, ejecutar=_ejecutor_real(raiz, llamadas, falla_ocr=True))
    segundo = retomar_entrada_desktop(raiz, LOTE, ejecutar=_ejecutor_real(raiz, llamadas))

    assert len(llamadas) == 1
    assert segundo["estado"] != RETOMADA
    assert "OCR falló" in _filas(raiz)[0]["error"]


@pytest.mark.parametrize("preparar, esperado", [
    (lambda raiz: _entrada(raiz, snapshot=False), COPIA_INCOMPLETA),
    (lambda raiz: _entrada(raiz, antiguedad=10), RECIENTE),
])
def test_estados_ambiguos_o_en_curso_no_se_retoman(tmp_path: Path, preparar, esperado) -> None:
    raiz = _raiz(tmp_path)
    preparar(raiz)
    llamadas: list[Path] = []

    resultado = retomar_entrada_desktop(raiz, LOTE, ejecutar=_ejecutor_real(raiz, llamadas))

    assert resultado["estado"] == esperado and llamadas == []


def test_snapshot_ilegible_es_copia_incompleta(tmp_path: Path) -> None:
    raiz = _raiz(tmp_path)
    carpeta = _entrada(raiz)
    (carpeta / "_snapshot_antes.json").write_text('{"transportes_exis', encoding="utf-8")
    os.utime(carpeta / "_snapshot_antes.json", (HACE_UNA_HORA, HACE_UNA_HORA))
    assert clasificar_entradas_desktop(raiz)[0]["estado"] == COPIA_INCOMPLETA


def test_lote_historico_parcial_sin_manifiesto_no_se_retoma(tmp_path: Path) -> None:
    """Real en G: (20260914_164800): anterior a los manifiestos, 9 de 11 en el dataset."""
    raiz = _raiz(tmp_path)
    carpeta = _entrada(raiz, lote="20260914_164800", archivos=("a.jpeg", "b.jpeg"))
    procesar_carpeta(carpeta, _dataset(raiz), procesador=lambda ruta: {"numero_guia": "1"})
    _manifiesto(raiz, "20260914_164800").unlink()
    (carpeta / "c.jpeg").write_bytes(b"x")
    os.utime(carpeta / "c.jpeg", (HACE_UNA_HORA, HACE_UNA_HORA))
    assert clasificar_entradas_desktop(raiz)[0]["estado"] == PARCIAL_SIN_MANIFIESTO
    assert entradas_para_retomar(raiz) == []


def test_lock_ocupado_no_compite(tmp_path: Path) -> None:
    raiz = _raiz(tmp_path)
    _entrada(raiz)
    llamadas: list[Path] = []
    anidado: dict[str, object] = {}

    def ejecutar(carpeta: Path) -> None:
        # Un segundo arranque mientras el primero procesa el mismo lote.
        anidado.update(retomar_entrada_desktop(raiz, LOTE, ejecutar=_ejecutor_real(raiz, llamadas)))
        _ejecutor_real(raiz, llamadas)(carpeta)

    primero = retomar_entrada_desktop(raiz, LOTE, ejecutar=ejecutar)

    assert primero["estado"] == RETOMADA
    assert anidado["estado"] == OCUPADA
    assert len(llamadas) == 1 and len(_filas(raiz)) == 1


def test_cli_listar_es_solo_lectura(tmp_path: Path, capsys) -> None:
    raiz = _raiz(tmp_path)
    _entrada(raiz)
    _entrada(raiz, lote="20261002_114359", archivos=("475200.jpeg",), snapshot=False)
    antes = {p: p.stat().st_mtime for p in raiz.rglob("*")}

    retomar_entradas_desktop.main(["--raiz-atlas", str(raiz), "--listar"])

    salida = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert [p["lote"] for p in salida["pendientes"]] == [LOTE]
    assert {p: p.stat().st_mtime for p in raiz.rglob("*")} == antes
    assert not _manifiesto(raiz).exists()


def test_cli_lote_invalido_no_escapa_de_entradas(tmp_path: Path, capsys) -> None:
    raiz = _raiz(tmp_path)
    resultado = retomar_entrada_desktop(raiz, "../actual", ejecutar=lambda c: pytest.fail("no debe ejecutar"))
    assert resultado["estado"] == "LOTE_INVALIDO"


def test_cli_lote_usa_el_mismo_analizador_que_desktop_sobre_la_entrada_existente(tmp_path: Path, capsys, monkeypatch) -> None:
    import analizar_guias_masivo

    raiz = _raiz(tmp_path)
    carpeta = _entrada(raiz)
    recibidos: list[list[str]] = []
    monkeypatch.setattr(analizar_guias_masivo, "main", lambda argv: recibidos.append(argv))

    retomar_entradas_desktop.main([
        "--raiz-atlas", str(raiz), "--lote", LOTE, "--salida", str(_dataset(raiz)), "--catalogos", str(raiz / "cat"),
    ])

    assert recibidos == [[str(carpeta), "--salida", str(_dataset(raiz)), "--catalogos", str(raiz / "cat"), "--reconciliar-focal"]]
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["estado"] == RETOMADA
