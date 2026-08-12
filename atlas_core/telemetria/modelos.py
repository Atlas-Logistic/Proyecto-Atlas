"""Modelos genéricos de telemetría GPS (Bloque TELEMETRÍA T1).

Ningún tipo de este módulo expone la forma JSON de un proveedor concreto
(Onelogis u otro) al resto de Atlas -- el adaptador (`proveedores/*.py`)
es responsable de traducir su respuesta cruda a estos modelos. Atlas es
multiempresa y multiproveedor: hoy el único adaptador es Onelogis, pero
el núcleo (extractor/rutas/gestor_viajes/Desktop) nunca debe importar
nada de `proveedores/` directamente.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum


class EstadoTelemetria(str, Enum):
    """Nunca lanza: cualquier fallo del proveedor de telemetría se expresa
    como uno de estos estados -- la ausencia/fallo de GPS nunca debe
    romper el resto del pipeline (ver Bloque L)."""

    OK = "OK"
    SIN_CREDENCIAL = "SIN_CREDENCIAL"
    NO_AUTORIZADO = "NO_AUTORIZADO"
    VEHICULO_NO_ENCONTRADO = "VEHICULO_NO_ENCONTRADO"
    TRIP_NO_ENCONTRADO = "TRIP_NO_ENCONTRADO"
    SIN_HISTORICO = "SIN_HISTORICO"
    SIN_CONEXION = "SIN_CONEXION"
    LIMITE_CUOTA = "LIMITE_CUOTA"
    RESPUESTA_INVALIDA = "RESPUESTA_INVALIDA"
    ERROR_PROVEEDOR = "ERROR_PROVEEDOR"
    RESULTADO_DESDE_CACHE = "RESULTADO_DESDE_CACHE"


@dataclass(frozen=True)
class VehiculoTelemetria:
    patente: str
    proveedor_id: str = ""
    alias: str = ""
    marca: str = ""
    modelo: str = ""

    def a_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PosicionTelemetria:
    latitud: float
    longitud: float
    timestamp: str = ""
    velocidad: float | None = None
    evento: str = ""

    def a_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ViajeTelemetria:
    proveedor_trip_id: str
    patente: str
    inicio: str = ""
    fin: str = ""
    distancia_km: float | None = None

    def a_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DetencionTelemetria:
    """Bloque TELEMETRÍA T3 -- una permanencia estacionaria real, inferida
    de trips consecutivos cuyos extremos (inicio/fin de breadcrumbs) son
    espacialmente coherentes entre sí -- nunca inventada sin esa
    coherencia. `trip_ids` conserva el/los trip(s) que forman el bloque
    (uno solo si el propio trip ya es estacionario de punta a punta; 2+ si
    se encadenan varios trips/huecos de telemetría en el mismo lugar,
    igual que el hueco real entre "trip A termina en planta" y "trip B
    empieza en planta" del caso real que motivó este bloque)."""

    inicio: str
    fin: str
    duracion_minutos: float
    latitud: float
    longitud: float
    fuente: str = ""
    trip_ids: tuple[str, ...] = ()
    # Bloque ORIGEN O2 -- los puntos REALES que forman este cluster (no
    # todos los breadcrumbs de los trips en `trip_ids`, que pueden traer
    # muchos otros puntos fuera del cluster -- ver bug real encontrado
    # con 464424: reconstruir "todos los puntos de los trips tocados"
    # diluía la proporción dentro/fuera con puntos de tramos de
    # aproximación/salida que nunca fueron parte de esta detención).
    puntos: tuple[PosicionTelemetria, ...] = ()

    def a_dict(self) -> dict[str, object]:
        datos = asdict(self)
        datos.pop("puntos", None)
        return datos


@dataclass(frozen=True)
class EvidenciaOrigenPlanta:
    """Bloque ORIGEN O2 -- evidencia GPS acumulada de UNA planta candidata
    dentro (o cerca) de la ventana documental [hora_entrada, hora_salida]
    de UN viaje/guía específico. La pregunta que responde no es "¿qué
    plantas visitó el vehículo hoy?" sino "¿en qué planta estuvo
    cargando durante ESTA ventana?" -- ver `resolver_planta_origen_gps`."""

    planta_id: str
    planta_nombre: str
    duracion_dentro_min: float
    porcentaje_ventana: float
    porcentaje_puntos: float
    entrada_gps: str
    salida_gps: str
    estadias: tuple[DetencionTelemetria, ...]
    score: float
    motivos: tuple[str, ...]

    def a_dict(self) -> dict[str, object]:
        return {
            "planta_id": self.planta_id,
            "planta_nombre": self.planta_nombre,
            "duracion_dentro_min": self.duracion_dentro_min,
            "porcentaje_ventana": self.porcentaje_ventana,
            "porcentaje_puntos": self.porcentaje_puntos,
            "entrada_gps": self.entrada_gps,
            "salida_gps": self.salida_gps,
            "score": self.score,
            "motivos": list(self.motivos),
        }


@dataclass(frozen=True)
class RecorridoTelemetria:
    viaje: ViajeTelemetria
    breadcrumbs: tuple[PosicionTelemetria, ...] = ()

    def a_dict(self) -> dict[str, object]:
        return {
            "viaje": self.viaje.a_dict(),
            "breadcrumbs": [p.a_dict() for p in self.breadcrumbs],
        }


@dataclass(frozen=True)
class ResultadoVehiculos:
    estado: EstadoTelemetria
    vehiculos: tuple[VehiculoTelemetria, ...] = ()
    motivo: str = ""


@dataclass(frozen=True)
class ResultadoPosicion:
    estado: EstadoTelemetria
    posicion: PosicionTelemetria | None = None
    motivo: str = ""


@dataclass(frozen=True)
class ResultadoViajes:
    estado: EstadoTelemetria
    viajes: tuple[ViajeTelemetria, ...] = ()
    motivo: str = ""
    desde_cache: bool = False


@dataclass(frozen=True)
class ResultadoBreadcrumbs:
    estado: EstadoTelemetria
    puntos: tuple[PosicionTelemetria, ...] = ()
    motivo: str = ""
    desde_cache: bool = False


class EstadoSeleccionRecorrido(str, Enum):
    """Bloque TELEMETRÍA T2 -- nunca lanza ni bloquea la creación del
    viaje Atlas; cualquier resultado de la selección automática de
    trips es uno de estos estados."""

    SELECCIONADO = "SELECCIONADO"
    SIN_HISTORICO_GPS = "SIN_HISTORICO_GPS"
    SIN_ANCLA_TEMPORAL = "SIN_ANCLA_TEMPORAL"
    TELEMETRIA_AMBIGUA = "TELEMETRIA_AMBIGUA"
    PROVEEDOR_NO_DISPONIBLE = "PROVEEDOR_NO_DISPONIBLE"


class EstadoConcordanciaHora(str, Enum):
    """Bloque TELEMETRÍA T2, Fase H -- comparación informativa, nunca
    sobrescribe la hora documental (hora_entrada_aza/hora_salida_aza son
    horas reales registradas en planta, no aproximadas)."""

    CONCORDANTE = "HORA_GPS_CONCORDANTE"
    DIVERGENTE = "HORA_GPS_DIVERGENTE"
    NO_DISPONIBLE = "HORA_GPS_NO_DISPONIBLE"


@dataclass(frozen=True)
class RecorridoOperacionalTelemetria:
    """Uno o más `trips` de telemetría, consecutivos y geográfica/
    temporalmente coherentes, que en conjunto representan UN viaje
    logístico real (un viaje Atlas puede quedar fragmentado en varios
    trips de Onelogis -- ver Bloque TELEMETRÍA T2, caso real 463630).

    Nunca guarda breadcrumbs completos aquí (ver Fase A/N) -- solo el
    primer y último punto, y la distancia GPS total ya sumada. Los
    breadcrumbs completos viven en la caché de telemetría
    (`RepositorioTelemetria`), separados de `viajes.csv`.
    """

    patente: str
    fecha: str
    trip_ids: tuple[str, ...]
    inicio: str = ""
    fin: str = ""
    distancia_gps_total_km: float | None = None
    primer_punto: PosicionTelemetria | None = None
    ultimo_punto: PosicionTelemetria | None = None
    huecos_temporales_min: tuple[float, ...] = ()
    confianza: float = 0.0
    evidencia_seleccion: str = ""

    def a_dict(self) -> dict[str, object]:
        return {
            "patente": self.patente,
            "fecha": self.fecha,
            "trip_ids": list(self.trip_ids),
            "inicio": self.inicio,
            "fin": self.fin,
            "distancia_gps_total_km": self.distancia_gps_total_km,
            "primer_punto": self.primer_punto.a_dict() if self.primer_punto else None,
            "ultimo_punto": self.ultimo_punto.a_dict() if self.ultimo_punto else None,
            "huecos_temporales_min": list(self.huecos_temporales_min),
            "confianza": self.confianza,
            "evidencia_seleccion": self.evidencia_seleccion,
        }


@dataclass(frozen=True)
class ResultadoSeleccionRecorrido:
    estado: EstadoSeleccionRecorrido
    recorrido: RecorridoOperacionalTelemetria | None = None
    motivo: str = ""
