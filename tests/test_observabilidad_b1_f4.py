"""Bloque AUTORIDAD OPERACIONAL -- Fase 4: OBSERVABILIDAD OBLIGATORIA +
Bloque E (dedup entre pasadas). Un único registro por lote, auditable sin
arqueología manual, que combina la pasada B1 sobre motivos con la segunda
pasada universal sobre decisiones.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone

from atlas_core.catalogo_vehiculos import TipoVehiculo, confirmar_vehiculo
from atlas_core.procesamiento_masivo import (
    COLUMNAS,
    _campos_ya_evaluados_por_b1,
    _persistir_observabilidad_b1,
    _segunda_pasada_universal,
    consolidar_observabilidad_b1,
)


def _confirmar_vehiculo(carpeta, patente, tipo, *, rut_chofer_asociado=""):
    ruta = carpeta / "vehiculos.json"
    if not ruta.exists():
        ruta.write_text(json.dumps({"version": 1, "vehiculos": []}), encoding="utf-8")
    return confirmar_vehiculo(
        ruta, patente=patente, tipo=tipo, actor="JAVIER", fuente_decision="T",
        fecha=datetime.now(timezone.utc), rut_chofer_asociado=rut_chofer_asociado,
    )


def _fila(**ov):
    fila = {c: "" for c in COLUMNAS}
    fila.update({"archivo": "g1.jpeg", "estado_procesamiento": "OK", "numero_guia": "900001",
                 "numero_transporte": "T-1"})
    fila.update(ov)
    return fila


def _csv(tmp_path, filas):
    ruta = tmp_path / "analisis_completo_guias.csv"
    with ruta.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)
    return ruta


def _decision_vehiculo(campo="patente_rampla", valor="JD8629"):
    return {
        "decision_id": "d1", "estado": "PENDIENTE", "tipo": "VEHICULO_DESCONOCIDO",
        "entidad": "VEHICULO", "documento": {"archivo": "g1.jpeg", "numero_guia": "900001",
        "numero_transporte": "T-1"}, "campo": campo, "valor_documental": valor,
        "valor_normalizado": valor, "identidad_resuelta": None, "contexto": None,
        "candidatos": [], "motivos": [], "evidencias": [],
        "acciones_permitidas": ["REGISTRAR", "NO_REGISTRAR", "POSPONER"],
    }


# ==========================================================================
# Consolidación -- las 10 métricas obligatorias
# ==========================================================================


def test_consolidacion_expone_las_metricas_obligatorias(tmp_path):
    traza = [
        {"problema": "PATENTE_SIN_HOMOLOGAR", "dominio": "PATENTE", "campo": "patente_tracto",
         "elegible_ia": True, "llamada_realizada": True, "estado": "BLOQUEADO_POR_VALIDACION",
         "clasificacion": "D_BLOQUEO", "validacion": {"motivo_rechazo": "VALOR_NO_RESPALDADO_POR_EVIDENCIA"}},
        {"problema": "CLIENTE_SIN_CORROBORAR", "dominio": "CLIENTE", "campo": "cliente",
         "elegible_ia": True, "llamada_realizada": False, "razon_no_elegible": "SIN_EVIDENCIA_PARA_RAZONAR"},
    ]
    fila = _fila(resultado_atlas_ia_json=json.dumps(traza),
                 metricas_procesamiento_json=json.dumps({
                     "resoluciones_convergentes": [{"campo": "obra_destino", "valor_ocr": "X",
                                                    "valor_canonico": "Y"}]}))
    ruta_csv = _csv(tmp_path, [fila])
    sp = {"decisiones_detectadas": 3, "resueltas_determinista": 1, "entregadas_b1": 2,
          "b1_respondio": 1, "b1_resolvio": 1, "b1_abstuvo": 1, "b1_bloqueado": 0,
          "b1_bloqueado_motivos": [], "b1_error_413": 0, "b1_error_429_cooldown": 1,
          "a_humano": 1, "dedup_con_pasada_motivos": 1}

    r = consolidar_observabilidad_b1(
        ruta_csv=ruta_csv, archivos_objetivo={"g1.jpeg"}, decisiones_pendientes=[],
        resumen_motivos={"latencia_segundos": 12.3}, resumen_segunda_pasada=sp,
    )
    for clave in (
        "problemas_detectados", "resueltos_determinista_antes_de_b1", "entregados_a_b1",
        "b1_respondio", "b1_resolvio_aplico", "b1_se_abstuvo", "b1_bloqueado_validacion",
        "b1_bloqueado_motivos", "b1_error_413", "b1_error_429_cooldown",
        "dedup_tareas_equivalentes", "decisiones_a_humano", "decisiones_pendientes_finales",
    ):
        assert clave in r
    # motivos + segunda pasada sumados
    assert r["problemas_detectados"] == 2 + 3
    assert r["resueltos_determinista_antes_de_b1"] == 1 + 1  # sp + convergencia en métricas
    assert r["b1_bloqueado_validacion"] == 1
    assert "VALOR_NO_RESPALDADO_POR_EVIDENCIA" in r["b1_bloqueado_motivos"]
    assert r["b1_error_429_cooldown"] == 1
    assert r["dedup_tareas_equivalentes"] == 1
    assert r["latencia_b1_segundos"] == 12.3


def test_persiste_una_linea_jsonl_por_lote(tmp_path):
    ruta_csv = _csv(tmp_path, [_fila()])
    _persistir_observabilidad_b1(ruta_csv, {"problemas_detectados": 5})
    _persistir_observabilidad_b1(ruta_csv, {"problemas_detectados": 2})
    destino = tmp_path / "b1_observabilidad.jsonl"
    lineas = destino.read_text(encoding="utf-8").strip().splitlines()
    assert len(lineas) == 2
    for linea in lineas:
        obj = json.loads(linea)
        assert "fecha" in obj and "problemas_detectados" in obj


# ==========================================================================
# Bloque E -- dedup de tareas equivalentes entre la pasada de motivos y la
#             segunda pasada
# ==========================================================================


def test_campos_ya_evaluados_por_b1_lee_la_traza():
    fila = {"resultado_atlas_ia_json": json.dumps([
        {"campo": "patente_rampla", "llamada_realizada": True},
        {"campo": "cliente", "llamada_realizada": False},
    ])}
    assert _campos_ya_evaluados_por_b1(fila) == {"patente_rampla"}


def test_segunda_pasada_no_reconsulta_un_campo_ya_evaluado(tmp_path):
    carpeta = tmp_path / "cat"
    carpeta.mkdir()
    _confirmar_vehiculo(carpeta, "JD8659", TipoVehiculo.CARRO, rut_chofer_asociado="15489424-1")
    _confirmar_vehiculo(carpeta, "JD8658", TipoVehiculo.CARRO, rut_chofer_asociado="15489424-1")
    # La pasada de motivos ya "llamó" a B1 para patente_rampla.
    fila = _fila(
        rut_chofer="15489424-1", patente_rampla="JD8629",
        resultado_atlas_ia_json=json.dumps([
            {"campo": "patente_rampla", "dominio": "PATENTE", "llamada_realizada": True,
             "estado": "ABSTENCION_IA"}]),
    )
    ruta_csv = _csv(tmp_path, [fila])

    class _OrqQueFalla:
        def resolver(self, contexto):
            raise AssertionError("no debe volver a llamar a B1 para un campo ya evaluado")

    m = _segunda_pasada_universal(ruta_csv, {"g1.jpeg"}, [_decision_vehiculo()], _OrqQueFalla(), carpeta)
    assert m["dedup_con_pasada_motivos"] == 1
    assert m["entregadas_b1"] == 0
    assert m["a_humano"] >= 1
