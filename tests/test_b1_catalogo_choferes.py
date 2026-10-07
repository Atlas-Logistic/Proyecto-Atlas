"""B1 -- catálogo de choferes (registrados / activos / inactivos / con y sin
viajes) distinto de los choferes presentes en viajes. Fixtures sintéticas:
nunca G: ni datos productivos."""
from __future__ import annotations

import csv
import hashlib
import json

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.b1_operador import OperadorB1, interpretar_determinista
from atlas_core.procesamiento_masivo import COLUMNAS

RUT_ANA, RUT_BRUNO, RUT_FELIPE = "12345678-5", "15432876-9", "16789012-1"
RUT_FUERA_CATALOGO = "17345678-6"


@pytest.fixture
def raiz(tmp_path):
    raiz = tmp_path / "AtlasCopia"
    cat, actual = raiz / "catalogos_privados", raiz / "operacion" / "actual"
    cat.mkdir(parents=True)
    actual.mkdir(parents=True)
    (cat / "choferes.json").write_text(json.dumps({
        "123456785": {"nombre": "ANA ROJAS", "rut": RUT_ANA, "aliases": ["ANITA ROJAS"], "activo": True},
        "154328769": {"nombre": "BRUNO DIAZ", "rut": RUT_BRUNO, "aliases": [], "activo": True},
        "PENDIENTE00000001": {"nombre": "CARLA SOTO", "aliases": [], "activo": True},
        "PENDIENTE00000002": {"nombre": "DIEGO PAZ", "aliases": [], "activo": True},
        "PENDIENTE00000003": {"nombre": "DIEGO PAZ", "aliases": [], "activo": True},
        "167890121": {"nombre": "FELIPE LARA", "rut": RUT_FELIPE, "aliases": [], "activo": False},
    }), encoding="utf-8")
    (cat / "vehiculos.json").write_text(json.dumps({"version": 1, "vehiculos": []}), encoding="utf-8")
    filas = [
        # ANA por RUT, aunque el nombre leído sea otro (incluso el de BRUNO).
        ("500001", "05-09-2026", "BRUNO DIAZ", RUT_ANA),
        # CARLA (sin RUT canónico) por nombre único.
        ("500002", "20-09-2026", "CARLA SOTO", ""),
        # DIEGO PAZ: dos registros sin RUT con el mismo nombre -> ambiguo.
        ("500003", "21-09-2026", "DIEGO PAZ", ""),
        # Chofer presente en viajes pero ausente del catálogo.
        ("500004", "22-09-2026", "ZETA FUERA", RUT_FUERA_CATALOGO),
    ]
    with (actual / "analisis_completo_guias.csv").open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        for guia, fecha, chofer, rut in filas:
            fila = {c: "" for c in COLUMNAS}
            fila.update(archivo=f"{guia}.jpeg", numero_guia=guia, numero_transporte=f"00009{guia}", fecha=fecha,
                        chofer=chofer, rut_chofer=rut, estado_procesamiento="OK")
            escritor.writerow(fila)
    return raiz


def _huella(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _leer(raiz, texto):
    r = OperadorB1(raiz).atender("c", texto)
    assert r["estado"] == "RESULTADO_LECTURA" and r["accion"] == "CHOFER_CONSULTAR", r
    return r


def _nombres(r):
    return sorted(c["nombre"] for c in r["resultado"]["choferes"])


# 1 / 2 -- catálogo, nunca los choferes de viajes.csv
@pytest.mark.parametrize("texto", ["¿Cuántos choferes están registrados?", "¿Cuántos choferes están en el catálogo?"])
def test_registrados_y_catalogo_cuentan_el_catalogo(raiz, texto):
    r = _leer(raiz, texto)
    assert r["resultado"]["resumen"] == {"registrados": 6, "activos": 5, "inactivos": 1,
                                         "con_viajes": 2, "sin_viajes": 4}
    assert r["mensaje"].startswith("6 choferes registrados en el catálogo")
    assert "ZETA FUERA" not in str(r)


# 3
def test_activos_e_inactivos_usan_el_estado_del_catalogo(raiz):
    activos = _leer(raiz, "¿Cuántos choferes están activos?")
    assert activos["resultado"]["total"] == 5 and "FELIPE LARA" not in _nombres(activos)
    inactivos = _leer(raiz, "¿Cuántos están inactivos?")
    assert inactivos["resultado"]["total"] == 1 and _nombres(inactivos) == ["FELIPE LARA"]


# 4
def test_trabajaron_sigue_siendo_consulta_de_viajes(raiz):
    assert interpretar_determinista("¿Cuántos choferes trabajaron?") is None
    assert interpretar_determinista("¿Qué choferes hicieron viajes este mes?") is None
    assert OperadorB1(raiz).atender("c", "¿Cuántos choferes trabajaron?")["estado"] == "NO_INTERPRETADA"


# 5 / 6
def test_con_y_sin_viajes_cruzan_catalogo_y_dataset(raiz):
    con = _leer(raiz, "¿Cuántos choferes tienen viajes?")
    assert con["resultado"]["total"] == 2 and _nombres(con) == ["ANA ROJAS", "CARLA SOTO"]
    sin = _leer(raiz, "¿Cuántos choferes del catálogo no tienen viajes?")
    assert sin["resultado"]["total"] == 4
    assert _nombres(sin) == ["BRUNO DIAZ", "DIEGO PAZ", "DIEGO PAZ", "FELIPE LARA"]


# 7
def test_el_cruce_prioriza_el_rut_canonico(raiz):
    con = _leer(raiz, "¿Cuántos choferes tienen viajes?")
    # La guía 500001 dice "BRUNO DIAZ" pero trae el RUT de ANA: cuenta ANA.
    assert "ANA ROJAS" in _nombres(con) and "BRUNO DIAZ" not in _nombres(con)


# 8
def test_fallback_nominal_solo_si_es_unico(raiz):
    con = _leer(raiz, "¿Cuántos choferes tienen viajes?")
    assert "CARLA SOTO" in _nombres(con)       # nombre único, sin RUT canónico
    assert "DIEGO PAZ" not in _nombres(con)    # dos registros con ese nombre: nunca se elige


# 9
def test_fallback_nominal_no_crea_ni_confirma_identidad(raiz):
    catalogo, dataset = raiz / "catalogos_privados" / "choferes.json", raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    antes = (_huella(catalogo), _huella(dataset))
    con = _leer(raiz, "¿Cuántos choferes tienen viajes?")
    assert (_huella(catalogo), _huella(dataset)) == antes
    carla = next(c for c in con["resultado"]["choferes"] if c["nombre"] == "CARLA SOTO")
    assert "rut" not in carla
    assert "rut" not in json.loads(catalogo.read_text(encoding="utf-8"))["PENDIENTE00000001"]
    assert CapaAccionesOperacionales(raiz).auditoria() == []


# 10
def test_periodo_limita_con_viajes(raiz):
    r = _leer(raiz, "¿Cuántos choferes tienen viajes entre 01-09-2026 y 10-09-2026?")
    assert r["resultado"]["periodo"] == {"desde": "2026-09-01", "hasta": "2026-09-10"}
    assert _nombres(r) == ["ANA ROJAS"]
    assert r["resultado"]["resumen"]["con_viajes"] == 1 and r["resultado"]["resumen"]["sin_viajes"] == 5
    assert "entre el 01-09-2026 y el 10-09-2026" in r["mensaje"]


# 11 / 15
def test_inactivar_conserva_historico_y_repetir_es_idempotente(raiz):
    catalogo = raiz / "catalogos_privados" / "choferes.json"
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    vehiculos = raiz / "catalogos_privados" / "vehiculos.json"
    antes = json.loads(catalogo.read_text(encoding="utf-8"))["123456785"]
    huellas = (_huella(dataset), _huella(vehiculos))
    b1 = OperadorB1(raiz)
    previa = b1.atender("c", "Pon inactiva a Ana Rojas")
    assert previa["estado"] == "PREVIEW_PENDIENTE"
    assert (previa["preview"]["valor_actual"], previa["preview"]["valor_propuesto"]) == ({"activo": True}, {"activo": False})
    e = b1.atender("c", "sí")
    assert e["estado"] == "EJECUTADA", e
    assert e["resultado"]["entidad"] == {"nombre": "ANA ROJAS"}
    assert (e["resultado"]["antes"], e["resultado"]["despues"]) == ({"activo": True}, {"activo": False})
    despues = json.loads(catalogo.read_text(encoding="utf-8"))["123456785"]
    assert despues == {**antes, "activo": False}   # nombre, RUT y alias intactos; nunca se borra
    assert (_huella(dataset), _huella(vehiculos)) == huellas  # viajes y vehículos intactos
    # sigue contando como chofer con viajes (histórico intacto), ahora inactivo
    con = _leer(raiz, "¿Cuántos choferes tienen viajes?")
    assert next(c for c in con["resultado"]["choferes"] if c["nombre"] == "ANA ROJAS")["activo"] is False
    # repetir la misma orden: nada que confirmar, sin nueva escritura ni auditoría
    huella_catalogo = _huella(catalogo)
    repetida = b1.atender("c", "Pon inactiva a Ana Rojas")
    assert repetida["estado"] == "SIN_CAMBIOS" and "ya está INACTIVO" in repetida["mensaje"]
    assert _huella(catalogo) == huella_catalogo
    assert len(CapaAccionesOperacionales(raiz).auditoria()) == 1


# 12
def test_cero_candidatos_pide_aclaracion(raiz):
    b1 = OperadorB1(raiz)
    r = b1.atender("c", "Pon inactivo a Pedro Nadie")
    assert r["estado"] == "ACLARACION_REQUERIDA" and r["candidatos"] == []
    assert b1.pendiente("c") is None


# 13
def test_varios_candidatos_pide_aclaracion_sin_claves_internas(raiz):
    b1 = OperadorB1(raiz)
    r = b1.atender("c", "Pon inactivo a Diego Paz")
    assert r["estado"] == "ACLARACION_REQUERIDA" and len(r["candidatos"]) == 2
    assert b1.pendiente("c") is None
    assert "PENDIENTE0000" not in json.dumps(r, ensure_ascii=False)
    assert b1.atender("c", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"


# 14
def test_preview_y_resultado_no_exponen_ids_internos(raiz):
    b1 = OperadorB1(raiz)
    preview = b1.atender("c", "Pon inactiva a Carla Soto")
    assert preview["estado"] == "PREVIEW_PENDIENTE"
    # Contrato que consume Desktop: entidad.nombre + valor_actual/valor_propuesto, sin id.
    assert preview["preview"]["entidad"] == {"nombre": "CARLA SOTO"}
    assert "id" not in preview["preview"]["entidad"]
    assert (preview["preview"]["valor_actual"], preview["preview"]["valor_propuesto"]) == ({"activo": True}, {"activo": False})
    texto = json.dumps(preview, ensure_ascii=False)
    assert "PENDIENTE00000001" not in texto and "CHOFER_CAMBIAR_ESTADO" not in preview["mensaje"]
    ejecutada = b1.atender("c", "sí")
    assert ejecutada["resultado"]["entidad"] == {"nombre": "CARLA SOTO"}
    assert (ejecutada["resultado"]["antes"], ejecutada["resultado"]["despues"]) == ({"activo": True}, {"activo": False})
    assert "PENDIENTE00000001" not in json.dumps(ejecutada, ensure_ascii=False)
    # reactivar: no -> sí
    reactivar = b1.atender("c", "Reactiva a Carla Soto")
    assert (reactivar["preview"]["valor_actual"], reactivar["preview"]["valor_propuesto"]) == ({"activo": False}, {"activo": True})
    assert "PENDIENTE00000001" not in json.dumps(reactivar, ensure_ascii=False)
    lectura = _leer(raiz, "¿Cuántos choferes están registrados?")
    assert "123456785" not in json.dumps(lectura, ensure_ascii=False)
    assert all(set(c) <= {"nombre", "activo", "con_viajes", "rut"} for c in lectura["resultado"]["choferes"])


# Dataset real (07-10-2026): evidencia JSON por fila > 131072 caracteres, el
# límite por defecto de ``csv`` -- la consulta de catálogo no debe caerse.
def test_dataset_con_campo_amplio_no_rompe_la_consulta(raiz):
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    with dataset.open("a", newline="", encoding="utf-8-sig") as archivo:
        fila = {c: "" for c in COLUMNAS}
        fila.update(archivo="500005.jpeg", numero_guia="500005", fecha="23-09-2026", chofer="ANA ROJAS",
                    rut_chofer=RUT_ANA, metricas_procesamiento_json="x" * 200_000)
        csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";").writerow(fila)
    r = _leer(raiz, "¿Cuántos choferes están registrados?")
    assert r["resultado"]["resumen"]["registrados"] == 6


# Estado de UN chofer concreto: lectura directa, nunca la lista general ni
# un preview de cambio de estado.
@pytest.mark.parametrize("texto", [
    "Felipe Lara está activo?", "¿Felipe Lara está inactivo?", "¿Está activo Felipe Lara?",
    "¿Está inactivo Felipe Lara?", "¿Cuál es el estado de Felipe Lara?", "¿Felipe Lara está habilitado?",
])
def test_estado_de_un_chofer_inactivo_responde_directo(raiz, texto):
    catalogo = raiz / "catalogos_privados" / "choferes.json"
    antes = _huella(catalogo)
    b1 = OperadorB1(raiz)
    r = b1.atender("c", texto)
    assert r["estado"] == "RESULTADO_LECTURA" and r["accion"] == "CHOFER_CONSULTAR", r
    assert r["mensaje"] == "FELIPE LARA está INACTIVO."
    assert r["resultado"]["total"] == 1 and _nombres(r) == ["FELIPE LARA"]
    assert "167890121" not in json.dumps(r, ensure_ascii=False)
    assert _huella(catalogo) == antes and b1.pendiente("c") is None
    assert CapaAccionesOperacionales(raiz).auditoria() == []


def test_estado_de_un_chofer_activo(raiz):
    r = _leer(raiz, "¿Está activo Ana Rojas?")
    assert r["mensaje"] == "ANA ROJAS está ACTIVO."


def test_estado_de_chofer_inexistente_pide_aclaracion_sin_lista_general(raiz):
    b1 = OperadorB1(raiz)
    r = b1.atender("c", "¿Pedro Nadie está activo?")
    assert r["estado"] == "ACLARACION_REQUERIDA" and r["candidatos"] == []
    assert "resultado" not in r and b1.pendiente("c") is None


def test_estado_de_chofer_ambiguo_pide_aclaracion_sin_lista_general(raiz):
    b1 = OperadorB1(raiz)
    r = b1.atender("c", "¿Diego Paz está activo?")
    assert r["estado"] == "ACLARACION_REQUERIDA" and len(r["candidatos"]) == 2
    assert all(set(c) <= {"nombre", "activo", "rut"} for c in r["candidatos"])
    assert "resultado" not in r and "PENDIENTE0000" not in json.dumps(r, ensure_ascii=False)
    assert b1.pendiente("c") is None


def test_consultas_generales_de_estado_no_cambian(raiz):
    activos = _leer(raiz, "¿Cuántos choferes están activos?")
    assert activos["resultado"]["total"] == 5 and not activos["resultado"]["chofer_individual"]
    inactivos = _leer(raiz, "¿Quiénes están inactivos?")
    assert inactivos["resultado"]["total"] == 1 and _nombres(inactivos) == ["FELIPE LARA"]
    assert not inactivos["resultado"]["chofer_individual"]
