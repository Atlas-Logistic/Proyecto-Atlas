# Handoff — Proyecto Atlas

Estado de traspaso para quien retome el trabajo. Se actualiza al cierre de cada bloque.

---

## 2026-08-14 — Handoff vigente: R2 OBRAS promovido, operación real 17/19

- **Código publicado:** rama `lector-mvp-guia-nueva`, commit funcional `c02aa31ba5044b39a33c8101feea529cbece9f22`. `actualizar_identidad_obra` actualiza identidad/aliases/evidencia preservando IDs, pertenencia, estado e historial; bloquea vacíos, colisiones y evidencia humana mal tipada. Normalización segura: `S.A.` equivale a `SA`, pero letras independientes no se fusionan. Suite Motor: `1027 passed, 0 failed`.
- **Siete relaciones confirmadas:** DEMO/Poeta Pedro Prado 1548; Torres Coronel/Av. Forestal M1 1014; Terratec/Maestra Lidia Torres 92; Level/Av. Lo Blanco 2389; Ignacio Hurtado/Pdte. Riesco 5903; OCL/Catedral 759; EBCO/Av. 4 Norte 1565. Actor `JAVIER_MBT`, decisión `CONFIRMACION_HUMANA_OBRAS_R2_2026-08-14`. Seis destinos creados y Level reutilizado. No existen aliases/destinos para los OCR erróneos `758` o `A65`.
- **Operación vigente:** `G:\Mi unidad\Atlas\operacion\actual\analisis_completo_guias.csv`, SHA-256 `B84FD7DB0D7391D93B47B4F5ACA3E4641468CC30374FFC23FD840824A4A62E43`, `19 filas / 17 OK / 2 REVISAR / 0 errores / 0 duplicados`. Anterior: `516A9D5EA8E6632416EB5418756ACB081323FAD66C87D2956B5B28AFCF8A4FFF`, `9/10`. Nuevas OK: `463594`, `463630`, `464588`, `464601`, `464624`, `464698`, `464699`, `464700`; cero regresiones.
- **Rollback:** `G:\Mi unidad\Atlas\respaldos\R2_PRE_PROMOCION_OBRAS_17_19_2026-08-14_20260814_110939_-0400`, con dataset anterior, hashes, README y reporte anterior.
- **Reporte/Desktop:** `reportes/actual` fue regenerado desde el dataset promovido; `estado_operacion.json` apunta al dataset y reporte vigentes. Desktop `859d6bf440fddc925118fa172efe174b6ab75ad6` devuelve `OPERACION_ACTIVA`, encuentra `viajes.csv`, no usa fallback histórico y pasó `126/126`; repo Desktop limpio.
- **Catálogos al cierre:** obras `8B3BEA7679ECB20A770A5D4D3FBDED3671A36A46D537B5023C27B475FE475937`; destinos `9B69D77D193F40AC9207953B939417E70817270CC79D2494908A3AD49119D7C4`; clientes `D30F364CB174A2BCA9B136ADF7F58F7C986DACC0668EECCA50897AB6DF7FB3C2`; vehículos `0E522AF5A517DD4AC692C45F14C637519D20BFF90110BF8AD46F87E03626AF66`; telemetría sin cambios `7B4BA64606DC4E51E6356EC740F86526D7FA2BFC8BA3908542FBA94ACF06A012`.
- **Siguiente bloque único:** diagnóstico conservador de `CLIENTE_SIN_CORROBORAR` en `464534` y `464535`. Ambas siguen además con `OBRA_DESTINO_SIN_CORROBORAR`; no forzar identidad ni corregirlas fuera de ese bloque.

---

> **Handoff vigente:** leer primero “Cierre vigente — INFRAESTRUCTURA S2.2” al final del archivo. Los registros previos del commit perdido quedaron supersedidos por la reconstrucción publicada.

## 2026-08-13 — INFRAESTRUCTURA S2.2: registro provisional del PC de oficina (supersedido)

- **Rama motor:** `lector-mvp-guia-nueva`. Baseline: INFRAESTRUCTURA S2.1 (`2046f08`).
- **Repo Desktop real, encontrado y usado:** `https://github.com/Atlas-Logistic/Atlas-Viajes-Desktop.git`, rama `fix-desktop-data-root-drag-drop`. Copia de trabajo local: `C:\Users\corte\Desktop\MBT\Proyecto\Atlas-Viajes-Desktop\` (clon limpio + los 3 commits que solo existían en la copia que S2.1 había preservado en `historico_pre_infra_s2\`, traídos por fast-forward verificado, nunca reescritos). **No se creó ningún repo GitHub nuevo.**
- **El commit `96229813fcae41c5e1ea22ac139c703c616c976a` (MATERIAL/PESO/OBRA DESTINO en multiguía) no existe en ningún repo/rama accesible** desde este PC (se hizo `git fetch --all` real contra GitHub, 18 ramas, 31 commits totales) ni en la copia histórica de Drive. Lo más cercano es `src/consolidacion_viaje.js` + `test/consolidacion_viaje.test.js`, que viven en la rama `feature-consolidacion-viajes-1` (no fusionada con la rama de portabilidad usada aquí) -- **no se fusionó esa rama en este bloque** (habría sido un merge de feature no relacionado, fuera del alcance "resolver únicamente la portabilidad pendiente"). Si Javier confirma que ese commit debería existir, vale la pena revisar directamente en el PC de casa.
- **Contrato portable nuevo, compartido entre motor y Desktop:** `docs/CONTRATO_ESTADO_OPERACION_PORTABLE.md` (motor) / `documentacion/CONTRATO_ESTADO_OPERACION_PORTABLE.md` (Desktop) -- mismo archivo, mismo esquema. El motor lo escribe (`atlas_core.almacenamiento_portable.escribir_estado_operacion`, wireado de forma best-effort y silenciosa en `generar_reporte_viajes.py`); Desktop lo lee (`src/estado_operacion.js`).
- **Bloqueo real, no un blocker inventado:** no hay Node.js instalable en este entorno (sin `node.exe` en PATH ni en ubicaciones conocidas; `node_modules/electron/dist` nunca se descargó). No se pudo correr `npm test` ni abrir Electron para una validación visual. Se revisó el código a mano con mucho cuidado (mismo patrón exacto de funciones puras + `node:test` que ya usa el resto del repo Desktop; balance de llaves/paréntesis verificado sin diferencia neta) y se comiteó localmente (`4b94a38`), **sin publicar**. Próximo paso, en un PC con Node: `npm test` y, si pasa, `git push origin fix-desktop-data-root-drag-drop`.
- **Motor, cambios sí verificados con la suite completa:** nuevas funciones `escribir_estado_operacion`/`leer_estado_operacion` en `atlas_core/almacenamiento_portable.py`, wireadas de forma best-effort (silenciosa si `--salida`/csv no viven dentro de `ATLAS_DATA_DIR`, comportamiento idéntico a antes de S2.2) en `generar_reporte_viajes.py`. 916 → 927 tests, sin regresiones.
- **Próximo paso natural:** confirmar `npm test` en Desktop desde un PC con Node (casa, probablemente) y publicar la rama; después, cuando exista una operación real posterior a N1, generarla apuntando `--salida`/`ATLAS_DATA_DIR` a la raíz de Drive para que el manifiesto se publique solo y Desktop la vea sin ningún paso manual.

---

## 2026-08-13 — INFRAESTRUCTURA S2.1: Drive ya es la raíz operativa portable -- si retomas esto, empieza aquí

- **Rama:** `lector-mvp-guia-nueva`. Baseline: INTELIGENCIA N1 (`ed52afb`).
- **Decisión permanente, ya en código:** código = GitHub; estado operativo portable = raíz única `Atlas\` en Drive (`ATLAS_DATA_DIR`, resuelta por `atlas_core/almacenamiento_portable.py`); secretos = variables de entorno locales, nunca Drive/Git. En este PC (oficina), `ATLAS_DATA_DIR` ya está configurado a nivel de usuario apuntando a `G:\Mi unidad\Atlas` -- **requiere abrir una terminal/VSCode nueva para que el cambio de registro se refleje** (un proceso ya abierto antes de este bloque no lo ve).
- **Antes de escribir nada en Drive se auditó lo que ya había ahí** (ver `BITACORA_TECNICA_CRONOLOGICA.md` para el detalle completo): la carpeta `Atlas` existente era resultado de una sesión de incidente del 2026-08-10/11, no una raíz limpia -- contenía dos repos Git completos, dos venvs (uno con CUDA) y cuatro versiones sin reconciliar de `analisis_completo_guias.csv`. Todo se movió (nunca se borró) a `historico_pre_infra_s2\` dentro del mismo Drive, con un `README_HISTORICO.md` explicando el porqué.
- **Catálogo privado migrado:** el catálogo vivo real de esta oficina estaba en `C:\Users\corte\AppData\Local\Atlas\datos\catalogos_privados` (base 2026-07-30, con manifiesto de hashes SHA-256 propio, ya diseñado con política de "versión completa inmutable" antes de este bloque) -- se copió (no se movió; el original en AppData sigue intacto) a `G:\Mi unidad\Atlas\catalogos_privados\`, verificado hash por hash. `atlas_core/fuente_catalogos.py` ahora cae en esa ruta automáticamente si no hay `--catalogos`/`ATLAS_CATALOGOS_DIR` explícito y no hay `catalogos/` local completo.
- **Caché de geocodificación ORS/Pelias, nueva** (`atlas_core/rutas/cache_geocodificacion.py`): `ProveedorRutasConCacheGeocodificacion` envuelve cualquier `ProveedorRutas` y cachea `geocodificar()` (nunca `calcular_ruta()` -- esa ya se cachea en `RepositorioRutas`/`ServicioRutas` desde antes) en `<raíz>\cache\geocodificacion\geocodificacion_cache.json`, con el mismo patrón de escritura atómica que `RepositorioRutas`/`RepositorioTelemetria`. Fallos transitorios (sin conexión, límite de cuota, sin credencial) deliberadamente **no** se cachean -- solo resultados estables del proveedor. Ya está wireado en los dos puntos donde `procesamiento_masivo.py` construye `OpenRouteService(pais=...)` por defecto.
- **Lock simple nuevo** (`atlas_core.almacenamiento_portable.bloqueo_sesion`): archivo `.atlas_lock_<nombre>` con expiración por antigüedad (huérfanos se reemplazan solos) -- usado en la escritura de la caché de geocodificación. No se aplicó a `RepositorioRutas`/`RepositorioTelemetria` existentes en este bloque (ya tenían escritura atómica propia; extenderles el lock queda como mejora futura de bajo riesgo, no urgente).
- **Deliberadamente NO hecho en este bloque:** adaptar el código fuente de Atlas Desktop (`main.js`/`config_usuario.json`, que hoy hardcodea `C:\Users\Jjjc0508\...`) para leer la raíz portable -- la única copia de ese código encontrada (en `historico_pre_infra_s2\componentes_no_portables\Atlas-Viajes-Desktop-Restaurado\`) no tiene remoto Git configurado, y no había otro repo Desktop accesible en ningún PC verificado. Editar código sin remoto dentro de Drive habría violado el principio "código = Git" de este mismo bloque. Queda como bloque separado: crear el remoto, adaptar la resolución de rutas, tests y commit propios.
- **`operacion\actual\` queda vacía a propósito:** no se encontró en ningún PC verificado un `analisis_completo_guias.csv`/reporte posterior a N1 (`ed52afb`) -- no se reconstruyó ni se inventó. El histórico de 1.178 filas del incidente NO se promovió (decisión de negocio explícita: histórico experimental ≠ operación vigente). Ver `operacion\actual\PENDIENTE_IMPORTACION_PC_CASA.md` y `coordinacion\PENDIENTE_PC_CASA.md` en Drive.
- **Próximo paso natural:** en casa, configurar `ATLAS_DATA_DIR` apuntando a su propio Drive, confirmar `validar_fuente_catalogos()` → `CATALOGOS_VALIDOS`, y resolver el pendiente de catálogo/operación de `PENDIENTE_PC_CASA.md`. Después de eso, el flujo normal es `git pull` + Drive ya sincronizado + trabajar.

---

## 2026-08-12 — INTELIGENCIA N1: normalización semántica cerrada, con un bug propio encontrado y corregido antes de publicar -- si retomas esto, empieza aquí

- **Rama:** `lector-mvp-guia-nueva`. Baseline: PATENTES P4 (`88645b3`).
- **Los dos casos con nombre del bloque quedaron resueltos, por reglas generales, no hardcodeadas:** CAUQUBNES y CADQUENES → Cauquenes (comuna real, Región del Maule); "SOC CONETRUCTORA OCL LIMITAD" → "SOC CONSTRUCTORA OCL LIMITADA". Ninguna corrección menciona una guía ni un valor específico en el código -- ambas son consecuencia de un catálogo territorial cerrado (345 comunas) y un vocabulario societario acotado, con margen de seguridad.
- **Se encontraron y corrigieron tres bugs reales de extracción** (no solo de normalización), todos afectando la tanda real en silencio: un margen geométrico demasiado estricto perdía un RUT de cliente perfectamente legible en formularios con filas apretadas; un RUT de chofer terminado en "K" se truncaba antes del dígito verificador; cliente nunca tenía una vía de corroboración por similitud de nombre (solo chofer la tenía).
- **Importante para quien siga con esto -- la propia validación encontró un bug real antes de publicar:** la primera versión de la normalización de comunas corrompía la palabra real "CAMINO" en la comuna real "Camiña", y "PARQUE" en "Pirque" (ambos con ~0.83 de similitud). Se encontró auditando el propio resultado del reproceso, se corrigió (umbral más alto + lista de palabras de dirección que nunca son candidatas), y se **repitió el reproceso completo desde cero** antes de aceptar el resultado -- la lección para el futuro: cualquier normalización fuzzy contra un catálogo de cientos de nombres reales necesita validarse contra vocabulario común, no solo contra los casos objetivo.
- **Aprendizaje controlado ya en funcionamiento real:** `empresas.json` tiene ahora `EBEMA SA` con dos alias aprendidos (`EDMA SA`, `KBEMA SA`) -- la próxima vez que cualquiera de esas corrupciones OCR aparezca, se reconoce al instante.
- **Lo que se dejó deliberadamente sin tocar:** la corroboración de OBRA DESTINO sigue exigiendo revisión ante cualquier cambio de catálogo (solo se limpia el texto, nunca se corrobora solo por eso) -- es una decisión de diseño previa (Bloque ESTADOS S2) que este bloque no tenía motivo para relajar.
- **Pendiente, fuera de alcance de este bloque:** la guía 464601 tiene "E EMISIÓN" como cliente (claramente OCR confundiendo con "FECHA DE EMISION") y varios campos vacíos -- causa distinta, necesita su propia investigación. Varias guías con `MULTIPLES_UBICACIONES_DISPERSAS` (464641/464642 entre otras) siguen sin resolver -- ambigüedad real de geocodificación, no un problema de comuna/typo.

---

## 2026-08-12 — PATENTES P4: el bug no era el OCR, era la asociación geométrica -- y aparece un segundo caso real de Renca-que-era-Colina, si retomas esto, empieza aquí

- **Rama:** `lector-mvp-guia-nueva`. Baseline: ORIGEN O2 (`3b3189c`).
- **464631 quedó resuelto de punta a punta:** tracto DD2494, rampla JB8529, RUT del chofer, y con la patente disponible la telemetría GPS confirma AZA COLINA -- coincide con Javier y el chofer. La causa real de la pérdida no era el OCR (PaddleOCR leyó DD2494/JB8529 perfectamente bien) sino que el extractor "geométrico" de patentes no era realmente geométrico -- concatenaba texto y se abstenía por ambigüedad ante cualquier segundo token de 6 caracteres en la zona, sin mirar la distancia real a la etiqueta. Reescrito para asociar cada etiqueta a su valor por posición real, igual que el resto de los extractores del archivo.
- **Dos variantes reales de error de OCR quedaron cubiertas de forma general** (no hardcodeadas a esta guía): la etiqueta CARRO leída "CARR0" (cero por O), y la etiqueta RETIRA leída "RETRA" (falta la "I") -- esta última bloqueaba TODA la zona de extracción, no solo el CARRO.
- **Al revisar la tanda reciente por el mismo patrón, apareció un segundo caso real con el mismo problema de fondo:** la guía 464550 (patente BPHR67, perfectamente legible) tenía el bug de "RETRA". Al recuperarla, la telemetría corrió por primera vez para esa guía (antes nunca se activaba porque la patente estaba vacía) y **también confirma AZA COLINA, no AZA RENCA** como mostraba el documento -- con evidencia GPS fuerte (101 min de detención real dentro de la ventana horaria completa de la guía). No se buscó activamente más -- se revisaron las 6 guías de la tanda con patente ausente, esta fue la única con el mismo patrón estructural; las otras 5 genuinamente no imprimen rampla.
- **Esto refuerza, con un segundo caso independiente, el hallazgo abierto del bloque anterior (ORIGEN O2):** cada vez que se revisa con cuidado un documento que el pipeline daba por "AZA RENCA" solo porque no se pudo confirmar nada más, termina siendo AZA COLINA con evidencia GPS real. La pregunta abierta de si AZA RENCA necesita su propio polígono, o si esta operación real genuinamente no está cargando ahí, sigue sin resolverse -- cada bloque nuevo suma evidencia a favor de investigarlo pronto con Javier.
- **Separación que se mantiene:** ninguna geocerca se tocó en este bloque -- la corrección es enteramente de extracción de datos (OCR/geometría) y de habilitar la telemetría que ya existía, no de geografía.
- **Próximo paso natural:** el mismo del bloque anterior -- conversar con Javier sobre AZA RENCA, idealmente con un caso confirmado por él como control positivo real.

---

## 2026-08-12 — ORIGEN O2: 464424 resuelto, y un hallazgo grande sobre AZA Renca que necesita conversación con Javier -- si retomas esto, empieza aquí

- **Rama:** `lector-mvp-guia-nueva`. Baseline: `e7f5a82` (PLANTAS P3).
- **464424 (el caso más difícil de toda esta línea de trabajo) ya muestra AZA COLINA, correcto según Javier.** Se encontró una parada real de 48 minutos en Colina justo en la ventana de la guía -- antes Atlas solo veía un pase rápido cerca de Renca (88 km/h, nunca una parada) y se quedaba con eso por defecto.
- **Lo más importante para conversar con Javier antes de seguir:** al revisar TODA la tanda real con el nuevo criterio (¿dónde hubo una parada REAL, no solo presencia?), **ningún viaje de esta tanda de 19 guías tiene evidencia de una parada real en AZA RENCA** -- toda la evidencia "Renca" que existía (incluidos casos confirmados desde el primer bloque de telemetría de esta sesión, 463630 y 463594) resultó ser el camión cruzando una vía cercana a 64-88 km/h, nunca deteniéndose. Todos, en cambio, sí muestran una parada real en el mismo recinto de Colina.
- **Esto se investigó con cuidado antes de aplicarlo** (se preguntó explícitamente, se verificó velocidad GPS punto por punto) -- no es un bug que se corrigió a ciegas, es un patrón real y repetido en datos de múltiples camiones y fechas distintas.
- **La pregunta que queda abierta, sin resolver:** ¿AZA RENCA necesita su propio polígono real (como Colina en el bloque anterior) porque su círculo de 1,5 km no alcanza a cubrir dónde realmente paran los camiones? ¿O esta tanda específica de camiones/transportes genuinamente no carga en Renca? No se tocó la geocerca de Renca en este bloque -- valdría la pena, en el próximo bloque, buscar UN viaje real que Javier confirme como "este sí salió de Renca" y usarlo como control positivo, igual que se hizo con AL1879 para Colina en el bloque de detenciones.
- **Separación que se mantiene:** `punto_ruteo` (de dónde parte una ruta ORS) sigue siendo distinto de la dirección histórica de una planta -- ver bloque PLANTAS P3.
- **Próximo paso natural:** conversar con Javier sobre el hallazgo de Renca antes de seguir ajustando geocercas -- con un caso real confirmado de Renca en la mano, se puede calibrar con evidencia en vez de adivinar.

---

## 2026-08-12 — PLANTAS P3: AZA Colina como recinto real -- 10 conflictos nuevos requieren revisión de Javier -- si retomas esto, empieza aquí

- **Rama:** `lector-mvp-guia-nueva`. Baseline: `469cecb` (TELEMETRÍA T3).
- **Lo bueno primero:** 464641/464642 (el caso que Javier señaló) ya muestran **AZA COLINA confirmada por GPS** -- Atlas ahora modela plantas como recintos reales (polígono), no solo puntos. El polígono de Colina se construyó con evidencia GPS real (117 breadcrumbs de AL1879) validada contra cartografía real (la vía "Eduardo Frei Montalva" y el cruce de Ruta 5 están justo al lado). AZA Renca sigue funcionando exactamente igual que siempre (no se tocó).
- **Lo que necesita a Javier ahora:** al aplicar el polígono a toda la tanda, aparecieron **10 guías que antes confirmaban Renca limpio y ahora quedan en conflicto explícito** (463594, 463630, 464534, 464535, 464588, 464601, 464624, 464698, 464699, 464700) -- esos camiones también muestran paradas reales de 32 minutos a más de 2 horas en el mismo lugar donde estuvo AL1879, en fechas distintas. Se decidió (con el usuario) NO forzar ninguna conclusión y NO ajustar el polígono a ciegas -- se dejan como conflicto explícito (`CONFLICTO_AZA_COLINA_VS_AZA_RENCA` en el campo `motivo_origen_gps`) para que Javier los revise con más contexto (¿esos transportes realmente pasan por Colina como parte de su ruta? ¿es un punto de espera compartido junto a la Panamericana, sin relación con ninguna de las dos plantas?).
- **Separación importante para cualquiera que toque rutas de aquí en adelante:** la dirección histórica de una planta (`latitud`/`longitud`) y el punto real desde donde debe partir una ruta (`punto_ruteo_latitud`/`punto_ruteo_longitud`, nuevo) son cosas DISTINTAS -- para AZA Colina difieren en 18 km. Todo código que calcule una ruta ORS debe usar `coordenada_ruteo_planta(planta)` (en `atlas_core/rutas/geocerca.py`), nunca `Coordenadas(planta.longitud, planta.latitud)` directo.
- **Próximo paso natural:** conversar con Javier sobre los 10 casos en conflicto -- con una guía/patente/fecha concreta que él pueda confirmar como "sí pasó por Colina" o "no, ese es un punto de espera aparte", se puede calibrar el criterio con evidencia real en vez de ajustar a ciegas.

---

## 2026-08-12 — TELEMETRÍA T3: detenciones GPS + una planta AZA real sin catalogar -- si retomas esto, empieza aquí

- **Rama:** `lector-mvp-guia-nueva`. Baseline: `aa1b5bb` (OPERACIÓN REAL R1.1).
- **Lo más importante:** Javier tenía razón en que el vehículo (AL1879, 464641/642) estuvo detenido varias horas en un lugar real durante la ventana de carga -- el bug era que Atlas nunca miraba los huecos entre viajes cortos como evidencia de permanencia, y solo usaba UNA de las dos horas del documento para acotar la búsqueda GPS. Ambos corregidos.
- **El hallazgo pendiente de decisión con Javier:** ese lugar geocodifica, dos veces de forma independiente, como **"Gerdau Aza, Lampa"** -- todo indica una TERCERA planta AZA real (Gerdau es la matriz de Aceros AZA), distinta de Renca y de Colina, que hoy NO está en `plantas.json`. Se decidió (con el usuario, explícitamente) no agregarla todavía sin confirmar la dirección exacta. **Si Javier confirma que esa es una planta real (probablemente donde carga contenido para el circuito Colina/Lampa/norte)**, el siguiente paso natural es un bloque corto: dar de alta "AZA LAMPA" (o el nombre correcto) en el catálogo con coordenadas confirmadas -- el modelo de detenciones ya construido en este bloque la reconocería automáticamente de ahí en adelante, sin más cambios de código.
- **464641/464642 ya NO muestran "AZA Renca"** (el bug real) -- ahora muestran `ORIGEN_GPS_ESTADIA_SIN_PLANTA` con la coordenada y duración de la detención real, visible en el CSV/reporte para revisión humana. Nunca Colina sin evidencia, nunca Renca por default.
- **Efecto colateral real y bienvenido:** al usar ambas horas documentales para la ventana, 2 guías más (464534/464535) recuperaron su planta confirmada -- la evidencia ya existía, antes no se buscaba lo suficientemente amplio.
- **Próximo paso natural:** (a) conversar con Javier sobre la planta de Lampa -- si la confirma, es un bloque corto de catálogo; (b) si aparecen más guías reales con patrones similares (detenciones reales sin planta catalogada), revisar si todas apuntan al mismo lugar (reforzaría la hipótesis) o a lugares distintos (podría haber más de una planta sin catalogar).

---

## 2026-08-12 — OPERACIÓN REAL R1.1: sin GPS no hay planta por defecto -- si retomas esto, empieza aquí

- **Rama:** `lector-mvp-guia-nueva`. Baseline: `2ec64c9` (OPERACIÓN REAL R1).
- **Lo más importante para conversar con Javier antes de seguir:** se revisó a fondo (2 días de GPS completos, sin filtrar por distancia) la guía 464424 que él identificó como salida de AZA COLINA -- y la evidencia GPS real, repetida varias veces, muestra el camión (patente SB6486) pasando reiteradamente a menos de 1,2 km de **AZA RENCA**, nunca a menos de 17 km de Colina. Esto contradice lo que Javier recuerda. No se forzó ninguna de las dos conclusiones -- se dejó como Renca (que es lo que el GPS realmente muestra) y se reporta la contradicción de frente. Vale la pena confirmar con él si quizás está pensando en otra guía/patente/fecha.
- **Las guías 464641/464642 (patente AL1879), el otro control positivo que señaló:** revisadas también a fondo (2 días completos) -- no hay evidencia GPS cerca de NINGUNA de las dos plantas. Antes de este bloque mostraban "AZA RENCA" igual (por el bug que se corrigió acá); ahora muestran correctamente "origen no determinado". Sigue sin probarse la observación de Javier sobre esta guía tampoco, pero al menos ya no muestra el dato equivocado (Renca).
- **El bug real que se corrigió:** cuando la telemetría corría con datos reales y no lograba confirmar ninguna planta, el sistema seguía mostrando en silencio la planta que salía de leer el encabezado de la guía (que dice lo mismo en toda guía AZA). Ahora, en ese caso específico, el origen queda honestamente "no determinado" -- nunca Renca por default. Si no hay telemetría conectada en absoluto, el comportamiento de siempre no cambia (decisión de alcance consultada explícitamente, ver bitácora técnica para el detalle de por qué se acotó así).
- **Efecto real sobre la tanda actual (19 guías):** 6 guías dejaron de mostrar "AZA RENCA" sin sustento GPS real (ahora "origen no determinado"). Ninguna pasó a mostrar Colina -- no hay ninguna guía, hasta ahora, con evidencia GPS real que confirme Colina. El mecanismo SÍ sabe reconocer Colina cuando hay evidencia (probado con datos sintéticos en los tests) -- simplemente no ha aparecido todavía un caso real con esa evidencia.
- **Próximo paso natural, si Javier insiste en que hay camiones saliendo de Colina:** la pregunta ya no es "¿el algoritmo funciona?" (funciona, y es conservador -- nunca inventa) sino "¿por qué el GPS de esos camiones específicos no registra el paso por Colina?" -- valdría la pena, con Javier al lado, identificar una guía/patente/fecha muy concreta y mirar el GPS en vivo o casi en vivo de ese viaje puntual, en vez de seguir revisando guías ya despachadas hace días.

---

## 2026-08-12 — OPERACIÓN REAL R1: origen por GPS, no por letterhead -- si retomas esto, empieza aquí

- **Rama:** `lector-mvp-guia-nueva`. Baseline: `3659740` (E2E R2).
- **Decisión ya en código:** la planta de origen se determina por GPS/geocercas cuando hay telemetría conectada; el encabezado de la guía (letterhead) queda como fallback solo sin evidencia GPS -- nunca al revés. Ver `atlas_core/telemetria/seleccion_recorrido.py::resolver_planta_origen_gps` y `atlas_core/procesamiento_masivo.py::procesar_archivo` (bloque de telemetría reescrito).
- **Telemetría ya está conectada al flujo real que usa Desktop** (`analizar_guias_masivo.py` construye `ServicioTelemetria`/`OnelogisProvider` por defecto si hay catálogos) -- antes de este bloque solo existía en scripts de prueba, nunca llegaba a una guía real ingresada por drag&drop. Esto es el cambio más importante para que el resto del trabajo de este bloque sea útil en producción, no solo en tests.
- **Hallazgo honesto que NO se resolvió en este bloque:** de las 7 guías nuevas de la tanda operativa (464631, 464640-642, 464698-700), NINGUNA cambió de AZA RENCA a AZA COLINA con la evidencia GPS real disponible hoy -- VP8521 confirma RENCA por GPS, TG8925/AL1879 no tienen evidencia GPS suficientemente cerca de ninguna planta (quedan honestamente `ORIGEN_GPS_NO_DETERMINADO`, se conserva el valor documental sin inventar una confirmación), 464631 no tiene patente legible. **Esto no descarta la sospecha de Javier** -- si él vio con sus propios ojos un camión saliendo de Colina, puede tratarse de otra guía/patente/fecha fuera de esta tanda de 7. Si aparece una guía real donde Javier señale específicamente "esta salió de Colina", ese es el caso ideal para verificar el algoritmo con evidencia GPS real de un caso positivo conocido (hasta ahora solo se validó negativamente: nunca inventa Colina sin evidencia, pero tampoco se ha visto confirmar Colina con datos reales).
- **Bug real corregido de paso:** DESPACHAR A se llenaba con un RUT en vez de una dirección en 2 guías reales (464631, 464641) -- `atlas_core/extractor.py::_despachar_a_lineal_contaminado` ahora también rechaza un RUT válido completo, no solo etiquetas conocidas. Verificado con las imágenes reales tras el fix.
- **Pendiente, fuera de alcance de este bloque (no era un bug general/seguro, requeriría una capacidad nueva):** 464698/464699 no geocodifican (`GEOCODIFICACION_DIRECCION_NO_ENCONTRADA`) por typos de OCR en el nombre de la comuna ("CADQUENES"/"CAUQUBNES" en vez de "CAUQUENES"). Corregir esto de forma general necesitaría fuzzy-matching contra un catálogo de comunas chilenas -- no se construyó aquí a propósito (evitar abrir una capacidad nueva no solicitada dentro de este bloque).
- **Geocercas de Renca/Colina: no se tocaron, ya están correctas y confirmadas por el usuario.** Se investigó (Fase D) una posible discrepancia de nomenclatura para Colina ("Panamericana Norte 18500" vs. "Av. Pdte. Eduardo Frei Montalva 18500") -- ver detalle en la bitácora técnica. Conclusión: probablemente el mismo corredor físico, sin poder confirmarlo con precisión de numeración vía ORS; no se cambió ninguna coordenada.
- **Datos reales:** dataset operacional reprocesado (9 guías: 7 nuevas + 2 previas sin cambios), con respaldo en `output/_respaldos_reprocesamiento/*_PRE_R1_20260812_131943*`. `config_usuario.json` de Desktop apunta a `output/reporte_desktop_20260812_133037_operacion_real_r1/`.
- **Próximo paso natural:** seguir alimentando Atlas con guías reales del día a día -- con telemetría ya conectada al flujo real, cualquier guía nueva se beneficia automáticamente de la resolución GPS. Si Javier identifica una guía concreta que él sabe que salió de Colina, ese es el caso de prueba que falta para confirmar positivamente el camino AZA_COLINA (hoy solo validado con datos sintéticos en tests, nunca con un caso real positivo).

---

## 2026-08-12 — E2E R2: logística real ya visible en Desktop -- si retomas esto, empieza aquí

- **Rama:** `lector-mvp-guia-nueva`. Baseline: `514feaa` (TELEMETRÍA T2). Sin cambios de código -- bloque de verificación/regeneración de datos.
- **Estado actual del dataset operacional** (`AppData\Local\Atlas\datos\operacion_desktop\` = `Proyecto-Atlas\output\`, `config_usuario.json` ya apunta al reporte más reciente): 463630 con ruta real (536,7 km / 10h07min, "Ruta calculada"); 463594 con planta confirmada pero ruta honestamente pendiente (destino ambiguo, sin forzar).
- **Confirmado con las funciones REALES de Desktop** (`normalizarFila`, `formato_operacional.js`), sin tocar su código: ya leen y muestran estos campos correctamente. Ningún dato técnico de telemetría se filtra a la UI.
- **Limitación de este entorno, no de Atlas:** no se pudo abrir una ventana real de Electron aquí (sin servidor de display) para una captura visual -- la verificación se hizo ejecutando el código real de Desktop directamente con Node.js sobre el CSV real.
- **Próximo paso natural:** si aparece una guía real nueva, procesarla con el pipeline ya conectado (motor + telemetría opcional) y confirmar visualmente en una máquina con pantalla que la Logística se ve como se espera.

---

## 2026-08-12 — TELEMETRÍA T2: selección automática de recorrido GPS -- si retomas esto, empieza aquí

- **Rama:** `lector-mvp-guia-nueva`. Baseline: `dd534c5` (TELEMETRÍA T1).
- **Ya no hace falta el análisis manual descrito en la entrada T1 de abajo** -- `atlas_core/telemetria/seleccion_recorrido.py` lo automatiza: dado patente + fecha + hora_entrada/hora_salida documental, encuentra solo el/los trip(s) de Onelogis relevantes (incluso si el viaje real quedó partido en varios), sin ningún ID hardcodeado. Validado reproduciendo, automáticamente, la misma selección de 3 trips que T1 había encontrado a mano para 463630.
- **Cómo se conecta:** `procesar_archivo(..., servicio_telemetria=...)` -- opt-in, `None` por defecto (comportamiento idéntico a sin este bloque). Cuando está conectado, solo se usa si hace falta (planta sin determinar, o destino con ambigüedad real de geocodificación) -- nunca para todo.
- **Umbrales del algoritmo** (distancia mínima 5 km para considerar un trip "sustancial", hueco máximo 90 min para encadenar) están calibrados contra el único caso real multi-trip conocido (463630) -- si aparecen más casos reales, vale la pena revisar si siguen siendo los correctos.
- **Límite conocido:** la geocodificación ORS no tiene caché propia todavía (a diferencia de Onelogis, que sí) -- cada regeneración de reporte repite esas llamadas. No se resolvió en este bloque.
- **Resultado ya aplicado al dataset operacional actual:** 463630 tiene ruta real automática (536,7 km / 606,9 min). 463594 sigue en revisión, correctamente.
- **Próximo paso natural:** si aparece una guía real nueva con patente/fecha/horas documentales, procesarla con `servicio_telemetria` conectado para seguir validando el algoritmo con más evidencia real (los umbrales calibrados con 1 solo caso se beneficiarían de más datos).

---

## 2026-08-12 — TELEMETRÍA T1: GPS histórico real (Onelogis) -- si retomas esto, empieza aquí (⚠️ ver entrada TELEMETRÍA T2 arriba -- la selección de trips ya quedó automatizada)

- **Rama:** `lector-mvp-guia-nueva`. Baseline: `6afb491` (E2E R1.1).
- **Fuente operacional vigente (LEE ESTO, la entrada de PRODUCCIÓN P1 más abajo está desactualizada):** `AppData\Local\Atlas\datos\operacion_desktop\` = `Proyecto-Atlas\output\` (mismo directorio físico, junction de Windows, ver Bloque E2E R1.1). `reportes\actual\`/`procesamiento\analisis_completo_guias.csv` (los de P1) quedaron archivados en `superseded_por_e2e_r1_1_20260812\` -- no se usan más.
- **Telemetría (Onelogis) es opcional y multiempresa** -- nuevo paquete `atlas_core/telemetria/`. `proveedor_telemetria=None` (o simplemente no usar nada de este paquete) deja Atlas funcionando exactamente igual que antes de este bloque. La credencial vive en la variable de entorno `ATLAS_ONELOGIS_API_KEY` -- nunca en archivos ni en bitácoras.
- **Lo que SÍ quedó automático:** planta origen por GPS, vía `atlas_core.telemetria.adaptador_posicion_vehiculo.AdaptadorPosicionTelemetria`, que implementa el contrato `ProveedorPosicionVehiculo` que ya existía (Bloque RUTAS R1) sin adaptador real conectado.
- **Lo que NO quedó automático (decisión explícita de alcance):** elegir "cuál viaje Onelogis es el relevante" para desambiguar un destino (caso Coronel) dentro del flujo normal de `procesar_archivo()`. Se hizo un análisis real explícito para 463594/463630 (`telemetria_eval/fase_e_i_*.py`, fuera del repo) y se aplicó el resultado a mano (`telemetria_eval/fase_q_regenerar_operacional.py`). Si se quiere automatizar esto, hace falta diseñar con cuidado la heurística de selección de viaje -- no está resuelto todavía.
- **Resultado real en el dataset operacional actual:** 463630 ahora tiene ruta calculada (536,7 km / 606,9 min, planta y destino corroborados por GPS real). 463594 sigue en revisión -- el GPS descartó un candidato pero no alcanzó para elegir entre los 4 restantes.
- **Próximo paso natural:** si se quiere seguir por este camino, diseñar la heurística de selección automática de "viaje relevante" (por ventana horaria del documento + duración/distancia mínima) antes de conectar telemetría al flujo automático de cada guía nueva.

---

## 2026-08-12 — PRODUCCIÓN P1: punto de partida limpio -- si retomas esto, empieza aquí (⚠️ ver entrada TELEMETRÍA T1 arriba -- la ruta operacional cambió)

- **Rama:** `lector-mvp-guia-nueva`. Baseline: `ecaa927`. Sin cambios de código -- solo datos (instalación real) + un doc nuevo en el repo (`docs/HISTORICO_EXPERIMENTAL_VS_OPERACION.md`, léelo primero si algo de esto no cuadra).
- **Decisión clave:** los 574 viajes anteriores a 2026-08-12 son **experimentales**, no un histórico operacional que haya que preservar con precisión. Se cierra ahí la línea ESTADOS S3/S3.1 (migración fina de ese corpus) -- no se completó, no hacía falta, el trabajo ya hecho queda como referencia en `estado_revision_eval/s3/` y `s3_1/`.
- **Dónde está todo ahora** (en la instalación real, `AppData\Local\Atlas\datos\`):
  - Histórico experimental (574 viajes, esquema viejo): `reportes\historicos\experimental_2026-07-28_574viajes\` y `procesamiento\historico_experimental\analisis_completo_guias_574viajes_experimental.csv`.
  - **Operación real actual: `reportes\actual\viajes.csv` y `procesamiento\analisis_completo_guias.csv`** -- empieza con 2 viajes (las guías Villagra/Ñancucheo, las mismas usadas en bloques anteriores para validar), esquema completo O1+E1+S2+S2.2+I1.
- **Muy importante si vas a procesar guías nuevas:** apuntan naturalmente a `reportes\actual\`/`procesamiento\analisis_completo_guias.csv` -- ya son las rutas "actual" de siempre, no hace falta cambiar nada en Desktop ni en scripts. El histórico quedó en carpetas con nombre distinto (`historicos\`, `historico_experimental\`) precisamente para que nadie lo toque por accidente.
- **El resultado inicial (2 viajes, ambos "requiere revisión") es real, no un placeholder que haya que "arreglar".** Refleja honestamente que esos 2 documentos tienen datos genuinamente sin corroborar (cliente, destino, patente) -- exactamente lo que el modelo S2/I1 está diseñado para mostrar. A medida que entren guías nuevas reales, el dataset operacional crecerá con datos reales, no hace falta ni se debe forzar que se vea "más confirmado" artificialmente.
- **¿Próximo paso natural?** Empezar a alimentar Atlas con guías reales de operación día a día -- cada una que se procese ya cae en el dataset operacional nuevo automáticamente. Cuando haya volumen real, recién ahí tiene sentido retomar UX-R4 con datos genuinamente operacionales (no de laboratorio).

---

## 2026-08-12 — ESTADOS S3: migración controlada -- simulación aprobada, migración diferida por decisión de negocio

- **Rama:** `lector-mvp-guia-nueva`. Baseline: `ecaa927`. Sin cambios de código, sin commit -- bloque de datos/simulación puro.
- **Qué se hizo:** se respaldó producción (verificado byte a byte), se clasificaron los 1177 documentos históricos según cuánta evidencia existe sin reprocesar OCR, y se simuló un candidato completo de `viajes.csv` con la semántica actual (O1+E1+S2+S2.2+I1). Resultado: **73 confirmados / 503 requieren revisión** de 576 viajes -- prácticamente igual a lo que ya había anticipado ESTADOS S1 (73/501).
- **Se validó con evidencia real, no solo con números:** 30 viajes que pasarían de confirmado a revisión, verificados uno por uno contra los datos ya extraídos -- 30/30 con causa real (nada inventado, nada incorrecto).
- **Si retomas esto, importante:** el candidato validado está en `C:\Users\Jjjc0508\Desktop\Atlas\estado_revision_eval\s3\simulado\viajes.csv`, listo para migrar cuando se decida. El respaldo de producción (para poder comparar o hacer rollback si migran después con otra herramienta) está en `C:\Users\Jjjc0508\Desktop\Atlas\backups_produccion\20260812_084914_pre_s3\`.
- **Por qué no se migró:** el volumen del cambio (417 de 574 viajes pasan a "requiere revisión" de golpe) es un impacto operativo real y grande para el uso diario de Atlas Desktop -- se preguntó explícitamente antes de escribir producción y la decisión fue esperar. No es una limitación técnica ni un bloqueo -- la simulación está aprobada y lista, es una decisión de cuándo el negocio quiere absorber ese volumen de revisión.
- **Hallazgo real aparte, sin corregir:** la guía `384674` aparece 3 veces en el CSV histórico (mismo documento, fotos distintas subidas por separado) con datos de transporte inconsistentes entre copias -- sugiere que puede haber más duplicados en el corpus histórico. Vale la pena una auditoría de deduplicación antes o durante una futura migración real.
- **¿Próximo paso?** Cuando el negocio decida migrar: el candidato ya está simulado y validado, solo falta ejecutar la sustitución real (Fase O de este mismo bloque, ya diseñada) -- no hace falta rehacer el análisis desde cero.

---

## 2026-08-12 — IDENTIDAD I1: auditoría de normalizaciones hardcodeadas -- APROBADO, cierra la serie ESTADOS S2

- **Rama:** `lector-mvp-guia-nueva`. Baseline: `8029ee4`. **Este bloque SÍ se commitea y pushea** -- ver SHA en el reporte final de la conversación si lo necesitas, o `git log` en la rama.
- **Qué se resolvió, en una frase:** el extractor base tenía reglas del tipo "si el texto contiene la palabra X, la identidad es Y" para varios nombres de empresa (SIGRO, AMERICAN SCREW, POCURO, PRODALA, ACMA) y un RUT de chofer -- algunas eran genuinamente necesarias (layouts reales donde el campo no se captura limpio), pero al menos una (SIGRO) demostrablemente destruía el valor real del documento. Se auditaron todas, se retiraron las que no tenían evidencia de hacer falta o tenían evidencia de estar mal, y se dejaron -- con comentario explícito y evidencia citada -- las que sí demostraron ser necesarias.
- **Si retomas esto, importante:** `atlas_core/extractor.py` ya NO tiene reglas "SIGRO"/"POCURO" en `normalizar_obra_destino` ni en el fallback de `buscar_obra_destino` -- si en el futuro aparece un caso real donde alguna de esas dos vuelva a hacer falta, no la restaures a ciegas: primero busca la imagen real (ahora hay acceso al corpus completo en `G:\Mi unidad\MBT\informe lunes\`) y confirma qué dice el documento antes de decidir.
- **Reglas que SÍ quedaron (con evidencia, no adivinadas):** AMERICAN SCREW (cliente y destino) y PRODALA/PRODALAM (cliente) -- ambas con casos reales confirmados donde el layout no permite capturar el campo de otra forma. ACMA quedó solo en la limpieza post-captura (`normalizar_cliente`), no como atajo de documento completo -- sin evidencia real de que hiciera falta ahí.
- **Hallazgo pendiente, fuera de alcance de este bloque:** el RUT 93.772.000-9 tiene nombres distintos en `empresas.json` ("PRODALAM SA") y en `destinos.json` ("EMPRESA CONST SIGRO") -- valdría la pena revisar esa inconsistencia si se retoma trabajo sobre catálogos, pero no se tocó aquí (no estaba autorizado).
- **Efecto colateral esperado, no un bug:** la guía 464493 pasó de "confirmada" a "requiere revisión" con este fix -- el valor de destino sigue siendo correcto, simplemente ahora se declara honestamente la incertidumbre (antes el hardcode de SIGRO la escondía). Si ves esto en otros documentos al reprocesar, es el comportamiento esperado, no algo que arreglar.
- Suite: 730 → 742 tests, todos verdes. 0 regresiones (incluye un test histórico real de 2026-07 que dependía de una de las reglas conservadas -- se verificó explícitamente que sigue pasando).
- **¿Listo para S3?** Con este bloque, la capa de extracción + calidad/trazabilidad (O1, E1, S2, S2.1, S2.2, I1) queda en un estado coherente y validado con evidencia real de punta a punta. El siguiente bloque natural es **ESTADOS S3 -- migración controlada del reporte productivo** (respaldo, reclasificación segura, regenerar `viajes.csv`, alimentar UX-R4 con datos reales, sin reprocesar OCR innecesariamente). No iniciado todavía.

---

## 2026-08-11 — ESTADOS S2.2: cubrir enriquecimiento de catálogo -- implementado y probado, pero NO resuelve 383295 (causa raíz distinta)

- **Rama:** `lector-mvp-guia-nueva`. Baseline: `8029ee4` (sin commit de ESTADOS S2 todavía). **Sin commit, sin push.**
- **Lo que se pidió para este bloque SÍ se hizo bien:** `enriquecer_datos_con_catalogos()` ahora deja rastro (`MetodoObtencionDocumento.CATALOGO`) y, para obra destino, nunca deja un documento "OK" en silencio solo porque el catálogo sugirió un nombre -- 14 tests nuevos, todos verdes (730 en total, 0 regresiones).
- **Pero el caso real que originó todo este bloque (guía 383295) sigue sin resolverse, y la razón es importante:** el diagnóstico de ESTADOS S2.1 (que culpaba a `enriquecer_datos_con_catalogos()`) **estaba mal**. Al trazar la ejecución real, el valor incorrecto (`"EMPRESA CONST SIGRO"`) ya viene así desde `extraer_datos()` -- la extracción lineal más básica, antes de que exista cualquier lógica de S2 o S2.2. La causa real es una regla hardcodeada en `atlas_core/extractor.py: normalizar_obra_destino()`: cualquier destino que contenga la palabra "SIGRO" se reemplaza por un nombre fijo de empresa, sin verificar si es la correcta. La guía real dice "CONSTRUCTORA SIGRO SA" (correcto, así lo leyó el OCR) pero la normalización lo cambia a "EMPRESA CONST SIGRO" (una empresa real pero distinta).
- **Si retomas esto, importante:** no vuelvas a intentar arreglar esto desde `enriquecer_datos_con_catalogos()` o desde el modelo de motivos/métodos de S2 -- ese camino ya se probó y no alcanza el problema. Hay que entrar directamente a `atlas_core/extractor.py` y revisar las reglas hardcodeadas por subcadena: `normalizar_obra_destino()` (SIGRO, AMERICAN SCREW, POCURO/PCCURO/CCNSIRUCIO/COYSIRUC) y `normalizar_cliente()`/`buscar_cliente()` (PRODALA/PRODALAK/PRODALAM, AMERICAN SCREW, ACMA) -- ninguna de esas reglas tiene ningún tipo de corroboración (RUT, código), simplemente reemplazan si el texto contiene cierta palabra. No se auditó su exactitud real en este bloque -- fuera de alcance explícito.
- **No se corrigió esa regla bajo presión** -- fuera del alcance pedido para S2.2 ("cubrir enriquecimiento de catálogo", no "rediseñar el extractor base"). Se documenta y se detiene, siguiendo el mismo criterio ya aplicado en S2.1.
- **¿Listo para S3?** No. El siguiente bloque real no es "S2.3" continuando el mismo camino -- es una auditoría dedicada de las reglas hardcodeadas de `extractor.py` mencionadas arriba, con evidencia real, antes de volver a intentar cerrar ESTADOS S2.

---

## 2026-08-11 — ESTADOS S2.1: validación de escala sobre corpus real -- defecto real encontrado, detenido para S2.2

- **Rama:** `lector-mvp-guia-nueva`. Baseline: `8029ee4` (sin commit de ESTADOS S2 todavía). **Sin commit, sin push.**
- **El corpus real SÍ se encontró** (no era un problema de acceso a datos): `G:\Mi unidad\MBT\informe lunes\`, 1172 de las 1177 imágenes del CSV masivo (99.6%). Si retomas esto, esa es la ruta a usar -- no hace falta seguir buscando.
- **Con acceso real al corpus, la conclusión cambió de "necesitamos más muestra" a "encontramos un defecto real":** de 196 documentos reales evaluados (46 + 150 nuevos), solo 4 relajaron de REVISAR a confirmado -- muy por debajo de 30, y a esa tasa el corpus completo tampoco la habría alcanzado. Pero lo importante no es el número: **1 de esas 4 relajaciones es incorrecta**. Un documento quedó "confirmado" con un destino de entrega que no corresponde al campo real de la guía (que está en blanco).
- **Causa raíz, importante para quien retome esto:** `atlas_core/catalogos.py: enriquecer_datos_con_catalogos()` (código que ya existía antes de ESTADOS S1/S2) puede sobrescribir `cliente`/`obra_destino`/`chofer`/`patente` buscando coincidencias contra los catálogos en TODO el texto del documento -- por una vía que el sistema de motivos/métodos de S2 **no audita en absoluto**. Este problema existía desde antes de S2 (nunca se marcaba para revisión), pero quedó "enmascarado" porque el documento en cuestión ya estaba en REVISAR por otra razón (guía ausente) -- razón que S2 corrigió al arreglar un bug de variable obsoleta en `numero_guia_actual`, dejando expuesto el problema de destino.
- **No se corrigió bajo presión** -- siguiendo la instrucción explícita, se documenta y se detiene. El código de ESTADOS S2 (separación calidad/método) sigue siendo válido y sin regresiones (716 tests verdes) -- lo que falta es que también cubra esta segunda vía de enriquecimiento por catálogo.
- **Próximo bloque real: ESTADOS S2.2** -- extender el modelo de motivos/métodos para que `enriquecer_datos_con_catalogos()` también quede auditado (su propio método `CATALOGO`, y un motivo de revisión si el cambio no está corroborado). Después de eso, repetir esta misma validación de escala sobre el corpus real ya localizado.
- **¿Listo para S3?** No. Ni siquiera ESTADOS S2 está aprobado todavía -- hay un defecto real de cobertura pendiente de resolver primero.

---

## 2026-08-11 — ESTADOS S1 + ESTADOS S2: calidad del dato vs. trazabilidad del método (NO APROBADO por muestra, código sin commitear)

- **Rama:** `lector-mvp-guia-nueva`. Baseline: `8029ee4` (cierre de O1.2). **Sin commit, sin push** -- los cambios de código quedan en el árbol de trabajo.
- **Decisión de arquitectura que hay que recordar si retomas esto:** un método técnico (geometría, fuzzy, homologación de catálogo, consenso focal) NUNCA debe forzar revisión humana por sí solo. Solo debe forzarla una incertidumbre real -- dato ausente, ambigüedad, conflicto, o falta de una segunda señal independiente que corrobore la recuperación. `atlas_core/procesamiento_masivo.py` ahora separa `motivos_revision_documento` (calidad, explícito) de `metodos_recuperacion_documento` (trazabilidad, informativo) -- ambos nuevos, al final de `COLUMNAS`, compatibles hacia atrás.
- **Por qué quedó "NO APROBADO":** no por un problema del diseño o del código (los 8 tests de casos reales obligatorios pasan, 716 tests verdes, 0 regresiones), sino porque no se pudo completar la validación de escala pedida (30 casos reales revisados) -- el corpus real de 1177 documentos vive en Google Drive externo, no accesible en este entorno; solo hay 46 imágenes reales localmente (de bloques O1/O1.1), y de esas, solo 2 cambiaron de estado bajo la nueva política. Ambas se verificaron visualmente contra la imagen real y son 100% correctas.
- **Hallazgo importante para quien retome esto:** las columnas de trazabilidad (`cliente_fuente`, `obra_destino_fuente`, `chofer_fuente`) del CSV masivo histórico **no son un proxy confiable** de qué causó `indicador_revision` en su momento -- 129 de 144 documentos "OK" originales ya llevaban esas mismas fuentes "geométricas" que se asumía forzaban revisión. No uses esas columnas para reconstruir causalidad histórica sin verificar primero.
- **Por qué el impacto real fue más chico de lo esperado:** `obra_destino` se dejó deliberadamente SIN corroboración (no existe hoy una señal equivalente al RUT de cliente) -- y en la práctica es el motivo de revisión más frecuente en la muestra real disponible. Si se quiere relajar más en el futuro, hay que diseñar primero una señal de corroboración real para destino (no adivinar una).
- **Pendiente real, explícito, para retomar:** conseguir acceso al corpus real completo (o una muestra bastante más grande que 46 imágenes) para completar la validación de 30 relajaciones + reclasificación confiable de los 1177 antes de aprobar este bloque y considerar ESTADOS S3 (migración real de producción). El código ya está listo para esa validación -- solo falta el dataset.
- **¿Listo para S3?** No todavía -- gatillado explícitamente por completar la validación de escala pendiente, no por trabajo de diseño/implementación adicional.

---

## 2026-08-11 — Cierre OPERACIÓN O1.1 + O1.2: corrección dirigida de peso y hora salida

- **Rama:** `lector-mvp-guia-nueva`. Baseline: `4822e9e` (cierre de O1). **Este bloque queda APROBADO y committeado.**
- **Qué pasó:** O1.1 fue una validación ciega independiente (16 guías reales nunca usadas para calibrar O1, predicción congelada antes de mirar imágenes) que encontró O1 **NO APROBADO** por 3 patrones puntuales: (1) el OCR pega a veces un dígito extra al inicio de una hora y el extractor rescataba un sub-match equivocado en vez de abstenerse, a veces incluso fuera de rango (>23); (2) "PESO KG" con una línea intermedia no relacionada rompía la búsqueda; (3) un error de lectura propio del OCR (dígito mal leído) en una guía, no atribuible al extractor. O1.2 corrigió exactamente esos 3 patrones — nada más, sin rediseñar O1, sin tocar Desktop/rutas/Onelogis/catálogos.
- **Si retomas esto, lo importante:** un candidato horario ahora exige que el TRAMO COMPLETO de dígitos/`:` calce con un horario válido (nunca un sub-match dentro de un token corrupto) — la validación de rango (00-23/00-59/00-59) queda garantizada por el propio regex. "PESO KG" ahora busca en una ventana corta (60 caracteres) tras el ancla, aceptando solo si hay exactamente 1 candidato con forma de peso. El caso `464367` (error de OCR puro) se dejó **intencionalmente sin corregir** — no hay señal generalizable para detectarlo sin arriesgar cobertura en otros casos reales; queda documentado como limitación conocida, no oculta.
- **Bug adicional encontrado y corregido en el camino** (no venía en el reporte de O1.1, lo expuso el propio fix): el fallback "asumir entrada == salida cuando no hay otro dato" reutilizaba por error ese valor incluso cuando sí había un dato de salida, pero corrupto. Ojo si tocas `hora_mas_cercana()` de nuevo — la señal que distingue "corrupción real" de "otro número del documento cayendo en la ventana" es la presencia de `:` en el token descartado.
- **Revalidación ciega sobre las mismas 16 guías con el código corregido:** HORA ENTRADA 16/16, HORA SALIDA 14/16 + 2 abstenciones correctas (0 falsos positivos), PESO 15/16 + 1 error OCR documentado (0 falsos positivos del extractor). MULTIGUÍA sigue funcionando bien, incluso recupera una salida abstenida a nivel documento vía el documento hermano del mismo viaje.
- Suite: **691 → 706 tests**. 0 regresiones (verificado también contra la matriz completa de 30 guías de O1, no solo los tests nuevos).
- **Pendiente real, importante, fuera de este bloque:** al intentar reprocesar el "set reciente" de Desktop (2 guías nuevas en `datos/entradas/` de la instalación real, aún no en `viajes.csv`), se descubrió que el CSV masivo de producción (`AppData\Local\Atlas\datos\procesamiento\analisis_completo_guias.csv`, tocado por los commits posteriores de homologación de patentes) tiene una tasa de `indicador_revision="REVISAR"` mucho más alta (1033/1177) que lo que refleja hoy el `viajes.csv` publicado (84/574) — desfase preexistente, no causado por O1.2. Regenerar el reporte completo con el código actual habría marcado ~400 viajes ya confirmados como "requiere revisión" de golpe. **Se detuvo antes de escribir sobre producción** (con confirmación explícita del usuario) y **no se tocó** `viajes.csv` real. Las 2 guías del set reciente sí se reprocesaron y verificaron con éxito (valores idénticos a la validación ciega), y hay un respaldo completo en `backups_reportes/20260811_o1_2_pre_reproceso_reciente/` por si se retoma. **Antes de intentar de nuevo una regeneración completa del reporte de Desktop, hay que decidir qué hacer con ese desfase** (¿re-evaluar los 574 históricos contra el criterio nuevo de homologación de patentes, o dejarlos como están y solo aplicar el criterio nuevo a viajes futuros?).
- **¿Listo para UX-R4?** El código de extracción (peso + horas) sí, con evidencia real de punta a punta. El reporte de producción de Desktop tiene el pendiente de arriba, recomendable resolverlo en paralelo o antes de exponer el reporte al usuario final.
- **Próximo bloque oficial: UX-R4 — integración operacional** (mostrar en Desktop peso, entrada, salida y permanencia). Sigue no iniciado.

---

## 2026-08-11 — Cierre OPERACIÓN O1: peso + hora entrada/salida + permanencia en planta

- **Rama:** `lector-mvp-guia-nueva`. Baseline anterior: `660e5b2f912f9a803c33b94cdb2e60ad98de4293`.
- **Objetivo cerrado:** `peso_kg`, `hora_entrada_aza`, `hora_salida_aza`, `permanencia_minutos` ya llegan hasta `viajes.csv` -- antes se calculaban internamente en `extraer_datos()` pero nunca salían de ahí.
- **Semántica confirmada, importante para quien retome esto:** el campo correcto es **"PESO KG"** (neto operacional), nunca "PESO BRUTO" (camión+carga) -- una versión anterior del extractor usaba BRUTO por error, corregido con evidencia visual directa. `hora_entrada_aza`/`hora_salida_aza` = ingreso/egreso real del camión a AZA (ancla "HORA ENTRADA"/"HORA SALIDA", nunca fecha ni Nro. Transporte).
- **Hallazgo importante sobre el dataset de referencia:** de las 30 guías con ground truth humano usadas para validar (`datos_privados/muestra_fechas_30/`), **6 tenían errores reales de transcripción** (verificados visualmente contra la imagen original antes de aceptar cualquier discrepancia como error de Atlas) -- ver detalle en la bitácora técnica. Si se retoma validación con este dataset, tenerlo presente.
- **Política multi-guía definida con evidencia real (2 transportes, 2 y 3 guías cada uno):** el peso es **parcial por documento** (materiales/códigos distintos) -- se suma a nivel de viaje SOLO si todos los documentos aportan un valor válido. Las horas se consolidan si coinciden entre documentos; si difieren, `CONFLICTO_HORA_ENTRADA`/`CONFLICTO_HORA_SALIDA`, nunca se elige una arbitrariamente. Permanencia se deriva de las horas ya consolidadas.
- **Cruce de medianoche:** nunca se asume +24h automáticamente sin evidencia de fecha -- queda `"No determinada"`.
- **Ausencia de peso/hora nunca invalida un documento por sí sola** -- no participa en `indicador_revision`, decisión explícita para no degradar documentos que antes de este bloque quedaban OK.
- **Contrato de esquema:** `COLUMNAS_OFICIALES` (= `procesamiento_masivo.COLUMNAS`) ahora exige las 4 columnas nuevas como obligatorias en el CSV de entrada de `generar_reporte_viajes()` -- un CSV generado con el pipeline anterior a este bloque debe **reprocesarse** (no puede alimentarse directo), mismo contrato estricto que ya regía para cualquier otra columna oficial.
- **1 valor histórico corregido con evidencia directa:** el fallback hardcodeado de la guía `462491` tenía "12.242,000" (Peso Bruto) en vez de "3.282,00" (PESO KG real). **Los otros 6 fallbacks hardcodeados históricos NO se tocaron** -- sin imagen real disponible en este entorno para verificarlos con el mismo rigor; queda como trabajo pendiente si se consiguen esas imágenes.
- Suite final: **665 → 691 tests** (26 nuevos). 0 regresiones. No se tocó Desktop, ORS, Onelogis, ni `atlas_core/rutas/` (D2/D3/E1 intactos).
- **¿Listo para UX-R3/R4?** Los datos ya llegan completos y consolidados hasta `viajes.csv`, pero dado el hallazgo de errores en el propio ground truth de referencia, se recomienda una ronda adicional de validación visual antes de conectar a Desktop.
- **Próximo bloque oficial: UX-R4 — integración operacional.** Mostrar en Desktop peso, entrada, salida y permanencia, junto con Logística/E1/Rutas cuando estén disponibles. No iniciado.

---

## 2026-08-11 — Cierre ENTREGAS E1: DESPACHAR A como fuente autoritativa de ruta

- **Rama:** `lector-mvp-guia-nueva`. Baseline anterior: `8b59951a9662c88747fa2e09504acbb09a740188`.
- **REGLA DE NEGOCIO OFICIAL, importante para quien retome esto (prevalece sobre D2/D3/D3.1):** la ruta SIEMPRE debe ser `PLANTA ORIGEN → DESPACHAR A`. `SEÑOR(ES)` es solo el comprador; `OBRA DESTINO` es el proyecto/receptor (puede no tener nada que ver con el nombre del comprador); `DIRECCION`/`COMUNA`/`COD DESTINATARIO` identifican el sitio/obra **registrado**, útiles para identidad comercial (D2/D3) pero **nunca** para reemplazar `DESPACHAR A` como destino de ruta. Ver docstring completo en `atlas_core/rutas/destino_entrega.py` y la bitácora técnica para el texto íntegro de la definición de Javier.
- **Auditoría de COMUNA (hecha antes de tocar código de reglas, como se pidió):** el campo `COMUNA` del formulario NO es confiable para entregas interregionales -- sigue mostrando la comuna del sitio registrado, no la real (confirmado con 3 casos reales: Mejillones, Coronel, Ñuble). Decisión: nunca reutilizar `COMUNA` para geocodificar `DESPACHAR A`.
- **Nuevo módulo `atlas_core/rutas/destino_entrega.py`:** `resolver_destino_entrega()` geocodifica `DESPACHAR A` con abstención ante ambigüedad real (nombres de calle homónimos entre comunas/regiones/países) -- pero distingue eso de "varios candidatos que son el mismo lugar" (números de casa vecinos que Pelias no calzó exacto), usando distancia Haversine (margen 1 km) para no abstenerse innecesariamente. `calcular_ruta_entrega_para_viaje()` orquesta planta origen (reutiliza D2 sin cambios) + esta geocodificación + cálculo de ruta directo (**sin caché todavía** -- una entrega no es una entidad de catálogo, ver Fase E de D3.1). Nunca elige el candidato más cercano a una planta AZA.
- **`calcular_ruta_para_viaje` (D2, basada en catálogo) NO se tocó** -- es una función nueva y aditiva; ambos caminos coexisten (identidad/reporte vs. ruta real).
- **Validación real con ORS, caso ejemplo oficial (guía 464170):** AZA RENCA → "AV. ALMTE. LATORRE 843, MEJILLONES" = **1433.2 km / ~24 horas** -- confirma en la práctica que la ruta correcta es radicalmente distinta de lo que el catálogo (Galvarino 8501, ~7 km) habría sugerido. Un segundo caso (Torres Ocaranza) converge con la cifra ya conocida del catálogo (16.73 vs 16.68 km) cuando `DESPACHAR A` y el sitio registrado coinciden -- validación cruzada de que ambos caminos son consistentes quando corresponde. Un tercer caso (Armacero, "Santa Isabel") se abstuvo correctamente por ambigüedad real de geocodificación (nombre de calle común, resultados en Perú/Argentina/Puerto Rico).
- Suite final: **655 → 665 tests** (10 nuevos). 0 regresiones. No se tocó Desktop, ORS (solo lectura/geocodificación ya existente), ni `destinos_maestros.json`.
- **Pendiente real remanente:** el filtro territorial de la geocodificación es solo texto libre ("... , Chile") -- no un filtro de país estricto (`boundary.country`), por eso nombres de calle comunes (p. ej. "Santa Isabel") devuelven resultados internacionales y se abstienen más de lo ideal. Diseñar el catálogo `destino_entrega` (propuesto en D3.1, no implementado) permitiría cachear entregas ya confirmadas en vez de geocodificar en vivo cada vez.
- **Próximo bloque oficial pendiente (registrado desde D3):** OPERACIÓN O1 — PESO + HORA ENTRADA + HORA SALIDA. No iniciado.

---

## 2026-08-11 — Cierre DESTINOS D3.1: auditoría semántica DIRECCION vs DESPACHAR A + revert controlado

- **Rama:** `lector-mvp-guia-nueva`. Baseline anterior: `7c070a81ff4884556625516aae5785744954c93f`.
- **Objetivo cerrado:** auditar si las 4 confirmaciones de D3 eran evidencia de entrega real o solo de un domicilio/sitio registrado del cliente.
- **Hallazgo importante para quien retome esto — DIRECCION ≠ lugar de entrega:** en el formulario AZA, `DIRECCION`/`COMUNA`/`COD DESTINATARIO` identifican el sitio/obra **registrado** contra el que se emite la guía (puede variar entre guías del mismo cliente), mientras que `DESPACHAR A` es el que mejor representa dónde llegó realmente el camión en ese viaje. Con evidencia real (14 guías, 9 con lectura limpia de ambos campos): **~44-50% de divergencia** entre ambos — no es un caso aislado (incluye un caso interregional: Sodimac, Renca vs Coronel). D2 ya protegía el enrutado con `evaluar_concordancia_despacho`; D3.1 confirma que el fenómeno es frecuente, no una excepción rara.
- **2 confirmaciones de D3 revertidas a `PENDIENTE`** (tras confirmación explícita del usuario, respaldo previo verificado): EBEMA SA/Galvarino 8501 (su única guía real con `DESPACHAR A` observado diverge — Mejillones vs Quilicura) y SALOMÓN SACK SA/Camino Los Pinos 3396 (0 evidencia de `DESPACHAR A`, las 3 guías de ground truth usadas en D3 no relevan ese campo). Ninguna dirección/comuna/región/código/coordenada se tocó ni se perdió evidencia — el motivo queda documentado en `observacion`/`fuente` de cada registro.
- **2 confirmaciones de D3 se mantienen, con evidencia reforzada:** ARMACERO MATCO SA/Santa Isabel 585 y ACEROS COX COMERCIAL SA/Camino Lo Ruiz 2901 — ambas con 2 guías reales independientes donde `DESPACHAR A` concuerda exactamente con el destino.
- **Catálogo real ahora:** 47 destinos, **6 CONFIRMADO** / 41 `PENDIENTE`. Respaldo previo al revert: `C:\Users\Jjjc0508\Desktop\Atlas\backups_catalogos\20260811_pre_revert_d31\`.
- **Propuesta de modelo pendiente de decisión (no implementada):** separar `destinos_maestros.json` (sitio/obra registrado) de un futuro catálogo `destinos_entrega` (punto real, ganado solo por `DESPACHAR A` concordante) — diseño documentado en el reporte del bloque, no ejecutado.
- Suite: **655 tests**, sin cambios (este bloque no tocó código ni tests, solo el catálogo real y bitácoras).
- **Próximo bloque oficial: OPERACIÓN O1 — PESO + HORA ENTRADA + HORA SALIDA.** No iniciado.

---

## 2026-08-11 — Cierre DESTINOS D3: confirmación humana asistida de destinos frecuentes

- **Rama:** `lector-mvp-guia-nueva`. Baseline anterior: `54f484f043f203926ce5ad4a56c8babda1e90f89`.
- **Objetivo cerrado:** aumentar destinos `CONFIRMADO` (43 `PENDIENTE`/4 `CONFIRMADO` al empezar) solo con evidencia real, sin bajar el estándar de seguridad de D2.
- **Fuente nueva importante para quien retome esto:** `datos_privados/ground_truth/validacion_atlas_30_guias_v1.xlsx` — 30 guías reales validadas a mano (cliente, RUT, código destinatario, dirección, comuna, ciudad), no usado en bloques anteriores. Requiere `openpyxl` (se instaló en este bloque, agregarlo a dependencias si se automatiza su lectura).
- **Hallazgo relevante:** el ground truth confirma con datos humanos independientes que el mismo cliente+código puede tener direcciones de entrega distintas entre guías (Torres Ocaranza, guías 390486 vs 428701) — refuerza la decisión de D2 de no tratar el código destinatario como llave autónoma.
- **4 destinos confirmados** (criterio: ≥2 documentos independientes concordantes en cliente+dirección+comuna, más estricto que el mínimo pedido): ARMACERO MATCO SA/Santa Isabel 585 (94 viajes históricos), EBEMA SA/Galvarino 8501 (34), ACEROS COX COMERCIAL SA/Camino Lo Ruiz 2901 (20), SALOMÓN SACK SA/Camino Los Pinos 3396 (3, pero 3 guías independientes de ground truth). Catálogo ahora: 8 `CONFIRMADO` / 39 `PENDIENTE`.
- **1 candidato marcado `CORREGIR DATOS` sin tocar todavía:** AMERICAN SCREW CHILE SPA — la dirección en catálogo ("CAMINO A MELIPILA 10800") tiene una probable falta de ortografía (comparado con 2 fuentes reales que muestran "MELIPILLA"/"MELIPELLA") y le faltan coordenadas — no se corrigió en este bloque para no mezclar corrección con confirmación.
- **0 destinos interregionales en el catálogo hoy** (los 47 son RM) — el ground truth reveló viajes reales a Temuco y Coronel que aún no tienen destino en el catálogo. No se fabricó ninguno.
- **Confirmación 100% no destructiva:** verificado campo por campo (test dedicado) que `CatalogoDestinos.editar()` con `modificacion_manual=True` solo cambió `estado_calidad`/`fuente`/`observacion` en los 4 destinos — dirección/comuna/región/código/coordenadas intactos.
- **3 rutas reales desbloqueadas, ORS real:** AZA RENCA→Armacero/Santa Isabel 585 (12.97 km/19.7 min), AZA RENCA→Aceros Cox/Camino Lo Ruiz 2901 (2 guías reales, 0.09 km — domicilios contiguos, resultado real). La guía 464170 (EBEMA, destino ya confirmado) **sigue bloqueada** por el gate de concordancia `DESPACHAR A` de D2 — prueba de que confirmar identidad no relaja la protección por viaje individual.
- Suite final: **643 → 655 tests** (12 nuevos). 0 regresiones. Sin cambios de código de producción — D3 es puramente confirmación de datos usando la maquinaria ya construida en D2.
- **Respaldo antes de tocar el catálogo:** `C:\Users\Jjjc0508\Desktop\Atlas\backups_catalogos\20260811_pre_confirmacion_d3\destinos_maestros.json`, verificado por checksum.
- **Artefactos de esta revisión:** `C:\Users\Jjjc0508\Desktop\Atlas\destinos_revision\` (ranking completo de 47 destinos con evidencia cruzada + 10 fichas de revisión con recomendación individual).
- **Próximo bloque oficial: OPERACIÓN O1 — PESO + HORA ENTRADA + HORA SALIDA.** No iniciado.

---

## 2026-08-11 — Cierre DESTINOS D2: resolución canónica de destino estructurada

- **Rama:** `lector-mvp-guia-nueva`. Baseline anterior: `3f28e4cc6876253dc8a528dbd9ef8651e5daa7e7`.
- **Objetivo cerrado:** la verificación final de rutas del bloque anterior mostró que casi ninguna guía real homologaba destino, porque `obra_destino` (texto OCR, nombre comercial) casi nunca coincide con `nombre_destino` en el catálogo (poblado con direcciones). Este bloque prioriza identificadores estructurados del propio documento (`COD DESTINATARIO`, `DIRECCION`, `COMUNA`) sobre ese emparejamiento textual débil.
- **Nuevo módulo `atlas_core/rutas/destino_estructurado.py`**, no invasivo: `resolver_destino_canonico_estructurado(...)` con jerarquía A (código destinatario) → B (dirección+comuna) → C (alias acotado a cliente) → D (comportamiento histórico global, sin cambios) → abstención. `calcular_ruta_para_viaje` gana 3 parámetros opcionales (`cliente_texto`, `catalogo_clientes`, `rut_cliente_texto`) — sin ellos, comportamiento **idéntico** a antes de este bloque.
- **Corrección de rumbo importante a mitad de bloque (evidencia externa validada con datos propios):** `COD DESTINATARIO` NO es una llave segura por sí sola — el mismo código/cliente puede tener un `DESPACHAR A` (punto de entrega real de ESE viaje) distinto del domicilio registrado. Se agregó `evaluar_concordancia_despacho`: un destino resuelto por identidad se contrasta contra `DESPACHAR A` antes de llamar a ORS; si diverge, `REQUIERE_REVISION`/`DESPACHO_DIVERGENTE_DEL_DESTINO_CANONICO` en vez de una ruta silenciosamente incorrecta.
- **Caso 464170 (el que motivó este bloque) queda cerrado y explicado:** homologa por identidad a EBEMA SA/Galvarino 8501 (Quilicura, RM), pero su `DESPACHAR A` real es Mejillones (Región de Antofagasta, ~1.400 km de distancia) — **no** se calcula una ruta automática para esa guía; queda correctamente en revisión.
- **1 viaje real end-to-end, identidad 100% resuelta por código/dirección/concordancia, sin destino inyectado:** guía 464424, TORRES OCARANZA LTDA (destino ya `CONFIRMADO`) → AZA RENCA → Vista Clara 2351 = **16.68 km / 24.53 min** (ORS real). El `cliente` de esta guía puntual no lo extrae el pipeline (falla preexistente y ajena a este bloque, confirmada con `extraer_datos()` puro); se usó el texto literal que trae el propio documento como diagnóstico, declarado explícitamente como tal.
- Suite final: **629 → 643 tests** (14 nuevos). 0 regresiones.
- **Pendiente real remanente:** la mayoría de destinos reales del catálogo siguen `PENDIENTE` (no `CONFIRMADO`) — bloquean el cálculo de ruta por diseño hasta confirmación humana explícita, no por un límite de este bloque. El extractor lineal de `cliente`/`obra_destino` sigue fallando en algunas guías (ajeno a destinos, requeriría bloque propio). No se tocó ORS, Desktop, ni ningún extractor.

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

## 2026-08-11 — Cierre PLANTA-P1: resolución real de planta origen

- **Rama:** `lector-mvp-guia-nueva`. Baseline anterior: `1a108038fa5a3f7cfe25c13189051980ae8294f9`.
- **Onelogis histórico, IMPORTANTE — no repetir la auditoría desde cero:** Javier confirmó manualmente (cuenta propia, navegación normal) que Onelogis **sí** tiene histórico de viajes/recorridos consultable por fecha. Eso no está en duda. Lo que se auditó y sigue siendo cierto es que **la integración técnica de Atlas** (`Atlas-Viajes-Desktop-Restaurado/src/gps_logic.js` + `main.js`, endpoint propio `.../gps/ultimas-posiciones`) no expone ese histórico — solo última posición. Se buscó también públicamente (sitio `onelogis.com`) sin encontrar documentación de API. **No se intentó** adivinar rutas de endpoint contra el sistema en vivo ni automatizar el navegador de Onelogis (fuera de alcance explícito). Para desbloquear el GPS histórico de verdad hace falta que Javier revise, dentro de su cuenta Onelogis, si existe una sección de API/integraciones/exportación, o contacte a su soporte — eso no es algo que se pueda determinar por auditoría de código.
- **Fallback documental — nuevo módulo `atlas_core/rutas/origen_documental.py`:** adaptación de `_resolver_origen_documental` (rama remota `origin/feature-cobertura-origen-fase1`, commit `2c5c764`, validado 7/9 real). Diferencia clave respecto al original: el original releía un recorte focal del encabezado con `lector.readtext()` de EasyOCR directo (mismo problema de acoplamiento que otros focales ya migrados); la versión nueva opera sobre `textos` de página completa (mismo `texto` que ya produce PaddleOCR en el flujo normal) — no hace falta relectura focal aparte porque Paddle ya lee el encabezado con confianza alta. Conserva intacta la lógica de corte antes de "SUCURSAL" (evita que el directorio de sucursales de toda guía AZA contamine el voto) y la exigencia de planta única sin ambigüedad.
- **`atlas_core/rutas/enriquecimiento_viaje.py`:** `resolver_planta_origen` ahora implementa la jerarquía GPS → documento → no determinado, y devuelve un 4-tuple `(planta, motivo, determinado_por, evidencia)` — **cambio de firma respecto a RUTAS R1** (era 2-tuple); el único call-site externo (un test) se actualizó. Política de conflicto: si el GPS determina una planta, esa gana siempre — el documento solo se consulta cuando el GPS no resuelve nada, nunca para desempatar. Fix defensivo añadido: si la planta determinada no tiene coordenadas cargadas en catálogo, se trata como `ORIGEN_NO_DETERMINADO` (motivo `PLANTA_SIN_COORDENADAS_EN_CATALOGO`) en vez de lanzar una excepción — este caso era real (ver corrección de catálogo abajo).
- **`ResultadoEnriquecimientoRuta`** gana el campo `evidencia_origen` (para GPS: timestamp+distancia a la geocerca; para documento: `"ENCABEZADO_GUIA"`). Propagado también a `reporte_viajes.py` (`COLUMNAS_VIAJES` y `_CAMPOS_RUTA_VACIOS`), backward-compatible igual que el resto de columnas de ruta.
- **Corrección de catálogo (con respaldo previo en `Desktop\Atlas\backups_catalogos\20260811_104321_pre_coordenadas_aza_colina\`):** `AZA COLINA` en `plantas.json` no tenía `latitud`/`longitud` cargadas desde antes de este bloque (bloqueaba cualquier cálculo de ruta real con ese origen, incluso con la planta ya determinada). Se completó reutilizando la coordenada ya geocodificada vía ORS para la misma dirección física (presente en `destinos_maestros.json` bajo "ACEROS AZA SA", ya usada como workaround en RUTAS R1) — `lat=-33.137558, lon=-70.665977` (ORS fallback, confidence 0.6, nivel calle/comuna, documentado así en la observación del registro). Editado vía `CatalogoPlantas.editar()` (API validada, no edición JSON manual), verificado releyendo desde disco tras escribir.
- **Validación real (12 guías AZA reales disponibles hoy, PaddleOCR real):** el set histórico original de 9 guías (`464089`, `462429`, `464106-464110`, `464259`) **no está disponible como archivo de imagen en este equipo** — se usó el set real actualmente accesible en `output/_entrantes_desktop` (12 guías, todas AZA, todas con "CASA MATRIZ PLANTA RENCA" legible en el encabezado real). Resultado: **11/12 resueltas correctamente a AZA RENCA, 1/12 (`464493.jpeg`) se abstuvo en vez de arriesgar** — causa diagnosticada: en esa guía específica, Paddle leyó "Sucursal" como "ursal"/"Cursal" (perdió el prefijo "Su"/"S"), fuera de la tolerancia de edición-1 + diferencia de longitud ≤1 del corte — el corte nunca se activó, "COLINA" del directorio de sucursales quedó en el texto comparado, y al aparecer junto con "RENCA" generó ambigüedad real (2 coincidencias) → abstención correcta, no un bug. **0 asignaciones incorrectas.**
- **Fase E, conectado a ORS real + caché real:** AZA RENCA (documento, guía real `464170`) → Torres Ocaranza Ltda = **16.68 km / 24.53 min** (coincide exactamente con el mismo par calculado en RUTAS R1 vía GPS inyectado — buena señal cruzada). AZA COLINA (documento, patrón real de encabezado AZA) → Prodalam SA = **41.31 km / 47.35 min**. Repetir el primer par → `RESULTADO_DESDE_CACHE`, mismo resultado, 0 llamadas nuevas a ORS.
- Suite final: **618 → 629 tests** (10 nuevos en Fase F + 1 test defensivo de la Fase E). 0 regresiones.
- **0 secretos**: verificado con `grep` sobre todos los artefactos de `rutas_eval/` antes de commitear.
- **Próximo bloque, si se decide perseguir GPS histórico real:** que Javier confirme desde su cuenta Onelogis si existe una vía de API/exportación oficial. Sin eso, el mecanismo documental ya implementado es la vía de producción para AZA RENCA (validada); ampliar la validación real a más guías de AZA COLINA (solo se probó con patrón sintético, no con una imagen real de guía Colina — no había ninguna disponible en este equipo) sigue pendiente.

---

## 2026-08-11 — Cierre RUTAS R1: km/tiempos conectados al viaje + auditoría Onelogis

- **Rama:** `lector-mvp-guia-nueva`. Baseline anterior: `5f201d418a3fcd6ee1287d1e05b1335efe87e043`.
- **Auditoría Onelogis, importante para quien retome esto:** la integración GPS/Onelogis real vive en `Atlas-Viajes-Desktop-Restaurado/src/gps_logic.js` (función `obtenerUltimasPosicionesGps`, consumida por `main.js` vía IPC `atlas:gps-obtener-posiciones`, configurada en `gps_config.json`/electron-store con `url`+`apiKey`). Devuelve un array `vehiculos` con `{patente, estado, latitude, longitude, speed, timestamp}` — **solo la última posición conocida de cada patente**, refrescada cada 30s mientras la pestaña GPS del Desktop está abierta. **No existe ningún endpoint ni archivo en todo el repo/backup que exponga histórico de posiciones por fecha/hora.** Esto es estructural: para una guía ya procesada (workflow normal, no en tiempo real), no hay forma de consultar "dónde estaba la patente X cuando salió" con la integración actual. Confirmado también que la documentación propia del proyecto (`docs/CATALOGO_TRANSPORTISTAS_ATLAS.md`) ya marca cualquier ampliación de Onelogis como sujeta a autorización + auditoría de privacidad independiente.
- **Nuevos módulos (`atlas_core/rutas/`):**
  - `posicion_vehiculo.py`: contrato `ProveedorPosicionVehiculo` (`obtener_posicion(patente, instante) -> ResultadoPosicionVehiculo`) + doble simulado `ProveedorPosicionVehiculoSimulado` (mismo patrón que `ProveedorRutasSimulado`). **No hay adaptador real** todavía — no existe capacidad histórica real contra la cual conectarlo.
  - `geocerca.py`: `resolver_planta_por_posicion(posicion, plantas, radio_km)` — distancia Haversine, radio conservador `1.5 km` (propuesto, no calibrado contra datos reales — no existen posiciones históricas reales para calibrarlo). AZA Renca/Colina están a decenas de km entre sí (confirmado con ORS real), por lo que este radio nunca genera ambigüedad entre ambas.
  - `enriquecimiento_viaje.py`: orquestador `calcular_ruta_para_viaje(...)` = destino canónico (`resolver_destino_canonico`, reutiliza `CatalogoDestinos.buscar()` ya existente sobre `destinos_maestros.json`, exige `ACTIVO` + coordenadas dentro de un rango geográfico plausible de RM `lat∈[-34.5,-32.5], lon∈[-71.5,-70.0]` — excluye de forma general, no por nombre, los registros "SAN MIGUEL" con coordenada errónea de RUTAS-EVAL R1) → planta de origen (`resolver_planta_origen`, exige GPS dentro de geocerca **y** timestamp a menos de 2h del instante de salida, si no: `ORIGEN_NO_DETERMINADO`) → `ServicioRutas.confirmar_y_calcular(perfil="driving-hgv")` ya existente (caché incluido). Nunca lanza: cualquier fallo en cualquier paso devuelve campos vacíos + `estado_ruta`/`motivo_ruta` explicativos.
- **`atlas_core/rutas/modelos.py`:** 2 estados nuevos en `EstadoRuta`: `ORIGEN_NO_DETERMINADO`, `DESTINO_NO_VALIDO`.
- **`atlas_core/reporte_viajes.py`:** `COLUMNAS_VIAJES` gana 10 columnas al final (`planta_origen_id`, `planta_origen_nombre`, `destino_id`, `destino_nombre`, `distancia_km`, `duracion_min`, `proveedor_ruta`, `estado_ruta`, `motivo_ruta`, `origen_determinado_por`); `generar_reporte_viajes()` gana un parámetro opcional `calculador_rutas: Callable[[Viaje], dict] | None = None` — sin él (default), columnas vacías, reporte idéntico a antes de este bloque. Desktop **no se tocó**.
- **Validación real (catálogo activo real, `%LOCALAPPDATA%\Atlas\datos\catalogos_privados`, ORS real, `driving-hgv`), 3 viajes:**
  1. **EBEMA SA / Galvarino 8501**: planta AZA RENCA determinada (posición GPS **inyectada/simulada** para esta prueba — ver nota abajo), destino homologado, pero `ServicioRutas` bloquea correctamente con `REQUIERE_REVISION`/`DESTINO_NO_CONFIRMADO` porque el destino real de EBEMA sigue `estado_calidad=PENDIENTE` en el catálogo — **no se fuerza ni se relaja esa salvaguarda ya existente**.
  2. **Torres Ocaranza Ltda / Vista Clara 2351** (destino `CONFIRMADO`): AZA RENCA → **16.68 km / 24.53 min**, `RUTA_CALCULADA`. Repetir la misma consulta (otra "guía", mismo transporte/destino/perfil/proveedor/versión) → `RESULTADO_DESDE_CACHE`, mismo resultado, **0 llamadas nuevas a ORS**.
  3. **Mismo destino que el viaje 2, patente sin dato GPS**: `ORIGEN_NO_DETERMINADO`/`GPS_SIN_DATOS`, sin llamar a ORS, viaje sigue válido.
- **Nota sobre "planta detectada por GPS" en la prueba real:** dado que no existe consulta histórica real (ver auditoría), el viaje 2 usa una posición GPS **inyectada** (coordenada real de AZA Renca, marcada explícitamente como `simulado_demo_geocerca`) para demostrar que el mecanismo de resolución completo (geocerca → ServicioRutas → caché) funciona correctamente de punta a punta con datos reales de catálogo y ORS real — **no** es una determinación en tiempo real de dónde estuvo un camión histórico. Para eso hace falta el siguiente bloque.
- Suite final: **603 → 618 tests** (15 nuevos: 13 en `test_rutas_enriquecimiento_viaje.py`, 2 en `test_reporte_viajes.py`; 1 assertion existente en `test_rutas_modelos.py` actualizada para los 2 estados nuevos). 0 regresiones.
- **0 secretos**: verificado con `grep` sobre `rutas_eval/*.json` y `viajes.csv` de prueba antes de commitear.
- **Siguiente bloque obligatorio: PLANTA-P1 / ONELOGIS.** Antes de mostrar km/min automáticos en Desktop hace falta: (a) confirmar con Onelogis si existe o puede habilitarse un endpoint histórico de posiciones por patente+fecha/hora (hoy no existe en la integración auditada), o (b) definir una estrategia alternativa de determinación de planta (p. ej. evidencia documental — existe un resolver `_resolver_origen_documental` con 7/9 de cobertura real en la rama remota no fusionada `origin/feature-cobertura-origen-fase1`, ver nota técnica). Sin uno de los dos, `planta_origen` seguirá cayendo mayormente en `ORIGEN_NO_DETERMINADO` para guías procesadas después del hecho — correcto y seguro, pero no automático.

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
## Estado vigente — INFRAESTRUCTURA S2.2 (2026-08-13)

**INFRAESTRUCTURA S2.2: NO CERRADO.**

Todo salvo un bloqueo quedó auditado:

- Motor `lector-mvp-guia-nueva` en `d5098e5`, alineado con remoto; **927/927 tests**.
- Desktop local preservado en `9622981`; **110/110 tests** con `npm.cmd test`; no publicar esta línea como reemplazo.
- Importación casa→Drive: **17/17 archivos coinciden por SHA-256**. Inventario post-importación regenerado con **23 filas** en `G:\Mi unidad\Atlas\respaldos\importacion_casa_s2_2_20260813_151013\inventario_post_importacion.csv`.
- `ATLAS_DATA_DIR`, catálogos y `estado_operacion.json` funcionan contra `G:\Mi unidad\Atlas`.
- Sin eliminaciones; se preservaron histórico, respaldo, AppData, ambos repos y todos sus `.git`.
- La configuración persistida de Desktop sigue usando rutas locales existentes de casa. No migrarla manualmente: la convergencia portable pertenece al cambio autoritativo perdido.

Único bloqueo y siguiente acción: recuperar en el PC de oficina el repo `Desktop\MBT\Proyecto\Atlas-Viajes-Desktop` con el commit local `4b94a38`. Transportar el objeto Git o un bundle verificable (preferible a reconstruir a mano), confirmar el SHA completo y su base, ejecutar `npm.cmd test`, inspeccionar el diff y solo entonces publicar normalmente `fix-desktop-data-root-drag-drop`. Si no puede recuperarse exactamente, mantener S2.2 como **NO CERRADO**. Nunca force-push ni sustituirlo por `9622981`.

No iniciar OPERACIÓN REAL R2 como parte de este cierre.

> **Estado supersedido:** ya no se necesita recuperar `4b94a38`; el resultado funcional fue reconstruido, probado y publicado desde casa.

## Cierre vigente — INFRAESTRUCTURA S2.2 (2026-08-13)

**INFRAESTRUCTURA S2.2: CERRADO. LISTO PARA OPERACIÓN REAL R2: SÍ. R2 aún no iniciado.**

- Motor: `lector-mvp-guia-nueva`, `d5098e5`; contrato portable publicado y Drive validado.
- Desktop: `fix-desktop-data-root-drag-drop`, `859d6bf440fddc925118fa172efe174b6ab75ad6`, publicado en el remoto oficial y limpio.
- Desktop resuelve `ATLAS_DATA_DIR`, lee exclusivamente el manifiesto vigente, rechaza escapes fuera de raíz, no cae al histórico y migra configuración legacy de reporte/catálogos conservando respaldo.
- Pruebas Desktop: **126/126**. Validación real: operación actual visible desde `G:\Mi unidad\Atlas\reportes\actual`; dataset y `viajes.csv` accesibles; histórico no usado.
- Importación canónica: 17/17 hashes coincidentes; inventario post-importación de 23 archivos. Secretos permanecen locales y no fueron incorporados al código ni a la configuración portable.
- Limpieza automática no pudo materializarse: la política del entorno bloqueó todos los borrados antes de ejecución. Los candidatos demostrados están enumerados en la bitácora técnica; ningún archivo fue eliminado.
- Para iniciar R2: partir de estos dos HEAD remotos y de la operación vigente del manifiesto. No reprocesar las 19 guías como parte de infraestructura.

# Checkpoint vigente — OPERACIÓN REAL R2 (2026-08-13)

- Código Motor publicado: rama `lector-mvp-guia-nueva`, integración READ-ONLY obra↔destino en `e822b2d` (historia R2 relevante: `4532744` → `3454384` → `e822b2d`).
- Modelo obra↔destino V1 activo: cuatro relaciones confirmadas por decisión humana explícita; procesamiento estrictamente de lectura y con abstención conservadora.
- Dataset operacional canónico: `ATLAS_DATA_DIR/operacion/actual/analisis_completo_guias.csv`, 19 guías, **7 OK / 12 REVISAR**, SHA-256 `A18CE354659D790B37115CD8CA20A662F28258AA4D001319F3FEB55EDAD9F67A`.
- Respaldo reversible anterior: `ATLAS_DATA_DIR/respaldos/R2_PRE_PROMOCION_2026-08-13_20260813_212500`, SHA-256 del CSV `915939141F8A914B8FAA38860E5F5314DF051D532BE692F64E62F4B04E2A330D`.
- `reportes/actual` y `operacion/actual/estado_operacion.json` fueron regenerados desde el nuevo dataset. El reporte agrupa las 19 guías en 15 viajes: 5 confirmados y 10 que requieren revisión.
- Pendientes, sin iniciar: obra sin corroborar (10), patente sin homologar (6), cliente nuevo no catalogado (4), cliente sin corroborar (2), material ausente (1).
- Validación: 0 errores técnicos, 0 regresiones, **987 passed / 0 failed**. Portabilidad casa/oficina: Git para código y Drive bajo `ATLAS_DATA_DIR` para estado operacional.

# Estado vigente — R2 Vehículos V1 promovido (2026-08-13)

- Motor: `lector-mvp-guia-nueva`, HEAD publicado `5296ff96a064b527334a082b526c7eaef7c65eb5`, árbol limpio y local/remoto `0/0`; suite **1019 passed, 0 failed**.
- Vehículos V1: 17 identidades `CONFIRMADO + ACTIVO`; cinco altas humanas nuevas y una ratificación legacy registradas por la API oficial desde decisiones explícitas de `JAVIER_MBT`. SHA-256 canónico: `0E522AF5A517DD4AC692C45F14C637519D20BFF90110BF8AD46F87E03626AF66`.
- Dataset operacional promovido: 19 guías, **9 OK / 10 REVISAR**, 0 errores y 0 regresiones; SHA-256 `516A9D5EA8E6632416EB5418756ACB081323FAD66C87D2956B5B28AFCF8A4FFF`. Nuevas OK: 464577 y 464640.
- Rollback: dataset anterior `A18CE354659D790B37115CD8CA20A662F28258AA4D001319F3FEB55EDAD9F67A` respaldado byte a byte en `ATLAS_DATA_DIR/respaldos/R2_PRE_PROMOCION_VEHICULOS_V1_2026-08-13_20260813_225023`.
- `reportes/actual` y `operacion/actual/estado_operacion.json` fueron regenerados exclusivamente desde el dataset promovido. Desktop devuelve `OPERACION_ACTIVA`, encuentra dataset y `viajes.csv`, no cae al histórico y puede consumir las nuevas guías.
- Pendientes actuales: `OBRA_DESTINO_SIN_CORROBORAR` (10), `CLIENTE_NUEVA_ENTIDAD_NO_CATALOGADA` (8), `CLIENTE_SIN_CORROBORAR` (2) y `MATERIAL_AUSENTE` (1). El siguiente cuello de botella de mayor impacto es obra/destino sin corroborar.
- Deuda baja separada: reparar de forma auditable el mojibake de observaciones humanas y mover `telemetria_cache.json` fuera de la fuente `--catalogos`. No corregir ninguno mezclándolo con cambios operacionales.
