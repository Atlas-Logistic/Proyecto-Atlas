# Bitácora Ejecutiva

## Propósito
Esta bitácora es la vista ejecutiva de coordinación para ChatGPT, GitHub Copilot y Claude Code. Su función es resumir, de forma liviana y auditable, el estado de cada bloque cerrado o activo sin duplicar la documentación técnica del proyecto.

## Convención de uso
- Se actualiza al cierre de cada bloque.
- Mantiene un resumen ejecutivo por bloque.
- Cuando el detalle técnico es extenso, se referencia la documentación oficial de Atlas en lugar de repetirla.

## Resumen ejecutivo por bloque

| Bloque | Estado | Fecha | Commit | Pruebas ejecutadas | Resultado de auditoría | Decisiones de arquitectura | Riesgos abiertos | Siguiente bloque |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Bloque 1C.1 + 1D.1 — Motor multicampo | COMPLETADO | 2026-07-31 | 8f40e9360682178c3095d8337ee0366f440c458a | 4 pruebas adversariales aprobadas; 79 pruebas de regresión aprobadas | Revisión independiente aprobada; sin regresiones funcionales detectadas en la superficie multicampo revisada | Se reforzó la política conservadora de resolución multicampo: no confirmar silenciosamente incompatibilidades; usar REQUIERE_REVISION cuando la evidencia contradice la hipótesis | Riesgo de falsos positivos en contexto débil; necesidad de más contexto operacional para reducir revisiones | Lector focal adaptativo |
| Bloque Lector Focal Adaptativo – Fase 1 | COMPLETADO | 2026-07-31 | 824c4ff39d816696669491c205cc6d48c16d5f8e | 244 pruebas aprobadas; 1 warning no bloqueante; exit code 0 | Revisión adversarial independiente aprobada | Se adoptó una relectura focal controlada sobre recortes de transporte; la segunda lectura solo se incorpora si aporta evidencia útil y no degrada el resultado | Riesgo de sobrecorrección por ruido OCR; necesidad de validar en imágenes reales y medir rendimiento | Resolución inteligente de choferes |
| Resolución Inteligente de Choferes – Fase 1 | COMPLETADO | 2026-07-31 | 095653365d5d07581f03caee9a284f14f4c4c91c | 130 pruebas aprobadas; 1 warning no bloqueante; exit code 0 | Revisión adversarial independiente aprobada | Se integró el motor multicampo determinista en el flujo principal; la confirmación solo ocurre con evidencia fuerte y se preserva el valor OCR cuando la evidencia es débil o contradictoria | Riesgo de exceso de REVISAR en escenas con contexto insuficiente; oportunidad de mejorar la resolución con más contexto de cliente, destino y vehículo | Contexto operacional adicional para resolución y auditoría histórica |
| Resolución Inteligente de Clientes – Fase 1 | COMPLETADO | 2026-08-01 | Registrado en commit de cierre del bloque | 164 pruebas aprobadas; 1 warning no bloqueante; exit code 0 | Segunda revisión adversarial independiente aprobada | `resolucion_cliente.py` queda como único punto de decisión para identidad de cliente; cualquier estado no confirmado propaga REVISAR; `enriquecer_datos_con_catalogos` deja definitivamente de resolver cliente | `extractor.py` mantiene fallbacks históricos por número de guía que precargan cliente y RUT. No constituyen una segunda ruta de decisión, pero deberán revisarse en futuras fases de unificación. | Pendiente de apertura formal del siguiente bloque |

## Fuentes oficiales de referencia
- [docs/MOTOR_INTELIGENTE_ATLAS.md](docs/MOTOR_INTELIGENTE_ATLAS.md)
- [docs/CONTRATO_VIAJES_DESKTOP.md](docs/CONTRATO_VIAJES_DESKTOP.md)
- [docs/ATLAS_MASTER_CATALOGS.md](docs/ATLAS_MASTER_CATALOGS.md)
- [04_TRABAJOS_ACTIVOS_ATLAS.md](04_TRABAJOS_ACTIVOS_ATLAS.md)

## Criterio de cierre de bloque
Un bloque se considera cerrado cuando:
1. el cambio quedó documentado;
2. las pruebas relevantes fueron ejecutadas;
3. la auditoría independiente fue aprobada; y
4. el estado queda registrado en esta bitácora y en la bitácora técnica cronológica.
