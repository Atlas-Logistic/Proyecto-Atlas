"""Tests del bloque REVALIDACIÓN POR TRANSPORTE
(`atlas_core.reprocesamiento_reparador.revalidar_documentos_por_
transporte`) -- exclusivamente sintéticos, nunca tocan G:\\. Caso real que
lo motivó: viaje 0000359510 (chofer SALOMÓN PIZARRO, guías
474285/474286/474287) -- tras Bloque O2 (peso) el dataset ya persistido
seguía mostrando los valores viejos porque ningún mecanismo existente
podía revalidar UN transporte puntual sin reprocesar el lote de ingesta
completo (riesgo de tocar documentos no relacionados) ni editar CSV a
mano."""
from __future__ import annotations

import json

from atlas_core import reprocesamiento_reparador as m
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import _escribir_filas_completas, _leer_filas


def _raiz(tmp_path):
    raiz = tmp_path / "atlas"
    (raiz / "operacion" / "actual").mkdir(parents=True)
    (raiz / "operacion" / "entradas" / "LOTE1").mkdir(parents=True)
    (raiz / "catalogos_privados").mkdir(parents=True)
    return raiz


def _crear_imagen(raiz, nombre):
    (raiz / "operacion" / "entradas" / "LOTE1" / nombre).write_bytes(b"fake-image-bytes")


def _fila_base(**overrides):
    fila = {columna: "" for columna in COLUMNAS}
    fila.update({
        "archivo": "IMG1.jpg",
        "numero_guia": "474285",
        "numero_transporte": "0000359510",
        "estado_procesamiento": "OK",
        "motivos_revision_documento": "",
        "indicador_revision": "OK",
        "estado_documental": "OK",
        "estado_operacional": "OK",
        "estado_ruta": "",
        "peso_kg": "19307",
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


# --- caso real: peso corregido por Bloque O2 se persiste, sólo para ESTE transporte ---

def test_reextrae_y_persiste_peso_corregido_solo_para_el_transporte_pedido(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path)
    _crear_imagen(raiz, "474285.jpg")
    _crear_imagen(raiz, "OTRO.jpg")
    fila_objetivo = _fila_base(archivo="474285.jpg", numero_guia="474285", peso_kg="19307")
    fila_ajena = _fila_base(
        archivo="OTRO.jpg", numero_guia="999999", numero_transporte="0000999999", peso_kg="12345",
    )
    _escribir_dataset(raiz, [fila_objetivo, fila_ajena])
    _escribir_ledger(raiz, [])

    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: {"peso_kg": "9307"})
    llamadas = []
    _stub_reconciliacion(monkeypatch, llamadas)

    resultado = m.revalidar_documentos_por_transporte(
        raiz_atlas=raiz, numero_transporte="0000359510", dry_run=False, proveedor=object(),
    )

    assert resultado["campos_cambiados_total"] == 1
    assert resultado["documentos"][0]["cambios"] == [{"campo": "peso_kg", "antes": "19307", "despues": "9307"}]
    assert len(llamadas) == 1  # reconciliación canónica invocada una sola vez

    filas_tras = _leer_filas(raiz / "operacion" / "actual" / "analisis_completo_guias.csv")
    por_archivo = {f["archivo"]: f for f in filas_tras}
    assert por_archivo["474285.jpg"]["peso_kg"] == "9307"
    # el documento de OTRO transporte queda absolutamente intacto
    assert por_archivo["OTRO.jpg"]["peso_kg"] == "12345"
    assert por_archivo["OTRO.jpg"]["numero_transporte"] == "0000999999"


def test_dry_run_no_escribe_nada(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path)
    _crear_imagen(raiz, "IMG1.jpg")
    _escribir_dataset(raiz, [_fila_base(peso_kg="19307")])
    _escribir_ledger(raiz, [])

    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: {"peso_kg": "9307"})
    llamadas = []
    _stub_reconciliacion(monkeypatch, llamadas)

    resultado = m.revalidar_documentos_por_transporte(
        raiz_atlas=raiz, numero_transporte="0000359510", dry_run=True, proveedor=object(),
    )

    assert resultado["campos_cambiados_total"] == 1  # se calcula igual, pero no se persiste
    assert llamadas == []
    filas_tras = _leer_filas(raiz / "operacion" / "actual" / "analisis_completo_guias.csv")
    assert filas_tras[0]["peso_kg"] == "19307"


def test_peso_ya_correcto_no_genera_cambio_ni_reconciliacion(tmp_path, monkeypatch):
    # 474286 (control real): el peso ya estaba correcto -- reextraer debe
    # devolver el mismo valor y no generar ningún cambio.
    raiz = _raiz(tmp_path)
    _crear_imagen(raiz, "474286.jpg")
    _escribir_dataset(raiz, [_fila_base(archivo="474286.jpg", numero_guia="474286", peso_kg="9535")])
    _escribir_ledger(raiz, [])

    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: {"peso_kg": "9535"})
    llamadas = []
    _stub_reconciliacion(monkeypatch, llamadas)

    resultado = m.revalidar_documentos_por_transporte(
        raiz_atlas=raiz, numero_transporte="0000359510", dry_run=False, proveedor=object(),
    )
    assert resultado["campos_cambiados_total"] == 0
    assert llamadas == []


def test_decision_humana_sobre_peso_nunca_se_pisa(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path)
    _crear_imagen(raiz, "IMG1.jpg")
    fila = _fila_base(peso_kg="9999")  # valor humano ya confirmado, distinto de ambos
    _escribir_dataset(raiz, [fila])
    _escribir_ledger(raiz, [
        {"documento": {"archivo": "IMG1.jpg", "numero_guia": "474285"}, "campo": "peso_kg"},
    ])

    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: {"peso_kg": "9307"})
    llamadas = []
    _stub_reconciliacion(monkeypatch, llamadas)

    resultado = m.revalidar_documentos_por_transporte(
        raiz_atlas=raiz, numero_transporte="0000359510", dry_run=False, proveedor=object(),
    )
    assert resultado["campos_cambiados_total"] == 0
    filas_tras = _leer_filas(raiz / "operacion" / "actual" / "analisis_completo_guias.csv")
    assert filas_tras[0]["peso_kg"] == "9999"


def test_no_promueve_campo_identidad_limpio_sin_motivo_de_degradacion(tmp_path, monkeypatch):
    # A diferencia de peso_kg (CAMPOS_SIEMPRE_REEXAMINADOS), un campo de
    # CAMPOS_REPARABLES (p. ej. chofer) NO debe cambiar si el documento no
    # trae ningún motivo de degradación que lo marque -- mismo criterio
    # que reprocesar_lote_reparador, reutilizado aquí sin duplicar lógica.
    raiz = _raiz(tmp_path)
    _crear_imagen(raiz, "IMG1.jpg")
    fila = _fila_base(chofer="SALOMÓN PIZARRO", motivos_revision_documento="")
    _escribir_dataset(raiz, [fila])
    _escribir_ledger(raiz, [])

    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: {
        "peso_kg": "9307", "chofer": "OTRO NOMBRE LEIDO DISTINTO",
    })
    llamadas = []
    _stub_reconciliacion(monkeypatch, llamadas)

    resultado = m.revalidar_documentos_por_transporte(
        raiz_atlas=raiz, numero_transporte="0000359510", dry_run=False, proveedor=object(),
    )
    campos_cambiados = {c["campo"] for d in resultado["documentos"] for c in d["cambios"]}
    assert campos_cambiados == {"peso_kg"}  # chofer NO se tocó


def test_transporte_inexistente_no_encuentra_documentos_ni_escribe(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path)
    _crear_imagen(raiz, "474285.jpg")
    _escribir_dataset(raiz, [_fila_base()])
    _escribir_ledger(raiz, [])
    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: {"peso_kg": "9307"})
    llamadas = []
    _stub_reconciliacion(monkeypatch, llamadas)

    resultado = m.revalidar_documentos_por_transporte(
        raiz_atlas=raiz, numero_transporte="0000000000", dry_run=False, proveedor=object(),
    )
    assert resultado["documentos_encontrados"] == 0
    assert resultado["campos_cambiados_total"] == 0
    assert llamadas == []


def test_numero_transporte_vacio_falla_explicitamente(tmp_path):
    raiz = _raiz(tmp_path)
    try:
        m.revalidar_documentos_por_transporte(raiz_atlas=raiz, numero_transporte="   ", dry_run=True)
        assert False, "debía lanzar ValueError"
    except ValueError:
        pass


def test_multiples_guias_del_mismo_transporte_se_reprocesan_todas(tmp_path, monkeypatch):
    # Caso real 0000359510: 3 guías, 2 con peso a corregir y 1 ya correcta.
    raiz = _raiz(tmp_path)
    for nombre in ("474285.jpg", "474286.jpg", "474287.jpg"):
        _crear_imagen(raiz, nombre)
    filas = [
        _fila_base(archivo="474285.jpg", numero_guia="474285", peso_kg="19307"),
        _fila_base(archivo="474286.jpg", numero_guia="474286", peso_kg="9535"),
        _fila_base(archivo="474287.jpg", numero_guia="474287", peso_kg="18937"),
    ]
    _escribir_dataset(raiz, filas)
    _escribir_ledger(raiz, [])

    pesos_corregidos = {"474285.jpg": "9307", "474286.jpg": "9535", "474287.jpg": "8937"}

    def _procesar(ruta, **kw):
        nombre = ruta.name if hasattr(ruta, "name") else str(ruta)
        return {"peso_kg": pesos_corregidos[nombre]}

    monkeypatch.setattr(m, "procesar_archivo", _procesar)
    llamadas = []
    _stub_reconciliacion(monkeypatch, llamadas)

    resultado = m.revalidar_documentos_por_transporte(
        raiz_atlas=raiz, numero_transporte="0000359510", dry_run=False, proveedor=object(),
    )
    assert resultado["documentos_encontrados"] == 3
    assert resultado["campos_cambiados_total"] == 2  # sólo 474285 y 474287 cambian
    assert len(llamadas) == 1

    filas_tras = _leer_filas(raiz / "operacion" / "actual" / "analisis_completo_guias.csv")
    pesos_finales = {f["numero_guia"]: f["peso_kg"] for f in filas_tras}
    assert pesos_finales == {"474285": "9307", "474286": "9535", "474287": "8937"}
