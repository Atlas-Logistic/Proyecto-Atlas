# Handoff — fecha de emisión con etiqueta compacta (diagnóstico 482851, 22/10/2026)

Diagnóstico cerrado, **sin implementar**. Para quien retome (Codex).

## Fallo vigente
Guía Mobile 482851, foto clara: emisión impresa 21-10-2026; Atlas registra y Desktop muestra 22-10-2026
(FECHA LLEGADA del pie) con `estado_documental = OK`, sin motivo. Reproducido en laboratorio aislado con el
Motor actual y RapidOCR por el camino Mobile (`procesar_archivo` con catálogos, recolector y planta informada).

## Base exacta
- Motor `ddcebf4` (git archive). La lógica de fecha es idéntica en d495011, b272104, 6af7836 y en OFICINA
  5fd2a56/80cfd5d (diferencias sólo en despachar_a/patentes).
- Desktop instalado `app.asar 3286704c…`: muestra `f.fecha` sin transformar (`atlas_viajes.html` normalizarFila y
  tabla de viajes).

## Causa y funciones responsables
1. OCR correcto: `21-10-2026` (conf. 0,953) junto a la etiqueta, pero ésta llega como `FECHA DEEMISION`.
2. `atlas_core/procesamiento_masivo._clasificar_contexto_fecha`: regex `FECHA\s+(?:DE\s+)?EMISION` no reconoce la
   etiqueta compacta -> la fecha de emisión queda prioridad 2 («OTRA ETIQUETA»); la de llegada queda prioridad 1
   («FECHA SALIDA») porque «LLEGADA» llegó separada de «FECHA» y el valor de salida no se leyó.
   `extraer_fecha` elige la de llegada.
3. `atlas_core/extractor._extraer_fecha_geometrico`: ancla `re.fullmatch(r"FECHA(?: DE)? EMISION", texto)`
   -> se abstiene (`{}`), así que la corroboración geométrica de `procesar_archivo` no corrige.
4. La normalización que ya resuelve esto, `atlas_core/ocr_manual.separar_etiqueta`, sólo actúa en
   `RapidOCRManualProvider` (`ATLAS_OCR_MANUAL=1`, ingreso manual de Desktop). Mobile/PULL usa `RapidOCRProvider`.
5. Validación acepta la fecha (válida y plausible); persistencia, consolidación de viaje y Desktop la propagan.

Condiciones necesarias: etiqueta de emisión compacta **y** otra fecha distinta mejor clasificada. Frecuencia no medida.

## Reproducción mínima (sintética, sin OCR)
`python -I -B experimentos_atlas_ia/diagnostico_fecha_emision/repro_sintetica.py` desde la raíz de Motor.
En ddcebf4 imprime `lineal compacta=02-01-2030 separada=01-01-2030` y `geometrica compacta={} separada=01-01-2030`.

## Cambio mínimo propuesto
Sin tocar OCR ni proveedores, reconocer la etiqueta compacta en el camino compartido:
- `_clasificar_contexto_fecha`: `FECHA\s*(?:DE\s*)?EMISION` (y tolerancia equivalente en SALIDA/LLEGADA).
- ancla de `_extraer_fecha_geometrico`: `FECHA ?(?:DE ?)?EMISION`.
Alternativa equivalente: aplicar `separar_etiqueta` a líneas/bloques antes de extraer en todos los caminos.

## Pruebas de aceptación
1. Convertir `repro_sintetica.py` en prueba: ambas reglas devuelven la fecha de emisión con la etiqueta compacta.
2. Regresión focal: pruebas existentes de prioridad emisión/salida/llegada, fecha geométrica y adaptador manual.
3. Laboratorio con la foto real por el camino Mobile: fecha 21-10-2026 y demás campos sin cambios.

## Evidencia privada (no versionada) y límites
- `C:\Atlas\pruebas\diagnostico-actual-482851-20261022\` (`RESULTADO.md`, recortes, OCR con geometría,
  extracción, filas de dataset/viajes, scripts de reproducción).
- No se acreditó qué PC procesó el envío en producción (la lógica de fecha es igual en todas las candidatas).
- El otro documento del mismo viaje (482850) también figura con 22-10-2026; no fue analizado.
- El peso ausente de esta foto no se diagnosticó: una firma tapa un dígito.
