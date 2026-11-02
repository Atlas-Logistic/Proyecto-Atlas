"""Revalidación sin OCR de destinos históricos con etiqueta compuesta
("RUTCHOFER") persistidos antes de e844ae6.

Casos reales: 483843 (inicio, ruta contaminada), 482941 (final, ruta limpia),
483859 (RUT mal leído + texto corrupto: abstención), 482813 (la traza lee
"LAESTERA 222" donde el original dice "LA ESTERA 525": sin corroboración no
se promueve), 483491/482487 (protegidos por decisión humana). Las trazas son
las fixtures OCR ya guardadas; nada invoca OCR ni red.
"""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import revalidar_destino_residuo_etiqueta_compuesta_sin_ocr
from atlas_core.trazabilidad_ocr import ruta_traza_ocr


_FIXTURES = Path(__file__).parent / "fixtures" / "trazas_ocr_aza"


def _fila(numero_guia, *, despachar, direccion="", archivo=None, ruta=True, **over):
    fila = {c: "" for c in COLUMNAS}
    fila.update(
        archivo=archivo or f"{numero_guia}.jpeg", estado_procesamiento="OK", numero_guia=numero_guia,
        despachar_a_crudo=despachar, direccion_entrega=direccion,
        planta_origen_id="p1", planta_origen_nombre="AZA COLINA",
        indicador_revision="OK", estado_documental="OK", estado_operacional="OK",
    )
    if ruta:
        fila.update(
            localidad_entrega="Lampa", region_entrega="Metropolitana", distancia_km="18.738",
            duracion_min="27.2", proveedor_ruta="openrouteservice", estado_ruta="RUTA_CALCULADA",
            estado_entrega="RESUELTO", codigo_pais="CL", codigo_unidad="13302", codigo_contexto="13",
        )
    fila.update(over)
    return fila


def _preparar(tmp_path, filas, *, aplicaciones=(), trazas=()):
    actual = tmp_path / "operacion" / "actual"
    actual.mkdir(parents=True)
    with (actual / "analisis_completo_guias.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        escritor = csv.DictWriter(fh, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)
    (actual / "decisiones_aplicadas.json").write_text(
        json.dumps({"aplicaciones": list(aplicaciones)}), encoding="utf-8")
    directorio = tmp_path / "operacion" / "trazas_ocr"
    directorio.mkdir(parents=True)
    for guia, archivo in trazas:
        shutil.copyfile(_FIXTURES / f"{guia}.json", ruta_traza_ocr(directorio, archivo))
    (tmp_path / "catalogos_privados").mkdir()
    return actual / "analisis_completo_guias.csv"


def _leer(ruta):
    with ruta.open(newline="", encoding="utf-8-sig") as fh:
        return {f["numero_guia"]: f for f in csv.DictReader(fh, delimiter=";")}


def _auditoria(fila):
    return json.loads(fila["metricas_procesamiento_json"])["recuperacion_p0"]["destino_residuo_etiqueta"]


def test_corrige_destino_y_solo_invalida_la_ruta_contaminada(tmp_path):
    dataset = _preparar(tmp_path, [
        # 483843: traza real corrobora; la ruta publicada arrastra la etiqueta.
        _fila("483843", despachar="RUTCHOFER PANAMERICANA NORTE 22650 SANTIAGO LAMPA",
              direccion="RUTCHOFER PANAMERICANA NORTE 22650 SANTIAGO LAMPA"),
        # 482941: sin traza; la geocodificación existente ya es la calle limpia.
        _fila("482941", despachar="GRAN VIA 10099 VITACURA SANTIAGO RUTCHOFER", direccion="GRAN VIA 10099"),
    ], trazas=[("483843", "483843.jpeg")])

    resultado = revalidar_destino_residuo_etiqueta_compuesta_sin_ocr(raiz_atlas=tmp_path)

    assert resultado["corregidas"] == ["483843", "482941"]
    filas = _leer(dataset)
    contaminada, limpia = filas["483843"], filas["482941"]
    assert contaminada["despachar_a_crudo"] == "PANAMERICANA NORTE 22650 SANTIAGO LAMPA"
    assert contaminada["direccion_entrega"] == contaminada["distancia_km"] == contaminada["estado_ruta"] == ""
    assert contaminada["estado_entrega"] == "NO_INTENTADO"
    assert contaminada["estado_operacional"] == "OK"  # no se recalcula el estado
    assert _auditoria(contaminada)["despachar_a_previo"] == "RUTCHOFER PANAMERICANA NORTE 22650 SANTIAGO LAMPA"
    assert _auditoria(contaminada)["ruta_invalidada"] is True
    assert limpia["despachar_a_crudo"] == "GRAN VIA 10099 VITACURA SANTIAGO"
    assert (limpia["direccion_entrega"], limpia["distancia_km"], limpia["estado_ruta"]) == (
        "GRAN VIA 10099", "18.738", "RUTA_CALCULADA")


def test_483859_texto_corrupto_se_abstiene_sin_tocar_la_traza(tmp_path):
    dataset = _preparar(tmp_path, [
        _fila("483859", despachar="RUTCHOFER ANTA ISABEL 5ESSANTIAIGOLUA 9706225-1", ruta=False),
    ], trazas=[("483859", "483859.jpeg")])
    traza = ruta_traza_ocr(tmp_path / "operacion" / "trazas_ocr", "483859.jpeg")
    antes = traza.read_bytes()

    resultado = revalidar_destino_residuo_etiqueta_compuesta_sin_ocr(raiz_atlas=tmp_path)

    assert resultado["abstenciones"] == ["483859"]
    fila = _leer(dataset)["483859"]
    assert fila["despachar_a_crudo"] == ""
    assert _auditoria(fila)["fuente"] == "SIN_DIRECCION_CONFIABLE"
    assert traza.read_bytes() == antes


def test_482813_geometria_sin_corroboracion_no_se_promueve(tmp_path):
    dataset = _preparar(tmp_path, [
        _fila("482813", archivo="482813.png", despachar="LAESTERA 222 RETRA RENE GARCIA RUTCHOFER 9701225-1", ruta=False),
    ], trazas=[("482813", "482813.png")])

    resultado = revalidar_destino_residuo_etiqueta_compuesta_sin_ocr(raiz_atlas=tmp_path)

    assert resultado["abstenciones"] == ["482813"]
    assert _leer(dataset)["482813"]["despachar_a_crudo"] == ""


def test_geometria_corroborada_por_un_destino_confirmado_se_acepta(tmp_path):
    confirmado = {"tipo": "DESTINO_OPERACIONAL_DOCUMENTO", "documento": {"archivo": "otro.jpeg", "numero_guia": "1"},
                  "destino_operacional": {"direccion": "LAESTERA 222", "comuna": "LAMPA"}}
    dataset = _preparar(tmp_path, [
        _fila("482813", archivo="482813.png", despachar="LAESTERA 222 RETRA RENE GARCIA RUTCHOFER 9701225-1", ruta=False),
    ], aplicaciones=[confirmado], trazas=[("482813", "482813.png")])

    resultado = revalidar_destino_residuo_etiqueta_compuesta_sin_ocr(raiz_atlas=tmp_path)

    assert resultado["corregidas"] == ["482813"]
    assert _leer(dataset)["482813"]["despachar_a_crudo"] == "LAESTERA 222"


def test_traza_que_contradice_el_valor_persistido_se_abstiene(tmp_path):
    dataset = _preparar(tmp_path, [
        _fila("483843", despachar="RUTCHOFER OTRA CALLE 999 SANTIAGO LAMPA",
              direccion="RUTCHOFER OTRA CALLE 999 SANTIAGO LAMPA"),
    ], trazas=[("483843", "483843.jpeg")])

    resultado = revalidar_destino_residuo_etiqueta_compuesta_sin_ocr(raiz_atlas=tmp_path)

    assert resultado["abstenciones"] == ["483843"]
    fila = _leer(dataset)["483843"]
    assert _auditoria(fila)["fuente"] == "CONTRADICCION_CON_TRAZA"
    assert fila["despachar_a_crudo"] == fila["direccion_entrega"] == fila["distancia_km"] == ""


def test_destinos_con_decision_humana_quedan_intactos(tmp_path):
    filas = [
        _fila("483491", despachar="RUTCHOFER PANAMERICANA NORTE 22650 SANTIAGO LAMPA",
              direccion="RUTCHOFER PANAMERICANA NORTE 22650 SANTIAGO LAMPA"),
        _fila("482487", despachar="CAMINO LO RUIZ 2901 SANTIAGO RENCA",
              direccion="RUTCHOFER CAMINO LO RUIZ 2901 SANTIAGO RENCA"),
    ]
    aplicaciones = [
        {"tipo": "DESTINO_OPERACIONAL_DOCUMENTO", "documento": {"archivo": "483491.jpeg", "numero_guia": "483491"},
         "destino_operacional": {"direccion": "PANAMERICANA NORTE 22650", "comuna": "LAMPA"}},
        {"tipo": "CORRECCION_DOCUMENTAL_OPERADOR", "campo": "despachar_a_crudo",
         "documento": {"archivo": "482487.jpeg", "numero_guia": "482487"}},
    ]
    dataset = _preparar(tmp_path, filas, aplicaciones=aplicaciones)
    antes = dataset.read_bytes()

    resultado = revalidar_destino_residuo_etiqueta_compuesta_sin_ocr(raiz_atlas=tmp_path)

    assert resultado["protegidas"] == ["483491", "482487"]
    assert resultado["corregidas"] == resultado["abstenciones"] == []
    assert dataset.read_bytes() == antes


def test_filas_no_afectadas_identicas_e_idempotente(tmp_path):
    limpias = [
        _fila("100001", despachar="SANTA ISABEL 585 SANTIAGO LAMPA", direccion="SANTA ISABEL 585, Lampa"),
        _fila("100002", despachar="DESPACHAR ARTURO PRAT 123", direccion="ARTURO PRAT 123"),
    ]
    dataset = _preparar(tmp_path, [
        *limpias,
        _fila("482967", despachar="RUTCHOFER CAMINO A MELIPILLA 10800 SANTIAGO MAIPU",
              direccion="CAMINO A MELIPILLA 10800 SANTIAGO MAIPU"),
    ])

    revalidar_destino_residuo_etiqueta_compuesta_sin_ocr(raiz_atlas=tmp_path)
    despues = _leer(dataset)
    for fila in limpias:
        assert despues[fila["numero_guia"]] == fila
    escrito = dataset.read_bytes()

    segunda = revalidar_destino_residuo_etiqueta_compuesta_sin_ocr(raiz_atlas=tmp_path)

    assert segunda["corregidas"] == segunda["abstenciones"] == []
    assert dataset.read_bytes() == escrito
