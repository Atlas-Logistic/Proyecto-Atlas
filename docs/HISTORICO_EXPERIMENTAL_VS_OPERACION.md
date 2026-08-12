# Histórico experimental vs. operación actual

Documento de referencia rápida para quien retome trabajo en Atlas.
Detalle técnico completo del análisis que llevó a esta decisión en
`docs/BITACORA_TECNICA_CRONOLOGICA.md` (bloques ESTADOS S1 → S2 → S2.1 →
S2.2 → IDENTIDAD I1 → S3 → S3.1 → PRODUCCIÓN P1).

## Decisión de producto (Javier, 2026-08-12)

Los **574 viajes** publicados hasta el 2026-08-12 fueron generados el
2026-07-28 a partir de un corpus usado como **prueba y experimentación**
durante el desarrollo de Atlas (validación de funciones, OCR, motores de
extracción, UX) — **no un histórico operacional real**. No se invirtió
más tiempo en migrarlos, reclasificarlos documento por documento ni
convertirlos en el dataset operativo definitivo.

## Fecha de corte

**2026-08-12.** Desde esta fecha, los viajes procesados por Atlas usan el
esquema y la semántica actuales (esta rama, `lector-mvp-guia-nueva`, HEAD
en el momento del corte: `ecaa92746fb30b3b4509fc99ec96842ffc806280` +
este bloque).

## Ubicaciones (instalación real, `AppData\Local\Atlas\datos\`)

| Qué | Antes del corte | Después del corte |
|---|---|---|
| Reporte de viajes | `reportes\actual\` (574 viajes, esquema anterior a O1/S2) | movido a `reportes\historicos\experimental_2026-07-28_574viajes\` |
| CSV masivo documental | `procesamiento\analisis_completo_guias.csv` (1177 filas) | movido a `procesamiento\historico_experimental\analisis_completo_guias_574viajes_experimental.csv` |
| **Reporte operacional actual** | — | **`reportes\actual\`** (nuevo, esquema completo O1+E1+S2+S2.2+I1) |
| **CSV masivo operacional actual** | — | **`procesamiento\analisis_completo_guias.csv`** (nuevo, empieza con las guías reales ya en `entradas\`) |

El histórico **no se borró ni se modificó** — solo se separó su rol. Cada
carpeta histórica incluye su propio `LEEME_HISTORICO_EXPERIMENTAL.md`
explicando qué es y por qué no es la fuente productiva.

## Dataset operacional inicial

Se construyó con las únicas guías reales ya presentes en `datos\entradas\`
al momento del corte (463594 "Villagra", 463630 "Ñancucheo") —
reprocesadas con el motor actual, **sin OCR masivo** sobre el corpus
histórico. Resultado inicial: 2 viajes, ambos `REQUIERE_REVISION` con
motivos explícitos reales (`CLIENTE_SIN_CORROBORAR`,
`OBRA_DESTINO_SIN_CORROBORAR`, `PATENTE_SIN_HOMOLOGAR`,
`CLIENTE_AUSENTE`) — no se maquilló el resultado para que se vea "más
limpio"; es el estado real de esos dos documentos bajo el modelo actual.

## Flujo hacia adelante

Cada imagen nueva arrastrada en Atlas Desktop desde el corte:

`imagen → motor actual (extractor.py + procesamiento_masivo.py, con S2/S2.2/I1) → analisis_completo_guias.csv operacional (procesamiento\) → viajes.csv operacional (reportes\actual\)`

**Nunca se mezcla automáticamente con el histórico experimental** — viven
en carpetas distintas, y `procesar_carpeta`/`generar_reporte_viajes`
siempre operan sobre las rutas operacionales actuales salvo que se les
indique explícitamente lo contrario.

## Cargar el histórico manualmente (si hace falta)

El histórico experimental sigue siendo un CSV/reporte válido con el
esquema anterior — Atlas Desktop puede abrirlo manualmente (selector de
archivo) para consulta o regresión. Los campos nuevos (peso, horas,
ruta) se mostrarán como "No disponible", comportamiento esperado (mismo
contrato de compatibilidad hacia atrás ya validado desde el Bloque O1).
No se construyó un filtro ni una vista especial para este caso — cargar
el archivo antiguo ya funciona con el parser existente.
