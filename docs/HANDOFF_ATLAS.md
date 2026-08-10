# Handoff — Proyecto Atlas

Estado de traspaso para quien retome el trabajo. Se actualiza al cierre de cada bloque.

---

## 2026-08-10 — Cierre Patentes P1: recuperación geométrica de patentes compatible con Paddle

- **Rama:** `lector-mvp-guia-nueva`. Baseline anterior: `0bcb43ca56e5ab1cdc6f596bb80af225ce234739`.
- **Problema resuelto:** `patente_tracto`/`patente_carro` volvían `"No encontrado"` con salida Paddle porque la extracción original exigía la frase contigua `"RETIRA PATENTE FECHA LLEGADA"`, y Paddle reparte esas etiquetas en bloques/líneas separados. Se agregó `_extraer_patentes_geometrico` (`atlas_core/extractor.py`), nueva función geométrica que ancla en la zona RETIRA–FECHA LLEGADA por coordenadas, activa solo como *fallback* cuando la lectura lineal ya devolvió "No encontrado". **PaddleOCR no se tocó.**
- **Camino histórico EasyOCR preservado:** `buscar_chofer_y_patentes()` (lectura lineal por frase contigua) no se modificó.
- **Alcance deliberadamente acotado:** P1 recupera el valor OCR disponible, no lo corrige. La guía real `464511` recupera `patente_tracto = SD6486` (el valor que Paddle realmente lee, con una B leída como D) y `patente_rampla = JF4288` (correcto); no se corrige `SD6486` a `SB6486`.
- Suite final: **566/566 tests** (556 → 566).
- No se tocó Desktop ni la generación de reportes — ambos consumen el dict que devuelve `procesar_archivo`, así que reciben el valor recuperado automáticamente sin cambios propios.
- **Próximo microbloque pendiente:** homologación de patente OCR contra catálogo de vehículos (ejemplo `SD6486 → SB6486`), sin alterar el OCR. No iniciado.

---

## 2026-08-10 — Integración Desktop ↔ Motor Paddle cerrada

- **Rama:** `lector-mvp-guia-nueva`. Baseline anterior: `e61c04af4081b3d52761ad7928291bd88b6a83d2`.
- Atlas Viajes Desktop 1.4.3 y el motor vuelven a compartir el contrato histórico `--catalogos <ruta>`. También se admite `ATLAS_CATALOGOS_DIR`; fuentes incompletas, inexistentes o compuestas solo por plantillas `.example` se rechazan.
- `resumen_procesamiento_desktop.py` fue recuperado desde Git y verificado contra su blob histórico. `generar_reporte_viajes.py`, `atlas_core/gestor_viajes.py` y `atlas_core/reporte_viajes.py` también fueron recuperados desde la línea histórica compatible y validados contra el HEAD actual.
- La propagación de catálogos fue fusionada selectivamente con M2. **PaddleOCR continúa como proveedor principal**, GPU activa en este PC, proveedor único reutilizado por lote y EasyOCR disponible como fallback.
- Suite final: **556/556 tests**.
- Prueba manual end-to-end exitosa: Desktop procesó la guía real `464511`, obtuvo transporte `0000352449`, fecha `10-08-2026`, cliente `ARMACERO MATCO SA` y chofer `RODRIGO NAHUELÑIR`; el viaje se mostró correctamente en Atlas Viajes 1.4.3 con estado OK.
- Los 574 viajes operativos no fueron reprocesados ni modificados durante las pruebas técnicas aisladas.
- **Próximo frente:** RECUPERACIÓN UX HISTÓRICA del Desktop. No iniciar cambios del motor como parte de ese frente. Antes de considerar perdido un archivo o comportamiento, revisar `G:\Mi unidad\BACKUP_PRE_FORMATEO_20260808`.

---

## 2026-08-10 — Cierre Bloque M2: runtime Paddle portable + activación batch (pendiente de tu aprobación final)

- **Rama:** `lector-mvp-guia-nueva`. **Sin commit, sin push** — a la espera de que apruebes antes de cerrar formalmente (a diferencia de M1, aquí no hice el commit todavía porque me pediste el reporte de los 10 puntos primero).
- **Runtime portable resuelto:** `%LOCALAPPDATA%\Atlas\runtime\paddleocr` (variable de entorno `ATLAS_PADDLE_RUNTIME` disponible como override de desarrollo). Ya no depende de `ocr_eval_gpu_env` ni de ninguna ruta de este PC — confirmado por tests y por `grep` sobre la validación real.
- **`procesar_carpeta` ya activa PaddleOCR en el flujo real de lote** — antes de este bloque solo `procesar_archivo` sabía usar un proveedor; ahora la CLI real (`analizar_guias_masivo.py`) lo hace por defecto, con un único proveedor por ejecución.
- **Validado con una instalación real desde cero** (no simulada): el bootstrap completo tomó 209 s. Una corrida corta real de 4 guías con la CLI real confirmó GPU seleccionada automáticamente, un solo mensaje de proveedor activo (no uno por imagen), y resultados correctos.
- **No se corrieron las 30 imágenes de nuevo** — decisión deliberada, ya justificada: la lógica de extracción no cambió respecto a M1 (que sí las validó completas), este bloque solo tocaba la resolución de runtime y la activación en `procesar_carpeta`.
- **Nota de rendimiento para quien lea las métricas de una primera corrida en una máquina nueva:** el primer uso de un runtime recién creado es notablemente más lento (antivirus escaneando binarios nuevos, cachés fríos) — no lo tomes como el rendimiento real; una segunda corrida ya estabiliza.
- **Hallazgo fuera de alcance:** apareció un archivo no rastreado `resumen_procesamiento_desktop.py` en la raíz del repo, que yo no creé ni toqué — queda ahí, sin explicación, fuera de este commit. Alguien debería revisar de dónde salió.
- Suite: 482 → **501 tests**, todos verdes.
- **Siguiente decisión pendiente:** no hay un bloque M3 definido todavía. Con M1+M2, PaddleOCR queda como motor principal, portable, activo en el flujo real, con EasyOCR de fallback — el trabajo de integración de este frente queda esencialmente completo salvo lo que decidas priorizar después (p. ej. confirmar el camino CPU puro en una máquina sin GPU, que sigue pendiente desde M1).

---

## 2026-08-10 — Cierre Bloque M1: proveedor OCR + PaddleOCR integrado (APROBADO)

- **Rama:** `lector-mvp-guia-nueva`. Commit hecho y pusheado a `origin/lector-mvp-guia-nueva` (ver SHA en el mensaje de cierre de esa sesión).
- **Decisión de cierre: PaddleOCR queda aprobado como motor OCR principal de Atlas. EasyOCR queda como fallback temporal**, no eliminado — sigue siendo el proveedor si Paddle no está disponible, y sigue siendo el camino usado por defecto en el código cuando no se pasa `proveedor=` explícitamente.
- **Precisión importante para quien retome esto:** "integrado" significa que la infraestructura (`ProveedorOCR`, `EasyOCRProvider`, `PaddleOCRProvider`, selección GPU/CPU, `numero_guia` robusto, focal generalizado) está lista, testeada (482 tests) y validada con una corrida real de las 30 guías — **no** que `procesar_carpeta` (el punto de entrada real de la CLI/lote) ya construya y use un `PaddleOCRProvider` por defecto. `procesar_carpeta` todavía no recibe ni pasa ningún `proveedor` — sigue llamando a `procesar_archivo` solo con `lector_ocr` (EasyOCR). Conectar el proveedor Paddle al flujo de lote real (`procesar_carpeta`/CLI) sigue pendiente y no se hizo en M1.
- **numero_guia recuperado:** 2/30 → 29/30, reutilizando `decidir_bloques_ocr` (ya existía) conectado al proveedor activo.
- **`IMG-20250930-WA0047.jpg` (número de guía):** discrepancia editorial de ground truth pendiente (410627 documentado vs 410267 que la imagen realmente muestra, según la observación original del validador) — no cuenta como fallo de Atlas, no bloqueó el cierre.
- **PaddleOCR corre en proceso completamente aislado**, nunca en el entorno principal — sus ~55 dependencias no tocan `requirements.txt` ni el venv de producción.
- **Selección GPU/CPU automática**, sin GPU hardcodeada. GPU real confirmada en este PC (3.03 s/imagen). **Portabilidad CPU explícitamente diferida**: no se corrió otro benchmark completo de 30 imágenes en CPU en este cierre — se validará con una prueba corta en el PC de oficina en un momento posterior.
- **Riesgo principal pendiente, con nombre:** `PaddleOCRProvider` apunta hoy a una ruta fija de este equipo (`C:\Users\Jjjc0508\Desktop\Atlas\ocr_eval_gpu_env`), creada para el bloque de evaluación — no es arquitectura de despliegue definitiva.
- **`IMG-20260512-WA0027.jpg` queda `REVISAR`** por la guarda documental — su fecha sigue siendo incorrecta, la guarda no la corrige, solo evita que pase como dato confiable.
- Suite: 458 → **482 tests**, todos verdes.
- **Próximo bloque oficial: M2 — runtime Paddle reproducible/portable** (reemplazar la ruta fija del venv por algo que no dependa de este equipo específico). No iniciado todavía.

---

## 2026-08-10 — Cierre Bloque Fechas F2 (con gate de confianza)

- **Rama:** `lector-mvp-guia-nueva`.
- **F2 completado y auditado:** recuperación OCR focal de FECHA DE EMISIÓN (recorte + 4 variantes, mismo mecanismo que transporte), disparada solo cuando la lectura global devuelve "No encontrado". El consenso exige ≥2 variantes coincidentes **y** que todas ellas tengan confianza ≥ `CONFIANZA_MINIMA_FECHA_FOCAL = 0.70`; si no, se abstiene.
- **Por qué existe el gate de confianza:** la primera versión (solo conteo, sin confianza) recuperó `IMG-20250930-WA0047.jpg` correctamente, pero también produjo un valor **incorrecto** en `IMG-20250930-WA0046.jpg` (3 de 4 variantes coincidieron en el mismo dígito mal leído). Auditar la confianza real de EasyOCR mostró una separación clara: los votos del caso incorrecto tenían confianza mínima 0.47; los del caso correcto, 0.95. Con el gate de 0.70, `WA0046` ahora se abstiene correctamente en vez de arriesgar el valor.
- **⚠️ El umbral 0.70 está validado sobre una muestra real limitada** (7 imágenes con caja geométrica, de las cuales solo 2 llegaron a tener consenso por conteo). El margen observado es amplio, pero esto **no demuestra que 0.70 generalice** a otros documentos o lotes. Antes de tratarlo como calibración definitiva, hace falta más muestra.
- **Estado final de la muestra real de 30 guías (OCR ejecutado de nuevo, dos veces, sin reutilizar corpus anterior):** 14/30 → **15/30** exactas. 1 recuperación correcta (`WA0047`), **0 recuperaciones incorrectas, 0 degradaciones** de los 14 aciertos previos.
- De los 15 fallos restantes: 6 dispararon focal y se abstuvieron correctamente (sin caja clara o sin consenso suficiente), 9 nunca encontraron ancla geométrica para "FECHA DE EMISION" en esta corrida (imágenes con degradación severa o donde la etiqueta no se leyó en absoluto).
- **Próximo bloque oficial: NO es seguir afinando EasyOCR.** Es **OCR-EVAL** — benchmark controlado de motores OCR alternativos, usando las muestras reales ya existentes (`Atlas\datos_privados\muestra_fechas_30` y su ground truth), para decidir si el techo actual (15/30, con la mayoría de fallos por degradación de imagen o pérdida total del valor en el OCR de página completa) es un límite del motor OCR en uso, no del pipeline de extracción.

---

## 2026-08-10 — Cierre Bloque Fechas F1

- **Rama:** `lector-mvp-guia-nueva`.
- **F1 completado:** guarda de plausibilidad temporal por defecto (2015–2035) en `extraer_fecha`, aplicada solo cuando no se entrega `fecha_desde`/`fecha_hasta` explícito.
- **Estado de la muestra real de 30 guías:** 14/30 exactas. **16/30 siguen sin acierto exacto.** De esos 16, 3 ahora fallan de forma segura (`"No encontrado"` en vez de una fecha con año absurdo como `7029`, `7025` o `1024`); los otros 13 no cambiaron con este bloque.
- **Evidencia previa (diagnóstico del mismo bloque de trabajo, antes de F1):** sobre las 16 fallas originales, se buscó la fecha real exacta (en todo formato) en el texto OCR crudo completo de cada imagen. En **0 de 16** casos la fecha correcta estaba presente en el OCR — es decir, los 16 errores originales nacen antes del extractor, en el OCR/calidad de imagen, no en la lógica de selección o prioridad de `extraer_fecha`.
- **Próximo bloque oficial:** mejora de OCR focal/adaptativa específicamente sobre la región de FECHA DE EMISIÓN (no tocar `extraer_fecha`; el cuello de botella está antes, en la lectura). No se ha iniciado.

### Para retomar

- Ground truth y muestra real viven fuera del repo, en `C:\Users\Jjjc0508\Desktop\Atlas\datos_privados\` (`muestra_fechas_30\`, `ground_truth\validacion_atlas_30_guias_v1.xlsx`) — no están versionados por diseño (datos privados de clientes).
- Bitácora ejecutiva: `docs/BITACORA_EJECUTIVA.md`. Bitácora técnica: `docs/BITACORA_TECNICA_CRONOLOGICA.md`.
- Baseline de tests: `python -m pytest -q` → 441 passed.
