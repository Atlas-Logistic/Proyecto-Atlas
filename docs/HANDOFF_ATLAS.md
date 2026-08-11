# Handoff — Proyecto Atlas

Estado de traspaso para quien retome el trabajo. Se actualiza al cierre de cada bloque.

---

## 2026-08-11 — Cierre: migración de endpoint ORS + validación real con credencial

- **Rama:** `lector-mvp-guia-nueva`. Baseline anterior: `ccc777229cbd072b1f89e5d60efbd5620859731a`.
- **Endpoint ORS migrado, URGENTE para quien retome esto:** `api.openrouteservice.org` se apaga el **24-ago-2026** (anuncio oficial HeiGIT, 28-abr-2026). El adaptador (`atlas_core/rutas/openrouteservice.py`) ahora usa `api.heigit.org`: direcciones en `/openrouteservice/v2/directions/{perfil}`, geocodificación migró de `/geocode/search` a la estructura Pelias `/pelias/v1/search`. Misma API key sirve para ambos hosts, sin cambio de credencial ni de contrato (`ProveedorRutas` intacto).
- **`OPENROUTESERVICE_API_KEY` ya está configurada** como variable de entorno de **usuario** de Windows en este PC (no de sistema, no en `.env` del repo). Configurada directamente por Javier en su propia terminal — el valor nunca pasó por Claude en ningún momento (ni se pidió pegarlo en el chat, ni se registró, ni se escribió en archivo alguno).
- **Nota técnica para quien retome esto:** una variable de entorno de **usuario** recién creada con `[Environment]::SetEnvironmentVariable(...,"User")` no se propaga automáticamente al bloque de entorno de un proceso/shell ya en ejecución (solo la ve `[Environment]::GetEnvironmentVariable(...,"User")`, que lee directo del registro). Para que un proceso hijo (p. ej. `python`) la vea vía `os.getenv(...)`, hace falta puentearla explícitamente en la misma invocación: `$env:OPENROUTESERVICE_API_KEY = [Environment]::GetEnvironmentVariable("OPENROUTESERVICE_API_KEY","User")` antes de lanzar el proceso — o reiniciar la sesión/terminal.
- **Validación real, con credencial real, perfil `driving-hgv`:**
  - Prueba mínima (AZA RENCA → EBEMA SA): `RUTA_CALCULADA` (no `SIN_CREDENCIAL`).
  - 3 rutas reales, coordenadas ya existentes en catálogo (sin geocodificar de nuevo): AZA_RENCA→EBEMA SA/Galvarino 8501 (7.43 km, 12.1 min), AZA_COLINA→Torres Ocaranza Ltda (49.70 km, 59.9 min), AZA_RENCA→DSI Underground Chile SpA (33.17 km, 40.4 min). Tiempos de respuesta 0.80-0.86s.
  - **Caché (`RepositorioRutas`) verificado end-to-end** vía `ServicioRutas.confirmar_y_calcular`: primera consulta AZA_RENCA→Torres Ocaranza → `RUTA_CALCULADA` (1 llamada real a ORS, contada con un wrapper de conteo, sin tocar el adaptador); segunda consulta idéntica → `RESULTADO_DESDE_CACHE`, **0 llamadas nuevas a ORS**, mismo `distancia_km`/`duracion_estimada_min` que la primera. Clave lógica confirmada: `planta_id + destino_id + perfil + proveedor + version`.
- Suite final: **603/603 tests** (601 → 603, 2 nuevos que fijan el host vigente y evitan una regresión silenciosa al host deprecado).
- **0 secretos en git** — el repo solo tiene el cambio de host (2 constantes) y los 2 tests nuevos; ningún archivo de credenciales, `.env` real, ni valor de clave fue tocado o creado dentro del repo.
- **Próximo bloque:** conectar km/tiempos al flujo real (Desktop, reportes) — explícitamente no iniciado en este bloque.

---

## 2026-08-11 — Cierre Bloque D1: separar GIRO de obra_destino

- **Rama:** `lector-mvp-guia-nueva`. Baseline anterior: `66d0edabbfd506795dc675f2149e4875dc6fede2`.
- **Objetivo cerrado:** `obra_destino` seguía devolviendo el valor de GIRO (`"VENTA AL POR MAYOR D"`) en la guía real `464170`, en vez del destino real (`"SUPERMERCADO SEÑOR DE LOS MI"`) — prerrequisito directo del próximo frente RUTAS/KM/TIEMPOS.
- **Causa exacta en `_extraer_asociaciones_geometricas` (`atlas_core/extractor.py`):** (1) `nominal()` rechazaba cualquier candidato que contuviera la subcadena "SEÑOR" — incluyendo el propio nombre real del destino, que casualmente contiene esa palabra; (2) sin ese candidato, GIRO (columna vecina, misma fila que OBRA DESTINO — patrón de formulario en dos columnas de este proveedor AZA) quedaba como única opción restante y ganaba por defecto, sin ninguna regla que lo excluyera.
- **Fix, general y sin heurísticas de guía:**
  - `nominal()` ya no descarta por subcadena "SEÑOR"; en su lugar descarta solo si el bloque completo *es* la etiqueta SEÑOR(ES) vía `_es_etiqueta_senor` (mismo criterio que C1 ya usa para la etiqueta, ahora aplicado también al lado del candidato).
  - Nueva identificación explícita de GIRO (`es_etiqueta_giro`) y de "cuál sería el propio valor de GIRO" (`_mejor_candidato`, misma función `puntuar` que usa el resto de la lógica): ese bloque queda excluido, por identidad, de competir como candidato de `obra_destino`. **Deliberadamente no se implementó por comparación de distancias** (primer intento, descartado): en este documento GIRO y OBRA DESTINO son columnas vecinas casi equidistantes de sus respectivos valores, y una comparación de distancia bruta puede perder por márgenes de 1-2 px — la exclusión por identidad es exacta y no depende de umbrales.
- **Bug colateral encontrado y corregido durante la validación con cajas reales exactas:** `_extraer_rut_cliente_geometrico` (C1, Parte D) nunca se activaba en producción real — exigía gap **estrictamente positivo** entre las etiquetas SEÑOR(ES) y R.U.T., pero PaddleOCR entrega esas dos filas con cajas exactamente adyacentes (gap 0) en este documento. El reporte de cierre de C1 afirmó erróneamente `rut_cliente = 83.585.400-0` como validado en el pipeline real — en realidad esa verificación se hizo solo con coordenadas de test redondeadas que evitaban el caso límite por casualidad, y el campo ni siquiera se expone en el dict que devuelve `procesar_archivo`. Corregido (`>` → `>=`) y confirmado ahora con las cajas reales completas.
- **Catálogo (solo inspección, sin conectar nada nuevo):** el destino real de EBEMA SA existe en `%LOCALAPPDATA%\Atlas\datos\catalogos_privados\destinos_maestros.json` — registro con `cliente_id` que coincide exactamente con el de EBEMA SA en `clientes.json`, dirección `GALVARINO 8501, QUILICURA, CHILE` ya geocodificada (lat/lon, `GEOCODIFICACION_ORS`, confidence 0.8, match_type=fallback). El nombre canónico ahí es la dirección, no "SUPERMERCADO SEÑOR DE LOS MI" — homologar por `cliente_id` cruzando catálogos es una integración nueva, fuera de alcance de D1; queda para RUTAS.
- **Caso real validado, guía `464170`, PaddleOCR GPU, catálogo activo real:** `obra_destino`: `"VENTA AL POR MAYOR D"` → **`"SUPERMERCADO SEÑOR DE LOS MI"`**. `cliente=EBEMA SA`, `chofer=IVAN ROA` (homologado), `rut_chofer=10190440-7` sin cambios respecto a C1.
- **Validación adicional corta (4 guías reales, destino ya conocido antes de este fix): `464511`, `464493`, `464479`, `464494`** — cliente/obra_destino/chofer/indicador_revision idénticos antes y después, 0 regresiones.
- Suite final: **601/601 tests** (594 → 601).
- **Próximo bloque oficial: RUTAS-EVAL / RUTAS R1** — comparación corta de proveedores y recuperación de infraestructura de km/tiempos, usando como insumo el destino ya recuperado por este bloque y la dirección canónica ya geocodificada encontrada en `destinos_maestros.json`. No iniciado.

---

## 2026-08-11 — Cierre Bloque C1: cliente + chofer nuevo + propagación de REVISAR al viaje

- **Rama:** `lector-mvp-guia-nueva`. Baseline anterior: `129b459d936d6d05ae0615cc93fa8842440f4d3a`.
- **Objetivo cerrado:** caso real guía `464170` — `cliente` vacío y chofer `NO HOMOLOGADO` con OCR correcto (`SEÑOR(ES): EBEMA SA`, `RETIRA: IVAN ROA`, `RUT CHOFER: 10190440-7`), viaje `CONFIRMADO` en silencio con esos campos vacíos. Diagnóstico previo ya cerrado; C1 corrige las causas.
- **Fuente de catálogos activa real, importante para quien retome esto:** NO es ninguna de las carpetas `Desktop\Atlas\Atlas-Viajes-*-Rollback-*` (son respaldos/snapshots). La fuente que el Desktop instalado usa de verdad está en `config_usuario.json` del electron-store (`%APPDATA%\atlas-viajes-desktop\config_usuario.json`, `modoCatalogos: OBLIGATORIO`) y apunta a `%LOCALAPPDATA%\Atlas\datos\catalogos_privados`. Ahí se hizo el alta de IVAN ROA, no en el repo.
- **Cambios en `atlas_core/extractor.py`:** `_normalizar_acentos()` centraliza Ñ→N (antes solo `_texto_simple` lo hacía; `texto_busqueda` de `extraer_datos` y `normalizar_cliente`/`normalizar_obra_destino` no); `_es_etiqueta_senor()` exige que el bloque completo (no una subcadena) sea la etiqueta SEÑOR(ES)/SEÑORES/SEÑOR(IES)/SEÑORIES, usado por `_extraer_asociaciones_geometricas`; nueva `_extraer_rut_cliente_geometrico()` (zona SEÑOR(ES)/R.U.T., valida con `validar_rut_chileno`, se abstiene ante ambigüedad); `buscar_rut_chofer()` ahora tolera `:` entre la etiqueta y el valor.
- **`atlas_core/procesamiento_masivo.py`:** `RUT del cliente` se agregó a `campos_ausentes` y se conecta `_extraer_rut_cliente_geometrico` como fallback, mismo patrón que cliente/obra/chofer/transporte/patentes.
- **`atlas_core/gestor_viajes.py`:** nuevo `MotivoRevision.DOCUMENTO_REQUIERE_REVISION` — si cualquier documento del viaje trae `indicador_revision=REVISAR`, el viaje no puede quedar `CONFIRMADO`, independiente de si hay o no contradicciones con otros documentos del mismo transporte (esos conflictos existentes se preservan intactos).
- **IVAN ROA dado de alta** en el catálogo activo real como chofer canónico (RUT `10190440-7`, sin alias — es nuevo real, confirmado por Javier). Respaldo íntegro previo en `Desktop\Atlas\backups_catalogos\20260811_063918_pre_alta_ivan_roa\`.
- **Caso real validado, guía `464170`, PaddleOCR GPU, catálogo activo real:**
  - Antes: `cliente=No encontrado`, `rut_cliente=No encontrado`, `chofer=IVAN ROA` (sin homologar), `rut_chofer=No encontrado`, viaje `CONFIRMADO` sin motivo.
  - Después: `cliente=EBEMA SA`, `rut_cliente=83.585.400-0`, `chofer=IVAN ROA` (homologado exacto contra catálogo), `rut_chofer=10190440-7`, viaje `REQUIERE_REVISION` (motivo `DOCUMENTO_REQUIERE_REVISION`, legítimo: el documento siguió necesitando recuperación geométrica).
- Suite final: **594/594 tests** (581 → 594). 0 regresiones (las 4 fallas transitorias durante el desarrollo eran fixtures de `test_procesamiento_masivo.py` que no incluían `RUT del cliente`; se actualizaron sin tocar su intención original).
- **Pendiente conocido, no bloqueante:** `obra_destino` sigue devolviendo el valor de GIRO (`"VENTA AL POR MAYOR D"`) en vez del destino real (`"SUPERMERCADO SEÑOR DE LOS MI"`) — mismo tipo de colisión geométrica que motivó C1, pero en el campo obra_destino, no cliente.
- **Próximo bloque oficial: DESTINO D1** — corregir `obra_destino`/GIRO, prerrequisito directo de rutas/KM/tiempos. No iniciado; no se tocó nada de ese frente en C1.

---

## 2026-08-10 — Cierre Patentes P2: homologación conservadora contra catálogo de vehículos

- **Rama:** `lector-mvp-guia-nueva`. Baseline anterior: `0021bde59a9bb2f7b18462377ea6634d5cade781`.
- **Objetivo cerrado:** homologación canónica de patentes contra el catálogo de vehículos (`vehiculos.json`, vía `carpeta_catalogos`), nueva función `resolver_patente_canonica` en `atlas_core/catalogos.py`, wireada en `procesar_archivo`.
- **Jerarquía:** (A) coincidencia exacta normalizada, (B) alias explícito declarado en el catálogo, (C) corrección OCR conservadora — solo con un único candidato, misma longitud, y una única diferencia posicional explicada por una confusión OCR documentada (B/D, 0/O, 1/I, 5/S, 8/B). Nunca crea una patente nueva.
- **Caso real confirmado, guía `464511`:** `patente_tracto` `SD6486 → SB6486` (corrección OCR conservadora, catálogo real); `patente_rampla` `JF4288 → JF4288` (coincidencia exacta, sin cambios). **La corrección no está hardcodeada por archivo** — surge de la jerarquía general aplicada contra el catálogo real.
- **Política de abstención:** ambigüedad → conserva el valor OCR y marca `REVISAR`; sin catálogo → no inventa nada.
- PaddleOCR, Desktop y generación de reportes no se tocaron — Desktop y reportes reciben el valor homologado automáticamente al consumir el dict de `procesar_archivo`.
- Suite final: **581/581 tests** (566 → 581).
- **Frente de patentes (P1 + P2) queda cerrado.** No hay un próximo microbloque de patentes definido.

---

## 2026-08-10 — Cierre Patentes P1: recuperación geométrica de patentes compatible con Paddle

- **Rama:** `lector-mvp-guia-nueva`. Baseline anterior: `0bcb43ca56e5ab1cdc6f596bb80af225ce234739`.
- **Problema resuelto:** `patente_tracto`/`patente_carro` volvían `"No encontrado"` con salida Paddle porque la extracción original exigía la frase contigua `"RETIRA PATENTE FECHA LLEGADA"`, y Paddle reparte esas etiquetas en bloques/líneas separados. Se agregó `_extraer_patentes_geometrico` (`atlas_core/extractor.py`), nueva función geométrica que ancla en la zona RETIRA–FECHA LLEGADA por coordenadas, activa solo como *fallback* cuando la lectura lineal ya devolvió "No encontrado". **PaddleOCR no se tocó.**
- **Camino histórico EasyOCR preservado:** `buscar_chofer_y_patentes()` (lectura lineal por frase contigua) no se modificó.
- **Alcance deliberadamente acotado:** P1 recupera el valor OCR disponible, no lo corrige. La guía real `464511` recupera `patente_tracto = SD6486` (el valor que Paddle realmente lee, con una B leída como D) y `patente_rampla = JF4288` (correcto); no se corrige `SD6486` a `SB6486`.
- Suite final: **566/566 tests** (556 → 566).
- No se tocó Desktop ni la generación de reportes — ambos consumen el dict que devuelve `procesar_archivo`, así que reciben el valor recuperado automáticamente sin cambios propios.
- **Próximo microbloque pendiente:** homologación de patente OCR contra catálogo de vehículos (ejemplo `SD6486 → SB6486`), sin alterar el OCR. No iniciado.

---

## 2026-08-10 — Integración Desktop ↔ Motor Paddle cerrada

- **Rama:** `lector-mvp-guia-nueva`. Baseline anterior: `e61c04af4081b3d52761ad7928291bd88b6a83d2`.
- Atlas Viajes Desktop 1.4.3 y el motor vuelven a compartir el contrato histórico `--catalogos <ruta>`. También se admite `ATLAS_CATALOGOS_DIR`; fuentes incompletas, inexistentes o compuestas solo por plantillas `.example` se rechazan.
- `resumen_procesamiento_desktop.py` fue recuperado desde Git y verificado contra su blob histórico. `generar_reporte_viajes.py`, `atlas_core/gestor_viajes.py` y `atlas_core/reporte_viajes.py` también fueron recuperados desde la línea histórica compatible y validados contra el HEAD actual.
- La propagación de catálogos fue fusionada selectivamente con M2. **PaddleOCR continúa como proveedor principal**, GPU activa en este PC, proveedor único reutilizado por lote y EasyOCR disponible como fallback.
- Suite final: **556/556 tests**.
- Prueba manual end-to-end exitosa: Desktop procesó la guía real `464511`, obtuvo transporte `0000352449`, fecha `10-08-2026`, cliente `ARMACERO MATCO SA` y chofer `RODRIGO NAHUELÑIR`; el viaje se mostró correctamente en Atlas Viajes 1.4.3 con estado OK.
- Los 574 viajes operativos no fueron reprocesados ni modificados durante las pruebas técnicas aisladas.
- **Próximo frente:** RECUPERACIÓN UX HISTÓRICA del Desktop. No iniciar cambios del motor como parte de ese frente. Antes de considerar perdido un archivo o comportamiento, revisar `G:\Mi unidad\BACKUP_PRE_FORMATEO_20260808`.

---

## 2026-08-10 — Cierre Bloque M2: runtime Paddle portable + activación batch (pendiente de tu aprobación final)

- **Rama:** `lector-mvp-guia-nueva`. **Sin commit, sin push** — a la espera de que apruebes antes de cerrar formalmente (a diferencia de M1, aquí no hice el commit todavía porque me pediste el reporte de los 10 puntos primero).
- **Runtime portable resuelto:** `%LOCALAPPDATA%\Atlas\runtime\paddleocr` (variable de entorno `ATLAS_PADDLE_RUNTIME` disponible como override de desarrollo). Ya no depende de `ocr_eval_gpu_env` ni de ninguna ruta de este PC — confirmado por tests y por `grep` sobre la validación real.
- **`procesar_carpeta` ya activa PaddleOCR en el flujo real de lote** — antes de este bloque solo `procesar_archivo` sabía usar un proveedor; ahora la CLI real (`analizar_guias_masivo.py`) lo hace por defecto, con un único proveedor por ejecución.
- **Validado con una instalación real desde cero** (no simulada): el bootstrap completo tomó 209 s. Una corrida corta real de 4 guías con la CLI real confirmó GPU seleccionada automáticamente, un solo mensaje de proveedor activo (no uno por imagen), y resultados correctos.
- **No se corrieron las 30 imágenes de nuevo** — decisión deliberada, ya justificada: la lógica de extracción no cambió respecto a M1 (que sí las validó completas), este bloque solo tocaba la resolución de runtime y la activación en `procesar_carpeta`.
- **Nota de rendimiento para quien lea las métricas de una primera corrida en una máquina nueva:** el primer uso de un runtime recién creado es notablemente más lento (antivirus escaneando binarios nuevos, cachés fríos) — no lo tomes como el rendimiento real; una segunda corrida ya estabiliza.
- **Hallazgo fuera de alcance:** apareció un archivo no rastreado `resumen_procesamiento_desktop.py` en la raíz del repo, que yo no creé ni toqué — queda ahí, sin explicación, fuera de este commit. Alguien debería revisar de dónde salió.
- Suite: 482 → **501 tests**, todos verdes.
- **Siguiente decisión pendiente:** no hay un bloque M3 definido todavía. Con M1+M2, PaddleOCR queda como motor principal, portable, activo en el flujo real, con EasyOCR de fallback — el trabajo de integración de este frente queda esencialmente completo salvo lo que decidas priorizar después (p. ej. confirmar el camino CPU puro en una máquina sin GPU, que sigue pendiente desde M1).

---

## 2026-08-10 — Cierre Bloque M1: proveedor OCR + PaddleOCR integrado (APROBADO)

- **Rama:** `lector-mvp-guia-nueva`. Commit hecho y pusheado a `origin/lector-mvp-guia-nueva` (ver SHA en el mensaje de cierre de esa sesión).
- **Decisión de cierre: PaddleOCR queda aprobado como motor OCR principal de Atlas. EasyOCR queda como fallback temporal**, no eliminado — sigue siendo el proveedor si Paddle no está disponible, y sigue siendo el camino usado por defecto en el código cuando no se pasa `proveedor=` explícitamente.
- **Precisión importante para quien retome esto:** "integrado" significa que la infraestructura (`ProveedorOCR`, `EasyOCRProvider`, `PaddleOCRProvider`, selección GPU/CPU, `numero_guia` robusto, focal generalizado) está lista, testeada (482 tests) y validada con una corrida real de las 30 guías — **no** que `procesar_carpeta` (el punto de entrada real de la CLI/lote) ya construya y use un `PaddleOCRProvider` por defecto. `procesar_carpeta` todavía no recibe ni pasa ningún `proveedor` — sigue llamando a `procesar_archivo` solo con `lector_ocr` (EasyOCR). Conectar el proveedor Paddle al flujo de lote real (`procesar_carpeta`/CLI) sigue pendiente y no se hizo en M1.
- **numero_guia recuperado:** 2/30 → 29/30, reutilizando `decidir_bloques_ocr` (ya existía) conectado al proveedor activo.
- **`IMG-20250930-WA0047.jpg` (número de guía):** discrepancia editorial de ground truth pendiente (410627 documentado vs 410267 que la imagen realmente muestra, según la observación original del validador) — no cuenta como fallo de Atlas, no bloqueó el cierre.
- **PaddleOCR corre en proceso completamente aislado**, nunca en el entorno principal — sus ~55 dependencias no tocan `requirements.txt` ni el venv de producción.
- **Selección GPU/CPU automática**, sin GPU hardcodeada. GPU real confirmada en este PC (3.03 s/imagen). **Portabilidad CPU explícitamente diferida**: no se corrió otro benchmark completo de 30 imágenes en CPU en este cierre — se validará con una prueba corta en el PC de oficina en un momento posterior.
- **Riesgo principal pendiente, con nombre:** `PaddleOCRProvider` apunta hoy a una ruta fija de este equipo (`C:\Users\Jjjc0508\Desktop\Atlas\ocr_eval_gpu_env`), creada para el bloque de evaluación — no es arquitectura de despliegue definitiva.
- **`IMG-20260512-WA0027.jpg` queda `REVISAR`** por la guarda documental — su fecha sigue siendo incorrecta, la guarda no la corrige, solo evita que pase como dato confiable.
- Suite: 458 → **482 tests**, todos verdes.
- **Próximo bloque oficial: M2 — runtime Paddle reproducible/portable** (reemplazar la ruta fija del venv por algo que no dependa de este equipo específico). No iniciado todavía.

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
