"""Componentes centrales del Proyecto Atlas."""

# Condición C1: todo proceso del Motor que escribe en una raíz operacional
# compartida debe poseer el turno local (ver atlas_core.exclusion_local).
# Sólo biblioteca estándar: no altera el costo ni el orden de importación.
from atlas_core.exclusion_local import instalar_guardia as _instalar_guardia

_instalar_guardia()

# Frontera entre empresas: mismo criterio, sin depender de cada CLI.
from atlas_core.aislamiento_empresas import entrar_proceso as _entrar_proceso  # noqa: E402

_contexto_empresa = _entrar_proceso()

# Identidad y permisos: inactiva salvo que la empresa exija identidad
# (catalogos_privados/desktop_usuarios.json, exigir_identidad: true).
from atlas_core.identidad import entrar_proceso as _entrar_identidad  # noqa: E402

_entrar_identidad(_contexto_empresa)
