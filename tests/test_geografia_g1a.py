"""Contrato, catálogo oficial y compatibilidad de Geografía G1-A."""
from __future__ import annotations

import json
from pathlib import Path

from atlas_core.geografia import (
    EstadoNormalizacion, GeografiaPais, MotorNormalizacion,
    UnidadAdministrativa, cargar_geografia, texto_normalizado,
)
from atlas_core.geografia.cl import NIVEL_COMUNA, NIVEL_PROVINCIA, NIVEL_REGION, RUTA_DATASET
from atlas_core.catalogo_destinos import normalizar_nombre_destino
from atlas_core.rutas.cache_geocodificacion import _normalizar_direccion
from atlas_core.territorio_chile import normalizar_comuna, region_valida


def test_carga_cl_y_contrato_publico():
    geografia = cargar_geografia("CL")
    assert geografia is cargar_geografia("CHL")
    assert isinstance(geografia, GeografiaPais)
    assert geografia.niveles == ("región", "provincia", "comuna")
    assert geografia.nivel_geocodificable == NIVEL_COMUNA


def test_dataset_oficial_tiene_346_comunas_y_jerarquia_completa():
    filas = json.loads(Path(RUTA_DATASET).read_text(encoding="utf-8"))
    assert len(filas) == 346
    assert len({fila["codigo_region"] for fila in filas}) == 16
    assert len({fila["codigo_provincia"] for fila in filas}) == 56
    assert len({fila["codigo_comuna"] for fila in filas}) == 346
    geografia = cargar_geografia("CL")
    providencia = geografia.buscar_por_codigo("13123")
    assert providencia and providencia.nivel == NIVEL_COMUNA
    provincia = geografia.buscar_por_codigo(providencia.codigo_padre)
    assert provincia and provincia.nivel == NIVEL_PROVINCIA and provincia.codigo == "131"
    region = geografia.buscar_por_codigo(provincia.codigo_padre)
    assert region and region.nivel == NIVEL_REGION and region.codigo == "13"


def test_exacta_segura_alias_ambigua_y_abstencion():
    geografia = cargar_geografia("CL")
    exacta = geografia.normalizar("Providencia", NIVEL_COMUNA)
    assert exacta.estado == EstadoNormalizacion.EXACTA
    assert exacta.unidad and exacta.unidad.codigo == "13123"
    assert exacta.unidad_de_nivel(NIVEL_REGION).nombre_canonico == "Metropolitana"
    segura = geografia.normalizar("CADQUENES", NIVEL_COMUNA)
    assert segura.estado == EstadoNormalizacion.NORMALIZADA_SEGURA
    assert segura.unidad and segura.unidad.nombre_canonico == "Cauquenes"
    assert geografia.normalizar("RM", NIVEL_REGION).unidad.nombre_canonico == "Metropolitana"
    assert geografia.normalizar("Iquique").estado == EstadoNormalizacion.AMBIGUA
    assert geografia.normalizar("CAMINO", NIVEL_COMUNA).estado == EstadoNormalizacion.NO_RECONOCIDA
    assert geografia.normalizar("PARQUE", NIVEL_COMUNA).estado == EstadoNormalizacion.NO_RECONOCIDA


def test_regresion_nombres_oficiales_de_comuna_mal_transcritos():
    """Revisión integral G1-A (2026-09-04): el dataset SUBDERE ingerido
    traía 3 nombres de comuna mal transcritos -- "LA CALERA" (05502)
    aparecía como "CALERA" (quedaba NO_RECONOCIDA pese a estar bien
    escrita), "PAIHUANO" (04105) como "PAIGUANO", y "TIL TIL" (13303)
    como "TILTIL" (ambas degradaban de EXACTA a fuzzy y resolvían a un
    canónico mal escrito). Fija los 3 nombres oficiales correctos contra
    EXACTA, para que una futura re-ingesta del dataset no los rompa de
    nuevo en silencio."""
    geografia = cargar_geografia("CL")

    la_calera = geografia.normalizar("LA CALERA", NIVEL_COMUNA)
    assert la_calera.estado == EstadoNormalizacion.EXACTA
    assert la_calera.unidad and la_calera.unidad.codigo == "05502"
    assert la_calera.unidad.nombre_canonico == "La Calera"

    paihuano = geografia.normalizar("PAIHUANO", NIVEL_COMUNA)
    assert paihuano.estado == EstadoNormalizacion.EXACTA
    assert paihuano.unidad and paihuano.unidad.codigo == "04105"
    assert paihuano.unidad.nombre_canonico == "Paihuano"

    til_til = geografia.normalizar("TIL TIL", NIVEL_COMUNA)
    assert til_til.estado == EstadoNormalizacion.EXACTA
    assert til_til.unidad and til_til.unidad.codigo == "13303"
    assert til_til.unidad.nombre_canonico == "Til Til"


def test_shim_y_normalizadores_delegados_preservan_compatibilidad():
    resultado = normalizar_comuna("CAUQUBNES")
    assert (resultado.estado, resultado.comuna, resultado.region) == (
        "NORMALIZADA_SEGURA", "Cauquenes", "Maule"
    )
    assert region_valida("RM") == "Metropolitana"
    assert normalizar_nombre_destino("  Ñuñoa,   RM ") == "NUNOA RM"
    assert _normalizar_direccion("CATEDRAL 759 CADQUENES CAUQUENES") == "CATEDRAL 759 CAUQUENES"


class GeografiaPruebaDosNiveles:
    """País ficticio: demuestra departamento/municipio sin tocar el core."""
    codigo_pais = "XX"
    codigos_pais = ("XX", "XXX")
    niveles = ("departamento", "municipio")
    nivel_geocodificable = 2
    nivel_region_geocodificacion = 1

    def __init__(self):
        self.motor = MotorNormalizacion((
            UnidadAdministrativa("XX", 1, "D-A", None, "Departamento A", texto_normalizado("Departamento A")),
            UnidadAdministrativa("XX", 2, "M-1", "D-A", "Municipio Uno", texto_normalizado("Municipio Uno")),
        ))

    def normalizar(self, texto, nivel=None): return self.motor.normalizar(texto, nivel)
    def normalizar_direccion(self, texto): return self.motor.normalizar_direccion(texto, nivel=2)
    def buscar_por_codigo(self, codigo): return self.motor.por_codigo.get(codigo)
    def parametros_geocodificacion(self, unidad): return {"codigo_pais": "XX", "unidad": unidad.nombre_canonico}
    def compatibilidad_territorial(self, a, b): return a.codigo == b.codigo or a.codigo_padre == b.codigo


def test_fixture_multipais_dos_niveles_cumple_core_sin_semantica_chile():
    geografia = GeografiaPruebaDosNiveles()
    assert isinstance(geografia, GeografiaPais)
    resultado = geografia.normalizar("Municipio Uno", nivel=2)
    assert resultado.unidad and resultado.unidad_de_nivel(1).nombre_canonico == "Departamento A"
    assert "comuna" not in vars(geografia) and "región" not in vars(geografia)
