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


def _es_estacionario(
    viaje: ViajeTelemetria,
    breadcrumbs_por_trip: dict[str, tuple[PosicionTelemetria, ...]],
    radio_km: float,
) -> tuple[bool, PosicionTelemetria | None, PosicionTelemetria | None]:
    puntos = breadcrumbs_por_trip.get(viaje.proveedor_trip_id) or ()
    # Un solo breadcrumb es una única foto instantánea -- no alcanza para
    # distinguir "estuvo detenido" de "iba en movimiento y solo se
    # registró un punto" (breadcrumbs incompletos/dispersos). Se exige
    # evidencia de al menos 2 puntos para afirmar estacionariedad; nunca
    # se infiere de un punto aislado.
    if len(puntos) < 2:
        return False, None, None
    inicio_pt, fin_pt = puntos[0], puntos[-1]
    distancia = distancia_km_haversine(
        Coordenadas(inicio_pt.longitud, inicio_pt.latitud),
        Coordenadas(fin_pt.longitud, fin_pt.latitud),
    )
    return distancia <= radio_km, inicio_pt, fin_pt


def detectar_detenciones(
    viajes: Iterable[ViajeTelemetria],
    breadcrumbs_por_trip: dict[str, tuple[PosicionTelemetria, ...]],
    *,
    radio_coherencia_km: float = RADIO_COHERENCIA_DETENCION_KM,
) -> tuple[DetencionTelemetria, ...]:
    """Bloque TELEMETRÍA T3, Fase C -- infiere permanencias estacionarias
    reales encadenando trips (y los huecos de telemetría ENTRE ellos, sin
    breadcrumbs propios) cuyos extremos quedan espacialmente coherentes:
    un trip es "estacionario" cuando su propio primer y último breadcrumb
    quedan a `radio_coherencia_km` uno de otro (ignition-cycling sin
    desplazamiento real); una cadena de trips estacionarios consecutivos
    cuyos puntos siguen coherentes entre sí forma UNA sola detención,
    desde el inicio del primer trip de la cadena hasta el fin del
    último -- el hueco de telemetría entre ellos (sin datos propios)
    queda cubierto implícitamente, igual que el caso real que motivó
    este bloque: "trip A termina en planta a las 08:55 + trip B empieza
    en planta a las 13:35" es evidencia de permanencia continua ahí,
    aunque no haya ningún breadcrumb entre esas dos horas.

    Nunca infiere una detención sin coherencia espacial real entre los
    puntos -- un trip de movimiento real (inicio y fin alejados entre sí)
    siempre corta la cadena."""
    viajes_con_datos = [
        v for v in viajes if breadcrumbs_por_trip.get(v.proveedor_trip_id)
    ]
    ordenados = sorted(viajes_con_datos, key=lambda v: _instante(v.inicio) or datetime.min)

    detenciones: list[DetencionTelemetria] = []
    bloque: list[tuple[ViajeTelemetria, PosicionTelemetria, PosicionTelemetria]] = []

    def cerrar_bloque() -> None:
        if not bloque:
            return
        primer_viaje = bloque[0][0]
        ultimo_viaje, _, ultimo_fin_pt = bloque[-1]
        inicio_dt = _instante(primer_viaje.inicio)
        fin_dt = _instante(ultimo_viaje.fin)
        if inicio_dt is not None and fin_dt is not None and fin_dt > inicio_dt:
            duracion_min = (fin_dt - inicio_dt).total_seconds() / 60.0
            detenciones.append(DetencionTelemetria(
                inicio=primer_viaje.inicio,
                fin=ultimo_viaje.fin,
                duracion_minutos=round(duracion_min, 1),
                latitud=ultimo_fin_pt.latitud,
                longitud=ultimo_fin_pt.longitud,
                fuente=(
                    "TRIPS_ESTACIONARIOS_ENCADENADOS" if len(bloque) > 1
                    else "TRIP_UNICO_ESTACIONARIO"
                ),
                trip_ids=tuple(v.proveedor_trip_id for v, _, _ in bloque),
            ))
        bloque.clear()

    for viaje in ordenados:
        estacionario, inicio_pt, fin_pt = _es_estacionario(
            viaje, breadcrumbs_por_trip, radio_coherencia_km
        )
        if not estacionario:
            cerrar_bloque()
            continue
        if bloque:
            _, _, punto_referencia = bloque[-1]
            coherente = distancia_km_haversine(
                Coordenadas(inicio_pt.longitud, inicio_pt.latitud),
                Coordenadas(punto_referencia.longitud, punto_referencia.latitud),
            ) <= radio_coherencia_km
            if not coherente:
                cerrar_bloque()
        bloque.append((viaje, inicio_pt, fin_pt))
    cerrar_bloque()

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

    # Bloque TELEMETRÍA T3, Fase D/I -- jerarquía de evidencia: una
    # detención real (estadía) dentro de la geocerca de una planta es la
    # evidencia MÁS fuerte de origen -- se evalúa antes que los
    # breadcrumbs sueltos (evidencia media/alta) y muy por delante de
    # cualquier fallback documental (Fase E de R1.1, ya eliminado).
    detenciones = detectar_detenciones(cercanos_ordenados, breadcrumbs_por_trip)
    detenciones_por_planta: dict[str, list[DetencionTelemetria]] = {}
    nombres_planta: dict[str, str] = {}
    motivo_geocerca_por_planta: dict[str, str] = {}
    mejor_estadia_sin_planta: DetencionTelemetria | None = None
    for detencion in detenciones:
        puntos_detencion = tuple(
            p for trip_id in detencion.trip_ids for p in breadcrumbs_por_trip.get(trip_id, ())
        )
        resultado_geocerca = _resolver_planta_para_detencion(
            puntos_detencion, Coordenadas(detencion.longitud, detencion.latitud),
            plantas, radio_km=radio_km,
        )
        if resultado_geocerca.determinada:
            detenciones_por_planta.setdefault(resultado_geocerca.planta_id, []).append(detencion)
            nombres_planta[resultado_geocerca.planta_id] = resultado_geocerca.planta_nombre
            motivo_geocerca_por_planta[resultado_geocerca.planta_id] = resultado_geocerca.motivo
        elif detencion.duracion_minutos >= DURACION_MINIMA_DETENCION_MIN and (
            mejor_estadia_sin_planta is None
            or detencion.duracion_minutos > mejor_estadia_sin_planta.duracion_minutos
        ):
            mejor_estadia_sin_planta = detencion

    # Evidencia media/alta (Fase I): breadcrumbs sueltos que pasan por
    # una geocerca, igual que antes de este bloque (comportamiento de R1
    # conservado) -- se calcula SIEMPRE, no solo cuando no hay detención,
    # porque también sirve para detectar un conflicto entre una estadía
    # confirmada y evidencia independiente de OTRA planta (Fase M, item
    # 10: nunca se ignora en silencio la señal más débil).
    resultado_breadcrumbs = detectar_entrada_salida_planta(tuple(puntos), plantas, radio_km=radio_km)

    if len(detenciones_por_planta) > 1:
        return ResultadoOrigenGPS(
            ORIGEN_GPS_CONFLICTO,
            motivo=(
                "DETENCION_CERCA_DE_MAS_DE_UNA_PLANTA("
                + ",".join(sorted(detenciones_por_planta)) + ")"
            ),
        )
    if len(detenciones_por_planta) == 1:
        (planta_id, lista_detenciones), = detenciones_por_planta.items()
        breadcrumbs_senalan_otra_planta = (
            resultado_breadcrumbs.estado == ORIGEN_GPS_CONFLICTO
            or (
                resultado_breadcrumbs.estado == ORIGEN_GPS_CONFIRMADO
                and resultado_breadcrumbs.planta_id != planta_id
            )
        )
        if breadcrumbs_senalan_otra_planta:
            nombre_detencion = nombres_planta.get(planta_id, planta_id)
            nombre_breadcrumb = resultado_breadcrumbs.planta_nombre or resultado_breadcrumbs.motivo
            return ResultadoOrigenGPS(
                ORIGEN_GPS_CONFLICTO,
                motivo=(
                    f"CONFLICTO_{nombre_detencion}_VS_{nombre_breadcrumb}"
                    f"(estadia_en={nombre_detencion};breadcrumb_aislado_en={nombre_breadcrumb})"
                ).replace(" ", "_"),
            )
        mejor = max(lista_detenciones, key=lambda d: d.duracion_minutos)
        planta_confirmada = next((p for p in plantas if p.planta_id == planta_id), None)
        # Bloque PLANTAS P3: para una planta POLIGONAL, "distancia al
        # centroide" no es la evidencia que confirmó nada (la contención
        # real en el polígono sí) y puede ser grande y confuso de leer
        # junto a un CONFIRMADO (ver AZA COLINA: 18 km a la dirección
        # histórica, sin relación con la detección real) -- se deja en
        # `None`, la proporción de puntos dentro ya queda en `motivo`.
        es_poligonal = (
            planta_confirmada is not None
            and getattr(planta_confirmada, "tipo_geocerca", "CIRCULAR") == "POLIGONAL"
        )
        distancia_min = (
            round(distancia_km_haversine(
                Coordenadas(mejor.longitud, mejor.latitud),
                Coordenadas(planta_confirmada.longitud, planta_confirmada.latitud),
            ), 3)
            if planta_confirmada is not None and not es_poligonal else None
        )
        solape_min = round(
            _solape_minutos(_instante(mejor.inicio), _instante(mejor.fin), hora_entrada, hora_salida), 1
        )
        motivo_geocerca = motivo_geocerca_por_planta.get(planta_id, "DENTRO_DE_GEOCERCA")
        return ResultadoOrigenGPS(
            ORIGEN_GPS_CONFIRMADO,
            planta_id=planta_id,
            planta_nombre=nombres_planta[planta_id],
            hora_entrada_gps=mejor.inicio,
            hora_salida_gps=mejor.fin,
            distancia_minima_km=distancia_min,
            motivo=(
                f"ESTADIA_EN_GEOCERCA({motivo_geocerca});duracion_min={mejor.duracion_minutos};"
                f"solape_documental_min={solape_min};trips={'|'.join(mejor.trip_ids)}"
            ),
        )

    # Sin ninguna detención dentro de una geocerca.
    if resultado_breadcrumbs.estado in (ORIGEN_GPS_CONFIRMADO, ORIGEN_GPS_CONFLICTO):
        return resultado_breadcrumbs

    # Nada calza con ninguna planta catalogada -- si de todas formas hay
    # una detención real y prolongada en algún otro lugar (Fase K, "nunca
    # se descarta en silencio"), se reporta honestamente con su
    # coordenada y duración, sin inventar el nombre de ninguna planta.
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

    return resultado_breadcrumbs


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
