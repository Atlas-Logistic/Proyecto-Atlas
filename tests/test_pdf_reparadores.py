"""Reparadores y revalidación sobre documentos que vinieron de un PDF.

Cadena completa, todo sintético en `tmp_path` (nunca G:\\): la ingesta real
(`procesar_carpeta`) deja filas `lote.pdf::pagina=NNNN`, PNG técnicos,
sidecars de texto y manifiesto en `operacion/evidencia_pdf/`; después
`resolver_ruta_evidencia` + los reparadores existentes deben releer
EXACTAMENTE esa página, con la misma fuente que usó la ingesta (texto
embebido -> `ProveedorPaginaPdf`; OCR -> el proveedor OCR recibido), sin
tocar el PDF original y absteniéndose de forma auditable si el derivado
falta sin original o está corrupto."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from atlas_core import reprocesamiento_reparador as m
from atlas_core.evidencia_documental import (
    UBICACION_DERIVADA_PDF, UBICACION_EVIDENCIA_PDF_AMBIGUA, UBICACION_EVIDENCIA_PDF_CORRUPTA,
    UBICACION_NO_ENCONTRADA, documentos_con_revision_pendiente,
    mover_evidencia_resuelta_sin_revision_pendiente, resolver_ruta_evidencia,
)
from atlas_core.ingesta_pdf import ProveedorPaginaPdf
from atlas_core.procesamiento_masivo import procesar_carpeta
from atlas_core.revalidacion_documental import (
    _escribir_filas_completas, _leer_filas, reprocesar_material_focal_desde_imagen_original,
)
from tests.fixtures_pdf_sinteticos import construir_pdf, pagina_escaneada, pagina_texto

MATERIAL = "B HORMIGON 25MM 12M A630-420H (N)"


@pytest.fixture(autouse=True)
def _sin_atlas_ia_por_red(monkeypatch):
    monkeypatch.setenv("ATLAS_IA_B1_OPERACIONAL", "0")


class OCRFalso:
    def __init__(self) -> None:
        self.leer_texto_llamadas: list[Path] = []

    def leer_texto(self, ruta_imagen):
        self.leer_texto_llamadas.append(Path(ruta_imagen))
        return ["GUIA DE DESPACHO ELECTRONICA", "N° 500001"]

    def leer_bloques(self, ruta_imagen):
        return []

    def leer_focal(self, ruta_imagen, caja, allowlist):
        return {"recorte": None, "lecturas": []}


def _pdf_mixto(ruta: Path) -> None:
    """p1 texto (guía 472601, con material), p2 escaneada, p3 texto (472603)."""
    cabecera = ["GUIA DE DESPACHO ELECTRONICA", "SEÑOR(ES): CONSTRUCTORA ÑUÑOA LIMITADA"]
    ruta.write_bytes(construir_pdf([
        pagina_texto(cabecera[0], "N° 472601", cabecera[1], MATERIAL),
        pagina_escaneada("GUIA ESCANEADA"),
        pagina_texto(cabecera[0], "N° 472603", cabecera[1]),
    ]))


@pytest.fixture()
def atlas_con_pdf(tmp_path):
    """raiz_atlas con `operacion/entradas/LOTE1/lote.pdf` ya ingerido."""
    raiz = tmp_path / "atlas"
    lote = raiz / "operacion" / "entradas" / "LOTE1"
    lote.mkdir(parents=True)
    (raiz / "catalogos_privados").mkdir(parents=True)
    _pdf_mixto(lote / "lote.pdf")
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    dataset.parent.mkdir(parents=True)
    procesar_carpeta(lote, dataset, proveedor=OCRFalso(), cada=1)
    # Transportes distintos por página para poder revalidar por transporte.
    filas = _leer_filas(dataset)
    for fila in filas:
        pagina = fila["archivo"].rsplit("=", 1)[1]
        fila["numero_transporte"] = f"000090{pagina}"
    _escribir_filas_completas(dataset, filas)
    (raiz / "operacion" / "actual" / "decisiones_aplicadas.json").write_text('{"aplicaciones": []}', encoding="utf-8")
    return raiz


def _evidencia_pdf(raiz: Path) -> Path:
    return raiz / "operacion" / "evidencia_pdf"


def _capturar_procesar_archivo(monkeypatch, llamadas: list[dict], respuesta=None):
    def falso(ruta, **kw):
        llamadas.append({"ruta": Path(ruta), **kw})
        return dict(respuesta or {})
    monkeypatch.setattr(m, "procesar_archivo", falso)


def _stub_reconciliacion(monkeypatch):
    monkeypatch.setattr(m, "revalidar_y_regenerar_reporte", lambda **kw: {"reporte_vigente": "stub"})


# ------------------------------------------------------------ resolución exacta

def test_la_ingesta_deja_filas_por_pagina_y_el_resolver_encuentra_cada_png(atlas_con_pdf) -> None:
    raiz = atlas_con_pdf
    filas = _leer_filas(raiz / "operacion" / "actual" / "analisis_completo_guias.csv")
    assert [f["archivo"] for f in filas] == [f"lote.pdf::pagina={n:04d}" for n in (1, 2, 3)]
    for n, con_texto in ((1, True), (2, False), (3, True)):
        evidencia = resolver_ruta_evidencia(raiz, f"lote.pdf::pagina={n:04d}")
        assert evidencia.ubicacion == UBICACION_DERIVADA_PDF
        assert evidencia.pagina_pdf == n
        assert evidencia.ruta.name.endswith(f"--p{n:04d}.png")
        assert evidencia.ruta.parent == _evidencia_pdf(raiz)
        assert (evidencia.ruta_texto_pdf is not None) == con_texto
        if con_texto:
            assert evidencia.ruta_texto_pdf.name.endswith(f"--p{n:04d}--texto.json")


def test_una_imagen_normal_se_resuelve_igual_que_antes(tmp_path) -> None:
    raiz = tmp_path / "atlas"
    lote = raiz / "operacion" / "entradas" / "L"; lote.mkdir(parents=True)
    Image.new("RGB", (4, 4)).save(lote / "a.jpg")
    evidencia = resolver_ruta_evidencia(raiz, "a.jpg")
    assert evidencia.ruta == lote / "a.jpg"
    assert evidencia.pagina_pdf is None and evidencia.ruta_texto_pdf is None


# ------------------------------------------------------------ revalidación por transporte

def test_revalidacion_sobre_pagina_con_texto_embebido_usa_proveedor_pagina_pdf(atlas_con_pdf, monkeypatch) -> None:
    llamadas: list[dict] = []
    _capturar_procesar_archivo(monkeypatch, llamadas)
    base = OCRFalso()

    m.revalidar_documentos_por_transporte(
        raiz_atlas=atlas_con_pdf, numero_transporte="0000900001", dry_run=True, proveedor=base,
    )

    (llamada,) = llamadas
    assert llamada["ruta"].name.endswith("--p0001.png")
    proveedor = llamada["proveedor"]
    assert isinstance(proveedor, ProveedorPaginaPdf) and llamada["lector_ocr"] is None
    assert "N° 472601" in proveedor.leer_texto(llamada["ruta"])
    proveedor.leer_focal(llamada["ruta"], (0, 0, 1, 1), allowlist="0123456789")
    assert base.leer_texto_llamadas == []  # texto: nunca OCR de líneas


def test_revalidacion_sobre_pagina_ocr_usa_el_proveedor_ocr_tal_cual(atlas_con_pdf, monkeypatch) -> None:
    llamadas: list[dict] = []
    _capturar_procesar_archivo(monkeypatch, llamadas)
    base = OCRFalso()

    m.revalidar_documentos_por_transporte(
        raiz_atlas=atlas_con_pdf, numero_transporte="0000900002", dry_run=True, proveedor=base,
    )

    (llamada,) = llamadas
    assert llamada["ruta"].name.endswith("--p0002.png")
    assert llamada["proveedor"] is base


def test_multipagina_revalida_exactamente_la_pagina_pedida(atlas_con_pdf, monkeypatch) -> None:
    llamadas: list[dict] = []
    _capturar_procesar_archivo(monkeypatch, llamadas)
    m.revalidar_documentos_por_transporte(
        raiz_atlas=atlas_con_pdf, numero_transporte="0000900003", dry_run=True, proveedor=OCRFalso(),
    )
    (llamada,) = llamadas
    assert llamada["ruta"].name.endswith("--p0003.png")
    lineas = llamada["proveedor"].leer_texto(llamada["ruta"])
    assert "N° 472603" in lineas and "N° 472601" not in lineas


# ------------------------------------------------------------ reparador de lote

def test_reparador_de_lote_expande_el_pdf_del_manifiesto_a_sus_paginas(atlas_con_pdf, monkeypatch) -> None:
    llamadas: list[dict] = []
    _capturar_procesar_archivo(monkeypatch, llamadas)
    resultado = m.reprocesar_lote_reparador(raiz_atlas=atlas_con_pdf, nombre_lote="LOTE1", dry_run=True, proveedor=OCRFalso())

    assert [d["archivo"] for d in resultado["documentos"]] == [f"lote.pdf::pagina={n:04d}" for n in (1, 2, 3)]
    assert [c["ruta"].name[-9:] for c in llamadas] == ["p0001.png", "p0002.png", "p0003.png"]
    assert [isinstance(c["proveedor"], ProveedorPaginaPdf) for c in llamadas] == [True, False, True]
    assert not any(d["motivo_no_reparado"] for d in resultado["documentos"])


def test_reproceso_repetido_no_duplica_filas_ni_derivados(atlas_con_pdf, monkeypatch) -> None:
    raiz = atlas_con_pdf
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    original = raiz / "operacion" / "entradas" / "LOTE1" / "lote.pdf"
    bytes_original = original.read_bytes()
    derivados = sorted(p.name for p in _evidencia_pdf(raiz).iterdir())
    filas_antes = _leer_filas(dataset)
    _stub_reconciliacion(monkeypatch)
    _capturar_procesar_archivo(monkeypatch, [])

    for _ in range(2):
        m.reprocesar_lote_reparador(raiz_atlas=raiz, nombre_lote="LOTE1", dry_run=False, proveedor=OCRFalso())

    assert [f["archivo"] for f in _leer_filas(dataset)] == [f["archivo"] for f in filas_antes]
    assert sorted(p.name for p in _evidencia_pdf(raiz).iterdir()) == derivados
    assert original.read_bytes() == bytes_original


def test_pdf_sin_paginas_procesables_en_el_lote_se_abstiene_sin_pasarlo_al_ocr(tmp_path, monkeypatch) -> None:
    raiz = tmp_path / "atlas"
    lote = raiz / "operacion" / "entradas" / "LOTE1"; lote.mkdir(parents=True)
    (lote / "cifrado.pdf").write_bytes(construir_pdf([pagina_texto("x")], contrasena_usuario="u", contrasena_propietario="o"))
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"; dataset.parent.mkdir(parents=True)
    procesar_carpeta(lote, dataset, proveedor=OCRFalso(), cada=1)
    llamadas: list[dict] = []
    _capturar_procesar_archivo(monkeypatch, llamadas)

    resultado = m.reprocesar_lote_reparador(raiz_atlas=raiz, nombre_lote="LOTE1", dry_run=True, proveedor=OCRFalso())

    assert llamadas == []
    assert [d["motivo_no_reparado"] for d in resultado["documentos"]] == ["PDF_SIN_PAGINAS_PROCESABLES"]


# ------------------------------------------------------------ material focal

def _preparar_material_ausente(raiz: Path, pagina: int) -> str:
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    filas = _leer_filas(dataset)
    fila = next(f for f in filas if f["archivo"].endswith(f"={pagina:04d}"))
    fila.update(descripcion_material="", tipo_carga="NO DETERMINADO", motivos_revision_documento="MATERIAL_AUSENTE")
    _escribir_filas_completas(dataset, filas)
    return fila["numero_guia"]


def test_material_recuperable_desde_texto_embebido_sin_ocr(atlas_con_pdf, monkeypatch) -> None:
    guia = _preparar_material_ausente(atlas_con_pdf, 1)
    monkeypatch.setattr("atlas_core.ocr.leer_texto_imagen", lambda *a, **k: pytest.fail("no debe usar OCR"))

    resultado = reprocesar_material_focal_desde_imagen_original(raiz_atlas=atlas_con_pdf, numero_guia=guia)

    assert resultado["aplicado"] is True
    assert resultado["descripcion_material"] == MATERIAL


def test_material_recuperable_desde_pagina_ocr_lee_el_png_de_esa_pagina(atlas_con_pdf, monkeypatch) -> None:
    guia = _preparar_material_ausente(atlas_con_pdf, 2)
    leidas: list[Path] = []
    monkeypatch.setattr(
        "atlas_core.ocr.leer_texto_imagen", lambda ruta, lector=None: leidas.append(Path(ruta)) or [MATERIAL],
    )

    resultado = reprocesar_material_focal_desde_imagen_original(raiz_atlas=atlas_con_pdf, numero_guia=guia)

    assert resultado["aplicado"] is True
    assert [r.name[-9:] for r in leidas] == ["p0002.png"]


# ------------------------------------------------------------ derivados faltantes / corruptos

def test_png_faltante_con_original_se_regenera_de_forma_determinista(atlas_con_pdf) -> None:
    antes = resolver_ruta_evidencia(atlas_con_pdf, "lote.pdf::pagina=0003")
    bytes_png = antes.ruta.read_bytes()
    antes.ruta.unlink()

    despues = resolver_ruta_evidencia(atlas_con_pdf, "lote.pdf::pagina=0003")

    assert despues.ubicacion == UBICACION_DERIVADA_PDF
    assert despues.ruta == antes.ruta and despues.ruta.read_bytes() == bytes_png


def test_derivado_faltante_sin_original_se_abstiene(atlas_con_pdf, monkeypatch) -> None:
    (atlas_con_pdf / "operacion" / "entradas" / "LOTE1" / "lote.pdf").unlink()
    next(_evidencia_pdf(atlas_con_pdf).glob("*--p0002.png")).unlink()

    evidencia = resolver_ruta_evidencia(atlas_con_pdf, "lote.pdf::pagina=0002")
    assert evidencia.ruta is None and evidencia.ubicacion == UBICACION_NO_ENCONTRADA

    llamadas: list[dict] = []
    _capturar_procesar_archivo(monkeypatch, llamadas)
    resultado = m.revalidar_documentos_por_transporte(
        raiz_atlas=atlas_con_pdf, numero_transporte="0000900002", dry_run=True, proveedor=OCRFalso(),
    )
    assert llamadas == []
    assert resultado["documentos"][0]["motivo_no_reparado"] == "IMAGEN_NO_ENCONTRADA"
    # Las otras páginas siguen resolviéndose con sus derivados.
    assert resolver_ruta_evidencia(atlas_con_pdf, "lote.pdf::pagina=0001").ubicacion == UBICACION_DERIVADA_PDF


@pytest.mark.parametrize("que", ["png", "texto"])
def test_derivado_corrupto_se_abstiene_y_nunca_se_reescribe(atlas_con_pdf, monkeypatch, que) -> None:
    patron = "*--p0001.png" if que == "png" else "*--p0001--texto.json"
    derivado = next(_evidencia_pdf(atlas_con_pdf).glob(patron))
    derivado.write_bytes(b"corrupto")
    dataset = atlas_con_pdf / "operacion" / "actual" / "analisis_completo_guias.csv"
    fila_antes = next(f for f in _leer_filas(dataset) if f["archivo"].endswith("=0001"))

    evidencia = resolver_ruta_evidencia(atlas_con_pdf, "lote.pdf::pagina=0001")
    assert evidencia.ruta is None and evidencia.ubicacion == UBICACION_EVIDENCIA_PDF_CORRUPTA

    llamadas: list[dict] = []
    _capturar_procesar_archivo(monkeypatch, llamadas)
    _stub_reconciliacion(monkeypatch)
    resultado = m.revalidar_documentos_por_transporte(
        raiz_atlas=atlas_con_pdf, numero_transporte="0000900001", dry_run=False, proveedor=OCRFalso(),
    )
    assert llamadas == []
    assert resultado["documentos"][0]["motivo_no_reparado"] == "IMAGEN_EVIDENCIA_PDF_CORRUPTA"
    assert derivado.read_bytes() == b"corrupto"
    assert next(f for f in _leer_filas(dataset) if f["archivo"].endswith("=0001")) == fila_antes


def test_sin_original_y_dos_manifiestos_del_mismo_nombre_es_ambiguo(atlas_con_pdf) -> None:
    carpeta = _evidencia_pdf(atlas_con_pdf)
    (manifiesto,) = carpeta.glob("*--manifiesto.json")
    contenido = json.loads(manifiesto.read_text(encoding="utf-8"))
    contenido["original_pdf"]["sha256"] = "0" * 64
    (carpeta / "lote--0000000000000000--manifiesto.json").write_text(json.dumps(contenido), encoding="utf-8")
    (atlas_con_pdf / "operacion" / "entradas" / "LOTE1" / "lote.pdf").unlink()

    evidencia = resolver_ruta_evidencia(atlas_con_pdf, "lote.pdf::pagina=0001")
    assert evidencia.ruta is None and evidencia.ubicacion == UBICACION_EVIDENCIA_PDF_AMBIGUA


# ------------------------------------------------------------ ciclo de vida de evidencia

def test_pdf_con_una_pagina_pendiente_sigue_activo(atlas_con_pdf) -> None:
    decisiones = {"decisiones": [{"estado": "PENDIENTE", "documento": {"archivo": "lote.pdf::pagina=0002"}}]}
    assert "lote.pdf" in documentos_con_revision_pendiente(decisiones)
    movidos = mover_evidencia_resuelta_sin_revision_pendiente(atlas_con_pdf, decisiones_pendientes=decisiones)
    assert "lote.pdf" not in movidos["movidos"]
    assert (atlas_con_pdf / "operacion" / "entradas" / "LOTE1" / "lote.pdf").is_file()


def test_pdf_movido_a_evidencia_resuelta_sigue_resolviendo_sus_paginas(atlas_con_pdf) -> None:
    movidos = mover_evidencia_resuelta_sin_revision_pendiente(atlas_con_pdf, decisiones_pendientes={"decisiones": []})
    assert "lote.pdf" in movidos["movidos"]
    next(_evidencia_pdf(atlas_con_pdf).glob("*--p0003.png")).unlink()  # obliga a usar el original movido

    evidencia = resolver_ruta_evidencia(atlas_con_pdf, "lote.pdf::pagina=0003")
    assert evidencia.ubicacion == UBICACION_DERIVADA_PDF and evidencia.ruta.is_file()
