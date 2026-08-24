"""Bloque B1 OBSERVADOR -- cuando el Motor resuelve una guía SIN ningún
problema elegible, B1 nunca es invocado (0 llamadas LLM), pero
`_ejecutar_ia_operacional` deja un registro OBSERVACIONAL compacto en la
MISMA columna/contrato ya existente (`resultado_atlas_ia_json`, nunca una
memoria paralela) -- reutilizable después por
`decisiones_pendientes.resumen_observacion_operacional` ("¿qué pasó con
una guía similar?"), sin gastar tokens si no hace falta."""
from __future__ import annotations

import csv
import json

from atlas_core.atlas_ia.orquestador import OrquestadorAtlasIA
from atlas_core.atlas_ia.proveedor import ProveedorModeloIASimulado
from atlas_core.decisiones_pendientes import resumen_observacion_operacional
from atlas_core.procesamiento_masivo import COLUMNAS, _ejecutar_ia_operacional


def _fila(**cambios):
    fila = {columna: "" for columna in COLUMNAS}
    fila.update({
        "archivo": "resuelta.jpg", "estado_procesamiento": "OK", "fecha": "24-08-2026",
        "chofer": "PERSONA EJEMPLO", "patente_tracto": "AB1234",
        "obra_destino": "OBRA NORTE", "cliente": "CLIENTE EJEMPLO",
        "planta_origen_nombre": "AZA COLINA", "origen_determinado_por": "TELEMETRIA_GPS",
        "indicador_revision": "OK", "motivos_revision_documento": "",
        "estado_ruta": "RUTA_CALCULADA",
    })
    fila.update(cambios)
    return fila


def _escribir(ruta, filas):
    with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerows(filas)


def _leer(ruta):
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return {f["archivo"]: f for f in csv.DictReader(archivo, delimiter=";")}


def test_motor_resuelve_deja_observacion_sin_llamar_a_b1(tmp_path):
    ruta = tmp_path / "dataset.csv"
    _escribir(ruta, [_fila()])
    llamadas = []
    orquestador = OrquestadorAtlasIA(proveedor=ProveedorModeloIASimulado(respuestas_por_valor_documental={}))
    orquestador.resolver = lambda *a, **k: llamadas.append(1)  # nunca debe llamarse

    resumen = _ejecutar_ia_operacional(ruta, {"resuelta.jpg"}, orquestador)

    assert resumen["llamadas"] == 0
    assert llamadas == []
    fila = _leer(ruta)["resuelta.jpg"]
    assert fila["resultado_atlas_ia_json"]
    trazas = json.loads(fila["resultado_atlas_ia_json"])
    assert len(trazas) == 1
    assert trazas[0]["dominio"] == "CICLO_GUIA"
    assert trazas[0]["llamada_realizada"] is False
    assert trazas[0]["resultado_motor"] == "RESUELTO"
    assert trazas[0]["resumen"]["estado_ruta"] == "RUTA_CALCULADA"
    assert trazas[0]["resumen"]["obra_destino"] == "OBRA NORTE"


def test_observacion_es_idempotente_no_se_reescribe_dos_veces(tmp_path):
    """Una guía ya observada (procesada en una corrida anterior) nunca
    se vuelve a tocar -- ni gasta ciclos ni pisa un contenido distinto
    que otro bloque pudiera haber dejado ahí después."""
    ruta = tmp_path / "dataset.csv"
    ya_observada = json.dumps([{"problema": "OBSERVACION_OPERACIONAL", "dominio": "CICLO_GUIA", "resumen": {"marca": "previa"}}])
    _escribir(ruta, [_fila(resultado_atlas_ia_json=ya_observada)])
    orquestador = OrquestadorAtlasIA(proveedor=ProveedorModeloIASimulado(respuestas_por_valor_documental={}))

    resumen = _ejecutar_ia_operacional(ruta, {"resuelta.jpg"}, orquestador)

    assert resumen["llamadas"] == 0
    fila = _leer(ruta)["resuelta.jpg"]
    assert json.loads(fila["resultado_atlas_ia_json"])[0]["resumen"]["marca"] == "previa"


def test_guia_con_problema_real_no_recibe_observacion_generica():
    """Control -- una fila que SÍ requiere atención sigue su camino
    normal (detección de problemas elegibles); nunca se le agrega,
    además, la traza observacional genérica (serían dos historias
    contradictorias para la misma guía)."""
    from atlas_core.procesamiento_masivo import _fila_requiere_atencion_operacional
    fila_con_problema = _fila(estado_ruta="REQUIERE_REVISION", motivo_ruta="CONFIANZA_INSUFICIENTE")
    assert _fila_requiere_atencion_operacional(fila_con_problema) is True


def test_resumen_observacion_operacional_lee_la_traza():
    fila = _fila(resultado_atlas_ia_json=json.dumps([{
        "problema": "OBSERVACION_OPERACIONAL", "dominio": "CICLO_GUIA", "campo": "resultado_final",
        "elegible_ia": False, "llamada_realizada": False, "resultado_motor": "RESUELTO",
        "resumen": {"estado_ruta": "RUTA_CALCULADA", "obra_destino": "OBRA NORTE"},
    }]))
    r = resumen_observacion_operacional(fila)
    assert r is not None
    assert r["resultado_motor"] == "RESUELTO"
    assert r["resumen"]["obra_destino"] == "OBRA NORTE"


def test_resumen_observacion_operacional_none_sin_traza():
    assert resumen_observacion_operacional(_fila(resultado_atlas_ia_json="")) is None


def test_resumen_observacion_operacional_none_si_solo_hay_hallazgo_de_otro_dominio():
    """No confunde la traza observacional con una traza de investigación
    real (`dominio="DESTINO"`, con llamada B1 real) -- dominios distintos,
    nunca se mezclan."""
    fila = _fila(resultado_atlas_ia_json=json.dumps([{
        "problema": "CONFIANZA_INSUFICIENTE", "dominio": "DESTINO", "campo": "despachar_a_crudo",
        "elegible_ia": True, "llamada_realizada": True,
    }]))
    assert resumen_observacion_operacional(fila) is None
