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
from atlas_core.inteligencia.politica_confianza_cliente import (
    POLITICA_CONFIANZA_CLIENTE_V1,
    PoliticaConfianzaCliente,
    ViaDecisionCliente,
)
from atlas_core.inteligencia.politica_confianza_destino import (
    POLITICA_CONFIANZA_DESTINO_V1,
    PoliticaConfianzaDestino,
    ViaDecisionDestino,
)
from atlas_core.inteligencia.politica_confianza_documento import (
    POLITICA_CONFIANZA_DOCUMENTO_V1,
    PoliticaConfianzaDocumento,
)
from atlas_core.inteligencia.politica_confianza_vehiculo import (
    POLITICA_CONFIANZA_VEHICULO_V1,
    PoliticaConfianzaVehiculo,
    ViaDecisionVehiculo,
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
from atlas_core.inteligencia.resolucion_cliente import (
    HallazgoCatalogoClientes,
    ResultadoResolucionCliente,
    auditar_catalogo_clientes,
    normalizar_nombre_cliente_multicampo,
    resolver_cliente_rut,
)
from atlas_core.inteligencia.resolucion_destino import (
    HallazgoCatalogoDestinos,
    ResultadoResolucionDestino,
    auditar_catalogo_destinos,
    resolver_destino_ubicacion,
)
from atlas_core.inteligencia.resolucion_documento import (
    CandidatoDocumento,
    ResultadoResolucionDocumento,
    resolver_guia_transporte_fecha,
)
from atlas_core.inteligencia.resolucion_vehiculo import (
    HallazgoCatalogoVehiculos,
    ResultadoResolucionVehiculo,
    auditar_catalogo_vehiculos,
    patente_chilena_valida,
    resolver_vehiculo_patente,
)
from atlas_core.inteligencia.politica_confianza_material import (
    POLITICA_CONFIANZA_MATERIAL_V1, PoliticaConfianzaMaterial,
    ViaDecisionMaterial,
)
from atlas_core.inteligencia.resolucion_material import (
    CandidatoMaterial, ResultadoResolucionMaterial, normalizar_material,
    resolver_material_tipo_carga,
)
from atlas_core.inteligencia.snapshot_catalogo_materiales import (
    InstantaneaCatalogoMateriales, crear_snapshot_catalogo_materiales,
)
from atlas_core.inteligencia.snapshot_catalogo_clientes import (
    InstantaneaCatalogoClientes,
    crear_snapshot_catalogo_clientes,
)
from atlas_core.inteligencia.snapshot_catalogo_destinos import (
    InstantaneaCatalogoDestinos,
    crear_snapshot_catalogo_destinos,
    normalizar_texto_destino,
    region_canonica,
)
from atlas_core.inteligencia.snapshot_catalogo_choferes import (
    InstantaneaCatalogoChoferes,
    crear_snapshot_catalogo_choferes,
)
from atlas_core.inteligencia.snapshot_catalogo_vehiculos import (
    InstantaneaCatalogoVehiculos,
    crear_snapshot_catalogo_vehiculos,
    normalizar_patente,
    normalizar_rol_vehiculo,
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
    "POLITICA_CONFIANZA_CLIENTE_V1", "PoliticaConfianzaCliente",
    "ViaDecisionCliente", "HallazgoCatalogoClientes",
    "ResultadoResolucionCliente",
    "auditar_catalogo_clientes", "normalizar_nombre_cliente_multicampo",
    "resolver_cliente_rut", "InstantaneaCatalogoClientes",
    "crear_snapshot_catalogo_clientes",
    "POLITICA_CONFIANZA_VEHICULO_V1", "PoliticaConfianzaVehiculo",
    "ViaDecisionVehiculo", "HallazgoCatalogoVehiculos",
    "ResultadoResolucionVehiculo", "auditar_catalogo_vehiculos",
    "patente_chilena_valida", "resolver_vehiculo_patente",
    "InstantaneaCatalogoVehiculos", "crear_snapshot_catalogo_vehiculos",
    "normalizar_patente", "normalizar_rol_vehiculo",
    "POLITICA_CONFIANZA_DESTINO_V1", "PoliticaConfianzaDestino",
    "ViaDecisionDestino", "HallazgoCatalogoDestinos",
    "ResultadoResolucionDestino", "auditar_catalogo_destinos",
    "resolver_destino_ubicacion", "InstantaneaCatalogoDestinos",
    "crear_snapshot_catalogo_destinos", "normalizar_texto_destino",
    "region_canonica",
    "POLITICA_CONFIANZA_DOCUMENTO_V1", "PoliticaConfianzaDocumento",
    "CandidatoDocumento", "ResultadoResolucionDocumento",
    "resolver_guia_transporte_fecha",
    "POLITICA_CONFIANZA_MATERIAL_V1", "PoliticaConfianzaMaterial",
    "ViaDecisionMaterial", "CandidatoMaterial", "ResultadoResolucionMaterial",
    "normalizar_material", "resolver_material_tipo_carga",
    "InstantaneaCatalogoMateriales", "crear_snapshot_catalogo_materiales",
]
