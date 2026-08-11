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

from atlas_core.catalogo_clientes import CatalogoClientes
from atlas_core.catalogo_destinos import CatalogoDestinos, Destino, EstadoBusquedaDestino
from atlas_core.catalogo_plantas import Planta
from atlas_core.rutas.geocerca import RADIO_GEOCERCA_KM_PREDETERMINADO, resolver_planta_por_posicion
from atlas_core.rutas.modelos import Coordenadas, EstadoRuta
from atlas_core.rutas.origen_documental import resolver_origen_documental
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
    "origen_determinado_por", "evidencia_origen",
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
    evidencia_origen: str = ""

    def a_dict(self) -> dict[str, str]:
        return asdict(self)


def validar_destino_resoluble(
    destino: Destino, motivo_exito: str = ""
) -> tuple[Destino | None, str]:
    """Controles de vigencia/coordenadas/rango geográfico comunes a
    cualquier camino de resolución de destino (nombre/alias global -- este
    módulo -- o identificador estructurado -- `destino_estructurado.py`,
    Bloque DESTINOS D2). Centralizado para que ningún camino nuevo pueda
    saltarse estos controles por accidente."""
    if destino.estado_vigencia != "ACTIVO":
        return None, "DESTINO_INACTIVO"
    if destino.latitud is None or destino.longitud is None:
        return None, "DESTINO_SIN_COORDENADAS"
    if not (RANGO_LATITUD_RM[0] <= destino.latitud <= RANGO_LATITUD_RM[1]):
        return None, "DESTINO_COORDENADAS_FUERA_DE_RANGO"
    if not (RANGO_LONGITUD_RM[0] <= destino.longitud <= RANGO_LONGITUD_RM[1]):
        return None, "DESTINO_COORDENADAS_FUERA_DE_RANGO"
    return destino, motivo_exito


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
    return validar_destino_resoluble(resultado.destino)


def _resolver_planta_por_gps(
    *,
    patente: str | None,
    instante_salida: datetime | None,
    proveedor_posicion: ProveedorPosicionVehiculo | None,
    plantas: Iterable[Planta],
    radio_km: float,
) -> tuple[Planta | None, str, str]:
    """Tramo GPS de la jerarquía. Devuelve (planta, motivo_si_falla,
    evidencia). GPS histórico si el proveedor lo entrega; con la
    integración auditada hoy (última posición conocida, ver
    docs/BITACORA_TECNICA_CRONOLOGICA.md bloque RUTAS R1) esto solo aporta
    evidencia útil para procesamiento cercano al instante real de salida."""
    patente_limpia = str(patente or "").strip()
    if not patente_limpia or instante_salida is None or proveedor_posicion is None:
        return None, "SIN_EVIDENCIA_GPS", ""
    resultado_posicion = proveedor_posicion.obtener_posicion(patente_limpia, instante_salida)
    if resultado_posicion.estado != EstadoPosicionVehiculo.POSICION_ENCONTRADA:
        return None, f"GPS_{resultado_posicion.estado.value}", ""
    try:
        timestamp_gps = datetime.fromisoformat(str(resultado_posicion.timestamp_gps))
    except (TypeError, ValueError):
        return None, "POSICION_GPS_SIN_TIMESTAMP_VALIDO", ""
    instante_comparable = instante_salida
    if timestamp_gps.tzinfo is None or instante_comparable.tzinfo is None:
        timestamp_gps = timestamp_gps.replace(tzinfo=None)
        instante_comparable = instante_comparable.replace(tzinfo=None)
    if abs(timestamp_gps - instante_comparable) > VENTANA_MAXIMA_POSICION_GPS:
        return None, "POSICION_GPS_DEMASIADO_ANTIGUA", ""
    resultado_geocerca = resolver_planta_por_posicion(
        resultado_posicion.coordenadas, plantas, radio_km=radio_km
    )
    if not resultado_geocerca.determinada:
        return None, resultado_geocerca.motivo, ""
    planta = next(
        (p for p in plantas if p.planta_id == resultado_geocerca.planta_id), None
    )
    if planta is None:
        return None, "PLANTA_NO_ENCONTRADA_EN_CATALOGO", ""
    evidencia = (
        f"gps_timestamp={resultado_posicion.timestamp_gps};"
        f"distancia_km={resultado_geocerca.distancia_km:.3f}"
    )
    return planta, "", evidencia


def resolver_planta_origen(
    *,
    patente: str | None,
    instante_salida: datetime | None,
    proveedor_posicion: ProveedorPosicionVehiculo | None,
    plantas: Iterable[Planta],
    textos_documento: Iterable[str] | None = None,
    radio_km: float = RADIO_GEOCERCA_KM_PREDETERMINADO,
) -> tuple[Planta | None, str, str, str]:
    """Jerarquía conservadora (Bloque PLANTA-P1):

    1. GPS histórico/geocerca, si hay evidencia (patente + instante +
       proveedor + posición dentro de ventana y geocerca válida).
    2. Evidencia documental (encabezado de la propia guía), como fallback
       -- **solo se consulta si el GPS no determinó nada**, nunca para
       "votar" contra el GPS ni para desempatar: si el GPS resuelve, gana
       el GPS sin excepción (política conservadora ante conflicto).
    3. `None` (`ORIGEN_NO_DETERMINADO`) si ninguno de los dos alcanza.

    Nunca infiere por conveniencia, por cercanía al destino ni por "ruta
    más corta". Devuelve (planta, motivo_si_falla, determinado_por,
    evidencia)."""
    plantas = list(plantas)

    planta_gps, motivo_gps, evidencia_gps = _resolver_planta_por_gps(
        patente=patente, instante_salida=instante_salida,
        proveedor_posicion=proveedor_posicion, plantas=plantas, radio_km=radio_km,
    )
    if planta_gps is not None:
        return planta_gps, "", "ONELOGIS_GPS", evidencia_gps

    if textos_documento is not None:
        planta_doc = resolver_origen_documental(textos_documento, plantas)
        if planta_doc is not None:
            return planta_doc, "", "DOCUMENTO", "ENCABEZADO_GUIA"

    return None, motivo_gps, "", ""


def calcular_ruta_para_viaje(
    *,
    obra_destino_texto: str,
    patente: str | None,
    instante_salida: datetime | None,
    catalogo_destinos: CatalogoDestinos,
    plantas: Iterable[Planta],
    proveedor_posicion: ProveedorPosicionVehiculo | None,
    servicio_rutas: ServicioRutas,
    textos_documento: Iterable[str] | None = None,
    perfil: str = "driving-hgv",
    radio_geocerca_km: float = RADIO_GEOCERCA_KM_PREDETERMINADO,
    cliente_texto: str | None = None,
    catalogo_clientes: CatalogoClientes | None = None,
    rut_cliente_texto: str | None = None,
) -> ResultadoEnriquecimientoRuta:
    """Orquesta destino -> origen (GPS -> documento -> sin determinar) ->
    ORS. Un fallo en cualquier paso deja campos vacíos y un estado/motivo
    explicativo -- nunca lanza, nunca inventa, nunca invalida el viaje que
    lo llama. `textos_documento` (opcional, Bloque PLANTA-P1): texto OCR de
    página completa de la guía, usado solo como fallback documental cuando
    el GPS no determina nada.

    `cliente_texto` + `catalogo_clientes` (opcionales, Bloque DESTINOS D2):
    cuando ambos se entregan, la resolución de destino prioriza
    identificadores estructurados del documento (código destinatario,
    dirección + comuna, alias acotado al cliente) sobre el emparejamiento
    textual global de `obra_destino_texto` -- ver
    `destino_estructurado.resolver_destino_canonico_estructurado`. Sin
    ellos (comportamiento por defecto), la resolución es idéntica a antes
    de este bloque. Un destino resuelto por identidad tampoco se enruta a
    ciegas: se contrasta contra DESPACHAR A del propio documento (el punto
    de entrega real declarado en este viaje, que puede diferir del
    domicilio registrado del cliente) antes de calcular la ruta."""
    plantas = list(plantas)

    if cliente_texto is not None and catalogo_clientes is not None:
        from atlas_core.rutas.destino_estructurado import (
            evaluar_concordancia_despacho,
            extraer_identificadores_destino,
            resolver_destino_canonico_estructurado,
        )

        destino, motivo_destino = resolver_destino_canonico_estructurado(
            cliente_texto=cliente_texto,
            obra_destino_texto=obra_destino_texto,
            textos_documento=textos_documento,
            catalogo_destinos=catalogo_destinos,
            catalogo_clientes=catalogo_clientes,
            rut_cliente_texto=rut_cliente_texto,
        )
        if destino is not None:
            identificadores = extraer_identificadores_destino(textos_documento or [])
            concordante, motivo_concordancia = evaluar_concordancia_despacho(
                destino, identificadores
            )
            if not concordante:
                return ResultadoEnriquecimientoRuta(
                    destino_id=destino.destino_id,
                    destino_nombre=destino.nombre_destino,
                    estado_ruta=EstadoRuta.REQUIERE_REVISION.value,
                    motivo_ruta=motivo_concordancia,
                )
    else:
        destino, motivo_destino = resolver_destino_canonico(obra_destino_texto, catalogo_destinos)

    if destino is None:
        return ResultadoEnriquecimientoRuta(
            estado_ruta=EstadoRuta.DESTINO_NO_VALIDO.value, motivo_ruta=motivo_destino
        )

    planta, motivo_origen, determinado_por, evidencia_origen = resolver_planta_origen(
        patente=patente, instante_salida=instante_salida,
        proveedor_posicion=proveedor_posicion, plantas=plantas,
        textos_documento=textos_documento, radio_km=radio_geocerca_km,
    )
    if planta is None:
        return ResultadoEnriquecimientoRuta(
            destino_id=destino.destino_id, destino_nombre=destino.nombre_destino,
            estado_ruta=EstadoRuta.ORIGEN_NO_DETERMINADO.value, motivo_ruta=motivo_origen,
        )
    if planta.latitud is None or planta.longitud is None:
        # La planta se determinó (GPS o documento) pero su registro de
        # catálogo no tiene coordenadas cargadas -- nunca se lanza una
        # excepción por un dato de catálogo incompleto; se trata igual que
        # "no determinada" para no bloquear el viaje.
        return ResultadoEnriquecimientoRuta(
            destino_id=destino.destino_id, destino_nombre=destino.nombre_destino,
            estado_ruta=EstadoRuta.ORIGEN_NO_DETERMINADO.value,
            motivo_ruta="PLANTA_SIN_COORDENADAS_EN_CATALOGO",
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
        origen_determinado_por=determinado_por,
        evidencia_origen=evidencia_origen,
    )
