"""Cierre funcional B1: casos 484293 y 484180 con datos sintéticos representativos."""
import json

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.b1_operador import OperadorB1
from atlas_core.decisiones_pendientes import crear_decision, generar_artefacto
from tests.test_acciones_operacionales import (
    _escribir_dataset, _fila, _filas_dataset, _registrar_obra, _sin_reporte_real, entorno,  # noqa: F401
)

ARCHIVO_369009 = "mobile/sintetico-369009/original.jpg"
OBRA = "CONSTRUCTORA IGNACIO HURTADO LTDA"
DIRECCION = "PRESIDENTE RIESCO 5903, LAS CONDES"


def _ledger(entorno):
    ruta = entorno["actual"] / "decisiones_aplicadas.json"
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.is_file() else {"aplicaciones": []}


def _bandeja(entorno):
    return json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]


def _caso_material(entorno, monkeypatch):
    hermana = _fila("484292", archivo="484292.jpeg", numero_transporte="0000369273", cliente="EBEMA SA",
                    obra_destino="EBEMA SA", descripcion_material="B HORMIGON 8MM 6MA630-420H (N)", tipo_carga="BARRAS",
                    estado_operacional="OK", estado_ruta="RUTA_CALCULADA", distancia_km="13.17")
    objetivo = _fila("484293", archivo="484293.jpeg", numero_transporte="0000369273", cliente="EBEMA SA",
                     obra_destino="EBEMA SA", descripcion_material="", tipo_carga="NO DETERMINADO",
                     estado_operacional="REQUIERE_REVISION", estado_ruta="", distancia_km="",
                     motivos_revision_documento="MATERIAL_AUSENTE")
    _escribir_dataset(entorno, [hermana, objetivo])
    _sin_reporte_real(monkeypatch, [])
    capa = CapaAccionesOperacionales(entorno["raiz"])
    return capa, OperadorB1(entorno["raiz"], capa=capa), hermana, objetivo


def _caso_obra_direccion(entorno, monkeypatch):
    fila = _fila("No encontrado", archivo=ARCHIVO_369009, numero_transporte="0000369009",
                 cliente="AGF ACEROS DE CHILE SPA", obra_destino="APOQUINDO OF.605 PISO 6 6410",
                 despachar_a_crudo="PDTE RISCO 5903 0", estado_operacional="REQUIERE_REVISION",
                 estado_ruta="REQUIERE_REVISION", distancia_km="",
                 motivos_revision_documento="OBRA_DESTINO_SIN_CORROBORAR | GUIA_AUSENTE")
    otra = _fila("500002")
    _escribir_dataset(entorno, [fila, otra])
    imagen = entorno["raiz"] / ARCHIVO_369009
    imagen.parent.mkdir(parents=True)
    imagen.write_bytes(b"original sintetico")
    _sin_reporte_real(monkeypatch, [])
    capa = CapaAccionesOperacionales(entorno["raiz"])
    _registrar_obra(capa, entorno["cliente"].cliente_id, OBRA)
    decision = crear_decision(tipo="DESTINO_NO_RESUELTO", entidad="DESTINO", archivo=ARCHIVO_369009,
        numero_guia="No encontrado", numero_transporte="0000369009", campo="despachar_a_crudo",
        valor_documental=fila["despachar_a_crudo"], valor_normalizado=fila["despachar_a_crudo"],
        identidad_resuelta=None, candidatos=(), motivos=("MULTIPLES_UBICACIONES_DISPERSAS",), evidencias=(),
        acciones_permitidas=("REGISTRAR_DIRECCION", "NO_PUEDO_DETERMINAR", "POSPONER"), contexto={})
    generar_artefacto(ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["cat"], decisiones=[decision])
    return capa, OperadorB1(entorno["raiz"], capa=capa), fila, otra


def test_material_ausente_se_corrige_por_valor_indicado(entorno, monkeypatch):
    capa, b1, hermana, objetivo = _caso_material(entorno, monkeypatch)
    antes = entorno["dataset"].read_bytes()
    preview = b1.atender("prueba", "El material de la guía 484293 es B HORMIGON 12MM 12M A630-420H (N)")
    assert preview["estado"] == "PREVIEW_PENDIENTE", preview
    assert entorno["dataset"].read_bytes() == antes
    resultado = b1.atender("prueba", "si")
    assert resultado["estado"] == "EJECUTADA", resultado
    filas = _filas_dataset(entorno)
    corregida = filas["484293.jpeg"]
    assert corregida["descripcion_material"] == "B HORMIGON 12MM 12M A630-420H (N)"
    assert corregida["tipo_carga"] == "BARRAS"
    assert "MATERIAL_AUSENTE" not in corregida["motivos_revision_documento"]
    assert filas["484292.jpeg"] == hermana
    assert corregida["estado_ruta"] == objetivo["estado_ruta"] and corregida["distancia_km"] == objetivo["distancia_km"]
    asiento = [a for a in _ledger(entorno)["aplicaciones"] if a.get("campo") == "descripcion_material"]
    assert len(asiento) == 1 and asiento[0]["confirmado_por"] == "JAVIER"
    assert capa.auditoria()[-1]["resultado"] == "APLICADA"


def test_material_no_se_copia_de_la_guia_hermana(entorno, monkeypatch):
    capa, b1, hermana, objetivo = _caso_material(entorno, monkeypatch)
    antes = entorno["dataset"].read_bytes()
    r = b1.atender("prueba", "Corrige el material de la guía 484293")
    assert r["estado"] != "EJECUTADA"
    assert "B HORMIGON 8MM" not in json.dumps(r.get("preview") or {}, ensure_ascii=False)
    assert entorno["dataset"].read_bytes() == antes


def test_obra_y_direccion_en_una_instruccion_conservan_cliente(entorno, monkeypatch):
    capa, b1, fila, otra = _caso_obra_direccion(entorno, monkeypatch)
    tarjeta = next(d for d in capa._ctx.decisiones() if d["tipo"] == "DESTINO_NO_RESUELTO")
    import atlas_core.destino_operacional as destino_modulo
    monkeypatch.setattr(destino_modulo, "calcular_ruta_operacional", lambda *a, **k: pytest.fail("no recalcular"))
    antes = entorno["dataset"].read_bytes()
    primero = b1.atender("prueba", f"@revision:{tarjeta['decision_id']} la obra correcta es {OBRA} y la dirección correcta es {DIRECCION}")
    assert primero["estado"] == "PREVIEW_PENDIENTE", primero
    assert entorno["dataset"].read_bytes() == antes
    segundo = b1.atender("prueba", "si")
    assert segundo["estado"] == "PREVIEW_PENDIENTE", segundo
    assert "PRESIDENTE RIESCO 5903" in json.dumps(segundo.get("preview"), ensure_ascii=False)
    final = b1.atender("prueba", "si")
    assert final["estado"] == "EJECUTADA", final
    corregida = _filas_dataset(entorno)[ARCHIVO_369009]
    assert corregida["obra_destino"] == OBRA
    assert corregida["cliente"] == "AGF ACEROS DE CHILE SPA"
    for campo in ("estado_operacional", "estado_ruta", "distancia_km"):
        assert corregida[campo] == fila[campo]
    assert _filas_dataset(entorno)["500002.jpeg"] == otra
    assert (entorno["raiz"] / ARCHIVO_369009).read_bytes() == b"original sintetico"
    # Sin folio legible la tarjeta sigue siendo la única identidad del documento.
    assert any(d["tipo"] == "DESTINO_NO_RESUELTO" for d in _bandeja(entorno))
    folio = b1.atender("prueba", f"@revision:{tarjeta['decision_id']} el folio correcto es 484180")
    assert folio["estado"] == "PREVIEW_PENDIENTE", folio
    assert b1.atender("prueba", "si")["estado"] == "EJECUTADA"
    assert not any(d["tipo"] == "DESTINO_NO_RESUELTO" for d in _bandeja(entorno))
    assert _filas_dataset(entorno)[ARCHIVO_369009]["numero_guia"] == "484180"


def test_rechazar_la_primera_descarta_tambien_la_segunda(entorno, monkeypatch):
    capa, b1, fila, otra = _caso_obra_direccion(entorno, monkeypatch)
    tarjeta = next(d for d in capa._ctx.decisiones() if d["tipo"] == "DESTINO_NO_RESUELTO")
    antes = entorno["dataset"].read_bytes()
    b1.atender("prueba", f"@revision:{tarjeta['decision_id']} la obra correcta es {OBRA} y la dirección correcta es {DIRECCION}")
    r = b1.atender("prueba", "no")
    assert r["estado"] != "PREVIEW_PENDIENTE", r
    assert b1.atender("prueba", "si")["estado"] != "EJECUTADA"
    assert entorno["dataset"].read_bytes() == antes


def test_corregir_otro_campo_no_cierra_tarjeta_de_destino(entorno, monkeypatch):
    capa, b1, fila, otra = _caso_obra_direccion(entorno, monkeypatch)
    tarjeta = next(d for d in capa._ctx.decisiones() if d["tipo"] == "DESTINO_NO_RESUELTO")
    b1.atender("prueba", f"@revision:{tarjeta['decision_id']} la obra correcta es {OBRA}")
    assert b1.atender("prueba", "si")["estado"] == "EJECUTADA"
    assert any(d["decision_id"] == tarjeta["decision_id"] for d in _bandeja(entorno))


# ------------------------------------------------- lenguaje natural por guía y transporte

@pytest.mark.parametrize("frase", [
    f"Guía 484180, transporte 0000369009: obra a {OBRA} y dirección a {DIRECCION}, conservando el cliente AGF ACEROS DE CHILE SPA",
    f"Corrige la guía 484180 transporte 0000369009: la obra correcta es {OBRA}; y la dirección correcta es {DIRECCION}",
])
def test_guia_y_transporte_identifican_documento_sin_folio(entorno, monkeypatch, frase):
    capa, b1, fila, otra = _caso_obra_direccion(entorno, monkeypatch)
    antes = entorno["dataset"].read_bytes()
    primero = b1.atender("prueba", frase)
    assert primero["estado"] == "PREVIEW_PENDIENTE", primero
    assert entorno["dataset"].read_bytes() == antes
    assert b1.atender("prueba", "si")["estado"] == "PREVIEW_PENDIENTE"
    assert b1.atender("prueba", "si")["estado"] == "EJECUTADA"
    corregida = _filas_dataset(entorno)[ARCHIVO_369009]
    assert corregida["obra_destino"] == OBRA and corregida["cliente"] == fila["cliente"]


def test_guia_y_transporte_material(entorno, monkeypatch):
    capa, b1, hermana, objetivo = _caso_material(entorno, monkeypatch)
    r = b1.atender("prueba", "Guía 484293, transporte 0000369273: material B HORMIGON 12MM 12M A630-420H (N)")
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert b1.atender("prueba", "si")["estado"] == "EJECUTADA"
    assert _filas_dataset(entorno)["484293.jpeg"]["descripcion_material"] == "B HORMIGON 12MM 12M A630-420H (N)"


def test_transporte_ambiguo_no_elige_documento(entorno, monkeypatch):
    capa, b1, fila, otra = _caso_obra_direccion(entorno, monkeypatch)
    _escribir_dataset(entorno, [fila, _fila("No encontrado", archivo="mobile/otra/original.jpg", numero_transporte="0000369009")])
    antes = entorno["dataset"].read_bytes()
    r = b1.atender("prueba", f"Guía 484180, transporte 0000369009: obra a {OBRA} y dirección a {DIRECCION}")
    assert r["estado"] == "ACLARACION_REQUERIDA", r
    assert entorno["dataset"].read_bytes() == antes


# ------------------------------------------------- tarjetas

def test_cierre_de_tarjeta_sobrevive_a_reconciliacion(entorno, monkeypatch):
    from atlas_core.revalidacion_documental import reconciliar_bandeja_decisiones
    capa, b1, fila, otra = _caso_obra_direccion(entorno, monkeypatch)
    tarjeta = next(d for d in capa._ctx.decisiones() if d["tipo"] == "DESTINO_NO_RESUELTO")
    b1.atender("prueba", f"@revision:{tarjeta['decision_id']} el destino correcto es {DIRECCION}")
    assert b1.atender("prueba", "si")["estado"] == "EJECUTADA"
    assert any(d["tipo"] == "DESTINO_NO_RESUELTO" for d in _bandeja(entorno))
    tarjeta = next(d for d in capa._ctx.decisiones() if d["tipo"] == "DESTINO_NO_RESUELTO")
    b1.atender("prueba", f"@revision:{tarjeta['decision_id']} el folio correcto es 484180")
    resultado = b1.atender("prueba", "si")
    assert resultado["estado"] == "EJECUTADA", resultado
    assert not any(d["tipo"] == "DESTINO_NO_RESUELTO" for d in _bandeja(entorno))
    reconciliar_bandeja_decisiones(raiz_atlas=entorno["raiz"], guias_objetivo={"484180"})
    assert not any(d["tipo"] == "DESTINO_NO_RESUELTO" for d in _bandeja(entorno))


def test_material_no_toca_tarjeta_de_otra_guia(entorno, monkeypatch):
    capa, b1, hermana, objetivo = _caso_material(entorno, monkeypatch)
    decision = crear_decision(tipo="DESTINO_NO_RESUELTO", entidad="DESTINO", archivo="484292.jpeg",
        numero_guia="484292", numero_transporte="0000369273", campo="despachar_a_crudo",
        valor_documental="GALVARINO 8501", valor_normalizado="GALVARINO 8501", identidad_resuelta=None, candidatos=(),
        motivos=("MULTIPLES_UBICACIONES_DISPERSAS",), evidencias=(),
        acciones_permitidas=("REGISTRAR_DIRECCION", "POSPONER"), contexto={})
    generar_artefacto(ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["cat"], decisiones=[decision])
    b1.atender("prueba", "El material de la guía 484293 es B HORMIGON 12MM 12M A630-420H (N)")
    assert b1.atender("prueba", "si")["estado"] == "EJECUTADA"
    assert [d["documento"]["numero_guia"] for d in _bandeja(entorno) if d["tipo"] == "DESTINO_NO_RESUELTO"] == ["484292"]


# ------------------------------------------------- cortes, recuperación y concurrencia

MATERIAL = "B HORMIGON 12MM 12M A630-420H (N)"


def _preview_material(capa):
    p = capa.previsualizar("DOCUMENTO_CORREGIR_CAMPO", {"numero_guia": "484293", "campo": "descripcion_material", "valor": MATERIAL},
                           actor="B1", origen="B1")
    assert p["estado"] == "PREVIEW", p
    return p


def _confirmar(capa, token):
    return capa.ejecutar(token, actor="B1", origen="B1", confirmado_por="JAVIER")


def _asientos(entorno, token):
    return [a for a in _ledger(entorno)["aplicaciones"] if a.get("decision_id") == f"ACCION_OPERACIONAL:{token}"]


def test_material_corte_antes_del_asiento_restaura_y_aplica(entorno, monkeypatch):
    import atlas_core.acciones_operacionales as acciones
    capa, b1, hermana, objetivo = _caso_material(entorno, monkeypatch)
    p = _preview_material(capa)
    escribir = acciones.escribir_json_atomico
    def corte(ruta, contenido):
        if ruta.name == "decisiones_aplicadas.json":
            raise SystemExit("corte antes del ledger")
        escribir(ruta, contenido)
    monkeypatch.setattr(acciones, "escribir_json_atomico", corte)
    with pytest.raises(SystemExit):
        _confirmar(capa, p["token"])
    monkeypatch.setattr(acciones, "escribir_json_atomico", escribir)
    assert _filas_dataset(entorno)["484293.jpeg"]["descripcion_material"] == MATERIAL  # el CSV alcanzó a escribirse
    with pytest.raises(acciones.ErrorAccionOperacional):
        CapaAccionesOperacionales(entorno["raiz"])._ctx.instantanea_documental()
    nueva = CapaAccionesOperacionales(entorno["raiz"])
    r = _confirmar(nueva, p["token"])
    assert r["estado"] == "APLICADA", r
    assert len(_asientos(entorno, p["token"])) == 1
    assert _filas_dataset(entorno)["484292.jpeg"] == hermana
    nueva._ctx.instantanea_documental()


def test_material_corte_tras_asiento_completa_sin_duplicar(entorno, monkeypatch):
    capa, b1, hermana, objetivo = _caso_material(entorno, monkeypatch)
    p = _preview_material(capa)
    llamado = []
    monkeypatch.setattr(capa, "_reconciliar", lambda **k: (_ for _ in ()).throw(SystemExit("corte antes de reconciliar")))
    with pytest.raises(SystemExit):
        _confirmar(capa, p["token"])
    assert len(_asientos(entorno, p["token"])) == 1
    nueva = CapaAccionesOperacionales(entorno["raiz"])
    monkeypatch.setattr(nueva, "_reconciliar", lambda **k: llamado.append(k) or {"ejecutado": True})
    r = _confirmar(nueva, p["token"])
    assert r["estado"] == "APLICADA" and r["recuperada_tras_corte"], r
    assert llamado and len(_asientos(entorno, p["token"])) == 1
    assert len([a for a in nueva.auditoria() if a["token"] == p["token"]]) == 1
    assert _confirmar(nueva, p["token"])["idempotente"]
    nueva._ctx.instantanea_documental()


@pytest.mark.parametrize("ajeno", ["otra_fila", "ledger"])
def test_material_rechaza_cambio_ajeno_tras_corte(entorno, monkeypatch, ajeno):
    import atlas_core.acciones_operacionales as acciones
    capa, b1, hermana, objetivo = _caso_material(entorno, monkeypatch)
    p = _preview_material(capa)
    escribir = acciones.escribir_json_atomico
    def corte(ruta, contenido):
        if ruta.name == "decisiones_aplicadas.json":
            raise SystemExit("corte")
        escribir(ruta, contenido)
    monkeypatch.setattr(acciones, "escribir_json_atomico", corte)
    with pytest.raises(SystemExit):
        _confirmar(capa, p["token"])
    monkeypatch.setattr(acciones, "escribir_json_atomico", escribir)
    if ajeno == "otra_fila":
        filas = _filas_dataset(entorno)
        filas["484292.jpeg"] = {**filas["484292.jpeg"], "observaciones": "CAMBIO AJENO"} if "observaciones" in filas["484292.jpeg"] else {**filas["484292.jpeg"], "tipo_carga": "AJENO"}
        _escribir_dataset(entorno, list(filas.values()))
    else:
        ruta = entorno["actual"] / "decisiones_aplicadas.json"
        ruta.write_text('{"schema_version": 1, "aplicaciones": [{"decision_id": "AJENA"}]}', encoding="utf-8")
    antes = entorno["dataset"].read_bytes()
    r = _confirmar(CapaAccionesOperacionales(entorno["raiz"]), p["token"])
    assert r["codigo"] == "PUBLICACION_INCOMPLETA", r
    assert entorno["dataset"].read_bytes() == antes


def test_material_corte_tras_reporte_real_se_reconoce(entorno, monkeypatch):
    import atlas_core.almacenamiento_portable as almacenamiento
    hermana = _fila("484292", archivo="484292.jpeg", numero_transporte="0000369273")
    objetivo = _fila("484293", archivo="484293.jpeg", numero_transporte="0000369273", descripcion_material="",
                     tipo_carga="NO DETERMINADO", motivos_revision_documento="MATERIAL_AUSENTE")
    _escribir_dataset(entorno, [hermana, objetivo])
    capa = CapaAccionesOperacionales(entorno["raiz"])
    p = _preview_material(capa)
    escribir = almacenamiento.escribir_estado_operacion
    def publicar_y_cortar(**kwargs):
        escribir(**kwargs)
        raise SystemExit("corte tras publicar")
    monkeypatch.setattr(almacenamiento, "escribir_estado_operacion", publicar_y_cortar)
    with pytest.raises(SystemExit):
        _confirmar(capa, p["token"])
    monkeypatch.setattr(almacenamiento, "escribir_estado_operacion", escribir)
    estado = entorno["actual"] / "estado_operacion.json"
    antes = estado.read_bytes()
    nueva = CapaAccionesOperacionales(entorno["raiz"])
    r = _confirmar(nueva, p["token"])
    assert r["estado"] == "APLICADA" and r["recuperada_tras_corte"], r
    assert estado.read_bytes() == antes
    vigente = json.loads(antes)["reporte_vigente"]
    assert MATERIAL in (entorno["raiz"] / vigente / "viajes.csv").read_text(encoding="utf-8-sig")


def test_reporte_de_otro_escritor_no_se_atribuye_al_token(entorno, monkeypatch):
    import atlas_core.almacenamiento_portable as almacenamiento
    capa, b1, fila, otra = _caso_obra_direccion(entorno, monkeypatch)
    monkeypatch.undo()
    capa = CapaAccionesOperacionales(entorno["raiz"])
    p = capa.previsualizar("DOCUMENTO_CORREGIR_DESTINO_OPERACIONAL", {
        "numero_guia": "No encontrado", "archivo": ARCHIVO_369009, "direccion": "PRESIDENTE RIESCO 5903",
        "comuna": "LAS CONDES", "conservar_estado": True}, actor="B1", origen="B1")
    assert p["estado"] == "PREVIEW", p
    escribir = almacenamiento.escribir_estado_operacion
    def publicar_y_cortar(**kwargs):
        escribir(**kwargs)
        raise SystemExit("corte")
    monkeypatch.setattr(almacenamiento, "escribir_estado_operacion", publicar_y_cortar)
    with pytest.raises(SystemExit):
        _confirmar(capa, p["token"])
    monkeypatch.undo()
    estado = entorno["actual"] / "estado_operacion.json"
    datos = json.loads(estado.read_text(encoding="utf-8"))
    datos["reporte_vigente"] = "reportes/otra_publicacion"
    estado.write_text(json.dumps(datos), encoding="utf-8")
    r = _confirmar(CapaAccionesOperacionales(entorno["raiz"]), p["token"])
    assert r.get("codigo") == "PUBLICACION_INCOMPLETA", r
    assert not [a for a in CapaAccionesOperacionales(entorno["raiz"]).auditoria() if a["token"] == p["token"]]


def test_dos_confirmaciones_concurrentes_aplican_una_vez(entorno, monkeypatch):
    from dataclasses import replace
    from threading import Event, Thread
    from atlas_core.acciones_operacionales import ACCIONES
    capa, b1, hermana, objetivo = _caso_material(entorno, monkeypatch)
    p = _preview_material(capa)
    original = ACCIONES[p["accion"]]
    entro, seguir = Event(), Event()
    def aplicar(*a, **k):
        entro.set()
        assert seguir.wait(10)
        return original.aplicar(*a, **k)
    monkeypatch.setitem(ACCIONES, p["accion"], replace(original, aplicar=aplicar))
    resultados = []
    hilo = Thread(target=lambda: resultados.append(_confirmar(capa, p["token"])))
    hilo.start()
    try:
        assert entro.wait(10)
        assert _confirmar(CapaAccionesOperacionales(entorno["raiz"]), p["token"])["codigo"] == "SESION_OCUPADA"
    finally:
        seguir.set()
        hilo.join(10)
    assert resultados[0]["estado"] == "APLICADA"
    assert len(_asientos(entorno, p["token"])) == 1


# ------------------------------------------------- lectores directos

def test_lector_directo_detecta_publicacion_sin_locks(entorno, monkeypatch):
    import atlas_core.acciones_operacionales as acciones
    capa, b1, hermana, objetivo = _caso_material(entorno, monkeypatch)
    p = _preview_material(capa)
    assert acciones.publicacion_documental_incompleta(entorno["raiz"]) is False
    escribir = acciones.escribir_json_atomico
    def corte(ruta, contenido):
        if ruta.name == "decisiones_aplicadas.json":
            raise SystemExit("corte")
        escribir(ruta, contenido)
    monkeypatch.setattr(acciones, "escribir_json_atomico", corte)
    with pytest.raises(SystemExit):
        _confirmar(capa, p["token"])
    monkeypatch.setattr(acciones, "escribir_json_atomico", escribir)
    locks = sorted(x.name for x in entorno["actual"].iterdir())
    assert acciones.publicacion_documental_incompleta(entorno["raiz"]) is True
    with pytest.raises(acciones.ErrorAccionOperacional) as error:
        acciones.exigir_publicacion_documental_completa(entorno["raiz"], espera_segundos=0.05)
    assert error.value.codigo == "PUBLICACION_INCOMPLETA"
    assert sorted(x.name for x in entorno["actual"].iterdir()) == locks  # sin locks ni escrituras
    assert _confirmar(CapaAccionesOperacionales(entorno["raiz"]), p["token"])["estado"] == "APLICADA"
    acciones.exigir_publicacion_documental_completa(entorno["raiz"], espera_segundos=0.05)


def test_cli_de_reporte_se_abstiene_durante_publicacion(entorno, monkeypatch):
    import subprocess
    import sys
    import atlas_core.acciones_operacionales as acciones
    capa, b1, hermana, objetivo = _caso_material(entorno, monkeypatch)
    p = _preview_material(capa)
    escribir = acciones.escribir_json_atomico
    def corte(ruta, contenido):
        if ruta.name == "decisiones_aplicadas.json":
            raise SystemExit("corte")
        escribir(ruta, contenido)
    monkeypatch.setattr(acciones, "escribir_json_atomico", corte)
    with pytest.raises(SystemExit):
        _confirmar(capa, p["token"])
    salida = entorno["raiz"] / "reportes" / "cli"
    proceso = subprocess.run([sys.executable, "generar_reporte_viajes.py", str(entorno["dataset"]), str(salida)],
                             capture_output=True, text=True, timeout=60)
    assert proceso.returncode != 0 and "documental incompleta" in proceso.stderr, proceso.stderr
    assert not salida.exists()
