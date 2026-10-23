# Fecha de emisión con etiqueta compacta — corrección 23/10/2026

Base operativa: `340bc63`. Diagnóstico previo: rama `docs/diagnostico-fecha-emision-compacta-20261022` (`005c97e`).

## Problema
RapidOCR (camino Mobile/PULL) puede entregar la etiqueta sin espacios (`FECHA DEEMISION`). Las reglas de fecha
exigían los espacios: `_clasificar_contexto_fecha` dejaba la fecha de emisión como «otra etiqueta» y elegía la de
salida/llegada; el ancla de `_extraer_fecha_geometrico` se abstenía y no corroboraba. La guía quedaba `OK` con la
fecha equivocada.

## Cambio
`extractor.patron_etiqueta_fecha(tipo)` = `FECHA\s*(?:DE\s*)?<tipo>`: un único patrón compartido por la regla lineal
(`procesamiento_masivo._clasificar_contexto_fecha`) y la geométrica (`_extraer_fecha_geometrico`, emisión y rivales
salida/llegada). Prioridades, distinción emisión/salida/llegada, abstenciones y OCR original sin cambios. No se
completa ninguna fecha desde reloj, archivo, captura u otras guías.

## Pruebas
`tests/test_fecha_emision_etiqueta_compacta.py` (21, sintéticas): regresión del caso (5 variantes compactas, lineal
y geométrica), etiquetas normales, clasificación compacta, salida/llegada compactas conservan su tipo, prioridad
emisión sobre salida legible, abstención geométrica junto a salida, emisión ausente sin confirmar otra fecha,
palabras que sólo contienen EMISION. En la base fallan 14 y pasan 7; con el cambio pasan 21.

Focales (extracción, procesamiento, fechas, OCR manual, RapidOCR, proveedor, progreso Desktop, Mobile):
531 aprobadas / 7 fallidas con el cambio; 517 / 21 en la base. Las 7 son idénticas en ambas (preexistentes,
reproducidas en la base también sin bloquear el runtime Paddle). Se ejecutaron con `ATLAS_PADDLE_RUNTIME` apuntando a
un archivo para impedir que una prueba descargue PaddleOCR.

Laboratorio aislado, foto real 482851 por el camino Mobile (RapidOCRProvider + `procesar_archivo`): base 22-10-2026,
corregido **21-10-2026**; texto OCR idéntico (117 líneas) y los otros 55 campos sin cambios.

## Integración
Fast-forward de la rama sobre el Motor operativo cuando Codex lo coordine, sin operaciones activas; repetir
`pytest tests/test_fecha_emision_etiqueta_compacta.py`. No corrige datos ya registrados: las guías existentes
conservan su fecha hasta una corrección controlada.
