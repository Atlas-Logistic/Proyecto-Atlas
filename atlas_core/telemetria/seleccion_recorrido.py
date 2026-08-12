"""Selección automática de RECORRIDO_OPERACIONAL_GPS (Bloque TELEMETRÍA T2).

Un viaje logístico real puede quedar fragmentado por el proveedor de
telemetría en varios `trips` (caso real 463630: Santiago -> Coronel quedó
partido en 2 trips consecutivos por Onelogis, con un hueco de ~51 min
entre ambos). Este módulo construye, a partir de la lista de trips de UN
día para UNA patente (ya obtenida vía `ServicioTelemetria`, con caché),
la cadena de 1..N trips que mejor representa el viaje documental --
usando solo metadatos de trip (inicio/fin/distancia, sin red adicional)
para la selección, y breadcrumbs (ya cacheados o a pedir) solo para la
cadena finalmente elegida.

Ningún umbral aquí es arbitrario sin evidencia: `distancia_minima_km` y
`gap_maximo_min` están calibrados contra el único caso real multi-trip
conocido (463630: hueco real entre trips consecutivos ~51 min, con punto
final de un trip a ~20 m del punto inicial del siguiente) -- ver
`docs/BITACORA_TECNICA_CRONOLOGICA.md`, bloque TELEMETRÍA T2.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Iterable

from atlas_core.catalogo_plantas import Planta
from atlas_core.rutas.geocerca import (
    RADIO_GEOCERCA_KM_PREDETERMINADO,
    ResultadoGeocercaPlanta,
    distancia_km_haversine,
    punto_en_poligono,
    resolver_planta_por_posicion,
)
from atlas_core.rutas.modelos import Coordenadas
from atlas_core.telemetria.modelos import (
    DetencionTelemetria,
    EstadoConcordanciaHora,
    EstadoSeleccionRecorrido,
    EstadoTelemetria,
    EvidenciaOrigenPlanta,
    PosicionTelemetria,
    RecorridoOperacionalTelemetria,
    ResultadoSeleccionRecorrido,
    ViajeTelemetria,
)
from atlas_core.telemetria.servicio import ServicioTelemetria

# Calibrados contra el caso real 463630 (única evidencia multi-trip
# disponible hoy): la distancia mínima separa "movimiento real" de ruido
# GPS de maniobra/ignición (trips reales observados: 16-258 km; ruido
# observado: -0.03 a 1.71 km) -- 5 km deja margen amplio sobre ambos
# extremos sin adivinar. El hueco máximo (51 min real, entre 30430425 y
# 30434174) se redondea con margen generoso a 90 min para tolerar una
# parada de descanso sin fusionar tramos de días/rutas distintas.
DISTANCIA_MINIMA_KM_PREDETERMINADA = 5.0
GAP_MAXIMO_MIN_PREDETERMINADO = 90.0
TOLERANCIA_ANCLA_MIN_PREDETERMINADA = 15.0
MARGEN_AMBIGUEDAD_MIN_PREDETERMINADO = 20.0


def _instante(texto: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(texto).strip())
    except (TypeError, ValueError):
        return None


def seleccionar_recorrido_operacional(
    viajes: tuple[ViajeTelemetria, ...],
    *,
    patente: str,
    fecha: str,
    hora_entrada: datetime | None,
    hora_salida: datetime | None,
    distancia_minima_km: float = DISTANCIA_MINIMA_KM_PREDETERMINADA,
    gap_maximo_min: float = GAP_MAXIMO_MIN_PREDETERMINADO,
    tolerancia_ancla_min: float = TOLERANCIA_ANCLA_MIN_PREDETERMINADA,
    margen_ambiguedad_min: float = MARGEN_AMBIGUEDAD_MIN_PREDETERMINADO,
) -> ResultadoSeleccionRecorrido:
    """Bloque TELEMETRÍA T2, Fases B/D/E. Puro -- no toca red ni caché,
    opera solo sobre la lista de trips ya obtenida. Nunca lanza.

    Ancla temporal (Fase B): `hora_salida` si existe (evidencia real más
    fuerte -- hora real registrada en planta); si no, `hora_entrada` +
    la secuencia posterior de trips (nunca se inventa una hora de
    salida). Sin ninguna de las dos, no hay con qué anclar la búsqueda
    -- `SIN_ANCLA_TEMPORAL`, no `TELEMETRIA_AMBIGUA` (son motivos
    distintos: aquí no hay evidencia documental con qué empezar, no hay
    varios candidatos plausibles)."""
    if not viajes:
        return ResultadoSeleccionRecorrido(
            EstadoSeleccionRecorrido.SIN_HISTORICO_GPS, motivo="SIN_TRIPS_EN_LA_FECHA"
        )
    ancla = hora_salida or hora_entrada
    if ancla is None:
        return ResultadoSeleccionRecorrido(
            EstadoSeleccionRecorrido.SIN_ANCLA_TEMPORAL, motivo="SIN_HORA_DOCUMENTAL"
        )

    con_instantes = []
    for viaje in viajes:
        inicio = _instante(viaje.inicio)
        fin = _instante(viaje.fin)
        if inicio is None or fin is None:
            continue
        con_instantes.append((viaje, inicio, fin))

    sustanciales = sorted(
        (
            (viaje, inicio, fin) for viaje, inicio, fin in con_instantes
            if viaje.distancia_km is not None and viaje.distancia_km >= distancia_minima_km
        ),
        key=lambda item: item[1],
    )
    tolerancia = timedelta(minutes=tolerancia_ancla_min)
    candidatos_seed = [item for item in sustanciales if item[1] >= ancla - tolerancia]
    if not candidatos_seed:
        return ResultadoSeleccionRecorrido(
            EstadoSeleccionRecorrido.SIN_HISTORICO_GPS,
            motivo="SIN_TRIPS_SUSTANCIALES_TRAS_ANCLA",
        )

    seed_viaje, seed_inicio, seed_fin = candidatos_seed[0]

    # Fase E -- ambigüedad real: otro trip sustancial, distinto del
    # elegido, empieza casi al mismo tiempo que el elegido -- no hay
    # forma de saber cuál es el correcto sin más evidencia.
    for viaje_rival, inicio_rival, _ in candidatos_seed[1:]:
        if viaje_rival is seed_viaje:
            continue
        if abs((inicio_rival - seed_inicio).total_seconds()) / 60 <= margen_ambiguedad_min:
            return ResultadoSeleccionRecorrido(
                EstadoSeleccionRecorrido.TELEMETRIA_AMBIGUA,
                motivo=(
                    f"DOS_TRIPS_SUSTANCIALES_CASI_SIMULTANEOS("
                    f"{seed_viaje.proveedor_trip_id},{viaje_rival.proveedor_trip_id})"
                ),
            )

    cadena = [(seed_viaje, seed_inicio, seed_fin)]
    huecos: list[float] = []
    for viaje, inicio, fin in candidatos_seed[1:]:
        anterior_fin = cadena[-1][2]
        gap_min = (inicio - anterior_fin).total_seconds() / 60
        if 0 <= gap_min <= gap_maximo_min:
            cadena.append((viaje, inicio, fin))
            huecos.append(gap_min)
        else:
            break

    distancia_total = sum(v.distancia_km for v, _, _ in cadena if v.distancia_km is not None)
    minutos_seed_a_ancla = abs((seed_inicio - ancla).total_seconds()) / 60
    # Ventana de normalización distinta según la fuerza del ancla (Fase B):
    # con hora_salida real, el trip debería arrancar casi de inmediato
    # (ventana angosta, 120 min). Con solo hora_entrada, el camión puede
    # llevar horas cargando antes de partir -- caso real 463630: 2 h 12 min
    # de carga documentada entre entrada y el trip sustancial de salida --
    # una ventana angosta ahí penalizaría injustamente un hallazgo correcto.
    ventana_min = 120.0 if hora_salida is not None else 240.0
    confianza = max(0.0, 1.0 - minutos_seed_a_ancla / ventana_min)
    confianza -= 0.05 * len(huecos)
    confianza = max(0.0, min(1.0, confianza))

    recorrido = RecorridoOperacionalTelemetria(
        patente=patente.strip().upper(),
        fecha=fecha,
        trip_ids=tuple(v.proveedor_trip_id for v, _, _ in cadena),
        inicio=cadena[0][0].inicio,
        fin=cadena[-1][0].fin,
        distancia_gps_total_km=round(distancia_total, 2),
        huecos_temporales_min=tuple(round(h, 1) for h in huecos),
        confianza=round(confianza, 3),
        evidencia_seleccion=(
            f"ancla={ancla.isoformat()};seed_trip={seed_viaje.proveedor_trip_id};"
            f"minutos_seed_a_ancla={minutos_seed_a_ancla:.1f};trips_encadenados={len(cadena)}"
        ),
    )
    return ResultadoSeleccionRecorrido(EstadoSeleccionRecorrido.SELECCIONADO, recorrido)


def obtener_breadcrumbs_recorrido(
    servicio: ServicioTelemetria, recorrido: RecorridoOperacionalTelemetria
) -> tuple[PosicionTelemetria, ...]:
    """Fase A/K -- pide breadcrumbs SOLO de los trips de la cadena ya
    seleccionada (nunca de toda la flota/día), reutilizando la caché de
    T1 (`ServicioTelemetria`) -- una guía ya procesada no vuelve a pedir
    los mismos breadcrumbs al regenerar el reporte."""
    puntos: list[PosicionTelemetria] = []
    for trip_id in recorrido.trip_ids:
        resultado = servicio.obtener_breadcrumbs(trip_id)
        if resultado.estado in (EstadoTelemetria.OK, EstadoTelemetria.RESULTADO_DESDE_CACHE):
            puntos.extend(resultado.puntos)
    return tuple(puntos)


def completar_recorrido_con_breadcrumbs(
    servicio: ServicioTelemetria, recorrido: RecorridoOperacionalTelemetria
) -> RecorridoOperacionalTelemetria:
    puntos = obtener_breadcrumbs_recorrido(servicio, recorrido)
    if not puntos:
        return recorrido
    return replace(recorrido, primer_punto=puntos[0], ultimo_punto=puntos[-1])


ORIGEN_GPS_CONFIRMADO = "ORIGEN_GPS_CONFIRMADO"
ORIGEN_GPS_CONFLICTO = "ORIGEN_GPS_CONFLICTO"
ORIGEN_GPS_NO_DETERMINADO = "ORIGEN_GPS_NO_DETERMINADO"
# Bloque TELEMETRÍA T3 -- distinto de NO_DETERMINADO: hay evidencia GPS
# REAL y fuerte de una detención prolongada (el vehículo estuvo
# estacionario), pero su coordenada no cae dentro de la geocerca de
# NINGUNA planta ya catalogada. Nunca se inventa un nombre de planta para
# esa coordenada -- se reporta la detención (coordenada, duración,
# solape con la hora documental) para revisión humana, honestamente
# distinta de "no hay evidencia de nada".
ORIGEN_GPS_ESTADIA_SIN_PLANTA = "ORIGEN_GPS_ESTADIA_SIN_PLANTA"


@dataclass(frozen=True)
class ResultadoOrigenGPS:
    estado: str = ORIGEN_GPS_NO_DETERMINADO
    planta_id: str = ""
    planta_nombre: str = ""
    hora_entrada_gps: str = ""
    hora_salida_gps: str = ""
    distancia_minima_km: float | None = None
    motivo: str = ""
    # Bloque TELEMETRÍA T3 -- poblados solo en ORIGEN_GPS_ESTADIA_SIN_PLANTA
    # (ver arriba): la detención real detectada, para que quede visible
    # aunque no se pueda nombrar una planta.
    latitud_estadia: float | None = None
    longitud_estadia: float | None = None
    duracion_estadia_min: float | None = None


# Calibrado con evidencia real (Bloque T3, caso AL1879/11-08-2026): los
# puntos de un mismo lugar de permanencia real (patio/planta) observados
# entre trips consecutivos varían 0.02-0.4 km entre sí (ruido GPS normal
# de un vehículo detenido) -- 0.6 km deja margen amplio sobre ese ruido
# sin llegar a fusionar dos lugares realmente distintos (la propia
# geocerca de planta, 1.5 km, es más ancha porque tolera imprecisión de
# la DIRECCIÓN de la planta, no del GPS del vehículo).
RADIO_COHERENCIA_DETENCION_KM = 0.6
# Detenciones más cortas que esto son ruido de maniobra/semáforo, no una
# permanencia operacional real (carga/descarga) -- sin evidencia real de
# paradas más breves siendo operacionalmente significativas, se usa un
# umbral conservador.
DURACION_MINIMA_DETENCION_MIN = 30.0
# Bloque ORIGEN O2 -- calibrado con evidencia real (464424/SB6486,
# 07-08-2026): dentro de la parada real confirmada (08:28-08:46 y
# 09:11-09:19, breadcrumbs con `evento=PERIODIC_ON`), la velocidad
# reportada por Onelogis nunca superó 16 km/h (maniobra/avance lento
# dentro del patio); en la aproximación y la salida reales, la
# velocidad ya estaba en 20-51 km/h. 18 km/h separa ambos grupos con
# margen. Un punto con velocidad reportada por encima de este umbral
# nunca extiende ni abre un cluster de detención -- sin este filtro, un
# tramo de aproximación/salida lento pero espacialmente cercano podía
# "puentear" dos paradas reales distintas en un solo cluster diluido
# (ver `detectar_detenciones`). Si el proveedor no informa velocidad
# (`None` -- no todo proveedor de telemetría la expone), se usa solo el
# criterio espacial, sin bloquear nada por falta de este dato.
VELOCIDAD_MAXIMA_DETENCION_KMH = 18.0


def detectar_detenciones(
    viajes: Iterable[ViajeTelemetria],
    breadcrumbs_por_trip: dict[str, tuple[PosicionTelemetria, ...]],
    *,
    radio_coherencia_km: float = RADIO_COHERENCIA_DETENCION_KM,
) -> tuple[DetencionTelemetria, ...]:
    """Bloque TELEMETRÍA T3 (Fase C), generalizado en Bloque ORIGEN O2 --
    infiere permanencias estacionarias reales agrupando la secuencia
    COMPLETA y ordenada de breadcrumbs de todos los trips en clusters
    espacio-temporales, sin depender de los límites de un trip
    individual.

    Bloque O2 -- causa raíz encontrada con evidencia real (464424): un
    trip de Onelogis puede contener una MICRO-DETENCIÓN real en el medio
    (el camión entra a un recinto, permanece ~10-15 min, sigue) sin que
    el trip completo alguna vez se detenga en el sentido de "primer y
    último punto del trip cercanos entre sí" -- el motor nunca se apaga,
    Onelogis lo registra todo como un único trip largo de "movimiento".
    La versión anterior (T3) solo miraba si el trip COMPLETO era
    estacionario de punta a punta, perdiendo estas paradas reales
    intermedias. Agrupar por CLUSTER de puntos (sin importar a qué trip
    pertenece cada uno) captura ambos casos: el hueco de telemetría
    entre trips (sin datos propios, caso real 463630) Y la parada real
    dentro de un trip más largo (caso real 464424).

    Un cluster se extiende mientras cada punto nuevo quede a
    `radio_coherencia_km` del PRIMER punto del cluster (referencia fija,
    evita que una deriva lenta acumulada rompa el cluster de a poco);
    un punto fuera de ese radio cierra el cluster vigente y abre uno
    nuevo. Se exige al menos 2 puntos por cluster -- un solo breadcrumb
    es una única foto instantánea, nunca prueba permanencia. Nunca
    infiere una detención sin coherencia espacial real entre los
    puntos."""
    puntos_con_trip: list[tuple[PosicionTelemetria, str]] = []
    for viaje in viajes:
        for punto in breadcrumbs_por_trip.get(viaje.proveedor_trip_id, ()):
            puntos_con_trip.append((punto, viaje.proveedor_trip_id))
    puntos_con_trip.sort(key=lambda par: _instante(par[0].timestamp) or datetime.min)

    detenciones: list[DetencionTelemetria] = []
    cluster: list[tuple[PosicionTelemetria, str]] = []

    def cerrar_cluster() -> None:
        if len(cluster) < 2:
            cluster.clear()
            return
        primer_punto, _ = cluster[0]
        ultimo_punto, _ = cluster[-1]
        inicio_dt = _instante(primer_punto.timestamp)
        fin_dt = _instante(ultimo_punto.timestamp)
        if inicio_dt is not None and fin_dt is not None and fin_dt > inicio_dt:
            trip_ids = tuple(dict.fromkeys(tid for _, tid in cluster))
            detenciones.append(DetencionTelemetria(
                inicio=primer_punto.timestamp,
                fin=ultimo_punto.timestamp,
                duracion_minutos=round((fin_dt - inicio_dt).total_seconds() / 60.0, 1),
                latitud=ultimo_punto.latitud,
                longitud=ultimo_punto.longitud,
                fuente=(
                    "CLUSTER_MULTI_TRIP" if len(trip_ids) > 1 else "CLUSTER_UNICO_TRIP"
                ),
                trip_ids=trip_ids,
                puntos=tuple(p for p, _ in cluster),
            ))
        cluster.clear()

    for punto, trip_id in puntos_con_trip:
        # Un punto con velocidad real por encima del umbral es movimiento
        # real -- nunca abre ni extiende un cluster de detención (caso
        # real 464424: sin este filtro, la aproximación/salida lenta
        # pero espacialmente cercana "puenteaba" dos paradas reales
        # distintas en un único cluster diluido). Sin velocidad
        # informada por el proveedor (`None`), no se bloquea nada por
        # este criterio -- solo el espacial.
        if punto.velocidad is not None and punto.velocidad > VELOCIDAD_MAXIMA_DETENCION_KMH:
            cerrar_cluster()
            continue
        if not cluster:
            cluster.append((punto, trip_id))
            continue
        # Centroide corriente del cluster (no el primer punto fijo): una
        # detención real de varias decenas de minutos puede derivar
        # lentamente dentro del mismo patio (caso real 464424, ~58 min)
        # -- comparar contra un punto fijo del inicio puede acabar
        # comparando contra un punto ya lejano del resto del cluster.
        # El centroide se adapta con el cluster sin perder coherencia.
        lat_centroide = sum(p.latitud for p, _ in cluster) / len(cluster)
        lon_centroide = sum(p.longitud for p, _ in cluster) / len(cluster)
        coherente = distancia_km_haversine(
            Coordenadas(punto.longitud, punto.latitud),
            Coordenadas(lon_centroide, lat_centroide),
        ) <= radio_coherencia_km
        if not coherente:
            cerrar_cluster()
        cluster.append((punto, trip_id))
    cerrar_cluster()

    return tuple(detenciones)


def _solape_minutos(
    inicio_a: datetime | None, fin_a: datetime | None,
    inicio_b: datetime | None, fin_b: datetime | None,
) -> float:
    """Minutos de solape entre dos intervalos temporales -- 0.0 si no
    solapan o falta algún dato (nunca negativo, nunca inventa solape sin
    ambos rangos)."""
    if inicio_a is None or fin_a is None or inicio_b is None or fin_b is None:
        return 0.0
    inicio_solape = max(inicio_a, inicio_b)
    fin_solape = min(fin_a, fin_b)
    if fin_solape <= inicio_solape:
        return 0.0
    return (fin_solape - inicio_solape).total_seconds() / 60.0


def detectar_entrada_salida_planta(
    puntos: tuple[PosicionTelemetria, ...],
    plantas: Iterable[Planta],
    *,
    radio_km: float = RADIO_GEOCERCA_KM_PREDETERMINADO,
) -> ResultadoOrigenGPS:
    """Fase C -- tolerancia por geocerca (`radio_km`, mismo radio ya
    calibrado y en uso para planta origen por GPS desde Bloque
    PLANTA-P1), nunca un punto exacto. `hora_entrada_gps`/
    `hora_salida_gps` son el primer y último instante del recorrido
    dentro del radio -- evidencia GPS separada, nunca sobrescribe
    hora_entrada_aza/hora_salida_aza documentales.

    Bloque PLANTAS P3 -- esta función evalúa CADA punto de forma
    independiente ("¿este punto suelto cae cerca de una planta?"), lo
    que es evidencia razonable para geocercas CIRCULARES pequeñas (1.5
    km: un vehículo solo pasa "cerca" brevemente si realmente pasa junto
    a la planta) pero NO para geocercas POLIGONALES del tamaño de un
    recinto real: un camión que solo viaja por la vía pública ADYACENTE
    (caso real: SB6486 cruzando cerca de AZA COLINA en un tramo de 30 km
    hacia otro destino, nunca deteniéndose) puede dejar varios
    breadcrumbs sueltos DENTRO del polígono sin haber entrado nunca al
    recinto operacional. Por eso, plantas POLIGONALES quedan EXCLUIDAS
    de este chequeo por punto aislado -- solo se confirman por una
    detención real (`resolver_planta_origen_gps` -> `detectar_detenciones`
    + `_resolver_planta_para_detencion`, que exige mayoría de puntos
    DENTRO durante una permanencia real, no un tránsito)."""
    if not puntos:
        return ResultadoOrigenGPS(ORIGEN_GPS_NO_DETERMINADO, motivo="SIN_BREADCRUMBS")
    plantas = [
        p for p in plantas if getattr(p, "tipo_geocerca", "CIRCULAR") != "POLIGONAL"
    ]
    por_planta: dict[str, list[PosicionTelemetria]] = {}
    nombres: dict[str, str] = {}
    # Bloque PLANTAS P3: un match POLIGONAL no trae distancia a un
    # centroide (`resultado.distancia_km is None`, contención real, no
    # proximidad) -- se ignora para el mínimo sin romper el cálculo, la
    # distancia mínima queda `None` si NINGÚN punto tuvo una distancia
    # numérica (todos los matches fueron poligonales).
    distancias_minimas: dict[str, float | None] = {}
    for punto in puntos:
        resultado = resolver_planta_por_posicion(
            Coordenadas(punto.longitud, punto.latitud), plantas, radio_km=radio_km
        )
        if resultado.determinada:
            por_planta.setdefault(resultado.planta_id, []).append(punto)
            nombres[resultado.planta_id] = resultado.planta_nombre
            if resultado.distancia_km is not None:
                actual = distancias_minimas.get(resultado.planta_id)
                if actual is None or resultado.distancia_km < actual:
                    distancias_minimas[resultado.planta_id] = resultado.distancia_km
            else:
                distancias_minimas.setdefault(resultado.planta_id, None)

    if not por_planta:
        return ResultadoOrigenGPS(ORIGEN_GPS_NO_DETERMINADO, motivo="NINGUN_PUNTO_DENTRO_DE_GEOCERCA")
    if len(por_planta) > 1:
        return ResultadoOrigenGPS(
            ORIGEN_GPS_CONFLICTO,
            motivo="RECORRIDO_PASA_CERCA_DE_MAS_DE_UNA_PLANTA(" + ",".join(sorted(por_planta)) + ")",
        )

    (planta_id, puntos_planta), = por_planta.items()
    distancia_final = distancias_minimas[planta_id]
    return ResultadoOrigenGPS(
        ORIGEN_GPS_CONFIRMADO,
        planta_id=planta_id,
        planta_nombre=nombres[planta_id],
        hora_entrada_gps=puntos_planta[0].timestamp,
        hora_salida_gps=puntos_planta[-1].timestamp,
        distancia_minima_km=round(distancia_final, 3) if distancia_final is not None else None,
    )


# Bloque OPERACIÓN REAL R1 -- causa raíz encontrada: la resolución de
# planta origen del documento (letterhead "CASA MATRIZ PLANTA RENCA",
# idéntico en TODAS las guías AZA sin importar desde qué planta despacha
# cada camión -- ver `origen_documental.py`) siempre "resuelve" a RENCA
# aunque el camión real haya salido de Colina; y la selección de
# "recorrido operacional" de T2 (Fase A) exige `distancia_km >= 5` para
# considerar un trip -- un tramo corto de maniobra DENTRO de la planta
# (el que realmente pasa por su geocerca) queda descartado, dejando el
# primer punto útil ya en carretera, lejos de cualquier planta. Esta
# función corrige ambas cosas: ventana temporal amplia alrededor de la
# hora documental, SIN filtro de distancia mínima (incluye tramos de
# maniobra), y solo entra en juego con evidencia GPS real -- nunca
# asume Renca ni ninguna otra planta por defecto.
MARGEN_HORAS_PLANTA_PREDETERMINADO = 4.0

# Bloque ORIGEN O2 -- la pregunta correcta no es "¿qué plantas visitó el
# vehículo hoy?" sino "¿en qué planta estuvo cargando durante la
# ventana ENTRADA→SALIDA de ESTE viaje?" (`hora_entrada_aza`/
# `hora_salida_aza` son horas REALES registradas en planta, ancla
# temporal fuerte). `MARGEN_HORAS_PLANTA_PREDETERMINADO` (arriba) sigue
# usándose solo para RECOLECTAR trips/breadcrumbs candidatos (ventana
# amplia, ±4h) -- nunca para decidir cuál planta ganó, eso ahora lo hace
# el score por solape con la ventana documental real, no con la ventana
# de recolección.

# Si solo hay UNA hora documental (falta la otra), se usa como ancla
# más débil con un margen simétrico configurable alrededor -- nunca se
# inventa la hora faltante. Reutiliza el mismo margen ya calibrado en
# T2 para encadenar trips (`GAP_MAXIMO_MIN_PREDETERMINADO`, hueco real
# más largo conocido ~51 min, con margen amplio) en vez de inventar un
# número nuevo sin evidencia.
MARGEN_VENTANA_UNA_HORA_MIN = GAP_MAXIMO_MIN_PREDETERMINADO

# Pesos del score de evidencia por planta (Fase C) -- suman 1.0. El
# solape con la ventana documental real domina (es la pregunta que
# Javier pidió responder); continuidad castiga evidencia fragmentada en
# muchos toques breves frente a una sola permanencia real; la
# proximidad de entrada/salida GPS a las horas documentales corrobora
# sin reemplazar al solape.
PESO_SOLAPE_VENTANA = 0.50
PESO_CONTINUIDAD = 0.20
PESO_PROXIMIDAD_SALIDA = 0.15
PESO_PROXIMIDAD_ENTRADA = 0.15

# Una diferencia de 60+ min entre la hora documental y la entrada/salida
# GPS ya no aporta nada al score de proximidad (decae linealmente a 0)
# -- más amplio que la tolerancia de concordancia de hora ya calibrada
# en T2 (`TOLERANCIA_ANCLA_MIN_PREDETERMINADA`=15 min) porque aquí se
# usa como señal continua de apoyo, no como corte binario.
VENTANA_PROXIMIDAD_MIN = 60.0

# Fase D: dos plantas con evidencia real en la MISMA ventana documental
# son un conflicto real solo si NO hay margen suficiente entre sus
# scores para preferir una con confianza -- 0.15 exige que la líder
# saque una ventaja clara (no solo estar técnicamente adelante) antes
# de descartar la segunda como ruido.
MARGEN_SCORE_SUFICIENTE = 0.15


def _proximidad_score(instante_gps: datetime | None, instante_documental: datetime | None) -> float:
    """1.0 si coinciden exactamente, decae linealmente a 0.0 a partir de
    `VENTANA_PROXIMIDAD_MIN` minutos de diferencia -- 0.0 (neutro, nunca
    penaliza de más) si falta cualquiera de los dos instantes."""
    if instante_gps is None or instante_documental is None:
        return 0.0
    diferencia_min = abs((instante_gps - instante_documental).total_seconds()) / 60.0
    return max(0.0, 1.0 - diferencia_min / VENTANA_PROXIMIDAD_MIN)


# Bloque PLANTAS P3, Fase E -- una detención dentro de un recinto
# POLIGONAL nunca exige que el 100% de sus puntos caigan adentro
# (maniobras cerca de accesos/bordes del recinto son normales, ver caso
# real AL1879: puntos junto al borde del polígono durante la salida).
# 0.5 es el umbral literal de "mayoritariamente" pedido -- más de la
# mitad de los puntos reales observados durante la detención.
PROPORCION_MINIMA_DENTRO_POLIGONO = 0.5


def _resolver_planta_para_detencion(
    puntos_detencion: tuple[PosicionTelemetria, ...],
    coordenada_representativa: Coordenadas,
    plantas: list[Planta],
    *,
    radio_km: float,
    proporcion_minima_poligono: float = PROPORCION_MINIMA_DENTRO_POLIGONO,
) -> ResultadoGeocercaPlanta:
    """Variante de `resolver_planta_por_posicion` para EVALUAR una
    detención completa (no un punto suelto): para plantas POLIGONALES,
    usa la PROPORCIÓN de los puntos reales de la detención que caen
    dentro del recinto (`proporcion_minima_poligono`, nunca el 100%) en
    vez de un solo punto representativo; para plantas CIRCULARES,
    comportamiento sin cambios (distancia del punto representativo al
    centroide, igual que `resolver_planta_por_posicion` -- Fase H: no se
    toca Renca). Un match poligonal junto con cualquier otro match
    (poligonal o circular) es ambigüedad real -- no hay una medida común
    con la que desempatar."""
    poligonales: list[tuple[object, float]] = []
    circulares: list[tuple[float, object]] = []
    for planta in plantas:
        tipo = getattr(planta, "tipo_geocerca", "CIRCULAR")
        vertices = getattr(planta, "vertices", ()) or ()
        if tipo == "POLIGONAL" and vertices:
            if not puntos_detencion:
                continue
            dentro = sum(
                1 for p in puntos_detencion
                if punto_en_poligono(Coordenadas(p.longitud, p.latitud), vertices)
            )
            proporcion = dentro / len(puntos_detencion)
            if proporcion >= proporcion_minima_poligono:
                poligonales.append((planta, proporcion))
            continue
        latitud = getattr(planta, "latitud", None)
        longitud = getattr(planta, "longitud", None)
        if latitud is None or longitud is None:
            continue
        distancia = distancia_km_haversine(
            coordenada_representativa, Coordenadas(longitud, latitud)
        )
        if distancia <= radio_km:
            circulares.append((distancia, planta))

    if not poligonales and not circulares:
        return ResultadoGeocercaPlanta(None, None, None, False, "FUERA_DE_GEOCERCA")
    if len(poligonales) > 1 or (poligonales and circulares):
        return ResultadoGeocercaPlanta(None, None, None, False, "AMBIGUO_ENTRE_PLANTAS")
    if poligonales:
        planta, proporcion = poligonales[0]
        return ResultadoGeocercaPlanta(
            planta.planta_id, planta.nombre, None, True,
            f"DENTRO_DE_POLIGONO;proporcion_puntos_dentro={round(proporcion, 3)}",
        )

    circulares.sort(key=lambda par: par[0])
    mejor_distancia = circulares[0][0]
    empatadas = [planta for distancia, planta in circulares if distancia == mejor_distancia]
    if len(empatadas) > 1:
        return ResultadoGeocercaPlanta(None, None, mejor_distancia, False, "AMBIGUO_ENTRE_PLANTAS")
    planta = empatadas[0]
    return ResultadoGeocercaPlanta(
        planta.planta_id, planta.nombre, mejor_distancia, True, "DENTRO_DE_GEOCERCA"
    )


def resolver_planta_origen_gps(
    servicio: ServicioTelemetria,
    *,
    patente: str,
    fecha: date,
    hora_entrada: datetime | None,
    hora_salida: datetime | None,
    plantas: Iterable[Planta],
    radio_km: float = RADIO_GEOCERCA_KM_PREDETERMINADO,
    margen_horas: float = MARGEN_HORAS_PLANTA_PREDETERMINADO,
) -> ResultadoOrigenGPS:
    """Identifica desde qué planta SALE realmente el camión (Fase B/C),
    usando una ventana temporal amplia (`margen_horas`, calibrado con
    margen sobre el mayor hueco real conocido hasta hoy: ~2 h 48 min
    entre la hora documental y el paso confirmado por geocerca en
    463630) alrededor del ancla documental -- nunca solo el primer trip
    "sustancial" de la entrega (ver T2, limitación conocida). Sin hora
    documental o sin histórico en la ventana, se abstiene explícitamente
    -- nunca asume una planta por defecto.

    Bloque TELEMETRÍA T3, Fase H -- corrige un límite real de R1/R1.1:
    la ventana se anclaba SOLO en `hora_salida` (o `hora_entrada` si
    faltaba la salida), nunca en ambas a la vez. Con las dos horas
    documentales lejos entre sí (caso real 464641/642: entrada 09:46,
    salida 14:39, casi 5h de separación), anclar solo en la salida podía
    dejar FUERA de la ventana trips reales cerca de la hora de entrada
    -- justo donde suele estar la evidencia de estadía en planta. Ahora
    la ventana cubre `[entrada, salida]` completo (o el único ancla
    disponible) con `margen_horas` de margen a cada lado, nunca solo un
    punto."""
    anclas = [instante for instante in (hora_entrada, hora_salida) if instante is not None]
    if not anclas:
        return ResultadoOrigenGPS(ORIGEN_GPS_NO_DETERMINADO, motivo="SIN_HORA_DOCUMENTAL")
    ancla_desde, ancla_hasta = min(anclas), max(anclas)

    resultado_viajes = servicio.buscar_viajes(patente, fecha, fecha)
    if resultado_viajes.estado not in (EstadoTelemetria.OK, EstadoTelemetria.RESULTADO_DESDE_CACHE):
        return ResultadoOrigenGPS(ORIGEN_GPS_NO_DETERMINADO, motivo=resultado_viajes.estado.value)

    margen = timedelta(hours=margen_horas)
    ventana_desde, ventana_hasta = ancla_desde - margen, ancla_hasta + margen
    cercanos = []
    for viaje in resultado_viajes.viajes:
        inicio = _instante(viaje.inicio)
        fin = _instante(viaje.fin)
        if inicio is None or fin is None:
            continue
        if fin >= ventana_desde and inicio <= ventana_hasta:
            cercanos.append(viaje)
    if not cercanos:
        return ResultadoOrigenGPS(ORIGEN_GPS_NO_DETERMINADO, motivo="SIN_TRIPS_EN_VENTANA_TEMPORAL")

    cercanos_ordenados = sorted(cercanos, key=lambda v: _instante(v.inicio) or datetime.min)
    breadcrumbs_por_trip: dict[str, tuple[PosicionTelemetria, ...]] = {}
    puntos: list[PosicionTelemetria] = []
    for viaje in cercanos_ordenados:
        resultado_bc = servicio.obtener_breadcrumbs(viaje.proveedor_trip_id)
        if resultado_bc.estado in (EstadoTelemetria.OK, EstadoTelemetria.RESULTADO_DESDE_CACHE):
            breadcrumbs_por_trip[viaje.proveedor_trip_id] = resultado_bc.puntos
            puntos.extend(resultado_bc.puntos)

    plantas = list(plantas)

    # Bloque ORIGEN O2, Fase H -- ventana documental REAL de carga: la
    # pregunta no es "qué plantas visitó el vehículo hoy" sino "en qué
    # planta estuvo cargando durante ESTA ventana". Con ambas horas,
    # [entrada, salida] exacto; con solo una, un margen simétrico
    # alrededor (ancla más débil); nunca se inventa la hora faltante.
    if hora_entrada is not None and hora_salida is not None:
        ventana_ini, ventana_fin = min(hora_entrada, hora_salida), max(hora_entrada, hora_salida)
    else:
        ancla_unica = hora_entrada or hora_salida
        margen_unica = timedelta(minutes=MARGEN_VENTANA_UNA_HORA_MIN)
        ventana_ini, ventana_fin = ancla_unica - margen_unica, ancla_unica + margen_unica
    duracion_ventana_min = max(1.0, (ventana_fin - ventana_ini).total_seconds() / 60.0)

    # Bloque TELEMETRÍA T3, Fase D/I -- jerarquía de evidencia: una
    # detención real (estadía) dentro de la geocerca de una planta es la
    # evidencia MÁS fuerte de origen -- se evalúa antes que los
    # breadcrumbs sueltos (evidencia media/alta) y muy por delante de
    # cualquier fallback documental (Fase E de R1.1, ya eliminado).
    detenciones = detectar_detenciones(cercanos_ordenados, breadcrumbs_por_trip)
    detenciones_por_planta: dict[str, list[DetencionTelemetria]] = {}
    nombres_planta: dict[str, str] = {}
    mejor_estadia_sin_planta: DetencionTelemetria | None = None
    for detencion in detenciones:
        resultado_geocerca = _resolver_planta_para_detencion(
            detencion.puntos, Coordenadas(detencion.longitud, detencion.latitud),
            plantas, radio_km=radio_km,
        )
        if resultado_geocerca.determinada:
            detenciones_por_planta.setdefault(resultado_geocerca.planta_id, []).append(detencion)
            nombres_planta[resultado_geocerca.planta_id] = resultado_geocerca.planta_nombre
        elif detencion.duracion_minutos >= DURACION_MINIMA_DETENCION_MIN and (
            mejor_estadia_sin_planta is None
            or detencion.duracion_minutos > mejor_estadia_sin_planta.duracion_minutos
        ):
            mejor_estadia_sin_planta = detencion

    # Evidencia media/alta (Fase I, T3): breadcrumbs sueltos que pasan
    # por una geocerca CIRCULAR. Si esa planta no tiene ya evidencia por
    # detención, se incorpora como detención(es) sintética(s) breve(s) --
    # misma vara de medir que cualquier otra evidencia (Fase C: nunca
    # depender de un único breadcrumb tratándolo como caso especial); por
    # su brevedad, casi siempre pierde frente a una detención real más
    # larga en el score, en vez de disparar un conflicto automático.
    #
    # Bug real encontrado (464424): agrupar TODOS los toques de una
    # planta en un solo span [primer_toque, último_toque] (como hacía
    # `detectar_entrada_salida_planta`) puede fusionar dos pasadas
    # rápidas SEPARADAS (velocidad 64-88 km/h -- el camión solo cruza la
    # vía pública cercana, dos veces, sin detenerse) en una sola
    # "detención sintética" de casi 100 min, como si hubiera permanecido
    # ahí todo ese tiempo. Se agrupan los toques por proximidad temporal
    # real (mismo criterio que encadenar trips, `GAP_MAXIMO_MIN_PREDETERMINADO`)
    # -- toques separados por más de eso son eventos DISTINTOS, cada uno
    # con su propia duración mínima, nunca conflados.
    resultado_breadcrumbs = detectar_entrada_salida_planta(tuple(puntos), plantas, radio_km=radio_km)
    for planta in plantas:
        if getattr(planta, "tipo_geocerca", "CIRCULAR") == "POLIGONAL":
            continue
        if planta.planta_id in detenciones_por_planta:
            continue
        if planta.latitud is None or planta.longitud is None:
            continue
        coordenada_planta = Coordenadas(planta.longitud, planta.latitud)
        puntos_planta = sorted(
            (
                p for p in puntos
                if distancia_km_haversine(Coordenadas(p.longitud, p.latitud), coordenada_planta) <= radio_km
            ),
            key=lambda p: _instante(p.timestamp) or datetime.min,
        )
        if not puntos_planta:
            continue
        grupos: list[list[PosicionTelemetria]] = [[puntos_planta[0]]]
        for punto in puntos_planta[1:]:
            anterior = _instante(grupos[-1][-1].timestamp)
            actual = _instante(punto.timestamp)
            if (
                anterior is not None and actual is not None
                and (actual - anterior).total_seconds() / 60.0 <= GAP_MAXIMO_MIN_PREDETERMINADO
            ):
                grupos[-1].append(punto)
            else:
                grupos.append([punto])
        sinteticas = []
        for grupo in grupos:
            inicio_dt = _instante(grupo[0].timestamp)
            fin_dt = _instante(grupo[-1].timestamp)
            if inicio_dt is None or fin_dt is None:
                continue
            duracion_grupo = max(0.1, (fin_dt - inicio_dt).total_seconds() / 60.0)
            sinteticas.append(DetencionTelemetria(
                inicio=grupo[0].timestamp,
                fin=grupo[-1].timestamp,
                duracion_minutos=round(duracion_grupo, 1),
                latitud=grupo[-1].latitud,
                longitud=grupo[-1].longitud,
                fuente="BREADCRUMB_SUELTO",
                trip_ids=(),
                puntos=tuple(grupo),
            ))
        if sinteticas:
            detenciones_por_planta[planta.planta_id] = sinteticas
            nombres_planta[planta.planta_id] = planta.nombre

    if not detenciones_por_planta:
        # Los breadcrumbs sueltos por sí solos ya son ambiguos (tocan
        # 2+ plantas circulares) -- ninguna detención qué comparar
        # contra qué, esto se conserva tal cual (comportamiento de T2/R1,
        # sin cambios).
        if resultado_breadcrumbs.estado == ORIGEN_GPS_CONFLICTO:
            return resultado_breadcrumbs
        # Nada calza con ninguna planta catalogada -- si de todas formas
        # hay una detención real y prolongada en algún otro lugar (Fase
        # K, "nunca se descarta en silencio"), se reporta honestamente
        # con su coordenada y duración, sin inventar el nombre de
        # ninguna planta.
        if mejor_estadia_sin_planta is not None:
            return ResultadoOrigenGPS(
                ORIGEN_GPS_ESTADIA_SIN_PLANTA,
                motivo=(
                    "DETENCION_REAL_FUERA_DE_TODA_GEOCERCA;"
                    f"duracion_min={mejor_estadia_sin_planta.duracion_minutos};"
                    f"trips={'|'.join(mejor_estadia_sin_planta.trip_ids)}"
                ),
                latitud_estadia=mejor_estadia_sin_planta.latitud,
                longitud_estadia=mejor_estadia_sin_planta.longitud,
                duracion_estadia_min=mejor_estadia_sin_planta.duracion_minutos,
            )
        return ResultadoOrigenGPS(ORIGEN_GPS_NO_DETERMINADO, motivo="NINGUN_PUNTO_DENTRO_DE_GEOCERCA")

    # Bloque ORIGEN O2, Fase A/C -- una EvidenciaOrigenPlanta por
    # candidata, puntuada contra la ventana documental real (no contra
    # la ventana amplia de recolección). Una visita fuera de la ventana
    # documental no aporta `duracion_dentro_min` (el solape con esa
    # visita es 0) -- Fase B: nunca produce conflicto contra la planta
    # donde realmente ocurrió la carga.
    evidencias: dict[str, EvidenciaOrigenPlanta] = {}
    for planta_id, lista in detenciones_por_planta.items():
        solapes = [
            (max(0.0, _solape_minutos(_instante(d.inicio), _instante(d.fin), ventana_ini, ventana_fin)), d)
            for d in lista
        ]
        duracion_dentro = sum(solape for solape, _ in solapes)
        mejor_solape = max((solape for solape, _ in solapes), default=0.0)
        continuidad = (mejor_solape / duracion_dentro) if duracion_dentro > 0 else 0.0
        porcentaje_ventana = min(100.0, duracion_dentro / duracion_ventana_min * 100)
        entrada_gps = min((d.inicio for d in lista), default="")
        salida_gps = max((d.fin for d in lista), default="")
        total_puntos_planta = sum(len(d.puntos) for d in lista)
        porcentaje_puntos = (total_puntos_planta / len(puntos) * 100) if puntos else 0.0
        score = (
            PESO_SOLAPE_VENTANA * (porcentaje_ventana / 100)
            + PESO_CONTINUIDAD * continuidad
            + PESO_PROXIMIDAD_SALIDA * _proximidad_score(_instante(salida_gps), hora_salida)
            + PESO_PROXIMIDAD_ENTRADA * _proximidad_score(_instante(entrada_gps), hora_entrada)
        )
        evidencias[planta_id] = EvidenciaOrigenPlanta(
            planta_id=planta_id,
            planta_nombre=nombres_planta[planta_id],
            duracion_dentro_min=round(duracion_dentro, 1),
            porcentaje_ventana=round(porcentaje_ventana, 1),
            porcentaje_puntos=round(porcentaje_puntos, 1),
            entrada_gps=entrada_gps,
            salida_gps=salida_gps,
            estadias=tuple(lista),
            score=round(score, 4),
            motivos=(
                f"solape_ventana={round(porcentaje_ventana, 1)}%",
                f"duracion_dentro_min={round(duracion_dentro, 1)}",
                f"continuidad={round(continuidad, 2)}",
            ),
        )

    ranking = sorted(evidencias.values(), key=lambda e: e.score, reverse=True)
    lider = ranking[0]
    margen_vs_siguiente = (lider.score - ranking[1].score) if len(ranking) > 1 else None

    if margen_vs_siguiente is None or margen_vs_siguiente >= MARGEN_SCORE_SUFICIENTE:
        estadia_principal = max(lider.estadias, key=lambda d: d.duracion_minutos)
        planta_confirmada = next((p for p in plantas if p.planta_id == lider.planta_id), None)
        # Bloque PLANTAS P3: para una planta POLIGONAL, "distancia al
        # centroide" no es la evidencia que confirmó nada (la contención
        # real en el polígono sí) y puede ser grande y confusa de leer
        # junto a un CONFIRMADO (ver AZA COLINA: 18 km a la dirección
        # histórica, sin relación con la detección real) -- se deja en
        # `None`. Tampoco aplica si la única evidencia es un breadcrumb
        # suelto sintético (sin coordenada real propia).
        es_poligonal = (
            planta_confirmada is not None
            and getattr(planta_confirmada, "tipo_geocerca", "CIRCULAR") == "POLIGONAL"
        )
        distancia_min = (
            round(distancia_km_haversine(
                Coordenadas(estadia_principal.longitud, estadia_principal.latitud),
                Coordenadas(planta_confirmada.longitud, planta_confirmada.latitud),
            ), 3)
            if planta_confirmada is not None
            and not es_poligonal
            and estadia_principal.fuente != "BREADCRUMB_SUELTO"
            else None
        )
        motivo_margen = (
            f"margen_vs_siguiente={round(margen_vs_siguiente, 4)};" if margen_vs_siguiente is not None else ""
        )
        return ResultadoOrigenGPS(
            ORIGEN_GPS_CONFIRMADO,
            planta_id=lider.planta_id,
            planta_nombre=lider.planta_nombre,
            hora_entrada_gps=lider.entrada_gps,
            hora_salida_gps=lider.salida_gps,
            distancia_minima_km=distancia_min,
            motivo=(
                f"VENTANA_DOCUMENTAL;score={lider.score};solape_ventana={lider.porcentaje_ventana}%;"
                f"duracion_dentro_min={lider.duracion_dentro_min};{motivo_margen}"
                f"trips={'|'.join(t for d in lider.estadias for t in d.trip_ids)}"
            ),
        )

    # Bloque ORIGEN O2, Fase D -- dos o más plantas con evidencia real
    # dentro de la MISMA ventana documental y sin margen suficiente para
    # distinguirlas: esto SÍ es un conflicto real (no una visita a otra
    # hora del mismo día, que ya quedó descartada como evidencia por el
    # solape con la ventana).
    top = ranking[:2]
    return ResultadoOrigenGPS(
        ORIGEN_GPS_CONFLICTO,
        motivo=(
            "CONFLICTO_REAL_EN_VENTANA("
            + ";".join(f"{e.planta_nombre}:score={e.score},solape={e.porcentaje_ventana}%" for e in top)
            + ")"
        ).replace(" ", "_"),
    )


def clasificar_concordancia_hora(
    instante_documental: datetime | None,
    instante_gps: datetime | None,
    *,
    tolerancia_min: float = 15.0,
) -> tuple[EstadoConcordanciaHora, str]:
    """Fase H -- nunca exige igualdad exacta (documento y GPS pueden
    diferir por minutos/segundos operacionales); clasifica, no corrige."""
    if instante_documental is None or instante_gps is None:
        return EstadoConcordanciaHora.NO_DISPONIBLE, ""
    diferencia_min = (instante_gps - instante_documental).total_seconds() / 60
    estado = (
        EstadoConcordanciaHora.CONCORDANTE
        if abs(diferencia_min) <= tolerancia_min
        else EstadoConcordanciaHora.DIVERGENTE
    )
    return estado, f"diferencia_min={diferencia_min:.1f}"
