"""Enriquecimiento de un viaje con ruta ORS (Bloque RUTAS R1).

Conecta: obra_destino (OCR ya homologado) -> destino canónico
(destinos_maestros.json) -> planta de origen (geocerca sobre posición GPS,
si hay evidencia) -> ServicioRutas (ORS, perfil driving-hgv, con caché de
RepositorioRutas) -> campos listos para adjuntar al viaje/reporte.

Nunca inventa un destino a partir de texto OCR no homologado, nunca elige
planta por "ruta más corta", y un fallo de ruta nunca invalida el viaje:
es enriquecimiento logístico opcional, no un requisito del viaje.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Iterable

from atlas_core.catalogo_destinos import CatalogoDestinos, Destino, EstadoBusquedaDestino
from atlas_core.catalogo_plantas import Planta
from atlas_core.rutas.geocerca import RADIO_GEOCERCA_KM_PREDETERMINADO, resolver_planta_por_posicion
from atlas_core.rutas.modelos import Coordenadas, EstadoRuta
from atlas_core.rutas.posicion_vehiculo import (
    EstadoPosicionVehiculo,
    ProveedorPosicionVehiculo,
)
from atlas_core.rutas.servicio import ServicioRutas

# Rango geográfico plausible para las operaciones actuales de Atlas (Región
# Metropolitana). Un destino con coordenadas fuera de este rango se trata
# como inválido en vez de consultar ORS -- cubre, de forma general (no
# hardcodeada por nombre de comuna), los registros "SAN MIGUEL" con
# geocodificación errónea detectados en RUTAS-EVAL R1 (lat=-30.81, zona de
# Ovalle/Coquimbo, a ~370 km de Santiago).
RANGO_LATITUD_RM = (-34.5, -32.5)
RANGO_LONGITUD_RM = (-71.5, -70.0)

# Margen conservador entre el timestamp de la posición GPS y el instante de
# salida del viaje. No existe todavía histórico real contra el cual
# calibrarlo (ver posicion_vehiculo.py) -- valor de partida explícito, no
# ajustado con datos reales.
VENTANA_MAXIMA_POSICION_GPS = timedelta(hours=2)

CAMPOS_RESULTADO = (
    "planta_origen_id", "planta_origen_nombre",
    "destino_id", "destino_nombre",
    "distancia_km", "duracion_min",
    "proveedor_ruta", "estado_ruta", "motivo_ruta",
    "origen_determinado_por",
)


@dataclass(frozen=True)
class ResultadoEnriquecimientoRuta:
    planta_origen_id: str = ""
    planta_origen_nombre: str = ""
    destino_id: str = ""
    destino_nombre: str = ""
    distancia_km: str = ""
    duracion_min: str = ""
    proveedor_ruta: str = ""
    estado_ruta: str = ""
    motivo_ruta: str = ""
    origen_determinado_por: str = ""

    def a_dict(self) -> dict[str, str]:
        return asdict(self)


def resolver_destino_canonico(
    obra_destino_texto: str, catalogo_destinos: CatalogoDestinos
) -> tuple[Destino | None, str]:
    """Homologa obra_destino (texto OCR ya extraído) contra el catálogo
    canónico. Nunca fabrica un destino: exige coincidencia exacta (nombre o
    alias, vía CatalogoDestinos.buscar -- mismo mecanismo ya usado para
    gestionar destinos), vigente, con coordenadas válidas y dentro del
    rango geográfico plausible."""
    texto = str(obra_destino_texto or "").strip()
    if not texto or texto.casefold() == "no encontrado":
        return None, "OBRA_DESTINO_NO_INFORMADA"
    resultado = catalogo_destinos.buscar(texto)
    if resultado.estado == EstadoBusquedaDestino.AMBIGUA:
        return None, "DESTINO_AMBIGUO"
    if resultado.estado == EstadoBusquedaDestino.SIN_COINCIDENCIA:
        return None, "DESTINO_NO_HOMOLOGADO"
    destino = resultado.destino
    if destino.estado_vigencia != "ACTIVO":
        return None, "DESTINO_INACTIVO"
    if destino.latitud is None or destino.longitud is None:
        return None, "DESTINO_SIN_COORDENADAS"
    if not (RANGO_LATITUD_RM[0] <= destino.latitud <= RANGO_LATITUD_RM[1]):
        return None, "DESTINO_COORDENADAS_FUERA_DE_RANGO"
    if not (RANGO_LONGITUD_RM[0] <= destino.longitud <= RANGO_LONGITUD_RM[1]):
        return None, "DESTINO_COORDENADAS_FUERA_DE_RANGO"
    return destino, ""


def resolver_planta_origen(
    *,
    patente: str | None,
    instante_salida: datetime | None,
    proveedor_posicion: ProveedorPosicionVehiculo | None,
    plantas: Iterable[Planta],
    radio_km: float = RADIO_GEOCERCA_KM_PREDETERMINADO,
) -> tuple[Planta | None, str]:
    """Jerarquía única soportada hoy: evidencia GPS/geocerca. Sin patente,
    sin instante o sin proveedor de posición, se abstiene explícitamente
    -- nunca infiere la planta por conveniencia ni por ruta más corta."""
    patente_limpia = str(patente or "").strip()
    if not patente_limpia or instante_salida is None or proveedor_posicion is None:
        return None, "SIN_EVIDENCIA_GPS"
    resultado_posicion = proveedor_posicion.obtener_posicion(patente_limpia, instante_salida)
    if resultado_posicion.estado != EstadoPosicionVehiculo.POSICION_ENCONTRADA:
        return None, f"GPS_{resultado_posicion.estado.value}"
    try:
        timestamp_gps = datetime.fromisoformat(str(resultado_posicion.timestamp_gps))
    except (TypeError, ValueError):
        return None, "POSICION_GPS_SIN_TIMESTAMP_VALIDO"
    instante_comparable = instante_salida
    if timestamp_gps.tzinfo is None or instante_comparable.tzinfo is None:
        timestamp_gps = timestamp_gps.replace(tzinfo=None)
        instante_comparable = instante_comparable.replace(tzinfo=None)
    if abs(timestamp_gps - instante_comparable) > VENTANA_MAXIMA_POSICION_GPS:
        return None, "POSICION_GPS_DEMASIADO_ANTIGUA"
    resultado_geocerca = resolver_planta_por_posicion(
        resultado_posicion.coordenadas, plantas, radio_km=radio_km
    )
    if not resultado_geocerca.determinada:
        return None, resultado_geocerca.motivo
    planta = next(
        (p for p in plantas if p.planta_id == resultado_geocerca.planta_id), None
    )
    if planta is None:
        return None, "PLANTA_NO_ENCONTRADA_EN_CATALOGO"
    return planta, ""


def calcular_ruta_para_viaje(
    *,
    obra_destino_texto: str,
    patente: str | None,
    instante_salida: datetime | None,
    catalogo_destinos: CatalogoDestinos,
    plantas: Iterable[Planta],
    proveedor_posicion: ProveedorPosicionVehiculo | None,
    servicio_rutas: ServicioRutas,
    perfil: str = "driving-hgv",
    radio_geocerca_km: float = RADIO_GEOCERCA_KM_PREDETERMINADO,
) -> ResultadoEnriquecimientoRuta:
    """Orquesta destino -> origen -> ORS. Un fallo en cualquier paso deja
    campos vacíos y un estado/motivo explicativo -- nunca lanza, nunca
    inventa, nunca invalida el viaje que lo llama."""
    plantas = list(plantas)

    destino, motivo_destino = resolver_destino_canonico(obra_destino_texto, catalogo_destinos)
    if destino is None:
        return ResultadoEnriquecimientoRuta(
            estado_ruta=EstadoRuta.DESTINO_NO_VALIDO.value, motivo_ruta=motivo_destino
        )

    planta, motivo_origen = resolver_planta_origen(
        patente=patente, instante_salida=instante_salida,
        proveedor_posicion=proveedor_posicion, plantas=plantas,
        radio_km=radio_geocerca_km,
    )
    if planta is None:
        return ResultadoEnriquecimientoRuta(
            destino_id=destino.destino_id, destino_nombre=destino.nombre_destino,
            estado_ruta=EstadoRuta.ORIGEN_NO_DETERMINADO.value, motivo_ruta=motivo_origen,
        )

    resultado_servicio = servicio_rutas.confirmar_y_calcular(
        planta, destino, perfil,
        Coordenadas(planta.longitud, planta.latitud),
        Coordenadas(destino.longitud, destino.latitud),
        confirmacion_explicita=True,
    )
    ruta = resultado_servicio.ruta
    return ResultadoEnriquecimientoRuta(
        planta_origen_id=planta.planta_id,
        planta_origen_nombre=planta.nombre,
        destino_id=destino.destino_id,
        destino_nombre=destino.nombre_destino,
        distancia_km=str(ruta.distancia_km) if ruta else "",
        duracion_min=str(ruta.duracion_estimada_min) if ruta else "",
        proveedor_ruta=servicio_rutas.proveedor.nombre,
        estado_ruta=resultado_servicio.estado.value,
        motivo_ruta=resultado_servicio.motivo,
        origen_determinado_por="ONELOGIS_GPS",
    )
