# Matriz de resultados — M1 sintético

Ejecución 18/11/2026, Motor base 42005eb, Python del venv local, sin PULL ni red deliberada: `python -m pytest -q pruebas_m1/test_integridad_m1.py tests/test_recuperacion_fila_custodia_p0.py -p no:cacheprovider` → **18 aprobadas**. Los cinco casos de `test_recuperacion_fila_custodia_p0.py` son pruebas sintéticas existentes del Motor, no pruebas de Cloud productivo.

| Área | Resultado | Límite |
|---|---|---|
| B1/B2 | Restauración de bytes ficticios verificados a directorio vacío; original ausente/corrupto se bloquea antes de escribir. | Oráculo y restaurador del arnés, no restaurador Atlas ni almacenamiento independiente real. |
| R1 | Reporte ausente bloquea aun cuando el resto existe. | No se reconstruye reporte ni se inspecciona lector productivo. |
| C1–C5 | Proceso hijo ejecuta `_confirmar_rutas` real con 101 rutas y Cloud ficticia; corte abrupto tras cada lote 50/50/1. Los dos primeros dejan manifiesto con G0 y G1; el oráculo lo rechaza. | No se prueban las cinco barreras exactas del plan, diario, reanudación, escritor concurrente ni lectores reales. El Motor no ha sido modificado para bloquear esa lectura mixta. |
| D1 | Pérdida, duplicación, cambio de confirmante y confirmación fabricada se rechazan frente a oráculo independiente. | Modelo sintético reducido, no auditoría de todas las vías B1/ledger reales. |
| M1 | Inventario detecta envío COMPLETADO posterior, conflicto y ausencia de identidad; queda pendiente sin cambios. Cinco pruebas existentes cubren recuperación focal, guardia e idempotencia. | No se prueba búsqueda en D1/R2 real ni recuperación integral de envío, decisiones y reporte. |
| I1/T1 | Rechazo de escape de ruta, conexión Python y empresa equivocada. | Los mocks Python y variables filtradas no son sandbox del sistema operativo; no se demuestra aislamiento de procesos nativos. |
| D2/M2/F1/U1 | No ejecutado. | Conflictos posteriores, corte R2/D1, falta de espacio, reinicio, Desktop/B1, dispositivo y consumidores directos requieren arnés y entorno adicional. |

**No se considera cerrado M1 ni aprobado el simulacro integral.** Pruebas puras y dobles no prueban seguridad o disponibilidad operacional. La VM sin red y sin acceso a producción del plan sigue siendo requisito para una prueba integral.
