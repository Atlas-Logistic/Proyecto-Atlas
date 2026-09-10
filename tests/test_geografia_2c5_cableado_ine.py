"""GEOGRAFÍA 2C.5 -- cableado seguro de la base territorial INE v3 al
flujo real de resolución de destino.

Cubre:
  * `cargar_base_geografica_local_ine` -- guardián: sólo devuelve una base
    provisionada + esquema v3 + con filas; en cualquier otro caso `None`
    (una base v1/v2 vieja NUNCA se cablea como si fuera la nueva).
  * `_candidato_geocodificacion_desde_base_local` -- un `DIRECCION_EXACTA`
    con coordenada real la aporta al flujo; `MULTIPLE` conserva la
    ambigüedad; `CALLE_CONOCIDA_NUMERO_NO_EN_BASE` / `CALLE_NO_ENCONTRADA`
    nunca inventan coordenada ni asumen una calle homónima.
  * integración en `resolver_destino_con_fallback_estructurado` -- la base
    sólo actúa donde el flujo YA se abstenía; sin base, comportamiento
    idéntico.

Base sintética a partir del fixture 2C.3 (`tests/fixtures/ine_rm_muestra.csv`),
que ya contiene los casos reales pedidos: CARMEN MENA 529 / SAN MIGUEL,
URUGUAY 15 / LA CISTERNA, PUERTA DEL SOL (19/36/100 -- el 83 NO está) /
LAS CONDES. "INTERIOR NUEVA 1148 / SAN BERNARDO" NO está en el fixture ->
CALLE_NO_ENCONTRADA (nunca se asume SANTA MARGARITA ni otra homónima).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from atlas_core.geografia.base_local import (
    BaseGeograficaLocalSQLite,
    cargar_base_geografica_local_ine,
    ruta_base_ine_predeterminada,
)
from atlas_core.geografia.importador_ine import importar_a_sqlite
from atlas_core.rutas.destino_entrega import (
    VIA_BASE_LOCAL,
    _candidato_geocodificacion_desde_base_local,
    resolver_destino_con_fallback_estructurado,
)
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

FIXTURE = Path(__file__).parent / "fixtures" / "ine_rm_muestra.csv"


@pytest.fixture
def base_ine_v3(tmp_path):
    sqlite_path = tmp_path / "base_local_rm_ine.sqlite"
    importar_a_sqlite(FIXTURE, sqlite_path, reemplazar=True)
    return BaseGeograficaLocalSQLite(sqlite_path)


# ============================================================
# 1. Loader / guardián de esquema
# ============================================================


def test_ruta_predeterminada_es_bajo_datos_privados_geografia(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))
    ruta = ruta_base_ine_predeterminada()
    assert ruta.name == "base_local_rm_ine.sqlite"
    assert ruta.parent.name == "geografia"
    assert ruta.parent.parent.name == "datos_privados"


def test_loader_devuelve_none_si_no_esta_provisionada(tmp_path):
    assert cargar_base_geografica_local_ine(ruta=tmp_path / "no_existe.sqlite") is None


def test_loader_rechaza_base_esquema_v1_v2_aunque_tenga_filas(tmp_path):
    # base con la PK ANTIGUA (sin ref_externa) -- v1/v2
    ruta = tmp_path / "vieja.sqlite"
    con = sqlite3.connect(str(ruta))
    con.execute(
        "CREATE TABLE direcciones ("
        " codigo_comuna TEXT NOT NULL, calle_normalizada TEXT NOT NULL,"
        " numero TEXT NOT NULL DEFAULT '', calle_canonica TEXT NOT NULL,"
        " comuna_canonica TEXT NOT NULL DEFAULT '', lon REAL, lat REAL,"
        " fuente TEXT NOT NULL DEFAULT '',"
        " PRIMARY KEY (codigo_comuna, calle_normalizada, numero));"
    )
    con.execute(
        "INSERT INTO direcciones VALUES ('13123','CARMEN MENA','529','CARMEN MENA','San Miguel',-70.6,-33.5,'OSM')"
    )
    con.commit(); con.close()
    b = BaseGeograficaLocalSQLite(ruta)
    assert b.disponible() is True          # tiene filas...
    assert b.esquema_v3_compatible() is False   # ...pero NO es v3
    assert cargar_base_geografica_local_ine(ruta=ruta) is None


def test_loader_rechaza_base_v3_vacia(tmp_path):
    ruta = tmp_path / "vacia.sqlite"
    BaseGeograficaLocalSQLite(ruta).importar_filas([])   # crea esquema v3, 0 filas
    assert BaseGeograficaLocalSQLite(ruta).esquema_v3_compatible() is True
    assert BaseGeograficaLocalSQLite(ruta).disponible() is False
    assert cargar_base_geografica_local_ine(ruta=ruta) is None


def test_loader_acepta_base_v3_provisionada_con_filas(tmp_path):
    ruta = tmp_path / "base_local_rm_ine.sqlite"
    importar_a_sqlite(FIXTURE, ruta, reemplazar=True)
    base = cargar_base_geografica_local_ine(ruta=ruta)
    assert base is not None
    assert base.esquema_v3_compatible() is True
    assert base.consultar(comuna="San Miguel", calle="CARMEN MENA", numero="529").resultado == "DIRECCION_EXACTA"


def test_loader_nunca_lanza_ante_archivo_corrupto(tmp_path):
    ruta = tmp_path / "corrupta.sqlite"
    ruta.write_bytes(b"no soy sqlite")
    assert cargar_base_geografica_local_ine(ruta=ruta) is None


# ============================================================
# 2. Síntesis de candidato desde la base -- casos reales
# ============================================================


def test_sin_base_no_hay_candidato():
    assert _candidato_geocodificacion_desde_base_local(None, "CARMEN MENA 529 SAN MIGUEL") is None


@pytest.mark.parametrize("texto,lon,lat,localidad", [
    ("CARMEN MENA 529 SAN MIGUEL", -70.63886, -33.508934, "San Miguel"),
    ("URUGUAY 15 LA CISTERNA", -70.660891, -33.529673, "La Cisterna"),
])
def test_direccion_exacta_aporta_coordenada_real(base_ine_v3, texto, lon, lat, localidad):
    c = _candidato_geocodificacion_desde_base_local(base_ine_v3, texto)
    assert c is not None
    assert (c.coordenadas.longitud, c.coordenadas.latitud) == (lon, lat)   # coordenada REAL de INE
    assert c.localidad == localidad
    assert c.region == "Metropolitana"
    assert c.codigo_contexto == "13"
    assert c.confianza == 1.0
    assert "[INE]" in c.etiqueta


def test_calle_conocida_numero_no_en_base_no_inventa_coordenada(base_ine_v3):
    # el fixture tiene PUERTA DEL SOL 19/36/100 en Las Condes, no el 83
    ev = base_ine_v3.consultar(comuna="Las Condes", calle="PUERTA DEL SOL", numero="83")
    assert ev.resultado == "CALLE_CONOCIDA_NUMERO_NO_EN_BASE"
    assert _candidato_geocodificacion_desde_base_local(base_ine_v3, "PUERTA DEL SOL 83 LAS CONDES") is None


def test_calle_no_encontrada_no_asume_calle_homonima(base_ine_v3):
    # "INTERIOR NUEVA 1148 SAN BERNARDO" no está -> NUNCA se asume
    # "SANTA MARGARITA 1148" ni ninguna otra homónima
    ev = base_ine_v3.consultar(comuna="San Bernardo", calle="INTERIOR NUEVA", numero="1148")
    assert ev.resultado == "CALLE_NO_ENCONTRADA"
    assert _candidato_geocodificacion_desde_base_local(base_ine_v3, "INTERIOR NUEVA 1148 SAN BERNARDO") is None


def test_multiple_conserva_ambiguedad_no_elige_candidato(base_ine_v3):
    # sin número -> PUERTA DEL SOL tiene 3 registros -> MULTIPLE
    ev = base_ine_v3.consultar(comuna="Las Condes", calle="PUERTA DEL SOL", numero="")
    assert ev.estado.value == "MULTIPLE"
    assert _candidato_geocodificacion_desde_base_local(base_ine_v3, "PUERTA DEL SOL LAS CONDES") is None


# ============================================================
# 3. Integración en resolver_destino_con_fallback_estructurado
# ============================================================


class _ProveedorQueFalla:
    nombre = "falla"; version = "1"

    def geocodificar(self, direccion):
        raise OSError("proveedor de respaldo caído")

    def geocodificar_estructurado(self, direccion, contexto):
        raise OSError("proveedor de respaldo caído")


def _proveedor_sin_candidatos(texto):
    return ProveedorRutasSimulado(geocodificaciones={
        f"{texto}, Chile": ResultadoGeocodificacion(EstadoRuta.REQUIERE_REVISION, (), "SIN_CANDIDATOS"),
    })


def test_base_ine_rescata_cuando_el_respaldo_no_da_candidato(base_ine_v3):
    texto = "CARMEN MENA 529 SAN MIGUEL"
    r = resolver_destino_con_fallback_estructurado(
        texto, proveedor_fallback=_proveedor_sin_candidatos(texto),
        base_geografica_local=base_ine_v3,
    )
    assert r.resuelto is True
    assert r.motivo == "DIRECCION_EXACTA_BASE_LOCAL_INE"
    assert r.vias == (VIA_BASE_LOCAL,)
    assert (r.candidato.coordenadas.longitud, r.candidato.coordenadas.latitud) == (-70.63886, -33.508934)


def test_base_ine_rescata_cuando_el_respaldo_esta_caido(base_ine_v3):
    r = resolver_destino_con_fallback_estructurado(
        "URUGUAY 15 LA CISTERNA", proveedor_fallback=_ProveedorQueFalla(),
        base_geografica_local=base_ine_v3,
    )
    assert r.resuelto is True
    assert r.motivo == "DIRECCION_EXACTA_BASE_LOCAL_INE"
    assert r.candidato.localidad == "La Cisterna"


def test_sin_base_ine_el_comportamiento_no_cambia():
    texto = "CARMEN MENA 529 SAN MIGUEL"
    r = resolver_destino_con_fallback_estructurado(
        texto, proveedor_fallback=_proveedor_sin_candidatos(texto),
        base_geografica_local=None,
    )
    assert r.resuelto is False
    assert r.motivo == "FALLBACK_SIN_CANDIDATO_UNICO"


def test_base_ine_no_rescata_una_calle_conocida_sin_ese_numero(base_ine_v3):
    texto = "PUERTA DEL SOL 83 LAS CONDES"
    r = resolver_destino_con_fallback_estructurado(
        texto, proveedor_fallback=_proveedor_sin_candidatos(texto),
        base_geografica_local=base_ine_v3,
    )
    assert r.resuelto is False
    assert r.motivo == "FALLBACK_SIN_CANDIDATO_UNICO"


def test_comuna_conocida_permite_resolver_cuando_el_texto_no_la_trae(base_ine_v3):
    # GEOGRAFÍA 3 -- "CARMEN MENA 529" a secas (sin comuna) YA resuelve:
    # esa calle+número es ÚNICA en toda la RM (San Miguel) -> región-wide.
    c0 = _candidato_geocodificacion_desde_base_local(base_ine_v3, "CARMEN MENA 529")
    assert c0 is not None
    assert (c0.coordenadas.longitud, c0.coordenadas.latitud) == (-70.63886, -33.508934)
    assert c0.localidad == "San Miguel"
    # con la comuna que Atlas ya conoce por evidencia confiable, también
    c = _candidato_geocodificacion_desde_base_local(
        base_ine_v3, "CARMEN MENA 529", comuna_territorial_conocida="San Miguel",
    )
    assert c is not None
    assert (c.coordenadas.longitud, c.coordenadas.latitud) == (-70.63886, -33.508934)
    # y una comuna EQUIVOCADA no fuerza un match (no hay CARMEN MENA 529 ahí)
    assert _candidato_geocodificacion_desde_base_local(
        base_ine_v3, "CARMEN MENA 529", comuna_territorial_conocida="Vitacura",
    ) is None


def test_region_wide_se_abstiene_si_la_calle_numero_esta_en_dos_comunas(tmp_path):
    # misma calle+número en DOS comunas -> MULTIPLE -> nunca elige un punto
    ruta = tmp_path / "base_local_rm_ine.sqlite"
    base = BaseGeograficaLocalSQLite(ruta)
    base.importar_filas(
        [
            {"comuna": "Maipú", "calle": "LOS AROMOS", "numero": "100",
             "ref_externa": "gid=1", "lon": -70.75, "lat": -33.51},
            {"comuna": "Puente Alto", "calle": "LOS AROMOS", "numero": "100",
             "ref_externa": "gid=2", "lon": -70.58, "lat": -33.61},
        ],
        reemplazar=True,
    )
    ev = base.consultar_sin_comuna(calle="LOS AROMOS", numero="100")
    assert ev.estado.value == "MULTIPLE"
    assert ev.resultado == "MULTIPLE"
    assert _candidato_geocodificacion_desde_base_local(base, "LOS AROMOS 100") is None
    # el mismo número EN una sola comuna sí resuelve
    ev2 = base.consultar_sin_comuna(calle="LOS AROMOS", numero="101")
    # (101 no está) -> abstención por número, nunca devuelve el 100
    assert ev2.resultado in ("CALLE_CONOCIDA_NUMERO_NO_EN_BASE", "CALLE_NO_ENCONTRADA")


def test_region_wide_sin_numero_se_abstiene(base_ine_v3):
    ev = base_ine_v3.consultar_sin_comuna(calle="CARMEN MENA", numero="")
    assert ev.estado.value == "NO_ENCONTRADO"
    assert ev.motivo == "NUMERO_NO_INFORMADO_CONSULTA_SIN_COMUNA"
    assert _candidato_geocodificacion_desde_base_local(base_ine_v3, "CARMEN MENA") is None


def test_region_wide_calle_inexistente_no_asume_homonima(base_ine_v3):
    ev = base_ine_v3.consultar_sin_comuna(calle="AVENIDA QUE NO EXISTE", numero="42")
    assert ev.resultado == "CALLE_NO_ENCONTRADA"
    assert all(c.coordenadas is None for c in ev.candidatos)


def test_resolver_con_fallback_propaga_la_comuna_conocida_a_la_base(base_ine_v3):
    texto = "CARMEN MENA 529"
    r = resolver_destino_con_fallback_estructurado(
        texto, proveedor_fallback=_proveedor_sin_candidatos(texto),
        base_geografica_local=base_ine_v3, comuna_territorial_conocida="San Miguel",
    )
    assert r.resuelto is True
    assert r.motivo == "DIRECCION_EXACTA_BASE_LOCAL_INE"


def test_calcular_ruta_con_planta_conocida_acepta_base_geografica_local():
    import inspect

    from atlas_core.rutas.destino_entrega import calcular_ruta_con_planta_conocida

    assert "base_geografica_local" in inspect.signature(calcular_ruta_con_planta_conocida).parameters


def test_primer_pase_cablea_base_geografica_local_de_punta_a_punta():
    """GEOGRAFÍA 3 -- el primer pase (procesamiento inicial) debe poder
    recibir la base INE y propagarla hasta `resolver_destino_entrega`."""
    import inspect

    from atlas_core.rutas.destino_entrega import (
        calcular_ruta_entrega_para_viaje,
        resolver_entrega_documento,
    )

    for fn in (resolver_entrega_documento, calcular_ruta_entrega_para_viaje):
        assert "base_geografica_local" in inspect.signature(fn).parameters, fn.__name__
