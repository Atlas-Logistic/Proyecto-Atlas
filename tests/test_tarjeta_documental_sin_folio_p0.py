"""Criterios de entrada de tarjeta para un documento sin folio, con datos sintÃ©ticos."""
import pytest
from tests.test_acciones_operacionales import entorno

from atlas_core.b1_operador import instruccion_en_revision


@pytest.mark.parametrize("texto", [
    "el folio correcto es 484180",
    "la obra correcta es CONSTRUCTORA EJEMPLO LTDA",
    "el destino correcto es PRESIDENTE RIESCO 5903, LAS CONDES",
])
def test_tarjeta_destino_acepta_correccion_independiente_sin_folio(texto):
    tarjeta = {"decision_id": "destino", "tipo": "DESTINO_NO_RESUELTO", "campo": "despachar_a_crudo",
               "documento": {"archivo": "mobile/sintetico/original.jpg", "numero_guia": "No encontrado",
                             "numero_transporte": "0000369009"}}
    assert instruccion_en_revision(tarjeta, texto) is not None

@pytest.mark.parametrize("orden", [
    ("destino", "obra", "folio"),
    ("folio", "destino", "obra"),
    ("obra", "folio", "destino"),
])
def test_tarjeta_corrige_tres_campos_en_cualquier_orden(entorno, monkeypatch, orden):
    import json
    from atlas_core.acciones_operacionales import CapaAccionesOperacionales
    from atlas_core.b1_operador import OperadorB1
    from atlas_core.decisiones_pendientes import crear_decision, generar_artefacto
    from atlas_core.destino_operacional import proyectar_destino
    from tests.test_acciones_operacionales import (_fila, _escribir_dataset, _filas_dataset,
        _sin_reporte_real, _registrar_obra)
    archivo = "mobile/sintetico/original.jpg"
    fila = _fila("No encontrado", archivo=archivo, numero_transporte="0000369009",
                 obra_destino="No encontrado", distancia_km="12", estado_operacional="REQUIERE_REVISION")
    otra = _fila("500002")
    _escribir_dataset(entorno, [fila, otra])
    imagen = entorno["raiz"] / archivo
    imagen.parent.mkdir(parents=True)
    imagen.write_bytes(b"original sintetico")
    _sin_reporte_real(monkeypatch, [])
    capa = CapaAccionesOperacionales(entorno["raiz"])
    _registrar_obra(capa, entorno["cliente"].cliente_id, "CONSTRUCTORA IGNACIO HURTADO LTDA")
    decision = crear_decision(tipo="DESTINO_NO_RESUELTO", entidad="DESTINO", archivo=archivo,
        numero_guia="No encontrado", numero_transporte="0000369009", campo="despachar_a_crudo",
        valor_documental=fila["despachar_a_crudo"], valor_normalizado=fila["despachar_a_crudo"],
        identidad_resuelta=None, candidatos=(), motivos=("DESTINO_NO_RESUELTO",), evidencias=(),
        acciones_permitidas=("REGISTRAR_DIRECCION", "POSPONER"), contexto={})
    generar_artefacto(ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["cat"], decisiones=[decision])
    b1 = OperadorB1(entorno["raiz"], capa=capa)
    import atlas_core.destino_operacional as destino_modulo
    monkeypatch.setattr(destino_modulo, "calcular_ruta_operacional", lambda *a, **k: pytest.fail("no se debe recalcular la ruta"))
    frases = {"destino": "el destino correcto es PRESIDENTE RIESCO 5903, LAS CONDES",
              "obra": "la obra correcta es CONSTRUCTORA IGNACIO HURTADO LTDA",
              "folio": "el folio correcto es 484180"}
    for nombre in orden:
        tarjeta = next(d for d in capa._ctx.decisiones() if d["tipo"] == "DESTINO_NO_RESUELTO")
        antes = entorno["dataset"].read_bytes()
        preview = b1.atender("prueba", f"@revision:{tarjeta['decision_id']} {frases[nombre]}")
        assert preview["estado"] == "PREVIEW_PENDIENTE", preview
        assert entorno["dataset"].read_bytes() == antes
        resultado = b1.atender("prueba", "si")
        assert resultado["estado"] == "EJECUTADA", resultado
    filas = _filas_dataset(entorno)
    assert filas[archivo]["numero_guia"] == "484180"
    assert filas[archivo]["obra_destino"] == "CONSTRUCTORA IGNACIO HURTADO LTDA"
    for campo in ("cliente", "estado_operacional", "estado_ruta", "distancia_km"):
        assert filas[archivo][campo] == fila[campo]
    assert filas["500002.jpeg"] == otra
    assert imagen.read_bytes() == b"original sintetico"
    ledger = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    correcciones = [a for a in ledger["aplicaciones"] if a.get("accion") in {
        "CORREGIR_NUMERO_GUIA", "CORREGIR_CAMPO", "CORREGIR_DESTINO_OPERACIONAL"}]
    assert len(correcciones) == 3
    assert all(a.get("confirmado_por") == "JAVIER" and a["documento"]["archivo"] == archivo
               for a in correcciones)
    proyectada = proyectar_destino(filas[archivo], ledger)
    assert proyectada["direccion_entrega"] == "PRESIDENTE RIESCO 5903"
    assert proyectada["localidad_entrega"] == "LAS CONDES"
    assert proyectada["ruta_requiere_comprobacion"] is True
    assert proyectada["estado_ruta"] == "REQUIERE_COMPROBACION"
    assert proyectada["estado_ruta_historica"] == fila["estado_ruta"]
    assert proyectada["distancia_km"] == "12"


def test_rechaza_archivo_duplicado_o_transporte_distinto(entorno, monkeypatch):
    from atlas_core.acciones_operacionales import CapaAccionesOperacionales
    from atlas_core.b1_operador import OperadorB1
    from tests.test_acciones_operacionales import _entorno_482402, _fila, _escribir_dataset, ARCHIVO_482402

    tarjeta = _entorno_482402(entorno)
    b1 = OperadorB1(entorno["raiz"], capa=CapaAccionesOperacionales(entorno["raiz"]))
    for filas in ([
        _fila("No encontrado", archivo=ARCHIVO_482402, numero_transporte="0000364552"),
        _fila("No encontrado", archivo=ARCHIVO_482402, numero_transporte="0000364552"),
    ], [_fila("No encontrado", archivo=ARCHIVO_482402, numero_transporte="0000369009")]):
        _escribir_dataset(entorno, filas)
        antes = entorno["dataset"].read_bytes()
        r = b1.atender("ambiguo", f"@revision:{tarjeta['decision_id']} el folio correcto es 484180")
        assert r["estado"] == "ACLARACION_REQUERIDA", r
        assert entorno["dataset"].read_bytes() == antes

