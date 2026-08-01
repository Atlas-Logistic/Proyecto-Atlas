# Trabajos activos Atlas

## Bloque 1C.1 + 1D.1 — Motor multicampo

- Estado: COMPLETADO
- Rama de trabajo: fix-motor-multicampo-1c1-1d1
- Rama de integración: main
- Fecha de cierre: 2026-07-31

### Resumen técnico
- La revisión independiente confirmó que la resolución de vehículo ya no confirma silenciosamente una patente genérica incompatible.
- La revisión independiente confirmó que la resolución de destino ya no confirma una compatibilidad cliente-destino incorrecta.
- El comportamiento correcto queda en REQUIERE_REVISION con contradicción cuando la evidencia es incompatible.

### Evidencia de cierre
- 4 pruebas adversariales aprobadas.
- 79 pruebas de regresión aprobadas.
- Sin regresiones funcionales detectadas en la superficie multicampo revisada.

### Handoff
- Cierre técnico del bloque ejecutado sin modificar datos reales ni introducir nuevas funcionalidades.
- El bloque queda listo para integración en la rama oficial.

## Bloque Lector Focal Adaptativo – Fase 1 (Relectura de campos numéricos)

- Estado: COMPLETADO
- Rama de trabajo: main
- Rama de integración: main
- Fecha de cierre: 2026-07-31

### Resumen técnico
- Se implementó la relectura focal controlada sobre recortes de transporte.
- La segunda lectura se evalúa antes de incorporarse como evidencia de consenso.
- Se descartan lecturas idénticas o degradadas, y solo se conservan conflictos relevantes o evidencia útil.
- No se modificó la política de decisión del consenso; se preserva la compatibilidad con extractor.py y procesamiento_masivo.py.

### Evidencia de cierre
- 244 pruebas aprobadas.
- 1 warning no bloqueante.
- Exit code 0.
- Revisión adversarial independiente aprobada.

### Seguimientos no bloqueantes
- Evolucionar el evaluador de evidencia hacia comparaciones semánticas además de literales.
- Validar el lector focal adaptativo mediante pruebas E2E con imágenes reales.
- Medir el impacto en rendimiento sobre procesamiento masivo.

### Handoff
- Cierre técnico del bloque ejecutado sin modificar la política de consenso ni introducir cambios en el contrato del flujo.
- El bloque queda listo para integración en la rama oficial.
