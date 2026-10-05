"""Recuperación de documentos leídos con el OCR de respaldo (EasyOCR).

Si la traza vigente demuestra que el documento se leyó con EasyOCR y la
reextracción se hizo efectivamente con PaddleOCR, el reparador lo trata como
DOCUMENTO_DEGRADADO: reemplaza basura plausible sin motivo, respeta el
ledger, no promueve ausencias y no repite la relectura. Además: horas AZA
reparables y motivos derivados (peso atípico) recalculados.

Todo sintético (tmp_path); procesar_archivo se sustituye por un doble.
"""
from __future__ import annotations

import json
from pathlib import Path

from atlas_core import reprocesamiento_reparador as m
from atlas_core.ocr import BloqueOCR
from atlas_core.ocr_provider import EasyOCRProvider, PaddleOCRProvider
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import _escribir_filas_completas, _leer_filas
from atlas_core.trazabilidad_ocr import persistir_traza_ocr

ARCHIVO = "IMG1.jpg"
LECTURA_BUENA = {
    "numero_guia": "473100",
    "numero_transporte": "0000473100",
    "cliente": "EMPRESA DEMO SPA",
    "rut_cliente": "15.234.567-4",
    "obra_destino": "EMPRESA DEMO SPA",
    "despachar_a_crudo": "AVENIDA DEMO 1234 SANTIAGO",
    "descripcion_material": "ROLLO HORMIGON 10MM A630-420H (N)",
    "patente_tracto": "AB1234",
    "patente_rampla": "CD5678",
    "peso_kg": "27500",
    "hora_entrada_aza": "08:15",
    "hora_salida_aza": "09:05",
    "permanencia_minutos": "50",
    "motivos_revision_documento": "",
}


def _fila(**overrides):
    fila = {columna: "" for columna in COLUMNAS}
    fila.update({
        "archivo": ARCHIVO, "numero_guia": "473100", "numero_transporte": "0000473100",
        "estado_procesamiento": "OK",
        # Lectura de respaldo: basura plausible SIN motivo propio.
        "cliente": "41O,UOO", "rut_cliente": "No encontrado", "obra_destino": "EMPRESO DFMO SPO",
        "despachar_a_crudo": "", "descripcion_material": "FECHA DE EMISION SENOR(ES) ROLLO HORMIGON",
        "patente_tracto": "No encontrado", "patente_rampla": "No encontrado", "peso_kg": "61",
        "hora_entrada_aza": "No encontrado", "hora_salida_aza": "No encontrado",
        "permanencia_minutos": "No encontrado",
        "motivos_revision_documento": "PESO_OPERACIONALMENTE_ATIPICO",
        "indicador_revision": "REVISAR", "estado_documental": "REQUIERE_REVISION",
        "estado_operacional": "REQUIERE_REVISION", "estado_ruta": "",
    })
    fila.update(overrides)
    return fila


def _raiz(tmp_path, fila, *, backend_traza="easy", referencia=ARCHIVO, ledger=()):
    raiz = tmp_path / "atlas"
    actual = raiz / "operacion" / "actual"
    (actual / "manifiestos_ingesta").mkdir(parents=True)
    (raiz / "operacion" / "entradas" / "LOTE1").mkdir(parents=True)
    (raiz / "catalogos_privados").mkdir(parents=True)
    (actual / "manifiestos_ingesta" / "LOTE1.json").write_text(json.dumps({
        "schema_version": 1, "lote": "LOTE1",
        "seleccion": [{"nombre_archivo": ARCHIVO, "ruta_origen": f"C:/origen/{ARCHIVO}",
                       "ingresado_en_utc": "2026-09-15T10:00:00Z", "sha256": "deadbeef"}],
    }), encoding="utf-8")
    (raiz / "operacion" / "entradas" / "LOTE1" / ARCHIVO).write_bytes(b"fake-image-bytes")
    _escribir_filas_completas(actual / "analisis_completo_guias.csv", [fila])
    (actual / "decisiones_aplicadas.json").write_text(json.dumps({"aplicaciones": list(ledger)}), encoding="utf-8")
    if backend_traza is not None:
        proveedor_traza = EasyOCRProvider(lector=object()) if backend_traza == "easy" else _paddle()
        ruta = persistir_traza_ocr(
            directorio=raiz / "operacion" / "trazas_ocr", referencia_imagen=referencia,
            textos=["texto"], bloques=[BloqueOCR("texto", ((0, 0), (1, 0), (1, 1), (0, 1)), 0.9)],
            proveedor=proveedor_traza,
        )
        if referencia != ARCHIVO:  # traza ajena colocada donde iría la de ARCHIVO
            ruta.rename(m.ruta_traza_ocr(raiz / "operacion" / "trazas_ocr", ARCHIVO))
    return raiz


def _paddle(degradado=False):
    proveedor = PaddleOCRProvider(device="cpu", ruta_python=Path("C:/runtime-falso/python.exe"))
    proveedor._degradado_a_easyocr = degradado
    return proveedor


def _reparar(monkeypatch, raiz, extraido, proveedor):
    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: dict(extraido))
    monkeypatch.setattr(m, "revalidar_y_regenerar_reporte", lambda **kw: {"reporte_vigente": "stub"})
    resultado = m.reprocesar_lote_reparador(raiz_atlas=raiz, dry_run=False, proveedor=proveedor)
    return resultado, _leer_filas(raiz / "operacion" / "actual" / "analisis_completo_guias.csv")[0]


def test_easyocr_previo_y_paddle_valido_reemplaza_basura_plausible(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path, _fila())
    _, tras = _reparar(monkeypatch, raiz, LECTURA_BUENA, _paddle())
    for campo in ("cliente", "rut_cliente", "obra_destino", "despachar_a_crudo", "descripcion_material",
                  "patente_tracto", "patente_rampla", "peso_kg", "hora_entrada_aza", "hora_salida_aza",
                  "permanencia_minutos"):
        assert tras[campo] == LECTURA_BUENA[campo], campo
    # El motivo derivado del peso viejo no sobrevive al peso nuevo.
    assert tras["motivos_revision_documento"] == ""
    metricas = json.loads(tras["metricas_procesamiento_json"])
    assert metricas["recuperacion_p0"]["relectura_ocr_principal"]["backend_relectura"] == "PaddleOCRProvider"


def test_motivo_derivado_se_conserva_si_la_reextraccion_lo_vuelve_a_producir(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path, _fila())
    lectura = dict(LECTURA_BUENA, peso_kg="70", motivos_revision_documento="PESO_OPERACIONALMENTE_ATIPICO")
    _, tras = _reparar(monkeypatch, raiz, lectura, _paddle())
    assert tras["peso_kg"] == "70"
    assert tras["motivos_revision_documento"] == "PESO_OPERACIONALMENTE_ATIPICO"


def test_decision_humana_no_se_sobrescribe(tmp_path, monkeypatch):
    ledger = [{"documento": {"archivo": ARCHIVO, "numero_guia": "473100"}, "campo": "cliente", "valor": "41O,UOO"}]
    raiz = _raiz(tmp_path, _fila(), ledger=ledger)
    _, tras = _reparar(monkeypatch, raiz, LECTURA_BUENA, _paddle())
    assert tras["cliente"] == "41O,UOO"
    assert tras["obra_destino"] == "EMPRESA DEMO SPA"


def test_paddle_ambiguo_no_sustituye_valor_existente(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path, _fila(cliente="EMPRESA PREVIA SPA"))
    lectura = dict(LECTURA_BUENA, cliente="No encontrado", hora_entrada_aza="8.15", patente_tracto="XX")
    _, tras = _reparar(monkeypatch, raiz, lectura, _paddle())
    assert tras["cliente"] == "EMPRESA PREVIA SPA"
    assert tras["hora_entrada_aza"] == "No encontrado"
    assert tras["patente_tracto"] == "No encontrado"


def test_documento_leido_originalmente_con_paddle_no_se_reescribe(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path, _fila(motivos_revision_documento=""), backend_traza="paddle")
    _, tras = _reparar(monkeypatch, raiz, LECTURA_BUENA, _paddle())
    # Campos presentes sin motivo quedan intactos; sólo lo ausente se completa.
    assert tras["cliente"] == "41O,UOO"
    assert tras["obra_destino"] == "EMPRESO DFMO SPO"
    assert tras["despachar_a_crudo"] == LECTURA_BUENA["despachar_a_crudo"]
    assert "relectura_ocr_principal" not in (tras["metricas_procesamiento_json"] or "")


def test_reextraccion_que_cayo_a_easyocr_no_cuenta_como_paddle(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path, _fila())
    _, tras = _reparar(monkeypatch, raiz, LECTURA_BUENA, _paddle(degradado=True))
    assert tras["cliente"] == "41O,UOO"


def test_sin_traza_o_traza_de_otro_documento_no_se_trata_como_degradado(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path / "a", _fila(), backend_traza=None)
    _, tras = _reparar(monkeypatch, raiz, LECTURA_BUENA, _paddle())
    assert tras["cliente"] == "41O,UOO"

    raiz = _raiz(tmp_path / "b", _fila(), referencia="OTRA.jpg")
    _, tras = _reparar(monkeypatch, raiz, LECTURA_BUENA, _paddle())
    assert tras["cliente"] == "41O,UOO"


def test_revalidar_dos_veces_es_idempotente(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path, _fila())
    primero, tras_1 = _reparar(monkeypatch, raiz, LECTURA_BUENA, _paddle())
    segundo, tras_2 = _reparar(monkeypatch, raiz, LECTURA_BUENA, _paddle())
    assert primero["campos_cambiados_total"] > 0
    assert segundo["campos_cambiados_total"] == 0
    assert tras_1 == tras_2


def test_tras_la_relectura_un_cambio_posterior_vuelve_al_gating_normal(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path, _fila())
    _reparar(monkeypatch, raiz, LECTURA_BUENA, _paddle())
    _, tras = _reparar(monkeypatch, raiz, dict(LECTURA_BUENA, cliente="OTRA EMPRESA SPA"), _paddle())
    assert tras["cliente"] == "EMPRESA DEMO SPA"


def test_horas_ausentes_se_completan_sin_documento_degradado(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path, _fila(motivos_revision_documento=""), backend_traza=None)
    _, tras = _reparar(monkeypatch, raiz, LECTURA_BUENA, object())
    assert (tras["hora_entrada_aza"], tras["hora_salida_aza"], tras["permanencia_minutos"]) == ("08:15", "09:05", "50")


def test_horas_presentes_sin_degradacion_no_se_tocan(tmp_path, monkeypatch):
    fila = _fila(motivos_revision_documento="", hora_entrada_aza="07:00", hora_salida_aza="07:30",
                 permanencia_minutos="30")
    raiz = _raiz(tmp_path, fila, backend_traza=None)
    _, tras = _reparar(monkeypatch, raiz, LECTURA_BUENA, object())
    assert (tras["hora_entrada_aza"], tras["hora_salida_aza"], tras["permanencia_minutos"]) == ("07:00", "07:30", "30")


def test_peso_reexaminado_sin_degradacion_tambien_recalcula_su_motivo(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path, _fila(), backend_traza=None)
    _, tras = _reparar(monkeypatch, raiz, {"peso_kg": "27500", "motivos_revision_documento": ""}, object())
    assert tras["peso_kg"] == "27500"
    assert "PESO_OPERACIONALMENTE_ATIPICO" not in tras["motivos_revision_documento"]
