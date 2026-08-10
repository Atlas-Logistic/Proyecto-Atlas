# Bitácora Ejecutiva — Proyecto Atlas

Registro de alto nivel de los bloques de trabajo cerrados sobre el lector de guías. Un párrafo por bloque, orientado a decisión y estado, no a implementación.

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
