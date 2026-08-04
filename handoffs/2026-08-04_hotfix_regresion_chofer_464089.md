# Handoff — Hotfix regresión Chofer 464089

## Estado

Hotfix completado y validado. La condición introducida en `67541f0` impedía
publicar cualquier recuperación geométrica cuando el Chofer lineal estaba
ausente. Se restauró la publicación al existir un valor geométrico válido.

## Resultado

- La guía real 464089 recupera `LEANDRO IOLEDO` desde sus bloques OCR.
- El resultado permanece en `REVISAR`; no se infiere ni canoniza el apellido.
- 120/120 pruebas de `procesamiento_masivo` aprobadas.
- Sin cambios fuera de la condición y sus pruebas de regresión.

El sprint de kilómetros permanece pausado y no forma parte de este hotfix.
