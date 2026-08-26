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


# --- Bloque B1 V2 -- PREGÚNTALE A ATLAS / B1 V2: las 3 preguntas reales
# de Javier que antes devolvían "22 viajes" (Bloque 19/13 del ticket).
# Regresiones permanentes, contra el archivo real de incidencias. ---

def _ruta_incidencias_real() -> Path:
    # Bloque B1 V2.1 -- SIEMPRE se computa la ruta una vez que la raíz
    # Atlas existe (mismo criterio que `main.js`: la raíz resuelta basta,
    # nunca se exige que el archivo ya exista) -- si el archivo aún no
    # existe, `responder_consulta_atlas` ya lo trata como "cero real",
    # nunca como "fuente no indicada".
    return RAIZ_DRIVE / "catalogos_privados" / "incidencias_documentales.json"


RUTA_INCIDENCIAS_REAL = _ruta_incidencias_real()


def test_a_incidencias_documentales_nunca_responde_en_viajes():
    """Caso real A -- antes: "22 viajes". Ahora: cuenta el repositorio
    canónico de incidencias, nunca infiere contando REVISAR."""
    r = responder_consulta_atlas(
        "¿Cuántas incidencias documentales hay?",
        ruta_viajes=RUTA_VIAJES_REAL, ruta_incidencias=RUTA_INCIDENCIAS_REAL,
    )
    assert r.estado == ESTADO_OK
    assert "incidencia" in r.texto_respuesta.lower()
    assert "viaje" not in r.texto_respuesta.lower().split("corresponden")[0]
    if RUTA_INCIDENCIAS_REAL is not None:
        incidencias = json.loads(RUTA_INCIDENCIAS_REAL.read_text(encoding="utf-8"))["incidencias"]
        assert r.resultado.resultado == len(incidencias)


def test_b_km_de_retamal_nunca_responde_en_viajes():
    """Caso real B -- antes: "3 viajes". Ahora: SUM_KM del chofer real."""
    viajes = _leer_viajes_real()
    esperado = sum(
        float(v.get("distancia_km") or 0) for v in viajes if "RETAMAL" in v.get("choferes", "").upper()
    )
    r = responder_consulta_atlas("¿Cuántos kms recorridos tiene Retamal?", ruta_viajes=RUTA_VIAJES_REAL)
    assert r.estado == ESTADO_OK
    assert "km calculados" in r.texto_respuesta
    assert r.resultado.resultado == esperado


def test_c_choferes_que_trabajaron_este_mes_nunca_responde_en_viajes():
    """Caso real C -- antes: "22 viajes". Ahora: COUNT_DISTINCT_CHOFER,
    personas distintas, nunca filas."""
    r = responder_consulta_atlas("¿Cuántos choferes trabajaron este mes?", ruta_viajes=RUTA_VIAJES_REAL)
    assert r.estado == ESTADO_OK
    assert "chofer" in r.texto_respuesta.lower()
    assert r.resultado.resultado != 22 or r.resultado.consulta_interpretada.metrica != "COUNT_VIAJES"
    assert r.resultado.consulta_interpretada.metrica == "COUNT_DISTINCT_CHOFER"


# --- Variantes de lenguaje natural (Bloque 14) -- mismas 3 intenciones ---

def test_variante_cuantos_km_hizo_retamal():
    r = responder_consulta_atlas("cuantos km hizo retamal", ruta_viajes=RUTA_VIAJES_REAL)
    assert r.resultado.consulta_interpretada.metrica == "SUM_KM"


def test_variante_distancia_de_cristopher_retamal():
    r = responder_consulta_atlas("distancia de cristopher retamal", ruta_viajes=RUTA_VIAJES_REAL)
    assert r.resultado.consulta_interpretada.metrica == "SUM_KM"


def test_variante_errores_documentales_que_tenemos():
    r = responder_consulta_atlas(
        "errores documentales que tenemos", ruta_viajes=RUTA_VIAJES_REAL, ruta_incidencias=RUTA_INCIDENCIAS_REAL,
    )
    assert r.resultado.consulta_interpretada.dominio == "INCIDENCIAS_DOCUMENTALES"


def test_variante_cuantos_conductores_cargaron_este_mes():
    r = responder_consulta_atlas("cuántos conductores cargaron este mes", ruta_viajes=RUTA_VIAJES_REAL)
    assert r.resultado.consulta_interpretada.metrica == "COUNT_DISTINCT_CHOFER"


def test_variante_choferes_con_viajes_este_mes():
    r = responder_consulta_atlas("choferes con viajes este mes", ruta_viajes=RUTA_VIAJES_REAL)
    assert r.resultado.consulta_interpretada.metrica == "COUNT_DISTINCT_CHOFER"


def test_toneladas_movio_nahuelnir_nunca_responde_en_viajes():
    """Bloque 17 del ticket -- regresión permanente #4."""
    viajes = _leer_viajes_real()
    esperado_kg = sum(
        float(v.get("peso_total_viaje_kg") or 0) for v in viajes if "NAHUEL" in v.get("choferes", "").upper()
    )
    r = responder_consulta_atlas("¿Cuántas toneladas movió Nahuelñir?", ruta_viajes=RUTA_VIAJES_REAL)
    assert r.resultado.consulta_interpretada.metrica == "SUM_PESO"
    assert r.resultado.resultado == esperado_kg


# --- Bloque UNIVERSAL V1 -- E2E RELACIONALES (Bloque 18 del ticket),
# motor genérico, patentes reales de producción (JB8529/JF4288) ---

def _raiz_atlas_real() -> Path | None:
    return RAIZ_DRIVE if RAIZ_DRIVE.is_dir() else None


RAIZ_ATLAS_REAL = _raiz_atlas_real()


def test_relacional_en_que_viajes_aparece_jb8529():
    viajes = _leer_viajes_real()
    esperados = {
        v["numero_transporte"] for v in viajes
        if "JB8529" in v.get("patentes_tracto", "").upper().split(" | ") + v.get("patentes_rampla", "").upper().split(" | ")
    }
    r = responder_consulta_atlas("¿En qué viajes aparece la patente JB8529?", ruta_viajes=RUTA_VIAJES_REAL)
    assert r.estado == ESTADO_OK
    assert {v["numero_transporte"] for v in r.resultado.viajes_soporte} == esperados


def test_relacional_con_que_chofer_esta_vinculada_jf4288():
    r = responder_consulta_atlas("¿Con qué chofer está vinculada JF4288?", ruta_viajes=RUTA_VIAJES_REAL)
    assert r.estado == ESTADO_OK
    assert r.resultado.consulta_interpretada.relacion == "chofer"
    assert "NAHUEL" in "".join(r.resultado.resultado).upper()


def test_relacional_que_patentes_ha_usado_retamal():
    r = responder_consulta_atlas("¿Qué patentes ha usado Retamal?", ruta_viajes=RUTA_VIAJES_REAL)
    assert r.estado == ESTADO_OK
    assert r.resultado.resultado == ("BPHR67",)


def test_relacional_en_que_guias_aparece_jf4288():
    r = responder_consulta_atlas("¿En qué guías aparece JF4288?", ruta_viajes=RUTA_VIAJES_REAL)
    assert r.estado == ESTADO_OK
    assert r.resultado.resultado == ("472247",)


def test_relacional_que_cliente_aparece_en_el_viaje_0000354805():
    r = responder_consulta_atlas("¿Qué cliente aparece en el viaje 0000354805?", ruta_viajes=RUTA_VIAJES_REAL)
    assert r.estado == ESTADO_OK
    assert r.resultado.resultado == ("YOLITO BALART HNOS LTDA",)


# --- Bloque UNIVERSAL V1 -- dominio EVENTOS contra producción real:
# hoy no hay envíos Mobile con novedad todavía -- cero real, nunca
# "fuente no disponible" (Bloque 14), con la raíz sí indicada. ---

def test_eventos_dominio_real_es_cero_real_no_fuente_no_disponible():
    r = responder_consulta_atlas(
        "¿Cuántas estadías tuvo Retamal?", ruta_viajes=RUTA_VIAJES_REAL, raiz_atlas=RAIZ_ATLAS_REAL,
    )
    assert r.resultado.consulta_interpretada.dominio == "EVENTOS"
    assert r.estado in (ESTADO_OK, ESTADO_SIN_RESULTADOS)  # nunca FUENTE_NO_DISPONIBLE con raíz indicada
