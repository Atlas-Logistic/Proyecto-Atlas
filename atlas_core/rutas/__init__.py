"""Infraestructura aislada y reemplazable de rutas de Atlas."""

from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion,
    Coordenadas,
    EstadoRuta,
    RegistroRuta,
    ResultadoGeocodificacion,
    ResultadoRuta,
    ResultadoServicioRutas,
)
from atlas_core.rutas.destino_estructurado import (
    IdentificadoresDestinoDocumento,
    evaluar_concordancia_despacho,
    extraer_identificadores_destino,
    resolver_destino_canonico_estructurado,
)
from atlas_core.rutas.enriquecimiento_viaje import (
    CAMPOS_RESULTADO,
    ResultadoEnriquecimientoRuta,
    calcular_ruta_para_viaje,
    resolver_destino_canonico,
    resolver_planta_origen,
    validar_destino_resoluble,
)
from atlas_core.rutas.geocerca import (
    RADIO_GEOCERCA_KM_PREDETERMINADO,
    ResultadoGeocercaPlanta,
    resolver_planta_por_posicion,
)
from atlas_core.rutas.origen_documental import resolver_origen_documental
from atlas_core.rutas.posicion_vehiculo import (
    EstadoPosicionVehiculo,
    ProveedorPosicionVehiculo,
    ProveedorPosicionVehiculoSimulado,
    ResultadoPosicionVehiculo,
)
from atlas_core.rutas.proveedor import ProveedorRutas, ProveedorRutasSimulado
from atlas_core.rutas.repositorio import RepositorioRutas
from atlas_core.rutas.servicio import ServicioRutas

__all__ = [
    "CandidatoGeocodificacion", "Coordenadas", "EstadoRuta", "RegistroRuta",
    "ResultadoGeocodificacion", "ResultadoRuta", "ResultadoServicioRutas",
    "ProveedorRutas", "ProveedorRutasSimulado", "RepositorioRutas", "ServicioRutas",
    "CAMPOS_RESULTADO", "ResultadoEnriquecimientoRuta", "calcular_ruta_para_viaje",
    "resolver_destino_canonico", "resolver_planta_origen", "validar_destino_resoluble",
    "RADIO_GEOCERCA_KM_PREDETERMINADO", "ResultadoGeocercaPlanta", "resolver_planta_por_posicion",
    "EstadoPosicionVehiculo", "ProveedorPosicionVehiculo",
    "ProveedorPosicionVehiculoSimulado", "ResultadoPosicionVehiculo",
    "resolver_origen_documental",
    "IdentificadoresDestinoDocumento", "evaluar_concordancia_despacho",
    "extraer_identificadores_destino", "resolver_destino_canonico_estructurado",
]
