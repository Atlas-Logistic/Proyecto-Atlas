"""Soporte semántico de Consultas Atlas -- caso real (Desktop 2026-10-02):
"cuantos choferes tenemos confirmados en atlas" -> "19 choferes." mostraba
355 viajes como soporte. El soporte debe ser las entidades de la respuesta.
Recorre el CLI real que usa Desktop (`atlas:consultar-atlas`)."""
from __future__ import annotations

import csv
import json

import pytest

from atlas_core import cli_consulta_atlas
from atlas_core.consultas_atlas import (
    METRICA_LIST_RELACION, ConsultaAtlas, cargar_viajes, ejecutar_consulta_atlas,
)
from atlas_core.soporte_consultas import soporte_semantico
from atlas_core.registro_eventos_operacionales import registrar_evento

COLUMNAS = (
    "viaje_id", "numero_transporte", "fecha", "estado", "numeros_guia", "clientes", "obras_destino",
    "choferes", "patentes_tracto", "patentes_rampla", "materiales", "tipos_carga", "peso_total_viaje_kg",
    "distancia_km", "duracion_min", "direccion_entrega", "localidad_entrega", "estado_ruta",
)
VIAJES = [
    # Valores tomados de viajes reales del reporte vigente (2026-10-02).
    ("0000361953", "02-10-2026", "475222", "EASY RETAIL SA", "EBCO S.A", "PATRICK ORTIZ", "XF3629", "29.6393", "12592"),
    ("0000361786", "01-10-2026", "475183", "AGF ACEROS DE CHILE SPA", "AGF ACEROS", "PATRICK ORTIZ", "XF3629", "26.7205", "11000"),
    ("0000361852", "01-10-2026", "475201", "PRODALAM SA", "EMPRESA CONST SIGRO", "CRISTOPHER RETAMAL", "JD8659", "32.2686", "24000"),
    ("0000361856", "01-10-2026", "475208 | 475209", "COM Y END DE ALAMBRES SPA", "COM Y END DE ALAMBRES SPA",
     "SALOMÓN PIZARRO", "TG8925", "", "20000"),
    ("0000361860", "01-10-2026", "475210", "PRODALAM SA", "CONSTRUCTORA FV SPA", "No encontrado", "", "15.0", ""),
]


@pytest.fixture()
def viajes_csv(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ruta = tmp_path / "viajes.csv"
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        for i, (nt, fecha, guias, cliente, obra, chofer, patente, km, kg) in enumerate(VIAJES):
            escritor.writerow({c: "" for c in COLUMNAS} | {
                "viaje_id": f"v{i}", "numero_transporte": nt, "fecha": fecha, "estado": "CONFIRMADO",
                "numeros_guia": guias, "clientes": cliente, "obras_destino": obra, "choferes": chofer,
                "patentes_tracto": patente, "materiales": "B HORMIGON 12MM", "tipos_carga": "BARRAS",
                "peso_total_viaje_kg": kg, "distancia_km": km, "estado_ruta": "RUTA_CALCULADA" if km else "REQUIERE_REVISION",
            })
    return ruta


def _consultar(pregunta, viajes_csv, capsys):
    cli_consulta_atlas.main([pregunta, "--viajes", str(viajes_csv)])
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_caso_real_conteo_de_choferes_muestra_los_choferes_no_viajes(viajes_csv, capsys):
    salida = _consultar("cuantos choferes tenemos confirmados en atlas", viajes_csv, capsys)

    assert salida["texto_respuesta"] == "3 choferes."  # misma semántica: choferes distintos en viajes
    soporte = salida["resultado"]["soporte"]
    assert soporte["tipo"] == "CHOFERES"
    assert soporte["columnas"] == ["Chofer", "Viajes"]
    assert soporte["filas"] == [["PATRICK ORTIZ", "2"], ["CRISTOPHER RETAMAL", "1"], ["SALOMÓN PIZARRO", "1"]]
    assert soporte["resumen"] == "3 choferes"
    # El contrato anterior se conserva para cualquier otro consumidor.
    assert len(salida["resultado"]["viajes_soporte"]) == len(VIAJES)


def test_conteo_de_clientes_muestra_los_clientes(viajes_csv, capsys):
    salida = _consultar("cuantos clientes tenemos", viajes_csv, capsys)

    soporte = salida["resultado"]["soporte"]
    assert soporte["tipo"] == "CLIENTES"
    assert [f[0] for f in soporte["filas"]][0] == "PRODALAM SA"
    assert len(soporte["filas"]) == 4 == int(salida["texto_respuesta"].split()[0])


def test_conteo_de_obras_muestra_las_obras(viajes_csv, capsys):
    salida = _consultar("cuantas obras tenemos", viajes_csv, capsys)

    soporte = salida["resultado"]["soporte"]
    assert salida["texto_respuesta"] == "5 obras."
    assert soporte["tipo"] == "OBRAS" and len(soporte["filas"]) == 5


def test_listado_de_obras_de_un_cliente_muestra_esas_obras(viajes_csv):
    """"que obras tiene PRODALAM" lo interpreta el proveedor LLM como
    LIST_RELACION obra + filtro cliente; se ejecuta esa misma consulta."""
    viajes = cargar_viajes(viajes_csv)
    consulta = ConsultaAtlas(metrica=METRICA_LIST_RELACION, filtros={"cliente": "PRODALAM SA"}, relacion="obra")

    soporte = soporte_semantico(ejecutar_consulta_atlas(consulta, viajes))

    assert soporte["tipo"] == "OBRAS"
    assert sorted(f[0] for f in soporte["filas"]) == ["CONSTRUCTORA FV SPA", "EMPRESA CONST SIGRO"]


def test_relacion_vehiculo_muestra_patentes(viajes_csv, capsys):
    salida = _consultar("que patentes ha usado Patrick Ortiz", viajes_csv, capsys)

    soporte = salida["resultado"]["soporte"]
    assert soporte["tipo"] == "PATENTES"
    assert soporte["filas"] == [["XF3629", "2"]]


def test_agregado_de_km_muestra_solo_los_viajes_usados_con_su_valor(viajes_csv, capsys):
    salida = _consultar("cuantos km recorrio Patrick Ortiz", viajes_csv, capsys)

    soporte = salida["resultado"]["soporte"]
    assert soporte["tipo"] == "VIAJES"
    assert soporte["columnas"][-1] == "Km calculados"
    assert [f[1] for f in soporte["filas"]] == ["0000361953", "0000361786"]
    assert soporte["resumen"] == "2 viajes usados en el cálculo"


def test_conteo_de_guias_muestra_las_guias(viajes_csv, capsys):
    salida = _consultar("cuantas guias hay", viajes_csv, capsys)

    soporte = salida["resultado"]["soporte"]
    assert soporte["tipo"] == "GUIAS"
    assert [f[0] for f in soporte["filas"]] == ["475183", "475201", "475208", "475209", "475210", "475222"]


def test_soporte_no_expone_identificadores_internos(viajes_csv, capsys):
    for pregunta in ("cuantos choferes tenemos confirmados en atlas", "cuantos clientes tenemos",
                     "cuantos km recorrio Patrick Ortiz", "cuantas guias hay"):
        soporte = _consultar(pregunta, viajes_csv, capsys)["resultado"]["soporte"]
        texto = json.dumps(soporte, ensure_ascii=False)
        assert "viaje_id" not in texto and '"v0"' not in texto
        assert all(not c.startswith(("numero_", "estado")) for c in soporte["columnas"])


def test_soporte_visible_de_estadias_no_expone_codigos_internos(viajes_csv, capsys, tmp_path):
    registrar_evento(
        raiz=tmp_path, tipo_evento="TIENE_ESTADIA", numero_transporte="0000361953", origen="TEST",
        estado_gestion="REPORTADA", enriquecimiento={"viaje_id": "interno-1", "numeros_guia": ["475222"],
        "fecha_operacional": "2026-10-02", "snapshot": {"chofer": "PATRICK ORTIZ"}, "vinculo_completo": True},
    )
    cli_consulta_atlas.main(["estadías pendientes", "--viajes", str(viajes_csv), "--raiz-atlas", str(tmp_path)])
    salida = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    soporte = salida["resultado"]["soporte"]
    texto = json.dumps(soporte, ensure_ascii=False)
    assert soporte["tipo"] == "ESTADIAS"
    assert soporte["columnas"] == ["Fecha", "Transporte", "Guías", "Chofer", "Estado de confirmación"]
    assert soporte["filas"] == [["2026-10-02", "0000361953", "475222", "PATRICK ORTIZ", "Pendiente de confirmación"]]
    assert "TIENE_ESTADIA" not in texto and "tipo_evento" not in texto and "interno-1" not in texto
