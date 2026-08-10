# Bitácora Técnica Cronológica — Proyecto Atlas

Registro técnico, en orden cronológico, de cambios de código sobre el lector de guías. Un bloque por entrada, con archivos modificados, decisión de diseño y validación.

---

## 2026-08-10 — Bloque M1: proveedor OCR + compatibilidad de extractores (CERRADO)

**Rama:** `lector-mvp-guia-nueva` · **HEAD previo:** `ddf4309c7bebc80704b733c0517da700666e93b6 feat: agregar recuperacion focal conservadora de fecha`

### Decisiones de cierre

- **PaddleOCR aprobado como motor principal**; `EasyOCRProvider` queda como fallback temporal (automático si Paddle no está disponible, y siempre disponible explícitamente vía `crear_proveedor_ocr("easyocr")`).
- No se ejecutó otro benchmark completo de 30 imágenes en CPU en este cierre — la portabilidad CPU se confirmará después con una prueba corta en el PC de oficina. No bloquea el cierre.
- `IMG-20250930-WA0047.jpg`: el desacuerdo entre `410627` (ground truth) y `410267` (lo que la imagen realmente muestra, según la propia observación del validador original en el Excel) se registra como discrepancia editorial de ground truth pendiente, no como fallo de `decidir_bloques_ocr` ni de Atlas.
- **Riesgo principal pendiente, explícito:** `PaddleOCRProvider` apunta hoy a `RUTA_VENV_PADDLE = C:\Users\Jjjc0508\Desktop\Atlas\ocr_eval_gpu_env` (constante en `atlas_core/ocr_provider.py`) — un venv creado para el bloque de evaluación, no una ruta de despliegue definitiva. El siguiente bloque oficial (**M2**) debe reemplazar esto por un runtime reproducible/portable, no atado a una ruta específica de este equipo.

### Contexto

Bloque de implementación (decisión de migrar a PaddleOCR ya tomada en evaluaciones previas, no se re-evalúa aquí). Objetivo: integrar PaddleOCR detrás de una abstracción, sin romper EasyOCR, resolviendo las dos incompatibilidades ya diagnosticadas (`numero_guia` frágil a adyacencia textual; recuperación focal acoplada a `easyocr.Reader`).

**Hallazgo relevante antes de implementar:** `atlas_core/experimento_numero_guia_contextual.py::decidir_bloques_ocr` (ya usado por `procesar_archivo`) es un mecanismo ancla→marcador→candidato **agnóstico al motor OCR** que ya tolera bloques intermedios entre "GUIA"/"DESPACHO"/"ELECTRONICA". Una prueba directa con los bloques de PaddleOCR (sin cambiar nada) ya recuperaba 29/30 — la "regresión" medida en el bloque de evaluación anterior fue un hueco del arnés de esa evaluación (no invocaba `decidir_bloques_ocr`), no una limitación real de Atlas. Esto simplificó el alcance de M1: no hizo falta escribir un extractor geométrico nuevo para `numero_guia`, solo conectar `decidir_bloques_ocr` al proveedor activo.

### Archivos nuevos

- **`atlas_core/ocr_provider.py`**: contrato `ProveedorOCR` (Protocol): `leer_texto`, `leer_bloques`, `leer_focal`. `EasyOCRProvider` envuelve las funciones existentes de `atlas_core.ocr` sin cambiarlas. `PaddleOCRProvider` ejecuta PaddleOCR en un **proceso aislado** (venv externo `C:\Users\Jjjc0508\Desktop\Atlas\ocr_eval_gpu_env`, el mismo ya validado en el bloque OCR-EVAL GPU — el wheel `paddlepaddle-gpu` corre igual en CPU pasando `device="cpu"`, así que un solo venv basta para ambos casos), comunicándose por un protocolo JSON línea a línea sobre stdin/stdout con un proceso worker persistente (no se recarga el modelo por imagen). `_gpu_nvidia_disponible()` detecta GPU vía `nvidia-smi` sin hardcodear ningún modelo. `crear_proveedor_ocr(preferido="paddleocr")` selecciona el proveedor y cae a `EasyOCRProvider` si Paddle no está disponible (venv ausente, worker no arranca, etc.) — `ProveedorOCRNoDisponible` es la excepción de señalización para ese fallback.
- **`atlas_core/paddleocr_worker.py`**: script standalone (solo stdlib + paddleocr + Pillow/numpy, **cero imports de atlas_core**) que corre bajo el intérprete del venv aislado. Replica el recorte/margen/4-variantes de `_leer_region_focal` (duplicado necesario por el aislamiento de proceso — si el recorte/margen cambia en `atlas_core/ocr.py`, este archivo debe actualizarse a mano, queda documentado en su docstring). Aplica `enable_mkldnn=False` cuando `device="cpu"` (workaround de Fase 0 de OCR-EVAL).

### Archivos modificados

**`atlas_core/procesamiento_masivo.py`:**
- `procesar_archivo` gana un parámetro opcional `proveedor: ProveedorOCR | None = None`. Sin él, el comportamiento es **exactamente el mismo de antes** (EasyOCR directo vía `lector_ocr`) — confirmado por test explícito y por la suite completa sin cambios. Con él, tres closures internas (`_leer_texto`, `_leer_bloques`, `_leer_focal`) enrutan cada llamada de OCR (texto completo, bloques, focal de fecha/transporte) al proveedor en vez de a `leer_texto_imagen`/`leer_bloques_imagen`/`_leer_transporte_focal`/`_leer_fecha_focal` directos.
- Import de `ALLOWLIST_FECHA`/`ALLOWLIST_TRANSPORTE` desde `atlas_core.ocr` para pasarlos explícitamente al proveedor en las llamadas focales (antes vivían implícitos dentro de `_leer_transporte_focal`/`_leer_fecha_focal`).
- **Guarda documental nueva:** `CAMPOS_GUARDA_DOCUMENTAL` (numero_guia, numero_transporte, cliente, obra_destino, chofer, patente_tracto, patente_carro) + `UMBRAL_CAMPOS_FALTANTES_DOCUMENTO_DEGRADADO = 5` + `_documento_degradado(datos, descripcion)`: si ≥5 de esos 8 indicadores (7 campos + descripción) vuelven vacíos a la vez, se suma a `requiere_revision`. Nunca cambia un valor ni descarta una fecha ya encontrada — solo empuja el indicador hacia `REVISAR`.

**Sin cambios:** regex de `extraer_fecha`, F1 (guarda de plausibilidad), F2 (consenso de confianza), extractores lineales/geométricos existentes, contrato `BloqueOCR`, `requirements.txt`, entorno Python principal.

### Tests

- `tests/test_ocr_provider.py` (16 nuevos): contrato `EasyOCRProvider` (delegación a `leer_texto_imagen`/`leer_bloques_imagen`/`_leer_region_focal`, lector creado una sola vez); contrato `PaddleOCRProvider` con proceso mockeado (texto/bloques/focal vía protocolo JSON, error de una imagen no mata el proceso, `ProveedorOCRNoDisponible` si el worker no arranca o el venv no existe); selección de proveedor (`easyocr` explícito nunca toca Paddle; Paddle disponible se usa; Paddle no disponible cae a EasyOCR); detección de GPU sin `nvidia-smi`.
- `tests/test_procesamiento_masivo.py` (8 nuevos): `numero_guia` con etiqueta fragmentada en bloques (caso real de Paddle) recuperado vía proveedor; `numero_guia` sin marcador cercano se abstiene; fecha focal vía proveedor; transporte focal vía proveedor; `_documento_degradado` activa con muchos campos faltantes / no activa con pocos (tests puros); `procesar_archivo` con documento degradado queda `REVISAR`; `procesar_archivo` sin `proveedor` conserva exactamente el comportamiento anterior (ancla de no-regresión).

### Validación

- Tests específicos: 24 nuevos, todos verdes.
- Suite completa: `458 → 482 passed`.
- Validación real: `procesar_archivo(ruta, proveedor=proveedor)` con un `PaddleOCRProvider` **real** (proceso vivo, GPU real, sin mocks) sobre las 30 imágenes:
  - `numero_guia`: **2/30 → 29/30** (el único caso restante, `IMG-20250930-WA0047.jpg`, es la disputa de ground truth ya documentada en el Excel original: "la validación manual anterior indicó guía 410627; la imagen muestra 410267").
  - `fecha`: 27/30 (sin cambio respecto a la evaluación previa).
  - `numero_transporte` 28/30, `cliente` 21/25, `obra_destino` 12/27, `chofer` 15/23, `descripción_material` 24/25, `tipo_carga` 24/29 — todos iguales a la evaluación previa, sin regresiones. (Nota: el primer cálculo de `descripcion_material` en el script de validación dio 0/25 por un comparador equivocado en el script — no en Atlas —, corregido antes de reportar; con el comparador correcto da 24/25, igual que antes.)
  - `IMG-20260512-WA0027.jpg`: `indicador_revision = REVISAR` confirmado.
  - Proveedor real creado: `PaddleOCRProvider` (no cayó a fallback). Tiempo: 90.9 s para 30 imágenes (3.03 s/imagen), consistente con uso real de GPU.
  - Camino CPU: implementado y cubierto por tests (incluye `enable_mkldnn=False`), pero no se re-ejecutó un benchmark completo de 30 imágenes en CPU dentro de este bloque — se apoya en la validación de Fase 0/OCR-EVAL CPU ya hecha sobre el mismo camino de código, que no cambió.

### Estado de cierre

`git status` previo al commit: working tree con 2 rutas modificadas (`atlas_core/procesamiento_masivo.py`, `tests/test_procesamiento_masivo.py`) y 3 rutas nuevas (`atlas_core/ocr_provider.py`, `atlas_core/paddleocr_worker.py`, `tests/test_ocr_provider.py`), más las 3 bitácoras/handoff. **Sin commit, sin push** — pendiente de revisión.

---

## 2026-08-10 — Bloque Fechas F2: recuperación OCR focal de FECHA DE EMISIÓN (cerrado, con gate de confianza)

**Rama:** `lector-mvp-guia-nueva` · **HEAD previo:** `61958f2718452916b4a8d6fc4807903067355c81 feat: agregar plausibilidad temporal a fechas`

### Contexto

Diagnóstico previo (mismo bloque de trabajo) sobre los 16 fallos de fecha de la muestra real concluyó: 0/16 atribuibles a `extraer_fecha`, todos originados en OCR/calidad de imagen; ~11/16 con probabilidad razonable de beneficiarse de una relectura focal (recorte + realce), reutilizando el mismo mecanismo ya en producción para número de transporte.

### Implementación

**`atlas_core/ocr.py`:**
- Extraído `_leer_region_focal(ruta_imagen, caja, lector, allowlist)`: mismo recorte con margen + 4 variantes (original, grises, ampliada 2x LANCZOS, ampliada 2x con contraste) que antes vivía hardcodeado dentro de `_leer_transporte_focal`.
- `_leer_transporte_focal` ahora delega en el helper con `ALLOWLIST_TRANSPORTE = "0123456789OoDdQqIl| .-"` (el mismo string de siempre) — **sin cambio funcional**, confirmado por test que compara ambas rutas byte a byte.
- `_leer_fecha_focal` nuevo, delega en el mismo helper con `ALLOWLIST_FECHA = "0123456789-/ "` — solo dígitos, separadores de fecha y espacio; sin letras de confusión (no se justificaban para este caso).

**`atlas_core/extractor.py`:**
- `_extraer_fecha_geometrico(bloques)` nuevo, mismo patrón que `_extraer_transporte_geometrico`: localiza la etiqueta `FECHA DE EMISION` (tolerante a "FECHA EMISION" / "EMISION" sola por fragmentación de bloques), puntúa candidatos a la derecha/abajo, excluye candidatos más cercanos a una etiqueta rival (`FECHA SALIDA`/`FECHA LLEGADA`/"SALIDA"/"LLEGADA"), y se abstiene (devuelve `{}`) ante ambigüedad (margen 0.06, igual que transporte). Devuelve `{valor, caja, confianza}` — no valida el contenido, solo localiza la zona a recortar.

**`atlas_core/procesamiento_masivo.py`:**
- `_valor_fecha_a_date(valor)` nuevo: convierte un valor ya devuelto por `extraer_fecha` a `date` comparable (soporta DD-MM-YYYY, DD/MM/YYYY, YYYY-MM-DD, YYYY/MM/DD), solo para comparar variantes focales entre sí — no reimplementa ni toca el reconocimiento de `extraer_fecha`.
- `procesar_archivo`: se calcula `fecha_actual = extraer_fecha(textos, ...)` una vez; si ya es distinta de `"No encontrado"` se conserva tal cual y **la ruta focal nunca se ejecuta**. Si es `"No encontrado"`: reutiliza `bloques_guia` si ya se cargó (o lo carga), llama `_extraer_fecha_geometrico`; si no hay caja, se abstiene; si hay caja, ejecuta `_leer_fecha_focal` (4 variantes) y corre `extraer_fecha` (sin tocar sus regex) sobre el texto de cada variante — F1 (guarda de plausibilidad) se aplica automáticamente en cada una de esas llamadas, sin código adicional. Cualquier recuperación focal marca `fecha_recuperada_focal = True`, que se suma a `requiere_revision` (mismo criterio que las demás recuperaciones geométricas/focales del archivo).

**Sin cambios:** regex de `extraer_fecha`, `validar_fecha`, `_clasificar_contexto_fecha`, criterio de selección `min()`, guarda de plausibilidad de F1 (se reutiliza tal cual).

### Auditoría de consenso (F2.1/F2.2, previa al cierre)

La primera versión del consenso agrupaba resultados válidos por fecha comparable y aceptaba con solo `len(votos) >= 2`, sin mirar confianza. Validación real sobre las 30 guías con esa versión: 14/30 → 15/30, pero **1 de las 2 convergencias fue un valor incorrecto** (`IMG-20250930-WA0046.jpg`: 3 de 4 variantes —`original`, `grises`, `ampliada_2x`— coincidieron en `10-09-2025`, dígito de día mal leído; real: `2025-09-30`).

Se auditó el campo `confianza` que `_leer_region_focal` ya calculaba pero el consenso ignoraba (mínimo de las confianzas de los segmentos detectados por variante, metodología ya existente en el código, no inventada para esta auditoría), sobre las 7 imágenes reales donde el localizador geométrico encontró caja:
- Votos del consenso **incorrecto** (`WA0046`): confianzas 0.818 / 0.825 / 0.466 → mínima 0.466.
- Votos del único consenso **correcto** (`WA0047`, `30-09-2025`): confianzas 0.953 / 0.981 → mínima 0.953.
- Margen amplio entre ambos (0.47–0.95): cualquier umbral en ese rango separa los dos casos observados.

### Cambio de cierre: gate de confianza

- Constante nueva `CONFIANZA_MINIMA_FECHA_FOCAL = 0.70`, documentada junto a las constantes de F1, con nota explícita de que está validada sobre muestra limitada y no prueba suficiencia general del OCR.
- El agrupamiento por fecha comparable ahora guarda `(valor, confianza)` por voto. `coincidencias` solo incluye un grupo de fecha si `len(votos) >= 2` **y** `all(confianza >= CONFIANZA_MINIMA_FECHA_FOCAL for cada voto del grupo)` — un voto con confianza `None` (sin segmentos detectados) no puede satisfacer el umbral, así que nunca aporta a un consenso aceptado. Se acepta solo si exactamente un grupo de fecha cumple ambas condiciones.
- Nada más del flujo cambió: no se tocaron regex de `extraer_fecha`, F1, ni cuándo se dispara el focal.

### Tests

- `tests/test_extraer_datos.py` (7 nuevos, del F2 original): candidato a la derecha, candidato debajo, etiqueta ausente, sin candidato, dos candidatos equivalentes → abstención, prioriza EMISIÓN sobre SALIDA cercana, rechaza candidato más cercano a SALIDA que a EMISIÓN.
- `tests/test_ocr.py` (3 nuevos, del F2 original): `_leer_transporte_focal` conserva su allowlist exacto sin cambios; el helper genérico reproduce byte a byte el comportamiento de transporte; `_leer_fecha_focal` usa el allowlist mínimo (incluye `/`, sin letras).
- `tests/test_procesamiento_masivo.py` (7 nuevos en total): fecha global válida → focal nunca se dispara; 2 votos con ambas confianzas ≥0.70 → acepta; **3 votos coincidentes donde uno tiene confianza <0.70 (reproduce `WA0046`) → abstiene**; 2 votos con confianza exactamente 0.70 → acepta (límite inclusive); variantes discordantes → sigue "No encontrado"; candidato focal con año absurdo → descartado por F1 automáticamente; sin caja geométrica → se abstiene sin llamar al focal.
- 2 tests preexistentes (no relacionados con fecha) ajustaron su dato de entrada: usaban `leer_texto_imagen` → `[]`, lo que ahora también deja la fecha en "No encontrado" y dispara la nueva ruta focal — se les agregó una fecha global válida en el texto simulado para preservar su intención original (probar preservación de valores lineales, no fecha).

### Validación final

- Tests específicos del bloque: 7 (procesamiento_masivo) + 7 (extractor) + 3 (ocr) = 17 nuevos en total, todos verdes.
- Suite completa: `441 → 458 passed`.
- Validación real sobre las 30 guías, **OCR ejecutado de nuevo** (dos veces: antes y después del gate de confianza, ninguna reutilizó corpus anterior), llamando a `procesar_archivo` de producción real:
  - Exactitud: **14/30 → 15/30**.
  - Recuperado: `IMG-20250930-WA0047.jpg` → `30-09-2025` (correcto).
  - `IMG-20250930-WA0046.jpg`: ahora `"No encontrado"` (antes era el valor incorrecto `10-09-2025`) — el gate de confianza lo descartó correctamente.
  - **0 recuperaciones incorrectas nuevas. 0 degradaciones de los 14 aciertos previos.**
  - Focal disparado: 7/16 fallos previos (sin cambio, el gate no afecta cuándo se dispara). Convergieron: 1 (antes 2). Se abstuvieron: 6 (antes 5).
  - Tiempo total de la corrida final: 1385.5 s (~23.1 min) para 30 imágenes, pipeline completo de `procesar_archivo` (no solo fecha).

### Estado de cierre

`git status` previo al commit: working tree con 6 rutas de código/tests modificadas (`atlas_core/extractor.py`, `atlas_core/ocr.py`, `atlas_core/procesamiento_masivo.py`, `tests/test_extraer_datos.py`, `tests/test_ocr.py`, `tests/test_procesamiento_masivo.py`) más las 3 bitácoras/handoff.

---

## 2026-08-10 — Bloque Fechas F1: guarda de plausibilidad temporal

**Rama:** `lector-mvp-guia-nueva` · **HEAD previo:** `cab3837 feat: integrar matching difuso conservador de chofer`

### Contexto

Diagnóstico previo (mismo bloque de trabajo) midió el comportamiento real de `extraer_fecha` sobre la muestra histórica de 30 guías (`Atlas\datos_privados\muestra_fechas_30`, ground truth en `Atlas\datos_privados\ground_truth\validacion_atlas_30_guias_v1.xlsx`), ejecutando OCR real (EasyOCR) + `extraer_fecha` sin modificar código: **14/30 exactas**. Búsqueda del texto real en el OCR crudo de los 16 fallos confirmó que en **0 de 16** casos el extractor perdió un candidato correcto disponible — los 16 fallos nacen antes del extractor, en el OCR/calidad de imagen. De esos 16, 3 devolvían un valor con año calendario-imposible en la práctica (`7029`, `7025`, `1024`), aceptado porque `extraer_fecha` no acota el año cuando no se entrega rango explícito.

### Implementación

**`atlas_core/procesamiento_masivo.py`:**
- Constantes nuevas: `ANIO_MINIMO_PLAUSIBLE = 2015`, `ANIO_MAXIMO_PLAUSIBLE = 2035`, `FECHA_MINIMA_PLAUSIBLE`, `FECHA_MAXIMA_PLAUSIBLE`. Centralizadas como constantes de módulo, no hardcodeadas dentro de los regex de `extraer_fecha`.
- Función nueva `_limites_temporales_efectivos(fecha_desde, fecha_hasta) -> tuple[date, date]`: si un límite viene `None`, se completa con la guarda por defecto; si viene explícito, se usa tal cual. **Un límite explícito prevalece por completo sobre el default — no se intersecta con él** (un `fecha_desde`/`fecha_hasta` explícito más amplio que 2015–2035 sigue aceptando años fuera de ese rango).
- `extraer_fecha` calcula `fecha_desde_efectiva`/`fecha_hasta_efectiva` una sola vez al inicio y las usa en ambas pasadas (estricta y tolerante), reemplazando los chequeos `is not None` dispersos por una sola comparación contra los límites ya resueltos.
- Sin cambios en: regex de reconocimiento, `_clasificar_contexto_fecha` (prioridad EMISIÓN>SALIDA>LLEGADA), `_normalizaciones_fecha_unicas`, criterio de selección `min()`, contrato de retorno (sigue devolviendo el valor original, no ISO).

**`tests/test_procesamiento_masivo.py`:**
- Actualizados intencionalmente (comportamiento cambiado a propósito, no regresión):
  - `test_fecha_sin_rango_conserva_comportamiento_de_etapa_uno` → renombrado `test_fecha_sin_rango_descarta_anio_operacionalmente_absurdo`; `extraer_fecha(["FECHA DE EMISIÓN 01-07-7025"])` pasa de esperar `"01-07-7025"` a esperar `"No encontrado"`.
  - `test_procesar_archivo_sin_rango_conserva_compatibilidad` → renombrado `test_procesar_archivo_sin_rango_descarta_anio_operacionalmente_absurdo`; mismo cambio de expectativa vía `procesar_archivo`.
- Tests nuevos (8):
  - `test_fecha_sin_rango_acepta_anio_normal_de_la_muestra` — fecha típica 2025-2026 sin rango sigue aceptándose.
  - `test_fecha_sin_rango_limite_inferior_plausible_es_aceptado` — año 2015 exacto (límite inferior) se acepta.
  - `test_fecha_sin_rango_limite_superior_plausible_es_aceptado` — año 2035 exacto (límite superior) se acepta.
  - `test_fecha_sin_rango_anio_fuera_del_rango_plausible_se_descarta` (parametrizado: 2014 y 2036) — un año fuera del rango por defecto se descarta.
  - `test_fecha_con_rango_explicito_mas_amplio_que_el_default_prevalece` — rango explícito 1990–2099 acepta año 2040, fuera del default; confirma que el explícito no se intersecta con el default.
  - `test_fecha_con_rango_explicito_mas_estrecho_que_el_default_prevalece` — rango explícito más angosto que el default sigue mandando.
  - `test_fecha_sin_rango_candidato_absurdo_y_plausible_elige_el_plausible` — dos candidatos en el mismo texto, uno con año absurdo y otro plausible; se elige el plausible.

### Validación

- `python -m pytest -q` dirigido a los tests del bloque: **12 passed**.
- `python -m pytest -q` suite completa: **433 → 441 passed** (8 tests nuevos, 0 tests rotos fuera de los 2 actualizados intencionalmente).
- Validación sobre las 30 guías reales: se reutilizó el texto OCR ya capturado en la corrida de diagnóstico (mismas imágenes, mismo motor EasyOCR, sin recalcular OCR) y se re-ejecutó únicamente `extraer_fecha` con el código nuevo:
  - Exactitud: **14/30 antes → 14/30 después** (sin cambio).
  - Degradaciones (acierto que pasa a fallo): **0**.
  - Casos que cambiaron de fecha falsa silenciosa a `"No encontrado"`: **3** — `IMG-20250625-WA0039.jpg` (`15-06-7029`→`No encontrado`), `IMG-20250626-WA0019.jpg` (`28-06-7025`→`No encontrado`), `IMG-20250701-WA0007.jpg` (`01-07-1024`→`No encontrado`).
  - Los 27 resultados restantes (14 aciertos + 13 fallas por OCR degradado) quedaron valor por valor idénticos.

### Estado de cierre

`git status`: `lector-mvp-guia-nueva`, sincronizado con `origin`, working tree con exactamente 5 rutas modificadas/nuevas: `atlas_core/procesamiento_masivo.py`, `tests/test_procesamiento_masivo.py`, `docs/BITACORA_EJECUTIVA.md`, `docs/BITACORA_TECNICA_CRONOLOGICA.md`, `docs/HANDOFF_ATLAS.md`.
