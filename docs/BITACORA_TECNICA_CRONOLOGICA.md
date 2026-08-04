# Bitácora Técnica Cronológica

## Propósito
Esta bitácora registra, en orden temporal, las decisiones importantes, cambios de estrategia, alternativas descartadas, problemas detectados, justificaciones de decisiones y acuerdos entre herramientas para que ChatGPT, GitHub Copilot y Claude Code compartan el mismo contexto sin revisar todo el historial del repositorio.

## Convención de uso
- Se actualiza al cierre de cada bloque.
- Cada entrada debe explicar por qué se tomó una decisión y qué alternativa fue descartada.
- La información detallada del flujo técnico debe enlazarse a la documentación de Atlas cuando sea extensa.

## Registro cronológico

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
