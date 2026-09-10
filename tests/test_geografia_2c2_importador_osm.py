"""GEOGRAFÍA 2C.2 -- importador offline OSM/PBF -> base local Atlas.

Fixture SINTÉTICO (tests/fixtures/osm_rm_muestra.osm, ~3.6 KB, 17 objetos
OSM). Valida el pipeline completo sin dependencias: xml.etree lee el .osm,
`consolidar_filas_rm` filtra RM + deduplica, y `BaseGeograficaLocalSQLite.
importar_filas` persiste. `osmium` sólo se necesita para .pbf real y su
ausencia produce un error aislado y explícito.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas_core.geografia import cargar_geografia
from atlas_core.geografia.base_local import BaseGeograficaLocalSQLite, EstadoConsultaLocal
from atlas_core.geografia.importador_osm import (
    DependenciaImportadorFaltante,
    ElementoOSM,
    consolidar_filas_rm,
    construir_filas_desde_osm,
    fila_cruda_desde_elemento,
    importar_a_sqlite,
    iter_elementos_xml,
    main,
    normalizar_numero_osm,
)

FIXTURE = Path(__file__).parent / "fixtures" / "osm_rm_muestra.osm"
GEO = cargar_geografia("CL")


# ============================================================
# 1. Número de casa -- preservación segura, sin equivalencias OCR
# ============================================================


@pytest.mark.parametrize("entrada,esperado", [
    ("1234", "1234"),
    ("0123", "0123"),        # ceros iniciales preservados
    ("12B", "12B"),          # letra preservada -- NUNCA "128"
    ("O123", "O123"),        # NUNCA "0123"
    ("100-104", "100-104"),  # rango preservado, no se inventa el intermedio
    ("  55 ", "55"),
    ("", ""),
    ("S/N", ""),             # "sin número" explícito -> ""
    ("s/n", ""),
    ("SN", ""),
    ("Sin Número", ""),
])
def test_normalizar_numero_osm(entrada, esperado):
    assert normalizar_numero_osm(entrada) == esperado


# ============================================================
# 2. Extracción por elemento
# ============================================================


def test_fila_cruda_requiere_calle_y_comuna():
    assert fila_cruda_desde_elemento(ElementoOSM("node/1", {"addr:housenumber": "10"}, -70.6, -33.4)) is None
    assert fila_cruda_desde_elemento(ElementoOSM("node/2", {"addr:street": "X"}, -70.6, -33.4)) is None
    ok = fila_cruda_desde_elemento(
        ElementoOSM("node/3", {"addr:street": "X", "addr:city": "Maipú"}, -70.6, -33.4)
    )
    assert ok is not None and ok["numero"] == "" and ok["fuente"] == "OSM node/3"


def test_fila_cruda_null_island_descarta_coordenada_pero_conserva_fila():
    fila = fila_cruda_desde_elemento(
        ElementoOSM("node/9", {"addr:street": "Camino Rinconada", "addr:housenumber": "88",
                               "addr:city": "Maipú"}, 0.0, 0.0)
    )
    assert fila is not None
    assert fila["lon"] is None and fila["lat"] is None   # nunca inventa coordenada
    assert fila["numero"] == "88"


def test_fila_cruda_coordenada_fuera_de_rango_se_descarta():
    fila = fila_cruda_desde_elemento(
        ElementoOSM("node/x", {"addr:street": "X", "addr:city": "Maipú"}, -200.0, -33.4)
    )
    assert fila["lon"] is None and fila["lat"] is None


def test_fila_cruda_way_sin_geometria_no_lleva_coordenada():
    fila = fila_cruda_desde_elemento(
        ElementoOSM("way/100", {"addr:street": "El Bosque Norte", "addr:housenumber": "500",
                                "addr:city": "Las Condes"})
    )
    assert fila["lon"] is None and fila["lat"] is None
    assert fila["fuente"] == "OSM way/100"


# ============================================================
# 3. consolidación -- RM, duplicados, colisiones, determinismo
# ============================================================


def _crudas(*elementos):
    filas = []
    for e in elementos:
        f = fila_cruda_desde_elemento(e)
        if f is not None:
            filas.append(f)
    return filas


def test_filtra_fuera_de_rm_y_comuna_no_resoluble():
    crudas = _crudas(
        ElementoOSM("node/1", {"addr:street": "A", "addr:housenumber": "1", "addr:city": "Providencia"}, -70.6, -33.4),
        ElementoOSM("node/2", {"addr:street": "B", "addr:housenumber": "2", "addr:city": "Valparaíso"}, -71.6, -33.0),
        ElementoOSM("node/3", {"addr:street": "C", "addr:housenumber": "3", "addr:city": "Comuna Falsa"}, -70.6, -33.4),
    )
    filas, conteos = consolidar_filas_rm(crudas, geografia=GEO)
    assert [f["comuna"] for f in filas] == ["13123"]
    assert conteos["fuera_de_rm_descartadas"] == 1
    assert conteos["comuna_no_resuelta_descartadas"] == 1


def test_duplicado_exacto_se_colapsa_determinista():
    e = lambda ref: ElementoOSM(  # noqa: E731
        ref, {"addr:street": "Av X", "addr:housenumber": "10", "addr:city": "Ñuñoa"}, -70.60, -33.45
    )
    filas, conteos = consolidar_filas_rm(_crudas(e("node/5"), e("node/2"), e("node/9")), geografia=GEO)
    assert len(filas) == 1
    assert conteos["duplicados_exactos_colapsados"] == 2
    assert filas[0]["fuente"] == "OSM node/2"   # menor referencia -> determinista


def test_colision_de_clave_se_resuelve_igual_siempre():
    crudas = _crudas(
        ElementoOSM("node/1", {"addr:street": "Av X", "addr:housenumber": "10", "addr:city": "Ñuñoa"}, -70.60, -33.4280),
        ElementoOSM("node/2", {"addr:street": "Av X", "addr:housenumber": "10", "addr:city": "Ñuñoa"}, -70.60, -33.4270),
        ElementoOSM("node/3", {"addr:street": "Av X", "addr:housenumber": "10", "addr:city": "Ñuñoa"}),
    )
    filas_a, _ = consolidar_filas_rm(list(reversed(crudas)), geografia=GEO)
    filas_b, conteos = consolidar_filas_rm(crudas, geografia=GEO)
    assert filas_a == filas_b                      # orden de entrada no cambia el resultado
    assert len(filas_b) == 1
    assert conteos["colisiones_clave_resueltas"] == 2
    # gana la que tiene coordenada; a igualdad, menor (lat, lon, ref)
    assert (filas_b[0]["lat"], filas_b[0]["fuente"]) == (-33.428, "OSM node/1")


def test_direcciones_reales_distintas_se_conservan_como_candidatos():
    crudas = _crudas(
        ElementoOSM("node/1", {"addr:street": "Los Olmos", "addr:housenumber": "100", "addr:city": "Maipú"}, -70.7, -33.5),
        ElementoOSM("node/2", {"addr:street": "Los Olmos", "addr:housenumber": "200", "addr:city": "Maipú"}, -70.7, -33.5),
        ElementoOSM("node/3", {"addr:street": "Los Olmos", "addr:city": "Maipú"}, -70.7, -33.5),
    )
    filas, _ = consolidar_filas_rm(crudas, geografia=GEO)
    assert {f["numero"] for f in filas} == {"100", "200", ""}   # nada se colapsa


def test_salida_ordenada_deterministicamente():
    filas, _ = construir_filas_desde_osm(FIXTURE).filas, None
    claves = [(f["comuna"], f["calle"].upper(), f["numero"]) for f in filas]
    assert claves == sorted(claves)


# ============================================================
# 4. Pipeline completo contra el fixture
# ============================================================


def test_fixture_conteos_exactos():
    r = construir_filas_desde_osm(FIXTURE)
    assert r.lector == "xml.etree (stdlib)"
    assert r.conteos == {
        "objetos_escaneados": 17,
        "con_direccion": 15,
        "rm_pre_consolidacion": 13,
        "fuera_de_rm_descartadas": 1,
        "comuna_no_resuelta_descartadas": 1,
        "duplicados_exactos_colapsados": 1,
        "colisiones_clave_resueltas": 1,
        "filas_escritas": 11,
    }


def test_fixture_preserva_numeros_sin_tocar_caracteres():
    filas = {(f["comuna"], f["calle"]): f for f in construir_filas_desde_osm(FIXTURE).filas}
    assert filas[("13120", "Pasaje Uno")]["numero"] == "0123"
    assert filas[("13113", "Calle Dos")]["numero"] == "12B"
    assert filas[("13130", "Gran Avenida")]["numero"] == "100-104"
    assert filas[("13114", "Camino El Alba")]["numero"] == ""   # era "S/N"


def test_importar_a_sqlite_genera_base_consultable_y_procedencia(tmp_path):
    sqlite = tmp_path / "base_local_rm.sqlite"
    resultado = importar_a_sqlite(FIXTURE, sqlite, reemplazar=True)
    assert resultado.conteos["filas_escritas"] == 11
    assert sqlite.exists()

    proc = sqlite.with_suffix(".sqlite.procedencia.json")
    assert proc.exists()
    meta = json.loads(proc.read_text(encoding="utf-8"))
    assert meta["region_filtro"] == "13"
    assert meta["region_nombre"] == "Metropolitana"
    assert meta["fuente"]["archivo"] == "osm_rm_muestra.osm"
    assert len(meta["fuente"]["sha256"]) == 64
    assert meta["fuente"]["lector"] == "xml.etree (stdlib)"
    assert meta["conteos"]["filas_escritas"] == 11

    base = BaseGeograficaLocalSQLite(sqlite)
    assert base.disponible() is True
    # EXACTA con coordenada real de OSM
    ev = base.consultar(comuna="Providencia", calle="Avenida Providencia", numero="1234")
    assert ev.estado == EstadoConsultaLocal.EXACTA
    assert ev.candidatos[0].coordenadas == (-70.61, -33.428)
    assert ev.candidatos[0].fuente == "OSM node/1"
    # dos direcciones reales -> candidatos, no colapso
    ev_multi = base.consultar(comuna="Maipú", calle="Calle Nueva")
    assert ev_multi.estado == EstadoConsultaLocal.MULTIPLE
    assert {c.numero for c in ev_multi.candidatos} == {"", "742"}
    # "0123" en base: la regla segura de 2C.1 acepta "123" == "0123"
    assert base.consultar(comuna="Ñuñoa", calle="Pasaje Uno", numero="123").numero_confirmado is True
    # "12B" NUNCA se convierte en "128"
    assert base.consultar(
        comuna="La Reina", calle="Calle Dos", numero="128"
    ).estado == EstadoConsultaLocal.NO_ENCONTRADO
    # way sin geometría: dirección conocida, sin coordenada inventada
    ev_way = base.consultar(comuna="Las Condes", calle="El Bosque Norte", numero="500")
    assert ev_way.estado == EstadoConsultaLocal.EXACTA
    assert ev_way.candidatos[0].coordenadas is None


def test_reimportar_es_idempotente(tmp_path):
    sqlite = tmp_path / "base.sqlite"
    importar_a_sqlite(FIXTURE, sqlite, reemplazar=True)
    b1 = BaseGeograficaLocalSQLite(sqlite)
    filas_1 = b1._conexion_lectura().execute(
        "SELECT codigo_comuna, calle_normalizada, numero, lon, lat, fuente FROM direcciones ORDER BY 1,2,3"
    ).fetchall()
    b1.cerrar()
    importar_a_sqlite(FIXTURE, sqlite, reemplazar=True)
    b2 = BaseGeograficaLocalSQLite(sqlite)
    filas_2 = b2._conexion_lectura().execute(
        "SELECT codigo_comuna, calle_normalizada, numero, lon, lat, fuente FROM direcciones ORDER BY 1,2,3"
    ).fetchall()
    b2.cerrar()
    assert filas_1 == filas_2


def test_limite_corta_el_procesamiento(tmp_path):
    r = construir_filas_desde_osm(FIXTURE, limite=2)
    assert r.conteos["con_direccion"] == 2


# ============================================================
# 5. Lectura XML en streaming
# ============================================================


def test_iter_elementos_xml_lee_nodos_y_ways_del_fixture():
    elementos = list(iter_elementos_xml(FIXTURE))
    refs = {e.referencia for e in elementos}
    assert "node/1" in refs and "way/100" in refs
    nodo1 = next(e for e in elementos if e.referencia == "node/1")
    assert nodo1.tags["addr:housenumber"] == "1234"
    assert float(nodo1.lat) == -33.428
    way = next(e for e in elementos if e.referencia == "way/100")
    assert way.lon is None and way.lat is None


# ============================================================
# 6. Dependencia PBF aislada -- error claro, sin contaminar runtime
# ============================================================


def test_pbf_sin_osmium_error_explicito_y_aislado(tmp_path):
    falso = tmp_path / "region.osm.pbf"
    falso.write_bytes(b"no importa el contenido")
    with pytest.raises(DependenciaImportadorFaltante) as exc:
        construir_filas_desde_osm(falso)
    mensaje = str(exc.value)
    assert "requirements-importador-osm.txt" in mensaje
    assert "NO es dependencia del Motor" in mensaje


def test_importador_no_es_importado_por_el_runtime():
    """El Motor en operación nunca debe arrastrar este módulo (ni, por
    tanto, osmium). Se verifica que los módulos de runtime del flujo
    geográfico no lo importan de forma transitiva."""
    import importlib
    import sys

    for nombre in list(sys.modules):
        if nombre.startswith("atlas_core.geografia.importador_osm"):
            del sys.modules[nombre]
    for modulo_runtime in (
        "atlas_core.geografia",
        "atlas_core.geografia.base_local",
        "atlas_core.rutas.destino_entrega",
        "atlas_core.rutas.cache_geocodificacion",
    ):
        importlib.import_module(modulo_runtime)
    assert "atlas_core.geografia.importador_osm" not in sys.modules


def test_extension_no_reconocida_falla_claro(tmp_path):
    malo = tmp_path / "cosa.txt"
    malo.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        construir_filas_desde_osm(malo)


# ============================================================
# 7. CLI
# ============================================================


def test_cli_dry_run_no_escribe_nada(tmp_path, capsys):
    rc = main(["--pbf", str(FIXTURE), "--dry-run"])
    assert rc == 0
    salida = capsys.readouterr().out
    assert "filas=11" in salida
    assert "no se escribió nada" in salida


def test_cli_importa_a_salida_explicita(tmp_path, capsys):
    destino = tmp_path / "rm.sqlite"
    rc = main(["--pbf", str(FIXTURE), "--salida", str(destino), "--reemplazar", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["conteos"]["filas_escritas"] == 11
    assert payload["salida_sqlite"] == str(destino)
    assert destino.exists()
    assert destino.with_suffix(".sqlite.procedencia.json").exists()
