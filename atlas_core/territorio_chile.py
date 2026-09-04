"""Shim histórico de territorio chileno sobre la autoridad geográfica G1-A."""
from __future__ import annotations

import re
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


# Bloque REGIONES V1 -- caso real 464170 (Mejillones/Antofagasta): el
# catálogo territorial (G1-A) guarda cada región por su nombre BARE
# ("Antofagasta", nunca "Región de Antofagasta"), pero un proveedor de
# geocodificación real devolvió literalmente "De Antofagasta" -- un
# nombre administrativo chileno real ("Región de Antofagasta") con la
# palabra "Región" recortada, dejando sólo la preposición pegada al
# nombre. `region_valida` exigía coincidencia EXACTA (nunca difusa, a
# propósito -- nada de fuzzy matching para regiones, para no aceptar por
# error una región extranjera homónima) y esa variante nunca calzaba,
# así que una entrega interregional real quedaba marcada
# `GEOCODIFICACION_FUERA_DE_CHILE` -- un falso positivo de normalización
# de nombre, no una entrega fuera del país. Se intenta primero el texto
# tal cual (ninguna región chilena real empieza con esta preposición); si
# no calza EXACTO, se reintenta UNA sola vez quitando SÓLO una preposición
# regional inicial ("de"/"del"/"de la"/"de los") -- nunca ninguna otra
# transformación, y el resultado final sigue exigiendo coincidencia
# EXACTA contra el catálogo cerrado, igual que antes. Genérico por diseño:
# no hardcodea "Antofagasta" ni ninguna región en particular.
_PREPOSICION_REGIONAL_INICIAL = re.compile(
    r"^\s*(?:del|de\s+la|de\s+los|de)\s+", re.IGNORECASE,
)


def region_valida(texto: str) -> str | None:
    decision = _GEOGRAFIA.normalizar(texto, nivel=1)
    if decision.estado == EstadoNormalizacion.EXACTA and decision.unidad:
        return decision.unidad.nombre_canonico
    sin_preposicion = _PREPOSICION_REGIONAL_INICIAL.sub("", str(texto or ""), count=1)
    if sin_preposicion == texto:
        return None
    decision_sin_preposicion = _GEOGRAFIA.normalizar(sin_preposicion, nivel=1)
    if decision_sin_preposicion.estado == EstadoNormalizacion.EXACTA and decision_sin_preposicion.unidad:
        return decision_sin_preposicion.unidad.nombre_canonico
    return None


def normalizar_direccion_con_comunas(texto: str) -> str:
    return _GEOGRAFIA.normalizar_direccion(texto)
