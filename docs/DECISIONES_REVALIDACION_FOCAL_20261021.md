# Decisiones operacionales: revalidación focal — 21/10/2026

## Causa

`aplicar_decision_obra` llamaba a `revalidar_y_regenerar_reporte` después de cerrar una decisión como OBRA_DESCONOCIDA/REGISTRAR, sin identificar las guías afectadas. Filtrar cada regla por su propio motivo no limita el alcance causal: cualquier otra fila elegible podía volver a evaluarse y perder o cambiar destino/estado. El comentario que afirmaba que los viajes ajenos quedaban intactos era incorrecto.

Había otras vías de escape: reparación de dataset_sha256 obsoleto dentro de aplicar_decision_obra, fallback de DecisionObsoletaError del CLI, batería agregada de un lote y reconciliación final del lote. Se cubrieron esas vías, además de la convergencia posterior a material ya existente. No se investigó ni restauró el destino real de 482188 ni se resolvió la revisión real de 482673.

## Cambio

Se calcula el alcance bajo el lock aplicar_decision_obra, a partir de la tarjeta vigente y del dataset: guía/documento, identidad compartida efectivamente modificada (incluidos nombres/aliases de obra y cliente correspondiente) y guías de esos mismos transportes. Los placeholders no identifican viajes. Un carro no expande el alcance por compartir tracto; una acción de rechazo que no cambia entidad no expande otros viajes por esa entidad.

El ContextVar de alcance está ligado a la ruta exacta del dataset. Una llamada anidada solo puede reducirlo; un conjunto vacío no significa mantenimiento global y el contexto se restaura también ante excepciones. La batería conserva las reglas existentes: recibe las filas focales por el lector canónico. El escritor rechaza filas ajenas, pérdida o incorporación de documentos y fusiona los resultados focales con las demás filas del dataset vigente, conservando orden y contenido ajeno.

Las consultas de evidencia histórica (origen por cliente, vecinos GPS, rutas y direcciones hermanas) mantienen lectura completa de donantes, pero solo pueden modificar beneficiarios del alcance. El reporte completo sigue incluyendo todos los viajes. La huella semántica sigue describiendo el dataset completo y no se publica una firma de mantenimiento global a partir de una corrida focal.

La regeneración/enriquecimiento solo evalúa tarjetas focales. La publicación preserva las tarjetas ajenas completas, incluso si otra regla global las reclasificaría. Los mantenimientos generales de catálogo/ledger no se ejecutan implícitamente al corregir una guía. El mantenimiento global explícito continúa disponible con guias_objetivo=None fuera de un alcance operacional.

Los lotes acumulan la unión de los alcances de sus decisiones y la transmiten tanto a la batería diferida como al cierre. El CLI de obsolescencia tampoco puede volver a abrir un alcance general.

## Evidencia de regresión

Todos los datos de prueba son sintéticos y locales; los folios reproducen la identidad de los casos para hacer visible la regresión. No se copiaron/reprocesaron guías productivas ni se cambiaron estados, revisiones o catálogos reales.

- Aplicar REGISTRAR a 482553 deja idénticos todos los campos de 482673/SIGRO y 482188/OKO CONSTRUCTORA, incluyendo destino, km, tiempo, motivos y estados. Sus tarjetas pendientes también son idénticas; el ledger solo incorpora 482553.
- La guía hermana 482554 del mismo viaje y 482555 de la misma obra en otro viaje sí reciben convergencia; el alcance publicado es exactamente esas tres guías.
- La prueba atraviesa también desktop_operacion.ejecutar → CLI aplicar_decision_pendiente → aplicar_decision_obra, usando el escritor real sobre raíz temporal.
- Se comprueba el cierre de lote real y la reparación de obsolescencia sin cambios en las dos guías ajenas.
- Los registros completos de los viajes ajenos en viajes.csv son iguales antes/después, con reloj fijo para comparar datos y no timestamps de generación.
- El origen focal puede resolverse por historial de guías donantes de otros viajes sin modificar ninguna de ellas.
- Se prueban alcance vacío, límites de escritura, contextos anidados, restauración tras excepción, separación por cliente, placeholders de transporte, carro frente a tracto y rechazo sin modificación de entidad.
- La misma fixture muestra que la batería global anterior sí cambiaba una fila ajena; la prueba no depende de que las filas extra sean inelegibles para revalidación.

Una prueba antigua exigía abrir una tarjeta AMBIG1 expresamente ajena al confirmar otra guía. Se corrigió ese contrato: la decisión focal no la abre; una llamada explícita de mantenimiento global sí puede descubrirla. La idempotencia compara dos corridas con el mismo alcance.

## Compatibilidad y límites

La suite ampliada detectó tres fallos previos de tests/test_decisiones_pendientes.py, reproducidos también en un worktree limpio de f05b154:

- test_obra_existente_sin_relacion_confirmada_y_caso_confirmado
- test_destino_sin_confirmar_sin_despachar_a_no_rompe_y_usa_obra_como_respaldo
- test_obra_global_reconocida_por_otro_cliente_no_genera_obra_desconocida

Base aislada: 42 aprobadas y esas mismas 3 fallidas (7,78 s). No se cambió su lógica ni los catálogos para resolverlas. También se verificó y conservó la identidad del objeto devuelto en un cache hit del regenerador; esa regresión detectada durante el desarrollo quedó corregida.

No se modificaron OCR, Desktop, formatos de catálogo ni datos productivos. El trabajo no recupera los destinos ya afectados: evita que nuevas decisiones repitan la revalidación general.

## Cierre de validación y disponibilidad

Aceptación final: 212 pruebas aprobadas y 3 excluidas por ser los fallos previos reproducidos en f05b154 (42,63 s). Comprobaciones focales adicionales de núcleo, convergencia GPS, coordenadas verificadas e historial de obra: 24/24 aprobadas (5,06 s). Total: 236 aprobadas, incluidas 13 pruebas nuevas del alcance. Logs locales C:/Atlas/pruebas/decisiones-focal-aceptacion.log, decisiones-focal-historial.log y decisiones-base-resultado.log.

Se verificó ausencia de procesos Python operacionales activos antes del cierre. La configuración de CASA apunta a C:/Atlas/Proyecto-Atlas: los próximos procesos cortos del escritor Desktop cargarán esta versión del Motor. No se requiere cambiar/reinstalar/reiniciar Desktop ni iniciar un escritor, OCR, reconciliación o PULL productivo para dejar disponible el código. No se desplegó nada en OFICINA ni se cambiaron tareas o procesos PULL.
