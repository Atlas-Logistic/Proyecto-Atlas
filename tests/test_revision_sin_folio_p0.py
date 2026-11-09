"""Regresión aislada: el destino debe sobrevivir a corregir un folio ausente."""
from atlas_core.destino_operacional import TIPO, proyectar_destino
from tests.test_acciones_operacionales import entorno  # noqa: F401


def test_destino_confirmado_conservado_al_corregir_folio():
    archivo = "mobile/ejemplo/original.jpg"
    fila = {"archivo": archivo, "numero_guia": "No encontrado", "numero_transporte": "0000369009"}
    ledger = {"aplicaciones": [{"tipo": TIPO, "documento": dict(fila),
                               "destino_operacional": {"direccion": "PRESIDENTE RIESCO 5903",
                                                       "comuna": "LAS CONDES"}}]}
    assert proyectar_destino(fila, ledger)["direccion_entrega"] == "PRESIDENTE RIESCO 5903"
    ledger["aplicaciones"].append({"tipo": "CORRECCION_DOCUMENTAL_OPERADOR", "accion": "CORREGIR_NUMERO_GUIA", "actor": "JAVIER",
                                    "documento": {**fila, "numero_guia": "484180"},
                                    "campo": "numero_guia", "valor_documental": "No encontrado",
                                    "valor_corregido": "484180"})
    assert proyectar_destino({**fila, "numero_guia": "484180"}, ledger).get("direccion_entrega") == "PRESIDENTE RIESCO 5903"


def test_no_se_transfiere_a_otro_documento_transporte_o_cambio_automatico():
    fila = {"archivo": "mobile/a/original.jpg", "numero_guia": "484180", "numero_transporte": "0000369009"}
    anterior = {**fila, "numero_guia": "No encontrado"}
    destino = {"tipo": TIPO, "documento": anterior, "actor": "JAVIER",
               "destino_operacional": {"direccion": "CALLE 123", "comuna": "LAS CONDES"}}
    cambio = {"tipo": "CORRECCION_DOCUMENTAL_OPERADOR", "accion": "CORREGIR_NUMERO_GUIA",
              "campo": "numero_guia", "actor": "JAVIER", "documento": dict(fila),
              "valor_documental": "No encontrado", "valor_corregido": "484180"}
    def proyectar(d, c):
        return proyectar_destino(fila, {"aplicaciones": [d, c]}).get("direccion_entrega")
    assert proyectar(destino, cambio) == "CALLE 123"
    assert proyectar(destino, {**cambio, "actor": "ATLAS_AUTOMATICO"}) is None
    assert proyectar(destino, {**cambio, "documento": {**fila, "archivo": "mobile/b/original.jpg"}}) is None
    assert proyectar(destino, {**cambio, "documento": {**fila, "numero_transporte": "0000999999"}}) is None
    assert proyectar({**destino, "documento": {**anterior, "numero_transporte": "0000999999"}}, cambio) is None


def test_destino_confirmado_despues_del_folio_tiene_precedencia_y_no_cambia_el_ledger():
    import copy
    fila = {"archivo": "mobile/a/original.jpg", "numero_guia": "484180", "numero_transporte": "0000369009"}
    cambio = {"tipo": "CORRECCION_DOCUMENTAL_OPERADOR", "accion": "CORREGIR_NUMERO_GUIA", "actor": "JAVIER",
              "campo": "numero_guia", "documento": dict(fila), "valor_documental": "No encontrado", "valor_corregido": "484180"}
    destino = {"tipo": TIPO, "actor": "JAVIER", "confirmado_por": "JAVIER", "documento": dict(fila),
               "destino_operacional": {"direccion": "CALLE 456", "comuna": "LAS CONDES"}}
    ledger = {"aplicaciones": [cambio, destino]}
    original = copy.deepcopy(ledger)
    assert proyectar_destino(fila, ledger)["direccion_entrega"] == "CALLE 456"
    assert ledger == original


def test_folio_real_preserva_destino_ruta_estado_y_auditoria(entorno, monkeypatch):
    import json
    from atlas_core.acciones_operacionales import CapaAccionesOperacionales
    from tests.test_acciones_operacionales import _fila, _escribir_dataset, _filas_dataset, _sin_reporte_real

    archivo = "mobile/sintetico/original.jpg"
    fila = _fila("No encontrado", archivo=archivo, numero_transporte="0000369009",
                 motivos_revision_documento="GUIA_AUSENTE", estado_operacional="REQUIERE_REVISION",
                 estado_documental="REQUIERE_REVISION", indicador_revision="REVISAR", distancia_km="12")
    _escribir_dataset(entorno, [fila, _fila("500002")])
    original = entorno["raiz"] / archivo
    original.parent.mkdir(parents=True)
    original.write_bytes(b"fotografia sintetica")
    destino = {"tipo": TIPO, "actor": "JAVIER", "confirmado_por": "JAVIER", "documento": dict(fila),
               "destino_operacional": {"direccion": "PRESIDENTE RIESCO 5903", "comuna": "LAS CONDES"},
               "ruta_operacional": {"estado_ruta": "RUTA_CALCULADA", "comuna": "LAS CONDES", "distancia_km": "17"}}
    ruta_ledger = entorno["actual"] / "decisiones_aplicadas.json"
    ruta_ledger.write_text(json.dumps({"aplicaciones": [destino]}), encoding="utf-8")
    antes = _filas_dataset(entorno)
    vista_antes = proyectar_destino(antes[archivo], {"aplicaciones": [destino]})
    reportes = []
    _sin_reporte_real(monkeypatch, reportes)
    capa = CapaAccionesOperacionales(entorno["raiz"])
    monkeypatch.setattr(capa, "_converger_mobile", lambda *a, **k: (_ for _ in ()).throw(AssertionError("mobile")))
    monkeypatch.setattr(capa, "_revalidar_guias", lambda guias: None if not guias else (_ for _ in ()).throw(AssertionError("revalidacion")))
    preview = capa.previsualizar("DOCUMENTO_CORREGIR_NUMERO_GUIA", {"numero_guia": "No encontrado",
        "numero_guia_corregido": "484180", "archivo": archivo}, actor="JAVIER")
    assert preview["estado"] == "PREVIEW", preview
    resultado = capa.ejecutar(preview["token"], actor="JAVIER", confirmado_por="JAVIER")
    assert resultado["estado"] == "APLICADA", resultado.get("mensaje")
    despues = _filas_dataset(entorno)
    assert despues[archivo] == {**antes[archivo], "numero_guia": "484180"}
    assert despues["500002.jpeg"] == antes["500002.jpeg"]
    ledger = json.loads(ruta_ledger.read_text(encoding="utf-8"))
    assert ledger["aplicaciones"][0] == destino
    assert ledger["aplicaciones"][-1]["confirmado_por"] == "JAVIER"
    proyectada = proyectar_destino(despues[archivo], ledger)
    assert proyectada["direccion_entrega"] == "PRESIDENTE RIESCO 5903"
    assert proyectada["distancia_km"] == "17"
    assert proyectada == {**vista_antes, "numero_guia": "484180"}
    assert original.read_bytes() == b"fotografia sintetica"
    from atlas_core.destino_operacional import identidades_destino_confirmado
    from atlas_core.revalidacion_documental import _escribir_filas_completas
    assert (archivo, "484180") in identidades_destino_confirmado(ruta_ledger)
    _escribir_filas_completas(entorno["dataset"], list(despues.values()))
    assert _filas_dataset(entorno)[archivo] == despues[archivo]


def test_orden_inverso_folio_y_despues_destino(entorno, monkeypatch):
    import json
    import atlas_core.destino_operacional as destino_modulo
    from atlas_core.acciones_operacionales import CapaAccionesOperacionales
    from tests.test_acciones_operacionales import _fila, _escribir_dataset, _filas_dataset, _sin_reporte_real

    archivo = "mobile/inverso/original.jpg"
    _escribir_dataset(entorno, [_fila("No encontrado", archivo=archivo, numero_transporte="0000369009"),
                                _fila("500002")])
    _sin_reporte_real(monkeypatch, [])
    monkeypatch.setattr(destino_modulo, "calcular_ruta_operacional", lambda *a, **k: {"estado_ruta": "PENDIENTE"})
    capa = CapaAccionesOperacionales(entorno["raiz"])
    folio = capa.previsualizar("DOCUMENTO_CORREGIR_NUMERO_GUIA", {"numero_guia": "No encontrado",
        "numero_guia_corregido": "484180", "archivo": archivo}, actor="JAVIER")
    assert folio["estado"] == "PREVIEW", folio
    assert capa.ejecutar(folio["token"], actor="JAVIER", confirmado_por="JAVIER")["estado"] == "APLICADA"
    preview = capa.previsualizar("DOCUMENTO_CORREGIR_DESTINO_OPERACIONAL", {"numero_guia": "484180",
        "archivo": archivo, "direccion": "PRESIDENTE RIESCO 5903", "comuna": "LAS CONDES"}, actor="JAVIER")
    assert preview["estado"] == "PREVIEW", preview
    resultado = capa.ejecutar(preview["token"], actor="JAVIER", confirmado_por="JAVIER")
    assert resultado["estado"] == "APLICADA", resultado
    ledger = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    assert [a["accion"] for a in ledger["aplicaciones"]] == ["CORREGIR_NUMERO_GUIA", "CORREGIR_DESTINO_OPERACIONAL"]
    assert all(a["confirmado_por"] == "JAVIER" for a in ledger["aplicaciones"])
    assert proyectar_destino(_filas_dataset(entorno)[archivo], ledger)["direccion_entrega"] == "PRESIDENTE RIESCO 5903"


def test_guardia_rechaza_transicion_con_transporte_o_datos_alterados(entorno):
    import json
    import pytest
    from atlas_core.revalidacion_documental import _escribir_filas_completas
    from tests.test_acciones_operacionales import _fila, _escribir_dataset, _filas_dataset

    archivo = "mobile/guardia/original.jpg"
    fila = _fila("No encontrado", archivo=archivo, numero_transporte="0000369009")
    _escribir_dataset(entorno, [fila])
    ledger = {"aplicaciones": [{"tipo": TIPO, "documento": dict(fila),
               "destino_operacional": {"direccion": "CALLE 123", "comuna": "LAS CONDES"}}]}
    (entorno["actual"] / "decisiones_aplicadas.json").write_text(json.dumps(ledger), encoding="utf-8")
    actual = _filas_dataset(entorno)[archivo]
    antes = entorno["dataset"].read_bytes()
    for cambio, transporte in [({"cliente": "OTRO"}, "0000369009"), ({}, "0000999999")]:
        with pytest.raises(ValueError):
            _escribir_filas_completas(entorno["dataset"], [{**actual, "numero_guia": "484180", **cambio}],
                                     transicion_folio=(archivo, "No encontrado", "484180", transporte))
        assert entorno["dataset"].read_bytes() == antes
