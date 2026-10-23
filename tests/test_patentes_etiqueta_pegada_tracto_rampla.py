"""Confusión tracto/rampla por etiqueta CARRO pegada al valor del tracto.

Casos reales (RapidOCR, 21-22/10/2026): 482953 José Lazcano
("ND6443CARRO:JB6878") y 482772/482902 Luis Reyes ("KN5439CARRO:JF6468").
El OCR leyó bien ambas patentes; el extractor no reconocía la etiqueta CARRO
pegada al valor anterior (`\\b` exige borde de palabra entre "3" y "C"), el
valor del tracto quedaba como token de 11 caracteres y el carro se tomaba como
tracto. Las coordenadas son las de las lecturas reales.

Además, con el chofer identificado y su tracto y carro vigentes confirmados,
una patente leída en el campo equivocado vuelve a su campo -- sólo con
coincidencia exacta, sin completar campos no leídos ni intercambiar ante
evidencia contradictoria.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from atlas_core.catalogo_vehiculos import TipoVehiculo, asociar_chofer_a_vehiculo_confirmado, cargar_catalogo_vehiculos
from atlas_core.decisiones_pendientes import clasificar_patentes_por_asignacion_vigente
from atlas_core.extractor import _extraer_patentes_geometrico, extraer_datos
from atlas_core.ocr import BloqueOCR
from atlas_core.procesamiento_masivo import procesar_archivo
from tests.test_motor_evidencia_vehiculos import _confirmar
from tests.test_patentes_p4 import _bloque, _datos_lineales, _preparar_mocks

REYES, LAZCANO, OTRO = "7814310-K", "10833150-K", "18091588-5"


def _caja(texto, puntos):
    return BloqueOCR(texto=texto, bounding_box=tuple(tuple(p) for p in puntos), confianza=0.95)


def _zona_482772():
    return [
        _caja("RETIRA", [[537, 1102], [588, 1102], [588, 1120], [537, 1120]]),
        _caja("LUIS REYES", [[605, 1103], [699, 1103], [699, 1120], [605, 1120]]),
        _caja("PATENTE", [[538, 1119], [599, 1119], [599, 1133], [538, 1133]]),
        _caja("KN5439CARRO:JF6468", [[596, 1118], [773, 1116], [774, 1133], [596, 1135]]),
        _caja("LLEGADA", [[539, 1145], [603, 1145], [603, 1162], [539, 1162]]),
    ]


def _zona_482953(valor="ND6443CARRO:JB6878"):
    return [
        _caja("RETIRA", [[1788, 2963], [1946, 2977], [1942, 3028], [1784, 3013]]),
        _caja("PATENTE", [[1786, 3007], [1981, 3026], [1977, 3076], [1782, 3057]]),
        _caja(valor, [[2004, 3028], [2539, 3086], [2533, 3135], [1998, 3076]]),
        _caja("LLEGADA", [[1784, 3093], [1981, 3114], [1975, 3164], [1778, 3143]]),
    ]


# --- extractor: causa raíz ---


def test_482772_482902_carro_pegado_al_tracto_se_separa():
    assert _extraer_patentes_geometrico(_zona_482772()) == {"tracto": "KN5439", "carro": "JF6468"}


def test_482953_carro_pegado_al_tracto_se_separa():
    assert _extraer_patentes_geometrico(_zona_482953()) == {"tracto": "ND6443", "carro": "JB6878"}


def test_482953_texto_lineal_no_toma_el_carro_como_tracto():
    datos = extraer_datos(["RETIRA PATENTE FECHA LLEGADA JOSE LAZCANO ND6443CARRO:JB6878 22-10-2026"])
    assert (datos["patente del tracto"], datos["patente del carro"]) == ("ND6443", "JB6878")


def test_carro_pegado_con_confusion_ocr_conocida_tambien_se_separa():
    assert _extraer_patentes_geometrico(_zona_482953("ND6443CARR0:JB6878")) == {"tracto": "ND6443", "carro": "JB6878"}


def test_etiqueta_pegada_irreconocible_se_abstiene_en_vez_de_tomar_el_carro():
    # Una letra pegada antes de CARRO impide reconocerla como etiqueta: el
    # valor que la sigue igual nunca se toma como tracto.
    resultado = _extraer_patentes_geometrico(_zona_482953("ND6443XCARRO:JB6878"))
    assert resultado.get("tracto") != "JB6878"
    assert "carro" not in resultado


def test_dos_valores_sin_etiqueta_siguen_abstenidos():
    assert _extraer_patentes_geometrico(_zona_482953("ND6443 JB6878")) == {}


# --- clasificación por asignación vigente ---


def _flota(tmp_path):
    ruta = tmp_path / "vehiculos.json"
    ruta.write_text(json.dumps({"version": 1, "vehiculos": []}), encoding="utf-8")
    for patente, tipo in (("KN5439", TipoVehiculo.TRACTO), ("JF6468", TipoVehiculo.CARRO),
                          ("ND6443", TipoVehiculo.TRACTO), ("JB6878", TipoVehiculo.CARRO)):
        _confirmar(ruta, patente, tipo)
    for patente, rut in (("KN5439", REYES), ("JF6468", REYES), ("ND6443", LAZCANO), ("JB6878", LAZCANO)):
        _asignar(ruta, patente, rut)
    return ruta


def _asignar(ruta, patente, rut, dia=1):
    asociar_chofer_a_vehiculo_confirmado(
        ruta, patente=patente, actor="JAVIER", fuente_decision="TEST", rut_chofer_asociado=rut,
        fecha=datetime(2026, 10, dia, tzinfo=timezone.utc),
    )


def _clasificar(ruta, tracto, rampla, rut):
    return clasificar_patentes_por_asignacion_vigente(
        tracto, rampla, rut, cargar_catalogo_vehiculos(ruta).homologables(),
    )


def test_carro_vigente_leido_como_tracto_vuelve_a_la_rampla_sin_inventar_tracto(tmp_path):
    ruta = _flota(tmp_path)
    assert _clasificar(ruta, "JF6468", "No encontrado", REYES) == ("No encontrado", "JF6468")
    assert _clasificar(ruta, "JB6878", "No encontrado", LAZCANO) == ("No encontrado", "JB6878")


def test_tracto_y_carro_vigentes_intercambiados_se_reubican(tmp_path):
    ruta = _flota(tmp_path)
    assert _clasificar(ruta, "JF6468", "KN5439", REYES) == ("KN5439", "JF6468")


def test_tracto_vigente_leido_como_rampla_vuelve_al_tracto(tmp_path):
    ruta = _flota(tmp_path)
    assert _clasificar(ruta, "No encontrado", "ND6443", LAZCANO) == ("ND6443", "No encontrado")


def test_lectura_ya_correcta_o_tracto_ausente_no_se_toca(tmp_path):
    ruta = _flota(tmp_path)
    assert _clasificar(ruta, "KN5439", "JF6468", REYES) is None
    assert _clasificar(ruta, "No encontrado", "JF6468", REYES) is None  # nunca completa el tracto


def test_evidencia_contradictoria_no_intercambia(tmp_path):
    ruta = _flota(tmp_path)
    assert _clasificar(ruta, "JF6468", "XX1234", REYES) is None  # rampla ajena a la asignación
    assert _clasificar(ruta, "JF6486", "No encontrado", REYES) is None  # sólo coincidencia exacta
    assert _clasificar(ruta, "JF6468", "No encontrado", LAZCANO) is None  # carro de otro chofer
    assert _clasificar(ruta, "JF6468", "No encontrado", "") is None  # chofer no identificado


def test_sin_tracto_y_carro_vigentes_confirmados_no_reclasifica(tmp_path):
    ruta = _flota(tmp_path)
    _confirmar(ruta, "BB1234", TipoVehiculo.CARRO)
    _asignar(ruta, "BB1234", OTRO, 2)
    assert _clasificar(ruta, "BB1234", "No encontrado", OTRO) is None  # OTRO no tiene tracto vigente


def test_dos_carros_vigentes_del_chofer_es_contradiccion(tmp_path):
    ruta = _flota(tmp_path)
    _confirmar(ruta, "BB1234", TipoVehiculo.CARRO)
    _asignar(ruta, "BB1234", REYES, 2)
    assert _clasificar(ruta, "JF6468", "No encontrado", REYES) is None


def test_ingesta_reubica_el_carro_vigente_y_conserva_la_lectura(tmp_path, monkeypatch):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir()
    ruta = _flota(carpeta)
    assert ruta == carpeta / "vehiculos.json"
    # El OCR sólo leyó el carro junto a la etiqueta PATENTE.
    bloques = [
        _bloque("RETIRA", 20, 20, 60),
        _bloque("PATENTE", 20, 50, 70), _bloque("JF6468", 120, 50, 70),
        _bloque("FECHA LLEGADA", 20, 80, 120),
    ]
    _preparar_mocks(monkeypatch, bloques, _datos_lineales(**{"RUT del chofer": REYES}))

    resultado = procesar_archivo(tmp_path / "guia.jpg", carpeta_catalogos=carpeta)

    assert resultado["patente_tracto"] == "No encontrado"
    assert resultado["patente_rampla"] == "JF6468"
    metricas = json.loads(resultado["metricas_procesamiento_json"])
    assert metricas["reclasificacion_patentes"] == {
        "metodo": "ASIGNACION_VIGENTE_CHOFER", "tracto_leido": "JF6468", "carro_leido": "No encontrado",
        "tracto": "No encontrado", "carro": "JF6468",
    }
