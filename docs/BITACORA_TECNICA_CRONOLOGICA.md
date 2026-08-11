# Bitácora Técnica Cronológica — Proyecto Atlas

Registro técnico, en orden cronológico, de cambios de código sobre el lector de guías. Un bloque por entrada, con archivos modificados, decisión de diseño y validación.

---

## 2026-08-11 — Cierre: OPERACIÓN O1.1 (validación ciega, NO APROBADO) + O1.2 (corrección dirigida, APROBADO)

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `4822e9e1e31a9b7e42dbd4c887324bdbdf777159` (cierre de O1)

### O1.1 — validación ciega independiente (metodología, sin cambios de código)

- Muestra independiente de **16 guías reales**: 14 reutilizadas de D2/D3/D3.1/E1 (`ux_r2_sincronizacion/entrada_14_guias/`, nunca usadas para calibrar reglas de peso/hora) + **2 genuinamente nuevas**, halladas en `datos/entradas/` de una instalación Desktop real (`463594` Villagra, `463630` Ñancucheo).
- Metodología: se corrió el pipeline real (`procesar_archivo`) y se **congeló la predicción en JSON antes de mirar cualquier imagen**; solo después se inspeccionó cada imagen visualmente (autoridad final, por encima del ground truth de planillas).
- **Veredicto: O1 NO APROBADO.** 3 patrones reales de falla:
  1. **Hora corrupta con dígitos adyacentes** (`464264`, `463630`): el OCR pega un dígito extra al inicio del valor horario ("112:15:18" en vez de "12:15:18"). Causa raíz exacta, trazada carácter por carácter: el regex anterior `\b([0-2]?\d):([0-5]\d)(?::[0-5]\d)?\b` no tiene límite de palabra (`\b`) entre dos dígitos consecutivos, pero **sí** lo tiene justo después de un `:` — el motor de regex "reinicia" el match ahí, capturando el sub-tramo `"15:18"` como si fuera una hora propia y descartando el `"112:"` corrupto en silencio. Mismo patrón produjo `"29:55"` (hora inválida, >23) en 463630.
  2. **PESO KG con línea intermedia** (`464264`): el ancla exigía adyacencia casi inmediata; una línea no relacionada ("ENTREGA 06.08 08:00 AM") intercalada entre "PESO KG." y su valor real ("17.150,00", que el OCR sí leyó bien) rompía el match — el extractor no encontraba nada (`ERROR_EXTRACTOR`).
  3. **Error OCR puro** (`464367`): el propio motor OCR leyó un dígito equivocado dentro de un valor por lo demás bien formado ("27.410,00" en vez de "27.610,00", 4 en vez de 6) — confirmado comparando la imagen real contra el texto crudo de PaddleOCR. No es un fallo del extractor.
- Política **MULTIGUÍA funcionó correctamente** durante O1.1, sin cambios necesarios.

### O1.2 — corrección dirigida (Fases A-I)

- **`atlas_core/extractor.py` — `buscar_horas()` (patrones 1 y 2 de O1.1):** rediseño "token maximal + match completo". En vez de buscar `\b`-anchored en cualquier posición, se toma cada tramo MAXIMAL de `[\d:]+` como un solo candidato y se exige que el token COMPLETO (nunca un sub-match) calce con `_PATRON_HORA_TOKEN_COMPLETO = ^([01]?\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?$`. Si el token no calza entero (dígito de más al inicio o al final), se descarta completo y se sigue con el siguiente tramo de la ventana — nunca se "recorta" para salvarlo. La validación de rango horario (00-23/00-59/00-59) queda estructuralmente garantizada por las clases de caracteres del propio regex, sin lógica adicional.
  - **Bug adicional descubierto y corregido durante la implementación** (no reportado explícitamente por O1.1, pero expuesto por el fix anterior): el fallback "asumir ENTRADA == SALIDA cuando no hay otro candidato" (ya existente desde O1, legítimo en casos reales como la guía `387789`) reutilizaba ciegamente el valor de ENTRADA también cuando la ventana de SALIDA sí tenía un token, pero corrupto (caso `464264`) — convirtiendo un falso positivo en otro falso positivo distinto (`"09:32"` en vez de `"15:18"`, ambos incorrectos). Corregido con una señal `hubo_corrupto` que solo se activa si el token descartado **contiene ":"** (evidencia real de que se intentó representar una hora) — un tramo de solo dígitos sin ":" (p. ej. un Nro. Transporte cayendo dentro de la ventana, caso real guía `387789`) nunca cuenta como corrupción. Esta distinción fue necesaria porque la primera versión del fix (contar cualquier token no-matcheante como corrupción) introdujo una regresión real en la matriz de 30 guías (387789 pasó de `EXACTO` a abstención) — detectada y corregida antes de cerrar el bloque.
- **`atlas_core/extractor.py` — `buscar_peso()` (patrón 3 de O1.1, línea intermedia):** tras el ancla `PESO\s*KG\.?`, se busca en una ventana corta y controlada (`_VENTANA_PESO_CARACTERES = 60`) en vez de exigir adyacencia inmediata. `_PATRON_VALOR_PESO` exige al menos un grupo de miles (3 dígitos tras "." o ",") — estructuralmente no matchea fechas ("06.08") ni horas ("08:00") que puedan aparecer en la línea intercalada. Se acepta el valor **solo si hay exactamente 1 candidato** en la ventana; 0 o ≥2 candidatos → abstención (nunca se elige arbitrariamente entre varios).
- **Caso `464367` (error OCR puro, patrón no corregido por instrucción explícita):** no se introdujo ninguna regla que mapee "27410"→"27610" ni ningún ajuste específico de archivo/guía — el extractor sigue reproduciendo fielmente el dígito que el OCR entregó. Se documenta como `ERROR_OCR_REPRODUCIDO`, distinto de `FALSO_POSITIVO_EXTRACTOR`, sin señal generalizable conocida para detectarlo sin arriesgar cobertura en otros casos reales.
- **Tests nuevos:** `tests/test_extractor_peso_horas_o1_2.py`, **15 tests** (mínimo pedido: 12) — horario limpio, sub-match por dígito extra al inicio/al final, hora/minuto/segundo fuera de rango, no-regresión de entrada/salida históricas válidas, PESO KG directo y con línea intermedia, abstención ante múltiples candidatos de peso, no-regresión de conflicto multiguía, corrupción de salida con entrada duplicada (no debe reutilizar entrada), entrada==salida legítimo sin corrupción (no debe abstenerse), y documentación explícita del caso `464367` (el extractor NO lo corrige).
- Suite completa: **691 → 706 passed**, 0 failed.
- **Verificación amplia (fuera del alcance mínimo pedido, hecha por rigor):** re-ejecución completa de la matriz real de 30 guías (`datos_privados/muestra_fechas_30/`, dataset de O1) contra el código YA corregido — resultado **idéntico** al baseline pre-O1.2 (peso: 24 EXACTO/3 abstención/2 incorrecto/1 falso positivo; entrada: 28 EXACTO/2 incorrecto; salida: **30/30 EXACTO**), confirmando 0 regresiones más allá de lo cubierto por los tests unitarios. Esta corrida fue la que expuso y permitió corregir el bug adicional descrito arriba (387789).

### Revalidación ciega O1.2 (Fase H) — mismas 16 guías de O1.1

- Mismo protocolo: pipeline real ANTES de comparar contra la verdad visual ya congelada en O1.1 (`o1_validacion/prediccion_ciega_congelada.json` / matriz), sin editarla. Resultado en `o1_validacion/o1_2_prediccion.json` y `o1_validacion/matriz_validacion_o1_2.json`.
- **`464264`:** peso `17150` = EXACTO (antes `ERROR_EXTRACTOR`, ahora resuelto por la ventana de 60 caracteres). Entrada `09:32` EXACTO. Salida: abstención correcta (`No encontrado`, visual real `12:15`) — antes emitía `15:18` (falso positivo); ahora prefiere abstenerse a adivinar mal. A nivel de **viaje** (transporte `0000351135`, multiguía con `464265`), la hora de salida SÍ se recupera correctamente vía el documento hermano (`12:15`), sin conflicto — verificado con `agrupar_viajes()` real.
- **`463630`:** peso `26857` EXACTO. Entrada `10:05` EXACTO. Salida: abstención correcta (antes emitía `29:55`, hora inválida fuera de rango).
- **`464367`:** peso `27410` sin cambios (visual real `27610`) — `ERROR_OCR_REPRODUCIDO`, documentado, deliberadamente no corregido. Entrada y salida EXACTO.
- **Métricas (16 guías):** PESO 15 EXACTO + 1 ERROR_OCR_REPRODUCIDO, 0 falsos positivos del extractor, precisión bruta 93.8% (15/16), precisión atribuible al extractor 100% (15/15, excluyendo el caso OCR exento explícitamente). ENTRADA 16/16 EXACTO, 100%. SALIDA 14 EXACTO + 2 abstención correcta (cobertura 87.5%, precisión sobre emitidos 100%, 0 falsos positivos). PERMANENCIA igual patrón que SALIDA (deriva de las mismas horas).
- **MULTIGUÍA re-verificada con los 2 transportes reales** tras el fix: `0000351135` (464264+464265) y `0000352241` (464494+464495) — ambos consolidan correctamente (peso sumado, hora única, sin conflicto espurio); el test de conflicto (`CONFLICTO_HORA_SALIDA`) sigue disparando cuando corresponde.
- **Veredicto Fase I: O1.2 APROBADO** — HORA ENTRADA y HORA SALIDA con 0 falsos positivos y precisión 100% (≥95%); PESO con 0 falsos positivos del extractor y precisión 100% atribuible al extractor (el único caso restante, `464367`, es el error OCR puro explícitamente exento); MULTIGUÍA sigue funcionando correctamente.

### Fase J — reproceso del set reciente (parcial, con hallazgo relevante)

- **Set reciente identificado:** las 2 guías en `datos/entradas/` de la instalación Desktop real (`AppData\Local\Atlas`) aún no reflejadas en `viajes.csv` (`463594`, `463630`) — el resto del CSV masivo (1175 filas / **574 viajes** en `viajes.csv`) es histórico.
- **Backup completo tomado antes de cualquier cambio:** `backups_reportes/20260811_o1_2_pre_reproceso_reciente/` (`actual/`, `procesamiento/`, `entradas/` de la instalación real).
- Las 2 guías se reprocesaron con el código O1.2 y dieron **exactamente los mismos valores que la Fase H** (determinismo confirmado): `463594` peso=12367/entrada=07:31/salida=09:26/perm=115; `463630` peso=26857/entrada=10:05/salida=abstención correcta/perm=No determinada.
- **Hallazgo que detuvo la regeneración completa de `viajes.csv` en producción:** el CSV masivo actual (`analisis_completo_guias.csv`, generado por bloques posteriores de homologación de patentes — commits `0021bde`/`129b459`) tiene **1033/1177 documentos con `indicador_revision="REVISAR"`**, mientras el `viajes.csv` en producción hoy solo refleja **84/574 viajes en `REQUIERE_REVISION`** — un desfase preexistente entre el CSV masivo (más reciente/estricto) y el reporte publicado (más antiguo), **no causado por O1.2 y fuera de su alcance**. Regenerar el reporte completo con el código actual habría reclasificado ~400 viajes ya confirmados como "requiere revisión" — un efecto colateral grande, ajeno al objetivo de este bloque. **No se sobrescribió el `viajes.csv` de producción.** Confirmado con el usuario antes de intentar cualquier escritura sobre el archivo real.
- Recomendación explícita para un bloque futuro y separado: investigar y reconciliar ese desfase (probablemente requiere decidir si el criterio "REVISAR" post-homologación de patentes debe re-evaluar los 574 viajes ya confirmados, o si necesita su propia migración) antes de intentar de nuevo una regeneración completa de `viajes.csv`.

### Archivos modificados

- `atlas_core/extractor.py` (`buscar_horas()`, `buscar_peso()`, patrones `_PATRON_HORA_TOKEN_COMPLETO`/`_PATRON_VALOR_PESO`/`_VENTANA_PESO_CARACTERES` nuevos).
- Tests: `tests/test_extractor_peso_horas_o1_2.py` (nuevo, 15 tests).
- Sin cambios: Desktop (código), ORS, Onelogis, `atlas_core/rutas/`, catálogos, `atlas_core/procesamiento_masivo.py`, `atlas_core/gestor_viajes.py`, `atlas_core/reporte_viajes.py` (todos de O1, no tocados en O1.2).

---

## 2026-08-11 — Cierre: OPERACIÓN O1, peso + hora entrada/salida + permanencia en planta

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `660e5b2f912f9a803c33b94cdb2e60ad98de4293`

### Problema real confirmado

- `atlas_core/extractor.py` ya calculaba `datos["peso"]`, `datos["hora de entrada"]`, `datos["hora de salida"]` desde bloques anteriores (`buscar_peso()`, `buscar_horas()`), pero **`procesar_archivo()` nunca los incluía en su dict de salida** — se perdían antes de llegar al CSV masivo, al reporte o a `viajes.csv`.
- Auditoría real (30 guías con ground truth humano, `datos_privados/muestra_fechas_30/`, mismo dataset ya usado para calibrar `CONFIANZA_MINIMA_FECHA_FOCAL`): con el `buscar_peso()` anterior, solo **2/30** guías resolvían un peso (25/30 `No encontrado`, 3/30 con valor incorrecto). Causas exactas diagnosticadas:
  1. **Anchor roto:** el regex exigía `PESO\s*KG\s*-?\s*(...)` sin tolerar el "." de "KG." ni el ":" antes del valor -- el layout real casi siempre trae ambos entre la etiqueta y el número.
  2. **Prioridad semántica invertida:** cuando sí matcheaba algo, priorizaba "PESO BRUTO" (camión+carga) sobre "PESO KG" (neto) -- confirmado incorrecto con evidencia real (ver semántica abajo).
- `buscar_horas()` (span de texto entre "HORA ENTRADA"/"HORA SALIDA") acertaba en la mayoría de casos, pero fallaba silenciosamente -- sin señal de error -- cuando el layout de Paddle scramblea los recuadros (caso real guía 383548: el valor real de ENTRADA queda pegado a la etiqueta "HORA SALIDA", produciendo una salida incorrecta sin ningún aviso).

### Semántica de PESO (Fase B, con evidencia real)

- **"PESO KG" es el peso NETO operacional de la carga/documento** -- verificado numéricamente en múltiples guías (`PESO KG = Peso Bruto - Tara`, exacto) y confirmado visualmente contra la imagen real de la guía 464170/462491: catálogo/fallback anterior usaba "12.242,000" (Peso Bruto), el valor real impreso en "PESO KG." es "3.282,00".
- "PESO BRUTO" (camión + carga) y "TARA" (camión vacío) nunca son el peso operacional -- no se usan como principal.

### Auditoría real y hallazgo sobre la calidad del ground truth (Fase A/K)

- 30 guías con ground truth humano (`ground_truth_30_guias.json`, mismo Excel de D3) + verificación visual directa (`Read` sobre la imagen) de cada discrepancia antes de aceptarla como error de Atlas.
- **6 guías con error real de transcripción en el propio ground truth**, confirmado visualmente contra la imagen original en cada caso:
  - `410266`: el ground truth copió las horas/peso de la fila vecina (`429061`) -- la imagen real muestra `10:08:00`/`12:27:32`/`3.100,00`.
  - El archivo etiquetado `410627` en el ground truth es en realidad la guía **`410267`** (visible en la propia imagen).
  - `452388`: marcado "ilegible" (`None`) en el ground truth -- la imagen es perfectamente legible: `10:36:00`/`12:18:27`/`3.024,00`.
  - `410925`: ground truth transcribió "25.454297" (formato imposible) -- el valor real impreso es "25.618,00".
  - `461523`: ground truth transcribió "1997" pese a marcar la imagen como "perfecta" -- el valor real impreso es "10.606,00".
  - `462598`: marcado `None` por calidad de imagen borrosa en otras zonas -- el campo PESO KG específico es legible: "28.421,00".
- Tras corregir estas 6 discrepancias con evidencia visual: peso ~26/30 exacto (3 abstenciones seguras por OCR degradado -- "P" de "PESO" perdida, o un dígito insertado que la validación de rango descarta -- 0 valores incorrectos), horas ~28/30 exacto (2 confusiones de un solo dígito del propio OCR, ej. "11:56"→"11:58").

### Diseño e implementación

- **`atlas_core/extractor.py`:**
  - `buscar_peso()`: reordenado (PESO KG primero, BRUTO como último recurso) y el anchor ahora tolera "KG." + salto de línea + ":" antes del valor: `PESO\s*KG\.?\s*[:\-]?\s*([0-9][0-9.,]{1,14})`. Devuelve el valor crudo tal cual -- la normalización a kg numérico vive en `procesamiento_masivo.py`.
  - `buscar_horas()`: reescrito con `hora_mas_cercana(etiqueta, excluir=None)`, acotado a la zona de encabezado (antes de "CANTIDAD", límite estable observado en todo el muestreo). Para SALIDA, descarta explícitamente un candidato idéntico al ya asignado a ENTRADA y sigue buscando uno distinto en la misma ventana -- corrige el caso real de intercambio silencioso (guía 383548) sin perder el caso real donde ambas horas genuinamente coinciden (guía 387789, verificado con ground truth).
  - Corregido un valor histórico incorrecto en el fallback hardcodeado de la guía `462491` (`"12.242,000"` → `"3.282,00"`, con evidencia visual directa). **Los otros 6 fallbacks hardcodeados históricos (462793, 462833, 461878, 462544, 462871, 462395) no se tocaron** -- no hay imagen real disponible en este entorno para verificarlos individualmente con el mismo rigor; se documenta como límite de alcance explícito, no como corrección omitida por descuido.
- **`atlas_core/procesamiento_masivo.py`:**
  - `_normalizar_peso_kg()`: tolera que el OCR confunda "." y "," como separador de miles (caso real: "6,971,00" en vez de "6.971,00") -- separa por grupos, descarta el último grupo si son puros ceros de 2-3 dígitos (los decimales, siempre observados en cero). Valida rango operativo plausible `1-60000` kg (generoso a propósito) -- descarta automáticamente el caso real de dígito insertado por OCR ("127.983" kg, imposible para un camión).
  - `_calcular_permanencia_minutos()`: `salida - entrada` en minutos; si `salida < entrada`, **nunca asume +24h automáticamente** -- devuelve `"No determinada"` (motivo trazable en el propio valor, sin degradar `indicador_revision`).
  - `COLUMNAS` gana 4 columnas al final: `peso_kg`, `hora_entrada_aza`, `hora_salida_aza`, `permanencia_minutos`. `procesar_archivo()` las incluye en su dict de salida -- **ausencia de estos datos nunca participa en `requiere_revision`** (decisión explícita de Fase I: no degradar documentos que antes de este bloque quedaban OK).
- **`atlas_core/gestor_viajes.py`** (Fase H, política multi-guía con evidencia real):
  - `DocumentoViaje` gana `peso_kg`, `hora_entrada_aza`, `hora_salida_aza`, `permanencia_minutos` (por documento, preservados en `evidencia` como el resto de campos).
  - `Viaje.peso_total_viaje_kg`: suma de `peso_kg` de todos los documentos, **solo si todos aportan un valor numérico válido** -- evidencia real (transporte `0000297304`, 3 guías): cada documento trae el peso parcial de su propia línea de material (códigos distintos: `6.971`, `3.100`, `4.256` kg) -- sumar no duplica.
  - `Viaje.hora_entrada_aza`/`hora_salida_aza`: consolidadas solo si todas las horas válidas presentes coinciden (`_valores_unicos` ya existente, reutilizado). Dos motivos nuevos en `MotivoRevision`: `CONFLICTO_HORA_ENTRADA`, `CONFLICTO_HORA_SALIDA` -- si difieren, nunca se elige una arbitrariamente.
  - `Viaje.permanencia_minutos`: derivada de las horas ya consolidadas, nunca promedia permanencias de documentos individuales.
- **`atlas_core/reporte_viajes.py`:** `COLUMNAS_VIAJES` gana `peso_total_viaje_kg`, `hora_entrada_aza`, `hora_salida_aza`, `permanencia_minutos` al final; `_fila_viaje()` los propaga directo desde `Viaje.a_dict()` (sin callback opcional -- a diferencia de las columnas de ruta, estos campos no dependen de un servicio externo). `COLUMNAS_OFICIALES` (= `procesamiento_masivo.COLUMNAS`) ahora exige estas 4 columnas como obligatorias en el CSV de entrada -- un CSV generado con el pipeline anterior a este bloque debe reprocesarse, no puede alimentar `generar_reporte_viajes()` directamente (mismo contrato de esquema estricto que ya regía para cualquier otra columna oficial faltante).

### Validación real multi-guía (Fase L)

- **Transporte `0000279246`** (guías `384674`, `384675`): pesos parciales `7.756` + `7.945` = **`15.701` kg**; horas coincidentes `10:30`/`12:48` → permanencia **138 min**.
- **Transporte `0000297304`** (guías `410265`, `410266`, `410267`): pesos parciales `6.971` + `3.100` + `4.256` = **`14.327` kg**; horas coincidentes `10:08`/`12:27` → permanencia **139 min**.
- Ambos ejecutados con el pipeline real completo (`procesar_archivo` + `agrupar_viajes`), sin inyectar nada.

### Validación

- Tests nuevos: **26** (`tests/test_extractor_peso_horas_o1.py` -- 14; `tests/test_gestor_viajes.py` -- 7 nuevos + 2 casos añadidos al parametrize existente; `tests/test_reporte_viajes.py` -- 3; `tests/test_procesamiento_masivo.py` -- 1; ajuste de 1 test existente con el set de columnas ampliado, y corrección de 1 valor de test que afirmaba el bug de PESO BRUTO como comportamiento esperado).
- Suite completa: **665 → 691 passed**, 0 failed, 0 regresiones.

### Archivos modificados

- `atlas_core/extractor.py`, `atlas_core/procesamiento_masivo.py`, `atlas_core/gestor_viajes.py`, `atlas_core/reporte_viajes.py`.
- Tests: `tests/test_extractor_peso_horas_o1.py` (nuevo), `tests/test_extraer_datos.py`, `tests/test_procesamiento_masivo.py`, `tests/test_gestor_viajes.py`, `tests/test_reporte_viajes.py`.
- Sin cambios: Desktop, ORS, Onelogis, `atlas_core/rutas/` (E1/D2/D3 intactos).

---

## 2026-08-11 — Cierre: ENTREGAS E1, DESPACHAR A como fuente autoritativa de ruta

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `8b59951a9662c88747fa2e09504acbb09a740188`

### Decisión de arquitectura/producto (registro formal)

Definición operacional entregada por Javier, **prevalece sobre inferencias anteriores de D2/D3/D3.1**:

1. `SEÑOR(ES)` = comprador. No implica que los materiales se entreguen en sus instalaciones.
2. `OBRA DESTINO` = obra/proyecto/receptor al que están destinados los materiales. Puede tener un nombre completamente distinto de `SEÑOR(ES)` -- nunca exigir coincidencia.
3. **`DESPACHAR A` = dirección física real de entrega. Es la fuente PRINCIPAL y AUTORITATIVA del destino geográfico de la ruta.** La ruta debe ser `PLANTA ORIGEN → DESPACHAR A`, nunca `PLANTA ORIGEN → dirección del cliente/sitio registrado` cuando `DESPACHAR A` esté disponible.
4. `COMUNA` (campo del formulario): no asumir que corresponde universalmente a la comuna de entrega -- auditar antes de usar (ver más abajo).
5. `COD DESTINATARIO`/`DIRECCION`/otros campos estructurados: siguen siendo evidencia válida de identidad/relación comercial (siguen sirviendo a D2/D3), pero **nunca reemplazan `DESPACHAR A` como punto final de una ruta**.
6. Aprendizaje futuro permitido: una combinación recurrente `cliente + obra_destino + despachar_a` puede aprenderse y reutilizarse -- pero la **primera** confirmación de una entrega debe venir siempre de evidencia real de `DESPACHAR A`, nunca de la dirección del comprador.

### Fase A/B del bloque -- auditoría de COMUNA (requisito explícito antes de implementar cualquier regla de comuna)

- Se completó la lectura OCR real de las 4 guías del set de 14 que aún faltaban por consolidar en un solo lugar comparativo (ya auditadas individualmente en D3/D3.1): confirmado con las 14, 11 con lectura usable de `COMUNA` + `DESPACHAR A`.
- **Resultado:** `COMUNA` coincide con la comuna real de entrega en ~8/11 lecturas (incluyendo 2 coincidencias "casuales" donde la calle exacta de `DESPACHAR A` difiere de `DIRECCION` pero la comuna sí coincide) -- pero en los 3 casos de entrega interregional (`464170`→Mejillones/Antofagasta, `464264`/`464265`→Coronel/Biobío, `464367`→aparente Ñuble), `COMUNA` siguió mostrando la comuna RM del sitio registrado, **no** la real. Conclusión operacional: `COMUNA` es *coincidentemente* confiable solo para entregas intra-comuna/región del sitio registrado, y activamente engañosa para las interregionales -- que son precisamente las que más importan corregir (mayor error de distancia). **Decisión: nunca reutilizar `COMUNA` para geocodificar `DESPACHAR A`; geocodificar el texto crudo de `DESPACHAR A` directamente**, dejando que el proveedor de geocodificación determine la localidad con contexto territorial real.

### Diseño e implementación

- **Nuevo módulo `atlas_core/rutas/destino_entrega.py`** (no reemplaza `destino_estructurado.py` de D2 -- lo complementa; identidad comercial y destino de ruta son preguntas distintas, ver D3.1):
  - `resolver_destino_entrega(despachar_a_crudo, proveedor_geocodificacion, *, contexto_territorial="Chile")`: geocodifica `DESPACHAR A` vía `ProveedorRutas.geocodificar()` (interfaz ya existente desde RUTAS-EVAL R1, reutilizada sin cambios). Preserva siempre el texto crudo original.
  - **Refinamiento de ambigüedad con evidencia real:** el primer intento (cualquier `RESULTADO_AMBIGUO` -> `REVISAR`) resultó en falsos positivos reales -- "AV. ALMTE. LATORRE 843, MEJILLONES" devolvió 5 candidatos, todos confianza 1.0, todos dentro de ~350 m entre sí (Pelias no calzó el número exacto de casa, devolvió vecinos de la misma cuadra). Se agregó `_candidatos_son_el_mismo_lugar()` (distancia Haversine, reutiliza `geocerca.distancia_km_haversine` ya existente, margen `MARGEN_MISMO_LUGAR_KM=1.0`): si TODOS los candidatos caen dentro del margen del primero, se usa el de mayor confianza (`_mejor_candidato`, nunca el más cercano a AZA); si no, sigue siendo `REVISAR` (`MULTIPLES_UBICACIONES_DISPERSAS`). Caso real confirmado de ambigüedad genuina: "SANTA ISABEL 585" devolvió resultados en Perú, Argentina, Puerto Rico y **dos puntos distintos** dentro de Lampa, RM -- correctamente `REVISAR`.
  - Confianza mínima (`UMBRAL_CONFIANZA_MINIMA=0.5`) para aceptar un único candidato no ambiguo -- por debajo, también `REVISAR`.
  - `calcular_ruta_entrega_para_viaje(...)`: orquesta `resolver_planta_origen` (reutilizado sin cambios de `enriquecimiento_viaje.py`, import perezoso para evitar ciclo) -> `resolver_destino_entrega` -> `proveedor_rutas.calcular_ruta()` directo (**sin la capa de caché de `ServicioRutas`/`RepositorioRutas`** -- esa caché indexa por `destino_id` de catálogo, y una entrega geocodificada en vivo no es todavía una entidad de catálogo; ver Fase E de D3.1, propuesta de modelo `destino_entrega` no implementada). Nunca lanza; un fallo en cualquier paso deja `estado_ruta`/`motivo_ruta` explicativos.
  - Función completamente nueva, aditiva -- **`calcular_ruta_para_viaje` (D2, catálogo) no se modificó**; ambos caminos coexisten para propósitos distintos (identidad/reporte vs. ruta real).

### Validación

- Tests nuevos: **10** en `tests/test_rutas_destino_entrega.py` -- sin dato, candidato único con/sin confianza suficiente, ambigüedad real (nunca elige el más cercano a AZA), candidatos dispersos-pero-cercanos resueltos como el mismo lugar (caso real Mejillones), fallo de geocodificación preserva el texto crudo, ruta real end-to-end, origen no determinado nunca geocodifica, entrega ambigua nunca calcula ruta.
- Suite completa: **655 → 665 passed**, 0 failed, 0 regresiones.
- **Validación real (ORS real, catálogo de plantas real, sin inyectar nada):**
  - **464170 (caso ejemplo oficial):** AZA RENCA → "AV. ALMTE. LATORRE 843, MEJILLONES" = **1433.2 km / 1441.08 min (~24 h)**, confianza 1.0. Confirma que la ruta correcta es radicalmente distinta de lo que el catálogo (Galvarino 8501, Quilicura) habría dado.
  - **464424 (Torres Ocaranza):** 16.73 km / 24.6 min -- converge con la cifra ya conocida por el camino de catálogo (16.68 km/24.53 min, D2/D3), validación cruzada de que ambos caminos son consistentes cuando `DESPACHAR A` y el sitio registrado coinciden.
  - **464511 (Armacero):** `REQUIERE_REVISION`/`MULTIPLES_UBICACIONES_DISPERSAS` -- "Santa Isabel" es un nombre de calle común, Pelias devolvió resultados internacionales; abstención correcta, limitación conocida (ver pendientes).

### Archivos modificados

- Nuevo: `atlas_core/rutas/destino_entrega.py`, `tests/test_rutas_destino_entrega.py`.
- Modificado: `atlas_core/rutas/__init__.py` (exports nuevos).
- Sin cambios: `atlas_core/rutas/openrouteservice.py`, `atlas_core/rutas/servicio.py`, `atlas_core/rutas/enriquecimiento_viaje.py`, `atlas_core/rutas/destino_estructurado.py`, extractores, Desktop, `destinos_maestros.json`.

---

## 2026-08-11 — Cierre: DESTINOS D3.1, auditoría semántica DIRECCION vs DESPACHAR A + revert controlado

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `7c070a81ff4884556625516aae5785744954c93f`

### Auditoría (solo lectura)

- Se completó la lectura OCR real de las 4 guías del set de 14 que aún no se habían auditado (`464265`, `464367`, `464395`, `464488`), llegando a las 14 con imagen disponible en el repo, todas con `DIRECCION`/`COMUNA`/`COD DESTINATARIO`/`DESPACHAR A` extraídos.
- **Hallazgo central:** de las 14, 9 tuvieron lectura limpia de `DIRECCION` y `DESPACHAR A` simultáneamente. **5 concordantes** (`464424`, `464479`, `464494`, `464495`, `464511`), **4 divergentes** (`464170` EBEMA→Mejillones vs Quilicura; `464395` Ingemeta→Carmen Mena 529 vs Santa Rosa 5587, mismo cliente, dos sitios registrados distintos observados en dos guías; `464264`/`464265` Sodimac→Coronel vs Renca, **interregional**; `464488` Easy Retail→misma comuna, calle distinta). Conclusión: `DIRECCION`/`COMUNA`/`COD DESTINATARIO` identifican el sitio/obra **registrado** contra el que se emite la guía, no necesariamente el punto físico de entrega — that campo es `DESPACHAR A`. Consistente con, y más granular que, el hallazgo ya usado por D2 (`evaluar_concordancia_despacho`).
- Auditoría de las 4 confirmaciones de D3 cruzando específicamente evidencia de `DESPACHAR A` (no solo repetición de `DIRECCION`+`COMUNA` como hizo D3): Armacero (2/2 guías con `DESPACHAR A` concordante: `464511`, `464489`) y Aceros Cox (2/2: `464494`, `464495`) quedan con evidencia de entrega real doble e independiente. Ebema (1 sola observación de `DESPACHAR A` disponible, y **diverge**) y Salomón Sack (0 observaciones de `DESPACHAR A` — el ground truth usado en D3 no releva ese campo) quedan sin evidencia positiva de entrega.

### Revert ejecutado (tras confirmación explícita del usuario, tool `AskUserQuestion`)

- Respaldo previo: `C:\Users\Jjjc0508\Desktop\Atlas\backups_catalogos\20260811_pre_revert_d31\destinos_maestros.json`, verificado por checksum contra el catálogo real antes de tocar nada.
- `CatalogoDestinos.editar(..., modificacion_manual=True, estado_calidad=PENDIENTE, fuente=..., observacion=...)` sobre `32d67fec-...` (EBEMA/Galvarino 8501) y `c25be79a-...` (Salomón Sack/Camino Los Pinos 3396) — únicos campos modificados: `estado_calidad`, `fuente` (marca `REVERSION_DESTINOS_D3.1_2026-08-11+AUDITORIA_SEMANTICA_SIN_EVIDENCIA_DESPACHO`) y `observacion` (motivo apendiado, sin borrar el texto de confirmación de D3 ni el de la migración original). Dirección/comuna/región/código/coordenadas verificados idénticos antes/después.
- Catálogo tras el revert: recargado sin `CatalogoDestinosCorruptoError`, 47 destinos, **6 CONFIRMADO** (los 4 originales + Armacero + Aceros Cox) / **41 PENDIENTE**.
- Suite: **655 passed**, sin cambios — este bloque no tocó ningún archivo de código de producción ni de tests (solo el catálogo real, fuera del repo, y las bitácoras).

### Archivos modificados

- Dato: `%LOCALAPPDATA%\Atlas\datos\catalogos_privados\destinos_maestros.json` (2 destinos `CONFIRMADO`→`PENDIENTE`, con respaldo verificado).
- Repo: solo `docs/BITACORA_EJECUTIVA.md`, `docs/BITACORA_TECNICA_CRONOLOGICA.md`, `docs/HANDOFF_ATLAS.md`. 0 código, 0 tests.
- Artefactos nuevos fuera del repo: `rutas_eval/d31_evidencia_real_faltante.json` (OCR real de las 4 guías completadas).

---

## 2026-08-11 — Cierre: DESTINOS D3, confirmación humana asistida de destinos frecuentes

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `54f484f043f203926ce5ad4a56c8babda1e90f89`

### Problema real confirmado

- `destinos_maestros.json` real: 47 destinos, 43 `PENDIENTE`, 4 `CONFIRMADO`. El gate de calidad de `ServicioRutas` (ya existente, sin tocar) bloquea el cálculo de ORS para cualquier destino `PENDIENTE` — correcto por diseño, pero deja casi todas las guías reales sin ruta.

### Fuentes de evidencia nuevas

- **`datos_privados/ground_truth/validacion_atlas_30_guias_v1.xlsx`** (hoja "Datos guías"): 30 guías reales con `CLIENTE`, `RUT CLIENTE`, `CÓDIGO DESTINATARIO`, `DIRECCIÓN DESTINO`, `COMUNA`, `CIUDAD` transcritos y validados a mano — no usado en bloques anteriores. Requirió instalar `openpyxl` (no estaba en el entorno).
- Hallazgo relevante para la jerarquía de D2: dos filas (guías `390486` y `428701`), mismo cliente (TORRES OCARANZA LTDA) y mismo código destinatario (`0001004443`), muestran direcciones de entrega distintas ("VISTA CLARA 391" vs "VISTA CLARA 2351") — confirma con datos humanos independientes la razón por la que D2 dejó de tratar el código como llave autónoma.
- Cruce de campos detectó una inconsistencia de transcripción: para EBEMA SA, el ground truth registra "CÓDIGO DESTINATARIO" = `0001001424`, pero ese valor coincide con el campo *distinto* "Código Cliente" visible en el encabezado de la guía real 464170 — el código real de `COD DESTINATARIO` en esa guía es `0002013046`. Documentado, no usado como evidencia de código para EBEMA en este bloque.

### Ranking (Fase A)

- Fuente primaria: campo `observacion` de cada destino migrado (`"N viajes en el periodo 01/04/2026-30/06/2026"`, dato real del Excel de origen). Cruzado automáticamente (normalización con `unicodedata`, comparación cliente+dirección+comuna) contra el ground truth y contra la evidencia OCR real ya recolectada en D2 más 2 guías nuevas de este bloque (464494, 464495 — ACEROS COX COMERCIAL SA).
- Top por frecuencia: ARMACERO MATCO SA/Santa Isabel 585 (94), EBEMA SA/Galvarino 8501 (34), AGF ACEROS DE CHILE SPA/Panamericana Norte 22650 (23), ACEROS COX COMERCIAL SA/Camino Lo Ruiz 2901 (20), AMERICAN SCREW CHILE SPA/Camino a Melipila 10800 (19, sin coordenadas).
- Artefactos completos: `C:\Users\Jjjc0508\Desktop\Atlas\destinos_revision\ranking_destinos_pendientes.json` (47 destinos con evidencia cruzada) y `fichas_lote_10.md` (10 fichas completas con recomendación individual).

### Fase B/C — validación geográfica y de región

- Confirmados los 4 registros "SAN MIGUEL" con coordenada errónea ya conocida (`lat=-30.81, lon=-70.60`, zona de Ovalle/Coquimbo, ~370 km de RM) -- ninguno estaba en el lote de 10, se documentan igual por instrucción explícita.
- Detectado (no corregido, fuera de este cliente/lote): varios destinos de la zona industrial de Renca (ACEROS COX y SODIMAC en "Camino Lo Ruiz"; ACMA SA en "Maruri", dos números distintos) comparten coordenada exacta entre sí — geocodificación a nivel de calle, no de número, un límite de precisión conocido del proceso de migración, no un error de identidad.
- Los 47 destinos actuales son región RM (uno con el texto "REGIÓN METROPOLITANA" en vez de "RM" — inconsistencia de formato en un registro ya `CONFIRMADO` de un bloque anterior, no tocado aquí). El ground truth reveló viajes reales interregionales (Temuco, Coronel) sin destino correspondiente todavía en el catálogo -- no se fabricó ninguno, documentado como brecha real para un bloque futuro.

### Fase D/E/F/G — evidencia, fichas y confirmación

- Criterio aplicado (más estricto que el mínimo pedido por el enunciado): **confirmar solo con ≥2 documentos independientes** (nunca el agregado de migración por sí solo) concordantes en cliente+dirección+comuna.
- Respaldo previo verificado por checksum: `C:\Users\Jjjc0508\Desktop\Atlas\backups_catalogos\20260811_pre_confirmacion_d3\destinos_maestros.json`.
- **4 destinos confirmados** vía `CatalogoDestinos.editar(..., modificacion_manual=True, estado_calidad=CONFIRMADO, fuente=..., observacion=...)` — nunca edición manual del JSON. Solo cambian `estado_calidad`, `fuente` (marca `CONFIRMACION_DESTINOS_D3_2026-08-11+EVIDENCIA_MULTIPLE_INDEPENDIENTE`, mismo patrón ya usado por Torres Ocaranza en un bloque anterior) y `observacion` (evidencia apendiada, preservando el texto original de migración) — dirección/comuna/región/código/coordenadas verificados idénticos antes/después, campo por campo, en el propio script de confirmación.
- 1 candidato (AMERICAN SCREW CHILE SPA) separado explícitamente como `CORREGIR DATOS`: 3 grafías distintas de la misma dirección real entre catálogo/OCR real/ground truth (posible error de tipeo heredado de la migración) + coordenadas ausentes — no confirmado ni corregido en este bloque, para no mezclar corrección de datos con confirmación en la misma operación.

### Fase H — rutas reales

- **AZA RENCA → ARMACERO MATCO SA/Santa Isabel 585** (guía real 464511): `RUTA_CALCULADA`, 12.969 km / 19.71 min.
- **AZA RENCA → ACEROS COX COMERCIAL SA/Camino Lo Ruiz 2901** (guías reales 464494 y 464495): `RUTA_CALCULADA`, 0.086 km / 0.13 min (segunda consulta → `RESULTADO_DESDE_CACHE`) — distancia real muy corta porque ambos domicilios están en el mismo tramo de la zona industrial de Renca, no es un error.
- **AZA RENCA → EBEMA SA/Galvarino 8501** (guía real 464170, destino ya confirmado): sigue en `REQUIERE_REVISION`/`DESPACHO_DIVERGENTE_DEL_DESTINO_CANONICO` — el gate de concordancia de D2 protege el viaje individual independientemente del estado de confirmación del destino, exactamente como se diseñó.
- No hubo ningún destino interregional confirmable en el lote (0 candidatos regionales `PENDIENTE` existían en el catálogo) — el requisito condicional de Fase H ("si algún destino regional queda confirmado") no aplicó; no se fabricó ninguno.

### Validación

- Tests nuevos: **12** en `tests/test_destinos_d3_confirmacion.py` -- destino RM válido por comuna+región, mismo nombre de calle en cliente/comuna/región distinta no colisiona (abstención, nunca elección arbitraria), coordenadas fuera de rango rechazadas, código destinatario concordante resuelve, `DESPACHAR A` divergente bloquea la ruta aun con destino confirmado, destino `PENDIENTE` no enruta, destino `CONFIRMADO`+concordante calcula ruta real, confirmar preserva dirección/comuna/región/código/coordenadas (verificado campo por campo), el catálogo sigue siendo válido (recarga sin `CatalogoDestinosCorruptoError`) tras confirmar, no regresión de la resolución global sin cliente (D1/D2) y de extracción/concordancia (D2).
- Suite completa: **643 → 655 passed**, 0 failed, 0 regresiones.

### Archivos modificados

- Nuevo: `tests/test_destinos_d3_confirmacion.py`.
- Sin cambios de código de producción -- D3 reutiliza `atlas_core/rutas/destino_estructurado.py` y `enriquecimiento_viaje.py` de D2 tal cual.
- Dato: `%LOCALAPPDATA%\Atlas\datos\catalogos_privados\destinos_maestros.json` (4 destinos `PENDIENTE`→`CONFIRMADO`, con respaldo previo verificado).
- Artefactos nuevos fuera del repo: `C:\Users\Jjjc0508\Desktop\Atlas\destinos_revision\` (ranking + fichas), `C:\Users\Jjjc0508\Desktop\Atlas\backups_catalogos\20260811_pre_confirmacion_d3\`.

---

## 2026-08-11 — Cierre: DESTINOS D2, resolución canónica de destino estructurada

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `3f28e4cc6876253dc8a528dbd9ef8651e5daa7e7`

### Problema real confirmado

- La verificación final de rutas (bloque anterior) mostró que `resolver_destino_canonico` (emparejamiento por nombre/alias contra `destinos_maestros.json`) fallaba con `DESTINO_NO_HOMOLOGADO` para prácticamente cualquier guía real, porque `obra_destino` (texto OCR, casi siempre un nombre comercial o de sitio de obra) casi nunca coincide textualmente con `nombre_destino` en el catálogo (que está poblado con direcciones, migradas desde un Excel de estudio de distancias, no desde el texto de las guías).
- Auditoría de 7 guías reales (`464170`, `464511`, `464489`, `464491`, `464493`, `464264`, `464424`) mostró que el propio documento AZA trae, además de `OBRA DESTINO`, los campos `COD DESTINATARIO`, `DIRECCION` y `COMUNA` -- y que `DIRECCION`+`COMUNA` coinciden **exactamente** (tras normalizar) con `nombre_destino`+`comuna` del catálogo en los casos con OCR limpio. El campo `codigo_destino` del catálogo (vacío en 46/47 registros migrados) coincide exactamente con `COD DESTINATARIO` cuando existe (validado con Torres Ocaranza, guía 464424: mismo código `0001004443` que la observación ya registrada en el catálogo, documentada desde otra guía histórica, 464106).
- Corrección de rumbo con evidencia externa (auditoría independiente de 31 guías, Codex): `COD DESTINATARIO` no es una llave autónoma segura -- el mismo código/cliente puede repetirse con `DESPACHAR A` (punto de entrega real de ESE viaje) distinto, incluso en otra región (caso documentado: `0001004443`/Torres Ocaranza con `DESPACHAR A` "VISTA CLARA 391" en una guía y "VISTA CLARA 2351" en otra). Confirmado con evidencia propia adicional: guía 464170 (EBEMA SA) homologa correctamente por dirección a GALVARINO 8501 (Quilicura, RM), pero su `DESPACHAR A` real es "AV. ALMTE. LATORRE 843, MEJILLONES" (Región de Antofagasta) -- domicilio registrado y punto de entrega real de este viaje son lugares físicamente distintos.

### Diseño

- **Nuevo módulo `atlas_core/rutas/destino_estructurado.py`** (no reemplaza nada existente):
  - `extraer_identificadores_destino(textos)`: lee `COD DESTINATARIO`, `DIRECCION`, `COMUNA`, `DESPACHAR A` del texto OCR de página completa ya disponible (mismo texto usado por `resolver_origen_documental`), con regex de límite genérico (un conjunto de etiquetas conocidas marca dónde termina cada valor, sin asumir un orden fijo entre etiquetas -- el orden varía guía a guía). Conservador: si el layout viene degradado por el OCR (etiquetas fuera de orden real, no solo reordenadas), simplemente no captura el campo -- nunca arriesga un valor.
  - `resolver_destino_canonico_estructurado(...)`: jerarquía **A.** cliente (RUT si se informa, cruzado contra el RUT ya registrado del cliente -- una contradicción de RUT no acota por cliente) + código destinatario exacto y único → **B.** dirección (+comuna si se extrajo) exacta normalizada y única → **C.** alias/nombre acotado al cliente (`CatalogoDestinos.buscar(..., cliente_id=...)`) → **D.** comportamiento histórico global sin cambios (`resolver_destino_canonico`, delegado tal cual). Cada nivel exige coincidencia única; ante 0 o >1 candidatos, cae al siguiente o se abstiene -- nunca fabrica ni "desempata".
  - `evaluar_concordancia_despacho(destino, identificadores)`: contrasta el destino ya resuelto (identidad/homologación) contra `DESPACHAR A` (punto de entrega real de este viaje) por solape de tokens normalizados (dirección o comuna). Sin `DESPACHAR A` en el documento, se considera concordante (compatible con el comportamiento previo a este campo).
  - **Refactor sin cambio de comportamiento** en `enriquecimiento_viaje.py`: se extrajo `validar_destino_resoluble` (vigencia/coordenadas/rango RM) de `resolver_destino_canonico`, reutilizado ahora por ambos caminos de resolución -- ningún camino nuevo puede saltarse esos controles.
  - `calcular_ruta_para_viaje` gana 3 parámetros opcionales (`cliente_texto`, `catalogo_clientes`, `rut_cliente_texto`, todos `None` por defecto): sin ellos, comportamiento **100% idéntico** a antes de este bloque (nivel D global). Con ellos, resuelve por identidad estructurada y, si el destino resuelve pero `DESPACHAR A` diverge materialmente, devuelve `REQUIERE_REVISION`/`DESPACHO_DIVERGENTE_DEL_DESTINO_CANONICO` **antes** de intentar resolver origen/ORS -- nunca calcula una ruta sobre una identidad de destino sin confirmar contra el punto de entrega real.
  - Import circular evitado con imports perezosos (dentro de función) en ambas direcciones: `destino_estructurado` usa `enriquecimiento_viaje` solo dentro de `resolver_destino_canonico_estructurado`; `enriquecimiento_viaje` usa `destino_estructurado` solo dentro de `calcular_ruta_para_viaje`.

### Validación

- Tests nuevos: **14** en `tests/test_rutas_destino_estructurado.py` -- código exacto, código desconocido cae a dirección, obra_destino sin coincidencia dentro del cliente abstiene, dirección+comuna exacta, alias acotado a cliente, ambigüedad real (entre clientes distintos, la única alcanzable -- `CatalogoDestinos` ya impide duplicados dentro de un mismo cliente en la escritura), cliente no resuelto cae al nivel D histórico, RUT contradictorio no acota por cliente, ruta real calculada con destino confirmado y despacho concordante, destino PENDIENTE bloquea la ruta (gate existente, sin tocar), despacho divergente bloquea la ruta aunque el destino resuelva, extracción robusta a 2 órdenes de etiquetas reales distintos, extracción de `DESPACHAR A`, concordancia por defecto sin evidencia de despacho.
- Suite completa: **629 → 643 passed**, 0 failed, 0 regresiones.
- **Validación real (catálogo activo real, 7 guías reales, ORS real):**
  - 464170 (EBEMA SA): identidad resuelve (`RESUELTO_DIRECCION_COMUNA` → GALVARINO 8501), pero `DESPACHO_DIVERGENTE_DEL_DESTINO_CANONICO` (Mejillones vs Quilicura) -- correctamente **no** calcula ruta.
  - 464511 (ARMACERO MATCO SA): identidad resuelve (`RESUELTO_DIRECCION_COMUNA` → SANTA ISABEL 585), concordancia con `DESPACHAR A` **sí**, planta AZA RENCA resuelta por documento -- bloqueado por `DESTINO_NO_CONFIRMADO` (destino aún `PENDIENTE`, gate de calidad existente funcionando como se diseñó).
  - 464424 (TORRES OCARANZA LTDA, destino ya `CONFIRMADO`): identidad resuelve por código destinatario, concordancia con `DESPACHAR A` **sí**, planta AZA RENCA por documento → **ruta real ORS: 16.683 km / 24.53 min**. Cliente de esta guía en particular no lo extrae el pipeline lineal ni el fallback geométrico (falla preexistente y ajena a este bloque, confirmada con `extraer_datos()` puro sin catálogos) -- se usó el texto literal `SEÑOR(ES)` del propio documento como entrada de cliente, documentado explícitamente como diagnóstico, no como sustitución de destino.
  - Otras 4 guías (464489, 464491, 464493, 464264): abstención correcta (`DESTINO_NO_HOMOLOGADO`) por OCR degradado o catálogo aún sin ese destino -- 0 asignaciones incorrectas.

### Archivos modificados

- Nuevo: `atlas_core/rutas/destino_estructurado.py`, `tests/test_rutas_destino_estructurado.py`.
- Modificados: `atlas_core/rutas/enriquecimiento_viaje.py` (refactor `validar_destino_resoluble` + parámetros opcionales en `calcular_ruta_para_viaje`), `atlas_core/rutas/__init__.py` (exports nuevos).
- Sin cambios: `atlas_core/rutas/openrouteservice.py`, `atlas_core/rutas/servicio.py` (ORS y el gate de confirmación no se tocaron), extractores (`atlas_core/extractor.py`), Desktop.

---

## 2026-08-11 — Cierre: migración de endpoint ORS + validación real con credencial

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `ccc777229cbd072b1f89e5d60efbd5620859731a`

### Problema real confirmado

- El adaptador `atlas_core/rutas/openrouteservice.py` apuntaba a `https://api.openrouteservice.org`, host que HeiGIT (operador de OpenRouteService) deprecó el 2026-04-28 en favor de `api.heigit.org`, con apagado definitivo confirmado para el **2026-08-24**. Verificado contra el hilo oficial de anuncio (`ask.openrouteservice.org`) y confirmado en vivo: ambos hosts responden `401 Unauthorized` (no `404`) sin credencial, es decir la ruta nueva ya existe y responde.

### Diseño

- Migración centralizada de 2 constantes de clase en `OpenRouteService`:
  - `URL_GEOCODIFICACION`: `https://api.openrouteservice.org/geocode/search` → `https://api.heigit.org/pelias/v1/search` (la geocodificación migró a la estructura Pelias, no es un simple cambio de dominio).
  - `URL_DIRECCIONES`: `https://api.openrouteservice.org/v2/directions/{perfil}` → `https://api.heigit.org/openrouteservice/v2/directions/{perfil}`.
- Sin cambios de autenticación (misma API key sirve para ambos hosts, confirmado en el anuncio oficial) ni de contrato (`ProveedorRutas`, `ResultadoRuta`, `EstadoRuta` sin tocar) — cambio estrictamente de host/ruta.
- **Configuración de credencial, sin exposición:** `OPENROUTESERVICE_API_KEY` se configuró como variable de entorno de **usuario** de Windows, escrita por Javier directamente con `[Environment]::SetEnvironmentVariable(...,"User")` en su propia terminal — nunca visible para Claude. Para las pruebas reales, la clave se puenteó al proceso hijo dentro de una sola invocación (`$env:OPENROUTESERVICE_API_KEY = [Environment]::GetEnvironmentVariable(...,"User")` inmediatamente antes de invocar Python), sin imprimirla ni guardarla en ningún archivo — necesario porque una variable de usuario recién creada no se propaga a procesos ya en ejecución, solo la lectura directa del registro la ve.

### Validación

- Tests nuevos: 2 en `tests/test_rutas_openrouteservice.py` (`test_direcciones_usa_endpoint_heigit_vigente`, `test_geocodificacion_usa_endpoint_heigit_pelias_vigente`) — fijan el host/ruta vigente con el mismo patrón de transporte simulado que ya usaba el resto del archivo (sin red real), para que una regresión al host deprecado la detecte la suite antes de producción.
- Suite completa: **601 → 603 passed**, 0 failed.
- **Prueba real de credencial** (`driving-hgv`, AZA RENCA → EBEMA SA): `EstadoRuta.RUTA_CALCULADA` (no `SIN_CREDENCIAL`), tiempo de respuesta 1.02s.
- **3 rutas reales**, coordenadas ya existentes en catálogo (`plantas.json`/`destinos_maestros.json`, sin geocodificar de nuevo — AZA COLINA reutiliza la coordenada ya geocodificada para la misma dirección física bajo "ACEROS AZA SA", igual que en RUTAS-EVAL R1):
  | origen | destino | km | min | estado | t (s) |
  |---|---|---|---|---|---|
  | AZA_RENCA | EBEMA SA (Galvarino 8501) | 7.43 | 12.06 | RUTA_CALCULADA | 0.80 |
  | AZA_COLINA | Torres Ocaranza Ltda | 49.70 | 59.87 | RUTA_CALCULADA | 0.80 |
  | AZA_RENCA | DSI Underground Chile SpA | 33.17 | 40.41 | RUTA_CALCULADA | 0.86 |
- **Caché verificado end-to-end** (no solo unitario): `ServicioRutas.confirmar_y_calcular` con `Planta`/`Destino` reales (`AZA RENCA` → `TORRES OCARANZA LTDA`, catálogo real) contra un `RepositorioRutas` apuntando a un archivo de prueba en `Desktop\Atlas\rutas_eval\cache_prueba_rutas.json` (fuera del repo, no se tocó ningún catálogo de producción). 1ª llamada: `RUTA_CALCULADA`, 1 llamada real a ORS (contada con un wrapper que subclasea `OpenRouteService.calcular_ruta`, sin modificar el adaptador). 2ª llamada idéntica: `RESULTADO_DESDE_CACHE`, **0 llamadas nuevas a ORS**, mismo `distancia_km`/`duracion_estimada_min`. Clave lógica confirmada: `planta_id + destino_id + perfil + proveedor + version` (`RepositorioRutas.buscar_vigente`).
- **0 secretos en git**: verificado con `grep` sobre los artefactos guardados (`rutas_eval/*.json`) antes de commitear — sin `Authorization`/`Bearer`/valor de clave en ningún archivo persistido, dentro ni fuera del repo.
- Archivos modificados: `atlas_core/rutas/openrouteservice.py`, `tests/test_rutas_openrouteservice.py`. Sin cambios en `atlas_core/rutas/{modelos,proveedor,servicio,repositorio}.py`, catálogos, Desktop, ni ningún archivo `.env`.

### Continuidad

- **Siguiente bloque:** conectar km/tiempos al flujo real (Desktop, generación de reportes) usando el módulo `atlas_core/rutas/` ya validado con credencial real. No iniciado — explícitamente fuera de alcance de este bloque ("No tocar Desktop todavía. No integrar km en UI todavía.").

---

## 2026-08-11 — Cierre Bloque D1: separar GIRO de obra_destino

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `66d0edabbfd506795dc675f2149e4875dc6fede2`

### Problema real confirmado

- Guía real `464170`. Con cliente/chofer/RUT ya corregidos por C1, `obra_destino` seguía devolviendo `"VENTA AL POR MAYOR D"` (el valor de GIRO) en vez del destino real `"SUPERMERCADO SEÑOR DE LOS MI"`. Diagnóstico previo (bloque anterior) ya había identificado la causa como "la geometría asocia el valor de GIRO como obra/destino".

### Diseño

- **Causa exacta, localizada en `_extraer_asociaciones_geometricas` (`atlas_core/extractor.py`):**
  1. `nominal()` (filtro de candidatos válidos) tenía `"SENOR"` en su lista de exclusión por subcadena — heredada de antes de C1. El candidato correcto de obra_destino, "SUPERMERCADO SEÑOR DE LOS MI", contiene esa palabra y quedaba excluido como candidato, aunque geométricamente fuera el mejor (score 0.147 vs 0.496 del valor de GIRO, verificado con las cajas reales exactas).
  2. Sin ese candidato, el único bloque que sobraba dentro del umbral de puntaje cerca de la etiqueta "OBRA DESTINO" era el valor de GIRO — en la columna vecina de la misma fila (este proveedor AZA imprime SEÑOR(ES)/R.U.T./GIRO/DIRECCION en la columna izquierda y SOLICITANTE/TELEFONO/OBRA DESTINO/COD DESTINATARIO en la derecha, ambas alineadas por fila) — y no existía ninguna regla que impidiera que GIRO ganara por default al ser la única opción restante.
- **Fix Parte B (extensión del fix C1 al lado del candidato):** se removió `"SENOR"` de la tupla `exclusiones` de `nominal()` y se agregó en su lugar `if _es_etiqueta_senor(texto): return False` — ahora solo se descarta un candidato si el bloque completo *es* la etiqueta SEÑOR(ES)/SEÑORES/SEÑOR(IES)/SEÑORIES, no si la palabra aparece dentro de un nombre real más largo. Mismo criterio ya validado en C1 para el lado de la etiqueta.
- **Fix Parte C (GIRO nunca elegible como obra/destino):** nueva `es_etiqueta_giro(item)` (`item["simple"] == "GIRO"`, exacto). Se probó primero una exclusión por **comparación de distancias** (candidato más cerca de GIRO que de la etiqueta destino real → descartado) — **descartada tras fallar en un test unitario minimal**: con GIRO y OBRA DESTINO como columnas vecinas casi equidistantes de sus valores, la diferencia de distancia puede ser de 1-2 px, insuficiente para garantizar la exclusión de forma robusta. Solución final: `_mejor_candidato(etiqueta)` calcula, con la misma `puntuar()` ya existente, cuál sería el candidato de mejor puntaje para una etiqueta dada; se aplica a cada etiqueta GIRO para obtener el conjunto `valores_giro` (por `id()` de objeto, no por texto) y esos candidatos quedan excluidos, por identidad, de la lista de candidatos válidos para `campo == "obra destino"` — sin importar cuán cerca o lejos estén de la etiqueta de destino real. Garantiza estructuralmente que GIRO nunca puede ganar, sin depender de umbrales de proximidad.
- **Bug colateral encontrado y corregido (Parte D de C1, `_extraer_rut_cliente_geometrico`):** al reconstruir un test con las cajas reales exactas de la guía 464170 (en vez de las coordenadas redondeadas usadas en C1), `_extraer_rut_cliente_geometrico` dejó de encontrar el RUT — su ancla `0 < item["y1"] - etiqueta_cliente["y2"]` exige un hueco **estrictamente positivo** entre las etiquetas SEÑOR(ES) y R.U.T., pero en el documento real esas dos filas quedan con cajas exactamente adyacentes (SEÑOR(ES) termina en y=570, R.U.T. empieza en y=570 — gap 0). Este bug ya existía desde C1: el "caso real obligatorio" reportado entonces (`rut_cliente = 83.585.400-0`) se verificó solo contra un test unitario con coordenadas redondeadas que por casualidad tenían un hueco de 3px, nunca contra las cajas reales completas — y el campo "RUT del cliente" ni siquiera se expone en el dict que devuelve `procesar_archivo` (solo se usa internamente para homologar `cliente` vía RUT contra `empresas.json`), por lo que el error pasó inadvertido porque el nombre OCR de EBEMA SA ya coincidía textualmente con el nombre canónico del catálogo. Corregido: `0 <` → `0 <=` (acepta gap cero, cajas adyacentes). Confirmado con las cajas reales completas: `_extraer_rut_cliente_geometrico` ahora sí devuelve `{"valor": "83.585.400-0"}`.
- **Catálogo (Paso 4, solo inspección):** `%LOCALAPPDATA%\Atlas\datos\catalogos_privados\destinos_maestros.json` (schema `{"version_formato":..., "destinos":[...]}`, 47 registros) contiene un destino con `cliente_id` idéntico al de EBEMA SA en `clientes.json` (`fb859a71-d7b7-453f-9f27-34b24eb59139`): dirección `GALVARINO 8501, QUILICURA, CHILE`, ya geocodificada (`lat=-33.370934, lon=-70.716168`, fuente `GEOCODIFICACION_ORS`, `match_type=fallback`, `confidence=0.8`), 34 viajes observados en el período. El `nombre_destino` canónico ahí es la dirección, no el nombre comercial leído por OCR ("SUPERMERCADO SEÑOR DE LOS MI") — homologar obra_destino contra este catálogo por `cliente_id` requeriría cruzar `clientes.json`→`destinos_maestros.json`, una integración nueva no implementada en D1 (el enriquecimiento existente, `_buscar_destino_en_textos` contra `destinos.json` por código de destinatario, no encuentra coincidencia para el código `0002013046` de esta guía — `destinos.json` solo tiene 6 registros — y correctamente se abstiene sin fabricar nada).
- No se tocó PaddleOCR, ni Desktop, ni `buscar_obra_destino()` (camino lineal, sin cambios — mismo criterio que C1 de no reescribir el extractor histórico de una sola línea).

### Validación

- Tests nuevos: 6 en `tests/test_extraer_datos.py` (GIRO ya no confunde con destino real usando geometría de la guía 464170; GIRO nunca se devuelve como obra_destino aunque sea el único bloque cercano; solo GIRO sin etiqueta de destino no inventa nada; obra con palabra SEÑOR no crea etiqueta falsa de cliente; obra_destino ambiguo se abstiene; no-regresión consolidada de cliente/chofer/RUT-cliente junto a obra_destino usando cajas reales completas) + 1 en `tests/test_catalogos.py` (obra_destino ya extraída se homologa a su nombre canónico vía código de destinatario).
- Suite completa: **594 → 601 passed**, 0 failed. Sin necesidad de tocar ningún test ya existente (a diferencia de C1) — este fix no activa ninguna ruta nueva de lectura de bloques que algún test ya mockeara.
- **Validación real, guía `464170`, PaddleOCR GPU real, catálogo activo real (mismo usado en C1, ya con IVAN ROA):**
  - `obra_destino`: `"VENTA AL POR MAYOR D"` → **`"SUPERMERCADO SEÑOR DE LOS MI"`**.
  - `cliente=EBEMA SA`, `chofer=IVAN ROA`, `rut_chofer=10190440-7`, `numero_guia=464170`, `numero_transporte=0000351177` — sin cambios respecto a C1.
  - `indicador_revision`: `REVISAR` (sin cambio; sigue siendo correcto — el documento continúa necesitando recuperación geométrica de varios campos).
  - Viaje agrupado (`agrupar_viajes`): `REQUIERE_REVISION`, motivo `DOCUMENTO_REQUIERE_REVISION` (sin cambio respecto a C1).
- **Validación adicional corta, 4 guías reales con obra_destino ya conocido antes de este fix** (`464511`→ARMACERO MATCO SA, `464493`→EMPRESA CONST SIGRO, `464479`→AMERICAN SCREW CHILE SPA, `464494`→ACEROS COX COMERCIAL SA), reprocesadas con PaddleOCR GPU real + catálogo activo real: **cliente, obra_destino, chofer e indicador_revision idénticos antes/después en las 4** — 0 regresiones.
- Archivos modificados: `atlas_core/extractor.py`, `tests/test_extraer_datos.py`, `tests/test_catalogos.py`. Sin cambios en `atlas_core/procesamiento_masivo.py`, `atlas_core/gestor_viajes.py`, `atlas_core/catalogos.py`, OCR (`atlas_core/ocr.py`, `atlas_core/ocr_provider.py`, `atlas_core/paddle_runtime.py`) ni Desktop.

### Continuidad

- **Siguiente bloque oficial: RUTAS-EVAL / RUTAS R1** — comparación corta de proveedores de ruteo y recuperación de infraestructura de km/tiempos. Insumo directo ya disponible: el destino ahora se extrae correctamente, y `destinos_maestros.json` ya tiene la dirección canónica geocodificada de EBEMA SA (y de otros clientes) lista para homologar por `cliente_id` — esa homologación específicamente queda para ese bloque, no se implementó aquí. No iniciado.

---

## 2026-08-11 — Cierre PLANTA-P1: resolución real de planta origen

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `1a108038fa5a3f7cfe25c13189051980ae8294f9`

### Fase A — Auditoría Onelogis histórico (revisión con aclaración de Javier)

- Se re-auditó `gps_logic.js`/`main.js`/`gps_config.json`/`atlas_viajes.html` buscando explícitamente `history`, `historical`, `trips`, `viajes`, `recorrido`, `positions`, `tracking`, `route`, `fechaDesde`, `fechaHasta` — sin resultados nuevos más allá de lo ya documentado en RUTAS R1 (solo `.../gps/ultimas-posiciones`). Búsqueda repetida en `G:\...\BACKUP_PRE_FORMATEO_20260808` — sin resultados.
- Javier confirmó (uso manual de su cuenta Onelogis) que la plataforma sí ofrece histórico de viajes por fecha. Se investigó si existe documentación pública de API de Onelogis (`WebSearch`/`WebFetch` sobre `onelogis.com`) — sin resultados (sitio bloquea `WebFetch`, sin documentación de API indexada públicamente).
- **No se intentó** probar rutas de endpoint no confirmadas contra el sistema en producción, ni automatizar el navegador de Onelogis — ambos explícitamente fuera de alcance. Conclusión: la capacidad existe en la plataforma Onelogis, pero no hay evidencia técnica de que la integración actual de Atlas (ni ninguna alternativa segura de descubrir desde este entorno) pueda consumirla hoy. Queda como gestión pendiente de Javier (revisar su cuenta/soporte Onelogis).

### Fase B — Inspección de `_resolver_origen_documental` (`origin/feature-cobertura-origen-fase1`)

- Leído vía `git show` (sin cherry-pick, sin restaurar archivos) el código completo: `_distancia_token` (Levenshtein acotado a diferencia de longitud ≤1), `_tokens_encabezado_origen` (corta tokens antes de la primera mención tolerante de "SUCURSAL"), `_resolver_origen_documental` (exige que TODOS los tokens del nombre de una planta CONFIRMADA/ACTIVA aparezcan entre los tokens observados, con distancia ≤1 cada uno; exige consenso ≥2 de N lecturas y planta única — 0 o ≥2 candidatas → abstención).
- Señales: nombre de planta impreso en el propio encabezado de la guía ("CASA MATRIZ PLANTA <NOMBRE>"). Precisión real reportada en el commit de cierre (`2c5c764`): 9 guías reales, cobertura 4/9 → 7/9, **0 falsos positivos** — los 2 casos sin resolver (464107, 464109) fueron por desenfoque/omisión de OCR, no por error de lógica. Generaliza correctamente Renca/Colina (compara contra CUALQUIER planta CONFIRMADA/ACTIVA del catálogo, no hardcodea nombres) — el propio caso que motivó el fix (`2c5c764`) es que el catálogo real confirma ambas plantas a la vez y el directorio de sucursales (que menciona "Colina") generaba una segunda coincidencia sin el corte "SUCURSAL".
- **Cambio necesario para adaptar a HEAD actual:** `leer_encabezado_origen_focal` (la función que RELEE el encabezado) llama `lector.readtext(..., detail=0, paragraph=False)` — API específica de `easyocr.Reader`, no soportada por `PaddleOCRProvider` (mismo patrón de acoplamiento ya diagnosticado y resuelto para fecha/transporte focal en bloques anteriores). **No se portó esa función.** En su lugar, se comprobó (con la guía real `464170`, ya usada en C1/D1) que el encabezado del emisor ya aparece dentro del texto de página completa que entrega PaddleOCR con confianza alta (`CASAMATRIZPLANTARENCA`, línea 5 del OCR real) — por lo que la relectura focal resulta innecesaria con el proveedor actual. Solo se adaptó/portó la lógica pura de texto (`_distancia_token`, `_tokens_encabezado_origen`, `_resolver_origen_documental`), operando sobre `textos` de página completa en vez de sobre 3 variantes de un recorte focal.

### Fase C — Estrategia elegida: `DOCUMENTAL_PRINCIPAL_GPS_TIEMPO_REAL`

- GPS histórico no disponible técnicamente hoy (Fase A) → no puede ser la vía principal. Evidencia documental ya validada (7/9 real, 0 falsos positivos, general por catálogo) → vía principal. GPS (última posición) queda disponible como señal de mayor prioridad SOLO cuando hay evidencia (patente+instante+proveedor+geocerca+ventana temporal), útil sobre todo para procesamiento cercano al instante real de salida, no para reprocesamiento histórico.

### Diseño (Fase C/E, implementación)

- **`atlas_core/rutas/origen_documental.py`** (nuevo): `resolver_origen_documental(textos, plantas)` — puerto de la lógica pura descrita en Fase B, con `_normalizar`/`_distancia_token`/`_tokens_encabezado_origen` propios (sin depender de `atlas_core.procesamiento_masivo`, evita acoplar el módulo aislado de rutas al extractor). Acepta cualquier objeto `planta` con atributos `nombre`/`estado_calidad`/`estado_vigencia` (duck typing vía `getattr`, compatible con `atlas_core.catalogo_plantas.Planta`).
- **`atlas_core/rutas/enriquecimiento_viaje.py`:**
  - `resolver_planta_origen` reestructurado: tramo GPS extraído a `_resolver_planta_por_gps` (misma lógica de RUTAS R1, sin cambios de comportamiento); si GPS no resuelve y se entrega `textos_documento`, se intenta `resolver_origen_documental`. **Política de conflicto conservadora:** el GPS, si resuelve, gana siempre — el documento nunca se evalúa si el GPS ya tuvo éxito (cortocircuito explícito en el código, no una regla de "votación"). **Cambio de firma:** devuelve ahora `(planta, motivo, determinado_por, evidencia)` — 4-tuple en vez del 2-tuple de RUTAS R1; único call-site externo (`tests/test_rutas_enriquecimiento_viaje.py`) actualizado.
  - `calcular_ruta_para_viaje` gana el parámetro opcional `textos_documento` y propaga `determinado_por`/`evidencia_origen` al resultado (antes hardcodeaba `"ONELOGIS_GPS"`).
  - **Fix defensivo nuevo:** si la planta determinada (por cualquier vía) no tiene `latitud`/`longitud` cargadas en catálogo, se trata como `ORIGEN_NO_DETERMINADO` (`motivo="PLANTA_SIN_COORDENADAS_EN_CATALOGO"`) en vez de dejar que `Coordenadas.__post_init__` lance `TypeError` — encontrado real al ejecutar la Fase E contra el catálogo real (AZA COLINA sin coordenadas, ver corrección de catálogo).
  - `ResultadoEnriquecimientoRuta` gana `evidencia_origen` (GPS: `"gps_timestamp=...;distancia_km=..."`; documento: `"ENCABEZADO_GUIA"`).
- **`atlas_core/reporte_viajes.py`:** `COLUMNAS_VIAJES`/`_CAMPOS_RUTA_VACIOS` ganan `evidencia_origen` al final — mismo criterio backward-compatible de RUTAS R1.
- **Corrección de catálogo real (`plantas.json`), con respaldo previo:** `AZA COLINA` no tenía `latitud`/`longitud` desde antes de este bloque (bug latente heredado, no introducido aquí — bloqueaba cualquier ruta real con ese origen). Respaldo completo en `Desktop\Atlas\backups_catalogos\20260811_104321_pre_coordenadas_aza_colina\`. Editado vía `CatalogoPlantas.editar(modificacion_manual=True, latitud=-33.137558, longitud=-70.665977, observacion=...)` — reutiliza la coordenada ya geocodificada vía ORS (2026-07-27, fallback, confidence 0.6, nivel calle/comuna) para la misma dirección física, presente en `destinos_maestros.json` bajo "ACEROS AZA SA" (mismo workaround ya documentado en RUTAS R1, ahora aplicado a la fuente correcta). Verificado releyendo desde disco tras escribir; `AZA RENCA` confirmada intacta.

### Validación

- Tests nuevos: 7 en `tests/test_rutas_origen_documental.py` (Renca resuelve, Colina resuelve, ignora directorio de sucursales con el caso real que motivó el fix histórico, sin evidencia abstiene, ambiguo abstiene, ignora plantas no confirmadas, ignora plantas inactivas) + 3 en `tests/test_rutas_enriquecimiento_viaje.py` (GPS no alcanza → cae a documento; conflicto GPS-vs-documento → gana GPS siempre; sin evidencia ninguna → `ORIGEN_NO_DETERMINADO`) + 1 test defensivo (planta determinada sin coordenadas en catálogo → no lanza, `ORIGEN_NO_DETERMINADO`). 1 test existente de RUTAS R1 actualizado para el nuevo 4-tuple de `resolver_planta_origen`.
- Suite completa: **618 → 629 passed**, 0 failed.
- **Fase D — matriz real, 12 guías AZA disponibles hoy** (el set histórico original de 9 —`464089`, `462429`, `464106-464110`, `464259`— no existe como archivo de imagen accesible en este equipo; sustituido por el set real disponible en `output/_entrantes_desktop`, superando el mínimo de 9 pedido), PaddleOCR real, catálogo real:

  | archivo | origen_real (lectura humana del encabezado OCR) | resultado_final | correcto | método |
  |---|---|---|---|---|
  | 464170.jpeg | AZA RENCA | AZA RENCA | ✅ | DOCUMENTO |
  | 464511.jpeg | AZA RENCA | AZA RENCA | ✅ | DOCUMENTO |
  | 464264.jpeg | AZA RENCA | AZA RENCA | ✅ | DOCUMENTO |
  | 464265.jpeg | AZA RENCA | AZA RENCA | ✅ | DOCUMENTO |
  | 464367.jpeg | AZA RENCA | AZA RENCA | ✅ | DOCUMENTO |
  | 464395.jpeg | AZA RENCA | AZA RENCA | ✅ | DOCUMENTO |
  | 464424.jpeg | AZA RENCA | AZA RENCA | ✅ | DOCUMENTO |
  | 464479.jpeg | AZA RENCA | AZA RENCA | ✅ | DOCUMENTO |
  | 464488.jpeg | AZA RENCA | AZA RENCA | ✅ | DOCUMENTO |
  | 464489.jpeg | AZA RENCA | AZA RENCA | ✅ | DOCUMENTO |
  | 464491.jpeg | AZA RENCA | AZA RENCA | ✅ | DOCUMENTO |
  | 464493.jpeg | AZA RENCA | `NO_DETERMINADO` (abstención segura) | ⚠️ abstención, no error | — |

  **11/12 correctas, 1/12 abstención segura, 0 asignaciones incorrectas.** GPS histórico no evaluado en la matriz por no estar disponible (Fase A); ninguna guía real de AZA COLINA estaba disponible para incluir en esta matriz (compensado en Fase E con un patrón real de encabezado, ver abajo). Causa diagnosticada del caso 464493: Paddle leyó "Sucursal" como "ursal"/"Cursal" (perdió el prefijo), fuera de la tolerancia de corte (edición ≤1 y diferencia de longitud ≤1 combinadas) — el corte no se activó, "COLINA" del directorio de sucursales quedó en el texto comparado y generó ambigüedad real junto con "RENCA" (2 coincidencias) → abstención correcta.
- **Fase E — conectado a ORS real + caché real:** AZA RENCA (documento, texto real de `464170`) → Torres Ocaranza Ltda = **16.683 km / 24.53 min**, `RUTA_CALCULADA` (idéntico al resultado de RUTAS R1 para el mismo par con GPS inyectado — validación cruzada). AZA COLINA (documento, patrón real de encabezado AZA, sin imagen real de guía Colina disponible en este equipo) → Prodalam SA = **41.310 km / 47.35 min**, `RUTA_CALCULADA`. Repetir el primer par → `RESULTADO_DESDE_CACHE`, mismo resultado, 0 llamadas nuevas a ORS.
- **0 secretos**: `grep` sobre todos los artefactos nuevos de `rutas_eval/` antes de commitear, sin coincidencias.
- Archivos modificados: `atlas_core/reporte_viajes.py`, `atlas_core/rutas/__init__.py`, `atlas_core/rutas/enriquecimiento_viaje.py`, `tests/test_rutas_enriquecimiento_viaje.py`. Archivos nuevos: `atlas_core/rutas/origen_documental.py`, `tests/test_rutas_origen_documental.py`. Catálogo real modificado fuera del repo: `plantas.json` (respaldo previo). Sin cambios en `atlas_core/rutas/{geocerca,posicion_vehiculo,modelos,proveedor,servicio,repositorio,openrouteservice}.py`, `atlas_core/gestor_viajes.py`, ni Desktop.

### Continuidad

- Sin bloqueo técnico que impida cerrar: se eligió `DOCUMENTAL_PRINCIPAL_GPS_TIEMPO_REAL` como conclusión concreta. Pendiente NO bloqueante: (a) que Javier confirme desde su cuenta Onelogis si existe una vía de API/exportación oficial para histórico — mejoraría cobertura y quitaría dependencia del encabezado de cada guía; (b) validar el mecanismo documental contra guías reales de AZA COLINA (solo probado con patrón sintético en Fase E, no había ninguna imagen real disponible en este equipo).

---

## 2026-08-11 — Cierre RUTAS R1: km/tiempos conectados al viaje + auditoría Onelogis

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `5f201d418a3fcd6ee1287d1e05b1335efe87e043`

### Auditoría Onelogis/GPS (Paso 1)

- **Búsqueda:** `grep -rli onelogis` sobre todo `Desktop\Atlas` (repo + Desktop app + backup) más `git log --all -i -S"onelogis"`. Hallazgo: `Atlas-Viajes-Desktop-Restaurado/src/gps_logic.js` (función `obtenerUltimasPosicionesGps`), consumida desde `main.js` (IPC `atlas:gps-obtener-posiciones`, `atlas:gps-estado-configuracion`, `atlas:gps-configurar`) y renderizada en `src/gps_ui.js` (mapa Leaflet, pestaña GPS del Desktop). Configuración persistida vía electron-store (`gps_config.json`: `url` + `apiKey`, ya detectada en un bloque anterior de este mismo día).
- **Esquema real de datos, por bloque `vehiculo`:** `{patente, estado, latitude, longitude, speed, timestamp}`; `estado !== "REPORTADO"` implica sin dato reciente. **Es exclusivamente snapshot de última posición** — la UI hace polling cada 30s (`INTERVALO_REFRESCO_MS`) mientras la pestaña está abierta; no hay parámro de fecha/rango en la llamada (`GET .../gps/ultimas-posiciones`, sin query de tiempo) ni ningún otro archivo/endpoint de histórico en todo el árbol (`grep` de "historico"/"historial"/"timeseries" sin resultados relevantes; sin código de backend/Lambda en el repo).
- **Conclusión:** Onelogis está integrado y funcionando, pero la única capacidad disponible es "dónde está el camión ahora", no "dónde estaba a las X". Para el flujo real de Atlas (guías OCR'd después del hecho, no en tiempo real), esto significa que la resolución de planta por GPS **no puede alimentarse con datos históricos reales hoy** — es una limitación estructural de la integración actual, no del código de este bloque.
- **Hallazgo adicional (contexto, no usado en este bloque):** existe una rama remota `origin/feature-cobertura-origen-fase1` (divergente de `lector-mvp-guia-nueva` desde antes de `61958f2`, con 54 archivos de test vs. los actuales) que contiene `_resolver_origen_documental`/`leer_encabezado_origen_focal` — un resolver de planta **documental** (lee qué sucursal AZA imprime la propia guía en su encabezado, no GPS), con cobertura real reportada 7/9 en su commit de cierre (`2c5c764`). No fusionado, no portado en este bloque (fuera de alcance: este bloque es específicamente sobre Onelogis/GPS, y fusionar esa rama implicaría reconciliar mucha lógica de cliente/chofer/destino divergente de C1/D1). Queda documentado como insumo directo para el próximo bloque de origen.

### Diseño

- **`atlas_core/rutas/posicion_vehiculo.py`** (nuevo): `EstadoPosicionVehiculo` (`POSICION_ENCONTRADA`/`SIN_DATOS`/`PROVEEDOR_NO_DISPONIBLE`), `ResultadoPosicionVehiculo` (estado, coordenadas, timestamp_gps, proveedor, motivo), protocolo `ProveedorPosicionVehiculo` (`obtener_posicion(patente, instante) -> ResultadoPosicionVehiculo`) y doble `ProveedorPosicionVehiculoSimulado` (mismo patrón que `ProveedorRutasSimulado` en `atlas_core/rutas/proveedor.py`). Sin adaptador real: no hay endpoint histórico contra el cual construirlo honestamente.
- **`atlas_core/rutas/geocerca.py`** (nuevo): `distancia_km_haversine` + `resolver_planta_por_posicion(posicion, plantas, radio_km=1.5)`. Ordena candidatas por distancia; se abstiene (`FUERA_DE_GEOCERCA`) si ninguna cae dentro del radio, o (`AMBIGUO_ENTRE_PLANTAS`) si dos quedan empatadas a la distancia mínima. Radio `1.5 km` es un valor de partida conservador, **no calibrado contra posiciones reales** (no existen, ver auditoría) — documentado explícitamente como tal en el código. AZA Renca/Colina están separadas por decenas de km reales (confirmado con ORS), por lo que el radio nunca las confunde entre sí.
- **`atlas_core/rutas/enriquecimiento_viaje.py`** (nuevo), tres funciones:
  - `resolver_destino_canonico(texto, catalogo_destinos)`: reutiliza `CatalogoDestinos.buscar()` (ya existente en `atlas_core/catalogo_destinos.py`, sin duplicar lógica de matching) sobre `destinos_maestros.json` (mismo formato `Destino`/`version_formato=1` que `CatalogoDestinos` ya sabe leer — confirmado comparando campos). Exige `COINCIDENCIA` exacta (nunca texto OCR no homologado), `estado_vigencia=ACTIVO`, coordenadas presentes y dentro de `RANGO_LATITUD_RM=(-34.5,-32.5)` / `RANGO_LONGITUD_RM=(-71.5,-70.0)` — un rango geográfico general, no una exclusión por nombre de comuna, que de forma natural excluye los 4 registros "SAN MIGUEL" con coordenada errónea (`lat=-30.81`, zona de Ovalle) detectados en RUTAS-EVAL R1, sin hardcodear ese caso particular.
  - `resolver_planta_origen(patente, instante_salida, proveedor_posicion, plantas, radio_km)`: sin patente, instante o proveedor → `SIN_EVIDENCIA_GPS`. Con proveedor, valida `POSICION_ENCONTRADA`, parsea `timestamp_gps` (ISO) y exige que esté a menos de `VENTANA_MAXIMA_POSICION_GPS=2h` del instante de salida (si no: `POSICION_GPS_DEMASIADO_ANTIGUA`; si el timestamp no es parseable: `POSICION_GPS_SIN_TIMESTAMP_VALIDO`), y solo entonces aplica la geocerca. Nunca infiere por ruta más corta.
  - `calcular_ruta_para_viaje(...)`: orquesta ambas resoluciones y, solo si ambas tienen éxito, llama a `ServicioRutas.confirmar_y_calcular(planta, destino, "driving-hgv", ...)` (ya existente, con caché de `RepositorioRutas` incluido sin cambios). Devuelve siempre un `ResultadoEnriquecimientoRuta` (nunca lanza) con `estado_ruta`/`motivo_ruta` explicativos ante cualquier fallo en cualquier paso — un error de ruta nunca invalida el viaje que lo llama.
- **`atlas_core/rutas/modelos.py`:** 2 miembros nuevos en `EstadoRuta`: `ORIGEN_NO_DETERMINADO`, `DESTINO_NO_VALIDO`.
- **`atlas_core/reporte_viajes.py`:** `COLUMNAS_VIAJES` gana 10 columnas al final (`planta_origen_id`, `planta_origen_nombre`, `destino_id`, `destino_nombre`, `distancia_km`, `duracion_min`, `proveedor_ruta`, `estado_ruta`, `motivo_ruta`, `origen_determinado_por`). `_fila_viaje()` y `generar_reporte_viajes()` ganan un parámetro opcional `calculador_rutas: Callable[[Viaje], dict[str,str]] | None = None`; sin él, las 10 columnas nuevas quedan vacías (`_CAMPOS_RUTA_VACIOS`) — el reporte generado es byte-idéntico en contenido al de antes de este bloque salvo por esas columnas vacías. Desktop no se tocó.
- **`atlas_core/rutas/__init__.py`:** exporta los símbolos nuevos, mismo criterio que los ya existentes.

### Validación

- Tests nuevos: 13 en `tests/test_rutas_enriquecimiento_viaje.py` (geocerca Renca/Colina/fuera-de-rango, GPS demasiado antiguo, planta+destino válidos → ORS real vía doble simulado, segunda ejecución → caché sin nueva llamada, destino inválido parametrizado en 4 casos → no llama ORS, Onelogis sin datos → no falla, sin proveedor de posición → no falla, km/min persistidos + perfil `driving-hgv` capturado) + 2 en `tests/test_reporte_viajes.py` (columnas de ruta vacías sin `calculador_rutas` = no regresión, propagación completa con `calculador_rutas` inyectado + verificación de ausencia de secretos en el CSV resultante). 1 assertion existente ajustada en `tests/test_rutas_modelos.py` (`test_estados_minimos_estan_disponibles`) para incluir los 2 estados nuevos.
- Suite completa: **603 → 618 passed**, 0 failed.
- **Validación real** (catálogo activo real `%LOCALAPPDATA%\Atlas\datos\catalogos_privados`, ORS real vía `api.heigit.org`, clave puenteada de proceso sin exponerla, `driving-hgv`), 3 viajes + 1 repetición:
  | viaje | destino | planta | km | min | estado | motivo |
  |---|---|---|---|---|---|---|
  | 1 | EBEMA SA / Galvarino 8501 | AZA RENCA (GPS inyectado) | — | — | `REQUIERE_REVISION` | `DESTINO_NO_CONFIRMADO` (salvaguarda ya existente de `ServicioRutas`, destino real aún `PENDIENTE`) |
  | 2 | Torres Ocaranza Ltda / Vista Clara 2351 | AZA RENCA (GPS inyectado) | 16.68 | 24.53 | `RUTA_CALCULADA` | — |
  | 3 | mismo que 2 | — (patente sin GPS) | — | — | `ORIGEN_NO_DETERMINADO` | `GPS_SIN_DATOS` |
  | repetición de 2 | igual | igual | 16.68 (idéntico) | 24.53 (idéntico) | `RESULTADO_DESDE_CACHE` | — |
- **Nota de honestidad técnica:** el "GPS" de los viajes 1/2 es una posición **inyectada** (coordenada real de AZA Renca, proveedor `simulado_demo_geocerca`), no una consulta histórica real a Onelogis — porque esa capacidad no existe hoy (ver auditoría). Demuestra que el mecanismo end-to-end (geocerca → destino canónico → ORS real → caché) funciona correctamente con datos y ORS reales; no demuestra determinación automática de origen para una guía histórica real.
- **0 secretos**: `grep` sobre `rutas_eval/resultado_rutas_r1_prueba_real.json`, `rutas_eval/cache_rutas_r1_real.json` y el `viajes.csv` de prueba, sin coincidencias de `authorization`/`bearer`/`api_key`.
- Archivos modificados: `atlas_core/reporte_viajes.py`, `atlas_core/rutas/__init__.py`, `atlas_core/rutas/modelos.py`, `tests/test_reporte_viajes.py`, `tests/test_rutas_modelos.py`. Archivos nuevos: `atlas_core/rutas/enriquecimiento_viaje.py`, `atlas_core/rutas/geocerca.py`, `atlas_core/rutas/posicion_vehiculo.py`, `tests/test_rutas_enriquecimiento_viaje.py`. Sin cambios en `atlas_core/gestor_viajes.py`, `atlas_core/rutas/{modelos con excepción de EstadoRuta,proveedor,servicio,repositorio,openrouteservice}.py`, catálogos, ni Desktop.

### Continuidad

- **Siguiente bloque obligatorio: PLANTA-P1 / ONELOGIS.** Sin una fuente real de posición histórica (o una alternativa documental, ver `_resolver_origen_documental` en `origin/feature-cobertura-origen-fase1`), `planta_origen` seguirá resolviendo `ORIGEN_NO_DETERMINADO` para la gran mayoría de guías reales procesadas después del hecho — comportamiento correcto y seguro (no hay km/min fabricados), pero no automático. No se debe mostrar km/min en Desktop hasta resolver esto.

---

## 2026-08-11 — Cierre Bloque C1: cliente + chofer nuevo + propagación de REVISAR al viaje

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `129b459d936d6d05ae0615cc93fa8842440f4d3a`

### Problema real confirmado

- Guía real `464170`, transporte `0000351177`. PaddleOCR real leía correctamente `SEÑOR(ES): EBEMA SA`, `R.U.T.:83.585.400-0`, `RETIRA: IVAN ROA`, `RUT CHOFER:10190440-7` — pero `cliente` y `rut_cliente` quedaban `"No encontrado"`, `chofer` quedaba sin homologar y el viaje agregado (`agrupar_viajes`) quedaba `CONFIRMADO` sin motivo pese al documento `REVISAR`.
- Diagnóstico ya cerrado en la sesión previa identificó seis causas puntuales (Ñ no normalizada en `buscar_cliente`, colisión de etiqueta geométrica SEÑOR con nombres de destino, ausencia de extracción genérica de RUT cliente, IVAN ROA no catalogado, y `agrupar_viajes` ignorando `indicador_revision`).

### Diseño

- **`atlas_core/extractor.py`:**
  - `_normalizar_acentos(texto)`: reemplaza Á/É/Í/Ó/Ú/Ñ (mayúscula y minúscula) por su forma sin tilde. Centraliza una normalización que antes vivía duplicada e inconsistente: `_texto_simple` sí incluía Ñ→N, pero `texto_busqueda` (usado por `buscar_cliente`/`buscar_obra_destino`/`buscar_rut_chofer` vía regex lineal) y `normalizar_cliente`/`normalizar_obra_destino` no. `_texto_simple` y esas tres funciones ahora llaman al mismo helper.
  - `_es_etiqueta_senor(texto_simple)`: `re.fullmatch(r"SENOR(?:\(ES\)|\(IES\)|ES|IES)?", texto_simple)` — el bloque OCR completo (ya normalizado) debe **ser** la etiqueta, no solo contenerla. Reemplaza el `re.search(r"\bSENOR(?:ES|IES)?\b", ...)` que usaba `_extraer_asociaciones_geometricas`, el cual disparaba (falso positivo) sobre cualquier bloque que contuviera la palabra "SEÑOR" en cualquier posición — caso real: el propio nombre del destino "SUPERMERCADO SEÑOR DE LOS MI" (aparece dos veces, en SOLICITANTE y OBRA DESTINO) generaba una etiqueta de cliente falsa cuyo candidato más cercano ("ORDEN DE COMPRA") quedaba a solo 0.045 de score de la decisión correcta — por debajo del margen de ambigüedad (0.06) del algoritmo, forzando abstención total aunque "EBEMA SA" ya fuera el mejor candidato real.
  - `_extraer_rut_cliente_geometrico(bloques)`: nueva función geométrica, mismo patrón ancla→zona→candidato que `_extraer_chofer_geometrico`/`_extraer_transporte_geometrico`. Ubica una etiqueta `SEÑOR(ES)` (vía `_es_etiqueta_senor`), busca una etiqueta `R.U.T.`/`RUT` inmediatamente debajo (misma columna x, gap vertical acotado), y solo acepta como candidato un valor a su derecha que sea un **RUT chileno válido** (dígito verificador correcto, vía `validar_rut_chileno`). Se abstiene si hay cero o más de un candidato válido distinto — nunca inventa un RUT ni depende de ningún nombre de cliente hardcodeado.
  - `buscar_rut_chofer()`: el regex `r"RUT\s*CHOFER\s*([0-9.\s-]{7,15})"` no toleraba el `:` que PaddleOCR deja pegado al valor cuando la etiqueta y el valor caen en líneas OCR separadas (`"RUT CHOFER\n:10190440-7"`); se agregó `:?` opcional entre la etiqueta y el valor. Genérico, no depende de ningún RUT/chofer particular.
- **`atlas_core/procesamiento_masivo.py`:** `RUT del cliente` se agregó a la condición `campos_ausentes`; dentro del mismo bloque `try` de recuperación geométrica (después de recuperar cliente/obra destino, antes de chofer), se llama `_extraer_rut_cliente_geometrico(bloques_guia)` y, si devuelve valor, se asigna a `datos["RUT del cliente"]` y se marca `recuperacion_geometrica = True` (mismo criterio de todas las recuperaciones geométricas: fuerza `indicador_revision = "REVISAR"`). El `enriquecer_datos_con_catalogos` que ya se re-ejecutaba al final del bloque de catálogos (P2, sin cambios) recoge automáticamente ese RUT recién recuperado y fija el nombre canónico del cliente desde `empresas.json` — sin lógica nueva de canonicalización, reutiliza la ya existente.
- **`atlas_core/gestor_viajes.py`:** nuevo `MotivoRevision.DOCUMENTO_REQUIERE_REVISION` y helper `_documento_marca_revision(fila)` (`str(fila.get("indicador_revision","")).strip().casefold() == "revisar"`). Dentro de `agrupar_viajes`, además de los `campos_conflicto` ya existentes (comparación entre documentos), se agrega este motivo si **cualquier** documento del grupo trae `indicador_revision=REVISAR` — independiente de si hay o no conflictos entre documentos. Antes, `indicador_revision` no se leía en ningún punto de esta función; un transporte de un solo documento nunca podía generar contradicción consigo mismo y quedaba `CONFIRMADO` sin importar su propio estado.
- **Catálogo (fuera del repo):** fuente activa real identificada vía `%APPDATA%\atlas-viajes-desktop\config_usuario.json` (electron-store del Desktop instalado) → `%LOCALAPPDATA%\Atlas\datos\catalogos_privados\choferes.json`. Se agregó el registro `"101904407": {"nombre": "IVAN ROA", "activo": true}` (RUT normalizado como clave, mismo esquema exacto de los 28 registros existentes, sin `aliases` — chofer nuevo real, no alias, confirmado por Javier). Validado: RUT con dígito verificador correcto, clave y nombre únicos, JSON parseable tras escritura.

### Validación

- Tests nuevos: 4 en `tests/test_extraer_datos.py` (SEÑOR(ES) con Ñ real resuelve cliente lineal; "SUPERMERCADO SEÑOR DE LOS MI" no se interpreta como etiqueta; RUT cliente genérico recupera 83.585.400-0; RUT cliente ambiguo se abstiene) + 1 corolario (`buscar_rut_chofer` tolera `:` pegado al valor); 3 en `tests/test_catalogos.py` (IVAN ROA resuelve exacto por RUT; RUT 10190440-7 asocia IVAN ROA vía enriquecimiento; EBEMA SA ya catalogada resuelve a su nombre canónico); 1 en `tests/test_catalogos.py` (fuzzy no reescribe IVAN ROA hacia otro chofer similar); 4 en `tests/test_gestor_viajes.py` (documento REVISAR fuerza REQUIERE_REVISION; documento OK simple puede quedar CONFIRMADO; conflicto multiguía persiste con documentos OK; conflicto y documento REVISAR coexisten sin eliminarse mutuamente).
- Fixtures existentes actualizadas (no tests nuevos): 3 en `tests/test_procesamiento_masivo.py` (`test_procesar_archivo_no_reemplaza_valores_lineales_correctos`, `test_procesar_archivo_preserva_chofer_lineal_limpio`, y el helper compartido `_datos_lineales_completos` usado por 2 tests más) — no incluían `RUT del cliente`, lo que ahora disparaba lectura de bloques que esos tests explícitamente verifican que no ocurra; se agregó el campo sin tocar la intención original de cada test.
- 1 assertion existente ajustada en `tests/test_gestor_viajes.py` (`test_conflictos_multiples_se_declaran_juntos_sin_perder_evidencia`): el set de "todos los motivos posibles" ahora también excluye `DOCUMENTO_REQUIERE_REVISION` además de `FECHA_NO_COMPATIBLE_DESKTOP`, porque ese escenario no fija `indicador_revision` en ninguna fila.
- Suite completa: **581 → 594 passed**, 0 failed.
- **Validación real, guía `464170`, PaddleOCR GPU real, catálogo activo real (`%LOCALAPPDATA%\Atlas\datos\catalogos_privados`, ya con IVAN ROA agregado):**
  - `numero_guia=464170`, `numero_transporte=0000351177` (sin cambio).
  - `cliente`: `No encontrado` → **`EBEMA SA`**.
  - `RUT del cliente`: `No encontrado` → **`83.585.400-0`** (formato canónico con puntos, vía `empresas.json`).
  - `chofer`: `IVAN ROA` (ya se leía, sin homologar) → **`IVAN ROA`** (homologado exacto contra catálogo).
  - `rut_chofer`: `No encontrado` → **`10190440-7`** (sin puntos — mismo formato histórico que `buscar_rut_chofer()` ya usaba para otros choferes, no una regresión).
  - `indicador_revision`: `REVISAR` → `REVISAR` (sin cambio; causa legítima vigente: el documento siguió necesitando recuperación geométrica de cliente/RUT cliente/chofer).
  - Viaje agrupado (`agrupar_viajes`): `CONFIRMADO` sin motivo → **`REQUIERE_REVISION`, motivo `DOCUMENTO_REQUIERE_REVISION`**.
  - `obra_destino` sin cambio (`"VENTA AL POR MAYOR D"`, incorrecto) — explícitamente fuera de alcance de C1.
- Archivos modificados: `atlas_core/extractor.py`, `atlas_core/procesamiento_masivo.py`, `atlas_core/gestor_viajes.py`, `tests/test_extraer_datos.py`, `tests/test_catalogos.py`, `tests/test_gestor_viajes.py`, `tests/test_procesamiento_masivo.py`. Catálogo real modificado fuera del repo: `%LOCALAPPDATA%\Atlas\datos\catalogos_privados\choferes.json` (respaldo previo en `Desktop\Atlas\backups_catalogos\20260811_063918_pre_alta_ivan_roa\`). Sin cambios en OCR (`atlas_core/ocr.py`, `atlas_core/ocr_provider.py`, `atlas_core/paddle_runtime.py`) ni en `atlas_core/catalogos.py`/`atlas_core/reporte_viajes.py`/`generar_reporte_viajes.py`.

### Continuidad

- **Siguiente bloque oficial: DESTINO D1** — corregir `obra_destino` (hoy resuelve al valor de GIRO en vez del destino real, misma familia de colisión geométrica que motivó C1 pero en otro campo), prerrequisito directo para rutas/KM/tiempos. No iniciado.

---

## 2026-08-10 — Cierre Patentes P2: homologación conservadora contra catálogo de vehículos

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `0021bde59a9bb2f7b18462377ea6634d5cade781`

### Objetivo

P1 ya recuperaba `patente_tracto`/`patente_carro` con salida Paddle, pero devolvía el valor OCR crudo tal cual (p. ej. `SD6486`), sin resolver su identidad canónica. P2 resuelve únicamente esa identidad, contra la fuente canónica de vehículos privados ya integrada vía `carpeta_catalogos` (`vehiculos.json`), sin tocar Paddle, sin cambiar regex de OCR, sin tocar Desktop ni la generación de reportes.

### Diseño

- Nueva función `resolver_patente_canonica(catalogo, patente_ocr, *, tipo_esperado=None)` en `atlas_core/catalogos.py`, junto a un dataclass `ResultadoResolucionPatente(estado, valor_original, valor_resultado, candidatos_ambiguos)` trazable (mismo patrón que `ResultadoCoincidenciaChofer`/`resolver_nombre_chofer_difuso`).
- Jerarquía de resolución, en orden:
  - **A. Coincidencia exacta normalizada** — el valor OCR ya está en el catálogo (mismo comportamiento que la normalización de formato ya existente en `enriquecer_datos_con_catalogos`).
  - **B. Alias explícito declarado en el catálogo** — si el registro del vehículo trae un campo `"alias": [...]`, se acepta un valor OCR que coincida con un alias, sin inferir nada no declarado.
  - **C. Corrección OCR conservadora** — se acepta solo si: (1) el valor OCR tiene forma plausible de patente chilena (`_forma_patente_plausible`, mismo patrón `[A-Z0-9]{6}` con al menos una letra y un dígito que ya usa el extractor); (2) hay un único candidato de catálogo con la misma longitud; (3) la diferencia es de **una sola posición**, explicada por una confusión OCR común y documentada — `_CONFUSIONES_OCR_PATENTE_COMUNES = {B/D, 0/O, 1/I, 5/S, 8/B}` (tabla deliberadamente pequeña y con evidencia, no una heurística amplia); (4) no hay un segundo candidato igualmente plausible. Dos o más diferencias, o dos o más candidatos, nunca se corrigen.
  - `tipo_esperado` (`"TRACTO"`/`"CARRO"`) filtra los candidatos de la corrección conservadora por el campo `tipo` del registro, cuando existe, para que una patente de tracto nunca se homologue accidentalmente contra un carro y viceversa.
  - Nunca crea una patente que no exista ya en el catálogo.
- `atlas_core/procesamiento_masivo.py` (`procesar_archivo`): dentro del bloque `if carpeta_catalogos is not None:` (después de `enriquecer_datos_con_catalogos`, para cubrir el valor final sea cual sea su origen — lectura lineal o recuperación geométrica P1), se carga `vehiculos.json` y se llama `resolver_patente_canonica` para `patente del tracto` (tipo `TRACTO`) y `patente del carro` (tipo `CARRO`):
  - `COINCIDENCIA_EXACTA` → aplica el valor, sin marcar revisión adicional (mismo comportamiento silencioso que ya existía).
  - `ALIAS` / `CORRECCION_OCR_SEGURA` → aplica el valor homologado y marca `homologacion_patente = True` (fuerza `indicador_revision = "REVISAR"`, mismo criterio que toda recuperación no literal en el proyecto).
  - `AMBIGUO` → conserva el valor OCR sin cambios y también marca `homologacion_patente = True` (mantener valor OCR + REVISAR, tal como pide el contrato).
  - `SIN_CANDIDATO` / `CATALOGO_VACIO` / `VACIO` → sin cambios, sin marca adicional.
  - Todo el bloque envuelto en `try/except` (mismo patrón que el resto de fallbacks): un problema de catálogo nunca invalida el procesamiento principal.

### Validación

- Caso real obligatorio, guía `464511`, catálogo real (`vehiculos.json` con `SB6486`/`JF4288`): **`patente_tracto` `SD6486` → `SB6486`** (corrección OCR conservadora, único candidato, diferencia B/D en una posición); **`patente_rampla` `JF4288` → `JF4288`** (coincidencia exacta, sin cambios). Resto de campos (`numero_guia`, `numero_transporte`, `fecha`, `chofer`, `cliente`) sin cambios respecto al resultado post-P1.
- La corrección `SD6486 → SB6486` no está hardcodeada por archivo/nombre de guía: surge exclusivamente de la jerarquía general de `resolver_patente_canonica` aplicada contra el contenido real del catálogo.
- Tests específicos: 11 unitarios de `resolver_patente_canonica` en `tests/test_catalogos.py` (exacto, alias, `SD6486→SB6486` con catálogo real simulado, rampla exacta sin modificar, candidato ambiguo → abstención, dos diferencias → no corregir, patente desconocida → conserva, `"NO_APLICA"` preservado sin inventar, `"No encontrado"` no se toca, sin catálogo/catálogo inexistente → no inventa, filtro por `tipo_esperado` entre tracto y carro) + 4 de integración end-to-end en `tests/test_procesamiento_masivo.py` (homologación real con catálogo escrito en disco, ambigüedad mantiene OCR + `REVISAR`, sin `carpeta_catalogos` no homologa, P1 geométrico + P2 homologación encadenados sobre la misma guía sin interferencia — no regresión de P1).
- Suite completa: **566 → 581 passed**.
- Archivos modificados: `atlas_core/catalogos.py`, `atlas_core/procesamiento_masivo.py`, `tests/test_catalogos.py`, `tests/test_procesamiento_masivo.py`. Sin cambios en OCR (`atlas_core/ocr.py`, `atlas_core/ocr_provider.py`, `atlas_core/paddle_runtime.py`, `atlas_core/extractor.py`), Desktop (`resumen_procesamiento_desktop.py`, `atlas_core/gestor_viajes.py`) ni reportes (`generar_reporte_viajes.py`, `atlas_core/reporte_viajes.py`) — ambos reciben el valor homologado únicamente porque consumen el dict que devuelve `procesar_archivo`.

### Continuidad

- Frente de patentes (P1 + P2) queda cerrado. No hay un microbloque siguiente de patentes definido.

---

## 2026-08-10 — Cierre Patentes P1: adaptar extractor a salida Paddle sin tocar OCR

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `0bcb43ca56e5ab1cdc6f596bb80af225ce234739`

### Problema real confirmado

- Guía real `464511`: tracto real `SB6486`, rampla real `JF4288`. Paddle entrega `PATENTE\n:SD6486 CARRO:JF4288` (B leída como D — error de reconocimiento, no de extracción).
- `buscar_chofer_y_patentes()` buscaba `texto_busqueda.find("RETIRA PATENTE FECHA LLEGADA")` como frase contigua; Paddle reparte esas etiquetas en bloques/líneas separados, por lo que el `find` nunca coincidía y la función retornaba `(None, None, None)` de inmediato. `patente_tracto`/`patente_carro` quedaban en `"No encontrado"`.

### Diseño

- `buscar_chofer_y_patentes()` (lectura lineal, formato histórico EasyOCR contiguo) **no se modificó** — sigue siendo la vía primaria en `extraer_datos`.
- Se movieron `patente_valida`/`normalizar_patente` (antes anidadas dentro de `extraer_datos`) a funciones de módulo `_patente_valida`/`_normalizar_patente`, sin cambiar su lógica, para reutilizarlas desde la nueva función geométrica.
- Nueva función `_extraer_patentes_geometrico(bloques)` en `atlas_core/extractor.py`, siguiendo el mismo patrón ancla→zona→candidato ya usado por `_extraer_chofer_geometrico`/`_extraer_transporte_geometrico`/`_extraer_fecha_geometrico`:
  - Ancla en bloques `RETIRA` (inicio) y `FECHA LLEGADA`/`LLEGADA` (fin) por coordenada Y; sin ancla `RETIRA`, se abstiene.
  - Define la zona geométrica entre ambas anclas (con margen de 15px; sin ancla de cierre, usa un margen conservador de 260px) y concatena solo los bloques dentro de esa zona en orden de lectura — tolerante a que Paddle fragmente las etiquetas en bloques distintos, sin requerir una frase contigua.
  - Extrae `CARRO`/`RAMPLA` con `\b(?:CARRO|RAMPLA)\s*:?\s*([A-Z0-9]{6})\b`; el resto de la zona (sin ese fragmento ni las etiquetas RETIRA/PATENTE/FECHA/LLEGADA) se escanea en busca de un token de 6 caracteres con forma de patente para el tracto.
  - Abstención conservadora: candidato fuera de la zona (no se incluye), o dos candidatos válidos para el mismo campo (ambigüedad) → no se resuelve ese campo.
  - **No corrige el valor OCR** (no convierte `SD6486` en `SB6486`): esa homologación queda fuera de alcance de P1 deliberadamente.
- `atlas_core/procesamiento_masivo.py` (`procesar_archivo`): se agregó `patente del tracto`/`patente del carro` a la condición `campos_ausentes` y se conectó `_extraer_patentes_geometrico` como *fallback* dentro del mismo bloque `try` que ya usan cliente/destino/chofer/transporte, activo solo si el campo sigue `"No encontrado"` tras la lectura lineal. Cualquier recuperación marca `recuperacion_patentes = True`, que fuerza `indicador_revision = "REVISAR"` (mismo criterio que las demás recuperaciones geométricas). No se tocó Desktop ni la generación de reportes — ambos consumen el dict que devuelve `procesar_archivo`, así que reciben el valor recuperado automáticamente.

### Validación

- Tests específicos: 8 escenarios geométricos unitarios (secuencia real Paddle con valor+CARRO en un solo bloque, etiquetas y valores en bloques separados, candidato fuera de zona → rechazo, dos candidatos ambiguos → abstención, solo tracto, solo carro, sin ancla RETIRA → abstención, no interferencia con extracción de chofer) + 1 regresión del formato histórico EasyOCR contiguo (`probar_guia5`, guía real SB6486/JF4288) + 1 integración end-to-end en `procesar_archivo` con bloques reales tipo Paddle.
- Suite completa: **556 → 566 passed**.
- Validación con la guía real `464511` (PaddleOCR real, GPU, sin mocks): **antes** `patente_tracto = "No encontrado"`, `patente_rampla = "No encontrado"`; **después** `patente_tracto = "SD6486"`, `patente_rampla = "JF4288"`. Resto de campos (`numero_guia`, `numero_transporte`, `fecha`, `chofer`, `cliente`) sin cambios. Confirmado mediante `git stash`/`git stash pop` comparando el mismo procesamiento real antes y después del cambio — **0 regresiones**.
- Archivos modificados: `atlas_core/extractor.py`, `atlas_core/procesamiento_masivo.py`, `tests/test_extraer_datos.py`, `tests/test_procesamiento_masivo.py`. Sin cambios en OCR (`atlas_core/ocr.py`, `atlas_core/ocr_provider.py`, `atlas_core/paddle_runtime.py`), Desktop (`resumen_procesamiento_desktop.py`, `atlas_core/gestor_viajes.py`) ni reportes (`generar_reporte_viajes.py`, `atlas_core/reporte_viajes.py`).

### Continuidad

- **Siguiente microbloque pendiente:** homologación de patente OCR contra catálogo de vehículos (ejemplo `SD6486 → SB6486`), sin alterar el OCR. No iniciado — es un problema de resolución/catálogo distinto al de extracción resuelto en P1.

---

## 2026-08-10 — Cierre integración Atlas Viajes Desktop ↔ Motor sobre Paddle M2

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `e61c04af4081b3d52761ad7928291bd88b6a83d2`

### Recuperación histórica selectiva

- `resumen_procesamiento_desktop.py` fue recuperado sin reconstrucción desde la historia Git; su blob `0b603a48be6af95370707a409bad5e3e0f711014` coincide con el original validado.
- El contrato coordinado se reconstruyó tomando como referencia el commit motor `9d65933171c79d52a6e780213bc0a9593154b3a7` y el commit Desktop `40d9c71f23872b60f4bbee36d9654af27a0a0019`, sin cherry-pick ni reemplazo de archivos M2.
- Se recuperaron selectivamente `atlas_core/fuente_catalogos.py`, `atlas_core/gestor_viajes.py`, `atlas_core/reporte_viajes.py` y `generar_reporte_viajes.py`, junto con sus pruebas relevantes.

### Contrato e integración actual

- `analizar_guias_masivo.py` acepta `--catalogos`, conserva `--salida`, `--reprocesar`, `--fecha-desde` y `--fecha-hasta`, y resuelve la fuente en orden: ruta explícita, `ATLAS_CATALOGOS_DIR`, o carpeta productiva local únicamente si contiene los siete archivos canónicos. Una ruta ausente/incompleta falla de forma explícita; los `*.example.json` no califican.
- `procesar_carpeta(..., carpeta_catalogos=...)` propaga la fuente a cada `procesar_archivo` sin alterar la creación/reutilización del `ProveedorOCR`. La recuperación geométrica y el enriquecimiento canónico comparten la misma fuente privada.
- La integración selectiva preserva M1/M2: PaddleOCR continúa como motor principal; el proveedor se crea una sola vez por lote; GPU/CPU/fallback permanecen sin cambios.

### Validación

- Suite completa: **501 → 556 passed**.
- Prueba CLI aislada de una sola guía: PaddleOCR `device=gpu`, catálogos válidos, 1 procesada, 0 errores y salida CSV correcta.
- Sanity check del generador restaurado: reporte completo de una guía con `viajes.csv`, `documentos_sin_transporte.csv`, `clientes_no_reconocidos.csv`, `resumen_viajes.md` y `manifest_reporte_viajes.json`, sin modificar el reporte operativo de 574 viajes.
- Prueba manual end-to-end confirmada por el usuario en Atlas Viajes 1.4.3: guía `464511` → transporte `0000352449`, fecha `10-08-2026`, cliente `ARMACERO MATCO SA`, chofer `RODRIGO NAHUELÑIR`; viaje visible en UI, estado OK.

### Continuidad

El próximo frente Desktop es **RECUPERACIÓN UX HISTÓRICA**, no cambios del motor. Antes de reconstruir cualquier elemento, consultar `G:\Mi unidad\BACKUP_PRE_FORMATEO_20260808`.

---

## 2026-08-10 — Bloque M2: runtime Paddle portable + activación en flujo batch

**Rama:** `lector-mvp-guia-nueva` · **HEAD previo:** `3304a4667d605da3dd9768ca246a3272e099c463 feat: integrar paddleocr como proveedor principal`

### Problemas que atacaba este bloque

1. `PaddleOCRProvider` apuntaba a `C:\Users\Jjjc0508\Desktop\Atlas\ocr_eval_gpu_env` — ruta fija de este PC, no portable.
2. `procesar_carpeta`/la CLI no construían ni pasaban ningún `ProveedorOCR` — PaddleOCR estaba integrado como infraestructura pero no activo en el flujo real de lote.

### Archivo nuevo

**`atlas_core/paddle_runtime.py`**: resuelve la ubicación del runtime (`ruta_runtime_paddle()` — prioridad: variable de entorno `ATLAS_PADDLE_RUNTIME` > `%LOCALAPPDATA%\Atlas\runtime\paddleocr`, sin nombre de usuario ni Desktop hardcodeados en el código, solo en la documentación explicando que no se depende de ello). `runtime_valido()` comprueba una marca de versión (`.version`) sin ejecutar nada. `asegurar_runtime_paddle()` crea el venv con `python -m venv`, instala `paddlepaddle-gpu==3.3.1` (índice `cu118`) si hay GPU NVIDIA o `paddlepaddle==3.3.1` si no, más `paddleocr==3.7.0`, y escribe la marca de versión — solo si el runtime no es ya válido. Nunca toca drivers ni CUDA del sistema.

### Archivos modificados

**`atlas_core/ocr_provider.py`**: se eliminaron las constantes `RUTA_VENV_PADDLE`/`RUTA_PYTHON_PADDLE` (apuntaban a `ocr_eval_gpu_env`). `PaddleOCRProvider` gana un parámetro `ruta_python` opcional (override para tests/uso avanzado); sin él, `_asegurar_proceso()` resuelve la ruta vía `asegurar_runtime_paddle()` en el momento de arrancar el proceso, no al construir el objeto. `crear_proveedor_ocr()` ahora también `print()`-ea (además de loguear) qué proveedor y dispositivo quedó activo, o por qué cayó a EasyOCR — visible en la CLI aunque no haya logging configurado.

**`atlas_core/procesamiento_masivo.py`**: `procesar_carpeta` gana un parámetro `proveedor`. Nueva lógica de `ejecutar()`: si se entrega `lector_ocr` explícito, camino EasyOCR directo sin cambios (compatibilidad); si no, se construye **un solo** proveedor vía `crear_proveedor_ocr()` (o se reutiliza el `proveedor` explícito recibido) para todo el lote, pasado a cada `procesar_archivo(..., proveedor=...)`. El import de `crear_lector_ocr` se conserva sin usar en el cuerpo del módulo, solo para no romper tests existentes que lo monkeypatchean.

**Sin cambios:** `procesar_archivo` (ya aceptaba `proveedor` desde M1), focal de fecha/transporte (ya usan el proveedor activo desde M1 — este bloque solo confirma que efectivamente comparten la misma instancia, no crean otra), regex de `extraer_fecha`, F1, guarda documental.

### Tests

- `tests/test_paddle_runtime.py` (11 nuevos): resolución de ruta con `LOCALAPPDATA` sin usuario hardcodeado, override por variable de entorno, fallback a `Path.home()`; `runtime_valido()` en sus tres casos; `asegurar_runtime_paddle()` no reinstala si ya es válido, instala build GPU si hay NVIDIA, instala build CPU si no, devuelve `None` si la instalación falla — todo con `subprocess.run` mockeado, ninguna instalación real; verificación de que el módulo no menciona `ocr_eval_gpu_env` ni la ruta del usuario.
- `tests/test_ocr_provider.py` (+7 respecto a M1): selección de dispositivo GPU/CPU de `PaddleOCRProvider` (y que no consulta GPU si el dispositivo viene explícito); mensajes visibles en consola tanto en éxito (`print` con el device) como en fallback a EasyOCR; el test de "venv no existe" de M1 se separó en dos (`asegurar_runtime_paddle` devuelve `None` vs. el `python.exe` resuelto no existe en disco) para reflejar el nuevo mecanismo de resolución; verificación de ausencia de `ocr_eval_gpu_env`/usuario hardcodeado.
- `tests/test_procesamiento_masivo.py`: `test_crea_lector_una_vez_y_lo_reutiliza` → reemplazado por `test_procesar_carpeta_crea_proveedor_una_vez_y_lo_reutiliza` (comportamiento intencionalmente distinto: el default ahora es el proveedor, no `crear_lector_ocr`); `test_lector_inyectado_no_crea_otro` → renombrado `test_lector_inyectado_no_crea_proveedor` (mismo comportamiento, nueva aserción); `test_proveedor_inyectado_se_reutiliza_sin_crear_otro` nuevo.
- **Importante:** un intento inicial de correr `tests/test_ocr_provider.py` antes de terminar de mockear todo disparó una instalación real accidental (creó un venv parcial en `%LOCALAPPDATA%\Atlas\runtime\paddleocr`) — se detectó, se abortó el proceso y se borró el venv parcial antes de continuar. Se agregó `_prohibir_bootstrap_real()` en los tests: cualquier llamada real a `asegurar_runtime_paddle()` no mockeada falla ruidosamente en vez de instalar algo de verdad.

### Validación

- Tests específicos: 19 nuevos, todos verdes (con timeout de seguridad en cada corrida, por precaución tras el incidente anterior).
- Suite completa: `482 → 501 passed`.
- **Bootstrap real (no mockeado):** `asegurar_runtime_paddle()` ejecutado de verdad — creó el venv, instaló `paddlepaddle-gpu==3.3.1` (GPU detectada) y `paddleocr==3.7.0` en `C:\Users\Jjjc0508\AppData\Local\Atlas\runtime\paddleocr` en 209.4 s. `runtime_valido()` confirmó `True` después.
- **Batch corto real (CLI real, `analizar_guias_masivo.py`, 4 imágenes reales):** `[Atlas OCR] Proveedor activo: PaddleOCR (device=gpu)` impreso **una sola vez** (no por imagen) — confirma un solo proveedor por ejecución, GPU seleccionada automáticamente, sin fallback silencioso. 4/4 procesados, 0 errores. Resultados verificados contra lo ya conocido: número de guía y fecha correctos en las 4 imágenes.
- Primera corrida: 190.5 s (47.6 s/imagen). Segunda corrida (mismo lote, runtime ya "tibio"): 42.0 s (10.5 s/imagen) — confirma que la primera fue sobrecarga de arranque (antivirus/caché), no un problema de la lógica.
- No se re-ejecutaron las 30 imágenes — la extracción ya se validó exhaustivamente en M1 sobre el mismo `procesar_archivo`+proveedor; este bloque solo cambiaba la resolución de ruta y la activación en `procesar_carpeta`, ambas ya confirmadas con el batch corto real.
- `grep` sobre los logs y el CSV de esta validación: cero menciones a `ocr_eval_gpu_env`.

### Estado de cierre

`git status` antes de commit: 4 rutas modificadas (`atlas_core/ocr_provider.py`, `atlas_core/procesamiento_masivo.py`, `tests/test_ocr_provider.py`, `tests/test_procesamiento_masivo.py`) + 2 nuevas (`atlas_core/paddle_runtime.py`, `tests/test_paddle_runtime.py`) + bitácoras/handoff. **Sin commit, sin push** — pendiente de revisión.

**Nota fuera de alcance:** se encontró un archivo no rastreado `resumen_procesamiento_desktop.py` en la raíz del repo que este bloque no creó ni modificó — no se tocó, se deja fuera del commit, y se reporta como hallazgo.

---

## 2026-08-10 — Bloque M1: proveedor OCR + compatibilidad de extractores (CERRADO)

**Rama:** `lector-mvp-guia-nueva` · **HEAD previo:** `ddf4309c7bebc80704b733c0517da700666e93b6 feat: agregar recuperacion focal conservadora de fecha`

### Decisiones de cierre

- **PaddleOCR aprobado como motor principal**; `EasyOCRProvider` queda como fallback temporal (automático si Paddle no está disponible, y siempre disponible explícitamente vía `crear_proveedor_ocr("easyocr")`).
- No se ejecutó otro benchmark completo de 30 imágenes en CPU en este cierre — la portabilidad CPU se confirmará después con una prueba corta en el PC de oficina. No bloquea el cierre.
- `IMG-20250930-WA0047.jpg`: el desacuerdo entre `410627` (ground truth) y `410267` (lo que la imagen realmente muestra, según la propia observación del validador original en el Excel) se registra como discrepancia editorial de ground truth pendiente, no como fallo de `decidir_bloques_ocr` ni de Atlas.
- **Riesgo principal pendiente, explícito:** `PaddleOCRProvider` apunta hoy a `RUTA_VENV_PADDLE = C:\Users\Jjjc0508\Desktop\Atlas\ocr_eval_gpu_env` (constante en `atlas_core/ocr_provider.py`) — un venv creado para el bloque de evaluación, no una ruta de despliegue definitiva. El siguiente bloque oficial (**M2**) debe reemplazar esto por un runtime reproducible/portable, no atado a una ruta específica de este equipo.

### Contexto

Bloque de implementación (decisión de migrar a PaddleOCR ya tomada en evaluaciones previas, no se re-evalúa aquí). Objetivo: integrar PaddleOCR detrás de una abstracción, sin romper EasyOCR, resolviendo las dos incompatibilidades ya diagnosticadas (`numero_guia` frágil a adyacencia textual; recuperación focal acoplada a `easyocr.Reader`).

**Hallazgo relevante antes de implementar:** `atlas_core/experimento_numero_guia_contextual.py::decidir_bloques_ocr` (ya usado por `procesar_archivo`) es un mecanismo ancla→marcador→candidato **agnóstico al motor OCR** que ya tolera bloques intermedios entre "GUIA"/"DESPACHO"/"ELECTRONICA". Una prueba directa con los bloques de PaddleOCR (sin cambiar nada) ya recuperaba 29/30 — la "regresión" medida en el bloque de evaluación anterior fue un hueco del arnés de esa evaluación (no invocaba `decidir_bloques_ocr`), no una limitación real de Atlas. Esto simplificó el alcance de M1: no hizo falta escribir un extractor geométrico nuevo para `numero_guia`, solo conectar `decidir_bloques_ocr` al proveedor activo.

### Archivos nuevos

- **`atlas_core/ocr_provider.py`**: contrato `ProveedorOCR` (Protocol): `leer_texto`, `leer_bloques`, `leer_focal`. `EasyOCRProvider` envuelve las funciones existentes de `atlas_core.ocr` sin cambiarlas. `PaddleOCRProvider` ejecuta PaddleOCR en un **proceso aislado** (venv externo `C:\Users\Jjjc0508\Desktop\Atlas\ocr_eval_gpu_env`, el mismo ya validado en el bloque OCR-EVAL GPU — el wheel `paddlepaddle-gpu` corre igual en CPU pasando `device="cpu"`, así que un solo venv basta para ambos casos), comunicándose por un protocolo JSON línea a línea sobre stdin/stdout con un proceso worker persistente (no se recarga el modelo por imagen). `_gpu_nvidia_disponible()` detecta GPU vía `nvidia-smi` sin hardcodear ningún modelo. `crear_proveedor_ocr(preferido="paddleocr")` selecciona el proveedor y cae a `EasyOCRProvider` si Paddle no está disponible (venv ausente, worker no arranca, etc.) — `ProveedorOCRNoDisponible` es la excepción de señalización para ese fallback.
- **`atlas_core/paddleocr_worker.py`**: script standalone (solo stdlib + paddleocr + Pillow/numpy, **cero imports de atlas_core**) que corre bajo el intérprete del venv aislado. Replica el recorte/margen/4-variantes de `_leer_region_focal` (duplicado necesario por el aislamiento de proceso — si el recorte/margen cambia en `atlas_core/ocr.py`, este archivo debe actualizarse a mano, queda documentado en su docstring). Aplica `enable_mkldnn=False` cuando `device="cpu"` (workaround de Fase 0 de OCR-EVAL).

### Archivos modificados

**`atlas_core/procesamiento_masivo.py`:**
- `procesar_archivo` gana un parámetro opcional `proveedor: ProveedorOCR | None = None`. Sin él, el comportamiento es **exactamente el mismo de antes** (EasyOCR directo vía `lector_ocr`) — confirmado por test explícito y por la suite completa sin cambios. Con él, tres closures internas (`_leer_texto`, `_leer_bloques`, `_leer_focal`) enrutan cada llamada de OCR (texto completo, bloques, focal de fecha/transporte) al proveedor en vez de a `leer_texto_imagen`/`leer_bloques_imagen`/`_leer_transporte_focal`/`_leer_fecha_focal` directos.
- Import de `ALLOWLIST_FECHA`/`ALLOWLIST_TRANSPORTE` desde `atlas_core.ocr` para pasarlos explícitamente al proveedor en las llamadas focales (antes vivían implícitos dentro de `_leer_transporte_focal`/`_leer_fecha_focal`).
- **Guarda documental nueva:** `CAMPOS_GUARDA_DOCUMENTAL` (numero_guia, numero_transporte, cliente, obra_destino, chofer, patente_tracto, patente_carro) + `UMBRAL_CAMPOS_FALTANTES_DOCUMENTO_DEGRADADO = 5` + `_documento_degradado(datos, descripcion)`: si ≥5 de esos 8 indicadores (7 campos + descripción) vuelven vacíos a la vez, se suma a `requiere_revision`. Nunca cambia un valor ni descarta una fecha ya encontrada — solo empuja el indicador hacia `REVISAR`.

**Sin cambios:** regex de `extraer_fecha`, F1 (guarda de plausibilidad), F2 (consenso de confianza), extractores lineales/geométricos existentes, contrato `BloqueOCR`, `requirements.txt`, entorno Python principal.

### Tests

- `tests/test_ocr_provider.py` (16 nuevos): contrato `EasyOCRProvider` (delegación a `leer_texto_imagen`/`leer_bloques_imagen`/`_leer_region_focal`, lector creado una sola vez); contrato `PaddleOCRProvider` con proceso mockeado (texto/bloques/focal vía protocolo JSON, error de una imagen no mata el proceso, `ProveedorOCRNoDisponible` si el worker no arranca o el venv no existe); selección de proveedor (`easyocr` explícito nunca toca Paddle; Paddle disponible se usa; Paddle no disponible cae a EasyOCR); detección de GPU sin `nvidia-smi`.
- `tests/test_procesamiento_masivo.py` (8 nuevos): `numero_guia` con etiqueta fragmentada en bloques (caso real de Paddle) recuperado vía proveedor; `numero_guia` sin marcador cercano se abstiene; fecha focal vía proveedor; transporte focal vía proveedor; `_documento_degradado` activa con muchos campos faltantes / no activa con pocos (tests puros); `procesar_archivo` con documento degradado queda `REVISAR`; `procesar_archivo` sin `proveedor` conserva exactamente el comportamiento anterior (ancla de no-regresión).

### Validación

- Tests específicos: 24 nuevos, todos verdes.
- Suite completa: `458 → 482 passed`.
- Validación real: `procesar_archivo(ruta, proveedor=proveedor)` con un `PaddleOCRProvider` **real** (proceso vivo, GPU real, sin mocks) sobre las 30 imágenes:
  - `numero_guia`: **2/30 → 29/30** (el único caso restante, `IMG-20250930-WA0047.jpg`, es la disputa de ground truth ya documentada en el Excel original: "la validación manual anterior indicó guía 410627; la imagen muestra 410267").
  - `fecha`: 27/30 (sin cambio respecto a la evaluación previa).
  - `numero_transporte` 28/30, `cliente` 21/25, `obra_destino` 12/27, `chofer` 15/23, `descripción_material` 24/25, `tipo_carga` 24/29 — todos iguales a la evaluación previa, sin regresiones. (Nota: el primer cálculo de `descripcion_material` en el script de validación dio 0/25 por un comparador equivocado en el script — no en Atlas —, corregido antes de reportar; con el comparador correcto da 24/25, igual que antes.)
  - `IMG-20260512-WA0027.jpg`: `indicador_revision = REVISAR` confirmado.
  - Proveedor real creado: `PaddleOCRProvider` (no cayó a fallback). Tiempo: 90.9 s para 30 imágenes (3.03 s/imagen), consistente con uso real de GPU.
  - Camino CPU: implementado y cubierto por tests (incluye `enable_mkldnn=False`), pero no se re-ejecutó un benchmark completo de 30 imágenes en CPU dentro de este bloque — se apoya en la validación de Fase 0/OCR-EVAL CPU ya hecha sobre el mismo camino de código, que no cambió.

### Estado de cierre

`git status` previo al commit: working tree con 2 rutas modificadas (`atlas_core/procesamiento_masivo.py`, `tests/test_procesamiento_masivo.py`) y 3 rutas nuevas (`atlas_core/ocr_provider.py`, `atlas_core/paddleocr_worker.py`, `tests/test_ocr_provider.py`), más las 3 bitácoras/handoff. **Sin commit, sin push** — pendiente de revisión.

---

## 2026-08-10 — Bloque Fechas F2: recuperación OCR focal de FECHA DE EMISIÓN (cerrado, con gate de confianza)

**Rama:** `lector-mvp-guia-nueva` · **HEAD previo:** `61958f2718452916b4a8d6fc4807903067355c81 feat: agregar plausibilidad temporal a fechas`

### Contexto

Diagnóstico previo (mismo bloque de trabajo) sobre los 16 fallos de fecha de la muestra real concluyó: 0/16 atribuibles a `extraer_fecha`, todos originados en OCR/calidad de imagen; ~11/16 con probabilidad razonable de beneficiarse de una relectura focal (recorte + realce), reutilizando el mismo mecanismo ya en producción para número de transporte.

### Implementación

**`atlas_core/ocr.py`:**
- Extraído `_leer_region_focal(ruta_imagen, caja, lector, allowlist)`: mismo recorte con margen + 4 variantes (original, grises, ampliada 2x LANCZOS, ampliada 2x con contraste) que antes vivía hardcodeado dentro de `_leer_transporte_focal`.
- `_leer_transporte_focal` ahora delega en el helper con `ALLOWLIST_TRANSPORTE = "0123456789OoDdQqIl| .-"` (el mismo string de siempre) — **sin cambio funcional**, confirmado por test que compara ambas rutas byte a byte.
- `_leer_fecha_focal` nuevo, delega en el mismo helper con `ALLOWLIST_FECHA = "0123456789-/ "` — solo dígitos, separadores de fecha y espacio; sin letras de confusión (no se justificaban para este caso).

**`atlas_core/extractor.py`:**
- `_extraer_fecha_geometrico(bloques)` nuevo, mismo patrón que `_extraer_transporte_geometrico`: localiza la etiqueta `FECHA DE EMISION` (tolerante a "FECHA EMISION" / "EMISION" sola por fragmentación de bloques), puntúa candidatos a la derecha/abajo, excluye candidatos más cercanos a una etiqueta rival (`FECHA SALIDA`/`FECHA LLEGADA`/"SALIDA"/"LLEGADA"), y se abstiene (devuelve `{}`) ante ambigüedad (margen 0.06, igual que transporte). Devuelve `{valor, caja, confianza}` — no valida el contenido, solo localiza la zona a recortar.

**`atlas_core/procesamiento_masivo.py`:**
- `_valor_fecha_a_date(valor)` nuevo: convierte un valor ya devuelto por `extraer_fecha` a `date` comparable (soporta DD-MM-YYYY, DD/MM/YYYY, YYYY-MM-DD, YYYY/MM/DD), solo para comparar variantes focales entre sí — no reimplementa ni toca el reconocimiento de `extraer_fecha`.
- `procesar_archivo`: se calcula `fecha_actual = extraer_fecha(textos, ...)` una vez; si ya es distinta de `"No encontrado"` se conserva tal cual y **la ruta focal nunca se ejecuta**. Si es `"No encontrado"`: reutiliza `bloques_guia` si ya se cargó (o lo carga), llama `_extraer_fecha_geometrico`; si no hay caja, se abstiene; si hay caja, ejecuta `_leer_fecha_focal` (4 variantes) y corre `extraer_fecha` (sin tocar sus regex) sobre el texto de cada variante — F1 (guarda de plausibilidad) se aplica automáticamente en cada una de esas llamadas, sin código adicional. Cualquier recuperación focal marca `fecha_recuperada_focal = True`, que se suma a `requiere_revision` (mismo criterio que las demás recuperaciones geométricas/focales del archivo).

**Sin cambios:** regex de `extraer_fecha`, `validar_fecha`, `_clasificar_contexto_fecha`, criterio de selección `min()`, guarda de plausibilidad de F1 (se reutiliza tal cual).

### Auditoría de consenso (F2.1/F2.2, previa al cierre)

La primera versión del consenso agrupaba resultados válidos por fecha comparable y aceptaba con solo `len(votos) >= 2`, sin mirar confianza. Validación real sobre las 30 guías con esa versión: 14/30 → 15/30, pero **1 de las 2 convergencias fue un valor incorrecto** (`IMG-20250930-WA0046.jpg`: 3 de 4 variantes —`original`, `grises`, `ampliada_2x`— coincidieron en `10-09-2025`, dígito de día mal leído; real: `2025-09-30`).

Se auditó el campo `confianza` que `_leer_region_focal` ya calculaba pero el consenso ignoraba (mínimo de las confianzas de los segmentos detectados por variante, metodología ya existente en el código, no inventada para esta auditoría), sobre las 7 imágenes reales donde el localizador geométrico encontró caja:
- Votos del consenso **incorrecto** (`WA0046`): confianzas 0.818 / 0.825 / 0.466 → mínima 0.466.
- Votos del único consenso **correcto** (`WA0047`, `30-09-2025`): confianzas 0.953 / 0.981 → mínima 0.953.
- Margen amplio entre ambos (0.47–0.95): cualquier umbral en ese rango separa los dos casos observados.

### Cambio de cierre: gate de confianza

- Constante nueva `CONFIANZA_MINIMA_FECHA_FOCAL = 0.70`, documentada junto a las constantes de F1, con nota explícita de que está validada sobre muestra limitada y no prueba suficiencia general del OCR.
- El agrupamiento por fecha comparable ahora guarda `(valor, confianza)` por voto. `coincidencias` solo incluye un grupo de fecha si `len(votos) >= 2` **y** `all(confianza >= CONFIANZA_MINIMA_FECHA_FOCAL for cada voto del grupo)` — un voto con confianza `None` (sin segmentos detectados) no puede satisfacer el umbral, así que nunca aporta a un consenso aceptado. Se acepta solo si exactamente un grupo de fecha cumple ambas condiciones.
- Nada más del flujo cambió: no se tocaron regex de `extraer_fecha`, F1, ni cuándo se dispara el focal.

### Tests

- `tests/test_extraer_datos.py` (7 nuevos, del F2 original): candidato a la derecha, candidato debajo, etiqueta ausente, sin candidato, dos candidatos equivalentes → abstención, prioriza EMISIÓN sobre SALIDA cercana, rechaza candidato más cercano a SALIDA que a EMISIÓN.
- `tests/test_ocr.py` (3 nuevos, del F2 original): `_leer_transporte_focal` conserva su allowlist exacto sin cambios; el helper genérico reproduce byte a byte el comportamiento de transporte; `_leer_fecha_focal` usa el allowlist mínimo (incluye `/`, sin letras).
- `tests/test_procesamiento_masivo.py` (7 nuevos en total): fecha global válida → focal nunca se dispara; 2 votos con ambas confianzas ≥0.70 → acepta; **3 votos coincidentes donde uno tiene confianza <0.70 (reproduce `WA0046`) → abstiene**; 2 votos con confianza exactamente 0.70 → acepta (límite inclusive); variantes discordantes → sigue "No encontrado"; candidato focal con año absurdo → descartado por F1 automáticamente; sin caja geométrica → se abstiene sin llamar al focal.
- 2 tests preexistentes (no relacionados con fecha) ajustaron su dato de entrada: usaban `leer_texto_imagen` → `[]`, lo que ahora también deja la fecha en "No encontrado" y dispara la nueva ruta focal — se les agregó una fecha global válida en el texto simulado para preservar su intención original (probar preservación de valores lineales, no fecha).

### Validación final

- Tests específicos del bloque: 7 (procesamiento_masivo) + 7 (extractor) + 3 (ocr) = 17 nuevos en total, todos verdes.
- Suite completa: `441 → 458 passed`.
- Validación real sobre las 30 guías, **OCR ejecutado de nuevo** (dos veces: antes y después del gate de confianza, ninguna reutilizó corpus anterior), llamando a `procesar_archivo` de producción real:
  - Exactitud: **14/30 → 15/30**.
  - Recuperado: `IMG-20250930-WA0047.jpg` → `30-09-2025` (correcto).
  - `IMG-20250930-WA0046.jpg`: ahora `"No encontrado"` (antes era el valor incorrecto `10-09-2025`) — el gate de confianza lo descartó correctamente.
  - **0 recuperaciones incorrectas nuevas. 0 degradaciones de los 14 aciertos previos.**
  - Focal disparado: 7/16 fallos previos (sin cambio, el gate no afecta cuándo se dispara). Convergieron: 1 (antes 2). Se abstuvieron: 6 (antes 5).
  - Tiempo total de la corrida final: 1385.5 s (~23.1 min) para 30 imágenes, pipeline completo de `procesar_archivo` (no solo fecha).

### Estado de cierre

`git status` previo al commit: working tree con 6 rutas de código/tests modificadas (`atlas_core/extractor.py`, `atlas_core/ocr.py`, `atlas_core/procesamiento_masivo.py`, `tests/test_extraer_datos.py`, `tests/test_ocr.py`, `tests/test_procesamiento_masivo.py`) más las 3 bitácoras/handoff.

---

## 2026-08-10 — Bloque Fechas F1: guarda de plausibilidad temporal

**Rama:** `lector-mvp-guia-nueva` · **HEAD previo:** `cab3837 feat: integrar matching difuso conservador de chofer`

### Contexto

Diagnóstico previo (mismo bloque de trabajo) midió el comportamiento real de `extraer_fecha` sobre la muestra histórica de 30 guías (`Atlas\datos_privados\muestra_fechas_30`, ground truth en `Atlas\datos_privados\ground_truth\validacion_atlas_30_guias_v1.xlsx`), ejecutando OCR real (EasyOCR) + `extraer_fecha` sin modificar código: **14/30 exactas**. Búsqueda del texto real en el OCR crudo de los 16 fallos confirmó que en **0 de 16** casos el extractor perdió un candidato correcto disponible — los 16 fallos nacen antes del extractor, en el OCR/calidad de imagen. De esos 16, 3 devolvían un valor con año calendario-imposible en la práctica (`7029`, `7025`, `1024`), aceptado porque `extraer_fecha` no acota el año cuando no se entrega rango explícito.

### Implementación

**`atlas_core/procesamiento_masivo.py`:**
- Constantes nuevas: `ANIO_MINIMO_PLAUSIBLE = 2015`, `ANIO_MAXIMO_PLAUSIBLE = 2035`, `FECHA_MINIMA_PLAUSIBLE`, `FECHA_MAXIMA_PLAUSIBLE`. Centralizadas como constantes de módulo, no hardcodeadas dentro de los regex de `extraer_fecha`.
- Función nueva `_limites_temporales_efectivos(fecha_desde, fecha_hasta) -> tuple[date, date]`: si un límite viene `None`, se completa con la guarda por defecto; si viene explícito, se usa tal cual. **Un límite explícito prevalece por completo sobre el default — no se intersecta con él** (un `fecha_desde`/`fecha_hasta` explícito más amplio que 2015–2035 sigue aceptando años fuera de ese rango).
- `extraer_fecha` calcula `fecha_desde_efectiva`/`fecha_hasta_efectiva` una sola vez al inicio y las usa en ambas pasadas (estricta y tolerante), reemplazando los chequeos `is not None` dispersos por una sola comparación contra los límites ya resueltos.
- Sin cambios en: regex de reconocimiento, `_clasificar_contexto_fecha` (prioridad EMISIÓN>SALIDA>LLEGADA), `_normalizaciones_fecha_unicas`, criterio de selección `min()`, contrato de retorno (sigue devolviendo el valor original, no ISO).

**`tests/test_procesamiento_masivo.py`:**
- Actualizados intencionalmente (comportamiento cambiado a propósito, no regresión):
  - `test_fecha_sin_rango_conserva_comportamiento_de_etapa_uno` → renombrado `test_fecha_sin_rango_descarta_anio_operacionalmente_absurdo`; `extraer_fecha(["FECHA DE EMISIÓN 01-07-7025"])` pasa de esperar `"01-07-7025"` a esperar `"No encontrado"`.
  - `test_procesar_archivo_sin_rango_conserva_compatibilidad` → renombrado `test_procesar_archivo_sin_rango_descarta_anio_operacionalmente_absurdo`; mismo cambio de expectativa vía `procesar_archivo`.
- Tests nuevos (8):
  - `test_fecha_sin_rango_acepta_anio_normal_de_la_muestra` — fecha típica 2025-2026 sin rango sigue aceptándose.
  - `test_fecha_sin_rango_limite_inferior_plausible_es_aceptado` — año 2015 exacto (límite inferior) se acepta.
  - `test_fecha_sin_rango_limite_superior_plausible_es_aceptado` — año 2035 exacto (límite superior) se acepta.
  - `test_fecha_sin_rango_anio_fuera_del_rango_plausible_se_descarta` (parametrizado: 2014 y 2036) — un año fuera del rango por defecto se descarta.
  - `test_fecha_con_rango_explicito_mas_amplio_que_el_default_prevalece` — rango explícito 1990–2099 acepta año 2040, fuera del default; confirma que el explícito no se intersecta con el default.
  - `test_fecha_con_rango_explicito_mas_estrecho_que_el_default_prevalece` — rango explícito más angosto que el default sigue mandando.
  - `test_fecha_sin_rango_candidato_absurdo_y_plausible_elige_el_plausible` — dos candidatos en el mismo texto, uno con año absurdo y otro plausible; se elige el plausible.

### Validación

- `python -m pytest -q` dirigido a los tests del bloque: **12 passed**.
- `python -m pytest -q` suite completa: **433 → 441 passed** (8 tests nuevos, 0 tests rotos fuera de los 2 actualizados intencionalmente).
- Validación sobre las 30 guías reales: se reutilizó el texto OCR ya capturado en la corrida de diagnóstico (mismas imágenes, mismo motor EasyOCR, sin recalcular OCR) y se re-ejecutó únicamente `extraer_fecha` con el código nuevo:
  - Exactitud: **14/30 antes → 14/30 después** (sin cambio).
  - Degradaciones (acierto que pasa a fallo): **0**.
  - Casos que cambiaron de fecha falsa silenciosa a `"No encontrado"`: **3** — `IMG-20250625-WA0039.jpg` (`15-06-7029`→`No encontrado`), `IMG-20250626-WA0019.jpg` (`28-06-7025`→`No encontrado`), `IMG-20250701-WA0007.jpg` (`01-07-1024`→`No encontrado`).
  - Los 27 resultados restantes (14 aciertos + 13 fallas por OCR degradado) quedaron valor por valor idénticos.

### Estado de cierre

`git status`: `lector-mvp-guia-nueva`, sincronizado con `origin`, working tree con exactamente 5 rutas modificadas/nuevas: `atlas_core/procesamiento_masivo.py`, `tests/test_procesamiento_masivo.py`, `docs/BITACORA_EJECUTIVA.md`, `docs/BITACORA_TECNICA_CRONOLOGICA.md`, `docs/HANDOFF_ATLAS.md`.
