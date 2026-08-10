# Bitácora Ejecutiva — Proyecto Atlas

Registro de alto nivel de los bloques de trabajo cerrados sobre el lector de guías. Un párrafo por bloque, orientado a decisión y estado, no a implementación.

---

## 2026-08-10 — Bloque Fechas F2: recuperación OCR focal de FECHA DE EMISIÓN (cerrado)

- Baseline de entrada: 14/30 exactas (F1 cerrado).
- F2 agrega una segunda pasada de OCR focal (recorte + 4 variantes: original, grises, ampliada 2x, ampliada 2x con contraste) **solo** cuando la lectura global de fecha devuelve "No encontrado". Nunca reemplaza una fecha global ya válida. Reutiliza en un 100% la arquitectura ya existente (el mismo mecanismo que hoy corrige número de transporte).
- **Auditoría previa al cierre (F2.1/F2.2):** la primera versión del consenso (aceptar con ≥2 de 4 variantes coincidentes, sin mirar confianza) recuperó 1 caso correcto (`IMG-20250930-WA0047.jpg`) pero también produjo 1 valor **incorrecto** con "consenso" aparente (`IMG-20250930-WA0046.jpg`, 3 de 4 variantes coincidiendo en un dígito mal leído). Se auditó la confianza real de EasyOCR por variante: los votos del caso incorrecto tenían confianza mínima 0.47; los del caso correcto, mínima 0.95 — margen amplio entre ambos.
- **Cambio de cierre:** el consenso ahora exige, además de ≥2 variantes coincidentes, que la confianza de **todas** esas variantes sea ≥ `CONFIANZA_MINIMA_FECHA_FOCAL = 0.70` (constante nombrada y documentada). Si algún voto coincidente queda por debajo, se abstiene.
- **Resultado real final sobre la muestra de 30 guías, OCR ejecutado de nuevo:** **14/30 → 15/30 exactas**. Recuperación correcta: `IMG-20250930-WA0047.jpg` → `30-09-2025`. `IMG-20250930-WA0046.jpg` ahora queda correctamente en `"No encontrado"` (antes era el valor incorrecto). **0 recuperaciones incorrectas, 0 degradaciones de los 14 aciertos previos.**
- Suite completa verde: 441 → **458 tests**.
- **Advertencia explícita:** el umbral `0.70` es conservador y está validado sobre una muestra real **limitada** (7 casos con caja geométrica, de los cuales solo 2 tenían consenso por conteo). Separa con margen amplio los dos únicos casos observados, pero **no prueba suficiencia general** del motor OCR ni garantiza que el umbral generalice a otros documentos. Requiere seguimiento con más muestra.
- Siguiente foco: **no** es seguir afinando EasyOCR. El próximo bloque oficial es OCR-EVAL — benchmark controlado de motores OCR alternativos sobre las muestras reales existentes.

---

## 2026-08-10 — Bloque Fechas F1: guarda de plausibilidad temporal

- **Baseline real de fechas** (muestra histórica de 30 guías, ejecución completa de OCR + `extraer_fecha` sobre `cab3837`): **14/30 exactas (46,7%)**.
- F1 agrega una guarda de plausibilidad temporal por defecto de **2015–2035** para cuando no se entrega `fecha_desde`/`fecha_hasta` explícito.
- Las 3 fechas con año absurdo detectadas en la muestra (`7029`, `7025`, `1024`) pasan de devolverse como fecha falsa silenciosa a **"No encontrado"**.
- La exactitud exacta **permanece en 14/30** — el cambio no convierte ningún error en acierto, solo hace más seguros los 3 casos anteriores.
- **16/30 siguen sin acierto exacto.** De esos 16, los 3 mencionados ahora fallan de forma segura ("No encontrado" en vez de un dato falso); los otros 13 no cambiaron.
- **0 degradaciones**: ningún acierto previo se perdió.
- **441 tests verdes** (433 base + 8 nuevos de este bloque).
- **Siguiente foco:** el cuello de botella ya no es `extraer_fecha` — es la calidad del OCR sobre la etiqueta FECHA DE EMISIÓN. El próximo bloque oficial ataca eso, no el extractor.
