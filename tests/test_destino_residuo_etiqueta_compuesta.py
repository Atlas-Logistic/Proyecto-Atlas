"""P0 destinos contaminados (02/11/2026): etiqueta compuesta del formulario
AZA, casi siempre "RUTCHOFER", pegada al DESPACHAR A lineal.

Causa raíz: RapidOCR entrega las etiquetas compuestas sin espacios y la
lectura lineal arrastra la de la fila vecina. `_despachar_a_lineal_
contaminado` sólo reconocía la forma espaciada al inicio, así que
"RUTCHOFER PANAMERICANA NORTE 22650 SANTIAGO LAMPA" se guardaba como destino
y se ruteaba.

Trazas reales (sólo OCR, obtenido una vez en ingesta; estas pruebas no
invocan OCR ni tocan datos operacionales): 483859, 483843, 483491, 482967.
Las otras cuatro guías afectadas (482483, 482487, 482941, 482813) no
conservan traza: se usa el valor `despachar_a_crudo` real persistido.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from atlas_core.extractor import (
    _despachar_a_lineal_contaminado,
    contiene_residuo_etiqueta_compuesta,
    limpiar_residuo_etiqueta_compuesta,
)
from atlas_core.ocr import BloqueOCR
from atlas_core.rutas import destino_entrega, enriquecimiento_viaje
from atlas_core.rutas.destino_entrega import despachar_a_documental, resolver_entrega_documento


_TRAZAS = Path(__file__).parent / "fixtures" / "trazas_ocr_aza"


def _cargar_bloques(guia: str) -> tuple[list[str], list[BloqueOCR]]:
    ocr = json.loads((_TRAZAS / f"{guia}.json").read_text(encoding="utf-8"))["ocr"]
    assert ocr["estado_bloques"] == "DISPONIBLES"
    bloques = [
        BloqueOCR(
            texto=bloque["texto"],
            bounding_box=tuple(tuple(punto) for punto in bloque["bounding_box"]),
            confianza=bloque["confianza"],
        )
        for bloque in ocr["bloques"]
    ]
    return ocr["lineas"], bloques


def _solo_lineal(valor: str) -> str:
    return despachar_a_documental([], None, identificadores=SimpleNamespace(despachar_a=valor))


# ============================================================
# 1 -- trazas reales: el destino queda sin la etiqueta
# ============================================================


@pytest.mark.parametrize(
    ("guia", "esperado"),
    [
        # Residuo al inicio; el RUT del chofer (válido) pegado al final.
        ("483843", "PANAMERICANA NORTE 22650 SANTIAGO LAMPA"),
        ("483491", "PANAMERICANA NORTE 22650 SANTIAGO LAMPA"),
        ("482967", "CAMINO A MELIPILLA 10800 SANTIAGO MAIPU"),
        # RUT mal leído (9706225-1, verificador inválido): la lineal deja de
        # ser confiable y la geométrica ("ANTA ISABEL 5ESSANTIAIGOLUA") no es
        # legible: abstención (ver test_destino_ocr_corrupto_tras_residuo).
        ("483859", ""),
    ],
)
def test_trazas_reales_no_guardan_la_etiqueta_en_el_destino(guia, esperado):
    lineas, bloques = _cargar_bloques(guia)

    resultado = despachar_a_documental(lineas, bloques)

    assert resultado == esperado
    assert not contiene_residuo_etiqueta_compuesta(resultado)


def test_traza_483859_sin_bloques_se_abstiene_en_vez_de_guardar_el_rut():
    lineas, _ = _cargar_bloques("483859")

    assert despachar_a_documental(lineas) == ""


# ============================================================
# 2 -- valores reales persistidos (guías sin traza)
# ============================================================


@pytest.mark.parametrize(
    ("persistido", "esperado"),
    [
        ("CAMINO A MELIPILLA 10800 SANTIAGO MAIPU RUTCHOFER", "CAMINO A MELIPILLA 10800 SANTIAGO MAIPU"),  # 482483
        ("RUTCHOFER CAMINO LO RUIZ 2901 SANTIAGO RENCA", "CAMINO LO RUIZ 2901 SANTIAGO RENCA"),  # 482487
        ("GRAN VIA 10099 VITACURA SANTIAGO RUTCHOFER", "GRAN VIA 10099 VITACURA SANTIAGO"),  # 482941
        ("RUTCHOFER PANAMERICANA NORTE 22650 SANTIAGO LAMPA", "PANAMERICANA NORTE 22650 SANTIAGO LAMPA"),  # 483491/483843
        ("RUT CHOFER : CAMINO LO RUIZ 2901 SANTIAGO RENCA", "CAMINO LO RUIZ 2901 SANTIAGO RENCA"),
        ("DESPACHARA CAMINO LO RUIZ 2901 SANTIAGO RENCA FECHASALIDA", "CAMINO LO RUIZ 2901 SANTIAGO RENCA"),
    ],
)
def test_residuo_en_los_bordes_se_recorta_y_la_direccion_se_conserva(persistido, esperado):
    assert _solo_lineal(persistido) == esperado


def test_residuo_en_medio_se_abstiene_482813():
    # Persistido real: dirección + valor de RETIRA + RUTCHOFER + RUT mal leído.
    assert _solo_lineal("LAESTERA 222 RETRA RENE GARCIA RUTCHOFER 9701225-1") == ""


def test_solo_la_etiqueta_no_es_destino():
    assert _solo_lineal("RUTCHOFER") == ""


# ============================================================
# 3 -- negativos: calles legítimas intactas
# ============================================================


@pytest.mark.parametrize(
    "direccion",
    [
        "DESPACHAR ARTURO PRAT 123",
        "RUTA 68 KM 20 CURACAVI",
        "LOS CHOFERES 345 PUDAHUEL",
        "AVENIDA DEL TRANSPORTE 450 PUDAHUEL",
        "AV. LA FECHA 55 SANTIAGO",
        "CAMINO A MELIPILLA 10800 SANTIAGO MAIPU",
        "SANTA ISABEL 585 SANTIAGO LAMPA",
        "PASAJE HORACIO SALINAS 12 RENCA",
    ],
)
def test_calles_legitimas_no_se_tocan(direccion):
    assert not contiene_residuo_etiqueta_compuesta(direccion)
    assert limpiar_residuo_etiqueta_compuesta(direccion) == direccion
    assert _despachar_a_lineal_contaminado(direccion) is False
    assert _solo_lineal(direccion) == direccion


def test_rut_valido_pegado_sin_etiqueta_mantiene_la_limpieza_previa_464511():
    assert _solo_lineal("SANTA ISABEL 585 SANTIAGO LAMPA :15454297-3") == "SANTA ISABEL 585 SANTIAGO LAMPA"


def test_detector_lineal_reconoce_la_etiqueta_sin_espacios_en_cualquier_posicion():
    assert _despachar_a_lineal_contaminado("RUTCHOFER PANAMERICANA NORTE 22650 SANTIAGO LAMPA") is True
    assert _despachar_a_lineal_contaminado("GRAN VIA 10099 VITACURA SANTIAGO RUTCHOFER") is True
    assert _despachar_a_lineal_contaminado("LAESTERA 222 RUTCHOFER 9701225-1") is True


# ============================================================
# 4 -- el cálculo de ruta nunca recibe un destino con residuo
# ============================================================


@pytest.mark.parametrize("guia", ["483843", "483491", "482967"])
def test_ruta_de_ingesta_recibe_el_destino_limpio(monkeypatch, guia):
    lineas, bloques = _cargar_bloques(guia)
    planta = SimpleNamespace(planta_id="p1", nombre="AZA COLINA")
    recibidos: list[str] = []

    monkeypatch.setattr(
        enriquecimiento_viaje, "resolver_planta_origen",
        lambda **_: (planta, "", "CATEGORIA_DESTINO_EXTERNO", ""),
    )

    def _ruta(*, despachar_a_crudo, **_):
        recibidos.append(despachar_a_crudo)
        return SimpleNamespace(
            direccion_entrega_geocodificada=despachar_a_crudo, localidad_entrega="", region_entrega="",
            codigo_pais="", codigo_unidad="", codigo_contexto="", distancia_km="", duracion_min="",
            proveedor_ruta="", estado_ruta="", motivo_ruta="",
        )

    monkeypatch.setattr(destino_entrega, "calcular_ruta_entrega_para_viaje", _ruta)

    resultado = resolver_entrega_documento(lineas, [planta], object(), bloques=bloques)

    assert recibidos and not contiene_residuo_etiqueta_compuesta(recibidos[0])
    assert not contiene_residuo_etiqueta_compuesta(resultado["despachar_a_crudo"])


def test_483859_sin_destino_legible_no_llega_al_calculo_de_ruta(monkeypatch):
    lineas, bloques = _cargar_bloques("483859")
    planta = SimpleNamespace(planta_id="p1", nombre="AZA COLINA")
    monkeypatch.setattr(
        enriquecimiento_viaje, "resolver_planta_origen",
        lambda **_: (planta, "", "CATEGORIA_DESTINO_EXTERNO", ""),
    )
    monkeypatch.setattr(
        destino_entrega, "calcular_ruta_entrega_para_viaje",
        lambda **_: pytest.fail("no debe rutearse un destino abstenido"),
    )

    resultado = resolver_entrega_documento(lineas, [planta], object(), bloques=bloques)

    assert resultado["despachar_a_crudo"] == ""
