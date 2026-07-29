"""API pública del prototipo inteligente, aislada del runtime productivo."""

from atlas_core.inteligencia.correcciones import (
    CorreccionHumana,
    EstadoCorreccion,
    RepositorioCorreccionesMemoria,
)
from atlas_core.inteligencia.contrato_multicampo import (
    AlternativaResolucion,
    CalidadObservacion,
    ContradiccionResolucion,
    Disponibilidad,
    EntidadCanonica,
    EstadoResolucion,
    EvidenciaResolucion,
    GravedadContradiccion,
    ResultadoResolucion,
    ValorObservado,
    congelar_profundo,
    descongelar,
    requiere_revision_por_estado,
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
from atlas_core.inteligencia.normalizacion_geografica import (
    ComparacionDireccion,
    ComponentesDireccion,
    EstadoCoincidenciaDireccion,
    ResultadoNormalizacionGeografica,
    comparar_direccion,
    comunas_equivalentes,
    normalizar_region_chile,
    regiones_equivalentes,
    separar_direccion,
)
from atlas_core.inteligencia.politicas import (
    PESOS_FUENTE,
    POLITICAS,
    PoliticaResolucion,
    obtener_politica,
)
from atlas_core.inteligencia.privacidad import EnvioAutorizado, preparar_envio
from atlas_core.inteligencia.revision_destinos import (
    ConfiguracionRevisionDestinos,
    DecisionHumanaDestino,
    DestinoEntrada,
    EstadoRevisionDestino,
    RegistroRevisionDestino,
    ResultadoLoteRevision,
    cargar_destinos,
    ejecutar_archivo,
    guardar_bandeja,
    procesar_destinos,
)
from atlas_core.inteligencia.proveedores import (
    ProveedorExternoSimulado,
    ProveedorModeloSimulado,
    RespuestaProveedor,
)
from atlas_core.inteligencia.politica_confianza_chofer import (
    POLITICA_CONFIANZA_CHOFER_V1_1,
    PoliticaConfianzaChofer,
    ViaDecisionChofer,
)
from atlas_core.inteligencia.redireccion_identidad import (
    EventoRedireccionIdentidad,
    HistorialRedireccionesIdentidad,
    TipoRedireccionIdentidad,
)
from atlas_core.inteligencia.resolucion_chofer import (
    HallazgoCatalogoChoferes,
    auditar_catalogo_choferes,
    normalizar_nombre_identidad,
    resolver_chofer_rut,
)
from atlas_core.inteligencia.snapshot_catalogo_choferes import (
    InstantaneaCatalogoChoferes,
    crear_snapshot_catalogo_choferes,
)
from atlas_core.inteligencia.verificacion_destinos import (
    CacheVerificacionesMemoria,
    EstadoVerificacionDestino,
    ResultadoVerificacionDestino,
    SolicitudVerificacionDestino,
    VerificadorDestinosOpenRouteService,
    convertir_a_evidencia,
    resolver_destino_con_verificacion,
)

__all__ = [
    "Contradiccion", "CorreccionHumana", "EnvioAutorizado", "EstadoCorreccion",
    "EstadoPropuesta", "Evidencia", "MotorResolucion", "NivelConfianza",
    "PESOS_FUENTE", "POLITICAS", "PoliticaResolucion", "Propuesta",
    "ProveedorExternoSimulado", "ProveedorModeloSimulado",
    "RepositorioCorreccionesMemoria", "RespuestaProveedor", "TipoFuente",
    "CacheVerificacionesMemoria", "EstadoVerificacionDestino",
    "ResultadoVerificacionDestino", "SolicitudVerificacionDestino",
    "VerificadorDestinosOpenRouteService", "convertir_a_evidencia",
    "resolver_destino_con_verificacion", "normalizar", "obtener_politica",
    "preparar_envio", "ComparacionDireccion", "ComponentesDireccion",
    "EstadoCoincidenciaDireccion", "ResultadoNormalizacionGeografica",
    "comparar_direccion", "comunas_equivalentes", "normalizar_region_chile",
    "regiones_equivalentes", "separar_direccion",
    "ConfiguracionRevisionDestinos", "DecisionHumanaDestino", "DestinoEntrada",
    "EstadoRevisionDestino", "RegistroRevisionDestino", "ResultadoLoteRevision",
    "cargar_destinos", "ejecutar_archivo", "guardar_bandeja",
    "procesar_destinos",
    "AlternativaResolucion", "CalidadObservacion", "ContradiccionResolucion",
    "Disponibilidad", "EntidadCanonica", "EstadoResolucion",
    "EvidenciaResolucion", "GravedadContradiccion", "ResultadoResolucion",
    "ValorObservado", "HallazgoCatalogoChoferes",
    "auditar_catalogo_choferes", "normalizar_nombre_identidad",
    "resolver_chofer_rut",
    "congelar_profundo", "descongelar", "requiere_revision_por_estado",
    "POLITICA_CONFIANZA_CHOFER_V1_1", "PoliticaConfianzaChofer",
    "ViaDecisionChofer", "InstantaneaCatalogoChoferes",
    "crear_snapshot_catalogo_choferes", "EventoRedireccionIdentidad",
    "HistorialRedireccionesIdentidad", "TipoRedireccionIdentidad",
]
