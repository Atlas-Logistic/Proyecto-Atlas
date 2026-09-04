"""Bloque ORIGEN V3 -- CONVERGENCIA DE EVIDENCIA ANTES DE PREGUNTAR.

`revalidar_origen_por_categoria_sin_candidato_sin_ocr`: a diferencia de
`revalidar_origen_por_eliminacion_categoria_sin_ocr` (R2.3, exige una
planta DOCUMENTAL ya identificada e INCOMPATIBLE que "eliminar"), este
bloque cubre el caso donde NUNCA hubo ningún origen informado -- ni
Mobile ni encabezado -- y el pipeline se rendía con "SIN_EVIDENCIA_GPS"
sin cruzar nunca la categoría real de la carga contra el catálogo.
Fixtures propias (nunca AZA/COLINA/RENCA hardcodeado en la LÓGICA --
sólo en los nombres de ejemplo, que son datos), más un caso de
regresión real al final (464730/464631/464529, lote 2)."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import revalidar_origen_por_categoria_sin_candidato_sin_ocr
from atlas_core.rutas.origen_evidencia import conflicto_gps_tiene_evidencia_real

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
        "motivo_ruta": "SIN_EVIDENCIA_GPS",
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


def test_resuelve_por_categoria_sola_sin_ningun_candidato_previo(tmp_path):
    carpeta = _catalogos_con_plantas(tmp_path, [PLANTA_NORTE, PLANTA_SUR])
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila(numero_guia="1")])

    resultado = revalidar_origen_por_categoria_sin_candidato_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)

    assert resultado["guias_actualizadas"] == ["1"]
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        fila = next(csv.DictReader(archivo, delimiter=";"))
    assert fila["planta_origen_nombre"] == "PLANTA NORTE"
    assert fila["planta_origen_id"]
    assert fila["origen_determinado_por"] == "CATEGORIA_DESTINO_EXTERNO"
    assert fila["estado_ruta"] == ""
    assert fila["motivo_ruta"] == ""


def test_ya_tiene_origen_no_se_toca(tmp_path):
    carpeta = _catalogos_con_plantas(tmp_path, [PLANTA_NORTE, PLANTA_SUR])
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila(numero_guia="1", planta_origen_id="ya-tiene-uno")])

    resultado = revalidar_origen_por_categoria_sin_candidato_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)

    assert resultado["guias_actualizadas"] == []


def test_categoria_no_determinada_se_abstiene_nunca_sin_regla(tmp_path):
    carpeta = _catalogos_con_plantas(tmp_path, [PLANTA_NORTE, PLANTA_SUR])
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila(numero_guia="1", tipo_carga="NO DETERMINADO")])

    resultado = revalidar_origen_por_categoria_sin_candidato_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)

    assert resultado["guias_actualizadas"] == []


def test_dos_plantas_compatibles_es_ambiguedad_real_se_abstiene(tmp_path):
    planta_norte_2 = _planta_json(nombre="PLANTA NORTE 2", categorias=("BARRAS",))
    carpeta = _catalogos_con_plantas(tmp_path, [PLANTA_NORTE, planta_norte_2, PLANTA_SUR])
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila(numero_guia="1")])

    resultado = revalidar_origen_por_categoria_sin_candidato_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)

    assert resultado["guias_actualizadas"] == []


def test_traslado_interno_hacia_la_unica_candidata_no_resuelve(tmp_path):
    carpeta = _catalogos_con_plantas(tmp_path, [PLANTA_NORTE, PLANTA_SUR])
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila(numero_guia="1", despachar_a_crudo="CALLE NORTE 100")])

    resultado = revalidar_origen_por_categoria_sin_candidato_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)

    assert resultado["guias_actualizadas"] == []


def test_conflicto_gps_con_solape_real_no_se_pisa(tmp_path):
    """Evidencia GPS real y positiva (solape > 0% en algún candidato)
    sigue siendo superior a la inferencia por categoría -- nunca se
    fuerza por encima."""
    carpeta = _catalogos_con_plantas(tmp_path, [PLANTA_NORTE, PLANTA_SUR])
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila(
        numero_guia="1",
        motivo_origen_gps="CONFLICTO_REAL_EN_VENTANA(PLANTA_NORTE:score=0.8,solape=45.2%;PLANTA_SUR:score=0.1,solape=0.0%)",
    )])

    resultado = revalidar_origen_por_categoria_sin_candidato_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)

    assert resultado["guias_actualizadas"] == []


def test_conflicto_gps_con_todo_solape_en_cero_no_bloquea():
    """Caso real 464730: ambas plantas midieron 0.0% de solape -- un
    empate en cero no es evidencia real, nunca debe bloquear."""
    assert conflicto_gps_tiene_evidencia_real(
        "CONFLICTO_REAL_EN_VENTANA(AZA_COLINA:score=0.0026,solape=0.0%;AZA_RENCA:score=0.0,solape=0.0%)"
    ) is False


def test_conflicto_gps_en_cero_no_bloquea_la_revalidacion(tmp_path):
    """Caso real 464730, end-to-end: GPS `CONFLICTO_REAL_EN_VENTANA` con
    0.0% de solape en ambos candidatos no bloquea la resolución por
    categoría."""
    carpeta = _catalogos_con_plantas(tmp_path, [PLANTA_NORTE, PLANTA_SUR])
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila(
        numero_guia="1",
        motivo_origen_gps="CONFLICTO_REAL_EN_VENTANA(PLANTA_NORTE:score=0.0026,solape=0.0%;PLANTA_SUR:score=0.0,solape=0.0%)",
    )])

    resultado = revalidar_origen_por_categoria_sin_candidato_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)

    assert resultado["guias_actualizadas"] == ["1"]
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        fila = next(csv.DictReader(archivo, delimiter=";"))
    assert fila["planta_origen_nombre"] == "PLANTA NORTE"


def test_detencion_real_fuera_de_geocerca_bloquea_siempre(tmp_path):
    carpeta = _catalogos_con_plantas(tmp_path, [PLANTA_NORTE, PLANTA_SUR])
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila(
        numero_guia="1", motivo_origen_gps="DETENCION_REAL_FUERA_DE_TODA_GEOCERCA(...)",
    )])

    resultado = revalidar_origen_por_categoria_sin_candidato_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)

    assert resultado["guias_actualizadas"] == []


def test_evidencia_geocerca_sin_solape_suficiente_no_bloquea(tmp_path):
    """`ORIGEN_GPS_NO_DETERMINADO` (ningún candidato tocó siquiera la
    ventana) es más débil que un conflicto -- nunca bloquea (caso real
    464631)."""
    carpeta = _catalogos_con_plantas(tmp_path, [PLANTA_NORTE, PLANTA_SUR])
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila(
        numero_guia="1", tipo_carga="ROLLOS",
        motivo_origen_gps="EVIDENCIA_GEOCERCA_SIN_SOLAPE_SUFICIENTE(PLANTA_NORTE:solape=0.0%,score=0.0)",
    )])

    resultado = revalidar_origen_por_categoria_sin_candidato_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)

    assert resultado["guias_actualizadas"] == ["1"]


def test_idempotente(tmp_path):
    carpeta = _catalogos_con_plantas(tmp_path, [PLANTA_NORTE, PLANTA_SUR])
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila(numero_guia="1")])

    r1 = revalidar_origen_por_categoria_sin_candidato_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)
    r2 = revalidar_origen_por_categoria_sin_candidato_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)

    assert r1["guias_actualizadas"] == ["1"]
    assert r2["guias_actualizadas"] == []  # ya resuelto -- nada más que hacer


# ============================================================
# Regresión real -- 464730/464631/464529 (lote 2). Copia del dataset
# real en tmp_path -- sin OCR nuevo, sin escribir nada en producción.
# ============================================================

@pytest.mark.skipif(not DATOS_REALES_DISPONIBLES, reason="G:\\Mi unidad\\Atlas no disponible en esta máquina")
def test_regresion_real_lote_2_convergen_a_aza_colina_sin_preguntar(tmp_path):
    """Verifica el ESTADO FINAL correcto sobre el dataset real, sin asumir
    CUÁL mecanismo lo resolvió -- la operación real converge de forma
    continua (otros revalidadores, p. ej. correlación GPS de guías
    vecinas, pueden alcanzar el mismo origen antes de que corra esta
    revalidación puntual). Cada guía del lote 2 que siga sin origen antes
    de esta llamada debe converger AQUÍ, por categoría/destino; una que
    ya haya convergido por otra vía real sigue siendo AZA COLINA -- nunca
    otra planta ni "sin determinar"."""
    import shutil
    dataset = tmp_path / "dataset.csv"
    shutil.copy2(CSV_REAL, dataset)
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        filas_antes = {f["numero_guia"]: f for f in csv.DictReader(archivo, delimiter=";")}

    esperadas = {"464730", "464631", "464529"} & set(filas_antes)
    assert esperadas, "el dataset real no tiene el lote esperado -- revalidar manualmente"
    aun_sin_origen = {g for g in esperadas if filas_antes[g]["estado_ruta"] == "ORIGEN_NO_DETERMINADO"}

    revalidar_origen_por_categoria_sin_candidato_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=CATALOGOS_REALES)

    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        filas_despues = {f["numero_guia"]: f for f in csv.DictReader(archivo, delimiter=";")}
    for guia in esperadas:
        assert filas_despues[guia]["planta_origen_nombre"] == "AZA COLINA", guia
    for guia in aun_sin_origen:
        assert filas_despues[guia]["origen_determinado_por"] == "CATEGORIA_DESTINO_EXTERNO", guia
