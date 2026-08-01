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
from atlas_core.rutas.proveedor import ProveedorRutas, ProveedorRutasSimulado
from atlas_core.rutas.cache_multicampo import CacheRutasMemoria
from atlas_core.rutas.contrato_multicampo import (
    EstadoCalculoMulticampo,
    ResultadoRutaMulticampo,
    SolicitudRutaMulticampo,
)
from atlas_core.rutas.servicio_multicampo import ServicioRutasMulticampo
from atlas_core.rutas.repositorio import RepositorioRutas
from atlas_core.rutas.servicio import ServicioRutas

__all__ = [
    "CandidatoGeocodificacion", "Coordenadas", "EstadoRuta", "RegistroRuta",
    "ResultadoGeocodificacion", "ResultadoRuta", "ResultadoServicioRutas",
    "ProveedorRutas", "ProveedorRutasSimulado", "RepositorioRutas", "ServicioRutas",
]
"""API pública del módulo aislado de rutas."""

from atlas_core.rutas.calculo import (
    PERFIL_PREDETERMINADO,
    PLANTAS_OPERACIONALES,
    CalculadorRutas,
    EstadoCalculoRuta,
    ResultadoCalculoRuta,
    SolicitudCalculoRuta,
)
from atlas_core.rutas.modelos import Coordenadas
from atlas_core.rutas.openrouteservice import OpenRouteService
from atlas_core.rutas.proveedor import ProveedorRutas, ProveedorRutasSimulado

__all__ = [
    "PERFIL_PREDETERMINADO",
    "PLANTAS_OPERACIONALES",
    "CalculadorRutas",
    "Coordenadas",
    "EstadoCalculoRuta",
    "OpenRouteService",
    "ProveedorRutas",
    "ProveedorRutasSimulado",
    "ResultadoCalculoRuta",
    "SolicitudCalculoRuta",
    "CacheRutasMemoria",
    "EstadoCalculoMulticampo",
    "ResultadoRutaMulticampo",
    "ServicioRutasMulticampo",
    "SolicitudRutaMulticampo",
]
