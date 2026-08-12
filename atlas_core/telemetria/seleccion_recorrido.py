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
from datetime import datetime, timedelta
from typing import Iterable

from atlas_core.catalogo_plantas import Planta
from atlas_core.rutas.geocerca import RADIO_GEOCERCA_KM_PREDETERMINADO, resolver_planta_por_posicion
from atlas_core.rutas.modelos import Coordenadas
from atlas_core.telemetria.modelos import (
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


@dataclass(frozen=True)
class ResultadoOrigenGPS:
    estado: str = ORIGEN_GPS_NO_DETERMINADO
    planta_id: str = ""
    planta_nombre: str = ""
    hora_entrada_gps: str = ""
    hora_salida_gps: str = ""
    distancia_minima_km: float | None = None
    motivo: str = ""


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
    hora_entrada_aza/hora_salida_aza documentales."""
    if not puntos:
        return ResultadoOrigenGPS(ORIGEN_GPS_NO_DETERMINADO, motivo="SIN_BREADCRUMBS")
    plantas = list(plantas)
    por_planta: dict[str, list[PosicionTelemetria]] = {}
    nombres: dict[str, str] = {}
    distancias_minimas: dict[str, float] = {}
    for punto in puntos:
        resultado = resolver_planta_por_posicion(
            Coordenadas(punto.longitud, punto.latitud), plantas, radio_km=radio_km
        )
        if resultado.determinada:
            por_planta.setdefault(resultado.planta_id, []).append(punto)
            nombres[resultado.planta_id] = resultado.planta_nombre
            actual = distancias_minimas.get(resultado.planta_id)
            if actual is None or resultado.distancia_km < actual:
                distancias_minimas[resultado.planta_id] = resultado.distancia_km

    if not por_planta:
        return ResultadoOrigenGPS(ORIGEN_GPS_NO_DETERMINADO, motivo="NINGUN_PUNTO_DENTRO_DE_GEOCERCA")
    if len(por_planta) > 1:
        return ResultadoOrigenGPS(
            ORIGEN_GPS_CONFLICTO,
            motivo="RECORRIDO_PASA_CERCA_DE_MAS_DE_UNA_PLANTA(" + ",".join(sorted(por_planta)) + ")",
        )

    (planta_id, puntos_planta), = por_planta.items()
    return ResultadoOrigenGPS(
        ORIGEN_GPS_CONFIRMADO,
        planta_id=planta_id,
        planta_nombre=nombres[planta_id],
        hora_entrada_gps=puntos_planta[0].timestamp,
        hora_salida_gps=puntos_planta[-1].timestamp,
        distancia_minima_km=round(distancias_minimas[planta_id], 3),
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
