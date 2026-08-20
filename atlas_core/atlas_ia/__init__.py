"""Atlas IA -- capa de razonamiento aditiva sobre el Motor determinista de
Atlas (ver docs/BITACORA_TECNICA_CRONOLOGICA.md, bloque ATLAS IA A1).

Bloque A1 (este): contratos + shadow harness aislado para el vertical
vehículos/patentes. Sin proveedor real conectado, sin escritura a la
operación real, sin autonomía -- Atlas IA todavía no puede autorresolver,
proponer en `decisiones_pendientes.json` ni tocar ningún catálogo. Ver
`atlas_core.decisiones_pendientes.evaluar_evidencia_patente` para el
Motor determinista que esta capa consume -- nunca reemplaza."""

from atlas_core.atlas_ia.adaptadores import (
    contexto_desde_resultado_evidencia,
    contexto_desde_resultado_evaluar_evidencia_patente,
    evidencias_ia_desde_candidatos_vehiculo,
)
from atlas_core.atlas_ia.contratos import (
    ContextoRazonamiento,
    EvidenciaIA,
    HipotesisIA,
    ResultadoShadow,
    ResultadoValidacionHipotesis,
    calcular_hipotesis_id,
)
from atlas_core.atlas_ia.politica_prompt import POLITICA_PROMPT_SISTEMA, POLITICA_PROMPT_VERSION
from atlas_core.atlas_ia.proveedor import ProveedorModeloIA, ProveedorModeloIASimulado, RespuestaSimulada
from atlas_core.atlas_ia.proveedor_anthropic import (
    CredencialProveedorIAAusente,
    ErrorProveedorModeloIA,
    ProveedorIANoDisponible,
    ProveedorModeloIAAnthropic,
)
from atlas_core.atlas_ia.shadow import ejecutar_caso_shadow, ejecutar_shadow
from atlas_core.atlas_ia.orquestador import OrquestadorAtlasIA, ResultadoOrquestacion
from atlas_core.atlas_ia.validadores import validar_hipotesis_multicampo, validar_hipotesis_vehiculo

__all__ = [
    "ContextoRazonamiento", "EvidenciaIA", "HipotesisIA", "ResultadoShadow",
    "ResultadoValidacionHipotesis", "calcular_hipotesis_id",
    "ProveedorModeloIA", "ProveedorModeloIASimulado", "RespuestaSimulada",
    "ProveedorModeloIAAnthropic", "ErrorProveedorModeloIA",
    "CredencialProveedorIAAusente", "ProveedorIANoDisponible",
    "POLITICA_PROMPT_SISTEMA", "POLITICA_PROMPT_VERSION",
    "contexto_desde_resultado_evaluar_evidencia_patente",
    "contexto_desde_resultado_evidencia",
    "evidencias_ia_desde_candidatos_vehiculo",
    "validar_hipotesis_vehiculo", "validar_hipotesis_multicampo",
    "OrquestadorAtlasIA", "ResultadoOrquestacion",
    "ejecutar_caso_shadow", "ejecutar_shadow",
]
