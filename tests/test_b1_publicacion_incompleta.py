"""Reintentos de correcciones sobre un dataset sintético, nunca producción."""
import json

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from tests.test_acciones_operacionales import entorno, _escribir_dataset, _fila, _sin_reporte_real


def test_interrupcion_tras_ledger_no_duplica_folio(entorno, monkeypatch):
    archivo = "mobile/prueba/original.jpg"
    _escribir_dataset(entorno, [_fila("No encontrado", archivo=archivo, numero_transporte="0000369009")])
    _sin_reporte_real(monkeypatch, [])
    capa = CapaAccionesOperacionales(entorno["raiz"])
    preview = capa.previsualizar("DOCUMENTO_CORREGIR_NUMERO_GUIA", {
        "numero_guia": "No encontrado", "numero_guia_corregido": "484180", "archivo": archivo,
    }, actor="B1", origen="B1")
    assert preview["estado"] == "PREVIEW"

    def corte(*args, **kwargs):
        raise SystemExit("corte simulado antes de auditar")

    monkeypatch.setattr(capa, "_auditar", corte)
    with pytest.raises(SystemExit):
        capa.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")

    ledger_path = entorno["actual"] / "decisiones_aplicadas.json"
    antes = ledger_path.read_bytes()
    reintento = CapaAccionesOperacionales(entorno["raiz"]).ejecutar(
        preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    assert reintento["codigo"] == "PUBLICACION_INCOMPLETA"
    assert ledger_path.read_bytes() == antes
    entradas = json.loads(antes)["aplicaciones"]
    assert len([e for e in entradas if e["decision_id"] == f"ACCION_OPERACIONAL:{preview['token']}"]) == 1
    assert entradas[-1]["confirmado_por"] == "JAVIER"
    recuperacion = CapaAccionesOperacionales(entorno["raiz"]).recuperar_publicacion_sin_cambios(preview["token"])
    assert recuperacion["codigo"] == "PUBLICACION_INCOMPLETA"
    assert ledger_path.read_bytes() == antes


def test_interrupcion_antes_ledger_bloquea_reintento(entorno, monkeypatch):
    import atlas_core.acciones_operacionales as acciones

    archivo = "mobile/prueba/original.jpg"
    _escribir_dataset(entorno, [_fila("No encontrado", archivo=archivo, numero_transporte="0000369009")])
    _sin_reporte_real(monkeypatch, [])
    capa = CapaAccionesOperacionales(entorno["raiz"])
    preview = capa.previsualizar("DOCUMENTO_CORREGIR_NUMERO_GUIA", {
        "numero_guia": "No encontrado", "numero_guia_corregido": "484180", "archivo": archivo,
    }, actor="B1", origen="B1")
    escribir = acciones.escribir_json_atomico

    def interrumpir_ledger(ruta, contenido):
        if ruta == entorno["actual"] / "decisiones_aplicadas.json":
            raise SystemExit("corte simulado antes del ledger")
        return escribir(ruta, contenido)

    monkeypatch.setattr(acciones, "escribir_json_atomico", interrumpir_ledger)
    with pytest.raises(SystemExit):
        capa.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    antes = entorno["dataset"].read_bytes()
    reintento = CapaAccionesOperacionales(entorno["raiz"]).ejecutar(
        preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    assert reintento["codigo"] == "PUBLICACION_INCOMPLETA"
    assert entorno["dataset"].read_bytes() == antes
    recuperacion = CapaAccionesOperacionales(entorno["raiz"]).recuperar_publicacion_sin_cambios(preview["token"])
    assert recuperacion["codigo"] == "PUBLICACION_INCOMPLETA"
    assert entorno["dataset"].read_bytes() == antes


@pytest.mark.parametrize("accion", ["folio", "obra", "destino"])
def test_reinicio_recupera_corte_sin_efectos(entorno, monkeypatch, accion):
    from dataclasses import replace
    from atlas_core.acciones_operacionales import ACCIONES
    from tests.test_acciones_operacionales import _registrar_obra

    archivo = "mobile/prueba/original.jpg"
    _escribir_dataset(entorno, [_fila("No encontrado", archivo=archivo, numero_transporte="0000369009")])
    _sin_reporte_real(monkeypatch, [])
    capa = CapaAccionesOperacionales(entorno["raiz"])
    obra_id = _registrar_obra(capa, entorno["cliente"].cliente_id, "CONSTRUCTORA EJEMPLO LTDA")
    acciones = {
        "folio": ("DOCUMENTO_CORREGIR_NUMERO_GUIA", {"numero_guia_corregido": "484180"}),
        "obra": ("DOCUMENTO_ASIGNAR_OBRA", {"obra_id": obra_id, "conservar_estado": True}),
        "destino": ("DOCUMENTO_CORREGIR_DESTINO_OPERACIONAL", {
            "direccion": "PRESIDENTE RIESCO 5903", "comuna": "LAS CONDES", "conservar_estado": True}),
    }
    nombre, adicionales = acciones[accion]
    preview = capa.previsualizar(nombre, {"numero_guia": "No encontrado", "archivo": archivo, **adicionales},
                                 actor="B1", origen="B1")
    assert preview["estado"] == "PREVIEW", preview
    original = ACCIONES[nombre]

    def corte(*args, **kwargs):
        raise SystemExit("corte antes de escribir")

    monkeypatch.setitem(ACCIONES, nombre, replace(original, aplicar=corte))
    with pytest.raises(SystemExit):
        capa.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    monkeypatch.setitem(ACCIONES, nombre, original)
    nueva = CapaAccionesOperacionales(entorno["raiz"])
    recuperacion = nueva.recuperar_publicacion_sin_cambios(preview["token"])
    assert recuperacion["estado"] == "APLICADA", recuperacion
    assert nueva.auditoria()[-1]["confirmado_por"] == "JAVIER"
    assert nueva.recuperar_publicacion_sin_cambios(preview["token"])["idempotente"]
    assert nueva.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")["idempotente"]


def test_recuperacion_rechaza_cambio_ajeno_y_no_restaura(entorno, monkeypatch):
    from dataclasses import replace
    from atlas_core.acciones_operacionales import ACCIONES

    archivo = "mobile/prueba/original.jpg"
    _escribir_dataset(entorno, [_fila("No encontrado", archivo=archivo, numero_transporte="0000369009")])
    capa = CapaAccionesOperacionales(entorno["raiz"])
    preview = capa.previsualizar("DOCUMENTO_CORREGIR_NUMERO_GUIA", {
        "numero_guia": "No encontrado", "numero_guia_corregido": "484180", "archivo": archivo,
    }, actor="B1", origen="B1")

    def corte(*args, **kwargs):
        raise SystemExit("corte antes de escribir")

    monkeypatch.setitem(ACCIONES, preview["accion"], replace(ACCIONES[preview["accion"]], aplicar=corte))
    with pytest.raises(SystemExit):
        capa.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    contenido_ajeno = b'{"schema_version": 1, "aplicaciones": [{"decision_id": "otra"}]}'
    ledger = entorno["actual"] / "decisiones_aplicadas.json"
    ledger.write_bytes(contenido_ajeno)
    resultado = CapaAccionesOperacionales(entorno["raiz"]).recuperar_publicacion_sin_cambios(preview["token"])
    assert resultado["codigo"] == "PUBLICACION_INCOMPLETA"
    assert ledger.read_bytes() == contenido_ajeno


def test_recuperacion_concurrente_no_ejecuta_dos_veces(entorno, monkeypatch):
    from dataclasses import replace
    from threading import Event, Thread
    from atlas_core.acciones_operacionales import ACCIONES

    archivo = "mobile/prueba/original.jpg"
    _escribir_dataset(entorno, [_fila("No encontrado", archivo=archivo, numero_transporte="0000369009")])
    _sin_reporte_real(monkeypatch, [])
    capa = CapaAccionesOperacionales(entorno["raiz"])
    preview = capa.previsualizar("DOCUMENTO_CORREGIR_NUMERO_GUIA", {
        "numero_guia": "No encontrado", "numero_guia_corregido": "484180", "archivo": archivo,
    }, actor="B1", origen="B1")
    original = ACCIONES[preview["accion"]]
    iniciada, continuar = Event(), Event()

    def aplicar_bloqueado(*args, **kwargs):
        iniciada.set()
        assert continuar.wait(10)
        return original.aplicar(*args, **kwargs)

    monkeypatch.setitem(ACCIONES, preview["accion"], replace(original, aplicar=aplicar_bloqueado))
    resultados = []
    hilo = Thread(target=lambda: resultados.append(capa.ejecutar(
        preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")))
    hilo.start()
    try:
        assert iniciada.wait(10)
        concurrente = CapaAccionesOperacionales(entorno["raiz"]).recuperar_publicacion_sin_cambios(preview["token"])
        assert concurrente["codigo"] == "SESION_OCUPADA"
    finally:
        continuar.set()
        hilo.join(10)
    assert not hilo.is_alive()
    assert resultados[0]["estado"] == "APLICADA"
    auditoria = capa.auditoria()
    assert len([a for a in auditoria if a["token"] == preview["token"]]) == 1


@pytest.mark.parametrize("confirmante", ["B1", "ATLAS_AUTOMATICO"])
def test_confirmacion_automatica_no_autoriza_folio(entorno, confirmante):
    archivo = "mobile/prueba/original.jpg"
    _escribir_dataset(entorno, [_fila("No encontrado", archivo=archivo, numero_transporte="0000369009")])
    capa = CapaAccionesOperacionales(entorno["raiz"])
    preview = capa.previsualizar("DOCUMENTO_CORREGIR_NUMERO_GUIA", {
        "numero_guia": "No encontrado", "numero_guia_corregido": "484180", "archivo": archivo,
    }, actor="B1", origen="B1")
    antes = entorno["dataset"].read_bytes()
    resultado = capa.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por=confirmante)
    assert resultado["codigo"] == "CONFIRMACION_REQUERIDA"
    assert entorno["dataset"].read_bytes() == antes
