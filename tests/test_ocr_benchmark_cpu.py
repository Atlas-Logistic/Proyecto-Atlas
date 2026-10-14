from __future__ import annotations

import json

import pytest

import ocr_benchmark_cpu as banco


def test_preparar_copia_sin_modificar_origen(tmp_path):
    origen = tmp_path / "original.jpeg"
    origen.write_bytes(b"foto-real-aislada")
    manifiesto = tmp_path / "manifiesto.json"
    manifiesto.write_text(json.dumps({"muestras": [{"id": "a", "origen": str(origen), "archivo": "a.jpeg"}]}), encoding="utf-8")
    resultado = banco.preparar_banco(manifiesto, tmp_path / "banco")
    assert origen.read_bytes() == b"foto-real-aislada"
    assert (tmp_path / "banco" / "a.jpeg").read_bytes() == origen.read_bytes()
    assert resultado["muestras"][0]["id"] == "a"


def test_comparar_mide_y_evalua_campos_con_dobles(tmp_path, monkeypatch):
    manifiesto = tmp_path / "manifiesto.json"
    manifiesto.write_text(json.dumps({"muestras": [{"id": "a", "archivo": "a.jpeg", "esperado": {"cliente": "ACME SA"}}]}), encoding="utf-8")
    (tmp_path / "a.jpeg").write_bytes(b"imagen")

    class Proveedor:
        def leer_texto(self, _ruta): return ["texto"]
        def cerrar(self): pass

    monkeypatch.setattr("atlas_core.extractor.extraer_datos", lambda _lineas: {"cliente": "ACME SA"})
    resultado = banco.comparar(manifiesto, tmp_path, fabrica=lambda _nombre: Proveedor())
    assert set(resultado["motores"]) == {"paddleocr_cpu", "easyocr"}
    assert resultado["motores"]["easyocr"][0]["campos"]["cliente"]["correcto"] is True


def test_cli_bloquea_ocr_con_pull_activo(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(banco, "pull_activo", lambda: True)
    salida = banco.main(["comparar", "--confirmar-ventana-segura", "--manifiesto", str(tmp_path / "m.json"),
                          "--directorio", str(tmp_path), "--salida", str(tmp_path / "r.json")])
    assert salida == 2
    assert "BLOQUEADO" in capsys.readouterr().err
