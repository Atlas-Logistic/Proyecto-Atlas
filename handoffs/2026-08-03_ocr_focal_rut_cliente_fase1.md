# Handoff — OCR focal estructurado de RUT de Cliente, Fase 1

Fecha: 2026-08-03
Estado: COMPLETADO

## Implementación

La relectura se activa solo cuando existe un RUT de Cliente observado pero su
formato o módulo 11 es inválido. La fila se localiza mediante la relación
geométrica entre `SEÑOR(ES)` y `RUT`; cuatro variantes leen exclusivamente ese
recorte. Se publica evidencia solo si un mismo RUT válido aparece al menos dos
veces y no existe otro candidato válido. Ante conflicto, ausencia o excepción
se conserva el valor original.

No se modificaron Orquestador, Política, resolvers, catálogos, Destinos,
Choferes, Materiales ni reglas de negocio.

## Validación

- Pruebas focales: 149/149; regresión completa: 1138/1138.
- ATLAS-E2E-005: `93.772.000`→`93772000-9`; Cliente confirmado; `OK`.
- ATLAS-E2E-007: `91.410.000`→`91410000-3`; Cliente confirmado; `OK`.
- `REVISAR`: 4/12→2/12.
- Precisión oficial: 48/49 (97,96 %), estable.
- Contradicciones: 0. Falsos positivos: 0.
- Tiempo: 385,779 s total y 32,148 s promedio. Los dos casos focales agregan
  aproximadamente 21–25 s respecto de sus mediciones oficiales anteriores.

## Riesgo y siguiente bloque

El costo por activación focal es material. ATLAS-E2E-002 y 010 permanecen en
revisión por causas distintas. Se recomienda validar la adjudicación
post-resolución de recuperación geométrica para 002 antes de modificar la
regla conservadora.
