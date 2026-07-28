"""API pública del prototipo inteligente, aislada del runtime productivo."""

from atlas_core.inteligencia.correcciones import (
    CorreccionHumana,
    EstadoCorreccion,
    RepositorioCorreccionesMemoria,
)
from atlas_core.inteligencia.modelos import (
    Contradiccion,
    EstadoPropuesta,
    Evidencia,
    NivelConfianza,
    Propuesta,
    TipoFuente,
)
from atlas_core.inteligencia.motor import MotorResolucion, normalizar
from atlas_core.inteligencia.politicas import (
    PESOS_FUENTE,
    POLITICAS,
    PoliticaResolucion,
    obtener_politica,
)
from atlas_core.inteligencia.privacidad import EnvioAutorizado, preparar_envio
from atlas_core.inteligencia.proveedores import (
    ProveedorExternoSimulado,
    ProveedorModeloSimulado,
    RespuestaProveedor,
)

__all__ = [
    "Contradiccion", "CorreccionHumana", "EnvioAutorizado", "EstadoCorreccion",
    "EstadoPropuesta", "Evidencia", "MotorResolucion", "NivelConfianza",
    "PESOS_FUENTE", "POLITICAS", "PoliticaResolucion", "Propuesta",
    "ProveedorExternoSimulado", "ProveedorModeloSimulado",
    "RepositorioCorreccionesMemoria", "RespuestaProveedor", "TipoFuente",
    "normalizar", "obtener_politica", "preparar_envio",
]
