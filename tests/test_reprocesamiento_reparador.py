"""Tests del bloque REPROCESAMIENTO_REPARADOR -- exclusivamente
sintéticos, nunca tocan G:\\. Cada test construye su propio `raiz_atlas`
en `tmp_path`."""
from __future__ import annotations

import json

import pytest

from atlas_core import reprocesamiento_reparador as m
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import _escribir_filas_completas, _leer_filas


def _raiz(tmp_path):
    raiz = tmp_path / "atlas"
    (raiz / "operacion" / "actual" / "manifiestos_ingesta").mkdir(parents=True)
    (raiz / "operacion" / "entradas" / "LOTE1").mkdir(parents=True)
    (raiz / "catalogos_privados").mkdir(parents=True)
    return raiz


def _escribir_manifiesto(raiz, *, lote, archivos, ingresado_en_utc="2026-09-15T10:00:00Z"):
    contenido = {
        "schema_version": 1,
        "lote": lote,
        "seleccion": [
            {
                "nombre_archivo": nombre,
                "ruta_origen": f"C:/origen/{nombre}",
                "ingresado_en_utc": ingresado_en_utc,
                "sha256": "deadbeef",
            }
            for nombre in archivos
        ],
    }
    ruta = raiz / "operacion" / "actual" / "manifiestos_ingesta" / f"{lote}.json"
    ruta.write_text(json.dumps(contenido), encoding="utf-8")


def _crear_imagen(raiz, lote, nombre):
    (raiz / "operacion" / "entradas" / lote / nombre).write_bytes(b"fake-image-bytes")


def _fila_base(**overrides):
    fila = {columna: "" for columna in COLUMNAS}
    fila.update({
        "archivo": "IMG1.jpg",
        "numero_guia": "473100",
        "numero_transporte": "0000473100",
        "estado_procesamiento": "OK",
        "motivos_revision_documento": "",
        "indicador_revision": "OK",
        "estado_documental": "OK",
        "estado_operacional": "OK",
        "estado_ruta": "",
    })
    fila.update(overrides)
    return fila


def _escribir_dataset(raiz, filas):
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    _escribir_filas_completas(dataset, filas)
    return dataset


def _escribir_ledger(raiz, aplicaciones):
    ledger = raiz / "operacion" / "actual" / "decisiones_aplicadas.json"
    ledger.write_text(json.dumps({"aplicaciones": aplicaciones}), encoding="utf-8")


def _stub_reconciliacion(monkeypatch, llamadas):
    def _fake(**kwargs):
        llamadas.append(kwargs)
        return {"reporte_vigente": "reportes/stub"}

    monkeypatch.setattr(m, "revalidar_y_regenerar_reporte", _fake)


def test_identifica_lote_por_manifiesto_mas_reciente(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path)
    _escribir_manifiesto(raiz, lote="LOTE_VIEJO", archivos=["A.jpg"], ingresado_en_utc="2026-09-01T00:00:00Z")
    _escribir_manifiesto(raiz, lote="LOTE1", archivos=["IMG1.jpg"], ingresado_en_utc="2026-09-15T10:00:00Z")
    _crear_imagen(raiz, "LOTE1", "IMG1.jpg")
    _escribir_dataset(raiz, [_fila_base()])
    _escribir_ledger(raiz, [])

    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: {})
    resultado = m.reprocesar_lote_reparador(raiz_atlas=raiz, dry_run=True, proveedor=object())

    assert resultado["lote"] == "LOTE1"
    assert resultado["documentos_en_manifiesto"] == 1


def test_identifica_lote_por_nombre_explicito(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path)
    _escribir_manifiesto(raiz, lote="LOTE_VIEJO", archivos=["A.jpg"], ingresado_en_utc="2026-09-15T23:00:00Z")
    _escribir_manifiesto(raiz, lote="LOTE1", archivos=["IMG1.jpg"], ingresado_en_utc="2026-09-01T00:00:00Z")
    _crear_imagen(raiz, "LOTE1", "IMG1.jpg")
    _escribir_dataset(raiz, [_fila_base()])
    _escribir_ledger(raiz, [])

    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: {})
    resultado = m.reprocesar_lote_reparador(raiz_atlas=raiz, nombre_lote="LOTE1", dry_run=True, proveedor=object())

    assert resultado["lote"] == "LOTE1"


def test_sin_manifiesto_lanza_error_explicito(tmp_path):
    raiz = _raiz(tmp_path)
    with pytest.raises(FileNotFoundError):
        m.reprocesar_lote_reparador(raiz_atlas=raiz, dry_run=True, proveedor=object())


def test_dry_run_no_escribe_nada_en_el_dataset(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path)
    _escribir_manifiesto(raiz, lote="LOTE1", archivos=["IMG1.jpg"])
    _crear_imagen(raiz, "LOTE1", "IMG1.jpg")
    fila = _fila_base(chofer="No encontrado", motivos_revision_documento="CHOFER_AUSENTE")
    _escribir_dataset(raiz, [fila])
    _escribir_ledger(raiz, [])

    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: {"chofer": "JUAN PEREZ SOTO"})
    llamadas = []
    _stub_reconciliacion(monkeypatch, llamadas)

    resultado = m.reprocesar_lote_reparador(raiz_atlas=raiz, dry_run=True, proveedor=object())

    assert resultado["campos_cambiados_total"] == 1  # se calcula igual, pero no se persiste
    assert resultado["reconciliacion"] is None
    assert llamadas == []
    filas_tras = _leer_filas(raiz / "operacion" / "actual" / "analisis_completo_guias.csv")
    assert filas_tras[0]["chofer"] == "No encontrado"


def test_promueve_campo_degradado_con_valor_estructuralmente_valido(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path)
    _escribir_manifiesto(raiz, lote="LOTE1", archivos=["IMG1.jpg"])
    _crear_imagen(raiz, "LOTE1", "IMG1.jpg")
    fila = _fila_base(chofer="No encontrado", motivos_revision_documento="CHOFER_AUSENTE")
    _escribir_dataset(raiz, [fila])
    _escribir_ledger(raiz, [])

    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: {"chofer": "JUAN PEREZ SOTO"})
    llamadas = []
    _stub_reconciliacion(monkeypatch, llamadas)

    resultado = m.reprocesar_lote_reparador(raiz_atlas=raiz, dry_run=False, proveedor=object())

    assert resultado["campos_cambiados_total"] == 1
    assert len(llamadas) == 1  # reconciliación canónica invocada una sola vez
    filas_tras = _leer_filas(raiz / "operacion" / "actual" / "analisis_completo_guias.csv")
    assert filas_tras[0]["chofer"] == "JUAN PEREZ SOTO"
    assert filas_tras[0]["motivos_revision_documento"] == ""
    assert filas_tras[0]["indicador_revision"] == "OK"


def test_campo_con_decision_humana_nunca_se_toca(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path)
    _escribir_manifiesto(raiz, lote="LOTE1", archivos=["IMG1.jpg"])
    _crear_imagen(raiz, "LOTE1", "IMG1.jpg")
    fila = _fila_base(chofer="PEDRO GOMEZ", motivos_revision_documento="CHOFER_AUSENTE")
    _escribir_dataset(raiz, [fila])
    _escribir_ledger(raiz, [
        {"documento": {"archivo": "IMG1.jpg", "numero_guia": "473100"}, "campo": "chofer", "valor": "PEDRO GOMEZ"},
    ])

    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: {"chofer": "OTRO NOMBRE DISTINTO"})
    llamadas = []
    _stub_reconciliacion(monkeypatch, llamadas)

    resultado = m.reprocesar_lote_reparador(raiz_atlas=raiz, dry_run=False, proveedor=object())

    assert resultado["campos_cambiados_total"] == 0
    filas_tras = _leer_filas(raiz / "operacion" / "actual" / "analisis_completo_guias.csv")
    assert filas_tras[0]["chofer"] == "PEDRO GOMEZ"
    assert llamadas == []  # nada cambió -> no dispara reconciliación


def test_campo_limpio_nunca_se_toca_aunque_extraccion_traiga_otro_valor(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path)
    _escribir_manifiesto(raiz, lote="LOTE1", archivos=["IMG1.jpg"])
    _crear_imagen(raiz, "LOTE1", "IMG1.jpg")
    fila = _fila_base(cliente="EMPRESA CONOCIDA SA", motivos_revision_documento="")
    _escribir_dataset(raiz, [fila])
    _escribir_ledger(raiz, [])

    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: {"cliente": "OTRA EMPRESA"})
    resultado = m.reprocesar_lote_reparador(raiz_atlas=raiz, dry_run=False, proveedor=object())

    assert resultado["campos_cambiados_total"] == 0
    filas_tras = _leer_filas(raiz / "operacion" / "actual" / "analisis_completo_guias.csv")
    assert filas_tras[0]["cliente"] == "EMPRESA CONOCIDA SA"


def test_valor_estructuralmente_invalido_no_se_promueve(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path)
    _escribir_manifiesto(raiz, lote="LOTE1", archivos=["IMG1.jpg"])
    _crear_imagen(raiz, "LOTE1", "IMG1.jpg")
    fila = _fila_base(rut_chofer="", motivos_revision_documento="RUT_CHOFER_INVALIDO")
    _escribir_dataset(raiz, [fila])
    _escribir_ledger(raiz, [])

    # "ABC" no cumple el formato estructural de un RUT -- nunca se promueve.
    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: {"rut_chofer": "ABC"})
    resultado = m.reprocesar_lote_reparador(raiz_atlas=raiz, dry_run=False, proveedor=object())

    assert resultado["campos_cambiados_total"] == 0
    filas_tras = _leer_filas(raiz / "operacion" / "actual" / "analisis_completo_guias.csv")
    assert filas_tras[0]["rut_chofer"] == ""
    assert "RUT_CHOFER_INVALIDO" in filas_tras[0]["motivos_revision_documento"]


def test_imagen_no_encontrada_se_reporta_sin_intentar_extraccion(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path)
    _escribir_manifiesto(raiz, lote="LOTE1", archivos=["FALTANTE.jpg"])
    fila = _fila_base(archivo="FALTANTE.jpg", motivos_revision_documento="CHOFER_AUSENTE")
    _escribir_dataset(raiz, [fila])
    _escribir_ledger(raiz, [])

    llamado = []
    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: llamado.append(1) or {})
    resultado = m.reprocesar_lote_reparador(raiz_atlas=raiz, dry_run=True, proveedor=object())

    assert llamado == []  # nunca se intenta OCR sin imagen
    assert resultado["documentos"][0]["motivo_no_reparado"].startswith("IMAGEN_")
    assert resultado["documentos_sin_reparar"] == ["FALTANTE.jpg"]


def test_no_duplica_identidad_existente_para_documento_sin_fila(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path)
    _escribir_manifiesto(raiz, lote="LOTE1", archivos=["NUEVO.jpg"])
    _crear_imagen(raiz, "LOTE1", "NUEVO.jpg")
    fila_existente = _fila_base(archivo="OTRO.jpg", numero_guia="473200", numero_transporte="0000473200")
    _escribir_dataset(raiz, [fila_existente])
    _escribir_ledger(raiz, [])

    # La reextracción del documento "sin fila" resuelve una identidad que
    # YA existe en otra fila -- nunca debe crear un duplicado.
    monkeypatch.setattr(
        m, "procesar_archivo",
        lambda *a, **kw: {"numero_guia": "473200", "numero_transporte": "0000473200"},
    )
    resultado = m.reprocesar_lote_reparador(raiz_atlas=raiz, dry_run=False, proveedor=object())

    assert resultado["documentos"][0]["fila_nueva"] is False
    assert resultado["documentos"][0]["motivo_no_reparado"] == "SIN_FILA_Y_SIN_IDENTIDAD_NUEVA_VALIDA"
    filas_tras = _leer_filas(raiz / "operacion" / "actual" / "analisis_completo_guias.csv")
    assert len(filas_tras) == 1


def test_rescata_documento_sin_fila_con_identidad_nueva_valida(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path)
    _escribir_manifiesto(raiz, lote="LOTE1", archivos=["NUEVO.jpg"])
    _crear_imagen(raiz, "LOTE1", "NUEVO.jpg")
    fila_existente = _fila_base(archivo="OTRO.jpg", numero_guia="473200", numero_transporte="0000473200")
    _escribir_dataset(raiz, [fila_existente])
    _escribir_ledger(raiz, [])

    monkeypatch.setattr(
        m, "procesar_archivo",
        lambda *a, **kw: {"numero_guia": "473999", "numero_transporte": "0000473999", "chofer": "NUEVO CHOFER"},
    )
    llamadas = []
    _stub_reconciliacion(monkeypatch, llamadas)

    resultado = m.reprocesar_lote_reparador(raiz_atlas=raiz, dry_run=False, proveedor=object())

    assert resultado["documentos"][0]["fila_nueva"] is True
    assert resultado["documentos"][0]["numero_guia_despues"] == "473999"
    filas_tras = _leer_filas(raiz / "operacion" / "actual" / "analisis_completo_guias.csv")
    assert len(filas_tras) == 2
    assert any(f["numero_guia"] == "473999" for f in filas_tras)
    assert len(llamadas) == 1


def test_reporte_incluye_metricas_de_tiempo_y_conteos(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path)
    _escribir_manifiesto(raiz, lote="LOTE1", archivos=["IMG1.jpg"])
    _crear_imagen(raiz, "LOTE1", "IMG1.jpg")
    _escribir_dataset(raiz, [_fila_base()])
    _escribir_ledger(raiz, [])

    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: {})
    resultado = m.reprocesar_lote_reparador(raiz_atlas=raiz, dry_run=True, proveedor=object())

    assert resultado["tiempo_total_ms"] >= 0
    assert resultado["tiempo_promedio_por_imagen_ms"] >= 0
    assert resultado["documentos_reprocesados"] == 1
    assert resultado["decisiones_pendientes_antes"] == 0
    assert resultado["decisiones_pendientes_despues"] is None  # dry_run: nunca se re-lee


def test_error_de_extraccion_no_aborta_el_resto_del_lote(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path)
    _escribir_manifiesto(raiz, lote="LOTE1", archivos=["ROTA.jpg", "IMG1.jpg"])
    _crear_imagen(raiz, "LOTE1", "ROTA.jpg")
    _crear_imagen(raiz, "LOTE1", "IMG1.jpg")
    fila = _fila_base(archivo="ROTA.jpg", motivos_revision_documento="CHOFER_AUSENTE")
    fila2 = _fila_base(archivo="IMG1.jpg", numero_guia="473777", numero_transporte="0000473777")
    _escribir_dataset(raiz, [fila, fila2])
    _escribir_ledger(raiz, [])

    def _procesar(ruta, **kw):
        if "ROTA" in str(ruta):
            raise RuntimeError("OCR falló")
        return {}

    monkeypatch.setattr(m, "procesar_archivo", _procesar)
    resultado = m.reprocesar_lote_reparador(raiz_atlas=raiz, dry_run=True, proveedor=object())

    assert resultado["documentos_reprocesados"] == 2
    motivo_rota = next(d["motivo_no_reparado"] for d in resultado["documentos"] if d["archivo"] == "ROTA.jpg")
    assert motivo_rota.startswith("ERROR_REPROCESO")


# --- Fix: DOCUMENTO_DEGRADADO habilita reparar campos sin motivo propio ---
# Caso real 473326 del lote 20260916_151401: motivos_revision_documento
# sólo traía "GUIA_AUSENTE | TRANSPORTE_AUSENTE | MATERIAL_AUSENTE |
# DOCUMENTO_DEGRADADO" -- chofer/cliente/patente_tracto ya tenían texto
# (basura OCR), así que nunca activaron su propio motivo específico y el
# gating original los dejaba fuera para siempre pese a que
# `procesar_archivo` real sí producía evidencia muy superior.

def test_documento_degradado_habilita_reparar_campo_sin_motivo_especifico(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path)
    _escribir_manifiesto(raiz, lote="LOTE1", archivos=["IMG1.jpg"])
    _crear_imagen(raiz, "LOTE1", "IMG1.jpg")
    fila = _fila_base(
        numero_guia="No encontrado",
        chofer="CRISIOPHER RSTAVAR BPHR NETOS",
        cliente="PAODALA 0A",
        patente_tracto="49W0DA",
        motivos_revision_documento="GUIA_AUSENTE | TRANSPORTE_AUSENTE | MATERIAL_AUSENTE | DOCUMENTO_DEGRADADO",
    )
    _escribir_dataset(raiz, [fila])
    _escribir_ledger(raiz, [])

    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: {
        "numero_guia": "473326", "chofer": "CRISTOPHER RETAMAL", "cliente": "PRODALAM SA",
        "patente_tracto": "BPHR67",
    })
    llamadas = []
    _stub_reconciliacion(monkeypatch, llamadas)

    resultado = m.reprocesar_lote_reparador(raiz_atlas=raiz, dry_run=False, proveedor=object())

    assert resultado["campos_cambiados_total"] == 4
    filas_tras = _leer_filas(raiz / "operacion" / "actual" / "analisis_completo_guias.csv")
    assert filas_tras[0]["numero_guia"] == "473326"
    assert filas_tras[0]["chofer"] == "CRISTOPHER RETAMAL"
    assert filas_tras[0]["cliente"] == "PRODALAM SA"
    assert filas_tras[0]["patente_tracto"] == "BPHR67"
    # GUIA_AUSENTE sí tenía motivo propio y se retira; DOCUMENTO_DEGRADADO
    # no es motivo de ningún campo de CAMPOS_REPARABLES -- se conserva
    # deliberadamente (otros aspectos del documento, fuera de este modo
    # focal, pueden seguir siendo degradados).
    assert "GUIA_AUSENTE" not in filas_tras[0]["motivos_revision_documento"]
    assert "DOCUMENTO_DEGRADADO" in filas_tras[0]["motivos_revision_documento"]


def test_sin_documento_degradado_mantiene_gating_estricto_por_campo(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path)
    _escribir_manifiesto(raiz, lote="LOTE1", archivos=["IMG1.jpg"])
    _crear_imagen(raiz, "LOTE1", "IMG1.jpg")
    # Sin DOCUMENTO_DEGRADADO y sin motivo propio de cliente -- el
    # broadening NUNCA debe activarse aquí; un campo "limpio" según el
    # pipeline real sigue sin tocarse jamás.
    fila = _fila_base(cliente="EMPRESA REAL SA", motivos_revision_documento="")
    _escribir_dataset(raiz, [fila])
    _escribir_ledger(raiz, [])

    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: {"cliente": "OTRO NOMBRE"})
    resultado = m.reprocesar_lote_reparador(raiz_atlas=raiz, dry_run=False, proveedor=object())

    assert resultado["campos_cambiados_total"] == 0
    filas_tras = _leer_filas(raiz / "operacion" / "actual" / "analisis_completo_guias.csv")
    assert filas_tras[0]["cliente"] == "EMPRESA REAL SA"


def test_ledger_gana_incluso_con_documento_degradado(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path)
    _escribir_manifiesto(raiz, lote="LOTE1", archivos=["IMG1.jpg"])
    _crear_imagen(raiz, "LOTE1", "IMG1.jpg")
    fila = _fila_base(
        chofer="CONFIRMADO POR HUMANO",
        motivos_revision_documento="GUIA_AUSENTE | DOCUMENTO_DEGRADADO",
    )
    _escribir_dataset(raiz, [fila])
    _escribir_ledger(raiz, [
        {"documento": {"archivo": "IMG1.jpg", "numero_guia": "473100"}, "campo": "chofer", "valor": "CONFIRMADO POR HUMANO"},
    ])

    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: {"chofer": "OTRO CHOFER DISTINTO"})
    resultado = m.reprocesar_lote_reparador(raiz_atlas=raiz, dry_run=False, proveedor=object())

    campos_tocados = {c["campo"] for d in resultado["documentos"] for c in d["cambios"]}
    assert "chofer" not in campos_tocados
    filas_tras = _leer_filas(raiz / "operacion" / "actual" / "analisis_completo_guias.csv")
    assert filas_tras[0]["chofer"] == "CONFIRMADO POR HUMANO"


# --- Fix: proveedor OCR real por defecto (antes caía a EasyOCR legacy) ---

def test_sin_proveedor_explicito_crea_uno_real_una_vez_y_lo_cierra(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path)
    _escribir_manifiesto(raiz, lote="LOTE1", archivos=["IMG1.jpg", "IMG2.jpg"])
    _crear_imagen(raiz, "LOTE1", "IMG1.jpg")
    _crear_imagen(raiz, "LOTE1", "IMG2.jpg")
    _escribir_dataset(raiz, [_fila_base(), _fila_base(archivo="IMG2.jpg", numero_guia="473200")])
    _escribir_ledger(raiz, [])

    llamadas_creacion = []
    cerrados = []

    class _ProveedorFalso:
        def cerrar(self):
            cerrados.append(1)

    def _crear_falso():
        llamadas_creacion.append(1)
        return _ProveedorFalso()

    monkeypatch.setattr(m, "crear_proveedor_ocr", _crear_falso)
    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: {})

    m.reprocesar_lote_reparador(raiz_atlas=raiz, dry_run=True)

    assert len(llamadas_creacion) == 1  # una sola vez para las 2 imágenes del lote
    assert len(cerrados) == 1


def test_proveedor_explicito_del_llamador_evita_crear_uno_nuevo(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path)
    _escribir_manifiesto(raiz, lote="LOTE1", archivos=["IMG1.jpg"])
    _crear_imagen(raiz, "LOTE1", "IMG1.jpg")
    _escribir_dataset(raiz, [_fila_base()])
    _escribir_ledger(raiz, [])

    llamadas_creacion = []
    monkeypatch.setattr(m, "crear_proveedor_ocr", lambda: llamadas_creacion.append(1))
    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: {})

    m.reprocesar_lote_reparador(raiz_atlas=raiz, dry_run=True, proveedor=object())

    assert llamadas_creacion == []
