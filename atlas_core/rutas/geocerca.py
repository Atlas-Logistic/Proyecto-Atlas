"""Resolución conservadora de planta de origen por geocerca (Bloque RUTAS R1).

Nunca elige planta por "cuál ruta es más corta": solo por proximidad real
(línea recta, Haversine) a la posición GPS entregada, dentro de un radio
conservador. Ante ambigüedad o fuera de rango, se abstiene.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from atlas_core.rutas.modelos import Coordenadas

# Radio conservador propuesto (Paso 2): no existe todavía un histórico real
# de posiciones GPS contra el cual validarlo (ver posicion_vehiculo.py) --
# valor de partida, no calibrado con datos reales. AZA RENCA y AZA COLINA
# están separadas ~25-50 km en ruta real (confirmado con ORS), muy por
# encima de este radio, por lo que no genera ambigüedad entre ambas.
RADIO_GEOCERCA_KM_PREDETERMINADO = 1.5


@dataclass(frozen=True)
class ResultadoGeocercaPlanta:
    planta_id: str | None
    planta_nombre: str | None
    distancia_km: float | None
    determinada: bool
    motivo: str


def distancia_km_haversine(a: Coordenadas, b: Coordenadas) -> float:
    radio_tierra_km = 6371.0088
    lat1, lat2 = math.radians(a.latitud), math.radians(b.latitud)
    dlat = lat2 - lat1
    dlon = math.radians(b.longitud - a.longitud)
    seno = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radio_tierra_km * math.asin(math.sqrt(seno))


def resolver_planta_por_posicion(
    posicion: Coordenadas,
    plantas: Iterable[object],
    *,
    radio_km: float = RADIO_GEOCERCA_KM_PREDETERMINADO,
) -> ResultadoGeocercaPlanta:
    """`plantas`: objetos con `planta_id`, `nombre`, `latitud`, `longitud`
    (p. ej. `atlas_core.catalogo_plantas.Planta`). Ignora plantas sin
    coordenadas. Se abstiene si ninguna planta cae dentro del radio, o si
    dos o más quedan empatadas a la misma distancia mínima."""
    candidatas: list[tuple[float, object]] = []
    for planta in plantas:
        latitud = getattr(planta, "latitud", None)
        longitud = getattr(planta, "longitud", None)
        if latitud is None or longitud is None:
            continue
        distancia = distancia_km_haversine(posicion, Coordenadas(longitud, latitud))
        if distancia <= radio_km:
            candidatas.append((distancia, planta))

    if not candidatas:
        return ResultadoGeocercaPlanta(None, None, None, False, "FUERA_DE_GEOCERCA")

    candidatas.sort(key=lambda par: par[0])
    mejor_distancia = candidatas[0][0]
    empatadas = [planta for distancia, planta in candidatas if distancia == mejor_distancia]
    if len(empatadas) > 1:
        return ResultadoGeocercaPlanta(None, None, mejor_distancia, False, "AMBIGUO_ENTRE_PLANTAS")

    planta = empatadas[0]
    return ResultadoGeocercaPlanta(
        planta.planta_id, planta.nombre, mejor_distancia, True, "DENTRO_DE_GEOCERCA"
    )
