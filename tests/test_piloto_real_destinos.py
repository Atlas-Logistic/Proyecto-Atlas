from __future__ import annotations

import json
import shutil
from pathlib import Path

from piloto_real_destinos import (
    CAMPOS_AUTORIZADOS,
    CASOS,
    _canon,
    _region_compatible_humana,
    preparar,
    recomendar,
    reproducir_desde_congelado,
    sha256,
)


def test_muestra_real_tiene_12_destinos_distintos_y_vista_clara_2351():
    assert len(CASOS) == 12
    assert len({caso["destino_id"] for caso in CASOS}) == 12
    vista = next(caso for caso in CASOS if caso["id_caso"] == "REAL-004")
    assert vista["direccion"] == "VISTA CLARA 2351"
    assert "2401" not in vista["direccion"]


def test_minimizacion_excluye_datos_operacionales_y_cliente():
    assert set(CAMPOS_AUTORIZADOS) == {
        "direccion_original", "comuna_esperada", "region_esperada", "pais"
    }
    assert "cliente" not in CAMPOS_AUTORIZADOS
    assert "rut" not in CAMPOS_AUTORIZADOS
    assert "chofer" not in CAMPOS_AUTORIZADOS


def test_preparacion_congela_manifest_y_ground_truth(tmp_path):
    hashes = preparar(tmp_path)
    assert hashes["manifiesto_definitivo.json"] == sha256(
        tmp_path / "manifiesto_definitivo.json"
    )
    assert hashes["ground_truth_congelado.csv"] == sha256(
        tmp_path / "ground_truth_congelado.csv"
    )
    manifest = json.loads((tmp_path / "manifiesto_definitivo.json").read_text())
    assert manifest["cantidad_casos"] == 12
    assert manifest["maximo_consultas_unicas"] == 12
    assert manifest["modifica_catalogos"] is False


def test_canon_omite_solo_cache_y_duracion():
    base = [{"id_caso": "REAL-001", "estado": "REVISAR", "desde_cache": False,
             "duracion_ms": 10.0}]
    cache = [{"id_caso": "REAL-001", "estado": "REVISAR", "desde_cache": True,
              "duracion_ms": 0.0}]
    assert _canon(base) == _canon(cache)


def test_region_metropolitana_admite_forma_abreviada_del_proveedor():
    assert _region_compatible_humana("REGIÓN METROPOLITANA", "Metropolitana")
    assert not _region_compatible_humana("REGIÓN METROPOLITANA", "Valparaíso")


def test_recomendacion_exige_cero_falsos_positivos_y_determinismo():
    metricas = {
        "casos": 12,
        "falsos_positivos": [0, 12],
        "originales_conservados": [12, 12],
        "trazabilidad_completa": [12, 12],
        "determinismo": {
            "resultados_semanticos_identicos": True,
            "consultas_nuevas_en_repeticion": 0,
        },
    }
    assert recomendar(metricas) == "APTO PARA INTEGRACIÓN OPCIONAL EN MODO REVISIÓN"
    metricas["falsos_positivos"] = [1, 12]
    assert recomendar(metricas) == "REQUIERE AJUSTES ANTES DE USAR DESTINOS REALES"


def test_reprocesamiento_congelado_corrige_la_union_sin_red(tmp_path, monkeypatch):
    origen = Path("validaciones/piloto_real_destinos_2026-07-28")
    salida = tmp_path / "piloto"
    shutil.copytree(origen, salida)
    monkeypatch.setattr(
        "atlas_core.inteligencia.verificacion_destinos._transporte_urllib",
        lambda *_: (_ for _ in ()).throw(AssertionError("red no autorizada")),
    )
    resultado = reproducir_desde_congelado(salida)
    assert resultado["metricas"]["falsos_positivos"] == [0, 12]
    assert resultado["metricas"]["falsos_negativos"] == [0, 12]
    assert resultado["metricas"]["cobertura_confirmaciones"] == [1, 12]
    assert resultado["metricas"]["determinismo"]["consultas_nuevas_en_repeticion"] == 0
