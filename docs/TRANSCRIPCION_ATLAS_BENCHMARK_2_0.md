# Transcripción — Atlas Benchmark 2.0

- Se inventariaron imágenes reales disponibles y se eliminaron 16 duplicados
  exactos; el corpus congelado quedó en 127 originales únicos.
- Se ejecutó el motor actual desde cero: 127 OK, cero errores y cero omisiones.
- No se reutilizó el CSV histórico ni se modificaron OCR, Multicampo, Política,
  Desktop, ORS, código o catálogos.
- Las mejoras de cobertura más grandes frente al snapshot fueron tracto
  (+46,45 pp), Origen (+40,94 pp), Cantidad (+29,92 pp) y Peso (+22,83 pp).
- Cliente obtuvo 55,91 %, 5,18 pp menos que el snapshot; la comparación no es
  pareada y no demuestra regresión por sí sola.
- Se generaron 86 viajes desde cero: 7 confirmados, 79 en revisión y 37
  documentos sin transporte.
- OpenRouteService calculó 2 rutas reales; 47 viajes carecen de origen y 36
  tienen bloqueo de destino.
- El principal patrón documental es Material/tipo de carga insuficiente
  (117/127), pero el mayor desbloqueo operacional inmediato es Origen.
- Siguiente sprint recomendado: Cobertura Operacional de Origen — Fase 1.
