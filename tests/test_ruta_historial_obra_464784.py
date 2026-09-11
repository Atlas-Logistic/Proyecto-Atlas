"""Regresión explícita -- REUTILIZACIÓN DE RUTA POR HISTORIAL DE OBRA
(Codex 464784, "URUGUAY 15").

464784 (EASY RETAIL SA / CONSTRUCTORA ALTIUS SPA, planta AZA COLINA) fue
`REGISTRAR_DIRECCION` por un humano ("URUGUAY 15", sin comuna) pero el
geocodificador la deja en `GEOCODIFICACION_NUMERO_INCOMPATIBLE` para
siempre: sin comuna, "15" cae ambiguo entre La Cisterna y Puente Alto. La
MISMA obra+planta ya tiene otra guía (464491) con la MISMA calle+número y
comuna EXPLÍCITA ("URUGUAY 15 SANTIAGO LA CISTERNA"), con ruta YA
CALCULADA por un proveedor real.

`revalidar_ruta_por_historial_de_obra_sin_ocr` reutiliza esa ruta ya
persistida -- nunca geocodifica, nunca inventa un km/tiempo nuevo."""
from __future__ import annotations

import csv
import json

from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import revalidar_ruta_por_historial_de_obra_sin_ocr

OBRA = "CONSTRUCTORA ALTIUS SPA"
PLANTA = "22429e82-82d7-4f00-ae06-0d4bf2403af4"


def _fila(numero_guia, *, despachar, direccion="", localidad="", region="", estado_ruta="REQUIERE_REVISION",
          motivo_ruta="", distancia="", duracion="", proveedor="", obra=OBRA, planta=PLANTA,
          indicador="OK", estado_doc="OK", estado_op="REQUIERE_REVISION"):
    fila = {c: "" for c in COLUMNAS}
    fila.update(
        archivo=f"{numero_guia}.jpeg", numero_guia=numero_guia, numero_transporte=f"t{numero_guia}",
        cliente="EASY RETAIL SA", obra_destino=obra, planta_origen_id=planta,
        despachar_a_crudo=despachar, direccion_entrega=direccion,
        localidad_entrega=localidad, region_entrega=region,
        distancia_km=distancia, duracion_min=duracion, proveedor_ruta=proveedor,
        estado_ruta=estado_ruta, motivo_ruta=motivo_ruta,
        estado_entrega="RESUELTO" if estado_ruta == "RUTA_CALCULADA" else "",
        indicador_revision=indicador, estado_documental=estado_doc, estado_operacional=estado_op,
        resultado_atlas_ia_json=json.dumps([], ensure_ascii=False),
    )
    return fila


def _escribir(ruta, filas, *, ledger):
    with ruta.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS, delimiter=";")
        w.writeheader()
        w.writerows(filas)
    (ruta.parent / "decisiones_aplicadas.json").write_text(
        json.dumps({"schema_version": 1, "aplicaciones": ledger}), encoding="utf-8",
    )


def _leer(ruta):
    with ruta.open(newline="", encoding="utf-8-sig") as fh:
        return {f["numero_guia"]: f for f in csv.DictReader(fh, delimiter=";")}


_LEDGER_464784 = [{
    "tipo": "DESTINO_NO_RESUELTO", "accion": "REGISTRAR_DIRECCION",
    "documento": {"numero_guia": "464784"}, "direccion_manual": "URUGUAY 15",
}]

_HERMANO_LA_CISTERNA = _fila(
    "464491", despachar="URUGUAY 15 SANTIAGO LA CISTERNA",
    direccion="URUGUAY 15 SANTIAGO LA CISTERNA", localidad="La Cisterna", region="Metropolitana",
    estado_ruta="RUTA_CALCULADA", distancia="37.462", duracion="52.098333333333336",
    proveedor="openrouteservice", indicador="OK", estado_op="OK",
)


def test_reutiliza_ruta_del_hermano_de_la_misma_obra(tmp_path):
    ruta = tmp_path / "guias.csv"
    objetivo = _fila(
        "464784", despachar="URUGUAY 15", estado_ruta="REQUIERE_REVISION",
        motivo_ruta="GEOCODIFICACION_NUMERO_INCOMPATIBLE: 15 != 1545",
    )
    _escribir(ruta, [objetivo, _HERMANO_LA_CISTERNA], ledger=_LEDGER_464784)
    res = revalidar_ruta_por_historial_de_obra_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == ["464784"]
    f = _leer(ruta)["464784"]
    assert f["despachar_a_crudo"] == "URUGUAY 15"  # nunca se sobrescribe
    assert f["localidad_entrega"] == "La Cisterna"
    assert f["region_entrega"] == "Metropolitana"
    assert f["distancia_km"] == "37.462"
    assert f["duracion_min"] == "52.098333333333336"
    assert f["proveedor_ruta"] == "openrouteservice"
    assert f["estado_ruta"] == "RUTA_CALCULADA"
    assert f["motivo_ruta"] == ""
    assert f["estado_operacional"] == "OK"


def test_no_toca_guia_sin_direccion_confirmada_por_humano(tmp_path):
    ruta = tmp_path / "guias.csv"
    objetivo = _fila(
        "464784", despachar="URUGUAY 15", estado_ruta="REQUIERE_REVISION",
        motivo_ruta="GEOCODIFICACION_NUMERO_INCOMPATIBLE: 15 != 1545",
    )
    _escribir(ruta, [objetivo, _HERMANO_LA_CISTERNA], ledger=[])
    res = revalidar_ruta_por_historial_de_obra_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == []


def test_abstiene_si_hermanos_dan_comunas_distintas(tmp_path):
    ruta = tmp_path / "guias.csv"
    objetivo = _fila(
        "464784", despachar="URUGUAY 15", estado_ruta="REQUIERE_REVISION",
        motivo_ruta="GEOCODIFICACION_NUMERO_INCOMPATIBLE: 15 != 1545",
    )
    hermano_puente_alto = _fila(
        "464999", despachar="URUGUAY 15 PUENTE ALTO", direccion="URUGUAY 15 PUENTE ALTO",
        localidad="Puente Alto", region="Metropolitana", estado_ruta="RUTA_CALCULADA",
        distancia="10", duracion="20", proveedor="openrouteservice", estado_op="OK",
    )
    _escribir(ruta, [objetivo, _HERMANO_LA_CISTERNA, hermano_puente_alto], ledger=_LEDGER_464784)
    res = revalidar_ruta_por_historial_de_obra_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == []
    assert _leer(ruta)["464784"]["estado_ruta"] == "REQUIERE_REVISION"


def test_no_toca_si_no_hay_hermano_con_ruta_calculada(tmp_path):
    ruta = tmp_path / "guias.csv"
    objetivo = _fila(
        "464784", despachar="URUGUAY 15", estado_ruta="REQUIERE_REVISION",
        motivo_ruta="GEOCODIFICACION_NUMERO_INCOMPATIBLE: 15 != 1545",
    )
    _escribir(ruta, [objetivo], ledger=_LEDGER_464784)
    res = revalidar_ruta_por_historial_de_obra_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == []


def test_no_toca_hermano_de_otra_obra_o_planta(tmp_path):
    ruta = tmp_path / "guias.csv"
    objetivo = _fila(
        "464784", despachar="URUGUAY 15", estado_ruta="REQUIERE_REVISION",
        motivo_ruta="GEOCODIFICACION_NUMERO_INCOMPATIBLE: 15 != 1545",
    )
    hermano_otra_obra = _fila(
        "464492", despachar="URUGUAY 15 SANTIAGO LA CISTERNA", direccion="URUGUAY 15 SANTIAGO LA CISTERNA",
        localidad="La Cisterna", region="Metropolitana", estado_ruta="RUTA_CALCULADA",
        distancia="37.462", duracion="52.1", proveedor="openrouteservice",
        obra="OTRA OBRA DISTINTA", estado_op="OK",
    )
    _escribir(ruta, [objetivo, hermano_otra_obra], ledger=_LEDGER_464784)
    res = revalidar_ruta_por_historial_de_obra_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == []


def test_no_toca_una_guia_ya_con_ruta_calculada(tmp_path):
    ruta = tmp_path / "guias.csv"
    ya_resuelto = _fila(
        "464784", despachar="URUGUAY 15", direccion="URUGUAY 15", localidad="La Cisterna",
        region="Metropolitana", estado_ruta="RUTA_CALCULADA", distancia="99", duracion="99",
        proveedor="openrouteservice", estado_op="OK",
    )
    _escribir(ruta, [ya_resuelto, _HERMANO_LA_CISTERNA], ledger=_LEDGER_464784)
    res = revalidar_ruta_por_historial_de_obra_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == []
    assert _leer(ruta)["464784"]["distancia_km"] == "99"  # nunca se pisa una ruta ya calculada


def test_idempotente(tmp_path):
    ruta = tmp_path / "guias.csv"
    objetivo = _fila(
        "464784", despachar="URUGUAY 15", estado_ruta="REQUIERE_REVISION",
        motivo_ruta="GEOCODIFICACION_NUMERO_INCOMPATIBLE: 15 != 1545",
    )
    _escribir(ruta, [objetivo, _HERMANO_LA_CISTERNA], ledger=_LEDGER_464784)
    assert revalidar_ruta_por_historial_de_obra_sin_ocr(ruta_dataset=ruta)["guias_actualizadas"] == ["464784"]
    assert revalidar_ruta_por_historial_de_obra_sin_ocr(ruta_dataset=ruta)["guias_actualizadas"] == []
