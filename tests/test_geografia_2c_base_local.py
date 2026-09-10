"""GEOGRAFÍA 2C -- BASE GEOGRÁFICA LOCAL (RM).

Contrato + backend SQLite + regla segura de número + adaptador de flujo.
La base es UNA fuente de evidencia, nunca autoridad ciega: nunca inventa
coordenadas, nunca acepta un número distinto, preserva ceros iniciales, y
funciona (devolviendo NO_ENCONTRADO explícito) aunque el archivo aún no
exista.
"""
from __future__ import annotations

import sqlite3

import pytest

from atlas_core.geografia.base_local import (
    BaseGeograficaLocal,
    BaseGeograficaLocalSQLite,
    DireccionLocal,
    EstadoConsultaLocal,
    EvidenciaGeoLocal,
    NOMBRE_ARCHIVO_PREDETERMINADO,
    evidencia_local_para_direccion,
    numero_equivalente_seguro,
)


def _base(tmp_path, filas=(), **kwargs):
    b = BaseGeograficaLocalSQLite(tmp_path / "base.sqlite")
    if filas:
        b.importar_filas(filas, **kwargs)
    return b


_FILAS_RM = [
    {"comuna": "Providencia", "calle": "Pedro de Valdivia", "numero": "100", "fuente": "SEMILLA"},
    {"comuna": "Providencia", "calle": "Pedro de Valdivia", "numero": "200", "fuente": "SEMILLA"},
    {"comuna": "Las Condes", "calle": "Apoquindo", "numero": "3000", "fuente": "SEMILLA"},
    {"comuna": "Maipú", "calle": "Vicuña Mackenna", "numero": "655", "fuente": "SEMILLA"},
]


# ============================================================
# 1. Regla segura de número -- ceros a la izquierda, nunca valores distintos
# ============================================================


@pytest.mark.parametrize("a,b", [("0100", "100"), ("0015", "15"), ("100", "100"), ("007", "7")])
def test_numero_equivalente_ceros_a_la_izquierda(a, b):
    assert numero_equivalente_seguro(a, b) is True
    assert numero_equivalente_seguro(b, a) is True


@pytest.mark.parametrize("a,b", [("15", "1545"), ("100", "1000"), ("83", "8351"), ("", "100"), ("100", "")])
def test_numero_no_equivalente_valores_distintos_o_ausencia(a, b):
    assert numero_equivalente_seguro(a, b) is False


@pytest.mark.parametrize("a,b", [("0114B", "1148"), ("O1148", "1148"), ("12A", "12")])
def test_numero_alfanumerico_nunca_se_colapsa(a, b):
    assert numero_equivalente_seguro(a, b) is False


# ============================================================
# 2. Funciona sin PBF -- archivo ausente / base vacía
# ============================================================


def test_base_inexistente_no_disponible_y_no_crea_archivo(tmp_path):
    ruta = tmp_path / "no_existe.sqlite"
    b = BaseGeograficaLocalSQLite(ruta)
    assert b.disponible() is False
    ev = b.consultar(comuna="Providencia", calle="Pedro de Valdivia", numero="100")
    assert ev.estado == EstadoConsultaLocal.NO_ENCONTRADO
    assert ev.disponible is False
    assert ev.motivo == "BASE_LOCAL_NO_PROVISIONADA"
    assert ev.candidatos == ()
    # una consulta JAMÁS crea el archivo
    assert not ruta.exists()


def test_base_vacia_tras_importar_cero_filas_sigue_no_disponible(tmp_path):
    b = BaseGeograficaLocalSQLite(tmp_path / "base.sqlite")
    assert b.importar_filas([]) == 0
    assert b.disponible() is False


def test_ruta_predeterminada_apunta_a_datos_privados_geografia(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))
    b = BaseGeograficaLocalSQLite()
    assert b.ruta.name == NOMBRE_ARCHIVO_PREDETERMINADO
    assert b.ruta.parent.name == "geografia"


# ============================================================
# 3. Cuatro desenlaces: EXACTA / NORMALIZADA / MULTIPLE / NO_ENCONTRADO
# ============================================================


def test_exacta_calle_y_numero(tmp_path):
    ev = _base(tmp_path, _FILAS_RM).consultar(
        comuna="Providencia", calle="Pedro de Valdivia", numero="100"
    )
    assert ev.estado == EstadoConsultaLocal.EXACTA
    assert ev.encontrada is True
    assert ev.numero_confirmado is True
    assert len(ev.candidatos) == 1
    assert ev.candidatos[0].codigo_comuna == "13123"
    assert ev.candidatos[0].numero == "100"
    assert ev.candidatos[0].coordenadas is None  # nunca inventa coordenadas


def test_exacta_con_cero_inicial_en_la_consulta_preserva_numero_almacenado(tmp_path):
    ev = _base(tmp_path, _FILAS_RM).consultar(
        comuna="Providencia", calle="Pedro de Valdivia", numero="0100"
    )
    assert ev.estado == EstadoConsultaLocal.EXACTA
    assert ev.numero_confirmado is True
    # el número ALMACENADO no se reescribe; la consulta se conserva tal cual
    assert ev.candidatos[0].numero == "100"
    assert ev.consulta["numero"] == "0100"


def test_normalizada_por_prefijo_estructural_no_discriminante(tmp_path):
    ev = _base(tmp_path, _FILAS_RM).consultar(
        comuna="Providencia", calle="CALLE Pedro de Valdivia", numero="100"
    )
    assert ev.estado == EstadoConsultaLocal.NORMALIZADA
    assert ev.numero_confirmado is True


def test_exacta_es_insensible_a_mayusculas_y_espacios(tmp_path):
    ev = _base(tmp_path, _FILAS_RM).consultar(
        comuna="providencia", calle="  pedro de  valdivia ", numero="100"
    )
    assert ev.estado == EstadoConsultaLocal.EXACTA
    assert ev.encontrada is True


def test_normalizada_por_acentos(tmp_path):
    filas = [{"comuna": "Ñuñoa", "calle": "Irarrázaval", "numero": "1000", "fuente": "SEMILLA"}]
    ev = _base(tmp_path, filas).consultar(comuna="Ñuñoa", calle="Irarrazaval", numero="1000")
    # la calle se reconoce, pero la forma consultada no es la canónica
    assert ev.estado == EstadoConsultaLocal.NORMALIZADA
    assert ev.encontrada is True
    assert ev.numero_confirmado is True


def test_multiple_varios_numeros_conocidos_sin_numero_consultado(tmp_path):
    ev = _base(tmp_path, _FILAS_RM).consultar(comuna="Providencia", calle="Pedro de Valdivia")
    assert ev.estado == EstadoConsultaLocal.MULTIPLE
    assert ev.encontrada is False  # MULTIPLE no es reconocimiento accionable
    assert ev.numero_confirmado is False
    assert len(ev.candidatos) == 2


def test_multiple_mismo_numero_en_dos_registros(tmp_path):
    filas = _FILAS_RM + [
        {"comuna": "Providencia", "calle": "Pedro de Valdivia", "numero": "100",
         "fuente": "OTRA", "lon": -70.61, "lat": -33.43},
    ]
    # INSERT OR REPLACE colapsa por PK (comuna+calle+numero) -> sigue habiendo 1
    ev = _base(tmp_path, filas).consultar(
        comuna="Providencia", calle="Pedro de Valdivia", numero="100"
    )
    assert ev.estado == EstadoConsultaLocal.EXACTA
    assert len(ev.candidatos) == 1
    # la segunda importación (con coords) reemplazó a la primera
    assert ev.candidatos[0].coordenadas == (-70.61, -33.43)


def test_no_encontrado_calle_ausente_en_la_comuna(tmp_path):
    ev = _base(tmp_path, _FILAS_RM).consultar(
        comuna="Providencia", calle="Calle Inexistente", numero="1"
    )
    assert ev.estado == EstadoConsultaLocal.NO_ENCONTRADO
    assert ev.motivo == "CALLE_NO_ENCONTRADA_EN_COMUNA"


def test_no_encontrado_comuna_no_resoluble(tmp_path):
    ev = _base(tmp_path, _FILAS_RM).consultar(
        comuna="Zona Rural Sin Comuna", calle="Pedro de Valdivia", numero="100"
    )
    assert ev.estado == EstadoConsultaLocal.NO_ENCONTRADO
    assert ev.motivo == "COMUNA_NO_RESUELTA"


# ============================================================
# 4. Nunca acepta un número distinto
# ============================================================


def test_numero_distinto_nunca_es_coincidencia(tmp_path):
    ev = _base(tmp_path, _FILAS_RM).consultar(
        comuna="Providencia", calle="Pedro de Valdivia", numero="150"
    )
    # GEOGRAFÍA 2C.3: la calle SÍ existe en la comuna -> CALLE_CONOCIDA,
    # nunca DIRECCION_EXACTA. El número distinto jamás se acepta.
    assert ev.resultado == "CALLE_CONOCIDA_NUMERO_NO_EN_BASE"
    assert ev.motivo == "CALLE_CONOCIDA_NUMERO_NO_EN_BASE"
    assert ev.calle_conocida is True
    assert ev.numero_confirmado is False
    # se devuelven los registros de la calle como EVIDENCIA (no como match)
    assert {c.numero for c in ev.candidatos} == {"100", "200"}
    assert all(c.numero_coincide is False for c in ev.candidatos)


def test_calle_conocida_pero_numero_no_en_base(tmp_path):
    filas = [{"comuna": "Maipú", "calle": "Los Aromos", "numero": "", "fuente": "SEMILLA"}]
    ev = _base(tmp_path, filas).consultar(comuna="Maipú", calle="Los Aromos", numero="742")
    assert ev.estado == EstadoConsultaLocal.EXACTA  # la CALLE sí se reconoce
    assert ev.motivo == "CALLE_CONOCIDA_NUMERO_NO_EN_BASE"
    assert ev.numero_confirmado is False  # el número no está -> nunca confirmado
    assert ev.candidatos[0].numero == ""


# ============================================================
# 5. Contrato + importación
# ============================================================


def test_backend_cumple_el_protocolo(tmp_path):
    assert isinstance(_base(tmp_path, _FILAS_RM), BaseGeograficaLocal)


def test_importar_acepta_codigo_cut_directo_como_comuna(tmp_path):
    b = _base(tmp_path, [{"comuna": "13123", "calle": "Antonio Varas", "numero": "50"}])
    ev = b.consultar(comuna="Providencia", calle="Antonio Varas", numero="50")
    assert ev.estado == EstadoConsultaLocal.EXACTA
    assert ev.candidatos[0].comuna_canonica == "Providencia"


def test_importar_falla_ruidoso_ante_comuna_no_resoluble(tmp_path):
    with pytest.raises(ValueError):
        _base(tmp_path, [{"comuna": "Comuna Falsa", "calle": "X", "numero": "1"}])


def test_importar_ignora_coordenadas_no_finitas(tmp_path):
    b = _base(tmp_path, [
        {"comuna": "Las Condes", "calle": "Apoquindo", "numero": "1", "lon": "nan", "lat": "1"},
    ])
    ev = b.consultar(comuna="Las Condes", calle="Apoquindo", numero="1")
    assert ev.candidatos[0].coordenadas is None


def test_importar_guarda_coordenadas_reales_cuando_existen(tmp_path):
    b = _base(tmp_path, [
        {"comuna": "Las Condes", "calle": "Apoquindo", "numero": "1", "lon": -70.57, "lat": -33.41},
    ])
    ev = b.consultar(comuna="Las Condes", calle="Apoquindo", numero="1")
    assert ev.candidatos[0].coordenadas == (-70.57, -33.41)


def test_reimportar_con_reemplazar_reconstruye(tmp_path):
    b = _base(tmp_path, _FILAS_RM)
    assert b.consultar(comuna="Las Condes", calle="Apoquindo", numero="3000").encontrada
    b.importar_filas([{"comuna": "Ñuñoa", "calle": "Irarrázaval", "numero": "1"}], reemplazar=True)
    assert not b.consultar(comuna="Las Condes", calle="Apoquindo", numero="3000").encontrada
    assert b.consultar(comuna="Ñuñoa", calle="Irarrázaval", numero="1").encontrada


def test_cache_corrupta_no_rompe(tmp_path):
    ruta = tmp_path / "base.sqlite"
    ruta.write_bytes(b"no soy sqlite")
    b = BaseGeograficaLocalSQLite(ruta)
    assert b.disponible() is False
    ev = b.consultar(comuna="Providencia", calle="Pedro de Valdivia", numero="1")
    assert ev.estado == EstadoConsultaLocal.NO_ENCONTRADO


# ============================================================
# 6. Adaptador de flujo -- interpreta un DESPACHAR A crudo
# ============================================================


def test_flujo_helper_sin_base_es_no_encontrado_sin_crash():
    ev = evidencia_local_para_direccion(None, "PEDRO DE VALDIVIA 100 PROVIDENCIA")
    assert ev.estado == EstadoConsultaLocal.NO_ENCONTRADO
    assert ev.motivo == "SIN_BASE_LOCAL"


def test_flujo_helper_extrae_comuna_del_texto(tmp_path):
    b = _base(tmp_path, _FILAS_RM)
    ev = evidencia_local_para_direccion(b, "PEDRO DE VALDIVIA 100 PROVIDENCIA")
    assert ev.estado == EstadoConsultaLocal.EXACTA
    assert ev.numero_confirmado is True
    assert ev.consulta["numero"] == "100"


def test_flujo_helper_comuna_explicita_tiene_prioridad(tmp_path):
    b = _base(tmp_path, _FILAS_RM)
    # el texto no nombra comuna; la localidad de un candidato del respaldo sí
    ev = evidencia_local_para_direccion(b, "VICUÑA MACKENNA 655", comuna="Maipú")
    assert ev.estado == EstadoConsultaLocal.EXACTA
    assert ev.candidatos[0].comuna_canonica == "Maipú"


def test_flujo_helper_numero_distinto_no_confirma(tmp_path):
    b = _base(tmp_path, _FILAS_RM)
    ev = evidencia_local_para_direccion(b, "PEDRO DE VALDIVIA 999 PROVIDENCIA")
    assert ev.numero_confirmado is False
    assert ev.resultado == "CALLE_CONOCIDA_NUMERO_NO_EN_BASE"
