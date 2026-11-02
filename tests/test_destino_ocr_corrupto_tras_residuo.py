"""P0 destinos OCR corruptos en guías nuevas (caso real 483859).

Impreso: "SANTA ISABEL 585 SANTIAGO LAMPA". La lectura lineal arrastró
"RUTCHOFER" y un RUT mal leído; tras e844ae6 la geometría devolvía
"ANTA ISABEL 5ESSANTIAIGOLUA" (número fundido con el texto) y se aceptaba.
Sólo cuando la lectura trae una etiqueta compuesta, el texto restante debe ser
legible por sí mismo; si no, el destino queda vacío y el documento pendiente
de revisión. Nunca se completa ni se inventa un número.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from atlas_core import procesamiento_masivo
from atlas_core.ocr import BloqueOCR
from atlas_core.procesamiento_masivo import MotivoRevisionDocumento, procesar_archivo
from atlas_core.rutas.destino_entrega import despachar_a_documental


_TRAZAS = Path(__file__).parent / "fixtures" / "trazas_ocr_aza"
_MOTIVO = MotivoRevisionDocumento.DESTINO_CONTAMINADO_POR_OTRA_SECCION.value


def _cargar(guia: str) -> tuple[list[str], list[BloqueOCR]]:
    ocr = json.loads((_TRAZAS / f"{guia}.json").read_text(encoding="utf-8"))["ocr"]
    bloques = [
        BloqueOCR(
            texto=b["texto"], bounding_box=tuple(tuple(p) for p in b["bounding_box"]), confianza=b["confianza"],
        )
        for b in ocr["bloques"]
    ]
    return ocr["lineas"], bloques


def _solo_lineal(valor: str) -> str:
    return despachar_a_documental([], None, identificadores=SimpleNamespace(despachar_a=valor))


# ============================================================
# 1 -- trazas reales
# ============================================================


def test_483859_geometria_corrupta_no_se_acepta():
    lineas, bloques = _cargar("483859")

    assert despachar_a_documental(lineas, bloques) == ""


@pytest.mark.parametrize(
    ("guia", "esperado"),
    [
        ("483843", "PANAMERICANA NORTE 22650 SANTIAGO LAMPA"),
        ("483491", "PANAMERICANA NORTE 22650 SANTIAGO LAMPA"),
        ("482967", "CAMINO A MELIPILLA 10800 SANTIAGO MAIPU"),
    ],
)
def test_limpiezas_legibles_se_conservan(guia, esperado):
    lineas, bloques = _cargar(guia)

    assert despachar_a_documental(lineas, bloques) == esperado


def test_lineal_limpia_pero_fundida_tambien_se_abstiene():
    # Mismo texto corrupto de 483859 con un RUT que sí se pudo recortar.
    assert _solo_lineal("RUTCHOFER ANTA ISABEL 5ESSANTIAIGOLUA 9708225-1") == ""


# ============================================================
# 2 -- direcciones legítimas de formatos diversos
# ============================================================


_LEGITIMAS = [
    "LOTE 3B 120 LAMPA",
    "PANAMERICANA NORTE KM20 LAMPA",
    "CAMINO LO BOZA S/N PUDAHUEL",
    "AV 2DA TRANSVERSAL 120 MAIPU",
    "21 DE MAYO 455 SANTIAGO",
    "PARCELA 24-A SANTA ROSA COLINA",
    "AV. PDTE. EDUARDO FREI MONTALVA 20670 COLINA",
    "RUTA 68 KM 20 CURACAVI",
]


@pytest.mark.parametrize("direccion", _LEGITIMAS)
def test_legitima_con_residuo_se_limpia_y_conserva(direccion):
    assert _solo_lineal(f"RUTCHOFER {direccion}") == direccion
    assert _solo_lineal(f"{direccion} RUTCHOFER") == direccion


@pytest.mark.parametrize("direccion", [*_LEGITIMAS, "CAMINO A MELIPILLA 10800SANTIAGO MAIPU"])
def test_sin_residuo_la_regla_no_se_aplica(direccion):
    # La exigencia de legibilidad sólo rige para una fila ya mezclada.
    assert _solo_lineal(direccion) == direccion


# ============================================================
# 3 -- ingesta: abstención = pendiente de revisión, nunca OK sin destino
# ============================================================


def _datos():
    return {
        "número de guía": "900001", "número de transporte": "0000900001",
        "cliente": "COMERCIAL PRUEBA SPA", "obra destino": "OBRA DE PRUEBA CENTRAL",
        "chofer": "CHOFER DE PRUEBA", "RUT del cliente": "11.111.111-1", "RUT del chofer": "11.111.111-1",
        "patente del tracto": "AB1234", "patente del carro": "CD5678",
    }


def _procesar(tmp_path, monkeypatch, guia):
    lineas, bloques = _cargar(guia)
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=lineas))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=bloques))
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", Mock(return_value=_datos()))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_descripcion_material", Mock(return_value="HORMIGON 8MM 12M A630-420H (N)"),
    )
    return procesar_archivo(tmp_path / "guia.jpg")


def test_ingesta_483859_queda_pendiente_de_revision(tmp_path, monkeypatch):
    resultado = _procesar(tmp_path, monkeypatch, "483859")

    assert _MOTIVO in resultado["motivos_revision_documento"]
    assert resultado["estado_documental"] == "REQUIERE_REVISION"


def test_ingesta_483843_limpia_no_agrega_el_motivo(tmp_path, monkeypatch):
    resultado = _procesar(tmp_path, monkeypatch, "483843")

    assert _MOTIVO not in resultado["motivos_revision_documento"]
