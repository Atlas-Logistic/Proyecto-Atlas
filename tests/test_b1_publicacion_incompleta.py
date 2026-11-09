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
    inspeccion = CapaAccionesOperacionales(entorno["raiz"]).inspeccionar_publicacion_interrumpida(preview["token"])
    assert inspeccion["estado"] == "INTERRUMPIDA"
    assert inspeccion["entradas_ledger"] == 1
    assert inspeccion["archivos"]["dataset"]["estado"] == "MODIFICADO"
    assert inspeccion["archivos"]["ledger_decisiones"]["estado"] == "MODIFICADO"
    assert not inspeccion["conflictos"]
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
    reintento = CapaAccionesOperacionales(entorno["raiz"]).recuperar_publicacion_sin_cambios(preview["token"])
    assert reintento["codigo"] == "PUBLICACION_INCOMPLETA"
    assert entorno["dataset"].read_bytes() == antes
    inspeccion = CapaAccionesOperacionales(entorno["raiz"]).inspeccionar_publicacion_interrumpida(preview["token"])
    assert inspeccion["estado"] == "INTERRUMPIDA"
    assert inspeccion["entradas_ledger"] == 0
    assert inspeccion["archivos"]["dataset"]["estado"] == "MODIFICADO"
    assert inspeccion["archivos"]["ledger_decisiones"]["estado"] == "SIN_CAMBIOS"
    from atlas_core.acciones_operacionales import ErrorAccionOperacional
    with pytest.raises(ErrorAccionOperacional) as lectura:
        CapaAccionesOperacionales(entorno["raiz"])._ctx.instantanea_documental()
    assert lectura.value.codigo == "PUBLICACION_INCOMPLETA"
    recuperacion = CapaAccionesOperacionales(entorno["raiz"]).recuperar_publicacion_sin_cambios(preview["token"])
    assert recuperacion["codigo"] == "PUBLICACION_INCOMPLETA"
    assert entorno["dataset"].read_bytes() == antes


@pytest.mark.parametrize("accion", ["folio", "obra"])
def test_recupera_dataset_confirmado_antes_del_ledger(entorno, monkeypatch, accion):
    import subprocess
    import sys
    import atlas_core.acciones_operacionales as acciones
    from tests.test_acciones_operacionales import _registrar_obra

    archivo = "mobile/prueba/original.jpg"
    fila = _fila("No encontrado", archivo=archivo, numero_transporte="0000369009", distancia_km="12")
    otra = _fila("500002")
    _escribir_dataset(entorno, [fila, otra])
    foto = entorno["raiz"] / archivo
    foto.parent.mkdir(parents=True)
    foto.write_bytes(b"original")
    _sin_reporte_real(monkeypatch, [])
    capa = CapaAccionesOperacionales(entorno["raiz"])
    obra_id = _registrar_obra(capa, entorno["cliente"].cliente_id, "CONSTRUCTORA EJEMPLO LTDA")
    nombre, extras = (("DOCUMENTO_CORREGIR_NUMERO_GUIA", {"numero_guia_corregido": "484180"})
                      if accion == "folio" else ("DOCUMENTO_ASIGNAR_OBRA", {"obra_id": obra_id, "conservar_estado": True}))
    preview = capa.previsualizar(nombre, {"numero_guia": "No encontrado", "archivo": archivo, **extras},
                                 actor="B1", origen="B1")
    assert preview["estado"] == "PREVIEW", preview
    escribir = acciones.escribir_json_atomico
    def corte(ruta, contenido):
        if ruta.name == "decisiones_aplicadas.json":
            raise SystemExit("corte antes del ledger")
        escribir(ruta, contenido)
    monkeypatch.setattr(acciones, "escribir_json_atomico", corte)
    with pytest.raises(SystemExit):
        capa.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    monkeypatch.setattr(acciones, "escribir_json_atomico", escribir)
    nueva = CapaAccionesOperacionales(entorno["raiz"])
    programa = ("import json, sys; from atlas_core.acciones_operacionales import CapaAccionesOperacionales as C; "
                "C._regenerar_reporte = lambda self: {'regenerado': True}; "
                "print(json.dumps(C(sys.argv[1]).ejecutar(sys.argv[2], actor='B1', origen='B1', confirmado_por='JAVIER')))")
    proceso = subprocess.run([sys.executable, "-c", programa, str(entorno["raiz"]), preview["token"]],
                             capture_output=True, text=True, timeout=30)
    assert proceso.returncode == 0, proceso.stderr
    resultado = json.loads(proceso.stdout)
    assert resultado["estado"] == "APLICADA", resultado
    assert nueva.recuperar_dataset_antes_del_ledger(preview["token"])["idempotente"]
    vista = nueva._ctx.instantanea_documental()
    documento = next(f for f in vista["filas"] if f["archivo"] == archivo)
    assert documento["numero_guia"] == ("484180" if accion == "folio" else "No encontrado")
    assert documento["obra_destino"] == ("CONSTRUCTORA EJEMPLO LTDA" if accion == "obra" else fila["obra_destino"])
    assert documento["cliente"] == fila["cliente"]
    assert documento["estado_ruta"] == fila["estado_ruta"]
    assert documento["distancia_km"] == "12"
    assert next(f for f in vista["filas"] if f["archivo"] == otra["archivo"]) == otra
    assert foto.read_bytes() == b"original"
    entradas = [e for e in vista["ledger"]["aplicaciones"] if e.get("decision_id") == f"ACCION_OPERACIONAL:{preview['token']}"]
    assert len(entradas) == 1 and entradas[0]["confirmado_por"] == "JAVIER"
    assert len([a for a in nueva.auditoria() if a["token"] == preview["token"]]) == 1


@pytest.mark.parametrize("ajeno", ["dataset", "ledger", "respaldo"])
def test_recuperacion_dataset_no_sobrescribe_cambio_ajeno(entorno, monkeypatch, ajeno):
    import atlas_core.acciones_operacionales as acciones
    archivo = "mobile/prueba/original.jpg"
    _escribir_dataset(entorno, [_fila("No encontrado", archivo=archivo, numero_transporte="0000369009")])
    capa = CapaAccionesOperacionales(entorno["raiz"])
    preview = capa.previsualizar("DOCUMENTO_CORREGIR_NUMERO_GUIA", {
        "numero_guia": "No encontrado", "numero_guia_corregido": "484180", "archivo": archivo,
    }, actor="B1", origen="B1")
    escribir = acciones.escribir_json_atomico
    def corte(ruta, contenido):
        if ruta.name == "decisiones_aplicadas.json":
            raise SystemExit("corte")
        escribir(ruta, contenido)
    monkeypatch.setattr(acciones, "escribir_json_atomico", corte)
    with pytest.raises(SystemExit):
        capa.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    monkeypatch.setattr(acciones, "escribir_json_atomico", escribir)
    registro = json.loads((entorno["actual"] / "acciones_operacionales.json").read_text(encoding="utf-8-sig"))
    respaldo = entorno["raiz"] / registro["previews"][preview["token"]]["publicacion_iniciada"]["respaldo"] / entorno["dataset"].name
    if ajeno == "dataset":
        with entorno["dataset"].open("ab") as f:
            f.write(b" ")
    elif ajeno == "ledger":
        (entorno["actual"] / "decisiones_aplicadas.json").write_text('{"aplicaciones": [{"decision_id": "ajeno"}]}', encoding="utf-8")
    else:
        with respaldo.open("ab") as f:
            f.write(b" ")
    antes_dataset = entorno["dataset"].read_bytes()
    antes_ledger = (entorno["actual"] / "decisiones_aplicadas.json").read_bytes()
    resultado = CapaAccionesOperacionales(entorno["raiz"]).recuperar_dataset_antes_del_ledger(preview["token"])
    assert resultado["codigo"] in {"PUBLICACION_INCOMPLETA", "RECUPERACION_NO_DISPONIBLE"}
    assert entorno["dataset"].read_bytes() == antes_dataset
    assert (entorno["actual"] / "decisiones_aplicadas.json").read_bytes() == antes_ledger


def test_segundo_corte_tras_restaurar_dataset_se_puede_reintentar(entorno, monkeypatch):
    import atlas_core.acciones_operacionales as acciones
    archivo = "mobile/prueba/original.jpg"
    _escribir_dataset(entorno, [_fila("No encontrado", archivo=archivo, numero_transporte="0000369009")])
    _sin_reporte_real(monkeypatch, [])
    capa = CapaAccionesOperacionales(entorno["raiz"])
    preview = capa.previsualizar("DOCUMENTO_CORREGIR_NUMERO_GUIA", {
        "numero_guia": "No encontrado", "numero_guia_corregido": "484180", "archivo": archivo,
    }, actor="B1", origen="B1")
    escribir = acciones.escribir_json_atomico
    def corte(ruta, contenido):
        if ruta.name == "decisiones_aplicadas.json":
            raise SystemExit("corte de publicación")
        escribir(ruta, contenido)
    monkeypatch.setattr(acciones, "escribir_json_atomico", corte)
    with pytest.raises(SystemExit):
        capa.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    monkeypatch.setattr(acciones, "escribir_json_atomico", escribir)
    recuperador = CapaAccionesOperacionales(entorno["raiz"])
    monkeypatch.setattr(recuperador, "recuperar_publicacion_sin_cambios",
                        lambda token: (_ for _ in ()).throw(SystemExit("segundo corte")))
    with pytest.raises(SystemExit):
        recuperador.recuperar_dataset_antes_del_ledger(preview["token"])
    nueva = CapaAccionesOperacionales(entorno["raiz"])
    resultado = nueva.recuperar_dataset_antes_del_ledger(preview["token"])
    assert resultado["estado"] == "APLICADA", resultado
    assert len([a for a in nueva.auditoria() if a["token"] == preview["token"]]) == 1


def test_recuperacion_publica_reporte_real_sintetico(entorno, monkeypatch):
    import atlas_core.acciones_operacionales as acciones
    archivo = "mobile/prueba/original.jpg"
    _escribir_dataset(entorno, [_fila("No encontrado", archivo=archivo, numero_transporte="0000369009")])
    capa = CapaAccionesOperacionales(entorno["raiz"])
    preview = capa.previsualizar("DOCUMENTO_CORREGIR_NUMERO_GUIA", {
        "numero_guia": "No encontrado", "numero_guia_corregido": "484180", "archivo": archivo,
    }, actor="B1", origen="B1")
    escribir = acciones.escribir_json_atomico
    def corte(ruta, contenido):
        if ruta.name == "decisiones_aplicadas.json":
            raise SystemExit("corte")
        escribir(ruta, contenido)
    monkeypatch.setattr(acciones, "escribir_json_atomico", corte)
    with pytest.raises(SystemExit):
        capa.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    monkeypatch.setattr(acciones, "escribir_json_atomico", escribir)
    resultado = CapaAccionesOperacionales(entorno["raiz"]).ejecutar(
        preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    assert resultado["estado"] == "APLICADA", resultado
    assert resultado["revalidacion"]["reporte"]["regenerado"] is True
    estado = json.loads((entorno["actual"] / "estado_operacion.json").read_text(encoding="utf-8-sig"))
    assert (entorno["raiz"] / estado["reporte_vigente"] / "viajes.csv").is_file()


def test_recupera_destino_tras_ledger_en_otro_proceso(entorno, monkeypatch):
    import subprocess
    import sys
    archivo = "mobile/prueba/original.jpg"
    fila = _fila("No encontrado", archivo=archivo, numero_transporte="0000369009", distancia_km="12")
    _escribir_dataset(entorno, [fila])
    capa = CapaAccionesOperacionales(entorno["raiz"])
    preview = capa.previsualizar("DOCUMENTO_CORREGIR_DESTINO_OPERACIONAL", {
        "numero_guia": "No encontrado", "archivo": archivo, "direccion": "PRESIDENTE RIESCO 5903",
        "comuna": "LAS CONDES", "conservar_estado": True,
    }, actor="B1", origen="B1")
    assert preview["estado"] == "PREVIEW", preview
    monkeypatch.setattr(capa, "_regenerar_reporte", lambda: (_ for _ in ()).throw(SystemExit("corte antes de reporte")))
    with pytest.raises(SystemExit):
        capa.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    programa = ("import json, sys; from atlas_core.acciones_operacionales import CapaAccionesOperacionales as C; "
                "C._regenerar_reporte = lambda self: {'regenerado': True}; "
                "print(json.dumps(C(sys.argv[1]).ejecutar(sys.argv[2], actor='B1', origen='B1', confirmado_por='JAVIER')))")
    proceso = subprocess.run([sys.executable, "-c", programa, str(entorno["raiz"]), preview["token"]],
                             capture_output=True, text=True, timeout=30)
    assert proceso.returncode == 0, proceso.stderr
    resultado = json.loads(proceso.stdout)
    assert resultado["estado"] == "APLICADA", resultado
    nueva = CapaAccionesOperacionales(entorno["raiz"])
    assert nueva.recuperar_destino_tras_ledger(preview["token"])["idempotente"]
    vista = nueva._ctx.instantanea_documental()
    assert vista["filas"][0]["distancia_km"] == "12"
    entradas = [e for e in vista["ledger"]["aplicaciones"] if e.get("decision_id") == f"ACCION_OPERACIONAL:{preview['token']}"]
    assert len(entradas) == 1 and entradas[0]["confirmado_por"] == "JAVIER"
    assert len([a for a in nueva.auditoria() if a["token"] == preview["token"]]) == 1


def test_reporte_fallido_no_cierra_recuperacion_destino(entorno, monkeypatch):
    archivo = "mobile/prueba/original.jpg"
    _escribir_dataset(entorno, [_fila("No encontrado", archivo=archivo, numero_transporte="0000369009")])
    capa = CapaAccionesOperacionales(entorno["raiz"])
    preview = capa.previsualizar("DOCUMENTO_CORREGIR_DESTINO_OPERACIONAL", {
        "numero_guia": "No encontrado", "archivo": archivo, "direccion": "PRESIDENTE RIESCO 5903",
        "comuna": "LAS CONDES", "conservar_estado": True,
    }, actor="B1", origen="B1")
    monkeypatch.setattr(capa, "_regenerar_reporte", lambda: (_ for _ in ()).throw(SystemExit("corte")))
    with pytest.raises(SystemExit):
        capa.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    monkeypatch.setattr(CapaAccionesOperacionales, "_regenerar_reporte", lambda self: {"regenerado": False})
    nueva = CapaAccionesOperacionales(entorno["raiz"])
    fallo = nueva.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    assert fallo["estado"] == "FALLIDA" and fallo["codigo"] == "PUBLICACION_INCOMPLETA"
    assert not [a for a in nueva.auditoria() if a["token"] == preview["token"]]
    from atlas_core.acciones_operacionales import ErrorAccionOperacional
    with pytest.raises(ErrorAccionOperacional):
        nueva._ctx.instantanea_documental()
    monkeypatch.setattr(CapaAccionesOperacionales, "_regenerar_reporte", lambda self: {"regenerado": True})
    completo = nueva.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    assert completo["estado"] == "APLICADA", completo
    assert len([a for a in nueva.auditoria() if a["token"] == preview["token"]]) == 1


@pytest.mark.parametrize("ajeno", ["dataset", "ledger", "estado_operacion"])
def test_recuperacion_destino_rechaza_cambio_ajeno(entorno, monkeypatch, ajeno):
    archivo = "mobile/prueba/original.jpg"
    _escribir_dataset(entorno, [_fila("No encontrado", archivo=archivo, numero_transporte="0000369009")])
    capa = CapaAccionesOperacionales(entorno["raiz"])
    preview = capa.previsualizar("DOCUMENTO_CORREGIR_DESTINO_OPERACIONAL", {
        "numero_guia": "No encontrado", "archivo": archivo, "direccion": "PRESIDENTE RIESCO 5903",
        "comuna": "LAS CONDES", "conservar_estado": True,
    }, actor="B1", origen="B1")
    monkeypatch.setattr(capa, "_regenerar_reporte", lambda: (_ for _ in ()).throw(SystemExit("corte")))
    with pytest.raises(SystemExit):
        capa.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    if ajeno == "dataset":
        with entorno["dataset"].open("ab") as archivo_csv:
            archivo_csv.write(b" ")
    elif ajeno == "ledger":
        ruta = entorno["actual"] / "decisiones_aplicadas.json"
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        datos["aplicaciones"].append({"decision_id": "ajeno"})
        ruta.write_text(json.dumps(datos), encoding="utf-8")
    else:
        (entorno["actual"] / "estado_operacion.json").write_text('{"reporte_vigente": "otro"}', encoding="utf-8")
    antes = {p: p.read_bytes() for p in (entorno["actual"] / "decisiones_aplicadas.json", entorno["dataset"])}
    recuperacion = CapaAccionesOperacionales(entorno["raiz"]).recuperar_destino_tras_ledger(preview["token"])
    assert recuperacion["codigo"] == "PUBLICACION_INCOMPLETA"
    assert all(p.read_bytes() == contenido for p, contenido in antes.items())


def test_inspeccion_detecta_confirmacion_ajena_sin_escribir(entorno, monkeypatch):
    archivo = "mobile/prueba/original.jpg"
    _escribir_dataset(entorno, [_fila("No encontrado", archivo=archivo, numero_transporte="0000369009")])
    _sin_reporte_real(monkeypatch, [])
    capa = CapaAccionesOperacionales(entorno["raiz"])
    preview = capa.previsualizar("DOCUMENTO_CORREGIR_NUMERO_GUIA", {
        "numero_guia": "No encontrado", "numero_guia_corregido": "484180", "archivo": archivo,
    }, actor="B1", origen="B1")
    monkeypatch.setattr(capa, "_auditar", lambda *a, **k: (_ for _ in ()).throw(SystemExit("corte")))
    with pytest.raises(SystemExit):
        capa.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    ruta = entorno["actual"] / "decisiones_aplicadas.json"
    ledger = json.loads(ruta.read_text(encoding="utf-8-sig"))
    ledger["aplicaciones"][-1]["confirmado_por"] = "OTRA_PERSONA"
    ruta.write_text(json.dumps(ledger), encoding="utf-8")
    antes = ruta.read_bytes()
    inspeccion = CapaAccionesOperacionales(entorno["raiz"]).inspeccionar_publicacion_interrumpida(preview["token"])
    assert inspeccion["estado"] == "CONFLICTO"
    assert inspeccion["conflictos"] == ["IDENTIDAD_O_CONFIRMACION_NO_COINCIDE"]
    assert ruta.read_bytes() == antes


@pytest.mark.parametrize("accion", ["obra", "destino"])
def test_inspeccion_identifica_escritura_de_obra_o_destino(entorno, monkeypatch, accion):
    from tests.test_acciones_operacionales import _registrar_obra
    archivo = "mobile/prueba/original.jpg"
    _escribir_dataset(entorno, [_fila("No encontrado", archivo=archivo, numero_transporte="0000369009")])
    _sin_reporte_real(monkeypatch, [])
    capa = CapaAccionesOperacionales(entorno["raiz"])
    obra_id = _registrar_obra(capa, entorno["cliente"].cliente_id, "CONSTRUCTORA EJEMPLO LTDA")
    nombre, extras = (("DOCUMENTO_ASIGNAR_OBRA", {"obra_id": obra_id, "conservar_estado": True})
                      if accion == "obra" else ("DOCUMENTO_CORREGIR_DESTINO_OPERACIONAL", {
                          "direccion": "PRESIDENTE RIESCO 5903", "comuna": "LAS CONDES", "conservar_estado": True}))
    preview = capa.previsualizar(nombre, {"numero_guia": "No encontrado", "archivo": archivo, **extras},
                                 actor="B1", origen="B1")
    assert preview["estado"] == "PREVIEW", preview
    monkeypatch.setattr(capa, "_auditar", lambda *a, **k: (_ for _ in ()).throw(SystemExit("corte")))
    with pytest.raises(SystemExit):
        capa.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    inspeccion = CapaAccionesOperacionales(entorno["raiz"]).inspeccionar_publicacion_interrumpida(preview["token"])
    assert inspeccion["estado"] == "INTERRUMPIDA", inspeccion
    assert inspeccion["entradas_ledger"] == 1
    assert inspeccion["archivos"]["ledger_decisiones"]["estado"] == "MODIFICADO"
    assert inspeccion["archivos"]["dataset"]["estado"] == ("MODIFICADO" if accion == "obra" else "SIN_CAMBIOS")


@pytest.mark.parametrize("etapa", ["bandeja", "estado_operacion"])
def test_inspeccion_observa_corte_despues_de_bandeja_o_reporte(entorno, monkeypatch, etapa):
    import atlas_core.acciones_operacionales as acciones
    from tests.test_acciones_operacionales import _entorno_482402, ARCHIVO_482402

    _entorno_482402(entorno)
    capa = CapaAccionesOperacionales(entorno["raiz"])
    preview = capa.previsualizar("DOCUMENTO_CORREGIR_NUMERO_GUIA", {
        "numero_guia": "No encontrado", "numero_guia_corregido": "482402", "archivo": ARCHIVO_482402,
    }, actor="B1", origen="B1")
    assert preview["estado"] == "PREVIEW", preview
    if etapa == "bandeja":
        real = acciones.escribir_json_atomico
        def escribir_y_cortar(ruta, contenido):
            real(ruta, contenido)
            if ruta.name == "decisiones_pendientes.json":
                raise SystemExit("corte después de bandeja")
        monkeypatch.setattr(acciones, "escribir_json_atomico", escribir_y_cortar)
    else:
        def publicar_y_cortar():
            acciones.escribir_json_atomico(entorno["actual"] / "estado_operacion.json", {"reporte_vigente": "sintetico"})
            raise SystemExit("corte después de estado del reporte")
        monkeypatch.setattr(capa, "_regenerar_reporte", publicar_y_cortar)
    with pytest.raises(SystemExit):
        capa.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    lector = CapaAccionesOperacionales(entorno["raiz"])
    inspeccion = lector.inspeccionar_publicacion_interrumpida(preview["token"])
    assert inspeccion["estado"] == "INTERRUMPIDA", inspeccion
    assert inspeccion["archivos"][etapa]["estado"] == "MODIFICADO"
    assert inspeccion["entradas_ledger"] == 1
    assert lector.recuperar_publicacion_sin_cambios(preview["token"])["codigo"] == "PUBLICACION_INCOMPLETA"


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
    recuperacion = nueva.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
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


def test_lectura_no_espera_indefinidamente_lock_abandonado(entorno, monkeypatch):
    import time
    import atlas_core.acciones_operacionales as acciones
    from atlas_core.almacenamiento_portable import SesionOcupadaError

    monkeypatch.setattr(acciones, "_ESPERA_LECTURA_SEGUNDOS", 0.1)
    lock = entorno["actual"] / ".atlas_lock_acciones_operacionales"
    lock.write_text('{"pid": 12345}', encoding="utf-8")
    inicio = time.monotonic()
    with pytest.raises(SesionOcupadaError):
        CapaAccionesOperacionales(entorno["raiz"])._ctx.instantanea_documental()
    assert time.monotonic() - inicio < 2


def test_lector_frena_tras_terminacion_brutal_de_otro_proceso(entorno, monkeypatch):
    import os
    import subprocess
    import sys
    import time
    import atlas_core.acciones_operacionales as acciones
    from atlas_core.acciones_operacionales import ErrorAccionOperacional
    from atlas_core.almacenamiento_portable import SesionOcupadaError

    archivo = "mobile/prueba/original.jpg"
    _escribir_dataset(entorno, [_fila("No encontrado", archivo=archivo, numero_transporte="0000369009")])
    capa = CapaAccionesOperacionales(entorno["raiz"])
    preview = capa.previsualizar("DOCUMENTO_CORREGIR_NUMERO_GUIA", {
        "numero_guia": "No encontrado", "numero_guia_corregido": "484180", "archivo": archivo,
    }, actor="B1", origen="B1")
    programa = '''
import sys, time
from pathlib import Path
import atlas_core.acciones_operacionales as a
raiz = Path(sys.argv[1])
real = a.escribir_json_atomico
def escribir(ruta, contenido):
    if ruta.name == "decisiones_aplicadas.json":
        print("PAUSADO", flush=True)
        time.sleep(60)
    return real(ruta, contenido)
a.escribir_json_atomico = escribir
a.CapaAccionesOperacionales(raiz).ejecutar(sys.argv[2], actor="B1", origen="B1", confirmado_por="JAVIER")
'''
    hijo = subprocess.Popen([sys.executable, "-c", programa, str(entorno["raiz"]), preview["token"]],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert hijo.stdout.readline().strip() == "PAUSADO"
        hijo.terminate()
        hijo.wait(timeout=10)
    finally:
        if hijo.poll() is None:
            hijo.kill()
            hijo.wait(timeout=10)
    monkeypatch.setattr(acciones, "_ESPERA_LECTURA_SEGUNDOS", 0.1)
    with pytest.raises(SesionOcupadaError):
        capa._ctx.instantanea_documental()
    lock = entorno["actual"] / ".atlas_lock_acciones_operacionales"
    pasado = time.time() - 6 * 3600 - 10
    os.utime(lock, (pasado, pasado))
    with pytest.raises(ErrorAccionOperacional) as lectura:
        capa._ctx.instantanea_documental()
    assert lectura.value.codigo == "PUBLICACION_INCOMPLETA"
    assert not lock.exists()


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


def test_reproduce_lector_con_dataset_nuevo_y_ledger_anterior(entorno, monkeypatch):
    """Otro proceso espera y lee CSV y ledger bajo el mismo bloqueo."""
    import subprocess
    import sys
    from threading import Event, Thread
    import atlas_core.acciones_operacionales as acciones

    archivo = "mobile/prueba/original.jpg"
    _escribir_dataset(entorno, [_fila("No encontrado", archivo=archivo, numero_transporte="0000369009")])
    _sin_reporte_real(monkeypatch, [])
    capa = CapaAccionesOperacionales(entorno["raiz"])
    preview = capa.previsualizar("DOCUMENTO_CORREGIR_NUMERO_GUIA", {
        "numero_guia": "No encontrado", "numero_guia_corregido": "484180", "archivo": archivo,
    }, actor="B1", origen="B1")
    assert preview["estado"] == "PREVIEW"
    listo, continuar = Event(), Event()
    escribir = acciones.escribir_json_atomico

    def detener_antes_del_ledger(ruta, contenido):
        if ruta == entorno["actual"] / "decisiones_aplicadas.json":
            listo.set()
            assert continuar.wait(10)
        return escribir(ruta, contenido)

    monkeypatch.setattr(acciones, "escribir_json_atomico", detener_antes_del_ledger)
    resultados = []
    hilo = Thread(target=lambda: resultados.append(capa.ejecutar(
        preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")))
    hilo.start()
    lector = None
    try:
        assert listo.wait(10)
        programa = ("import json, sys; from atlas_core.acciones_operacionales import CapaAccionesOperacionales; "
                    "c = CapaAccionesOperacionales(sys.argv[1]); print('INICIADO', flush=True); "
                    "filas = c._ctx.filas(); vista = c._ctx.instantanea_documental(); "
                    "print(json.dumps({'filas_directas': filas, 'vista': vista}), flush=True)")
        lector = subprocess.Popen([sys.executable, "-c", programa, str(entorno["raiz"])],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert lector.stdout.readline().strip() == "INICIADO"
        with pytest.raises(subprocess.TimeoutExpired):
            lector.wait(timeout=0.3)
    finally:
        continuar.set()
        hilo.join(10)
    assert not hilo.is_alive()
    assert resultados[0]["estado"] == "APLICADA"
    salida, errores = lector.communicate(timeout=10)
    assert lector.returncode == 0, errores
    resultado_lector = json.loads(salida)
    assert resultado_lector["filas_directas"][0]["numero_guia"] == "484180"
    vista = resultado_lector["vista"]
    assert vista["filas"][0]["numero_guia"] == "484180"
    assert any(e["decision_id"] == f"ACCION_OPERACIONAL:{preview['token']}" for e in vista["ledger"]["aplicaciones"])


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
