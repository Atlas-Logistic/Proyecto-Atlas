import json
import pytest
from atlas_core.b1_operador import OperadorB1, interpretar_determinista
from atlas_core.destino_operacional import proyectar_destino
from tests.test_acciones_operacionales import entorno

ORDEN = "El destino de la guia 500001 es GALVARINO 8501, QUILICURA"
ACCION = "DOCUMENTO_CORREGIR_DESTINO_OPERACIONAL"


def test_instruccion_acepta_comuna_explicita():
    i = interpretar_determinista(ORDEN)
    assert i.accion == ACCION
    assert i.parametros == {"numero_guia": "500001", "direccion": "GALVARINO 8501", "comuna": "QUILICURA"}


@pytest.mark.parametrize("desde_tarjeta", [False, True])
def test_preview_confirmacion_ledger_y_documentos_intactos(entorno, desde_tarjeta):
    antes = entorno["dataset"].read_bytes()
    b1 = OperadorB1(entorno["raiz"], usuario="JAVIER")
    texto = ("@revision:" + entorno["decision"]["decision_id"] + " " if desde_tarjeta else "") + ORDEN
    preview = b1.atender("destino-test", texto)
    assert preview["estado"] == "PREVIEW_PENDIENTE", preview
    assert preview["preview"]["entidad"]["id"] == "500001.jpeg"
    assert preview["preview"]["valor_propuesto"]["direccion"] == "GALVARINO 8501"
    assert entorno["dataset"].read_bytes() == antes
    r = b1.atender("destino-test", "si")
    assert r["estado"] == "EJECUTADA", r
    assert r["resultado"]["persistencia_verificada"] is True
    assert entorno["dataset"].read_bytes() == antes
    ledger = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    assert ledger["aplicaciones"][-1]["destino_operacional"] == {"direccion":"GALVARINO 8501", "comuna":"QUILICURA"}
    assert ledger["aplicaciones"][-1]["confirmado_por"] == "JAVIER"


def test_cancelar_no_escribe_ledger(entorno):
    ledger = entorno["actual"] / "decisiones_aplicadas.json"
    antes = ledger.read_bytes()
    b1 = OperadorB1(entorno["raiz"], usuario="JAVIER")
    assert b1.atender("destino-test", ORDEN)["estado"] == "PREVIEW_PENDIENTE"
    assert b1.atender("destino-test", "no")["estado"] == "CANCELADA"
    assert ledger.read_bytes() == antes
from atlas_core.revalidacion_documental import reconciliar_bandeja_decisiones
from atlas_core.reporte_viajes import generar_reporte_viajes
import csv


def test_reconciliacion_y_reporte_respetan_el_ledger_por_documento(entorno, tmp_path):
    b1 = OperadorB1(entorno["raiz"], usuario="JAVIER")
    assert b1.atender("destino-test", ORDEN)["estado"] == "PREVIEW_PENDIENTE"
    resultado = b1.atender("destino-test", "si")
    assert resultado["estado"] == "EJECUTADA", resultado
    antes = entorno["dataset"].read_bytes()
    reconciliar_bandeja_decisiones(raiz_atlas=entorno["raiz"])
    assert entorno["dataset"].read_bytes() == antes
    salida = tmp_path / "reporte-test"
    generar_reporte_viajes(entorno["dataset"], salida, carpeta_catalogos=entorno["cat"],
                          ruta_ledger=entorno["actual"] / "decisiones_aplicadas.json")
    with (salida / "viajes.csv").open(encoding="utf-8-sig", newline="") as f:
        viajes = list(csv.DictReader(f, delimiter=";"))
    entregas = json.loads(viajes[0]["entregas"])
    e = next(e for e in entregas if "500001" in e["numeros_guia"])
    assert e["destino_operacional"] == "GALVARINO 8501"
    assert e["distancia_km"] == "" and e["estado_ruta"] == ""
    assert all("500002" not in e["numeros_guia"] for e in entregas if "500001" in e["numeros_guia"])

def test_sin_comuna_pide_aclaracion_sin_cambios(entorno):
    antes = (entorno["actual"] / "decisiones_aplicadas.json").read_bytes()
    b1 = OperadorB1(entorno["raiz"], usuario="JAVIER")
    r = b1.atender("destino-test", "El destino de la guia 500001 es GALVARINO 8501")
    assert r["estado"] == "ACLARACION_REQUERIDA" and "comuna" in r["mensaje"]
    assert (entorno["actual"] / "decisiones_aplicadas.json").read_bytes() == antes

def test_reconciliacion_retira_solo_tarjeta_destino_exacta(entorno):
    from atlas_core.destino_operacional import retirar_decisiones_destino_operacional
    b1 = OperadorB1(entorno["raiz"], usuario="JAVIER")
    assert b1.atender("destino-test", ORDEN)["estado"] == "PREVIEW_PENDIENTE"
    assert b1.atender("destino-test", "si")["estado"] == "EJECUTADA"
    documento = {"archivo":"500001.jpeg", "numero_guia":"500001"}
    decisiones = [
        {"tipo":"DESTINO_NO_RESUELTO", "documento": documento},
        {"tipo":"OBRA_DESCONOCIDA", "documento": documento},
        {"tipo":"DESTINO_NO_RESUELTO", "documento": {"archivo":"500002.jpeg", "numero_guia":"500002"}},
    ]
    salida = retirar_decisiones_destino_operacional(decisiones, ruta_ledger=entorno["actual"] / "decisiones_aplicadas.json")
    assert salida == decisiones[1:]

def test_revalidacion_conserva_documental_confirmado(entorno):
    from atlas_core.revalidacion_documental import revalidar_destino_rut_pegado_persistido_sin_ocr
    from atlas_core.procesamiento_masivo import COLUMNAS
    with entorno["dataset"].open(encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f, delimiter=";"))
    filas[0]["despachar_a_crudo"] = "CALLE VIEJA 100 :15454297-3"
    filas[0]["direccion_entrega"] = "CALLE VIEJA 100 :15454297-3"
    with entorno["dataset"].open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";"); w.writeheader(); w.writerows(filas)
    b1 = OperadorB1(entorno["raiz"], usuario="JAVIER")
    assert b1.atender("destino-test", ORDEN)["estado"] == "PREVIEW_PENDIENTE"
    assert b1.atender("destino-test", "si")["estado"] == "EJECUTADA"
    antes = entorno["dataset"].read_bytes()
    revalidar_destino_rut_pegado_persistido_sin_ocr(ruta_dataset=entorno["dataset"])
    assert entorno["dataset"].read_bytes() == antes

def test_revalidador_no_puede_reescribir_documento_ni_ruta(entorno):
    from atlas_core.revalidacion_documental import _leer_filas, _escribir_filas_completas
    b1 = OperadorB1(entorno["raiz"], usuario="JAVIER")
    assert b1.atender("destino-test", ORDEN)["estado"] == "PREVIEW_PENDIENTE"
    assert b1.atender("destino-test", "si")["estado"] == "EJECUTADA"
    filas = _leer_filas(entorno["dataset"])
    original = dict(filas[0])
    filas[0].update({"despachar_a_crudo": "CALLE ALTERADA 111", "direccion_entrega": "CALLE ALTERADA 111", "distancia_km": "99"})
    _escribir_filas_completas(entorno["dataset"], filas)
    actual = _leer_filas(entorno["dataset"])[0]
    for campo in ("despachar_a_crudo", "direccion_entrega", "distancia_km"):
        assert actual[campo] == original[campo]


def test_ledger_corrupto_no_publica_reporte(entorno, tmp_path):
    ledger = entorno["actual"] / "decisiones_aplicadas.json"
    ledger.write_text("{", encoding="utf-8")
    with pytest.raises(RuntimeError, match="ledger"):
        generar_reporte_viajes(entorno["dataset"], tmp_path / "salida", carpeta_catalogos=entorno["cat"], ruta_ledger=ledger)

def test_documento_sin_destino_no_hereda_correccion_ni_cede_ruta(entorno, tmp_path):
    from atlas_core.procesamiento_masivo import COLUMNAS
    with entorno["dataset"].open(encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f, delimiter=";"))
    filas[1].update({"obra_destino":filas[0]["obra_destino"], "despachar_a_crudo":filas[0]["despachar_a_crudo"],
                     "direccion_entrega":"", "distancia_km":"17", "estado_ruta":"RUTA_CALCULADA"})
    with entorno["dataset"].open("w", encoding="utf-8-sig", newline="") as f:
        w=csv.DictWriter(f,fieldnames=COLUMNAS,delimiter=";");w.writeheader();w.writerows(filas)
    b1=OperadorB1(entorno["raiz"], usuario="JAVIER")
    assert b1.atender("destino-test", ORDEN)["estado"]=="PREVIEW_PENDIENTE"
    assert b1.atender("destino-test", "si")["estado"]=="EJECUTADA"
    salida=tmp_path / "reporte"
    generar_reporte_viajes(entorno["dataset"], salida, carpeta_catalogos=entorno["cat"],
                          ruta_ledger=entorno["actual"] / "decisiones_aplicadas.json")
    with (salida / "viajes.csv").open(encoding="utf-8-sig",newline="") as f:
        viaje=next(csv.DictReader(f,delimiter=";"))
    entregas=json.loads(viaje["entregas"])
    objetivo=next(e for e in entregas if "500001" in e["numeros_guia"])
    assert objetivo["numeros_guia"]==["500001"] and objetivo["distancia_km"]==""
    assert viaje["distancia_km"]=="" and viaje["estado_ruta"]==""

def test_destino_confirmado_visible_en_viaje_de_una_guia_sin_ruta(entorno, tmp_path):
    from atlas_core.procesamiento_masivo import COLUMNAS
    with entorno["dataset"].open(encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f, delimiter=";"))[:1]
    with entorno["dataset"].open("w", encoding="utf-8-sig", newline="") as f:
        w=csv.DictWriter(f,fieldnames=COLUMNAS,delimiter=";");w.writeheader();w.writerows(filas)
    b1=OperadorB1(entorno["raiz"], usuario="JAVIER")
    assert b1.atender("destino-test", ORDEN)["estado"]=="PREVIEW_PENDIENTE"
    assert b1.atender("destino-test", "si")["estado"]=="EJECUTADA"
    salida=tmp_path / "single"
    generar_reporte_viajes(entorno["dataset"], salida, carpeta_catalogos=entorno["cat"],
                          ruta_ledger=entorno["actual"] / "decisiones_aplicadas.json")
    with (salida / "viajes.csv").open(encoding="utf-8-sig",newline="") as f:
        viaje=next(csv.DictReader(f,delimiter=";"))
    assert viaje["direccion_entrega"] == "GALVARINO 8501"
    assert viaje["localidad_entrega"] == "QUILICURA"
    assert viaje["distancia_km"] == viaje["estado_ruta"] == ""

def test_reproceso_mobile_de_guia_confirmada_se_abstiene(tmp_path):
    from atlas_core.mobile import reprocesar_envio_mobile_persistido, ErrorEnvioMobile
    from tests.test_mobile_reproceso_persistido import _recibir, _dataset_con_filas, _fila_vieja
    repo, envio_id = _recibir(tmp_path)
    dataset = tmp_path / "operacion" / "actual" / "analisis_completo_guias.csv"
    archivo = f"mobile/{envio_id}/original.jpg"
    _dataset_con_filas(dataset, [_fila_vieja(archivo)])
    ledger = dataset.parent / "decisiones_aplicadas.json"
    ledger.write_text(json.dumps({"aplicaciones": [{"tipo":"DESTINO_OPERACIONAL_DOCUMENTO",
        "documento":{"archivo":archivo,"numero_guia":"900001"},
        "destino_operacional":{"direccion":"CALLE 123","comuna":"RENCA"}}]}),encoding="utf-8")
    antes=dataset.read_bytes()
    with pytest.raises(ErrorEnvioMobile, match="destino operacional confirmado"):
        reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset)
    assert dataset.read_bytes()==antes

def test_reconstruccion_no_elimina_ni_duplica_documento_confirmado(entorno):
    from atlas_core.revalidacion_documental import _leer_filas, _escribir_filas_completas
    b1=OperadorB1(entorno["raiz"],usuario="JAVIER")
    assert b1.atender("destino-test",ORDEN)["estado"]=="PREVIEW_PENDIENTE"
    assert b1.atender("destino-test","si")["estado"]=="EJECUTADA"
    filas=_leer_filas(entorno["dataset"]); antes=entorno["dataset"].read_bytes()
    for alteradas in (filas[1:], filas+[filas[0]]):
        with pytest.raises(ValueError,match="eliminado o duplicado"):
            _escribir_filas_completas(entorno["dataset"],alteradas)
        assert entorno["dataset"].read_bytes()==antes

def test_ingreso_mobile_sintetico_conserva_decision_y_documento(entorno, tmp_path):
    from atlas_core.mobile import procesar_envio_mobile
    from tests.test_mobile_reproceso_persistido import _recibir
    b1=OperadorB1(entorno["raiz"],usuario="JAVIER")
    assert b1.atender("destino-test",ORDEN)["estado"]=="PREVIEW_PENDIENTE"
    assert b1.atender("destino-test","si")["estado"]=="EJECUTADA"
    with entorno["dataset"].open(encoding="utf-8-sig",newline="") as f:
        antes=next(csv.DictReader(f,delimiter=";"))
    repo, envio_id=_recibir(entorno["raiz"])
    datos={"numero_guia":"900999","numero_transporte":"0000900999","estado_procesamiento":"OK",
           "cliente":"CLIENTE NUEVO SA","chofer":"PEDRO NUEVO","despachar_a_crudo":"OTRA 999"}
    procesar_envio_mobile(repo, envio_id, dataset=entorno["dataset"], procesador=lambda _: datos)
    with entorno["dataset"].open(encoding="utf-8-sig",newline="") as f:
        filas=list(csv.DictReader(f,delimiter=";"))
    assert next(f for f in filas if f["archivo"]=="500001.jpeg")==antes
    assert any(f["numero_guia"]=="900999" for f in filas)
    ledger=json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    corregida=proyectar_destino(antes,ledger)
    assert corregida["direccion_entrega"]=="GALVARINO 8501" and corregida["distancia_km"]==""

def test_revalidacion_completa_respeta_decision_y_vista_sin_red(entorno, tmp_path):
    from atlas_core.revalidacion_documental import revalidar_y_regenerar_reporte
    from atlas_core.rutas.proveedor import ProveedorRutasSimulado
    b1=OperadorB1(entorno["raiz"],usuario="JAVIER")
    assert b1.atender("destino-test",ORDEN)["estado"]=="PREVIEW_PENDIENTE"
    assert b1.atender("destino-test","si")["estado"]=="EJECUTADA"
    with entorno["dataset"].open(encoding="utf-8-sig",newline="") as f:
        antes=next(csv.DictReader(f,delimiter=";"))
    proveedor=ProveedorRutasSimulado()
    revalidar_y_regenerar_reporte(raiz_atlas=entorno["raiz"], nombre_carpeta_reporte="test-revalidacion",
                                proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor,
                                guias_objetivo={"500001"})
    with entorno["dataset"].open(encoding="utf-8-sig",newline="") as f:
        despues=next(csv.DictReader(f,delimiter=";"))
    for campo in ("despachar_a_crudo","direccion_entrega","estado_ruta","distancia_km"):
        assert despues[campo]==antes[campo]
    ledger=json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    vigente=proyectar_destino(despues,ledger)
    assert vigente["direccion_entrega"]=="GALVARINO 8501" and vigente["estado_ruta"]==""


# ------------------------------------------------ cierre: tarjetas reales, ruta y ciclo PULL

from types import SimpleNamespace


def _con_planta(entorno, monkeypatch, *, comuna_resuelta="QUILICURA", estado="RUTA_CALCULADA"):
    """Planta conocida y proveedor de rutas simulado: nunca red."""
    from atlas_core.procesamiento_masivo import COLUMNAS
    with entorno["dataset"].open(encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f, delimiter=";"))
    for fila in filas:
        fila["planta_origen_id"] = "P1"
    with entorno["dataset"].open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";"); w.writeheader(); w.writerows(filas)
    import atlas_core.catalogo_plantas as plantas
    import atlas_core.rutas.destino_entrega as rutas
    monkeypatch.setattr(plantas, "CatalogoPlantas",
                        lambda _ruta: SimpleNamespace(listar=lambda: [SimpleNamespace(planta_id="P1")]))
    llamadas = []

    def calcular(**kw):
        llamadas.append(kw)
        return SimpleNamespace(estado_ruta=estado, motivo_ruta="" if estado == "RUTA_CALCULADA" else "SIN_RESULTADO",
                               localidad_entrega=comuna_resuelta, distancia_km="23.4", duracion_min="31",
                               proveedor_ruta="SIMULADO", latitud_entrega="-33.36", longitud_entrega="-70.73",
                               region_entrega="METROPOLITANA", codigo_pais="CL", codigo_unidad="13125",
                               codigo_contexto="C1")
    monkeypatch.setattr(rutas, "calcular_ruta_con_planta_conocida", calcular)
    return llamadas


def _bandeja_ids(entorno):
    return [d["decision_id"] for d in json.loads(
        (entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]]


def _filas(entorno):
    with entorno["dataset"].open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def _tarjeta(guia):
    from atlas_core.decisiones_pendientes import crear_decision
    return crear_decision(
        tipo="DESTINO_SIN_CONFIRMAR", entidad="RELACION_OBRA_DESTINO", archivo=f"{guia}.jpeg", numero_guia=guia,
        numero_transporte="0000900001", campo="destino_entrega", valor_documental="C5 28.10 12PM/ROLLOS CYD",
        valor_normalizado="C5 28 10 12PM ROLLOS CYD", identidad_resuelta=None, candidatos=(),
        motivos=("OBRA_SIN_RELACION_CONFIRMADA_UNICA",), evidencias=(),
        acciones_permitidas=("CONFIRMAR", "NO_CONFIRMAR", "POSPONER"), contexto={})


def _publicar(entorno, *tarjetas):
    from atlas_core.decisiones_pendientes import generar_artefacto
    generar_artefacto(ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["cat"],
                      decisiones=[entorno["decision"], *tarjetas])


def test_tarjeta_destino_sin_confirmar_corrige_y_no_reaparece(entorno):
    tarjeta, hermana = _tarjeta("500001"), _tarjeta("500002")
    _publicar(entorno, tarjeta, hermana)
    antes = entorno["dataset"].read_bytes()
    b1 = OperadorB1(entorno["raiz"], usuario="JAVIER")
    r = b1.atender("t", f"@revision:{tarjeta['decision_id']} el destino es GALVARINO 8501, QUILICURA")
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert r["preview"]["valor_actual"]["direccion"] == "CALLE DOS 200 SANTIAGO"
    assert r["preview"]["entidad"]["id"] == "500001.jpeg"
    assert tarjeta["decision_id"] in _bandeja_ids(entorno)
    e = b1.atender("t", "si")
    assert e["estado"] == "EJECUTADA", e
    ids = _bandeja_ids(entorno)
    assert tarjeta["decision_id"] not in ids
    assert hermana["decision_id"] in ids and entorno["decision"]["decision_id"] in ids
    # Una regeneración posterior que vuelve a detectar la tarjeta no la publica.
    _publicar(entorno, tarjeta, hermana)
    assert tarjeta["decision_id"] not in _bandeja_ids(entorno)
    reconciliar_bandeja_decisiones(raiz_atlas=entorno["raiz"])
    assert tarjeta["decision_id"] not in _bandeja_ids(entorno)
    assert entorno["dataset"].read_bytes() == antes


def test_tarjeta_destino_sin_comuna_explica_formato(entorno):
    tarjeta = _tarjeta("500001")
    _publicar(entorno, tarjeta)
    b1 = OperadorB1(entorno["raiz"], usuario="JAVIER")
    r = b1.atender("t", f"@revision:{tarjeta['decision_id']} el destino es GALVARINO 8501")
    assert r["estado"] == "ACLARACION_REQUERIDA" and "comuna" in r["mensaje"]
    assert b1.pendiente("t") is None


def test_ruta_recalculada_valida_se_publica_solo_en_la_guia(entorno, monkeypatch, tmp_path):
    llamadas = _con_planta(entorno, monkeypatch)
    b1 = OperadorB1(entorno["raiz"], usuario="JAVIER")
    assert b1.atender("d", ORDEN)["estado"] == "PREVIEW_PENDIENTE"
    assert llamadas == []  # el preview no consulta proveedores
    e = b1.atender("d", "si")
    assert e["estado"] == "EJECUTADA" and "23.4 km" in e["mensaje"], e
    assert len(llamadas) == 1 and llamadas[0]["despachar_a_crudo"] == "GALVARINO 8501"
    assert llamadas[0]["comuna_confirmada_humano"] == "QUILICURA"
    ledger = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    assert ledger["aplicaciones"][-1]["ruta_operacional"]["distancia_km"] == "23.4"
    salida = tmp_path / "rep"
    generar_reporte_viajes(entorno["dataset"], salida, carpeta_catalogos=entorno["cat"],
                           ruta_ledger=entorno["actual"] / "decisiones_aplicadas.json")
    with (salida / "viajes.csv").open(encoding="utf-8-sig", newline="") as f:
        viaje = next(csv.DictReader(f, delimiter=";"))
    entregas = json.loads(viaje["entregas"])
    propia = next(x for x in entregas if "500001" in x["numeros_guia"])
    assert propia["numeros_guia"] == ["500001"] and propia["distancia_km"] == "23.4"
    assert all(x["distancia_km"] != "23.4" for x in entregas if "500002" in x["numeros_guia"])


def test_ruta_que_contradice_la_comuna_queda_pendiente(entorno, monkeypatch):
    _con_planta(entorno, monkeypatch, comuna_resuelta="RENCA")
    b1 = OperadorB1(entorno["raiz"], usuario="JAVIER")
    assert b1.atender("d", ORDEN)["estado"] == "PREVIEW_PENDIENTE"
    e = b1.atender("d", "si")
    assert e["estado"] == "EJECUTADA" and "pendiente" in e["mensaje"], e
    ledger = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    vista = proyectar_destino(_filas(entorno)[0], ledger)
    assert vista["direccion_entrega"] == "GALVARINO 8501"
    assert vista["distancia_km"] == "" and vista["estado_ruta"] == ""


def test_proveedor_caido_no_impide_guardar_destino(entorno, monkeypatch):
    _con_planta(entorno, monkeypatch)
    import atlas_core.rutas.destino_entrega as rutas

    def caido(**_kw):
        raise OSError("sin red")
    monkeypatch.setattr(rutas, "calcular_ruta_con_planta_conocida", caido)
    b1 = OperadorB1(entorno["raiz"], usuario="JAVIER")
    assert b1.atender("d", ORDEN)["estado"] == "PREVIEW_PENDIENTE"
    e = b1.atender("d", "si")
    assert e["estado"] == "EJECUTADA" and e["resultado"]["persistencia_verificada"] is True
    assert e["resultado"]["despues"]["ruta"] == "PENDIENTE"


def test_doble_confirmacion_y_reorden_no_duplican(entorno):
    b1 = OperadorB1(entorno["raiz"], usuario="JAVIER")
    assert b1.atender("d", ORDEN)["estado"] == "PREVIEW_PENDIENTE"
    assert b1.atender("d", "si")["estado"] == "EJECUTADA"
    assert b1.atender("d", "si")["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert b1.atender("d", ORDEN)["estado"] == "SIN_CAMBIOS"
    ledger = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    assert len([a for a in ledger["aplicaciones"] if a.get("tipo") == "DESTINO_OPERACIONAL_DOCUMENTO"]) == 1


def test_correccion_posterior_reemplaza_la_anterior_y_hermana_independiente(entorno):
    b1 = OperadorB1(entorno["raiz"], usuario="JAVIER")
    for orden in (ORDEN, "El destino de la guia 500001 es AVENIDA AMERICO VESPUCIO 1500, RENCA"):
        assert b1.atender("d", orden)["estado"] == "PREVIEW_PENDIENTE"
        assert b1.atender("d", "si")["estado"] == "EJECUTADA"
    ledger = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    filas = _filas(entorno)
    vista = {f["numero_guia"]: proyectar_destino(f, ledger) for f in filas}
    assert vista["500001"]["direccion_entrega"] == "AVENIDA AMERICO VESPUCIO 1500"
    assert vista["500001"]["localidad_entrega"] == "RENCA"
    assert vista["500002"] == next(f for f in filas if f["numero_guia"] == "500002")


def test_ciclo_pull_sintetico_conserva_destino_y_tarjeta_cerrada(entorno, tmp_path):
    """Confirmación -> revalidaciones -> reconciliación de bandeja -> reporte, dos veces."""
    from atlas_core.revalidacion_documental import revalidar_y_regenerar_reporte
    from atlas_core.rutas.proveedor import ProveedorRutasSimulado
    tarjeta = _tarjeta("500001")
    _publicar(entorno, tarjeta)
    b1 = OperadorB1(entorno["raiz"], usuario="JAVIER")
    assert b1.atender("p", f"@revision:{tarjeta['decision_id']} {ORDEN}")["estado"] == "PREVIEW_PENDIENTE"
    assert b1.atender("p", "si")["estado"] == "EJECUTADA"
    original = _filas(entorno)[0]
    proveedor = ProveedorRutasSimulado()
    for _ in range(2):
        revalidar_y_regenerar_reporte(raiz_atlas=entorno["raiz"], nombre_carpeta_reporte="pull-sintetico",
                                      proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor)
        reconciliar_bandeja_decisiones(raiz_atlas=entorno["raiz"])
    assert tarjeta["decision_id"] not in _bandeja_ids(entorno)
    fila = _filas(entorno)[0]
    assert fila["despachar_a_crudo"] == original["despachar_a_crudo"]
    salida = tmp_path / "post-pull"
    generar_reporte_viajes(entorno["dataset"], salida, carpeta_catalogos=entorno["cat"],
                           ruta_ledger=entorno["actual"] / "decisiones_aplicadas.json")
    with (salida / "viajes.csv").open(encoding="utf-8-sig", newline="") as f:
        entregas = json.loads(next(csv.DictReader(f, delimiter=";"))["entregas"])
    assert next(x for x in entregas if "500001" in x["numeros_guia"])["destino_operacional"] == "GALVARINO 8501"
