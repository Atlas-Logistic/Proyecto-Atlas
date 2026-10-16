"""Destino con ruido OCR contra el catálogo CONFIRMADO.

Regresiones reales (16-10-2026):
- 482106 (AMERICAN SCREW, transporte 0000363543): "CAMINO A MELIPILLA 10B00
  SANTIAGO MAIPU" frente a la relación confirmada "CAMINO A MELIPILLA 10800
  SANTIAGO MAIPU". La B estaba DENTRO del número (la regla anterior sólo
  aceptaba una B inicial), así que la ruta se calculó con el texto corrupto y
  la entrega quedó en REVISAR.
- 482402 (ARMACERO MATCO, transporte 0000364552, sin obra leída): "SANTA
  ISABSL SB5 SANTIAGO LAMPA" frente al destino confirmado del cliente "SANTA
  ISABEL 585, LAMPA". Sin obra no se consultaba ningún destino confirmado,
  "SB5" no equivalía a 585 y la tolerancia de typo exigía un nombre de vía.

Siempre: candidato único, número y comuna confirmados como anclas; el texto
documental original se conserva.
"""
from __future__ import annotations

import json
from dataclasses import replace

from atlas_core.catalogo_destinos import (
    Destino, coincide_solo_por_numeracion_ocr, direccion_confirmada_coincide,
)
from atlas_core.procesamiento_masivo import (
    _destinos_confirmados_cliente_sin_obra, _destinos_relacion_confirmada_para_obra,
)
from atlas_core.rutas.destino_entrega import _entrega_desde_conocimiento_confirmado, destino_por_relacion_confirmada

FECHA = "2026-10-16T00:00:00+00:00"
DOC_482106 = "CAMINO A MELIPILLA 10B00 SANTIAGO MAIPU"
DOC_482402 = "SANTA ISABSL SB5 SANTIAGO LAMPA"


def _destino(destino_id, direccion, comuna, cliente_id="", **cambios) -> Destino:
    return replace(Destino(
        destino_id=destino_id, cliente_id=cliente_id, nombre_destino=direccion.split(",")[0],
        nombre_normalizado=direccion.split(",")[0], codigo_destino="", direccion=direccion, comuna=comuna,
        region="RM", pais="CHILE", latitud=-33.31, longitud=-70.73, aliases=(), estado_calidad="CONFIRMADO",
        estado_vigencia="ACTIVO", fuente="TEST", observacion="", fecha_creacion=FECHA, fecha_modificacion=FECHA,
    ), **cambios)


MELIPILLA = _destino("d-melipilla", "CAMINO A MELIPILLA 10800 SANTIAGO MAIPU", "MAIPU")
SANTA_ISABEL = _destino("d-santa-isabel", "SANTA ISABEL 585, LAMPA, CHILE", "LAMPA", "cliente-matco")
INTERIOR_700 = _destino("d-interior", "CALLE INTERIOR 700, FUNDO LA MONTANA, LAMPA, CHILE", "LAMPA",
                        "cliente-matco", aliases=("SANTA ISABEL 700",))


# --- comparador ------------------------------------------------------------


def test_482106_b_dentro_del_numero_coincide_con_comuna_y_solo_por_ocr():
    calle = MELIPILLA.direccion
    assert direccion_confirmada_coincide(calle, DOC_482106, comuna_confirmada="MAIPU")
    # Es una coincidencia SÓLO por numeración OCR: la ruta ya calculada con el
    # texto corrupto es re-anclable por la vía focal existente.
    assert coincide_solo_por_numeracion_ocr(calle, DOC_482106, comuna_confirmada="MAIPU")
    # Sin comuna confirmada (otros llamadores) el comportamiento no cambia.
    assert not direccion_confirmada_coincide(calle, DOC_482106)


def test_482402_numero_mixto_y_un_typo_sin_via_coincide_sólo_con_comuna():
    calle = "SANTA ISABEL 585"
    assert direccion_confirmada_coincide(calle, DOC_482402, comuna_confirmada="LAMPA")
    assert not direccion_confirmada_coincide(calle, DOC_482402)
    assert not direccion_confirmada_coincide(calle, DOC_482402, comuna_confirmada="COLINA")


def test_no_inventa_numeros_ni_typos_mayores():
    calle = "SANTA ISABEL 585"
    assert not direccion_confirmada_coincide(calle, "SANTA ISABSL SB6 SANTIAGO LAMPA", comuna_confirmada="LAMPA")
    assert not direccion_confirmada_coincide(calle, "SANTA ISASSL SB5 SANTIAGO LAMPA", comuna_confirmada="LAMPA")
    assert not direccion_confirmada_coincide(calle, "SANTA ISABEL 58B SANTIAGO LAMPA", comuna_confirmada="LAMPA")
    assert not direccion_confirmada_coincide(
        "CAMINO A MELIPILLA 10800", "CAMINO A MELIPILLA 10B01 MAIPU", comuna_confirmada="MAIPU")


# --- selección del destino --------------------------------------------------


def test_482106_relacion_confirmada_resuelve_destino_canonico_y_conserva_texto():
    assert destino_por_relacion_confirmada(DOC_482106, [MELIPILLA]) is MELIPILLA
    entrega = _entrega_desde_conocimiento_confirmado(DOC_482106, (), [MELIPILLA])
    assert entrega.etiqueta_geocodificada == MELIPILLA.direccion
    assert entrega.despachar_a_crudo == DOC_482106


def test_482402_destinos_del_cliente_resuelven_unico_candidato():
    assert destino_por_relacion_confirmada(DOC_482402, [SANTA_ISABEL, INTERIOR_700]) is SANTA_ISABEL
    entrega = _entrega_desde_conocimiento_confirmado(DOC_482402, (), [SANTA_ISABEL, INTERIOR_700])
    assert entrega.etiqueta_geocodificada == "SANTA ISABEL 585, LAMPA, CHILE"
    assert entrega.localidad == "LAMPA" and entrega.despachar_a_crudo == DOC_482402


def test_dos_candidatos_igual_de_fuertes_se_abstiene():
    gemelo = _destino("d-gemelo", "SANTA ISABEL 585, LAMPA, CHILE", "LAMPA", "cliente-matco",
                      latitud=-33.40, longitud=-70.80)
    assert destino_por_relacion_confirmada(DOC_482402, [SANTA_ISABEL, gemelo]) is None


# --- candidatos por cliente cuando no hay obra ------------------------------


def _catalogos(tmp_path):
    carpeta = tmp_path / "catalogos_privados"
    carpeta.mkdir()
    cliente = {
        "cliente_id": "cliente-matco", "razon_social": "ARMACERO MATCO SA", "nombre_normalizado": "ARMACERO MATCO",
        "nombre_comercial": "", "rut": "78170790-2", "aliases": [], "estado_calidad": "CONFIRMADO",
        "estado_vigencia": "ACTIVO", "fuente": "TEST", "observacion": "", "fecha_creacion": FECHA,
        "fecha_modificacion": FECHA,
    }
    destinos = []
    for d, calidad, vigencia in ((SANTA_ISABEL, "CONFIRMADO", "ACTIVO"), (INTERIOR_700, "PENDIENTE", "ACTIVO")):
        destinos.append({
            "destino_id": d.destino_id, "cliente_id": d.cliente_id, "nombre_destino": d.nombre_destino,
            "nombre_normalizado": d.nombre_normalizado, "codigo_destino": "", "direccion": d.direccion,
            "comuna": d.comuna, "region": "RM", "pais": "CHILE", "latitud": d.latitud, "longitud": d.longitud,
            "aliases": list(d.aliases), "estado_calidad": calidad, "estado_vigencia": vigencia, "fuente": "TEST",
            "observacion": "", "fecha_creacion": FECHA, "fecha_modificacion": FECHA,
        })
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": [cliente]},
        "destinos_maestros.json": {"version_formato": 1, "destinos": destinos},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
    }.items():
        (carpeta / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    return carpeta


def test_482402_sin_obra_usa_destinos_confirmados_del_cliente_sin_confirmar_obra(tmp_path):
    carpeta = _catalogos(tmp_path)
    candidatos = _destinos_confirmados_cliente_sin_obra(
        carpeta, obra_documental="No encontrado", cliente_texto="ARMACERO MATCO SA", rut_cliente="78.170.790-2",
    )
    assert [d.destino_id for d in candidatos] == ["d-santa-isabel"]  # el PENDIENTE no entra
    assert destino_por_relacion_confirmada(DOC_482402, candidatos).destino_id == "d-santa-isabel"
    # La identidad de obra sigue sin confirmarse.
    assert _destinos_relacion_confirmada_para_obra(carpeta, obra_documental="No encontrado") == []
    # Con obra leída, o sin cliente resoluble, no hay respaldo por cliente.
    assert _destinos_confirmados_cliente_sin_obra(
        carpeta, obra_documental="OBRA X", rut_cliente="78.170.790-2") == []
    assert _destinos_confirmados_cliente_sin_obra(
        carpeta, obra_documental="No encontrado", cliente_texto="OTRO", rut_cliente="") == []
