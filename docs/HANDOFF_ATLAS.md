# Handoff — Proyecto Atlas

Estado de traspaso para quien retome el trabajo. Se actualiza al cierre de cada bloque.

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
