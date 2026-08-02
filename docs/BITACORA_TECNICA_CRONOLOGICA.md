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

## Acuerdos operativos de coordinación
- La bitácora ejecutiva resume estado, pruebas y riesgos; la bitácora técnica cronológica conserva el porqué de las decisiones.
- Los cambios de bloque deben cerrarse con: documentación, pruebas, auditoría y registro en ambas bitácoras.
- Para detalles de arquitectura y contratos, se consultan las fuentes oficiales de Atlas en lugar de duplicar información extensa.

## Fuentes oficiales de referencia
- [docs/MOTOR_INTELIGENTE_ATLAS.md](docs/MOTOR_INTELIGENTE_ATLAS.md)
- [docs/CONTRATO_VIAJES_DESKTOP.md](docs/CONTRATO_VIAJES_DESKTOP.md)
- [docs/ATLAS_MASTER_CATALOGS.md](docs/ATLAS_MASTER_CATALOGS.md)
- [04_TRABAJOS_ACTIVOS_ATLAS.md](04_TRABAJOS_ACTIVOS_ATLAS.md)
