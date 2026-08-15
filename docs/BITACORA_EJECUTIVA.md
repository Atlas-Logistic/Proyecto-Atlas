# Bitácora Ejecutiva — Proyecto Atlas

Registro de alto nivel de los bloques de trabajo cerrados sobre el lector de guías. Un párrafo por bloque, orientado a decisión y estado, no a implementación.

---

## 2026-08-14 — R2 CERRADO: lote controlado 19/19

- Se publicó el cierre funcional `093cce923d172cac18cafb5b453c0cef8de95242` (`feat: corroborar clientes por rut maestro`), aprobado por auditoría Claude. La geometría `SEÑOR(ES)↔R.U.T.` usa tolerancias relativas y el Motor corrobora identidad por RUT exacto contra clientes confirmados y activos en `clientes.json`; `empresas.json` se conserva como fallback compatible. Las guías `464534` y `464535` quedaron resueltas sin hardcode y sin sustituir el texto documental.
- El dataset operacional pasó de `17 OK / 2 REVISAR` (SHA-256 `B84FD7DB0D7391D93B47B4F5ACA3E4641468CC30374FFC23FD840824A4A62E43`) a `19 OK / 0 REVISAR` (SHA-256 `3DF7C5BB88FE5C9DEE2CAA14EEBB885DB5A14C90EB1F80989F19536697D87A4B`), con cero regresiones. Respaldo completo: `respaldos/R2_PRE_PROMOCION_FINAL_19_19_2026-08-14_20260814_115726_-0400`.
- `19/19` significa que los 19 documentos del lote controlado R2 no tienen motivos bloqueantes; no significa que todos los campos opcionales estén poblados. Sigue registrado `MATERIAL_AUSENTE` no bloqueante en `464699`, faltan peso/dirección en `464601`, varias direcciones y algunas horas.
- La consolidación oficial produjo 15 viajes: 13 confirmados y 2 en revisión por conflictos entre documentos. Motor `1044 passed, 0 failed`; Desktop `126 passed, 0 failed`, `OPERACION_ACTIVA`, sin fallback histórico.
- Deuda baja, deliberadamente no abordada: corregir un comentario con mojibake y endurecer conservadoramente el fallback exacto por nombre cuando no hay RUT. Siguiente frente recomendado: consolidación inteligente de viajes.

---

## 2026-08-14 — R2 OBRAS: siete relaciones confirmadas y operación promovida a 17/19

- Se cerró la auditoría Claude del modelo obra↔destino y se publicó el commit funcional `c02aa31ba5044b39a33c8101feea529cbece9f22` (`feat: robustecer identidad canonica de obras`). La nueva API `actualizar_identidad_obra` preserva ID, cliente, estado e historial, usa bloqueo/escritura atómica y rechaza aliases vacíos, colisiones y confirmaciones humanas usadas incorrectamente como evidencia de identidad. La normalización sólo compacta siglas realmente puntuadas (`S.A.`), sin fusionar letras independientes.
- Quedaron confirmadas por `JAVIER_MBT` siete relaciones operacionales: DEMO→Poeta Pedro Prado 1548; Torres Coronel→Av. Forestal M1 1014; Terratec→Maestra Lidia Torres 92; Level→Av. Lo Blanco 2389; Ignacio Hurtado→Pdte. Riesco 5903; OCL→Catedral 759; EBCO→Av. 4 Norte 1565. Se crearon seis destinos y se reutilizó el destino de Level; no se registraron los errores OCR `758` ni `A65`.
- El dataset canónico pasó de `9 OK / 10 REVISAR` (SHA-256 `516A9D5EA8E6632416EB5418756ACB081323FAD66C87D2956B5B28AFCF8A4FFF`) a `17 OK / 2 REVISAR` (SHA-256 `B84FD7DB0D7391D93B47B4F5ACA3E4641468CC30374FFC23FD840824A4A62E43`), con ocho nuevas OK (`463594`, `463630`, `464588`, `464601`, `464624`, `464698`, `464699`, `464700`) y cero regresiones. Respaldo: `respaldos/R2_PRE_PROMOCION_OBRAS_17_19_2026-08-14_20260814_110939_-0400`.
- Se regeneraron los artefactos oficiales en `reportes/actual` y se publicó `operacion/actual/estado_operacion.json`. Atlas Desktop confirmó `OPERACION_ACTIVA`, dataset/reporte vigentes y ausencia de fallback histórico; suite Desktop `126/126`. Suite Motor final `1027/1027`.
- Único cuello de botella documental restante: guías `464534` y `464535`, ambas por `CLIENTE_SIN_CORROBORAR | OBRA_DESTINO_SIN_CORROBORAR`. Próximo bloque: diagnóstico conservador de `CLIENTE_SIN_CORROBORAR`, sin forzar identidad.

---

> **Actualización posterior:** el cierre reconstruido y publicado al final del archivo reemplaza este registro provisional y la auditoría intermedia del commit perdido.

## 2026-08-13 — INFRAESTRUCTURA S2.2: registro provisional (supersedido por la auditoría final)

- **Se encontró el repo real de Atlas Desktop** (no estaba donde S2.1 asumía): un clon local con remoto oficial en GitHub (`Atlas-Logistic/Atlas-Viajes-Desktop`) en `C:\Users\corte\Desktop\MBT\Proyecto\_build-atlas-desktop-1.2.0-oficina\`, y una copia local más avanzada (3 commits sin publicar) dentro de la carpeta histórica que dejó S2.1 en Drive. Ambas apuntan al mismo linaje real de commits -- se combinaron en una copia de trabajo local nueva y ordenada (`Desktop\MBT\Proyecto\Atlas-Viajes-Desktop\`, fuera de Drive, tal como exige la arquitectura "código = Git").
- **Decisión permanente, ahora en código en ambos repos:** Desktop y motor comparten el mismo contrato portable. `ATLAS_DATA_DIR` resuelve la raíz igual que en el motor (mismo orden de prioridad, mismo criterio de autodetección de Drive), con un respaldo adicional propio de Desktop (una configuración local mínima que guarda solo la raíz) para el caso en que Electron, lanzado desde un acceso directo o el instalador, no herede variables de entorno del shell.
- **Nuevo manifiesto compartido `operacion/actual/estado_operacion.json`** (documentado en ambos repos): el motor lo publica al generar un reporte dentro de la raíz portable; Desktop lo lee para saber cuál es el reporte vigente, sin depender de "la carpeta con timestamp más reciente" (que podría escoger un reporte incompleto) y sin caer nunca, bajo ninguna circunstancia, en el histórico preservado por S2.1.
- **Configuración legacy de otro PC ya no se usa en silencio:** si `config_usuario` de Desktop tiene una ruta que no existe en la máquina actual o que pertenece a otra raíz (el caso real encontrado: rutas `C:\Users\Jjjc0508\...` del PC de casa), se respalda automáticamente (nunca se borra) y se reemplaza por el equivalente derivado de la raíz portable.
- **Bloqueo real y transparente, no maquillado:** este PC/entorno no tiene Node.js instalable, así que no se pudo ejecutar la suite de Desktop (110 tests previos + 16 nuevos) ni abrir Electron para una validación visual. El trabajo quedó completo y comiteado localmente, sin publicar (push) hasta confirmar los tests en verde -- ver `coordinacion\PENDIENTE_PC_CASA.md` en Drive para el paso exacto pendiente.
- Motor: suite completa 916 → **927 tests**, sin regresiones (todo lo tocado del lado Python se pudo ejecutar y verificar normalmente).

---

## 2026-08-13 — INFRAESTRUCTURA S2.1: Google Drive pasa a ser la raíz operativa real de Atlas entre casa y oficina, y una auditoría previa evitó mezclar dos historias de datos incompatibles

- **Decisión permanente de arquitectura, ahora en código y documentada:** código = GitHub; estado operativo portable (catálogos privados, caché de geocodificación/telemetría, reportes, respaldos) = una única raíz `Atlas\` sincronizada por Google Drive; secretos = variables de entorno locales, nunca Drive ni Git. El objetivo práctico -- `git pull` → abrir Atlas → trabajar, sin copiar CSV/catálogos/cachés a mano entre PCs -- ya funciona en la oficina.
- **La auditoría previa a mover nada encontró que la carpeta `Atlas` ya existente en Drive NO era una raíz limpia, sino el resultado de una sesión de incidente del 2026-08-10/11** (rollback/reinstalación de Atlas Desktop, evaluación de motores OCR): contenía dos copias completas de repos Git (el motor y Atlas Desktop), dos entornos virtuales de Python (uno con CUDA/GPU completo) y al menos cuatro versiones distintas de `analisis_completo_guias.csv` sin reconciliar -- una de 1.178 filas / 574 viajes (histórico experimental) y otra mucho más pequeña y más reciente. **Se decidió explícitamente NO promover ninguna de esas versiones históricas a "operación vigente"** -- se preservaron todas (sin borrar nada) en `historico_pre_infra_s2\`, con una nota explicando por qué.
- **Se encontró y migró el catálogo privado realmente vivo de esta oficina** (`AppData\Local\Atlas`, con manifiesto propio de hashes SHA-256 del 2026-07-30, ya con una política de versionado inmutable diseñada antes de este bloque) hacia la nueva raíz de Drive -- verificado byte a byte contra sus hashes originales antes de darlo por bueno. No se usó ninguno de los catálogos de los snapshots del incidente.
- **Caché ORS/Pelias implementada por primera vez:** hasta ahora Onelogis tenía caché propia pero ORS repetía llamadas de geocodificación idénticas en cada ejecución. Ahora una dirección ya geocodificada en cualquiera de los dos PCs queda disponible para el otro sin gastar una llamada nueva -- probado con una demostración instrumentada (cache hit real contado en código, sin gastar ninguna llamada externa nueva) contra la ruta real de Drive.
- **Pendiente real, explícito y acotado** (`coordinacion\PENDIENTE_PC_CASA.md` en Drive): confirmar si el catálogo de casa tiene ediciones posteriores al 2026-07-30 y traerlas con la misma disciplina de hashes; el código fuente de Atlas Desktop no se tocó en este bloque (la única copia disponible no tiene remoto Git configurado) -- queda como bloque separado.
- Suite completa: 892 → **916 tests**, sin regresiones.

---

## 2026-08-12 — INTELIGENCIA N1: Atlas deja de tratar el OCR como verdad literal -- y aparece un bug real propio, encontrado y corregido en el camino

- **Principio nuevo, ahora en código:** VALOR OCR ≠ VALOR NORMALIZADO ≠ VALOR CANÓNICO CORROBORADO. Un typo de comuna (CAUQUBNES/CADQUENES) o una razón social deformada (SOC CONETRUCTORA OCL LIMITAD) ya no se publican tal cual ni se "corrigen" a ciegas -- se comparan contra un catálogo territorial cerrado de las 345 comunas de Chile y contra un vocabulario acotado de formas societarias reales, y solo se normalizan cuando hay un candidato único con margen claro. Ambos casos reales del bloque quedan resueltos: **CAUQUBNES y CADQUENES → Cauquenes** (Región del Maule), **SOC CONETRUCTORA OCL LIMITAD → SOC CONSTRUCTORA OCL LIMITADA**.
- **Encontramos y corregimos tres bugs reales de extracción**, no solo de normalización: un RUT de cliente perfectamente legible se perdía por un margen geométrico demasiado estricto entre filas de un formulario apretado; un RUT de chofer terminado en "K" quedaba truncado antes del dígito verificador (perdiendo la corroboración contra un chofer que sí estaba en catálogo); y un RUT de cliente válido, junto a un nombre bien leído, no tenía ninguna vía de corroboración por similitud de nombre (solo existía para chofer). Los tres ya estaban afectando la tanda real, en silencio.
- **Un cliente real (EBEMA SA) se estaba mostrando con DOS nombres corruptos distintos** en dos guías del mismo envío (EDMA SA / KBEMA SA) -- ambos ahora corrigen al nombre real por RUT exacto, y esa corrección queda "aprendida": la próxima vez que aparezca cualquiera de esas dos variantes OCR, Atlas la reconoce de inmediato sin tener que volver a calcularla (aprendizaje controlado, nunca automático sobre algo ambiguo).
- **Autocrítica real, no cosmética:** la primera versión de la normalización de comunas tenía un umbral demasiado permisivo -- corrompía la palabra real "CAMINO" (de una dirección) en la comuna real "Camiña", y "PARQUE" en "Pirque". Se encontró validando el propio bloque contra la tanda, antes de cerrar -- se subió el umbral y se agregó una lista de palabras de dirección que nunca se tratan como comuna, sin importar la similitud.
- Suite completa: 872 → **892 tests**, sin regresiones de comportamiento.

---

## 2026-08-12 — PATENTES P4: una patente perfectamente legible se estaba perdiendo por un bug de asociación, no de OCR -- y aparece otro caso real de Renca-que-era-Colina

- **El diagnóstico de Javier era correcto y el nuestro estaba equivocado:** la guía 464631 mostraba "patente ausente" pese a que DD2494/JB8529 están impresos con total claridad. PaddleOCR SÍ los leyó bien -- el problema era que el extractor "geométrico" de patentes en realidad no era geométrico: concatenaba todo el texto de la zona en una sola cadena y buscaba por regex, así que cualquier segundo texto de 6 caracteres en la zona (aunque estuviera lejos de la etiqueta PATENTE) producía una abstención total por "ambigüedad". Se reescribió para asociar cada etiqueta a su valor por posición real en la imagen, igual que ya hacían el resto de los extractores del documento.
- **Dos variantes reales de error de OCR, ahora toleradas de forma general (no solo para esta guía):** la etiqueta CARRO se leyó "CARR0" (cero por O) en 464631, y la etiqueta RETIRA se leyó "RETRA" (falta la "I") en otra guía de la misma tanda (464550) -- ambas bloqueaban toda la extracción antes de este fix. También se agregó recuperación geométrica del RUT del chofer, que se perdía por el mismo motivo que ya se había corregido para DESPACHAR A en un bloque anterior (columnas del documento intercaladas por el orden de lectura del OCR).
- **464631 ya está resuelto correctamente:** tracto DD2494, rampla JB8529, RUT del chofer recuperado -- y con la patente disponible, la telemetría GPS pudo correr y confirma **AZA COLINA**, coincidiendo con lo que Javier y el chofer ya sabían.
- **Al revisar la misma tanda reciente por el mismo patrón (sin reprocesar histórico), apareció un segundo caso real con el mismo problema de fondo:** la guía 464550 tampoco tenía patente (BPHR67, perfectamente legible) por el bug de "RETRA". Al recuperarla, la telemetría también pudo correr por primera vez para esa guía -- y **también confirma AZA COLINA**, no AZA RENCA como mostraba el documento. Ninguna de las dos correcciones fue forzada: ambas se confirmaron con evidencia GPS real, con la misma lógica de ventana horaria del bloque anterior.
- Suite completa: 872 tests (11 nuevos), sin regresiones de código -- 4 tests existentes se ajustaron mecánicamente para incluir un campo (RUT del chofer) que antes no formaba parte de sus datos de prueba.

---

## 2026-08-12 — ORIGEN O2: la planta se determina por dónde estuvo cargando, no por dónde pasó -- y aparece un hallazgo mayor sobre AZA Renca

- **La pregunta correcta, ya resuelta en código:** Atlas ya no pregunta "¿qué plantas visitó este camión hoy?" -- pregunta "¿en qué planta estuvo cargando durante la ventana de horas de ESTA guía?". Un camión puede pasar cerca de dos plantas en un mismo día; solo la que coincide en el tiempo con la carga cuenta como evidencia real. **464424 (el caso más difícil, señalado por Javier) ya muestra AZA COLINA** -- se encontró que el camión hizo una parada real de 48 minutos en Colina justo durante la ventana de la guía, mientras que su cercanía a Renca esa mañana fue solo un cruce a más de 60 km/h por la carretera, nunca una detención real.
- **Segundo hallazgo técnico real:** un viaje registrado por Onelogis puede contener una parada real de varios minutos EN EL MEDIO de un trayecto más largo (el motor nunca se apaga) -- Atlas antes solo miraba si el viaje completo estaba detenido de punta a punta, y se perdía estas paradas. Ahora agrupa los puntos GPS reales por cercanía en tiempo y espacio (usando también la velocidad reportada, cuando está disponible) para encontrarlas donde sea que ocurran.
- **Hallazgo mayor, más allá del alcance original de este bloque:** al aplicar esta lógica a las 10 guías que quedaron en conflicto en el bloque anterior, TODAS resultan en una detención real en Colina, mientras que la evidencia "Renca" de cada una resultó ser, sistemáticamente, un cruce a alta velocidad por la carretera cercana -- nunca una parada real. Esto incluye viajes que se habían dado por confirmados en Renca desde los primeros bloques de telemetría de esta sesión. **Esto no se aplicó a ciegas a toda la operación** -- se consultó primero, y se investigó con evidencia real (velocidad GPS punto por punto) antes de aceptar la conclusión.
- **Pregunta abierta para un bloque futuro, NO resuelta aquí:** ¿la geocerca de AZA RENCA necesita el mismo tipo de corrección que tuvo Colina (un polígono real, no un punto con radio chico), o los camiones de esta tanda real genuinamente no cargan en Renca? Se decidió no tocar la geocerca de Renca en este bloque -- la corrección de O2 es sobre lógica temporal, no sobre geografía.
- Suite completa: 849 → **861 tests**, sin regresiones.

---

## 2026-08-12 — PLANTAS P3: AZA Colina ya es un recinto real, no un punto en el mapa -- y aparece un hallazgo nuevo que requiere revisión de Javier

- **La corrección central:** Atlas ahora puede modelar una planta como un RECINTO (polígono real), no solo como un punto con un radio chico. AZA Colina se corrigió con el perímetro real donde AL1879 estuvo detenido 6 horas (los mismos datos de T3) -- **464641/464642 ya muestran "AZA COLINA" confirmada por GPS**, exactamente lo que Javier confirmó viendo el recinto completo en Onelogis (acceso, estacionamientos, oficinas, zonas de carga). AZA Renca no se tocó -- sigue funcionando exactamente igual (punto + radio, como siempre).
- **Separación importante:** la coordenada antigua de AZA Colina (la de la dirección de texto, ya demostrada ~18 km lejos del recinto real) se dejó *sin tocar* -- sigue siendo la dirección de referencia. Para calcular rutas se agregó un "punto de acceso" nuevo, real (validado contra la vía pública real que pasa junto al recinto), separado del polígono y de la dirección -- una ruta calculada hoy desde AZA Colina ya parte desde ahí, no desde un punto a 18 km de distancia.
- **Hallazgo nuevo, honesto, que requiere que Javier revise:** al aplicar el polígono a TODA la tanda reciente, aparecieron **10 guías que antes confirmaban "AZA Renca" limpio y ahora quedan en conflicto explícito** (Renca vs. Colina) -- esos camiones también registran paradas reales de una o más horas en el mismo lugar donde estuvo AL1879, en fechas distintas. Puede ser que esos transportes también pasen por AZA Colina como parte de su ruta real, o puede ser un punto de espera/consolidación compartido junto al cruce de la Panamericana -- Atlas no lo inventa ni lo fuerza a ninguna de las dos plantas: lo deja como conflicto explícito, visible, para que se revise con evidencia adicional (no oculta el problema para "que se vea prolijo").
- Suite completa: 837 → **849 tests**, sin regresiones.

---

## 2026-08-12 — TELEMETRÍA T3: Atlas ahora entiende "detenido" además de "en movimiento" -- y encontró una tercera planta AZA

- **Lo que Javier tenía razón en señalar:** el vehículo SÍ estuvo detenido varias horas en un lugar real durante la ventana de carga -- Atlas antes solo miraba puntos GPS sueltos dentro de una ventana horaria estrecha (anclada en una sola de las dos horas del documento) y nunca consideraba los huecos entre viajes cortos como evidencia de una permanencia real. Corregido: Atlas ahora reconoce cuándo un vehículo estuvo parado en un mismo lugar durante horas (aunque no haya GPS registrado momento a momento durante esa permanencia) y usa AMBAS horas del documento (entrada y salida) para acotar la búsqueda, no solo una.
- **El hallazgo real, verificado dos veces de forma independiente:** el lugar donde el vehículo (patente AL1879) estuvo detenido más de 6 horas ese día -- solapando casi todo el rango documental -- geocodifica como **"Gerdau Aza, Lampa"**. Gerdau es la empresa matriz de Aceros AZA. Todo indica una TERCERA planta AZA real, en la comuna de Lampa, que hoy no está en el catálogo de Atlas -- ni Renca ni Colina, un lugar distinto de ambas (18 km de Colina, 12,5 km de Renca). Por decisión explícita, **no se agregó todavía al catálogo** -- se necesita confirmar la dirección exacta antes de darla de alta como planta oficial.
- **Resultado para 464641/464642 (el caso que señaló Javier):** ya no muestra "AZA Renca" (el bug de origen documental que quedaba vivo) -- ahora muestra honestamente que hubo una detención real de 6+ horas en un lugar conocido pero no catalogado, con la coordenada y duración visibles para revisión. Nunca inventa "Colina" (no hay evidencia de que ese lugar sea Colina) ni vuelve a "Renca" por default.
- **El mecanismo SÍ sabe confirmar Colina cuando la evidencia real cae ahí** -- validado con datos de prueba. El motivo por el que este caso puntual no muestra Colina es que la detención real está en otro lugar (Lampa), no una limitación del algoritmo.
- **Efecto adicional, no buscado pero real:** al corregir el uso de ambas horas documentales, 2 guías que antes quedaban sin planta confirmada (464534/464535) ahora sí la tienen -- evidencia que ya estaba disponible pero la ventana anterior no alcanzaba a mirar.
- Suite completa: 825 → **837 tests**, sin regresiones.

---

## 2026-08-12 — OPERACIÓN REAL R1.1: sin confirmación GPS, ya no se muestra ninguna planta por defecto

- **El bug real que quedaba de R1:** cuando la telemetría corría con datos reales y no lograba confirmar una planta única (ni Renca ni Colina), el sistema seguía mostrando en silencio "AZA RENCA" -- el valor que salía de leer el encabezado impreso de la guía, que dice lo mismo en todas las guías AZA sin importar la planta real de despacho. Corregido: ahora, si la telemetría corrió sobre datos reales y no confirma ninguna planta, el origen queda explícitamente "no determinado" -- nunca Renca por default. Si no hay telemetría conectada en absoluto, el comportamiento de siempre no cambia (no hay ninguna señal GPS real con la que reemplazarlo).
- **Los dos controles positivos que Javier señaló, con la evidencia real revisada a fondo (varios días, sin filtrar por distancia):** la guía 464424 (patente SB6486) muestra, de forma repetida en 2 días distintos, el camión pasando a menos de 1,2 km de AZA RENCA -- y nunca a menos de 17 km de AZA COLINA. La evidencia GPS real, tal como está disponible hoy, indica RENCA para esta guía específica, no Colina -- esto contradice lo que Javier recuerda haber visto, y se reporta así de frente, sin forzar ni el uno ni el otro: puede que la guía/patente/fecha que Javier tiene en mente no sea exactamente esta, vale la pena confirmarlo con él directamente. Las guías 464641/464642 (patente AL1879), en cambio, no muestran evidencia GPS cerca de NINGUNA de las dos plantas en 2 días completos revisados -- antes de este bloque mostraban "AZA RENCA" igual (por el bug de arriba); ahora muestran correctamente "origen no determinado", sin inventar ninguna de las dos.
- **Efecto sobre la tanda operativa reciente (19 guías reales):** 6 guías que antes mostraban "AZA RENCA" sin confirmación GPS real ahora muestran honestamente "origen no determinado" -- ninguna cambia a Colina, porque ninguna tiene evidencia GPS real que lo sustente hoy. El resto (incluidas 464424, 464698-700, y las guías previas) mantienen o mejoran su confirmación por GPS real.
- **Geocercas de Renca y Colina: se auditaron de nuevo con la evidencia real recolectada, siguen correctas -- no se tocaron.**
- Suite completa: 818 → **825 tests**, sin regresiones.

---

## 2026-08-12 — OPERACIÓN REAL R1: la planta de origen ya no se lee del papel, se lee del GPS

- **Decisión de negocio confirmada en código:** la guía NO trae la dirección de la planta de origen -- el encabezado impreso de AZA dice "CASA MATRIZ PLANTA RENCA" en TODAS las guías, sin importar desde qué planta salió realmente el camión ese día. Antes de este bloque, Atlas confiaba en ese encabezado como si fuera confiable; ahora la planta de origen se determina primero por GPS/geocercas (Onelogis + catálogo de plantas), y el documento solo se usa como respaldo cuando no hay evidencia GPS disponible.
- **Causa raíz real, no cosmética:** no era un bug de prioridad (GPS ya ganaba al documento cuando corría) -- era que el GPS casi nunca llegaba a correr sobre el origen real. Se corrigió para que, con telemetría conectada, la resolución de origen por GPS se intente siempre que haya patente/fecha/hora, en una ventana horaria amplia (±4h) que sí capta viajes cortos de maniobra dentro/fuera de una planta -- antes esos viajes cortos quedaban descartados por el mismo filtro pensado para el tramo de entrega larga.
- **Geocercas auditadas:** las coordenadas de AZA RENCA y AZA COLINA en el catálogo están correctas y confirmadas por el usuario -- no se tocaron. Se investigó honestamente una posible discrepancia de nomenclatura ("Panamericana Norte 18500" vs. "Av. Pdte. Eduardo Frei Montalva 18500" para Colina): ambas direcciones probablemente describen el mismo corredor físico, pero el geocodificador no tiene precisión de numeración para confirmarlo con certeza -- se documenta el hallazgo, no se cambia una coordenada ya confirmada por el usuario.
- **Resultado real sobre la tanda operativa nueva (7 guías: 464631, 464640, 464641, 464642, 464698, 464699, 464700):** con la evidencia GPS real disponible hoy, **ninguna de estas 7 guías cambia de Renca a Colina** -- el transporte VP8521 (464698-700) confirma AZA RENCA por GPS (coincide con el documento, ahora con evidencia real en vez de una lectura de encabezado); los transportes TG8925 (464640) y AL1879 (464641-642) no tienen evidencia GPS suficientemente cercana a ninguna planta ese día y quedan honestamente sin determinar (se conserva el valor documental, sin inventar una confirmación); 464631 no tiene patente legible, no se puede evaluar por GPS. Esto no invalida la sospecha de Javier sobre otras guías -- solo confirma que, para estas 7 específicas, la evidencia GPS disponible no prueba un cambio.
- **Bug real encontrado y corregido de paso:** en 2 de las 7 guías (464631, 464641), DESPACHAR A se estaba llenando con un RUT ("14293816-2") en vez de la dirección real -- la extracción lineal absorbía el valor de otro campo. Corregido de forma general (cualquier valor que sea íntegramente un RUT válido se descarta y se recupera la dirección real por posición en la imagen), verificado con las imágenes reales: ambas guías ahora muestran la dirección de entrega correcta.
- Se conectó telemetría al flujo real que usa Atlas Desktop (antes solo existía en scripts de prueba) -- de aquí en adelante, cualquier guía nueva que ingrese por Desktop se beneficia automáticamente de esta corrección, sin pasos manuales.
- Datos reales reprocesados con respaldo previo (las 9 guías del dataset operacional: las 7 nuevas + las 2 ya conocidas de bloques anteriores, que se confirman sin cambios). Suite completa: 806 → **818 tests**, sin regresiones.

## 2026-08-12 — E2E R2: la logística real ya llega a la pantalla, sin construir nada nuevo

- **Qué se confirmó:** todo lo que se construyó en los bloques anteriores (ruta real, GPS, telemetría) ya llegaba solo hasta el reporte que usa Atlas Desktop -- no hizo falta escribir código nuevo, solo verificarlo con datos reales y dejar la operación al día.
- **Qué se ve ahora en Desktop, con datos reales, sin ningún ajuste manual:** para la guía a Coronel -- Planta origen AZA Renca, distancia 536,7 km, tiempo estimado 10 h 07 min, estado "Ruta calculada". Para la otra guía -- planta confirmada, pero distancia y tiempo quedan honestamente "No disponible" con el motivo real, porque la dirección de entrega sigue siendo ambigua y el sistema no inventa una respuesta.
- **Costo:** cero consultas nuevas a Onelogis para regenerar estos dos viajes -- toda la información ya estaba en caché de los bloques anteriores.
- **Nada técnico (identificadores de viaje GPS, puntos del recorrido) se muestra en pantalla** -- eso queda interno, tal como se pidió.
- Suite completa del motor (806 tests) y de Desktop (110 tests) verdes.

---

## 2026-08-12 — TELEMETRÍA T2: selección automática de recorrido GPS, sin intervención manual por guía

- **Qué resolvía:** en el bloque anterior (T1), corroborar planta y desambiguar destino con GPS funcionaba, pero solo analizando a mano cuál viaje de Onelogis correspondía a cada guía -- no era todavía algo que Atlas hiciera solo.
- **Qué se hizo:** un algoritmo que, dada la patente y la hora real de entrada/salida de planta que ya trae el documento, encuentra automáticamente el recorrido GPS correcto -- incluso cuando el viaje real quedó dividido en varios tramos por el proveedor de GPS (como pasó con la guía a Coronel: el camión aparece en 3 tramos distintos ese día, y el sistema los reconoce y los une solo, sin que nadie le diga cuáles son).
- **Resultado real, sin tocar nada a mano:** la guía a Coronel ahora calcula su ruta real automáticamente -- **536,7 km, 10 horas 7 minutos aproximados** -- exactamente igual que cuando se probó a mano en el bloque anterior, pero esta vez el sistema lo encontró solo. La otra guía (con dirección dentro de Santiago) sigue honestamente "requiere revisión": el GPS ayuda a descartar candidatos claramente equivocados, pero no alcanza para elegir con certeza entre los que quedan -- y el sistema no fuerza una elección sin evidencia suficiente.
- **Sigue siendo opcional:** sin configurar telemetría, Atlas funciona exactamente igual que antes. Cuando está conectada, solo se usa cuando realmente hace falta (planta sin confirmar, o destino ambiguo) -- no se consulta por cada guía sin motivo.
- Suite completa (806 tests) y Desktop verdes, sin regresiones.

---

## 2026-08-12 — TELEMETRÍA T1: primera integración real con GPS histórico (Onelogis)

- **Decisión:** telemetría GPS es un proveedor opcional y multiempresa -- Onelogis es el primer adaptador conectado, nunca una dependencia obligatoria del núcleo. Si Onelogis no responde o no hay credencial, Atlas sigue funcionando exactamente igual que hoy.
- **Qué se hizo:** se conectó, con la API real de Onelogis (autenticada, credencial nunca expuesta), el historial GPS de los dos camiones de las guías operacionales actuales (463594/463630, 27-07-2026) -- vehículos, viajes del día y el recorrido real punto por punto.
- **Resultado real:** el recorrido GPS confirma que ambos camiones efectivamente pasaron por la planta AZA Renca ese día (corrobora lo que ya decía el documento). Para la guía 463630, el punto final real del recorrido permitió resolver una ambigüedad que la geocodificación por sí sola no podía: el documento menciona "Coronel", y Chile tiene dos lugares con ese nombre (uno en la Región del Biobío, otro en la Región del Maule) -- el GPS confirma que el camión terminó en el de Biobío y descarta el otro (a más de 470 km de distancia). Con eso, se pudo calcular la ruta real: **536,7 km / 606,9 minutos**, ahora visibles en el reporte operacional.
- Para la guía 463594, el GPS descartó un candidato claramente incorrecto (a 473 km) pero no alcanzó para elegir entre los 4 restantes, todos dentro de Santiago y muy cercanos entre sí -- se mantuvo honestamente "requiere revisión", sin forzar una elección sin evidencia suficiente.
- Se implementó una caché local para no volver a pagar la misma consulta histórica cada vez que se abre Atlas Desktop.
- Suite completa (787 tests) y Desktop (105 tests) verdes, sin regresiones.

---

## 2026-08-12 — PRODUCCIÓN P1: punto de partida limpio para operación real

- **Decisión de producto:** los 574 viajes publicados hasta hoy fueron un corpus de prueba durante el desarrollo, no un histórico operacional real -- se dejan de lado sin invertir más tiempo en migrarlos o reclasificarlos uno a uno. Cierra la línea de trabajo de migración (ESTADOS S3/S3.1) sin completarla; el análisis ya hecho queda guardado como referencia, no se pierde.
- **Qué se hizo:** se preservó ese histórico intacto (movido, no borrado, verificado byte a byte) a una carpeta claramente etiquetada como experimental. Se creó un reporte operacional nuevo, vacío salvo por las dos únicas guías reales que ya existían para pruebas de validación -- reprocesadas con el motor actual completo (peso, horas, estados, identidad corregida).
- **Resultado inicial honesto:** 2 viajes, ambos marcados "requiere revisión" con la razón explícita de cada uno -- no se ajustó el resultado para que se vea mejor, es el estado real de esos documentos.
- **Desde hoy (2026-08-12),** cada guía nueva que se procese en Atlas Desktop alimenta este reporte operacional nuevo, con el esquema y las reglas actuales -- nunca se mezcla automáticamente con el histórico de pruebas.
- El histórico sigue disponible para consulta manual si hace falta (Atlas Desktop ya sabe leer reportes con esquema anterior, campo por campo faltante se muestra como "No disponible").
- Producción real intacta y verificada; suite completa (742 tests) sin cambios, todos verdes.

---

## 2026-08-12 — ESTADOS S3: migración controlada del dataset productivo -- simulación APROBADA, migración diferida (decisión de negocio)

- Se respaldó íntegramente el reporte productivo actual (574 viajes) y se generó, sin tocar producción, un candidato completo con la semántica corregida de todos los bloques anteriores (O1, E1, S2, S2.2, I1).
- **Resultado de la simulación: 73 confirmados / 503 requieren revisión** (de 576 viajes) -- consistente con lo ya anticipado en el diagnóstico ESTADOS S1: el reporte que hoy usa Desktop (490 confirmados / 84 en revisión) se generó **antes** de que el sistema propagara correctamente la revisión de documento a viaje, así que nunca reflejó ese volumen real de incertidumbre.
- **Validación exhaustiva antes de proponer el cambio:** se verificaron con datos reales 30 viajes que pasarían de "confirmado" a "requiere revisión" -- los 30 tienen una causa real y verificable (un dato faltante, un documento degradado, o una contradicción real entre documentos del mismo transporte). **0 cambios incorrectos.**
- **Se consultó antes de escribir producción**, dado que el cambio implica que ~417 viajes que hoy aparecen "confirmados" pasarían de golpe a "requieren revisión" -- un volumen de trabajo operativo grande para el día a día. **Decisión: no migrar todavía.** El candidato queda validado y disponible (`estado_revision_eval/s3/simulado/`) para cuando se decida absorber ese volumen.
- Producción **no fue modificada**. Respaldo verificado byte a byte disponible para cualquier necesidad futura.
- Hallazgo adicional real, documentado aparte: una guía del histórico aparece duplicada 3 veces en el CSV productivo (misma guía, fotos distintas, con datos inconsistentes entre copias) -- no se corrigió en este bloque, queda como trabajo futuro.

---

## 2026-08-12 — IDENTIDAD I1: auditoría de normalizaciones hardcodeadas -- APROBADO (cierra la serie ESTADOS S2)

- Se auditaron todas las reglas del extractor base que podían reemplazar silenciosamente la identidad de un cliente, chofer o destino por coincidir con una palabra clave (SIGRO, AMERICAN SCREW, POCURO, PRODALA/PRODALAM, ACMA, y un RUT de chofer sin ninguna justificación en el código). **14 reglas en total, confinadas a un único archivo** (`atlas_core/extractor.py`) -- 6 se retiraron, 8 se conservaron con evidencia real de que hacen falta.
- **Confirmado con la imagen real:** la guía 383295 ahora extrae correctamente "CONSTRUCTORA SIGRO SA" (lo que el documento realmente dice), en vez del nombre fijo "EMPRESA CONST SIGRO" que la regla imponía antes -- y queda marcada para revisión humana con el motivo explícito correspondiente, en vez de aparecer confirmada en silencio.
- **Hallazgo adicional real:** el mismo RUT (93.772.000-9) aparece con nombres distintos en dos catálogos internos (uno lo llama "PRODALAM SA", el otro "EMPRESA CONST SIGRO") -- una inconsistencia de datos real, documentada pero no corregida en este bloque (no se autorizó tocar catálogos).
- **Validación real, sin reprocesar el corpus completo:** 9 documentos reales verificados de forma focal (no 196, no 1172), más las 5 relajaciones ya conocidas de bloques anteriores. Un caso (guía 464493) pasó de "confirmado" a "requiere revisión" tras el arreglo -- no es un error: el valor sigue siendo correcto, simplemente ahora se declara honestamente que llegó por un camino que necesita corroboración, en vez de esconder esa incertidumbre detrás del atajo que se acaba de retirar.
- **0 identidades incorrectas encontradas** en toda la validación real de este bloque.
- Suite completa: 730 → 742 tests, todos verdes, 0 regresiones (se protegió explícitamente un test histórico real que dependía de una de las reglas conservadas).
- **Veredicto: APROBADO.** Cierra la serie completa ESTADOS S2 → S2.1 → S2.2 → IDENTIDAD I1.
- Producción intacta durante todo el bloque. **Este bloque sí generó commit** (ver detalle técnico).

---

## 2026-08-11 — ESTADOS S2.2: cubrir enriquecimiento de catálogo -- NO APROBADO, la causa raíz real era otra (CERRADO)

- Se implementó y probó (14 tests nuevos, 730 verdes en total) la cobertura de `enriquecer_datos_con_catalogos()` dentro del modelo de calidad/trazabilidad: cliente y chofer confirmados por catálogo solo cuando el RUT calza exacto (corroboración fuerte, sin revisión); obra destino, en cambio, **nunca** queda confirmado en silencio solo porque el catálogo sugirió un nombre -- si cambia el valor, siempre pide revisión, tenga o no el documento su propio valor de destino.
- **Al revalidar con datos reales el caso que motivó este bloque (guía 383295), se descubrió que el diagnóstico anterior estaba equivocado.** El problema no viene del enriquecimiento por catálogo -- viene de una regla mucho más antigua, ya existente en el extractor base, que reemplaza automáticamente cualquier destino que contenga la palabra "SIGRO" por un nombre de empresa fijo, sin verificar si es la empresa correcta. Ese reemplazo ocurre antes de que cualquier lógica de este bloque (o del anterior) tenga oportunidad de intervenir.
- **No se corrigió esa regla bajo presión** -- está fuera del alcance de "cubrir enriquecimiento de catálogo" que se pidió para este bloque, y correrla sin evidencia amplia sería exactamente el tipo de parche apresurado que este proceso está diseñado para evitar. Se documenta como hallazgo y se recomienda un bloque dedicado.
- **Veredicto: NO APROBADO.** El trabajo pedido para este bloque se completó correctamente (y quedó probado), pero no resuelve el caso real que lo originó -- ese caso necesita su propio bloque, con su propio análisis.
- Producción intacta. Sin commit ni push.

---

## 2026-08-11 — ESTADOS S2.1: validación a escala sobre corpus real -- NO APROBADO, defecto real encontrado (CERRADO, detenido para S2.2)

- **Se localizó el corpus real completo** que generó el reporte productivo (`G:\Mi unidad\MBT\informe lunes`, 1172 de 1177 imágenes, 99.6% de cobertura) -- no vive en este equipo, solo en Google Drive, y nunca se había usado hasta este bloque.
- Se procesaron **150 documentos reales nuevos** con el motor S2 (sumados a los 46 ya validados en el bloque anterior, 196 en total). Resultado: **solo 4 relajaciones reales** (REVISAR -> confirmado) en los 196 -- una tasa (~2%) que hace **estructuralmente inalcanzable** la meta de 30 relajaciones, incluso si se hubiera procesado el corpus completo.
- **Se encontró un defecto real:** de las 4 relajaciones, **3 son correctas** (verificadas contra la imagen) pero **1 no lo es** -- un documento quedó "confirmado sin revisión" con un destino de entrega inventado que no corresponde al campo real (en blanco) de la guía. La causa **no está en la lógica nueva de este bloque**, sino en un mecanismo de enriquecimiento por catálogo que ya existía antes y que nunca quedó cubierto por el sistema de motivos/métodos -- puede cambiar cliente, destino, chofer o patente sin dejar ningún rastro de revisión, ni en el código viejo ni en el nuevo.
- **Siguiendo la instrucción explícita de este bloque, no se intentó corregir el defecto bajo presión** -- se documenta y se detiene para un bloque dedicado (ESTADOS S2.2).
- **Veredicto: NO APROBADO.** No es una cuestión de volumen de muestra (eso ya se resolvió, se accedió al corpus real) sino de un defecto de cobertura real encontrado -- exactamente el tipo de hallazgo que este bloque estaba diseñado para detectar antes de tocar producción.
- Producción (`viajes.csv`, `analisis_completo_guias.csv`) **no fue tocada**. Suite: 716 tests, todos verdes. Sin commit ni push.

---

## 2026-08-11 — ESTADOS S1 (diagnóstico) + ESTADOS S2 (calidad del dato vs. método): NO APROBADO por criterio de muestra, código listo

- **Decisión de arquitectura registrada:** Atlas separa la **calidad del dato** (¿requiere revisión humana, y por qué?) de la **trazabilidad del método** (¿cómo se obtuvo el valor?). Usar geometría, fuzzy, catálogos u otros métodos técnicos **no implica por sí solo** revisión humana -- solo la implica una incertidumbre real: dato ausente, ambigüedad genuina, conflicto entre documentos, o una recuperación sin una segunda señal independiente que la corrobore (RUT válido para cliente/chofer, catálogo para patente, consenso de múltiples lecturas para transporte/fecha/guía).
- **ESTADOS S1 (diagnóstico):** encontró que el reporte productivo (574 viajes, 490 confirmados) quedó congelado el 2026-07-28, **un día antes** de que el motor empezara a propagar la revisión de documento a viaje -- explica la mayor parte del desfase frente al CSV masivo actual (1177 documentos, 1033 en revisión). Mezcla real de revisiones legítimas (~73% de una muestra representativa) y sobremarcado técnico (~27%).
- **ESTADOS S2 (corrección):** implementado y testeado -- una patente homologada de forma determinista contra catálogo, un chofer con RUT que coincide en catálogo, o un número de guía/transporte/fecha recuperado con consenso de múltiples lecturas, ya no fuerzan revisión solo por el método. Lo que sí se sigue exigiendo sin excepción: un dato realmente ausente, una ambigüedad real, un conflicto entre documentos del mismo viaje, o una recuperación sin corroboración disponible (el destino de entrega, por ejemplo, se mantuvo deliberadamente conservador -- no existe hoy una señal de corroboración equivalente al RUT).
- **Validación real:** de las 46 guías reales ya conocidas de bloques anteriores (con imagen disponible localmente), solo 2 pasaron de "requiere revisión" a "confirmado" bajo la nueva política -- ambas verificadas visualmente contra la imagen real, 100% correctas. El impacto práctico resultó más modesto de lo esperado porque el destino de entrega (mantenido conservador a propósito) es, en la práctica, el motivo de revisión más frecuente.
- **Hallazgo relevante:** las columnas de trazabilidad del CSV masivo histórico (usadas en el diagnóstico de S1) resultaron **no ser un proxy confiable** para reconstruir qué causó la revisión en su momento -- intentar reclasificar los 1177 documentos existentes con esas columnas habría dado un número sin sustento real. Se documentó esta limitación en vez de presentar una cifra poco confiable como si fuera precisa.
- **Veredicto: NO APROBADO**, estrictamente por no alcanzar la muestra mínima de 30 casos reales revisados (solo 2 disponibles localmente -- el resto del corpus real vive fuera de este entorno). El código y los 8 tests de los casos reales obligatorios (más 10 tests existentes actualizados) están completos, verdes (706 -> 716 tests, 0 regresiones), y verificados sin ningún error en la muestra real disponible -- pero no se commiteó ni se sugiere migrar producción todavía, a la espera de completar la validación de escala con acceso al corpus real completo.
- Producción (`viajes.csv` de 574 viajes) **no fue tocada** en ningún momento de este bloque.

---

## 2026-08-11 — OPERACIÓN O1.1 (validación ciega) + O1.2 (corrección dirigida): peso + hora salida (CERRADO, APROBADO)

- **O1.1 (validación ciega independiente, sin cambios de código):** se corrió el pipeline real sobre 16 guías nunca usadas para calibrar reglas de O1 (14 conocidas + 2 genuinamente nuevas), congelando la predicción ANTES de mirar cualquier imagen. **Veredicto: O1 NO APROBADO** — 3 patrones reales de falla: (1) el OCR a veces pega un dígito extra al inicio de una hora ("112:15:18"), y el extractor "rescataba" un sub-tramo con forma válida pero equivocada en vez de detectar la corrupción; en un caso además emitía una hora inválida fuera de rango ("29:55"); (2) "PESO KG" con una línea no relacionada intercalada antes de su valor real rompía la búsqueda; (3) un error de lectura del propio motor OCR (un dígito mal leído) en una guía, ajeno al extractor.
- **O1.2 (corrección dirigida, exclusivamente estos 3 patrones):** hora — un candidato horario ahora debe calzar COMPLETO (nunca un sub-match) con un patrón que ya exige rango válido 00-23/00-59/00-59 estructuralmente; ante corrupción, el sistema prefiere abstenerse a inventar un valor. Peso — la búsqueda de "PESO KG" ahora tolera una línea intermedia dentro de una ventana corta y controlada, exigiendo un único candidato con forma de peso (ambigüedad → abstención, nunca se elige al azar). El error de OCR puro (guía `464367`) se dejó **deliberadamente sin corregir** — documentado como limitación conocida, sin inventar reglas específicas de archivo ni usar el valor real para "reparar" el OCR.
- **Durante la implementación se encontró y corrigió un bug adicional** (expuesto por el propio fix, no reportado por O1.1): el mecanismo que asume "hora entrada = hora salida" cuando genuinamente no hay otro dato, reutilizaba por error ese mismo valor incluso cuando sí existía un dato de salida, pero corrupto — convirtiendo un valor incorrecto en otro valor incorrecto distinto. Corregido antes de cerrar el bloque, verificado sin regresiones sobre la muestra de 30 guías de O1 (resultado idéntico antes/después).
- **Revalidación ciega sobre las mismas 16 guías, con el código ya corregido:** HORA ENTRADA 16/16 exacto (100%). HORA SALIDA 14/16 exacto + 2 abstenciones correctas donde antes había 2 valores incorrectos (0 falsos positivos, 100% de precisión sobre lo emitido). PESO 15/16 exacto + 1 error de OCR puro documentado (0 falsos positivos atribuibles al extractor, 100% de precisión propia). Política **MULTIGUÍA** re-verificada con los 2 transportes reales, sigue funcionando correctamente — incluso recupera automáticamente una hora de salida abstenida a nivel documento usando el documento hermano del mismo viaje.
- **Veredicto: O1.2 APROBADO.** Suite automatizada: 691 → 706 tests, todos verdes, 0 regresiones (verificado también sobre la matriz completa de 30 guías de O1, no solo los tests unitarios).
- **Reproceso del set reciente de Desktop:** se identificaron y reprocesaron con éxito las 2 guías reales aún no reflejadas en el reporte de producción (resultado idéntico a la validación ciega, confirmando determinismo). Se tomó respaldo completo antes de cualquier cambio. **La regeneración completa de `viajes.csv` en producción se detuvo** al descubrir un desfase preexistente y ajeno a este bloque: el CSV masivo (actualizado por trabajo posterior de homologación de patentes) marca muchos más documentos "requiere revisión" que el reporte publicado hoy — sobrescribir habría reclasificado ~400 viajes ya confirmados sin que fuera parte del objetivo de este bloque. El archivo de producción **no fue modificado**; queda como trabajo de seguimiento explícito, separado de O1.2.
- **¿Listo para UX-R4?** El código de extracción (peso + horas) queda robusto y validado con evidencia real de punta a punta. El reproceso completo del reporte de producción de Desktop queda pendiente de una investigación aparte (desfase de `indicador_revision` post-homologación de patentes) — no bloquea UX-R4 en sí, pero se recomienda resolverlo antes o en paralelo para que el reporte que verá el usuario final sea consistente.

---

## 2026-08-11 — OPERACIÓN O1: peso + hora entrada/salida + permanencia en planta (CERRADO)

- **Objetivo:** extraer de forma confiable, persistir y propagar `peso_kg`, `hora_entrada_aza`, `hora_salida_aza` y `permanencia_minutos` desde la guía real hasta `viajes.csv`. Estos campos ya se calculaban internamente en `extraer_datos()` desde bloques anteriores, pero nunca salían de ahí — no llegaban ni al CSV masivo ni al reporte.
- **Semántica de PESO confirmada con evidencia real (30 guías, visual + cruzada):** el campo correcto es **"PESO KG"** (peso neto operacional de la carga) — nunca "PESO BRUTO" (camión + carga). Una versión anterior del extractor priorizaba BRUTO por error; corregido con evidencia directa (guía 464170/462491: Peso Bruto=12.242,000 vs PESO KG real=3.282,00, confirmado contra la imagen).
- **Hallazgo relevante — calidad del ground truth:** de las 30 guías usadas para validar, **6 tenían errores reales de transcripción humana** en el propio dataset de referencia (copiar valores de la fila vecina, omitir un campo legible marcándolo "ilegible", un archivo mal indexado al número de guía equivocado) — todos detectados y corregidos verificando visualmente la imagen original antes de aceptar cualquier discrepancia como error de Atlas.
- **Resultado de extracción tras las correcciones:** peso ~26/30 exacto (el resto, abstención segura ante OCR degradado — nunca un valor inventado), horas ~28-29/30 exacto (limitado por confusiones de un solo dígito del propio OCR, no por el algoritmo).
- **Política de peso/horas multi-guía, definida con evidencia real (2 transportes reales con 2 y 3 guías):** cada documento trae el peso **parcial** de su propia línea de carga (materiales distintos) — se suma a nivel de viaje solo si todos los documentos aportan un peso válido. Las horas de entrada/salida se consolidan cuando coinciden entre documentos del mismo transporte (caso real: 3 guías, misma hora exacta); si difieren, se marca `CONFLICTO_HORA_ENTRADA`/`CONFLICTO_HORA_SALIDA` y nunca se elige una arbitrariamente.
- **Permanencia** = hora salida − hora entrada, en minutos, consolidada a nivel de viaje. Un cruce de medianoche sin evidencia de fecha nunca se asume automáticamente (+24h) — queda "No determinada" con motivo trazable.
- Ausencia de peso/hora **nunca** invalida un documento por sí sola — no participa en `indicador_revision`.
- Validación automatizada: **691 tests**, todos verdes (665 → 691, 26 nuevos). 0 regresiones.
- **No listo para UX-R3/R4 todavía:** los datos ya llegan completos hasta `viajes.csv` con política multi-guía verificada, pero antes de conectar a Desktop conviene una ronda de validación visual adicional (muestra más amplia) dado el hallazgo de errores en el propio ground truth de referencia.
- **Próximo bloque oficial: UX-R4 — integración operacional (mostrar en Desktop peso, entrada, salida y permanencia junto con Logística/E1/Rutas).**

---

## 2026-08-11 — ENTREGAS E1: DESPACHAR A como fuente autoritativa de ruta (CERRADO)

- **Decisión de arquitectura/producto (definida por Javier, prevalece sobre inferencias anteriores de D2/D3/D3.1):** la ruta logística siempre debe ser `PLANTA ORIGEN → DESPACHAR A`, nunca `PLANTA ORIGEN → dirección del cliente/sitio registrado`. `SEÑOR(ES)` es el comprador, `OBRA DESTINO` es el proyecto/receptor comercial (puede tener un nombre completamente distinto del comprador, sin exigir coincidencia), y `DIRECCION`/`COMUNA`/`COD DESTINATARIO` identifican el sitio/obra **registrado** contra el que se emite la guía — útiles para identidad comercial y recurrencia, pero **nunca** deben reemplazar `DESPACHAR A` como destino de una ruta. Caso ejemplo oficial: guía 464170, `DESPACHAR A`="AV. ALMTE. LATORRE 843, MEJILLONES" — la ruta correcta termina ahí, no en Galvarino 8501 (Quilicura).
- **Auditoría de COMUNA (requisito explícito antes de implementar cualquier regla)**, 14 guías reales: el campo `COMUNA` del formulario coincide con la comuna real de entrega solo cuando la entrega cae dentro de la misma comuna/región que el sitio registrado; en los 3 casos de entrega interregional observados siguió mostrando la comuna del sitio registrado, no la real. **Conclusión operacional: nunca reutilizar `COMUNA` para geocodificar `DESPACHAR A`** — se geocodifica el texto crudo de `DESPACHAR A` directamente.
- **Implementado:** nuevo módulo de geocodificación de `DESPACHAR A` con abstención (`REVISAR`) ante ambigüedad real — pero distinguiendo, con evidencia real, entre "varios candidatos que son el mismo lugar" (números de casa vecinos sobre la misma calle) y "ubicaciones genuinamente dispersas" (calles homónimas entre comunas/regiones/países) — solo la segunda se marca `REVISAR`. Nunca elige el candidato más cercano a una planta AZA.
- **Validación real con ORS:** el caso ejemplo (464170) ahora calcula una ruta real de **1433.2 km / ~24 horas** hacia Mejillones — completamente distinta de lo que el catálogo (Galvarino 8501, ~7 km) habría sugerido, confirmando en la práctica por qué esta regla de negocio es necesaria. Un segundo caso (Torres Ocaranza) confirma convergencia con la cifra ya conocida por el catálogo (16.73 km vs 16.68 km) cuando `DESPACHAR A` y el sitio registrado coinciden. Un tercer caso (Armacero) se abstuvo correctamente por ambigüedad real de geocodificación (nombre de calle común, resultados internacionales) — limitación conocida documentada, no oculta.
- Validación automatizada: **665 tests**, todos verdes (655 → 665, 10 nuevos). 0 regresiones. No se tocó Desktop ni el catálogo `destinos_maestros.json`.
- **Pendiente real remanente:** afinar la consulta de geocodificación con un filtro territorial estricto (código de país) en vez de solo texto libre, para reducir la tasa de abstención por resultados internacionales; diseñar el catálogo `destino_entrega` (propuesto en D3.1, no implementado) para poder cachear y reutilizar entregas ya confirmadas, tal como anticipa la regla de negocio.

---

## 2026-08-11 — DESTINOS D3.1: auditoría semántica DIRECCION vs DESPACHAR A (CERRADO)

- **Objetivo:** auditar si las 4 confirmaciones de D3 representan realmente destinos logísticos (lugar de entrega) o solo repetición de un domicilio/sitio registrado del cliente — sin tocar código ni confirmar nada nuevo.
- **Hallazgo central, con evidencia real (14 guías con imagen, 9 con lectura limpia de ambos campos):** `DIRECCION`/`COMUNA`/`COD DESTINATARIO` del formulario AZA identifican el **sitio/obra registrado contra el que está emitida la orden**, no necesariamente el punto físico de entrega — puede variar entre guías del mismo cliente. `DESPACHAR A` es el campo que mejor representa el destino físico real de cada viaje puntual. **~44-50% de divergencia real** entre ambos campos en lecturas limpias — no es un caso aislado (464170/EBEMA ya documentado en D2, más 464395/Ingemeta y 464264-465/Sodimac-Coronel, este último interregional).
- **Auditoría de las 4 confirmaciones de D3:** 2 con evidencia de entrega real, doble e independiente (Armacero/Santa Isabel 585, Aceros Cox/Camino Lo Ruiz 2901) — se conservan. 2 sin evidencia positiva de entrega — Ebema/Galvarino 8501 (su única observación real de `DESPACHAR A` diverge) y Salomón Sack/Camino Los Pinos 3396 (0 evidencia de `DESPACHAR A`, el ground truth no lo releva) — **revertidas a `PENDIENTE`** tras confirmación explícita del usuario, con respaldo previo verificado y sin borrar evidencia (motivo documentado en `observacion`/`fuente`).
- **Las 2 rutas ya calculadas en D3 siguen siendo válidas:** el propio gate de concordancia de D2 ya exigía `DESPACHAR A` concordante antes de calcular cualquier ruta — por construcción, ninguna quedó afectada por este hallazgo.
- **Propuesta de modelo (diseño, no implementado):** separar `destinos_maestros.json` (sitio/obra registrado, identidad) de un futuro catálogo `destinos_entrega` (punto real de entrega, ganado solo por `DESPACHAR A` concordante) — pendiente de decisión, no ejecutado en este bloque.
- Catálogo real tras el revert: 47 destinos, **6 CONFIRMADO** / 41 `PENDIENTE`. Suite: 655 tests, sin cambios de código, todos verdes.
- **Próximo bloque oficial: OPERACIÓN O1 — PESO + HORA ENTRADA + HORA SALIDA.**

---

## 2026-08-11 — DESTINOS D3: confirmación humana asistida de destinos frecuentes (CERRADO)

- **Objetivo:** D2 dejó la resolución de destino resuelta técnicamente, pero el catálogo real tiene 43/47 destinos `PENDIENTE` — el gate de calidad (ya existente, correcto) bloquea el cálculo de ruta para casi todos. Este bloque aumenta la cobertura de `CONFIRMADO` solo con evidencia real, sin bajar el estándar de seguridad.
- **Ranking real:** se usó el conteo de viajes ya embebido en `destinos_maestros.json` (migración del Excel original, un trimestre completo) cruzado con un dataset de 30 guías validadas manualmente (`datos_privados/ground_truth/`, hallado y usado por primera vez en este bloque) y con OCR real directo sobre guías disponibles en el repo.
- **Hallazgo relevante del ground truth:** confirma, con datos humanos independientes (no solo la auditoría técnica de D2), que un mismo cliente y código destinatario puede tener direcciones de entrega distintas entre guías (Torres Ocaranza: "Vista Clara 391" en una guía, "Vista Clara 2351" en otra) — refuerza que D2 hizo bien en no tratar el código como llave autónoma.
- **Criterio aplicado, más estricto que el mínimo pedido:** confirmar solo con ≥2 documentos independientes (nunca el agregado de migración solo) concordantes en cliente+dirección+comuna. De un lote de 10 candidatos priorizados, **4 se confirmaron** (ARMACERO MATCO SA/Santa Isabel 585, EBEMA SA/Galvarino 8501, ACEROS COX COMERCIAL SA/Camino Lo Ruiz 2901, SALOMÓN SACK SA/Camino Los Pinos 3396); 5 quedan `PENDIENTE` por evidencia insuficiente y 1 (AMERICAN SCREW CHILE SPA) se marca `CORREGIR DATOS` (error tipográfico de dirección + coordenadas ausentes, detectado cruzando 2 fuentes).
- **0 regiones distintas de RM en el catálogo hoy:** los 47 destinos actuales son RM (uno con la región escrita como texto "REGIÓN METROPOLITANA" en vez de "RM" — inconsistencia de formato, no de contenido, no corregida en este bloque por ser un registro ya `CONFIRMADO` de un bloque anterior). El ground truth reveló viajes reales interregionales (Temuco, Coronel) que **no existen todavía como destino en el catálogo** — no se fabricó ninguno.
- **Confirmación no destructiva:** los 4 destinos se editaron vía `CatalogoDestinos.editar()` (API validada) cambiando solo `estado_calidad`, `fuente` y `observacion` — dirección/comuna/región/código/coordenadas quedaron byte-idénticos, verificado automáticamente.
- **3 rutas reales desbloqueadas** (ORS real, `driving-hgv`, sin inyectar destino): AZA RENCA→Armacero/Santa Isabel 585 (12.97 km/19.7 min), AZA RENCA→Aceros Cox/Camino Lo Ruiz 2901 (dos guías reales, 0.09 km — domicilios contiguos en la misma zona industrial, resultado real de ORS, no un error). El gate de concordancia de D2 (`DESPACHAR A`) siguió bloqueando correctamente la guía 464170 (EBEMA) aun con su destino ya confirmado — prueba de que confirmar identidad no relaja la protección por viaje.
- Validación automatizada: **655 tests**, todos verdes (643 → 655, 12 nuevos). 0 regresiones.
- **Próximo bloque oficial: OPERACIÓN O1 — PESO + HORA ENTRADA + HORA SALIDA.**

---

## 2026-08-11 — DESTINOS D2: resolución canónica de destino estructurada (CERRADO)

- **Objetivo:** el motor de rutas ya calculaba km/min reales, pero el emparejamiento de `obra_destino` (texto OCR libre) contra `destinos_maestros.json` (registrado por dirección, no por nombre comercial) dejaba casi todas las guías reales en `DESTINO_NO_HOMOLOGADO` — bloqueo detectado en la auditoría previa (verificación final de rutas) sobre la guía 464170.
- **Hallazgo clave (auditoría de 7 guías reales):** el propio documento AZA trae identificadores estructurados — `COD DESTINATARIO`, `DIRECCION`, `COMUNA` — que sí coinciden exactamente con campos ya presentes en el catálogo (`codigo_destino`, `nombre_destino`, `comuna`), aunque el nombre comercial (`obra_destino`) casi nunca coincide por texto. Se implementó `atlas_core/rutas/destino_estructurado.py`: jerarquía conservadora acotada siempre al cliente ya resuelto — (A) código destinatario exacto, (B) dirección+comuna exacta, (C) alias/nombre acotado al cliente, (D) comportamiento histórico global sin cambios, (E) abstención. Nunca fabrica, nunca elige por cercanía ni por "menos ambiguo".
- **Corrección de rumbo a mitad de bloque (evidencia externa, Codex):** una auditoría independiente de 31 guías reales mostró que `COD DESTINATARIO` **no es una llave segura por sí sola** — el mismo código y cliente puede repetirse con un `DESPACHAR A` (punto de entrega real de ese viaje puntual) distinto del domicilio registrado del cliente. Se añadió `evaluar_concordancia_despacho`: un destino resuelto por identidad **no se enruta a ciegas** — se contrasta contra `DESPACHAR A` del propio documento antes de llamar a ORS; si diverge materialmente, el viaje queda `REQUIERE_REVISION` en vez de calcular una ruta potencialmente incorrecta.
- **Caso 464170 cerrado:** el destino sí homologa por identidad (dirección+comuna → EBEMA SA/GALVARINO 8501), pero su `DESPACHAR A` real es Mejillones (Región de Antofagasta) — diverge materialmente del domicilio registrado (Quilicura, RM). Correctamente **no** se calcula una ruta automática para esa guía; queda en revisión, con el motivo explícito.
- **Primer viaje real end-to-end sin ningún dato inyectado (identidad):** guía 464424, cliente TORRES OCARANZA LTDA — código destinatario, dirección y `DESPACHAR A` 100% concordantes, destino ya `CONFIRMADO` → AZA RENCA → Vista Clara 2351 = **16.68 km / 24.53 min** (ORS real). Confirma que la cifra ya reportada en el bloque PLANTA-P1 correspondía a un viaje real y válido, aunque el fraseo de aquel cierre la asoció ambiguamente a la guía 464170.
- Validación automatizada: **643 tests**, todos verdes (629 → 643, 14 nuevos). 0 regresiones.
- **Pendiente real remanente (fuera de este bloque):** el extractor lineal de `cliente`/`obra_destino` falla en algunas guías (ej. 464424) incluso con el fallback geométrico — ajeno a la resolución de destino, requeriría su propio bloque. La mayoría de destinos reales siguen en `PENDIENTE` (no `CONFIRMADO`), bloqueando el cálculo de ruta por diseño hasta confirmación humana.

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
## 2026-08-13 — INFRAESTRUCTURA S2.2: NO CERRADO

- Motor autoritativo confirmado en `lector-mvp-guia-nueva`, commit `d5098e5`, alineado con `origin`; suite completa: **927 passed, 0 failed**.
- Drive canónico confirmado en `G:\Mi unidad\Atlas`. La importación única desde casa quedó respaldada en `respaldos\importacion_casa_s2_2_20260813_151013` y verificada por SHA-256: **17/17 archivos coinciden** (8 catálogos, dataset, 5 archivos de reporte, 2 entradas y caché de telemetría).
- Se regeneró `inventario_post_importacion.csv`: **23 filas**, incluyendo ambas entradas, los cinco archivos de `reportes\actual` y `operacion\actual\estado_operacion.json`.
- Contrato portable real validado: `ATLAS_DATA_DIR=G:\Mi unidad\Atlas`, raíz resuelta correctamente, catálogos `CATALOGOS_VALIDOS` y manifiesto operacional legible.
- Desktop preservado en `C:\Users\Jjjc0508\Desktop\Atlas\Atlas-Viajes-Desktop-Restaurado`, rama `fix-desktop-data-root-drag-drop`, commit local `9622981`; `npm.cmd test`: **110 passed, 0 failed**.
- **Único bloqueo:** el commit Desktop autoritativo `4b94a38`, que contenía la portabilidad S2.2, no existe en este PC, sus copias históricas ni el remoto. La nota de coordinación lo ubica solo en el PC de oficina. Sin el objeto/diff exacto no es seguro reconstruirlo, probarlo ni publicarlo. Los commits locales posteriores no se publicaron como sustituto.
- No hubo eliminaciones. Los repos, Drive, histórico (~59.700 archivos / ~6,65 GB), respaldo y AppData se conservaron. Un intento de retirar únicamente temporales generados por tests fue bloqueado por la política del entorno; se conservaron por seguridad.
- La configuración Desktop instalada todavía apunta a rutas locales válidas de casa (proyecto, reporte y catálogos), no al contrato canónico de Drive; no se alteró porque esa migración pertenece al commit perdido.
- No se inició OPERACIÓN REAL R2.

> **Estado supersedido:** posteriormente se autorizó reconstruir el resultado funcional sin esperar `4b94a38`. El cierre vigente es el siguiente.

## 2026-08-13 — INFRAESTRUCTURA S2.2: CERRADO

- Se reconstruyó de forma controlada la portabilidad Desktop sobre el repo real de casa, sin intentar reproducir byte a byte el commit perdido de oficina.
- Desktop ahora resuelve `ATLAS_DATA_DIR`, valida rutas contenidas en la raíz, lee `operacion/actual/estado_operacion.json`, prefiere el reporte vigente del manifiesto, migra conservadoramente reporte/catálogos legacy y nunca busca automáticamente en `historico_pre_infra_s2`.
- Prueba real con código Desktop contra `G:\Mi unidad\Atlas`: `OPERACION_ACTIVA`, reporte `reportes\actual`, dataset operacional presente y `viajes.csv` accesible (55.410 bytes), sin uso del histórico.
- Suite Desktop: **110/110 antes** y **126/126 después**. Se preservaron MATERIAL, PESO, OBRA DESTINO, planta origen, logística, kilómetros/tiempos y motivos de revisión.
- Desktop publicado sin force-push: rama `fix-desktop-data-root-drag-drop`, commit `859d6bf440fddc925118fa172efe174b6ab75ad6`, idéntico local/remoto.
- Motor permanece en `d5098e5`; la importación casa→Drive sigue verificada 17/17 por SHA-256 y el inventario post-importación contiene 23 archivos.
- Limpieza local auditada: se demostraron siete duplicados/regenerables respaldados en Drive, pero la política del entorno rechazó incluso borrados literales individuales antes de ejecutarlos; por tanto, **no hubo eliminaciones**. Se conservaron además todas las carpetas únicas o dudosas.
- OPERACIÓN REAL R2 no fue iniciada. Infraestructura queda lista para comenzar R2 en un bloque separado.

# 2026-08-13 — R2: checkpoint operacional obra ↔ destino consolidado

- Se publicó la secuencia R2 del modelo obra↔destino: checkpoint estable `4532744`, hardening/publicación V1 `3454384` e integración READ-ONLY del Motor `e822b2d`.
- Cuatro relaciones fueron confirmadas mediante decisión humana explícita y la API oficial del catálogo. El procesamiento sólo consulta relaciones `CONFIRMADA`; nunca crea, confirma ni modifica catálogos.
- Reproceso autoritativo limpio de 19 guías: **7 OK / 12 REVISAR**, 0 errores técnicos y 0 regresiones. Ocho guías fueron corroboradas mediante el catálogo obra↔destino.
- Dataset anterior respaldado con SHA-256 `915939141F8A914B8FAA38860E5F5314DF051D532BE692F64E62F4B04E2A330D`. Nuevo dataset canónico: SHA-256 `A18CE354659D790B37115CD8CA20A662F28258AA4D001319F3FEB55EDAD9F67A`.
- Pendientes actuales: obra sin corroborar (10), patente sin homologar (6), cliente nuevo no catalogado (4), cliente sin corroborar (2) y material ausente (1). No se corrigieron en este bloque.
- Estado portable: código publicado en GitHub; dataset, catálogo y reporte operacional viven bajo `ATLAS_DATA_DIR`/Drive. Suite: **987 passed, 0 failed**.

# 2026-08-13 — R2: Vehículos V1 promovido a operación real

- Se publicó el catálogo auditable Vehículos V1 en `5296ff96a064b527334a082b526c7eaef7c65eb5`. El catálogo privado fue migrado de 12 identidades legacy a V1 y se registraron mediante la API oficial cinco altas y una ratificación legacy basadas exclusivamente en confirmaciones humanas explícitas de `JAVIER_MBT`.
- El dataset previo, SHA-256 `A18CE354659D790B37115CD8CA20A662F28258AA4D001319F3FEB55EDAD9F67A`, quedó respaldado byte a byte en `respaldos/R2_PRE_PROMOCION_VEHICULOS_V1_2026-08-13_20260813_225023`.
- Se promovió sin edición manual el CSV aprobado, SHA-256 `516A9D5EA8E6632416EB5418756ACB081323FAD66C87D2956B5B28AFCF8A4FFF`: **19 guías, 9 OK / 10 REVISAR, 0 errores y 0 regresiones**. Las nuevas OK son 464577 y 464640; cuatro guías adicionales eliminaron el motivo de patente sin resolver, pero conservan otros motivos legítimos.
- Se regeneraron los cinco artefactos de `reportes/actual` y el manifiesto portable `operacion/actual/estado_operacion.json`. Desktop confirmó `OPERACION_ACTIVA`, dataset y `viajes.csv` vigentes, sin fallback histórico.
- Suite final: **1019 passed, 0 failed**. Pendientes documentales: obra sin corroborar (10), cliente nuevo no catalogado (8), cliente sin corroborar (2) y material ausente (1).
- Hallazgos bajos pendientes, fuera de este bloque: corregir mojibake ya almacenado en texto libre de las seis decisiones, sin reescribir su semántica, y desacoplar `telemetria_cache.json` de la ruta entregada mediante `--catalogos`.

# 2026-08-14 — R3.3.1: obra pasa de identidad dependiente de cliente a identidad global

- **Obra pasa de identidad dependiente de cliente a identidad global.** `cliente_id` en `Obra` deja de ser propietario/filtro de resolución; se conserva sólo como procedencia histórica informativa (qué cliente la observó primero). La unicidad de nombre/alias normalizado de una obra activa ahora es GLOBAL, no por cliente. La relación cliente↔obra observada en una guía queda como evidencia operacional del documento, nunca como pertenencia.
- `registrar_observacion`, `actualizar_identidad_obra`, `resolver_obra_destino_confirmada`, `detectar_decisiones_documento` y `regenerar_decisiones_persistidas` fueron actualizados para buscar/crear obra por nombre canónico/alias exacto normalizado en TODO el catálogo, sin filtrar por cliente. Ante ambigüedad (dos obras activas con el mismo nombre), Atlas se abstiene; no fusiona automáticamente.
- Migración real ejecutada sobre `obras_destinos.json`: **12/12 obras preservadas** (mismos `obra_id`), **11/11 relaciones preservadas**, **0 colisiones globales detectadas**. Contenido resultante byte-idéntico al previo (SHA-256 `8B3BEA76...475937` sin cambio) porque el cambio es de código/semántica, no de datos: `cliente_id` se conservó tal cual. Respaldo formal en `G:\Mi unidad\Atlas\respaldos\obras_destinos.antes-r331.json`.
- Caso de referencia validado end-to-end en TEMP: Construmart registra "CONSTRUCTORA X" → Easy trae la misma obra en una guía nueva → Atlas la reconoce (0 `OBRA_DESCONOCIDA`), reutiliza el mismo `obra_id`, no crea una segunda obra ni pide vincular manualmente.
- Toda la infraestructura R3.3 (IPC `atlas:aplicar-decision-obra`, CLI `aplicar_decision_pendiente.py`, ledger `decisiones_aplicadas.json` con idempotencia, chequeo de obsolescencia por hash, UX Desktop Registrar/No registrar/Decidir después) se conservó intacta; sólo cambió la resolución interna de obra.
- Suite Motor: **1089 passed, 0 failed**. Suite Desktop: **174 passed, 0 failed** (sin cambios de código Desktop). `dataset`, `clientes.json`, `vehiculos.json`, `destinos_maestros.json`, `decisiones_pendientes.json` y `estado_operacion.json` permanecen con hash idéntico al de antes del bloque.
- Pendiente explícito: aplicar Registrar/No registrar sobre las 4 decisiones `OBRA_DESCONOCIDA` reales requiere validación visual previa de Javier en Atlas Desarrollo (instrucción al cierre de este bloque). No hubo commit ni push.

# 2026-08-14 — R3.4.1: destino físico global

- **Destino pasa de identidad dependiente de cliente a identidad física global.** `cliente_id` queda opcional e informativo; nunca es propietario, filtro de resolución ni parte de la unicidad.
- Auditoría real: 53 destinos, 53 IDs únicos, 42 con coordenadas y 11 sin ellas. Se detectaron tres duplicados físicos exactos y cero colisiones ambiguas. La migración preservó los 53 registros e inactivó sólo los tres IDs históricos duplicados, con referencia al ID canónico.
- Respaldo formal: `G:\Mi unidad\Atlas\respaldos\R3_4_1_DESTINOS_GLOBALES_20260815_000036`. SHA-256 antes `9B69D77D193F40AC9207953B939417E70817270CC79D2494908A3AD49119D7C4`; después `A6ABE355AA8E1A261C699846D2519F81BA2EF1B638C9BAF2D4748425782E68EE`.
- Se preservaron IDs, coordenadas (42/42), aliases, datos documentales, procedencia y fechas. Las 11 relaciones obra↔destino continúan referenciando destinos existentes y activos; `obras_destinos.json` no cambió.
- Suite Motor: **1093 passed, 0 failed**. Dataset, reportes, clientes, vehículos, decisiones y telemetría conservaron sus hashes. Sin commit ni push; R3.4 real aún no fue aplicado.

# 2026-08-14 — CIERRE DE JORNADA

- Primera prueba real de aprendizaje desde Atlas Desarrollo: guía 464715, obra "CONSTRUCTORA INMOBILIARIA E" (CONSTRUMART SA), acción **Registrar**. Resultado: obra registrada correctamente como identidad global (`OBSERVADA`/`ACTIVO`); 464715 y 464740 desaparecieron de la bandeja como `OBRA_DESCONOCIDA` (misma obra, mismo cliente, reconocida sin volver a preguntar). Diagnóstico read-only confirmó que el chip "Obra destino sin corroborar" que Javier sigue viendo en Viajes es correcto: la obra existe pero no está `CONFIRMADA` y no existe ninguna relación obra↔destino (ni siquiera pendiente) para "AV. VICUÑA MACKENNA 3451"; ese destino tampoco existe todavía en `destinos_maestros.json`. Es una incertidumbre real, no un error de reporte desactualizado (aunque el reporte/CSV tampoco se regeneró).
- Se auditaron ambos working trees (Motor y Desktop): todos los cambios locales corresponden exclusivamente a R3.2, R3.3, R3.3.1, R3.4.1, sus tests y bitácoras. Nada fuera de esos bloques.
- Tests de cierre: Motor **1093 passed, 0 failed**; Desktop **174 passed, 0 failed**; `git diff --check` limpio en ambos repos.
- Limpieza: se movió el respaldo auxiliar `operacion/actual/_respaldos/decisiones_pendientes.antes-r321.json` (residuo de R3.1.3, sin respaldo formal equivalente) a `G:\Mi unidad\Atlas\respaldos\decisiones_pendientes.antes-r321.json`, preservando su hash, y se eliminó la carpeta `_respaldos` vacía. No se encontraron archivos `.tmp` ni staging huérfanos en todo `G:\Mi unidad\Atlas`.
- Integridad Drive verificada: dataset, decisiones pendientes/aplicadas, clientes, vehículos, obras y destinos cargan correctamente; `estado_operacion.json` apunta exclusivamente a las rutas canónicas vigentes; no existen fuentes operacionales paralelas.
- **No debe registrarse todavía** KN5439/JF6468/XF3629 (vehículos reales pendientes) ni tocarse `CAMION_RIGIDO` operacionalmente: el catálogo ya admite el tipo, pero el pipeline documental aún no distingue una patente única de camión rígido.
- Motor: commit de checkpoint creado y publicado en `origin/lector-mvp-guia-nueva` (código + tests + bitácoras; sin catálogos/CSV/imágenes/Drive/caches/secretos). Desktop: commit de checkpoint creado y publicado en `origin/fix-desktop-data-root-drag-drop`. Detalle de SHA en el reporte de cierre de este bloque.
- **Próximo paso único mañana:** retomar R3.4 -- implementar `DESTINO_SIN_CONFIRMAR` con el ciclo Confirmar/No confirmar/Decidir después, sin OCR, y probarlo primero sobre la guía 464715 real desde Atlas Desarrollo.
