# Handoff — Desktop UX: Reprocesamiento Inteligente

Fecha: 2026-08-04
Estado: COMPLETADO

Atlas Desktop detecta nombres ya presentes en el CSV acumulado antes de copiar
o procesar imágenes. El diálogo ofrece reutilizar resultados existentes,
reprocesar completamente o cancelar.

Reutilizar conserva el comportamiento idempotente. Reprocesar llama al motor
con `--reprocesar` sobre una salida nueva y luego reemplaza atómicamente solo
las filas obtenidas. Cancelar no copia imágenes ni modifica resultados.

La guía 464089 validó los dos caminos: reutilización sin cambio de hash y
reprocesamiento con `LEANDRO IOLEDO` en la evidencia. La vista agregada muestra
`LEANDRO TOLEDO` por el normalizador histórico del reporte.

No se modificaron OCR, recuperación geométrica, `procesamiento_masivo`, Sistema
Multicampo, Política de Activación ni resolvers.
