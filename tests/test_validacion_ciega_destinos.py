from __future__ import annotations

import json

from validacion_ciega_destinos import (
    calcular_metricas,
    clasificar,
    comparar,
    construir_casos,
    ejecutar,
    ejecutar_predicciones,
    recomendar,
    sha256,
)


def test_muestra_cumple_distribucion_y_es_sintetica():
    muestra, gt = construir_casos()
    assert len(muestra) == len(gt) == 64
    distribucion = {
        clase: sum(f["clase_gt"] == clase for f in gt)
        for clase in {f["clase_gt"] for f in gt}
    }
    assert distribucion == {
        "VERIFICABLE_EXACTA": 12,
        "VERIFICABLE_APROXIMADA": 12,
        "CONTRADICCION_COMUNA": 11,
        "CONTRADICCION_REGION": 9,
        "AMBIGUA": 8,
        "SIN_RESULTADOS": 6,
        "DATOS_INSUFICIENTES": 6,
    }
    assert sum(f["caso_especial"] for f in muestra) == 8


def test_ground_truth_se_congela_antes_de_predicciones(tmp_path, monkeypatch):
    eventos = []
    original_sha = sha256

    def registrar_hash(ruta):
        eventos.append(ruta.name)
        return original_sha(ruta)

    monkeypatch.setattr("validacion_ciega_destinos.sha256", registrar_hash)
    ejecutar(tmp_path / "salida")
    assert eventos.index("ground_truth_congelado.csv") < eventos.index(
        "predicciones_congeladas.csv"
    )


def test_predicciones_se_congelan_antes_de_comparar(tmp_path):
    salida = tmp_path / "salida"
    ejecutar(salida)
    assert (salida / "predicciones_congeladas.csv").exists()
    assert (salida / "comparacion.csv").exists()
    assert (salida / "hash_predicciones.txt").read_text().strip() == sha256(
        salida / "predicciones_congeladas.csv"
    )


def test_falso_positivo_tiene_prioridad():
    gt = {
        "clase_gt": "AMBIGUA",
        "requiere_revision_esperado": True,
        "resultado_esperado": "REVISAR",
    }
    pred = {
        "estado_predicho": "VERIFICADA",
        "acepta_coordenadas": True,
        "requiere_revision": False,
    }
    assert clasificar(gt, pred) == "FALSO_POSITIVO"


def test_falso_negativo_se_distingue():
    gt = {
        "clase_gt": "VERIFICABLE_EXACTA",
        "requiere_revision_esperado": False,
        "resultado_esperado": "VERIFICADA",
    }
    pred = {
        "estado_predicho": "REVISAR",
        "acepta_coordenadas": False,
        "requiere_revision": True,
    }
    assert clasificar(gt, pred) == "FALSO_NEGATIVO"


def test_comparador_y_metricas_cubren_todos_los_casos(tmp_path):
    muestra, gt = construir_casos()
    predicciones = ejecutar_predicciones(muestra, tmp_path / "pred.csv")
    comparacion = comparar(gt, predicciones)
    metricas = calcular_metricas(comparacion, predicciones)
    assert len(comparacion) == metricas["casos"] == 64
    assert metricas["falsos_positivos"][1] == 64


def test_determinismo_total(tmp_path):
    resultado = ejecutar(tmp_path / "salida")
    assert resultado["hash_pred"] == resultado["hash_repeticion"]
    assert resultado["metricas"]["determinismo"]["archivos_identicos"]
    assert resultado["metricas"]["determinismo"]["metricas_identicas"]


def test_originales_y_trazabilidad_completos(tmp_path):
    resultado = ejecutar(tmp_path / "salida")
    metricas = resultado["metricas"]
    assert metricas["originales_conservados"] == [64, 64]
    assert metricas["trazabilidad_completa"] == [64, 64]


def test_evaluacion_no_usa_red_ni_credencial_real(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *_: (_ for _ in ()).throw(
            AssertionError("red no autorizada")
        )
    )
    resultado = ejecutar(tmp_path / "salida")
    assert resultado["metricas"]["casos"] == 64


def test_consulta_real_opcional_no_forma_parte_de_manifest(tmp_path):
    salida = tmp_path / "salida"
    ejecutar(salida)
    manifest = json.loads((salida / "manifest_muestra.json").read_text())
    assert manifest["red_permitida"] is False
    assert "OPENROUTESERVICE_API_KEY" not in (salida / "hashes.json").read_text()


def test_recomendacion_exige_criterios_criticos(tmp_path):
    resultado = ejecutar(tmp_path / "salida")
    assert recomendar(resultado["metricas"]) == resultado["recomendacion"]
    metricas = dict(resultado["metricas"])
    metricas["falsos_positivos"] = [1, 64]
    assert recomendar(metricas) == "REQUIERE AJUSTES ANTES DEL PILOTO"
