"""Separación de guías de un viaje Atlas agrupado, desde B1
(`agrupacion_viajes.evaluar_separacion/separar_agrupacion/revertir_separacion`
+ VIAJE_SEPARAR_GUIAS / VIAJE_REVERTIR_SEPARACION + B1). Datos sintéticos.

Invariantes que se prueban:
- un transporte AZA nunca se divide; sólo se sacan transportes COMPLETOS de
  una agrupación confirmada por un humano;
- vista previa con el viaje original y los resultantes (cargas, entregas,
  pesos, estado), sin escribir nada antes del "sí";
- ninguna guía se pierde ni se duplica; el dataset documental no cambia;
- eventos (estadías, observaciones, adicionales) se conservan o la
  operación se bloquea si su viaje resultante es ambiguo;
- registro auditado, nunca borrado, y reversible."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales, catalogo_acciones
from atlas_core.agrupacion_viajes import (
    evaluar_separacion, registrar_agrupacion, revertir_separacion, separar_agrupacion, ultima_separacion_reversible,
)
from atlas_core.b1_operador import OperadorB1, interpretar_determinista
from atlas_core.procesamiento_masivo import COLUMNAS

T1, T2, T3, T4 = "0000910101", "0000910202", "0000910303", "0000910404"


def _fila(guia, transporte, **extra):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": f"{guia}.jpeg", "estado_procesamiento": "OK", "numero_guia": guia, "numero_transporte": transporte,
        "fecha": "26-09-2026", "chofer": "LUIS REYES", "rut_chofer": "12.345.678-5", "patente_tracto": "KN5439",
        "patente_rampla": "JF6468", "cliente": "CLIENTE UNO SA", "obra_destino": "CLIENTE UNO SA",
        "despachar_a_crudo": "LA ESTERA 525", "direccion_entrega": "LA ESTERA 525", "planta_origen_id": "p-colina",
        "planta_origen_nombre": "AZA COLINA", "hora_entrada_aza": "07:18", "hora_salida_aza": "08:27",
        "peso_kg": "12000", "estado_ruta": "RUTA_CALCULADA", "distancia_km": "7.0038", "duracion_min": "15",
        "indicador_revision": "OK", "estado_documental": "OK", "estado_operacional": "OK",
    })
    fila.update(extra)
    return fila


def _filas():
    return [
        _fila("610001", T1),
        _fila("610002", T2, hora_entrada_aza="09:38", hora_salida_aza="10:55", peso_kg="16119",
              despachar_a_crudo="AV MATTA 100", direccion_entrega="AV MATTA 100", distancia_km="12.5"),
        _fila("610003", T3, hora_entrada_aza="11:00", hora_salida_aza="11:40", peso_kg="9000"),
        _fila("610004", T3, hora_entrada_aza="11:00", hora_salida_aza="11:40", peso_kg="3000"),
        _fila("610005", T4, peso_kg="5000"),
        _fila("610006", T4, peso_kg="5000"),
    ]


def _grupo(*transportes):
    return {"agrupacion_id": "g-" + "-".join(transportes), "estado": "ACTIVA", "transportes": list(transportes)}


# ------------------------------------------------------------ evaluación (pura)


def test_separa_un_transporte_de_una_agrupacion_de_dos():
    e = evaluar_separacion(guias=["610002"], filas=_filas(), agrupaciones=[_grupo(T1, T2)])
    assert not e.motivo_rechazo and not e.ya_separadas
    assert e.transportes_separados == [T2] and e.transportes_restantes == [T1]
    assert e.grupos_resultantes == [[T1], [T2]]


def test_nombrar_las_dos_guias_de_un_viaje_de_dos_transportes_deshace_la_agrupacion():
    e = evaluar_separacion(guias=["610001", "610002"], filas=_filas(), agrupaciones=[_grupo(T1, T2)])
    assert not e.motivo_rechazo
    assert e.transportes_separados == [T2] and e.transportes_restantes == [T1]  # el principal conserva el viaje


def test_agrupacion_de_tres_separa_un_transporte_completo_y_rechaza_nombrar_todos():
    filas = _filas()
    e = evaluar_separacion(guias=["610003", "610004"], filas=filas, agrupaciones=[_grupo(T1, T2, T3)])
    assert not e.motivo_rechazo
    assert e.transportes_separados == [T3] and e.transportes_restantes == [T1, T2]
    assert e.grupos_resultantes == [[T1, T2], [T3]]
    todas = evaluar_separacion(guias=["610001", "610002", "610003", "610004"], filas=filas,
                               agrupaciones=[_grupo(T1, T2, T3)])
    assert todas.codigo == "ENTIDAD_AMBIGUA" and "no se sabe" in todas.motivo_rechazo


def test_un_transporte_aza_nunca_se_divide():
    parcial = evaluar_separacion(guias=["610003"], filas=_filas(), agrupaciones=[_grupo(T1, T3)])
    assert "comparte el transporte AZA" in parcial.motivo_rechazo and "610004" in parcial.motivo_rechazo
    assert "corrige ese número" in parcial.motivo_rechazo
    # transporte sin agrupar: el viaje Atlas ES el transporte AZA
    suelto = evaluar_separacion(guias=["610005"], filas=_filas(), agrupaciones=[])
    assert "forman el transporte AZA" in suelto.motivo_rechazo and "nunca lo divide" in suelto.motivo_rechazo


def test_guia_que_ya_es_viaje_propio_no_tiene_nada_que_separar():
    e = evaluar_separacion(guias=["610002"], filas=_filas(), agrupaciones=[])
    assert e.ya_separadas and not e.motivo_rechazo and e.transportes_separados == [T2]


@pytest.mark.parametrize("guias,agrupaciones,filas_extra,fragmento,codigo", [
    (["999999"], [_grupo(T1, T2)], [], "no existe", "ENTIDAD_NO_ENCONTRADA"),
    (["610002"], [_grupo(T1, T2)], [_fila("610002", T2, archivo="otro.jpeg")], "2 documentos", "ENTIDAD_AMBIGUA"),
    (["610002"], [_grupo(T1, T2)], [_fila("", T1, archivo="sin_folio.jpeg")], "sin folio", "ENTIDAD_AMBIGUA"),
    (["610002", "610005"], [_grupo(T1, T2), _grupo(T3, T4)], [], "viajes agrupados distintos", "ENTIDAD_AMBIGUA"),
    (["610002"], [_grupo(T1, T2), _grupo(T2, T3)], [], "dos agrupaciones activas", "ESTADO_ILEGIBLE"),
    (["610002", "610005"], [_grupo(T1, T2)], [], "viaje propio", "ENTIDAD_AMBIGUA"),
])
def test_rechazos_sin_resultado_unico(guias, agrupaciones, filas_extra, fragmento, codigo):
    e = evaluar_separacion(guias=guias, filas=_filas() + filas_extra, agrupaciones=agrupaciones)
    assert fragmento in e.motivo_rechazo and e.codigo == codigo, (e.motivo_rechazo, e.codigo)


def test_guia_de_referencia_identifica_el_viaje_que_queda():
    ok = evaluar_separacion(guias=["610002"], filas=_filas(), agrupaciones=[_grupo(T1, T2)], guia_viaje="610001")
    assert not ok.motivo_rechazo
    ajena = evaluar_separacion(guias=["610002"], filas=_filas(), agrupaciones=[_grupo(T1, T2)], guia_viaje="610005")
    assert "no pertenece al viaje" in ajena.motivo_rechazo


# ------------------------------------------------------------ registro / reversión


def test_registro_separa_sin_borrar_crea_derivada_y_revierte(tmp_path):
    registrar_agrupacion(tmp_path, transportes=[T1, T2, T3], guias=["610001", "610002", "610003", "610004"],
                         actor="B1", confirmado_por="JAVIER", fuente="TEST")
    agrupacion_id = json.loads((tmp_path / "agrupaciones_viaje.json").read_text("utf-8"))["agrupaciones"][0]["agrupacion_id"]
    with pytest.raises(ValueError):  # la vista previa conocía otros transportes
        separar_agrupacion(tmp_path, agrupacion_id=agrupacion_id, transportes_esperados=[T1, T2],
                           transportes_separados=[T2], guias_restantes=[], actor="B1", confirmado_por="J", fuente="X")
    original, derivada = separar_agrupacion(
        tmp_path, agrupacion_id=agrupacion_id, transportes_esperados=[T1, T2, T3], transportes_separados=[T3],
        guias_restantes=["610001", "610002"], actor="B1", confirmado_por="JAVIER", fuente="ACCION_OPERACIONAL:t1")
    registro = json.loads((tmp_path / "agrupaciones_viaje.json").read_text("utf-8"))["agrupaciones"]
    assert [a["estado"] for a in registro] == ["SEPARADA", "ACTIVA"]
    assert registro[0]["separacion"]["transportes_separados"] == [T3]
    assert registro[0]["separacion"]["confirmado_por"] == "JAVIER"
    assert registro[1]["transportes"] == [T1, T2] and registro[1]["confirmado_por"] == "JAVIER"
    assert registro[1]["derivada_de"]["agrupacion_id"] == agrupacion_id

    reversible = ultima_separacion_reversible(tmp_path, T3)
    assert reversible["agrupacion_id"] == agrupacion_id
    revertir_separacion(tmp_path, agrupacion_id=agrupacion_id, fecha_separacion=reversible["separacion"]["fecha"],
                        actor="B1", confirmado_por="JAVIER", fuente="ACCION_OPERACIONAL:t2")
    registro = json.loads((tmp_path / "agrupaciones_viaje.json").read_text("utf-8"))["agrupaciones"]
    assert [a["estado"] for a in registro] == ["ACTIVA", "REVERTIDA"]
    assert registro[0]["historial"][0]["separacion"]["fuente"] == "ACCION_OPERACIONAL:t1"
    assert ultima_separacion_reversible(tmp_path, T3) is None


def test_no_se_revierte_si_el_resultado_cambio(tmp_path):
    registrar_agrupacion(tmp_path, transportes=[T1, T2], guias=[], actor="B1", confirmado_por="J", fuente="T")
    agrupacion_id = json.loads((tmp_path / "agrupaciones_viaje.json").read_text("utf-8"))["agrupaciones"][0]["agrupacion_id"]
    separar_agrupacion(tmp_path, agrupacion_id=agrupacion_id, transportes_esperados=[T1, T2],
                       transportes_separados=[T2], guias_restantes=[], actor="B1", confirmado_por="J", fuente="X")
    registrar_agrupacion(tmp_path, transportes=[T2, T3], guias=[], actor="B1", confirmado_por="J", fuente="T")
    assert ultima_separacion_reversible(tmp_path, T2) is None


# ------------------------------------------------------------ capa + B1 (de punta a punta)


@pytest.fixture
def raiz(tmp_path):
    raiz = tmp_path / "AtlasCopia"
    cat, actual = raiz / "catalogos_privados", raiz / "operacion" / "actual"
    cat.mkdir(parents=True)
    actual.mkdir(parents=True)
    (cat / "choferes.json").write_text(json.dumps(
        {"123456785": {"nombre": "LUIS REYES", "rut": "12.345.678-5", "aliases": [], "activo": True}}), encoding="utf-8")
    for nombre, contenido in {"vehiculos.json": {"version": 1, "vehiculos": []}, "empresas.json": {},
                              "clientes.json": {"version_formato": 1, "clientes": []},
                              "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
                              "destinos_maestros.json": {"version_formato": 1, "destinos": []},
                              "plantas.json": {"plantas": []}}.items():
        (cat / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    with (actual / "analisis_completo_guias.csv").open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(_filas())
    return raiz


def _actual(raiz: Path) -> Path:
    return raiz / "operacion" / "actual"


def _hash(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _viajes(raiz: Path) -> dict[str, dict]:
    estado = json.loads((_actual(raiz) / "estado_operacion.json").read_text(encoding="utf-8"))
    ruta = Path(estado["reporte_vigente"])
    ruta = ruta if ruta.is_absolute() else raiz / ruta
    filas = list(csv.DictReader((ruta / "viajes.csv").open(encoding="utf-8-sig", newline=""), delimiter=";"))
    return {f["numero_transporte"]: f for f in filas}


def _agrupar(b1: OperadorB1, *guias: str) -> None:
    r = b1.atender("agrupar", f"Las guías {' y '.join(guias)} pertenecen al mismo viaje")
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert b1.atender("agrupar", "sí")["estado"] == "EJECUTADA"


def _registro(raiz: Path) -> list[dict]:
    return json.loads((_actual(raiz) / "agrupaciones_viaje.json").read_text(encoding="utf-8"))["agrupaciones"]


def _eventos(raiz: Path, *eventos: dict) -> None:
    (_actual(raiz) / "eventos_operacionales.json").write_text(json.dumps(
        {"schema_version": 1, "revision": 1, "eventos": list(eventos), "revisiones_incidencias": []}),
        encoding="utf-8")


def _evento(transporte: str, guias: list[str], tipo="TIENE_ESTADIA", nota="ESTADIA 2 HORAS") -> dict:
    return {"evento_id": f"e-{transporte}-{'-'.join(guias)}", "tipo_evento": tipo, "numero_transporte": transporte,
            "numeros_guia": guias, "nota": nota, "estado": "ACTIVO", "vinculo_completo": True}


def test_b1_separa_muestra_original_y_resultantes_y_recalcula_el_reporte(raiz):
    b1 = OperadorB1(raiz)
    _agrupar(b1, "610001", "610002")
    assert sorted(_viajes(raiz)) == [T1, T3, T4]
    dataset = _hash(_actual(raiz) / "analisis_completo_guias.csv")
    registro_antes = _hash(_actual(raiz) / "agrupaciones_viaje.json")

    r = b1.atender("c", "Separa la guía 610002 del viaje")
    assert r["estado"] == "PREVIEW_PENDIENTE" and r["accion"] == "VIAJE_SEPARAR_GUIAS", r
    mensaje = r["mensaje"]
    assert f"VIAJE ORIGINAL: viaje {T1} [transporte {T1}: guía 610001" in mensaje
    assert f"transporte {T2}: guía 610002" in mensaje and "RESULTARÁN 2 VIAJES" in mensaje
    assert "empresa MBT" in mensaje and "deshaz la separación" in mensaje
    propuesto = r["preview"]["valor_propuesto"]
    assert [v["transportes_aza"] for v in propuesto["viajes"]] == [[T1], [T2]]
    assert [v["peso_total_kg"] for v in propuesto["viajes"]] == ["12000", "16119"]
    assert r["preview"]["valor_actual"]["viaje"]["peso_total_kg"] == "28119"
    assert _hash(_actual(raiz) / "agrupaciones_viaje.json") == registro_antes  # nada escrito antes del "sí"

    e = b1.atender("c", "sí")
    assert e["estado"] == "EJECUTADA", e
    assert e["resultado"]["revalidacion"]["reporte"]["regenerado"] is True
    registro = _registro(raiz)
    assert [a["estado"] for a in registro] == ["SEPARADA"]
    assert registro[0]["separacion"]["confirmado_por"] == "JAVIER"
    assert registro[0]["separacion"]["fuente"].startswith("ACCION_OPERACIONAL:")
    viajes = _viajes(raiz)
    assert sorted(viajes) == [T1, T2, T3, T4]
    assert viajes[T1]["numeros_guia"] == "610001" and viajes[T2]["numeros_guia"] == "610002"
    assert viajes[T1]["transportes_aza"] == T1 and viajes[T2]["transportes_aza"] == T2
    # ninguna guía perdida ni duplicada; dataset documental intacto
    guias_reporte = sorted(g for v in viajes.values() for g in v["numeros_guia"].split(" | "))
    assert guias_reporte == sorted(f["numero_guia"] for f in _filas())
    assert _hash(_actual(raiz) / "analisis_completo_guias.csv") == dataset
    auditoria = b1.capa.auditoria()
    assert [a["accion"] for a in auditoria] == ["VIAJE_AGRUPAR_GUIAS", "VIAJE_SEPARAR_GUIAS"]
    assert auditoria[-1]["confirmado_por"] == "JAVIER"

    again = b1.atender("c", "Separa la guía 610002 del viaje")
    assert again["estado"] == "SIN_CAMBIOS" and "ya forma un viaje propio" in again["mensaje"]

    # reversión explícita
    r = b1.atender("c", "Deshaz la separación de la guía 610002")
    assert r["estado"] == "PREVIEW_PENDIENTE" and r["accion"] == "VIAJE_REVERTIR_SEPARACION", r
    assert f"VIAJE RESULTANTE: viaje {T1}" in r["mensaje"]
    assert b1.atender("c", "sí")["estado"] == "EJECUTADA"
    assert [a["estado"] for a in _registro(raiz)] == ["ACTIVA"]
    viajes = _viajes(raiz)
    assert sorted(viajes) == [T1, T3, T4] and viajes[T1]["numeros_guia"] == "610001 | 610002"
    assert _hash(_actual(raiz) / "analisis_completo_guias.csv") == dataset


def test_b1_separa_un_transporte_de_un_viaje_de_tres_y_los_restantes_siguen_juntos(raiz):
    b1 = OperadorB1(raiz)
    _agrupar(b1, "610001", "610002", "610003")
    r = b1.atender("c", "Saca las guías 610003 y 610004 del viaje de la guía 610001")
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert [v["transportes_aza"] for v in r["preview"]["valor_propuesto"]["viajes"]] == [[T1, T2], [T3]]
    assert b1.atender("c", "sí")["estado"] == "EJECUTADA"
    assert [a["estado"] for a in _registro(raiz)] == ["SEPARADA", "ACTIVA"]
    viajes = _viajes(raiz)
    assert viajes[T1]["transportes_aza"] == f"{T1} | {T2}" and viajes[T3]["numeros_guia"] == "610003 | 610004"
    # revertir vuelve a los tres juntos
    assert b1.atender("c", "Revierte la separación de la guía 610004")["estado"] == "PREVIEW_PENDIENTE"
    assert b1.atender("c", "sí")["estado"] == "EJECUTADA"
    assert _viajes(raiz)[T1]["transportes_aza"] == f"{T1} | {T2} | {T3}"


def test_b1_rechaza_dividir_un_transporte_y_no_escribe(raiz):
    b1 = OperadorB1(raiz)
    _agrupar(b1, "610001", "610003")
    antes = _hash(_actual(raiz) / "agrupaciones_viaje.json")
    r = b1.atender("c", "Separa la guía 610003 del viaje")
    assert r["estado"] == "RECHAZADA" and "un transporte AZA no se divide" in r["mensaje"], r
    assert _hash(_actual(raiz) / "agrupaciones_viaje.json") == antes
    assert b1.atender("c", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"


def test_evento_del_viaje_agrupado_bloquea_si_quedaria_repartido(raiz):
    b1 = OperadorB1(raiz)
    _agrupar(b1, "610001", "610002")
    _eventos(raiz, _evento(T1, ["610001", "610002"]))
    antes = _hash(_actual(raiz) / "agrupaciones_viaje.json")
    r = b1.atender("c", "Separa la guía 610002 del viaje")
    assert r["estado"] == "RECHAZADA", r
    assert "quedarían en viajes distintos" in r["mensaje"] and "ESTADIA 2 HORAS" in r["mensaje"]
    assert _hash(_actual(raiz) / "agrupaciones_viaje.json") == antes


def test_evento_que_cuelga_del_transporte_equivocado_bloquea(raiz):
    b1 = OperadorB1(raiz)
    _agrupar(b1, "610001", "610002")
    _eventos(raiz, _evento(T1, ["610002"], tipo="OBSERVACION_OPERACIONAL", nota="ESTE VIAJE TIENE ADICIONAL DE $30.000"))
    r = b1.atender("c", "Separa la guía 610002 del viaje")
    assert r["estado"] == "RECHAZADA" and "requiere reasignarla" in r["mensaje"], r


def test_evento_propio_del_transporte_que_queda_se_conserva_sin_tocarlo(raiz):
    b1 = OperadorB1(raiz)
    _agrupar(b1, "610001", "610002")
    _eventos(raiz, _evento(T1, ["610001"]))
    eventos_antes = _hash(_actual(raiz) / "eventos_operacionales.json")
    r = b1.atender("c", "La guía 610002 no es del mismo viaje que la guía 610001")
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert f"Se conservan sin cambios: tiene estadia del transporte {T1} (guía 610001)" in r["mensaje"]
    assert b1.atender("c", "sí")["estado"] == "EJECUTADA"
    assert _hash(_actual(raiz) / "eventos_operacionales.json") == eventos_antes


def test_confirmacion_sobre_un_registro_que_cambio_no_ejecuta(raiz):
    b1 = OperadorB1(raiz)
    _agrupar(b1, "610001", "610002")
    r = b1.atender("c", "Separa la guía 610002 del viaje")
    assert r["estado"] == "PREVIEW_PENDIENTE"
    agrupacion_id = _registro(raiz)[0]["agrupacion_id"]
    separar_agrupacion(_actual(raiz), agrupacion_id=agrupacion_id, transportes_esperados=[T1, T2],
                       transportes_separados=[T2], guias_restantes=[], actor="OTRO", confirmado_por="OTRO",
                       fuente="CONCURRENTE")
    e = b1.atender("c", "sí")
    assert e["estado"] != "EJECUTADA", e
    assert [a["accion"] for a in b1.capa.auditoria()] == ["VIAJE_AGRUPAR_GUIAS"]


def test_capa_exige_confirmacion_humana(raiz):
    b1 = OperadorB1(raiz)
    _agrupar(b1, "610001", "610002")
    capa = CapaAccionesOperacionales(raiz)
    preview = capa.previsualizar("VIAJE_SEPARAR_GUIAS", {"guias": ["610002"]}, actor="B1", origen="B1")
    resultado = capa.ejecutar(preview["token"], actor="B1", confirmado_por="ATLAS_AUTOMATICO", origen="B1")
    assert resultado["estado"] == "RECHAZADA" and resultado["codigo"] == "CONFIRMACION_REQUERIDA", resultado
    assert [a["estado"] for a in _registro(raiz)] == ["ACTIVA"]


def test_frases_y_catalogo():
    i = interpretar_determinista("Separa las guías 610003 y 610004 del viaje de la guía 610001")
    assert i.accion == "VIAJE_SEPARAR_GUIAS" and i.parametros == {"guias": ["610003", "610004"], "guia_viaje": "610001"}
    i = interpretar_determinista("Las guías 610001 y 610002 no son del mismo viaje")
    assert i.accion == "VIAJE_SEPARAR_GUIAS" and i.parametros == {"guias": ["610002"], "guia_viaje": "610001"}
    tres = interpretar_determinista("Las guías 610001, 610002 y 610003 no son del mismo viaje")
    assert tres is None or tres.accion != "VIAJE_SEPARAR_GUIAS"  # con más de dos no hay certeza
    i = interpretar_determinista("Deshaz la separación de la guía 610002")
    assert i.accion == "VIAJE_REVERTIR_SEPARACION" and i.parametros == {"numero_guia": "610002"}
    # agrupar no cambia
    assert interpretar_determinista("Las guías 610001 y 610002 pertenecen al mismo viaje").accion == "VIAJE_AGRUPAR_GUIAS"
    acciones = {a["accion"]: a for a in catalogo_acciones()}
    assert acciones["VIAJE_SEPARAR_GUIAS"]["riesgo"] == "OPERACIONAL_REVERSIBLE"
    assert acciones["VIAJE_REVERTIR_SEPARACION"]["riesgo"] == "OPERACIONAL_REVERSIBLE"
