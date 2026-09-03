"""Shim histórico de territorio chileno sobre la autoridad geográfica G1-A."""
from __future__ import annotations

from dataclasses import dataclass

from atlas_core.geografia import EstadoNormalizacion, MotorNormalizacion, UnidadAdministrativa, cargar_geografia
from atlas_core.geografia.cl import NIVEL_COMUNA

_GEOGRAFIA = cargar_geografia("CL")

ESTADO_COMUNA_EXACTA = EstadoNormalizacion.EXACTA.value
ESTADO_COMUNA_NORMALIZADA_SEGURA = EstadoNormalizacion.NORMALIZADA_SEGURA.value
ESTADO_COMUNA_AMBIGUA = EstadoNormalizacion.AMBIGUA.value
ESTADO_COMUNA_NO_RECONOCIDA = EstadoNormalizacion.NO_RECONOCIDA.value
UMBRAL_COMUNA_DIFUSA = _GEOGRAFIA.motor.umbral
MARGEN_AMBIGUEDAD_COMUNA = _GEOGRAFIA.motor.margen_ambiguedad
LONGITUD_MINIMA_COMUNA_DIFUSA = _GEOGRAFIA.motor.longitud_minima

# Vistas históricas de sólo compatibilidad. Algunos tests inyectan aquí un
# universo sintético para verificar la abstención por ambigüedad.
_INDICE_COMUNAS = {
    unidad.nombre_normalizado: (
        unidad.nombre_canonico,
        _GEOGRAFIA.motor.por_codigo[
            _GEOGRAFIA.motor.por_codigo[unidad.codigo_padre].codigo_padre
        ].nombre_canonico,
    )
    for unidad in _GEOGRAFIA.unidades if unidad.nivel == NIVEL_COMUNA
}
_NOMBRES_SIMPLES_COMUNAS = tuple(_INDICE_COMUNAS)
_CLAVES_OFICIALES = frozenset(_INDICE_COMUNAS)


@dataclass(frozen=True)
class ResultadoNormalizacionComuna:
    estado: str
    valor_original: str
    comuna: str | None = None
    region: str | None = None
    similitud: float | None = None


def _resultado_compat(decision) -> ResultadoNormalizacionComuna:
    unidad = decision.unidad
    region = decision.unidad_de_nivel(1)
    return ResultadoNormalizacionComuna(
        decision.estado.value, decision.valor_original,
        unidad.nombre_canonico if unidad else None,
        region.nombre_canonico if region else None,
        decision.similitud,
    )


def normalizar_comuna(texto: str) -> ResultadoNormalizacionComuna:
    if frozenset(_INDICE_COMUNAS) == _CLAVES_OFICIALES:
        return _resultado_compat(_GEOGRAFIA.normalizar(texto, nivel=NIVEL_COMUNA))
    unidades = [
        UnidadAdministrativa(
            "CL", NIVEL_COMUNA, f"TEST:{clave}", None, comuna, clave,
            metadata={"region_compatibilidad": region},
        )
        for clave, (comuna, region) in _INDICE_COMUNAS.items()
        if clave in _NOMBRES_SIMPLES_COMUNAS
    ]
    decision = MotorNormalizacion(
        unidades, palabras_estructurales=_GEOGRAFIA.motor.palabras_estructurales
    ).normalizar(texto, nivel=NIVEL_COMUNA)
    unidad = decision.unidad
    return ResultadoNormalizacionComuna(
        decision.estado.value, decision.valor_original,
        unidad.nombre_canonico if unidad else None,
        unidad.metadata.get("region_compatibilidad") if unidad else None,
        decision.similitud,
    )


def region_valida(texto: str) -> str | None:
    decision = _GEOGRAFIA.normalizar(texto, nivel=1)
    return decision.unidad.nombre_canonico if decision.estado == EstadoNormalizacion.EXACTA and decision.unidad else None


def normalizar_direccion_con_comunas(texto: str) -> str:
    return _GEOGRAFIA.normalizar_direccion(texto)
