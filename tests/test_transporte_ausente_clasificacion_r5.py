"""Bloque R5 I -- clasificación general (nunca por guía/cliente/chofer) de
"sin número de transporte" en tres causas distintas:

1. Omisión documental real (la etiqueta "NRO...TRANSPORTE" nunca aparece
   en el OCR, documento no degradado) -> Incidencia Documental, nunca
   pendiente de Revisión de Atlas.
2. Problema de lectura de Atlas (la etiqueta SÍ aparece pero ningún número
   válido la acompaña) -> TRANSPORTE_AUSENTE normal, bloqueante.
3. Calidad/captura general del documento (varios campos ausentes a la vez,
   `_documento_degradado`) -> DOCUMENTO_DEGRADADO, ya existente, distinto
   de ambos anteriores.

Cubre el extractor (señal de etiqueta), la clasificación en
`procesamiento_masivo` (ver `tests/test_procesamiento_masivo.py` para el
pipeline completo) y el registro automático en el almacén ya existente de
Incidencias Documentales."""
from __future__ import annotations

from datetime import datetime, timezone

from atlas_core.extractor import extraer_datos
from atlas_core.incidencias_documentales import (
    TIPO_TRANSPORTE_AUSENTE_DOCUMENTAL,
    AlmacenIncidenciasDocumentales,
)
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    detectar_incidencias_transporte_ausente_sin_ocr,
    reconciliar_incidencias_transporte_documental,
)

ENCABEZADO = [
    "ACEROS AZA S.A GUIA DE DESPACHO ELECTRONICA N 464170",
    "SEÑOR(ES) : EBEMA SA",
]


# ============================================================
# Extractor -- señal de etiqueta ("NRO...TRANSPORTE")
# ============================================================


def test_etiqueta_y_numero_presentes():
    textos = ENCABEZADO + ["NRO GUIA DE TRANSPORTE : 0000348808"]
    datos = extraer_datos(textos)
    assert datos["número de transporte"] == "0000348808"
    assert datos["_etiqueta_transporte_documental"] == "SI"


def test_etiqueta_presente_pero_sin_numero_legible():
    """Caso 2 -- la etiqueta aparece pero ningún patrón numérico válido la
    acompaña (p. ej. el OCR no pudo leer el número): la etiqueta se marca
    encontrada igual, aunque el número final quede 'No encontrado'."""
    textos = ENCABEZADO + ["NRO GUIA DE TRANSPORTE : ###"]
    datos = extraer_datos(textos)
    assert datos["número de transporte"] == "No encontrado"
    assert datos["_etiqueta_transporte_documental"] == "SI"


def test_etiqueta_nunca_aparece():
    """Caso 1 -- ninguna mención de 'NRO'/'TRANSPORTE' en todo el
    documento: el campo simplemente no está impreso."""
    textos = ENCABEZADO + ["PESO KG. : 26.999,00"]
    datos = extraer_datos(textos)
    assert datos["número de transporte"] == "No encontrado"
    assert datos["_etiqueta_transporte_documental"] == "NO"


# ============================================================
# Reconciliación -- registro automático en Incidencias Documentales
# ============================================================


def _entorno(tmp_path, *, filas):
    import csv

    raiz = tmp_path / "Atlas"
    actual = raiz / "operacion" / "actual"
    actual.mkdir(parents=True)
    (raiz / "catalogos_privados").mkdir(parents=True)
    dataset = actual / "analisis_completo_guias.csv"
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)
    return raiz


def _fila(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "1.jpeg", "estado_procesamiento": "OK", "numero_guia": "1",
        "numero_transporte": "No encontrado", "cliente": "CLIENTE X",
        "motivos_revision_documento": "TRANSPORTE_AUSENTE_SIN_ETIQUETA",
        "indicador_revision": "OK",
    })
    fila.update(overrides)
    return fila


def test_detecta_solo_filas_marcadas_sin_etiqueta(tmp_path):
    filas = [
        _fila(numero_guia="1", motivos_revision_documento="TRANSPORTE_AUSENTE_SIN_ETIQUETA"),
        _fila(numero_guia="2", motivos_revision_documento="TRANSPORTE_AUSENTE"),
        _fila(numero_guia="3", motivos_revision_documento="DOCUMENTO_DEGRADADO | TRANSPORTE_AUSENTE"),
        _fila(numero_guia="4", motivos_revision_documento=""),
    ]
    raiz = _entorno(tmp_path, filas=filas)
    candidatas = detectar_incidencias_transporte_ausente_sin_ocr(raiz_atlas=raiz)
    assert [c["numero_guia"] for c in candidatas] == ["1"]


def test_reconciliar_registra_incidencia_y_es_idempotente(tmp_path):
    raiz = _entorno(tmp_path, filas=[_fila(numero_guia="472099", numero_transporte="No encontrado")])
    reloj = lambda: datetime(2026, 8, 21, tzinfo=timezone.utc)

    primero = reconciliar_incidencias_transporte_documental(raiz_atlas=raiz, reloj=reloj)
    assert primero["candidatas"] == 1
    assert len(primero["incidencias_registradas"]) == 1

    incidencias = AlmacenIncidenciasDocumentales(
        raiz / "catalogos_privados" / "incidencias_documentales.json"
    ).listar()
    assert len(incidencias) == 1
    assert incidencias[0].numero_guia == "472099"
    assert incidencias[0].tipo_incidencia == TIPO_TRANSPORTE_AUSENTE_DOCUMENTAL
    assert incidencias[0].actor == ""  # detección automática, sin humano

    segundo = reconciliar_incidencias_transporte_documental(raiz_atlas=raiz, reloj=reloj)
    incidencias_tras_segundo = AlmacenIncidenciasDocumentales(
        raiz / "catalogos_privados" / "incidencias_documentales.json"
    ).listar()
    assert len(incidencias_tras_segundo) == 1  # no duplica


def test_reconciliar_sin_candidatas_no_crea_archivo(tmp_path):
    raiz = _entorno(tmp_path, filas=[_fila(numero_guia="1", motivos_revision_documento="TRANSPORTE_AUSENTE")])
    resultado = reconciliar_incidencias_transporte_documental(raiz_atlas=raiz)
    assert resultado["candidatas"] == 0
    assert not (raiz / "catalogos_privados" / "incidencias_documentales.json").exists()
