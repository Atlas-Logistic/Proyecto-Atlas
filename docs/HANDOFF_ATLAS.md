# Handoff — Proyecto Atlas

Estado de traspaso para quien retome el trabajo. Se actualiza al cierre de cada bloque.

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
