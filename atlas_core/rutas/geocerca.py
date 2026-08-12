"""Resolución conservadora de planta de origen por geocerca (Bloque RUTAS R1).

Nunca elige planta por "cuál ruta es más corta": solo por proximidad real
(línea recta, Haversine) a la posición GPS entregada, dentro de un radio
conservador. Ante ambigüedad o fuera de rango, se abstiene.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

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


def coordenada_ruteo_planta(planta: object) -> Coordenadas | None:
    """Bloque PLANTAS P3 -- punto desde donde debe iniciar/terminar una
    ruta ORS hacia/desde `planta`. Prioriza `punto_ruteo_latitud`/
    `punto_ruteo_longitud` (el acceso real de camiones, validado contra
    cartografía/telemetría -- ver `atlas_core.catalogo_plantas.Planta`)
    cuando la planta lo trae; si no (toda planta de antes de este bloque,
    o una sin punto de ruteo propio todavía), cae a `latitud`/`longitud`
    exactamente como siempre. `None` si no hay ninguna coordenada
    disponible -- nunca inventa un punto de partida."""
    lat_ruteo = getattr(planta, "punto_ruteo_latitud", None)
    lon_ruteo = getattr(planta, "punto_ruteo_longitud", None)
    if lat_ruteo is not None and lon_ruteo is not None:
        return Coordenadas(lon_ruteo, lat_ruteo)
    latitud = getattr(planta, "latitud", None)
    longitud = getattr(planta, "longitud", None)
    if latitud is not None and longitud is not None:
        return Coordenadas(longitud, latitud)
    return None


def punto_en_poligono(
    punto: Coordenadas, vertices: Sequence[Sequence[float]]
) -> bool:
    """Bloque PLANTAS P3 -- ray casting determinista sobre (latitud,
    longitud) tratados como un plano local: a la escala de un recinto
    real (cientos de metros), la distorsión de no usar geodesia es
    despreciable -- no hace falta ninguna dependencia GIS para esto.
    `vertices`: secuencia de `(latitud, longitud)`, en cualquier orden
    (no exige sentido horario/antihorario). Un polígono con menos de 3
    vértices nunca contiene ningún punto (nunca lanza)."""
    if len(vertices) < 3:
        return False
    x, y = punto.longitud, punto.latitud
    dentro = False
    x1, y1 = vertices[-1][1], vertices[-1][0]
    for lat2, lon2 in vertices:
        x2, y2 = lon2, lat2
        if (y1 > y) != (y2 > y):
            interseccion_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < interseccion_x:
                dentro = not dentro
        x1, y1 = x2, y2
    return dentro


def resolver_planta_por_posicion(
    posicion: Coordenadas,
    plantas: Iterable[object],
    *,
    radio_km: float = RADIO_GEOCERCA_KM_PREDETERMINADO,
) -> ResultadoGeocercaPlanta:
    """`plantas`: objetos con `planta_id`, `nombre`, `latitud`, `longitud`
    (p. ej. `atlas_core.catalogo_plantas.Planta`) -- opcionalmente
    `tipo_geocerca`/`vertices` (Bloque PLANTAS P3): si la planta es
    POLIGONAL y trae vértices, se usa contención real (point-in-polygon)
    en vez de distancia a un centroide; si no, comportamiento CIRCULAR de
    siempre, sin cambios (incluida su regla de desempate: la más cercana
    gana, ambigüedad solo si dos o más quedan a la MISMA distancia
    mínima exacta). Ignora plantas sin coordenadas/vértices. Un punto
    dentro de una planta POLIGONAL y a la vez cerca de cualquier otra
    planta (poligonal o circular) es ambigüedad real -- no hay una
    medida común (contención vs. distancia) con la que desempatar."""
    poligonales: list[object] = []
    circulares: list[tuple[float, object]] = []
    for planta in plantas:
        tipo = getattr(planta, "tipo_geocerca", "CIRCULAR")
        vertices = getattr(planta, "vertices", ()) or ()
        if tipo == "POLIGONAL" and vertices:
            if punto_en_poligono(posicion, vertices):
                poligonales.append(planta)
            continue
        latitud = getattr(planta, "latitud", None)
        longitud = getattr(planta, "longitud", None)
        if latitud is None or longitud is None:
            continue
        distancia = distancia_km_haversine(posicion, Coordenadas(longitud, latitud))
        if distancia <= radio_km:
            circulares.append((distancia, planta))

    if not poligonales and not circulares:
        return ResultadoGeocercaPlanta(None, None, None, False, "FUERA_DE_GEOCERCA")
    if len(poligonales) > 1 or (poligonales and circulares):
        return ResultadoGeocercaPlanta(None, None, None, False, "AMBIGUO_ENTRE_PLANTAS")
    if poligonales:
        planta = poligonales[0]
        return ResultadoGeocercaPlanta(
            planta.planta_id, planta.nombre, None, True, "DENTRO_DE_GEOCERCA"
        )

    # Solo candidatas CIRCULARES -- comportamiento original, sin cambios.
    circulares.sort(key=lambda par: par[0])
    mejor_distancia = circulares[0][0]
    empatadas = [planta for distancia, planta in circulares if distancia == mejor_distancia]
    if len(empatadas) > 1:
        return ResultadoGeocercaPlanta(None, None, mejor_distancia, False, "AMBIGUO_ENTRE_PLANTAS")
    planta = empatadas[0]
    return ResultadoGeocercaPlanta(
        planta.planta_id, planta.nombre, mejor_distancia, True, "DENTRO_DE_GEOCERCA"
    )
