# Transcripción — Validación Operacional Masiva, Fase 1

- Se auditó el mayor snapshot operacional disponible: 1.177 guías reales y
  574 viajes.
- Los 1.177 procesamientos terminaron OK; 1.033 documentos están marcados
  globalmente como `REVISAR`.
- Cobertura: Cliente 61,09 %, Destino 66,02 %, Chofer 60,41 %, Transporte
  62,02 %, tracto 8,67 %, rampla 2,72 % y Material 22,43 %.
- Origen, Peso y Cantidad no forman parte del esquema del snapshot histórico;
  Kilómetros queda en 0/574 para ese corte.
- La consolidación conserva 730/730 documentos con transporte en 574 viajes;
  447 documentos no poseen transporte.
- No se declaró precisión masiva sin ground truth. La referencia E2E separada
  permanece en 48/49 (97,96 %).
- No se implementaron correcciones ni se modificó el producto.
- Recomendación: Reprocesamiento Operacional Controlado y Ground Truth
  Estratificado, priorizando Origen/Transporte/Destino.
