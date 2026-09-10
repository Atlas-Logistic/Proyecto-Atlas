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
        "colisiones_pk": 0,
        "filas_en_tabla": 0,
    }


def test_import_conteos_y_colision_pk(tmp_path):
    _base_obj, sqlite_path = _base(tmp_path)
    meta = json.loads((tmp_path / "base_local_rm_ine.sqlite.procedencia.json").read_text("utf-8"))
    c = meta["conteos"]
    assert c["aceptadas"] == 17
    assert c["filas_enviadas"] == 17
    assert c["colisiones_pk"] == 1          # gid 1 y gid 20 -> misma (comuna,calle,numero)
    assert c["filas_en_tabla"] == 16
    assert BaseGeograficaLocalSQLite(sqlite_path).contar() == 16


def test_chunk_pequeno_no_pierde_filas(tmp_path):
    sqlite_path = tmp_path / "b.sqlite"
    importar_a_sqlite(FIXTURE, sqlite_path, reemplazar=True, chunk=1)
    assert BaseGeograficaLocalSQLite(sqlite_path).contar() == 16


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
    assert conteos["filas_en_tabla"] == 16
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
    assert payload["conteos"]["filas_en_tabla"] == 16
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
