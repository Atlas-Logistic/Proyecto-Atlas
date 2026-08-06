# Bitácora Técnica Cronológica

## Propósito
Esta bitácora registra, en orden temporal, las decisiones importantes, cambios de estrategia, alternativas descartadas, problemas detectados, justificaciones de decisiones y acuerdos entre herramientas para que ChatGPT, GitHub Copilot y Claude Code compartan el mismo contexto sin revisar todo el historial del repositorio.

## Convención de uso
- Se actualiza al cierre de cada bloque.
- Cada entrada debe explicar por qué se tomó una decisión y qué alternativa fue descartada.
- La información detallada del flujo técnico debe enlazarse a la documentación de Atlas cuando sea extensa.

## Registro cronológico

### 2026-08-04 — Atlas Benchmark 2.0, motor actual
- Decisión: reconstruir un corpus actual desde las imágenes originales
  recuperables y no reutilizar ninguna fila del snapshot histórico.
- Universo: 143 archivos candidatos, 16 duplicados exactos descartados y 127
  imágenes únicas procesadas. Se excluyeron derivados visuales y recortes OCR.
- Ejecución: motor funcional base `173f135`, HEAD documental `7f61ff1`,
  catálogos privados vigentes, 127 OK, cero errores y cero omisiones. La salida,
  reporte y rutas permanecen en el área temporal privada de Atlas.
- Rendimiento: la primera cohorte secuencial requirió cerca de 65 segundos por
  documento; tres lectores concurrentes elevaron el promedio individual a
  165–174 segundos por contención CPU. No se alteraron relecturas ni parámetros.
- Cobertura: Cliente 55,91 %, Destino 70,87 %, Chofer 71,65 %, Transporte
  70,87 %, tracto 55,12 %, rampla 14,96 %, Peso 22,83 %, Cantidad 29,92 %,
  Material 22,83 % y Origen 40,94 %.
- Consolidación: 90/127 documentos forman 86 viajes; 7 viajes/7 documentos
  quedan confirmados y 79 viajes/83 documentos requieren revisión; 37
  documentos carecen de transporte.
- Rutas: ORS calculó 2/86 viajes, ambos AZA RENCA → VISTA CLARA 2351, 16,7 km
  y 25 min. Permanecen 84 pendientes: 47 sin origen, 29 con destino no
  confirmado, 5 sin destino, 2 con destino ambiguo y 1 sin coordenadas de
  origen.
- Interpretación: la variación frente al snapshot es descriptiva, no pareada;
  Cliente baja 5,18 pp mientras los restantes campos mejoran o permanecen
  estables. Sin ground truth completo no se declara precisión masiva.
- Priorización: Origen primero por bloquear 47 rutas y faltar en 75 documentos;
  Destino segundo por bloquear otros 36 viajes; Transporte tercero por excluir
  37 documentos de consolidación.

### 2026-08-04 — Validación Operacional Masiva, Fase 1
- Decisión importante: medir el mayor corpus operacional disponible (1.177
  guías reales y 574 viajes) sin equiparar cobertura con precisión.
- Evidencia: 1.177/1.177 filas fueron procesadas sin error; 1.033 conservan
  indicador global `REVISAR`. Cliente aparece en 719, Destino en 777, Chofer en
  711 y Transporte en 730 documentos.
- Hallazgo estructural: el snapshot masivo del 28-07-2026 no contiene columnas
  Origen, Peso ni Cantidad; por ello esos campos y los kilómetros no pueden
  medirse como publicados en ese corte, aunque existan validaciones focales
  posteriores del pipeline vigente.
- Consolidación: los 730 documentos con transporte se conservan exactamente en
  574 viajes; 490 viajes/529 documentos quedan confirmados y 84 viajes/201
  documentos requieren revisión. Otros 447 documentos no poseen transporte.
- Calidad: no hay ground truth humano masivo por campo. Se mantiene como
  referencia separada el E2E oficial de 48/49 valores (97,96 %), sin
  extrapolación estadística al corpus operacional.
- Alternativa descartada: declarar como correctos todos los valores presentes o
  ejecutar correcciones/reprocesamiento durante una fase exclusivamente de
  medición.
- Siguiente bloque recomendado: reprocesar una cohorte estratificada con el
  pipeline vigente, congelar ground truth por campo y priorizar
  Origen/Transporte/Destino para desbloquear consolidación y rutas.

### 2026-07-31 — Priorización del cuello de botella de calidad de lectura
- Decisión importante: priorizar la calidad de lectura real sobre seguir el roadmap únicamente por orden histórico.
- Cambio de estrategia: enfocar la siguiente iteración en el bloque de lectura y resolución antes de ampliar capacidades nuevas.
- Alternativas descartadas: seguir el roadmap sin filtrar el cuello de botella real; introducir nuevas reglas sin validar la calidad de lectura.
- Problemas encontrados: ruido OCR, confirmación silenciosa de valores incorrectos y contradicciones entre campos.
- Justificación: el impacto en la fidelidad de lectura era mayor que el valor de seguir tareas de menor impacto inmediato.
- Acuerdo entre herramientas: mantener una política conservadora, auditable y con revisión cuando la evidencia sea débil o contradictoria.

### 2026-07-31 — Bloque 1C.1 + 1D.1 — Motor multicampo
- Decisión importante: mantener el motor multicampo existente y reforzar su política de decisión en lugar de introducir una nueva arquitectura.
- Cambio de estrategia: convertir la contradicción en un estado de revisión y no en una confirmación automática.
- Alternativas descartadas: aceptar coincidencias parciales como válidas o corregir silenciosamente datos incompatibles.
- Problemas encontrados: confirmación incorrecta de patentes y compatibilidades cliente-destino que no correspondían a la evidencia.
- Justificación: la arquitectura ya existía y el riesgo de introducir un nuevo motor era mayor que el beneficio de una adaptación incremental.
- Acuerdo entre herramientas: las decisiones deben ser conservadoras y explícitas cuando la evidencia no sea suficiente.

### 2026-07-31 — Bloque Lector Focal Adaptativo – Fase 1
- Decisión importante: introducir una relectura focal controlada solo cuando exista evidencia de que puede mejorar la lectura.
- Cambio de estrategia: usar una segunda lectura de los recortes de transporte como mecanismo de apoyo, no como sustituto del OCR base.
- Alternativas descartadas: relecturas agresivas en todos los campos o corregir automáticamente cualquier diferencia entre lecturas.
- Problemas encontrados: el riesgo de introducir ruido y reducir la calidad al corregir sin criterio.
- Justificación: la segunda lectura solo aporta valor si puede confirmar, detectar conflicto o aportar evidencia útil sin degradar el consenso.
- Acuerdo entre herramientas: la relectura debe ser evaluada antes de incorporarse como evidencia.

### 2026-07-31 — Resolución Inteligente de Choferes – Fase 1
- Decisión importante: integrar la resolución de choferes en el flujo principal mediante el motor multicampo determinista ya existente.
- Cambio de estrategia: usar el RUT como señal fuerte de confirmación, pero conservar el OCR y marcar revisión si la evidencia es débil o contradictoria.
- Alternativas descartadas: usar un fuzzy matching como fuente primaria o corregir el nombre de chofer sin contexto suficiente.
- Problemas encontrados: la resolución estaba fragmentada y podía producir decisiones inconsistentes entre el flujo principal y los componentes de inteligencia.
- Justificación: un flujo único, conservador y explicable reduce errores silenciosos y mejora la trazabilidad.
- Acuerdo entre herramientas: la decisión debe preservarse en el flujo principal y documentarse con pruebas y revisión adversarial.

### 2026-08-01 — Endurecimiento de integración de Resolución Inteligente de Clientes – Fase 1
- Decisión importante: fijar `resolucion_cliente.py` como único punto de decisión para identidad de cliente dentro del flujo principal y retirar el contrato antiguo donde `enriquecer_datos_con_catalogos` podía sobrescribir `cliente` por RUT o catálogo.
- Cambio de estrategia: `enriquecer_datos_con_catalogos` queda limitado a campos auxiliares y jamás resuelve identidad de cliente; `procesamiento_masivo.py` debe propagar `REVISAR` para cualquier estado no confirmado del contrato multicampo.
- Alternativas descartadas: restaurar la sustitución directa por catálogo dentro del enriquecimiento o mantener ambos contratos en paralelo.
- Problemas encontrados: la integración aceptaba `PROPUESTO` y `NO_RESUELTO` como `OK` en algunos casos, y coexistían pruebas heredadas que seguían esperando sobrescritura directa del cliente desde catálogo.
- Justificación: mantener dos autoridades sobre `cliente` vuelve opaca la trazabilidad y reintroduce riesgo de corrección silenciosa; centralizar la decisión en el resolver conserva coherencia con la política conservadora del motor.
- Acuerdo entre herramientas: a partir de este endurecimiento, cualquier estado no confirmado del resolver de cliente implica revisión humana en el flujo principal y el enriquecimiento por catálogo no modifica `cliente`.

### 2026-08-01 — Cierre oficial de Resolución Inteligente de Clientes – Fase 1
- Decisión importante: cerrar oficialmente el bloque tras aprobación de la segunda auditoría independiente, sin abrir aún el siguiente bloque funcional.
- Cambio de estrategia: consolidar primero la publicación en `origin/main` antes de habilitar nuevas iteraciones sobre Destinos.
- Alternativas descartadas: abrir inmediatamente el siguiente bloque o mantener ambiguo el contrato final de catálogo pese a la auditoría aprobada.
- Problemas encontrados: se confirmó como seguimiento no bloqueante que `extractor.py` mantiene fallbacks históricos por número de guía que precargan cliente y RUT; no constituyen una segunda ruta de decisión, pero deberán revisarse en futuras fases de unificación.
- Justificación: el bloque quedó estable, auditado y con contrato unificado; el riesgo restante es conocido, acotado y no invalida la centralización de decisión en `resolucion_cliente.py`.
- Acuerdo entre herramientas: Clientes queda cerrado solo después de commit, integración y publicación en `origin/main`, y Destinos no debe abrirse antes de confirmar ese estado.

### 2026-08-01 — Infraestructura mínima de integración multicampo
- Decisión importante: introducir un helper mínimo en `procesamiento_masivo.py` para encapsular la integración común de resoluciones multicampo, sin mover reglas de matching ni políticas de negocio fuera de sus resolvers.
- Cambio de estrategia: reutilizar solo la capa repetida de aplicación del valor canónico, conservación del OCR, logging homogéneo y propagación opcional de revisión según contrato.
- Alternativas descartadas: crear un framework genérico de resolución, abstraer las reglas de matching nombre/RUT o unificar prematuramente Choferes, Clientes, Destinos y Materiales bajo una arquitectura nueva.
- Problemas encontrados: Choferes y Clientes repetían la misma capa de integración en el flujo principal, que ya había demostrado ser un punto sensible a defectos de propagación de estado.
- Justificación: la deduplicación se concentra en la zona de mayor retorno y menor riesgo; la lógica de negocio permanece intacta y las pruebas del comportamiento previo siguen aprobando sin cambios funcionales.
- Acuerdo entre herramientas: migrar primero Choferes y Clientes al helper mínimo; Destinos y Materiales no se incorporan todavía a esta infraestructura.
- Decisión permanente: a partir de este cambio, toda integración entre un resolver multicampo y `procesamiento_masivo` deberá realizarse mediante el helper de integración oficial. No se permitirá duplicar nuevamente esta lógica en futuros resolvers.

### 2026-08-03 — Orquestador Multicampo – Fase 1
- Decisión importante: incorporar una capa de aplicación reutilizable que ejecute resolvers existentes únicamente en modo sombra, sin publicar valores ni reemplazar el flujo actual.
- Cambio de estrategia: adoptar composición por solicitudes e inyección de funciones en vez de crear un objeto de entrada universal que conociera anticipadamente todas las firmas, catálogos y políticas.
- Alternativas descartadas: modificar cada resolver para ajustarlo a una interfaz nueva; duplicar sus reglas dentro del orquestador; conectar inmediatamente el orquestador a `procesamiento_masivo`; traducir implícitamente contratos externos como rutas.
- Justificación: la inyección preserva los contratos actuales, permite usar snapshots y políticas ya preparados por cada llamador, mantiene aislamiento por campo y admite contratos externos mediante un adaptador de resumen explícito.
- Comportamiento: conserva el resultado crudo de cada resolver; genera solo estado, confianza, revisión y cantidad de contradicciones; aísla fallos sin guardar mensajes potencialmente sensibles; rechaza campos duplicados y cualquier modo distinto de `SOMBRA`.
- Integridad: no se modificaron resolvers, políticas, snapshots, extractor, procesamiento masivo, Desktop, catálogos ni resultados productivos.
- Validación: 12 pruebas específicas y 217 pruebas de consumidores de la API pública; `compileall` y `git diff --check` aprobados.
- Estado: implementación `acfe3f19854043fa5c824a14e50a47618b7c3a35`, lista para auditoría independiente.

### 2026-08-03 — Activación Controlada de Materiales — Fase 1
- Decisión importante: promover exclusivamente `material` de `SOMBRA` a `PRODUCTIVO_CONTROLADO` en el registro inmutable existente.
- Cambio de estrategia: ninguno; se reutiliza la Política de Activación aprobada y la autorización explícita por ejecución.
- Alternativas descartadas: activar Materiales como `PRODUCTIVO`, publicar sin autorización o modificar OCR, resolver, Orquestador y catálogos.
- Validación: sin autorización se preserva OCR; con autorización se publican únicamente GT-MAT-009 y GT-MAT-010; el rollback a `SOMBRA` preserva OCR y no cambia Choferes, Clientes, Destinos ni revisión.
- E2E: 12/12 guías, 2 confirmaciones, 10 abstenciones, precisión 2/2, cero falsos positivos, cero contradicciones y 4/12 revisiones.
- Acuerdo entre herramientas: el Sistema Multicampo queda oficialmente finalizado con Choferes y Clientes en `PRODUCTIVO`, y Destinos y Materiales en `PRODUCTIVO_CONTROLADO`.

### 2026-08-03 — Análisis profundo de los casos REVISAR — Fase 1
- Decisión importante: separar la causa que marca revisión de las diferencias de salida; Destinos y Materiales pueden abstenerse sin propagar `REVISAR`.
- Evidencia: 002 queda marcado solo por recuperación geométrica; 005 y 007 entregan al resolver RUT de Cliente sin DV; 010 combina Destino mal asociado, Chofer no resuelto y ausencia de LUIS REYES en catálogo.
- Alternativas descartadas: relajar resolvers, aceptar RUT incompletos, convertir `COMUNA` en alias o inferir el Chofer.
- Justificación: esas alternativas elevan falsos positivos y contradicen los contratos congelados.
- Acuerdo: priorizar un bloque único de OCR focal estructurado de RUT de Cliente, con consenso y módulo 11, antes de reconsiderar reglas o catálogos.

### 2026-08-03 — OCR focal estructurado de RUT de Cliente — Fase 1
- Decisión importante: releer únicamente RUT de Cliente ya observado pero incompleto o inválido, sin ampliar OCR a campos ausentes.
- Diseño: localizar la fila `RUT` por proximidad geométrica a `SEÑOR(ES)`, ejecutar cuatro variantes sobre el recorte y extraer exclusivamente candidatos completos.
- Política conservadora: aceptar un único RUT módulo 11 válido observado al menos dos veces; cualquier candidato válido diferente provoca abstención y preserva el original.
- E2E: ATLAS-E2E-005 recupera 93772000-9 y ATLAS-E2E-007 recupera 91410000-3; ambos pasan de `REVISAR` a `OK`; quedan 002 y 010.
- Calidad: precisión oficial 48/49 (97,96 %), contradicciones 0 y falsos positivos 0, sin cambios.
- Rendimiento: total 385,779 s frente a 439,647 s de la evidencia oficial; por caso activado se observa un costo adicional de 21,413 s y 24,923 s, que debe optimizarse antes de ampliar cobertura.
- Acuerdo: no completar dígitos por inferencia ni usar el catálogo para fabricar el DV; el siguiente análisis debe abordar la recuperación geométrica de 002 con autorización separada.

### 2026-08-04 — Atlas Desktop UX 1.0 — Fases 1 y 2

- Decisión importante: presentar la inteligencia existente mediante un modelo
  de vista aislado en Desktop que consume `evidencias_documentos` y las columnas
  opcionales de trazabilidad del contrato vigente.
- Comportamiento: cada campo muestra `Confirmado`, `Propuesto` o `Revisar`, su
  origen visible (`OCR`, `Catálogo` o `Multicampo`), confianza solo si existe y
  una marca de corrección automática cuando la fuente existente lo demuestra.
- Resumen: la aplicación muestra porcentaje de campos confirmados y, después de
  procesar imágenes, cantidad, resultado y tiempo total medido en Desktop.
- Kilómetros: se reservó la superficie para distancia, tiempo estimado y
  proveedor, con estados iniciales `No calculado` y `Pendiente`; no se ejecutan
  rutas ni llamadas externas.
- Alternativas descartadas: modificar el CSV productivo, extraer trazabilidad
  nueva del motor, inferir confianza o duplicar decisiones multicampo.
- Integridad: OCR, Orquestador, Política, resolvers, catálogos, negocio,
  arquitectura e infraestructura permanecen congelados.
- Validación: 35/35 pruebas, prueba estructural con captura Electron, build
  Windows y ausencia de desbordamiento horizontal.

### 2026-08-04 — Kilómetros visibles en Atlas Desktop — Fase 1

- Decisión importante: conectar Desktop al adaptador OpenRouteService y al
  `CalculadorRutas` existentes mediante un caso de uso Python independiente y
  un único IPC de solo resultado.
- Selección: cada viaje exige un origen y un destino únicos. Ambos deben
  coincidir exactamente con entidades activas y confirmadas; además requieren
  dirección completa y coordenadas canónicas. No se geocodifica ni se infiere.
- Estados: una ruta válida publica kilómetros, duración, proveedor y
  `Calculado`; faltantes documentales producen `Pendiente`; credencial,
  conexión o proveedor fallido producen `No disponible`. Todo estado incluye
  un motivo legible.
- Reutilización: no se creó otro proveedor ni se duplicó transporte HTTP,
  validación de métricas o contrato logístico. El puerto existente permite una
  futura selección multiproveedor sin acoplar Desktop.
- Fuera de alcance: caché, persistencia de rutas, reintentos, fallback,
  analítica y geocodificación automática.
- Validación: consulta ORS real `CALCULADA` entre AZA RENCA y LAS VIOLETAS 55,
  con 33,2 km y 40 min; 63/63 pruebas focales, 1144/1144 de regresión,
  36/36 Desktop, prueba visual
  Electron, build Windows, `compileall` y `git diff --check`.
- Integridad: cero cambios en OCR, Orquestador, Política, resolvers, negocio o
  arquitectura multicampo.

## Acuerdos operativos de coordinación
- La bitácora ejecutiva resume estado, pruebas y riesgos; la bitácora técnica cronológica conserva el porqué de las decisiones.
- Los cambios de bloque deben cerrarse con: documentación, pruebas, auditoría y registro en ambas bitácoras.
- Para detalles de arquitectura y contratos, se consultan las fuentes oficiales de Atlas en lugar de duplicar información extensa.

## Fuentes oficiales de referencia
- [docs/MOTOR_INTELIGENTE_ATLAS.md](docs/MOTOR_INTELIGENTE_ATLAS.md)
- [docs/CONTRATO_VIAJES_DESKTOP.md](docs/CONTRATO_VIAJES_DESKTOP.md)
- [docs/ATLAS_MASTER_CATALOGS.md](docs/ATLAS_MASTER_CATALOGS.md)
- [04_TRABAJOS_ACTIVOS_ATLAS.md](04_TRABAJOS_ACTIVOS_ATLAS.md)
### 2026-08-04 — Hotfix regresión Chofer — guía 464089

- Causa: `67541f0` añadió una condición imposible para publicar la recuperación
  geométrica cuando el valor lineal era `None`, vacío o `No encontrado`.
- Corrección: se restauró la única precondición válida: publicar cuando el
  recuperador geométrico conservador entrega un valor.
- Evidencia real: 464089 pasa de `No encontrado` a `LEANDRO IOLEDO`, lectura OCR
  geométrica disponible; continúa en `REVISAR` porque no se modificaron
  resolvers ni reglas de canonización.
- Regresión: 120/120 pruebas de `procesamiento_masivo` aprobadas. Un caso de
  evidencia débil conserva ahora la recuperación cruda y continúa en
  `REVISAR`, coherente con el comportamiento restaurado.
- Integridad: ningún cambio en OCR, recuperador geométrico, resolvers, Desktop,
  Política de Activación, Sistema Multicampo, catálogos o reglas de negocio.
### 2026-08-04 — Desktop UX — Reprocesamiento Inteligente

- Causa abordada: el arrastre omitía silenciosamente nombres presentes en el
  CSV acumulado, aunque la interfaz comunicaba un procesamiento nuevo.
- Decisión: Desktop consulta primero los nombres existentes y presenta tres
  acciones explícitas: reutilizar, reprocesar completamente o cancelar.
- Reutilizar mantiene el flujo idempotente actual. Reprocesar ejecuta
  `--reprocesar` sobre un CSV nuevo y reemplaza atómicamente las filas
  seleccionadas en el acumulado. Cancelar retorna antes de copiar imágenes.
- Validación 464089: reutilizar mantuvo SHA-256
  `0BC1B97256035467B0EBFAD6A046BFF12A44F677C55EA80DC7B261290ED075EE`;
  reprocesar ejecutó OCR, recuperó `LEANDRO IOLEDO` y actualizó el reporte.
  Desktop muestra `LEANDRO TOLEDO` por normalización existente y conserva la
  lectura cruda en `evidencias_documentos`.
- Integridad: OCR, recuperador geométrico, `procesamiento_masivo`, Orquestador,
  Política, resolvers y reglas de negocio permanecen intactos.

### 2026-08-04 — Despliegue controlado de Atlas Desktop

- Se oficializó `npm run deploy:dev` como único comando de despliegue de
  desarrollo. Exige repositorio limpio, genera metadatos del build, empaqueta,
  respalda `app.asar` y configuración, copia la distribución y relanza la
  instalación objetivo.
- La verificación inspecciona el contenido del `app.asar` y compara ruta,
  SHA-256, commit embebido y versión; además comprueba que el diálogo de
  reprocesamiento forme parte del paquete activo.
- Instalación activa: `C:\Users\corte\Desktop\Atlas Viajes`; commit
  `3bbd3b277fe1a37652c93d7c22cfbfe7da1e2ac7`, versión `1.2.0`, SHA-256
  `5e638fa7efa78202e9636b3ed198462d4b21feff397f75abc7ab63045afd418f`.
- El arranque neutraliza `ELECTRON_RUN_AS_NODE` para impedir que variables del
  entorno de automatización cambien el modo de ejecución de Electron.
- La guía 464089 fue reprocesada realmente: 1/1 procesada, OCR en 49,66 s,
  evidencia `LEANDRO IOLEDO`; el reporte y Desktop publicaron el canónico
  existente `LEANDRO TOLEDO`.

### 2026-08-04 — Logistics UX 1.0

- Se reorganizó exclusivamente la presentación del panel logístico: resumen
  operativo, distancia destacada, tiempo, proveedor, estado y motivo cuando no
  existe cálculo. No cambió el contrato ni el cálculo OpenRouteService.
- La prueba visual cubrió 462429 calculada (33,2 km, 40 min), 464089 pendiente,
  464135 sin dirección y 462474 con proveedor no disponible.
- `npm run deploy:dev` construyó y copió el build. El `app.asar` activo quedó en
  versión 1.2.0, commit `9b67abb7a2b3d6a9ecc98bdf2a644cbdb168eb43`, SHA-256
  `03f0bcddc1e8b3299f31cf973c1fea4266a2fa256706c9b070c1aaefcb5e3892`.
- El relanzamiento fue rechazado por Smart App Control. Code Integrity evento
  3077 registra que el ejecutable no cumple el nivel de firma exigido por la
  política `{0283ac0f-fff1-49ae-ada1-8a933130cad6}`. El flujo oficial no fue
  modificado y la instalación activa no se declaró funcionalmente validada.

### 2026-08-04 — Auditoría de publicación de Cliente canónico 464089

- La imagen documenta `COMERCIAL A Y B LTDA`, RUT `78.634.910-9`. El OCR
  completo observa `COMERCIAL B LIDA` y un RUT incompleto; el extractor entrega
  al Resolver `COMERCIAL` y `No encontrado`.
- Con esos valores y el catálogo activo, el Resolver devuelve `NO_RESUELTO`,
  sin identificador ni valor canónico, vía `NO_RESUELTO` y confianza `0.0`.
  `ACEROS COX COMERCIAL SA` aparece solo como alternativa de similitud 0,6207.
- El catálogo activo no contiene `COMERCIAL A Y B LTDA` ni su RUT documental.
  Por tanto, la Política en estado `PRODUCTIVO` publica correctamente el valor
  previo `COMERCIAL`, motivo `publicacion-productiva`.
- `procesamiento_masivo`, el CSV acumulado, `viajes.csv`, el JSON embebido de
  evidencias y Desktop conservan exactamente `COMERCIAL`. No existe una pérdida
  posterior al Resolver ni una integración canónica pendiente en Desktop.

### 2026-08-04 — Hotfix crítico Drag & Drop Electron 43

- Reproducción: el drop contenía un `File` llamado `464089.jpeg`, MIME
  `image/jpeg`; `DataTransfer.files=1` y `DataTransfer.items=1`. La ruta leída
  mediante `file.path` era `undefined`, por lo que no existía extensión y el
  filtro descartaba el archivo antes de invocar IPC u OCR.
- Último estado funcional en la línea oficial: `f293e8c`, con Electron 31.3.1.
  El commit introductor fue `e15d294`, que fijó Electron 43.2.0 manteniendo el
  acceso obsoleto `File.path`.
- Corrección mínima: `webUtils.getPathForFile` queda encapsulado en preload; el
  renderer procesa `files` y `items`, deduplica objetos y valida `.jpg`, `.jpeg`
  y `.png` sobre la ruta real.
- Instalación empaquetada: JPEG `image/jpeg`, JPG `image/jpeg` y PNG `image/png`
  produjeron rutas absolutas. `384674.jpg` ejecutó OCR en 54,15 s con 1/1
  procesada y cero errores. `464089.jpeg` fue detectada como duplicada por el
  CSV acumulado, condición que abre el diálogo de reprocesamiento.

### 2026-08-04 — Consolidación Inteligente de Viajes, Fase 1

- Atlas Desktop incorpora un modelo de presentación encapsulado que agrupa por el viaje ya emitido por `viajes.csv`; no altera el motor ni la información documental.
- El panel consolidado muestra cantidad y lista de guías, peso total, cantidad total y una tabla por guía con peso, cantidad, material y archivo origen.
- Los totales se calculan únicamente cuando todas las guías poseen evidencia numérica válida. Ante cualquier ausencia, el total y el campo individual se muestran como `No disponible`.
- Validación histórica: transporte `0000350703` con 2 guías; `0000279246` con 3; `0000279047` con 5 documentos. Este último sólo publica cuatro números de guía, por lo que la quinta fila queda explícitamente sin número inferido.
- Validación técnica: 46/46 pruebas Desktop, prueba visual Electron sin desbordamiento y `git diff --check` correcto.
- Despliegue oficial: versión 1.2.0, commit `5acbed0e08e2a0547104c30c62b85fe0e5026e4e`, `app.asar` SHA-256 `17ce3bb5e4cd257411fba7bcc817ee50016cc0602580e2995969c1428d3557e8`.

### 2026-08-04 — UX Operacional Atlas, Fase 1

- La tabla principal queda limitada a fecha, número de guía, cliente, chofer, material y estado. El número de transporte pasa al encabezado del viaje consolidado.
- El detalle se ordena por urgencia operacional: observaciones compactas, viaje consolidado, información logística, inteligencia aplicada y datos auxiliares.
- Las observaciones usan chips compactos editables y, sin marcas activas, presentan únicamente `Sin observaciones operacionales` en estado cerrado.
- Peso y cantidad total se omiten cuando la evidencia no permite totalizarlos; las fuentes `No disponible` dejan de renderizarse. Se incorpora la etiqueta útil `Recuperación geométrica` cuando la trazabilidad la entrega.
- Validación: 49/49 pruebas Desktop, Electron visual sin desbordamiento y matriz simple/multiguía/confirmado/revisión aprobada.
- Alcance preservado: sin cambios en OCR, Multicampo, Política, resolvers, catálogos, ORS ni procesamiento masivo.
- Instalación activa validada: versión 1.2.0, commit `dbc75685bf433beb365f339902f2c89eb45a5dad`, `app.asar` SHA-256 `5bfdfbcf6d7f6bb443340069f2042455ebbca487a39931530ef2778504535891`.

### 2026-08-04 — Calidad de Datos Operacionales, Fase 1

- Cliente 464089: OCR lineal entregaba `COMERCIAL` y ningún RUT; la relectura focal real obtuvo cuatro lecturas concordantes de `78.634.910-9`, válido por módulo 11. El catálogo activo no contenía la entidad y se incorporó `COMERCIAL A Y B LTDA` con evidencia de la guía, sin alias parcial.
- El Resolver confirma el nombre completo sólo cuando el RUT es válido, exacto y único, y el prefijo OCR identifica una única entidad canónica confirmada. La prueba adversarial con dos clientes `COMERCIAL ...` conserva `REQUIERE_REVISION`.
- Peso: `extraer_datos` ya obtenía `14.947,000`, pero `procesamiento_masivo` lo descartaba antes del CSV. Se preserva como columna adicional compatible y queda en `evidencias_documentos`; las 15 columnas oficiales permanecen intactas.
- Validación real 464089: Cliente `COMERCIAL A Y B LTDA`, peso `14.947,000`, material y evidencia originales preservados; Desktop puede totalizar el peso sin inferencias.
- Destinos: 464089 continúa como `COMERCIAL LIDA`; no existe destino canónico documentado para la nueva entidad. 464106 tiene evidencia `VISTA CLARA 2351`, pero requiere validación aislada contra el registro maestro corregido a 2401.
- Patentes: la imagen 464106 documenta tracto `SB6486` y carro `JF4288`; el flujo anterior publicó `J54288` como tracto y perdió ambos roles. No se corrigió porque exige recuperación focal/geométrica específica y regresión vehicular.
- Cantidad: no existe extractor independiente; no se reutilizó peso como cantidad. Materiales: se preservaron descripciones OCR y sólo avanzaron canónicos ya aprobados. Kilómetros: los reportes reales publican `origenes` vacío, por lo que el cálculo se abstiene antes de ORS.
- Regresión: 168 focalizadas, 1148/1148 Atlas y 49/49 Desktop; `compileall` y `git diff --check` aprobados.

### 2026-08-04 — Auditoría del Pipeline de Publicación Operacional, Fase 1

- Trazabilidad real 464106: OCR contenía `CANTIDAD 15.253`, `PESO KG 15.253`,
  “Casa Matriz Planta Renca” y los roles PATENTE/CARRO; el flujo anterior no
  tenía contrato de publicación para origen/cantidad y el OCR lineal degradaba
  las patentes a `836486`/`J54288`.
- Corrección: cantidad se asocia geométricamente sólo bajo su encabezado;
  patentes se recuperan sólo con rol documental, distancia OCR acotada y un
  único vehículo del tipo esperado; origen exige dos lecturas focales
  concordantes y una única planta activa confirmada. Los conflictos abstienen.
- Resultado real: `AZA RENCA`, tracto `SB6486`, rampla `JF4288`, cantidad
  `15.253` y peso `15.253` se preservan en CSV, `viajes.csv`, JSON embebido y el
  modelo de presentación Desktop. El consolidado publica peso y cantidad sin
  inferir.
- ORS recibe `AZA RENCA`; la ruta permanece correctamente `PENDIENTE` por
  “destino no confirmado en catálogo”, ya no por origen ausente.
- Clientes: COMERCIAL A Y B, EBEMA y TORRES OCARANZA confirman con RUT exacto;
  las variantes sin RUT o con RUT inválido siguen `NO_RESUELTO`. En 464106 el
  Cliente y Destino permanecen pendientes; no se redujeron umbrales.
- Validación: 1154/1154 pruebas Atlas, 49/49 Desktop, `compileall` y
  `git diff --check` aprobados.

### 2026-08-04 — Resolución Canónica de Clientes y Destinos, Fase 1

- 464089 permanece estable: el consenso focal `78.634.910-9` y la entidad única
  siguen publicando `COMERCIAL A Y B LTDA`.
- 464106: extracción inicial `IORRSS OCARANZA`; relectura focal estructurada
  `50.234.350-5` en tres lecturas útiles concordantes, válido por módulo 11.
  El fuzzy de nombre era 0,8667, inferior al umbral 0,88, por lo que se mantuvo
  el umbral y se añadió sólo el alias OCR documental exacto a TORRES OCARANZA.
- El reprocesamiento real publica `TORRES OCARANZA LTDA` en procesamiento, CSV,
  reporte y evidencia Desktop. No cambian resolvers, Política, Orquestador,
  pipeline, ORS ni UX.
- Caso equivalente 463528: imagen legible con TORRES OCARANZA LTDA, RUT
  `50.234.350-5` y VISTA CLARA 2351; el RUT focal alcanza consenso y el flujo
  existente confirma el Cliente al reprocesar.
- Destino: `VISTA CLARA 2351` figura en 464106, 463528 y la clave histórica del
  catálogo. Sin embargo, una corrección manual previa establece 2401. El
  registro permanece `PENDIENTE`, con latitud/longitud nulas y existen además
  otros dos destinos de TORRES OCARANZA; el nombre del Cliente no puede usarse
  como alias de Destino.
- Kilómetros: 464106 sigue `PENDIENTE`, motivo `destino no confirmado en
  catálogo`. Para avanzar faltan confirmación autoritativa de 2351/2401 y
  coordenadas exactas.
- Catálogo privado respaldado y manifiesto regenerado: 28 Clientes, 42 alias,
  cero identificadores duplicados y cero promociones automáticas desde OCR.
- Regresión: 1154/1154 Atlas y 49/49 Desktop; compileall y diff-check aprobados.

### 2026-08-04 — Normalización Maestra de Destinos Operacionales, Fase 1

- Decisión operacional aplicada: `VISTA CLARA 2351` es el destino canónico de
  TORRES OCARANZA para el registro `34b754bc-4d2f-4f3f-85e5-98d907106262`.
- Registro confirmado con código destinatario `0001004443`, Cerrillos, Región
  Metropolitana y coordenadas `-33.524258,-70.7149958`, provenientes de la
  ficha Google Maps de Torres Ocaranza Ltda
  (`ChIJN5_ex2HbYpYRfHMnbmBX5q0`).
- ORS/Pelias fue consultado nuevamente y sólo devolvió el centroide de la calle,
  sin número y con comuna genérica Santiago; esas coordenadas no se persistieron.
- El catálogo previo y su manifiesto quedaron respaldados. La fuente privada
  valida 47 destinos y el manifiesto consolidado fue regenerado.
- Reprocesamiento real sin errores: 464106 y 463528. Ambos documentos contienen
  VISTA CLARA 2351 y el código 0001004443, pero el OCR separa la etiqueta
  `COD DESTINATARIO` de su valor; el patrón conservador existente no los asocia
  y la publicación conserva `IORRES OCARANZA LIDA/LTDA`.
- No se añadió ese nombre de Cliente como alias de Destino porque existen tres
  destinos de TORRES OCARANZA y se introducirían falsos positivos.
- Validación controlada, reemplazando sólo en memoria el valor publicado por el
  maestro ya confirmado: AZA RENCA → VISTA CLARA 2351 calculó 16,7 km y 25 min
  con OpenRouteService. El flujo real continúa pendiente hasta que el código
  documental llegue al enriquecimiento; 463528 también requiere origen.
- Regresión: 197/197 pruebas focalizadas y 1154/1154 pruebas Atlas; `compileall`
  y `git diff --check` aprobados.

### 2026-08-04 — Reconstrucción Estructurada de Campos OCR, Fase 1

- Causa demostrada: el OCR detallado entrega etiqueta y valor como cajas
  independientes; `leer_texto_imagen(..., paragraph=True)` pierde la relación
  espacial y el patrón textual exige adyacencia que no existe en el párrafo.
- Se agregó `_reconstruir_campos_etiqueta_valor`, parametrizable por patrones de
  etiqueta y valor. Sólo acepta cajas alineadas o inmediatamente inferiores,
  limita distancia, impide cruzar otra etiqueta y exige un único valor global.
- `_reconstruir_campos_documentales` configura código Cliente, código
  Destinatario, número SAP y número Transporte. También compone etiquetas
  físicamente contiguas como `COD` + `DESTINATARIO`, sin alterar los bloques OCR.
- El enriquecimiento por código exige coincidencia exacta, única, activa y
  confirmada en `destinos_maestros.json`; desconocidos y duplicados se abstienen.
- Reprocesamiento real: 464106 y 463528 pasan de `IORRES OCARANZA LIDA/LTDA` a
  `VISTA CLARA 2351`; el equivalente 464110 pasa de `No encontrado` al mismo
  maestro pese a la etiqueta dividida.
- Ruta real 464106: AZA RENCA → VISTA CLARA 2351, 16,7 km, 25 min,
  OpenRouteService, estado `CALCULADO`. El contrato de presentación Desktop
  consume el resultado como `Calculada`, `16,7 km`, `25 min` y proveedor
  `OpenRouteService`. 463528 conserva `PENDIENTE` por origen
  no informado, no por destino.
- Regresión: 1160/1160 Atlas y 49/49 Desktop; `compileall` y diff-check aprobados.

### 2026-08-05 — Cobertura Operacional de Origen, Fase 1

- Decisión importante: no asumir la causa de los 75/127 documentos sin origen
  del Benchmark 2.0; reproducir el algoritmo real (`leer_encabezado_origen_focal`
  + `_resolver_origen_documental`) contra 9 guías reales del repositorio y
  contra el catálogo privado de plantas realmente vigente en este equipo antes
  de tocar código.
- Hallazgo 1 (dominante y activo hoy): el catálogo privado real ya confirma
  `AZA RENCA` y `AZA COLINA` a la vez. El resolver comparaba contra el bloque
  OCR completo del encabezado, que siempre incluye el directorio fijo de
  sucursales impreso en toda guía AZA (Antofagasta, Temuco, Talcahuano,
  Colina). Cuando ese directorio menciona "Colina", coincide también con la
  planta confirmada `AZA COLINA` y la ambigüedad anula el voto — reproducido
  ejecutando el resolver real contra el catálogo real: 464089 y 462429 (guías
  reales, evidencia legible de `AZA RENCA`) pasaban de `AZA RENCA` a `None`
  únicamente por agregar `AZA COLINA` como planta confirmada, sin tocar OCR
  ni umbrales.
- Hallazgo 2 (independiente): el recorte del encabezado usa porcentajes fijos
  de ancho/alto que asumen orientación vertical. La guía real 464108
  (1280×960, apaisada, sin EXIF útil) cae con ese recorte sobre la tabla de
  cantidades y nunca ve el encabezado; confirmado visualmente y por OCR real,
  con probabilidad cero de coincidencia sin importar el catálogo.
- Alternativas descartadas: releer con `leer_bloques_imagen` de página
  completa (probado contra 4 guías reales; en 3 de 4 el detector ni siquiera
  segmentó "CASA MATRIZ PLANTA RENCA" como texto a resolución completa — el
  recorte dedicado con realce de contraste es necesario, no el problema);
  bajar el umbral de distancia OCR; crear un alias o regla específica para
  AZA; ampliar OCR a campos ausentes.
- Corrección: `_resolver_origen_documental` corta los tokens de cada lectura
  en la primera mención tolerante a ruido OCR (distancia≤1) de "SUCURSAL"
  antes de comparar contra el catálogo; sin esa palabra el comportamiento es
  idéntico al previo. `leer_encabezado_origen_focal` admite un giro opcional
  y `procesar_archivo` reintenta 90/180/270 grados únicamente cuando la
  lectura a 0° no confirma origen, sin costo adicional en el caso típico.
- Validación real (catálogos privados reales, 9 guías reales, sin datos
  sintéticos): cobertura de origen en la muestra 4/9→7/9. 464089 y 462429
  recuperados por el corte de sucursales; 464108 recuperado por el reintento
  de rotación; 464106, 464135, 464110 y 384674 sin cambios porque ya
  resolvían; 464107 (desenfoque severo, texto irreproducible en las 3
  variantes) y 464109 (EasyOCR omite la línea del encabezado en las 3
  variantes pese a ser legible a simple vista) permanecen correctamente en
  `No encontrado`: ninguna corrección conservadora puede recuperarlos sin
  inventar evidencia.
- Impacto en rutas verificado con datos reales: ninguno de los tres
  documentos recuperados tiene destino `CONFIRMADO`/`ACTIVO` en el catálogo
  privado vigente (solo 3 de 47 destinos lo están). `calcular_rutas_desktop.
  calcular_fila` confirma que el motivo de bloqueo cambia de "origen no
  informado" a "destino no confirmado en catálogo" / "destino no informado"
  — el origen deja de ser el bloqueador, pero el viaje sigue `PENDIENTE`.
  Con una consulta real a OpenRouteService confirmé el mecanismo completo:
  sin origen y con VISTA CLARA 2351 confirmado → `PENDIENTE` "origen no
  informado"; con `AZA RENCA` presente → `CALCULADO`, 16,7 km, 25 min (mismo
  resultado ya validado para 464106). No se declara un número de viajes ni de
  kilómetros nuevos en Desktop: ningún documento disponible combina origen
  recién recuperado con destino ya confirmado, y no se inventa esa cifra.
- Regresión: 1165/1165 Atlas (5 pruebas nuevas); `compileall` y
  `git diff --check` aprobados.
- Integridad: sin cambios en OCR base, Sistema Multicampo, Política de
  Activación, Orquestador, resolvers de Cliente/Chofer/Destino/Material,
  OpenRouteService ni Desktop.
- Acuerdo: el siguiente bloque debe abordar la calidad documental de Destino
  sobre el universo real para que los orígenes ya recuperados también puedan
  calcular ruta; no se autoriza tocar resolvers ni catálogos de destino en
  este bloque.

### 2026-08-05 — Calidad Documental de Destinos, Fase 1

- Decisión importante: analizar el pipeline completo de Destino (OCR →
  extracción → resolución canónica → procesamiento → CSV → reporte →
  Desktop) con guías reales y catálogos privados reales antes de tocar
  código, igual que en Origen.
- Hallazgo 1 (dominante): `_orquestar_destino_sombra` cargaba `destinos.json`
  — un catálogo legado código→nombre de 6 registros sin relación con el
  esquema que `resolver_destino_ubicacion`/`crear_snapshot_catalogo_destinos`
  esperan — en vez de `destinos_maestros.json` (47 registros reales, 3
  `CONFIRMADO`, el mismo catálogo que usan `calcular_rutas_desktop.py` y la
  reconstrucción de código destinatario). Confirmado por `git log`: ambos
  catálogos se conectaron en commits de días distintos y el punto de
  integración del orquestador nunca se migró. Reproducido ejecutando el
  resolver real con el mismo input exacto: `NO_RESUELTO` con `destinos.json`,
  `CONFIRMADO → VISTA CLARA 2351` con `destinos_maestros.json`.
- Hallazgo 2: `extraer_datos` nunca capturaba los campos documentales
  `DIRECCION`/`COMUNA`. El OCR real sí los lee correctamente en la misma
  línea (verificado en 3 guías reales), pero el resolver de destino solo
  recibía el campo libre `OBRA DESTINO`, que en el layout real observado
  suele ser el nombre del cliente, no una dirección (464106 real imprime
  "OBRA DESTINO: TORRES OCARANZA LTDA").
- Hallazgo 3: ningún CLI de producción (`analizar_guias_masivo.py`) exponía
  `campos_controlados_autorizados`; aunque el resolver confirmara, la
  Política nunca publicaba Destino por falta de autorización explícita.
- Alternativas descartadas: cambiar a lectura de página completa para
  dirección/comuna (innecesario; el recorte por línea ya funciona con datos
  reales); bajar el umbral fuzzy de destino; promover en bloque los 44
  destinos `PENDIENTE` sin evidencia documental individual; modificar
  Política o el Orquestador para forzar publicación.
- Corrección: (1) apuntar el orquestador en sombra a `destinos_maestros.json`;
  (2) `extraer_datos` agrega `buscar_direccion`/`buscar_comuna`, mismo patrón
  de línea que `buscar_obra_destino`, y `procesar_archivo` los pasa al
  resolver como cadena vacía (no "No encontrado") cuando están ausentes, para
  no fabricar una contradicción de dirección; (3) se agregó
  `--autorizar-campos-controlados` a `analizar_guias_masivo.py`, plomeado al
  parámetro `campos_controlados_autorizados` que ya existía en
  `procesar_carpeta`/`procesar_archivo`, sin tocar Política.
- Defecto adicional encontrado durante la validación con datos reales (no
  hipotético): al reprocesar con autorización activa, la guía real 464110
  perdió su destino ya confirmado `VISTA CLARA 2351` (vinculado por código
  destinatario) y publicó `No encontrado`. Causa: cuando el resolver en
  sombra no confirmaba nada nuevo pero la Política sí publicaba, el valor de
  respaldo era el OCR previo al enriquecimiento por código destinatario, no
  el valor ya enriquecido — pisando una identidad ya validada por un
  mecanismo distinto. Corregido para respaldar siempre con
  `datos.get("obra destino")` actual, nunca con el OCR original. Prueba de
  regresión agregada reproduciendo exactamente este caso.
- Curación documental con evidencia real: la guía 462429 (PRODALAM SA,
  RUT 93.772.000 sin DV en el OCR, confirmado como 93772000-9 por el
  resolver de cliente) imprime dirección "ALBERIO PEPPER 1610" y comuna
  "RENCA". El catálogo privado ya contenía "ALBERTO PEPPER 1610, RENCA,
  CHILE" con el mismo `cliente_id` de PRODALAM SA, migrado de un estudio
  histórico y en estado `PENDIENTE`. Con número exacto (1610) y calle casi
  idéntica (ruido OCR T→I), se promovió a `CONFIRMADO` siguiendo el mismo
  criterio documental usado para VISTA CLARA 2351; se respaldó el catálogo
  antes de editar y se documentó la evidencia en la observación del
  registro. Las coordenadas del registro siguen siendo aproximadas (ORS
  fallback, confidence=0.6, nivel calle/comuna); el kilómetro resultante
  hereda esa aproximación, declarado explícitamente.
- Validación real (9 guías reales, catálogos privados reales,
  `--autorizar-campos-controlados destino`): 462429 pasa a `ALBERTO PEPPER
  1610` confirmado; 464106 y 464110 conservan `VISTA CLARA 2351` sin
  regresión; 464089, 464135 y 384674 conservan su texto OCR sin confirmar
  (sin destino catalogado equivalente evaluado con evidencia suficiente);
  464107, 464108 y 464109 continúan sin destino por las mismas causas de
  calidad de imagen ya documentadas en Origen.
- Impacto operativo real, verificado con `calcular_rutas_desktop.py` y una
  consulta real a OpenRouteService: la guía 462429 pasa de `PENDIENTE`
  ("origen no informado") a `CALCULADO`, 6,3 km, 11 min. Es el primer viaje
  real de esta fase que llega a Ruta Calculada combinando el origen
  recuperado en el bloque anterior con el destino confirmado en este bloque.
- Regresión: 1172/1172 Atlas (7 pruebas nuevas); `compileall` y
  `git diff --check` aprobados.
- Integridad: sin cambios en OCR base, Sistema Multicampo, Política de
  Activación, Orquestador, resolvers de Cliente/Chofer/Material,
  OpenRouteService ni Desktop. `resolver_destino_ubicacion` no se modificó;
  solo se corrigió el catálogo que recibe y se le agregó evidencia de
  dirección/comuna que antes nunca le llegaba.
- Riesgo residual: 42/47 destinos reales ya tienen dirección y coordenadas
  pero siguen `PENDIENTE` sin evidencia documental individual verificada;
  no se promovieron sin esa evidencia. El flag de autorización no está
  conectado a Desktop; solo se usó manualmente para esta validación.
- Acuerdo: el siguiente bloque debe revisar guía por guía los 42 destinos
  `PENDIENTE` restantes contra evidencia documental real, y decidir si
  Desktop debe exponer la autorización de Destino de forma controlada.

### 2026-08-05 — Hotfix: Incompatibilidad de Esquema en CSV de Reprocesamiento

- Decisión importante: diagnosticar con el CSV real de producción antes de
  tocar código. El usuario reportó que Atlas abortaba antes de iniciar OCR
  al cargar 35 guías nuevas desde Desktop, con
  `ValueError: Los CSV de reprocesamiento tienen esquemas incompatibles`
  desde `resumen_procesamiento_desktop.py`.
- Hallazgo: el CSV acumulado real de la instalación activa
  (`C:\Users\...\AppData\Local\Atlas\datos\procesamiento\
  analisis_completo_guias.csv`) no se había tocado desde 2026-07-28 (1.177
  filas, 21 columnas: 15 base + 6 de traza histórica). Los bloques
  "Calidad de Datos Operacionales" y "Auditoría del Pipeline de
  Publicación Operacional" (2026-08-04) ampliaron `COLUMNAS_PUBLICACION` a
  18 columnas (+`peso`, `cantidad`, `origen`) y enseñaron a
  `_validar_csv_existente` a migrar esa diferencia de forma aditiva, pero
  nunca tocaron `resumen_procesamiento_desktop.py::comando_reemplazar`, que
  mantenía su propia comparación `columnas_masivo != columnas_reprocesado`
  — una igualdad estricta de orden y conjunto, sin ninguna tolerancia a la
  evolución aditiva del esquema.
- Evidencia real, no simulada: reproduje el error exacto usando una copia
  del CSV acumulado real de producción contra un CSV sintético con el
  esquema vigente — mismo mensaje reportado por el usuario. Verifiqué
  también que `_validar_csv_existente`, aplicada a una copia del mismo
  archivo real, migra correctamente: agrega `peso`/`cantidad`/`origen`
  vacíos, conserva las 1.177 filas y las 21 columnas originales sin ninguna
  diferencia.
- Alternativas descartadas: reescribir manualmente el CSV de producción;
  bajar o eliminar la validación de esquema en `comando_reemplazar`;
  mantener dos validaciones de esquema en paralelo (la causa del defecto).
- Corrección: `comando_reemplazar` reutiliza `_validar_csv_existente` como
  única fuente de verdad — se eliminó por completo la comparación paralela.
  Se aplica a ambos archivos (acumulado y reprocesado) antes de leerlos, de
  forma atómica y determinista. La fusión final usa la unión de columnas de
  ambos encabezados (ya normalizados), preservando toda columna de traza
  histórica y sin inventar valores en las columnas nuevas; la escritura usa
  `extrasaction="ignore"` para tolerar la diferencia legítima entre ambos
  orígenes. Las validaciones de seguridad (prefijo de 15 columnas fijas,
  columnas desconocidas o duplicadas) se conservan intactas, por ser las
  mismas de `_validar_csv_existente`; se agregó una prueba que confirma que
  un esquema genuinamente incompatible sigue rechazándose.
- Validación real end-to-end: se respaldó el CSV de producción y se migró
  con `_validar_csv_existente` — 1.177 filas antes y después, cero
  diferencias en las 21 columnas originales, cero valores inventados en las
  3 columnas nuevas. Se reprodujo además el flujo completo de Desktop
  (`comando_existentes` → OCR real vía `procesar_carpeta` con catálogos
  privados reales → `comando_reemplazar`) contra una copia del acumulado
  **sin migrar**, usando 4 guías reales nunca antes procesadas (464107,
  464108, 464109, 464110): el merge ya no lanza `ValueError`, produce
  1.177+4=1.181 filas y cero diferencias en las 1.177 filas históricas.
- Regresión: 1174/1174 Atlas (3 pruebas nuevas); `compileall` y
  `git diff --check` aprobados.
- Integridad: sin cambios en OCR, Sistema Multicampo, Política de
  Activación, Orquestador, resolvers, catálogos, OpenRouteService ni
  Desktop; `procesamiento_masivo.py::_validar_csv_existente` no se
  modificó, solo se reutilizó desde el segundo punto de validación.
- Riesgo residual: no fue posible confirmar visualmente en la interfaz de
  Desktop porque el ejecutable instalado sigue bloqueado por Smart App
  Control (Code Integrity 3077, ya documentado en "Logistics UX 1.0" y sin
  relación con este fix). La validación se hizo en la capa Python que
  Desktop invoca directamente, confirmada por la ruta `carpetaProyectoPython`
  del `config.json` activo de la instalación.
- Acuerdo: el siguiente bloque de Desktop debe resolver la firma/confianza
  del ejecutable para permitir una validación visual completa.

### 2026-08-05 — Calidad de Publicación Operacional — Fase 1

- Decisión importante: diagnosticar primero, sin tocar código, por qué los
  datos extraídos no terminan publicados correctamente en Desktop, usando la
  guía real 464260 como caso principal (valores observados por el usuario en
  Desktop: Cliente `"SOLICITANTE SALCMON SACX SAX SRUOKON SACK"`, Destino
  `"DIRECCION PAES1D EDO FAEL MOYTALVA 9770"`, Patente tracto `"J54288"`,
  Cantidad `"10002943"`, Material `"No disponible"`) más otras guías reales
  del mismo lote (`output/_entrantes_desktop/20260805_170250` y
  `output/_entrantes_desktop/20260805_152139`) antes de proponer ninguna
  corrección.
- Trazado real campo por campo (EasyOCR → `extractor.py` lineal → geometría →
  `procesamiento_masivo.py` → `procesar_archivo` completo) sobre 464260,
  reproducido con `crear_lector_ocr`/`leer_texto_imagen`/`leer_bloques_imagen`
  reales, sin simular ningún texto:
  1. **Cliente/Destino (Extracción → Publicación)**: el extractor lineal captura
     por regex sobre el párrafo OCR completo sin límite de columna. EasyOCR
     fusionó la fila `SOLICITANTE/TELEFONO/OBRA DESTINO/COD DESTINATARIO` (columna
     derecha) con la fila `SEÑOR(ES)` (columna del cliente) y la fila
     `DIRECCION/COMUNA/CIUDAD` (columna izquierda) con `OBRA DESTINO`, en un
     único bloque de 842 caracteres. El resultado lineal arrastra la etiqueta
     ajena completa. `procesamiento_masivo.procesar_archivo` ya detecta y
     corrige esta misma contaminación para Chofer (`_chofer_lineal_contaminado`
     + recuperación geométrica en el bloque `campos_ausentes`), pero no existía
     un detector equivalente para Cliente/Destino, así que el valor
     contaminado se publicaba tal cual.
  2. **Patente rampla (Extracción)**: la etiqueta "CARRO" solo se reconocía con
     la letra "O" (`_extraer_patentes_geometricas` y `buscar_chofer_y_patentes`
     dentro de `extraer_datos`). El bloque OCR real de 464260 es
     `"RodRiGo NAHUELNIR 506466 CARR0:J54288 05-08-2026"` — EasyOCR leyó la
     etiqueta como "CARR0" (cero). Sin reconocerla, el único candidato válido
     de 6 caracteres alfanuméricos en la zona ("J54288") quedaba asignado al
     tracto por el escaneo genérico, y la rampla nunca se publicaba.
  3. **Cantidad (Extracción)**: `_extraer_cantidad_geometrica` aceptaba
     `\d{1,3}(?:[.]\d{3})+` **o** cualquier `\d+` suelto bajo la etiqueta
     CANTIDAD. En 464260 la celda fusionada bajo esa etiqueta contiene el
     código de producto `"10002943"` (sin separador de miles); al no exigir el
     formato documental, ese código se publicaba como si fuera la cantidad.
  4. Chofer, patente tracto (cuando no hay contaminación de carro) y demás
     campos ya llegaban correctamente hasta Desktop; el problema estaba
     acotado a estos tres puntos, confirmados también en 464145 (Destino con
     "RUT" arrastrado) y en el bug de patente ya documentado en 464106.
- Alternativas descartadas: bajar el umbral de confianza de OCR; agregar un
  alias genérico "CARRO/CARR0" en el catálogo de vehículos; tratar el caso
  como específico de la guía 464260 (`if numero_guia == "464260"`), igual que
  los fallbacks legado ya señalados en la auditoría previa — todas
  rechazadas por instrucción explícita del usuario y por reintroducir el
  mismo patrón fuera de alcance.
- Corrección (autorizada explícitamente tras el diagnóstico, alcance
  estrictamente acotado a lo demostrado):
  1. `atlas_core/extractor.py`: `_valor_lineal_contaminado(valor, etiquetas)`
     generaliza la lógica ya existente de `_chofer_lineal_contaminado`;
     `_cliente_lineal_contaminado`/`_obra_destino_lineal_contaminado` reutilizan
     esa función con tablas de etiquetas ajenas (`_ETIQUETAS_AJENAS_CLIENTE`,
     `_ETIQUETAS_AJENAS_OBRA_DESTINO`) documentadas con evidencia real
     (464260, 464145). `atlas_core/procesamiento_masivo.py`: el bloque
     `campos_ausentes` de `procesar_archivo` ahora también dispara la
     recuperación geométrica cuando Cliente/Destino están contaminados (no
     solo ausentes), reutilizando `_extraer_asociaciones_geometricas` ya
     congelada; nunca sobreescribe con un valor geométrico vacío ni inventa
     datos nuevos.
  2. `_extraer_patentes_geometricas` y `buscar_chofer_y_patentes` (dentro de
     `extraer_datos`) toleran de forma determinista `CARR[O0]` (una sola
     letra en una posición fija, no una coincidencia difusa). En la ruta
     lineal se añadió una exclusión posicional: el tramo de texto ya asignado
     al carro por su propia etiqueta no puede volver a reclamarse como
     tracto en el escaneo genérico de 6 caracteres.
  3. `_extraer_cantidad_geometrica` exige el separador de miles
     (`\d{1,3}(?:[.]\d{3})+`); sin él, se abstiene en vez de publicar un
     código de producto como cantidad.
- Validación real end-to-end, guía 464260 (antes → después, mismo catálogo
  real de vehículos y plantas):
  - Cliente: `"SOLICITANTE SALCMON SACX SAX SRUOKON SACK"` → `"SRUOKON SACK"`.
  - Obra destino: `"DIRECCION PAES1D EDO FAEL MOYTALVA 9770"` →
    `"SALCHON SACX SAY"`.
  - Patente tracto: `"J54288"` (robado al carro) → `"No encontrado"`
    (abstención correcta; el catálogo de vehículos real no ofrece un segundo
    candidato de tracto en esta guía).
  - Patente rampla: `"No encontrado"` → `"JF4288"` (recuperada por
    coincidencia con el catálogo real de vehículos, distancia 1).
  - Cantidad: `"10002943"` → `"No encontrado"` (abstención correcta).
  - Sin cambios: Chofer (`"RodRiGo NAHUELNIR"`), origen (`"AZA RENCA"`).
  - La calidad intrínseca del OCR de los nombres propios ("SRUOKON SACK",
    "SALCHON SACX SAY") no se corrigió: es exactamente el texto que EasyOCR
    ya leía en esa columna, y mejorar OCR estaba fuera de alcance.
- Validación real adicional, mismo lote (`extraer_datos`/`procesar_archivo`
  reales, sin simulación): 463774 y 463936 sin regresión en los campos ya
  correctos; 464145 deja de publicar el destino contaminado con "RUT ..." y
  pasa a `"SODIYAS RENC"`. Guía de control 463604 (contiene "CARRO" con
  letra O, no "CARR0"): `patente_tracto="KX5439"` y `patente_rampla="JF6468"`
  permanecen exactamente iguales — cero regresión. Se completó además el
  reprocesamiento real de 464206, 464259 y del lote 464106–464110 (las
  guías usadas en los bloques "Cobertura Operacional de Origen" y
  "Reconstrucción Estructurada de Campos OCR"): 464106 conserva intactos
  `patente_tracto="SB6486"`, `patente_rampla="JF4288"`, `cantidad="15.253"`
  y `peso="15.253"` (los mismos valores ya validados en esos bloques
  anteriores); 464110 conserva `obra_destino="VISTA CLARA 2351"` (el caso
  exacto protegido por
  `test_procesar_archivo_destino_por_codigo_no_se_pierde_si_sombra_no_confirma`
  de la Fase 1 de Destinos); 464107/464108/464109 permanecen con las mismas
  ausencias ya documentadas por desenfoque u omisión de OCR, no corregibles
  de forma conservadora. Cero regresiones en todo el lote real disponible.
- Regresión: 1185/1185 Atlas (11 pruebas nuevas: contaminación de
  Cliente/Destino, tolerancia CARR0 en ambas rutas de patente con exclusión
  posicional, abstención de Cantidad sin separador de miles); `compileall` y
  `git diff --check` aprobados.
- Integridad: sin cambios en EasyOCR, umbrales, Sistema Multicampo, Política
  de Activación, Orquestador, OpenRouteService ni Desktop; ninguna regla usa
  el número de guía como condición.
- Hallazgo adicional fuera del alcance de este bloque (diagnóstico, sin
  cambios de código): el usuario reportó que la pestaña "Revisión de
  destinos" de Atlas Desktop se ve completamente vacía, cuando antes mostraba
  un mapa e información GPS de destinos. Para diagnosticarlo con evidencia
  real (no especulación) se extrajo de forma solo-lectura el `app.asar` de la
  instalación activa (`C:\Users\...\Desktop\Atlas Viajes\resources\app.asar`,
  vía `npx asar extract`, sin modificar el archivo original). El
  `build_info.json` embebido identifica exactamente el build activo: versión
  `1.2.0`, commit `dbc75685bf433beb365f339902f2c89eb45a5dad`, rama
  `feature-consolidacion-viajes-1` — que coincide con el commit corto
  `dbc7568` citado en esta misma bitácora para "UX Operacional Atlas — Fase
  1" (2026-08-04), el **último** despliegue de Desktop registrado en el
  proyecto. La pestaña vive en `src/atlas_viajes.html`
  (`#tab-revision-destinos` / `#vista-revision-destinos`) y su lógica en
  `src/revision_destinos_ui.js` + `src/revision_destinos_logic.js`: una
  búsqueda exhaustiva en todo el árbol de la aplicación (fuente y
  `node_modules` empaquetados) por "mapa", "leaflet", "gps", "latitud" y
  "longitud" no arrojó ningún resultado — no hay ninguna librería de mapas
  incluida ni código que dibuje coordenadas. La pestaña es, en este build, un
  flujo de revisión de decisiones sobre un archivo JSON ("bandeja") que el
  usuario debe abrir manualmente (`window.atlasAPI.seleccionarBandejaDestinos`
  → diálogo nativo de archivo → `revisiones_destinos.json`); sin ese archivo
  cargado muestra el estado vacío por diseño ("No hay una bandeja de destinos
  cargada"), y aun con datos cargados solo renderiza tabla y texto, nunca un
  mapa. No se pudo identificar el commit exacto que haya retirado un
  eventual mapa anterior porque el repositorio fuente de
  `Atlas-Viajes-Desktop` no es accesible desde esta sesión (solo el binario
  empaquetado) y ninguna entrada previa de esta bitácora documenta haber
  construido un componente de mapa para esta pestaña. No se implementó
  ningún rediseño ni hotfix, conforme a lo solicitado.
- Riesgo residual: la limpieza de contaminación de Cliente/Destino expone
  texto OCR crudo de esa columna que puede seguir siendo poco legible por
  calidad de imagen; ambos campos permanecen sujetos a
  `indicador_revision = REVISAR` cuando corresponde. La pestaña "Revisión de
  destinos" de Desktop sigue sin mostrar mapa/GPS; resolverlo requiere
  trabajo en el repositorio `Atlas-Viajes-Desktop`, fuera del alcance de esta
  sesión.
- Acuerdo: si se confirma que existió un mapa antes de
  `feature-consolidacion-viajes-1`, el siguiente bloque de Desktop debe
  revisar su propio historial de git alrededor de esa rama para decidir entre
  restaurarlo o documentar el flujo manual de bandeja como comportamiento
  esperado.

### 2026-08-05 — Resolución Inteligente de Identidades Operacionales — Fase 1 (Cliente ↔ Destino)

- Decisión importante: diagnosticar primero, sin tocar código, por qué Atlas
  publica el texto OCR limpio de Cliente/Destino tal cual, sin convertirlo en
  identidad canónica, cuando ya existe evidencia estructural suficiente
  (RUT, Código Cliente, Código Destinatario, SAP, catálogos) para hacerlo.
- Mapeo real de la arquitectura (lectura directa del código, no supuestos):
  `resolver_cliente_rut` (`atlas_core/inteligencia/resolucion_cliente.py`)
  solo combinaba nombre + RUT propios; `contexto` (destino/material en
  texto) únicamente sumaba un bono de 0.25 a un candidato ya elegido por
  nombre o RUT, nunca generaba uno. `resolver_destino_ubicacion`
  (`atlas_core/inteligencia/resolucion_destino.py`) sí recibía
  `id_cliente_canonico`/`cliente_canonico`, pero solo como bono de +20 sobre
  un `score` que ya debía ser mayor que 0 por nombre o dirección — si el
  nombre OCR no superaba el umbral fuzzy (0.88) y la dirección tampoco
  coincidía, ese destino nunca entraba al diccionario de candidatos,
  cliente_id o no. El Código Destinatario, extraído de forma estructural por
  `_reconstruir_campos_documentales`, solo se usaba en un atajo previo y
  simple (`atlas_core.catalogos.enriquecer_datos_con_catalogos` →
  `_buscar_destino_maestro_por_codigo_estructurado`), completamente fuera
  del contrato Multicampo (sin `EvidenciaResolucion`, sin `via_decision`, sin
  traza de auditoría) y nunca llegaba al resolver real de Destino ni,
  mucho menos, al de Cliente.
- Evidencia real, guía 464110 (inspección directa de los catálogos privados
  reales): `destinos_maestros.json` tiene `"VISTA CLARA 2351"` con
  `codigo_destino="0001004443"` y `cliente_id="0f9d4dfa-..."`;
  `clientes.json` tiene ese mismo `cliente_id` con
  `razon_social="TORRES OCARANZA LTDA"`, `estado_calidad="CONFIRMADO"`,
  `estado_vigencia="ACTIVO"`. Trazado real (`extraer_datos` +
  `_reconstruir_campos_documentales` + `enriquecer_datos_con_catalogos`
  sobre la guía real): `cliente` y `RUT del cliente` llegan `"No encontrado"`
  desde el extractor lineal; el gate de `procesamiento_masivo.procesar_archivo`
  que decide si vale la pena llamar a `resolver_cliente_rut` (`nombre != ""
  or rut != ""`) daba `False`, así que **el resolver de Cliente nunca se
  invocaba** para esta guía — mientras que `obra destino` sí se resolvía
  correctamente a `"VISTA CLARA 2351"` por el atajo de Código Destinatario.
  La identidad de cliente estaba deducible con evidencia 100% determinista,
  ya cargada en memoria para la misma guía, y nunca se usaba.
- Alternativas descartadas: bajar el umbral fuzzy de nombre; agregar un
  alias genérico "TORRES OCARANZA"/variantes OCR al catálogo; memorizar la
  guía 464110/464106 con un `if numero_guia == ...` — todas rechazadas por
  instrucción explícita y por reproducir el mismo patrón de fallbacks por
  guía ya señalado en la auditoría previa.
- Mecanismo general implementado (autorizado tras el diagnóstico, alcance
  estrictamente acotado a Cliente↔Destino):
  1. `atlas_core/inteligencia/snapshot_catalogo_destinos.py`: se agrega
     `codigo_destino` a los campos preservados del snapshot de destinos
     (antes se descartaba por completo al congelar el catálogo).
  2. `atlas_core/inteligencia/politica_confianza_destino.py` y
     `politica_confianza_cliente.py`: nuevas vías `CODIGO_DESTINATARIO_EXACTO`
     (0.98, al nivel de una dirección completa exacta) y
     `CLIENTE_ID_POR_DESTINO_CODIGO` (0.93, por debajo del RUT leído en el
     propio documento pero por encima de un nombre canónico exacto aislado,
     porque exige unicidad y calidad confirmada en dos catálogos distintos).
  3. `resolver_destino_ubicacion` gana el parámetro `codigo_destinatario`:
     una coincidencia exacta y única contra `codigo_destino` del registro
     genera candidato por sí sola (antes solo nombre/dirección podían
     hacerlo); un conflicto entre código y un nombre/dirección fuerte de
     *otro* destino se vuelve `ContradiccionResolucion` explícita en vez de
     sobrescribir en silencio. El resto de las validaciones ya existentes
     (calidad confirmada, activo, dirección/comuna/región compatibles)
     siguen aplicando igual, por ser genéricas sobre el candidato elegido.
  4. `resolver_cliente_rut` gana el parámetro `id_cliente_por_destino_codigo`:
     se busca ese identificador exacto en el snapshot de clientes (sin
     ninguna comparación difusa); si es único, activo y de calidad
     confirmada, y no contradice al RUT o nombre observados, confirma
     cliente por la nueva vía. Un conflicto con RUT o nombre se vuelve
     `ContradiccionResolucion` y exige revisión, igual que la contradicción
     RUT-vs-nombre ya existente.
  5. `procesamiento_masivo.procesar_archivo` conecta la cadena reutilizando
     `_buscar_destino_maestro_por_codigo_estructurado` (la misma función ya
     usada por el enriquecimiento de destino, sin duplicar lógica de
     búsqueda) para obtener el `cliente_id` del destino ya vinculado por
     código, y lo pasa a `resolver_cliente_rut`. El gate que decide si
     reconstruir campos estructurados desde bloques OCR ahora también se
     activa cuando cliente no tiene nombre ni RUT legibles (antes solo
     dependía del estado de destino), y el gate que decide si invocar al
     resolver de Cliente ahora también se activa cuando existe esa
     evidencia cruzada, aunque nombre y RUT vengan vacíos.
- Corrección de una regresión propia detectada en el primer `pytest` tras
  implementar: extender el primer gate a "cliente sin evidencia" sin
  condicionarlo a que el catálogo realmente tenga códigos de destino rompió
  4 pruebas existentes que no mockean catálogos ni imagen (`extraer_datos`
  devolvía `{}`; el código intentaba entonces leer una imagen de prueba
  inexistente y lanzaba `FileNotFoundError`). Se corrigió exigiendo primero,
  como ya hacía el gate original, que el catálogo de destinos tenga al menos
  un `codigo_destino` no vacío antes de intentar la reconstrucción
  geométrica.
- Validación real end-to-end (mismos catálogos privados reales,
  reprocesamiento completo):
  - 464110 (caso principal): `cliente` `"No encontrado"` →
    `"TORRES OCARANZA LTDA"`; `obra_destino` se mantiene `"VISTA CLARA 2351"`;
    el resto de los campos sin cambios.
  - 464106: `cliente="TORRES OCARANZA LTDA"` sin cambios (ya resolvía por
    evidencia directa); cero regresión.
  - 464260: `cliente="SRUOKON SACK"` sin cambios — su Código Destinatario
    (`00D2N032BD`) no coincide con ningún destino confirmado del catálogo
    real, así que la cadena nunca se completa y el campo permanece
    correctamente en abstención, tal como exige el contrato conservador.
  - Guía de control 463604: `cliente="TORRES OCARANZA LTDA"` sin cambios.
  - Resto del lote real (463774, 463936, 464145, 464206, 464259, 464107,
    464108, 464109): sin cambios en ningún campo — cero regresiones.
- Regresión: 1199/1199 Atlas (14 pruebas nuevas: vía por código en
  `resolucion_cliente_multicampo`, vía por código en
  `resolucion_destino_multicampo`, dos pruebas de integración reales en
  `test_procesamiento_masivo.py` reproduciendo 464110 y 464260);
  `compileall` y `git diff --check` aprobados.
- Integridad: sin cambios en EasyOCR, umbrales de ningún campo, alias
  genéricos, Política de Activación, Orquestador Multicampo,
  OpenRouteService ni Desktop; ninguna regla usa el número de guía como
  condición; el mismo contrato de evidencia/confianza/contradicción/
  abstención de los resolvers existentes se mantiene sin excepciones.
- Riesgo residual: Código Cliente quedó cableado con el mismo mecanismo
  general (parámetro `id_cliente_por_destino_codigo` acepta cualquier
  `cliente_id` determinado externamente, no solo el derivado de destino),
  pero es inerte en producción porque `clientes.json` no tiene ningún campo
  `codigo_cliente` hoy. Chofer y Material quedaron explícitamente fuera de
  este bloque: Chofer porque `vehiculos.json` no tiene ningún vínculo
  patente↔chofer; Material porque no existe `materiales.json` real en la
  instalación de producción (ninguno de los dos es un problema de cableado
  de evidencia, sino de datos/catálogo faltante).
- Acuerdo: por instrucción explícita, el siguiente bloque es exclusivamente
  la recuperación del panel GPS / "Revisión de destinos" de Atlas Desktop;
  Chofer y Material quedan pendientes de una autorización aparte.
