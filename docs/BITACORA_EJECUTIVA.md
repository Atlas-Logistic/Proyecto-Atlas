# Bitácora Ejecutiva — Proyecto Atlas

Registro de alto nivel de los bloques de trabajo cerrados sobre el lector de guías. Un párrafo por bloque, orientado a decisión y estado, no a implementación.

---

## 2026-08-10 — Bloque Patentes P1: recuperación geométrica de patentes compatible con Paddle (CERRADO)

- **Problema real confirmado:** `buscar_chofer_y_patentes()` exigía la frase contigua `"RETIRA PATENTE FECHA LLEGADA"` en el texto OCR; PaddleOCR reparte esas etiquetas en bloques/líneas separados, por lo que `patente_tracto`/`patente_carro` volvían `"No encontrado"` aunque el valor estuviera presente en el OCR.
- **Solución:** se agregó `_extraer_patentes_geometrico`, una nueva función geométrica (mismo patrón ya usado para chofer/transporte/fecha) que ancla la búsqueda en la zona RETIRA–FECHA LLEGADA por coordenadas, sin depender de la frase contigua. Se activa solo como *fallback*, cuando la lectura lineal ya devolvió "No encontrado". **PaddleOCR no se tocó.**
- **Camino histórico EasyOCR preservado:** `buscar_chofer_y_patentes()` (lectura lineal por frase contigua) no se modificó; sigue siendo la vía primaria y sigue funcionando igual que antes.
- **Alcance deliberadamente acotado:** P1 solo recupera el valor OCR disponible, no lo corrige. La guía real `464511` expone esto con claridad: Paddle lee la patente del tracto como `SD6486` (una B real leída como D); P1 recupera ese valor tal cual, no lo corrige a `SB6486` — esa homologación queda para un microbloque posterior.
- **Resultado real, guía `464511`:** `patente_tracto` pasa de `"No encontrado"` a `SD6486`; `patente_rampla` pasa de `"No encontrado"` a `JF4288` (correcto). Resto de campos sin cambios. **0 regresiones** (confirmado comparando el mismo procesamiento real antes/después del cambio).
- Validación automatizada: **566 tests**, todos verdes (556 → 566).
- No se tocó Desktop ni la generación de reportes: `procesar_archivo` es el único punto de propagación, así que Desktop y reportes reciben el valor recuperado automáticamente sin cambios propios.
- **Siguiente microbloque pendiente:** homologación de patente OCR contra catálogo de vehículos (ejemplo `SD6486 → SB6486`), sin alterar el OCR. No iniciado.

---

## 2026-08-10 — Integración Desktop ↔ Motor Paddle restaurada y validada

- Se restauró el contrato histórico de integración utilizado por Atlas Viajes Desktop: `analizar_guias_masivo.py` vuelve a aceptar `--catalogos <ruta>` y valida explícitamente la fuente privada canónica antes de procesar. También admite `ATLAS_CATALOGOS_DIR`; los archivos `*.example.json` nunca se aceptan silenciosamente como producción.
- `procesar_carpeta` propaga la fuente validada hasta `procesar_archivo` y la resolución canónica de clientes/choferes, conservando intacta la arquitectura M2: PaddleOCR sigue siendo el proveedor principal, con GPU automática en este PC, un único proveedor reutilizado por lote y EasyOCR como fallback.
- Se recuperó `resumen_procesamiento_desktop.py` desde la historia real del proyecto y se verificó que coincide con el blob histórico validado. También se recuperaron `generar_reporte_viajes.py` y sus dependencias originales de agrupación/publicación de viajes.
- Validación automatizada final: **556 tests**, todos verdes.
- Validación manual end-to-end confirmada en Atlas Viajes 1.4.3: al arrastrar la guía real `464511`, Desktop ejecutó el motor con PaddleOCR GPU, produjo transporte `0000352449`, fecha `10-08-2026`, cliente `ARMACERO MATCO SA` y chofer `RODRIGO NAHUELÑIR`; el viaje apareció correctamente en la UI con estado OK.
- **Siguiente frente Desktop:** recuperación de UX histórica. No corresponde introducir nuevos cambios del motor en ese bloque. Antes de asumir perdido cualquier elemento histórico, revisar `G:\Mi unidad\BACKUP_PRE_FORMATEO_20260808`.

---

## 2026-08-10 — Bloque M2: runtime Paddle portable + activación en flujo batch

- El runtime de PaddleOCR ya no depende de ninguna ruta de este PC: se resuelve en `%LOCALAPPDATA%\Atlas\runtime\paddleocr` (portable, sin nombre de usuario ni Desktop hardcodeados), con posibilidad de override explícito por variable de entorno para desarrollo.
- Se agregó un mecanismo de bootstrap que crea/valida ese runtime automáticamente: no reinstala si ya existe y coincide con las versiones fijadas (`paddleocr==3.7.0`, `paddlepaddle`/`paddlepaddle-gpu==3.3.1`), elige build GPU o CPU según haya o no una NVIDIA disponible, y aplica el workaround de CPU ya conocido. No modifica drivers del sistema.
- **`procesar_carpeta` (el flujo real de lote/CLI) ya construye y usa un proveedor OCR por defecto** — antes de este bloque, la integración de PaddleOCR existía como capacidad pero no se activaba en el camino real de procesamiento masivo. Ahora sí: un solo proveedor por ejecución, reutilizado para todo el lote, sin recargar el modelo por imagen.
- **Validado con el runtime real, recién creado desde cero** (bootstrap real, sin mocks, ~3.5 min) en la ubicación definitiva, y con una corrida corta real de la CLI sobre 4 guías reales: proveedor PaddleOCR con GPU seleccionada automáticamente, mensaje visible en consola, resultados coherentes (número de guía y fecha correctos en las 4).
- No se corrió otra vez el lote completo de 30 — la lógica de extracción ya se validó exhaustivamente en el bloque M1; este bloque solo cambiaba *cómo* se resuelve y activa el proveedor, no la lógica de extracción en sí.
- Suite completa verde: 482 → **501 tests**.
- **Hallazgo de rendimiento, no de corrección:** el primer uso del runtime recién creado fue notablemente más lento (~48 s/imagen) que corridas posteriores (~10.5 s/imagen) — consistente con sobrecarga de primer uso del sistema (antivirus escaneando binarios nuevos, cachés de disco fríos), no con un problema del código. Se re-ejecutó el mismo lote una segunda vez para confirmarlo.
- Sin commit ni push — pendiente de tu revisión.

---

## 2026-08-10 — Bloque M1: PaddleOCR integrado detrás de un proveedor OCR (CERRADO Y APROBADO)

- **Cierre aprobado.** PaddleOCR queda como **motor principal** de Atlas; EasyOCR queda como **fallback temporal** (no eliminado, se usa automáticamente si Paddle no está disponible).
- `IMG-20250930-WA0047.jpg` (número de guía) se registra como **discrepancia editorial de ground truth pendiente** — el propio Excel de validación documenta "410627" pero la imagen muestra "410267" — no se cuenta como fallo de Atlas.
- **Riesgo principal pendiente:** PaddleOCR depende hoy de un runtime externo en `C:\Users\Jjjc0508\Desktop\Atlas\ocr_eval_gpu_env`. Esa ruta es temporal, no es la arquitectura definitiva de despliegue — es el objetivo del próximo bloque.
- La validación de portabilidad en CPU (máquina sin GPU) se hará más adelante con una prueba corta en el PC de oficina — no bloqueó este cierre.
- **Próximo bloque oficial: M2 — runtime Paddle reproducible/portable** (no iniciado).

- Decisión ya tomada previamente (evaluación OCR-EVAL): PaddleOCR reemplaza a EasyOCR como motor principal. Este bloque es la primera implementación real, no una nueva evaluación.
- Se creó una abstracción de proveedor OCR (`ProveedorOCR`) de la que depende el resto de Atlas — ya no hay ningún llamado directo a `easyocr.Reader` fuera de `EasyOCRProvider`. PaddleOCR corre en un **proceso completamente aislado** (venv externo, fuera del entorno principal de Atlas) para no mezclar sus ~55 dependencias con las de Atlas; se comunica por un protocolo simple, sin acoplar el resto del código a los detalles de ese aislamiento.
- Selección de dispositivo automática: usa GPU NVIDIA si hay una disponible, si no cae a CPU con el workaround ya validado (`enable_mkldnn=False`). No hay ninguna GPU hardcodeada.
- EasyOCR **no se eliminó** — sigue siendo el comportamiento por defecto si no se pasa un proveedor, y es el fallback automático si PaddleOCR no está disponible (venv ausente, proceso no arranca, etc.).
- Se resolvieron las dos incompatibilidades diagnosticadas en el bloque de evaluación:
  1. **`numero_guia`** ya no depende de que "GUIA DE DESPACHO ELECTRONICA N°..." llegue como frase contigua — se conectó al mecanismo geométrico ancla→marcador→candidato que Atlas ya tenía (`decidir_bloques_ocr`), simplemente asegurando que reciba los bloques del proveedor activo. **Resultado real: 2/30 → 29/30** (el único caso restante es una disputa de ground truth ya documentada en el Excel original, no un error del algoritmo).
  2. La **recuperación focal** (fecha F2 y transporte) se generalizó para hablar con el proveedor activo en vez de llamar `lector.readtext()` específico de EasyOCR — sigue funcionando igual con ambos motores.
- Se agregó una guarda documental mínima: si muchos campos clave de un mismo documento vuelven vacíos a la vez, el documento completo queda marcado `REVISAR`, sin inventar ni corregir ningún valor. Confirmado: `IMG-20260512-WA0027.jpg` (el caso con fecha incorrecta detectado en la evaluación) queda `REVISAR`.
- **Resultado real sobre las 30 guías, con PaddleOCR real integrado (no simulado):** fecha 27/30, numero_guia 29/30, numero_transporte 28/30 (93.3%), cliente 21/25 (84.0%), obra_destino 12/27 (44.4%), chofer 15/23 (65.2%), descripción de material 24/25 (96.0%), tipo de carga 24/29 (82.8%) — todos consistentes con la evaluación previa, **sin regresiones**. Tiempo: 3.03 s/imagen (proceso persistente + GPU).
- Suite completa verde: 458 → **482 tests** (24 nuevos de este bloque).
- Pendiente para el próximo bloque: esto integra PaddleOCR como proveedor disponible y probado, pero **no cambia todavía el proveedor por defecto en producción** ni hace commit — eso queda para una decisión explícita posterior.

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
