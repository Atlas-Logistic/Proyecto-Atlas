# Transcripción técnica — Hotfix Chofer 464089

## Solicitud

Eliminar exclusivamente la regresión que descartaba el Chofer recuperado
geométricamente en la guía 464089, sin modificar OCR, resolvers, Desktop ni el
Sistema Multicampo.

## Ejecución

Se confirmó mediante historial que `67541f0` reemplazó la publicación directa
del valor geométrico por una condición que resultaba falsa cuando el Chofer
lineal era `None`, vacío o `No encontrado`. Se restauró la condición anterior:
publicar únicamente si la recuperación geométrica devuelve un valor.

La prueba específica de 464089 confirma la recuperación. La regresión completa
del módulo aprobó 120/120 casos. La imagen real produce `LEANDRO IOLEDO` y
permanece en `REVISAR`, preservando la política conservadora sin alterar el
resolver.
