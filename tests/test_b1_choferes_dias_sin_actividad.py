"""B1 -- choferes ACTIVOS del catálogo con más de N días sin actividad
("¿cuántos choferes tienen más de 30 días sin cargar?"). Fixtures
sintéticas con reloj fijo: nunca G: ni datos productivos."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.b1_operador import OperadorB1, interpretar_determinista
from atlas_core.procesamiento_masivo import COLUMNAS

HOY = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)  # 07-10-2026 en Chile
CHOFERES = {
    # clave: (nombre, rut, activo, fechas de sus guías)
    "123456785": ("ANA ROJAS", "12345678-5", True, ["01-09-2026", "07-09-2026"]),       # 30 días
    "154328769": ("BRUNO DIAZ", "15432876-9", True, ["06-09-2026"]),                     # 31 días
    "167890121": ("CARLA SOTO", "16789012-1", True, ["01-07-2026", "08-08-2026"]),       # 60 días
    "173456786": ("DIEGO PAZ", "17345678-6", True, ["07-08-2026"]),                      # 61 días
    "144444442": ("ELENA RIOS", "14444444-2", True, []),                                 # sin viajes
    "PENDIENTE00000001": ("FELIPE LARA", "", False, ["01-01-2026"]),                      # inactivo
    "PENDIENTE00000002": ("GABRIEL VEGA", "", True, ["05-10-2026"]),                      # 2 días (por nombre)
}


@pytest.fixture
def raiz(tmp_path):
    raiz = tmp_path / "AtlasCopia"
    cat, actual = raiz / "catalogos_privados", raiz / "operacion" / "actual"
    cat.mkdir(parents=True)
    actual.mkdir(parents=True)
    (cat / "choferes.json").write_text(json.dumps({
        clave: {"nombre": nombre, **({"rut": rut} if rut else {}), "aliases": [], "activo": activo}
        for clave, (nombre, rut, activo, _) in CHOFERES.items()
    }), encoding="utf-8")
    (cat / "vehiculos.json").write_text(json.dumps({"version": 1, "vehiculos": []}), encoding="utf-8")
    guia = 600000
    with (actual / "analisis_completo_guias.csv").open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        for nombre, rut, _, fechas in CHOFERES.values():
            for fecha in fechas:
                guia += 1
                fila = {c: "" for c in COLUMNAS}
                fila.update(archivo=f"{guia}.jpeg", numero_guia=str(guia), fecha=fecha, chofer=nombre,
                            rut_chofer=rut, estado_procesamiento="OK")
                escritor.writerow(fila)
    return raiz


def _preguntar(raiz, texto):
    r = OperadorB1(raiz, reloj=lambda: HOY).atender("c", texto)
    assert r["estado"] == "RESULTADO_LECTURA" and r["accion"] == "CHOFER_CONSULTAR", r
    return r


def _filas(r):
    return [(c["nombre"], c["ultimo_viaje"], c["dias_sin_actividad"]) for c in r["resultado"]["choferes"]]


def _huella(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


# 1 / 4 / 7 / 8 / 9 / 10
def test_mas_de_30_dias_sin_cargar(raiz):
    r = _preguntar(raiz, "¿Cuántos choferes tienen más de 30 días sin cargar?")
    assert _filas(r) == [("DIEGO PAZ", "2026-08-07", 61), ("CARLA SOTO", "2026-08-08", 60),
                         ("BRUNO DIAZ", "2026-09-06", 31)]           # 31 entra, ANA (30 exactos) no
    assert "FELIPE LARA" not in json.dumps(r, ensure_ascii=False)  # inactivo excluido
    assert [c["nombre"] for c in r["resultado"]["sin_viajes_registrados"]] == ["ELENA RIOS"]
    assert all("dias_sin_actividad" not in c for c in r["resultado"]["sin_viajes_registrados"])
    assert r["mensaje"].startswith("3 choferes activos llevan más de 30 días sin cargar (al 07-10-2026).")
    assert "Además, 1 chofer activo no tiene viajes registrados." in r["mensaje"]


# 2 / 11
def test_mas_de_15_dias_ordenado_de_mayor_a_menor(raiz):
    r = _preguntar(raiz, "¿Quiénes llevan más de 15 días sin cargar?")
    assert [n for n, _, _ in _filas(r)] == ["DIEGO PAZ", "CARLA SOTO", "BRUNO DIAZ", "ANA ROJAS"]
    assert [d for _, _, d in _filas(r)] == sorted([d for _, _, d in _filas(r)], reverse=True)
    assert "GABRIEL VEGA" not in json.dumps(r, ensure_ascii=False)  # 2 días, por nombre único
    assert r["tablas"][0]["filas"][0] == ["DIEGO PAZ", "07-08-2026", "61"]
    assert r["tablas"][1]["filas"] == [["ELENA RIOS"]]


# 3 / 5
def test_mas_de_60_dias_sin_trabajar(raiz):
    r = _preguntar(raiz, "¿Qué choferes llevan más de 60 días sin trabajar?")
    assert _filas(r) == [("DIEGO PAZ", "2026-08-07", 61)]          # 60 exactos no entra


# 6
def test_variante_sin_viajes_respeta_los_dias(raiz):
    r = _preguntar(raiz, "¿Cuántos choferes tienen más de 20 días sin viajes?")
    assert r["resultado"]["dias"] == 20 and r["resultado"]["total"] == 4
    assert r["mensaje"].startswith("4 choferes activos llevan más de 20 días sin cargar")


def test_no_escribe_nada(raiz):
    catalogo = raiz / "catalogos_privados" / "choferes.json"
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    antes = (_huella(catalogo), _huella(dataset))
    b1 = OperadorB1(raiz, reloj=lambda: HOY)
    b1.atender("c", "¿Cuántos choferes tienen más de 30 días sin cargar?")
    assert (_huella(catalogo), _huella(dataset)) == antes
    assert b1.pendiente("c") is None and CapaAccionesOperacionales(raiz).auditoria() == []
    assert "PENDIENTE0000" not in json.dumps(b1.atender("c", "¿Quiénes llevan más de 1 días sin cargar?"))


# 12
def test_consulta_general_trabajaron_sigue_igual(raiz):
    assert interpretar_determinista("¿Cuántos choferes trabajaron?") is None
    assert OperadorB1(raiz).atender("c", "¿Cuántos choferes trabajaron?")["estado"] == "NO_INTERPRETADA"
    sin = interpretar_determinista("¿Cuántos choferes no tienen viajes?")
    assert sin.parametros == {"estado": "TODOS", "viajes": "SIN"}


# --- Presentación estructurada (tablas) -----------------------------------
# Mismo contrato que el soporte semántico de Consultas que Desktop ya
# renderiza: {tipo, resumen, columnas, filas} con celdas de texto.

def test_mas_de_45_dias_devuelve_tabla_de_dos_filas_ordenada(raiz):
    r = _preguntar(raiz, "¿Cuántos choferes tienen más de 45 días sin cargar?")
    principal = r["tablas"][0]
    assert principal["columnas"] == ["Chofer", "Último viaje", "Días sin cargar"]
    assert principal["filas"] == [["DIEGO PAZ", "07-08-2026", "61"], ["CARLA SOTO", "08-08-2026", "60"]]
    assert principal["filas"] == [[n, f"{u[8:10]}-{u[5:7]}-{u[:4]}", str(d)] for n, u, d in _filas(r)]
    assert r["mensaje"] == ("2 choferes activos llevan más de 45 días sin cargar (al 07-10-2026). "
                            "Además, 1 chofer activo no tiene viajes registrados.")


def test_sin_viajes_van_en_bloque_separado_y_vertical(raiz):
    r = _preguntar(raiz, "¿Quiénes llevan más de 45 días sin cargar?")
    assert len(r["tablas"]) == 2
    sin_viajes = r["tablas"][1]
    assert sin_viajes["resumen"] == "Activos sin viajes registrados (1)"
    assert sin_viajes["columnas"] == ["Chofer"] and sin_viajes["filas"] == [["ELENA RIOS"]]
    assert all("ELENA RIOS" not in c for fila in r["tablas"][0]["filas"] for c in fila)
    # nunca nombres concatenados: ni en el texto ni en una celda
    assert "DIEGO PAZ" not in r["mensaje"] and "ELENA RIOS" not in r["mensaje"]
    assert all(";" not in c and "|" not in c for t in r["tablas"] for fila in t["filas"] for c in fila)


def test_un_resultado_es_una_fila(raiz):
    r = _preguntar(raiz, "¿Cuántos choferes tienen más de 60 días sin cargar?")
    assert r["tablas"][0]["filas"] == [["DIEGO PAZ", "07-08-2026", "61"]]
    assert r["mensaje"].startswith("1 chofer activo lleva más de 60 días sin cargar (al 07-10-2026).")


def test_cero_resultados_sin_tabla_vacia(raiz):
    r = _preguntar(raiz, "¿Cuántos choferes tienen más de 61 días sin cargar?")
    assert r["resultado"]["total"] == 0 and r["resultado"]["choferes"] == []
    assert [t["tipo"] for t in r["tablas"]] == ["choferes_sin_viajes_registrados"]
    assert r["mensaje"].startswith("0 choferes activos llevan más de 61 días sin cargar")


def test_tablas_sin_claves_internas_y_renderizables(raiz):
    r = _preguntar(raiz, "¿Quiénes llevan más de 1 días sin cargar?")
    texto = json.dumps(r["tablas"], ensure_ascii=False)
    assert "PENDIENTE0000" not in texto and "chofer_id" not in texto and "123456785" not in texto
    for t in r["tablas"]:
        assert set(t) == {"tipo", "resumen", "columnas", "filas"}
        assert all(isinstance(c, str) for c in t["columnas"])
        assert all(len(f) == len(t["columnas"]) and all(isinstance(c, str) and c for c in f) for f in t["filas"])


def test_la_semantica_del_resultado_no_cambia(raiz):
    r = _preguntar(raiz, "¿Cuántos choferes tienen más de 30 días sin cargar?")
    assert {k: v for k, v in r["resultado"].items() if k not in {"choferes", "sin_viajes_registrados"}} == {
        "total": 3, "dias": 30, "fecha_referencia": "2026-10-07", "activos": 6, "detalle": False, "modo": "INACTIVIDAD"}
    assert _filas(r) == [("DIEGO PAZ", "2026-08-07", 61), ("CARLA SOTO", "2026-08-08", 60),
                         ("BRUNO DIAZ", "2026-09-06", 31)]


def test_otras_lecturas_de_choferes_no_traen_tablas(raiz):
    r = OperadorB1(raiz, reloj=lambda: HOY).atender("c", "¿Cuántos choferes están registrados?")
    assert r["estado"] == "RESULTADO_LECTURA" and "tablas" not in r
