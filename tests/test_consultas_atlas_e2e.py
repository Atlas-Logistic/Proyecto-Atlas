"""Bloque CONSULTAS ATLAS V1 -- E2E real obligatorio (Bloque 19 del
ticket): las 6 preguntas de ejemplo (A-F), ejecutadas contra el
`viajes.csv` REAL vigente (`G:\\Mi unidad\\Atlas`), verificadas
directamente contra el dataset -- no una copia sintética.

Se salta automáticamente (nunca falla) si el Drive real no está
montado en el entorno que corre la suite -- mismo criterio ya usado
por otros tests E2E de este repo contra `G:\\Mi unidad\\Atlas`."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from atlas_core.responder_consulta_atlas import ESTADO_OK, ESTADO_SIN_RESULTADOS, responder_consulta_atlas

RAIZ_DRIVE = Path(r"G:\Mi unidad\Atlas")


def _ruta_viajes_real() -> Path | None:
    ruta_estado = RAIZ_DRIVE / "operacion" / "actual" / "estado_operacion.json"
    if not ruta_estado.is_file():
        return None
    estado = json.loads(ruta_estado.read_text(encoding="utf-8"))
    reporte = estado.get("reporte_vigente")
    if not reporte:
        return None
    ruta = RAIZ_DRIVE / Path(*reporte.split("/")) / "viajes.csv"
    return ruta if ruta.is_file() else None


RUTA_VIAJES_REAL = _ruta_viajes_real()
pytestmark = pytest.mark.skipif(RUTA_VIAJES_REAL is None, reason="Drive real (G:\\Mi unidad\\Atlas) no disponible en este entorno.")


def _leer_viajes_real():
    with RUTA_VIAJES_REAL.open(encoding="utf-8-sig") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def test_a_conteo_villagra_coincide_con_dataset_real():
    viajes = _leer_viajes_real()
    esperado = sum(1 for v in viajes if "VILLAGRA" in v.get("choferes", "").upper())
    r = responder_consulta_atlas("¿Cuántos viajes hizo Villagra?", ruta_viajes=RUTA_VIAJES_REAL)
    assert r.estado == ESTADO_OK
    assert r.resultado.resultado == esperado
    assert r.resultado.total_coincidencias == esperado
    assert len(r.resultado.viajes_soporte) == esperado


def test_b_listar_viajes_de_villagra_devuelve_las_filas_reales():
    viajes = _leer_viajes_real()
    esperados = {v["numero_transporte"] for v in viajes if "VILLAGRA" in v.get("choferes", "").upper()}
    r = responder_consulta_atlas("Muéstrame los viajes de Villagra.", ruta_viajes=RUTA_VIAJES_REAL)
    assert r.estado == ESTADO_OK
    obtenidos = {v["numero_transporte"] for v in r.resultado.viajes_soporte}
    assert obtenidos == esperados


def test_c_conteo_rollos_coincide_con_dataset_real():
    viajes = _leer_viajes_real()
    esperado = sum(1 for v in viajes if "ROLLOS" in v.get("tipos_carga", "").upper().split(" | "))
    r = responder_consulta_atlas("¿Cuántos viajes fueron con rollos?", ruta_viajes=RUTA_VIAJES_REAL)
    assert r.estado == ESTADO_OK
    assert r.resultado.resultado == esperado


def test_d_toneladas_por_chofer_coincide_con_suma_real():
    viajes = _leer_viajes_real()
    esperado_por_chofer: dict[str, float] = {}
    for v in viajes:
        for chofer in v.get("choferes", "").split(" | "):
            chofer = chofer.strip()
            if chofer:
                esperado_por_chofer[chofer] = esperado_por_chofer.get(chofer, 0.0) + float(v.get("peso_total_viaje_kg") or 0)
    r = responder_consulta_atlas("¿Cuántas toneladas transportó cada chofer?", ruta_viajes=RUTA_VIAJES_REAL)
    assert r.estado == ESTADO_OK
    obtenido = {f["grupo"]: f["valor"] for f in r.resultado.resultado}
    assert obtenido == esperado_por_chofer


def test_e_conteo_salomon_sack_coincide_con_dataset_real():
    viajes = _leer_viajes_real()
    esperado = sum(1 for v in viajes if "SALOMON SACK SA" in v.get("clientes", "").upper())
    r = responder_consulta_atlas("¿Cuántos viajes fueron para Salomon Sack?", ruta_viajes=RUTA_VIAJES_REAL)
    assert r.estado == ESTADO_OK
    assert r.resultado.resultado == esperado


def test_f_consulta_compuesta_chofer_tipo_carga_periodo():
    """Villagra + rollos + este mes -- verificado contra el dataset real
    que, hoy, no da ninguna coincidencia (Villagra sólo transportó
    BARRAS este mes) -- Bloque 13: cero resultados no es error."""
    viajes = _leer_viajes_real()
    esperado = sum(
        1 for v in viajes
        if "VILLAGRA" in v.get("choferes", "").upper()
        and "ROLLOS" in v.get("tipos_carga", "").upper().split(" | ")
    )
    r = responder_consulta_atlas(
        "¿Cuántos viajes hizo Villagra con rollos este mes?", ruta_viajes=RUTA_VIAJES_REAL,
    )
    if esperado == 0:
        assert r.estado == ESTADO_SIN_RESULTADOS
    else:
        assert r.estado == ESTADO_OK
    assert r.resultado.resultado == esperado


def test_total_viajes_actuales_coincide_con_23_reportados():
    """Control -- el total de viajes del reporte vigente sigue siendo el
    universo real sobre el que Consultas Atlas trabaja."""
    viajes = _leer_viajes_real()
    r = responder_consulta_atlas("¿Cuántos viajes hay?", ruta_viajes=RUTA_VIAJES_REAL)
    assert r.estado == ESTADO_OK
    assert r.resultado.resultado == len(viajes)
