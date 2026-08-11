# Bitácora Ejecutiva — Proyecto Atlas

Registro de alto nivel de los bloques de trabajo cerrados sobre el lector de guías. Un párrafo por bloque, orientado a decisión y estado, no a implementación.

---

## 2026-08-11 — PLANTA-P1: resolución real de planta origen (CERRADO)

- **Objetivo:** el bloque anterior (RUTAS R1) dejó la integración de rutas lista pero sin forma automática de saber si un viaje salió de AZA RENCA o AZA COLINA. Este bloque resuelve eso.
- **Onelogis histórico — auditoría técnica exhaustiva + aclaración de Javier:** Javier confirmó que, entrando manualmente a su cuenta Onelogis, sí puede ver histórico de viajes y recorridos — **la plataforma Onelogis tiene esa capacidad**. Lo que se auditó y confirmó es que **la integración técnica actual de Atlas** (`gps_logic.js`/`main.js`, vía un endpoint propio de Atlas) solo expone la última posición conocida; no hay ningún endpoint histórico configurado ni documentado en el código, backup o búsqueda pública. No se pudo identificar de forma segura un endpoint histórico accesible con la configuración actual (se descartó automatizar navegador o adivinar rutas contra el sistema en vivo, por instrucción explícita). Queda como gestión pendiente que solo Javier puede resolver (revisar configuración/documentación de su cuenta Onelogis).
- **Fallback documental adaptado y activado:** se recuperó y adaptó `_resolver_origen_documental` (rama remota no fusionada `origin/feature-cobertura-origen-fase1`, validado 7/9 en guías reales, 0 falsos positivos conocidos) para trabajar sobre el texto OCR de página completa que ya produce PaddleOCR — más simple y robusto que el original, que dependía de una relectura focal atada a EasyOCR.
- **Jerarquía implementada:** GPS (si hay evidencia) → documento (si el GPS no alcanza) → `ORIGEN_NO_DETERMINADO`. Ante conflicto, el GPS siempre gana — nunca se promedia ni se elige por conveniencia.
- **Validación real:** 12 guías reales de AZA disponibles hoy (el set histórico original de 9 no está accesible como archivo en este equipo) — **11/12 resueltas correctamente a AZA RENCA por documento, 1/12 se abstuvo de forma segura (0 asignaciones incorrectas)**. Conectado a ORS real: AZA RENCA→Torres Ocaranza (16.68 km/24.53 min) y AZA COLINA→Prodalam SA (41.31 km/47.35 min), ambas con caché confirmado.
- **Corrección de catálogo:** se completaron las coordenadas de AZA COLINA en `plantas.json` (faltaban desde antes de este bloque), reutilizando una coordenada ya geocodificada — con respaldo previo.
- Validación automatizada: **629 tests**, todos verdes (618 → 629). 0 regresiones.
- **Conclusión de estrategia: DOCUMENTAL_PRINCIPAL_GPS_TIEMPO_REAL.**
- **Atlas ya puede calcular km/min automáticamente para la mayoría de guías reales de AZA RENCA** (mecanismo documental validado). Sigue pendiente: confirmar con Onelogis el acceso histórico (mejoraría cobertura y dependería menos del encabezado de la guía) y ampliar la validación a más casos reales de AZA COLINA.

---

## 2026-08-11 — RUTAS R1: km/tiempos conectados al viaje + auditoría Onelogis (CERRADO)

- **Objetivo:** conectar el módulo de rutas (ya validado con ORS real) al flujo de viajes: destino canónico → planta de origen → ORS → campos en el reporte, sin inventar ningún origen.
- **Auditoría Onelogis (Paso 1, hallazgo clave):** Onelogis **sí** está integrado en Atlas, pero solo del lado Desktop (`Atlas-Viajes-Desktop-Restaurado/src/gps_logic.js` + `main.js`), vía un endpoint propio que expone exclusivamente la **última posición conocida** de cada patente (`estado`, `latitude`, `longitud`, `speed`, `timestamp`) — no existe ningún endpoint ni registro histórico consultable por fecha/hora en toda la integración actual. Por diseño, esto significa que **hoy no es posible determinar retroactivamente** en qué planta estaba un camión al momento de una guía ya procesada; solo sería viable para guías procesadas en tiempo real. La documentación del propio proyecto (`CATALOGO_TRANSPORTISTAS_ATLAS.md`) ya señala que ampliar la integración Onelogis requiere autorización y auditoría de privacidad aparte.
- **Arquitectura implementada:** nuevo contrato `ProveedorPosicionVehiculo` + resolución por geocerca (Haversine, radio conservador 1.5 km, sin ambigüedad entre AZA Renca/Colina) + resolución de destino canónico reutilizando `CatalogoDestinos` (ya existente, sin duplicar lógica) contra `destinos_maestros.json`, con exclusión general (por rango geográfico plausible, no por nombre) de los registros con coordenada errónea detectados en RUTAS-EVAL R1. Todo conectado a `ServicioRutas`/`RepositorioRutas` ya validados con ORS real.
- **Validación real (catálogo activo real, ORS real, `driving-hgv`):** 3 viajes reales probados. EBEMA SA correctamente bloqueado por una salvaguarda ya existente (destino aún no `CONFIRMADO` en catálogo — no se fuerza nada). Torres Ocaranza Ltda (destino `CONFIRMADO`): planta AZA RENCA (determinada por posición GPS **inyectada/simulada**, ya que no existe consulta histórica real hoy) → **16.68 km / 24.53 min**, y una repetición del mismo par confirma **caché activo, 0 llamadas nuevas a ORS**. Un tercer caso sin evidencia GPS se abstiene correctamente (`ORIGEN_NO_DETERMINADO`) sin invalidar el viaje.
- Campos propagados a `viajes.csv` de forma **100% backward-compatible** (columnas nuevas al final, vacías por defecto sin el nuevo parámetro opcional).
- Validación automatizada: **618 tests**, todos verdes (603 → 618). 0 regresiones.
- **Bloqueo real remanente:** no hay hoy una fuente de posición GPS histórica utilizable para guías ya procesadas. **Siguiente bloque obligatorio antes de mostrar km automáticos en Desktop: PLANTA-P1 / ONELOGIS** — confirmar con Onelogis si existe (o puede habilitarse) un endpoint histórico, o definir una estrategia alternativa de origen documental.

---

## 2026-08-11 — ORS: migración de endpoint + validación real con credencial (CERRADO)

- **Objetivo:** activar la integración real de OpenRouteService (bloqueada desde RUTAS-EVAL R1 por falta de credencial) y confirmar que el adaptador apunta al host vigente.
- **Hallazgo crítico de plazo:** `api.openrouteservice.org` (host usado por el adaptador) está deprecado por HeiGIT desde el 28-abr-2026, con **apagado definitivo el 24-ago-2026** — a 13 días al momento de este bloque. Confirmado contra el anuncio oficial y verificado en vivo (ambos hosts responden 401 sin credencial, es decir la ruta existe). Se migró el adaptador (`atlas_core/rutas/openrouteservice.py`) al host vigente `api.heigit.org`, de forma centralizada (solo 2 constantes), sin cambio de credencial ni de contrato.
- **`OPENROUTESERVICE_API_KEY` configurada** como variable de entorno de **usuario** de Windows en este PC, por el propio Javier, en su terminal, fuera de cualquier canal visible para Claude — nunca fue pegada, mostrada, registrada ni escrita en ningún archivo del repo.
- **Validación real con credencial real:** prueba mínima (`driving-hgv`) exitosa; 3 rutas reales calculadas AZA RENCA/AZA COLINA → EBEMA SA (Galvarino 8501), TORRES OCARANZA LTDA, DSI UNDERGROUND CHILE SPA — todas `RUTA_CALCULADA`, tiempos de respuesta ~0.8-1.0s. Caché (`RepositorioRutas`) verificado: segunda consulta del mismo par usa el resultado guardado y **no** vuelve a llamar a ORS.
- Validación automatizada: **603 tests**, todos verdes (601 → 603, 2 nuevos fijando el endpoint vigente).
- **0 secretos en git** — confirmado antes de commitear.
- **Siguiente bloque:** integrar km/tiempos en el flujo real de Desktop (explícitamente fuera de alcance de este bloque).

---

## 2026-08-11 — Bloque D1: separar GIRO de obra_destino (CERRADO)

- **Objetivo:** con cliente/chofer/RUT ya corregidos en C1, `obra_destino` seguía devolviendo el valor de **GIRO** (`"VENTA AL POR MAYOR D"`) en vez del destino real (`"SUPERMERCADO SEÑOR DE LOS MI"`) en la guía real `464170` — prerrequisito directo del próximo frente de rutas/KM/tiempos, que necesita un destino confiable.
- **Causa exacta:** dos colisiones combinadas en `_extraer_asociaciones_geometricas`. (1) La lista de exclusión de candidatos rechazaba por subcadena cualquier texto que contuviera la palabra "SEÑOR" — el propio nombre real del destino ("SUPERMERCADO SEÑOR DE LOS MI") quedaba descartado como candidato. (2) Sin ese candidato, el único bloque que sobraba cerca de la etiqueta OBRA DESTINO era el valor de GIRO, en la columna vecina de la misma fila (patrón de formulario en dos columnas), y sin ninguna regla que lo excluyera explícitamente, terminaba ganando por ser la única opción.
- **Corrección, general y sin heurísticas de archivo:** (1) el candidato ya no se descarta por contener la palabra suelta "SEÑOR" — solo se descarta si el bloque completo *es* la etiqueta SEÑOR(ES) (mismo criterio conservador que ya usa C1 para la etiqueta); (2) GIRO queda estructuralmente inelegible como obra/destino: se identifica por identidad cuál sería el propio valor de GIRO y se excluye de competir por cualquier otro campo, sin depender de comparar distancias (frágil cuando GIRO y el destino real son columnas vecinas casi equidistantes).
- **Hallazgo colateral corregido:** al validar con coordenadas reales exactas se detectó que `_extraer_rut_cliente_geometrico` (Parte D de C1) nunca llegaba a activarse en producción — su ancla exigía una separación positiva estricta entre las etiquetas SEÑOR(ES) y R.U.T., pero en el documento real esas cajas quedan exactamente adyacentes (gap cero). Corregido a `>=` inclusive del gap cero; confirmado con las cajas reales completas.
- **Catálogo:** el destino real de EBEMA SA (dirección `GALVARINO 8501, QUILICURA`, ya geocodificada) existe en `destinos_maestros.json`, vinculado por `cliente_id` — pero solo se reportó, no se conectó una homologación nueva por esa vía (fuera de alcance de D1; el enriquecimiento existente por código de destinatario contra `destinos.json` sigue funcionando igual, sin fabricar nada).
- **Caso real validado, guía `464170`:** `obra_destino` pasa de `"VENTA AL POR MAYOR D"` a `"SUPERMERCADO SEÑOR DE LOS MI"`; `cliente=EBEMA SA`, `chofer=IVAN ROA`, `rut_chofer=10190440-7` sin cambios.
- **Validación adicional corta (4 guías reales con destino ya conocido: `464511`, `464493`, `464479`, `464494`):** resultados idénticos antes/después en cliente, obra_destino, chofer e indicador_revision — 0 regresiones.
- Validación automatizada: **601 tests**, todos verdes (594 → 601). 0 regresiones.
- **Siguiente bloque oficial: RUTAS-EVAL / RUTAS R1** — comparación corta de proveedores y recuperación de infraestructura de km/tiempos. No iniciado.

---

## 2026-08-11 — Bloque C1: cliente + chofer nuevo + propagación de REVISAR al viaje (CERRADO)

- **Objetivo:** la guía real `464170` mostraba `cliente` vacío y chofer `NO HOMOLOGADO` pese a que PaddleOCR leía ambos campos correctamente (`SEÑOR(ES): EBEMA SA`, `RETIRA: IVAN ROA`, `RUT CHOFER: 10190440-7`); el viaje además quedaba `CONFIRMADO` en silencio con esos vacíos. C1 corrige las causas generales (sin heurísticas de archivo) y cierra el ciclo end-to-end.
- **Causas corregidas, todas genéricas:** (1) la normalización de texto usada por `buscar_cliente`/obra destino no convertía Ñ→N — centralizada ahora en un único helper; (2) la etiqueta geométrica `SEÑOR(ES)` matcheaba por subcadena y confundía nombres de destino que contienen la palabra "SEÑOR" (caso real: "SUPERMERCADO SEÑOR DE LOS MI") — ahora exige que el bloque completo sea la etiqueta; (3) nueva extracción **genérica** de RUT cliente por geometría (zona SEÑOR(ES)/R.U.T.), validada contra RUT chileno real, sin hardcodear ningún cliente; (4) el buscador de RUT chofer no toleraba el `:` que Paddle deja pegado al valor; (5) `agrupar_viajes()` ahora respeta el `indicador_revision` de cada documento además de los conflictos entre documentos que ya detectaba — un transporte de un único documento marcado `REVISAR` ya no puede quedar `CONFIRMADO` en silencio.
- **IVAN ROA (RUT 10190440-7)** se dio de alta como chofer canónico real — confirmado por Javier como chofer nuevo real, no alias de otro — en el catálogo **activo real** (`%LOCALAPPDATA%\Atlas\datos\catalogos_privados\choferes.json`, identificado vía el config del Desktop instalado, no una carpeta de respaldo). Respaldo previo íntegro del catálogo en `Desktop\Atlas\backups_catalogos\`.
- **Caso real validado end-to-end** (guía `464170`, PaddleOCR GPU, catálogo activo real): `cliente = EBEMA SA`, `rut_cliente = 83.585.400-0`, `chofer = IVAN ROA` (homologado exacto), `rut_chofer = 10190440-7`. El viaje queda `REQUIERE_REVISION` (motivo `DOCUMENTO_REQUIERE_REVISION`) — correcto: el documento siguió necesitando recuperación geométrica, señal conservadora ya existente que no se relajó.
- Validación automatizada: **594 tests**, todos verdes (581 → 594). **0 regresiones.**
- **Pendiente conocido, no bloqueante:** `obra_destino` sigue resolviendo mal (`"VENTA AL POR MAYOR D"`, valor de GIRO, en vez de `"SUPERMERCADO SEÑOR DE LOS MI"`).
- **Siguiente bloque oficial: DESTINO D1** — corregir `obra_destino`/GIRO, prerrequisito directo de rutas/KM/tiempos. No iniciado.

---

## 2026-08-10 — Bloque Patentes P2: homologación conservadora contra catálogo de vehículos (CERRADO)

- **Objetivo:** P1 ya recuperaba el valor OCR de la patente (p. ej. `SD6486`), pero no resolvía su identidad canónica cuando el OCR confunde una letra. P2 homologa esa patente contra el catálogo canónico de vehículos, de forma conservadora y sin tocar OCR/Paddle.
- **Jerarquía de resolución:** (1) coincidencia exacta normalizada contra el catálogo; (2) alias explícito declarado en el registro del vehículo; (3) corrección OCR conservadora, aceptada **solo** si existe un único candidato de catálogo, con la misma longitud, y una única diferencia posicional explicada por una confusión OCR común y documentada (B/D, 0/O, 1/I, 5/S, 8/B). Nunca se crea una patente nueva.
- **Caso real obligatorio confirmado, guía `464511`:** `patente_tracto` pasa de `SD6486` (valor OCR) a `SB6486` (canónico), porque el catálogo real contiene `SB6486` como único candidato seguro a una diferencia OCR de `SD6486`. **La corrección `SD6486 → SB6486` no está hardcodeada por archivo**: surge únicamente de aplicar la jerarquía general contra el catálogo real. `patente_rampla` (`JF4288`) es coincidencia exacta y se preserva sin cambios.
- **Política de abstención:** ante dos candidatos igualmente plausibles (ambigüedad), o dos o más diferencias entre el valor OCR y un candidato, la patente se conserva sin corregir y el documento se marca `REVISAR`. Sin catálogo disponible, no se inventa ni se intenta corregir nada.
- **PaddleOCR, Desktop y generación de reportes no se tocaron.** La homologación vive en `procesar_archivo`, el único punto de propagación; Desktop y reportes reciben el valor homologado automáticamente sin cambios propios.
- Validación automatizada: **581 tests**, todos verdes (566 → 581).
- **Frente de patentes queda cerrado** con P1 (recuperación geométrica) + P2 (homologación canónica). No hay un próximo microbloque de patentes definido todavía.

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
