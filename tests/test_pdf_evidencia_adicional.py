"""PDF firmado de una guía YA existente (casos focales 473473/473523/474172):
la reingesta sigue sin crear fila ni viaje duplicados (misma guía+transporte),
pero la página PDF queda asociada como evidencia ADICIONAL del documento
existente -- sin reemplazar su evidencia original, idempotente y sólo si el
documento es inequívoco. También: el resumen de Desktop reconoce PDFs.
Todo sintético en `tmp_path`; nunca G:\\."""
from __future__ import annotations

import argparse
import csv
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from PIL import Image

import resumen_procesamiento_desktop as resumen_desktop
from atlas_core.ingesta_pdf import MOTIVO_EVIDENCIA_REINGESTA, leer_evidencias_adicionales
from atlas_core.procesamiento_masivo import procesar_carpeta
from atlas_core.revalidacion_documental import _escribir_filas_completas
from tests.fixtures_pdf_sinteticos import construir_pdf, pagina_escaneada

IDENTIDADES = {
    "473473": "0000357567",
    "473523": "0000357595",
    "474172": "0000359308",
}


@pytest.fixture(autouse=True)
def _sin_atlas_ia_por_red(monkeypatch):
    monkeypatch.setenv("ATLAS_IA_B1_OPERACIONAL", "0")


def _operacion(tmp_path: Path) -> tuple[Path, Path]:
    dataset = tmp_path / "atlas" / "operacion" / "actual" / "analisis_completo_guias.csv"
    dataset.parent.mkdir(parents=True)
    return tmp_path / "atlas", dataset


def _lote(raiz: Path, nombre: str) -> Path:
    carpeta = raiz / "operacion" / "entradas" / nombre
    carpeta.mkdir(parents=True)
    return carpeta


def _procesador_por_guia(ruta: Path) -> dict[str, str]:
    """Simula la extracción: la guía está en el nombre (del JPEG o del PNG
    técnico derivado del PDF, que conserva el nombre del original)."""
    guia = next(g for g in IDENTIDADES if g in ruta.name)
    return {"numero_guia": guia, "numero_transporte": IDENTIDADES[guia]}


def _filas(dataset: Path) -> list[dict[str, str]]:
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _pdf_firmado(carpeta: Path, guia: str, nombre: str | None = None) -> Path:
    ruta = carpeta / (nombre or f"[MBT] guia nro {guia} firmada estadia.pdf")
    ruta.write_bytes(construir_pdf([pagina_escaneada(f"GUIA {guia} FIRMADA")]))
    return ruta


@pytest.fixture()
def con_guias_existentes(tmp_path):
    """Operación con los 3 documentos focales ya ingresados como JPEG."""
    raiz, dataset = _operacion(tmp_path)
    lote = _lote(raiz, "20260911_092000")
    for guia in IDENTIDADES:
        Image.new("RGB", (40, 40), "white").save(lote / f"{guia}.jpeg")
    procesar_carpeta(lote, dataset, procesador=_procesador_por_guia, cada=1)
    return raiz, dataset


def test_pdf_firmado_de_guia_existente_queda_como_evidencia_adicional(con_guias_existentes) -> None:
    raiz, dataset = con_guias_existentes
    filas_antes = _filas(dataset)
    lote = _lote(raiz, "20260923_152801")
    pdfs = {guia: _pdf_firmado(lote, guia) for guia in IDENTIDADES}
    bytes_pdfs = {guia: ruta.read_bytes() for guia, ruta in pdfs.items()}

    resumen = procesar_carpeta(lote, dataset, procesador=_procesador_por_guia, cada=1)

    # Deduplicación intacta: ninguna fila/viaje nuevo, filas previas idénticas.
    assert resumen["reingestas_omitidas"] == 3
    assert _filas(dataset) == filas_antes
    # Cada PDF queda asociado a SU documento existente, sin reemplazarlo.
    asociaciones = leer_evidencias_adicionales(raiz / "operacion" / "evidencia_pdf")
    por_guia = {a["documento"]["numero_guia"]: a for a in asociaciones}
    assert sorted(por_guia) == sorted(IDENTIDADES)
    for guia, asociacion in por_guia.items():
        assert asociacion["documento"] == {
            "archivo": f"{guia}.jpeg", "numero_guia": guia, "numero_transporte": IDENTIDADES[guia],
        }
        assert asociacion["evidencia"]["archivo"] == f"{pdfs[guia].name}::pagina=0001"
        assert asociacion["evidencia"]["pagina"] == 1
        assert asociacion["motivo"] == MOTIVO_EVIDENCIA_REINGESTA
        assert (raiz / "operacion" / "evidencia_pdf" / asociacion["evidencia"]["imagen_tecnica"]).is_file()
    # Evidencia anterior intacta; PDF nuevo preservado.
    for guia in IDENTIDADES:
        assert (raiz / "operacion" / "entradas" / "20260911_092000" / f"{guia}.jpeg").is_file()
        assert pdfs[guia].read_bytes() == bytes_pdfs[guia]
    assert {e["numero_guia"] for e in resumen["evidencias_adicionales"]} == set(IDENTIDADES)
    assert resumen["evidencias_adicionales_ambiguas"] == []


def test_reingresar_el_mismo_pdf_no_agrega_otra_asociacion(con_guias_existentes) -> None:
    raiz, dataset = con_guias_existentes
    primero = _pdf_firmado(_lote(raiz, "20260923_152801"), "473473")
    procesar_carpeta(primero.parent, dataset, procesador=_procesador_por_guia, cada=1)
    # Mismo PDF (mismos bytes) en otro lote y con otro nombre.
    segundo_lote = _lote(raiz, "20260924_080000")
    (segundo_lote / "473473 renombrado.pdf").write_bytes(primero.read_bytes())

    resumen = procesar_carpeta(segundo_lote, dataset, procesador=_procesador_por_guia, cada=1)

    assert [e["nueva"] for e in resumen["evidencias_adicionales"]] == [False]
    assert len(leer_evidencias_adicionales(raiz / "operacion" / "evidencia_pdf")) == 1
    assert len(_filas(dataset)) == 3


def test_asociacion_ambigua_no_se_realiza(tmp_path) -> None:
    raiz, dataset = _operacion(tmp_path)
    lote = _lote(raiz, "20260917_100000")
    Image.new("RGB", (40, 40), "white").save(lote / "474172.jpeg")
    procesar_carpeta(lote, dataset, procesador=_procesador_por_guia, cada=1)
    # Dataset histórico con DOS documentos de la misma guía+transporte (la
    # reingesta actual ya no lo permitiría; se simula el estado previo).
    filas = _filas(dataset)
    _escribir_filas_completas(dataset, filas + [{**filas[0], "archivo": "474172 otra copia.jpeg"}])
    assert len(_filas(dataset)) == 2
    lote = _lote(raiz, "20260923_152801")
    pdf = _pdf_firmado(lote, "474172")

    resumen = procesar_carpeta(lote, dataset, procesador=_procesador_por_guia, cada=1)

    assert resumen["evidencias_adicionales"] == []
    assert resumen["evidencias_adicionales_ambiguas"] == [f"{pdf.name}::pagina=0001"]
    assert leer_evidencias_adicionales(raiz / "operacion" / "evidencia_pdf") == []
    assert len(_filas(dataset)) == 2


def test_imagen_duplicada_sigue_descartandose_sin_asociacion(con_guias_existentes) -> None:
    raiz, dataset = con_guias_existentes
    lote = _lote(raiz, "20260923_152801")
    Image.new("RGB", (40, 40), "black").save(lote / "473523 otra foto.jpeg")

    resumen = procesar_carpeta(lote, dataset, procesador=_procesador_por_guia, cada=1)

    assert resumen["reingestas_omitidas"] == 1 and resumen["evidencias_adicionales"] == []
    assert len(_filas(dataset)) == 3


# ------------------------------------------------------------ resumen Desktop

def _resumen(dataset: Path, nombres: list[str], viajes: list[dict[str, str]], tmp_path: Path) -> list[dict]:
    reporte = tmp_path / "reporte"
    reporte.mkdir(exist_ok=True)
    with (reporte / "viajes.csv").open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=["numero_transporte", "documentos", "estado", "numeros_guia"], delimiter=";")
        escritor.writeheader()
        escritor.writerows(viajes)
    (reporte / "documentos_sin_transporte.csv").write_text("archivo;numero_transporte\n", encoding="utf-8-sig")
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"transportes_existentes": list(IDENTIDADES.values())}), encoding="utf-8")
    salida = io.StringIO()
    with redirect_stdout(salida):
        resumen_desktop.comando_resumen(argparse.Namespace(
            csv_masivo=dataset, reporte=reporte, snapshot=snapshot, archivo=nombres,
        ))
    return json.loads(salida.getvalue())


def test_resumen_reconoce_pdf_procesado_y_pdf_asociado(con_guias_existentes, tmp_path) -> None:
    raiz, dataset = con_guias_existentes
    lote = _lote(raiz, "20260923_152801")
    asociado = _pdf_firmado(lote, "473473")
    nuevo = lote / "[MBT] guia nro 472941 firmada estadia.pdf"
    nuevo.write_bytes(construir_pdf([pagina_escaneada("GUIA 472941")]))
    IDENTIDADES_EXTRA = {"472941": "0000356145"}

    def procesador(ruta: Path) -> dict[str, str]:
        if "472941" in ruta.name:
            return {"numero_guia": "472941", "numero_transporte": IDENTIDADES_EXTRA["472941"]}
        return _procesador_por_guia(ruta)

    procesar_carpeta(lote, dataset, procesador=procesador, cada=1)
    viajes = [
        {"numero_transporte": "0000356145", "documentos": f"{nuevo.name}::pagina=0001", "estado": "CONFIRMADO", "numeros_guia": "472941"},
        {"numero_transporte": "0000357567", "documentos": "473473.jpeg", "estado": "CONFIRMADO", "numeros_guia": "473473"},
    ]

    resultados = _resumen(dataset, [nuevo.name, asociado.name], viajes, tmp_path)

    procesado, adicional = resultados
    assert procesado["archivo"] == f"{nuevo.name}::pagina=0001"
    assert procesado["encontrado"] is True and procesado["numero_transporte"] == "0000356145"
    assert procesado["es_nuevo"] is True and procesado["estado"] == "CONFIRMADO"
    assert adicional["encontrado"] is True and adicional["numero_transporte"] == "0000357567"
    assert adicional["evidencia_adicional_de"] == "473473.jpeg" and adicional["es_nuevo"] is False
    assert all(r.get("encontrado") for r in resultados)  # nunca "sin información adicional"


def test_resumen_de_jpeg_sigue_igual(con_guias_existentes, tmp_path) -> None:
    _, dataset = con_guias_existentes
    viajes = [{"numero_transporte": "0000357595", "documentos": "473523.jpeg", "estado": "CONFIRMADO", "numeros_guia": "473523"}]
    (resultado,) = _resumen(dataset, ["473523.jpeg"], viajes, tmp_path)
    assert resultado == {
        "archivo": "473523.jpeg", "encontrado": True, "sin_transporte": False,
        "numero_transporte": "0000357595", "es_nuevo": False, "estado": "CONFIRMADO", "numeros_guia": "473523",
    }
