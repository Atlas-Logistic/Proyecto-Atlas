"""Bloque R2.3 (adición) -- RESOLUCIÓN OPERACIONAL DE PLANTA ORIGEN.

`revalidar_origen_por_eliminacion_categoria_sin_ocr`: reconcilia, sin OCR,
un origen que quedó `CONTRADICCION_OPERACIONAL_ORIGEN[...]` cuando la
planta documental resulta incompatible con la categoría real de la carga
y existe exactamente una alternativa vigente compatible que no es, ella
misma, el destino del despacho. Fixtures propias (nunca AZA/COLINA/RENCA
hardcodeado en la LÓGICA -- sólo en los nombres de ejemplo, que son
datos), más un caso de regresión real al final."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import revalidar_origen_por_eliminacion_categoria_sin_ocr

RAIZ_REAL = Path("G:/Mi unidad/Atlas")
CSV_REAL = RAIZ_REAL / "operacion" / "actual" / "analisis_completo_guias.csv"
CATALOGOS_REALES = RAIZ_REAL / "catalogos_privados"
DATOS_REALES_DISPONIBLES = CSV_REAL.is_file() and CATALOGOS_REALES.is_dir()


def _fila(**cambios):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "g.jpeg", "numero_guia": "1", "numero_transporte": "00001",
        "fecha": "31-08-2026", "cliente": "CLIENTE EJEMPLO", "obra_destino": "OBRA EJEMPLO",
        "estado_ruta": "ORIGEN_NO_DETERMINADO",
        "motivo_ruta": "CONTRADICCION_OPERACIONAL_ORIGEN[DOCUMENTO=PLANTA_SUR:INCOMPATIBLE]",
        "tipo_carga": "BARRAS", "despachar_a_crudo": "CALLE DE UN CLIENTE 500",
        "motivo_origen_gps": "",
    })
    fila.update(cambios)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        for fila in filas:
            escritor.writerow(fila)


def _planta_json(*, nombre, categorias, direccion="", estado_vigencia="ACTIVA"):
    ahora = datetime.now(timezone.utc).isoformat()
    return {
        "planta_id": nombre.replace(" ", "_").lower(), "nombre": nombre,
        "nombre_normalizado": nombre.upper(), "direccion": direccion, "comuna": "", "region": "",
        "pais": "CHILE", "latitud": None, "longitud": None,
        "estado_calidad": "CONFIRMADA", "estado_vigencia": estado_vigencia,
        "fuente": "TEST", "observacion": "", "fecha_creacion": ahora, "fecha_modificacion": ahora,
        "tipo_geocerca": "CIRCULAR", "vertices": [],
        "categorias_permitidas": list(categorias),
    }


def _catalogos_con_plantas(tmp_path, plantas):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir()
    (carpeta / "plantas.json").write_text(
        json.dumps({"version_formato": 1, "plantas": plantas}), encoding="utf-8"
    )
    return carpeta


PLANTA_NORTE = _planta_json(nombre="PLANTA NORTE", categorias=("BARRAS", "ROLLOS"), direccion="CALLE NORTE 100")
PLANTA_SUR = _planta_json(nombre="PLANTA SUR", categorias=("ANGULOS",))


def test_resuelve_origen_por_eliminacion_y_limpia_el_bloqueo(tmp_path):
    carpeta = _catalogos_con_plantas(tmp_path, [PLANTA_NORTE, PLANTA_SUR])
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila(numero_guia="1")])

    resultado = revalidar_origen_por_eliminacion_categoria_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)

    assert resultado["guias_actualizadas"] == ["1"]
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        fila = next(csv.DictReader(archivo, delimiter=";"))
    assert fila["planta_origen_nombre"] == "PLANTA NORTE"
    assert fila["planta_origen_id"]
    assert fila["estado_ruta"] == ""
    assert fila["motivo_ruta"] == ""
    assert "PLANTA_SUR" in fila["evidencia_origen"] or "PLANTA SUR" in fila["evidencia_origen"]


def test_origen_resuelto_con_destino_pendiente_sigue_requiere_revision(tmp_path):
    """Bloque R2.4 -- CORRECCIÓN de un bug real encontrado en producción:
    la versión anterior ponía OK aquí mismo apenas se limpiaba
    estado_ruta, ANTES de calcular ningún km/tiempo -- Desktop mostraba
    "estado OK" + "Ruta aún no calculada" a la vez (caso real 464170).
    Con un destino (`despachar_a_crudo`) todavía por rutear, la
    dependencia sigue pendiente -- sólo el revalidador de ruta (que corre
    después, con el origen ya resuelto) puede confirmar OK de verdad."""
    carpeta = _catalogos_con_plantas(tmp_path, [PLANTA_NORTE, PLANTA_SUR])
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila(
        numero_guia="1", estado_documental="OK", estado_operacional="REQUIERE_REVISION",
        despachar_a_crudo="CALLE DE UN CLIENTE 500",
    )])

    revalidar_origen_por_eliminacion_categoria_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)

    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        fila = next(csv.DictReader(archivo, delimiter=";"))
    assert fila["estado_operacional"] == "REQUIERE_REVISION", (
        "no debe adelantarse a OK mientras la ruta siga sin calcularse"
    )
    assert fila["planta_origen_nombre"] == "PLANTA NORTE"  # el origen sí quedó resuelto


def test_origen_resuelto_sin_destino_que_rutear_confirma_directo(tmp_path):
    """Control: sin ningún destino que rutear, no hay dependencia de ruta
    pendiente -- basta con que la extracción documental esté sana."""
    carpeta = _catalogos_con_plantas(tmp_path, [PLANTA_NORTE, PLANTA_SUR])
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila(
        numero_guia="1", estado_documental="OK", estado_operacional="REQUIERE_REVISION",
        despachar_a_crudo="",
    )])

    revalidar_origen_por_eliminacion_categoria_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)

    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        fila = next(csv.DictReader(archivo, delimiter=";"))
    assert fila["estado_operacional"] == "OK"

    revalidar_origen_por_eliminacion_categoria_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)

    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        fila = next(csv.DictReader(archivo, delimiter=";"))
    assert fila["estado_operacional"] == "OK"


def test_ya_tiene_origen_no_se_toca(tmp_path):
    carpeta = _catalogos_con_plantas(tmp_path, [PLANTA_NORTE, PLANTA_SUR])
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila(numero_guia="1", planta_origen_id="ya-tiene-uno")])

    resultado = revalidar_origen_por_eliminacion_categoria_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)

    assert resultado["guias_actualizadas"] == []


def test_evidencia_gps_real_positiva_no_se_pisa(tmp_path):
    """Caso 5 del bloque de pruebas: GPS contemporáneo fuerte contradictorio
    -- nunca se fuerza la resolución por categoría por encima de evidencia
    real ya calculada."""
    carpeta = _catalogos_con_plantas(tmp_path, [PLANTA_NORTE, PLANTA_SUR])
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila(
        numero_guia="1", motivo_origen_gps="CONFLICTO_REAL_EN_VENTANA:PLANTA_ESTE=0.8|PLANTA_OESTE=0.3",
    )])

    resultado = revalidar_origen_por_eliminacion_categoria_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)

    assert resultado["guias_actualizadas"] == []


def test_traslado_interno_hacia_la_alternativa_no_resuelve(tmp_path):
    carpeta = _catalogos_con_plantas(tmp_path, [PLANTA_NORTE, PLANTA_SUR])
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila(numero_guia="1", despachar_a_crudo="CALLE NORTE 100")])

    resultado = revalidar_origen_por_eliminacion_categoria_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)

    assert resultado["guias_actualizadas"] == []


def test_motivo_ruta_no_reconocido_se_abstiene(tmp_path):
    carpeta = _catalogos_con_plantas(tmp_path, [PLANTA_NORTE, PLANTA_SUR])
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila(numero_guia="1", motivo_ruta="ALGO_NO_RECONOCIDO")])

    resultado = revalidar_origen_por_eliminacion_categoria_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)

    assert resultado["guias_actualizadas"] == []


def test_idempotente(tmp_path):
    carpeta = _catalogos_con_plantas(tmp_path, [PLANTA_NORTE, PLANTA_SUR])
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila(numero_guia="1")])

    r1 = revalidar_origen_por_eliminacion_categoria_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)
    r2 = revalidar_origen_por_eliminacion_categoria_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)

    assert r1["guias_actualizadas"] == ["1"]
    assert r2["guias_actualizadas"] == []  # ya resuelto -- nada más que hacer


# ============================================================
# Regresión real -- revalida directamente contra el catálogo real de
# producción (sin OCR nuevo, sin escribir nada -- una copia del dataset
# real en tmp_path).
# ============================================================

@pytest.mark.skipif(not DATOS_REALES_DISPONIBLES, reason="G:\\Mi unidad\\Atlas no disponible en esta máquina")
def test_regresion_real_464479_y_464170_quedaron_resueltos_a_aza_colina(tmp_path):
    """La operación real de producción ya fue reconciliada por este mismo
    bloque (R2.3) -- verifica el ESTADO FINAL correcto (nunca que "se
    actualice de nuevo": sobre datos ya resueltos, la función es
    idempotente y no toca nada más, ver test_idempotente arriba)."""
    import shutil
    dataset = tmp_path / "dataset.csv"
    shutil.copy2(CSV_REAL, dataset)

    resultado = revalidar_origen_por_eliminacion_categoria_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=CATALOGOS_REALES,
    )

    assert resultado["guias_actualizadas"] == [], "ya resuelto en producción -- nada nuevo que actualizar"
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        filas = {f["archivo"]: f for f in csv.DictReader(archivo, delimiter=";")}
    assert filas["464479.jpeg"]["planta_origen_nombre"] == "AZA COLINA"
    assert filas["464479.jpeg"]["origen_determinado_por"] == "ORIGEN_RESUELTO_POR_ELIMINACION_DE_CATEGORIA"
    assert filas["464170.jpeg"]["planta_origen_nombre"] == "AZA COLINA"
    assert filas["464170.jpeg"]["origen_determinado_por"] == "ORIGEN_RESUELTO_POR_ELIMINACION_DE_CATEGORIA"
