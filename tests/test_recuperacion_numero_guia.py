"""DOCUMENTO_RECUPERAR_NUMERO_GUIA y `atlas_core.recuperacion_numero_guia`
(26/10/2026). Casos reales 483169/483170/483211: encabezado "GUIADEDESPACHO"
y número "N483169" leídos por RapidOCR. Dataset sintético (nunca G:\\)."""
from __future__ import annotations

import csv
import json

import pytest

from atlas_core import acciones_operacionales as ao
from atlas_core import recuperacion_numero_guia as rg
from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.ocr import BloqueOCR
from atlas_core.procesamiento_masivo import COLUMNAS
from tests.test_acciones_operacionales import _EscritorDisponible, _sha, entorno  # noqa: F401


def _bloque(texto, x, y, ancho, alto):
    return BloqueOCR(texto=texto, bounding_box=((x, y), (x + ancho, y), (x + ancho, y + alto), (x, y + alto)), confianza=0.98)


ENCABEZADO_483169 = [  # geometría del encabezado real AZA (ver test_numero_guia_geometrico)
    _bloque("R.U.T.:92.176.000-0", 2025, 359, 633, 142), _bloque("GUIADEDESPACHO", 2001, 467, 681, 146),
    _bloque("ELECTRONICA", 2092, 558, 490, 121), _bloque("N483169", 2175, 686, 323, 94),
]


def _fila(**extra):
    fila = {c: "" for c in COLUMNAS}
    fila.update({"archivo": "mobile/x/original.jpg", "numero_guia": "No encontrado", "numero_transporte": "0000366176",
                 "motivos_revision_documento": "OBRA_DESTINO_SIN_CORROBORAR | GUIA_AUSENTE",
                 "indicador_revision": "REVISAR", "estado_documental": "REQUIERE_REVISION",
                 "estado_operacional": "REQUIERE_REVISION", "estado_ruta": "RUTA_CALCULADA"})
    fila.update(extra)
    return fila


def test_lectura_usa_el_mismo_extractor_lineal_y_geometrico():
    assert rg.numero_desde_lectura(["GUIA DE DESPACHO ELECTRONICA N° 483170"], None) == "483170"
    assert rg.numero_desde_lectura(["GUIADEDESPACHO", "N483169"], ENCABEZADO_483169) == "483169"
    assert rg.numero_desde_lectura(["GUIADEDESPACHO"], []) == ""


def test_recupera_numero_y_solo_estados_de_revision():
    veredicto, valores = rg.evaluar_recuperacion(_fila(), "483169", [_fila()])
    assert veredicto == rg.RECUPERAR and set(valores) <= rg.CAMPOS_ESCRITOS
    assert valores["numero_guia"] == "483169"
    # El motivo ajeno se conserva (sigue bloqueando la revisión).
    assert valores["motivos_revision_documento"] == "OBRA_DESTINO_SIN_CORROBORAR"
    assert "estado_documental" not in valores


def test_sin_otros_motivos_queda_ok_si_la_ruta_esta_calculada():
    fila = _fila(motivos_revision_documento="GUIA_AUSENTE")
    _, valores = rg.evaluar_recuperacion(fila, "483211", [fila])
    assert valores["estado_documental"] == "OK" and valores["indicador_revision"] == "OK"
    assert valores["estado_operacional"] == "OK"
    pendiente = _fila(motivos_revision_documento="GUIA_AUSENTE", estado_ruta="REQUIERE_REVISION")
    assert rg.evaluar_recuperacion(pendiente, "483211", [pendiente])[1].get("estado_operacional") is None


@pytest.mark.parametrize("fila, numero, filas, veredicto", [
    (_fila(numero_guia="483100"), "483169", [], rg.YA_TIENE_NUMERO),             # nunca reemplaza un número
    (_fila(), "", [], rg.SIN_EVIDENCIA),
    (_fila(), "0000366176", [], rg.SIN_EVIDENCIA),                               # nunca el transporte
    (_fila(), "483169", [_fila(archivo="otro.jpg", numero_guia="483169")], rg.DUPLICADO),
])
def test_abstenciones(fila, numero, filas, veredicto):
    assert rg.evaluar_recuperacion(fila, numero, filas) == (veredicto, {})


def _dataset(tmp_path, filas):
    ruta = tmp_path / "analisis_completo_guias.csv"
    with ruta.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";"); w.writeheader(); w.writerows(filas)
    return ruta


def test_escritura_concurrente_o_campos_ajenos_no_escriben(tmp_path):
    fila = _fila()
    ruta = _dataset(tmp_path, [{**fila, "estado_ruta": "SIN_CREDENCIAL"}])
    antes = ruta.read_bytes()
    with pytest.raises(rg.ErrorRecuperacionGuia, match="cambió"):
        rg.aplicar_en_dataset(ruta, archivo=fila["archivo"], fila_base=fila, valores={"numero_guia": "483169"})
    with pytest.raises(rg.ErrorRecuperacionGuia, match="no autorizados"):
        rg.aplicar_en_dataset(ruta, archivo=fila["archivo"], fila_base=fila, valores={"despachar_a_crudo": "X"})
    assert ruta.read_bytes() == antes


def _sin_guia(entorno, guia="500001"):
    filas = list(csv.DictReader(entorno["dataset"].open(encoding="utf-8-sig", newline=""), delimiter=";"))
    for f in filas:
        if f["numero_guia"] == guia:
            f.update(numero_guia="No encontrado", motivos_revision_documento="GUIA_AUSENTE",
                     indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION")
    with entorno["dataset"].open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";"); w.writeheader(); w.writerows(filas)


def test_accion_recupera_solo_el_numero_sin_ledger_y_es_idempotente(entorno, monkeypatch):
    _sin_guia(entorno)
    monkeypatch.setattr(ao, "_leer_numero_guia_evidencia", lambda ctx, archivo: "500009")
    ledger = _sha(entorno["actual"] / "decisiones_aplicadas.json")
    leer = lambda: {r["archivo"]: r for r in csv.DictReader(entorno["dataset"].open(encoding="utf-8-sig", newline=""), delimiter=";")}
    antes = leer()
    capa = CapaAccionesOperacionales(entorno["raiz"], fabrica_escritor=lambda: _EscritorDisponible())
    preview = capa.previsualizar("DOCUMENTO_RECUPERAR_NUMERO_GUIA", {"archivo": "500001.jpeg"}, actor="CLAUDE_CODE")
    assert preview["valor_propuesto"]["numero_guia"] == "500009"
    assert capa.ejecutar(preview["token"], actor="CLAUDE_CODE", confirmado_por="JAVIER")["estado"] == "APLICADA"
    despues = leer()
    assert despues["500002.jpeg"] == antes["500002.jpeg"]
    assert {c for c in antes["500001.jpeg"] if antes["500001.jpeg"][c] != despues["500001.jpeg"][c]} <= rg.CAMPOS_ESCRITOS
    assert despues["500001.jpeg"]["numero_guia"] == "500009"
    assert _sha(entorno["actual"] / "decisiones_aplicadas.json") == ledger
    segundo = capa.previsualizar("DOCUMENTO_RECUPERAR_NUMERO_GUIA", {"archivo": "500001.jpeg"}, actor="CLAUDE_CODE")
    assert segundo["estado"] == "SIN_CAMBIOS" and leer() == despues


def test_accion_rechaza_numero_de_otro_documento(entorno, monkeypatch):
    _sin_guia(entorno)
    monkeypatch.setattr(ao, "_leer_numero_guia_evidencia", lambda ctx, archivo: "500002")
    capa = CapaAccionesOperacionales(entorno["raiz"], fabrica_escritor=lambda: _EscritorDisponible())
    resultado = capa.previsualizar("DOCUMENTO_RECUPERAR_NUMERO_GUIA", {"archivo": "500001.jpeg"}, actor="CLAUDE_CODE")
    assert resultado.get("codigo") == "PRECONDICION_FALLIDA"
