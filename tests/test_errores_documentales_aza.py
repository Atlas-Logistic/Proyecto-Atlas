"""Errores documentales AZA (patentes/RUT impresos distintos del equipo
vigente del chofer) y normalización de comuna de destino no oficial.
Sólo fixtures sintéticas: nunca G: ni datos productivos."""
from __future__ import annotations

import csv
import hashlib
import json

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.chofer_operacional import revalidar_motivos_choferes_operacionales_sin_ocr
from atlas_core.decisiones_pendientes import crear_decision, generar_artefacto
from atlas_core.equipo_operacional import (
    ResolutorEquipoOperacional, equipo_por_asignacion_vigente, es_discrepancia_documental,
    proyectar_incidencias_equipo_por_asignacion, retirar_decisiones_vehiculo_resueltas,
)
from atlas_core.incidencias_documentales import AlmacenIncidenciasDocumentales, EstadoIncidencia
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.reporte_viajes import generar_reporte_viajes
from tests.test_acciones_operacionales import _fila, _vehiculo, entorno  # noqa: F401 -- fixture compartida

RUT_VARAS, RUT_IMPRESO = "14293816-2", "17338559-5"
TRANSPORTE = "0000365294"


def _asignado(patente, tipo, rut, fecha="2026-10-01T00:00:00+00:00"):
    v = _vehiculo(patente, tipo)
    v["evidencias"].append({**v["evidencias"][0], "fecha": fecha, "identificador_fuente": "ASIGNACION",
                            "campos_observados": {"patente": patente, "tipo": tipo, "rut_chofer_asociado": rut}})
    return v


def _filas(e):
    with e["dataset"].open(encoding="utf-8-sig", newline="") as a:
        return {f["numero_guia"]: f for f in csv.DictReader(a, delimiter=";")}


def _escribir(e, filas):
    with e["dataset"].open("w", encoding="utf-8-sig", newline="") as a:
        w = csv.DictWriter(a, fieldnames=COLUMNAS, delimiter=";")
        w.writeheader()
        w.writerows(filas)


def _ejecutar(capa, accion, parametros):
    preview = capa.previsualizar(accion, parametros, actor="CLAUDE_CODE", origen="HUMANO")
    if preview.get("estado") != "PREVIEW":
        return preview
    return capa.ejecutar(preview["token"], actor="CLAUDE_CODE", origen="HUMANO", confirmado_por="JAVIER")


def _incidencias(e):
    return AlmacenIncidenciasDocumentales(e["cat"] / "incidencias_documentales.json").listar()


@pytest.fixture
def varas(entorno, monkeypatch):
    """Luis Varas con DD2494 + JB8529 vigentes. 482740 y 482816 (mismo
    transporte que 500003, otra guía de Varas) traen impreso el carro JC4173
    y un RUT ajeno; 500003 es la hermana que nunca debe cambiar."""
    monkeypatch.delenv("OPENROUTESERVICE_API_KEY", raising=False)
    catalogo = json.loads((entorno["cat"] / "choferes.json").read_text(encoding="utf-8"))
    catalogo["142938162"] = {"nombre": "LUIS VARAS", "rut": "14.293.816-2", "aliases": [], "activo": True}
    (entorno["cat"] / "choferes.json").write_text(json.dumps(catalogo), encoding="utf-8")
    (entorno["cat"] / "vehiculos.json").write_text(json.dumps({"version": 1, "vehiculos": [
        _vehiculo("KN5439"), _asignado("DD2494", "TRACTO", "142938162"), _asignado("JB8529", "CARRO", "142938162"),
        _vehiculo("JK2501", "CARRO")]}), encoding="utf-8")
    base = dict(numero_transporte=TRANSPORTE, chofer="LUIS VARAS", rut_chofer=RUT_IMPRESO, patente_tracto="DD2494",
                patente_rampla="JC4173", fecha="21-10-2026", motivos_revision_documento="CHOFER_SIN_CORROBORAR",
                indicador_revision="REVISAR")
    _escribir(entorno, [*_filas(entorno).values(), _fila("482740", **base), _fila("482816", **base),
                        _fila("500003", **{**base, "rut_chofer": RUT_VARAS, "motivos_revision_documento": "",
                                           "indicador_revision": "OK"})])
    tarjeta = crear_decision(
        tipo="VEHICULO_DESCONOCIDO", entidad="VEHICULO", archivo="482816.jpeg", numero_guia="482816",
        numero_transporte=TRANSPORTE, campo="patente_rampla", valor_documental="JC4173", valor_normalizado="JC4173",
        identidad_resuelta=None, candidatos=(), motivos=("SIN_VEHICULO_CONFIRMADO_COMPATIBLE",), evidencias=(),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"))
    generar_artefacto(ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["cat"],
                      decisiones=[entorno["decision"], tarjeta])
    entorno["tarjeta_vehiculo"] = tarjeta["decision_id"]
    return entorno


def _resolutor(e):
    return ResolutorEquipoOperacional(carpeta_catalogos=e["cat"], ruta_ledger=e["actual"] / "decisiones_aplicadas.json")


def _confirmar_varas(e, guia):
    capa = CapaAccionesOperacionales(e["raiz"])
    chofer = _ejecutar(capa, "DOCUMENTO_CORREGIR_CHOFER_OPERACIONAL",
                       {"numero_guia": guia, "chofer": "142938162", "confirmar_discrepancia_rut": True})
    assert chofer["estado"] == "APLICADA", chofer
    return _ejecutar(capa, "DOCUMENTO_CONFIRMAR_ERROR_DOCUMENTAL_AZA", {"numero_guia": guia})


# ------------------------------------------------------------ confirmación del administrador


def test_error_documental_aza_usa_equipo_vigente_y_conserva_lo_impreso(varas, tmp_path):
    antes = _filas(varas)
    r = _confirmar_varas(varas, "482816")
    assert r["estado"] == "APLICADA" and r["persistencia_verificada"] is True, r
    despues = _filas(varas)
    for campo in ("patente_tracto", "patente_rampla", "rut_chofer", "chofer"):
        assert despues["482816"][campo] == antes["482816"][campo]  # impreso intacto
    assert despues["500003"] == antes["500003"] and despues["482740"] == antes["482740"]  # sin propagación
    incidencias = {(i.numero_guia, i.campo): i for i in _incidencias(varas)}
    rampla, rut = incidencias[("482816", "patente_rampla")], incidencias[("482816", "rut_chofer")]
    assert (rampla.valor_documental, rampla.valor_canonico, rampla.tipo_incidencia, rampla.estado) == (
        "JC4173", "JB8529", "ERROR_DOCUMENTAL_AZA", "CONFIRMADA")
    assert (rut.valor_documental, rut.valor_canonico) == (RUT_IMPRESO, "14.293.816-2")
    assert ("482740", "patente_rampla") not in incidencias
    generar_reporte_viajes(varas["dataset"], tmp_path / "rep", carpeta_catalogos=varas["cat"])
    with (tmp_path / "rep" / "viajes.csv").open(encoding="utf-8-sig", newline="") as a:
        viaje = next(v for v in csv.DictReader(a, delimiter=";") if v["numero_transporte"] == TRANSPORTE)
    evidencia = {e["numero_guia"]: e for e in json.loads(viaje["evidencias_documentos"])}
    assert evidencia["482816"]["patente_rampla"] == "JC4173"
    assert "JB8529" in viaje["patentes_rampla"]
    # La hermana 482740 conserva su lectura sin chofer confirmado: el viaje no la homologa.
    assert "JC4173" in viaje["patentes_rampla"]


def test_tarjeta_repetitiva_no_vuelve_y_relectura_no_revierte(varas):
    _confirmar_varas(varas, "482816")
    bandeja = json.loads((varas["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]
    assert varas["tarjeta_vehiculo"] not in {d["decision_id"] for d in bandeja}
    reaparecida = [{"tipo": "VEHICULO_DESCONOCIDO", "campo": "patente_rampla", "valor_documental": "JC4173",
                    "documento": {"archivo": "482816.jpeg"}}]
    filas = {f["archivo"]: f for f in _filas(varas).values()}
    assert retirar_decisiones_vehiculo_resueltas(reaparecida, filas_por_archivo=filas, resolutor=_resolutor(varas)) == []
    # Una relectura que vuelve a marcar el motivo de chofer lo pierde en el ciclo del PULL.
    todas = list(_filas(varas).values())
    next(f for f in todas if f["numero_guia"] == "482816")["motivos_revision_documento"] = "CHOFER_SIN_CORROBORAR"
    _escribir(varas, todas)
    assert revalidar_motivos_choferes_operacionales_sin_ocr(ruta_dataset=varas["dataset"])["guias_actualizadas"] == [
        "482816"]
    assert _filas(varas)["482816"]["motivos_revision_documento"] == ""


def test_detectada_se_confirma_sin_duplicar(varas):
    almacen = AlmacenIncidenciasDocumentales(varas["cat"] / "incidencias_documentales.json")
    from datetime import datetime, timezone
    almacen.registrar(contexto="x", numero_guia="482816", numero_transporte=TRANSPORTE, campo="patente_rampla",
                      valor_documental="JC4173", valor_canonico="JB8529", tipo_incidencia="ERROR_DOCUMENTAL_AZA",
                      evidencia=(), fecha=datetime.now(timezone.utc), estado=EstadoIncidencia.DETECTADA)
    _confirmar_varas(varas, "482816")
    rampla = [i for i in _incidencias(varas) if i.numero_guia == "482816" and i.campo == "patente_rampla"]
    assert len(rampla) == 1 and rampla[0].estado == "CONFIRMADA"
    # Repetir la confirmación no escribe nada nuevo.
    capa = CapaAccionesOperacionales(varas["raiz"])
    assert capa.previsualizar("DOCUMENTO_CONFIRMAR_ERROR_DOCUMENTAL_AZA", {"numero_guia": "482816"},
                              actor="CLAUDE_CODE", origen="HUMANO")["estado"] == "SIN_CAMBIOS"


def test_sin_chofer_inequivoco_se_abstiene(varas):
    # RUT impreso válido de otra persona y sin chofer operacional: contradicción no resuelta.
    capa = CapaAccionesOperacionales(varas["raiz"])
    r = capa.previsualizar("DOCUMENTO_CONFIRMAR_ERROR_DOCUMENTAL_AZA", {"numero_guia": "482740"},
                           actor="CLAUDE_CODE", origen="HUMANO")
    assert r["estado"] == "RECHAZADA" and "inequívoca" in r["mensaje"]


def test_patente_impresa_conocida_es_contradiccion(varas):
    todas = list(_filas(varas).values())
    next(f for f in todas if f["numero_guia"] == "482816")["patente_rampla"] = "JK2501"  # carro real del catálogo
    _escribir(varas, todas)
    capa = CapaAccionesOperacionales(varas["raiz"])
    assert _ejecutar(capa, "DOCUMENTO_CORREGIR_CHOFER_OPERACIONAL", {
        "numero_guia": "482816", "chofer": "142938162", "confirmar_discrepancia_rut": True})["estado"] == "APLICADA"
    r = capa.previsualizar("DOCUMENTO_CONFIRMAR_ERROR_DOCUMENTAL_AZA", {"numero_guia": "482816"},
                           actor="CLAUDE_CODE", origen="HUMANO")
    assert r["estado"] == "RECHAZADA" and "vehículo conocido" in r["mensaje"]


# ------------------------------------------------------------ regla general conservadora


def _regla(e, fila):
    r = _resolutor(e)
    return equipo_por_asignacion_vigente(fila, choferes=r._choferes, vehiculos=r._vehiculos,
                                         choferes_operacionales=r._operacionales)


def test_regla_general_exige_identidad_y_asignacion_unica(varas):
    fila = {"archivo": "x.jpeg", "chofer": "LUIS VARAS", "rut_chofer": RUT_VARAS, "patente_tracto": "DD2494",
            "patente_rampla": "JC4173", "fecha": "21-10-2026"}
    assert _regla(varas, fila) == {"patente_rampla": {"valor_documental": "JC4173", "valor_operacional": "JB8529"}}
    assert _regla(varas, {**fila, "rut_chofer": RUT_IMPRESO}) == {}          # RUT contradictorio
    assert _regla(varas, {**fila, "chofer": "OTRO NOMBRE"}) == {}            # identidad no corroborada
    assert _regla(varas, {**fila, "patente_rampla": "No encontrado"}) == {}  # nunca completa
    assert _regla(varas, {**fila, "patente_rampla": "JK2501"}) == {}         # patente conocida
    assert _regla(varas, {**fila, "fecha": "20-09-2026"}) == {}              # antes de la asignación
    vehiculos = json.loads((varas["cat"] / "vehiculos.json").read_text(encoding="utf-8"))
    vehiculos["vehiculos"].append(_asignado("JB9999", "CARRO", "142938162"))
    (varas["cat"] / "vehiculos.json").write_text(json.dumps(vehiculos), encoding="utf-8")
    assert _regla(varas, fila) == {}                                         # dos carros vigentes


def test_lectura_ocr_cercana_no_es_incidencia(varas):
    assert es_discrepancia_documental("JC4173", "JB8529")
    assert not es_discrepancia_documental("JB8S29", "JB8529")
    assert not es_discrepancia_documental("JF9557", "JF9575")
    filas = [{"archivo": "y.jpeg", "numero_guia": "600100", "numero_transporte": "1", "chofer": "LUIS VARAS",
              "rut_chofer": RUT_VARAS, "patente_tracto": "DD2494", "patente_rampla": "JB8528", "fecha": "21-10-2026"}]
    from datetime import datetime, timezone
    proyectar_incidencias_equipo_por_asignacion(
        filas=filas, resolutor=_resolutor(varas), ruta_incidencias=varas["cat"] / "incidencias_documentales.json",
        reloj=lambda: datetime.now(timezone.utc))
    assert not _incidencias(varas)
    filas[0]["patente_rampla"] = "JC4173"
    proyectar_incidencias_equipo_por_asignacion(
        filas=filas, resolutor=_resolutor(varas), ruta_incidencias=varas["cat"] / "incidencias_documentales.json",
        reloj=lambda: datetime.now(timezone.utc))
    assert [(i.campo, i.estado) for i in _incidencias(varas)] == [("patente_rampla", "DETECTADA")]


# ------------------------------------------------------------ comuna de destino


@pytest.fixture
def temuco(entorno, monkeypatch):
    monkeypatch.delenv("OPENROUTESERVICE_API_KEY", raising=False)
    _escribir(entorno, [*_filas(entorno).values(),
                        _fila("482908", numero_transporte="0000365504", despachar_a_crudo="ANTONIO VARAS 1134, CAUTIN",
                              estado_ruta="REQUIERE_REVISION", motivo_ruta="GEOCODIFICACION_DEMASIADO_GENERICA"),
                        _fila("482909", numero_transporte="0000365504", despachar_a_crudo="ANTONIO VARAS 1134",
                              localidad_entrega="CAUTIN", estado_ruta="REQUIERE_REVISION")])
    destino = {"destino_id": "d-cautin", "cliente_id": "", "nombre_destino": "ANTONIO VARAS 1134",
               "nombre_normalizado": "ANTONIO VARAS 1134", "codigo_destino": "", "direccion": "ANTONIO VARAS 1134",
               "comuna": "CAUTIN", "region": "", "pais": "CHILE", "latitud": None, "longitud": None, "aliases": [],
               "estado_calidad": "CONFIRMADO", "estado_vigencia": "ACTIVO", "fuente": "TEST", "observacion": "",
               "fecha_creacion": "2026-10-27T21:25:40+00:00", "fecha_modificacion": "2026-10-27T21:25:40+00:00"}
    (entorno["cat"] / "destinos_maestros.json").write_text(
        json.dumps({"version_formato": 1, "destinos": [destino]}), encoding="utf-8")
    return entorno


def test_comuna_no_oficial_se_normaliza_conservando_lo_impreso(temuco):
    capa = CapaAccionesOperacionales(temuco["raiz"])
    antes = _filas(temuco)
    r = _ejecutar(capa, "DOCUMENTO_NORMALIZAR_COMUNA_DESTINO", {"numero_guia": "482908", "comuna": "Temuco"})
    assert r["estado"] == "APLICADA", r
    despues = _filas(temuco)
    assert despues["482908"]["despachar_a_crudo"] == "ANTONIO VARAS 1134, TEMUCO"
    assert despues["482909"] == antes["482909"]  # la hermana sólo con su propia corrección
    # Sin credencial de rutas no hay coordenadas ni kilómetros inventados.
    assert despues["482908"]["distancia_km"] == ""
    ledger = json.loads((temuco["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))["aplicaciones"]
    entrada = [a for a in ledger if a.get("accion") == "NORMALIZAR_COMUNA_DESTINO"][0]
    assert entrada["valor_documental"] == "ANTONIO VARAS 1134, CAUTIN"
    assert entrada["normalizacion_geografica"]["comuna_documental"] == "CAUTIN"
    destino = json.loads((temuco["cat"] / "destinos_maestros.json").read_text(encoding="utf-8"))["destinos"][0]
    assert (destino["comuna"], destino["latitud"]) == ("Temuco", None)
    inc = [i for i in _incidencias(temuco) if i.numero_guia == "482908"][0]
    assert (inc.tipo_incidencia, inc.valor_documental, inc.valor_canonico) == (
        "COMUNA_DOCUMENTAL_INCORRECTA", "CAUTIN", "TEMUCO")
    r2 = _ejecutar(capa, "DOCUMENTO_NORMALIZAR_COMUNA_DESTINO", {"numero_guia": "482909", "comuna": "Temuco"})
    assert r2["estado"] == "APLICADA", r2
    assert _filas(temuco)["482909"]["localidad_entrega"] != "CAUTIN"


@pytest.mark.parametrize("comuna", ["CAUTIN", "Araucanía", "Ciudad Inventada"])
def test_comuna_indicada_debe_ser_oficial(temuco, comuna):
    capa = CapaAccionesOperacionales(temuco["raiz"])
    r = capa.previsualizar("DOCUMENTO_NORMALIZAR_COMUNA_DESTINO", {"numero_guia": "482908", "comuna": comuna},
                           actor="CLAUDE_CODE", origen="HUMANO")
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "PARAMETRO_INVALIDO"


def test_destino_con_comuna_oficial_no_se_normaliza(temuco):
    todas = list(_filas(temuco).values())
    next(f for f in todas if f["numero_guia"] == "482908")["despachar_a_crudo"] = "ANTONIO VARAS 1134, TEMUCO"
    _escribir(temuco, todas)
    r = CapaAccionesOperacionales(temuco["raiz"]).previsualizar(
        "DOCUMENTO_NORMALIZAR_COMUNA_DESTINO", {"numero_guia": "482908", "comuna": "Temuco"},
        actor="CLAUDE_CODE", origen="HUMANO")
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "PRECONDICION_FALLIDA"


def test_registrar_direccion_rechaza_comuna_no_oficial(temuco):
    from atlas_core.aplicacion_decisiones import ErrorAplicacionDecision, aplicar_decision_obra
    decision = crear_decision(
        tipo="DESTINO_NO_RESUELTO", entidad="DESTINO", archivo="482909.jpeg", numero_guia="482909",
        numero_transporte="0000365504", campo="despachar_a_crudo", valor_documental="ANTONIO VARAS 1134",
        valor_normalizado="ANTONIO VARAS 1134", identidad_resuelta=None, candidatos=(),
        motivos=("GEOCODIFICACION_DEMASIADO_GENERICA",), evidencias=(),
        acciones_permitidas=("REGISTRAR_DIRECCION", "POSPONER"))
    generar_artefacto(ruta_dataset=temuco["dataset"], carpeta_catalogos=temuco["cat"], decisiones=[decision])
    antes = hashlib.sha256(temuco["dataset"].read_bytes()).hexdigest()
    with pytest.raises(ErrorAplicacionDecision, match="no es una comuna oficial"):
        aplicar_decision_obra(raiz_atlas=temuco["raiz"], decision_id=decision["decision_id"],
                              accion="REGISTRAR_DIRECCION", direccion_manual="ANTONIO VARAS 1134",
                              comuna_manual="CAUTIN")
    assert hashlib.sha256(temuco["dataset"].read_bytes()).hexdigest() == antes
