# Bitácora Ejecutiva — Proyecto Atlas

Registro de alto nivel de los bloques de trabajo cerrados sobre el lector de guías. Un párrafo por bloque, orientado a decisión y estado, no a implementación.

---

## 2026-08-26 — 472339/CASA HELSINSKI: RECONCILIACIÓN DE OBRA + B1 + PROMOCIÓN AUTOMÁTICA

- **Evidencia real reconstruida:** B1 NUNCA confirmó "Casa Helsinski" -- su único intento sobre `obra_destino` abortó por falta de la herramienta DOCUMENTOS_RELACIONADOS (`REQUIERE_HERRAMIENTA`, sin evidencia usada); la única mención real de RELSINSKI/HELSINSKI en la evidencia persistida es una nota de B1 sobre el dominio DESTINO, rechazada por el validador. Investigación externa real (fuera del proceso Python, guardada como fixture -- mismo patrón ya documentado para el caso SIGRO) confirmó que "Casa Helsinski" es un proyecto real de Inmobiliaria IKNOW en Helsinski 5810, La Reina (inmobiliariaiknow.cl).
- **Causa de la revisión huérfana:** no era un bug de clasificación (`_decisiones_obra_para_cliente`, llamada hoy con los datos reales de 472339, sí genera la decisión correctamente) -- la decisión de obra simplemente nunca quedó persistida en la bandeja, y no existía ningún mecanismo que la regenerara. Nueva red de seguridad GENERAL, `regenerar_decisiones_obra_faltantes_sin_ocr`: cualquier fila con `OBRA_DESTINO_SIN_CORROBORAR` vigente pero sin decisión pendiente ni resolución terminal en el ledger recupera su tarjeta, sin OCR.
- **Regla general de auto-resolución (nunca hardcode RELSINSKI→HELSINSKI):** `evaluar_evidencia_obra` gana un nuevo criterio -- evidencia externa OFICIAL/CORPORATIVO, sin contradicciones, cuya dirección corrobora EXACTAMENTE la dirección documental ya resuelta del mismo documento (dos fuentes independientes convergiendo), sin ambigüedad -- alcanza `RESUELTO_AUTOMATICAMENTE`. `aplicar_decision_obra` usa el nombre CANÓNICO de esa evidencia (nunca el texto OCR), conserva el texto documental como alias (`catalogo_obras_destinos.registrar_observacion`, extendido para aceptar alias también al crear una obra nueva), crea/confirma el destino con la dirección canónica en la misma aplicación, y registra una Incidencia Documental (`OBRA_DOCUMENTAL_INCONSISTENTE`) -- RELSINSKI nunca queda como entidad canónica aparte.
- **472339 antes→después:** obra "INMOB CASA RELSINSKI SPA" (sin tarjeta) → obra canónica "CASA HELSINSKI" (alias "INMOB CASA RELSINSKI SPA"), CONFIRMADA; destino "HELSINSKI 5810 LA REINA SANTIAGO" (La Reina) CONFIRMADO; motivo `OBRA_DESTINO_SIN_CORROBORAR` limpiado; decisión aplicada automáticamente (`actor=""`, evidencia externa). Aplicado a producción -- backup + SHA-256 en `respaldos/CASA_HELSINSKI_472339_ROLLBACK_PRE_APLICACION_20260826_181237`.
- **Tests:** 13 focales nuevos (`tests/test_obra_evidencia_externa_direccion_corroborada.py`, incluye regresiones A-D de seguridad + no-hardcode + E2E con bandeja vacía real) + suite completa Motor **1985 passed**. Sin cambios de código Desktop.
- **Pendiente real:** ninguno de código -- el mecanismo es general y queda disponible para cualquier caso futuro con la misma conjunción de evidencia.

---

## 2026-08-26 — PULIDO OPERACIONAL DESKTOP + CANONICALIZACIÓN BKYX63 → BKYK63

- **Choferes:** la ficha ya no muestra observaciones técnicas largas (fusiones, aliases OCR, reconciliación) en la vista principal -- quedan en "Ver detalles técnicos" (mismo patrón que Incidencias V2). Nueva fila "Última actividad", conceptualmente separada del Estado de catálogo (Activo/Inactivo, nunca se modifica): ≤30 días desde la última guía real → "hace N días" (badge verde); >30 días → "Sin actividad reciente · N días" (badge ámbar); sin histórico → "Sin actividad registrada" (nunca inventa una fecha). 100% Desktop -- el dato ya existía en la ficha (`historico.ultima_aparicion`).
- **BKYX63 → BKYK63 (mismo mecanismo que BPHF67 → BPHR67):** trazado en el histórico real -- BKYX63 aparece UNA sola vez en todo el histórico (guía legacy 462429), mientras BKYK63 tiene 13 apariciones consistentes del mismo chofer/RUT (LEANDRO TOLEDO, 18.611.137-0), incluyendo una el mismo día. Nueva confusión OCR documentada K/X (`catalogo_vehiculos._CONFUSIONES_OCR`) + nueva función general `_vehiculos_plegables_por_confusion_ocr`: un vehículo CONFIRMADO/ACTIVO del catálogo SIN evidencia en el histórico vigente, que es la única confusión OCR posible de otra canónica que SÍ tiene evidencia real, se excluye del listado de Vehículos (nunca se muta el catálogo, nunca se elige ante ambigüedad -- ver tests). BKYX63 ya no aparece en Catálogos → Vehículos; BKYK63 permanece con sus 2 guías reales.
- **Viajes:** contador "X de Y viajes" (se quitó el prefijo "Mostrando"), más pequeño y secundario. Período por defecto cambiado de "Hoy" a "Últimos 15 días" (resto de opciones intactas, ningún dato se borra).
- **Incidencias -- agrupación por viaje:** varias guías del MISMO transporte con exactamente el mismo error (tipo + campo + entidad + valor documental + valor canónico) se muestran como UNA tarjeta con "N guías afectadas" plegable; el detalle técnico conserva cada incidencia individual íntegra. Sin transporte confiable, nunca se agrupa. Caso real: transporte 0000354443 (guías 472238/472239, RUT de WLADIMIR AGUILAR) pasa de 2 tarjetas a 1. Tipografía de la vista principal ahora es la misma tipográfica normal de Desktop (monospace sólo dentro de "Ver detalles técnicos"); fecha principal sin hora ("25 ago 2026").
- **Tests:** Motor 4 focales nuevos (`tests/test_catalogo_fichas_v2.py`) + suite completa **1972 passed**. Desktop 30 focales nuevos (`test/microajustes_desktop_v2.test.js` + ajustes en tests existentes) + suite completa **397 passed**.
- **E2E real (G:\Mi unidad\Atlas):** PATRICIO VILLAGRA MUÑOZ (sin observación técnica visible, "Última actividad: hace 6 días"), BKYX63 (ya no listado)/BKYK63 (2 guías), Wladimir/transporte 0000354443 (1 tarjeta, "2 guías afectadas", ambas incidencias íntegras en detalles). Ningún chofer real tiene hoy >30 días sin viajes -- lógica cubierta por tests unitarios.
- **Pendiente real:** ninguno de código.

---

## 2026-08-26 — MICROAJUSTES DESKTOP: CATÁLOGOS + REVISIÓN DE ATLAS + INCIDENCIAS

- **Problema real:** CRISTOPHER RETAMAL mostraba BPHF67 como si fuera un segundo vehículo real (era BPHR67 mal leído por OCR); la ficha de chofer saturaba la vista principal con aliases OCR y una fila "Estado del RUT" aparte; la tabla de Destinos mostraba una columna Fuente de poco valor para un jefe/mandante; "Guías móviles sin asociación" y la revisión normal se apilaban en una página vertical muy larga.
- **Fix Motor (mínimo, sólo lectura):** nueva función pública `catalogo_vehiculos.es_confusion_ocr_de_patente` (reutiliza la tabla de confusiones OCR ya existente) usada por `catalogo_fichas._patente_canonica_o_plegada` -- una patente documental que sólo difiere de una canónica CONFIRMADA/ACTIVA en una confusión OCR conocida y compatible con el rol (TRACTO/CARRO) se resuelve a la canónica en la ficha (chofer y vehículo), sin tocar el dato documental ni el catálogo; nunca se pliega ante ambigüedad. Caso real: BPHF67 (guía 472339) se pliega en BPHR67 -- 3 apariciones, nunca aparece como vehículo aparte.
- **Fix Desktop:** ficha de chofer/vehículo con Identidad reducida a lo esencial (Nombre/RUT/Estado, Patente/Tipo/Estado) -- aliases OCR y "Estado del RUT" como fila aparte ya no se muestran (el RUT observado/histórico sigue visible, ahora inline con su valor); badge verde ("ok", mismo lenguaje visual que el resto de Desktop) para estados confirmados, ámbar para pendientes/observados; tabla de Destinos sin columna Fuente, Dirección ~65% de ancho (nunca cortada en 5-6 líneas); Revisión de Atlas en layout de dos columnas (grid `auto-fit`, Mobile a la izquierda, revisión normal a la derecha, colapsa a una columna si no hay Mobile pendiente, se apila en pantallas angostas) -- el flujo secuencial "Caso X de N / Anterior / Siguiente" ya existía en `decisiones_pendientes_ui.js` y no se tocó.
- **Tests:** Motor 3 focales nuevos (`tests/test_catalogo_fichas_v2.py`) + suite completa **1968 passed**. Desktop 12 focales nuevos (`test/microajustes_desktop_v1.test.js`) + suite completa **382 passed**.
- **E2E real (G:\Mi unidad\Atlas):** Cristopher Retamal (sólo BPHR67, 3 guías), Wladimir Aguilar (RUT observado/histórico inline, sin aliases), AUSIN SAN BERNARDO (Destinos sin Fuente, badges), BPHR67/JF9575 (ficha vehículo mínima), incidencias Wladimir (fecha "25 ago 2026 · 13:58", sin N.º transporte visible).
- **Pendiente real:** ninguno de código -- bloque puramente de presentación, sin cambios de lógica de detección ni de decisiones.

---

## 2026-08-26 — INCIDENCIAS DOCUMENTALES V2: VISTA HUMANA DE CONTROL DE CALIDAD DOCUMENTAL

- **Problema real:** la pestaña era una tabla técnica (ISO largo, enums crudos, sin jerarquía) -- no quedaba claro en segundos qué dato venía mal en una guía, qué usó Atlas en su lugar, ni por qué. Poco usable como herramienta de control de calidad para operación/mandante.
- **Fix (100% Desktop, sólo lectura -- Motor no cambió, el JSON ya se leía completo):** `src/incidencias_documentales_ui.js` reescrito -- cada incidencia se traduce a un título operacional humano (patrón general por `tipo_incidencia`, nunca hardcodeado a un caso), con "Dato emitido" vs "Dato usado por Atlas" como contraste visual (ámbar/verde), "Origen del problema" (Emisión de la guía / Error documental / Pendiente de determinar -- nunca afirma "emisión" fuera de lo que Motor ya confirmó como error de contenido), "Corroborado por" en lenguaje humano (nunca nombres de función), fecha compacta ("25 ago 2026 · 13:58") y categoría operacional (Datos del chofer/Cliente/Obra-destino/Vehículo-patente/Dirección/Horario-fecha/Peso-material/Otros). Detalles técnicos (ID, tipo interno, ISO completo, evidencia cruda) quedan plegados en "Ver detalles técnicos", nunca en la vista principal. Filtros nuevos: categoría y período (Hoy/7 días/30 días), sumados a campo/estado/búsqueda libre ya existentes. Resumen superior compacto (mostradas, errores de emisión, pendientes, categoría más frecuente). Segunda capa de seguridad: cualquier `PROBLEMA_DE_LECTURA`/`CALIDAD_DOCUMENTAL_O_IMAGEN` que llegara al almacén se excluye igual en la UI (nunca sólo confiando en que Motor no lo escriba).
- **Caso real Wladimir Aguilar (E2E contra producción):** guías 472238/472239 -- "Error en la emisión de la guía · RUT del chofer incorrecto", Chofer: WLADIMIR AGUILAR, Cliente: TORRES OCARANZA LTDA, Dato emitido 55.555.555-5 → Dato usado por Atlas 26.646.499-1, Corroborado por "Catálogo confirmado o histórico consistente", Detectado 25 ago 2026 · 13:58. Se entiende en segundos sin conocer Atlas por dentro; el enum `RUT_DOCUMENTAL_INVALIDO` y el ISO completo sólo aparecen en "Ver detalles técnicos".
- **Tests:** Desktop 25 focales nuevos (`test/incidencias_documentales_ui.test.js`, reescrito) + suite completa **370 passed**. Sin cambios de código Motor -- suite Motor no requiere re-ejecución.
- **Pendiente real:** ninguno de código para este bloque -- edición/cierre manual de incidencias queda explícitamente diferida, tal como pidió el ticket (bloque sigue siendo 100% de sólo lectura).

---

## 2026-08-26 — CATÁLOGOS V2: FICHAS COMPLETAS DE ENTIDADES (CHOFERES, CLIENTES, OBRAS, VEHÍCULOS)

- **Problema real:** la pestaña Catálogos sólo mostraba nombres en 3 listas planas -- buscando WLADIMIR AGUILAR, Javier no podía ver su RUT ni nada operacional que Atlas ya sabía (vehículos asociados, histórico de viajes, etc.).
- **Fix:** nuevo módulo Motor read-only (`atlas_core/catalogo_fichas.py` + CLI `construir_fichas_catalogos.py`, mismo patrón IPC ya usado por `consultar_atlas.py`) que arma, en una sola pasada del dataset y de los catálogos ya existentes (sin releer Drive por click, sin B1), una ficha completa por entidad: IDENTIDAD, VEHÍCULOS/RELACIONES asociadas, HISTÓRICO operacional y TRAZABILIDAD. Desktop reemplaza las 3 listas planas por: buscador único (nombre/RUT/patente) → lista de resultados → ficha detallada por secciones, con estados técnicos traducidos a lenguaje humano (Confirmado/Observado/Pendiente) y "Conflicto de datos" explícito cuando hay 2 valores incompatibles -- nunca se elige uno silenciosamente. Bloque 100% de sólo lectura (Motor Core y catálogos no se tocan; nada se edita, fusiona ni borra desde acá).
- **Caso real Wladimir Aguilar:** ficha muestra RUT `26.646.499-1` como "Observado / histórico" (nunca como "Confirmado" -- el catálogo formal aún lo tiene como `PENDIENTE`), con sus 4 guías de respaldo y el vehículo `AL1879` asociado. Validado además con Cristopher Retamal/BPHR67 (vehículo con tipo, choferes y apariciones), SALOMON SACK SA (RUT + histórico) y AUSIN SAN BERNARDO (dirección/comuna aprendidas, reutilizando `listar_destinos_confirmados_para_obra`).
- **Tests:** Motor 11 focales nuevos (`tests/test_catalogo_fichas_v2.py`) + suite completa **1965 passed**. Desktop 16 focales nuevos (`test/catalogos_fichas_ui.test.js`) + suite completa **355 passed**.
- **Pendiente real:** ninguno de código para este bloque -- edición de fichas (RUT/patente/fusión de entidades) queda explícitamente diferida a un bloque posterior, tal como pidió el ticket.

---

## 2026-08-26 — MOBILE V1: SELECTOR DE PLANTA DE ORIGEN (COLINA/RENCA) EN ATLAS CONDUCTORES

- **Selector:** interruptor grande de dos posiciones (radios nativos ocultos + etiquetas estilizadas, nunca `<select>`) en la pantalla de captura, antes de "Fotografiar guía". Sin selección previa, ningún lado viene marcado -- el chofer debe elegir antes del primer envío.
- **Persistencia local:** nueva tienda IndexedDB `preferencias` (separada de `sesion`, sobrevive a cerrar sesión) -- la última planta elegida se recuerda entre capturas, reintentos y cierres/reaperturas de la app.
- **Dato enviado:** `planta_origen_informada` (`AZA_COLINA`/`AZA_RENCA`, ID canónico -- nunca texto libre) viaja en el mismo `POST /api/mobile/envios` de siempre, validado en `sync-core.js` igual que `tipo_novedad`.
- **Core/trazabilidad:** `atlas_core.mobile.RepositorioEnviosMobile.recibir` exige y persiste el dato (mismo criterio que `tipo_novedad`, defensa en profundidad -- nunca confía sólo en el cliente); queda junto a `chofer_id`/timestamp en el mismo `envio.json`. Nunca contamina `datos`/`planta_origen_id`/`planta_origen_nombre` del dataset -- esos siguen siendo exclusivamente del pipeline determinista GPS/documento (verificado con test dedicado). Evidencia informada, nunca verdad absoluta -- cruzarla con GPS/histórico queda para un bloque posterior. 0 llamadas B1 nuevas.
- **Tests:** Mobile 20 focales nuevos (`test/planta-origen-v1.test.js`) + suite completa **78 passed**. Motor 7 focales nuevos (`tests/test_mobile_planta_origen_v1.py`) + suite completa **1954 passed**.
- **Pendiente real para la prueba de mañana:** ningún cambio de código -- Javier prueba con choferes reales (login real, selector, envío real); GPS automático/roles/multiempresa siguen fuera de alcance, explícitamente diferidos por este bloque.

---

## 2026-08-26 — PERFORMANCE V1: PARALELIZACIÓN SEGURA DE B1 Y TELEMETRÍA (472339 ~4 min → segundos)

- **Baseline instrumentado real** (guía 472339, PaddleOCR/GPU + ORS + Groq + Onelogis reales, copia aislada, nunca `G:\Mi unidad\Atlas`): con los fixes de patente/destino ya aplicados, el caso ya no dispara 4 problemas B1 sino 2 (`OBRA_DESTINO_SIN_CORROBORAR`, `SIN_ACCESO_VIAL`) — baseline limpio 24.1 s totales (`ocr_seg` 7.3, `telemetria_seg` 6.5, `atlas_ia` 6.5 llamado secuencial). El ~4 min original se explica, con evidencia real, por: 2 llamadas B1 de patente ya eliminadas (una de ellas sola, 20.5 s, por reintento de límite de cuota de Groq) + ejecución secuencial de las llamadas B1/telemetría restantes.
- **Causa de los 2 cuellos reales confirmados por profiling:** (1) `_ejecutar_ia_operacional` llamaba cada problema B1 de un documento uno tras otro aunque son independientes entre sí; (2) `recolectar_puntos_ventana_origen`/`obtener_breadcrumbs_recorrido` pedían los breadcrumbs de cada trip GPS candidato (hasta 6 en el caso real) uno tras otro a Onelogis, también independientes.
- **Fix (mismo patrón en ambos, nunca cambia resultado/orden):** se arma la lista de tareas primero (sin red), se disparan EN PARALELO sólo las llamadas de red reales (`ThreadPoolExecutor`), y los resultados se aplican en el mismo orden secuencial de siempre, en el hilo principal -- mutación de `fila`/caché nunca concurrente (`RepositorioTelemetria` no soporta escritura concurrente; se detectó y evitó ese riesgo antes de paralelizar). Un solo problema/trip nunca paga el costo de un executor.
- **Medido:** B1 -- tiempo de pared pasó de ser igual a la suma de latencias (ejecución secuencial demostrada) a ser menor que la suma (paralelo demostrado matemáticamente); test controlado con reloj real confirma paralelo ~0.5s vs secuencial ~1.0s para 2 llamadas. Telemetría -- test controlado confirma paralelo ~0.3s vs secuencial ~0.9s para 3 trips. E2E real (462339 aislado): 24.1s → 9.0s (mismos resultados operacionales exactos: chofer, cliente, obra, patente BPHR67, destino, motivos, indicador_revision).
- **Nunca se tocó:** OCR (PaddleOCR, fuera de alcance), validadores, B1 (mismo razonamiento, mismas restricciones), caché existente (se reutiliza, nunca se recrea), orden semántico de aplicación de resultados.
- **Tests:** 7 focales nuevos (`tests/test_performance_v1_b1_paralelo.py`, `tests/test_performance_v1_telemetria_paralela.py`) + suite completa Motor **1947 passed**.

---

## 2026-08-26 — FIX DE AUTONOMÍA DE DESTINO: HELSINSKI 5810 YA NO QUEDA EN SIN_ACCESO_VIAL SIN AGOTAR EL PIPELINE

- **Causa real:** el proveedor principal (ORS) sólo resolvió dos centroides genéricos de la misma comuna ("La Reina, RM, Chile", >1 km entre sí) -- correctamente tratados como "el mismo lugar real" (regla ya calibrada, caso Coronel/Biobío) y aceptados como resuelto, pero el punto elegido no tenía acceso vial. El reintento con el respaldo estructurado (Nominatim) SÍ ubicó la calle real ("Helsinski"), pero como su etiqueta nunca trae el número de casa exacto (hueco real de cobertura del geocodificador en calles chilenas menos densamente mapeadas), `_candidato_unico_con_numero_de_calle` lo descartaba igual que si no hubiera encontrado nada -- sólo aceptaba un calce EXACTO de número.
- **Dirección/candidato:** se agregó un segundo nivel de aceptación -- único candidato TOTAL del respaldo (sin rivales), cuya etiqueta identifica algo más específico que la sola comuna (nunca un centroide genérico) -- sigue exigiendo exactamente la misma corroboración territorial ya vigente (la comuna debe aparecer en el propio texto documental, en un destino confirmado, o en evidencia B1 ya persistida). Candidato: "Helsinski", comuna "La Reina" (coincide con el texto documental) -- coordenada -70.5705666,-33.4565182, confirmada ruteable por ORS.
- **472339 antes→después:** `estado_ruta` SIN_ACCESO_VIAL → RUTA_CALCULADA (20.7 km, 28.9 min, proveedor openrouteservice); `despachar_a_crudo`/`direccion_entrega` nunca se reescriben (evidencia documental intacta); `estado_operacional` sigue REQUIERE_REVISION por el motivo no relacionado `OBRA_DESTINO_SIN_CORROBORAR` (fuera de este bloque).
- **B1/aprendizaje:** 0 llamadas B1 nuevas -- Motor resolvió determinísticamente reutilizando el mecanismo ya existente (Vía C + reintento SIN_ACCESO_VIAL). La asociación queda persistida en la caché de geocodificación real (documento→coordenada), no como regla global de sustitución de nombres de calle.
- **Tests/commit:** 7 tests focales nuevos (`tests/test_destino_autonomia_e1.py`, casos A-E) + suite completa Motor **1940 passed**. Aplicado a producción -- sólo la fila 472339, con backup + SHA-256 en `backups/destino_autonomia_*`.

---

## 2026-08-26 — FIX DE AUTONOMÍA: PATENTE OCR CON ERROR MENOR NO ESCALA A JAVIER

- **Causa real:** el Motor de Evidencia de Vehículos ya combinaba histórico del chofer + similitud OCR calibrada en candidatos, pero `RESUELTO_AUTOMATICAMENTE` (la única clasificación que se aplica sola, sin tarjeta) sólo era alcanzable con `CONFIRMACION_HUMANA` previa asociada a ese RUT exacto -- un único candidato con corroboración documental independiente (dos transportes distintos del mismo chofer) siempre quedaba en `SUGERENCIA_HUMANA`, sin importar cuán inequívoco fuera.
- **Regla general:** `NIVEL_DOCUMENTAL_INDEPENDIENTE` ahora también resuelve solo -- pero SÓLO cuando es el único candidato Y trae `SIMILITUD_OCR_CALIBRADA` (el valor documental de ESTE documento es una lectura OCR plausible de la canónica, no sólo "un vehículo que el chofer usó alguna vez" -- evita forzar histórico viejo si el chofer cambió de vehículo). `reconciliar_bandeja_decisiones` (Fase 4) extendido para aplicar también `VEHICULO_DESCONOCIDO` vía `USAR_PATENTE_EXISTENTE`, mismo mecanismo ya usado por `ALIAS_CANDIDATO`, `actor="ATLAS_AUTOMATICO"`.
- **472339 (Cristopher Retamal) antes→después:** OCR "BPHF67" generaba una tarjeta `VEHICULO_DESCONOCIDO` pendiente para Javier. F/R se agregó como confusión OCR calibrada (evidencia real de este caso, mismo criterio que E/F de 472247) → único candidato "BPHR67" (2 transportes independientes previos, confirmada/activa) → se resolvió y aplicó solo; la decisión desapareció de la bandeja; `PATENTE_SIN_HOMOLOGAR` se limpió del CSV vía la revalidación ya existente que corre dentro de la propia aplicación. `patente_tracto` documental nunca se reescribió (sigue "BPHF67", evidencia preservada en el ledger). Catálogo de vehículos sin cambios (sin alias nuevo, sin vehículo nuevo).
- **B1/aprendizaje:** 0 llamadas B1 -- determinístico. Nada se aprendió como regla global ("F siempre es R"); sólo se calibró una confusión de trazo general y se vinculó documento→canónica en el ledger, igual que cualquier confirmación humana. Desktop no se modificó (la bandeja ya refleja decisiones aplicadas vía el mecanismo existente).
- **Tests:** 6 focales nuevos (`tests/test_vehiculo_autonomia_e2.py`, casos A-E + end-to-end) + suite completa Motor **1933 passed**. Aplicado a producción con backup + SHA-256 en `backups/vehiculo_autonomia_*`; idempotente verificado.

---

## 2026-08-25 — FIX RUT DOCUMENTAL INVÁLIDO → VALOR CANÓNICO + INCIDENCIA DOCUMENTAL

- **Causa real:** `validar_rut_chileno` sólo comprobaba el dígito verificador (módulo 11), que no distingue un RUT real de un cuerpo de dígitos repetidos (p. ej. "55.555.555-5" calza matemáticamente). Un documento de WLADIMIR AGUILAR traía ese valor impreso; al procesarse junto a su guía hermana, el mecanismo existente de corroboración por documentos relacionados confirmó ese RUT inválido contra sí mismo (dos lecturas iguales, ninguna validada), dejándolo silenciosamente como dato operacional sin motivo ni incidencia.
- **Regla general (sin hardcodear el caso):** se agregó un chequeo de plausibilidad de cuerpo (dígito repetido) al validador compartido, usado ya por todo el extractor; `buscar_rut_chofer`/`buscar_rut_cliente` ahora exigen validación antes de aceptar cualquier RUT como operacional, conservando el valor documental como evidencia. Se distingue duda de OCR (dígito verificador no calza) de error documental confirmado (dígito verificador calza, cuerpo implausible) -- sólo el segundo dispara `RUT_CHOFER_INVALIDO`/`RUT_CLIENTE_INVALIDO`, no bloqueante, resuelto vía Incidencia Documental. Se cerró además el hueco en `_corroborar_documentos_relacionados`: ya no acepta como corroboración un RUT fuente que él mismo sea inválido.
- **Catch-up (sin OCR):** `detectar_incidencias_rut_chofer_invalido_sin_ocr`/`reconciliar_incidencias_rut_chofer_documental` (mismo patrón que transporte-ausente R5 I) revalidan el dataset ya persistido, buscan RUT canónico en catálogo o histórico consistente, corrigen el dato operacional sólo si hay canónico confiable y registran la Incidencia Documental (`TIPO_RUT_DOCUMENTAL_INVALIDO`) -- nunca inventan.
- **Aplicado a producción (472238/472239, WLADIMIR AGUILAR):** único caso real detectado. `rut_chofer` corregido de "55.555.555-5" a "26.646.499-1" (histórico consistente de otros dos viajes, catálogo aún sin RUT confirmado); 2 Incidencias Documentales registradas, visibles en la pestaña existente sin cambios de Desktop (vista genérica por columnas). Backup + SHA-256 antes/después en `backups/rut_documental_invalido_*`.
- **Tests:** 18 focales nuevos (`tests/test_rut_documental_invalido.py`, casos A-E de regresión) + suite completa Motor **1927 passed**. B1 no fue necesario -- el Motor resolvió determinísticamente. Desktop no se modificó.

---

## 2026-08-20 — MOBILE M1 — CONEXIÓN REAL MOBILE → MOTOR

- Se implementó `POST /api/mobile/login` y `POST /api/mobile/envios` conservando el contrato ya instalado en iPhone: Bearer token, foto, `envio_id`, timestamp, una de cinco incidencias operacionales y flag de guía firmada por correo. El chofer nunca elige guía, transporte ni viaje.
- Cada envío queda durable e idempotente en `operacion/mobile/envios/<envio_id>/`: foto original inmutable más `envio.json`. Estados: `RECIBIDO`, `PROCESANDO`, `ASOCIADO`, `REQUIERE_REVISION`, `ERROR`. Un retry devuelve `ACEPTADO` sin duplicar.
- La imagen pasa por `procesar_archivo`, el mismo OCR/extractor del Motor. Asociación automática sólo por coincidencia exacta de guía/transporte con la operación vigente; ante insuficiencia se abstiene y publica la excepción. Las cinco novedades son incidencias operacionales, nunca documentales.
- Desktop incorporó dentro de Revisión de Atlas una bandeja mínima para ver foto, chofer, hora, incidencia, OCR, candidatos y motivo, y confirmar un transporte existente mediante el CLI del Motor.
- Prueba real en TEMP con la foto 464265: recepción 0,023 s; OCR/asociación CPU 47,493 s; resultado `ASOCIADO`, guía 464265, transporte 0000351135; devolución parcial y flag correo preservados. Drive real sólo leído.

---

## 2026-08-20 — ATLAS IA B1 — ASISTENCIA OPERACIONAL MULTICAMPO

- **Atlas IA dejó de estar limitada a patentes:** el contrato compatible ahora transporta identidad documental/operacional, evidencia, resultado previo, herramientas y restricciones; el orquestador reusable cubre patente, chofer/RUT, cliente/RUT, obra/destino, fecha y cualquier campo que el Motor genérico represente limpiamente.
- **Separación preservada:** el Motor determinista sigue resolviendo lo inequívoco; sólo los problemas restantes llegan a Groq. La IA devuelve propuesta, abstención o solicitud de evidencia; nunca escribe CSV, catálogos, ledger ni decisiones. El valor documental original permanece intacto.
- **Tool/evidence calling mínimo real:** `DOCUMENTOS_RELACIONADOS` consulta otras guías del mismo transporte, aporta evidencia débil/no independiente y permite una segunda pasada. Límite absoluto de dos rondas, sin framework agente ni loops.
- **Seguridad multicampo:** valor fuera de evidencia, contradicción humana, contexto incorrecto o formato inválido de patente/RUT/fecha se bloquean. Caída, timeout, 429 o cuota Groq se convierten en `ERROR_PROVEEDOR` clase D; Atlas determinista continúa operativo.
- **Muestra real vigente, read-only, Groq `openai/gpt-oss-120b`:** 6 problemas (2 patente, 1 fecha, 1 cliente, 2 obra/destino). Resultado: **A=0, B=1, C=5, D=0**. La propuesta B fue `VP8521` para 464265; Ortiz y los conflictos documentales se abstuvieron correctamente. Fecha pidió documentos relacionados y agotó las dos rondas sin inventar una resolución. **0 intervenciones evitables todavía**, porque B1 no autoriza escrituras y no apareció evidencia fuerte nueva. **0 incidencias documentales propuestas por el modelo** en esta muestra.
- **Ruta mínima al primer ingreso — bloqueadores para cobrar (máximo 5):** (1) contrato operativo de entrada/salida y alcance por transportista; (2) configuración aislada mínima de catálogos/reglas del segundo cliente sin construir SaaS multiempresa; (3) lote piloto real con criterios de aceptación y ground truth revisado por Javier; (4) reporte profesional entregable de viajes/incidencias más checklist de control de calidad; (5) procedimiento operativo de excepciones, respaldo y trazabilidad de correcciones. **Mejoras posteriores:** autoservicio, Mobile, UI nueva, cloud y multiempresa completa.
- **Validación:** 11 pruebas focales B1 dentro de 22 pruebas IA focales; suite completa **1513 passed, 0 failed**. Drive operacional y Desktop no se modificaron. Artefacto real únicamente en `experimentos_atlas_ia/resultados/` (gitignored). Commit funcional `8e0f2cf`.

---

## 2026-08-20 — ATLAS IA GROQ FREE + GPT-OSS 120B — BENCHMARK 6/6

- **Groq Free completó el mismo benchmark real de seis casos con `openai/gpt-oss-120b`:** 464036 abstención correcta; 464265 propuesta `VP8521`; 464264 y 464698 propuestas `JD8659`; 463594 y 464424 abstenciones correctas. Total: 3 propuestas correctas, 3 abstenciones correctas, 0 incorrectas, 0 bloqueos del validador.
- **Igualó a Claude RUN #2 en decisiones.** Confianzas Groq: 0.00, 0.60, 0.90, 0.90, 0.00, 0.00. No hubo valores inventados ni afirmaciones fácticas graves; en 464036 citó `OCR_actual_XF3662` como etiqueta de evidencia usada aunque no es un identificador formal de `EvidenciaIA`, sin afectar la conclusión.
- **Velocidad remota:** Groq reportó ~0,92–2,31 s de servicio por caso (11,06 s acumulados). Extremo a extremo fueron 2,43–20,72 s por caso (78,16 s acumulados) debido a esperas TPM automáticas del Free Plan. Claude había demorado ~44 s para el lote, por lo que Groq fue más rápido en inferencia pura pero el throttling hizo el lote completo más lento.
- **Uso/costo observado:** 7.864 tokens de prompt + 5.028 de completion = 12.892 totales. La API no devolvió campo `cost`; la cuenta siguió en Free Plan, sin compra de créditos ni habilitación de facturación. No se afirma un saldo descontado porque Chat Completions no expuso ese dato.
- **Integración robusta:** JSON Schema strict, todos los campos requeridos, `additionalProperties:false`, errores saneados, reasoning no persistido y reintento acotado respetando 429. El primer 403 se resolvió agregando `User-Agent`; un 429 TPM se trató como limitación técnica, no como fallo cognitivo.
- **Recomendación B:** Groq/GPT-OSS 120B como IA primaria gratuita y Claude como fallback ante cuota, disponibilidad o casos futuros donde el modelo gratuito degrade. Atlas permanece completamente en SHADOW.
- **Tests:** 62 focales del conjunto proveedor/shadow; suite completa `1502 passed, 0 failed`. Ollama vacío, GPU local no usada, Drive/operación/Desktop intactos.

---

## 2026-08-20 — ATLAS IA REMOTA GRATUITA — OPENROUTER FREE-TIER

- **Se incorporaron dos proveedores intercambiables sin alterar contratos, validadores ni SHADOW:** Ollama local y OpenRouter remoto. El trabajo Ollama interrumpido quedó preservado en un commit propio; no se volvió a ejecutar Qwen3 y `ollama ps` permaneció vacío durante las llamadas remotas.
- **Catálogo OpenRouter consultado en tiempo real:** se eligieron como máximo dos slugs explícitos `:free`, con entrada/salida a precio cero y structured outputs declarado. `z-ai/glm-5.2:free` fue el mejor listado por inteligencia; `nvidia/nemotron-3-super-120b-a12b:free`, el segundo.
- **Resultado honesto:** GLM 5.2 devolvió dos `HTTP 429` consecutivos del pool compartido antes de inferir. Nemotron respondió en aproximadamente 11 segundos, pero entregó JSON inválido pese al schema estricto; Atlas lo bloqueó antes de crear una hipótesis. Ninguno completó el primer caso 464036, por lo que no existe una tabla cognitiva de seis casos que comparar con Claude.
- **Costo:** el catálogo indicó USD 0 para input/output de ambos slugs. Los 429 no produjeron uso. La respuesta malformada no quedó convertida en artefacto de uso, por lo que su `usage.cost` no puede afirmarse desde el resultado preservado; futuras respuestas se detienen automáticamente si reportan costo distinto de cero.
- **Conclusión:** estos endpoints free-tier no son hoy una IA primaria confiable para Atlas. Recomendación **C: probar otro free-tier/API antes de decidir**; Claude conserva el único benchmark completo y correcto (3 propuestas + 3 abstenciones).
- **Seguridad y regresión:** schema estricto, precio máximo cero, slug `:free` obligatorio, credencial saneada, thinking no persistido y 47 tests focales. Suite completa: `1492 passed, 0 failed`. Cero cambios en Drive, operación o Desktop; cero carga de GPU local para OpenRouter.

---

## 2026-08-20 — PRIMER RAZONAMIENTO REAL DE ATLAS IA — COMPLETADO

- **Claude real razonó sobre seis casos reales en SHADOW, sin cambios operacionales.** Modelo `claude-sonnet-5`, política `atlas-ia-politica-v1`; no se modificaron CSV, ledger, catálogos, estado operacional ni Desktop.
- **RUN REAL #1 (14:55 local):** 464036 abstención correcta; 464265 degradado a abstención porque Claude copió el estado interno no válido `SUGERENCIA_HUMANA`; 464264 y 464698 propuestas correctas `JD8659`; 463594 y 464424 abstenciones correctas. Total: 2 propuestas correctas, 3 abstenciones correctas, 1 salida fuera de contrato, 0 valores inventados aceptados.
- **Iteración mínima:** se eliminó `temperature` (deprecado por el modelo), se saneó el detalle JSON de errores HTTP y se conectaron referencias auditables de documentos/eventos relacionados que el Motor ya poseía. Para 464265 llegaron ahora la guía 464264 del mismo transporte y las guías 464698/699/700 de otro transporte; esta capacidad es genérica para evidencias de cualquier campo.
- **RUN REAL #2 (15:03 local):** 464265 mejoró a propuesta correcta `VP8521`; los otros cinco casos conservaron el resultado esperado. Total: 3 propuestas correctas y 3 abstenciones correctas; 0 propuestas incorrectas, 0 valores inventados y 0 regresiones de resultado.
- **Limitación observada:** en la explicación de 464265 Claude llamó erróneamente “3 transportes independientes” a tres guías que pertenecen a un solo transporte. El contexto estructurado indicaba correctamente `independencia=1`; el valor propuesto siguió siendo real y correcto. Validar afirmaciones narrativas contra metadatos estructurados es el siguiente salto recomendado, no ejecutado aquí.
- **Regresión:** 57 tests focales y suite completa `1472 passed, 0 failed`. Los artefactos crudos RUN #1/#2 se preservaron localmente bajo `experimentos_atlas_ia/resultados/`, manteniendo su política gitignored deliberada.

---

## 2026-08-20 — ATLAS IA A2: proveedor real conectado -- BLOQUEADO por falta de credencial, todo lo demás listo

- **Se conectó un proveedor de IA real (Anthropic/Claude) al mismo enchufe genérico construido en A1** -- ningún cambio a los contratos ni a las barreras de seguridad ya construidas. Se preparó un lote de 6 casos reales (incluido Ortiz) con evidencia real de Atlas, listo para ejecutarse.
- **La ejecución real quedó bloqueada en un único punto, exactamente donde debía:** no existe hoy ninguna credencial de un proveedor de IA configurada en este computador. Se verificó explícitamente (variables de entorno, archivos de configuración) antes de construir nada -- no se inventó, no se pidió por otro canal, no se intentó rodear.
- **Acción concreta pendiente de Javier:** configurar `ANTHROPIC_API_KEY` como variable de entorno de **usuario** de Windows, en su propia terminal -- mismo mecanismo ya usado para las claves de rutas/telemetría. Instrucciones exactas en `experimentos_atlas_ia/README.md`. En cuanto exista, el experimento ya está listo para correr con un solo comando -- no hace falta escribir código nuevo.
- **Todo lo demás quedó construido y probado:** el prompt de sistema de Atlas IA (pequeño, versionado, sin lógica de negocio), el proveedor real completo (probado con conexiones simuladas, nunca red real en los tests), y el lote de 6 casos reales -- 2 donde se espera una corrección, 2 que el propio Motor determinista ya resuelve solo, 2 donde se espera abstención.
- **Cero efectos sobre la operación real**, verificado explícitamente por fecha de modificación de los archivos reales de Drive -- ninguno cambió.
- **Motor `1451 → 1471 passed, 0 failed`** (20 tests nuevos). Commit local únicamente, sin publicar todavía.

---

## 2026-08-20 — ATLAS IA A1: infraestructura shadow aislada, sin modelo real (vertical vehículos)

- **Primer bloque de Atlas IA, deliberadamente pequeño y sin riesgo operacional.** Se construyó una capa nueva (`atlas_core/atlas_ia/`) con los contratos y el "arnés" necesarios para que, el día que se conecte un modelo de razonamiento real, Atlas pueda recibir sus propuestas, validarlas contra evidencia real y auditarlas -- sin que ese modelo pueda, hoy ni en el futuro, inventar un dato operacional.
- **Todavía NO hay ningún modelo de IA conectado.** Este bloque usa exclusivamente un "doble" simulado y determinista para probar que el mecanismo funciona -- no mide, y no debe interpretarse como, capacidad de razonamiento de ninguna IA real. El benchmark cognitivo empieza cuando exista un proveedor real, no antes.
- **La barrera central ya está construida y probada:** una propuesta que no aparezca en la evidencia ya reunida por el Motor determinista se rechaza automáticamente, sin excepción -- Atlas IA no puede convertir una ocurrencia del modelo en un hecho operacional. También se rechaza cualquier propuesta que contradiga una decisión humana ya confirmada.
- **El Motor determinista existente no se tocó.** El caso de Patrick Ortiz (464036) se usó como ejemplo para demostrar que, si un futuro modelo llegara a sugerir la misma patente que Atlas ya venía razonando por su cuenta, la nueva arquitectura sabría recibirla correctamente -- eso no significa que Atlas ya "resolvió" ese caso; sigue exactamente igual que antes, sin ninguna decisión aplicada.
- **Cero efectos sobre la operación real:** nada de este bloque toca Drive, catálogos, el historial de decisiones ni el reporte vigente -- confirmado explícitamente con pruebas automáticas.
- **Motor `1414 → 1451 passed, 0 failed`** (37 tests nuevos). Commit local únicamente, sin publicar todavía.

---

## 2026-08-20 — G1 APLICADO A OPERACIÓN REAL: el reporte vigente ya publica las patentes que Javier confirmó

- **El fix G1 de hoy ya está reflejado en la operación real, no sólo en el código.** Se regeneró el reporte vigente sobre `G:\Mi unidad\Atlas` con el Motor corregido -- el transporte `0000351135` (Carlos Simón) ya publica `VP8521` (tracto) y `JD8659` (rampla) como valores operacionales, en vez de las dos variantes documentales sin resolver.
- **Cambio quirúrgico, verificado uno por uno:** de los 38 viajes, exactamente **uno** cambió, y sólo en los tres campos que G1 debía tocar (motivos de revisión y las dos patentes). Los otros 37 viajes -- cliente, chofer, RUT, obra, material, peso, evidencia -- quedaron byte a byte iguales. El dataset documental, el historial de decisiones y la bandeja de pendientes tampoco cambiaron.
- **El viaje sigue en revisión, como corresponde:** `0000351135` no se marcó `CONFIRMADO` -- todavía tiene un conflicto real de fecha y de obra/destino entre sus dos guías, sin relación con G1, esperando el criterio de Javier.
- **Nada se perdió:** las patentes documentales originales (`VP6521`, `JD0659`, `JD6659`) siguen disponibles íntegras como evidencia de cada guía.
- **Hallazgo del propio proceso, sin impacto en el resultado:** el mecanismo que se usa normalmente tras aplicar una decisión (`revalidar_y_regenerar_reporte`) no habría regenerado nada hoy -- sólo actúa cuando encuentra un motivo documental que limpiar, y ese ya se había limpiado ayer. Se usó en su lugar el generador de reportes ya publicado, que sí construye siempre el reporte más reciente. Documentado como hallazgo técnico, no como problema a resolver en este bloque.
- **Respaldo creado antes de escribir**, con los mismos archivos y hashes verificados antes/después.

---

## 2026-08-20 — FIX G1: las decisiones de patente ya confirmadas ahora se ven en el viaje publicado

- **Hallazgo de la auditoría READ-ONLY de esta mañana, corregido hoy:** cuando Javier confirmaba una patente incorrecta (tracto o rampla) desde Desktop, la decisión quedaba guardada de forma auditable pero **nunca llegaba al viaje que ve el operador** -- `viajes.csv` seguía publicando el texto documental crudo (p. ej. "JD0659 | JD6659") como si la decisión nunca hubiera ocurrido. Era un límite ya documentado explícitamente en el propio código desde el bloque anterior ("queda para un consumidor futuro del ledger") -- ese consumidor no existía todavía.
- **Caso real que lo expuso:** transporte `0000351135` (guías 464264/464265, Carlos Simón). Javier ya había seleccionado `JD8659` (rampla) y `VP8521` (tracto) el 19-08; el viaje seguía mostrando ambas variantes documentales sin resolver.
- **Corregido en el Motor, no en Desktop.** Desktop ya consumía `patentes_tracto`/`patentes_rampla` directamente del reporte, sin lógica propia -- no necesitó ningún cambio. El fix vive donde corresponde: en la consolidación de viajes, que ahora consulta el historial de decisiones ya aplicadas para publicar la patente canónica como valor operacional.
- **Nada de la evidencia original se pierde ni se reescribe.** El documento leído (`analisis_completo_guias.csv`) permanece byte a byte igual; la evidencia de cada guía sigue disponible íntegra en el propio viaje. Sólo cambia qué patente se publica como la vigente para operar.
- **Verificado contra los datos reales de Drive, sin tocar Drive:** se generó el reporte con una copia controlada de la operación real (fuera de `G:\Mi unidad\Atlas`, nunca escrito) -- el transporte `0000351135` pasa a publicar `VP8521`/`JD8659` únicos, sin los conflictos de patente ya resueltos, conservando correctamente en revisión los dos conflictos reales que siguen sin decidir (fecha, obra/destino). El conteo de 7 viajes en revisión no cambió -- exactamente lo esperado, ya que ese caso sigue teniendo motivos legítimos pendientes por otras razones.
- **Sigue pendiente, deliberadamente fuera de este bloque (G2):** el caso Ortiz (464036, patente rechazada como error documental del mandante) no tiene todavía un estado terminal que lo saque de "Requiere revisión" -- este fix no lo toca.
- **Motor `1414 passed, 0 failed`** (10 tests nuevos). Nada aplicado a Drive real; commit local únicamente, sin push.

---

## 2026-08-19 — CIERRE OPERACIONAL DEL DÍA: Javier vació la Revisión de Atlas; los 7 viajes que siguen en "Revisar" son todos reales

- **Javier resolvió manualmente todas las decisiones pendientes** desde Desktop -- la bandeja quedó en cero. Quedaron 7 viajes (de 38) que el sistema sigue marcando "Requiere revisión". Se auditó cada uno, con evidencia, para saber por qué.
- **Resultado honesto: los 7 son reales.** Ninguno es un simple "olvido" del sistema -- cada uno tiene al menos un motivo genuino que todavía necesita a Javier o a más información del documento original: conflictos entre documentos del mismo transporte (fechas, obras o patentes que no coinciden entre sí), clientes que la guía nunca llegó a identificar, o destinos con varias direcciones posibles sin poder elegir cuál es la correcta.
- **Sí se encontró y corrigió un detalle real, más chico:** dos guías de Carlos Simón (464264, 464265) seguían mostrando "patente sin homologar" aunque Javier YA había confirmado la patente correcta -- el sistema nunca se enteró de esa confirmación al calcular ese motivo en particular. Se corrigió de forma general (no sólo para esas dos guías) para que esto no vuelva a pasar. Ninguno de los 7 viajes cambió de estado por esto -- cada uno sigue en revisión por sus propias razones reales, sólo que ahora las razones que se muestran son las verdaderas.
- **Nada se inventó ni se forzó.** No se resolvió ningún conflicto real por Atlas -- todos quedan esperando el criterio de Javier.
- **Jornada cerrada de forma portable:** Motor y Desktop publicados, Drive verificado, respaldo completo con manifiesto antes de tocar cualquier dato real, bitácoras al día. Javier puede continuar mañana desde la oficina sin depender de nada de esta máquina.

---

## 2026-08-19 — PRIMER CICLO OPERACIONAL: Ortiz cerrado con motivo estructurado; bandeja real 13 → 12; ningún aprendizaje inventado

- **Se aplicó, sobre Drive real, únicamente el caso que ya estaba inequívocamente confirmado:** el tracto de la guía 464036 (Patrick Ortiz, XF3662) se cierra con `NO_REGISTRAR` y el motivo estructurado `ERROR_DOCUMENTAL_MANDANTE` -- exactamente lo que Javier ya había confirmado en una auditoría anterior de esta misma sesión. El documento original (`XF3662`) nunca se tocó.
- **Deliberadamente NO se aplicó nada más.** Ni la sugerencia de Carlos Simón (VP8521 sigue siendo sólo una sugerencia fuerte, no una confirmación), ni ninguna de las 6 obras "administrativas", ni el caso SIGRO -- ninguno tiene, en este momento, una confirmación de Javier lo bastante inequívoca como para aplicarla sin él. Se prefirió dejarlas pendientes en Desktop antes que inventar una confirmación que no existe.
- **Bandeja real: 13 → 12.** El aprendizaje (confirmaciones independientes) sigue en cero -- este bloque no generó ninguna, porque cerrar con `NO_REGISTRAR` no es lo mismo que confirmar un alias; ese mecanismo (`CONFIRMAR_ALIAS`) es justamente el que Javier puede empezar a usar ahora desde Desktop.
- **Hallazgo honesto, no una falla:** cerrar una decisión de vehículo por error documental todavía no genera una Incidencia Documental (ese enganche sólo existe hoy para clientes) -- quedó reportado como un límite conocido, no se construyó un parche apurado para cubrirlo en este bloque.
- **Backup completo y verificado byte a byte antes de escribir**, con manifiesto y rollback documentado.
- **Este es el punto de partida real para medir si Atlas empieza a preguntar menos:** 0 confirmaciones acumuladas, 0 auto-resoluciones, 12 decisiones esperando a Javier en Desktop.

---

## 2026-08-19 — MOTOR DE EVIDENCIA FASE 4: auto-resolución activada (código listo, sin activar sobre datos reales)

- **Decisión de producto de Javier, ya implementada:** cuando Atlas tiene evidencia suficiente para un cliente/obra (`RESUELTO_AUTOMATICAMENTE`), ya no pide un clic -- aplica la entidad canónica sola, deja registrada la evidencia completa (qué decía la guía, qué usó Atlas, por qué) y crea automáticamente una Incidencia Documental. Javier sólo interviene cuando persiste una duda real.
- **Nunca se pierde nada:** el documento original nunca se toca. El CSV, la lectura OCR, el RUT documental, todo queda exactamente igual -- lo único que cambia es que el catálogo aprende la relación real y la decisión deja de aparecer como pendiente.
- **Auditoría de consumidores reales:** escribir la entidad canónica directamente en el CSV consolidado tocaría varios sistemas (consolidación de viajes, reportes, Excel, Desktop) que hoy no están preparados para eso -- se decidió NO tocar el CSV en este bloque (mismo criterio ya usado para vehículos desde hace dos bloques) y en cambio dejar la resolución completamente auditable en el catálogo y el historial. Que el resto de Atlas empiece a "ver" el nombre canónico en vez del documental queda como una decisión de producto separada, explícita, para cuando Javier la pida.
- **Encontrado y corregido: un bug real que habría degradado la clasificación de vehículos si se hubiera dejado pasar** -- ya corregido en el bloque anterior, esta vez validado que sigue funcionando correctamente con la auto-resolución activa.
- **Probado de punta a punta, con acciones reales:** primera confirmación → segunda independiente → tercera aparición se resuelve sola, sin pedir nada. Corrido dos veces seguidas sin duplicar nada. Nunca aplica una simple "sugerencia" -- sólo lo que de verdad ya está resuelto.
- **Nueva pestaña en Desktop: Incidencias Documentales** -- primera versión funcional, con filtros básicos, mostrando exactamente lo que Motor ya registra.
- **Sobre los 13 casos reales pendientes de la operación:** hoy nada se resuelve solo todavía, porque el catálogo de confirmaciones humanas reales sigue vacío -- exactamente lo esperado, no un error. En cuanto Javier empiece a confirmar alias reales desde Desktop, el aprendizaje arranca solo.
- **Nada se aplicó a Drive real.** Motor `1402 passed`; Desktop `242 passed`.

---

## 2026-08-19 — MOTOR DE EVIDENCIA FASE 3: conectado al flujo real (sin aplicar a producción) — y un bug real de tipo de vehículo encontrado y corregido

- **El motor de clientes/obras del bloque anterior ya está conectado al flujo real** que usa Desktop (`reconciliar_bandeja_decisiones`), no a un flujo paralelo. Además, **por primera vez, `CLIENTE_DESCONOCIDO` y `ALIAS_CANDIDATO` tienen una aplicación real** -- hasta este bloque, aunque Desktop mostraba sus opciones, el botón "Aplicar" nunca hacía nada (sólo UX preparatoria). Ahora sí: registrar un cliente nuevo, o confirmar que un texto documental corresponde a una entidad ya conocida, funciona de punta a punta.
- **El aprendizaje operacional ya es real, no sólo diseño:** cada vez que un humano confirma un alias, Atlas lo recuerda (asociado al RUT, nunca al mismo documento repetido). A la segunda confirmación independiente, la relación queda como conocimiento fuerte; una tercera aparición equivalente se resuelve sola y queda registrada como Incidencia Documental -- probado de punta a punta, no sólo en teoría.
- **Hallazgo real importante, encontrado validando contra los datos reales (no en un test sintético):** una vez que la rampla de un documento se resolvía, su tracto hermano perdía la clasificación de tipo y podía llegar a sugerir una patente del tipo equivocado (una rampla como si fuera un tracto). Corregido antes de tocar nada real -- una clasificación de tipo ya establecida nunca vuelve a degradarse.
- **Validado contra las 13 decisiones reales vigentes (sólo lectura, nunca aplicado):** con el caché de evidencia externa real de SIGRO conectado, esa decisión mejoró de "sugerencia" a "contradicción documental" (evidencia más fuerte). El resto se mantiene exactamente como el bloque anterior lo había clasificado -- nada se resuelve solo todavía porque el historial de confirmaciones humanas recién empieza en cero.
- **Desktop ya puede mostrar y aplicar estas decisiones:** las tarjetas de cliente/obra ahora explican, en lenguaje humano, por qué Atlas sugiere una entidad -- nunca un puntaje sin explicar.
- **Nada se aplicó a Drive real.** Motor `1399 passed, 0 failed` (12 nuevos, incluida la corrección del bug de tipo). Código publicado (no modifica datos reales por sí mismo); pendiente de que Javier decida activar la integración sobre la operación real.

---

## 2026-08-19 — MOTOR DE EVIDENCIA FASE 2: clientes, obras, verificación externa e Incidencias Documentales -- construido y validado, sin aplicar a producción

- **Cambio de etapa:** el mismo patrón que resolvió vehículos (evidencia estructurada, nunca autocorrección silenciosa) se extendió a clientes y obras, y se formalizó como capa reutilizable (`atlas_core/motor_evidencia.py`) para que el próximo dominio (destinos, y más adelante otros) no tenga que reinventarlo.
- **Internet es ahora una fuente explícita de evidencia -- probado con dos casos reales, no simulados:** se consultaron fuentes públicas reales para "EMPRESA CONST SIGRO SA" (guía 464493) y "Supermercado Señor de los Milagros" (guía 464170). El primero corroboró, con la razón social y RUT reales de la empresa (Empresa Constructora Sigro S.A., RUT 89.037.500-6, sitio corporativo `sigro.cl`), que la obra ya confirmada "EMPRESA CONST SIGRO" es la misma entidad, sólo con un sufijo societario de más -- Atlas la marca como sugerencia fuerte, nunca resuelta sola. El segundo, honestamente, no encontró ningún negocio con ese nombre exacto en Mejillones -- Atlas se abstiene, sin inventar una respuesta, y deja anotado (sólo como referencia para Javier, nunca como conclusión propia) que existen otros dos supermercados reales confirmados en la misma calle.
- **Aprendizaje operacional, nuevo:** Atlas ahora puede recordar que un humano ya confirmó, en dos o más ocasiones independientes (nunca el mismo documento repetido), que un RUT corresponde a una entidad -- a la tercera aparición equivalente, aunque el documento traiga un texto nunca visto antes, Atlas ya no vuelve a preguntar: resuelve solo y registra una Incidencia Documental, sin bloquear el viaje.
- **Incidencias Documentales, capacidad nueva y obligatoria:** un registro auditable para errores reales del CONTENIDO de una guía (cliente equivocado, patente que no corresponde, obra inconsistente, etc.) -- explícitamente separado, y protegido por tests, de cualquier problema de foto borrosa, mancha o confusión de OCR, que nunca debe aparecer ahí.
- **Validado contra el dataset real completo (sólo lectura, nunca escrito a Drive):** de 14 nombres de cliente documentales únicos, 13 ya coinciden exactos y 1 (`TORRES OCARANEA LTDA`) es un candidato real a revisar (variante de `TORRES OCARANZA LTDA`, ya confirmado). De 28 nombres de obra únicos, 15 ya coinciden, 12 son altas genuinamente nuevas sin ninguna duda, y 1 es el caso SIGRO ya descrito -- el motor lo encontró sin que nadie le dijera dónde buscar.
- **Nada de esto se aplicó a producción:** Drive, catálogos y decisiones reales quedan intactos. Motor `1388 passed, 0 failed` (55 tests nuevos). Queda pendiente de una única revisión de Javier antes de: aplicar cualquier resolución, empezar a acumular confirmaciones reales, o conectar el motor al flujo de decisiones en vivo.

---

## 2026-08-19 — PUESTA EN PRODUCCIÓN CONTROLADA del Motor de Evidencia de Vehículos: JD8659 registrada, 2 de 15 decisiones reales resueltas sin preguntarle a Javier

- **Motor y Desktop publicados:** `335c59c` + `87d49b2` (Motor) y `a55a726` (Desktop), ambos en `origin`, working trees limpios. Motor `1333 passed`; Desktop `221 passed`.
- **JD8659 registrada en el catálogo real:** CARRO, CONFIRMADO, ACTIVO, asociada al RUT de Carlos Simón, fuente `CONFIRMACION_HUMANA`, actor `JAVIER_MBT`. JE8659 y VP8521 quedaron exactamente igual que antes -- ninguna se borró, fusionó ni reinterpretó.
- **Bug real encontrado y corregido antes de aplicar nada:** el mecanismo que actualiza los candidatos de una decisión (`enriquecer_decisiones_vehiculo`) sólo actuaba si la decisión todavía no tenía ninguno -- una decisión con candidatos "viejos" (de antes de que JD8659 existiera) quedaba congelada para siempre, y JD8659 nunca habría llegado a aparecer como candidata real. Corregido de forma general (siempre recalcula), no como parche puntual.
- **2 de las 15 decisiones reales se resolvieron solas, sin preguntarle nada a Javier:** las dos guías de Carlos Simón con rampla mal leída (464264: JD6659→JD8659; 464265: JD0659→JD8659) tenían evidencia suficiente (confirmación humana directa asociada al RUT del chofer) -- Atlas las cerró con `SELECCIONAR_OTRA_PATENTE`, preservando intacta la lectura OCR original en el CSV y dejando el razonamiento completo auditable en el ledger.
- **El resto de la bandeja se clasificó, no se forzó:** el caso VP6521→VP8521 (mismo Carlos Simón, tracto) quedó deliberadamente como sugerencia -- aunque la evidencia documental es fuerte (2 transportes independientes, 2 mandantes distintos, sin rival), Atlas decidió no autorresolver sin una confirmación humana explícita, para no mover el umbral de "documentos que coinciden" a "verdad". El caso Ortiz (XF3662) y el de la obra "EMPRESA CONST SIGRO SA" (que probablemente ya existe con otro sufijo) quedan señalados con toda la evidencia a la vista, listos para un clic de Javier -- ninguno se resolvió unilateralmente.
- **Bandeja real: 15 → 13 pendientes.** Drive: sólo `vehiculos.json`, `decisiones_pendientes.json` y `decisiones_aplicadas.json` cambiaron; `analisis_completo_guias.csv` (los datos documentales) no se tocó. 3 respaldos completos con manifiesto SHA-256 quedaron en `respaldos/`.
- **Siguiente frente recomendado:** que Javier revise en Desktop las 2 sugerencias fuertes (VP8521, EMPRESA CONST SIGRO) y decida si aplicarlas con un clic; después, generalizar el mismo patrón (evidencia estructurada, nunca autocorrección silenciosa) a obras/destinos.

---

## 2026-08-19 — MOTOR DE EVIDENCIA DE VEHÍCULOS: primera capa de razonamiento determinista de Atlas (no "IA" todavía) — validado, sin tocar Drive, pendiente de revisión con Javier

- **Origen del bloque:** al preparar el registro canónico de JD8659 (la rampla de Carlos Simón, confirmada directamente por el chofer a Javier), se descubrió que el mecanismo existente (`sugerir_vehiculos_por_chofer`) sólo podía sugerir una patente si OTRO documento ya la había leído literalmente por OCR — y ningún documento leyó nunca "JD8659". Javier detuvo el registro puntual y pidió corregir la **capacidad general**, no parchear este caso.
- **Se construyó `evaluar_evidencia_patente`** (nueva pieza de `atlas_core.decisiones_pendientes`), un motor de reglas determinista — nunca LLM, nunca IA generativa, nunca red externa — que combina señales ya existentes en el proyecto (RUT del chofer normalizado, compatibilidad de tipo de vehículo, corroboración por corrección OCR ya calibrada, y una nueva confirmación humana estructurada "esta patente es de este chofer") en una jerarquía de precedencia explícita, nunca un score numérico sin explicar. Produce siempre uno de tres resultados: `RESUELTO_AUTOMATICAMENTE` (sólo informativo — nunca escribe nada por sí solo), `SUGERENCIA_HUMANA`, o `ABSTENCION` ("no puedo determinarlo con seguridad").
- **Principio central, ya en código y en tests: "repetición no equivale a independencia".** Tres documentos del mismo transporte/evento repitiendo el mismo error de OCR cuentan como UNA sola corroboración, nunca tres — exactamente lo que le pasaba a JE8659 (el error que Javier ya había descartado) frente a JD8659 (la verdad confirmada, sin ninguna repetición documental a su favor). Verificado tanto con tests sintéticos como corriendo el motor nuevo contra los datos reales vigentes: lo que antes se reportaba como "3 documentos" para JE8659 el motor nuevo lo reporta correctamente como 1 transporte independiente.
- **Caso positivo obligatorio (Carlos Simón) y caso negativo obligatorio (Patrick Ortiz — XF3662) ambos honran la regla de fondo:** Simón, con confirmación humana directa asociada a su RUT, alcanza `RESUELTO_AUTOMATICAMENTE`; Ortiz, sin ninguna confirmación humana y con un único candidato circunstancial, queda en `SUGERENCIA_HUMANA` débil — **nunca se autocorrige** XF3662 → XF3629. 13 tests nuevos cubren estos casos y siete controles adicionales (candidatos empatados, tipo incorrecto, formato de RUT con/sin puntos — un caso real encontrado en el propio dataset).
- **Validación TEMP contra las 15 decisiones reales vigentes (sin escribir Drive):** de las 8 decisiones `VEHICULO_DESCONOCIDO` reales, hoy (sin registrar JD8659 todavía) el motor clasifica 4 como `SUGERENCIA_HUMANA` (las de Carlos Simón) y 4 como `ABSTENCION` (464170 y 464854, sin evidencia real) — **cero `RESUELTO_AUTOMATICAMENTE`**, exactamente lo esperado mientras JD8659 no esté registrado con su confirmación humana. Esto confirma que el motor no se adelanta ni actúa por su cuenta.
- **Se integró con la infraestructura ya publicada, sin crear un segundo sistema de decisiones:** el CLI (`aplicar_decision_pendiente.py`) y Atlas Desktop (antes con un bug real que impedía mostrar `USAR_PATENTE_EXISTENTE`/`SELECCIONAR_OTRA_PATENTE` aunque ya estuvieran implementadas en Motor) ahora exponen ambas acciones de punta a punta.
- **Nada de esto se aplicó a producción:** Drive, catálogos y decisiones reales quedan intactos; JD8659 **no** se registró. Motor 1332/1332, Desktop 221/221. Queda pendiente de revisión con Javier antes de: registrar JD8659 real, regenerar la bandeja, o empezar a resolver las 15 revisiones reales.

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
# 2026-08-17 — Cierre funcional R3.4 + buscador

- R3.4 quedó validado en operación real desde Atlas Desarrollo: Javier confirmó desde Desktop el destino de la guía 464715 mediante la decisión `DESTINO_SIN_CONFIRMAR`.
- La revalidación documental sin OCR funcionó: 464715 quedó `OK`, sin `OBRA_DESTINO_SIN_CORROBORAR`, dejó de requerir revisión y Viajes se refrescó con el reporte vigente. **OCR ejecutado: NO**.
- El buscador Desktop quedó validado para chofer, N.º de transporte y N.º de guía (caso real 464715). La patente está excluida del índice de búsqueda.
- Cierre técnico: Motor **1114 passed, 0 failed**; Desktop **184 passed, 0 failed**. Drive coherente y sin residuos `.tmp`, staging ni `_respaldos` operacionales.
- Vehículos continúa pendiente para el bloque siguiente; no se modificó en este cierre.
## 2026-08-17 — Checkpoint R3.5/R3.6.1 validado en operación real

- R3.5/R3.5.1 aprobado: Javier aplicó varias decisiones consecutivas y la bandeja se regeneró sin obsolescencia encadenada.
- R3.6.1 aprobado desde Atlas Desarrollo: KN5439 y JF6468 se clasificaron inequívocamente; XF3629 solicitó tipo humano y quedó registrada como `CAMION_RIGIDO`. La experiencia visual fue aprobada y Revisión de Atlas quedó en **0 pendientes**.
- R3.6.2 queda **PENDIENTE, no implementado ni publicado**. Hallazgo para el próximo bloque: algunos Viajes conservan motivos posiblemente obsoletos, especialmente `PATENTE_SIN_HOMOLOGAR` en la guía 464740 después de registrar XF3629.
- Este checkpoint no ejecutó OCR ni modificó Drive.

## 2026-08-17 — R3.6.2 implementado y validado read-only: revalidación conservadora de `PATENTE_SIN_HOMOLOGAR`

- **Causa raíz confirmada en código:** `aplicacion_decisiones.py` sólo disparaba `revalidar_y_regenerar_reporte` para `DESTINO_SIN_CONFIRMAR/CONFIRMAR`; la decisión `VEHICULO_DESCONOCIDO/REGISTRAR` (la que confirma canónicamente una patente) nunca disparaba revalidación, así que una patente recién confirmada no limpiaba `PATENTE_SIN_HOMOLOGAR` en el dataset. Se agregó el disparo faltante, reutilizando la misma infraestructura ya vigente para obra/destino.
- **Nueva revalidación conservadora en `revalidacion_documental.py`:** retira `PATENTE_SIN_HOMOLOGAR` de una fila únicamente cuando TODAS sus patentes documentales relevantes (`patente_tracto`/`patente_rampla`) resuelven, de forma inequívoca, contra un vehículo `CONFIRMADO`+`ACTIVO` con tipo compatible con el rol documental (rampla→CARRO; tracto con rampla válida→TRACTO; tracto aislado→TRACTO o CAMION_RIGIDO). Ante cualquier patente faltante, ambigua, inactiva, no confirmada o de tipo incompatible, conserva el motivo. `OBRA_DESTINO_SIN_CORROBORAR` no fue tocado.
- Se auditaron explícitamente otros motivos catalogales (`CLIENTE_SIN_CORROBORAR`, `CHOFER_SIN_CORROBORAR`, `PATENTE_AMBIGUA`, `CLIENTE_NUEVA_ENTIDAD_NO_CATALOGADA`) y se dejaron deliberadamente fuera de alcance por no poder demostrarse puramente catalogales sin releer el documento original.
- Tests: 15 nuevos focalizados + 87 en el grupo relacionado (vehículos R3.6.1, obra/destino R3.4, decisiones R3.3) + suite completa **1145 passed, 0 failed** (baseline R3.6.1 = 1130 + 15 nuevos).
- **Validación real read-only** (sobre copia temporal de los datos reales, nunca sobre Drive): guía **464740** pierde `PATENTE_SIN_HOMOLOGAR` y conserva `CLIENTE_AUSENTE` (`XF3629` ya es `CAMION_RIGIDO`/`CONFIRMADO`/`ACTIVO`, confirmado por Javier el mismo día); guía **464726** queda completamente `OK` (`KN5439`=TRACTO, `JF6468`=CARRO, ambas confirmadas/activas). `OBRA_DESTINO_SIN_CORROBORAR` no tuvo cambios. Verificado independientemente por Claude (orquestador), no sólo reportado por el agente que implementó.
- **Drive modificado: NO.** `G:\Mi unidad\Atlas` permaneció con su `mtime` sin cambios durante todo el bloque (confirmado antes y después). Sin commit ni push -- working tree del Motor con 3 archivos modificados + 1 test nuevo, pendiente de revisión de Javier/ChatGPT.
- **Pendiente explícito para el próximo bloque:** aplicar esta revalidación contra `G:\Mi unidad\Atlas` real (con backup previo, bajo supervisión), lo que resolvería `PATENTE_SIN_HOMOLOGAR` en 464726 y 464740 y regeneraría el reporte vigente. No ejecutado en este bloque por instrucción explícita.

## 2026-08-17 — R3.6.2 aplicado realmente sobre la operación vigente (controlado, con rollback verificado)

- **Backup previo verificado byte a byte:** `respaldos/R3_6_2_ROLLBACK_PRE_APLICACION_20260817_165251/` -- copia de `analisis_completo_guias.csv` (SHA-256 `90E268...E3E480`) y `estado_operacion.json` (SHA-256 `A4AFE0...D9168B`), ambos verificados idénticos al original antes de escribir. Backup preservado deliberadamente hasta confirmar estabilidad y publicar.
- **Snapshot antes:** 28 filas, 24 OK / 4 REVISAR, motivos `MATERIAL_AUSENTE`(1) `OBRA_DESTINO_SIN_CORROBORAR`(2) `PATENTE_SIN_HOMOLOGAR`(2) `CLIENTE_AUSENTE`(1). 464740 = `PATENTE_SIN_HOMOLOGAR | CLIENTE_AUSENTE`/REVISAR; 464726 = `PATENTE_SIN_HOMOLOGAR`/REVISAR.
- **Aplicación real:** se ejecutó exclusivamente `revalidar_y_regenerar_reporte(raiz_atlas="G:\Mi unidad\Atlas", nombre_carpeta_reporte="reporte_revalidacion_20260817_205408_942731")`, el mismo esquema de nombre que usa el flujo ya auditado. Sin OCR, sin reprocesar imágenes, sin tocar catálogos.
- **Resultado exactamente igual al predicho por la simulación previa:** 28 filas antes y después (sin guías agregadas ni desaparecidas); sólo 2 filas cambiaron (464726, 464740) y sólo en las columnas `motivos_revision_documento`/`indicador_revision` -- las 26 filas restantes quedaron byte-idénticas. **464740** perdió únicamente `PATENTE_SIN_HOMOLOGAR`, conservó `CLIENTE_AUSENTE`, permaneció `REVISAR`. **464726** quedó completamente `OK`, sin motivos. Dataset final: 25 OK / 3 REVISAR, `PATENTE_SIN_HOMOLOGAR` en 0 filas, `OBRA_DESTINO_SIN_CORROBORAR`(2)/`MATERIAL_AUSENTE`(1)/`CLIENTE_AUSENTE`(1) intactos.
- **Integridad confirmada:** los 11 archivos de `catalogos_privados/` (vehículos, obras/destinos, clientes, destinos, choferes, empresas, etc.) conservaron su `mtime` exacto de antes del bloque -- ninguno fue tocado. `cache/`, `datos_privados/` (imágenes) y `coordinacion/` tampoco cambiaron. `decisiones_pendientes.json`/`decisiones_aplicadas.json` sin cambios. Se creó una única carpeta nueva `reportes/reporte_revalidacion_20260817_205408_942731/` (viajes.csv, documentos_sin_transporte.csv, clientes_no_reconocidos.csv, resumen_viajes.md, manifest) y `estado_operacion.json` se actualizó para apuntar a ella; ningún reporte histórico anterior fue modificado.
- **Drive modificado: SÍ -- únicamente por esta aplicación controlada R3.6.2.** Rollback no fue necesario (no hubo ninguna diferencia inesperada). Backup conservado en `respaldos/R3_6_2_ROLLBACK_PRE_APLICACION_20260817_165251/` hasta que se confirme la estabilidad y se publique el bloque.
- Sin commit ni push en ningún repo. No se repitió la suite completa (código sin cambios desde los 1145 passed ya verificados).
- **Estado: R3.6.2 VALIDADO REALMENTE -- LISTO PARA PUBLICAR** (pendiente de decisión de Javier/ChatGPT sobre commit/push y eliminación del backup).

## 2026-08-17 — R3.6.2 publicado (commit `a46b3e8`) y auditoría funcional post-cierre

- R3.6.2 se publicó: commit `a46b3e8` ("feat: revalidar motivos catalogales tras aprendizaje") pusheado a `origin/lector-mvp-guia-nueva`, local=remoto, ahead/behind 0/0. Backup de rollback preservado sin eliminar.
- Auditoría funcional completa (read-only, sin tocar código ni Drive) sobre lectura/OCR, Revisión de Atlas, viajes, catálogos, Desktop/UX y reportes. Sin `P0`. Tres `P1` identificados y verificados con evidencia real: (1) falso `CONFLICTO_RUT_CHOFER` por formato de RUT; (2) `CLIENTE_DESCONOCIDO`/`CLIENTE_CANDIDATO`/`ALIAS_CANDIDATO` sin aplicación real desde Revisión de Atlas; (3) `CLIENTE_SIN_CORROBORAR`/`CHOFER_SIN_CORROBORAR` sin ningún tipo de decisión asociado. Recomendado como próximo bloque el ítem (1), por ser el único bug puro y acotado a un solo archivo.

## 2026-08-17 — P1: falso `CONFLICTO_RUT_CHOFER` por formato corregido

- **Bug real confirmado:** dos documentos del mismo viaje con el mismo RUT de chofer pero distinto formato textual (`10.833.150-K` vs `10833150-K`) generaban `CONFLICTO_RUT_CHOFER` porque la comparación de conflictos usaba la misma normalización genérica (`_clave_normalizada`: casefold + espacios + acentos) que todos los demás campos, sin quitar puntuación de RUT. Caso real confirmado en el dataset vigente: transporte `0000352752` (guías 464641/464642, chofer JOSE LAZCANO).
- **Corrección quirúrgica en `atlas_core/gestor_viajes.py`:** nueva `_valores_compatibles_rut`, exclusiva de `CONFLICTO_RUT_CHOFER`, que reutiliza `normalizar_rut` (ya usada en producción para corroborar RUT de chofer contra catálogo) y cae a la comparación literal previa cuando el valor no tiene forma de RUT (sin dígitos/K), para no ocultar conflictos entre textos no-RUT. Ningún otro campo de conflicto (chofer, cliente, obra, patentes, fecha, horas) cambió su comparación.
- 12 tests nuevos en `tests/test_gestor_viajes.py`: equivalencia de formato, verificador en minúscula, conflicto real preservado, valores ausentes, texto no-RUT (oculta/no oculta según corresponda), y confirmación explícita de que otros campos no cambiaron. Suite completa: **1157 passed, 0 failed** (baseline 1145 + 12).
- **Validación real read-only** (sin escribir en Drive): se corrió `agrupar_viajes` sobre una copia en memoria del dataset real vigente con el código antes y después del fix. Único motivo retirado en `0000352752`: `CONFLICTO_RUT_CHOFER` (pasa a `CONFIRMADO`). Se descubrió un **segundo caso real** con el mismo defecto: transporte `0000352376` (chofer CARLOS SIMON, RUT `15.489.424-1` vs `15489424-1`) -- pierde `CONFLICTO_RUT_CHOFER` pero conserva intactos `CONFLICTO_CLIENTE` y `CONFLICTO_OBRA_DESTINO` (conflicto real y ya conocido de EBEMA/PRODALAM bajo el mismo transporte), quedando correctamente `REQUIERE_REVISION`. Ningún otro de los 24 viajes reales cambió.
- Desktop no fue tocado. Drive no fue modificado (solo lecturas; el resultado no se escribió al dataset real). Sin commit ni push -- working tree con `atlas_core/gestor_viajes.py` y `tests/test_gestor_viajes.py` pendientes de revisión.
- **Estado: LISTO PARA VALIDACIÓN REAL** (aplicación controlada sobre Drive queda para el bloque siguiente, con el mismo procedimiento de backup/rollback ya usado en R3.6.2).

## 2026-08-17 — Diagnóstico Viajes ↔ Revisión de Atlas (read-only)

- Auditoría diagnóstica completa (sin código, sin Drive) sobre por qué Atlas puede mostrar viajes `REQUIERE_REVISION` mientras Revisión de Atlas muestra 0 pendientes. Tres causas raíz confirmadas con datos reales: (1) el ledger de decisiones está vacío por diseño; (2) `OBRA_DESCONOCIDA→REGISTRAR` sin `destino_id` deja al documento sin ninguna vía de decisión posterior -- confirmado con las guías reales 464718/464746, ambas con obra registrada pero `relaciones: []` en `obras_destinos.json`, y siguen `OBRA_DESTINO_SIN_CORROBORAR`/`REVISAR`; (3) ningún `CONFLICTO_*` de nivel viaje tiene tipo de decisión asociado. Hallazgo adicional en Desktop: `atlas_viajes.html:1222-1224` prioriza motivos documentales (incluso no bloqueantes) sobre los conflictos reales de viaje, ocultando la causa real -- confirmado con el caso real 464699/`0000352376`.
- Clasificación A–E de todos los motivos; matriz motivo↔decisión completa; plan de 7 bloques recomendado, derivado de la evidencia. Próximo bloque recomendado: aplicar el fix de RUT (`2cb67cb`) al dataset real -- ejecutado en el bloque siguiente.

## 2026-08-17 — Fix de RUT (`2cb67cb`) aplicado realmente al reporte vigente

- **Paso 1 del roadmap de reconciliación Viajes↔Revisión de Atlas.** Se regeneró el reporte de viajes vigente usando el mecanismo canónico (`generar_reporte_viajes.py`, el mismo CLI de producción), para que refleje la normalización de RUT ya publicada en `2cb67cb`. **No se tocó `analisis_completo_guias.csv`** (confirmado por SHA-256 idéntico antes/después) ni ningún catálogo ni decisión -- el mecanismo usado sólo lee el CSV y escribe una carpeta de reporte nueva + `estado_operacion.json`.
- Backup previo verificado byte a byte: `respaldos/FIX_RUT_ROLLBACK_PRE_APLICACION_20260817_193719/` (`estado_operacion.json`, único archivo modificado in-place, más referencia SHA-256 del CSV que no debía cambiar).
- Dry-run sobre copia temporal confirmó el resultado exacto antes de tocar Drive; la aplicación real lo reprodujo sin diferencias.
- **Resultado exactamente igual al predicho:** de 24 viajes, sólo 2 cambiaron semánticamente. **`0000352752`** (464641/464642): `REQUIERE_REVISION`/`CONFLICTO_RUT_CHOFER` → **`CONFIRMADO`**, sin motivos. **`0000352376`** (464698/699/700): pierde únicamente `CONFLICTO_RUT_CHOFER`, conserva intactos `CONFLICTO_CLIENTE` y `CONFLICTO_OBRA_DESTINO`, sigue `REQUIERE_REVISION` -- exactamente lo pedido. Los 22 viajes restantes: idénticos (única diferencia, esperada, el timestamp `fecha_creacion` de regeneración). Dataset final: **20 CONFIRMADO / 4 REQUIERE_REVISION** (antes 19/5).
- Nuevo reporte vigente: `reportes/reporte_fix_rut_chofer_20260817_233840/`. Integridad verificada: los 11 archivos de `catalogos_privados/`, `decisiones_pendientes.json`/`decisiones_aplicadas.json`, `cache/`, `datos_privados/` (imágenes) y todos los reportes históricos previos conservaron su `mtime` exacto -- ninguno fue tocado.
- **Drive modificado: SÍ -- únicamente por esta aplicación controlada del fix de RUT.** Rollback no requerido (cero diferencias inesperadas). Backup preservado, no eliminado. Motor y Desktop sin cambios de código (`git status` limpio en ambos, HEAD `2cb67cb`/`87b9c8c` intactos) -- sólo estas tres bitácoras quedan modificadas en el working tree del Motor, sin commit.
- **Estado: FIX RUT APLICADO REALMENTE -- LISTO PARA PASO 2** (Paso 2 del roadmap: cerrar el ciclo `OBRA_DESCONOCIDA→DESTINO_SIN_CONFIRMAR`, no iniciado en este bloque).

---

## 2026-08-17 — R3.4.2 (Paso 2): cerrado el callejón sin salida `OBRA_DESCONOCIDA→REGISTRAR` sin siguiente paso

- **Causa raíz confirmada** (no sólo el diagnóstico previo -- se reprodujo el flujo completo en TEMP antes de tocar código): `detectar_decisiones_documento` sólo puede emitir `DESTINO_SIN_CONFIRMAR` cuando la obra YA existe en el catálogo (necesita un `obra_id` al que referenciarse). Cuando la obra es realmente desconocida, esa condición nunca se cumple en el momento del procesamiento -- sólo se emite `OBRA_DESCONOCIDA`. Al REGISTRARLA, `aplicar_decision_obra` llamaba `registrar_observacion` sin `destino_id`: la obra queda creada (`OBSERVADA`/`ACTIVO`) pero `relaciones: []`. Y `regenerar_decisiones_persistidas` -- el único mecanismo que corre después de aplicar una decisión -- sólo **reclasifica decisiones ya persistidas**, nunca sintetiza un tipo nuevo a partir de datos ya observados: no había ninguna vía para que apareciera la pregunta de destino. Confirmado con las guías reales `464718` y `464746` (validación read-only, ver abajo): ambas con obra `OBSERVADA`/`ACTIVO`, `relaciones: []`, y el CSV real sigue `OBRA_DESTINO_SIN_CORROBORAR`/`REVISAR`.
- **Fix (aditivo, sin tocar el contrato existente de R3.4):** `detectar_decisiones_documento` ahora guarda `destino_documental` (la misma dirección ya resuelta por `resolver_entrega_documento`, sin nueva extracción) también en el `contexto` de `OBRA_DESCONOCIDA` -- dato que antes se perdía. Nueva función `decision_destino_para_obra_registrada` (`atlas_core/decisiones_pendientes.py`) reconstruye, sin OCR, la misma decisión `DESTINO_SIN_CONFIRMAR` que se habría generado si la obra ya hubiera existido, distinguiendo los tres casos: **CASO A** (la relación ya es corroborable sin decisión adicional -- se abstiene, nada redundante); **CASO B** (hay destino documental -- genera la decisión); **CASO C** (no hay destino documental, o la decisión persistida es de antes de este cambio y no trae el dato -- se abstiene, nunca inventa). Se conecta en dos puntos: (1) `aplicar_decision_obra`, justo después de `REGISTRAR`, agrega la decisión sintetizada a la bandeja que se publica; (2) `regenerar_decisiones_persistidas`, en el punto donde ya descartaba silenciosamente una `OBRA_DESCONOCIDA` persistida cuya obra resultó existir por otra vía, ahora la reemplaza por su propia pregunta de destino en vez de descartarla sin dejar rastro.
- **Idempotencia y no resurrección garantizadas por el mecanismo ya existente, no por código nuevo:** el `decision_id` de la decisión sintetizada es determinístico (mismo hash que si se hubiera generado en vivo); `generar_artefacto` ya filtra contra el ledger (`decisiones_aplicadas.json`) antes de publicar, así que una decisión ya `CONFIRMAR`/`NO_CONFIRMAR` nunca resucita aunque el mecanismo de regeneración la vuelva a sintetizar. R3.5/R3.5.1 (regeneración encadenada, ventana legacy) quedaron intactos -- no se tocó esa lógica.
- **Desktop: sin cambios.** `DESTINO_SIN_CONFIRMAR` ya se renderiza y aplica de forma completamente genérica en `decisiones_pendientes_ui.js` (mismo mecanismo que `OBRA_DESCONOCIDA`/`VEHICULO_DESCONOCIDO`) -- verificado antes de tocar Motor; no hace falta ninguna brecha que cerrar del lado Desktop.
- 13 tests nuevos en `tests/test_ciclo_obra_destino_r342.py` (CASO A/B/C, decisión consecutiva sin obsolescencia, decidir después, rechazo terminal sin resurrección, idempotencia, motivos independientes, regeneración general para otra guía con la misma obra, abstención sobre decisiones legado sin el campo nuevo) + 1 test existente actualizado (`test_obra_desconocida_transporta_cliente_reconocido_separado_de_la_obra`, ahora con `destino_documental` en el contexto esperado). Suite completa: **1170 passed, 0 failed** (baseline 1157 + 13).
- **Validación real read-only sobre 464718 y 464746** (sin escribir en Drive, verificado por hash antes/después de `obras_destinos.json`/`destinos_maestros.json`): con la obra real ya registrada y el `despachar_a_crudo` real de cada guía, `decision_destino_para_obra_registrada` produce exactamente la decisión `DESTINO_SIN_CONFIRMAR` esperada -- `464718` → "RICARDO MORALES 3369 SAN MIGUEL SAN MIGUEL"; `464746` → "CAM. EL NOVICIADO LAMPA LAMPA" -- ambas con `identidad_resuelta` apuntando a la obra real ya creada. **No se reparó el histórico real** (464718/464746 siguen atrapados hoy); eso queda para un bloque de reconciliación aparte, deliberadamente fuera de este bloque.
- Drive no fue modificado (sólo lecturas para la validación). Sin commit ni push -- working tree del Motor con `atlas_core/decisiones_pendientes.py`, `atlas_core/aplicacion_decisiones.py`, `tests/test_ciclo_obra_destino_r342.py` y `tests/test_decisiones_pendientes.py` pendientes de revisión.
- **Estado: LISTO PARA VALIDACIÓN REAL** (reconciliar 464718/464746 -- y cualquier otra guía real en el mismo estado -- queda para el bloque siguiente, con el mismo procedimiento de backup/rollback ya usado en bloques anteriores).

---

## 2026-08-17 — R3.4.3 (Paso 3): reconciliación histórica aplicada realmente -- 464718/464746 vuelven a aparecer en Revisión de Atlas

- **Brecha real descubierta al intentar la validación real:** el mecanismo del Paso 2 cierra el ciclo hacia adelante (documentos nuevos) y para decisiones todavía pendientes en la bandeja, pero **no** reconcilia una `OBRA_DESCONOCIDA` que ya fue `REGISTRAR`-ada *antes* de que el fix existiera -- confirmado con un dry-run real (no sólo razonado): reaplicar la decisión original de 464718 es idempotente (no dispara nada) y regenerar la bandeja pendiente real (vacía) tampoco produce nada, porque el `contexto.destino_documental` nunca se persistió para esas dos aplicaciones ya hechas.
- **Nueva función, general y determinística, sin mencionar guías reales en el código:** `detectar_decisiones_destino_historicas_sin_ocr` (`atlas_core/revalidacion_documental.py`) recorre el ledger (`decisiones_aplicadas.json`), y para cada `OBRA_DESCONOCIDA`/`REGISTRAR` ya aplicada reconstruye la decisión `DESTINO_SIN_CONFIRMAR` que faltó -- usando exclusivamente `obra_id`/`cliente_id` ya persistidos por el ledger (nunca inferidos por nombre) y el destino documental de la fila del dataset con el MISMO `numero_guia` (correlación por clave exacta, con verificación adicional de que el `obra_destino` de esa fila coincide con la obra del ledger). Se abstiene ante cualquier ambigüedad (fila ausente/duplicada, obra/cliente inactivo, destino ausente, obra ya corroborada). `reconciliar_decisiones_destino_historicas` publica el resultado en `decisiones_pendientes.json`, reutilizando el mismo filtro contra el ledger que ya da idempotencia y no-resurrección al resto del sistema.
- **Validado con el ledger real completo, no sólo los dos casos conocidos:** de 3 aplicaciones `OBRA_DESCONOCIDA`/`REGISTRAR` reales, la de 464715 se excluye correctamente (ya tenía relación `CONFIRMADA` -- CASO A) y sólo 464718/464746 entran por la regla general, sin excepción en código.
- **14 tests nuevos** (`tests/test_reconciliacion_historica_destino_r343.py`): candidato básico, CASO A (ya confirmada), CASO C (sin destino), fila ausente/ambigua, obra/cliente inactivo, correlación obra≠fila (descarta), otros tipos/acciones del ledger ignorados, 3 obras reales-símil (2 generan candidato, 1 no), publicación sin tocar catálogos/CSV/ledger, idempotencia, no resurrección de decisión terminal, preserva otras decisiones pendientes. Suite completa: **1184 passed, 0 failed** (baseline 1170 + 14).
- **Backup previo:** `respaldos/CICLO_OBRA_DESTINO_ROLLBACK_PRE_APLICACION_20260817_210220/`, con manifiesto y SHA-256 del único archivo real que cambiaría (`decisiones_pendientes.json`), verificado byte a byte antes de escribir.
- **Aplicación real ejecutada:** `reconciliar_decisiones_destino_historicas(raiz_atlas="G:\Mi unidad\Atlas")`. Resultado: 2 candidatas detectadas, 2 publicadas. `decisiones_pendientes.json` real pasó de 0 a 2 decisiones `DESTINO_SIN_CONFIRMAR` -- guía 464718 (destino "RICARDO MORALES 3369 SAN MIGUEL SAN MIGUEL") y guía 464746 (destino "CAM. EL NOVICIADO LAMPA LAMPA"), cada una con `identidad_resuelta`/`contexto` apuntando a la obra y cliente reales ya registrados.
- **Integridad verificada por SHA-256 y por escaneo de `mtime` de todo el árbol de Drive:** en los últimos 5 minutos del bloque, únicamente cambiaron el backup nuevo y `operacion/actual/decisiones_pendientes.json` -- ningún catálogo, el CSV documental, el ledger ni `estado_operacion.json` fueron tocados. **No se aplicó ni confirmó ninguna decisión** (eso queda para que Javier lo haga desde Desktop).
- **Drive modificado: SÍ -- únicamente `operacion/actual/decisiones_pendientes.json` (más el backup nuevo).** Rollback no requerido. Backup preservado.
- Motor y Desktop sin cambios de código adicionales a los del Paso 2 + esta función. Sin commit ni push -- working tree con `atlas_core/revalidacion_documental.py` modificado y `tests/test_reconciliacion_historica_destino_r343.py` nuevo, además de estas bitácoras.
- **Próximo paso:** Javier abre Atlas Viajes DESARROLLO → Revisión de Atlas y confirma visualmente que 464718/464746 aparecen como `DESTINO_SIN_CONFIRMAR` con el destino correcto -- sin confirmar nada todavía dentro de este bloque.
- **Estado: DECISIONES RECONCILIADAS -- LISTO PARA VALIDACIÓN VISUAL DE JAVIER.**

---

## 2026-08-17 — Cierre de jornada: validación visual de Javier exitosa, decisiones todavía sin aplicar

- **Javier validó manualmente en Atlas Viajes DESARROLLO → Revisión de Atlas** ambas decisiones `DESTINO_SIN_CONFIRMAR` reconciliadas en el bloque anterior: **464718** aparece con la obra correcta y el destino mostrado coincide con la guía física; **464746** aparece con la obra correcta y el destino mostrado coincide con la guía física.
- **Ninguna decisión fue aplicada todavía** -- ambas permanecen `PENDIENTE` en `decisiones_pendientes.json` real, exactamente como quedaron tras la reconciliación.
- **Siguiente paso oficial, no iniciado hoy:** aplicar `464718` y `464746` desde Desktop (Revisión de Atlas, no por script) y verificar el cierre del ciclo completo -- creación de la relación obra↔destino, revalidación automática, desaparición de `OBRA_DESTINO_SIN_CORROBORAR` en el dataset real, y regeneración/revisión de viajes.
- **Sin commit ni push todavía** -- falta la validación final del ciclo completo con la aplicación real de ambas decisiones. Working tree del Motor sin cambios de código respecto al bloque anterior (sólo estas tres bitácoras).
- Drive no fue modificado en este bloque (sólo lecturas de verificación). Backups de bloques previos (`R3_6_2_...`, `FIX_RUT_...`, `CICLO_OBRA_DESTINO_...`) preservados.
- **Estado: JORNADA CERRADA -- LISTO PARA CONTINUAR MAÑANA DESDE VALIDACIÓN FINAL DEL CICLO OBRA→DESTINO.**

---

## 2026-08-18 — Ciclo obra→destino validado completamente con las dos aplicaciones reales de Javier

- **Javier aplicó realmente ambas decisiones desde Atlas Viajes DESARROLLO** (Revisión de Atlas), cada una `CONFIRMAR`, una sola vez: **464718** (obra "CONSULTORES EN ARQUITECTURA" ↔ destino "RICARDO MORALES 3369 SAN MIGUEL SAN MIGUEL") y **464746** (obra "EMPRESA CONSTRUCTORA MENA Y" ↔ destino "CAM. EL NOVICIADO LAMPA LAMPA"). Revisión de Atlas pasó de 2 a 0 pendientes, como reportó Javier.
- **Verificado técnicamente, no sólo visualmente:** `decisiones_pendientes.json` real tiene 0 pendientes; `decisiones_aplicadas.json` tiene exactamente una aplicación `DESTINO_SIN_CONFIRMAR`/`CONFIRMAR` por cada guía, actor `JAVIER_DESKTOP`, sin duplicados (10 aplicaciones totales en el ledger, todas con `decision_id` distinto). Ambas relaciones obra↔destino quedaron `CONFIRMADA`, con evidencia humana auditable (`CONFIRMACION_HUMANA`), y ambas obras pasaron a `CONFIRMADA`. Ningún destino ni obra se duplicó.
- **Revalidación automática funcionó exactamente como diseñó R3.4.2:** ambas filas del dataset real pasaron a `estado_procesamiento=OK`, `indicador_revision=OK`, `motivos_revision_documento` vacío -- `OBRA_DESTINO_SIN_CORROBORAR` desapareció de las dos. Se generaron automáticamente dos reportes de revalidación nuevos (uno por cada `CONFIRMAR`); el segundo (`reporte_revalidacion_20260818_125145_074341`) quedó publicado como vigente en `estado_operacion.json`.
- **Viajes ya refleja el resultado sin intervención manual:** el reporte vigente, verificado con un dry-run independiente de regeneración (sobre TEMP, sin tocar Drive) que coincidió byte a byte, muestra **24 viajes: 22 CONFIRMADO / 2 REQUIERE_REVISION** (antes 20/4). Los 2 que quedan `REQUIERE_REVISION` son ajenos a este bloque: `0000352376` (conflicto cliente/obra ya documentado, pendiente de "consolidación inteligente de viajes") y `0000353164` (motivo documental sin relación con obra/destino).
- **Integridad verificada en dos formas:** hashes de `clientes.json`/`vehiculos.json` idénticos a antes de las aplicaciones; escaneo de `mtime` de todo el árbol de Drive confirma que sólo se tocaron los archivos esperados por el flujo (`obras_destinos.json`, `destinos_maestros.json`, `decisiones_aplicadas.json`, `decisiones_pendientes.json`, `analisis_completo_guias.csv`, `estado_operacion.json`, y dos carpetas nuevas de reportes) -- ningún catálogo de choferes/empresas/plantas/rutas/destinos/telemetría, imagen, caché ni reporte previo fue tocado.
- **Drive modificado: SÍ -- exclusivamente por las dos aplicaciones reales de Javier desde Desktop**, no por ninguna acción de este bloque (que fue enteramente de verificación read-only + un dry-run en TEMP eliminado al terminar).
- Sin cambios de código en este bloque (no hizo falta -- el comportamiento fue exactamente el diseñado en el Paso 2/Paso 3). Suite conservada: **1184 passed, 0 failed**, sin necesidad de repetirla.
- **Estado: CICLO OBRA→DESTINO VALIDADO COMPLETAMENTE -- LISTO PARA PUBLICAR.**

---

## 2026-08-18 — Bloque 3 (Desktop): Viajes deja de ocultar conflictos reales detrás de motivos documentales benignos

- **Bug real confirmado con evidencia concreta:** `renderDatosAuxiliares` en `atlas_viajes.html` decidía qué motivos mostrar con `motivosDocumentales.length ? motivosDocumentales : viaje.motivos` -- si CUALQUIER documento del viaje traía un motivo documental (incluso no bloqueante, como `MATERIAL_AUSENTE`), Desktop mostraba SÓLO ese motivo y ocultaba por completo los `CONFLICTO_*` reales de nivel viaje. Caso real: transporte `0000352376` (`CONFLICTO_CLIENTE | CONFLICTO_OBRA_DESTINO`, real, con evidencia de dos documentos del mismo transporte con cliente/obra distintos) mostraba únicamente "Material ausente" porque la guía `464699` de ese transporte trae ese motivo no bloqueante.
- **Corrección:** nueva `AtlasFormatoOperacional.motivosPresentables(motivosViaje, motivosDocumentales)` en `src/formato_operacional.js` -- unión deduplicada de ambos niveles (motivos de viaje primero), en vez de que uno reemplace al otro. Se agregaron traducciones humanas para los `CONFLICTO_*` de viaje que antes carecían de ellas (`CONFLICTO_CLIENTE`, `CONFLICTO_OBRA_DESTINO`, `CONFLICTO_CHOFER`, `CONFLICTO_RUT_CHOFER`, `CONFLICTO_FECHA`, `CONFLICTO_ORIGEN`).
- **13 tests nuevos** (`test/viajes_motivos_reales.test.js`, casos 1-8 más extras y regresión de wiring HTML). `npm test` completo: **199 passed, 0 failed** (baseline 186 + 13).
- **Validación real read-only** contra los datos reales del reporte vigente (sin escribir Drive): `0000352376` pasa de mostrar sólo "Material ausente" a mostrar "Cliente en conflicto", "Obra o destino en conflicto" y "Material ausente"; `0000353164` pasa de mostrar sólo "Cliente ausente" a mostrar "Documento requiere revisión" y "Cliente ausente" juntos.
- **Validación visual real de Javier, confirmada:** en Atlas Viajes DESARROLLO, el transporte `0000352376` muestra los tres motivos esperados y los conflictos reales ya no quedan ocultos; el transporte `0000353164` muestra los dos motivos esperados. Resultado visual aprobado.
- **Drive no fue modificado en ningún momento de este bloque** (sólo lecturas de verificación read-only, con un volcado temporal fuera de Drive eliminado al terminar).
- Motor sin cambios de código -- el bug y el fix eran exclusivamente de Desktop.
- **Estado: BLOQUE 3 VALIDADO VISUALMENTE -- LISTO PARA PUBLICAR.**

---

## 2026-08-18 — Bloque post-lote: dos falsos OK corregidos (`obra_destino` sin corroborar) -- lote controlado de 15 guías

- **Lote controlado ejecutado:** 15 guías nuevas procesadas y congeladas ANTES de auditoría manual, en `operacion/procesamiento/lote_controlado_15_guias_20260818_100841/` (predicción congelada + manifiesto SHA-256, verificado íntegro al inicio y al final de este bloque). **No promovido a `operacion/actual`; ninguna de las 15 decisiones del lote fue aplicada.**
- **Hallazgo de la auditoría de Javier: 2 falsos `OK`.** `464395` y `464479` quedaron `indicador_revision=OK` aunque Atlas nunca corroboró su `obra_destino` contra el catálogo real -- rompiendo el principio central: si Atlas necesita una decisión humana para corroborar una entidad relevante, el documento no puede presentarse como completamente `OK`.
- **Causa raíz única, común a ambos casos** (confirmada reproduciendo primero en fixtures, con los mismos valores de extracción exactos que dejó el OCR real, antes de tocar código): el bloque "OPERACION REAL R2" de `procesar_archivo` sí consulta la fuente de verdad real (`obras_destinos.json`, vía `_corroborar_obra_destino_confirmada`) para una `obra_destino` leída limpiamente -- pero sólo usaba la respuesta POSITIVA (retirar sospecha). Una respuesta negativa (obra no confirmada) no tenía ningún efecto, porque el campo nunca había entrado al mecanismo de sospecha (`campos_geometricos_sin_corroborar`) por ninguna otra vía cuando la lectura fue limpia. `detectar_decisiones_documento` sí evaluaba el catálogo correctamente y de forma independiente -- generó `OBRA_DESCONOCIDA` para `464395` (obra distinta del cliente) y correctamente NO generó nada para `464479` (regla de Javier R3.2: `obra_destino` idéntica al cliente ya reconocido, "mismo hecho dos veces, no dos entidades") -- pero ninguna de las dos rutas estaba acoplada a `indicador_revision`, que se calcula ANTES de invocar `detectar_decisiones_documento` por diseño. El fix no podía ser "¿hay una decisión pendiente? → REVISAR" (acoplamiento circular) -- se corrigió la evaluación de corroboración de `obra_destino` en sí misma.
- **Fix (un solo bloque, aditivo, en `atlas_core/procesamiento_masivo.py`):** cuando la obra no queda confirmada por el catálogo real Y el cliente documental sí resuelve a una identidad maestra concreta en `clientes.json` (mismo criterio de "cliente resoluble" que ya usa `detectar_decisiones_documento` para decidir si corresponde preguntar por la obra), se marca `obra destino` como pendiente de corroborar, reutilizando el motivo canónico ya existente `OBRA_DESTINO_SIN_CORROBORAR` -- sin taxonomía nueva. Si el cliente no resuelve, se preserva la abstención conservadora ya existente (no hay base para juzgar la obra). La regla R3.2 (`decisiones_pendientes.py`) queda intacta, sin tocar.
- **7 tests nuevos** (`tests/test_falso_ok_obra_destino_p1.py`): equivalente funcional de 464395, equivalente funcional de 464479 (causa distinta documentada -- sin decisión redundante), obra conocida confirmada (sigue OK), obra nueva genérica (motivo + decisión coherentes), destino pendiente (R3.4, sigue generando `DESTINO_SIN_CONFIRMAR`, ahora también pide revisión), cliente no resoluble (se abstiene, sin motivo inventado), idempotencia + no duplicados + motivos independientes preservados. Suite completa: **1191 passed, 0 failed** (baseline 1184 + 7, sin cambios de código durante el lote).
- **Reevaluación read-only del lote congelado, sin reprocesar OCR ni imágenes:** se reconstruyeron los mismos valores exactos de `cliente`/`obra_destino`/RUT que ya dejó el OCR real (verificados contra `PREDICCION_CONGELADA_analisis_completo_guias.csv`, SHA-256 idéntico antes y después de todo el bloque) y se corrió únicamente la lógica corregida contra copias efímeras en TEMP de los catálogos reales (`catalogos_privados/`, sólo lectura).
  - **464395:** antes `OK` / sin motivo / decisión `OBRA_DESCONOCIDA` generada pero sin efecto → después `REVISAR` / `OBRA_DESTINO_SIN_CORROBORAR` / misma decisión `OBRA_DESCONOCIDA`, ahora coherente. Extracción sin cambio.
  - **464479:** antes `OK` / sin motivo / sin decisión → después `REVISAR` / `OBRA_DESTINO_SIN_CORROBORAR` / sin decisión (R3.2 preservado). Extracción sin cambio.
  - **Controles (no debían cambiar y no cambiaron):** `464511`/`464892` (obra "ARMACERO MATCO SA") y `464781` (obra "CONSTRUCTORA IGNACIO HURTADO") -- ambas con relación `CONFIRMADA` real en `obras_destinos.json` -- siguen `OK`, sin motivo, con método `CATALOGO_OBRA_DESTINO` presente.
- **Drive:** predicción congelada, manifiesto, imágenes del lote, `operacion/actual` y catálogos reales -- **ninguno modificado en ningún momento** (sólo lecturas; SHA-256 de la predicción congelada verificado idéntico al cierre).
- **Git:** Motor sin commit ni push -- `atlas_core/procesamiento_masivo.py` modificado (+22 líneas), `tests/test_falso_ok_obra_destino_p1.py` nuevo, más estas tres bitácoras. `git diff --check` limpio. Desktop sin cambios, HEAD `fba95ac` intacto.
- No se tocó OCR, ni los errores `464265`/`464367`, ni el catálogo YOLITO/TOLITO, ni consolidación, ni Desktop, ni Multiempresa, ni Mobile -- fuera de alcance explícito de este bloque.
- **Estado: LISTO PARA VALIDACIÓN REAL SOBRE LOTE CONGELADO.**

---

## 2026-08-18 — Validación real del fix sobre el lote congelado: 464395/464479 reprocesadas con OCR real -- 2 falsos OK confirmados en 0

- **Reprocesamiento real, no simulado:** se copiaron las imágenes canónicas del lote (`operacion/entradas/lote_controlado_15_guias_20260818_100841/464395.jpeg` y `464479.jpeg`, verificadas SHA-256 idénticas al manifiesto del lote) a una carpeta TEMP fuera de Drive, y se ejecutó el CLI real del Motor (`analizar_guias_masivo.py`, PaddleOCR/GPU) con el fix ya aplicado, contra una copia efímera de `catalogos_privados/` -- salida exclusivamente en TEMP, eliminada al terminar.
- **Extracción idéntica campo a campo** (los 11 campos documentales: guía, transporte, fecha, chofer, RUT chofer, cliente, obra_destino, ambas patentes, descripción, tipo de carga) entre la predicción congelada original y esta nueva corrida con OCR real -- **cero diferencias**, confirmado programáticamente. El fix nunca toca extracción.
- **Único cambio real, en ambas guías:** `indicador_revision` `OK`→`REVISAR`, con motivo nuevo `OBRA_DESTINO_SIN_CORROBORAR`. `464395` conserva su decisión `OBRA_DESCONOCIDA`/`OBRA_NO_EXISTE_PARA_CLIENTE` (ahora coherente con el estado del documento); `464479` sigue sin generar ninguna decisión (0 decisiones en el `decisiones_pendientes.json` de esta corrida) -- R3.2 se preserva exactamente como se diseñó.
- **Validado contra la guía física, no sólo contra el dato extraído:** en ambas imágenes reales, "OBRA DESTINO" impreso coincide EXACTAMENTE con lo extraído ("ING Y METALURGICA INGEMETA" en 464395; "AMERICAN SCREW CHILE SPA" en 464479, idéntico al "SEÑOR(ES)" del mismo documento). Ninguna de las dos obras existe como obra confirmada en `catalogos_privados/obras_destinos.json` real -- `REVISAR` es correcto en ambos casos, no es un falso `REVISAR`.
- **Controles read-only, sin OCR** (mismos catálogos reales, sólo lectura): `464511`/`464892` (obra "ARMACERO MATCO SA") y `464781` (obra "CONSTRUCTORA IGNACIO HURTADO") -- ambas con relación `CONFIRMADA` real -- siguen `OK`, sin motivo nuevo, con método `CATALOGO_OBRA_DESTINO` presente. Sin cambio.
- **Métricas del lote (15 guías), recalculadas conceptualmente sin tocar la predicción congelada:** ANTES -- 5 `OK` (3 correctos + **2 falsos OK**), 10 `REVISAR`. DESPUÉS -- 3 `OK` (todos correctos, verificados), 12 `REVISAR` (10 previos, sin cambio, + los 2 corregidos). **Falsos OK: 2 → 0. Falsos REVISAR: 0** (ninguno detectado; ambas transiciones a `REVISAR` están justificadas contra la guía física y el catálogo real).
- **Hueco funcional identificado (no resuelto en este bloque, sólo documentado):** `464479` queda `REVISAR` con motivo `OBRA_DESTINO_SIN_CORROBORAR`, pero sin generar ninguna decisión pendiente -- y "Revisión de Atlas" (Desktop, `decisiones_pendientes_ui.js`) sólo renderiza tarjetas a partir de `decisiones_pendientes.json`; con el arreglo `contenedor.hidden = !decisiones.length` no aparece ninguna tarjeta cuando el arreglo está vacío (confirmado leyendo el código, sin modificarlo). Javier vería el documento `REVISAR` en el dataset/viajes, pero no tendría ninguna tarjeta accionable en Revisión de Atlas para resolverlo -- mismo patrón de "REVISAR sin vía de decisión humana" ya cerrado en bloques anteriores (R3.4.2/R3.4.3) para el ciclo obra→destino, ahora aplicado al caso "obra == cliente ya reconocido". **No se diseñó solución -- queda para un bloque futuro si se autoriza.**
- **Drive:** predicción congelada (SHA-256 verificado `OK` al cierre), manifiesto, imágenes canónicas, `operacion/actual` y catálogos reales -- **ninguno modificado**. Carpeta TEMP de esta validación eliminada al terminar, sin dejar carpetas nuevas permanentes.
- **Tests:** sin cambios de código en este bloque -- se conserva **1191 passed, 0 failed** sin necesidad de repetir la suite.
- **Git:** Motor sin cambios adicionales de código (sólo estas tres bitácoras); el diff pendiente sigue siendo el mismo del bloque anterior (`atlas_core/procesamiento_masivo.py` + `tests/test_falso_ok_obra_destino_p1.py`). **Sin commit ni push.** Desktop sin cambios, HEAD `fba95ac` intacto.
- No se tocó OCR (más allá de ejecutarlo, sin modificarlo), ni `464265`/`464367`, ni catálogo YOLITO/TOLITO, ni consolidación, ni Mobile, ni Multiempresa. No se aplicó ninguna decisión ni se promovió el lote.
- **Estado: FIX FALSOS OK VALIDADO REALMENTE -- LISTO PARA PUBLICAR.**

---

## 2026-08-18 — Publicación del fix (`793b240`) y promoción del lote de 15 guías a operación vigente

- **Motor publicado:** commit `793b240` ("fix: marcar obras no corroboradas para revision") empujado a `origin/lector-mvp-guia-nueva` -- local=remoto 0/0, working tree limpio.
- **Promoción del lote:** las 15 guías del lote controlado se incorporaron a `operacion/actual` **junto** a los 28 documentos previos -- **43 documentos totales, sin pérdidas ni duplicados** (verificado por `numero_guia` y por `archivo` antes de escribir). Mecanismo canónico: se reprocesaron las 15 imágenes con el Motor ya corregido (`procesar_carpeta`/`generar_artefacto`, con telemetría real) contra una copia efímera de catálogos en TEMP, validado en dry-run, y sólo entonces el resultado ya-canónico se trasladó a `operacion/actual` (sin edición manual de CSV/JSON). Backup previo verificado byte a byte en `respaldos/PROMOCION_LOTE15_ROLLBACK_PRE_APLICACION_20260818_153220/`.
- **Resultado:** **43 documentos (30 OK / 13 REVISAR)**, **38 viajes (25 CONFIRMADO / 13 REQUIERE_REVISION)**, **15 decisiones pendientes** (8 `VEHICULO_DESCONOCIDO` + 7 `OBRA_DESCONOCIDA`) publicadas en `decisiones_pendientes.json`, ninguna aplicada. El conflicto real `464264`+`464265` (mismo viaje, patentes distintas) sigue visible sin resolver automáticamente. Catálogos, predicción congelada, procesamiento original e imágenes de entrada -- intactos.
- **Estado: LOTE DE 15 PROMOVIDO -- LISTO PARA VALIDACIÓN VISUAL DE JAVIER.**

---

## 2026-08-18 — Validación visual de Javier: 2 hallazgos de patente + diagnóstico dirigido de 464367

- **Auditoría exhaustiva de patentes de las 15 guías** (ground truth desde la imagen, nunca desde catálogo/CSV): **23/25 patentes documentales coinciden exactamente con lo que extrajo Atlas** (14/15 tracto, 9/10 rampla) -- **precisión 92%**. Un único error real de extracción (`464367`, ver abajo). El resto de discrepancias observadas no son de lectura de Atlas.
- **Evidencia operacional confirmada por Javier (registrada, no aplicada a ningún catálogo):**
  - **Patrick Ortiz** (guía `464036`): patente canónica real **XF3629**; **XF3662** es la que está impresa en la guía -- confirmado como error de la documentación de AZA, no de Atlas (Atlas leyó XF3662 correctamente). No se registra XF3662 como vehículo canónico.
  - **Carlos Simón** (guías `464264`/`464265`, mismo viaje/transporte con patentes distintas entre sí): tracto canónico confirmado **VP8521** (coincide con `464264`, ya conocido en catálogo); **VP6521** (de `464265`) **no debe registrarse**. Rampla **todavía sin confirmar** -- Javier recuerda `JE8659`/`JE8650`, ninguno coincide literalmente con lo auditado en las guías (`JD6659`/`JD0659`) -- no se elige ninguna hasta nueva confirmación.
- **Diagnóstico dirigido de `464367`** (único error real de Atlas): OCR bruto (PaddleOCR) sí capturó el texto -- `': T2MN86 CARBO:J35478'` -- pero la etiqueta `CARRO` salió corrompida como `CARBO` (R leída B). El mecanismo de extracción geométrica quedó con dos tokens de 6 caracteres válidos como patente en el mismo bloque, sin poder separar cuál era cuál, y se abstuvo (diseño correcto y deliberado: nunca adivinar por posición) -- perdiendo tracto y rampla juntos. Comparación con control real `464511` (estructura de bloque IDÉNTICA, pero `CARRO` bien leído) aisló la causa con precisión.
- **Concepto de producto identificado, registrado para roadmap, NO implementado:** Atlas necesitará, más adelante, un módulo genérico de **INCIDENCIAS DOCUMENTALES** (no "errores AZA" -- válido para cualquier emisor/mandante futuro) que distinga patente documental / patente canónica / incidencia confirmada humanamente. No se diseña ni se implementa en este bloque.
- **Estado: DIAGNÓSTICO COMPLETADO -- REQUIERE DECISIÓN** (sobre si corregir la extracción de `464367`).

---

## 2026-08-18 — Fix conservador de extracción de patentes: `CARRO` leído `CARBO` (guía real 464367)

- **Causa raíz ya confirmada** en el bloque de diagnóstico anterior: `_valor_unico_residual` (extractor de patentes por geometría) sólo reconoce el par fusionado "CARRO:valor" dentro de un bloque OCR si la palabra `CARRO` aparece literalmente (con la única tolerancia previa 0↔O, ya usada para la guía real 464631). Cuando el OCR corrompe `CARRO`→`CARBO` (B por R, guía 464367), la función no logra separar el par y quedan dos candidatos de patente ambiguos en el mismo bloque -- se abstiene, perdiendo tracto y rampla juntos, aunque la asociación geométrica a la etiqueta `PATENTE` ya había funcionado bien.
- **Fix mínimo y conservador:** se generalizó la tolerancia existente (antes sólo 0↔O) a una **tabla explícita y pequeña de confusiones de OCR ya confirmadas con guías reales** (`_CONFUSIONES_OCR_ETIQUETA_VEHICULAR = {"0": "O", "B": "R"}`), usada únicamente para decidir si un token ES una etiqueta vehicular conocida (`PATENTE`/`TRACTO`/`CARRO`/`RAMPLA`/`REMOLQUE`) -- nunca para interpretar el valor de una patente, nunca una distancia de edición abierta. Ninguna de las 5 etiquetas contiene "0" ni "B", así que la sustitución sólo puede habilitar coincidencias nuevas, nunca romper una ya correcta. El texto residual devuelto siempre proviene del texto ORIGINAL sin sustituir -- un valor documental que legítimamente contenga "B" (p. ej. `BPHR67`) nunca se corrompe.
- **6 tests nuevos** en `tests/test_patentes_p4.py`: reproducción sintética de la estructura real de 464367 (unitaria + end-to-end vía `procesar_archivo`), y 4 negativos explícitos -- palabra parecida mas NO tolerada (`CARGO`) sigue en abstención, dos patentes sin ninguna etiqueta reconocible se abstiene, ambigüedad geométrica genuina preexistente se preserva, valor documental con "B" legítimo (`BPHR67`) no se corrompe con `CARRO` bien escrito. Suite completa: **1197 passed, 0 failed** (baseline 1191 + 6).
- **Validado con OCR real, aislado en TEMP, contra la imagen canónica de 464367** (sin tocar `operacion/actual` ni catálogos reales): `patente_tracto`/`patente_rampla` pasan de `"No encontrado"` a un valor documental real (`T2MN86`/`J35478`) -- el resto de los campos permanece exactamente igual. Como ninguno de los dos existe en el catálogo real, generan `VEHICULO_DESCONOCIDO`/`PATENTE_SIN_HOMOLOGAR`, el mismo patrón honesto que las demás decisiones ya auditadas del lote -- ya no queda un campo invisible.
- **Límite explícito, no resuelto en este bloque:** el fix corrige la etapa de EXTRACCIÓN (el campo ya no se pierde) -- no corrige el ruido de OCR dentro del propio VALOR (`T2MN86`/`J35478` siguen siendo distintos de la lectura visual `TZWR86`/`JU5478`). Corregir eso sería un problema distinto (calidad de OCR carácter a carácter), fuera de alcance de este bloque -- Atlas ahora al menos deja el campo visible y accionable en vez de invisible.
- **Drive/catálogos/Desktop:** sin cambios. Sólo `atlas_core/extractor.py` y `tests/test_patentes_p4.py` modificados en el working tree del Motor. **Sin commit, sin push.**
- **Estado: FIX VALIDADO -- LISTO PARA REVISIÓN CON JAVIER.**

---

## 2026-08-18 — 464367: el ruido de OCR a nivel de carácter NO es recuperable con seguridad -- comportamiento correcto confirmado, sin cambios de código

- **Trazado completo, sin modificar nada:** `T2MN86` (tracto documental recuperado) vs `TZWR86` (vehículo canónico ya confirmado en catálogo) difieren en **3 posiciones** (`2/Z`, `M/W`, `N/R`) -- muy por encima de la única regla segura que ya usa Atlas para homologar OCR (`_diferencia_ocr_segura`: exactamente 1 posición distinta, y sólo si ese par de caracteres está en una tabla pequeña ya vetada: B/D, 0/O, 1/I, 5/S, 8/B, 8/E, K/R). `J35478` (rampla documental) vs `JU5478` (lo que Javier/la auditoría visual creen que dice la guía) difiere en **una sola posición** (`3/U`), pero ese par **no** está en la tabla vetada -- y además `JU5478` **no existe** como vehículo confirmado en el catálogo real, así que no hay ni siquiera un candidato contra el cual aplicar la regla.
- **Por qué `SD6486→SB6486` sí funciona y esto no:** ese caso cumple los tres requisitos a la vez (1 sola posición distinta, el par `B/D` sí está vetado, y `SB6486` ya existe confirmado en catálogo) -- 464367 no cumple ninguno de los tres para el tracto, y sólo cumple parcialmente (posición única, pero par no vetado y sin candidato) para la rampla.
- **Clasificación:** tracto `T2MN86` y rampla `J35478` -- **ambos categoría C: NO_RECUPERABLE_CON_SEGURIDAD.** No existe hoy una corrección automática pequeña, generalizable y demostrable -- forzar una implicaría o bien una distancia de edición abierta, o bien usar la asociación histórica chofer↔vehículo como autocorrección, ambas explícitamente prohibidas para este bloque.
- **No se implementó ningún cambio de código.** El comportamiento actual (conservar el valor documental leído, generar `PATENTE_SIN_HOMOLOGAR` + decisión `VEHICULO_DESCONOCIDO`, sin inventar ni forzar una patente) ya es el comportamiento seguro correcto -- se confirma, no se modifica.
- **Diseño de producto futuro, documentado en detalle en la bitácora técnica y en HANDOFF -- NO implementado en este bloque ni en ninguno anterior:** separar patente documental / vehículo canónico operacional / asociación histórica chofer↔vehículo (nunca chofer→un único vehículo; sólo evidencia para sugerir, nunca autocorrección) / incidencias documentales genéricas (no "errores AZA" -- válido para cualquier emisor futuro, incluye el caso ya observado por Javier de guías MBT con otra empresa transportista documental incorrecta, p. ej. Transportes Carwork en vez de Transportes MBT).
- **Drive:** no modificado. **Desktop:** no modificado. **Git:** working tree sin cambios adicionales a los del bloque anterior (mismo diff: `atlas_core/extractor.py`, `tests/test_patentes_p4.py`, tres bitácoras). Sin commit, sin push.
- **Estado: 464367 REQUIERE CONFIRMACIÓN HUMANA -- COMPORTAMIENTO SEGURO VALIDADO.**

---

## 2026-08-18 — Publicado el fix estructural de patentes (`b86e280`) -- checkpoint limpio

- **Commit `b86e280`** ("fix: tolerar ruido OCR en etiquetas vehiculares") publicado en `origin/lector-mvp-guia-nueva`. Verificado local=remoto, 0/0, working tree limpio. Diff revisado completo antes de commitear: exactamente los 5 archivos esperados, sin hardcode de guía/patente/chofer, tabla de confusiones limitada a `0→O`/`B→R`, abstención ante ambigüedad intacta.
- **Confirmado para continuidad:** el fallo estructural `CARRO→CARBO` queda corregido y publicado; `464367` sigue requiriendo resolución humana de sus dos patentes (`T2MN86`/`J35478` no homologables con seguridad; evidencia visual real es `TZWR86`/`JU5478`); no se forzó ninguna autocorrección; el siguiente bloque no es Incidencias Documentales -- seguimos cerrando hallazgos reales de lectura/extracción del lote de 15; el diseño futuro (patente documental/canónica, asociación histórica chofer↔vehículo, Incidencias Documentales) queda registrado, no implementado.
- **Nueva decisión de producto registrada (pendiente de roadmap, no auditada aquí):** **kilometraje operacional** es un dato obligatorio de Atlas (no opcional); ORS/Onelogis son las fuentes actuales; si su cobertura no permite obtenerlo de forma fiable para todos los viajes aplicables, deberá auditarse una alternativa -- sin auditar ni implementar en este bloque.
- **Drive/Desktop:** sin cambios.
- **Estado: CHECKPOINT LIMPIO -- FIX ESTRUCTURAL DE PATENTES PUBLICADO -- LISTO PARA CONTINUAR AUDITORÍA DEL LOTE 15.**

---

## 2026-08-18 — Diagnóstico dirigido de `464265` (control `464264`) -- fix puntual de material validado

- **Alcance:** sólo los errores reales de lectura/extracción de `464265` (fecha, cliente, obra/destino, material, tipo de carga) -- las patentes quedan explícitamente fuera de este bloque (ver checkpoint anterior: tracto canónico Carlos Simón `VP8521` confirmado, `VP6521` no se registra, rampla todavía sin confirmar).
- **Ground truth leído directamente de las imágenes canónicas** (nunca del CSV ni del catálogo), con recortes ampliados para las zonas dudosas. `464264` y `464265` son el mismo viaje (transporte `0000351135`, chofer Carlos Simón) con guías consecutivas de Sodimac SA → obra "SODIMAC SA CORONEL".
- **Cuatro causas independientes identificadas, cada una con su propia evidencia -- no comparten una sola causa:**
  1. **FECHA (`05-08-2024` en vez de `05-08-2026`):** el OCR bruto realmente leyó "2024" (confianza 0,80) sobre una mancha física real que cubre justo esos dígitos en el papel de `464265`. Como "2024" es una fecha calendario válida y cae dentro de la ventana de plausibilidad (2015-2035), `extraer_fecha` la aceptó sin más. El mecanismo de seguridad que sí existe (relectura focal con doble confirmación) sólo se activa cuando el campo queda "No encontrado" -- nunca cuando hay una lectura plausible pero equivocada. **No se corrigió**: ampliar ese mecanismo de seguridad es un cambio de diseño más amplio (cuándo confiar en una sola lectura OCR), no una corrección puntual segura.
  2. **CLIENTE (`No encontrado`):** el recuadro OCR exacto donde debería estar "SODIMAC SA" volvió vacío (confianza 0). Con zoom se confirma que el texto sí está impreso -- la sombra de la misma mancha física reduce el contraste lo suficiente para que el detector no proponga ninguna caja ahí. El RUT tampoco sirve de respaldo: también salió mal leído y no pasa la validación. **Comportamiento de Atlas correcto** (se abstuvo en vez de inventar); no hay corrección de código segura para una detección que nunca ocurrió.
  3. **OBRA_DESTINO (`SODIMAC SA COROBEL` en vez de `CORONEL`):** la geometría acertó la zona y el texto completo; el único error es un carácter (`N`→`B`) dentro de la palabra "CORONEL". Atlas ya se abstuvo de corroborarlo contra catálogo (`OBRA_DESTINO_SIN_CORROBORAR`) en vez de adivinar -- comportamiento correcto, sin fuzzy abierto. **No se corrigió.**
  4. **MATERIAL (vacío):** el OCR leyó la palabra clave "HORMIGON" como "BORHIGON" (dos letras confundidas), y el filtro exigía la palabra exacta -- la única línea de material de `464265` se descartaba entera. **Mismo patrón, ya presente en el control `464264`**: su segunda línea de material ("HOMMIGON" en vez de "HORMIGON") se pierde de la misma forma, silenciosamente, en el dato ya promovido a `operacion/actual`.
- **Comparación 464264 vs 464265:** confirma que no es "un documento que falla y otro que funciona" -- ambos comparten el mismo defecto de material (uno pierde 1 de 2 líneas, el otro su única línea), y además 464264 tiene su propio problema distinto y no relacionado en `obra_destino` (el valor guardado es literalmente "COMUNA", la etiqueta de un campo vecino) -- **hallazgo nuevo, registrado aquí, explícitamente fuera de alcance de este bloque** por ser una causa distinta que merece su propia auditoría dedicada.
- **Fix implementado (el único de este bloque, el de mayor impacto y menor riesgo):** una tabla pequeña y acotada de tres confusiones de OCR ya confirmadas con estas dos guías reales (mismo patrón que la tabla ya existente para etiquetas vehiculares) permite reconocer "HORMIGON" en una línea de material aunque el OCR la haya escrito "BORHIGON" o "HOMMIGON" -- nunca reescribe el texto guardado, sólo decide si la línea se conserva. `tipo_carga` sigue "NO DETERMINADO" en ambas guías después del fix (el clasificador de tipo de carga no se tocó -- queda como límite explícito, no como bug nuevo).
- **4 tests nuevos** (`tests/test_procesamiento_masivo.py`): reproducción real de ambas guías (positivos) y 3 negativos (más de dos diferencias, par de caracteres no vetado, y confirmación de que el resto de palabras clave y el texto ajeno no se ven afectados). Suite completa: **1201 passed, 0 failed** (baseline 1197 + 4).
- **Validado con OCR real en TEMP sobre las imágenes canónicas de `464264` y `464265`:** comparación campo a campo antes/después -- el único cambio en `464265` es `descripcion_material` (ahora recupera el texto real en vez de vacío) y la caída de `MATERIAL_AUSENTE` de `motivos_revision_documento`; el único cambio en `464264` es que `descripcion_material` ahora trae sus dos líneas en vez de una. Ningún otro campo se movió en ninguna de las dos guías -- sin regresiones colaterales.
- **Drive:** no modificado -- validación 100% en TEMP (imágenes y catálogos copiados desde Drive read-only, verificados SHA-256 idénticos al manifiesto), TEMP eliminado al terminar. `operacion/actual` sigue con los valores originales de ambas guías -- este fix **no se aplicó todavía al lote real**.
- **Git:** Motor con `atlas_core/procesamiento_masivo.py` y `tests/test_procesamiento_masivo.py` modificados, más estas tres bitácoras. **Sin commit, sin push.** Desktop sin cambios, HEAD `fba95ac`.
- **Qué debe decidir Javier ahora:** si aprueba este fix y autoriza reprocesar `464264`/`464265` (o el lote completo) para que `operacion/actual` refleje las líneas de material recuperadas; si el hallazgo nuevo de `464264` (`obra_destino` = "COMUNA") amerita un bloque de diagnóstico propio; qué hacer con fecha/cliente de `464265` (ambos quedan honestamente marcados para revisión humana, sin corrección automática posible con seguridad hoy).
- No se tocó Desktop, catálogos, decisiones, patentes, Mobile ni Multiempresa. No se aplicó ninguna decisión del lote ni se promovió nada.
- **Estado: FIX PUNTUAL 464265 VALIDADO -- LISTO PARA REVISIÓN CON JAVIER.**

---

## 2026-08-18 — Nueva evidencia humana: rampla canónica de Carlos Simón confirmada

- **Confirmación operacional directa de Javier**, registrada aquí sin aplicar a ningún catálogo: para el chofer **Carlos Simón**, el vehículo canónico/real es **tracto `VP8521`** (ya confirmado en el checkpoint anterior) + **rampla `JD8659`** (nueva, antes sin confirmar).
- **`VP6521` y `JD0659` (patentes documentales de `464265`) NO deben registrarse como canónicas.** Tampoco `JD6659` (documental de `464264`) como rampla canónica -- queda reemplazada por la confirmación de Javier.
- **Documental vs. canónico se mantienen separados, sin autocorrección:** los valores documentales originales de `464264` (`VP8521`/`JD6659`) y `464265` (`VP6521`/`JD0659`) -- tal como Atlas los extrajo de cada guía -- **no se modifican silenciosamente**. Esta confirmación queda como evidencia para el futuro diseño de Incidencias Documentales / sugerencia humana (patente documental vs. vehículo canónico), **no implementado todavía**.
- **Sin cambios de catálogo, sin aplicación de decisiones, sin cambios de código en este addendum** -- sólo registro de la evidencia. El objetivo del bloque de diagnóstico de `464265` no cambia.
- **Estado: EVIDENCIA REGISTRADA -- CATÁLOGO SIN MODIFICAR, PENDIENTE DE APLICACIÓN FORMAL.**

---

## 2026-08-18 — Diagnóstico dirigido de `obra_destino` en `464264` -- fix validado

- **Objetivo único de este bloque:** `464264` guardaba `obra_destino = "COMUNA"` -- la etiqueta de un campo vecino -- en vez del valor real (`SODIMAC SA CORONEL`), que el OCR sí había leído correctamente. Se aisló la causa exacta y, al ser una corrección pequeña y segura, se implementó.
- **Causa raíz encontrada con evidencia directa (trazado imagen → OCR → extracción → valor final):** Atlas primero intenta capturar `obra_destino` con un patrón de texto que busca lo que hay escrito entre las etiquetas "OBRA DESTINO" y "COD DESTINATARIO". El problema es el **orden en que el OCR entrega el texto**: en esta guía en particular, entre esas dos etiquetas (que están en la columna derecha del documento) se coló -- en el orden de lectura -- la etiqueta "COMUNA" de la columna izquierda, cuya fila cae casi a la misma altura. El patrón de texto capturó esa etiqueta suelta en vez del valor real, que en el orden de lectura apareció recién después. **El valor correcto sí existía** -- de hecho, el mecanismo de respaldo por geometría (posición real en la imagen, no orden de lectura) lo identifica sin ambigüedad como el candidato claramente mejor -- pero nunca llegó a usarse porque el primer mecanismo ya había entregado (mal) una respuesta.
- **Comparación con 3 controles del mismo lote donde `obra_destino` funciona bien** (`464511`, `464892`, `464781`, mismo layout AZA): en los tres, el patrón de texto simplemente **no encuentra nada** entre "OBRA DESTINO" y "COD DESTINATARIO" (hay más de una línea de por medio, o ninguna) -- y por eso el mecanismo de respaldo por geometría entra a resolverlo correctamente, como estaba diseñado. `464264` es el único caso, de los 15 de este lote, donde la interferencia cae exactamente en el punto que produce una captura incorrecta en vez de "sin encontrar nada".
- **Fix implementado (mínimo, sin lista nueva):** se reutilizó una lista ya existente en el código -- la misma que usa el mecanismo de respaldo por geometría para reconocer etiquetas estructurales del documento (COMUNA, CIUDAD, DIRECCION, GIRO, RUT, TOTAL, etc.) -- para que el patrón de texto rechace una captura que sea, ella misma, una de esas etiquetas. Al rechazarla, el mecanismo de respaldo por geometría queda libre de resolverlo bien, tal como ya hace en los tres controles. Coincidencia exacta tras normalizar, nunca por parecido ni por contener la palabra -- un nombre real de obra/destino que solo contenga una de esas palabras (p. ej. "TOTAL") sigue funcionando normalmente.
- **9 tests nuevos** (`tests/test_extraer_datos.py`): reproducción exacta del patrón real de `464264`; una versión generalizada con las 6 etiquetas más relevantes de la lista; confirmación de que el camino que ya funcionaba sigue igual; y un negativo explícito de que un nombre real que contiene una de esas palabras no se pierde. Suite completa: **1210 passed, 0 failed** (baseline 1201 + 9).
- **Validado con OCR real en TEMP** sobre `464264` + 4 controles (`464265`, `464511`, `464781`, `464892`): `464264` pasa de `obra_destino = "COMUNA"` a `obra_destino = "SODIMAC SA CORONEL"` (el valor documental correcto, exactamente lo que dice la guía) -- gana honestamente la señal `OBRA_DESTINO_SIN_CORROBORAR` porque esa obra todavía no está confirmada en el catálogo real (mismo patrón que el resto del lote). **Ningún otro campo cambió en ninguna de las 5 guías** -- los 3 controles y `464265` quedan exactamente iguales. El fix de material del bloque anterior sigue intacto (`464264` conserva sus 2 líneas, `464265` su línea recuperada).
- **Drive:** no modificado -- validación 100% en TEMP (copias verificadas por SHA-256, eliminadas al terminar). `operacion/actual` sigue con `464264` en `"COMUNA"` -- el fix **no se aplicó todavía al lote real**.
- **Git:** Motor con `atlas_core/extractor.py` y `tests/test_extraer_datos.py` modificados (además de lo ya pendiente del bloque de material), más estas tres bitácoras. **Sin commit, sin push.** Desktop sin cambios, HEAD `fba95ac`.
- **Evidencia Carlos Simón, vigente sin cambios:** tracto canónico `VP8521`, rampla canónica `JD8659`; `VP6521`/`JD0659` no se registran; discrepancias documentales intactas.
- **Qué debe decidir Javier ahora:** si aprueba este fix y autoriza reprocesar `464264` (o el lote completo) para que `operacion/actual` refleje el valor real de obra_destino; y si autoriza publicar (commit + push) el conjunto de fixes ya validados de este bloque de auditoría (material + obra_destino).
- No se tocó Desktop, catálogos, decisiones, patentes, fecha, cliente, Mobile ni Multiempresa. No se aplicó ninguna decisión del lote ni se promovió nada.
- **Estado: FIX OBRA_DESTINO 464264 VALIDADO -- LISTO PARA REVISIÓN CON JAVIER.**

---

## 2026-08-18 — Publicado (`9aabce2`) + diagnóstico de fecha de `464265`: la detección ya existe, sin código nuevo

- **Publicación:** el fix de material (464264/464265) + el fix de obra_destino/COMUNA (464264) quedaron publicados en `9aabce2` sobre `origin/lector-mvp-guia-nueva`, verificado post-push local=remoto, 0/0, working tree limpio. Desktop sin cambios, HEAD `fba95ac`.
- **Objetivo de este bloque:** determinar si existe una forma general, conservadora y auditable de tratar la fecha de `464265` (Atlas produjo `05-08-2024`, sintácticamente válida pero equivocada -- el documento dice `05-08-2026`, con una mancha física real sobre esos dígitos).
- **Hallazgo central, verificado con código real y datos reales, sin escribir nada:** **esa detección ya existe hoy, en producción, y ya está disparándose para este caso exacto.** El reporte de viajes ya publicado (`reportes/reporte_promocion_lote15_20260818_153512/viajes.csv`, el vigente según `estado_operacion.json`) ya muestra el viaje de `464264`+`464265` (mismo transporte) con **`CONFLICTO_FECHA`** entre sus motivos y estado `REQUIERE_REVISION` -- Atlas ya compara las fechas de los documentos de un mismo viaje y, al no coincidir, nunca elige una en silencio: dejó la discrepancia visible para revisión humana, exactamente el comportamiento que se buscaba.
- **Por qué la fecha del documento individual `464265` sí queda mal (`05-08-2024`) sin que el propio documento lo señale:** el OCR realmente leyó "2024" (confianza 0,80) sobre la mancha física; como es una fecha calendario válida y cae dentro de la ventana amplia de plausibilidad (2015-2035), se acepta sin más. El único mecanismo de verificación adicional que existe (relectura focal con doble confirmación) sólo se activa si el campo queda "No encontrado" -- nunca ante una lectura plausible pero errónea. Esto ya se había diagnosticado en el bloque anterior de `464265`; este bloque confirma que, aunque el documento individual no lo detecta, el consolidado de viaje sí.
- **Se evaluaron y se descartaron, con evidencia, dos vías de "arreglo" que habrían sido inseguras:** (1) usar la fecha de `464264` (mismo viaje) para sustituir la de `464265` -- prohibido explícitamente, y además no hay ninguna regla estructural que garantice que dos documentos del mismo transporte comparten fecha; (2) acotar la ventana de plausibilidad al rango de fechas del lote actual -- equivale a asumir "todas las guías son de 2026", exactamente la heurística que el bloque pedía no usar.
- **Se evaluó una tercera vía -- ampliar el mecanismo de relectura focal para que también corrobore fechas ya aceptadas (no sólo las "No encontrado"), usando la confianza de OCR como disparador:** técnicamente plausible, pero requiere calibrar un umbral de confianza con más evidencia que las ~5 guías disponibles en este bloque, tiene impacto de rendimiento (relecturas OCR adicionales) a validar sobre el histórico completo, y necesitaría una señal nueva (`FECHA_SIN_CORROBORAR` o similar) nunca antes probada. **Clasificada como diseño independiente (no una corrección puntual), no implementada.**
- **Controles:** `464264` (mismo viaje, fecha correcta y consistente en OCR lineal/geométrico), `464488` y `464494` (guías no relacionadas del lote, ambas con fecha correcta y consistente). **Hallazgo adicional durante los controles, fuera de alcance de este bloque, registrado para continuidad:** `464367` (ya cerrado en un bloque anterior por su patente) tiene su propio problema de fecha, distinto al de `464265` -- el extractor lineal eligió `06-08-2026` (que en realidad es la FECHA SALIDA del documento) en vez de `04-08-2026` (la FECHA DE EMISIÓN real), porque en el orden de lectura del OCR la etiqueta "FECHA DE EMISIÓN" quedó demasiado lejos de su valor -- misma familia de causa que el bug de `obra_destino`/COMUNA ya corregido, pero no diagnosticado a fondo ni tocado en este bloque.
- **Fix implementado: NO.** No hizo falta -- el resultado que se buscaba (detectar `2024` como no confiable) ya está funcionando en producción, verificado con los datos reales ya promovidos. Implementar algo nuevo habría sido redundante y, en las variantes evaluadas, o inseguro (autocorrección) o de mayor alcance del permitido en este bloque (relectura focal ampliada).
- **Cliente de `464265`: no tocado, sigue pendiente como estaba.**
- **Drive:** no modificado -- todo el bloque fue 100% lectura (imágenes, CSV real, catálogos, el reporte de viajes ya publicado). Ningún archivo escrito en Drive.
- **Git:** sin cambios de código en este bloque -- working tree del Motor limpio (idéntico a `9aabce2`), sólo estas tres bitácoras. Sin commit, sin push.
- **Pendientes explícitos, sin iniciar:** fecha de `464265` a nivel de documento individual (queda "05-08-2024" en `analisis_completo_guias.csv`, honestamente sin corroborar, con la discrepancia ya visible a nivel de viaje); cliente de `464265`; demás hallazgos del lote de 15; diseño de relectura focal ampliada (registrado, no iniciado); fecha de `464367` (registrado, no iniciado).
- **Estado: DIAGNÓSTICO FECHA 464265 COMPLETADO -- REQUIERE DECISIÓN.**

---

## 2026-08-18 — Publicado (`d22829d`) + diagnóstico dirigido de `CLIENTE_AUSENTE` en `464265`

- **Publicación:** el diagnóstico de fecha (sin cambio de código) quedó documentado y publicado en `d22829d` sobre `origin/lector-mvp-guia-nueva` (`9aabce2..d22829d`), verificado post-push local=remoto, working tree limpio. Desktop sin cambios, HEAD `fba95ac`.
- **Objetivo de este bloque:** `464265` devuelve `cliente = "No encontrado"` aunque la inspección física confirma que el documento sí dice "SODIMAC SA" (RUT `96.792.430-K`, mismo cliente que `464264`).
- **Ground truth confirmado desde la imagen, con recortes ampliados:** nombre "SODIMAC SA" y RUT "96.792.430-K" son legibles bajo la sombra de la mancha física -- no son ilegibles para un ojo humano, sólo están degradados.
- **Causa raíz, con evidencia directa (OCR real dirigido, TEMP):** en la posición exacta donde debería estar el nombre del cliente, el motor de OCR **no generó ninguna caja de texto** -- confianza 0 (ausencia total, no una lectura de mala calidad). Se comparó directamente con `464264` (mismo cliente, mismo viaje, mismo layout): ahí el OCR sí detectó "SODIMAC SA" con buena confianza (0,93) en la posición equivalente, sin ninguna mancha encima. El RUT de `464265` sí fue detectado, pero salió corrupto de una forma que **no pasa la validación de RUT chileno** (dígito verificador "X", que ni siquiera es un dígito verificador válido) -- y esto no es un caso aislado de la mancha: `464264` (sin mancha) también trae su RUT con el mismo tipo de corrupción (un dígito de más al principio), así que ese RUT tampoco habría servido de ancla en ese control.
- **Se investigó explícitamente si el RUT ofrece una vía sería de recuperación:** hoy, no -- el mecanismo que ya existe para esto (`_extraer_rut_cliente_geometrico`) exige que el RUT capturado pase el dígito verificador chileno completo, y correctamente se abstiene ante un RUT inválido (comportamiento correcto, no un bug). Tampoco existe hoy un mecanismo de relectura focal para nombres de cliente -- ese tipo de relectura (usado para fecha y número de transporte) sólo existe para campos de alfabeto restringido (dígitos), no para texto libre.
- **Se evaluó y se descartó explícitamente usar el campo SOLICITANTE (que sí trae "SODIMAC SA CORWEL", con OCR) como sustituto de cliente:** es un campo distinto del documento, con su propio significado -- en el propio `464264` SOLICITANTE trae "SODIMAC SA CORONEL", no el mismo texto simple que el campo cliente ("SODIMAC SA") -- usarlo como respaldo automático mezclaría dos campos que no siempre coinciden.
- **¿Existe evidencia documental suficiente para recuperar "SODIMAC SA" con seguridad hoy? NO.** El nombre no fue detectado en absoluto (no hay texto que "seleccionar mal"), y el RUT capturado es inválido. No hay ninguna corrección de código pequeña y segura que resuelva esto sin depender del documento hermano o del catálogo por contexto -- ambos explícitamente prohibidos.
- **Vía plausible identificada para el futuro, NO implementada:** una relectura focal del recorte del RUT (mismo patrón ya usado para fecha y transporte, con una lista de caracteres restringida a dígitos/puntos/guión/K), que si logra un RUT válido con consenso, se usaría por la vía YA EXISTENTE y segura de coincidencia exacta contra catálogo por RUT -- nunca por nombre aproximado. Se descarta implementarla en este bloque por ser una capacidad nueva (no una corrección puntual) que necesita su propia validación de riesgo (una relectura de RUT parcialmente incorrecta podría producir un RUT válido pero equivocado, mucho más delicado que el caso de fecha). **Queda registrado como diseño futuro (FIX_B), no implementado.**
- **Fix implementado: NO.**
- **Drive:** no modificado -- bloque 100% lectura. **Desktop:** no modificado.
- **Git:** sin cambios de código -- working tree del Motor limpio (idéntico a `d22829d`). Sin commit, sin push de este bloque.
- **Pendientes explícitos, sin iniciar:** relectura focal de RUT para cliente (diseño futuro, registrado); demás hallazgos del lote de 15; fecha de `464367` (registrado en el bloque anterior).
- **Estado: DIAGNÓSTICO CLIENTE 464265 COMPLETADO -- REQUIERE DECISIÓN.**

---

## 2026-08-18 — Cierre aceptado de `CLIENTE_AUSENTE 464265` + principio operacional ratificado por Javier

- **Diagnóstico de `464265` ACEPTADO y CERRADO, sin fix de código.** Confirmado explícitamente para que quede sin ambigüedad en continuidad: **el campo cliente SÍ existe en el documento físico de `464265`** ("SODIMAC SA", RUT `96.792.430-K`, confirmado visualmente con recorte ampliado) -- `CLIENTE_AUSENTE` describe que **Atlas no logró extraerlo** (el detector de OCR no generó ninguna caja de texto en esa posición), no que el documento carezca del campo. Esta distinción -- "el dato existe en el papel pero Atlas no pudo leerlo" vs. "el documento realmente no trae el dato" -- es relevante para el futuro diseño de motivos/Incidencias Documentales y queda registrada aquí explícitamente.
- **Principio operacional ratificado por Javier, registrado formalmente:**
  > Cuando Atlas tiene evidencia suficiente, actúa. Cuando existe una duda material, consulta. Cuando no existe evidencia suficiente, se abstiene. Atlas nunca debe adivinar para evitar una revisión humana.
  >
  > Esto no significa preguntar innecesariamente: si una identidad está inequívocamente corroborada, Atlas debe resolverla sin intervención humana.

  Este principio ya gobernaba de hecho el comportamiento de Atlas en todos los bloques de esta auditoría (abstención en `464265` cliente/fecha, abstención en `obra_destino` ante corroboración fallida, resolución automática cuando el RUT corrobora exactamente contra catálogo) -- queda ahora expresado como regla explícita de producto/ingeniería, no sólo como comportamiento observado caso a caso.
- **Drive/catálogos/Desktop:** sin cambios. **Git:** sólo estas tres bitácoras en el working tree del Motor, listas para publicarse como cierre documental de FASE 0.
- **Estado: CLIENTE 464265 CERRADO SIN FIX -- LISTO PARA PUBLICAR Y CONTINUAR CON EL SIGUIENTE HALLAZGO DEL LOTE.**

---

## 2026-08-18 — Diagnóstico dirigido de `464367`: FECHA EMISIÓN vs. FECHA SALIDA

- **Publicado antes de empezar:** cierre de cliente `464265` + principio operacional en `74c1478` sobre `origin/lector-mvp-guia-nueva`, verificado local=remoto, 0/0, working tree limpio.
- **Objetivo de este bloque:** `464367` (ya cerrada en un bloque anterior por su patente) usa `fecha = "06-08-2026"`, que en realidad es la **FECHA SALIDA** documental -- la **FECHA DE EMISIÓN** real, confirmada en la imagen, es `04-08-2026` (también hay una **FECHA LLEGADA** de `08-08-2026`).
- **Causa raíz, demostrada con evidencia real:** el motivo NO es que Atlas confunda "cualquier fecha válida" -- ambas fechas fueron leídas correctamente por el OCR, con etiqueta y valor correctos, cada una. El problema es el **orden en que el OCR entrega el texto**: en esta guía en particular, el valor de FECHA DE EMISIÓN aparece en el texto ANTES que su propia etiqueta (una inversión de orden, causada por el mismo tipo de layout de dos columnas que ya causó el bug de `obra_destino`/COMUNA en `464264`) -- y el mecanismo que decide "a qué etiqueta pertenece cada fecha" sólo mira una ventana corta de texto alrededor de cada candidato. Como la etiqueta quedó fuera de esa ventana por muy poco, el sistema termina asociando la fecha de emisión real con ninguna etiqueta reconocible, mientras que "FECHA SALIDA" (correctamente adyacente a su propio valor en el orden de lectura) sí gana la comparación -- y termina eligiéndose por error.
- **Comparado con 3 controles limpios del lote** (`464264`, `464488`, `464494`): en los tres, la etiqueta FECHA DE EMISIÓN aparece siempre justo antes de su valor en el orden de lectura -- nunca invertida. `464367` es el único caso observado con esta inversión específica.
- **El mecanismo geométrico (ubicación real en la imagen, no orden de lectura) ya identifica correctamente `04-08-2026` como FECHA DE EMISIÓN, con alta confianza** -- pero nunca llega a usarse porque, igual que en los otros dos bloques de fecha/obra_destino ya diagnosticados esta sesión, sólo se activa cuando el resultado inicial queda vacío -- y aquí no queda vacío, queda con la fecha equivocada.
- **Confirmado el significado del campo `fecha`:** representa FECHA DE EMISIÓN (documentado ya en el handoff técnico, función `F2` construida específicamente para recuperar ese campo) -- no hay ambigüedad histórica que resolver.
- **¿Es el mismo patrón que COMUNA en `464264`? Parcialmente.** Comparten el mismo origen (el orden de lectura del OCR no respeta el layout de dos columnas del documento), pero el mecanismo de código que falla es distinto -- en COMUNA, un patrón de texto capturaba por error una etiqueta vecina como si fuera el valor; aquí, el candidato correcto SÍ se captura, pero queda mal clasificado por quedar fuera de una ventana de texto acotada.
- **Fix implementado: NO.** Existen varias formas plausibles de corregir esto, con niveles de riesgo distintos entre sí (desde una comprobación barata que sólo señala la discrepancia sin cambiar ningún valor, hasta una verificación más profunda que si confirma la fecha correcta, la usaría automáticamente) -- ninguna de ellas es tan claramente la "única opción segura" como lo fueron los fixes ya publicados de material y obra_destino. Siguiendo el mismo criterio conservador de esta auditoría, se presentan las alternativas para que Javier decida en vez de elegir una arbitrariamente.
- **Drive:** no modificado -- bloque 100% lectura. **Desktop:** no modificado. **Git:** sin cambios de código -- sólo estas tres bitácoras, sin commit ni push de este bloque todavía.
- **Cliente `464265`:** cerrado sin fix, no reabierto.
- **Estado: DIAGNÓSTICO FECHA 464367 COMPLETADO -- REQUIERE DECISIÓN.**

---

## 2026-08-18 — Publicado (`b343a41`) + corroboración geométrica de fecha: implementada, validada por tests, bloqueada en producción por un hallazgo nuevo

- **Publicación:** el diagnóstico de fecha 464367 (sin código) quedó publicado en `b343a41` sobre `origin/lector-mvp-guia-nueva`, verificado local=remoto, working tree limpio. Desktop sin cambios, HEAD `fba95ac`.
- **Auditoría real amplia, 100% lectura, antes de implementar:** se compararon `extraer_fecha()` (lineal) contra `_extraer_fecha_geometrico()` (anclado específicamente a FECHA DE EMISIÓN) sobre **43 guías reales** -- todas las disponibles en el histórico de Drive, no sólo las 15 del lote actual. Resultado: **38 coinciden** (sin conflicto), **4 sin candidato geométrico** (el mecanismo se abstiene por diseño, sin cambio), y **exactamente 1 discrepancia real: `464367`** -- donde el candidato geométrico, ya verificado contra la imagen en el bloque anterior, es el correcto. **Cero casos de geometría ambigua** -- confirmado también que `_extraer_fecha_geometrico()` ya tiene tests dedicados (`test_fecha_geometrica_prioriza_emision_sobre_salida_cercana`, `test_fecha_geometrica_no_toma_candidato_mas_cercano_a_salida_que_a_emision`) que garantizan que nunca devuelve el valor de FECHA SALIDA/LLEGADA por error.
- **Decisión: OPCIÓN A (autocorrección segura), con la misma exigencia de verificación ya usada en el resto de esta auditoría.** Con evidencia tan favorable (1 discrepancia real en 43 guías, geometría siempre inequívoca cuando produce resultado), se implementó una corroboración: si la fecha geométrica difiere de la ya aceptada, se exige la MISMA relectura focal con doble confirmación ya usada para recuperar una fecha ausente -- nunca se confía en el texto geométrico bruto por sí solo. Si la relectura confirma la geometría, la reemplaza; si no logra consenso, el documento queda marcado `FECHA_SIN_CORROBORAR` (nuevo motivo, mismo patrón que `OBRA_DESTINO_SIN_CORROBORAR`) y el valor original se conserva intacto -- nunca se elige a ciegas.
- **Alcance deliberadamente acotado por seguridad de rendimiento:** la corroboración sólo corre si los bloques con geometría YA estaban cargados por otro campo ausente en el mismo documento (nunca fuerza una carga nueva sólo para esto) -- preserva el invariante ya existente y ya probado de que un documento cuyo texto lineal resuelve todo nunca toca geometría. `464367` cumple esta condición (tenía cliente y patentes ausentes), así que no se pierde cobertura del único caso real conocido.
- **10 tests nuevos, todos verdes:** reproducción exacta del caso real, corroboración confirmada, y 4 negativos (geometría ambigua, etiqueta ausente, relectura focal sin consenso, alcance acotado que no toca bloques innecesariamente) más un control de no-disparo cuando ya coinciden. Suite completa: **1216 passed, 0 failed** (baseline 1210 + 6).
- **Hallazgo nuevo, significativo, NO relacionado con este fix, descubierto durante la validación real en TEMP:** la relectura focal con PaddleOCR (el proveedor activo hoy) **falla siempre** -- confirmado reproduciéndolo en dos imágenes distintas sin relación entre sí -- porque dos de las cuatro variantes que genera (`grises` y `ampliada_2x_contraste`, ambas en escala de grises) llegan como imagen de 2 dimensiones al modelo, que exige 3. Esto significa que **el mecanismo de relectura focal -- ya publicado, usado hoy para recuperar fecha y número de transporte ausentes -- está silenciosamente inactivo en producción con el proveedor activo actual**, degradándose de forma segura (nunca rompe el resto del procesamiento) pero sin poder cumplir su función. No se detectó antes porque, hasta ahora, ningún documento del dataset real había quedado con fecha `"No encontrado"` que necesitara esa recuperación.
- **Consecuencia práctica para este bloque:** el fix de corroboración de fecha queda **implementado y validado por tests** (con relecturas focales simuladas), pero **no pudo validarse de extremo a extremo con OCR real** sobre `464367` -- al intentarlo, la relectura focal falló por el motivo anterior, y el sistema se abstuvo correctamente (comportamiento seguro, tal como está diseñado): `464367` sigue mostrando `06-08-2026`, sin cambio.
- **No se intentó corregir el bug del worker de PaddleOCR en este bloque** -- es un hallazgo separado, de mayor alcance (afecta también la recuperación ya publicada de fecha/transporte ausentes), fuera del objetivo único de este bloque.
- **Fix implementado: SÍ (código + tests). Validado de extremo a extremo con OCR real: NO** -- bloqueado por el hallazgo nuevo. **Drive:** no modificado. **Desktop:** no modificado. **Git:** working tree con `atlas_core/procesamiento_masivo.py` y `tests/test_procesamiento_masivo.py` modificados. **Sin commit, sin push de este bloque.**
- **Qué debe decidir Javier ahora:** si prioriza corregir el worker de PaddleOCR (bug separado, de mayor impacto que sólo `464367` -- desbloquearía también la recuperación de fecha/transporte ausentes ya publicada) antes de publicar este fix; o si publica este fix ya (queda correcto y seguro, sólo inactivo hasta que se corrija el worker).
- **Estado: DIAGNÓSTICO DE CORROBORACIÓN DE FECHA COMPLETADO -- REQUIERE DECISIÓN.**

---

## 2026-08-18 — P1 reparado: la relectura focal de PaddleOCR ya funciona con OCR real -- `464367` corregida de extremo a extremo

- **Objetivo de este bloque:** reparar el bug de infraestructura descubierto en el bloque anterior (la relectura focal con PaddleOCR fallaba siempre) antes de publicar el fix de fecha de `464367`, que dependía de ella.
- **Causa raíz aislada con precisión, reproducida en dos imágenes reales distintas:** de las 4 variantes de imagen que genera la relectura focal (original, en escala de grises, ampliada, ampliada con contraste), las **dos en escala de grises** llegan a `PaddleOCR.predict()` como una imagen de 2 dimensiones (sin canal de color) -- y `predict()` exige 3. El error era exactamente `ValueError: not enough values to unpack (expected 3, got 2)`, y ocurría **siempre**, en cualquier imagen, porque la escala de grises es una de las 4 variantes fijas que siempre se generan.
- **Alcance real, confirmado exhaustivamente:** el mismo mecanismo roto es usado por **tres capacidades**, todas dentro de `procesar_archivo()`: (1) recuperación de número de transporte ausente -- ya publicada; (2) recuperación de fecha ausente (bloque "F2") -- ya publicada; (3) corroboración de fecha lineal ya presente -- nueva, pendiente de publicar (bloque anterior). Las tres estaban silenciosamente inactivas en producción con PaddleOCR (proveedor activo hoy). No causó pérdida de datos visible hasta ahora porque, verificado contra el dataset real, **0 guías tienen hoy fecha o número de transporte ausentes** -- el extractor lineal había bastado siempre, así que el disparador de recuperación nunca se había ejercitado de verdad.
- **Fix: normalizar cada variante a 3 canales de color justo antes de entregarla a PaddleOCR**, sin alterar su contenido visual (una imagen en escala de grises ya tiene sus tres canales de color idénticos entre sí -- normalizar sólo cambia el formato del dato, no lo que se ve). Cambio mínimo, dentro del propio worker aislado de PaddleOCR -- no toca ninguna regla de negocio, ningún umbral, ninguna validación existente.
- **9 tests nuevos** para el worker (antes sin ninguna cobertura -- se agregó `tests/test_paddleocr_worker.py`), incluida una prueba de regresión que reproduce exactamente el error real y confirma que las 4 variantes llegan ahora con el formato correcto, y una prueba que confirma que un fallo real de OCR (no relacionado con el formato) se sigue reportando como error, nunca como éxito falso. Se verificó además, deliberadamente, que el código original (sin el fix) sí reproduce el error real -- confirmando que las pruebas nuevas realmente lo habrían detectado antes.
- **Validado con PaddleOCR real, no sólo con simulaciones:** la relectura focal ya no falla -- confirmado devolviendo lecturas reales tanto para fecha como para número de transporte, sobre imágenes reales.
- **Resultado central, con OCR real de extremo a extremo:** `464367` pasa de `fecha = "06-08-2026"` (equivocada) a **`fecha = "04-08-2026"`** (la fecha de emisión real) -- la geometría inequívoca ubicó la zona correcta, la relectura focal (ya reparada) la confirmó con dos lecturas concordantes de alta confianza, y sólo entonces se aceptó el cambio. Verificado que las capacidades ya publicadas también funcionan ahora de extremo a extremo con OCR real (no sólo con tests): la recuperación de fecha ausente reconstruida artificialmente sobre la imagen real de `464367` alcanza el mismo consenso; el llamado real de recuperación de número de transporte ya no falla.
- **Controles reales (`464264`, `464265`, `464488`, `464493`, `464494`):** comparación campo a campo, antes/después de este fix específico -- **cero cambios en cualquier campo, en las 5 guías**. `464265` (que tiene su propia fecha equivocada, diagnosticada en un bloque anterior y todavía sin corrección segura) permanece exactamente igual -- ese caso no tiene discrepancia entre lineal y geométrico, así que la corroboración correctamente no interviene.
- **Suite completa: 1225 passed, 0 failed** (baseline 1216 + 9).
- **Drive:** no modificado -- toda la validación fue lectura, en TEMP, eliminado al terminar. **Desktop:** no modificado.
- **Git:** working tree con `atlas_core/paddleocr_worker.py` (nuevo fix), `atlas_core/procesamiento_masivo.py` y `tests/test_procesamiento_masivo.py` (bloque anterior), `tests/test_paddleocr_worker.py` (nuevo), más estas tres bitácoras. **Sin commit, sin push -- Javier pidió revisar antes.**
- **Temas de continuidad ya registrados, sin iniciar aquí:** Incidencias Documentales genéricas; patente documental vs. vehículo canónico; sugerencia chofer↔vehículo sin autocorrección; transportista documental incorrecto (caso MBT ya visto); Analítica/IA; kilometraje operacional obligatorio; **planta de origen + rutas + kilómetros, próximo frente operacional ya identificado, no iniciado**.
- **Estado: P1 RELECTURA FOCAL REPARADO + FECHA 464367 VALIDADA -- LISTO PARA REVISIÓN CON JAVIER.**

---

## 2026-08-18 — Publicado (`3929174`) + diagnóstico READ-ONLY: planta de origen / rutas / kilómetros

- **Publicación:** commit `3929174` ("fix: restaurar relectura focal y corroborar fecha de emision") en `origin/lector-mvp-guia-nueva` (`b343a41..3929174`), verificado local=remoto, working tree limpio. Desktop sin cambios, HEAD `fba95ac`.
- **Objetivo de este bloque (100% lectura, sin tocar código ni Drive):** entender por qué Javier observa que la planta de origen no siempre se muestra correctamente, y auditar el estado real de origen/rutas/kilómetros en toda la operación vigente (43 documentos, 38 viajes).
- **Hallazgo principal -- la arquitectura correcta ya existe y funciona cuando se ejecuta, pero varias cosas le impiden ejecutarse siempre:** Atlas ya tiene una jerarquía bien diseñada (GPS/Onelogis real primero, encabezado documental solo como respaldo) y ORS real conectado con caché -- confirmado funcionando de punta a punta en 13 de 38 viajes (`RUTA_CALCULADA` real, con kilómetros y minutos reales). El problema no es que falte la infraestructura: es que, hoy, **25 de 43 documentos (58%) muestran la planta por el método menos confiable** (el encabezado impreso, que según ya quedó demostrado y documentado en bloques anteriores de este mismo proyecto siempre imprime la misma planta matriz, sin importar desde dónde salió realmente el camión) -- de esos 25, **19 nunca llegaron a intentar GPS en absoluto** (telemetría no conectada en esa corrida), y sólo 6 sí lo intentaron y genuinamente no encontraron el vehículo.
- **Caso concreto real, documentado con precisión:** `464264` y `464265` son el mismo viaje (mismo transporte). `464264` confirma su planta por GPS real (AZA Colina). `464265` -- que ya se sabía, de un bloque de diagnóstico anterior de esta misma auditoría, que trae su propia patente mal leída -- no logra que Onelogis encuentre su vehículo (con la patente equivocada, es lógico que no lo encuentre) y cae al encabezado (AZA Renca). El sistema hoy resuelve el origen **documento por documento**, nunca a nivel de viaje completo -- no "hereda" la confirmación GPS ya lograda por su propio documento hermano.
- **Hallazgo adicional, de código, confirmado leyendo el archivo real:** el mecanismo que debería avisar cuando dos documentos del mismo viaje traen plantas de origen distintas (`CONFLICTO_ORIGEN`) está roto -- compara contra una columna que no existe con ese nombre en el dato real, así que nunca se dispara. El caso de `464264`/`464265` de arriba debería haber generado esta alerta y no lo hizo.
- **Kilómetros:** 13 de 38 viajes ya tienen kilómetros reales, calculados con ORS. La causa más frecuente de que falten en el resto no es que ORS falle -- es que, aguas arriba, la planta de origen o el destino todavía no están resueltos. Dentro del lote de 15 más reciente, el motivo más común (6 de 15 guías) es que la geocodificación de la dirección de entrega devuelve varias ubicaciones dispersas sin poder elegir una sola -- existe un mecanismo para desambiguar esto con GPS real, pero requiere un tramo de viaje "sustancial" que, para estos 6 casos concretos, todavía no se encontró en los datos de Onelogis disponibles al momento de la consulta.
- **Nunca se confundió kilometraje con distancia en línea recta** -- no se calculó ninguna distancia auxiliar en este bloque.
- **Desktop revisado (sólo lectura, sin tocar nada):** ya muestra correctamente la planta y los kilómetros cuando existen, y "No disponible" cuando genuinamente no existen -- no se encontró ningún caso de un dato ya calculado por el Motor que Desktop no esté mostrando.
- **Respuesta a la pregunta central:** **ORS y Onelogis ya son, con la evidencia disponible hoy, herramientas suficientes** -- ninguna de las dos falló cuando efectivamente se les consultó con datos válidos. Lo que falta es cerrar huecos concretos ya identificados en cómo Atlas las usa (consolidar origen a nivel de viaje, no sólo por documento; revisar el umbral de "tramo sustancial" para desambiguar destino; reparar la alerta de conflicto de origen). No se determinó necesidad de un tercer proveedor.
- **Drive:** no modificado -- bloque 100% lectura directa sobre los datos reales ya publicados, sin copiar nada a TEMP. **Desktop:** no modificado. **Código:** sin cambios.
- **Próximo bloque recomendado, no iniciado:** consolidar la resolución de planta de origen a nivel de viaje completo (no sólo por documento) -- es el hallazgo de mayor impacto con causa más clara de este diagnóstico.
- **Git:** sin commit, sin push de este bloque -- Javier pidió revisar primero.
- **Estado: DIAGNÓSTICO PLANTA / RUTAS / KILÓMETROS COMPLETADO -- LISTO PARA REVISIÓN CON JAVIER.**

---

## 2026-08-18 — Publicado (`51fa504`) + consolidación de planta de origen a nivel de viaje + `CONFLICTO_ORIGEN` reparado

- **Publicación:** el diagnóstico de planta/rutas/km quedó publicado en `51fa504` sobre `origin/lector-mvp-guia-nueva`, verificado local=remoto, working tree limpio. Desktop sin cambios, HEAD `fba95ac`.
- **Objetivo de este bloque:** el diagnóstico anterior encontró que el origen se resuelve documento por documento, nunca a nivel del viaje completo -- un documento cuya propia patente impide confirmarse por GPS puede degradar en silencio el origen ya confirmado por su documento hermano del mismo viaje. Se corrigió exactamente eso, y de paso se reparó `CONFLICTO_ORIGEN`, que nunca podía dispararse.
- **Regla implementada, con jerarquía (GPS siempre gana sobre el documento, nunca al revés):** entre todos los documentos de un viaje con origen presente, se conserva sólo la fuente más confiable disponible; si esos coinciden en la misma planta, esa es la planta del viaje; si discrepan entre sí (mismo nivel de confianza, plantas distintas), es un conflicto real y no se elige ninguna a ciegas. Documentos sin origen nunca impiden ni degradan la consolidación de los demás. La comparación es por el identificador estable de la planta (no por el nombre), para no generar un conflicto falso por diferencias de formato.
- **`CONFLICTO_ORIGEN`, causa y solución:** el código comparaba una columna que nunca existió en los datos reales -- por eso nunca se disparaba, ni siquiera en el caso real ya conocido. Ahora usa la misma regla de jerarquía de arriba: sólo es conflicto real cuando dos fuentes igualmente confiables (ambas GPS, o ambas sólo documento) discrepan -- nunca cuando una fuente menos confiable simplemente pierde frente a una más confiable.
- **Caso real validado, sin hardcodear ninguna guía/transporte/planta en el código:** el viaje que ya se sabía afectado (mismo transporte de las guías `464264`/`464265`) pasa de mostrar el origen vacío (perdido en silencio por la discrepancia) a mostrar correctamente la planta ya confirmada por GPS -- sin inventar nada, sólo dejando de perder la evidencia ya disponible.
- **12 tests nuevos/actualizados** (7 casos de la jerarquía + caso real + 3 negativos, más 2 tests existentes que usaban un nombre de columna sintético corregidos para usar el esquema real). Suite completa: **1235 passed, 0 failed** (baseline 1225 + 10).
- **Validado con los 38 viajes reales** (comparación antes/después con el mismo dataset ya promovido, 100% lectura): **sólo 1 viaje cambia** -- exactamente el caso ya conocido, pasa de origen vacío a origen correcto. Ningún otro viaje se movió. **Cero conflictos nuevos, cero conflictos falsos.**
- **Impacto directo en kilómetros: ninguno todavía** -- este fix corrige cómo se consolida el origen ya calculado por cada documento, no vuelve a calcular rutas. El viaje corregido ahora tiene, por primera vez, un origen confiable a nivel de viaje completo -- la base necesaria para que un futuro bloque (destino/geocodificación, deliberadamente no tocado aquí) pueda intentar calcular su ruta.
- **Desktop:** no necesita ningún cambio -- ya lee las mismas columnas/propiedades que este fix corrigió, así que mostrará el origen correcto automáticamente en cuanto se reprocese el dato real (no se reprocesó en este bloque).
- **Drive:** no modificado -- validación 100% con datos ya promovidos, sin escribir nada, sin llamadas a ORS/Onelogis.
- **Git:** working tree con `atlas_core/gestor_viajes.py` y `tests/test_gestor_viajes.py` modificados. **Sin commit, sin push -- Javier pidió revisar antes.**
- **Próximo paso recomendado, no iniciado:** investigar la desambiguación de destino por GPS (umbral de "tramo sustancial" de Onelogis) -- la causa más común de kilómetros faltantes en el lote más reciente, ya identificada en el bloque anterior, todavía no tocada.
- **Estado: FIX ORIGEN DE VIAJE + CONFLICTO_ORIGEN VALIDADO -- LISTO PARA REVISIÓN CON JAVIER.**

## Bloque ONELOGIS / DESTINO / KM (diagnóstico, sin fix) -- 2026-08-18

- **Publicado antes de empezar:** fix de origen de viaje en `feb5afb`, push confirmado, local=remoto, working tree limpio.
- **Objetivo:** entender por qué el umbral de "tramo sustancial" (≥5 km) de Onelogis parecía bloquear la desambiguación de destino en varios viajes (`MULTIPLES_UBICACIONES_DISPERSAS`) y decidir si existe una corrección segura.
- **Método:** 100% lectura -- CSVs ya persistidos, más las cachés YA GUARDADAS de geocodificación y de trips de telemetría (ninguna llamada nueva a ORS ni a Onelogis), más la reproducción pura (sin red) de la función real de selección de recorrido contra esos trips ya cacheados.
- **Hallazgo principal:** `MULTIPLES_UBICACIONES_DISPERSAS` es la causa dominante de kilómetros faltantes (17 de 25 viajes sin km, 68%), pero NO tiene una única causa. De los 17: 7 no tienen ninguna telemetría conectada en el dato ya persistido (aunque los trips SÍ existen en caché -- una reprocesada más reciente del documento perdió esa conexión, hallazgo aparte, no es el umbral); 2 no tienen ningún trip de Onelogis ese día para esa patente (cobertura real ausente); 4 tienen origen confirmado por GPS pero el "recorrido operacional" de entrega nunca se selecciona -- **se verificó con los trips reales que bajar el umbral de 5 km a 0.5 km NO cambia el resultado**, porque simplemente no hay ningún movimiento sustancial registrado cerca de la hora de salida documental ese día (la causa no es el valor del umbral); los 4 restantes SÍ tuvieron el punto GPS disponible y el reintento de desambiguación se ejecutó, pero la dirección sigue siendo ambigua porque los candidatos de geocodificación quedan dispersos dentro de la misma región (más allá de lo que un radio de 50 km puede discriminar) o el propio `Pelias` nunca resolvió la calle y cayó a un homónimo de comuna a nivel nacional.
- **Onelogis, en este dataset real, nunca fue el factor decisivo de un destino resuelto** -- los 13 viajes con km hoy se resolvieron porque la geocodificación devolvió un único candidato de confianza suficiente desde el principio, no porque GPS haya desempatado nada.
- **ORS: 0 fallos reales** -- nunca se llegó a invocar en ningún caso ambiguo (el bloqueo es siempre anterior, en geocodificación/origen); en los 13 casos donde sí se invocó, funcionó siempre.
- **Decisión:** no se implementa ningún fix. Hay al menos 4 causas raíz distintas detrás del mismo síntoma, cada una necesitando una corrección diferente -- no existe una única corrección pequeña, segura y generalizable que las cubra todas. Se presenta la comparación completa a Javier.
- **Drive:** no modificado. **Desktop:** no modificado. **Git:** sin commit, sin push de este bloque.
- **Próximo paso recomendado, no iniciado:** decisión de Javier sobre cuál(es) de las 4 causas atacar primero, y si vale la pena reparar primero el gap de reprocesamiento (telemetría ya cacheada pero no conectada) antes de tocar ninguna lógica de desambiguación.
- **Estado: DIAGNÓSTICO ONELOGIS / DESTINO / KM COMPLETADO -- LISTO PARA REVISIÓN CON JAVIER.**

## Bloque GAP TELEMETRÍA CACHEADA (fix, validado, sin publicar) -- 2026-08-18

- **Publicado antes de empezar:** commit documental `7ea1a1b` con el diagnóstico Onelogis/destino/km, push confirmado, local=remoto, working tree limpio.
- **Causa raíz confirmada:** un documento puede quedar sin ninguna columna de telemetría en el CSV aunque el proveedor YA tenga sus trips cacheados -- verificado comparando la caché real (`telemetria_cache.json`) contra el CSV vigente para los 7 casos conocidos: la caché sí tenía los trips, el CSV no. No es un problema de cobertura de Onelogis ni del umbral de "tramo sustancial".
- **Mecanismo canónico ya existente, reutilizado:** el proyecto ya tenía un patrón establecido para esto (`atlas_core/revalidacion_documental.py`, usado hoy para `OBRA_DESTINO_SIN_CORROBORAR` y `PATENTE_SIN_HOMOLOGAR`) -- releer filas ya procesadas y corregir sólo lo que corresponde, sin OCR. Se agregó `revalidar_telemetria_sin_ocr()` siguiendo exactamente ese mismo patrón.
- **Nunca toca la red:** se creó `ProveedorTelemetriaSoloCache` (nunca abre conexión real) para garantizar, por construcción, que ni un solo caso de breadcrumb faltante en caché pueda disparar una llamada real a Onelogis.
- **Deliberadamente no recalcula rutas/km** (eso requiere ORS, fuera de alcance): sólo actualiza telemetría y origen; si el origen cambia y ya había un km calculado con el origen anterior (posiblemente la planta matriz documental, incorrecta), ese km se invalida explícitamente en vez de dejarse desactualizado en silencio.
- **12 tests nuevos.** Suite completa: **1247 passed, 0 failed** (baseline 1235 + 12).
- **Validación real en TEMP (43 documentos reales, sin tocar Drive):** 19 documentos recuperaron telemetría (más que los 7 originalmente identificados -- el gap era más amplio). 18 de ellos ahora tienen origen confirmado por GPS (17 pasan de "AZA RENCA" documental, incorrecto, a "AZA COLINA" real). **Hallazgo adicional importante: 9 documentos que HOY muestran un kilometraje ya calculado lo tenían calculado con el origen incorrecto** -- se invalidan correctamente (quedan pendientes de recalcular con ORS) en vez de mantenerse silenciosamente errados. De esos, 4 viajes quedan completamente listos para reintentar ORS de inmediato (origen correcto + destino ya resuelto); 1 revela que su origen nunca debió darse por bueno (ahora "no determinado", más honesto que antes); 1 sigue bloqueado por un conflicto documental preexistente no relacionado.
- **Desktop:** no necesita ningún cambio -- lee las mismas columnas.
- **Drive:** no modificado. **Git:** working tree con `atlas_core/revalidacion_documental.py`, `atlas_core/telemetria/proveedor.py` y `tests/test_revalidacion_telemetria_gap.py`. **Sin commit, sin push -- Javier pidió revisar antes.**
- **Próximo paso recomendado:** decisión de Javier sobre aplicar esto contra `operacion/actual` real (todavía no se hizo) y, después, un bloque aparte para recalcular con ORS los 4 viajes ya listos.
- **Estado: FIX RE-ENRIQUECIMIENTO TELEMETRÍA VALIDADO -- LISTO PARA REVISIÓN CON JAVIER.**

## Bloque APLICACIÓN REAL — revalidación telemetría en `operacion/actual` -- 2026-08-18

- **Publicado antes de empezar:** commit funcional `fb370ff` (fix ya en producción), push confirmado, local=remoto, working tree limpio.
- **Backup obligatorio:** `respaldos/REVALIDACION_TELEMETRIA_ROLLBACK_PRE_APLICACION_20260818_185739/` (`analisis_completo_guias.csv` + `estado_operacion.json`), verificado byte a byte por SHA-256, manifiesto incluido. Backups previos intactos.
- **Dry-run final** contra copia TEMP exacta del dato real vigente: coincidencia exacta con lo esperado (19 documentos, 18 mejoran origen, 17 RENCA→COLINA, 6 transportes con km a invalidar) -- sin sorpresas, se procedió.
- **Aplicación real** de `revalidar_telemetria_sin_ocr()` contra `G:\Mi unidad\Atlas\operacion\actual\analisis_completo_guias.csv`: **19 documentos recuperaron telemetría**, resultado idéntico al dry-run. **0 llamadas a Onelogis, 0 llamadas a ORS** (garantizado por `ProveedorTelemetriaSoloCache`).
- Reporte regenerado con el mecanismo canónico existente (`generar_reporte_viajes`, sin ORS) en `reportes/reporte_revalidacion_20260818_225946_039407/`; `estado_operacion.json` actualizado para apuntar ahí.
- **Integridad documental: 0 violaciones** -- ningún campo documental (guía, transporte, fecha, cliente, obra, patentes, material, horas) cambió; catálogos y decisiones sin tocar (mtimes verificados).
- **17 documentos corrigen origen** de `AZA RENCA` (documental, encabezado matriz -- causa raíz conocida) a `AZA COLINA` (real, GPS). **1 documento (464529)** queda honestamente sin determinar (antes tenía "AZA RENCA" heredado sin corroborar). **0 conflictos nuevos** (el único `ORIGEN_GPS_CONFLICTO` visto, 464730, ya existía antes de este bloque).
- **6 transportes con km calculado sobre origen incorrecto, invalidados correctamente** (nunca se dejó un número que ya no correspondía). **4 quedan `LISTOS_PARA_RECALCULO_RUTA`** (origen coherente + destino ya resuelto, sin conflicto): 0000351956, 0000352552, 0000352568, 0000352584 -- confirmado contra el reporte real regenerado, no hardcodeado.
- **Desktop:** no se tocó código; verificado que ya muestra "No disponible" para `distancia_km` vacío (`formatearDistancia`) -- funcionará correctamente en cuanto se abra con el reporte vigente actualizado.
- **Drive:** modificado, exclusivamente por esta revalidación controlada (2 archivos existentes + 1 reporte nuevo + puntero de estado).
- **Git:** working tree con sólo las tres bitácoras -- fix funcional ya publicado antes de esta aplicación.
- **Próximo paso recomendado:** bloque aparte, con autorización explícita, para recalcular con ORS los 4 viajes ya listos.
- **Estado: REVALIDACIÓN TELEMETRÍA APLICADA Y PUBLICADA -- LISTO PARA RECÁLCULO CONTROLADO DE RUTAS/KM.**

## Bloque RECÁLCULO CONTROLADO DE RUTAS/KM -- 2026-08-18

- **Publicado antes de empezar:** checkpoint `e4a354d` (Motor) / `fba95ac` (Desktop) verificados limpios.
- **Candidatos determinados programáticamente** (origen resoluble + destino ya resuelto + sin conflicto a nivel documento NI a nivel viaje + km ausente): **4 transportes / 5 documentos** -- coincide exactamente con la expectativa (0000351956, 0000352552, 0000352568, 0000352584), verificado, no asumido.
- **Backup:** `respaldos/RECALCULO_RUTAS_KM_ROLLBACK_PRE_APLICACION_20260818_190921/`, verificado byte a byte por SHA-256.
- **Dry-run con ORS real** (autorizado explícitamente sólo para estos 4 pares origen/destino): 4 rutas calculadas, todas `RUTA_CALCULADA`, todas con distancia > 0 y coherentes con el área metropolitana de Santiago. **Verificación cruzada:** la ruta AZA COLINA→VISTA CLARA 2351 CERRILLOS coincidió EXACTO (30.7719 km) con la misma ruta ya calculada antes para otra guía (464763) -- confirma correctness sin ambigüedad.
- **Aplicación real:** los 4 resultados del dry-run (no se llamó ORS una segunda vez) se persistieron en las 5 filas candidatas. Reporte regenerado (mecanismo canónico, sin ORS adicional) en `reportes/reporte_revalidacion_20260818_231011_223069/`.
- **0 otros documentos modificados. 0 violaciones de integridad** (documental + origen/telemetría). Catálogos y decisiones intactos (verificado por mtime).
- **Cobertura km final: 12/38 viajes (31.6%)**, antes 8/38 (21.1%). Los 26 restantes sin km, todos con causa explicada: 17 `MULTIPLES_UBICACIONES_DISPERSAS`, 6 origen no determinado (incluye 1 conflicto GPS ya conocido), 1 `GEOCODIFICACION_DIRECCION_NO_ENCONTRADA`, 1 conflicto documental preexistente, 1 sin `despachar_a`.
- **Desktop:** no se tocó código; `estado_operacion.json` ya apunta al reporte con los km nuevos, Javier podrá verlo al abrir Desktop.
- **Drive:** modificado, exclusivamente por este recálculo controlado. **Git:** working tree con sólo las tres bitácoras (no hubo cambios de código en este bloque).
- **Próximo paso recomendado:** ninguno urgente -- los 22 viajes restantes sin km requieren decisiones de negocio ya identificadas en bloques anteriores (umbral Onelogis, radio GPS destino, conflictos documentales), no un recálculo mecánico más.
- **Estado: RUTAS/KM RECALCULADOS -- LISTO PARA VALIDACIÓN VISUAL DE JAVIER.**

## Bloque DIAGNÓSTICO DESTINOS AMBIGUOS (MULTIPLES_UBICACIONES_DISPERSAS) -- 2026-08-18

- **Checkpoint verificado, 100% lectura** -- ningún archivo de Drive tocado (mtimes re-verificados sin cambios).
- **17 casos inventariados programáticamente** (coincide exacto, no hardcodeado), con evidencia real: candidatos de geocodificación ya cacheados, TODOS los breadcrumbs GPS cacheados de cada patente/fecha (no sólo los que el algoritmo actual usa), y cruce contra `obras_destinos.json`/`destinos_maestros.json`.
- **Clasificación final: 7 resolubles automáticamente con evidencia inequívoca (A), 6 resolubles con confirmación humana asistida (B), 4 no resolubles con datos actuales (C).**
- **Hallazgo clave:** en varios casos A, el GPS real (usando TODOS los breadcrumbs disponibles, no sólo la ventana estrecha que usa hoy el algoritmo) sí discrimina con claridad -- confirmando que el problema no es "falta de evidencia" sino que el mecanismo actual no la está aprovechando toda. En 3 casos A además hay una entrada `CONFIRMADA` en `destinos_maestros.json` con la MISMA dirección exacta y coordenadas -- evidencia independiente adicional, no sólo GPS.
- **2 de los 4 casos C** muestran que el geocodificador (Pelias/ORS) devuelve candidatos en regiones completamente equivocadas para direcciones donde el documento SÍ nombra la comuna real correctamente (p. ej. "LA CISTERNA" nunca aparece entre los candidatos) -- esto es una limitación del geocodificador, no de la lógica de desambiguación de Atlas.
- **Cobertura potencial (sin ejecutar ORS, sólo calculada):** actual 12/38 (31.6%) → sólo con A: 19/38 (50.0%) → con A+B confirmados por Javier: 25/38 (65.8%).
- **ORS sigue siendo suficiente para el routing** (100% de éxito en cada llamada real hecha hasta ahora); el cuello de botella real está en la geocodificación de un subconjunto de direcciones, no en el ruteo.
- **No se implementó ningún fix.** No se tocó Drive, catálogos, ni Desktop.
- **Próximo paso recomendado:** decisión de Javier sobre cómo tratar los casos A (¿confiar en GPS+catálogo automáticamente, o seguir pidiendo confirmación?) y los B (diseñar la sugerencia con evidencia, sin adivinar).
- **Estado: DIAGNÓSTICO DE DESTINOS AMBIGUOS COMPLETADO -- LISTO PARA REVISIÓN CON JAVIER.**

## Bloque RESOLUCIÓN SEGURA DE DESTINOS CLASE A (mecanismo general, validado, sin publicar) -- 2026-08-18

- **Publicado antes de empezar:** commit documental del diagnóstico anterior, push confirmado, limpio.
- **Mecanismo general implementado** (`resolver_destino_ambiguo_con_evidencia_inequivoca`, nuevo): dos vías independientes, **sin inventar ningún umbral nuevo** -- reutiliza exclusivamente constantes/funciones ya calibradas y en producción (`MARGEN_MISMO_LUGAR_KM=1.0`, radio GPS `50.0` ya usado en `resolver_destino_entrega`). Vía A: catálogo `destinos_maestros.json` con estado `CONFIRMADO` (nunca `PENDIENTE`) y dirección exacta. Vía B: recorrido GPS COMPLETO de la ventana documental (no sólo el último punto, como hace hoy el mecanismo de producción) descarta a todos los rivales. Si ambas vías responden distinto, se abstiene -- nunca prioriza una fuente en silencio.
- **Validado contra los 17 casos reales, sin tocar Drive:** **6 de los 7 casos A se resolvieron automáticamente, 0 falsos positivos entre los 6 B y 4 C** (los 10 siguen correctamente en abstención). El 7º caso A (candidatos casi idénticos, a metros entre sí) se abstiene correctamente -- ni el catálogo ni el GPS pueden distinguir CUÁL candidato exacto es el correcto, coincide con la regla explícita "candidatos cercanos entre sí: abstenerse". **No se forzó el código para llegar a 7/7.**
- **18 tests nuevos** (11 controles negativos, 7 positivos). Suite completa: **1265 passed, 0 failed** (baseline 1247 + 18).
- **0 llamadas a ORS** en todo el bloque -- selección de destino y cálculo de ruta quedan estrictamente separados, verificado con test dedicado.
- **Los 12 viajes con km válido no fueron tocados** -- el mecanismo nuevo es código standalone, no está conectado todavía al pipeline de producción.
- **Drive: no modificado.** **Desktop: no modificado.**
- **Git:** working tree con `atlas_core/rutas/destino_entrega.py`, `atlas_core/telemetria/seleccion_recorrido.py` (refactor puro, sin cambio de comportamiento, 84 tests de telemetría siguen en verde) y `tests/test_desambiguacion_destino_inequivoca.py`. **Sin commit, sin push -- Javier pidió revisar antes.**
- **Próximo paso recomendado:** decisión de Javier sobre publicar este mecanismo y, en un bloque aparte, conectarlo al pipeline real (sólo para los casos que de verdad resuelva -- nunca forzando los B/C).
- **Estado: RESOLUCIÓN SEGURA DE DESTINOS CLASE A VALIDADA -- LISTO PARA REVISIÓN CON JAVIER.**

## Bloque PUBLICACIÓN + APLICACIÓN REAL: resolución clase A + ORS controlado -- 2026-08-18/19

- **Publicado:** commit funcional `515d9ef` ("fix: resolver destinos ambiguos con evidencia inequivoca"), push confirmado, local=remoto, working tree limpio antes de tocar Drive.
- **Backup:** `respaldos/RESOLUCION_DESTINOS_A_ROLLBACK_PRE_APLICACION_20260818_203757/`, verificado byte a byte por SHA-256, con `LEEME_ROLLBACK.md`. Backups previos intactos.
- **Detección programática (no hardcodeada):** de los 17 viajes `MULTIPLES_UBICACIONES_DISPERSAS` vigentes, el mecanismo publicado resolvió exactamente **6** -- mismo resultado que la validación previa, sin sorpresas, confirmado antes de escribir Drive.
- **Dry-run ORS real** (sólo para esos 6 pares origen/destino): 6/6 `RUTA_CALCULADA`, todas coherentes (distancia > 0, coordenadas de origen del punto de ruteo real documentado en `plantas.json` para AZA COLINA).
- **Aplicación real:** los mismos valores ya calculados y verificados en TEMP se copiaron al dataset real -- **0 llamadas ORS adicionales** (nunca se recalculó dos veces la misma ruta). Reporte regenerado (mecanismo canónico) en `reportes/reporte_revalidacion_20260819_004409_246309/`; `estado_operacion.json` actualizado.
- **Integridad: exactamente las 6 guías esperadas cambiaron, 0 documentos ajenos modificados, 0 violaciones de campos documentales.** Catálogos y decisiones intactos (verificado por mtime).
- **Cobertura: 18/38 (47.4%)**, antes 12/38 (31.6%). 11 viajes siguen correctamente `MULTIPLES_UBICACIONES_DISPERSAS` (0 casos B/C promovidos automáticamente). El caso límite (Camino Lo Ruiz, 0000352241) se sigue absteniendo tal como se validó.
- **Desktop:** no se tocó código; los km/destino nuevos ya están disponibles en el esquema que Desktop consume.
- **Drive:** modificado -- exclusivamente `analisis_completo_guias.csv` (6 filas), `estado_operacion.json` (puntero) y el nuevo reporte (no sobrescribe ninguno anterior).
- **Git:** working tree con sólo las tres bitácoras -- el fix funcional ya estaba publicado antes de esta aplicación.
- **Pendiente explícito, no iniciado en este bloque:** casos B (confirmación humana asistida con sugerencia), casos C (requieren nueva evidencia/fuente), geocodificador complementario, Incidencias Documentales, patente documental vs vehículo canónico, Analítica/IA, Mobile, Multiempresa.
- **Estado: RESOLUCIÓN SEGURA CLASE A APLICADA + RUTAS/KM RECALCULADOS -- LISTO PARA VALIDACIÓN VISUAL DE JAVIER.**

## Bloque AUDITORÍA VIAJES SIN PLANTA DE ORIGEN (diagnóstico, sin fix) -- 2026-08-19

- **Checkpoint verificado, 100% lectura** -- Drive re-verificado sin cambios al terminar.
- **5 viajes sin planta de origen** en el reporte vigente (todos de un solo documento): 464479, 464529, 464717, 464730, 464892. Los 3 vehículos involucrados (DD2494, TG8925, AL1879) están confirmados y activos en el catálogo -- **el problema nunca es la patente**.
- **0 casos resolubles automáticamente hoy.** 2 casos (464717, 464892) son "casi" -- una detención GPS real y prolongada cae 39-49% dentro del polígono conocido de AZA COLINA, justo por debajo del umbral de 50% ya calibrado (evidencia real, no un umbral inventado para este bloque). 1 caso (464730) es un conflicto real: el vehículo visitó AMBAS plantas confirmadas en la misma ventana -- agravado porque el documento registra la misma hora para entrada y salida (08:18=08:18), lo que le quita al algoritmo cualquier ventana real contra la cual comparar. 2 casos (464479, 464529, mismo patente y semana) tienen telemetría genuinamente escasa (1 solo trip, 5 puntos GPS) que no cubre la salida real de planta -- límite de cobertura de Onelogis, no corregible con datos ya existentes.
- **Hallazgo relevante (no un bug de cálculo, sí de reporte):** para 2 de los 5 casos (464479, 464892), el motivo de destino ambiguo queda oculto porque el mismo campo `motivo_ruta` se sobrescribe con el motivo de origen -- esto explica por qué el diagnóstico de destinos del bloque anterior no los detectó entre los 17. **464892 en particular usa la MISMA dirección ("Santa Isabel 585, Lampa") ya resuelta automáticamente para otros 4 viajes** -- si se resolviera su origen, su destino ya tiene el camino resuelto y quedaría listo para ORS de inmediato.
- **Cobertura:** actual 18/38 (47,4%); potencial si Javier confirma los 2 casos límite = **19/38 (50,0%)** (sólo 464892 desbloquea routing completo; 464717 seguiría bloqueado por destino ambiguo); el conflicto de 464730, si Javier lo resuelve, sumaría potencialmente 1 más (destino ya resuelto).
- **0 llamadas a ORS. 0 llamadas a Onelogis por red.** Sin fix implementado. Drive y Desktop no modificados.
- **Próximo paso recomendado:** decisión de Javier caso por caso -- no hay una corrección única y segura aplicable a los 5 a la vez.
- **Estado: AUDITORÍA DE VIAJES SIN PLANTA DE ORIGEN COMPLETADA -- LISTO PARA REVISIÓN CON JAVIER.**

## Bloque EVIDENCIA HUMANA PARA RESOLUCIÓN DE ORIGEN -- 464717 / 464892 / 464730 -- 2026-08-19

- **100% lectura**, sin código nuevo, sin fix, sin cambios en Drive/Desktop.
- Se reconstruyó la cronología GPS completa del día (no sólo la ventana estrecha) para los tres casos, usando exclusivamente `telemetria_cache.json` real, y se tradujo a lenguaje humano para que Javier decida caso por caso.
- **464717:** detención real de casi 5 horas que contiene por completo la ventana horaria de la guía; 49.1% de sus puntos dentro del área ya confirmada de AZA Colina (justo bajo el umbral); cero actividad ese día cerca de Renca. **Sugerencia: AZA COLINA, evidencia moderada-fuerte.**
- **464892:** detención de 88 minutos que coincide casi al minuto con la guía; 39.2% dentro de Colina; cero evidencia de Renca. **Sugerencia: AZA COLINA, evidencia moderada.** Su destino ("Santa Isabel 585, Lampa") ya se resuelve automáticamente -- confirmar origen lo dejaría listo para ruta.
- **464730:** el vehículo SÍ visitó ambas plantas ese día con evidencia fuerte para las dos (76.9% Colina, 100% Renca) -- pero la visita a Colina termina casi exactamente a la hora que registra la guía (08:18), y la visita a Renca ocurre casi 2 horas después, sugiriendo un viaje distinto posterior. Se detectó además que el documento registra la misma hora para entrada y salida (08:18=08:18) -- candidata a futura Incidencia Documental, no creada todavía. **Sugerencia: AZA COLINA por secuencia temporal, evidencia contradictoria a nivel algorítmico.**
- Se preparó una pregunta concreta por caso para Javier y una propuesta conceptual de UX (`ORIGEN_NO_CONFIRMADO`) -- sin implementar.
- 464479/464529 preservados sin tocar, tal como quedaron clasificados (evidencia insuficiente).
- **Estado: EVIDENCIA DE ORIGEN PREPARADA -- ESPERANDO DECISIÓN DE JAVIER.**

## Bloque INCORPORAR CONFIRMACIONES HUMANAS DE ORIGEN + DISEÑO DE CIERRE SEGURO -- 2026-08-19

- **Javier confirmó operacionalmente:** 464717 → AZA COLINA, 464892 → AZA COLINA, **464730 → AZA RENCA**.
- **Lección de producto (464730):** la evidencia GPS mostraba visitas reales y fuertes a AMBAS plantas; la secuencia temporal sugería Colina, pero el origen real confirmado por Javier fue Renca. Atlas se abstuvo correctamente en vez de decidir por sugerencia -- este caso queda como prueba viva de que GPS/cronología son evidencia, nunca verdad canónica automática.
- **No se aplicó ninguna de las tres confirmaciones todavía** -- este bloque fue 100% diseño y auditoría, sin tocar Drive.
- **Mecanismo existente auditado:** el sistema de decisiones (`decisiones_pendientes.py`/`aplicacion_decisiones.py`) ya soporta este patrón exacto para otras entidades (`DESTINO_SIN_CONFIRMAR`, `VEHICULO_DESCONOCIDO`) -- transaccional, auditable, con protección de obsolescencia. **No existe todavía el tipo `ORIGEN_NO_CONFIRMADO`**, ni un nivel de jerarquía "confirmación humana" por encima de GPS/documento, ni protección para que una revalidación futura no sobrescriba una confirmación humana ya aplicada.
- **Diseño completo preparado** (payload, acciones, auditoría, propagación hasta Desktop) -- **no implementado, per instrucción explícita.**
- **Simulación (sin escribir Drive, sin ORS):** de los tres, sólo 464730 quedaría técnicamente listo para calcular ruta de inmediato al confirmar origen (su destino ya está resuelto); 464717 y 464892 seguirían bloqueados por destino (ambiguo, actualmente oculto por el mismo motivo de origen).
- **464479/464529:** preservados intactos, sin pedir nada a Javier -- evidencia genuinamente insuficiente.
- **Hallazgo adicional de observabilidad:** 4/38 viajes tienen `motivo_ruta` no fiable como única fuente -- 3 por enmascaramiento (origen oculta destino) y **1 nuevo hallazgo: 464522 tiene el origen ya corregido (AZA Colina) pero el motivo_ruta quedó con texto obsoleto** de antes de esa corrección, porque no había km que invalidar en ese momento.
- **Estado: DISEÑO DE CONFIRMACIÓN HUMANA DE ORIGEN COMPLETADO -- LISTO PARA REVISIÓN CON JAVIER.**

## Bloque IMPLEMENTAR ORIGEN_NO_CONFIRMADO / CONFIRMACIÓN HUMANA AUDITABLE DE ORIGEN -- 2026-08-19

- **Checkpoint verificado, commit documental publicado antes de tocar código** (`87dc2ba`, "docs: registrar decisiones humanas de origen"), push confirmado, working tree limpio antes de empezar.
- **`ORIGEN_NO_CONFIRMADO` implementado** siguiendo exactamente el diseño auditado en el bloque anterior -- 4 archivos extendidos (`decisiones_pendientes.py`, `aplicacion_decisiones.py`, `gestor_viajes.py`, `revalidacion_documental.py`), **cero infraestructura paralela**: reutiliza `crear_decision`, `generar_artefacto`, el ledger transaccional con rollback y la protección de obsolescencia ya existentes.
- **Generación conservadora, sin hardcodear ninguna guía:** sólo publica cuando el `motivo_origen_gps` ya persistido describe evidencia real (conflicto nombrado entre plantas, o una detención real sin planta con al menos una planta CONFIRMADA/ACTIVA dentro de 50 km -- mismo radio que ya usa el mecanismo de destinos, ningún umbral nuevo). Nunca fuerza un único candidato: cuando hay más de uno, presenta todos.
- **Jerarquía de origen extendida:** `CONFIRMACION_HUMANA` por encima de GPS y documento. **Protección contra sobrescritura:** `revalidar_telemetria_sin_ocr` ahora nunca toca una fila ya confirmada por un humano, verificado como PRIMER chequeo del bucle, aun si otras columnas quedaran vacías.
- **4 acciones auditables:** `CONFIRMAR_PLANTA` (un solo candidato), `SELECCIONAR_OTRA_PLANTA` (cualquier planta válida, incluida una distinta a la sugerida), `NO_PUEDO_DETERMINAR` (no inventa origen, y por el mismo `decision_id` determinista ya existente Atlas nunca vuelve a preguntar lo mismo sin evidencia nueva) y `POSPONER`. **ORS nunca se dispara desde esta acción** -- confirmar origen y calcular ruta siguen siendo pasos separados.
- **Control crítico 464730 verificado con datos reales en TEMP:** GPS con evidencia fuerte para AZA COLINA (score 0.14) y AZA RENCA (score 0.0) -- Atlas presentó ambas, sin forzar ninguna, y el humano pudo elegir **AZA RENCA** exactamente como Javier confirmó. La evidencia GPS original queda intacta en el documento; sólo cambia cuál planta es la canónica.
- **Desktop:** cambios mínimos en `decisiones_pendientes_ui.js` (tarjeta con Transporte/Planta sugerida o candidatas/evidencia resumida/las 4 acciones) -- **ningún tipo existente cambió de comportamiento**.
- **Tests (estado al cerrar el bloque de diseño): 21 nuevos en Motor** (incluye el control 464730 y los casos de abstención 464479/464529 -- patrón, no las guías reales) -- **suite completa 1286 passed, 0 failed** (baseline 1265+21). **60 tests en Desktop** para la tarjeta nueva -- **suite completa 208 passed, 0 failed**.
- **Validación real en TEMP (nunca en Drive):** las 43 filas reales del dataset produjeron **exactamente 3 decisiones** (464717, 464730, 464892) -- **0 para 464479/464529**, confirmando que la abstención funciona con datos reales, no sólo simulados. Se simuló aplicar 464717→COLINA, 464892→COLINA, 464730→RENCA: los tres quedaron con `origen_determinado_por=CONFIRMACION_HUMANA`, evidencia GPS previa intacta. Al regenerar `viajes.csv` en TEMP: **464730 quedó listo para ORS** (destino ya resuelto), 464717 sigue bloqueado por destino ambiguo (esperado), y 464892 mostró el precondición de catálogo (`destinos_maestros.json` CONFIRMADO con la misma dirección que ya resolvió 3 viajes hermanos) que sugiere que resolvería si se reintenta el mecanismo Clase A -- no se completó esa reconstrucción end-to-end en esta validación ni se llamó ORS en ningún momento.
- **Cierre del gap Desktop (FASE 0 del bloque siguiente, antes de publicar):** `main.js` ahora incluye las 3 acciones nuevas en su whitelist más `--planta-id-elegida`; `preload.js` y `atlas_viajes.html` propagan el 4º argumento (planta elegida) hasta `atlasAPI.aplicarDecisionObra`; `aplicar_decision_pendiente.py` acepta las 3 acciones y el nuevo flag. **3 tests Motor nuevos** (CLI real vía subprocess, las 3 acciones de punta a punta) y **3 tests Desktop nuevos** (verifican el wiring en el código fuente) -- **Motor 1289 passed, Desktop 211 passed, 0 failed en ambos.** El click real en Desktop ya queda funcional de punta a punta -- gap cerrado.
- **Drive: no modificado** (mtimes re-verificados idénticos al cierre). **Git:** publicado -- ver bloque siguiente para el commit/push real de este cierre.
- **Pendiente explícito, no iniciado en este bloque:** aplicar las 3 confirmaciones reales a Drive; reintentar el mecanismo Clase A para 464892; corregir el gap de observabilidad de `motivo_ruta` (4/38, sigue igual); Incidencias Documentales; Analítica/IA; Mobile; Multiempresa.
- **Estado: ORIGEN_NO_CONFIRMADO VALIDADO PUNTA A PUNTA -- LISTO PARA REVISIÓN CON JAVIER.**

## Bloque VISITA_A_PLANTA + ASOCIACIÓN VIAJE↔VISITA -- 2026-08-19

- **FASE 0 -- publicación del bloque anterior, completada primero:** gap de `main.js`/`preload.js` auditado y cerrado (whitelist de acciones + `--planta-id-elegida`, validado con formato UUID antes de invocar Python). **Motor publicado** (commit `d5adb2e`, push confirmado, local=remoto, limpio). **Desktop publicado** (commit `a34059f`, push confirmado, local=remoto, limpio). Tests al publicar: Motor 1289 passed, Desktop 211 passed, 0 failed.
- **Hallazgo central de este bloque, verificado con datos reales:** **el modelo VISITA_A_PLANTA que se pidió diseñar YA EXISTE y ya está en producción**, dentro de `resolver_planta_origen_gps`/`detectar_detenciones`/`_resolver_planta_para_detencion` (`atlas_core/telemetria/seleccion_recorrido.py`). Detecta permanencias reales por vehículo/día (clusters espacio-temporales de GPS), las asocia a la geocerca de cada planta, y las puntúa contra la ventana documental real (`hora_entrada_aza`→`hora_salida_aza`) con un score explicable (solape con la ventana 50%, continuidad 20%, proximidad de entrada/salida GPS 15%+15%) -- exactamente la "puntuación semántica basada en evidencia real, sin score arbitrario opaco" que pedía la FASE 5. Ya produce, de fábrica, las 4 clasificaciones pedidas (inequívoca / sugerible / ambigua / sin evidencia) a través de sus estados `ORIGEN_GPS_CONFIRMADO`/`ORIGEN_GPS_ESTADIA_SIN_PLANTA`/`ORIGEN_GPS_CONFLICTO`/`ORIGEN_GPS_NO_DETERMINADO`. Y ya soporta múltiples visitas el mismo día a plantas distintas -- nunca asumió "una planta por vehículo/día".
- **Verificación con datos reales (no simulados) en TEMP:** se reprodujeron 464717/464892/464730 llamando DIRECTAMENTE a la función de producción con sus horas documentales reales -- **coincidencia exacta, carácter por carácter, con lo ya persistido en el CSV real** (mismo estado, misma planta, mismo texto de motivo). Cero deriva entre lo calculado y lo guardado.
- **Búsqueda real del caso "misma jornada, dos plantas" (FASE 6):** se escanearon las 27 combinaciones patente/día cacheadas -- **6 tienen evidencia GPS real de visitas a AMBAS plantas el mismo día** (no sólo 464730). En los **otros 5**, cada uno tiene exactamente 1 guía documentada ese día y **el mecanismo ya existente la asoció correctamente a la planta real** pese a que el mismo vehículo tocó la otra planta ese mismo día -- validación cruzada fuerte, con datos reales, de que el score basado en la ventana documental discrimina correctamente. **No se encontró, entre los 43 documentos reales disponibles, un caso de DOS guías documentadas del mismo chofer/vehículo en plantas distintas el mismo día** -- se reporta así, sin inventar cuál sería.
- **Control crítico 464730, explicado con precisión:** su documento trae `hora_entrada_aza == hora_salida_aza == "08:18"` -- una ventana degenerada (un instante, no un rango). Con un instante, el solape con CUALQUIER visita es matemáticamente 0% siempre -- el desempate queda solo en manos de la señal más débil (proximidad GPS, 30% del score). Colina (termina 6 min después del instante) saca 0.1366 vs. Renca (empieza ~2 h después) 0.0 -- una diferencia real pero por debajo del margen de 0.15 exigido para preferir una con confianza, así que Atlas concluye **CONFLICTO** correctamente, tal como está sucediendo hoy en producción. **No se ajustó ningún umbral para forzar el resultado correcto (Renca) -- eso habría sido exactamente el error que este bloque pedía evitar.**
- **Clasificación sobre el histórico completo (43 documentos, leyendo columnas ya persistidas, sin recalcular nada):** **A (inequívoca) = 38**, **B (sugerible) = 2** (464717, 464892), **C (ambigua) = 1** (464730), **D (sin evidencia) = 2** (464479, 464529). Coincide exactamente con lo ya sabido del bloque ORIGEN_NO_CONFIRMADO -- porque es la MISMA evidencia subyacente.
- **Relación con ORIGEN_NO_CONFIRMADO:** ya está resuelta -- `detectar_decision_origen_no_confirmado` (bloque anterior) lee directamente el `motivo_origen_gps` que produce este mismo mecanismo, sin duplicar lógica. No hace falta ningún puente nuevo.
- **Decisión de implementación (FASE 13):** **no se implementó código productivo nuevo.** Crear una estructura `VISITA_A_PLANTA` paralela habría sido exactamente la infraestructura duplicada que el proyecto pide evitar -- el modelo, con ese nombre o sin él, ya existe, ya está probado y ya está validado con datos reales de este mismo bloque. Se identificaron 2 huecos reales de cobertura de test (dos visitas a la MISMA planta el mismo día; el patrón exacto de ventana degenerada 464730) y se cerraron con **2 tests nuevos** en el archivo ya existente `test_origen_o2.py` -- sin infraestructura paralela.
- **Tests: 2 nuevos. Suite completa Motor: 1291 passed, 0 failed** (baseline 1289+2). Desktop no modificado en este bloque -- sigue en 211.
- **Drive: no modificado** (mtimes re-verificados idénticos). **Desktop: no modificado** en este bloque (los cambios de Desktop de FASE 0 ya están publicados, ver arriba).
- **Git:** working tree con `tests/test_origen_o2.py` (2 tests nuevos) y las tres bitácoras. **Sin commit, sin push del bloque funcional -- instrucción explícita.**
- **Próximo paso recomendado:** si Javier confirma que no hace falta un modelo separado, cerrar este frente sin más código y volver a destinos B/C o a la deuda de `motivo_ruta`; si en cambio quiere exponer las "visitas" como objetos de primera clase (p. ej. para enriquecer la evidencia mostrada en Desktop más allá del texto de `motivo_origen_gps`), eso sería una extensión pequeña y acotada, no rediseñar el mecanismo.
- **Estado: MODELO VISITA_A_PLANTA VALIDADO -- LISTO PARA REVISIÓN CON JAVIER.**

## Bloque CIERRE VISITA_A_PLANTA + APLICACIÓN REAL DE CONFIRMACIONES DE ORIGEN -- 2026-08-19

- **FASE 0:** checkpoint verificado exacto (Motor `d5adb2e`, working tree sólo con `tests/test_origen_o2.py` + 3 bitácoras; Desktop `a34059f`, limpio). Suite completa Motor: **1291 passed, 0 failed** (esperado, confirmado). **Publicado:** commit `d7c5694` ("test: cubrir asociaciones de visitas a planta"), push confirmado, local=remoto, limpio. Desktop no se tocó.
- **Backup pre-aplicación:** `respaldos/ORIGEN_HUMANO_ROLLBACK_PRE_APLICACION_20260819_115529/` -- dataset, `estado_operacion.json`, `decisiones_pendientes.json` y `decisiones_aplicadas.json` de antes de cualquier escritura de este bloque, verificados SHA-256 byte a byte contra el original antes de continuar.
- **Dry-run primero, en TEMP, con el mecanismo real (no simulado a mano):** las 3 confirmaciones se aplicaron sobre una copia aislada usando exactamente `aplicar_decision_obra`/`SELECCIONAR_OTRA_PLANTA` -- resultado idéntico campo por campo al esperado, y **exactamente 3 filas de 43 cambiaron, exactamente las 4 columnas de origen esperadas, ninguna otra.** Recién con eso verificado se tocó Drive real.
- **Aplicación real en Drive, mecanismo canónico, sin edición manual de CSV:** 464717 → AZA COLINA, 464892 → AZA COLINA, **464730 → AZA RENCA**, los tres con `origen_determinado_por=CONFIRMACION_HUMANA`, actor `JAVIER_MBT`, evidencia GPS previa 100% intacta. **Confirmado en Drive real: exactamente las mismas 3 filas y las mismas 4 columnas del dry-run cambiaron -- cero sorpresas.** 464479 y 464529 quedaron **byte-idénticos** al backup (verificado por comparación completa, no sólo por muestreo).
- **Reevaluación de destinos, exclusivamente con el mecanismo Clase A ya publicado, sin regla nueva:** **464892 SÍ resuelve** -- su dirección ("Santa Isabel 585, Lampa") calza con el mismo destino `CONFIRMADO` del catálogo que ya respalda a 3 viajes hermanos del mismo cliente (ARMACERO MATCO SA), mismas coordenadas exactas. **464730** ya tenía destino resuelto de un bloque anterior (Maipú). **464717 se verificó y sigue ambiguo (5 candidatos dispersos) -- se dejó bloqueado, sin forzar ninguna regla nueva**, tal como exige la instrucción.
- **Dry-run ORS real (sólo para los 2 viajes que quedaron con origen + destino resueltos):** **464730 → 20.18 km, 27.2 min. 464892 → 6.50 km, 10.8 min.** Ambos `RUTA_CALCULADA`, coherentes (distancias plausibles, sin anomalías). **Aplicados** -- se persistieron exactamente los valores ya calculados y verificados, **sin recalcular ninguno dos veces.** Reporte regenerado por el mecanismo canónico (`reportes/reporte_revalidacion_20260819_160555_130539/`), `estado_operacion.json` actualizado.
- **Nota de transparencia:** al verificar el estado de 464717 (paso de sólo lectura) se hizo una consulta de geocodificación real (no de ruteo) para su dirección, porque no estaba cacheada -- resultado idéntico al ya conocido (ambiguo, 5 candidatos), **nada se escribió para 464717**, y la consulta queda cacheada para no repetirse. No hubo ninguna llamada de ruteo (ORS/directions) fuera de las 2 explícitamente autorizadas y reportadas arriba.
- **Cobertura: origen 38→41 de 43 (2 sin evidencia suficiente, esperado). Km 19→21 de 43.**
- **Integridad:** sólo las 3 guías esperadas cambiaron (comparación completa de las 43 filas contra el backup); ningún campo documental (cliente/chofer/fecha/patentes/material) se tocó; catálogos (`plantas.json` y el resto) sin cambios (mtimes verificados); ledger con 3 aplicaciones nuevas, actor Javier, evidencia previa preservada.
- **Drive: modificado** -- exclusivamente `analisis_completo_guias.csv` (3 filas), `estado_operacion.json` (puntero), `decisiones_pendientes.json` (3 decisiones cerradas, 15 preexistentes intactas), `decisiones_aplicadas.json` (+3), el nuevo reporte, y (efecto secundario de sólo lectura de 464717) `geocodificacion_cache.json` (+1 entrada, ningún dato operacional). **Desktop: no modificado.**
- **Git:** Motor -- ver bloque siguiente para el commit documental de cierre. Desktop -- sin cambios en este bloque.
- **Pendiente explícito, no iniciado:** destinos B/C; deuda de `motivo_ruta` (464892 queda con el mismo patrón de texto obsoleto que 464522, sin corregir); 464717 sigue bloqueado por destino ambiguo; Incidencias Documentales; Analítica/IA; Mobile; Multiempresa.
- **Estado: CONFIRMACIONES HUMANAS DE ORIGEN APLICADAS + ESTADO OPERACIONAL REGENERADO -- LISTO PARA VALIDACIÓN VISUAL DE JAVIER.**

## Bloque AUDITORÍA INTEGRAL DE LAS 15 REVISIONES PENDIENTES + ESTADO DE RUTA 464717 -- 2026-08-19

- **100% diagnóstico, cero escritura.** Checkpoint verificado exacto: Motor `ace8608`, Desktop `a34059f`, ambos local=remoto, limpios -- confirmado con `git rev-parse`/`git status`, no asumido.
- **Inventario real de las 15 decisiones** leído directamente del artefacto vigente (`decisiones_pendientes.json`), cruzado documento por documento contra el dataset real, `vehiculos.json`, `obras_destinos.json` y `decisiones_aplicadas.json`. **Hallazgo general no anticipado:** el artefacto tiene `dataset_sha256` **obsoleto** respecto al dataset real -- consecuencia esperada de que la aplicación de ruta/km de 464730/464892 en el bloque anterior escribió el CSV directamente sin volver a publicar la bandeja. Efecto práctico: **hoy, cualquiera de las 15 fallaría con error de obsolescencia si Javier intentara aplicarla** -- de forma segura (sin corromper nada, mismo mecanismo de protección ya probado), pero requiere una reconciliación antes de que cualquiera de las 15 pueda aplicarse.
- **Caso Ortiz (464036, patente tracto):** Javier confirma que es un error documental del mandante -- **no se sustituyó esa confirmación por una inferencia automática.** Único candidato circunstancial encontrado (XF3629, del propio Ortiz en otra guía, ya CONFIRMADO en catálogo) -- pero es un `CAMION_RIGIDO` (tipo distinto a un tracto) y difiere en 2 dígitos, no 1 -- **evidencia insuficiente para ser "inequívoca"**, se reporta como posible pero no se propone como solución.
- **Caso Carlos Simón -- hallazgo limpio y contundente:** las patentes reales (**VP8521 tracto, JE8659 carro/rampla**) YA están `CONFIRMADO`/`ACTIVO` en catálogo, y quedan corroboradas de forma idéntica en **otras 3 guías reales** del mismo chofer (464698/699/700). Las 3 decisiones pendientes de este chofer (no 2, como recordaba Javier -- ver desfase de numeración abajo) son simples variantes OCR de esas mismas dos patentes. Nota aparte: Javier mencionó "JD8659"; el catálogo tiene **JE8659** (una letra de diferencia) -- se reporta la discrepancia exacta, sin asumir cuál es la correcta.
- **Desfase de numeración de Javier, confirmado:** lo que Javier identificó como ítem "8" (contenido no identificado) es en realidad la tercera decisión de Carlos Simón (464265, rampla JD0659) -- hay 3 decisiones de este chofer, no 2.
- **Hallazgo mayor no anticipado -- ítem 12 ("EMPRESA CONST SIGRO SA"):** Javier lo agrupó visualmente entre las obras "a registrar", pero la auditoría encontró que **"EMPRESA CONST SIGRO" (sin el "SA" final) ya existe, `CONFIRMADA`, para el MISMO cliente (PRODALAM SA)**, confirmada por Javier mismo el 2026-08-17 sobre la guía 464550. La única diferencia es un sufijo corporativo (" SA") que el normalizador actual no ignora -- coincide exactamente con el mismo patrón de gap ya encontrado en vehículos (comparación por texto exacto, sin tolerancia a variantes).
- **Caso "Supermercado Señor de los Milagros" (ítem 5):** **no se encontró evidencia** de que esta decisión específica haya sido aplicada antes -- ni en el ledger real (0 coincidencias) ni en el catálogo de obras (ninguna entrada similar para el cliente EBEMA SA). El recuerdo de Javier no coincide con la evidencia persistida disponible; se reporta la discrepancia para que él aclare, sin asumir ni "obsoleta" ni "nueva" en su nombre.
- **Auditoría de `NO_REGISTRAR`:** hoy sólo registra en el ledger que un STRING documental específico fue rechazado -- no escribe catálogo, no escribe CSV, y ese `decision_id` exacto nunca vuelve a aparecer (protegido por el mismo filtro de acciones terminales de `generar_artefacto`). Pero si una futura relectura del documento produjera un texto distinto (nuevo `decision_id`), Atlas SÍ volvería a preguntar -- comportamiento correcto (evidencia nueva), pero sin ningún concepto hoy de "esta patente documental está mal, la canónica es X para ESTE documento" -- ese hueco es real y general (vehículos y obras).
- **Infraestructura reutilizable:** el patrón completo (valor documental + candidato sugerido + confirmación humana + ledger auditable + preservación de evidencia) **ya existe y ya está probado** -- es exactamente `ORIGEN_NO_CONFIRMADO`. Extenderlo a vehículos/obras es, en principio, una extensión pequeña y generalizable, no un cambio estructural -- pendiente de autorización, no implementado en este bloque.
- **464717 diagnosticado con precisión:** origen ya `AZA COLINA`/`CONFIRMACION_HUMANA` (correcto), pero `estado_ruta`/`motivo_ruta` quedaron con el texto exacto de ANTES de confirmar el origen (`ORIGEN_NO_DETERMINADO`/`ORIGEN_GPS_ESTADIA_SIN_PLANTA`) porque `aplicar_decision_obra` (por diseño) sólo escribe las 4 columnas de origen, nunca recalcula ruta. **Es el mismo bug de observabilidad ya conocido (464522), y 464717 ahora lo exhibe en su forma más aguda** -- ya no sólo "enmascara" un problema de destino real, sino que además describe un origen que ya no es cierto. Estado correcto esperado: `estado_ruta=REQUIERE_REVISION`/`motivo_ruta=MULTIPLES_UBICACIONES_DISPERSAS(5)` (destino, no origen) -- confirmado que el bug afecta hoy a **3 viajes** (464479, 464522, 464717) -- 464892 quedó corregido como efecto colateral del bloque anterior.
- **Clasificación final de las 15:** REGISTRAR legítimamente = **9**. CORRECCIÓN DOCUMENTAL→CANÓNICA = **4** (las 3 de Carlos Simón + el ítem 12). REQUIERE DECISIÓN HUMANA REAL = **2** (Ortiz + Supermercado, por razones distintas). ENTIDAD YA EXISTENTE (idéntica) = 0. DECISIÓN OBSOLETA = 0. OTROS = 0. **Total = 15.**
- **Fix implementado: NO.** Sólo diagnóstico -- ninguna decisión aplicada, ningún catálogo tocado, `operacion/actual` no modificado (salvo por la sola lectura, sin escritura).
- **Drive: no modificado. Desktop: no modificado. Git: sin commit, sin push.**
- **Próximo bloque recomendado:** extender el patrón `ORIGEN_NO_CONFIRMADO` a vehículos y obras (sugerencia por asociación histórica chofer↔patente / tolerancia a sufijos corporativos en obras, siempre como sugerencia, nunca autocorrección silenciosa); reparar el refresco de `estado_ruta`/`motivo_ruta` tras cualquier confirmación de origen que no resuelva también el destino.
- **Estado: AUDITORÍA DE LAS 15 REVISIONES + ESTADO RUTA 464717 COMPLETADA -- LISTO PARA REVISIÓN CON JAVIER.**

## Bloque RECONCILIACIÓN DE REVISIÓN ATLAS + VEHÍCULO DOCUMENTAL/CANÓNICO + ESTADO DE RUTA + CONTADORES UX -- 2026-08-19

- **Checkpoint verificado exacto:** Motor `fb8ba95` (working tree limpio antes de empezar), Desktop `a34059f` limpio.
- **Ground truth de Carlos Simón, actualizado por Javier a mitad de bloque:** la rampla correcta es **JD8659** (confirmada directamente con el chofer) -- **JE8659** (lo que aparece 3 veces en el dataset, ya `CONFIRMADO` en catálogo) se trata como posible error documental de un mandante, nunca como canónica por repetirse. **JD8659 todavía no existe en el catálogo real -- no se registró en este bloque**, tal como exigió la instrucción.
- **Auditoría con evidencia visual (imágenes reales de las guías, no sólo el CSV):** 464264 y 464265 (cliente SODIMAC SA) imprimen literalmente **"PATENTE: VP8521 CARRO:JD8659"** -- el documento en sí ya es correcto, coincide exactamente con el ground truth de Javier; el error es de **extracción OCR de Atlas** (JD8659 leído como JD6659/JD0659, VP8521 leído como VP6521), no del documento. 464698/699/700 (cliente EBEMA SA) imprimen **"CARRO:JE8659"** -- un valor sistemático del sistema de otro mandante, repetido porque es la MISMA fuente, no tres verificaciones independientes.
- **Mecanismo VEHÍCULO documental→canónico implementado, reutilizando `ORIGEN_NO_CONFIRMADO`** (mismo patrón, sin sistema paralelo): sugerencia por asociación histórica de RUT de chofer (nunca autocorrección -- **repetición documental NUNCA decide por mayoría**, control crítico verificado con datos reales: JE8659 con 3 documentos NO se prefiere automáticamente sobre JD8659 con 1). Dos acciones nuevas -- `USAR_PATENTE_EXISTENTE`/`SELECCIONAR_OTRA_PATENTE` -- se suman a `REGISTRAR`/`NO_REGISTRAR`/`POSPONER` ya existentes (nunca las reemplazan). `NO_REGISTRAR` extendido con `motivo_rechazo` opcional (100% compatible con lo ya existente) -- cubre el caso Ortiz exactamente.
- **Caso Ortiz cerrado conceptualmente:** único candidato circunstancial (XF3629, mismo chofer, un solo documento, tipo de vehículo distinto) se sugiere transparentemente pero **nunca se fuerza** -- Javier puede rechazarlo con `NO_REGISTRAR(motivo_rechazo="ERROR_DOCUMENTAL_MANDANTE")`, preservando el valor documental, sin inventar sustituto, con evidencia auditada en el ledger.
- **Reconciliación general de la bandeja** (`reconciliar_bandeja_decisiones`, nueva): refresca `dataset_sha256`/`catalogos_sha256` sin re-ejecutar OCR ni tocar el CSV/catálogos -- soluciona la obsolescencia de las 15 detectada en el bloque anterior. **Validado con datos reales en TEMP: las 15 decisiones se conservan, el hash queda idéntico al dataset real, ninguna decisión ya cerrada resucita.**
- **Hallazgo corregido durante la validación TEMP (no en el diseño original):** aplicar CUALQUIER decisión (incluso una no relacionada) regeneraba internamente toda la bandeja y borraba silenciosamente las acciones enriquecidas de otras decisiones de vehículo -- corregido antes de publicar, con test de regresión dedicado. También se encontró y corrigió que la comparación de RUT de chofer no toleraba formato inconsistente (con/sin puntos) entre documentos del mismo chofer -- real en el dataset (464699).
- **Refresco de `estado_ruta`/`motivo_ruta` implementado y generalizado** (nunca un parche sólo para 464717): tras cualquier confirmación de origen (humana o por telemetría) que deje el destino todavía sin resolver, el texto pasa a expresar el bloqueo REAL de destino (`REQUIERE_REVISION`/`DESTINO_<estado_entrega>`) en vez de seguir describiendo un origen que ya se resolvió -- nunca fuerza `RUTA_CALCULADA`. Wireado en las dos rutas de confirmación de origen existentes (`ORIGEN_NO_CONFIRMADO` y `revalidar_telemetria_sin_ocr`).
- **Contadores Desktop, causa exacta demostrada desde código:** "36/38" es el filtro de período ("Este mes") aplicado sobre 38 viajes reales (2 de julio quedan fuera); las tarjetas de resumen YA se calculan sobre lo filtrado, no sobre el total -- confirmado programáticamente contra el reporte real (36 dentro de agosto, 23 confirmados, 13 no confirmados -- coincide exacto con lo que vio Javier). "13" (viajes) y "15" (decisiones) son conteos de ENTIDADES DISTINTAS por diseño -- matriz de conciliación construida con datos reales: 8 de los 13 viajes cubren exactamente las 15 decisiones, 5 no tienen ninguna decisión accionable (bloqueados por otros motivos documentales), 0 decisiones huérfanas. **Sólo se cambió texto, nunca lógica**, según instrucción explícita.
- **Tests: 25 nuevos en Motor** (`tests/test_vehiculo_documental_canonico.py`) + **3 nuevos en Desktop** (contadores explícitos). **Motor: 1316 passed, 0 failed** (baseline 1291+25). **Desktop: 214 passed, 0 failed** (baseline 211+3).
- **Validación TEMP con datos reales** (nunca Drive): reconciliación real de las 15 -- confirmado 3 documentos corroborando JE8659 (464698/699/700) y 4 corroborando VP8521; Ortiz simulado con `NO_REGISTRAR`+motivo, ledger completo con `candidatos_previos` preservados, 0 vehículos registrados; intento de `SELECCIONAR_OTRA_PATENTE(JD8659)` rechazado correctamente (no está en catálogo) -- **nada de esto se aplicó a Drive real.**
- **Drive: no modificado** (mtimes re-verificados idénticos). **Catálogos: no modificados** (vehículos sigue en 20, sin JD8659). **15 decisiones reales: sin aplicar.**
- **Git:** Motor y Desktop -- ver bloque de publicación (commit/push de los fixes de código, NO de las 15 decisiones reales).
- **Pendiente explícito, no iniciado:** aplicar las 15 decisiones reales (ahora reconciliadas, requiere que Javier las revise una por una); decidir JD8659 vs JE8659 en catálogo real; destinos B/C; Incidencias Documentales; Analítica/IA; Mobile; Multiempresa.
- **Estado: REVISIÓN ATLAS RECONCILIADA A NIVEL DE CÓDIGO -- LISTO PARA REGENERACIÓN CONTROLADA DE BANDEJA REAL.**

## Bloque REGENERACIÓN CONTROLADA DE BANDEJA REAL DE REVISIÓN -- 2026-08-19

- **Checkpoint verificado exacto:** Motor `2b43452`, Desktop `7ad5cc9`, ambos local=remoto, limpios.
- **Backup pre-aplicación:** `respaldos/RECONCILIACION_BANDEJA_ROLLBACK_PRE_APLICACION_20260819_134448/` -- auditado el mecanismo real (`reconciliar_bandeja_decisiones`) ANTES de decidir el alcance: sólo escribe `decisiones_pendientes.json` (confirmado por lectura de código, no supuesto) -- backup y manifiesto SHA-256 limitados a ese único archivo, verificado byte a byte.
- **Dry-run completo en TEMP con datos reales:** reconciliación completa comparada decisión por decisión -- **las 15 decisiones permanecen con `decision_id` idéntico** (misma evidencia, ninguna se pierde ni se inventa), **0 decisiones nuevas espurias**. Sólo 4 ganan candidatos por asociación histórica de RUT (Ortiz→XF3629; las 3 de Carlos Simón→VP8521/JE8659), el resto queda exactamente igual. `dataset_sha256` pasa de obsoleto a coincidir exactamente con el dataset real.
- **Carlos Simón:** las 3 decisiones siguen pendientes tras regenerar, ahora con JE8659 sugerido (nunca forzado). **JD8659 sigue sin registrar** -- verificado que un intento de elegirla se rechaza correctamente (`ErrorAplicacionDecision`, no existe en catálogo). Lo que Atlas debería preguntarle a Javier ahora: para cada una de las 3 lecturas erróneas, ¿usar JE8659 (ya en catálogo, aunque el ground truth del chofer diga que es un posible error de otro mandante) o esperar a que JD8659 se registre primero?
- **Ortiz:** verificado (en copia aislada, nunca aplicado a Drive) que `NO_REGISTRAR(motivo_rechazo="ERROR_DOCUMENTAL_MANDANTE")` cierra la decisión correctamente, sin tocar catálogo ni CSV.
- **Supermercado Señor de los Milagros:** sigue exactamente igual -- sin evidencia de resolución previa, sin candidatos (obras no recibieron el mecanismo de sugerencia en este bloque, sólo vehículos).
- **464717 -- hallazgo honesto, no ocultado:** la regeneración de bandeja **no toca `analisis_completo_guias.csv`** (fuera de su alcance por diseño) -- 464717 sigue mostrando `estado_ruta=ORIGEN_NO_DETERMINADO` en el dataset real. Verificado que la función de refresco (`derivar_estado_ruta_tras_cambio_origen`, publicada en el bloque anterior) SÍ sabe corregirlo (`REQUIERE_REVISION`/`DESTINO_REVISAR`) si se le invoca -- pero la corrección es **prospectiva, no retroactiva**: sólo se dispara automáticamente en una NUEVA confirmación de origen, y la de 464717 ya se aplicó en un bloque anterior, antes de que este mecanismo existiera. Reportado explícitamente como pendiente -- requiere un paso pequeño y separado, no incluido en este bloque (que se limitó a regenerar la bandeja).
- **Contadores:** sin cambios respecto al bloque anterior (la regeneración de bandeja no toca `viajes.csv`) -- 38 viajes, 25 confirmados, 13 requieren revisión; dentro de "Este mes": 36/23/13; documentos 43 (41 dentro de agosto); 15 decisiones pendientes de Atlas (mismas 15, ahora reconciliadas).
- **Aplicado a Drive real: SÓLO la regeneración de la bandeja.** Verificado campo a campo: los 15 `decision_id` son idénticos antes/después: `dataset_sha256` ahora coincide con el dataset real; catálogos (`vehiculos.json`=20, `obras_destinos.json`=15, `clientes.json`) con mtime idéntico; CSV documental con mtime idéntico; ledger con mtime idéntico. **Ninguna decisión aplicada. JD8659 no registrada. Ninguna obra registrada.**
- **Rollback: NO requerido** -- ningún efecto no deseado detectado.
- **Git:** Motor y Desktop -- commit documental de bitácoras al final (ver hashes reales en el checkpoint siguiente).
- **Pendiente explícito, no iniciado:** que Javier resuelva las 15 decisiones una por una en Desktop; refresco retroactivo de `estado_ruta`/`motivo_ruta` para 464717 (paso pequeño, separado, no autorizado en este bloque); decidir JD8659 vs JE8659 en catálogo real; destinos B/C; Incidencias Documentales; Analítica/IA; Mobile; Multiempresa.
- **Estado: BANDEJA REAL DE REVISIÓN ATLAS REGENERADA Y RECONCILIADA -- LISTA PARA QUE JAVIER RESUELVA LAS DECISIONES UNA POR UNA.**

## Baseline operacional limpio — reevaluación de los 7 viajes — 2026-08-20

- Se reevaluaron exclusivamente los 7 viajes vigentes en `REQUIERE_REVISION` con Motor determinístico, catálogos, ledger/histórico y Atlas IA B1 sobre Groq (`openai/gpt-oss-120b`).
- Resultado: **0 `RESOLUBLE_HOY`; 7 `AMBIGUEDAD_REAL`**. B1 produjo 2 asistencias de nivel B y 4 abstenciones de nivel C; ninguna propuesta alcanzó evidencia suficiente para aplicación autónoma.
- La revalidación canónica se ejecutó sobre una copia aislada de los datos reales: 43 filas, 0 guías actualizadas y 0 reportes regenerados. Por ello no se escribió la operación real ni se publicó un reporte artificialmente distinto.
- Desktop se comprobó visualmente con el filtro `Requiere revisión`: 7 viajes / 10 documentos, coherente con el reporte vigente.
- No se ejecutó OCR, no se modificaron catálogos, dataset, ledger, Mobile ni el lote nuevo. No hubo cambio funcional ni tests aplicables.
- **Estado: BASELINE OPERACIONAL LIMPIO: SÍ** — las 7 revisiones restantes representan evidencia ausente, contradictoria o un error documental ya rechazado sin sustituto seguro.
# 2026-08-20 — R4 basado en RUN real

R4 corrigió extracción crítica, uso conservador de documentos relacionados e
histórico, semántica de vehículos, estados documental/routing separados e
integración shadow de Atlas IA. Suite completa: 1.526 pruebas. Replay aislado:
112,17 s para diez documentos; holdout 472044/472073 ejecutado una sola vez y
sin correcciones posteriores. Detalle en `R4_RUN_REAL_Y_HOLDOUT_20260820.md`.
# 2026-08-20 — R4.7 B1 operacional

B1 quedó integrado al pipeline común Desktop/Mobile. E2E real Groq: una llamada,
B_ASISTENCIA validada, 1,727 s. Reset preparado y probado sólo en aislamiento;
operación real intacta. Ver `R4_7_B1_OPERACIONAL_Y_RESET.md`.
# 2026-08-21 — Cierre VEHICULO_DESCONOCIDO/CAMION_RIGIDO (caso Ortiz/XF3629)

Causa: `detectar_decisiones_documento` seguía filtrando `patente_tracto`
aislada exclusivamente por `TRACTO`, sin reconocer `CAMION_RIGIDO` --
inconsistente con la homologación documental (P2) y con
`revalidar_patente_sin_homologar_sin_ocr`, que ya trataban ambos tipos como
compatibles para ese rol. Una patente ya `CONFIRMADO`/`ACTIVO` volvía a
generar `VEHICULO_DESCONOCIDO` en cada reproceso -- Viajes mostraba OK,
Revisión de Atlas seguía pidiendo registrarla. Reproducido con datos reales
del checkpoint R4 (guía 472073).

Fix general (commit `3632ff3`): mismo criterio TRACTO/CAMION_RIGIDO ya
establecido en los otros dos lugares del pipeline, aplicado también en
detección. `patente_rampla` no se toca. 4 tests focales nuevos; suite
completa 1533 passed.

**Aplicado a Drive real:** `regenerar_decisiones_persistidas` +
`generar_artefacto` sobre `operacion/actual/decisiones_pendientes.json`
(mecanismo canónico, sin OCR, sin reprocesar el lote). Backup previo
verificado byte a byte en
`respaldos/LIMPIEZA_VEHICULO_DESCONOCIDO_XF3629_R4_20260821_090507/`.
Bandeja real: **3 → 2 decisiones** -- `VEHICULO_DESCONOCIDO`/XF3629 (guía
464991, chofer Ortiz) cerrada; las 2 `OBRA_DESCONOCIDA` legítimas se
conservan con `decision_id` idéntico. Verificado por SHA-256: catálogos,
CSV documental, ledger y `estado_operacion.json` sin cambios -- sólo se
escribió `decisiones_pendientes.json`. Control con patente realmente
desconocida, contra el catálogo real: sigue generando su decisión.

**Estado: CASO ORTIZ/XF3629 CERRADO EN CÓDIGO Y EN DRIVE REAL. Sin push.**
# 2026-08-21 — Coherencia Viaje ↔ Revisión de Atlas + limpieza de detalle (472037/464981)

Causa: un motivo de revisión (`CLIENTE_SIN_CORROBORAR`, `OBRA_DESTINO_SIN_CORROBORAR`)
podía quedar fijado en el dataset sin ningún mecanismo capaz de generar una
decisión accionable ni de retirarlo -- el viaje quedaba eternamente en
`REQUIERE_REVISION` sin aparecer en Revisión de Atlas. Casos reales: 472037
(cliente sin RUT documental corroborable) y 464981 (`obra_destino` ==
`cliente`, "mismo hecho documental dos veces" -- Motor ya se abstenía en
detección pero el motivo del dataset no tenía vía de salida).

Fix general (commit `208372a`): (1) `CLIENTE_CANDIDATO` -- tipo reservado
desde R3.1, nunca implementado -- ahora genera una decisión accionable
cuando el nombre documental coincide (difuso o por alias, mismo motor ya
calibrado para chofer/`empresas.json`) con un cliente `CONFIRMADO`/`ACTIVO`,
con backend completo (detección, aplicación, revalidación, reconstrucción
histórica sin OCR) y encadena la pregunta de obra/destino tras confirmarse.
(2) `revalidar_obra_destino_sin_ocr` retira el motivo cuando obra y cliente
de la misma fila son el mismo texto. 14 tests focales; suite completa 1545
passed.

**Aplicado a Drive real:** backup verificado
(`respaldos/COHERENCIA_REVISION_ATLAS_R48_20260821_102802/`) →
`revalidar_y_regenerar_reporte` (464981: motivo retirado, `OK`) +
`reconciliar_decisiones_cliente_candidato_historico` (472037: decisión
`CLIENTE_CANDIDATO` reconstruida sin OCR, apuntando a "COMERCIAL A Y B
LTDA"). Catálogos y ledger sin cambios (verificado SHA-256); XF3629 sigue
sin reaparecer; control con patente desconocida sigue generando decisión.

**Desktop (commit `36411aa`, rama `fix-desktop-data-root-drag-drop`):**
detalle de viaje ya no repite fecha/N° guía/cliente único/chofer único
(la fila principal ya los trae); cliente(s)/chofer(es) sólo reaparecen con
más de un valor real (multiguía 464959/464960 verificado: mismo cliente y
chofer en ambos documentos, no se repite). Logística retira el rótulo
"Estado ruta"/"Ruta calculada"; aviso discreto sólo si la ausencia de
km/tiempo es operacional (origen/destino sin determinar), nunca por un
problema técnico. `DOCUMENTO_REQUIERE_REVISION` se retira cuando ya hay un
motivo específico (caso 472037). 238 tests, 0 failing.

**Estado: CASO 472037/464981 CERRADO EN CÓDIGO Y EN DRIVE REAL. Sin push
en ninguno de los dos repos.**
# 2026-08-21 — Cierre final 472037 (obra registrada sin destino) + badges de pestaña

Tras confirmar el `CLIENTE_CANDIDATO` de 472037, Javier registró la obra
encadenada ("ING Y CONST FUNDAMENTA SPA") -- pero sin destino documental
capturado (`despachar_a_crudo` vacío), `REGISTRAR` es terminal por diseño
(CASO C, no genera decisión siguiente) y `OBRA_DESTINO_SIN_CORROBORAR`
quedaba fijado en el CSV sin vía de salida: viaje en revisión, 0
decisiones pendientes -- el limbo "REVISAR pero nadie puede hacer nada".

Fix general (commit `3b30076`): `revalidar_obra_destino_sin_ocr` gana un
`ruta_ledger` opcional -- cualquier aplicación terminal de OBRA_DESCONOCIDA
o DESTINO_SIN_CONFIRMAR para ese `numero_guia` exacto retira el motivo
(mismo patrón que los índices de ledger ya usados para patente/cliente).
6 tests focales, incluido un end-to-end del flujo real completo. Suite
completa: 1551 passed.

**Aplicado a Drive real:** backup verificado
(`respaldos/CIERRE_472037_OBRA_SIN_DESTINO_R49_20260821_105557/`) →
`revalidar_y_regenerar_reporte`. 472037: motivo retirado, `OK`, 0
decisiones pendientes (correcto -- nada más que preguntar). Catálogos y
ledger sin cambios; XF3629 sigue sin reaparecer; control con patente
desconocida sigue generando decisión.

**Desktop (commit `09b23b2`, rama `fix-desktop-data-root-drag-drop`):**
contraste de los contadores de pestaña ("Sin número de transporte",
"Revisión de Atlas") corregido -- `--amber` pasa de `#b45309` (~4,5:1
sobre `--amber-bg`, al límite de WCAG AA y perceptualmente lavado contra
el fondo general de la app) a `#805312` (~5,9:1), el mismo tono ya usado
y probado en `.motivo-chip` de la misma página -- ningún color nuevo, sólo
el ya validado en la UI. 4 tests focales de contraste (WCAG calculado
sobre los valores reales del CSS). 242 tests, 0 failing.

**Estado: CASO 472037 CERRADO POR COMPLETO. Sin push en ninguno de los dos
repos.**
# 2026-08-21 — Bloque afinación operacional: rutas + orden + peso + badges

Causa raíz #1: un destino RECHAZADO (confianza insuficiente o comuna
documental contradicha) seguía escribiendo su etiqueta en
`direccion_entrega` -- lo que Desktop muestra como destino -- aunque
`estado_ruta` ya lo marcaba sin resolver. Casos reales: 460807 ("Angol"
en vez de San Bernardo) y 472008 (degradado a "Chile").

Causa raíz #2, hallada por el propio dry-run antes de tocar producción:
la detección de "comuna documental" tomaba la PRIMERA coincidencia contra
el catálogo territorial (345 comunas) -- caso real 472002 "GALVARINO 8501
QUILICURA": "Galvarino" es la calle, pero también existe una comuna real
con ese nombre en otra región, así que el chequeo iba a rechazar un
destino YA CORRECTO. Corregido con `_comuna_documental_inequivoca`:
sólo contradice cuando el texto menciona EXACTAMENTE una comuna real
distinta, nunca la primera de varias en conflicto.

Fix (commit `fd31579`): destino rechazado nunca expone etiqueta/localidad
(coordenadas se conservan como auditoría); limpieza retroactiva sin OCR/
sin red para datos ya persistidos; `revalidar_ruta_sin_destino_calculado_
sin_ocr` reintenta ruta (con caché real) para filas con planta+destino ya
persistidos sin ruta -- recuperó 464991 (7,38 km / 11,78 min reales, vía
ORS), bloqueado antes por la misma ambigüedad de comuna que 472002. 19
tests focales. Suite completa: 1569 passed.

**Aplicado a Drive real:** backup verificado
(`respaldos/BLOQUE_RUTAS_ORDEN_PESO_BADGES_R410_20260821_120950/`) →
`revalidar_y_regenerar_reporte` + `revalidar_ruta_sin_destino_calculado_
sin_ocr`. Métricas del dataset real (9 viajes):

| | Antes | Después |
|---|---|---|
| Con km/tiempo | 3 (464945, 464959\|464960, 472002) | 4 (+464991) |
| Destino degradado/absurdo | 2 (460807="Angol", 472008="Chile") | 0 |
| Con planta origen | 7/9 | 7/9 (sin cambio -- 464981/472037 sin evidencia GPS, correctamente vacíos) |
| Falsos positivos introducidos | — | 0 (472002 protegido explícitamente) |

Catálogos y ledger sin cambios (verificado SHA-256); 0 decisiones
pendientes espurias; XF3629 sigue sin reaparecer.

**Desktop (commit `98ccc5c`, rama `fix-desktop-data-root-drag-drop`):**
badges de pestaña con fondo SÓLIDO + texto blanco (~6,6:1, ya no
pastilla pálida-sobre-pálida); orden por afinidad (chofer/RUT/patente
tracto) deja 460807/472008 contiguos sin fusionarlos; "Viaje consolidado"
agrega "Total del viaje" en multiguía (464959/464960 = 11.429 kg,
regresión positiva verificada) y ya no se repite en Información
operacional. 24 tests focales/actualizados. 252 tests, 0 failing.

**Estado: BLOQUE RUTAS/ORDEN/PESO/BADGES CERRADO EN CÓDIGO Y EN DRIVE
REAL. Sin push en ninguno de los dos repos.**

## Bloque R5 -- Producto integral: planta origen + Envíos Mobile + jerarquía visual (2026-08-21)

**Motor (`Proyecto-Atlas`):**
- **Planta origen (Parte A/B):** el mecanismo `ORIGEN_NO_CONFIRMADO`
  (detección + aplicación + reconciliación) ya existía completo desde un
  bloque anterior pero nunca se invocaba desde ningún punto de entrada
  real -- caso real 472037 quedaba con origen vacío sin ninguna pregunta
  visible. Se conectó (`reconciliar_decisiones_origen`, sin cambios de
  código, sólo aplicación real) -- 472037 ahora ofrece AZA RENCA/AZA
  COLINA como candidatas con su evidencia GPS real (score=0.104/0.0559),
  nunca fuerza una. 464981 sigue correctamente sin pregunta (evidencia
  demasiado escasa -- `SIN_TRIPS_EN_VENTANA_TEMPORAL`). Ninguna
  arquitectura nueva.
- **"Sin número de transporte" (Parte I):** clasificación general de 3
  causas, nunca por guía/cliente: si la etiqueta "NRO...TRANSPORTE" nunca
  aparece en el OCR y el documento no está degradado -> omisión
  documental, registrada automáticamente como Incidencia Documental
  (`TRANSPORTE_AUSENTE_DOCUMENTAL`, `reconciliar_incidencias_transporte_
  documental`), nunca bloquea Revisión de Atlas. Si la etiqueta aparece
  pero Atlas no logra leer el número -> `TRANSPORTE_AUSENTE` normal,
  sigue bloqueando (sin cambios). Si el documento está degradado en
  general -> ya cubierto por `DOCUMENTO_DEGRADADO` existente. 0 casos
  reales hoy (los 10 documentos actuales tienen transporte); mecanismo
  queda listo hacia adelante. 9 tests focales.
- Suite completa: 1579 passed (antes 1569).
- Aplicado a Drive real: backup verificado
  (`respaldos/R5_AB_20260821_131053/`) → `reconciliar_decisiones_origen`.
  CSV/catálogos/ledger sin cambios (SHA-256 verificado); bandeja pasó de
  0 a 1 decisión pendiente (472037, legítima); 9 viajes/9 confirmados/0
  revisión sin degradar; 464959+464960 siguen en 11.429 kg / 22,94 km /
  32,96 min; XF3629 sigue sin reaparecer.

**Desktop (`Atlas-Viajes-Desktop-Restaurado`):**
- **Envíos Mobile (Parte E/F):** pestaña nueva, historial completo de
  todos los envíos Mobile de todos los choferes en cualquier estado
  (`cargarEnviosMobileHistorial`, IPC nuevo en `main.js`/`preload.js`,
  misma carpeta/contrato M1 que ya usa `cargarEnviosMobilePendientes` --
  ningún flujo paralelo). Filtros: chofer, estado, período, texto libre.
  Un envío ASOCIADO queda sólo aquí, como historial; uno
  REQUIERE_REVISION aparece aquí Y en Revisión de Atlas mientras esté
  pendiente.
- **Navegación (Parte G):** pestañas rediseñadas de subrayado-sobre-texto
  a módulos con borde/relieve propio y estado activo de fondo lleno.
- **Indicadores (Parte H):** las 4 tarjetas altas se comprimieron en una
  franja compacta en línea -- mismas 4 métricas, mismos colores de
  estado.
- **"Sin número de transporte" (Parte I):** pestaña de carga manual de
  CSV eliminada por completo (código muerto, sin relación con datos
  Mobile en vivo); sus casos reales quedan cubiertos por Incidencias
  Documentales (ya genérica, sin cambios de renderizado) y Revisión de
  Atlas.
- **Total del viaje (Parte K):** movido del resumen superior (junto a N°
  transporte/RUT/planta) al pie de la propia tabla de materiales/peso,
  como fila de cierre (`<tfoot>`) -- 464959/464960 siguen en 11.429 kg.
- 20 tests focales nuevos/actualizados. Suite completa: 264 passed (antes
  252).

**Estado: BLOQUE R5 CERRADO EN CÓDIGO Y EN DRIVE REAL. Sin push en
ninguno de los dos repos.**

## Bloque R6 A/B/E -- ciclo de vida completo origen→destino→ruta (2026-08-21)

**Causa raíz de los 5 viajes sin km/tiempo:** ninguna es la misma.
460807/472008/472018 ya tenían un problema real de geocodificación
(comuna contradicha/resultado genérico/ubicaciones dispersas) desde antes
de este bloque -- correctamente rechazados, nunca expuestos como ruta
inventada. 472037 es distinto: origen se confirmó bien
(`ORIGEN_NO_CONFIRMADO`, Bloque R5), pero el documento nunca trajo
ninguna dirección de entrega (`DESTINO_SIN_DATO`) -- ni catálogo, ni
histórico, ni relación confirmada tenían nada que ofrecer (la obra "ING Y
CONST FUNDAMENTA SPA" se registró sin destino asociado). 464981 sigue sin
planta -- telemetría no encontró ningún trip en la ventana documental
(`SIN_EVIDENCIA_GPS`), evidencia insuficiente incluso para sugerir una
candidata; se mantiene la abstención ya diseñada (mismo criterio que
464479/464529) -- preguntar sin nada que mostrar sería adivinar delegado
a un humano.

**El gap real (los 4 con planta ya resuelta):** el mecanismo determinista
ya rechazaba correctamente cada destino degradado/ambiguo, pero ninguno
de esos rechazos se convertía en una decisión accionable -- el humano
nunca veía nada en Revisión de Atlas, sólo "No disponible" en Desktop.
Se cierra con `DESTINO_NO_RESUELTO` (detección + aplicación +
reconciliación, mismo patrón que `ORIGEN_NO_CONFIRMADO`): con origen
resuelto y un motivo de destino reconocido, Atlas pregunta. Al escribir
la dirección real, se revalida con el MISMO mecanismo determinista ya
existente (`revalidar_ruta_sin_destino_calculado_sin_ocr`, con su
rechazo de comuna/genérico/disperso intacto) -- nunca se acepta a
ciegas. Si la ruta se calcula, la relación obra↔destino queda CONFIRMADA
en el catálogo ya existente -- documentos futuros de la misma obra
resuelven solos, sin volver a preguntar.

**Atlas IA B1:** 0 llamadas para el problema de destino en los 5 casos,
explicado -- la escalada a B1 (`_ejecutar_ia_operacional`) está acotada,
por diseño, a 4 motivos de corroboración documental (obra/chofer/
patente/cliente), nunca a `motivo_ruta`. Verificado en datos reales: 2 de
los 5 (460807, 472008) sí tuvieron una llamada B1 real, pero para
`OBRA_DESTINO_SIN_CORROBORAR` (ya resuelto aparte), nunca para el
problema de ruta. No se extendió el alcance de B1 en este bloque (fuera
de alcance -- "no refactor grande", "no nuevo proveedor IA").

**Aprendizaje:** cada `REGISTRAR_DIRECCION` exitoso registra la relación
obra↔destino en `catalogo_obras_destinos` (mismo catálogo que ya usa
`resolver_obra_destino_confirmada_global`) -- nunca una memoria paralela.

29 tests focales nuevos (12 Motor + 6 Desktop UI/wiring + 11 ya
existentes actualizados). Suite completa: Motor 1591 passed (antes
1579); Desktop 270 passed (antes 264).

**Aplicado a Drive real:** backup verificado
(`respaldos/R6_AB_20260821_150352/`), dry-run previo,
`reconciliar_decisiones_destino_no_resuelto` ejecutado. CSV/catálogos/
ledger sin cambios (SHA-256 verificado); bandeja: 4 decisiones nuevas
(460807, 472008, 472018, 472037), 0 sin causa real. 9 viajes/9
confirmados/0 revisión sin degradar; 464959+464960 intactos (11.429 kg/
22,94 km/32,96 min); XF3629 correctamente resuelto (CONFIRMADO), no
stuck en la bandeja. No se escribió ninguna dirección real para 472037
-- Atlas no la conoce y no se inventa; queda como decisión accionable
pendiente de que Javier la escriba (outcome B del bloque, nunca
silencio).

**Estado: BLOQUE R6 CERRADO EN CÓDIGO Y EN DRIVE REAL. Sin push en
ninguno de los dos repos.**

## Bloque R7 -- B1 universal: capa cognitiva transversal (2026-08-21)

**Limitación anterior:** `procesamiento_masivo._ejecutar_ia_operacional`
escalaba a B1 sólo para 4 motivos hardcodeados en un diccionario fijo
(`OBRA_DESTINO_SIN_CORROBORAR`/`CHOFER_SIN_CORROBORAR`/
`PATENTE_SIN_HOMOLOGAR`/`CLIENTE_SIN_CORROBORAR`). El orquestador
(`atlas_ia/orquestador.py`) y los contratos (`contratos.py`,
`validadores.py`) ya eran genéricos por diseño -- el cuello de botella
vivía enteramente en ese diccionario del punto de entrada, nunca en la
capa de razonamiento.

**Arquitectura universal implementada:** nuevo
`atlas_core/atlas_ia/registro_problemas.py` -- un REGISTRO de
`TipoProblemaIA` (código(s) de motivo activador, dominio, campo,
recolector de evidencia propio, herramientas relevantes, si se auto-
aplica o sólo asiste). `_ejecutar_ia_operacional` se reescribió para
despachar por este registro (`detectar_problemas_elegibles`) en vez del
diccionario fijo -- agregar un problema nuevo es agregar UNA entrada,
nunca tocar el bucle. Puerta de entrada generalizada
(`_fila_requiere_atencion_operacional`): ya no depende sólo de
`indicador_revision == REVISAR` (que nunca veía problemas de ruta/
origen) -- también mira `estado_ruta`.

**Dominios habilitados:** los 4 de siempre (comportamiento IDÉNTICO,
verificado por regresión) + 2 nuevos: DESTINO (Bloque R6, evidencia por
obra relacionada con entrega ya resuelta) y PLANTA_ORIGEN (Bloque R5,
reutiliza EXACTAMENTE los candidatos que ya calcula
`detectar_decision_origen_no_confirmado` -- nunca un cálculo nuevo).
Ninguno de los 2 nuevos se auto-aplica -- sólo alimentan, como evidencia
adicional, la decisión humana ya existente (`DESTINO_NO_RESUELTO`/
`ORIGEN_NO_CONFIRMADO`) -- Motor y confirmación humana siguen mandando.
`NO_ELEGIBLE_IA` explícito para motivos técnicos externos
(`MOTIVOS_RUTA_TECNICOS_NO_ELEGIBLES`: sin credencial/conexión/proveedor
caído/límite de cuota/etc.) y para evidencia genuinamente insuficiente
(p.ej. `SIN_EVIDENCIA_GPS`) -- nunca un silencio de "0 llamadas" sin
explicación.

**Prueba E2E real (Groq, `openai/gpt-oss-120b`), 2 dominios distintos,
sin tocar producción (copia controlada):**
- DESTINO: guías reales 460807 + 472008 (ambas con problema real de
  geocodificación) + 1 documento fixture representativo de la misma obra
  real "AUSIN SAN BERNARDO" con entrega ya resuelta (política explícita
  del bloque: "si no existen dos casos reales, uno real + fixture"). 2
  llamadas reales, ambas B_ASISTENCIA -- propuesta razonada, evidencia
  usada, validador aceptó la hipótesis, nunca se auto-aplicó
  (`despachar_a_crudo` intacto en ambas).
- CLIENTE_SIN_CORROBORAR: fixture representativo (hoy sin caso real
  pendiente -- los 9 viajes reales están confirmados), mismo patrón
  exacto que ya usa producción. 1 llamada real, B_ASISTENCIA, tampoco se
  auto-aplicó (evidencia nivel DOCUMENTO_RELACIONADO nunca alcanza clase
  A -- mismo límite que ya regía antes de este bloque).
- Total: 3 llamadas reales a Groq, 0 escrituras indebidas, validadores
  gobernando la aceptación en los 3 casos.

**Aprendizaje:** cada llamada queda trazada en `resultado_atlas_ia_json`
(dominio/campo/elegible/llamada_realizada/clasificación/evidencia/
validación) -- ninguna memoria paralela; el aprendizaje de decisiones
humanas sigue viviendo en los mecanismos ya existentes (ledger,
catálogos, `catalogo_obras_destinos`).

**Compatibilidad:** 464959/464960, XF3629, 9 confirmados/0 revisión,
decisiones R5/R6, Incidencias Documentales -- sin cambios de código en
esas rutas; Desktop no requirió ningún cambio (consume
`resultado_atlas_ia_json` sin parsear su forma interna).

17 tests focales nuevos + toda la suite existente sin cambios de
comportamiento para los 4 dominios de siempre. Suite completa: 1608
passed (antes 1591).

**No se aplicó nada a Drive real en este bloque** -- el registro es
código nuevo que empieza a operar en el próximo procesamiento real; no
había ninguna escritura retroactiva segura que hacer (los 2 dominios
nuevos nunca escriben solos, y los 4 de siempre no cambiaron de
comportamiento).

**Estado: BLOQUE R7 CERRADO EN CÓDIGO, VALIDADO END-TO-END CON GROQ
REAL EN 2 DOMINIOS. Sin push en ninguno de los dos repos.**

## Bloque R8 -- evidencia operacional real de AZA RENCA (2026-08-21)

**Investigación previa (sin código nuevo):** se localizó, en la propia
caché real de telemetría (`cache/telemetria/telemetria_cache.json`), el
patrón GPS real que corresponde a la evidencia que Javier describió --
patente SB6486, 2026-08-06: permanencia real cerca de AZA RENCA de
~10:26 a ~12:22, con 2 ciclos reales ENGINE_OFF/ENGINE_ON dentro de esa
permanencia y salida definitiva confirmada a las 13:48:46 -- puntos con
velocidad 0 a 0,22-0,44 km del punto documental ya confirmado (LA UNION
3070, RENCA). Se comprobó, contra esta evidencia real, que el mecanismo
YA existente (`resolver_planta_origen_gps`, Bloque TELEMETRÍA T3;
`atlas_ia.registro_problemas`, Bloque R7) discrimina correctamente RENCA
vs COLINA usando permanencia real (no un ping aislado) -- CERO cambios
de código hicieron falta en la lógica de resolución.

**Incorporación al catálogo real (mismo mecanismo que ya usa AZA COLINA,
Bloque PLANTAS P3 -- ninguna memoria paralela):** `latitud`/`longitud`
de AZA RENCA quedan SIN CAMBIAR (ya exactas, confidence=1.0); se agregó
`punto_ruteo_latitud/longitud` con el centroide real de los puntos de
permanencia (0,29 km del punto documental, dentro de la geocerca
circular por defecto de 1,5 km -- no hizo falta ampliarla ni convertir a
poligonal); `observacion` documenta fuente (CONFIRMACION_HUMANA +
EVIDENCIA_GPS_OPERACIONAL), autoridad (alta), evidencia (trips
OneLogis reales 30539854/30540537/30542187/30543835) y trazabilidad
completa, mismo formato ya usado en AZA COLINA.

**Prueba real (3 casos, datos GPS reales, sin tocar producción hasta
validar):**
- Caso 1 (patrón real de RENCA): `resolver_planta_origen_gps` identifica
  AZA RENCA con esta evidencia real, favoreciendo la permanencia larga
  sobre el paso corto y anterior por COLINA que cae en la misma ventana.
- Caso 2 (mismo vehículo, sólo tramo real de COLINA): identifica AZA
  COLINA, nunca fuerza RENCA; y sin evidencia cerca de ninguna planta,
  no determina nada (nunca inventa).
- Caso 3 (ambiguo real, guía 472037, `motivo_origen_gps` real ya
  persistido en producción): B1 recibe evidencia estructurada (2
  candidatos con score/solape, nunca un dump de GPS), se abstiene con
  motivo trazable, nunca autoaplica planta.

**Aprendizaje:** vive en `catalogos_privados/plantas.json` (mismo
catálogo que ya consumen Motor y B1) -- reutilizable por cualquier
vehículo/documento futuro compatible con esta geocerca, nunca ligado a
SB6486, esta guía ni este chofer.

5 tests focales nuevos con datos reales (`fixtures_telemetria_renca_r8.py`).
Suite completa: 1613 passed (antes 1608).

**Aplicado a Drive real:** backup verificado
(`respaldos/R8_RENCA_20260821_155659/`), dry-run previo. Sólo
`catalogos_privados/plantas.json` (AZA RENCA) escrito; AZA COLINA,
dataset, ledger y bandeja verificados sin cambios por este bloque
(SHA-256). No se reprocesaron las 10 guías. 9 viajes/9 confirmados/0
revisión intacto; 464959+464960 en 11.429 kg/22,94 km/32,96 min; XF3629
correctamente resuelto.

**Estado: BLOQUE R8 CERRADO EN CÓDIGO Y EN DRIVE REAL. Sin push en
ninguno de los dos repos.**

## Bloque R9 -- lote nuevo (10 guías) como E2E real: routing, huérfana, B1, performance (2026-08-21)

**472099 (caso obligatorio) y las otras 6 guías sin km/tiempo:** todas
tenían origen+destino ya resueltos pero un rechazo real de destino
(comuna contradicha/genérico/disperso -- protecciones R4.10 funcionando
correctamente) sin NINGUNA decisión asociada -- el mecanismo
`DESTINO_NO_RESUELTO` (Bloque R6) existía pero nunca se había
reconciliado contra este lote. Reconciliado: 7 decisiones nuevas
(472044, 472073, 472099, 472163, 472227, 472238, 472239). 472099 queda
con causa explícita y trazable (`GEOCODIFICACION_CONTRADICE_COMUNA_
DOCUMENTAL: Cerrillos != Santiago`) y accionable en Revisión de Atlas --
nunca una ruta inventada.

**472044 -- causa real distinta, encontrada:** `estado_ruta` quedó en
`PROVEEDOR_NO_DISPONIBLE` durante el procesamiento original, pero el
proveedor SÍ respondía al reintentar -- con un 404 propio de ORS
(código 2010, "no routable point") para el punto geocodificado
(confianza 0.6, "Las Condes, RM, Chile", comuna sin dirección precisa).
Nunca era una falla técnica: es evidencia real de destino impreciso.
Nuevo `EstadoRuta.SIN_ACCESO_VIAL`, distinguido explícitamente de
`PROVEEDOR_NO_DISPONIBLE` en `openrouteservice.py`; sumado a
`MOTIVOS_DESTINO_NO_RESUELTO` (R6) y al registro B1 (R7). También
corregido: `revalidar_ruta_sin_destino_calculado_sin_ocr` ahora
actualiza la etiqueta de un motivo técnico obsoleto cuando el reintento
trae una causa real distinta (antes quedaba pegada la etiqueta técnica
vieja).

**Revisión huérfana (3 REVISAR vs 2 en Revisión de Atlas):** causa real
encontrada -- `CLIENTE_AUSENTE` (motivo bloqueante real,
`motivos_revision_documento`) nunca tuvo NINGUNA decisión asociada desde
que existe, a diferencia de CLIENTE_DESCONOCIDO/CLIENTE_CANDIDATO/
ALIAS_CANDIDATO (los 3 exigen algún texto documental de partida). Nuevo
tipo `CLIENTE_AUSENTE`/acción `REGISTRAR_CLIENTE_MANUAL` (mismo patrón
que `DESTINO_NO_RESUELTO`): un humano escribe la razón social real,
Atlas la registra en el catálogo ya existente y resuelve el documento.
472238/472239 (mismo transporte, huérfanas reales) ahora tienen decisión
-- los 3 viajes REVISAR (472163, 472238+472239, 472247) quedan con
decisión accionable, 0 huérfanas.

**B1 (Parte 7):** telemetría de R7 ya funcionando en producción sin
ningún cambio de código -- cada problema no resuelto del lote (destino
x6, patente, obra) trae `elegible_ia`/`razon_no_elegible` explícitos
(mayoría `SIN_EVIDENCIA_PARA_RAZONAR`: sin documento hermano con destino
ya resuelto para la misma obra); 472044 correctamente `NO_ELEGIBLE_IA`
(`FALLA_TECNICA_EXTERNA_SIN_RAZONAMIENTO_POSIBLE`) antes del fix de
reclasificación. Cero "0 llamadas" sin explicación.

**Aprendizaje reutilizado:** catálogo de plantas (Renca/Colina, R8),
relaciones obra↔destino y catálogo de clientes -- ningún mecanismo
paralelo; `revalidar_y_regenerar_reporte` ya usa todo esto (confirmó
472247 con AMERICAN SCREW CHILE SPA vía alias ya conocido).

**Performance:** lote nuevo 130,5 s/10 guías vs lote anterior 58,9 s/10
-- diferencia casi enteramente en telemetría (75,1 s vs 12,2 s, ~88% de
la diferencia total). Medido por documento: la mayoría de las guías
nuevas pagó una consulta OneLogis FRESCA (8-14 s cada una, sin caché
previa); un documento del mismo transporte que reutilizó caché tardó
0,52 s. Causa concreta: más combinaciones patente+fecha nuevas en este
lote, no una regresión de código -- no se optimizó a ciegas.

30 tests focales nuevos. Suite completa: Motor 1627 passed (antes 1613);
Desktop 275 passed (antes 270).

**Aplicado a Drive real:** backup verificado
(`respaldos/R9_LOTE_NUEVO_20260821_162538/`), dry-run previo. CSV/
catálogos actualizados sólo donde correspondía (472247, 472044,
bandeja); 464959+464960 y XF3629 intactos; 18 viajes/15 confirmados/3
revisión, las 3 con decisión accionable. No se reprocesaron las 10
guías nuevas.

**Estado: BLOQUE R9 CERRADO EN CÓDIGO Y EN DRIVE REAL. Sin push en
ninguno de los dos repos.**

## Bloque R10 -- decisión aplicada → revalidación → viaje OK → routing (2026-08-21)

**Caso real (encontrado por ledger/timestamps, no preguntado a Javier):**
guía 472163 -- Javier aplicó `OBRA_DESCONOCIDA`/`REGISTRAR` desde Desktop
(última aplicación real del ledger, 21:02:59); la decisión desapareció
correctamente de Revisión de Atlas, pero el documento seguía con
`motivos_revision_documento=OBRA_DESTINO_SIN_CORROBORAR` e
`indicador_revision=REVISAR` -- el viaje seguía REVISAR en Viajes.

**Causa raíz (general, no de esta guía):** `aplicar_decision_obra`
disparaba `revalidar_y_regenerar_reporte` (que YA sabe retirar el motivo
vía el índice del ledger, R4.9) sólo para una lista blanca cerrada de
3 tipos de decisión (`ORIGEN_NO_CONFIRMADO`, `DESTINO_NO_RESUELTO`,
`CLIENTE_AUSENTE`) -- cualquier otro tipo (obra, cliente, vehículo,
alias...) cerraba la decisión sin revalidar nunca el motivo documental
de ese mismo documento.

**Fix general:** se invirtió la condición -- ahora CUALQUIER acción que
cierre una decisión (todas salvo `POSPONER`/`NO_PUEDO_DETERMINAR`, que no
escriben nada) dispara `revalidar_y_regenerar_reporte` automáticamente,
salvo los 3 tipos que ya regeneran directo (evitar trabajo redundante,
no por riesgo). Cubre obra/cliente/destino/vehículo/alias hoy y
cualquier tipo nuevo mañana sin volver a tocar esta lista. Nuevo archivo
`test_invariante_revision_huerfana_r10.py` (5 tests): prueba el
invariante -- decisión cerrada + único motivo resuelto → indicador OK y
sin decisión pendiente -- contra los dominios obra, vehículo y cliente
por separado (destino/planta ya cubiertos en sus propios archivos), más
el control inverso (otro motivo legítimo → REVISAR se mantiene con causa
explícita).

**472163 antes → después:** `motivos_revision_documento`
`OBRA_DESTINO_SIN_CORROBORAR`→`""`, `indicador_revision`
`REVISAR`→`OK`, viaje (transporte 0000354328) `REQUIERE_REVISION`→
`CONFIRMADO`.

**Routing después (Parte F):** `estado_ruta` sigue `REQUIERE_REVISION`
(`GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL: Vitacura != Santiago`,
km/tiempo vacíos) -- causa técnica explícita y ya con decisión
`DESTINO_NO_RESUELTO` accionable en Revisión de Atlas desde R9; el
badge REVISAR del viaje y el estado de ruta son señales independientes
por diseño (Desktop ya muestra ambas) -- no se confunden ni se ocultan.

**B1 (Parte E):** sin cambios en R7 -- no hay fallo de integración
demostrado. `resultado_atlas_ia_json` del reporte confirma ambos
problemas restantes de 472163 como `elegible_ia=true`,
`llamada_realizada=false`, `razon_no_elegible=SIN_EVIDENCIA_PARA_RAZONAR`
(sin documento hermano para corroborar) -- abstención correcta y
explícita, nunca un corte silencioso.

**Tests:** 5 nuevos + 5 archivos existentes corregidos (fixtures con CSV
mínimo/aserciones que asumían la revalidación selectiva vieja). Motor
completo: 1632 passed (antes 1627). Desktop: sin cambios, nada que
correr.

**Aplicado a Drive real:** backup verificado
(`respaldos/R10_PRE_RECONCILIACION_20260821_213140/`), dry-run contra
copia temporal (confirmó que sólo 472163 cambiaba) antes de aplicar.
Catch-up único de `revalidar_y_regenerar_reporte` contra producción real
(sin reprocesar, sin OCR): sólo 472163 actualizado; las otras 10
decisiones pendientes, ledger y catálogos verificados byte-idénticos
(SHA-256) al backup. Nuevo `reporte_vigente` publicado
(`reporte_revalidacion_r10_20260821_213141_022921`). Ningún futuro caso
como éste va a requerir este catch-up manual -- el fix lo hace
automático desde ahora.

**Estado: BLOQUE R10 CERRADO EN CÓDIGO Y EN DRIVE REAL. Sin push en
ninguno de los dos repos.**

## Bloque R11 -- decisiones obsoletas autorregenerables + reconciliación OCR de patente (2026-08-22)

**A. Decisión obsoleta atrapando al usuario:** causa real -- el propio
catch-up de R10 (`revalidar_y_regenerar_reporte`, llamado standalone
contra producción, sin pasar por `aplicar_decision_obra`) cambió el
dataset pero nunca republicó `decisiones_pendientes.json`: su
`dataset_sha256` grabado quedó apuntando al dataset ANTERIOR. La barrera
de obsolescencia (correcta en sí) empezó a rechazar las 11 decisiones
reales pendientes, no sólo la guía que cambió -- "Refrescar datos" en
Desktop sólo relee archivos, nunca revalida, así que el usuario quedaba
atrapado para siempre reintentando una tarjeta muerta.

**Fix general (dos capas, sin mecanismo paralelo):**
1. `revalidar_y_regenerar_reporte` ahora republica la bandeja ella misma
   cada vez que corre (vía `regenerar_decisiones_persistidas` +
   `generar_artefacto`), sin condicionarlo a si ESA corrida cambió algo
   -- el hash pudo quedar desincronizado en una corrida anterior.
2. `aplicar_decision_obra` se autorrepara en el punto exacto de la
   comprobación: si el dataset cambió, revalida/republica y reevalúa la
   MISMA decisión contra el resultado fresco -- si sigue idéntica y
   vigente, continúa aplicándola sin exigir un segundo intento; si
   realmente cambió o ya no aplica, rechaza con un mensaje claro y la
   bandeja ya queda fresca para el siguiente refresco. Se descubrió
   además `reconciliar_bandeja_decisiones` (Bloque RECONCILIACIÓN D1,
   preexistente, nunca conectado a ningún flujo real) -- ahora
   `aplicar_decision_pendiente.py` (el CLI que usa Desktop) lo invoca
   como reintento único tras cualquier obsolescencia genuina, reutilizando
   enriquecimiento vehículo/cliente/obra y auto-resolución ya existentes.

**B. Patente JE4288 (472247, Rodrigo Nahuelñir):** causa real -- sin
ningún documento hermano de este RUT (ni en el dataset ni en el ledger),
`evaluar_evidencia_patente` sólo buscaba candidatos en el historial de
ESE chofer; nunca ampliaba al catálogo completo, aunque "JF4288" ya
estuviera CONFIRMADO/ACTIVO como CARRO (mismo rol documental) a una
única confusión OCR (E/F) de distancia -- confusión real, ausente del
set calibrado hasta ahora.

**Fix general:** `{"E","F"}` sumado al set de confusiones OCR calibradas
(documentado, no ampliado a ciegas). `evaluar_evidencia_patente` ahora
también considera patentes CONFIRMADAS/ACTIVAS de todo el catálogo a una
confusión OCR calibrada de distancia -- sólo cuando el tipo de vehículo
ya es INEQUIVOCO (nunca sin tipo conocido, para no ampliar demasiado el
universo). Nunca alcanza `RESUELTO_AUTOMATICAMENTE` (exige
`CONFIRMACION_HUMANA` real); si más de un vehículo del catálogo compite,
ninguno gana solo. **JE4288 antes → después:** VEHICULO_DESCONOCIDO sin
ningún candidato → VEHICULO_DESCONOCIDO con JF4288 como único candidato,
`USAR_PATENTE_EXISTENTE` disponible; JE4288 nunca se registra como
entidad nueva.

**B1:** sin cambios en R7 -- el determinista ya resuelve 472247 sin
ambigüedad, no hace falta escalar. Aprendizaje: el ledger indexa por
`(numero_guia, campo, valor_documental)` -- confirmar JF4288 para esta
guía nunca crea una regla universal "JE significa JF".

**Tests/E2E:** 8 tests focales nuevos (2 en decisiones obsoletas, 6 en
reconciliación de patente) + 3 archivos existentes corregidos (asumían
la ventana de obsolescencia vieja). Motor completo: 1640 passed (antes
1632). Desktop: sin cambios, nada que correr. E2E sobre copia de
producción real: CASO 1 (472044) se autorreparó y aplicó sin ningún paso
manual, resto de la bandeja intacto; CASO 2 confirmó JF4288 como único
candidato de 472247.

**Aplicado a Drive real:** backup verificado
(`respaldos/R11_PRE_RECONCILIACION_20260822_010437/`). `reconciliar_
bandeja_decisiones` aplicado una vez contra producción real: dataset/
catálogos/ledger verificados byte-idénticos (SHA-256) al backup -- sólo
`decisiones_pendientes.json` se republicó (hash fresco; 472247 ahora con
JF4288). Las 11 decisiones pendientes reales preservadas, ninguna
aplicada automáticamente.

**Estado: BLOQUE R11 CERRADO EN CÓDIGO Y EN DRIVE REAL. Sin push en
ninguno de los dos repos.**

## Bloque R12 -- auditoría y cierre de universalidad real de B1 (2026-08-22)

**Pregunta:** ¿todo problema residual pasa por elegibilidad IA antes de
llegar a Javier? **Respuesta: NO (bypass real encontrado), corregido en
este bloque.**

**Bypass 1 -- colisión de clave silenciosa:** `REGISTRO_PROBLEMAS_IA`
guardaba una única entrada por `(fuente, código)` -- `PATENTE_SIN_
HOMOLOGAR` sólo podía registrar UN campo (`patente_tracto`); la entrada
de `patente_rampla` nunca pudo agregarse (causa raíz real de que B1
nunca evaluara la rampla de 472247, Bloque R11). Fix: el registro ahora
guarda una TUPLA por clave; `detectar_problemas_elegibles` itera todas.

**Bypass 2 -- 10 de 14 motivos documentales sin ninguna entrada NI
fallback:** sólo 4 motivos (los originales de R7) tenían registro; los
otros 10 (`GUIA_AUSENTE`, `TRANSPORTE_AUSENTE`, `CLIENTE_AUSENTE`,
`CHOFER_AUSENTE`, `DOCUMENTO_DEGRADADO`, `FECHA_SIN_CORROBORAR`,
`PATENTE_AMBIGUA`, `MATERIAL_AUSENTE`, `CLIENTE_NUEVA_ENTIDAD_NO_
CATALOGADA`, `TRANSPORTE_AUSENTE_SIN_ETIQUETA`) no producían NINGUNA
traza -- ni evaluados ni explicados. El más grave: `CLIENTE_AUSENTE`
tiene decisión humana accionable desde Bloque R9 (`REGISTRAR_CLIENTE_
MANUAL`) y llegaba a Revisión de Atlas sin haber pasado nunca por B1.
El mismo vacío existía para `motivo_origen_gps` (sólo `motivo_ruta`
tenía red de seguridad, Bloque R7).

**Fix general (nunca una whitelist más grande):** 6 motivos con campo
real se registraron (`CLIENTE_AUSENTE`, `CHOFER_AUSENTE`, `FECHA_SIN_
CORROBORAR`, `MATERIAL_AUSENTE`, `PATENTE_AMBIGUA` ×2 campos,
`CLIENTE_NUEVA_ENTIDAD_NO_CATALOGADA`) con el mismo adaptador genérico
ya existente (`recopilar_evidencia_documentos_relacionados`). Además --
el fix estructural real -- se agregó `codigos_residuales_no_
registrados`/`clasificar_motivo_no_registrado`: cualquier código de
CUALQUIERA de las 3 fuentes (documental/ruta/origen GPS) que el
registro no reconozca hoy, o que se agregue mañana sin registrar,
produce igual una traza explícita (técnico/estructural o evidencia
insuficiente) -- generaliza la red de seguridad que antes sólo existía
para `motivo_ruta`. Agregar un motivo nuevo mañana sigue sin tocar el
dispatcher; si además nadie lo registra, ya no desaparece en silencio.

**Dominios cubiertos:** los 14 motivos documentales + los ya existentes
de ruta/origen GPS -- ver `test_todo_motivo_documental_conocido_tiene_
clasificacion_explicita` (recorre el enum completo) y `test_todo_
motivo_documental_bloqueante_produce_traza_end_to_end` (E2E real por
motivo). Fuera de alcance, documentado no oculto: conflictos de
consolidación a nivel VIAJE (`CONFLICTO_FECHA`/`CONFLICTO_CHOFER`/etc.,
`gestor_viajes.py`) son señales de reporte, no decisiones accionables
-- dominio arquitectónicamente distinto (post-agrupación, no por
documento), no tocado en este bloque.

**Desktop/Mobile:** confirmado un único gate -- `_ejecutar_ia_
operacional`, con exactamente 2 llamadores (`procesar_carpeta` para
Desktop/lote, `escalar_resultado_ia_en_memoria` para Mobile), ningún
camino paralelo.

**Orden determinista → B1 → humano:** verificado -- `analizar_guias_
masivo.py` corre `procesar_carpeta` (incluye B1) completo ANTES de
`generar_artefacto` (bandeja). Auto-aplicación (clase A) sigue
estructuralmente inalcanzable con el único recolector de evidencia
genérico hoy (`DOCUMENTO_RELACIONADO` nunca alcanza el nivel exigido,
`CONFIRMACION_HUMANA`/`EXTERNO_OFICIAL`) -- comportamiento preexistente
y ya documentado (casos reales 460807/472008), no una regresión.

**E2E real:** 5 casos contra fixtures de integración (nunca producción)
-- determinista resuelve (0 llamadas); llamada REAL a Groq (2 llamadas
reales ejecutadas, clasificación B_ASISTENCIA, traza completa);
NO_ELEGIBLE_IA explícito sin llamada; dominio nuevo (MATERIAL) llega al
mismo gate sin tocar el dispatcher durante la prueba; Mobile confirma
mismo mecanismo.

**Tests:** `test_b1_universal_r7.py` corregido (estructura tupla) +6
tests nuevos (cobertura arquitectónica, patente sin colisión,
CLIENTE_AUSENTE real, motivos estructurales, origen GPS no registrado).
Motor completo: 1647 passed (antes 1640). Desktop: sin cambios.

**B1 UNIVERSAL REAL: SÍ** (tras el fix de este bloque).

**Estado: BLOQUE R12 CERRADO EN CÓDIGO. Sin cambios en Drive real (nada
que reconciliar -- el fix es de dispatch, no de datos). Sin push en
ninguno de los dos repos.**

## Bloque R13 -- reconciliación global post-aprendizaje + cliente leído + UX + coherencia Viajes↔Revisión (2026-08-22)

**Causa repetición de destinos:** el aprendizaje reutilizable (Destino +
relación obra↔destino) sólo se persistía cuando el proveedor de rutas
SÍ lograba geocodificar la dirección (`ruta_resuelta`). "¿Es correcta
esta dirección?" (confirmación humana) y "¿el proveedor externo puede
ubicarla?" (limitación de terceros) se trataban como la misma pregunta
-- si el proveedor fallaba, la confirmación de Javier se perdía por
completo y la misma dirección en otra guía (misma u otra obra/cliente)
volvía a preguntarse desde cero.

**Fix reconciliación global:** (1) la persistencia de Destino/relación
en `aplicar_decision_obra` ahora corre SIEMPRE que hay dirección manual,
geocodifique o no -- km/tiempo siguen sin inventarse jamás. (2)
`regenerar_decisiones_persistidas` ahora también descarta
`DESTINO_NO_RESUELTO` cuando la obra ya tiene relación CONFIRMADA
(mismo criterio ya usado para `DESTINO_SIN_CONFIRMAR`). (3) nuevo
`ruta_dataset` (opcional, aditivo) en `regenerar_decisiones_persistidas`:
descarta cualquier decisión cuyo motivo declarado sea un código real de
`motivos_revision_documento` que ya no está en la fila actual -- cierra
la revisión huérfana para CUALQUIER tipo futuro que use ese mismo
vocabulario, sin agregar casos por tipo.

**VISTA CLARA / VIA MORADA antes → después:** ambas quedaban pidiendo
confirmación en cada guía nueva pese a que Javier ya las había
confirmado dentro del mismo ciclo. "TORRES OCARANZA LTDA" (VISTA CLARA)
YA tenía relación CONFIRMADA en el catálogo desde antes (R2,
2026-08-13/14) -- el bug real era que `regenerar_decisiones_persistidas`
nunca lo comprobaba para `DESTINO_NO_RESUELTO`. "CONSTRUCTORA SAN
CRISTOBAL L" (VIA MORADA) no tenía ninguna relación -- se persistió
retroactivamente usando la misma evidencia que Javier ya dejó en el
ledger real (`REGISTRAR_DIRECCION`, guía 472163). Después: ninguna de
las dos vuelve a preguntarse; el proveedor de rutas sigue sin poder
geocodificarlas (visible aparte, vía `estado_ruta`, nunca oculto).

**Causa CLIENTE_AUSENTE (TORRES OCARANZA):** el campo `cliente` quedó
genuinamente vacío en la extracción original, pero `obra_destino` de la
misma fila ("TORRES OCARANZA LTDA") ya coincidía EXACTO con un cliente
CONFIRMADO/ACTIVO del catálogo -- nunca se aprovechó ese cruce (mismo
patrón "cliente == obra" ya usado en sentido inverso para retirar
`OBRA_DESTINO_SIN_CORROBORAR`). Nuevo `revalidar_cliente_ausente_por_
obra_coincidente_sin_ocr`, sin OCR, sin inventar nada -- se abstiene sin
coincidencia exacta. **472238/472239 antes → después:** cliente
`No encontrado` → `TORRES OCARANZA LTDA`; `CLIENTE_AUSENTE` retirado.

**17/1/5 antes → después:** el dataset real ya tenía 20 guías (no 18 --
el reporte vigente estaba desactualizado respecto al dataset,
independiente de este bloque); tras reconciliar: 20 viajes / 20
confirmados / 0 requieren revisión / 0 decisiones pendientes. Ledger,
catálogos de vehículos y las demás guías (464959/464960, XF3629)
verificados intactos.

**UX post-decisión (Desktop):** causa real -- sin decisiones pendientes,
el panel de Revisión de Atlas quedaba `hidden` sin ningún mensaje
propio; dependía por completo de un elemento externo (acoplado al
conteo combinado de Envíos Mobile) para mostrar algo, y cualquier
demora/fallo ahí dejaba el panel en blanco -- indistinguible de haber
sido expulsado de la pestaña. Fix: `renderizar()` es ahora autosuficiente
(siempre muestra "Sin decisiones pendientes." si no hay ninguna, nunca
queda oculto); el refresco de Envíos Mobile ya no puede impedir que el
resto del refresco se complete. Funciona igual para cualquier tipo de
decisión -- corregido en el único punto compartido.

**B1:** sin cambios -- universalidad ya confirmada en R12; determinista
resuelve cliente/destino sin ambigüedad en los casos reales, 0 llamadas
necesarias.

**Aprendizaje:** todo vía mecanismos ya existentes (catálogo de
clientes/obras/destinos, ledger) -- ninguna memoria paralela.

**Tests:** Motor -- `test_reconciliacion_global_r13.py` (8 tests
nuevos) + `test_destino_no_resuelto_r6.py` corregido (1 test, invariante
real actualizado). Motor completo: 1655 passed (antes 1647). Desktop --
`decisiones_pendientes.test.js` corregido (1 test, comportamiento
nuevo correcto). Desktop completo: 275 passed.

**E2E:** en copia de producción real -- CASO 1/2 (destinos ya
confirmados no repreguntan), CASO 3 (TORRES OCARANZA resuelto sin
inventar), CASO 5 (reporte regenerado, Viajes↔Revisión coherente, 0
decisiones obsoletas) -- todos confirmados antes de aplicar a real.

**Aplicado a Drive real:** backup verificado
(`respaldos/R13_PRE_RECONCILIACION_20260822_020854/`). Relación
CONSTRUCTORA SAN CRISTOBAL L↔VIA MORADA persistida retroactivamente;
`revalidar_y_regenerar_reporte` aplicado; ledger y catálogo de vehículos
verificados byte-idénticos (SHA-256) al backup -- nada aplicado
automáticamente por Atlas, todo aprendizaje ya provenía de confirmaciones
humanas reales (ledger + catálogo R2).

**Estado: BLOQUE R13 CERRADO EN CÓDIGO Y EN DRIVE REAL. Sin push en
ninguno de los dos repos.**

## Bloque R14 (LOGÍSTICA L1) -- destino específico + km + tiempo (2026-08-22)

**Causas de los 3 destinos degradados (472044/472227/472247):** el
geocodificador a veces sólo resuelve hasta nivel comuna (p. ej. "Las
Condes, RM, Chile"); `resolver_destino_entrega` tomaba esa etiqueta tal
cual como destino OPERACIONAL, perdiendo calle+número que el propio
documento sí traía ("PUERTA DEL SOL 83 LAS CONDES"). Fix general: nueva
`_etiqueta_geocodificada_o_texto_documental` (proxy barato: presencia de
número de calle) -- si el documento trae número y la etiqueta del
proveedor no, se conserva el texto documental como destino operacional;
coordenadas/localidad/km/tiempo siguen viniendo del geocodificador, sin
cambios. Como la mayoría de las filas YA tenían ruta calculada (nunca
vuelven a pasar por geocodificación), se agregó
`revalidar_direccion_entrega_degradada_sin_ocr` -- corrige sólo la
ETIQUETA persistida, nunca km/tiempo/coordenadas. **Destinos antes →
después:** 9 filas degradadas (detectadas con el mismo criterio) → 1
(residual, en una fila que ya no está `RUTA_CALCULADA`, sin impacto
operacional).

**Los 11 sin km/tiempo:** `revalidar_ruta_sin_destino_calculado_sin_ocr`
ya existía (reintenta geocodificación/routing sin OCR, con caché) pero
nunca estaba conectada a `revalidar_y_regenerar_reporte` -- dependía de
un script manual. Conectada al final del pipeline de reconciliación
(única revalidación con red, siempre con caché). Además: un motivo en
blanco (dejado por un intento anterior que nunca persistió causa) NO
se actualizaba con el resultado fresco del reintento -- sólo lo hacía un
motivo técnico ya conocido. Corregido: un motivo en blanco se trata
igual (nunca es una causa estable, a diferencia de un rechazo ya
explicado por evidencia real). **Km/tiempo antes → después:** 11 sin
km/tiempo → siguen 11 (ninguno era genuinamente resoluble hoy), pero
**0 causas silenciosas → 11/11 con causa explícita** (`MULTIPLES_
UBICACIONES_DISPERSAS`, `GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL`,
`SIN_ACCESO_VIAL`, `SIN_EVIDENCIA_GPS`).

**B1:** evaluado explícitamente para los 11 (antes 5 no tenían ninguna
traza IA -- el motivo fresco nunca había pasado por B1, que sólo corre
en el procesamiento por lote). Ejecutado directo contra el dataset ya
persistido (sin OCR): 0 llamadas reales -- todas correctamente
`SIN_EVIDENCIA_PARA_RAZONAR` (ningún documento hermano con la misma obra
ya resuelta). 0 sin explicación.

**Desktop:** `renderLogistica` ocultaba TODO aviso para cualquier causa
que no fuera `ORIGEN_NO_DETERMINADO`/`DESTINO_NO_VALIDO` -- ni siquiera
"No disponible" para `SIN_ACCESO_VIAL`/`MULTIPLES_UBICACIONES_
DISPERSAS`/etc., pese a que Atlas ya conocía la causa. Fix mínimo:
nuevo `motivo_ruta` en el contrato de viaje + `causaLogisticaTexto`
-- siempre muestra la causa real cuando falta km/tiempo, nunca oculta
silenciosamente.

**Performance:** revalidación de rutas usa caché de geocodificación
existente (misma dirección no se paga dos veces); sin refactor de
performance. 16 filas reconciliadas en una sola pasada.

**Regresiones:** 464959/464960 (11.429 kg, ruta 22.9378 km/32.955 min),
XF3629, JF4288, Renca/Colina, 20/20/0 documental, B1 universal --
verificados intactos.

**Tests:** Motor -- `test_logistica_l1.py` (9 nuevos) + 2 archivos
existentes corregidos (etiquetas ya no degradan). Motor completo: 1664
passed (antes 1655). Desktop -- `ux_r4.test.js` corregido (1 test).
Desktop completo: 275 passed.

**Aplicado a Drive real:** 2 backups verificados
(`respaldos/R14_PRE_LOGISTICA_.../`, `respaldos/R14_PRE_B1_11_.../`).
Reconciliación de rutas + etiquetas + B1 aplicadas; ledger/catálogos de
clientes/vehículos verificados byte-idénticos al backup.

**Estado: BLOQUE R14 CERRADO EN CÓDIGO Y EN DRIVE REAL. Sin push en
ninguno de los dos repos.**

## Bloque R15 (TERRITORIAL T1) -- corrección de validación territorial + recuperación de rutas bloqueadas (2026-08-22)

**Causa raíz:** dos comparaciones territoriales mal construidas en
`resolver_destino_entrega_validado` (comuna documental vs comuna
geocodificada). (1) `_comuna_explicita`/`_comunas_explicitas` escaneaban
TODO el texto de `despachar_a_crudo`, así que la primera palabra de una
calle compuesta ("Vicuña Mackenna") se leía como comuna real "Vicuña"
-- caso real 472037. (2) La comparación no tenía ningún concepto de
jerarquía territorial: "Santiago" usado como etiqueta de ciudad/área
metropolitana por el geocodificador se comparaba, a nivel comuna, contra
la comuna real específica documental ("Cerrillos") como si fueran
incompatibles -- caso real 472238/472239/472099. Fix general, reutiliza
el catálogo territorial ya existente (`territorio_chile.normalizar_
comuna`, sin lista propia): `_texto_candidato_a_comuna` restringe el
escaneo al texto DESPUÉS del último número reconocido (nunca antes,
donde vive la calle); nueva `_comunas_territorialmente_compatibles`
acepta comuna real vs "Santiago" sólo cuando ambas están en la MISMA
región (Metropolitana) -- cualquier otra discrepancia (San Bernardo vs
Angol, Renca vs Maipú) sigue bloqueada igual que antes.

**Bonus (hallado por E2E, no hardcodeado):** al corregir el falso
positivo de "Vicuña Mackenna", el proveedor real geocodificó la
dirección a Córdoba, Argentina -- nunca antes detectado porque nada
validaba la región resultante contra el universo cerrado de regiones
chilenas. Nueva verificación independiente en `resolver_destino_entrega`
(reutiliza `region_valida` del mismo catálogo): rechaza cualquier región
geocodificada fuera de Chile con motivo explícito
`GEOCODIFICACION_FUERA_DE_CHILE`, sin importar si hay o no comuna
documental con la que contrastar.

**Reconciliación retroactiva:** las filas YA bloqueadas antes de este
fix con `GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL` nunca se
reintentaban (esa causa se trataba como evidencia externa inmutable).
Como la causa es la propia lógica de comparación de Atlas -- la que este
bloque acaba de corregir --, se agregó `motivo_previo_reevaluable` en
`revalidar_ruta_sin_destino_calculado_sin_ocr`: permite el reintento con
la lógica fresca (nunca afloja una contradicción real; sólo cuesta una
consulta más, ya cacheada) y sólo persiste si el CÓDIGO base del motivo
cambia (evita reescrituras ruidosas cuando la conclusión es la misma,
mismo criterio de motivos técnicos del Bloque R9).

**Falsos positivos antes → después:** 4 →
0 (`GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL`). 472099/472238/472239
recuperaron km/tiempo automáticamente (~30.77 km); 472037 pasó de un
motivo territorial FALSO a uno real y explícito
(`GEOCODIFICACION_FUERA_DE_CHILE: Cordoba`).

**SIN_ACCESO_VIAL (Parte G):** revisados individualmente los 3 casos
(472044/472073/472163) tras el fix territorial -- no eran ambigüedad
territorial. El geocodificador nunca encontró la dirección a nivel de
calle (confianza 0.6, centroide de comuna genérico); ORS routing sigue
devolviendo, en vivo, el error real 2010 ("no hay punto ruteable cerca
de la coordenada") contra ese centroide. Sin evidencia de un punto de
acceso mejor -- se conservan sin cambios, ninguna ruta inventada.

**B1:** sin cambios de código -- el registro genérico de `motivo_ruta`
(Bloque R7/R12) y el fallback `codigos_residuales_no_registrados` ya
cubren cualquier código nuevo (`GEOCODIFICACION_FUERA_DE_CHILE`) sin
registro explícito. No quedó ninguna ambigüedad territorial genuina
(dos comunas plausibles, jerarquía inconsistente) que requiriera
intervención de B1 tras el fix determinístico.

**Regresiones:** 464959/464960 (22.9378 km), San Bernardo vs Angol,
comunas compuestas (Pedro Aguirre Cerda) -- verificados intactos.

**Tests:** Motor -- `test_territorial_t1.py` (11 nuevos) + 4 archivos
existentes corregidos (fixtures con región no canónica, motivo ahora
reevaluable). Motor completo: 1676 passed. E2E en copia de producción
real (proveedor real, caché real): confirma 4→0 antes de aplicar.
Desktop: sin cambios (contrato `motivo_ruta` del Bloque R14 ya muestra
cualquier causa nueva sin código adicional).

**Aplicado a Drive real:** 1 backup verificado
(`respaldos/R15_PRE_TERRITORIAL_T1_.../`, SHA-256 antes/después).
Reconciliación de rutas aplicada (472037/472099/472238/472239);
ledger/catálogos de clientes/vehículos/obras verificados
byte-idénticos al backup.

**Estado: BLOQUE R15 (TERRITORIAL T1) CERRADO EN CÓDIGO Y EN DRIVE REAL.
Sin push en ninguno de los dos repos.**

## Bloque R16 (RESOLUCIÓN AVANZADA) -- destinos difíciles agotan fuentes antes de rendirse (2026-08-24)

**Causas raíz encontradas (nunca asumidas, todas trazadas):** (1)
`resolver_destino_ambiguo_con_evidencia_inequivoca` (Vía A catálogo
CONFIRMADO / Vía B GPS completo, Bloque DESTINOS D1) existía, estaba
probada, y NUNCA estuvo conectada a `resolver_destino_entrega` -- ante
`MULTIPLES_UBICACIONES_DISPERSAS` Atlas se rendía sin ni siquiera
intentar la evidencia que ya sabía calcular. (2) La reconciliación
retroactiva (`revalidar_ruta_sin_destino_calculado_sin_ocr`, usada en
R10-R15) construía `OpenRouteService()` SIN el filtro de país que el
procesamiento en vivo sí usa -- causa real de que 472037 geocodificara
en Córdoba, Argentina. (3) Los destinos que un humano CONFIRMA
(`DESTINO_SIN_CONFIRMAR`/R6 `REGISTRAR_DIRECCION`) quedaban con
`estado_calidad=PENDIENTE` para siempre y SIN coordenadas -- la Vía A
nunca podría usarlos aunque se conectara: no había ni un solo destino
`CONFIRMADO` con coordenadas en todo el catálogo real.

**Fix (Motor, reutiliza infraestructura existente, cero validador
degradado):** `resolver_destino_entrega` ahora intenta Vía A/B antes de
declarar `MULTIPLES_UBICACIONES_DISPERSAS` final; `calcular_ruta_con_
planta_conocida`/`calcular_ruta_entrega_para_viaje` propagan
`destinos_confirmados`. Nueva `_reintentar_ruta_sin_acceso_vial_con_
destino_confirmado`: si `SIN_ACCESO_VIAL` y un destino YA CONFIRMADO
(coincidencia literal, mismo criterio que Vía A) aporta un punto
distinto del centroide fallido, reintenta el ruteo desde ahí -- nunca
inventa una coordenada. `revalidar_ruta_sin_destino_calculado_sin_ocr`
ahora construye `OpenRouteService(pais="CL")` (mismo criterio que
`procesamiento_masivo`) y carga los destinos `CONFIRMADO` del catálogo
real. `catalogo_destinos.crear_o_reutilizar_global` ahora PROMUEVE un
destino ya existente a `CONFIRMADO` cuando se confirma con evidencia
nueva, y completa coordenadas ausentes sin sobrescribir las existentes
-- las dos confirmaciones humanas (`aplicacion_decisiones.py`) ahora
persisten `estado_calidad=CONFIRMADO` y, si la fila ya tenía ruta
calculada, sus coordenadas reales. `GEOCODIFICACION_FUERA_DE_CHILE` se
agregó al dominio DESTINO ya elegible para B1 (evidencia de documentos
hermanos) -- nunca "no elegible" sólo porque el geocodificador falló.

**Prueba real (Parte K, caso AUSIN SAN BERNARDO -- 460807/472008,
misma obra, mismo texto documental "INTERIOR NUEVA O1148 SAN
BERNARDO"):** verificado externamente contra el registro oficial SII
(portalchile.org, corroborado con una segunda fuente independiente) --
"Interior Nueva 01148, San Bernardo" es una sucursal real y
registrada de AUSIN HNOS S.A. El geocodificador principal (reintentado
con `pais=CL`, y con variantes de consulta) NUNCA resuelve esta
dirección a nivel de calle -- limitación real de cobertura del
proveedor, no un error de Atlas. Con la infraestructura de este bloque,
se demostró en una COPIA aislada (nunca en producción real) que UNA
sola confirmación humana futura de esta dirección resolvería
AUTOMÁTICAMENTE ambas guías vía Vía A (27.5 km / 41.4 km) -- prueba
concreta de "conocimiento nuevo se reutiliza, nunca se vuelve a
investigar desde cero". No se persistió ningún dato sintético en Drive
real: la precisión exacta de la coordenada (centroide de comuna vs.
punto de calle) sigue siendo una confirmación humana genuina.

**Casos actuales (Parte J, 8/20 sin km/tiempo):** 3
`MULTIPLES_UBICACIONES_DISPERSAS` (460807/472008/472018, familia AUSIN/
SALOMON SACK, San Bernardo -- limitación real de cobertura del
geocodificador, confirmada arriba), 1 `GEOCODIFICACION_FUERA_DE_CHILE`
(472037, causa real y trazable, ya no un falso positivo territorial),
3 `SIN_ACCESO_VIAL` (472044/472073/472163, Las Condes/Vitacura --
mismos 3 de R15, re-verificados: geocodificador nunca encuentra calle,
sólo centroide sin acceso vial cercano; probado con `pais=CL` y
variantes de consulta, sin resultado mejor), 1 `ORIGEN_NO_DETERMINADO`
(464981, sin evidencia GPS -- fuera del alcance de este bloque,
capa de origen no de destino). Los 8 quedan con causa 100% explícita y
trazable -- ninguno silencioso.

**Tests:** Motor -- `test_resolucion_r16.py` (8 nuevos: Vía A resuelve
dispersas con catálogo confirmado y control de abstención sin catálogo;
`SIN_ACCESO_VIAL` se recupera con destino confirmado distinto y control
sin catálogo; `pais=CL` verificado en el proveedor por defecto de la
revalidación retroactiva; `GEOCODIFICACION_FUERA_DE_CHILE` elegible
para B1; promoción a CONFIRMADO + coordenadas nunca sobrescritas).
Motor completo: 1684 passed (antes 1676). E2E en copia real de
producción (proveedor real, `pais=CL`): 0 regresiones
(464959/464960, 472099/472238/472239 intactos); demostración Vía A
aislada en la misma copia, revertida antes de aplicar a real.

**Aplicado a Drive real:** 1 backup verificado
(`respaldos/R16_PRE_RESOLUCION_AVANZADA_.../`, SHA-256 antes/después).
`revalidar_y_regenerar_reporte` corrido contra producción real con la
infraestructura nueva activa: 0 cambios inmediatos (esperado -- ningún
destino confirmado con coordenadas existía aún para los 8 casos
restantes), catálogos/ledger verificados byte-idénticos al backup.

**Pendiente real (no bloqueante, requiere decisión humana genuina):**
las 8 guías restantes necesitan que Javier confirme al menos UNA
dirección por familia (AUSIN/SALOMON SACK San Bernardo, Las Condes,
Vitacura, VICUÑA MACKENNA) vía Desktop -- con la infraestructura de
este bloque, esa única confirmación se propaga sola a cualquier
guía hermana futura o ya persistida de la misma obra.

**Estado: BLOQUE R16 (RESOLUCIÓN AVANZADA) CERRADO EN CÓDIGO Y EN DRIVE
REAL. Sin push en ninguno de los dos repos.**

## Bloque R17 -- cierre de los viajes reales sin km/tiempo (2026-08-24)

**Causa raíz nueva encontrada (revisando los 8 casos uno a uno, ninguno
asumido):** en 2 de los 8 (472018/464981), el texto documental repite
"SANTIAGO" como etiqueta de ciudad ANTES de la comuna real específica
("...SANTIAGO SAN BERNARDO", "...SANTIAGO MAIPU") -- enviado tal cual
al geocodificador, ese token competía como si fuera una comuna real
distinta y dispersaba los candidatos (verificado en vivo: 5 candidatos
para 472018). Fix general (reutiliza el mismo principio de Bloque
TERRITORIAL T1 -- "Santiago" como etiqueta de ciudad/metro, no como
comuna): nueva `_texto_geocodificable_sin_etiqueta_ciudad_santiago`
quita el token "SANTIAGO" SÓLO de la consulta al proveedor, y SÓLO
cuando el catálogo territorial ya identificó otra comuna real distinta
en el mismo texto -- nunca toca el texto documental almacenado, nunca
actúa si "Santiago" es la única comuna mencionada.

**Los 8 revisados individualmente (fuentes agotadas antes de rendirse):**
- **472018** (SALOMON SACK, CAMINO LOS PINOS 3396 SAN BERNARDO) --
  RESUELTO: 5 candidatos dispersos -> 1 inequívoco, **35.62 km / tiempo
  calculado**, verificado con el proveedor real antes de aplicar.
- **460807/472008** (AUSIN SAN BERNARDO, INTERIOR NUEVA O1148) --
  verificado externamente contra el registro oficial SII
  (portalchile.org, corroborado con segunda fuente): "Interior Nueva
  01148" es una sucursal real. El geocodificador (reintentado con
  variantes de consulta) nunca resuelve a nivel de calle -- limitación
  real de cobertura del proveedor. La infraestructura del Bloque R16
  (Vía A) ya está lista: una futura confirmación humana resuelve ambas
  guías automáticamente.
- **472037** (VICUÑA MACKENNA 655) -- variantes de consulta confirman
  que "Vicuña Mackenna" es una avenida real que cruza VARIAS comunas
  distintas de la RM (Santiago/Renca/Peñaflor/La Florida); sin comuna
  documental y sin confirmación externa fiable del número exacto, es
  ambigüedad territorial GENUINA -- correcto que quede para B1/humano,
  nunca adivinada.
- **472044/472073/472163** (Las Condes/Vitacura) -- re-verificados con
  múltiples variantes de consulta: el proveedor sólo devuelve
  centroides de comuna (0.6 confianza, sin calle) -- limitación real de
  cobertura, no un error de Atlas; `SIN_ACCESO_VIAL` sigue siendo la
  causa correcta.
- **464981** (AMERICAN SCREW, origen no determinado) -- consulta en
  vivo (no masiva, sólo esta patente/ventana) a Onelogis confirma CERO
  viajes GPS en la ventana documental (14:15-15:56); el viaje real más
  cercano ese día es a las 06:29 -- vacío real de telemetría, no un
  bug de selección de recorrido. `SIN_TRIPS_EN_VENTANA_TEMPORAL`
  confirmado como causa real y vigente.

**Tests:** Motor -- `test_resolucion_r17.py` (5 nuevos) + 1 fixture
existente corregido (`test_revalidar_ruta_sin_destino_r410.py`, consulta
ya no incluye "SANTIAGO" redundante). Motor completo: 1689 passed
(antes 1684). E2E en copia real de producción (proveedor real): 472018
recuperado (35.62 km), 0 regresiones.

**Aplicado a Drive real:** 1 backup verificado
(`respaldos/R17_PRE_CIERRE_7_SIN_KM_.../`, SHA-256 antes/después).
472018 con km/tiempo real; catálogos/ledger verificados
byte-idénticos al backup. **Con km/tiempo: 13/20** (antes 12/20).

**Pendiente real (no bloqueante, requiere decisión humana genuina):** 7
guías (460807/472008/472037/472044/472073/472163/464981) agotaron toda
fuente razonable disponible hoy -- 6 son limitación real de cobertura
del proveedor de geocodificación/telemetría (confirmada en vivo, no
asumida), 1 es ambigüedad territorial genuina (calle que cruza varias
comunas). Ninguna requiere una nueva investigación desde cero: la
infraestructura del Bloque R16 ya propaga automáticamente cualquier
confirmación humana futura a guías hermanas de la misma obra.

**Estado: BLOQUE R17 CERRADO EN CÓDIGO Y EN DRIVE REAL. Sin push en
ninguno de los dos repos.**

## Bloque R18 -- decisiones logísticas accionables para los 7 casos irresueltos (2026-08-24)

**Causa raíz real de "requiere humano + 0 decisiones":** tres
mecanismos ya existían, ya probados, cada uno con su propio
`detectar_decisiones_*_sin_ocr`/`reconciliar_decisiones_*`
(`ORIGEN_NO_CONFIRMADO`, `DESTINO_NO_RESUELTO`, `CLIENTE_AUSENTE`) --
pero NINGUNO estaba conectado al auto-republicado de la bandeja que
`revalidar_y_regenerar_reporte` corre siempre después de cada
revalidación retroactiva. Sólo se PODABAN decisiones ya publicadas;
nunca se DESCUBRÍAN candidatas nuevas que la revalidación acababa de
habilitar. Además, `GEOCODIFICACION_FUERA_DE_CHILE` (Bloque R16) nunca
se había agregado al conjunto `MOTIVOS_DESTINO_NO_RESUELTO` -- ni
siquiera detectable.

**Segunda causa real, encontrada al investigar por qué sólo 1 de 6
casos generaba una decisión al conectar lo anterior:** la mayoría de
los 6 YA TENÍAN respuesta humana -- Javier ya había confirmado la
dirección/relación obra↔destino (vía `DESTINO_SIN_CONFIRMAR` o una
reconciliación anterior), pero ese flujo NUNCA geocodifica, así que el
destino queda `CONFIRMADO` para siempre SIN coordenadas -- "¿es
correcta esta dirección?" ya está contestada, pero Vía A (Bloque
RESOLUCIÓN R16) nunca podía usarlo para rutear. Y, al revés, la
supresión de una decisión ya contestada (Bloque R13) sólo comprobaba
que la OBRA tuviera ALGUNA relación confirmada -- sin verificar que
fuera la MISMA dirección: caso real 472044 (EMPRESA CONSTRUCTORA MENA
Y), cuya obra ya tenía confirmado "CAM. EL NOVICIADO LAMPA LAMPA" (guía
distinta) mientras ÉSTA trae "PUERTA DEL SOL 83 LAS CONDES" -- una
pregunta genuina quedaba silenciada por una confirmación de OTRO lugar.

**Fix general (tres piezas, todas reutilizan mecanismos existentes):**
(1) `revalidar_y_regenerar_reporte` ahora fusiona, en su auto-republicado
de bandeja, las candidatas frescas de `detectar_decisiones_origen_sin_ocr`
/`_destino_no_resuelto_sin_ocr`/`_cliente_ausente_sin_ocr` -- corre
siempre, sin script manual; `generar_artefacto` deduplica por
`decision_id`, nunca produce una tarjeta repetida ni resucita una ya
cerrada. (2) `GEOCODIFICACION_FUERA_DE_CHILE` agregado a
`MOTIVOS_DESTINO_NO_RESUELTO`. (3) Nueva
`revalidar_destinos_confirmados_sin_coordenadas_sin_ocr`: geocodifica
(con caché, `pais=CL`, mismo mecanismo determinista ya calibrado) todo
destino `CONFIRMADO` sin coordenadas -- corre ANTES de la revalidación
de ruta, para que Vía A pueda usarlo en la MISMA pasada; nunca vuelve a
preguntar nada, sólo completa un dato que Atlas puede obtener solo. (4)
La supresión de `DESTINO_NO_RESUELTO` (Bloque R13) ahora exige que la
dirección CONFIRMADA de la obra coincida LITERALMENTE (mismo criterio
exacto de Vía A) con el texto documental de la guía -- nunca suprime
sólo porque la obra tiene alguna relación confirmada, sea cual sea.

**Los 7 clasificados uno a uno:**
- **472008/472037/472044** -- decisión `DESTINO_NO_RESUELTO` publicada
  (3 nuevas, cada una representa una familia/obra distinta): Javier
  puede resolverlas desde Desktop con `REGISTRAR_DIRECCION`.
- **460807/472073/472163** -- dirección YA confirmada por Javier (dos
  desde este mismo catálogo, una desde Bloque R13); Atlas intentó
  geocodificarla sola (Parte 3) y no pudo -- limitación real del
  proveedor (mismo hallazgo del Bloque R17), causa técnica final, no
  decisión. Bonus real: un destino confirmado de OTRA obra
  ("MAESTRA LIDIA TORRES 92, RECOLETA") sí se geocodificó solo.
- **464981** -- `SIN_TRIPS_EN_VENTANA_TEMPORAL`: sin ningún candidato de
  planta que ofrecer (criterio ya establecido, Bloque ORIGEN D1), causa
  técnica final confirmada, no decisión.

**B1:** sin nueva ambigüedad elegible para razonar más allá de la ya
confirmada en Bloque R16 (`SIN_EVIDENCIA_PARA_RAZONAR` vigente, sin
documentos hermanos con la misma obra ya resueltos). No se repitió la
llamada (0 evidencia nueva desde el último bloque, mismo resultado
garantizado -- ver criterio de performance).

**Post-decisión:** ya cubierto por infraestructura existente
(`aplicar_decision_obra` ya dispara `revalidar_y_regenerar_reporte`
tras cada aplicación, ahora con las 4 piezas de arriba activas) --
confirmado con test E2E (`test_decision_hermana_desaparece_sola_tras_
confirmar_una_familia`): responder una guía resuelve la ruta y hace
desaparecer sola la decisión de su hermana, sin responder por Javier.

**Tests:** Motor -- `test_resolucion_r18.py` (7 nuevos). Motor
completo: 1696 passed (antes 1689). E2E en copia real de producción
(proveedor real): 3 decisiones descubiertas, 0 regresiones de ruta.

**Aplicado a Drive real:** 1 backup verificado
(`respaldos/R18_PRE_DECISIONES_ACCIONABLES_.../`, SHA-256 antes/después).
3 decisiones `DESTINO_NO_RESUELTO` publicadas en Revisión de Atlas
(472008/472037/472044); 1 destino confirmado ajeno geocodificado
solo; catálogos de clientes/vehículos/obras/ledger verificados
byte-idénticos al backup.

**Estado: BLOQUE R18 CERRADO EN CÓDIGO Y EN DRIVE REAL. Sin push en
ninguno de los dos repos.**

## Bloque R19 -- las 3 revisiones de destino, con evidencia externa real (2026-08-24)

**Causa raíz nueva, real y grave, encontrada al investigar por qué el
fix `pais=CL` (Bloque R16) nunca cambió el resultado de 472037 pese a
estar aplicado:** `RepositorioCacheGeocodificacion` cachea por
`(proveedor_nombre, proveedor_version, dirección)` -- `OpenRouteService.
version` era un atributo de CLASE fijo ("v2"), idéntico sin importar
`pais`. Una consulta restringida a Chile y una sin restringir
compartían la MISMA entrada de caché: cualquier dirección ya
geocodificada (a veces meses atrás, sin restricción) seguía sirviendo
su resultado viejo -- incluido Córdoba, Argentina -- para siempre,
sin importar cuántas veces se corrigiera la consulta. Fix: `version`
pasa a ser de instancia e incluye el país (`"v2:pais=CL"` vs
`"v2:pais=SIN_RESTRICCION"`) -- una entrada cacheada bajo la
configuración vieja queda invisible para la nueva (se re-consulta una
vez, con caché real después).

**Segunda causa real:** una vez que `motivo_ruta` se refresca (p. ej.
472037 pasa de `GEOCODIFICACION_FUERA_DE_CHILE` a `MULTIPLES_
UBICACIONES_DISPERSAS`), la decisión `DESTINO_NO_RESUELTO` YA
publicada -- construida sobre la evidencia VIEJA -- nunca se
invalidaba (su hash de identidad cambia con el motivo, así que la
próxima detección genera una tarjeta NUEVA, dejando la vieja
huérfana). Fix: `regenerar_decisiones_persistidas` descarta una
decisión `DESTINO_NO_RESUELTO` cuyo motivo declarado ya no coincide
(por código base) con el `motivo_ruta` vigente de la fila -- mismo
criterio exacto que el descarte ya existente para motivos
documentales (Bloque R13), generalizado a motivos de ruta.

**Los 3 casos, investigados con evidencia externa real (WebSearch/
WebFetch, nunca un solo resultado dudoso):**
- **472008** (AUSIN SAN BERNARDO) -- corroborado con DOS fuentes
  independientes: registro oficial SII (portalchile.org, ya usado en
  Bloque R16) + verificación de mapa aportada en el propio bloque
  (proximidad real a AUSIN HNOS). "INTERIOR" es, en la convención de
  direcciones chilenas, un calificador de predio interior -- no un
  error, no se reescribe el texto documental. La dirección se
  confirma (`REGISTRAR_DIRECCION`, mecanismo existente, actor
  `ATLAS_EVIDENCIA_EXTERNA_R19` para trazabilidad -- nunca se hace
  pasar por un clic humano) con el texto documental verbatim: el
  proveedor real geocodifica varias calles reales homónimas
  ("Nueva", "Nueva Espejino", "Nueva Dos"...) en San Bernardo -- la
  ambigüedad de CALLE exacta persiste (nunca se inventa una
  coordenada), pero la decisión de identidad/dirección queda resuelta
  y fuera de Revisión de Atlas -- aprendizaje reutilizable para 460807
  (misma obra, mismo texto como prefijo).
- **472037** (VICUÑA MACKENNA 655) -- confirmado definitivamente FUERA
  de la contradicción "Argentina" (el bug de caché era la causa real).
  La calle SÍ cruza múltiples comunas reales de la RM (Santiago,
  Renca, Peñaflor, La Florida, Macul...) -- ni el geocodificador real
  ni la evidencia externa (que la propia ticket reporta con
  "Santiago/Ñuñoa", ella misma ambigua) permiten elegir una comuna con
  confianza -- ambigüedad territorial GENUINA, correctamente vigente
  para B1/humano, ahora con causa exacta y fresca (nunca la etiqueta
  vieja/engañosa de Argentina).
- **472044** (PUERTA DEL SOL 83 LAS CONDES) -- confirmado como edificio
  real y documentado (Edificio Puerta del Sol, cerca de Metro Escuela
  Militar) mediante búsqueda externa, pero el proveedor de
  geocodificación real no tiene cobertura a nivel de calle para esa
  dirección NI para "Escuela Militar" (verificado con múltiples
  variantes de consulta) -- limitación real y demostrada del
  proveedor, no inventable con un centroide. `SIN_ACCESO_VIAL` se
  mantiene con causa técnica real.

**B1:** sin nueva ambigüedad elegible más allá de lo ya cubierto
(Bloque R16); no se invocó de nuevo sin evidencia nueva que aportarle.

**Tests:** Motor -- `test_resolucion_r19.py` (3 nuevos) +
`test_rutas_openrouteservice.py` (1 nuevo, versión-por-país). Motor
completo: 1700 passed (antes 1699 tras R18 + 1 del fix de caché). E2E
en copia real de producción (proveedor real): 472037 refrescado sin
duplicar tarjeta, 472008 resuelto con evidencia externa, 0
regresiones.

**Aplicado a Drive real:** 1 backup verificado
(`respaldos/R19_PRE_EVIDENCIA_EXTERNA_.../`, SHA-256 antes/después).
472037 refrescado (causa real, sin Argentina); 472008 confirmado con
evidencia externa (aprendizaje persistido, ruta sigue ambigua);
**Revisión de Atlas: 3 → 2** (472044/472037, ambos con causa técnica
real demostrada). Catálogos de clientes/vehículos verificados
byte-idénticos al backup.

**Estado: BLOQUE R19 CERRADO EN CÓDIGO Y EN DRIVE REAL. Sin push en
ninguno de los dos repos.**

## Bloque B1 INVESTIGADOR -- ciclo de investigación real con herramientas (2026-08-24)

**Limitación real encontrada (dos causas, no una):** (1)
`OrquestadorAtlasIA.resolver` YA implementaba el ciclo "razona -> pide
herramienta -> Motor la ejecuta -> reevalúa -> concluye" (2 rondas,
`RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA` ya en el contrato) -- pero
NINGUNA herramienta de investigación externa real existía nunca
(`EvidenciaIA.tipo_fuente="EXTERNO"` estaba documentado desde el
principio como "hoy sin proveedor real conectado"). (2) Causa raíz más
grave: `_ejecutar_ia_operacional` NUNCA llamaba a B1 cuando el Motor no
había reunido evidencia previa (`if not evidencias: continue`, "SIN_
EVIDENCIA_PARA_RAZONAR") -- sin importar si el dominio tenía una
herramienta capaz de INVESTIGAR y producir esa evidencia. B1 nunca
llegaba a tener la oportunidad de pedir nada.

**Fix (reutiliza el ciclo ya existente, no crea arquitectura
paralela):** (1) Nueva `atlas_ia/buscador_web.py` -- herramienta REAL
de búsqueda web (OpenRouter + Perplexity Sonar, misma credencial
`OPENROUTER_API_KEY` ya presente y ya usada por otro proveedor del
sistema; costo real y pequeño, ~USD 0.005/consulta, verificado; caché
real, misma consulta nunca se paga dos veces). (2) Nueva
`herramienta_verificacion_externa` (`herramientas.py`) -- construye
consultas vinculando SIEMPRE dirección+obra/cliente (nunca la
dirección como string aislado, "regla crítica"), máximo 2 búsquedas
reales por invocación; produce `EvidenciaIA(tipo_fuente="EXTERNO")` --
nunca decide nada, sólo trae texto+citas para que B1 los lea. (3)
`_ejecutar_ia_operacional` ya no descarta el problema sin llamar a B1
cuando el dominio tiene AL MENOS una herramienta declarada -- B1 recibe
el problema con evidencia vacía y decide él mismo si investiga.
(4) `RONDAS_MAXIMAS` de 2 a 4 (varias rondas de herramienta antes de
concluir, con protección: si la MISMA herramienta no aporta evidencia
nueva, se detiene en vez de agotar rondas sin avanzar). (5) `VERIFICACION_
EXTERNA` declarada permitida para el dominio DESTINO
(`registro_problemas.py`, mismo mecanismo declarativo por dominio ya
usado para `DOCUMENTOS_RELACIONADOS` -- "cada dominio define sus
herramientas", nunca un dispatcher nuevo). (6) Política de sistema
(v2): reglas explícitas sobre cuándo/cómo pedir una herramienta
disponible y sobre nunca investigar una dirección aislada de su
contexto empresarial.

**E2E real (Groq + OpenRouter, llamadas reales, NO simuladas) contra
los 3 casos reales:**
- **472008** (AUSIN SAN BERNARDO) -- B1 razonó directo desde
  identidad_operacional (sin pedir herramienta) y propuso el valor
  documental; el validador existente lo BLOQUEÓ (`D_BLOQUEO`) por no
  estar respaldado por evidencia formal -- la protección "B1 nunca
  inventa" funcionando exactamente como debe, incluso cuando B1 mismo
  se equivoca de camino.
- **472037** (VICUÑA MACKENNA 655) -- ciclo completo demostrado: Motor
  falla -> B1 pide `VERIFICACION_EXTERNA` -> Motor ejecuta 2 búsquedas
  reales -> encuentra evidencia real nueva (proyecto inmobiliario real
  registrado en SNIFA en esa dirección exacta, desarrollado por
  "Fundamenta" -- coincide con el nombre de la obra "ING Y CONST
  FUNDAMENTA SPA", nunca antes detectado) -> B1 reevalúa en una segunda
  ronda -> concluye "Sí, existe, comuna Santiago" -- el validador
  bloqueó el valor propuesto por no ser un formato de dirección válido
  (fallo de forma, no de investigación: la investigación en sí
  funcionó).
- **472044** (PUERTA DEL SOL 83 LAS CONDES) -- ciclo completo: Motor
  falla -> B1 pide `VERIFICACION_EXTERNA` -> 2 búsquedas reales
  confirman que es una calle real en Las Condes -> B1 concluye
  `ABSTENCION` honesta (ninguna fuente vincula la dirección con la
  obra ni confirma acceso vial) -- exactamente el comportamiento
  correcto, nunca inventa un punto ruteable.
- Control: cuando el Motor ya resuelve, B1 no se invoca (0 llamadas) --
  cubierto por tests ya existentes del orquestador.

**Aprendizaje:** ninguna de las 3 investigaciones produjo una
`HipotesisIA` aceptada por los validadores existentes -- por diseño,
nada se aplicó a catálogos/producción esta vez (nunca forzar una
resolución). El aprendizaje real de 472008 (dirección confirmada) ya
había quedado persistido en el Bloque R19 por la vía humana/evidencia
externa existente -- este bloque no la duplica.

**Tests:** Motor -- `test_atlas_ia_buscador_web.py` (9 nuevos),
`test_atlas_ia_orquestador_b1.py` (+2 rondas reales), `test_b1_
universal_r7.py` (1 test reescrito para reflejar la conducta correcta,
1 control nuevo). Motor completo: 1711 passed (antes 1701). E2E real
(no simulado) contra 472008/472037/472044 documentado arriba.

**Sin cambios en Drive real** (ningún aprendizaje seguro que aplicar
esta vez -- ver arriba). Desktop sin cambios.

**Estado: BLOQUE B1 INVESTIGADOR CERRADO EN CÓDIGO. Sin push en
ninguno de los dos repos.**

## Bloque B1 EXPOSICIÓN -- Revisión de Atlas muestra lo que B1 ya encontró (2026-08-24)

**Causa de la desconexión:** el resultado completo de B1 (hipótesis,
evidencia `EXTERNO`, explicación en lenguaje natural, fuentes) YA
quedaba persistido en `resultado_atlas_ia_json` (misma columna de
siempre) -- pero `detectar_decision_destino_no_resuelto` nunca lo leía,
así que la tarjeta de Revisión de Atlas sólo mostraba el mensaje
genérico por motivo. Ningún dato faltaba; sólo no estaba conectado.

**Contrato/flujo conectado (reutiliza `resultado_atlas_ia_json`, cero
memoria paralela):** nueva `resumen_hallazgo_b1` (Motor) lee la traza
B1 del dominio DESTINO y la traduce a `contexto.b1_*` (resumen_hallazgo,
propuesta, evidencia_resumida, fuentes_resumidas, motivo_no_
autoaplicable, pregunta_humana) -- `None` si B1 no dejó nada útil (caso
7 intacto). `regenerar_decisiones_persistidas` refresca este hallazgo
en decisiones YA publicadas (mismo `decision_id`, nunca una tarjeta
duplicada). `_propuesta_b1_confirmable` es conservadora a propósito:
sólo ofrece "Confirmar destino" cuando el valor tiene forma real
(número o texto compartido con lo documental) -- nunca sobre un "Sí"
suelto. Desktop (`decisiones_pendientes_ui.js`): mensaje traducido a
lenguaje operacional, pregunta humana visible, evidencia resumida como
"N fuentes concordantes" (URLs sólo en "Ver detalles técnicos"); con
propuesta confirmable, las opciones pasan a "Confirmar destino"/"No
corresponde" -- MISMA acción de backend (`REGISTRAR_DIRECCION`/`NO_
PUEDO_DETERMINAR`, cero camino nuevo), con el valor pre-llenado (nunca
se le pide a Javier reescribir lo que Atlas ya encontró).

**472037 antes → después:** antes, "La dirección de la guía coincide
con varios lugares distintos y dispersos...". Después (catch-up real,
caché de búsqueda reusada, 0 búsquedas nuevas): "Atlas encontró
evidencia que vincula 'ING Y CONST FUNDAMENTA SPA' con este destino:
[explicación real de B1, cita el proyecto 'Vicuña Mackenna 655' y
SNIFA] La evidencia es fuerte, pero Atlas nunca aplica un destino nuevo
sin confirmación humana." + pregunta "¿Confirma que este es el destino
correcto?" + botón "Confirmar destino" pre-llenado con "Vicuña Mackenna
655".

**472044 antes → después:** antes, "Atlas detectó un elemento que puede
ayudarle...". Después: "Atlas investigó este destino y encontró
evidencia externa: Puerta del Sol es una calle real en Las Condes,
pero ninguna fuente confirma el número exacto ni el acceso vial." +
"Evidencia externa: 11 fuentes concordantes" -- sin propuesta
confirmable (B1 no llegó a un valor con forma de dirección), así que
conserva "Registrar dirección"/"No puedo determinar" -- nunca inventa
una propuesta sólo para mejorar la UI.

**Post-decisión:** sin cambios -- "Confirmar destino" viaja por el
mismo `REGISTRAR_DIRECCION` que ya usa `aplicar_decision_obra`
(revalidación/routing/km/tiempo/reconciliación ya encadenados desde
Bloque R13/R18).

**Hallazgo real durante el catch-up (no una regresión de este bloque):**
al aplicar, reaparecieron 2 decisiones más (460807/472008, familia
AUSIN SAN BERNARDO) -- la confirmación de 472008 (Bloque R19) creó una
SEGUNDA relación obra↔destino confirmada para la misma obra (texto
ligeramente distinto al de 460807, confirmado en R13), y
`resolver_obra_destino_confirmada_global` correctamente trata dos
relaciones confirmadas distintas como ambigüedad real -- deja de
suprimir. Dato coherente, comportamiento por diseño (abstenerse ante
evidencia ambigua), pero requiere que Javier reconcilie cuál de las
dos direcciones es la canónica -- pendiente real, fuera de alcance de
este bloque (no es un problema de exposición B1→UI).

**Tests:** Motor -- `test_b1_exposicion_ui.py` (8 nuevos). Motor
completo: 1719 passed (antes 1711). Desktop -- 6 tests nuevos en
`decisiones_pendientes.test.js` (confirmable/no-confirmable/sin
hallazgo). Desktop completo: 281 passed (antes 275).

**Aplicado a Drive real:** 1 backup verificado
(`respaldos/B1_EXPOSICION_PRE_.../`, SHA-256 antes/después). Catch-up
de B1 con caché de búsqueda reusada (0 búsquedas web nuevas) persistido
en `resultado_atlas_ia_json` para 472037/472044; catálogos/ledger
verificados byte-idénticos al backup; 0 regresiones de ruta
(464959/464960 intactos, 13/20 con km igual que antes).

**Pendiente real:** Javier debe reconciliar la ambigüedad AUSIN SAN
BERNARDO (460807/472008, dos relaciones confirmadas para la misma
obra) desde Desktop; y confirmar/rechazar 472037/472044 con el
hallazgo B1 ya visible.

**Estado: BLOQUE B1 EXPOSICIÓN CERRADO EN CÓDIGO Y EN DRIVE REAL. Sin
push en ninguno de los dos repos.**

## Bloque REGENERACIÓN B1 -- fix: no revivir decisiones resueltas + preservar contexto B1 (2026-08-24)

**Causa raíz #1 (confirmada en vivo, reproducible): AUSIN revive.**
`resolver_obra_destino_confirmada_global` exige EXACTAMENTE una
relación obra↔destino CONFIRMADA -- correcto para elegir un único
destino operacional a usar en rutas, pero demasiado estricto para
decidir si una pregunta ya está contestada. La obra "AUSIN SAN
BERNARDO" acumuló DOS relaciones confirmadas reales y legítimas (460807
en Bloque R13, 472008 en Bloque R19), cada una con su propio `Destino`
de texto ligeramente distinto (misma dirección real, dos variantes de
OCR) -- evidencia REDUNDANTE, nunca una contradicción. Ante dos
relaciones, el resolver empezó a devolver `None` ("no hay relación
confirmada", justo lo opuesto de lo que pasó), y la supresión de
`DESTINO_NO_RESUELTO` que depende de él dejó de funcionar -- ambas
guías reaparecieron en Revisión de Atlas.

**Fix #1:** nueva `CatalogoObrasDestinos.listar_destinos_confirmados_
para_obra` (sin exigir unicidad, mismo filtro de confirmación/no-
contradicción que el resolver original) -- la supresión de `DESTINO_
NO_RESUELTO` ahora suprime si CUALQUIERA de los destinos confirmados de
la obra coincide literalmente con el texto documental, nunca sólo "el
primero" ni "el más nuevo". Reutiliza el mismo catálogo, cero
arquitectura paralela.

**Causa raíz #2 (hallazgo defensivo, no reproducida con certeza como el
disparador exacto reportado, pero real y corregida): posible pérdida de
contexto B1.** `aplicar_decision_obra` regenera la bandeja sobre
`artefacto`, la copia en memoria leída al PRINCIPIO de la función. Si
una rama anterior de la MISMA llamada ya invocó `revalidar_y_
regenerar_reporte` (que republica `decisiones_pendientes.json` en
disco, incluyendo cualquier hallazgo B1 fresco de OTRAS decisiones),
regenerar sobre esa copia vieja y reescribir con `generar_artefacto`
más abajo podía descartar silenciosamente lo que el disco ya tenía --
"usa snapshot/artefacto anterior", exactamente la hipótesis del
bloque. **Fix #2:** se relee `decisiones_pendientes.json` justo antes
de la regeneración final -- nunca se opera sobre una copia en memoria
que pudo quedar desactualizada por una escritura propia de la misma
llamada.

**AUSIN antes → después:** 460807/472008 reaparecidas (4 decisiones
totales) → suprimidas de nuevo, ninguna pregunta nueva a Javier (2
decisiones: 472037/472044).

**B1 context antes → después:** verificado en Drive real -- 472037 y
472044 mantienen `b1_resumen_hallazgo`/`propuesta`/`evidencia_
resumida`/`fuentes_resumidas`/`motivo_no_autoaplicable` intactos tras
la regeneración; nunca se volvió a llamar a Groq ni a la búsqueda web
para este bloque (0 investigación nueva).

**Idempotencia:** verificada -- regenerar dos veces seguidas sobre el
mismo estado produce el mismo conjunto de decisiones, mismos
`decision_id`, mismo contexto B1 (test dedicado + verificado en vivo
contra producción real).

**Tests:** Motor -- `tests/test_regeneracion_b1.py` (4 nuevos: contexto
B1 sobrevive una regeneración disparada por otra decisión; dos
relaciones confirmadas redundantes suprimen ambas guías hermanas;
control -- una relación confirmada de un lugar REALMENTE distinto NO
suprime; regenerar dos veces es idempotente). Motor completo: 1723
passed (antes 1719). E2E en copia real de producción: AUSIN suprimida,
472037/472044 con contexto B1 intacto, 0 regresiones de ruta.

**Aplicado a Drive real:** 1 backup verificado
(`respaldos/REGENERACION_B1_PRE_.../`, SHA-256 antes/después).
Reconciliación pura (sin OCR, sin red, sin B1 nuevo) -- catálogos/
ledger verificados byte-idénticos al backup; `guias_actualizadas: []`
(ningún dato de ruta cambió, sólo la bandeja de decisiones).
**Revisión de Atlas: 4 → 2** (472037/472044, ambos con hallazgo B1
visible).

**Estado: BLOQUE REGENERACIÓN B1 CERRADO EN CÓDIGO Y EN DRIVE REAL. Sin
push en ninguno de los dos repos.**

## Bloque CONFIRMACIÓN D2 -- confirmación humana cierra ambigüedad de identidad + Desktop no sale de Revisión de Atlas (2026-08-24)

**Caso real: 472037.** Javier confirmó "VICUÑA MACKENNA 655" en Revisión
de Atlas; la decisión desapareció, pero Viajes seguía mostrando
`MULTIPLES_UBICACIONES_DISPERSAS(5)` sin km/tiempo, y aplicar cualquier
decisión sacaba a Javier de la pestaña Revisión de Atlas.

**Causa raíz #1 (Motor):** `aplicar_decision_obra` registra el destino
como `CONFIRMADO` en el catálogo aunque la ruta no llegue a calcularse
(Bloque R16, nunca persiste coordenadas a medias) -- Vía A
(`resolver_destino_ambiguo_con_evidencia_inequivoca`) exige coordenadas
propias para respaldar un candidato, así que nunca podía actuar sobre
ESTE destino; el motivo dejado era `MULTIPLES_UBICACIONES_DISPERSAS`, el
mismo que implica "identidad sin resolver" -- contradiciendo la
confirmación humana ya aplicada. **Fix:** `ResultadoDesambiguacionInequivoca`
ahora expone `identidad_confirmada` (coincidencia textual con un destino
`CONFIRMADO`, independiente de si tiene coordenadas); cuando la
ambigüedad geográfica persiste pero la identidad ya está confirmada,
`resolver_destino_entrega` deja `COORDENADA_NO_CONFIRMADA(N)` en vez de
`MULTIPLES_UBICACIONES_DISPERSAS(N)` -- nunca inventa un punto, sólo dice
la verdad vigente. `revalidar_ruta_sin_destino_calculado_sin_ocr` reevalúa
esa transición exacta (y sólo esa) para filas YA persistidas con el
motivo viejo, sin tocar la estabilidad general de motivos con evidencia
real (control ya existente, `test_logistica_l1.py`, sigue en verde).
`COORDENADA_NO_CONFIRMADA` no entra a `MOTIVOS_DESTINO_NO_RESUELTO` --
nunca vuelve a preguntarle a Javier algo que ya respondió.

**Causa raíz #2 (Desktop):** `cargarArchivo` (usada tanto por el input
manual como por el refresco automático tras aplicar cualquier decisión,
`intentarCargaAutomatica`) forzaba `vista-datos`/`vista-vacia` sin
condición -- ganándole en silencio a la pestaña realmente activa.
**Fix:** única función `actualizarVisibilidadViajes()` (misma regla que
ya usaba `cambiarPestana`, ahora compartida) -- `cargarArchivo` nunca
vuelve a decidir la pestaña visible por su cuenta.

**472037 antes → después (Drive real):** `MULTIPLES_UBICACIONES_
DISPERSAS(5)`, sin km/tiempo → `COORDENADA_NO_CONFIRMADA(5)`, sigue sin
km/tiempo (ninguna evidencia nueva permite pinchar el punto exacto entre
5 comunas homónimas) -- pero ya no contradice la confirmación de Javier.
Mismo efecto, correctamente generalizado, en 460807/472008 (AUSIN SAN
BERNARDO, mismo patrón real).

**Tests:** Motor -- `tests/test_desambiguacion_destino_inequivoca.py` (3
nuevos: `identidad_confirmada` con/sin coordenadas, con/sin match),
`tests/test_resolucion_r16.py` (2 nuevos: motivo correcto con/sin
identidad confirmada), `tests/test_confirmacion_d2_reevaluacion_
ambiguedad.py` (2 nuevos: reevaluación real vía `revalidar_ruta_sin_
destino_calculado_sin_ocr`, control de estabilidad sin confirmación).
Motor completo: 1730 passed (antes 1723). Desktop --
`test/confirmacion_d2_permanece_en_revision.test.js` (4 nuevos, misma
convención textual ya usada en `ux_r5.test.js`). Desktop completo: 285
passed (antes 281). E2E en copia real de Drive: `analisis_completo_
guias.csv` + `catalogos_privados/*` copiados, proveedor con la misma
respuesta de 5 candidatos ya cacheada en producción -- 472037 transiciona
correctamente, nunca inventa km/tiempo.

**Aplicado a Drive real:** 2 backups verificados (`respaldos/
CONFIRMACION_D2_PRE_.../`, `respaldos/CONFIRMACION_D2_REPORTE_PRE_.../`,
SHA-256 antes/después). Paso 1: `revalidar_ruta_sin_destino_calculado_
sin_ocr` con el proveedor real+caché (0 llamadas de red nuevas, consulta
ya cacheada) -- `guias_actualizadas: [460807, 472008, 472037]`; catálogos/
ledger/`decisiones_pendientes.json` byte-idénticos al backup. Paso 2:
reporte oficial regenerado (`reportes/reporte_confirmacion_d2_.../`) y
publicado en `estado_operacion.json` -- Desktop leía `viajes.csv` del
reporte vigente, no el dataset directo; sin este paso el fix quedaba
invisible en Desktop pese a estar correcto en el dataset (verificado:
`viajes.csv` nuevo trae `COORDENADA_NO_CONFIRMADA(5)` para 472037).

**Estado: BLOQUE CONFIRMACIÓN D2 CERRADO EN CÓDIGO Y EN DRIVE REAL. Sin
push en ninguno de los dos repos.**

## Bloque CIERRE POST-CONFIRMACIÓN -- dirección canónica preservada tras confirmar (2026-08-24)

**Caso real: 472044.** Javier confirmó "PUERTA DEL SOL 83" (Bloque
CONFIRMACIÓN D2 anterior), pero tras refrescar, el destino operacional
seguía mostrando "Las Condes, RM, Chile" -- una etiqueta de comuna
degradada, sin número de calle.

**Causa raíz:** `direccion_entrega` quedó persistida con esa etiqueta de
una corrida ANTERIOR a Bloque F (que ya impide exponer un candidato
rechazado como destino operacional). `revalidar_ruta_sin_destino_
calculado_sin_ocr` sólo refresca esa columna cuando el MOTIVO cambia
entre reintentos -- aquí no cambiaba (seguía siendo `CONFIANZA_
INSUFICIENTE`, una causa técnica ya correcta), así que la etiqueta vieja
sobrevivía para siempre a cualquier confirmación humana posterior. Esa
misma clase de bug YA tenía una limpieza retroactiva hermana
(`revalidar_direccion_entrega_degradada_sin_ocr`, Bloque LOGÍSTICA L1),
pero sólo cubría filas con `RUTA_CALCULADA` -- 472044 nunca llegó ahí.

**Fix:** `revalidar_destino_operacional_sin_numero_de_calle_sin_ocr`
(nueva, hermana de la anterior): mismo criterio EXACTO ya usado
prospectivamente (`_etiqueta_geocodificada_o_texto_documental` --
calle+número documental gana sobre una etiqueta sin número), aplicado
retroactivamente a filas SIN ruta calculada -- limpia `direccion_
entrega`/`localidad_entrega`/`region_entrega` (nunca sólo la etiqueta:
sin ruta calculada esos tres describen un candidato ya RECHAZADO,
Bloque F) y NUNCA toca `motivo_ruta`/`estado_ruta` (ya correctos --
cambiarlos resucitaría una pregunta sobre una identidad ya confirmada).
Conectada a `revalidar_y_regenerar_reporte` junto a su hermana. También
se sincronizan las mismas 3 columnas en la rama de reescritura de
`revalidar_ruta_sin_destino_calculado_sin_ocr` (motivo técnico obsoleto/
sin causa/reevaluable/identidad-recién-confirmada) para que un caso
futuro no vuelva a depender de esta limpieza retroactiva.

**472044 antes → después (Drive real):** destino operacional "Las
Condes, RM, Chile" → vacío (Desktop cae de vuelta a `despachar_a_crudo`,
"PUERTA DEL SOL 83", verificado en `viajes.csv` del reporte vigente
regenerado); `motivo_ruta` intacto (`CONFIANZA_INSUFICIENTE`, ya
correcto); sin km/tiempo inventado. 472037 sin tocar en este bloque
(`COORDENADA_NO_CONFIRMADA(5)`, ya correcto desde el bloque anterior).

**Tests:** Motor -- `tests/test_logistica_l1.py` (3 nuevos: limpieza sin
ruta calculada, control con etiqueta ya específica, control con fila
vacía/ya calculada). Suite completa: 1735 passed (antes 1732). E2E en
copia real de Drive: 472044 confirmado con la respuesta YA cacheada en
producción ("PUERTA DEL SOL 83, Chile" -> "Chile", confianza 0.1) --
etiqueta degradada limpiada, motivo intacto.

**Aplicado a Drive real:** 1 backup verificado (`respaldos/
CIERRE_CONFIRMACION_PRE_.../`, SHA-256 antes/después). Sólo limpieza
retroactiva (sin OCR, sin red -- ninguna consulta nueva, sólo columnas ya
persistidas) -- catálogos/ledger/`decisiones_pendientes.json` byte-
idénticos al backup; `guias_actualizadas: [472044]`. Reporte oficial
regenerado y publicado (`reportes/reporte_cierre_confirmacion_.../`) --
verificado en `viajes.csv`: `direccion_entrega` vacío, `despachar_a`
"PUERTA DEL SOL 83".

**Pendiente real (fuera de alcance de este bloque):** 472037 sigue sin
punto ruteable (`COORDENADA_NO_CONFIRMADA(5)`) -- B1 sólo aporta comuna
("Santiago") en texto libre, y NINGUNO de los 5 candidatos geocodificados
cae en esa comuna; forzar una elección sin evidencia estructurada sería
adivinar. Requiere, si Javier lo decide, una nueva búsqueda dirigida
(fuera del alcance "sin investigar de nuevo" de este bloque) o esperar
más evidencia.

**Estado: BLOQUE CIERRE POST-CONFIRMACIÓN CERRADO EN CÓDIGO Y EN DRIVE
REAL. Sin push en ninguno de los dos repos.**

## Bloque B1 OBSERVADOR + FALLBACK GEOGRÁFICO ESTRUCTURADO (2026-08-24)

**1. Fallback geográfico estructurado ("Vía C").** Nuevo
`atlas_core/rutas/nominatim.py` (`NominatimGeocoder`, sin credencial,
mismo patrón HTTP que `OpenRouteService`) -- geocodificador de RESPALDO,
consultado por `resolver_destino_entrega` SÓLO cuando el principal (ORS)
deja ambigüedad sin resolver y ni Vía A (catálogo confirmado) ni Vía B
(GPS) desambiguan ("sólo si A falla"). Se acepta el candidato SÓLO si:
(1) es el ÚNICO con número de calle coincidente
(`_candidato_unico_con_numero_de_calle`), Y (2) un destino ya CONFIRMADO
trae comuna propia territorialmente compatible con la comuna del
candidato -- sin corroboración, se abstiene (nunca adivina). Comparte
caché de geocodificación con ORS.

**2. B1 observador.** `_ejecutar_ia_operacional` ahora deja, para
CUALQUIER guía que el Motor resuelva sin ningún problema elegible, una
traza OBSERVACIONAL compacta en `resultado_atlas_ia_json` (misma
columna, 0 llamadas LLM, idempotente -- sólo la primera vez) --
reutilizable después vía `decisiones_pendientes.
resumen_observacion_operacional` ("¿qué pasó con una guía similar?").

**Caso real 472037.** El respaldo SÍ encuentra un candidato con número
de calle coincidente ("655 Pasaje Vicuña Mackenna", Maipú, confianza
0.9) -- verificado en vivo. Pero el destino ya CONFIRMADO de esta obra
no tiene comuna propia registrada (Bloque CONFIRMACIÓN D2: se confirmó
sin que la ruta llegara a calcularse) -- nada que corrobore el
candidato del respaldo contra el hallazgo B1 (comuna "Santiago", en
texto libre, no estructurado). Atlas se abstiene -- **antes → después:
sin cambio, `COORDENADA_NO_CONFIRMADA(5)`**, honestamente demostrado
(no inventado): el ÚNICO candidato estructurado disponible no coincide
con la comuna que la evidencia ya conocida sugiere, y ninguna fuente
adicional lo corrobora.

**Tests:** Motor -- `tests/test_rutas_nominatim.py` (14 nuevos:
adaptador HTTP), `tests/test_fallback_geografico_estructurado.py` (9
nuevos: Vía C unidad + integración en `resolver_destino_entrega`),
`tests/test_confirmacion_d2_reevaluacion_ambiguedad.py` (1 nuevo: E2E
con corroboración -> `RUTA_CALCULADA` real), `tests/test_b1_observador.py`
(6 nuevos: observación sin llamada, idempotencia, lectura). Suite
completa: 1765 passed (antes 1735).

**Aplicado a Drive real:** 1 backup verificado (`respaldos/
B1_OBSERVADOR_FALLBACK_PRE_.../`, SHA-256 antes/después). El fallback
corrió de verdad contra Nominatim (1 consulta real para 472037, ahora
cacheada -- 0 llamadas nuevas en corridas futuras); `guias_actualizadas:
[]` -- ninguna fila cambió (honesto: el fallback no encontró
corroboración para nada pendiente hoy). El observador B1 sólo aplica
hacia adelante (guías nuevas que entren al pipeline) -- no se
reprocesaron retroactivamente las 13 guías ya existentes (evita
"auditoría general").

**Estado: BLOQUE B1 OBSERVADOR + FALLBACK GEOGRÁFICO CERRADO EN CÓDIGO
Y EN DRIVE REAL. Sin push en ninguno de los dos repos.**

## Bloque VALIDACIÓN TERRITORIAL T2 -- Santiago (área metro) vs Maipú (comuna) ya no son incompatibles (2026-08-24)

**Causa:** Vía C (fallback geográfico) sólo corroboraba un candidato
contra la comuna PROPIA de un destino confirmado -- 472037 no tiene
comuna estructurada (se confirmó sin ruta calculada, Bloque
CONFIRMACIÓN D2), así que el candidato de Nominatim (Maipú, número de
calle exacto, confianza 0.9) nunca podía corroborarse, aunque B1 ya
había dejado "Santiago" en su evidencia persistida.

**Validación Santiago/Maipú:** `resolver_destino_con_fallback_
estructurado` ahora también corrobora contra la evidencia B1 YA
PERSISTIDA (`resultado_atlas_ia_json`, nunca una llamada nueva): si
menciona "Santiago" (palabra completa, nunca un `in` ingenuo) y esa
mención es territorialmente compatible con la comuna del candidato
(`_comunas_territorialmente_compatibles`, criterio YA calibrado en
Bloque TERRITORIAL T1 -- "Santiago" ciudad/área metropolitana vs
cualquier comuna real de la MISMA región no es una contradicción),
corrobora igual que una comuna confirmada estructurada. Nunca
hardcodea "Maipú" -- funciona para cualquier comuna de la RM que el
catálogo territorial reconozca.

**472037 antes → después:** `COORDENADA_NO_CONFIRMADA(5)` sin
km/tiempo → **`RUTA_CALCULADA`**, comuna "Maipú", `direccion_entrega`
"Pasaje Vicuña Mackenna 655". **km/tiempo: 35.50 km / 48.78 min**
(AZA COLINA -> Maipú, ORS real).

**Tests:** Motor -- `tests/test_fallback_geografico_estructurado.py`
(5 nuevos: corroboración por evidencia B1, control fuera de RM, control
sin mención, control substring-no-cuenta, E2E en `resolver_destino_
entrega`), `tests/test_confirmacion_d2_reevaluacion_ambiguedad.py` (1
nuevo: E2E real completo hasta `RUTA_CALCULADA` vía `revalidar_ruta_
sin_destino_calculado_sin_ocr`). Suite completa: 1771 passed (antes
1765). E2E en copia real de Drive: confirmado con la evidencia B1 y el
candidato Nominatim YA cacheados en producción.

**Aplicado a Drive real:** 1 backup verificado (`respaldos/
B1_OBSERVADOR_FALLBACK_PRE_20260824_185851/`, SHA-256 antes/después).
`guias_actualizadas: [472037]` -- única fila que cambió; catálogos/
ledger/`decisiones_pendientes.json` byte-idénticos al backup. Reporte
oficial regenerado y publicado (`reportes/reporte_b1_observador_
fallback_20260824_185851/`) -- verificado en `viajes.csv`:
`RUTA_CALCULADA`, 35.50 km, 48.78 min.

**Estado: BLOQUE VALIDACIÓN TERRITORIAL T2 CERRADO EN CÓDIGO Y EN
DRIVE REAL. Sin push en ninguno de los dos repos.**

## Bloque CATCH-UP LOGÍSTICO RETROACTIVO -- pipeline actual aplicado a todos los pendientes (2026-08-24)

**Generalizaciones (nunca por guía):** (1) Vía C (fallback estructurado)
ahora también se intenta cuando el principal deja UN ÚNICO candidato de
confianza insuficiente (antes sólo en el camino ambiguo) -- "sólo si A
falla" cubre cualquier forma de que A falle. (2) `SIN_ACCESO_VIAL`
también reintenta con el candidato del fallback (mismas reglas de
corroboración de Vía C), no sólo con coordenadas ya presentes en un
destino confirmado. (3) Detección de número de calle generalizada
(`_numeros_de_calle`) para reconocer un patrón OCR real (símbolo de
numeral "Nº"/"N°" pegado como una letra al número, p. ej. "O1148") sin
volver a leer el documento.

**Diagnóstico automático (sin asumir la lista conocida):** 6 viajes con
`estado_ruta != RUTA_CALCULADA` detectados en el dataset real: 460807,
464981, 472008, 472044, 472073, 472163.

**Resultado E2E (copia real + Drive real, idéntico):**
`guias_actualizadas: []` -- ninguno cambió, con causa demostrada caso
por caso (nunca inventado):
- **472044** (`PUERTA DEL SOL 83`): fallback consultado, Nominatim sólo
  devuelve "Chile" (sin número) -- `CONFIANZA_INSUFICIENTE` real tras
  agotar candidatos.
- **472073** (`PDTE. RIESCO 5903 LAS CONDES`): fallback consultado, dos
  candidatos sin número de calle coincidente -- `SIN_ACCESO_VIAL` real
  tras fallback.
- **460807/472008** (`INTERIOR NUEVA O1148 SAN BERNARDO`): número ya
  detectado generalizadamente, pero Nominatim no encuentra ningún
  candidato con ese número en esa comuna -- `COORDENADA_NO_CONFIRMADA`
  real tras agotar candidatos.
- **472163** (`VIA MORADA 6480 VITACURA`): Nominatim SÍ encuentra un
  candidato exacto (confianza 0.9), pero el destino de esta dirección
  está `PENDIENTE` (nunca `CONFIRMADO`) y B1 nunca investigó -- ninguna
  corroboración disponible; aceptar igual sería exactamente "adivinar".
  Queda `SIN_ACCESO_VIAL` real, con la evidencia estructurada visible
  para una futura decisión humana o investigación B1 explícita.
- **464981** (origen, `SIN_EVIDENCIA_GPS`): `estado_telemetria` ya
  poblado (`SELECCIONADO`) -- la reconciliación de telemetría ya corrió
  sin encontrar trips en la ventana; ningún viaje del dataset real quedó
  con telemetría sin conectar. Causa final ya demostrada, no un "nunca
  se intentó".
- **Control 472037:** permanece `RUTA_CALCULADA`, 35.50 km / 48.78 min
  -- no se degradó.

**Tests:** Motor -- `tests/test_fallback_geografico_estructurado.py` (7
nuevos: candidato único con confianza insuficiente + control,
SIN_ACCESO_VIAL con fallback + control, generalización de número OCR +
2 controles). Suite completa: 1778 passed (antes 1771).

**Aplicado a Drive real:** 1 backup verificado (`respaldos/
B1_OBSERVADOR_FALLBACK_PRE_20260824_192352/`, SHA-256 antes/después).
`guias_actualizadas: []` -- honesto: el catch-up ya corrió sobre estos
mismos pendientes en el bloque anterior; ningún dato cambió porque cada
causa restante ya está genuinamente demostrada, no porque el pipeline
no se ejecutara.

**Estado: BLOQUE CATCH-UP LOGÍSTICO RETROACTIVO CERRADO EN CÓDIGO Y EN
DRIVE REAL. Todos los pendientes actuales tienen causa final
demostrada (Sección 8B) o ruta calculada (Sección 8A); ninguno conserva
un motivo obsoleto. Sin push en ninguno de los dos repos.**

## Bloque CIERRE DEFINITIVO DE LOGÍSTICA RESIDUAL ACTUAL (2026-08-24)

**Generalizaciones (nunca por guía):** (1) `NominatimGeocoder` ahora
intenta consulta ESTRUCTURADA (`street=`/`city=`, con comuna
auto-detectada del catálogo territorial cerrado en los últimos 1-3
tokens del texto) antes de la libre (`q=`) -- verificado en vivo:
significativamente más precisa para número de calle exacto. (2) Si la
calle completa no encuentra el número, reintenta progresivamente con
menos palabras al principio (nunca inventa un nombre nuevo, sólo
subconjuntos del texto ya presente) -- resuelve abreviaturas como
"PDTE." sin una lista de abreviaturas hardcodeada. (3) Vía C
(`resolver_destino_con_fallback_estructurado`) gana una TERCERA vía de
corroboración: si el propio texto documental confirmado ya menciona,
explícitamente, la comuna del candidato (`_comunas_explicitas`, catálogo
cerrado), corrobora -- sin depender de un destino aparte o de B1. (4)
Nueva `revalidar_destino_confirmado_desde_ledger_sin_ocr`: corrige
retroactivamente la etiqueta de un destino CONFIRMADO cuando el ledger
(`REGISTRAR_DIRECCION`) ya registra una dirección más específica que la
persistida en el catálogo -- general, recorre todo el ledger, no una
guía. (5) `NominatimGeocoder.version` subida a "v2" -- la consulta
estructurada cambia materialmente los resultados; sin esto, caché vieja
serviría respuestas obsoletas para siempre.

**6 casos (antes -> después):**
- **472044** (`PUERTA DEL SOL 83`): catálogo tenía la etiqueta degradada
  ("Las Condes, RM, Chile") de un bug anterior nunca corregido
  retroactivamente -- corregida vía ledger, luego geocodificada
  (estructurada) y corroborada por el propio texto documental.
  `RUTA_CALCULADA`, 26.058 km.
- **472073** (`PDTE. RIESCO 5903 LAS CONDES`): consulta libre encontraba
  sólo avenidas sin número; la estructurada con reintento sí encuentra
  "Avenida Presidente Riesco 5903" exacto, corroborado por "LAS CONDES"
  en el propio texto. `RUTA_CALCULADA`, 14.7369 km.
- **472163** (`VIA MORADA 6480 VITACURA`): mismo mecanismo, "Vía Morada
  6480" exacto, corroborado por "VITACURA" en el texto. `RUTA_CALCULADA`,
  29.9961 km.
- **460807/472008** (`INTERIOR NUEVA O1148 SAN BERNARDO`): estructurada y
  libre agotadas -- Nominatim no tiene ese número indexado en San
  Bernardo. `COORDENADA_NO_CONFIRMADA(3)` real, causa específica ya
  verificada, no genérica.
- **464981** (origen): `planta_origen_id` sigue vacío -- bloqueo es de
  origen/GPS, nunca llega a geocodificar destino; no existe en el
  código ningún mecanismo calibrado de inferencia de planta por
  patrón histórico de chofer/vehículo (verificado, no se inventó uno
  nuevo en este bloque). `SIN_EVIDENCIA_GPS`/`ORIGEN_NO_DETERMINADO`
  real.
- **Control 472037:** permanece `RUTA_CALCULADA`, 35.5038 km -- no se
  degradó.

**Tests:** Motor -- `tests/test_rutas_nominatim.py` (+5: detección de
comuna final, reintento con calle reducida, control sin comuna
reconocible, fallback a libre); `tests/test_destino_confirmado_desde_ledger.py`
(nuevo, 5 tests: corrección desde ledger, control ya-específico,
control tipo/acción distinto, control ledger ausente, control
destino_id inexistente); 4 tests existentes ajustados para inyectar
`proveedor_rutas_fallback` explícito (antes construían por defecto un
`NominatimGeocoder` real -- no determinista una vez que "Puerta del Sol
83, Las Condes" pasó a ser resoluble de verdad). Suite completa: 1787
passed (antes 1778).

**Aplicado a Drive real:** backup verificado (`respaldos/
CIERRE_LOGISTICA_RESIDUAL_PRE_20260824_203826/`, SHA-256 antes/después
de 4 archivos). `guias_actualizadas: ["472044", "472073", "472163"]`.
Dataset: 20 viajes, 17 con ruta (antes 14), 3 sin ruta (antes 6).
Catálogo: 2 destinos corregidos vía ledger. Reporte regenerado
(`reportes/reporte_cierre_logistica_residual/`), `reporte_vigente`
publicado, `decisiones_pendientes.json` en 0, hash del dataset
sincronizado.

**Estado: BLOQUE CIERRE LOGÍSTICA RESIDUAL CERRADO EN CÓDIGO Y EN DRIVE
REAL. 3 de 6 casos resueltos con ruta calculada y dirección específica;
3 quedan en causa final genuinamente demostrada (no premature). Ninguna
dirección canónica degradada en las 20 guías. Sin push en ninguno de
los dos repos.**

## Bloque FIX DE ACEPTACION -- variación ortográfica/OCR menor no pide registrar entidad conocida (2026-08-24)

**Causa:** la resolución de OBRA_DESCONOCIDA (`_decisiones_obra_para_
cliente`) sólo comparaba por igualdad EXACTA normalizada (nombre
canónico + alias) -- sin ningún paso de similitud, un typo de UN solo
carácter en un solo token ("SALOMON SACK SA SAN BERNGARDO" vs la obra
ya CONFIRMADA "SALOMON SACK SA SAN BERNARDO") bastaba para generar una
pregunta a Javier sobre una entidad que Atlas ya conocía.

**Regla general:** nueva `coincide_salvo_variacion_ortografica_menor`
(`motor_evidencia_obras.py`, distancia de Levenshtein, sin dependencias
externas) -- calibrada y estrecha, mismo principio ya probado en
producción para patentes de vehículo (`_diferencia_ocr_segura`): mismo
número de tokens, TODOS idénticos salvo uno, ese token a distancia de
edición == 1 y con al menos 6 caracteres (piso de seguridad contra
palabras cortas). `resolver_obra_por_variacion_ortografica_menor` sólo
autorresuelve si hay exactamente UN candidato CONFIRMADO del mismo
cliente -- con dos o más, se abstiene (sigue yendo a Javier). Wireado
en `_decisiones_obra_para_cliente` (detección, antes de crear la
decisión) y en nueva `revalidar_obra_desconocida_por_variacion_
ortografica_sin_ocr` (retira retroactivamente decisiones YA
persistidas, aprende el alias vía `actualizar_identidad_obra` con
evidencia GUIA -- nunca CONFIRMACION_HUMANA, nunca una regla global de
texto). No hardcodea BERNGARDO->BERNARDO -- funciona para cualquier
variación de un token que cumpla el mismo criterio calibrado.

**460861 (antes -> después):** 1 decisión OBRA_DESCONOCIDA pendiente ->
0. Obra canónica = "SALOMON SACK SA SAN BERNARDO" (no se creó entidad
nueva); alias "SALOMON SACK SA SAN BERNGARDO" aprendido en el catálogo
real (`obra_id e177cdfd-...`); ruta/destino ya estaban calculados
(RUTA_CALCULADA, 21.7619 km) y se conservaron intactos.

**B1/aprendizaje:** este bloque resuelve por evidencia INTERNA
determinística (catálogo propio), nunca invoca B1 -- eficiencia
(Sección 7). El aprendizaje es el alias persistido, atado a esta obra
específica, reutilizable por cualquier guía futura con el mismo texto
exacto (comparación EXACTA, sin recalcular la variación).

**Tests/commit:** 15 tests focales nuevos (motor_evidencia_obras:
casos A/B/C/D + controles; decisiones_pendientes: detección en vivo +
no repregunta destino; revalidacion_documental: retroactivo + 4
controles). Suite completa: 1807 passed (antes 1787). E2E contra copia
real + aplicado a Drive real con backup+SHA-256 (`respaldos/
FIX_ACEPTACION_460861_PRE_20260824_222951/`). Sin push.

## Bloque FIX DE ACEPTACION -- número de casa corrompido por OCR ya no degrada la dirección canónica (2026-08-24)

**Causa:** `_trae_numero_calle` (proxy de "tiene dirección específica",
usado por `_etiqueta_geocodificada_o_texto_documental`) sólo reconocía
dígitos PUROS (`\b\d{1,6}\b`). Caso real 472247: el documento trae
"CAMINO A MELIFILLA 1OBOD SANTIAGO MAIPU" -- el OCR mezcló letras
DENTRO del número de casa ("1OBOD"), un patrón de ruido distinto del ya
cubierto (letra pegada ADELANTE de dígitos, "O1148"). Sin un token
reconocible como número, la etiqueta genérica del geocoder ("Maipú, RM,
Chile") ganaba pese a que el destino operacional ya tenía ruta
calculada (34,9 km / 47,6 min).

**Regla general:** `_trae_numero_calle` ahora también reconoce
cualquier token corto (2-6 caracteres) que mezcle dígitos y letras en
CUALQUIER posición -- nunca decodifica ni asume el valor real, sólo
reconoce la FORMA (mismo principio barato ya documentado). Un token
puramente alfabético (comuna, palabra estructural) sigue sin calificar
-- exige al menos un dígito. Aplica a CUALQUIER guía con esta forma de
ruido OCR, no sólo 472247 (472212, con el mismo patrón "10B00" en la
misma calle, se corrigió en la misma pasada).

**472247 (antes -> después):** `direccion_entrega` "Maipú, RM, Chile"
-> "CAMINO A MELIFILLA 1OBOD SANTIAGO MAIPU"; 34.8694 km / 47.61 min
intactos (nunca se reintentó routing); `estado_ruta` sin cambios.

**Tests/commit:** 5 tests focales nuevos en `test_logistica_l1.py`
(unidad: caso real + control alfabético puro; integración: 472247
completo con km/tiempo intactos). Suite completa: 1810 passed (antes
1807). Aplicado a Drive real con backup+SHA-256 (`respaldos/
FIX_DIRECCION_CANONICA_472247_PRE_20260824_224353/`). Sin push.

## Bloque FIX FINAL DE ACEPTACION -- dirección canónica gana sobre OCR corrupto vía documentos hermanos (2026-08-24)

**Causa:** el fix anterior preserva texto documental ESPECÍFICO sobre
una etiqueta genérica, pero no distingue un texto específico LIMPIO de
uno específico pero CORROMPIDO por OCR ("CAMINO A MELIFILLA 1OBOD
SANTIAGO MAIPU" -- calle Y número corrompidos). Sin comparación contra
otra fuente, Atlas no tiene forma de saber que ese texto, aunque
específico, no es el correcto.

**Regla general:** nueva `resolver_direccion_canonica_mas_limpia`
(`destino_entrega.py`) compara el texto objetivo contra candidatos
(documentos hermanos del mismo cliente + destinos ya CONFIRMADOS) por
alineación de tokens -- misma cantidad de tokens, mayoría idéntica,
MENOS tokens con forma de ruido OCR (dígito+letra mezclados, mismo
criterio ya calibrado). Nunca mapea caracteres ("MELIFILLA->MELIPILLA"
no existe en el código); si sobreviven dos candidatos limpios DISTINTOS,
se abstiene (nunca elige entre direcciones reales parecidas). Nueva
`revalidar_direccion_entrega_por_documentos_hermanos_sin_ocr`, wireada
DESPUÉS de la revalidación anterior, mismo alcance (sólo `RUTA_
CALCULADA`, nunca toca km/tiempo/ruta/`despachar_a_crudo`).

**472247/472212 (antes -> después):** ambas mostraban su propio texto
OCR-corrupto ("...MELIFILLA 1OBOD..." / "...MELIPILLA 10B00...") --
ahora ambas muestran "CAMINO A MELIPILLA 10800 SANTIAGO MAIPU" (la
forma limpia del documento hermano 464981, mismo cliente AMERICAN SCREW
CHILE SPA). km/tiempo/ruta intactos en ambas (34.8694/47.61 y
35.3246/49.43).

**Tests/commit:** 8 tests focales nuevos en `test_logistica_l1.py`
(unidad: caso real + regresión "no sustituir por parecido débil" +
ambigüedad + control ya-limpio + sin candidatos; integración: 472247+
472212+464981 juntos + control de aislamiento por cliente). Suite
completa: 1818 passed (antes 1810). Aplicado a Drive real con
backup+SHA-256 (`respaldos/FIX_DIRECCION_CANONICA_HERMANOS_PRE_20260824_230054/`).
Sin push.

## Bloque FINAL CORE V1 -- cierre de los 3 históricos residuales sin ruta (2026-08-24)

**460807/472008 (AUSIN SAN BERNARDO):** identidad ya conocida, nunca
reinvestigada -- ningún geocodificador indexa "INTERIOR NUEVA O1148 SAN
BERNARDO" a nivel de número. Nueva `revalidar_ruta_por_convergencia_
gps_historica_sin_ocr`: para cada obra, calcula `punto_gps_destino`
(recorrido de entrega ya cacheado por telemetría -- `enriquecer_
documento_con_telemetria`, sin red) de TODAS sus filas; si al menos DOS
observaciones históricas independientes convergen dentro de
`MARGEN_MISMO_LUGAR_KM` (1 km, ya calibrado), ese punto se acepta como
operacional/ruteable -- nunca con una sola observación. Caso real: las
DOS entregas históricas (460807 18-08, 472008 18/19-08) convergen en la
MISMA coordenada exacta (-33.543683,-70.704833). Punto persistido en el
destino ya CONFIRMADO (`05b006b6-...`) para reuso automático futuro.
**Antes -> después:** ambas `COORDENADA_NO_CONFIRMADA(3)` -> `RUTA_
CALCULADA` (460807: 18.45 km/26.72 min desde AZA RENCA; 472008: 51.47
km/62.07 min desde AZA COLINA).

**464981 (origen sin GPS):** "sin GPS en SU ventana" no es lo mismo que
"sin evidencia de origen". Nueva `revalidar_origen_por_vecinos_
temporales_gps_sin_ocr`: busca, para el MISMO vehículo, viajes vecinos
(±5 días) cuyo origen ya fue CONFIRMADO por GPS (nunca por documento,
menos confiable por diseño ya vigente del resto del sistema) -- si TODOS
convergen en una misma planta (nunca "el chofer normalmente carga en
X": exige ≥2 observaciones GPS reales, cero en desacuerdo), esa planta
se acepta. Caso real: 3 viajes GPS-confirmados inmediatamente
posteriores (472018/472099/472162, mismo vehículo DD2494) convergen en
AZA COLINA -- material también consistente (ALAMBRON AZA 1006). Con la
planta resuelta, `revalidar_ruta_sin_destino_calculado_sin_ocr` (ya
existente) calcula la ruta en la MISMA pasada. **Antes -> después:**
`ORIGEN_NO_DETERMINADO`/`SIN_EVIDENCIA_GPS` -> `RUTA_CALCULADA` (35.32
km/49.43 min, dirección canónica "CAMINO A MELIPILLA 10800 SANTIAGO
MAIPU" ya aprendida en el bloque anterior).

**B1:** no se invocó -- ambos casos resueltos con evidencia
estructurada determinística ya cacheada (Motor-level), sin necesitar
discriminación adicional.

**Rutas finales:** 23/23 viajes con `RUTA_CALCULADA` (100%). 0
decisiones pendientes. Control 472037 intacto (RUTA_CALCULADA, 35.50
km/48.78 min, sin cambios).

**Tests/commit:** 11 tests focales nuevos en `test_final_core_v1.py`
(vecinos temporales: caso real + 5 regresiones -- una sola observación,
dos plantas plausibles, vecino documental no cuenta, fuera de ventana,
planta ya resuelta no se reinvestiga; convergencia GPS: caso real +
control una sola observación + puntos no convergentes + ruta ya
calculada intacta + aprendizaje persistido). Suite completa: 1829
passed (antes 1818). E2E contra copia real + aplicado a Drive real con
backup+SHA-256 (`respaldos/FINAL_CORE_V1_PRE_20260824_234320/`). Sin
push.

**ATLAS CORE V1 -- TÉCNICAMENTE CERRABLE: SÍ.** Los 3 históricos
residuales quedaron con `RUTA_CALCULADA` real (no un límite aceptado);
0 decisiones pendientes; 0 regresiones; identidades/aprendizaje
reutilizados sin reinvestigar; B1 no necesitó intervenir.

## Bloque CONSULTAS ATLAS V1 -- preguntas en lenguaje natural sobre la operación real (2026-08-25)

**Arquitectura (Bloque 1/22):** separación estricta interpretación/
cálculo. `atlas_core/consultas_atlas.py` -- contrato `ConsultaAtlas`
(métrica/filtros/agrupación/orden/límite), `validar_consulta` (rechaza
cualquier campo inventado) y `ejecutar_consulta_atlas`, única autoridad
de cálculo -- lee `viajes.csv` (el mismo reporte que ya consume
Desktop), nunca inventa un dato. `atlas_core/interpretador_consultas.py`
-- camino rápido determinístico: vocabulario de palabras clave (nunca
una función por pregunta) + `resolver_entidad_por_palabras` (reutiliza
el mismo criterio de coincidencia parcial que ya usa Desktop, aplicado
a chofer/cliente/obra/tipo de carga/comuna construidos desde el propio
dataset cargado -- nunca un catálogo paralelo). `atlas_core/
proveedor_interpretacion_consultas.py` -- B1 real (misma mecánica HTTP/
credencial que `atlas_ia.proveedor_anthropic`, esquema propio vía
tool-use forzado) sólo si el camino rápido no reconoce ninguna métrica;
su salida pasa por el MISMO validador antes de ejecutarse.
`atlas_core/responder_consulta_atlas.py` orquesta todo y formatea la
respuesta breve (Bloque 11). `consultar_atlas.py` (raíz) -- CLI que
Desktop invoca por IPC, JSON ASCII (mismo criterio ya establecido para
consola Windows), columnas de soporte recortadas a lo que la UI
muestra.

**Métricas/filtros:** COUNT_VIAJES, COUNT_GUIAS, SUM_PESO, SUM_KM,
SUM_TIEMPO, LISTAR_VIAJES; filtros chofer/cliente/obra/destino/comuna/
material/tipo_carga/patente_tracto/patente_rampla/estado/numero_guia/
numero_transporte/período; agrupación por chofer/cliente/obra/destino/
comuna/material/tipo_carga/día/semana/mes. `tipo_carga` (enumeración
cerrada) exige coincidencia exacta; `material` (texto libre) usa
subcadena -- nunca se mezclan (Bloque 7). Bug real encontrado y
corregido durante el desarrollo: una coincidencia débil de una familia
(p. ej. "Salomon" con el chofer "SALOMÓN PIZARRO") podía sobre-
restringir una consulta ya resuelta por una familia más fuerte
(cliente "SALOMON SACK SA") -- ahora la evidencia más fuerte
"reclama" sus palabras y la más débil, subsumida, se descarta. Segundo
bug: un nombre propio no reconocido ("Lazcano") se ignoraba en
silencio y la consulta respondía sobre TODOS los viajes -- ahora se
detecta y se reporta explícitamente en vez de adivinar.

**B1/costo (Bloque 21):** cero llamadas B1 en los 6 casos E2E
requeridos -- todos deterministas. B1 sólo se conecta si hay
`ANTHROPIC_API_KEY`; sin ella, o si aun así se abstiene, la respuesta
es "no interpretable", nunca un error de proceso ni un número
inventado.

**Desktop:** nueva pestaña "Pregúntale a Atlas" (mismo estilo de
navegación ya cerrado), caja de pregunta + botón Consultar, respuesta
breve + filtros interpretados + tabla de viajes soporte expandible.
IPC `atlas:consultar-atlas` (mismo patrón `spawn('py', ['-3', '-u', ...])`
ya usado para el resto del pipeline) -- read-only, nunca escribe nada.

**Resultados E2E reales (Bloque 19, contra los 21 viajes vigentes):**
A) Villagra este mes: 3 viajes. B) Listar viajes de Villagra: 3 filas
reales. C) Con rollos: 6 viajes. D) Toneladas por chofer: 9 choferes,
top LUIS VARAS 137.05 t. E) Para Salomon Sack: 2 viajes. F) Villagra +
rollos + este mes: 0 (Villagra sólo transportó BARRAS este mes -- cero
resultados, no error). Los 6 verificados directamente contra el
dataset real, cifra por cifra.

**Seguridad/trazabilidad (Bloque 9/13/14/18/20):** toda cifra sale del
ejecutor determinístico, nunca del LLM; toda respuesta trae
`viajes_soporte` real e inspeccionable; cero resultados nunca es error;
ambigüedad real (dos choferes "Juan") nunca se resuelve sola --
devuelve opciones; read-only estricto, ninguna función escribe dataset/
catálogos/decisiones.

**Tests:** Motor -- 68 tests focales nuevos (contrato/validador/
períodos/métricas/filtros/agrupaciones en `test_consultas_atlas.py`;
resolución de entidades/vocabulario/ambigüedad/colisión entre familias
en `test_interpretador_consultas.py`; orquestador/B1 en
`test_responder_consulta_atlas.py`; mecánica HTTP de B1 en
`test_proveedor_interpretacion_consultas.py`; CLI en
`test_cli_consulta_atlas.py`) + 7 E2E reales en
`test_consultas_atlas_e2e.py`. Suite completa: 1897 passed (antes
1829).

## Bloque GUÍAS MÓVILES V1 -- Mobile entra al mismo Motor que Desktop (2026-08-25)

**Diagnóstico (inspección mínima):** el backend Mobile (`atlas_core/mobile.py`,
`servidor_mobile.py`, `resolver_envio_mobile.py`) y la bandeja Desktop
("Guías móviles" + "Revisión de Atlas") ya existían y eran reales -- HTTP
real, autenticación, almacenamiento durable idempotente, procesamiento
automático en segundo plano. El hueco real: `procesar_envio_mobile`
llamaba a `procesar_archivo` SIN catálogos/decisiones/recolector y NUNCA
escribía la fila resultante en el dataset compartido -- una guía Mobile
genuinamente nueva quedaba encerrada para siempre en su propio JSON,
sin ruta posible hacia Viajes salvo que alguien la volviera a cargar a
mano por Desktop (lo que habría duplicado el OCR).

**Fix (mismo Core, no uno paralelo):** `procesar_envio_mobile` ahora
llama a `procesar_archivo` con `carpeta_catalogos`/`recolector_decisiones`
(mismos argumentos que usa `procesar_carpeta` por archivo) y persiste la
fila resultante en el dataset real vía `_escribir_filas`/`COLUMNAS` --
la MISMA función que ya usa el lote de Desktop. `asociar_documento` gana
`documento_ya_existe` (coincidencia exacta por número de guía): si el
documento ya está representado, nunca se agrega una fila duplicada
(Sección 9). Las decisiones nuevas se fusionan (nunca pisan) con
`decisiones_pendientes.json` ya publicado por Desktop.

**Captura vs. Incidencia Documental (Sección 10):** si el OCR no logra
leer ni guía ni transporte (foto ilegible/cortada), se marca
`problema_captura=true` y NO se escribe fila en blanco -- nunca se
confunde con una Incidencia Documental. Si el propio Core marca
`indicador_revision=REVISAR` (regla ya existente, igual que Desktop), el
envío pasa a REQUIERE_REVISION con la fila igual persistida.

**B1/trazabilidad:** sin cambios de mecanismo -- sigue usando
`escalar_resultado_ia_en_memoria`/`_ejecutar_ia_operacional`, la misma
función que ya usa el lote (0 llamadas si el Core resuelve solo).
`servidor_mobile.py` resuelve catálogos vía `ATLAS_CATALOGOS_DIR` (misma
variable que usa `analizar_guias_masivo.py`, nunca una config paralela).

**Desktop:** ajuste mínimo en las 2 vistas que ya mostraban el motivo de
revisión (Revisión de Atlas + historial "Guías móviles"): si
`problema_captura` es true, el mensaje dice "pedir foto nueva" en vez del
motivo genérico de asociación. El resto de la bandeja (foto, OCR,
"Ver viaje asociado", filtros) no cambió -- ya cumplía la Sección 5/6.

**Tests:** Motor -- 9 tests focales nuevos en `test_mobile_guias_v1.py`
(persistencia de guía nueva, no duplicar guía ya existente, no duplicar
por reproceso del mismo envío, captura ilegible vs. indicador_revision
del Core, dataset de esquema reducido nunca recibe escritura completa,
decisiones pendientes de Desktop no se pierden, envio_id con traversal
rechazado, E2E HTTP real con reintento). Suite completa: 1906 passed
(antes 1897). Desktop -- 2 tests focales nuevos en
`guias_moviles_v1.test.js`. Suite completa: 322 passed. Mobile
(`Atlas-Conductores-Mobile`) -- sin cambios de código; no se corrió su
suite (regla de la Sección 20: sólo suites de repos modificados).

**Pendiente real:** telemetría GPS/rutas (`servicio_telemetria`) no se
conecta desde Mobile (opt-in, mismo criterio que Desktop sin bandera
explícita -- no bloquea ningún caso E2E); la app Mobile en sí no
necesitó cambios (Sección 13/14 ya estaban cerradas).
