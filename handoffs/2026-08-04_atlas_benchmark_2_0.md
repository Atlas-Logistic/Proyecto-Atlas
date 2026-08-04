# Handoff — Atlas Benchmark 2.0

## Resumen

Se reprocesó desde cero todo el corpus original recuperable: 127 imágenes
reales únicas, 127 OK, cero errores y ninguna reutilización histórica. El
snapshot anterior de 1.177 filas sólo se usa como línea base porcentual; los
universos no son pareados.

`Confirmado` significa que el campo está presente en un documento cuyo estado
global no es `REVISAR`. Es una medida operacional conservadora, no exactitud
contra ground truth.

| Campo | Evaluados | Extraídos | Confirmados | Revisión | No encontrados | Actual | Snapshot | Variación |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Cliente | 127 | 71 | 8 | 63 | 56 | 55,91 % | 61,09 % | -5,18 pp |
| Destino | 127 | 90 | 8 | 82 | 37 | 70,87 % | 66,02 % | +4,85 pp |
| Chofer | 127 | 91 | 8 | 83 | 36 | 71,65 % | 60,41 % | +11,24 pp |
| Número de transporte | 127 | 90 | 8 | 82 | 37 | 70,87 % | 62,02 % | +8,85 pp |
| Patente tracto | 127 | 70 | 8 | 62 | 57 | 55,12 % | 8,67 % | +46,45 pp |
| Patente rampla | 127 | 19 | 4 | 15 | 108 | 14,96 % | 2,72 % | +12,24 pp |
| Peso | 127 | 29 | 8 | 21 | 98 | 22,83 % | 0,00 % | +22,83 pp |
| Cantidad | 127 | 38 | 1 | 37 | 89 | 29,92 % | 0,00 % | +29,92 pp |
| Material | 127 | 29 | 3 | 26 | 98 | 22,83 % | 22,43 % | +0,40 pp |
| Origen | 127 | 52 | 4 | 48 | 75 | 40,94 % | 0,00 % | +40,94 pp |
| Consolidación | 127 | 90 | 7 | 83 | 37 | 70,87 % | 62,02 % | +8,85 pp |
| Kilómetros | 86 viajes | 2 | 2 | 84 | 0 | 2,33 % | 0,00 % | +2,33 pp |

## Fallos agrupados

| # | Causa raíz operacional | Casos | Impacto | Complejidad estimada |
| ---: | --- | ---: | --- | --- |
| 1 | Material/tipo de carga insuficiente | 117 | Sin identidad material explotable | Alta |
| 2 | Patente rampla ausente o incompleta | 108 | Trazabilidad de equipo incompleta | Media |
| 3 | Peso sin evidencia publicada | 98 | Totales de viaje incompletos | Media |
| 4 | Cantidad sin evidencia publicada | 89 | Totales/unidades incompletos | Alta |
| 5 | Origen ausente | 75 documentos; 47 viajes | Principal bloqueo de rutas | Media-alta |
| 6 | Patente tracto ausente o incompleta | 57 | Identificación de flota incompleta | Media |
| 7 | Cliente ausente o ambiguo | 56 | Búsqueda, filtros y canonización limitados | Alta |
| 8 | Número de transporte no recuperado | 37 | Documento excluido de consolidación | Media-alta |
| 9 | Destino ausente/no confirmado/ambiguo | 37 documentos; 36 viajes | Segundo bloqueo de rutas | Alta |
| 10 | Chofer ausente | 36 | Responsabilidad operacional incompleta | Media |

## Hoja de ruta

1. Cobertura Operacional de Origen: 75 documentos y 47 rutas bloqueadas.
2. Confirmación Maestra de Destinos: 36 rutas bloqueadas.
3. Recuperación de Transporte: 37 documentos fuera de viajes.
4. Recuperación tipada de tracto/rampla: 57/108 ausencias.
5. Evidencia estructurada de Peso y Cantidad: 98/89 ausencias.
6. Identidad de Materiales: 117 tipos no determinados.
7. Resolución conservadora de Clientes: 56 ausencias.
8. Recuperación de Chofer: 36 ausencias.
9. Ground truth estratificado por campo para medir exactitud real.
10. Rendimiento masivo CPU, sólo después de cerrar los bloqueos de datos.

Próximo sprint recomendado: **Cobertura Operacional de Origen — Fase 1**.
