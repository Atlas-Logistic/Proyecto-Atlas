"""Asociación RETROACTIVA de evidencia adicional (casos 473473/473523/474172):
PDFs firmados ya ingresados ANTES de existir `evidencias_adicionales.json`
se asocian desde sus manifiestos y trazas OCR existentes -- sin OCR, sin
reingesta, sin tocar el dataset -- con el MISMO registro que produciría una
reingesta actual. Todo sintético en `tmp_path`; nunca G:\\."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from atlas_core import procesamiento_masivo
from atlas_core.ingesta_pdf import NOMBRE_REGISTRO_EVIDENCIAS_ADICIONALES, leer_evidencias_adicionales
from atlas_core.procesamiento_masivo import asociar_evidencias_pdf_de_lote, procesar_carpeta
from atlas_core.revalidacion_documental import _escribir_filas_completas, _leer_filas
from tests.fixtures_pdf_sinteticos import construir_pdf, pagina_escaneada

IDENTIDADES = {"473473": "0000357567", "473523": "0000357595", "474172": "0000359308", "472941": "0000356145"}
LOTE_PDF = "20260923_152801"


@pytest.fixture(autouse=True)
def _sin_atlas_ia_por_red(monkeypatch):
    monkeypatch.setenv("ATLAS_IA_B1_OPERACIONAL", "0")


class OCRFalso:
    """OCR de prueba: lee guía+transporte del nombre (JPEG o PNG técnico)."""

    def __init__(self) -> None:
        self.llamadas = 0

    def leer_texto(self, ruta):
        self.llamadas += 1
        guia = next(g for g in IDENTIDADES if g in Path(ruta).name)
        return ["GUIA DE DESPACHO ELECTRONICA", f"N° {guia}", f"N° TRANSPORTE: {IDENTIDADES[guia]}"]

    def leer_bloques(self, ruta):
        return []

    def leer_focal(self, ruta, caja, allowlist):
        return {"recorte": None, "lecturas": []}


@pytest.fixture()
def operacion_historica(tmp_path):
    """Réplica del estado real: JPEGs originales de 473473/473523/474172 ya
    ingresados; luego un lote con sus PDFs firmados (reingesta omitida) y un
    PDF nuevo (472941, con fila propia) -- procesado cuando todavía NO
    existía el registro de evidencias adicionales (se elimina tras la
    ingesta para reproducir exactamente ese estado histórico)."""
    raiz = tmp_path / "atlas"
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    dataset.parent.mkdir(parents=True)
    lote_jpeg = raiz / "operacion" / "entradas" / "20260911_092000"
    lote_jpeg.mkdir(parents=True)
    for guia in ("473473", "473523", "474172"):
        Image.new("RGB", (40, 40), "white").save(lote_jpeg / f"{guia}.jpeg")
    procesar_carpeta(lote_jpeg, dataset, proveedor=OCRFalso(), cada=1)
    lote_pdf = raiz / "operacion" / "entradas" / LOTE_PDF
    lote_pdf.mkdir(parents=True)
    for guia in IDENTIDADES:
        (lote_pdf / f"[MBT] guia nro {guia} firmada estadia.pdf").write_bytes(
            construir_pdf([pagina_escaneada(f"GUIA {guia} FIRMADA")])
        )
    procesar_carpeta(lote_pdf, dataset, proveedor=OCRFalso(), cada=1)
    registro = raiz / "operacion" / "evidencia_pdf" / NOMBRE_REGISTRO_EVIDENCIAS_ADICIONALES
    en_vivo = leer_evidencias_adicionales(registro.parent)  # lo que produjo la reingesta actual
    registro.unlink()
    return raiz, dataset, en_vivo


def _sin_fecha(asociaciones):
    return sorted(
        ({k: v for k, v in a.items() if k != "asociado_en_utc"} for a in asociaciones),
        key=lambda a: a["documento"]["numero_guia"],
    )


def _instantanea(raiz: Path) -> dict[str, bytes]:
    """Bytes de todo lo que la asociación NO debe tocar: dataset, entradas,
    manifiestos/PNG y trazas OCR."""
    salida = {}
    for carpeta in ("operacion/actual", "operacion/entradas", "operacion/evidencia_pdf", "operacion/trazas_ocr"):
        for ruta in sorted((raiz / carpeta).rglob("*")):
            if ruta.is_file() and ruta.name != NOMBRE_REGISTRO_EVIDENCIAS_ADICIONALES:
                salida[ruta.relative_to(raiz).as_posix()] = ruta.read_bytes()
    return salida


def test_simulacion_no_escribe_y_reporta_documento_y_evidencia(operacion_historica) -> None:
    raiz, _, _ = operacion_historica
    antes = _instantanea(raiz)

    resultado = asociar_evidencias_pdf_de_lote(raiz_atlas=raiz, lote=LOTE_PDF, aplicar=False)

    por_guia = {e["numero_guia"]: e for e in resultado["evidencias_adicionales"]}
    assert sorted(por_guia) == ["473473", "473523", "474172"]
    for guia, entrada in por_guia.items():
        assert entrada["documento"] == f"{guia}.jpeg" and entrada["nueva"] is True
        assert entrada["numero_transporte"] == IDENTIDADES[guia]
        assert entrada["archivo"] == f"[MBT] guia nro {guia} firmada estadia.pdf::pagina=0001"
    assert {"archivo": f"[MBT] guia nro 472941 firmada estadia.pdf::pagina=0001",
            "motivo": "DOCUMENTO_CON_FILA_PROPIA"} in resultado["omitidas"]
    assert not (raiz / "operacion" / "evidencia_pdf" / NOMBRE_REGISTRO_EVIDENCIAS_ADICIONALES).exists()
    assert _instantanea(raiz) == antes


def test_aplicar_produce_el_mismo_registro_que_la_reingesta_actual_sin_ocr(operacion_historica, monkeypatch) -> None:
    raiz, _, en_vivo = operacion_historica
    antes = _instantanea(raiz)
    monkeypatch.setattr(procesamiento_masivo, "procesar_archivo", lambda *a, **k: pytest.fail("no debe haber OCR"))
    monkeypatch.setattr(procesamiento_masivo, "rasterizar_pdf", lambda *a, **k: pytest.fail("no debe re-rasterizar"))

    asociar_evidencias_pdf_de_lote(raiz_atlas=raiz, lote=LOTE_PDF, aplicar=True)

    retroactivas = leer_evidencias_adicionales(raiz / "operacion" / "evidencia_pdf")
    assert len(retroactivas) == 3
    assert _sin_fecha(retroactivas) == _sin_fecha(en_vivo)
    assert _instantanea(raiz) == antes  # dataset, filas, estados, fechas, derivados: idénticos


def test_catch_up_es_idempotente(operacion_historica) -> None:
    raiz, _, _ = operacion_historica
    asociar_evidencias_pdf_de_lote(raiz_atlas=raiz, lote=LOTE_PDF, aplicar=True)
    segundo = asociar_evidencias_pdf_de_lote(raiz_atlas=raiz, lote=LOTE_PDF, aplicar=True)
    assert [e["nueva"] for e in segundo["evidencias_adicionales"]] == [False, False, False]
    assert len(leer_evidencias_adicionales(raiz / "operacion" / "evidencia_pdf")) == 3


def test_documento_ambiguo_no_se_asocia(operacion_historica) -> None:
    raiz, dataset, _ = operacion_historica
    filas = _leer_filas(dataset)
    original_474172 = next(f for f in filas if f["archivo"] == "474172.jpeg")
    _escribir_filas_completas(dataset, filas + [{**original_474172, "archivo": "474172 copia.jpeg"}])

    resultado = asociar_evidencias_pdf_de_lote(raiz_atlas=raiz, lote=LOTE_PDF, aplicar=True)

    assert resultado["evidencias_adicionales_ambiguas"] == ["[MBT] guia nro 474172 firmada estadia.pdf::pagina=0001"]
    asociadas = {a["documento"]["numero_guia"] for a in leer_evidencias_adicionales(raiz / "operacion" / "evidencia_pdf")}
    assert asociadas == {"473473", "473523"}


def test_derivado_corrupto_no_se_asocia(operacion_historica) -> None:
    raiz, _, _ = operacion_historica
    png = next((raiz / "operacion" / "evidencia_pdf").glob("*473523*--p0001.png"))
    png.write_bytes(b"alterado")

    resultado = asociar_evidencias_pdf_de_lote(raiz_atlas=raiz, lote=LOTE_PDF, aplicar=True)

    assert {"archivo": "[MBT] guia nro 473523 firmada estadia.pdf::pagina=0001",
            "motivo": "DERIVADO_PNG_CORRUPTO"} in resultado["omitidas"]
    assert "473523" not in {a["documento"]["numero_guia"] for a in leer_evidencias_adicionales(raiz / "operacion" / "evidencia_pdf")}
