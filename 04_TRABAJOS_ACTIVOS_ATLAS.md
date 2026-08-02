# Trabajos activos Atlas

> Nota (Claude, 2026-08-01): este archivo es una copia local, dentro del
> repositorio, del archivo de coordinación entre herramientas. La copia
> canónica y compartida vive en Google Drive:
> `Contexto compartido Atlas/04_TRABAJOS_ACTIVOS_ATLAS.md`, junto con
> `01_BITACORA_CRONOLOGICA_ATLAS.md` y `02_REGLAS_DE_COORDINACION.md`.
> Mantener ambas sincronizadas manualmente hasta que se decida si esta
> copia local debe eliminarse o formalizarse.

## Bloque 1C.1 + 1D.1 — Motor multicampo

- Estado: COMPLETADO E INTEGRADO — ya en `main` (commit de merge `8f40e93`)
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
- Revisión de seguridad independiente adicional (Claude, 2026-08-01): 1079/1079 pruebas de la suite completa, sin marcadores de conflicto ni problemas de compilación. Ver `handoffs/2026-08-01_claude_revision_seguridad_merge_main_lector_mvp.md` en Drive.

### Handoff
- Cierre técnico del bloque ejecutado sin modificar datos reales ni introducir nuevas funcionalidades.
- **Ya integrado en `main`** — no queda pendiente de integración.

## Bloque Lector Focal Adaptativo – Fase 1 (Relectura de campos numéricos)

- Estado: COMPLETADO E INTEGRADO — ya en `main` (commit `824c4ff`)
- Rama de trabajo: main (trabajado directo sobre main, sin rama aislada)
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
- Revisión de seguridad independiente adicional (Claude, 2026-08-01): sin hallazgos en esta revisión más liviana; observación operativa (no bug): la relectura duplica las llamadas de OCR sobre el recorte de transporte — medir impacto real en procesamiento masivo, ya anotado abajo como seguimiento.

### Seguimientos no bloqueantes
- Evolucionar el evaluador de evidencia hacia comparaciones semánticas además de literales.
- Validar el lector focal adaptativo mediante pruebas E2E con imágenes reales.
- Medir el impacto en rendimiento sobre procesamiento masivo.

### Handoff
- Cierre técnico del bloque ejecutado sin modificar la política de consenso ni introducir cambios en el contrato del flujo.
- **Ya integrado en `main`** — no queda pendiente de integración.

## Resolución Inteligente de Choferes – Fase 1

- Estado: **EN CURSO — código todavía SIN COMMITEAR, con un defecto conocido pendiente de corregir antes de cerrar el bloque**
- Rama de trabajo: main (trabajado directo sobre main, sin rama aislada; cambios sin commitear en `atlas_core/procesamiento_masivo.py` y `tests/test_procesamiento_masivo.py`)
- Rama de integración: main (pendiente el commit)
- Fecha de cierre: **todavía no cerrado** (la fecha `2026-08-01` que decía antes esta sección era incorrecta — el trabajo se hizo el 2026-07-31 por la noche, hora de Chile, y sigue sin commitear)

### Resumen técnico
- Se conectó `resolver_chofer_rut` (Motor Multicampo) al flujo principal de `procesamiento_masivo.py`.
- La política pretende ser conservadora: confirma solo cuando la evidencia es fuerte, preserva el valor OCR cuando la evidencia es débil o contradictoria y marca revisión cuando no alcanza el umbral.

### ⚠️ Defecto real encontrado en revisión de seguridad (Claude, 2026-08-01) — corregir antes de cerrar
La lógica de `requiere_revision` fuerza revisión manual **incluso cuando el chofer se confirma correctamente** (`EstadoResolucion.CONFIRMADO`), si el nombre canónico coincide textualmente con el OCR — que es el caso común de un OCR limpio. Reproducido con `resolver_chofer_rut` real (no simulado): un caso `CONFIRMADO` con nombre y RUT exactos queda igual marcado para revisión que uno donde el chofer no se pudo identificar. Esto contradice el objetivo declarado ("ya no depende del fuzzy matcher... confirma solo cuando la evidencia es fuerte"). Detalle completo y reproducción exacta:
`handoffs/2026-08-01_claude_revision_seguridad_merge_main_lector_mvp.md` (Drive, carpeta "Contexto compartido Atlas").

### Evidencia de cierre (parcial — pendiente corregir el defecto de arriba antes de considerar esto cerrado)
- 130 pruebas aprobadas (no cubren el caso del defecto encontrado).
- 1 warning no bloqueante.
- Exit code 0.

### Seguimientos no bloqueantes
- Añadir contexto adicional de cliente, destino y vehículo para mejorar la resolución cuando el RUT es débil o ausente.
- Registrar historial de evidencia de resolución para auditoría y aprendizaje.
- Reducir los casos que terminan en REVISAR sin incrementar falsos positivos.

### Handoff
- **No commitear como "cerrado" hasta corregir el defecto de `requiere_revision` descrito arriba.**
- Una vez corregido, commitear los cambios de `procesamiento_masivo.py`/`test_procesamiento_masivo.py` antes de considerar el bloque integrado.

## Resolución Inteligente de Clientes – Fase 1

- Estado: COMPLETADO E INTEGRADO — listo para publicación en `main`
- Rama de trabajo: main
- Rama de integración: main
- Fecha de cierre: 2026-08-01

### Resumen técnico
- `resolucion_cliente.py` quedó como único punto de decisión para identidad de cliente dentro del flujo principal.
- `procesamiento_masivo.py` ahora propaga `REVISAR` para cualquier estado no confirmado del contrato multicampo.
- `enriquecer_datos_con_catalogos` dejó definitivamente de resolver identidad de cliente y quedó limitado a campos auxiliares.
- Se eliminaron restos de la ruta migrada y se amplió la cobertura de integración para contradicción, ambigüedad, propuesta y no resuelto.

### Evidencia de cierre
- 164 pruebas aprobadas.
- 1 warning no bloqueante.
- Exit code 0.
- Segunda auditoría independiente aprobada: el bloque puede pasar a cierre técnico, integración y publicación.

### Seguimientos no bloqueantes
- `extractor.py` mantiene fallbacks históricos por número de guía que precargan cliente y RUT. No constituyen una segunda ruta de decisión, pero deberán revisarse en futuras fases de unificación.

### Handoff
- No abrir todavía el bloque de Destinos hasta confirmar que Clientes quedó completamente integrado y publicado en `origin/main`.
