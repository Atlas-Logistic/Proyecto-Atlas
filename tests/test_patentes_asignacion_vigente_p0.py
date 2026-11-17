"""P0 17/11/2026 -- patentes por asignación vigente del chofer.

Con el chofer identificado de forma inequívoca, la guía que muestra otra
patente o ninguna usa la patente asignada y confirmada del rol (tracto/camión
rígido o rampla); la lectura documental se conserva, la sustitución queda
visible (leída, aplicada, motivo) y no genera tarjetas. Decisiones humanas,
ambigüedad e identidad dudosa siempre abstienen. Sólo fixtures sintéticas.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone

from atlas_core.equipo_operacional import (
    proyectar_incidencias_equipo_por_asignacion, retirar_decisiones_vehiculo_resueltas,
    sustituciones_automaticas_patente,
)
from atlas_core.reporte_viajes import generar_reporte_viajes
from tests.test_acciones_operacionales import _fila, _vehiculo, entorno  # noqa: F401 -- fixture compartida
from tests.test_errores_documentales_aza import (  # noqa: F401 -- fixture compartida
    RUT_VARAS, _asignado, _escribir, _filas, _incidencias, _regla, _resolutor, varas,
)

RUT_ROJAS = "16000000-7"


def _fila_varas(**extra):
    return {"archivo": "x.jpeg", "numero_guia": "700001", "chofer": "LUIS VARAS", "rut_chofer": RUT_VARAS,
            "patente_tracto": "DD2494", "patente_rampla": "JB8529", "fecha": "21-10-2026", **extra}


def _ledger(e, *aplicaciones):
    ruta = e["actual"] / "decisiones_aplicadas.json"
    ledger = json.loads(ruta.read_text(encoding="utf-8"))
    ledger["aplicaciones"].extend(aplicaciones)
    ruta.write_text(json.dumps(ledger), encoding="utf-8")


def _vehiculos(e, *extra):
    ruta = e["cat"] / "vehiculos.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["vehiculos"].extend(extra)
    ruta.write_text(json.dumps(datos), encoding="utf-8")


def _correccion(archivo, campo, actor, confirmado_por=None, tipo="CORRECCION_DOCUMENTAL_OPERADOR"):
    return {"decision_id": f"d-{archivo}-{campo}-{actor}", "tipo": tipo, "accion": "CORREGIR_CAMPO", "campo": campo,
            "actor": actor, "confirmado_por": confirmado_por, "fecha": "2026-11-01T00:00:00+00:00",
            "documento": {"archivo": archivo, "numero_guia": archivo.split(".")[0]}}


def _rojas_camion(e):
    """Chofer de camión rígido único (sin rampla)."""
    catalogo = json.loads((e["cat"] / "choferes.json").read_text(encoding="utf-8"))
    catalogo["160000007"] = {"nombre": "PEDRO ROJAS", "rut": "16.000.000-7", "aliases": [], "activo": True}
    (e["cat"] / "choferes.json").write_text(json.dumps(catalogo), encoding="utf-8")
    _vehiculos(e, _asignado("XF3629", "CAMION_RIGIDO", "160000007"))


# ------------------------------------------------------------ regla: casos positivos


def test_tracto_y_rampla_correctos_no_cambian(varas):
    assert _regla(varas, _fila_varas()) == {}


def test_patente_erronea_desconocida_usa_la_asignada(varas):
    assert _regla(varas, _fila_varas(patente_tracto="ZZ9999")) == {"patente_tracto": {
        "valor_documental": "ZZ9999", "valor_operacional": "DD2494", "motivo": "PATENTE_DISTINTA"}}


def test_patente_erronea_conocida_por_el_catalogo_usa_la_asignada(varas):
    assert _regla(varas, _fila_varas(patente_rampla="JK2501")) == {"patente_rampla": {
        "valor_documental": "JK2501", "valor_operacional": "JB8529", "motivo": "PATENTE_DISTINTA"}}


def test_lectura_ocr_cercana_usa_la_asignada_con_su_motivo(varas):
    assert _regla(varas, _fila_varas(patente_tracto="DD2484"))["patente_tracto"]["motivo"] == "LECTURA_OCR_CERCANA"


def test_patentes_ausentes_se_completan_con_tracto_y_rampla(varas):
    assert _regla(varas, _fila_varas(patente_tracto="No encontrado", patente_rampla="")) == {
        "patente_tracto": {"valor_documental": "", "valor_operacional": "DD2494", "motivo": "PATENTE_AUSENTE"},
        "patente_rampla": {"valor_documental": "", "valor_operacional": "JB8529", "motivo": "PATENTE_AUSENTE"}}


def test_rampla_leida_en_el_campo_tracto_se_reubica(varas):
    assert _regla(varas, _fila_varas(patente_tracto="JB8529", patente_rampla="No encontrado")) == {
        "patente_tracto": {"valor_documental": "JB8529", "valor_operacional": "DD2494",
                           "motivo": "PATENTE_EN_CAMPO_INTERCAMBIADO"},
        "patente_rampla": {"valor_documental": "", "valor_operacional": "JB8529", "motivo": "PATENTE_AUSENTE"}}


def test_camion_unico_usa_su_camion_y_no_inventa_rampla(varas):
    _rojas_camion(varas)
    fila = _fila_varas(chofer="PEDRO ROJAS", rut_chofer=RUT_ROJAS, patente_tracto="No encontrado",
                       patente_rampla="No encontrado")
    assert _regla(varas, fila) == {"patente_tracto": {
        "valor_documental": "", "valor_operacional": "XF3629", "motivo": "PATENTE_AUSENTE"}}
    assert _regla(varas, {**fila, "patente_tracto": "XF3620"})["patente_tracto"]["valor_operacional"] == "XF3629"


# ------------------------------------------------------------ regla: abstenciones


def test_ambiguedad_de_asignacion_se_abstiene_por_rol(varas):
    _vehiculos(varas, _asignado("SB1111", "TRACTO", "142938162"))
    resultado = _regla(varas, _fila_varas(patente_tracto="No encontrado", patente_rampla="No encontrado"))
    assert "patente_tracto" not in resultado                     # dos tractos vigentes: no se elige
    assert resultado["patente_rampla"]["valor_operacional"] == "JB8529"  # la rampla sigue siendo única


def test_tracto_y_camion_rigido_vigentes_es_ambiguo(varas):
    _vehiculos(varas, _asignado("XF3629", "CAMION_RIGIDO", "142938162"))
    assert "patente_tracto" not in _regla(varas, _fila_varas(patente_tracto="No encontrado"))


def test_identidad_del_chofer_dudosa_se_abstiene(varas):
    assert _regla(varas, _fila_varas(patente_tracto="", rut_chofer="17338559-5")) == {}  # RUT ajeno
    assert _regla(varas, _fila_varas(patente_tracto="", chofer="No encontrado")) == {}
    assert _regla(varas, _fila_varas(patente_tracto="", chofer="LUIS VARGAS")) == {}


def test_asignacion_posterior_a_la_guia_no_se_aplica_hacia_atras(varas):
    assert _regla(varas, _fila_varas(patente_tracto="", fecha="30-09-2026")) == {}
    assert _regla(varas, _fila_varas(patente_tracto="", fecha="")) == {}


def test_chofer_de_asignacion_variable_se_abstiene(varas):
    catalogo = json.loads((varas["cat"] / "choferes.json").read_text(encoding="utf-8"))
    catalogo["142938162"]["asignacion_variable"] = True
    (varas["cat"] / "choferes.json").write_text(json.dumps(catalogo), encoding="utf-8")
    assert _regla(varas, _fila_varas(patente_tracto="")) == {}


# ------------------------------------------------------------ precedencia humana


def test_decision_humana_sobre_el_campo_prevalece(varas):
    fila = _fila_varas(patente_tracto="ZZ9999", patente_rampla="")
    _ledger(varas, _correccion("x.jpeg", "patente_tracto", "B1", confirmado_por="JAVIER_DESKTOP"))
    resolutor = _resolutor(varas)
    discrepancias = resolutor.discrepancias(fila)
    assert "patente_tracto" not in discrepancias                     # humano fijó el tracto
    assert discrepancias["patente_rampla"]["valor_operacional"] == "JB8529"  # otro campo: sí aplica


def test_decision_de_vehiculo_por_encargo_humano_prevalece(varas):
    _ledger(varas, _correccion("x.jpeg", "patente_rampla", "CLAUDE_CODE_POR_ENCARGO", tipo="VEHICULO_DESCONOCIDO"))
    assert "patente_rampla" not in _resolutor(varas).discrepancias(_fila_varas(patente_rampla="JK2501"))


def test_decision_automatica_no_cuenta_como_humana(varas):
    _ledger(varas, _correccion("x.jpeg", "patente_tracto", "ATLAS_AUTOMATICO", tipo="VEHICULO_DESCONOCIDO"),
            _correccion("x.jpeg", "patente_rampla", "B1"))
    discrepancias = _resolutor(varas).discrepancias(_fila_varas(patente_tracto="ZZ9999", patente_rampla=""))
    assert set(discrepancias) == {"patente_tracto", "patente_rampla"}


def test_decision_humana_posterior_descarta_la_incidencia_automatica(varas):
    filas = [{**_fila_varas(patente_rampla=""), "archivo": "x.jpeg", "numero_transporte": "1"}]
    reloj = lambda: datetime.now(timezone.utc)  # noqa: E731
    ruta = varas["cat"] / "incidencias_documentales.json"
    proyectar_incidencias_equipo_por_asignacion(filas=filas, resolutor=_resolutor(varas), ruta_incidencias=ruta,
                                                reloj=reloj)
    assert [(i.estado, i.valor_documental) for i in _incidencias(varas)] == [
        ("DETECTADA", "(campo ausente en el documento)")]
    _ledger(varas, _correccion("x.jpeg", "patente_rampla", "JAVIER_DESKTOP"))
    r = proyectar_incidencias_equipo_por_asignacion(filas=filas, resolutor=_resolutor(varas), ruta_incidencias=ruta,
                                                    reloj=reloj)
    assert r == {"incidencias_evaluadas": 0, "incidencias_descartadas": 1}
    assert [i.estado for i in _incidencias(varas)] == ["DESCARTADA"]


# ------------------------------------------------------------ visibilidad, tarjetas y reporte


def test_incidencia_registra_leida_aplicada_motivo_y_chofer_sin_duplicar(varas):
    filas = [{**_fila_varas(patente_tracto="ZZ9999"), "numero_transporte": "1", "cliente": "CLIENTE UNO SA"}]
    reloj = lambda: datetime.now(timezone.utc)  # noqa: E731
    for _ in range(2):
        proyectar_incidencias_equipo_por_asignacion(
            filas=filas, resolutor=_resolutor(varas),
            ruta_incidencias=varas["cat"] / "incidencias_documentales.json", reloj=reloj)
    [incidencia] = _incidencias(varas)
    assert (incidencia.tipo_incidencia, incidencia.campo, incidencia.valor_documental, incidencia.valor_canonico,
            incidencia.estado, incidencia.actor, incidencia.decision_id) == (
        "PATENTE_CORREGIDA_POR_ASIGNACION", "patente_tracto", "ZZ9999", "DD2494", "DETECTADA", "", "")
    assert "MOTIVO:PATENTE_DISTINTA" in incidencia.evidencia
    assert "CHOFER_IDENTIFICADO_POR_NOMBRE:LUIS VARAS" in incidencia.evidencia
    assert "ORIGEN:PROYECCION" in incidencia.evidencia and incidencia.contexto == "CLIENTE UNO SA"


def test_sustitucion_hecha_al_procesar_queda_visible_con_el_ocr_original(varas):
    metricas = {"patentes_por_asignacion_chofer": {
        "metodo": "ASIGNACION_CHOFER_VEHICULO", "resultado": "RESUELTO",
        "valor_ocr": {"patente_tracto": "JB8529", "patente_rampla": "No encontrado"},
        "valor_aplicado": {"patente_tracto": "DD2494", "patente_rampla": "JB8529"}}}
    fila = _fila_varas(metricas_procesamiento_json=json.dumps(metricas))
    assert sustituciones_automaticas_patente(fila, resolutor=_resolutor(varas)) == {
        "patente_tracto": {"valor_documental": "JB8529", "valor_operacional": "DD2494",
                           "motivo": "PATENTE_EN_CAMPO_INTERCAMBIADO", "origen": "PROCESAMIENTO",
                           "fuente": "ASIGNACION_VIGENTE"},
        "patente_rampla": {"valor_documental": "", "valor_operacional": "JB8529", "motivo": "PATENTE_AUSENTE",
                           "origen": "PROCESAMIENTO", "fuente": "ASIGNACION_VIGENTE"}}
    # Si después un humano fijó otro valor para el tracto, esa traza ya no aplica.
    _ledger(varas, _correccion("x.jpeg", "patente_tracto", "JAVIER_DESKTOP"))
    assert sustituciones_automaticas_patente({**fila, "patente_tracto": "SB1111"}, resolutor=_resolutor(varas)) == {
        "patente_rampla": {"valor_documental": "", "valor_operacional": "JB8529", "motivo": "PATENTE_AUSENTE",
                           "origen": "PROCESAMIENTO", "fuente": "ASIGNACION_VIGENTE"}}


def test_tarjeta_de_patente_resuelta_no_se_genera(varas):
    filas = {"x.jpeg": _fila_varas(patente_rampla="JK2501")}
    tarjeta = [{"tipo": "VEHICULO_DESCONOCIDO", "campo": "patente_rampla", "valor_documental": "JK2501",
                "documento": {"archivo": "x.jpeg"}}]
    assert retirar_decisiones_vehiculo_resueltas(tarjeta, filas_por_archivo=filas, resolutor=_resolutor(varas)) == []
    _ledger(varas, _correccion("x.jpeg", "patente_rampla", "JAVIER_DESKTOP"))
    # Con decisión humana sobre el campo, Atlas no la resuelve por su cuenta.
    assert retirar_decisiones_vehiculo_resueltas(tarjeta, filas_por_archivo=filas,
                                                 resolutor=_resolutor(varas)) == tarjeta


def test_reporte_usa_la_asignada_y_conserva_el_documento(varas, tmp_path):
    todas = list(_filas(varas).values())
    todas.append(_fila("700010", numero_transporte="0000700010", chofer="LUIS VARAS", rut_chofer=RUT_VARAS,
                       patente_tracto="No encontrado", patente_rampla="JK2501", fecha="21-10-2026"))
    _escribir(varas, todas)
    antes = (varas["dataset"]).read_bytes()
    generar_reporte_viajes(varas["dataset"], tmp_path / "rep", carpeta_catalogos=varas["cat"])
    assert varas["dataset"].read_bytes() == antes  # el dataset documental no se toca
    with (tmp_path / "rep" / "viajes.csv").open(encoding="utf-8-sig", newline="") as a:
        viaje = next(v for v in csv.DictReader(a, delimiter=";") if v["numero_transporte"] == "0000700010")
    assert json.loads(viaje["patentes_tracto"]) == ["DD2494"] if viaje["patentes_tracto"].startswith("[") else (
        viaje["patentes_tracto"] == "DD2494")
    assert "JB8529" in viaje["patentes_rampla"] and "JK2501" not in viaje["patentes_rampla"]
    evidencia = json.loads(viaje["evidencias_documentos"])[0]
    assert (evidencia["patente_tracto"], evidencia["patente_rampla"]) == ("No encontrado", "JK2501")


def test_reporte_no_completa_ausente_de_guias_homonimas(varas, tmp_path):
    todas = list(_filas(varas).values())
    for archivo in ("a.jpeg", "b.jpeg"):
        todas.append(_fila("No encontrado", archivo=archivo, numero_transporte="0000700020", chofer="LUIS VARAS",
                           rut_chofer=RUT_VARAS, patente_tracto="DD2494", patente_rampla="", fecha="21-10-2026"))
    _escribir(varas, todas)
    generar_reporte_viajes(varas["dataset"], tmp_path / "rep", carpeta_catalogos=varas["cat"])
    with (tmp_path / "rep" / "viajes.csv").open(encoding="utf-8-sig", newline="") as a:
        viaje = next(v for v in csv.DictReader(a, delimiter=";") if v["numero_transporte"] == "0000700020")
    assert "JB8529" not in viaje["patentes_rampla"]  # identidad por guía no única: no se completa
