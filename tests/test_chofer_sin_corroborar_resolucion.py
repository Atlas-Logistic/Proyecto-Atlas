"""Salida humana general para CHOFER_SIN_CORROBORAR, sin OCR ni G:."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

from atlas_core.aplicacion_decisiones import aplicar_decision_obra
from atlas_core.decisiones_pendientes import detectar_decisiones_documento, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    detectar_decisiones_chofer_sin_corroborar_sin_ocr,
    revalidar_chofer_sin_corroborar_por_catalogo_sin_ocr,
)

RUT = "14.418.349-5"


def _raiz(tmp_path, *, chofer="CARLO SIMON NUEVO", rut=RUT, catalogo=None):
    raiz = tmp_path / "Atlas"; actual = raiz / "operacion" / "actual"; actual.mkdir(parents=True)
    catalogos = raiz / "catalogos_privados"; catalogos.mkdir()
    for nombre, contenido in {
        "choferes.json": catalogo or {}, "clientes.json": {"version_formato": 1, "clientes": []},
        "empresas.json": {}, "vehiculos.json": {},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []}, "plantas.json": {"plantas": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    fila = {c: "" for c in COLUMNAS}
    fila.update({"archivo": "473263.jpeg", "numero_guia": "473263", "numero_transporte": "0000356721",
                 "estado_procesamiento": "OK", "chofer": chofer, "rut_chofer": rut,
                 "motivos_revision_documento": "CHOFER_SIN_CORROBORAR", "indicador_revision": "REVISAR",
                 "estado_documental": "REQUIERE_REVISION", "estado_operacional": "REQUIERE_REVISION"})
    with (actual / "analisis_completo_guias.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";"); w.writeheader(); w.writerow(fila)
    return raiz


def _fila(raiz):
    with (raiz / "operacion" / "actual" / "analisis_completo_guias.csv").open(newline="", encoding="utf-8-sig") as f:
        return next(csv.DictReader(f, delimiter=";"))


def test_conocido_con_variante_segura_se_homologa_sin_revision(tmp_path):
    raiz = _raiz(tmp_path, chofer="CARLO SIMONN", catalogo={"144183495": {"nombre": "CARLO SIMON", "rut": RUT, "activo": True}})
    resultado = revalidar_chofer_sin_corroborar_por_catalogo_sin_ocr(raiz_atlas=raiz)
    assert resultado["guias_actualizadas"] == ["473263"]
    assert _fila(raiz)["chofer"] == "CARLO SIMON"
    assert detectar_decisiones_chofer_sin_corroborar_sin_ocr(raiz_atlas=raiz) == []


def test_chofer_nuevo_historico_publica_revision_y_registrar_cierra(tmp_path):
    raiz = _raiz(tmp_path)
    decisiones = detectar_decisiones_chofer_sin_corroborar_sin_ocr(raiz_atlas=raiz)
    assert [d["tipo"] for d in decisiones] == ["CHOFER_DESCONOCIDO"]
    actual = raiz / "operacion" / "actual"; catalogos = raiz / "catalogos_privados"
    generar_artefacto(ruta_dataset=actual / "analisis_completo_guias.csv", carpeta_catalogos=catalogos,
                       decisiones=decisiones, ruta_salida=actual / "decisiones_pendientes.json")
    respuesta = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decisiones[0]["decision_id"], accion="REGISTRAR")
    assert respuesta["ok"] is True
    assert "CHOFER_SIN_CORROBORAR" not in _fila(raiz)["motivos_revision_documento"]
    assert json.loads((catalogos / "choferes.json").read_text(encoding="utf-8"))["144183495"]["nombre"] == "CARLO SIMON NUEVO"
    # ledger terminal: una reconciliación posterior no resucita la tarjeta.
    assert detectar_decisiones_chofer_sin_corroborar_sin_ocr(raiz_atlas=raiz) == []


def test_dos_candidatos_plausibles_piden_confirmacion_no_autocorrigen(tmp_path):
    catalogo = {
        "111111111": {"nombre": "JUAN PEREZ A", "rut": "11.111.111-1", "activo": True},
        "222222222": {"nombre": "JUAN PEREZ B", "rut": "22.222.222-2", "activo": True},
    }
    raiz = _raiz(tmp_path, chofer="JUAN PEREZ", catalogo=catalogo)
    datos = {"número de guía": "473263", "número de transporte": "0000356721", "chofer": "JUAN PEREZ", "RUT del chofer": ""}
    decisiones = detectar_decisiones_documento(archivo="473263.jpeg", datos=datos, carpeta_catalogos=raiz / "catalogos_privados")
    assert [d["tipo"] for d in decisiones if d["tipo"].startswith("CHOFER_")] == ["CHOFER_CANDIDATO"]


def test_confirmar_candidato_aprende_alias_y_cierra_motivo(tmp_path):
    catalogo = {
        "144183495": {"nombre": "CARLO SIMON A", "rut": RUT, "activo": True},
        "10833150K": {"nombre": "CARLO SIMON B", "rut": "10.833.150-K", "activo": True},
    }
    raiz = _raiz(tmp_path, chofer="CARLO SIMON", rut="", catalogo=catalogo)
    decisiones = detectar_decisiones_chofer_sin_corroborar_sin_ocr(raiz_atlas=raiz)
    decision = next(d for d in decisiones if d["tipo"] == "CHOFER_CANDIDATO")
    actual = raiz / "operacion" / "actual"; catalogos = raiz / "catalogos_privados"
    generar_artefacto(ruta_dataset=actual / "analisis_completo_guias.csv", carpeta_catalogos=catalogos,
                       decisiones=decisiones, ruta_salida=actual / "decisiones_pendientes.json")
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="CONFIRMAR", rut_chofer_elegido=RUT)
    assert "CHOFER_SIN_CORROBORAR" not in _fila(raiz)["motivos_revision_documento"]
    assert "CARLO SIMON" in json.loads((catalogos / "choferes.json").read_text(encoding="utf-8"))["144183495"]["aliases"]


def test_cli_confirma_chofer_candidato_con_el_rut_elegido_por_javier(tmp_path):
    catalogo = {
        "144183495": {"nombre": "CARLO SIMON A", "rut": RUT, "activo": True},
        "10833150K": {"nombre": "CARLO SIMON B", "rut": "10.833.150-K", "activo": True},
    }
    raiz = _raiz(tmp_path, chofer="CARLO SIMON", rut="", catalogo=catalogo)
    decision = detectar_decisiones_chofer_sin_corroborar_sin_ocr(raiz_atlas=raiz)[0]
    actual = raiz / "operacion" / "actual"
    generar_artefacto(
        ruta_dataset=actual / "analisis_completo_guias.csv", carpeta_catalogos=raiz / "catalogos_privados",
        decisiones=[decision], ruta_salida=actual / "decisiones_pendientes.json",
    )
    script = Path(__file__).resolve().parents[1] / "aplicar_decision_pendiente.py"
    proceso = subprocess.run(
        [sys.executable, str(script), "--raiz-atlas", str(raiz), "--decision-id", decision["decision_id"],
         "--accion", "CONFIRMAR", "--rut-chofer-elegido", RUT],
        cwd=script.parent, capture_output=True, check=True,
    )
    assert json.loads(proceso.stdout.decode("ascii"))["ok"] is True
    assert "CHOFER_SIN_CORROBORAR" not in _fila(raiz)["motivos_revision_documento"]
