"""GEOGRAFÍA 2C.3 -- importador OFFLINE del maestro territorial INE
(A4A/geoaddress) -> base geográfica local Atlas.

Fixture SINTÉTICO (tests/fixtures/ine_rm_muestra.csv). Valida el pipeline
streaming sin dependencias externas: filtro RM (TILTIL -> TIL TIL por
catálogo territorial), preservación de calle/número TAL CUAL, coordenada
real sólo en coincidencia exacta, nunca inventada, y los cuatro
desenlaces de consulta (DIRECCION_EXACTA / CALLE_CONOCIDA_NUMERO_NO_EN_BASE
/ CALLE_NO_ENCONTRADA / MULTIPLE).
"""
from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from atlas_core.geografia.base_local import (
    BaseGeograficaLocalSQLite,
    evidencia_local_para_direccion,
)
from atlas_core.geografia.importador_ine import (
    contar_dry_run,
    importar_a_sqlite,
    iter_filas_rm,
    main,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ine_rm_muestra.csv"


def _base(tmp_path, **kw):
    sqlite_path = tmp_path / "base_local_rm_ine.sqlite"
    importar_a_sqlite(FIXTURE, sqlite_path, reemplazar=True, chunk=kw.pop("chunk", 4), **kw)
    return BaseGeograficaLocalSQLite(sqlite_path), sqlite_path


# ============================================================
# 1. Conteos exactos del fixture (streaming, chunks pequeños)
# ============================================================


def test_dry_run_conteos_exactos():
    assert contar_dry_run(FIXTURE) == {
        "filas_csv_leidas": 23,
        "malformadas": 1,
        "fuera_de_rm_descartadas": 1,
        "comuna_no_resuelta_descartadas": 1,
        "coordenada_invalida_descartadas": 2,
        "via_vacia_descartadas": 1,
        "aceptadas": 17,
        "filas_enviadas": 0,
        "direcciones_con_multiples_observaciones": 0,
        "direcciones_multipunto": 0,
        "filas_en_tabla": 0,
    }


def test_import_preserva_multiplicidad_sin_ultima_fila(tmp_path):
    _base_obj, sqlite_path = _base(tmp_path)
    meta = json.loads((tmp_path / "base_local_rm_ine.sqlite.procedencia.json").read_text("utf-8"))
    c = meta["conteos"]
    assert c["aceptadas"] == 17
    assert c["filas_enviadas"] == 17
    # gid 1 y gid 20 son la MISMA dirección (CARMEN MENA 529 SAN MIGUEL):
    # ya NO se colapsan a "la última fila" -- ambas filas quedan en la base.
    assert c["direcciones_con_multiples_observaciones"] == 1
    # ...y como sus coordenadas caen en la misma celda espacial (~1 m de
    # diferencia), NO es multipunto: la consulta sigue siendo EXACTA.
    assert c["direcciones_multipunto"] == 0
    assert c["filas_en_tabla"] == 17
    assert BaseGeograficaLocalSQLite(sqlite_path).contar() == 17
    # las DOS observaciones son auditables por gid
    gids = sqlite3.connect(f"file:{sqlite_path.as_posix()}?mode=ro", uri=True).execute(
        "SELECT ref_externa FROM direcciones"
        " WHERE calle_normalizada='CARMEN MENA' AND numero='529' ORDER BY ref_externa"
    ).fetchall()
    assert [g[0] for g in gids] == ["gid=1", "gid=20"]


def test_chunk_pequeno_no_pierde_filas(tmp_path):
    sqlite_path = tmp_path / "b.sqlite"
    importar_a_sqlite(FIXTURE, sqlite_path, reemplazar=True, chunk=1)
    assert BaseGeograficaLocalSQLite(sqlite_path).contar() == 17


# ============================================================
# 2. Seis casos equivalentes a los reales
# ============================================================


@pytest.mark.parametrize("texto,comuna,resultado,con_coord", [
    ("CARMEN MENA 529 SAN MIGUEL", "San Miguel", "DIRECCION_EXACTA", True),
    ("URUGUAY 15 LA CISTERNA", "La Cisterna", "DIRECCION_EXACTA", True),
    ("PUERTA DEL SOL 83 LAS CONDES", "Las Condes", "CALLE_CONOCIDA_NUMERO_NO_EN_BASE", False),
    ("SAN DAMIAN 100 VITACURA", "Vitacura", "DIRECCION_EXACTA", True),
    ("INTERIOR NUEVA 1148 SAN BERNARDO", "San Bernardo", "CALLE_NO_ENCONTRADA", False),
    ("CAMINO A MELIPILLA 10800 MAIPU", "Maipú", "DIRECCION_EXACTA", True),
])
def test_seis_casos(tmp_path, texto, comuna, resultado, con_coord):
    base, _ = _base(tmp_path)
    ev = evidencia_local_para_direccion(base, texto, comuna=comuna)
    assert ev.resultado == resultado
    if resultado == "DIRECCION_EXACTA":
        assert ev.numero_confirmado is True
        assert ev.candidatos[0].coordenadas is not None       # coordenada REAL INE
        assert ev.candidatos[0].ref_externa.startswith("gid=")
    else:
        assert ev.numero_confirmado is False
    if not con_coord:
        # nunca inventa/deja una coordenada como "respuesta"
        assert all(c.coordenadas is None for c in ev.candidatos)


def test_san_damian_cero_inicial_matchea_bajo_regla_segura(tmp_path):
    base, _ = _base(tmp_path)
    # base guarda "0100"; consulta "100" -> confirmado (regla de ceros 2A).
    assert base.consultar(comuna="Vitacura", calle="SAN DAMIAN", numero="100").numero_confirmado
    # y "0100" literal también
    assert base.consultar(comuna="Vitacura", calle="SAN DAMIAN", numero="0100").numero_confirmado
    # un número realmente distinto nunca
    assert base.consultar(comuna="Vitacura", calle="SAN DAMIAN", numero="1000").numero_confirmado is False


def test_puerta_del_sol_multiples_numeros_es_evidencia_de_calle(tmp_path):
    base, _ = _base(tmp_path)
    ev = base.consultar(comuna="Las Condes", calle="PUERTA DEL SOL", numero="")
    assert ev.estado.value == "MULTIPLE"
    assert {c.numero for c in ev.candidatos} == {"19", "36", "100"}


# ============================================================
# 3. Preservación / normalización segura
# ============================================================


def test_preserva_calle_canonica_y_numero_tal_cual(tmp_path):
    base, sqlite_path = _base(tmp_path)
    filas = sqlite3.connect(f"file:{sqlite_path.as_posix()}?mode=ro", uri=True).execute(
        "SELECT calle_canonica, numero FROM direcciones WHERE calle_normalizada='SAN DAMIAN' ORDER BY numero"
    ).fetchall()
    assert filas == [("SAN DAMIAN", "0100"), ("SAN DAMIAN", "0149")]  # ceros preservados


def test_tiltil_se_normaliza_por_catalogo_territorial(tmp_path):
    base, _ = _base(tmp_path)
    ev = base.consultar(comuna="Til Til", calle="PLAZA DE ARMAS", numero="7")
    assert ev.resultado == "DIRECCION_EXACTA"
    assert ev.codigo_comuna == "13303"


def test_via_con_coma_va_entre_comillas_y_se_parsea(tmp_path):
    base, sqlite_path = _base(tmp_path)
    fila = sqlite3.connect(f"file:{sqlite_path.as_posix()}?mode=ro", uri=True).execute(
        "SELECT calle_canonica, numero, alias FROM direcciones WHERE codigo_comuna='13202'"
    ).fetchone()
    assert fila == ("LOS OLMOS, PARCELA 4", "8", "LOTE 4")


def test_alias_se_guarda_pero_no_participa_en_la_resolucion(tmp_path):
    base, _ = _base(tmp_path)
    # el alias "LOTE 4" NO debe permitir encontrar la calle por su alias
    assert base.consultar(comuna="Pirque", calle="LOTE 4", numero="8").resultado == "CALLE_NO_ENCONTRADA"
    # pero sí está persistido junto a la calle real
    ev = base.consultar(comuna="Pirque", calle="LOS OLMOS, PARCELA 4", numero="8")
    assert ev.candidatos[0].alias == "LOTE 4"


def test_hnum_vacio_produce_fila_de_calle_sin_numero(tmp_path):
    base, _ = _base(tmp_path)
    ev = base.consultar(comuna="Colina", calle="VIA RURAL", numero="")
    assert ev.calle_conocida is True
    assert ev.candidatos[0].numero == ""


# ============================================================
# 4. Nunca inventa / corrige coordenadas
# ============================================================


def test_coordenada_cero_cero_y_fuera_de_chile_se_descartan(tmp_path):
    # gid 17 (0,0 en Las Condes) y gid 18 (-120,10 en Maipú) no entran
    base, sqlite_path = _base(tmp_path)
    con = sqlite3.connect(f"file:{sqlite_path.as_posix()}?mode=ro", uri=True)
    assert con.execute(
        "SELECT COUNT(*) FROM direcciones WHERE calle_normalizada IN ('CERRO PLOMO','MAR DEL PLATA')"
    ).fetchone()[0] == 0


def test_calle_conocida_no_arrastra_coordenada_de_otro_numero(tmp_path):
    base, _ = _base(tmp_path)
    ev = base.consultar(comuna="Las Condes", calle="PUERTA DEL SOL", numero="83")
    assert ev.resultado == "CALLE_CONOCIDA_NUMERO_NO_EN_BASE"
    assert all(c.coordenadas is None for c in ev.candidatos)


# ============================================================
# 5. ZIP + CLI
# ============================================================


def test_importa_desde_zip(tmp_path):
    zip_path = tmp_path / "ine.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(FIXTURE, arcname="a4a_cl_geoaddress_test.csv")
    sqlite_path = tmp_path / "b.sqlite"
    conteos = importar_a_sqlite(zip_path, sqlite_path, reemplazar=True)
    assert conteos["filas_en_tabla"] == 17
    meta = json.loads((tmp_path / "b.sqlite.procedencia.json").read_text("utf-8"))
    assert meta["dataset"]["csv_interno"] == "a4a_cl_geoaddress_test.csv"
    assert len(meta["dataset"]["sha256"]) == 64
    assert meta["dataset"]["corte"] == "2023-12"
    assert meta["dataset"]["paquete"] == "pk0004.02"


def test_cli_dry_run(tmp_path, capsys):
    assert main(["--csv", str(FIXTURE), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "aceptadas=17" in out
    assert "no se escribió nada" in out


def test_cli_import_json(tmp_path, capsys):
    destino = tmp_path / "salida.sqlite"
    assert main(["--csv", str(FIXTURE), "--salida", str(destino), "--reemplazar", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["conteos"]["filas_en_tabla"] == 17
    assert destino.exists()
    assert (tmp_path / "salida.sqlite.procedencia.json").exists()


# ============================================================
# 6. Aislamiento del runtime
# ============================================================


def test_importador_ine_no_lo_importa_el_runtime():
    import importlib
    import sys

    for nombre in list(sys.modules):
        if nombre.startswith("atlas_core.geografia.importador_ine"):
            del sys.modules[nombre]
    for modulo in (
        "atlas_core.geografia",
        "atlas_core.geografia.base_local",
        "atlas_core.rutas.destino_entrega",
        "atlas_core.rutas.cache_geocodificacion",
        "atlas_core.procesamiento_masivo",
    ):
        importlib.import_module(modulo)
    assert "atlas_core.geografia.importador_ine" not in sys.modules


def test_importador_ine_solo_stdlib():
    import atlas_core.geografia.importador_ine as mod

    fuente = Path(mod.__file__).read_text("utf-8")
    for prohibido in ("import osmium", "osmium.", "import pandas", "import numpy"):
        assert prohibido not in fuente


def test_cabecera_inesperada_falla_claro(tmp_path):
    malo = tmp_path / "malo.csv"
    malo.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    with pytest.raises(ValueError):
        list(iter_filas_rm(malo, geografia=__import__(
            "atlas_core.geografia", fromlist=["cargar_geografia"]
        ).cargar_geografia("CL")))


# ============================================================
# 7. GEOGRAFÍA 2C.4 -- multiplicidad de coordenadas por dirección
# ============================================================

_CABECERA_INE = "gid,via,hnum,alias,error,region,clase_urbana,nombre_comuna,longitude,latitude\n"


def _fila_ine(gid, via, hnum, comuna, lon, lat, alias=""):
    return (
        f"{gid},{via},{hnum},{alias},,METROPOLITANA DE SANTIAGO,CALLE,"
        f"{comuna},{lon},{lat}\n"
    )


def _csv_ine(tmp_path, filas, nombre="mini_ine.csv"):
    ruta = tmp_path / nombre
    ruta.write_text(_CABECERA_INE + "".join(filas), encoding="utf-8")
    return ruta


def test_2c4_duplicado_mismo_punto_no_crea_ambiguedad(tmp_path):
    """Duplicado exacto / coordenadas dentro de la misma celda espacial =>
    NO se inventa una ambigüedad: la consulta sigue siendo
    DIRECCION_EXACTA con UN candidato, pero las N observaciones quedan en
    la base para auditar."""
    ruta = _csv_ine(tmp_path, [
        _fila_ine(101, "LOS AROMOS", "500", "MAIPU", -70.75000, -33.50000),
        _fila_ine(102, "LOS AROMOS", "500", "MAIPU", -70.750004, -33.499997),  # ~0.5 m
        _fila_ine(103, "LOS AROMOS", "500", "MAIPU", -70.75000, -33.50000),    # idéntica a gid 101
    ])
    sqlite_path = tmp_path / "b.sqlite"
    conteos = importar_a_sqlite(ruta, sqlite_path, reemplazar=True, chunk=2)

    assert conteos["aceptadas"] == 3
    assert conteos["filas_en_tabla"] == 3                       # nada se pisa
    assert conteos["direcciones_con_multiples_observaciones"] == 1
    assert conteos["direcciones_multipunto"] == 0               # una sola celda

    base = BaseGeograficaLocalSQLite(sqlite_path)
    ev = base.consultar(comuna="Maipú", calle="LOS AROMOS", numero="500")
    assert ev.resultado == "DIRECCION_EXACTA"
    assert len(ev.candidatos) == 1
    assert ev.candidatos[0].coordenadas is not None
    assert ev.candidatos[0].ref_externa == "gid=101"            # representante determinista

    gids = sqlite3.connect(f"file:{sqlite_path.as_posix()}?mode=ro", uri=True).execute(
        "SELECT ref_externa FROM direcciones WHERE calle_normalizada='LOS AROMOS' ORDER BY ref_externa"
    ).fetchall()
    assert [g[0] for g in gids] == ["gid=101", "gid=102", "gid=103"]


def test_2c4_misma_direccion_coordenadas_distintas_devuelve_multiple(tmp_path):
    """Misma ``(comuna, calle, numero)`` con coordenadas materialmente
    distintas => MULTIPLE con un candidato por punto; jamás "la última
    fila", y cada candidato conserva su gid y su coordenada."""
    ruta = _csv_ine(tmp_path, [
        _fila_ine(201, "EL BOSQUE", "1234", "LAS CONDES", -70.60000, -33.40000),
        _fila_ine(202, "EL BOSQUE", "1234", "LAS CONDES", -70.61500, -33.41500),  # ~2 km
    ])
    sqlite_path = tmp_path / "b.sqlite"
    conteos = importar_a_sqlite(ruta, sqlite_path, reemplazar=True)

    assert conteos["filas_en_tabla"] == 2
    assert conteos["direcciones_con_multiples_observaciones"] == 1
    assert conteos["direcciones_multipunto"] == 1

    base = BaseGeograficaLocalSQLite(sqlite_path)
    ev = base.consultar(comuna="Las Condes", calle="EL BOSQUE", numero="1234")
    assert ev.estado.value == "MULTIPLE"
    assert ev.resultado == "MULTIPLE"
    assert ev.numero_confirmado is False
    assert {c.ref_externa for c in ev.candidatos} == {"gid=201", "gid=202"}
    assert {c.coordenadas for c in ev.candidatos} == {(-70.6, -33.4), (-70.615, -33.415)}


def test_2c4_resultado_no_depende_del_orden_del_csv(tmp_path):
    """El desenlace y los candidatos NO dependen del orden de las filas en
    el CSV -- ni el colapso del punto repetido ni la elección del
    representante."""
    f1 = _fila_ine(301, "LAS ROSAS", "10", "LAS CONDES", -70.70000, -33.40000)
    f2 = _fila_ine(302, "LAS ROSAS", "10", "LAS CONDES", -70.72000, -33.42000)     # otro punto
    f3 = _fila_ine(303, "LAS ROSAS", "10", "LAS CONDES", -70.700004, -33.399997)   # = gid 301

    def _desenlace(orden, nombre):
        ruta = _csv_ine(tmp_path, orden, nombre)
        sqlite_path = tmp_path / f"{nombre}.sqlite"
        conteos = importar_a_sqlite(ruta, sqlite_path, reemplazar=True, chunk=2)
        ev = BaseGeograficaLocalSQLite(sqlite_path).consultar(
            comuna="Las Condes", calle="LAS ROSAS", numero="10"
        )
        return (
            ev.estado.value,
            tuple(sorted(c.ref_externa for c in ev.candidatos)),
            tuple(sorted(c.coordenadas for c in ev.candidatos)),
            conteos["direcciones_multipunto"],
            conteos["filas_en_tabla"],
        )

    a = _desenlace([f1, f2, f3], "orden_a")
    b = _desenlace([f3, f2, f1], "orden_b")
    c = _desenlace([f2, f3, f1], "orden_c")
    assert a == b == c
    estado, refs, _coords, multipunto, en_tabla = a
    assert estado == "MULTIPLE"
    assert en_tabla == 3
    assert multipunto == 1
    # el representante del punto colapsado es SIEMPRE gid=301 (menor
    # ref_externa), nunca la fila que quedó última en el CSV
    assert refs == ("gid=301", "gid=302")


def test_2c4_importacion_grande_es_por_lotes_y_memoria_acotada(tmp_path):
    """Una importación grande sigue siendo streaming: el pico de memoria
    asignada NO escala con el nº de filas (un chunk << total)."""
    import tracemalloc

    from atlas_core.geografia import cargar_geografia

    cargar_geografia("CL")  # catálogo ya en RAM antes de medir (lru_cache)

    n = 60_000
    ruta = tmp_path / "grande.csv"
    with ruta.open("w", encoding="utf-8") as fh:
        fh.write(_CABECERA_INE)
        for i in range(n):
            g = i // 4  # 4 observaciones por dirección, todas al mismo punto
            lon = -70.60 - g * 1e-5
            lat = -33.40 - g * 1e-5
            fh.write(_fila_ine(i, f"CALLE {g}", "100", "MAIPU", f"{lon:.6f}", f"{lat:.6f}"))

    sqlite_path = tmp_path / "g.sqlite"
    tracemalloc.start()
    conteos = importar_a_sqlite(ruta, sqlite_path, reemplazar=True, chunk=1_000)
    _actual, pico = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert conteos["aceptadas"] == n
    assert conteos["filas_en_tabla"] == n                       # nada se pisa
    assert conteos["direcciones_con_multiples_observaciones"] == n // 4
    assert conteos["direcciones_multipunto"] == 0
    # un impl. no-streaming (list() de las 60 000 filas) superaría de
    # lejos esta cota; el pipeline por lotes se queda muy por debajo.
    assert pico < 16 * 1024 * 1024


def test_2c4_reimportar_mismo_gid_es_idempotente(tmp_path):
    """Re-importar el MISMO gid pisa su propia fila (INSERT OR REPLACE por
    PK que incluye ref_externa); no multiplica observaciones."""
    ruta = _csv_ine(tmp_path, [
        _fila_ine(401, "LOS CEREZOS", "20", "MAIPU", -70.71000, -33.41000),
        _fila_ine(402, "LOS CEREZOS", "20", "MAIPU", -70.71000, -33.41000),
    ])
    sqlite_path = tmp_path / "b.sqlite"
    importar_a_sqlite(ruta, sqlite_path, reemplazar=True)
    importar_a_sqlite(ruta, sqlite_path, reemplazar=True)
    base = BaseGeograficaLocalSQLite(sqlite_path)
    assert base.contar() == 2
    filas = sqlite3.connect(f"file:{sqlite_path.as_posix()}?mode=ro", uri=True).execute(
        "SELECT ref_externa FROM direcciones ORDER BY ref_externa"
    ).fetchall()
    assert [f[0] for f in filas] == ["gid=401", "gid=402"]


def test_2c4_base_esquema_previo_exige_reemplazar(tmp_path):
    """Una base con la PK antigua (sin ref_externa) no se puede completar
    sin reconstruir: importar sin ``reemplazar`` aborta con un mensaje
    accionable en vez de seguir perdiendo multiplicidad."""
    sqlite_path = tmp_path / "vieja.sqlite"
    con = sqlite3.connect(str(sqlite_path))
    con.execute(
        "CREATE TABLE direcciones ("
        " codigo_comuna TEXT NOT NULL, calle_normalizada TEXT NOT NULL,"
        " numero TEXT NOT NULL DEFAULT '', calle_canonica TEXT NOT NULL,"
        " comuna_canonica TEXT NOT NULL DEFAULT '', lon REAL, lat REAL,"
        " fuente TEXT NOT NULL DEFAULT '', ref_externa TEXT NOT NULL DEFAULT '',"
        " alias TEXT NOT NULL DEFAULT '',"
        " PRIMARY KEY (codigo_comuna, calle_normalizada, numero));"
    )
    con.commit()
    con.close()

    base = BaseGeograficaLocalSQLite(sqlite_path)
    with pytest.raises(ValueError, match="reemplazar=True"):
        base.importar_filas(
            [{"comuna": "Maipú", "calle": "X", "numero": "1", "ref_externa": "gid=9"}]
        )
    # con reemplazar reconstruye a v3 y ya preserva la multiplicidad
    base.importar_filas(
        [
            {"comuna": "Maipú", "calle": "X", "numero": "1", "ref_externa": "gid=9",
             "lon": -70.7, "lat": -33.5},
            {"comuna": "Maipú", "calle": "X", "numero": "1", "ref_externa": "gid=10",
             "lon": -70.8, "lat": -33.6},
        ],
        reemplazar=True,
    )
    assert base.contar() == 2
