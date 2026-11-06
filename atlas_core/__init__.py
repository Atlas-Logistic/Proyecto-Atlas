"""Componentes centrales del Proyecto Atlas."""

# Condición C1: todo proceso del Motor que escribe en una raíz operacional
# compartida debe poseer el turno local (ver atlas_core.exclusion_local).
# Sólo biblioteca estándar: no altera el costo ni el orden de importación.
from atlas_core.exclusion_local import instalar_guardia as _instalar_guardia

_instalar_guardia()
