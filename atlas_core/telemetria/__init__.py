"""Telemetría GPS multiproveedor (Bloque TELEMETRÍA T1).

El núcleo de Atlas debe importar solo `modelos`, `proveedor` y
`servicio` -- nunca un adaptador concreto de `proveedores/` directamente
(eso lo decide quien orquesta el procesamiento, ver
`atlas_core.procesamiento_masivo`).
"""
