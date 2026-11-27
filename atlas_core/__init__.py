"""Componentes centrales del Proyecto Atlas."""

# Condición C1: todo proceso del Motor que escribe en una raíz operacional
# compartida debe poseer el turno local (ver atlas_core.exclusion_local).
# Sólo biblioteca estándar: no altera el costo ni el orden de importación.
from atlas_core.exclusion_local import instalar_guardia as _instalar_guardia

_instalar_guardia()

# Frontera entre empresas: mismo criterio, sin depender de cada CLI.
from atlas_core.aislamiento_empresas import entrar_proceso as _entrar_proceso  # noqa: E402

_entrar_proceso()

# Raíz publicada (Drive) -> raíz de trabajo local (P0.3.1/P0.6): Desktop
# entrega la ruta que muestra; el Motor opera bajo lease en la de trabajo.
try:
    from atlas_core.raiz_publicada import redirigir_proceso as _redirigir_proceso  # noqa: E402

    _redirigir_proceso()
except Exception:  # noqa: BLE001 - sin configuración legible no se redirige nada
    pass
