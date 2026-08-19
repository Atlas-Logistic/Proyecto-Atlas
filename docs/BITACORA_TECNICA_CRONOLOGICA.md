# Bitácora Técnica Cronológica — Proyecto Atlas

Registro técnico, en orden cronológico, de cambios de código sobre el lector de guías. Un bloque por entrada, con archivos modificados, decisión de diseño y validación.

---

## 2026-08-19 — MOTOR DE EVIDENCIA FASE 2: entidades/clientes/obras + verificación externa + Incidencias Documentales

**Rama motor:** `lector-mvp-guia-nueva` · Sin commit funcional todavía (código nuevo, no aplicado a Drive -- pendiente de revisión de Javier, ver FASE 17 de la instrucción de este bloque).

### FASE 0 -- checkpoint

`git status`/`git log` en Motor y Desktop: `ab7e16f`/`a55a726`, `local=remoto`, `0/0`, working trees limpios -- coincide exactamente con lo reportado al cierre del bloque anterior. Drive verificado: JD8659 CARRO/CONFIRMADO/ACTIVO, 13 decisiones pendientes, 2 aplicaciones reales con `patente_canonica=JD8659` (464264, 464265) en el ledger -- sin discrepancia. Se buscó la frase "15 revisiones antes → 6" en las 3 bitácoras: no existe -- la única mención real dice "15 → 13", correcta. Sin sorpresas -- se continuó.

### FASE 1 -- capa genérica, reutilización sin refactor

`atlas_core/motor_evidencia.py` (nuevo): extrae el patrón OBSERVACIÓN→CANDIDATOS→EVIDENCIAS→CONTRADICCIONES→CONFIRMACIONES→RESULTADO→EXPLICACIÓN ya validado en producción para vehículos, como dataclasses reutilizables (`CandidatoEvidencia`, `ResultadoEvidencia`) y una jerarquía de precedencia por niveles (`NIVEL_CONFIRMACION_HUMANA` > `NIVEL_EXTERNO_OFICIAL` > `NIVEL_EXTERNO_CORPORATIVO` > `NIVEL_DOCUMENTAL_INDEPENDIENTE` > `NIVEL_EXTERNO_DIRECTORIO` > `NIVEL_EXTERNO_AUXILIAR` > `NIVEL_DOCUMENTAL_DEBIL`), más `elegir_mejor_candidato`/`hay_empate_en_el_tope` (nunca elige arbitrariamente). Vocabulario de resultado ampliado a 5 estados (`RESUELTO_AUTOMATICAMENTE`, `SUGERENCIA_HUMANA`, `CONTRADICCION_DOCUMENTAL`, `ALTA_NUEVA`, `ABSTENCION_REAL`) -- el motor de vehículos (3 estados) NO se reescribió para adoptar este vocabulario (evitar refactor de una pieza ya validada en producción); la reutilización es de patrón, no de código forzado a compartirse.

### Verificación externa

`atlas_core/verificacion_externa.py` (nuevo): `EvidenciaExterna` (fuente, tipo_fuente, url, fecha_consulta, campos_corroborados, contradicciones -- trazabilidad completa, nunca contenido web masivo), `ProveedorVerificacionEntidades` (Protocol, nunca acoplado a un buscador concreto), `ProveedorVerificacionFijo` (fixtures/caché, sin red -- el único proveedor que corre hoy), `CacheVerificacionExterna`. Auditado el entorno real: HTTP de salida SÍ funciona desde Python (`urllib.request` contra `api.github.com`, 200 OK), pero no hay ningún proveedor de búsqueda/registro empresarial configurado (sin API key/servicio contratado) -- componente real faltante para producción autónoma, reportado explícitamente, no fingido.

**2 evidencias reales, no simuladas**, obtenidas por el agente con sus propias herramientas de búsqueda (fuera del proceso Python) y guardadas en `tests/fixtures_verificacion_externa.py`: SIGRO (directorio Mercantil.com: razón social "Empresa Constructora Sigro S.A.", RUT 89.037.500-6, dirección Las Condes; sitio corporativo `web.sigro.cl`: "SIGRO S.A.", dirección Vitacura) y Supermercado Señor de los Milagros (búsqueda real en Mejillones -- 0 resultados; hallazgo colateral real: dos supermercados confirmados en la misma calle, Av. Almirante Latorre, con OTRO nombre -- documentado como referencia, nunca usado para forzar una conclusión).

### Confirmaciones independientes -- aprendizaje operacional

`atlas_core/evidencia_entidades.py` (nuevo, almacén aditivo -- `catalogos_privados/evidencia_entidades.json`, NUNCA una migración de `clientes.json`/`obras_destinos.json`, cuyos dataclasses validan el conjunto EXACTO de campos): `ConfirmacionIdentidad`, `AlmacenEvidenciaEntidades.registrar_confirmacion`/`confirmaciones_para` (idempotente por `confirmacion_id` determinista), `transportes_independientes()` (mismo principio "repetición no equivale a independencia" ya validado para vehículos -- cuenta transportes distintos, nunca documentos). `UMBRAL_CONFIRMACIONES_PARA_CONOCIMIENTO_FUERTE = 2`, una única constante nombrada, nunca repetida como número mágico.

### Incidencias Documentales

`atlas_core/incidencias_documentales.py` (nuevo): `IncidenciaDocumental`, `AlmacenIncidenciasDocumentales.registrar` (idempotente; rechaza explícitamente `MOTIVO_PROBLEMA_LECTURA`/`MOTIVO_CALIDAD_DOCUMENTAL_O_IMAGEN` como `tipo_incidencia` -- la frontera OCR/calidad != incidencia documental está protegida en el propio código, no sólo en la documentación). Taxonomía inicial pequeña y extensible (`PATENTE_DOCUMENTAL_INCORRECTA`, `IDENTIDAD_CLIENTE_INCONSISTENTE`, `RUT_NO_CORRESPONDE_A_RAZON_SOCIAL`, `DIRECCION_NO_CORRESPONDE_A_ENTIDAD`, `OBRA_DOCUMENTAL_INCONSISTENTE`, `COMUNA_DOCUMENTAL_INCORRECTA`, `TRANSPORTISTA_DOCUMENTAL_INCORRECTO`, `HORA_DOCUMENTAL_INCONSISTENTE`). Estados `DETECTADA`/`CONFIRMADA`/`DESCARTADA`. Sin ningún mecanismo de bloqueo -- verificado también por test (`test_incidencias_documentales_no_tiene_ningun_mecanismo_de_bloqueo`).

### Motor de Evidencia -- Clientes

`atlas_core/motor_evidencia_clientes.py` (nuevo): `clasificar_rut_documental` distingue `RUT_AUSENTE`/`RUT_INVALIDO`/`RUT_VALIDADO`/`RUT_CANONICO`. `evaluar_evidencia_cliente` se invoca DESPUÉS del paso determinista ya existente (`_identidad_cliente_por_rut`, RUT exacto contra `clientes.json` `CONFIRMADO`/`ACTIVO`) -- nunca lo reemplaza. Árbol de decisión: RUT canónico sin contradicción de texto -> `RESUELTO_AUTOMATICAMENTE`; RUT canónico CON contradicción y sin confirmaciones acumuladas -> `CONTRADICCION_DOCUMENTAL` (CASO B del bloque: "PPP CONSTRUCCIONES" con el RUT de EBEMA sugiere EBEMA, nunca registra PPP); RUT canónico CON contradicción y >=2 confirmaciones independientes de esa misma relación -> `RESUELTO_AUTOMATICAMENTE` (CASO C); fuente externa oficial/corporativa -> `CONTRADICCION_DOCUMENTAL`; fuente externa débil o confirmación única -> `SUGERENCIA_HUMANA`; sin ningún candidato ni evidencia en contra -> `ALTA_NUEVA`; RUT inválido/ausente y sin nada más -> `ABSTENCION_REAL`. Empate real en el nivel más alto -> `SUGERENCIA_HUMANA`, nunca una elección arbitraria.

**No se conectó** a `aplicar_decision_obra`/`detectar_decisiones_documento` en este bloque (deliberado -- "no aplicar todavía el nuevo motor", instrucción explícita FASE 17): el `CONFIRMAR_ALIAS` real todavía no registra `ConfirmacionIdentidad`; esa integración queda para el bloque de aplicación controlada, después de la revisión de Javier.

### Motor de Evidencia -- Obras (caso SIGRO)

`atlas_core/motor_evidencia_obras.py` (nuevo): `coincide_salvo_sufijo_societario` (calibrada, sufijos `SA`/`LTDA`/`SPA`/`EIRL`/`LIMITADA`, nunca decide identidad sola -- sólo sugiere). Deliberadamente NO se modificó `normalizar_nombre_obra` (`atlas_core.catalogo_obras_destinos`, ya validada en producción para deduplicar el catálogo real) -- ensancharla para ignorar sufijos societarios habría arriesgado fusionar en silencio dos obras legalmente distintas; se agregó una función nueva y acotada en su lugar, mismo principio que `_diferencia_ocr_segura` para vehículos. `evaluar_evidencia_obra`: coincidencia por sufijo contra obras confirmadas del mismo cliente -> `SUGERENCIA_HUMANA`; + evidencia externa oficial/corporativa -> `CONTRADICCION_DOCUMENTAL`; sin nada -> `ALTA_NUEVA`. Ninguna fuente disponible para obras alcanza hoy `RESUELTO_AUTOMATICAMENTE` sin confirmación humana estructural -- misma decisión de producto ya tomada para VP6521→VP8521 en el bloque anterior.

### FASE 14 -- validación contra el dataset real completo (sólo lectura)

Copiado a TEMP (`clientes.json`, `obras_destinos.json`, `destinos_maestros.json`, `analisis_completo_guias.csv`, `decisiones_pendientes.json`); nunca escrito de vuelta. **Hallazgo real de alcance:** el CSV consolidado NO retiene el RUT documental por guía (sólo el nombre de cliente ya resuelto o el texto tal cual) -- el RUT crudo sólo vive en la extracción OCR original de cada documento, fuera de esta pasada (evitar lectura/OCR masivo, fuera de alcance). Por eso la validación de clientes contra el dataset completo usó una comparación nombre-only (más débil, sólo para priorizar candidatos a revisar), no el motor RUT-based completo -- reportado con honestidad, no maquillado.

**Clientes:** 14 nombres documentales únicos, 13 ya exactos, 1 candidato real (`TORRES OCARANEA LTDA`, variante de `TORRES OCARANZA LTDA`, ya `CONFIRMADO`/`ACTIVO` con el alias `IORRSS OCARANZA` -- este bloque no lo agrega, sólo lo señala). **Obras:** 28 valores únicos, 15 ya exactos, 12 `ALTA_NUEVA` sin ninguna duda, 1 `SUGERENCIA_HUMANA` -- exactamente el caso SIGRO, encontrado por el motor sin indicarle dónde buscar (nada hardcodeado).

### Tests

55 tests nuevos, 0 regresiones: `test_motor_evidencia.py` (8, capa genérica), `test_verificacion_externa.py` (6), `test_evidencia_entidades.py` (7), `test_incidencias_documentales.py` (7, incluida la frontera OCR/calidad protegida por código), `test_motor_evidencia_clientes.py` (16, incluye CASO B/C completos y los 2 casos reales SIGRO/RUT-exacto), `test_motor_evidencia_obras.py` (9, SIGRO real con evidencia de directorio y de sitio corporativo), `test_motor_evidencia_integracion.py` (2, cierre del ciclo motor->incidencia + ausencia de bloqueo). Suite completa: **1333 → 1388 passed, 0 failed.**

**Drive:** no modificado (0 escrituras). **Catálogos reales:** sin cambios. **Decisiones reales:** ninguna aplicada. **Git:** sin commit funcional -- código nuevo en working tree, pendiente de la revisión única de Javier antes de conectar el motor al flujo en vivo.

---

## 2026-08-19 — PUESTA EN PRODUCCIÓN CONTROLADA del Motor de Evidencia de Vehículos

**Rama motor:** `lector-mvp-guia-nueva`, commits `335c59c` (motor de evidencia) + `87d49b2` (fix candidatos congelados) · **Rama Desktop:** `fix-desktop-data-root-drag-drop`, commit `a55a726` · Ambos publicados en `origin`.

### FASE 0 — checkpoint y publicación

Working trees verificados byte a byte contra lo reportado al cierre del bloque anterior (sólo los archivos ya descritos, nada ajeno). Motor `1332 passed`, Desktop `221 passed` antes de comitear. Commit + push normales en ambos repos; `git fetch` posterior confirmó `local=remoto`, `ahead/behind 0/0`, working trees limpios.

### FASE 1 — JD8659 canónica en Drive real

Backup escoped (`respaldos/REGISTRO_JD8659_ROLLBACK_PRE_APLICACION_20260819_163138/`, manifiesto SHA-256) + dry-run en TEMP contra una copia exacta del catálogo real (20→21 vehículos, JE8659/VP8521 preservados byte a byte) antes de tocar Drive. Escritura real vía `confirmar_vehiculo(patente="JD8659", tipo=CARRO, rut_chofer_asociado=<RUT normalizado de Carlos Simón>, fuente_decision="CONFIRMACION_CHOFER_CARLOS_SIMON_2026-08-19", actor="JAVIER_MBT")`. Verificado post-escritura: 20→21, ninguna patente previa cambió de estado.

### Bug real encontrado y corregido: candidatos congelados

Al reconciliar la bandeja real en TEMP tras registrar JD8659, `reconciliar_bandeja_decisiones` NO hizo aparecer JD8659 como candidata en 464264/464265. Causa raíz: `enriquecer_decisiones_vehiculo` sólo evaluaba una decisión si ésta *todavía no traía* `candidatos` -- las 4 decisiones de vehículo ya tenían candidatos persistidos desde una corrida anterior del mecanismo viejo (antes de este bloque), así que nunca se les daba la oportunidad de reevaluarse con el catálogo nuevo. Confirmado que `decision_id` (`_decision_id`) no depende de `candidatos` -- recalcular es seguro, nunca resucita una decisión ya cerrada en el ledger.

**Fix (`atlas_core/decisiones_pendientes.py`):** `enriquecer_decisiones_vehiculo` ahora siempre reevalúa cada `VEHICULO_DESCONOCIDO` con `evaluar_evidencia_patente`, y reconstruye `acciones_permitidas` desde una base limpia en cada corrida (evita acumular duplicados; permite que una candidata que deja de ser válida también retire su acción). Idempotente por construcción. Test nuevo `test_enriquecer_decisiones_vehiculo_refresca_candidatos_ya_presentes` reproduce el escenario real exacto (candidato documental congelado → aparece confirmación humana nueva → debe reflejarse en la siguiente corrida). `_confirmar` (helper de test) ganó `rut_chofer_asociado` opcional. Suite completa tras el fix: `1333 passed, 0 failed`.

### FASE 2 — VP6521→VP8521: ¿el motor general ya tiene evidencia suficiente?

Auditado programáticamente contra el dataset real: RUT de Simón coincide, tipo compatible (TRACTO), VP8521 confirmada/activa, **2 transportes independientes** (`0000351135` con SODIMAC, `0000352376` con EBEMA/PRODALAM -- dos mandantes distintos, no el mismo cliente repitiendo), sin ningún tracto rival para ese RUT, sin confirmación humana directamente asociada (a diferencia de JD8659, VP8521 se confirmó en un bloque anterior sin `rut_chofer_asociado`).

**Decisión de producto, explícita y razonada:** no se bajó el umbral. Un patrón general "≥N transportes independientes + tipo compatible + sin rival ⇒ `RESUELTO_AUTOMATICAMENTE`" seguiría siendo, en el fondo, "más documentos que coinciden = más certeza" -- exactamente el razonamiento que este bloque existe para evitar (`JE8659` también tenía evidencia documental repetida y era la respuesta equivocada). La línea que separa `RESUELTO_AUTOMATICAMENTE` de `SUGERENCIA_HUMANA` se mantiene en la confirmación humana estructural, no en el conteo de corroboraciones documentales, sin importar cuán fuertes. **La arquitectura ya producía la clasificación correcta -- no se modificó.** VP6521→VP8521 queda como `SUGERENCIA_HUMANA` fuerte (nivel `DOCUMENTAL_INDEPENDIENTE`, candidata única, cero conflictos salvo `OCR_ACTUAL_DIFIERE`), resoluble por Javier con un clic (`USAR_PATENTE_EXISTENTE`, ya wireado de punta a punta).

### FASE 3/4 — clasificación completa de las 15 decisiones reales y medición

Ver reporte final para la matriz completa. Resumen: **A (RESUELTO_AUTOMATICAMENTE) = 2** (464264, 464265-rampla); **B (SUGERENCIA_HUMANA) = 2** (464265-tracto VP6521→VP8521; 464493-obra, probable duplicado de una obra ya confirmada con otro sufijo corporativo); **C (ALTA_ADMINISTRATIVA) = 9** (vehículos/obras genuinamente nuevos, sin ninguna evidencia en contra); **D (INCIDENCIA_DOCUMENTAL) = 1** (464036 Ortiz -- diferencia de 2 dígitos, no 1, y Javier ya había señalado independientemente que es un error documental del mandante en la auditoría previa (`fb8ba95`); no se aplicó unilateralmente en este bloque, sin una confirmación fresca); **E (ABSTENCION_REAL) = 1** (464170-obra "Supermercado Señor de los Milagros" -- discrepancia sin resolver con la memoria de Javier, sin evidencia documental en ningún sentido).

### FASE 5 — aplicación real, sólo lo inequívoco

Backup adicional (`respaldos/PUESTA_EN_PRODUCCION_MOTOR_VEHICULOS_ROLLBACK_PRE_APLICACION_20260819_164133/`) antes de escribir. `reconciliar_bandeja_decisiones(raiz_atlas=Drive real)`: 15 conservadas, 15 publicadas, candidatos refrescados (JD8659 visible por primera vez). Aplicadas por CLI real (`aplicar_decision_pendiente.py`, el mismo binario que invoca Desktop): `SELECCIONAR_OTRA_PATENTE --patente-elegida JD8659` para 464264 y 464265 (rampla) -- ambas con 2 candidatos persistidos (JD8659 nivel `CONFIRMACION_HUMANA`, JE8659 nivel `DOCUMENTAL_INDEPENDIENTE`), por lo que `USAR_PATENTE_EXISTENTE` (que exige exactamente 1 candidato) no aplicaba. Verificado: `analisis_completo_guias.csv` byte a byte sin cambios en las columnas de patente (JD6659/JD0659 siguen ahí, tal como los leyó OCR); `decisiones_pendientes.json` 15→13; `decisiones_aplicadas.json` 13→15, cada entrada con `candidatos_previos` completo (evidencias, conflictos, `razon_legible`) para auditoría permanente. No se aplicó ninguna de las 13 restantes -- ninguna era inequívoca sin intervención de Javier, y `REGISTRAR` de vehículos nuevos quedó explícitamente fuera de alcance de este bloque por instrucción. `estado_operacion.json`/`reportes/actual` no requirieron regeneración (apuntan por ruta, no por conteo; el ledger de vehículo es un consumidor futuro separado del reporte, scope ya delimitado en el bloque anterior). ORS/Onelogis: 0 llamadas.

---

## 2026-08-19 — MOTOR DE EVIDENCIA DE VEHÍCULOS: razonamiento determinista (no IA) para VEHICULO_DESCONOCIDO

**Rama motor:** `lector-mvp-guia-nueva` · **Rama Desktop:** `fix-desktop-data-root-drag-drop` · **Estado:** sin commit funcional (pendiente de revisión con Javier) · Drive/catálogos/decisiones reales: **sin tocar**.

### Detonante y decisión de diseño

El bloque anterior (JD8659 canónica + reconciliación final) se detuvo en FASE 4 al descubrir que `sugerir_vehiculos_por_chofer` sólo podía proponer una patente ya leída literalmente por OCR en algún otro documento del dataset — JD8659 nunca lo fue (los tres documentos de Carlos Simón leyeron JD6659/JD0659/VP6521). Javier pidió corregir la **capacidad general**, explícitamente prohibiendo hardcodear el caso (`Carlos Simón`, `JD8659`, `VP8521`, `Ortiz`, `XF3662`, números de guía) en lógica de producción, LLM/IA externa, y cualquier cambio de umbral sin evidencia.

### Modelo implementado

`atlas_core/catalogo_vehiculos.py`: `confirmar_vehiculo()` gana el parámetro opcional `rut_chofer_asociado: str = ""`, guardado en `campos_observados` sólo si no está vacío (aditivo, sin romper el JSON existente ni ningún dataclass).

`atlas_core/decisiones_pendientes.py`: nueva función `evaluar_evidencia_patente(*, campo, valor_documental, rut_chofer, tipo_esperado, numero_transporte_actual, filas, vehiculos)` — el motor completo. Jerarquía de precedencia por niveles (no pesos arbitrarios): `NIVEL_CONFIRMACION_HUMANA` > `NIVEL_DOCUMENTAL_INDEPENDIENTE` > `NIVEL_DOCUMENTAL_DEBIL`. Helpers privados: `_transportes_por_patente_de_chofer` (agrupa candidatas por `numero_transporte`, nunca por conteo de documentos — implementa "repetición no equivale a independencia"), `_vehiculos_confirmados_para_rut` (cruza `rut_chofer_asociado` normalizado contra el RUT del documento), `_razon_legible_candidato` (arma la explicación en español, plantillada, sin LLM). Reutiliza `_diferencia_ocr_segura`/`_CONFUSIONES_OCR` ya calibrados (deliberadamente NO se agregó `"6"↔"8"` al set — sería un cambio de umbral motivado por un solo caso). Produce siempre `{"resultado": RESUELTO_AUTOMATICAMENTE|SUGERENCIA_HUMANA|ABSTENCION, "candidatos": [...], "explicacion": str}`; `RESUELTO_AUTOMATICAMENTE` es puramente clasificatorio — nunca escribe nada por sí solo, la aplicación real sigue exigiendo `USAR_PATENTE_EXISTENTE`/`SELECCIONAR_OTRA_PATENTE` (acción humana ya existente).

`sugerir_vehiculos_por_chofer` queda como envoltorio compatible hacia atrás sobre el motor nuevo; `enriquecer_decisiones_vehiculo` pasa a usar `tipo_esperado`/`numero_transporte_actual` reales y adjunta `decision["evaluacion_evidencia"]`.

`aplicar_decision_pendiente.py` (CLI Motor): agrega `USAR_PATENTE_EXISTENTE`/`SELECCIONAR_OTRA_PATENTE` a `--accion` (faltaban desde el bloque anterior, nunca se habían wireado) y los argumentos `--patente-elegida`/`--motivo-rechazo`.

### Integración Desktop (gap encontrado y cerrado)

`src/decisiones_pendientes_ui.js`: `opcionesAccion()` trataba `VEHICULO_DESCONOCIDO` siempre como "entidad desconocida" (Registrar/No registrar/Decidir después), sin mirar `candidatos` — por lo que `USAR_PATENTE_EXISTENTE`/`SELECCIONAR_OTRA_PATENTE`, aunque ya implementadas en Motor desde el bloque anterior, nunca fueron clickeables. Se agregó una rama previa (mismo patrón que `ORIGEN_NO_CONFIRMADO`: un candidato → "Usar patente sugerida"; dos o más → "Elegir otra patente", nunca ambas a la vez, nunca se ofrece "Registrar" cuando ya hay evidencia). Nuevo `selectorPatente` en `nodoAcciones` (radios sobre `decision.candidatos`, mismo patrón que `selectorPlanta`). Nuevo bloque "Patente sugerida"/"Patentes candidatas" con `razon_legible` en `nodoTarjetaCaso` (mismo patrón que las plantas candidatas de origen).

`preload.js`/`main.js`: `aplicarDecisionObra` gana un 5º argumento posicional fijo `patenteElegida` (siempre presente, `null` cuando no aplica — igual que `plantaIdElegida`); `ACCIONES_DECISION_OBRA` suma las dos acciones nuevas; validación superficial `PATRON_PATENTE` antes de invocar el CLI (la autoridad real sigue siendo `aplicar_decision_obra` en Motor). `src/atlas_viajes.html` propaga el 5º argumento en el callback `aplicar`.

### Validación

13 tests nuevos en `tests/test_motor_evidencia_vehiculos.py` (los 10 obligatorios de la especificación + 2 extra + el control de formato de RUT con/sin puntos, hallazgo real del propio dataset): los 3 casos reales de Carlos Simón (JD6659→JD8659, JD0659→JD8659, VP6521→VP8521, cada uno clasificado honestamente, no forzado igual), el control negativo de Ortiz (XF3662 nunca autocorrige a XF3629), candidatos empatados, tipo incorrecto, repetición-vs-independencia (documental y transporte), precedencia de confirmación humana, auditabilidad del valor OCR, abstención sin evidencia. 3 tests CLI nuevos en `tests/test_vehiculo_documental_canonico.py` ejercitan `USAR_PATENTE_EXISTENTE`/`SELECCIONAR_OTRA_PATENTE`/`NO_REGISTRAR` de punta a punta vía `aplicar_decision_pendiente.py`. Motor: `1332 passed, 0 failed`. Desktop: 7 tests nuevos (candidatos de vehículo + wiring de `patenteElegida`) más el ajuste de 5 assertions existentes al nuevo 5º argumento posicional; `221 passed, 0 failed`.

**FASE 12 — validación TEMP contra las 15 decisiones reales vigentes** (copia de Drive a TEMP, sólo lectura, nunca escrita de vuelta): de las 8 decisiones `VEHICULO_DESCONOCIDO` reales, el motor nuevo clasifica hoy 4 como `SUGERENCIA_HUMANA` (las 4 de Carlos Simón — 464264 rampla, 464265 tracto y rampla) y 4 como `ABSTENCION` (464170 tracto/rampla, 464854 tracto/rampla — sin ningún vehículo confirmado asociado a esos RUT). **Cero `RESUELTO_AUTOMATICAMENTE`**, porque JD8659 todavía no está registrado con `rut_chofer_asociado` — exactamente el comportamiento esperado mientras Javier no autorice el registro real. Confirma además, contra datos reales (no sintéticos), que JE8659 corrobora por 1 transporte independiente, no 3 documentos.

Ningún archivo de `G:\Mi unidad\Atlas` fue modificado en este bloque.

---

## 2026-08-14 — R2 CLIENTES: cierre técnico y promoción final 19/19

**Rama:** `lector-mvp-guia-nueva` · **Commit funcional:** `093cce923d172cac18cafb5b453c0cef8de95242` · **Auditoría Claude:** aprobada.

### Solución general

`atlas_core/extractor.py` reemplaza márgenes absolutos de la relación geométrica `SEÑOR(ES)↔R.U.T.` por límites relativos al alto de las cajas OCR, exige que el centro de RUT quede debajo del centro de cliente y conserva abstenciones ante geometría insegura o DV inválido. `atlas_core/procesamiento_masivo.py` usa `clientes.json` como identidad maestra sólo ante RUT exacto, único, `CONFIRMADO` y `ACTIVO`; conserva el nombre documental y mantiene `empresas.json` como compatibilidad. No hay condiciones por guía, cliente u obra. `464534` y `464535` se recuperaron con esta misma ruta general.

### Validación y promoción

Suite final: `1044 passed, 0 failed`. El CSV aprobado, 19 filas únicas y sin errores, promovió el dataset de SHA `B84FD7DB0D7391D93B47B4F5ACA3E4641468CC30374FFC23FD840824A4A62E43` (`17/2`) a `3DF7C5BB88FE5C9DEE2CAA14EEBB885DB5A14C90EB1F80989F19536697D87A4B` (`19/0`) mediante staging en Drive. Respaldo byte-idéntico y reporte anterior: `G:\Mi unidad\Atlas\respaldos\R2_PRE_PROMOCION_FINAL_19_19_2026-08-14_20260814_115726_-0400`. Cero regresiones.

El reporte oficial agrupa los 19 documentos en 15 viajes: 13 confirmados y 2 `REQUIERE_REVISION`. Persisten conflictos entre documentos en `464641/464642` (`CONFLICTO_RUT_CHOFER`, sólo formato documental distinto) y `464698/464699/464700` (`CONFLICTO_RUT_CHOFER | CONFLICTO_CLIENTE | CONFLICTO_OBRA_DESTINO`). No se alteró la consolidación para forzar una cifra.

`19/19` sólo certifica ausencia de motivos documentales bloqueantes en el lote R2. Campos opcionales conocidos: `464699` conserva `MATERIAL_AUSENTE`; `464601` carece de peso y dirección; hay direcciones y algunas horas ausentes en otras guías. Deuda baja no resuelta: comentario con mojibake y endurecimiento conservador del fallback exacto por nombre sin RUT.

---

## 2026-08-14 — R2 OBRAS: identidad canónica, promoción 17/19 y publicación operacional

**Rama:** `lector-mvp-guia-nueva` · **Commit funcional:** `c02aa31ba5044b39a33c8101feea529cbece9f22`.

### API y auditoría

`atlas_core/catalogo_obras_destinos.py` incorpora `actualizar_identidad_obra`: valida evidencia no decisional, conserva `obra_id`, `cliente_id`, estado, vigencia, fecha de creación e historial; une aliases sin duplicar su forma normalizada; rechaza identidad/alias vacíos y colisiones contra otra obra activa del mismo cliente; escribe bajo `bloqueo_sesion` y mediante escritura JSON atómica. `normalizar_nombre_obra` compacta siglas con puntuación explícita (`S.A.`→`SA`) y mantiene separadas letras independientes. `tests/test_catalogo_obras_destinos.py` cubre rechazo sin escritura byte a byte, preservación/deduplicación de aliases, vacíos, colisiones, invariantes y el caso negativo de letras independientes. Auditoría específica `37 passed`; suite `1027 passed, 0 failed`.

### Datos canónicos confirmados

Con decisión `CONFIRMACION_HUMANA_OBRAS_R2_2026-08-14`, actor `JAVIER_MBT`, se confirmaron siete obras y siete relaciones. Identidades externas auditadas: DEMO CONSTRUCCIONES S.A.; INMOBILIARIA Y CONSTRUCTORA TERRATEC LIMITADA (alias AZA conservado); LEVEL INGENIERÍA Y CONSTRUCCIÓN SpA (alias AZA); CONSTRUCTORA IGNACIO HURTADO LIMITADA (alias AZA); SOC CONSTRUCTORA OCL LIMITADA; EBCO S.A. Torres Coronel se conserva como nombre operacional, sin inventar una entidad/RUT. Se crearon seis destinos sin coordenadas inventadas y se reutilizó `f92cbc37-263a-4cca-93fd-74431881a582` para Level, conservando sus coordenadas históricas como aproximadas. Hashes de catálogos al cierre: obras `8B3BEA7679ECB20A770A5D4D3FBDED3671A36A46D537B5023C27B475FE475937`; destinos `9B69D77D193F40AC9207953B939417E70817270CC79D2494908A3AD49119D7C4`.

### Promoción y artefactos

El CSV limpio de 19 filas/19 guías, SHA-256 `B84FD7DB0D7391D93B47B4F5ACA3E4641468CC30374FFC23FD840824A4A62E43`, reemplazó mediante staging en el mismo filesystem al dataset anterior `516A9D5EA8E6632416EB5418756ACB081323FAD66C87D2956B5B28AFCF8A4FFF`. El baseline y el reporte anterior quedaron recuperables en `respaldos/R2_PRE_PROMOCION_OBRAS_17_19_2026-08-14_20260814_110939_-0400`. Resultado documental: `17 OK / 2 REVISAR / 0 errores / 0 duplicados`, ocho nuevas OK y cero OK→REVISAR.

Se regeneró `reportes/actual` con la API oficial: `viajes.csv` `94EC33D30FB72C00869B48CF16496C00744CCA41EF950A2F33978BA5ABB87D93`; `documentos_sin_transporte.csv` `371E32340B678A59089039BEC5B0E549C22932B6A864177A0D8D1D164C097EA0`; `clientes_no_reconocidos.csv` `EBD9C6C5B9E5C2C01E49C5E24791B443035F40A22437AA13CBD321423B3225A0`; `resumen_viajes.md` `01ECCA0CCA5E710CBDBF86BA1B8D2B0C6FAC1E7563DCA87507059254EA533776`; manifest `C017087E98578EB1A5E374041860632AE80B79A1B14B37E22E7B29B5863AFD39`. `estado_operacion.json` apunta a `operacion/actual/analisis_completo_guias.csv` y `reportes/actual` (SHA `91D7277880E7DC5A043FC2B5913A4B430FF1E9BDF733FBE0FFC6C68B4F8FBB64`). Desktop real: `OPERACION_ACTIVA`, sin fallback histórico, repo intacto, `126 passed`.

Pendiente deliberado: `464534` y `464535` siguen `REVISAR` por `CLIENTE_SIN_CORROBORAR | OBRA_DESTINO_SIN_CORROBORAR`; no se modificó esa lógica.

---

> **Actualización posterior:** este registro describe el trabajo del PC de oficina. El cierre reconstruido y publicado al final del archivo fija el estado vigente.

## 2026-08-13 — Registro provisional: INFRAESTRUCTURA S2.2 (trabajo local del PC de oficina)

**Rama motor:** `lector-mvp-guia-nueva` · **Baseline:** posterior a INFRAESTRUCTURA S2.1 (`2046f08`).

### Fase A -- localizar el repo Desktop real

Búsqueda exhaustiva en el PC de oficina (`package.json`/`atlas_viajes.html`/`consolidacion_viaje.js`/historial Git) encontró `C:\Users\corte\Desktop\MBT\Proyecto\_build-atlas-desktop-1.2.0-oficina\` -- clon con `origin` real (`https://github.com/Atlas-Logistic/Atlas-Viajes-Desktop.git`), HEAD detached en `ef6dfb0`. `git fetch --all` reveló 18 ramas remotas / 31 commits totales. El commit buscado (`96229813fcae41c5e1ea22ac139c703c616c976a`, MATERIAL/PESO/OBRA DESTINO multiguía) **no existe en ninguna rama fetcheada** ni en la copia histórica de Drive; lo más cercano es `src/consolidacion_viaje.js` en la rama `feature-consolidacion-viajes-1` (no fusionada aquí -- fuera de alcance).

La copia que S2.1 había movido a `historico_pre_infra_s2\componentes_no_portables\Atlas-Viajes-Desktop-Restaurado\` resultó tener el mismo linaje real (comparte el commit `139d41f` byte a byte con `origin/fix-desktop-data-root-drag-drop`) más 3 commits locales nunca publicados (`0ec8a3b`, `50b4323`, `b247432`) -- confirmado con `git merge-base --is-ancestor` (fast-forward limpio, sin reescritura). Se creó una copia de trabajo nueva (`Desktop\MBT\Proyecto\Atlas-Viajes-Desktop\`, clon limpio de `origin` + los 3 commits traídos como remoto temporal, luego removido) en vez de desarrollar dentro de Drive o reutilizar el clon viejo desactualizado.

### Fase C/D -- auditoría y contrato portable

`main.js` resolvía `carpetaReportes`/`carpetaProyectoPython`/`carpetaCatalogos` desde `electron-store` (`config_usuario`), poblado por migración desde un `config.json` legado -- mecanismo de almacenamiento ya correcto (sobrevive reinstalaciones), pero los *valores* migrados venían de un PC específico (`C:\Users\Jjjc0508\...`). `carpetaProyectoPython` se dejó deliberadamente fuera de cualquier derivación portable: apunta al repo de código, y S2.1 ya decidió "código = Git, no Drive" -- forzarla a derivar de `ATLAS_DATA_DIR` violaría esa decisión.

`src/atlas_data_dir.js` (nuevo): mismo contrato que `atlas_core/almacenamiento_portable.py` (override > `ATLAS_DATA_DIR` > configuración local mínima > autodetección de Drive > `null`), con un nivel extra (configuración local) inexistente del lado Python -- necesario porque Electron lanzado desde un acceso directo/instalador puede no heredar variables de entorno definidas después del inicio de sesión de Windows.

### Fase F/G -- manifiesto de operación vigente, contrato compartido

El motor (tras S2.1) no tenía ningún mecanismo de "operación vigente" -- solo carpetas. Se definió `operacion/actual/estado_operacion.json` (schema_version 1: `reporte_vigente`, `dataset_operacional` opcional, `fecha_actualizacion`, `origen`), documentado idénticamente en `docs/CONTRATO_ESTADO_OPERACION_PORTABLE.md` (motor) y `documentacion/CONTRATO_ESTADO_OPERACION_PORTABLE.md` (Desktop).

Lado motor: `atlas_core/almacenamiento_portable.py` gana `escribir_estado_operacion`/`leer_estado_operacion` (mismo patrón de escritura atómica). Cualquier ruta relativa que resuelva fuera de la raíz invalida todo el manifiesto (`_ruta_relativa_segura`, usa `Path.relative_to`). Wireado en `generar_reporte_viajes.py` como paso *best-effort* tras generar el reporte: si `--salida`/el CSV no viven dentro de `ATLAS_DATA_DIR`, no se publica nada -- comportamiento idéntico al de antes de S2.2 (verificado con test dedicado).

Lado Desktop: `src/estado_operacion.js` (`leerEstadoOperacion`) -- ausencia de manifiesto es `SIN_OPERACION_ACTIVA` (caso válido, no error); JSON corrupto es `MANIFIESTO_INVALIDO`; `schema_version` no reconocida es `SCHEMA_NO_SOPORTADO`; campo `reporte_vigente` ausente es `MANIFIESTO_INCOMPLETO`; cualquier ruta (relativa) que resuelva fuera de la raíz es `RUTA_FUERA_DE_RAIZ`. Nunca hace `readdir`/glob -- solo lee ese archivo exacto, por lo que estructuralmente no puede "caer" a `historico_pre_infra_s2\`.

`main.js`: `atlas:cargar-automatico` ahora prefiere `estadoOperacion.reporteVigente` sobre `configuracion.carpetaReportes`, cayendo al valor legacy solo si no hay manifiesto -- superset estricto del comportamiento anterior (si no hay manifiesto, se comporta exactamente igual que antes). Dos IPC nuevos, aditivos: `atlas:estado-operacion-vigente` (para un futuro panel de estado) y `atlas:configurar-raiz-atlas` (para una futura pantalla de configuración de la raíz local mínima -- la lectura/escritura ya existen, la UI queda pendiente, deliberadamente fuera de alcance de este bloque).

### Fase H -- migración de config_usuario legacy

`migrarHaciaRaizPortableSiCorresponde` (nuevo en `src/configuracion_usuario.js`): un valor de `carpetaCatalogos`/`carpetaReportes` se trata como legacy si no existe como carpeta real en este PC, o si existe pero no vive dentro de la raíz portable resuelta (comparación por límite de carpeta real, con separador de por medio -- **bug encontrado y corregido durante la implementación**: una comparación por prefijo de texto simple hacía que `G:\Atlas2\...` contara como "dentro de" `G:\Atlas`, falso positivo real corregido con un test dedicado). Se respalda bajo una clave con timestamp antes de reemplazar -- nunca se pierde el valor original. Idempotente (`_migradoHaciaRaizPortable`). `carpetaProyectoPython` explícitamente excluida (ver Fase C).

### Bloqueo real de verificación (Desktop)

Este entorno de ejecución no tiene Node.js instalable: sin `node.exe` en PATH ni en ubicaciones conocidas (`Program Files`, `AppData\Local\Programs`, `nvm`, Chocolatey), y `node_modules/electron/dist` nunca se descargó en ningún clon local encontrado (instalación de dependencias hecha originalmente sin acceso a la descarga del binario de Electron). No se pudo ejecutar `npm test` (110 tests previos reportados + 16 nuevos) ni abrir Electron para validación visual. El código se revisó manualmente con cuidado -- mismo patrón exacto de funciones puras que ya usa el resto del repo, balance de llaves/paréntesis verificado sin diferencia neta introducida (`git show HEAD:main.js` vs versión editada: +36 `(` / +36 `)`) -- y se comiteó localmente (`4b94a38` sobre `fix-desktop-data-root-drag-drop`), **sin publicar**. Ver `coordinacion\PENDIENTE_PC_CASA.md` en Drive para el paso exacto pendiente (`npm test` + `git push` desde un PC con Node).

### Validación (motor)

Suite completa: 916 → **927 tests** (11 nuevos: `tests/test_generar_reporte_viajes_cli.py`, 8 nuevos en `tests/test_almacenamiento_portable.py`), sin regresiones.

---

## 2026-08-13 — Cierre: INFRAESTRUCTURA S2 / S2.1 (raíz portable de Drive, caché ORS, saneamiento de la carpeta Drive existente)

**Rama:** `lector-mvp-guia-nueva` · **Baseline:** posterior a INTELIGENCIA N1 (`ed52afb`).

### Decisión de arquitectura

Código = GitHub. Estado operativo portable (catálogos privados, cachés, reportes, respaldos, coordinación) = una única raíz `Atlas\` sincronizada por Drive. Secretos = variables de entorno locales, nunca Drive ni Git. Un solo módulo (`atlas_core/almacenamiento_portable.py`) concentra CÓMO se resuelve esa raíz -- nada más en el repo construye la ruta a mano.

### Fase 0 (S2.1) -- auditoría de la carpeta `Atlas` ya existente en Drive, antes de tocar nada

`G:\Mi unidad\Atlas` (Google Drive for Desktop, detectado vía `HKCU:\Software\Google\DriveFS`) ya existía, pero no era una raíz limpia: resultado de una sesión de incidente del 2026-08-10/11 (rollback/reinstalación de Atlas Desktop 1.4.2→1.4.4, evaluación comparativa PaddleOCR/EasyOCR con GPU). Contenía: dos copias completas de repos Git (`Proyecto-Atlas`, HEAD `129b459` -- ancestro confirmado del HEAD actual, no una rama divergente; `Atlas-Viajes-Desktop-Restaurado`, **sin remoto Git configurado**); dos venvs de Python (`ocr_eval_env`, `ocr_eval_gpu_env` -- este último con PaddlePaddle-GPU 3.3.1 + CUDA 11.8 completo); y cuatro copias no reconciliadas de `analisis_completo_guias.csv` (tres idénticas de 1.178 filas/410.100 bytes fechadas 2026-08-08, una de 15 filas/3.342 bytes fechada 2026-08-11). `REPORTE_RESTAURACION.md` dentro de `datos_privados\` confirmó que ese material vino del PC de casa (usuario Windows `Jjjc0508`).

**Decisión de negocio aplicada, no derivada por heurística:** el histórico de 1.178 filas no se promueve a operación vigente. Se preservó sin borrar nada, moviendo (operación de metadatos de Drive, prácticamente instantánea -- no hay recarga de bytes en un `move` dentro del mismo volumen) todo lo no-portable a `historico_pre_infra_s2\` (snapshots, `ocr_eval`, `IMAGENES`, `backups_config`) y `historico_pre_infra_s2\componentes_no_portables\` (los dos repos Git, los dos venvs), cada uno con su propio `README_HISTORICO.md`/`NO_USAR_COMO_CODIGO_CANONICO.md`.

### Fase 1 -- `atlas_core/almacenamiento_portable.py` (nuevo)

`resolver_raiz_atlas(override=None)`: prioridad `override` explícito → `ATLAS_DATA_DIR` → `autodetectar_raiz_drive()` (solo lectura: prueba `<letra>:\{Mi unidad,My Drive}\Atlas` en D:-Z: y `%USERPROFILE%\Google Drive\Atlas`; nunca crea nada, devuelve `None` si no hay evidencia real) → fallback local `Path(".atlas_local")` (cwd-relativo, gitignored, uso de desarrollo/tests). Expone helpers de subcarpeta (`ruta_operacion`, `ruta_catalogos_privados`, `ruta_cache`, `ruta_reportes`, `ruta_respaldos`, `ruta_datos_privados`, `ruta_coordinacion`) que todos aceptan `raiz=` explícito para tests. También centraliza `escribir_json_atomico` (mismo patrón tempfile+`os.replace` que ya usaban `RepositorioRutas`/`RepositorioTelemetria`) y `bloqueo_sesion` (lock de archivo simple con expiración por antigüedad para locks huérfanos, `SesionOcupadaError` si otra sesión activa sostiene el mismo nombre).

**Aislamiento de tests (`tests/conftest.py`, nuevo):** fixture `autouse` que hace `delenv("ATLAS_DATA_DIR")` y fuerza `autodetectar_raiz_drive` a devolver `None` en cada test -- sin esto, configurar `ATLAS_DATA_DIR` de forma persistente en una máquina de desarrollo (como se hizo en este mismo bloque) rompería silenciosamente `test_fuente_inexistente_incompleta_e_invalida` y cualquier otro test que dependa de que no exista fuente de catálogos por defecto.

### Fase 2 -- `atlas_core/fuente_catalogos.py`

Nueva tercera capa de fallback en `resolver_fuente_catalogos`: si no hay `ruta`/`ATLAS_CATALOGOS_DIR` explícitos ni `catalogos/` local completo, se prueba `ruta_catalogos_privados()` (misma verificación "los 7 archivos requeridos están presentes" que ya se usaba para el fallback local) antes de lanzar `ErrorFuenteCatalogos`. Retrocompatible: si esa carpeta no existe o está incompleta, el comportamiento (y el mensaje de error) es idéntico al de antes de este bloque.

### Fase 3 -- `atlas_core/rutas/cache_geocodificacion.py` (nuevo)

Gap real encontrado: `RepositorioRutas`/`ServicioRutas` ya cacheaban la ruta calculada final (clave lógica planta/destino/perfil/proveedor), pero `ServicioRutas.preparar()` llamaba `proveedor.geocodificar()` en cada ejecución, sin ninguna caché -- exactamente la llamada que Onelogis ya no repetía y ORS sí. `RepositorioCacheGeocodificacion` (JSON, escritura atómica, protegida por `bloqueo_sesion`, ubicación predeterminada `<raíz>\cache\geocodificacion\geocodificacion_cache.json`) cachea por `proveedor.nombre|proveedor.version|dirección_normalizada` (mismo normalizador NFKD-mayúsculas-solo-alfanumérico que `huella_direccion` en `atlas_core/rutas/servicio.py`). `ProveedorRutasConCacheGeocodificacion` (decorador `@dataclass(eq=False)` -- deliberado, para conservar igualdad/hash por identidad y no romper código que guarda instancias de proveedor en un `set`) envuelve cualquier `ProveedorRutas`: cachea `geocodificar()`, delega `calcular_ruta()` sin cambios. Solo se cachean estados estables (`REQUIERE_REVISION`, `RESULTADO_AMBIGUO`, `DIRECCION_NO_ENCONTRADA`) -- fallos transitorios (`SIN_CONEXION`, `LIMITE_CUOTA`, `SIN_CREDENCIAL`) nunca quedan "pegados" en caché.

Wireado en `atlas_core/procesamiento_masivo.py` en los dos puntos donde se construye `OpenRouteService(pais=pais_operacion)` por defecto (`resolver_entrega_documento` en modo un-solo-archivo, y el proveedor compartido de todo un lote) -- ningún test existente ejercía esa rama por defecto (todos inyectan `proveedor_rutas` explícito), así que el cambio no tocó ningún comportamiento cubierto por la suite previa.

**Bug encontrado y corregido durante la implementación:** `ProveedorRutasConCacheGeocodificacion` como `@dataclass` normal generaba `__eq__`/`__hash__` por valor, lo que lo volvía no-hasheable (dataclass con `eq=True` por defecto y sin `frozen=True` pone `__hash__ = None`) -- rompía `test_integracion_catalogos_desktop.py::test_catalogos_y_proveedor_compartido_se_propagan_juntos`, que mete instancias de proveedor en un `set` para verificar que el lote reutiliza la misma instancia. Corregido con `@dataclass(eq=False)`.

### Fase 4 -- migración real en PC de oficina (sin gastar llamadas externas)

Catálogo vivo real encontrado en `C:\Users\corte\AppData\Local\Atlas\datos\catalogos_privados\` (8 archivos, base 2026-07-30, con manifiesto SHA-256 propio ya diseñado con política "versión completa inmutable; activación solo con hashes coincidentes"). Copiado (no movido -- Desktop sigue leyendo del original hasta que se adapte) a `G:\Mi unidad\Atlas\catalogos_privados\`; verificado con `sha256sum` contra las 8 hashes del manifiesto -- coincidencia exacta. `ATLAS_DATA_DIR` configurado a nivel de usuario Windows (`SetEnvironmentVariable(..., "User")`) apuntando a `G:\Mi unidad\Atlas`.

Prueba E2E de bajo costo, sin llamadas externas: `validar_fuente_catalogos()` con `ATLAS_DATA_DIR` real → `CATALOGOS_VALIDOS`, conteos idénticos al manifiesto. Cache hit de geocodificación demostrado con un `ProveedorRutasSimulado` instrumentado contra la ruta real de caché en Drive (`interno.llamadas_geocodificacion == 1` tras dos consultas idénticas); archivo de demostración borrado después de la prueba para no dejar datos sintéticos en la caché real.

### Deliberadamente fuera de alcance

Adaptar `main.js`/`config_usuario.json` de Atlas Desktop (hoy hardcodea `C:\Users\Jjjc0508\...`): la única copia de ese código disponible (`historico_pre_infra_s2\componentes_no_portables\Atlas-Viajes-Desktop-Restaurado\`) no tiene remoto Git -- editarla dentro de Drive habría violado el propio principio "código = Git" de este bloque. Documentado como pendiente en `coordinacion\PENDIENTE_PC_CASA.md`.

### Validación

Suite completa: 892 → **916 tests** (24 nuevos: `tests/test_almacenamiento_portable.py`, `tests/test_cache_geocodificacion.py`, 3 nuevos en `tests/test_fuente_catalogos.py`), sin regresiones -- corrida completa en verde después del fix de hasheabilidad.

---

## 2026-08-12 — Cierre: INTELIGENCIA N1 (normalización semántica controlada de territorios y entidades)

**Rama:** `lector-mvp-guia-nueva` · **Baseline:** posterior a PATENTES P4 (`88645b3`).

### Principio de diseño

`VALOR OCR` ≠ `VALOR NORMALIZADO` ≠ `VALOR CANÓNICO CORROBORADO`. Un valor OCR se normaliza SOLO contra un universo/vocabulario cerrado, con candidato único y margen; se corrobora SOLO contra RUT/código/catálogo real. Ninguna corrección es un reemplazo aislado por caso -- todas viven en funciones generales (`normalizar_comuna`, `normalizar_nombre_societario`, `resolver_nombre_empresa_difuso`) sin ninguna guía/valor hardcodeado.

### Fase A -- auditoría real (19 guías, sin reproceso masivo)

Volcado completo de `cliente`/`obra_destino`/`chofer`/`rut_chofer`/`motivos_revision_documento` de las 19 filas del CSV operacional. Hallazgos que definieron el alcance real del bloque (no los del enunciado original, encontrados investigando):

1. **464698/464699** (imágenes reales inspeccionadas): SEÑOR(ES) impreso "EBEMA SA" -- PaddleOCR lo lee "EDMA SA" y "KBEMA SA" en cada guía. R.U.T. impreso "83.585.400-0" (= `835854000`, existe exacto en `empresas.json` como EBEMA SA) -- pero `_extraer_rut_cliente_geometrico` nunca lo encontraba.
2. **Causa raíz del punto 1 (bug real):** la etiqueta SEÑOR(ES) termina en y=479, R.U.T. empieza en y=476 (gap **-3px**, filas de un formulario apretado que se solapan levemente) -- el filtro geométrico exigía `0 <= gap`, rechazando la etiqueta R.U.T. válida por un margen de 3px.
3. **OBRA DESTINO** impreso "SOC CONSTRUCTORA OCL LIMITAD" -- PaddleOCR lo lee "I SOC CONETRUCTORA OCL LIMITAD" (un "I" espurio al inicio, más "CONETRUCTORA"/"LIMITAD" corruptos). `COD DESTINATARIO` (0002013090) no existe en `destinos.json` -- destino genuinamente no catalogado, no un bug.
4. **464522/464642** (JOSE LAZCANO, catálogo `choferes.json` clave `10833150K`): `buscar_rut_chofer()` usaba `[0-9.\s-]` -- sin "K" en la clase de caracteres, el RUT quedaba truncado en "10.833.150-" (perdiendo el verificador), y `buscar_chofer_por_rut` nunca calzaba contra el catálogo aunque el chofer sí estuviera ahí.
5. **Cliente sin corroborar generalizado:** `resolver_nombre_chofer_difuso` (fuzzy contra catálogo) solo existía para chofer -- cliente nunca tenía una vía de corroboración por similitud de nombre, solo RUT exacto.
6. **despachar_a_crudo** de 464698/464699: `"CATEDRAL 759 CADQUENES CAUQUENES"` / `"...758 CAUQUBNES CAUQUENES"` -- el documento repite la comuna en dos campos (COMUNA + CIUDAD); el OCR corrompió uno de los dos en cada guía, mientras el otro quedó legible. `estado_ruta=REQUIERE_REVISION`, `motivo=GEOCODIFICACION_DIRECCION_NO_ENCONTRADA`.

### Fase B/C/D/M -- `atlas_core/territorio_chile.py` (nuevo)

Snapshot estático de 16 regiones / 345 comunas (adaptado de un dataset público de GitHub, corregido a mano contra nombres oficiales: `Quilcura→Quilicura`, `Vitcarua→Vitacura`, `Couhaique→Coyhaique`, etc.). `normalizar_comuna(texto)`: EXACTA / NORMALIZADA_SEGURA (único candidato, similitud ≥ umbral, margen sobre el segundo) / AMBIGUA / NO_RECONOCIDA. `normalizar_direccion_con_comunas(texto)`: aplica esto palabra por palabra sobre una dirección completa -- si el token corrupto normaliza a una comuna que YA aparece exacta en otra parte del texto, se **descarta** (no se duplica); si no, se **reemplaza**. Se usa únicamente para construir la consulta al geocodificador -- `despachar_a_crudo` en el resultado nunca pierde el texto documental original.

**Bug real encontrado validando el propio bloque (antes de cerrar, no en producción):** con el umbral inicial (0.82), la palabra real "CAMINO" (de "CAMINO LOS PINOS...") normalizaba a la comuna real "Camiña" (0.833 de similitud), y "PARQUE" a "Pirque" (0.833) -- ambos falsos positivos reales, no hipotéticos. Corregido subiendo el umbral a 0.87 (los dos casos reales del bloque quedan en 0.889 y 0.923, con margen) y agregando una lista cerrada de vocabulario estructural de direcciones (CAMINO, CALLE, AVENIDA, PARQUE, SECTOR, ...) que nunca es candidato a comuna sin importar la similitud -- defensa en profundidad, no solo el umbral.

### Fase E -- `atlas_core/normalizacion_semantica.py` (nuevo)

Vocabulario societario acotado a evidencia real (catálogos + tanda): formas abreviadas cortas (SA/SPA/LTDA/EIRL, ≤4 caracteres) y palabras descriptivas largas (CONSTRUCTORA, INGENIERIA, INMOBILIARIA, ...). `normalizar_token_societario`: las formas cortas solo aceptan sustitución en la MISMA longitud (nunca inserción/eliminación); las largas toleran una distancia de edición completa (1-2 según longitud). **Bug real encontrado y corregido durante la implementación:** una tolerancia de edición uniforme dejaba "SAN" (real, común en topónimos -- "SAN BERNARDO") a distancia 1 de "SA" por eliminación, corrompiendo "SALOMON SACK SA SAN BERNARDO" en "...SA SA BERNARDO". La regla de longitud-exacta-para-formas-cortas lo corrige de raíz. `normalizar_nombre_societario`: aplica esto token por token sobre un nombre completo, más un stripper de prefijo de un solo carácter suelto (artefacto OCR real: "I SOC CONSTRUCTORA...", "I TORRES OCARANZA..." -- probablemente un separador ":"/"|" mal leído).

### Fase F/I/K -- `atlas_core/catalogos.py`

`_resolver_nombre_difuso_generico`: núcleo compartido extraído de `resolver_nombre_chofer_difuso` (comportamiento idéntico, sin romper ningún test existente) + `resolver_nombre_empresa_difuso` (nuevo, mismo criterio contra `empresas.json`). Ambos ahora también consultan `aliases` (lista opcional por registro, ya presente en `choferes.json` pero nunca antes leída por este resolver) como coincidencia EXACTA previa al fuzzy -- evidencia fuerte por diseño. `registrar_alias_seguro(ruta, identificador, alias)` (Fase K): persiste una variante OCR como alias SOLO si identifica un único registro, no es ya su nombre canónico, y no coincide con el nombre/alias de NINGÚN otro registro -- escritura atómica (temp file + `os.replace`, mismo patrón que `catalogo_clientes.py`).

### Fase G/H/L -- `atlas_core/procesamiento_masivo.py`

Bloque nuevo tras la homologación de patentes: (1) normalización societaria de `cliente`/`obra destino` (Fase E, siempre, corrobore o no -- método `NORMALIZADO`, nuevo en `MetodoObtencionDocumento`); (2) RUT exacto contra `empresas.json` -- si corrobora, aprende alias usando el valor OCR **anterior** a `enriquecer_datos_con_catalogos` (`cliente_antes_catalogo`, ya existente para trazabilidad S2.2 -- si se usara el valor ya corregido no habría nada que aprender); (3) si no, fuzzy contra `empresas.json` (Fase F, NIVEL FUERTE). Nuevo motivo informativo `CLIENTE_NUEVA_ENTIDAD_NO_CATALOGADA` (no bloqueante, agregado a `MOTIVOS_NO_BLOQUEANTES`): RUT válido + nombre consistente pero sin catálogo que lo confirme -- distinto de "OCR dudoso". **Obra destino se mantiene deliberadamente conservador** (Fase H/L, sin tocar): la corroboración por `COD DESTINATARIO` sigue exigiendo revisión ante cualquier cambio, solo se agregó la limpieza de texto (Fase E) -- nunca se "maquilla" ese estado.

### Fase M -- `atlas_core/rutas/destino_entrega.py`

`resolver_destino_entrega` aplica `normalizar_direccion_con_comunas` SOLO a la cadena de consulta enviada al geocodificador -- `despachar_a_crudo` en el resultado sigue siendo el texto documental sin tocar. Normalización local primero (Fase N): nunca se llama a ORS para "adivinar" un typo que el catálogo local ya resuelve; el proveedor de rutas se sigue llamando exactamente igual de veces que antes (no hay reintento adicional).

### Tests y regresión

20 tests nuevos en `tests/test_inteligencia_n1.py` (cubren los 18 ítems de la Fase Q). 2 tests existentes actualizados con justificación explícita (`test_caso_real_coronel_descarta_localidad_sin_soporte_textual`, `test_resolver_destino_entrega_usa_gps_para_desambiguar_de_extremo_a_extremo`): la consulta real enviada al geocodificador ya no incluye "CORONE" (token duplicado/corrupto de "CORONEL", ya legible en el mismo texto) -- el mock debía reflejar la consulta real. Suite completa: **872 → 892 tests**, 0 regresiones de comportamiento.

### Reproceso operacional

Backup: `output/_respaldos_reprocesamiento/analisis_completo_guias_PRE_N1_20260812_194428.csv`. Reproceso completo de las 19 guías reales (`procesar_archivo` real: PaddleOCR + catálogos reales + `ServicioTelemetria`/Onelogis con caché real + `OpenRouteService` real) -- justificado por el alcance del bloque (cliente/obra_destino/comuna tocan potencialmente cualquier fila, a diferencia de P4 que aisló 2 filas). Reprocesado DOS veces: la primera corrida usó el umbral de comuna sin corregir (0.82) y produjo un falso positivo real (`CAMINO`→`Camiña` en 464641/464642, que coincidentemente dejaba `RUTA_CALCULADA` con un motivo distinto pero geocodificado a un lugar equivocado); se detectó auditando el propio resultado, se corrigió el umbral+lista de exclusión, y se re-ejecutó el reproceso completo desde el backup original antes de aceptar el resultado. Reporte regenerado en `output/reporte_desktop_20260812_195650_inteligencia_n1/`; `config_usuario.json` del Desktop actualizado. Alias aprendidos en `empresas.json` durante el reproceso real: `EBEMA SA` ← `EDMA SA`, `KBEMA SA`.

### Costo

0 llamadas OCR nuevas (misma tanda ya presente localmente). Onelogis: 0 llamadas nuevas (toda la tanda ya estaba cacheada desde O2/P4). ORS: 19 llamadas de geocodificación/ruta (una por guía reprocesada, mismo patrón de costo que P4/O2 -- normalización de comuna es 100% local, nunca agrega una llamada ORS adicional).

---

## 2026-08-12 — Cierre: PATENTES P4 (recuperar patente/remolque por geometría real + revalidar 464631)

**Rama:** `lector-mvp-guia-nueva` · **Baseline:** posterior a ORIGEN O2 (`3b3189c`).

### Fase A -- traza real sobre la imagen 464631 (PaddleOCR, sin mocks)

Bloques OCR reales relevantes:
- `'PATENTE'` (bloque propio) seguido, en la misma fila, del bloque `': DD2494 CARR0:JB8529'` -- valor de PATENTE y el par CARRO:valor fusionados en un solo bloque, con la etiqueta CARRO leída **"CARR0"** (cero por O).
- `'RUT CHOFER'` (bloque propio, columna izquierda) mientras que su valor real `':14293816-2'` aparece en el texto lineal pegado a `'DESPACHAR A'` (la etiqueta de la fila anterior) -- el mismo patrón de columnas intercaladas por orden de lectura de PaddleOCR ya documentado para DESPACHAR A en OPERACIÓN REAL R1 (`_despachar_a_lineal_contaminado`).

`extraer_datos()` (la vía lineal, `buscar_chofer_y_patentes()`) exige el substring literal `"RETIRA PATENTE FECHA LLEGADA"` contiguo -- nunca aparece en un layout de dos columnas, así que la vía lineal siempre devuelve `(None, None, None)` para este tipo de documento. La causa real de la pérdida estaba en el fallback "geométrico" (`_extraer_patentes_geometrico`), que pese a su nombre no asociaba etiqueta→valor por posición: concatenaba TODO el texto de la zona RETIRA-FECHA LLEGADA en una sola cadena y buscaba por regex sobre esa cadena. Con `CARRO` leído `CARR0`, el patrón de CARRO nunca matcheaba; al buscar luego cualquier token suelto de 6 caracteres válido como patente en el resto de la zona, encontraba DOS (`DD2494` y `JB8529`, éste liberado por la falla del patrón de CARRO) y se abstenía por "ambigüedad" -- perdiendo ambas patentes.

### Fase B/C -- reescritura de `_extraer_patentes_geometrico` (`atlas_core/extractor.py`)

Nuevo diseño en dos pasos, sin hardcodear ningún valor:
1. **Inline por bloque** (`_valor_tras_etiqueta_en_bloque`): busca, DENTRO de un único bloque OCR, `ETIQUETA[:] VALOR` de 6 caracteres -- cubre el caso real (label+valor fusionados). Tolerante a confusión O/0 en la ETIQUETA vía `_tolerante_o_cero` (nunca en el valor).
2. **Fallback geométrico** (`resolver_por_geometria`): si no hay match inline, busca un bloque-etiqueta (`PATENTE`/`TRACTO`/`CARRO`/`RAMPLA`/`REMOLQUE`, comparación de bloque completo tolerante a O/0 vía `_es_etiqueta_patente`) y asocia por proximidad real (misma fila a la derecha, o alineado debajo -- mismo criterio que `_extraer_chofer_geometrico`/`_extraer_transporte_geometrico`) a su valor, excluyendo candidatos más cercanos a la etiqueta RIVAL (TRACTO vs CARRO) para que un valor sin etiqueta propia adyacente no se filtre al campo equivocado.
3. `_valor_unico_residual`: dentro de un bloque de valor ya asociado, remueve cualquier segundo par `ETIQUETA:VALOR` embebido (p. ej. el `CARRO:JB8529` que viene pegado al valor de PATENTE) y exige que quede exactamente un token de 6 caracteres válido -- se abstiene si queda más de uno.
4. Ambigüedad real ahora se mide por MARGEN DE SCORE entre candidatos de la MISMA etiqueta (margen 0.06, mismo patrón que el resto del archivo) -- un segundo token válido en la zona que esté claramente más lejos de la etiqueta ya NO bloquea el hallazgo (comportamiento anterior, ver test actualizado `test_patentes_candidato_lejano_ya_no_bloquea_al_mas_cercano`).

**Bug real encontrado durante la implementación** (no en el plan original): el fallback geométrico de TRACTO, al no conocer las etiquetas de CARRO, podía adoptar por descarte el valor de un CARRO/RAMPLA sin candidato propio de TRACTO cerca. Corregido excluyendo explícitamente cualquier candidato geométricamente más cercano a una etiqueta rival (ver `resolver_por_geometria(etiquetas, etiquetas_rivales)`).

**Ancla RETIRA tolerante** (`_es_ancla_retira`, patrón `RETI?RA`): guía real 464550 de la misma tanda, etiqueta RETIRA leída "RETRA" (falta la "I") -- sin esta tolerancia, la zona nunca se delimitaba y la función abortaba antes de llegar a evaluar PATENTE/CARRO, aunque la patente (BPHR67) estuviera perfectamente legible y geométricamente asociada.

### Fase E -- RUT del chofer por geometría (`_extraer_rut_chofer_geometrico`, nuevo)

Mismo patrón que `_extraer_rut_cliente_geometrico`: ancla en el bloque `RUT CHOFER` (bloque completo, sin subcadena), asocia por proximidad (misma fila a la derecha o alineado debajo), exige `validar_rut_chileno` con dígito verificador correcto, se abstiene ante ambigüedad. Cablea en `procesamiento_masivo.py`: se agregó `"RUT del chofer"` a la condición `campos_ausentes` que dispara la lectura de bloques geométricos, y una llamada nueva junto al resto de recuperaciones geométricas (cliente, chofer, transporte).

### Fase D -- homologación (sin cambios de código, verificado)

`DD2494`/`JB8529`/`BPHR67` ya existen en el catálogo real de vehículos (`vehiculos.json`) con el tipo correcto -- homologan a `COINCIDENCIA_EXACTA`, sin motivo `PATENTE_SIN_HOMOLOGAR`. El mecanismo que preserva un valor legible pero no homologado (motivo `PATENTE_SIN_HOMOLOGAR`, nunca "No encontrado") ya existía desde P2 y no requirió cambios -- se agregó un test dedicado (`test_patente_geometrica_sin_homologar_se_conserva_con_motivo`) para dejarlo cubierto explícitamente en este bloque.

### Fase F -- 464631, cronología real (Onelogis, cache real)

Consulta en vivo a Onelogis (bypaseando caché) confirma que la caché NO estaba desactualizada: DD2494 tiene únicamente 2 trips registrados el 11-08-2026, el último terminando a las 10:26:56 -- casi 3 horas antes de la ventana documental (13:10-13:52). Ese último trip incluye una detención real (velocidad 0 en ambos extremos, 10:20:23-10:26:56) dentro del polígono de AZA COLINA; no hay ningún trip ni evidencia de AZA RENCA ese día. `resolver_planta_origen_gps` confirma AZA COLINA como única candidata (`score=0.0` porque la detención no solapa la ventana documental -- regla de "candidato único confirma" de O2, Fase D). Se documenta explícitamente: la cobertura GPS no cubre la ventana exacta de carga, pero es la única evidencia existente y coincide con el terreno confirmado por Javier/chofer.

### Fase G -- ruta

Origen AZA COLINA + destino SANTA ISABEL 585 LAMPA (ya geocodificado) → recalculada con OpenRouteService: 7.49 km / 13.48 min, `RUTA_CALCULADA` (antes: sin resolver, origen documental era AZA RENCA).

### Fase H -- regresión en tanda reciente

Se revisaron visualmente y por extracción las 6 guías de la misma tanda con patente/rampla ausente (`464534`, `464535`, `464550`, `464588`, `464624`, `463594`). Cinco de seis no cambian (ya recuperaban tracto correctamente vía geometría, sin CARRO/RAMPLA visible en el documento -- no es un bug, esos camiones no imprimen rampla). **464550 sí tenía el mismo patrón** (`RETIRA` leído `RETRA`, bloqueando toda la zona) con `BPHR67` claramente impreso -- confirmado visualmente en la imagen real. Al recuperar la patente, la telemetría (antes nunca gateada, `_patente_valida` fallaba con `"No encontrado"`) corrió por primera vez para esta guía: confirma **AZA COLINA** con score alto (0.767, 100% de solape con la ventana documental, 101 min de detención real dentro de la ventana completa) -- reemplaza el fallback documental (`AZA RENCA`, encabezado). Ruta recalculada: 27.75 km / 38.51 min.

### Archivos modificados

- `atlas_core/extractor.py`: `_extraer_patentes_geometrico` reescrito; `_extraer_rut_chofer_geometrico` (nuevo); helpers `_es_ancla_retira`, `_es_etiqueta_patente`, `_valor_tras_etiqueta_en_bloque`, `_valor_unico_residual`, `_tolerante_o_cero`.
- `atlas_core/procesamiento_masivo.py`: import de `_extraer_rut_chofer_geometrico`; `campos_ausentes` incluye `"RUT del chofer"`; llamada de recuperación geométrica de RUT del chofer.
- `tests/test_patentes_p4.py` (nuevo, 15 tests incluyendo parametrizados): items 1-10 del bloque (patente junto a RETIRA, CARRO junto a PATENTE, orden intercalado RUT chofer, patente única, rampla única con etiquetas sinónimas, valor sin homologar conservado, ambigüedad real, regresión estructural 464631, patente habilita telemetría, planta GPS reemplaza fallback documental).
- `tests/test_extraer_datos.py`: `test_patentes_dos_candidatos_ambiguos_se_abstiene` reescrito como `test_patentes_candidato_lejano_ya_no_bloquea_al_mas_cercano` (el algoritmo anterior trataba cualquier segundo token de 6 caracteres en la zona como ambigüedad sin medir distancia real; el nuevo no).
- `tests/test_procesamiento_masivo.py`: 4 tests existentes actualizados mecánicamente (`_datos_lineales_completos` y 2 diccionarios inline) para incluir `"RUT del chofer"` -- antes ausente del diccionario de prueba, ahora forma parte de `campos_ausentes`.

### Tests y regresión

12 tests nuevos (más 3 variantes parametrizadas) en `test_patentes_p4.py`, 1 reescrito en `test_extraer_datos.py`. Suite completa: **872 passed** (861 antes + 11 netos). 0 regresiones de comportamiento -- los 4 ajustes en `test_procesamiento_masivo.py` son mecánicos (campo faltante en fixture, no en código).

### Reproceso operacional

Backup: `output/_respaldos_reprocesamiento/analisis_completo_guias_PRE_P4_20260812_185912.csv`. Reproceso quirúrgico de únicamente las 2 filas afectadas (`464631.jpeg`, `464550.jpeg`) vía `procesar_archivo()` real (PaddleOCR + catálogo real + `ServicioTelemetria`/Onelogis con caché real + `OpenRouteService` real) -- diff verificado byte a byte contra el backup: únicamente esas 2 filas cambian, las 17 restantes quedan idénticas. Reporte regenerado en `output/reporte_desktop_20260812_190025_patentes_p4/`; `config_usuario.json` del Desktop actualizado.

### Costo

0 llamadas OCR masivas (misma tanda ya presente localmente). Onelogis: 0 llamadas nuevas para 464631 (reutiliza caché de O2); 464550 generó su primera consulta real (nunca antes gateada). ORS: 2 llamadas de ruta (una por guía reprocesada).

---

## 2026-08-12 — Cierre: ORIGEN O2 (planta por ventana real de carga, no por presencia en el día)

**Rama:** `lector-mvp-guia-nueva` · **Baseline:** `e7f5a82` (PLANTAS P3).

### Decisión de negocio

`hora_entrada_aza`/`hora_salida_aza` (tiempos reales registrados en planta para ESA carga) son ancla temporal fuerte: la planta de origen se determina por dónde hubo evidencia GPS real DENTRO de `[hora_entrada, hora_salida]`, no por cualquier presencia del vehículo en cualquier momento del día. Una visita a otra planta fuera de esa ventana nunca produce conflicto contra la planta donde ocurrió la carga real.

### Fase C -- causa raíz de por qué T3 perdía paradas reales (bug real, 464424)

`detectar_detenciones` (T3) agrupaba por TRIP: un trip completo era "estacionario" solo si su primer y último punto quedaban cerca entre sí. Con evidencia real (464424, SB6486): el trip 30550165 recorre 29,79 km en total, pero contiene una parada real de ~15-18 min en el medio (velocidad GPS 0-16 km/h) entre una aproximación y una salida a 20-51 km/h -- el trip COMPLETO nunca se detiene de punta a punta, así que T3 nunca la detectaba. Reescrito para agrupar la secuencia COMPLETA y ordenada de breadcrumbs (de todos los trips en la ventana, cruzando límites de trip) en clusters espacio-temporales: un cluster se extiende mientras cada punto nuevo quede a `RADIO_COHERENCIA_DETENCION_KM` (0,6 km) del CENTROIDE corriente del cluster (no un punto fijo -- una detención real de decenas de minutos puede derivar lentamente dentro del mismo patio, comparar contra un punto ya lejano rompía el cluster de a poco). Exige ≥2 puntos por cluster (un solo breadcrumb nunca prueba permanencia).

Segundo filtro real, `VELOCIDAD_MAXIMA_DETENCION_KMH = 18.0` (calibrado con evidencia real: dentro de la parada confirmada de 464424 la velocidad nunca superó 16 km/h; en la aproximación/salida ya estaba en 20-51 km/h): un punto con velocidad reportada por encima del umbral nunca abre ni extiende un cluster -- sin este filtro, el tramo de aproximación/salida (lento pero espacialmente cercano) "puenteaba" dos paradas reales distintas en un cluster diluido. Si el proveedor no informa velocidad (`None`), no bloquea nada -- solo el criterio espacial.

**Bug real encontrado y corregido durante la validación:** `_resolver_planta_para_detencion` recibía "todos los breadcrumbs de los trips tocados por la detención" en vez de los puntos REALES del cluster -- diluía la proporción dentro/fuera con puntos de aproximación/salida ajenos al cluster. `DetencionTelemetria` gana un campo `puntos` (los puntos reales del cluster) para que esto ya no dependa de reconstruir aproximaciones.

### Fase A/C -- `EvidenciaOrigenPlanta` y score (nuevo modelo, `atlas_core/telemetria/modelos.py`)

Por cada planta candidata: `duracion_dentro_min` (solape de sus detenciones con la ventana documental), `porcentaje_ventana`, `porcentaje_puntos`, `entrada_gps`/`salida_gps`, `estadias`, `score`, `motivos`. Score (pesos suman 1.0, ver `PESO_*` en `seleccion_recorrido.py`): 0,50 solape con la ventana + 0,20 continuidad (una sola permanencia real vs. muchos toques fragmentados) + 0,15 proximidad de salida GPS a `hora_salida` + 0,15 proximidad de entrada GPS a `hora_entrada` (decae linealmente a 0 a partir de 60 min de diferencia). Evidencia de breadcrumbs sueltos (Fase I de T3) se incorpora con la MISMA vara de medir -- agrupada por proximidad TEMPORAL real (`GAP_MAXIMO_MIN_PREDETERMINADO`, ya calibrado en T2) para no fusionar dos toques separados por una hora+ en una sola "detención sintética" (bug real encontrado con 463630: dos pases por carretera a 88 km/h, 08:03 y 09:42, se fusionaban en un supuesto span de 99 minutos).

### Fase D -- conflicto real vs. margen suficiente

`MARGEN_SCORE_SUFICIENTE = 0.15`: con 2+ plantas candidatas, si la líder saca esa ventaja o más sobre la siguiente, se confirma con margen amplio; si no, `ORIGEN_GPS_CONFLICTO` explícito (`CONFLICTO_REAL_EN_VENTANA`, con el score y solape de cada una en el motivo). Una detención real y sustancial ya no puede ser invalidada por un breadcrumb aislado de otra planta (comportamiento de T3 corregido) -- pierde por margen, no crea un conflicto automático.

### Fase H -- una hora o ninguna

Con solo una hora documental: ventana = ancla ± `MARGEN_VENTANA_UNA_HORA_MIN` (= `GAP_MAXIMO_MIN_PREDETERMINADO`, 90 min, reutiliza una constante ya calibrada en vez de inventar un número nuevo). Sin ninguna hora: se abstiene igual que siempre (`SIN_HORA_DOCUMENTAL`), sin cambios.

### Hallazgo real que excede el alcance original (consultado con el usuario antes de aplicar)

Al validar contra los 10 casos de conflicto de P3 y contra 464424, la evidencia GPS real de "Renca" en TODOS los casos (incluidos 463630 y 463594, confirmados desde TELEMETRÍA T1, el primer bloque de esta línea de trabajo) resultó ser un cruce por la vía pública cercana a 64-88 km/h -- nunca una detención real -- mientras que en TODOS existe una detención real (45 min-2h+) en el mismo recinto de Colina. Se consultó explícitamente antes de aplicar esta conclusión ampliamente (ver Fase H del bloque, "Renca debe seguir funcionando"): se confirmó que NINGUNA guía de esta tanda real tenía, antes de este bloque, una detención real confirmada en Renca (todas las confirmaciones previas de Renca en esta tanda -- salvo 464424, ya corregido a Colina por decisión explícita -- ya estaban marcadas `CONFLICTO` desde P3, no eran evidencia "limpia" que este bloque estuviera rompiendo). Se aplicó el resultado de O2 a los 19 documentos de la tanda. **Pregunta abierta, no resuelta en este bloque:** si AZA RENCA necesita su propia geocerca poligonal (como Colina en P3) para capturar dónde realmente se detienen los camiones, o si esta tanda real específicamente no incluye cargas en Renca -- no se tocó la geocerca de ninguna planta (Fase K del bloque).

### Datos reales (Fase N)

Respaldo previo (`analisis_completo_guias_PRE_O2_20260812_175004.csv`). Reproceso de la tanda completa (19 guías). Reporte en `output/reporte_desktop_20260812_175433_origen_o2/`; `config_usuario.json` actualizado. Rutas recalculadas desde el origen corregido (Fase J, mecanismo ya existente de R1/T3, sin código nuevo): 464424 pasa de 16,73 km (desde Renca) a 30,77 km (desde Colina, `punto_ruteo` real); 463630 pasa de 536,70 km a 549,73 km; 464700 pasa de 505,08 km a 518,10 km.

### Tests

12 nuevos en `tests/test_origen_o2.py`: visita fuera de ventana no afecta la planta dentro (ambos sentidos); ambas plantas dentro de la misma ventana es conflicto real; estadía prolongada domina sobre punto aislado; salida de geocerca cerca de `hora_salida` corrobora; patrón real 464641/642 (sin hardcodear el número de guía); parada real en medio de un trip largo se detecta (patrón 464424, sin hardcodear); multiguía; una sola hora usa margen simétrico; sin ninguna hora se abstiene; cambio de planta recalcula la ruta desde el `punto_ruteo` correcto; no regresión (suite completa). Suite: 849 → **861 passed**, 0 regresiones de código.



## 2026-08-12 — Cierre: PLANTAS P3 (geocercas operacionales poligonales + corrección real de AZA COLINA)

**Rama:** `lector-mvp-guia-nueva` · **Baseline:** `469cecb` (TELEMETRÍA T3).

### Decisión de producto (contexto)

Javier confirmó visualmente en Onelogis, para AL1879 (464641/464642), que la ubicación de la detención de T3 ("Gerdau Aza, Lampa") ES el recinto operacional real de AZA COLINA (acceso, estacionamientos, oficinas, zonas de carga) -- un punto+radio de 1,5 km nunca puede representar bien un complejo real amplio. Explícito: no crear "AZA LAMPA" -- es la misma planta, con nomenclatura cartográfica de apoyo.

### Fase B -- modelo de geocerca (backward-compatible)

`atlas_core/catalogo_plantas.py`: `Planta` gana `tipo_geocerca` (`TipoGeocerca.CIRCULAR|POLIGONAL`, default `CIRCULAR`) y `vertices: tuple[tuple[float,float],...]` (default `()`), agregados AL FINAL del dataclass. `desde_dict()` ya no exige coincidencia EXACTA de campos -- calcula `faltantes`/`desconocidos` contra `Planta.CAMPOS_OPCIONALES_LEGADO` y rellena los opcionales ausentes con su default (`registro antiguo sin tipo_geocerca/vertices/punto_ruteo_* -> CIRCULAR, comportamiento sin cambios`); campos realmente desconocidos siguen rechazándose (protección contra corrupción). `_validar_geocerca()`: CIRCULAR nunca trae vértices; POLIGONAL exige ≥3. `crear()`/`editar()` aceptan los campos nuevos.

`atlas_core/rutas/geocerca.py`: nueva `punto_en_poligono()` (ray casting determinista sobre lat/lon como plano local -- válido a escala de un recinto real de cientos de metros, sin dependencia GIS). `resolver_planta_por_posicion()` reescrito para separar candidatas POLIGONALES (contención real) de CIRCULARES (distancia/radio, comportamiento intacto) -- un match poligonal junto con cualquier otro es ambigüedad real (no hay medida común de desempate); con solo candidatas circulares, la regla de desempate original (más cercana gana, empate exacto = ambiguo) queda sin tocar.

### Fase C -- polígono real de AZA COLINA (evidencia, no el dibujo de Javier)

Fuente de los vértices: envolvente convexa (10 vértices, algoritmo monótono de Andrew) de los 117 breadcrumbs reales de la detención de T3 (AL1879, 11-08-2026, 08:48:58-14:57:22), reutilizando la caché ya existente -- **0 llamadas nuevas a Onelogis**. Validación cartográfica independiente (ORS/Pelias, 2 métodos): reversa de cada vértice → "Gerdau Aza, Lampa"; búsqueda directa de "Avenida Presidente Eduardo Frei Montalva, Lampa" → coincide (confianza 1.0) a 0,2-0,3 km del polígono; búsqueda de "Ruta 5" → "Cruce Ruta 5 - Av. Américo Vespucio/Costanera Norte" real a ~0,4-0,65 km. Confirma que el recinto linda directamente con la vía que Javier describió.

### Fase E -- jerarquía de evidencia con polígonos (2 correcciones reales durante la validación)

1. **Bug real:** `detectar_entrada_salida_planta()` (chequeo por punto SUELTO, usado como evidencia media/alta) aceptaba un match POLIGONAL de un solo breadcrumb -- un camión que solo ATRAVIESA la vía pública junto al polígono (caso real: SB6486 cruzando en un trip de 30 km) dejaba puntos sueltos "dentro" sin haberse detenido nunca. Corregido: plantas POLIGONALES quedan EXCLUIDAS de este chequeo por punto aislado -- solo se confirman por una detención real (mayoría de puntos, `_resolver_planta_para_detencion`, nueva función: proporción de puntos de la detención dentro del polígono, `PROPORCION_MINIMA_DENTRO_POLIGONO=0.5`, "mayoritariamente" literal, nunca 100%).
2. **Hallazgo real durante el reproceso completo (no un bug, una ambigüedad real):** 10 guías de la tanda que ya confirmaban AZA RENCA limpio (463594, 463630, 464534/535, 464588, 464601, 464624, 464698/699/700) también muestran detenciones reales (68-98% de puntos dentro, 32min-2h+) en el mismo polígono, en fechas distintas -- se consultó con el usuario (decisión de alto impacto): mantener el polígono tal cual (confiar en la evidencia visual de Javier para AL1879) y dejar estos casos en `ORIGEN_GPS_CONFLICTO` explícito para revisión manual, en vez de forzar Renca o ajustar el polígono a ciegas. Motivo legible: `CONFLICTO_AZA_COLINA_VS_AZA_RENCA(estadia_en=...;breadcrumb_aislado_en=...)`.

### Fase I -- `punto_ruteo` (separado del polígono y de la dirección, decisión explícita del usuario)

`Planta` gana `punto_ruteo_latitud`/`punto_ruteo_longitud` (opcionales, `None` default). Nueva `coordenada_ruteo_planta(planta)` en `geocerca.py`: usa `punto_ruteo_*` si la planta lo trae, si no cae a `latitud`/`longitud` exactamente como siempre (fallback explícito para toda planta sin punto de ruteo propio). Reemplaza los 3 usos directos de `Coordenadas(planta.longitud, planta.latitud)` como origen de ruta (`destino_entrega.py` ×2, `enriquecimiento_viaje.py` ×1) -- Renca sigue usando su único punto de siempre (fallback). Para AZA COLINA: `punto_ruteo` = el breadcrumb real más cercano (0,303 km) a "Avenida Presidente Eduardo Frei Montalva" real -- nunca el centroide del polígono ni la coordenada histórica ya demostrada imprecisa (18,4 km fuera del recinto).

### Catálogo real (`plantas.json`)

AZA COLINA: `tipo_geocerca=POLIGONAL`, 10 vértices reales, `punto_ruteo_latitud/longitud` nuevos: `latitud`/`longitud` (dirección histórica) **sin cambios**. Observación documenta fuente de vértices, validación cartográfica, decisión de no crear "AZA LAMPA", alias asociados ("Gerdau Aza", "Av. Pdte. Eduardo Frei Montalva, Colina/Lampa", "Panamericana Norte 18500"), y el propósito del `punto_ruteo`. AZA RENCA: sin cambios (`CIRCULAR`, sin vértices, sin `punto_ruteo` -- Fase H).

### Datos reales (Fase M)

Respaldo previo (`analisis_completo_guias_PRE_P3_20260812_161332.csv`). Reproceso de la tanda completa (19 guías, mismo criterio de esquema consistente que R1.1/T3). Reporte en `output/reporte_desktop_20260812_162735_plantas_p3/`; `config_usuario.json` actualizado. Ruta real recalculada desde el nuevo `punto_ruteo`: 464577 (TG8925) → AZA COLINA → Galvarino 8501, Quilicura, 13,18 km / 19,06 min (RUTA_CALCULADA) -- confirma que el punto de acceso real, no el centroide ni la dirección antigua, es el que efectivamente alimenta ORS.

### Tests

12 nuevos en `tests/test_plantas_p3_geocercas_poligonales.py`: point-in-polygon dentro/fuera/borde (sin lanzar); planta circular legado (sin `tipo_geocerca`/`vertices`) sigue funcionando igual; estadía mayoritaria dentro confirma; maniobra parcial en el borde no impide confirmar (mayoría, no 100%); dos plantas en conflicto vía detenciones; tránsito aislado por el polígono NO confirma sin detención real (regresión del bug de Fase E); multiguía comparte la misma planta; Renca circular sin regresión; ningún alias cartográfico crea una planta nueva; cambio de planta usa el `punto_ruteo` real, nunca el centroide ni el histórico. Suite completa: 837 → **849 passed**, 0 regresiones de código (10 conflictos nuevos son un hallazgo real de datos, documentado, no un bug).



## 2026-08-12 — Cierre: TELEMETRÍA T3 (origen por detenciones/estadías GPS, no solo breadcrumbs sueltos)

**Rama:** `lector-mvp-guia-nueva` · **Baseline:** `aa1b5bb` (OPERACIÓN REAL R1.1).

### Contradicción real que motivó el bloque

R1.1 concluyó `ORIGEN_GPS_NO_DETERMINADO` para AL1879 (464641/464642, 11-08-2026). Javier revisó la UI de Onelogis y vio al vehículo detenido varias horas en "AVENIDA PRESIDENTE EDU...", con confirmación directa de los choferes de que el viaje salió de AZA COLINA. Se investigó la contradicción sin asumir que Javier estaba equivocado ni que la API carecía de evidencia.

### Fase A -- releído `openapi.yaml` real (WebFetch, 2026-08-12)

Confirma lo ya documentado en T1: `Trip` no trae coordenadas de inicio/fin ni dirección (`trip_id, plate, start_time, end_time, distance_km, max_speed, idle_minutes, type`); no existe endpoint de "stops"/detenciones. `BreadcrumbPoint`/`Position` sí traen `event` (valores reales observados: `ENGINE_ON`, `ENGINE_OFF`, `PERIODIC_ON`). La única evidencia de permanencia disponible es indirecta: trips con desplazamiento neto ~0 (ignition-cycling sin movimiento real) y los huecos SIN telemetría entre trips consecutivos cuyos extremos son espacialmente coherentes.

### Fase B/C -- causa raíz real (no una limitación de la API)

Traza completa (sin filtro de distancia) de AL1879, 11-08-2026: 11 trips entre 05:56 y 14:57. Un hueco de **3h08min** entre el trip que termina a las 10:22 y el que empieza a las 13:30 -- con extremos coherentes (~30m de diferencia) -- es evidencia fuerte de permanencia continua. Encadenando TODOS los trips con extremos coherentes entre sí (incluidos los de desplazamiento neto ~0), la permanencia real cubre **08:48:58 → 14:57:22 (6h08min)**, solapando casi todo el rango documental (09:46-14:39).

### Fase E -- auditoría de coordenadas (hallazgo principal del bloque)

La coordenada de esa detención (-33.2947, -70.7281) geocodifica -- dos veces, con métodos independientes (reversa y directa, vía Pelias/ORS) -- como **"Gerdau Aza, Lampa, RM, Chile"** (confianza 0.6-0.8, capa `venue`). Gerdau es la matriz de Aceros AZA; el mismo buscador devuelve por separado "Gerdau, Renca" coincidiendo exacto con el catálogo, y "Gerdau AZA Antofagasta" como tercer sitio conocido. Todo indica una planta AZA real en Lampa, no catalogada, distinta de Colina (18,4 km) y de Renca (12,5 km). **Se consultó al usuario antes de tocar el catálogo** (decisión de alto impacto, no reversible sin más evidencia): se optó por NO agregarla todavía -- el modelo nuevo debía poder reportar la detención honestamente sin nombrarla, no por asumir que es Colina ni inventar un nombre de planta nuevo.

### Cambios de código

- **`atlas_core/telemetria/modelos.py`**: nuevo `DetencionTelemetria` (inicio, fin, duracion_minutos, latitud, longitud, fuente, trip_ids) -- sin depender de `atlas_core.rutas` (mismo criterio que `PosicionTelemetria`).
- **`atlas_core/telemetria/seleccion_recorrido.py`**:
  - `ORIGEN_GPS_ESTADIA_SIN_PLANTA` (nuevo estado): hay una detención GPS real y prolongada, pero su coordenada no cae en ninguna geocerca catalogada -- nunca se le asigna nombre de planta.
  - `ResultadoOrigenGPS` gana `latitud_estadia`/`longitud_estadia`/`duracion_estadia_min` (solo poblados en ese estado).
  - `RADIO_COHERENCIA_DETENCION_KM = 0.6` (calibrado con el caso real: puntos del mismo lugar de permanencia varían 0.02-0.4 km entre sí) y `DURACION_MINIMA_DETENCION_MIN = 30.0` (paradas más cortas son ruido de maniobra, no evidencia operacional).
  - `detectar_detenciones(viajes, breadcrumbs_por_trip)`: encadena trips (y sus huecos de telemetría) cuyos extremos son espacialmente coherentes -- un trip es "estacionario" cuando su propio primer y último breadcrumb quedan a `radio_coherencia_km` uno de otro. Exige **al menos 2 breadcrumbs** por trip para juzgar estacionariedad (un solo punto no prueba nada -- podría ser una foto instantánea de un trip real disperso).
  - `resolver_planta_origen_gps` reescrito: (1) la ventana temporal ahora cubre `[min(entrada,salida), max(entrada,salida)] ± margen_horas` -- antes anclaba solo en `hora_salida` (o `hora_entrada` si faltaba), lo que en casos reales con las dos horas muy separadas (464641/642: 09:46 y 14:39, casi 5h) dejaba fuera trips reales cerca de la otra hora; (2) jerarquía de evidencia (Fase I): detención dentro de geocerca (evidencia máxima, con `solape_documental_min` calculado contra las horas documentales) > breadcrumbs sueltos que pasan por geocerca (comportamiento de R1, sin cambios) > detención real sin planta catalogada (`ORIGEN_GPS_ESTADIA_SIN_PLANTA`, nunca silenciada) > sin evidencia; (3) cruza SIEMPRE la detención confirmada contra el escaneo de breadcrumbs sueltos -- si señalan una planta DISTINTA, es `ORIGEN_GPS_CONFLICTO` explícito, nunca se ignora la señal más débil.
- **`atlas_core/telemetria/enriquecimiento.py`**: `CAMPOS_TELEMETRIA_DOCUMENTO` pasa de 9 a 13 campos (+ `motivo_origen_gps`, `latitud_estadia_gps`, `longitud_estadia_gps`, `duracion_estadia_gps_min`).
- **`atlas_core/procesamiento_masivo.py`**: la rama que limpia el fallback documental (R1.1) ahora también dispara con `ORIGEN_GPS_ESTADIA_SIN_PLANTA` (antes solo `CONFLICTO`/`NO_DETERMINADO`) -- una detención sin planta catalogada tampoco debe dejar "AZA RENCA" del encabezado.
- **`atlas_core/gestor_viajes.py`** / **`atlas_core/reporte_viajes.py`**: propagan los 4 campos nuevos hasta `viajes.csv` (mismo criterio de consolidación "coincide en todos los documentos o vacío").

### Resultado real (Fase F/G/H)

- **464641/464642 (AL1879)**: `ORIGEN_GPS_ESTADIA_SIN_PLANTA` -- detención real de 368,4 / 286,3 min (según la hora documental disponible en cada guía) en (-33.2949, -70.7285) aprox., trips `30585346|30586520|30586682|30586909|30590516|...`. Nunca Renca, nunca Colina sin evidencia.
- **464424 (SB6486)**: sin cambios -- sigue `ORIGEN_GPS_CONFIRMADO`/AZA RENCA, ahora validado también contra el modelo de detenciones (mismo resultado, evidencia más rica).
- **Efecto colateral real del fix de ventana (Fase H)**: 464534/464535 (BDFG50, antes sin planta confirmada) ahora resuelven `ORIGEN_GPS_CONFIRMADO`/AZA RENCA -- la evidencia ya existía, la ventana anterior no llegaba a mirarla.

### Datos reales (Fase K/L)

Respaldo previo (`analisis_completo_guias_PRE_T3_20260812_145913.csv`). Reproceso focal (3 guías) validado, luego reproceso de la tanda completa (19 guías, mismo criterio que R1.1 -- todas comparten el esquema de columnas). CSV maestro reemplazado; reporte regenerado en `output/reporte_desktop_20260812_150552_telemetria_t3/`; `config_usuario.json` de Desktop actualizado. Ninguna ruta se recalculó hacia Colina (sin confirmación); las guías que ganaron confirmación de Renca (464534/535) se benefician del cálculo de ruta automático ya existente en `procesamiento_masivo.py` (sin código nuevo).

### Tests

12 nuevos en `tests/test_telemetria_t3.py`: detención encadenada entre trips en la misma posición; estadía dentro de geocerca confirma planta; solape con hora documental se registra en el motivo; salida real (movimiento) corta la cadena de detención; endpoint sin breadcrumbs se ignora sin lanzar; un solo breadcrumb nunca se considera estacionario; validación positiva de que el mecanismo SÍ confirma Colina con evidencia real (no hardcodeado); multiguía comparte la misma resolución; nunca cae a Renca por defecto aunque haya estadía real fuerte; conflicto explícito entre estadía confirmada y breadcrumb aislado de otra planta; la caché de breadcrumbs se reutiliza para detectar detenciones sin llamadas nuevas; no regresión (verificada con la suite completa). `tests/test_operacion_real_r1.py` (1 aserción actualizada -- comportamiento mejorado, ver test) y `tests/test_procesamiento_masivo.py` (conjunto de columnas, mecánico). Suite completa: 825 → **837 passed**, 0 regresiones reales.



## 2026-08-12 — Cierre: OPERACIÓN REAL R1.1 (eliminar fallback documental sin confirmación GPS)

**Rama:** `lector-mvp-guia-nueva` · **Baseline:** `2ec64c9` (OPERACIÓN REAL R1).

### Decisión de alcance (consultada explícitamente antes de implementar)

R1.1 pedía eliminar "GPS no determinado + encabezado dice Renca → AZA RENCA" sin especificar si el cambio debía aplicar solo al punto donde corre el bug (telemetría conectada y corrida) o a todo el pipeline (incluyendo cuando no hay telemetría en absoluto, lo que habría tocado `resolver_origen_documental`/`resolver_planta_origen` y ~15 archivos de test existentes que validan ese fallback como comportamiento intencional para arquitectura sin GPS). Se preguntó al usuario; eligió el alcance acotado: el fix vive únicamente en `procesamiento_masivo.py`, en el punto exacto donde el bug ocurre.

### Investigación real (Fase A/B/C/D) antes de tocar código

Traza GPS completa (sin filtro de distancia, múltiples días) para los 2 controles positivos que Javier señaló:

- **464424 / SB6486 (07-08-2026):** 2 trips ese día pasan a 1,14 km y 1,21 km de AZA RENCA -- dentro de la geocerca de 1,5 km. Nunca a menos de 17,7 km de AZA COLINA. Se revisó también el día anterior (06-08-2026): el mismo patrón se repite 4 veces más (0,15-1,2 km de RENCA, 17,7-29 km de COLINA). **Conclusión: la evidencia GPS real, repetida en 2 días, indica RENCA, no Colina, para este vehículo/fecha específicos.** Esto contradice la observación de Javier sobre esta guía puntual -- se reporta así, sin forzar ninguna de las dos plantas artificialmente (ni Colina porque Javier lo dijo, ni descartar su observación como error).
- **464641/464642 / AL1879 (11-08-2026):** revisados TODOS los trips del día (11 tramos, 05:56-14:57), no solo los cercanos a la hora documental -- ninguno pasa a menos de 10,3 km de RENCA ni de 17,7 km de COLINA. Se revisó también el día anterior (10-08-2026, 6 trips): mismo patrón, el vehículo pasa el día cerca de un punto fijo (~12,5 km de Renca, ~18,3 km de Colina) que no corresponde a ninguna de las dos plantas -- muy probablemente el depósito/base propia del transportista. **Conclusión: no hay evidencia GPS real, en 2 días completos de datos, que confirme ni Renca ni Colina para este transporte.**
- **Causa raíz de por qué R1 no detectó Colina en estos casos:** no es un bug de geocerca, ventana temporal, ni cache -- las coordenadas GPS reales de estos vehículos, en las fechas revisadas, simplemente no pasan cerca de ninguna de las dos plantas. R1 SÍ tenía razón en abstenerse (`ORIGEN_GPS_NO_DETERMINADO`) para AL1879 -- el bug real era que, a pesar de esa abstención correcta, el resultado final seguía mostrando "AZA RENCA" por la razón documental de siempre (ver Fase E).
- **Geocerca de Colina confirmada de nuevo:** no se encontró ningún punto real que pase cerca de Colina y quede fuera del radio por poco -- las distancias mínimas observadas (17,7-29 km) descartan que sea un problema de radio insuficiente.

### Cambio de código (Fase E)

`atlas_core/procesamiento_masivo.py::procesar_archivo` -- nueva rama `elif` justo después de la que aplica `ORIGEN_GPS_CONFIRMADO`: si `estado_telemetria == EstadoSeleccionRecorrido.SELECCIONADO` (la telemetría corrió sobre datos reales, no un fallo de conexión/credencial) y `origen_gps` es `ORIGEN_GPS_CONFLICTO` o `ORIGEN_GPS_NO_DETERMINADO`, se limpian `planta_origen_id`/`planta_origen_nombre`/`origen_determinado_por`/`evidencia_origen` y se invalida cualquier ruta (`distancia_km`/`duracion_min`/`proveedor_ruta`/`estado_ruta="ORIGEN_NO_DETERMINADO"`/`motivo_ruta`) que hubiera quedado calculada desde el origen documental descartado. `despachar_a_crudo`/`direccion_entrega`/`localidad_entrega`/`region_entrega`/`estado_entrega` (destino) nunca se tocan -- siguen siendo independientes del origen. Si `servicio_telemetria` es `None`, o el proveedor no pudo ni conectar (`SIN_CREDENCIAL`, `VEHICULO_NO_ENCONTRADO`, etc. -- `estado_telemetria` distinto de `SELECCIONADO`), el comportamiento documental de siempre no cambia.

Imports nuevos: `EstadoSeleccionRecorrido` (`atlas_core.telemetria.modelos`), `ORIGEN_GPS_CONFLICTO`/`ORIGEN_GPS_NO_DETERMINADO` (ya existían en `seleccion_recorrido.py`, ahora también importados aquí).

### Datos reales (Fase L/H)

Respaldo previo (`analisis_completo_guias_PRE_R1_1_20260812_141342.csv`). Reproceso focal de las 3 guías señaladas (464424, 464641, 464642) primero, validado; luego reproceso de la tanda reciente completa (19 guías reales -- creció de 9 a 19 porque Javier ingresó más guías vía Desktop entre R1 y R1.1) para aplicar el fix consistentemente (Fase H). Reporte regenerado en `output/reporte_desktop_20260812_142001_operacion_real_r1_1/`; `config_usuario.json` de Desktop actualizado.

**Clasificación final de la tanda (19 guías):** `RENCA_CONFIRMADA_GPS` (`origen_gps=ORIGEN_GPS_CONFIRMADO`, `origen_determinado_por=TELEMETRIA_GPS`) -- 464424, 464588, 464601, 464624, 464698, 464699, 464700, 463594, 463630 (9). `ORIGEN_GPS_NO_DETERMINADO` (planta vacía, antes mostraban Renca por el bug) -- 464522, 464529, 464534, 464535, 464577, 464640, 464641, 464642 (8). `AZA RENCA` por `DOCUMENTO` (sin patente legible, telemetría nunca corrió) -- 464550, 464631 (2). Ningún caso de `AZA COLINA` confirmada ni de `ORIGEN_GPS_CONFLICTO` en esta tanda.

### Tests

7 nuevos en `tests/test_operacion_real_r1_1.py`: GPS confirma Colina si la evidencia lo sustenta (mecanismo general validado con datos sintéticos); GPS no determinado limpia la planta del encabezado (integración real vía `procesar_archivo`, con mocks de OCR/telemetría/rutas); sin telemetría conectada conserva el comportamiento documental previo (fija el límite del alcance elegido); ruta previa se invalida si GPS deja de confirmar; caché solo guarda datos crudos, nunca una selección derivada (por eso cambiar la lógica de resolución nunca reutiliza una selección vieja incorrecta); multiguía -- ambos documentos del mismo transporte quedan consistentemente sin planta; Renca confirmado sigue funcionando (regresión explícita del camino mayoritario). Suite completa: 818 → **825 passed**, 0 regresiones.



## 2026-08-12 — Cierre: OPERACIÓN REAL R1 (origen por GPS, no por letterhead)

**Rama:** `lector-mvp-guia-nueva` · **Baseline:** `3659740` (E2E R2).

### Decisión

La planta de origen de un viaje Atlas se determina mediante telemetría/GPS y geocercas de plantas cuando el proveedor está disponible. La guía no contiene la dirección de origen y no se usa para inferirla. `resolver_origen_documental()` (encabezado impreso) queda como fallback legítimo únicamente cuando no hay evidencia GPS -- nunca se filtra el catálogo de plantas para forzar un match documental sobre una planta ya confirmada por GPS (se evaluó y se descartó: forzaría un fallo del letterhead, que nunca menciona "COLINA").

### Causa raíz

`resolver_origen_documental()` tokeniza el encabezado de la guía y matchea contra el catálogo de plantas -- pero el encabezado de AZA es idéntico ("CASA MATRIZ PLANTA RENCA...") en toda guía, sin importar la planta real de despacho: resuelve a AZA RENCA siempre, nunca genuinamente a COLINA. No era un problema de prioridad GPS-vs-documento (la prioridad ya estaba bien diseñada) sino de que el chequeo GPS casi nunca llegaba a correr sobre el origen: (a) `resolver_entrega_documento()`/`calcular_ruta_entrega_para_viaje()` no reciben `patente`/`instante_salida` en el camino normal, así que la rama GPS de `resolver_planta_origen()` nunca tenía datos con los que trabajar; (b) en T2, la detección de origen GPS vivía DENTRO de la rama de éxito de `seleccionar_recorrido_operacional` (que exige un tramo "sustancial", `distancia_km >= 5.0`), así que un viaje de maniobra corto que sí pasa por la geocerca de la planta quedaba fuera del análisis.

### Cambios

- **`atlas_core/telemetria/seleccion_recorrido.py`**: nueva `resolver_planta_origen_gps(servicio, *, patente, fecha, hora_entrada, hora_salida, plantas, radio_km=1.5, margen_horas=4.0) -> ResultadoOrigenGPS`. Independiente de `seleccionar_recorrido_operacional`: toma como ancla `hora_salida` o `hora_entrada`, reúne TODOS los trips de Onelogis del día cuyo rango se solapa con `[ancla-4h, ancla+4h]` (sin filtro de distancia -- capta maniobras cortas), pide TODOS sus breadcrumbs y llama `detectar_entrada_salida_planta` sobre el conjunto completo. `margen_horas=4.0` calibrado contra el mayor hueco real observado hasta ahora (~2h48m, guía 463630) con margen amplio.
- **`atlas_core/telemetria/enriquecimiento.py`** (reescrito): `enriquecer_documento_con_telemetria()` ahora resuelve origen (`resolver_planta_origen_gps`) y recorrido de entrega (`seleccionar_recorrido_operacional`, para desambiguar destino) como dos preocupaciones separadas -- antes, el origen dependía de que el recorrido de entrega tuviera éxito. `CAMPOS_TELEMETRIA_DOCUMENTO` pasa de 7 a 9 campos (+ `planta_gps_id`, `planta_gps_nombre`).
- **`atlas_core/rutas/destino_entrega.py`**: nueva `calcular_ruta_con_planta_conocida(*, planta, despachar_a_crudo, proveedor_rutas, origen_determinado_por="TELEMETRIA_GPS", evidencia_origen="", perfil="driving-hgv", punto_gps_destino=None, radio_gps_destino_km=50.0) -> ResultadoRutaEntrega`. Reutiliza la geocodificación/ORS de `calcular_ruta_entrega_para_viaje` pero se salta `resolver_planta_origen()` -- la planta ya se conoce con certeza (GPS), y volver a derivarla del letterhead fallaría siempre para COLINA.
- **`atlas_core/procesamiento_masivo.py`**: el bloque de telemetría en `procesar_archivo()` se reescribió: (1) intenta origen GPS SIEMPRE que haya `servicio_telemetria` + patente + fecha + al menos una hora (antes: solo si el origen documental "no se había determinado", condición casi nunca verdadera porque el letterhead siempre resuelve algo); (2) si `origen_gps == ORIGEN_GPS_CONFIRMADO`, sobreescribe `planta_origen_id`/`planta_origen_nombre`/`origen_determinado_por="TELEMETRIA_GPS"`/`evidencia_origen`; (3) si la planta efectivamente CAMBIÓ, invalida y recalcula la ruta vía `calcular_ruta_con_planta_conocida()` (o limpia `distancia_km`/`duracion_min` si no hay `despachar_a_crudo` o coordenadas) -- nunca reutiliza una ruta calculada desde el origen equivocado (Fase I). El reintento de destino ambiguo (`MULTIPLES_UBICACIONES_DISPERSAS`) también migra a `calcular_ruta_con_planta_conocida()`.
- **`atlas_core/extractor.py`**: `_despachar_a_lineal_contaminado()` gana un segundo chequeo -- si el valor lineal completo es un RUT chileno con dígito verificador válido (`validar_rut_chileno`), se trata como contaminado igual que una etiqueta estructural conocida, disparando el fallback geométrico. Bug real encontrado en la tanda nueva: 464631/464641 mostraban `despachar_a_crudo` = un RUT ("14293816-2"/"10833150-K") en vez de la dirección real -- el chequeo anterior solo detectaba ETIQUETAS (p. ej. "PATENTE"), no VALORES de otro campo.
- **`atlas_core/gestor_viajes.py`** / **`atlas_core/reporte_viajes.py`**: propagan `planta_gps_id`/`planta_gps_nombre` (documento → `Viaje` consolidado, mismo criterio "coincide en todos los documentos o vacío" que O1 → CSV de viajes).
- **`analizar_guias_masivo.py`**: construye `ServicioTelemetria(OnelogisProvider(), RepositorioTelemetria(carpeta_catalogos/telemetria_cache.json))` por defecto cuando hay catálogos y no se pasa `--sin-telemetria` -- antes, el CLI real que usa Atlas Desktop (`main.js` invoca este script directo) nunca conectaba telemetría; toda la corrección de origen GPS de este bloque, aunque correcta en el motor, no llegaba al flujo real de Javier hasta este cambio. `OnelogisProvider()` lee la credencial por sí mismo desde `ATLAS_ONELOGIS_API_KEY` (nunca se imprime/guarda en el CLI); sin credencial, cada consulta se abstiene con `SIN_CREDENCIAL` sin romper el procesamiento documental.

### Geocercas (Fase D)

Coordenadas de AZA RENCA (`LA UNIÓN 3070, RENCA`, lat -33.401595, lon -70.685226) y AZA COLINA (`AV. PDTE. EDUARDO FREI MONTALVA 18500, COLINA`, lat -33.137558, lon -70.665977) en el catálogo real: correctas, confirmadas por el usuario, **no se tocaron** ("no cambiar catálogo si ya está correcto"). Investigación real con ORS: geocodificar "AV. PDTE. EDUARDO FREI MONTALVA 18500, COLINA" devuelve un único candidato a 16.4 km de la coordenada guardada (confianza 0.8, sin precisión de numeración); geocodificar "PANAMERICANA NORTE 18500, COLINA" devuelve un candidato EXACTAMENTE en la coordenada guardada (distancia 0.000 km) más un segundo candidato ambiguo a 7.3 km. Conclusión: la coordenada guardada casi seguro se geocodificó originalmente desde el texto "Panamericana Norte", no desde "Eduardo Frei Montalva" de forma independiente -- ambas direcciones probablemente describen el mismo corredor físico (Av. Pdte. Eduardo Frei Montalva es el nombre oficial de ese tramo de la Ruta 5/Panamericana Norte), pero el geocodificador no tiene precisión de numeración para confirmarlo. Se documenta el hallazgo; no se agrega alias al catálogo en este bloque (no era necesario para resolver ningún caso real de la tanda).

### Datos reales (Fase O)

Respaldo previo en `output/_respaldos_reprocesamiento/` (`analisis_completo_guias_PRE_R1_20260812_131943.csv` + copia completa del reporte `reporte_desktop_20260812_123325`). Reproceso de las 9 guías del dataset operacional (7 nuevas + 463594/463630, que se reprocesan también para no dejar filas con esquema de columnas desactualizado en el mismo CSV -- ambas confirman AZA RENCA sin cambios, ahora con evidencia GPS real en vez de solo letterhead) vía `analizar_guias_masivo.py` con `ATLAS_ONELOGIS_API_KEY`/`OPENROUTESERVICE_API_KEY` inyectadas en el proceso (nunca impresas ni guardadas). CSV maestro reemplazado; `generar_reporte_viajes.py` regeneró `output/reporte_desktop_20260812_133037_operacion_real_r1/`; `config_usuario.json` (Desktop, `%APPDATA%\atlas-viajes-desktop\config_usuario.json`) actualizado para apuntar ahí.

**Resultado real de origen GPS sobre las 7 guías nuevas:** VP8521 (464698-700) → `ORIGEN_GPS_CONFIRMADO`/AZA RENCA (coincide con el documento, ahora con evidencia). TG8925 (464640) y AL1879 (464641-642) → `ORIGEN_GPS_NO_DETERMINADO` (los puntos GPS más cercanos de ese día quedan a 6.6-11.3 km de RENCA y 17.8-18.5 km de COLINA -- fuera de la geocerca de 1.5 km de ambas; se conserva el valor documental sin inventar una confirmación GPS que no existe). 464631 sin patente legible, no evaluable por GPS. Ninguna de las 7 cambia de RENCA a COLINA con la evidencia disponible hoy -- esto no contradice la observación de Javier, solo indica que estas 7 guías puntuales no la prueban con los datos GPS reales recolectados.

### Tests

Suite completa: 806 → **818 passed**. 12 tests nuevos en `tests/test_operacion_real_r1.py` (GPS cerca de Renca/Colina confirma la planta correcta; sin evidencia GPS nunca asume Renca por defecto; GPS ambiguo entre dos plantas no confirma ninguna; ventana amplia no depende solo del primer viaje "sustancial"; detección de entrada/salida de geocerca; caché no contamina otra patente/otro viaje; cambio de planta invalida y recalcula la ruta desde el origen correcto; DESPACHAR A nunca acepta un RUT como dirección, con recuperación geométrica real; multiguía resuelve una única planta física por transporte). `tests/test_procesamiento_masivo.py` actualizado (conjunto de columnas esperado, mecánico). Regresión: 0.



## 2026-08-12 — Cierre: E2E R2 (publicación de logística real en el dataset operacional y Desktop)

**Rama:** `lector-mvp-guia-nueva` · **Baseline:** `514feaa2ffec245ef9675a99f979a44d18bd019a` (TELEMETRÍA T2). **Sin cambios de código en `atlas_core` ni en Desktop** -- este bloque fue de auditoría, regeneración de datos y verificación, no de desarrollo.

### Decisión

La telemetría y ORS ya alimentan automáticamente el dataset operacional consumido por Desktop -- no hacía falta ninguna lógica nueva (Fase A confirmó que todos los campos requeridos ya existían end-to-end desde los bloques E2E R1.1/TELEMETRÍA T1/T2: `planta_origen_nombre`, `despachar_a`, `distancia_km`, `duracion_min`, `estado_ruta`, `motivo_ruta`, `proveedor_telemetria`, `estado_telemetria`, `origen_gps`, `distancia_gps_km` ya recorrían todo el camino documento → `gestor_viajes` → `reporte_viajes` → `viajes.csv`).

### Qué se hizo

Respaldo de la operación actual, luego regeneración focal (solo 463594/463630, motor E2E+T2 completo, sin histórico) de `analisis_completo_guias.csv` y `viajes.csv` en la fuente operacional canónica (`AppData\Local\Atlas\datos\operacion_desktop\` = `Proyecto-Atlas\output\`, mismo junction del Bloque E2E R1.1). `config_usuario.json` (Desktop) actualizado para apuntar al reporte nuevo.

Verificación: se instrumentó el proveedor Onelogis para contar peticiones HTTP reales durante la regeneración -- **0 llamadas nuevas** (toda la telemetría salió de la caché de T1/T2). Se ejecutó `atlas_viajes.html::normalizarFila()` y `formato_operacional.js` REALES (sin modificar Desktop) contra el `viajes.csv` regenerado, vía Node.js directo -- confirma que Desktop, sin ningún cambio de código, ya muestra: Planta origen "AZA RENCA", Destino entrega (DESPACHAR A), Distancia "536,7 km", Tiempo estimado "10 h 07 min", Estado ruta "Ruta calculada" para 463630; y "No disponible"/"Pendiente de revisión" para 463594, sin forzar ningún candidato. Ningún campo técnico de telemetría (trip_id, breadcrumbs, origen_gps) aparece en la UI -- confirmado por búsqueda textual en `atlas_viajes.html`.

`npm start` no pudo abrir una ventana real en este entorno (sin servidor de display) -- limitación del entorno de ejecución, no de Atlas; `npm test` (110 tests, sin necesitar display) sigue verde.

### Tests

806 passed (motor, sin cambios desde T2). Desktop: 110 passed, sin cambios propios de este bloque.

---

## 2026-08-12 — Cierre: TELEMETRÍA T2 (selección automática de recorrido GPS + integración E2E)

**Rama:** `lector-mvp-guia-nueva` · **Baseline:** `dd534c505fe4fa455bef317c10e016a53aa84bd9` (TELEMETRÍA T1).

### Decisión de arquitectura

**Atlas puede construir un recorrido operacional a partir de múltiples trips de telemetría y usarlo como evidencia, sin reemplazar silenciosamente los datos documentales.** Cierra la limitación explícita de T1 ("Atlas todavía NO selecciona automáticamente qué viaje/tramo Onelogis corresponde a una guía Atlas"): nuevo `atlas_core/telemetria/seleccion_recorrido.py` implementa `RECORRIDO_OPERACIONAL_GPS` -- 1..N trips consecutivos, coherentes en tiempo y espacio, tratados como UN viaje logístico real (un viaje Atlas puede quedar fragmentado en varios trips de Onelogis).

### Algoritmo (`seleccionar_recorrido_operacional`)

Puro, sin red -- opera solo sobre metadatos de trip (inicio/fin/distancia) ya obtenidos vía `ServicioTelemetria` (con caché). Ancla temporal: `hora_salida_aza` si existe (evidencia real más fuerte), si no `hora_entrada_aza` (Fase B -- ambas son horas reales registradas en planta, nunca "aproximadas"). Trips "sustanciales" (`distancia_km >= 5.0`, calibrado contra ruido real observado: -0.03 a 1.71 km) se encadenan hacia adelante mientras el hueco temporal entre el fin de uno y el inicio del siguiente sea ≤ 90 min (calibrado contra el único hueco real conocido: 51 min entre los 2 trips de 463630). Ambigüedad real (dos trips sustanciales casi simultáneos) → `TELEMETRIA_AMBIGUA`, nunca se elige arbitrariamente.

Los breadcrumbs completos SOLO se piden para los trips de la cadena ya seleccionada (nunca para toda la flota/día) -- se cachean vía la misma `RepositorioTelemetria` de T1.

### Conectado al pipeline (Fase I/J, opt-in)

`procesamiento_masivo.procesar_archivo()`/`procesar_carpeta()` aceptan `servicio_telemetria` opcional (nunca se construye uno por defecto -- requiere credencial/configuración explícita). Sin él, comportamiento idéntico a antes de este bloque. Con él conectado, se consulta SOLO si: origen sin determinar, o destino con ambigüedad real de geocodificación (`MULTIPLES_UBICACIONES_DISPERSAS`) -- nunca "para todo". `atlas_core/telemetria/enriquecimiento.py` orquesta: selecciona recorrido → detecta planta por geocerca (reutiliza `resolver_planta_por_posicion`, radio 1.5 km ya calibrado desde Bloque PLANTA-P1) → si el destino estaba ambiguo, reintenta `calcular_ruta_entrega_para_viaje` con el punto final GPS real.

Nuevas columnas (backward-compatible, vacías sin telemetría conectada): `proveedor_telemetria`, `estado_telemetria`, `origen_gps`, `hora_entrada_gps`, `hora_salida_gps`, `distancia_gps_km`, `evidencia_telemetria` -- en `procesamiento_masivo.COLUMNAS`, `gestor_viajes.DocumentoViaje`/`Viaje` (consolidación "coincide en todos los documentos o vacío", igual criterio que O1) y `reporte_viajes.COLUMNAS_VIAJES`. Nunca se guardan breadcrumbs completos aquí. `distancia_gps_km` (recorrido real medido) queda siempre separada de `distancia_km` (estimación ORS) -- Fase M.

### Resultado real, 100% automático, sin ningún tripId hardcodeado

- **463630**: recorrido seleccionado = 3 trips (el mismo conjunto identificado manualmente en T1, encontrado aquí sin conocer los IDs de antemano). Origen GPS confirmado (AZA RENCA, ~1.13 km). Destino desambiguado por GPS (Coronel/Biobío vs Coronel/Maule). **ORS desbloqueado automáticamente: 536,70 km / 606,92 min** -- mismo resultado que el reintento manual de T1, ahora producido por el pipeline sin intervención por guía.
- **463594**: recorrido seleccionado = 1 trip. Origen GPS confirmado (AZA RENCA, ~1.04 km). GPS no alcanza a desambiguar entre los 4 candidatos RM restantes -- se mantiene `REQUIERE_REVISION`, sin forzar.

### Archivos nuevos/modificados

`atlas_core/telemetria/seleccion_recorrido.py`, `atlas_core/telemetria/enriquecimiento.py` (nuevos); `atlas_core/telemetria/modelos.py` (`RecorridoOperacionalTelemetria`, `EstadoSeleccionRecorrido`, `EstadoConcordanciaHora`); `atlas_core/procesamiento_masivo.py`, `atlas_core/gestor_viajes.py`, `atlas_core/reporte_viajes.py` (columnas nuevas, opt-in); `tests/test_telemetria_t2.py` (19 tests, sin red).

### Límite conocido, no resuelto en este bloque

La geocodificación ORS (a diferencia de Onelogis, ya bien cacheado) no tiene caché propia en `destino_entrega.py` (limitación documentada desde antes de este bloque) -- cada regeneración del reporte repite las llamadas de geocodificación, aunque no las de telemetría.

### Tests

806 passed (787 previos + 19 nuevos), 0 regresiones. Desktop: sin cambios propios de este bloque.

---

## 2026-08-12 — Cierre: TELEMETRÍA T1 (integración histórica real de Onelogis, multiproveedor)

**Rama:** `lector-mvp-guia-nueva` · **Baseline:** `6afb491235ed60e3745c7d79495204b70cccf497` (E2E R1.1).

### Decisión de arquitectura

**Telemetría es un proveedor opcional y multiempresa. Onelogis es el primer adaptador, no una dependencia del núcleo.** Nuevo paquete `atlas_core/telemetria/` (`modelos.py`, `proveedor.py` — contrato `ProveedorTelemetria` + doble simulado, `servicio.py` — caché, `repositorio.py` — persistencia JSON simple, `proveedores/onelogis.py` — adaptador HTTP real). El núcleo (extractor/rutas/gestor_viajes/Desktop) nunca importa `proveedores/onelogis.py` directamente. `proveedor_telemetria=None` es un caso de primera clase en todo el pipeline: ausencia de GPS nunca rompe Atlas.

Contrato leído completo del OpenAPI real (`https://app.onelogis.com/docs/api/openapi.yaml`), sin adivinar parámetros — resumen fuera del repo en `telemetria_eval/fase_a_openapi_resumen.md`. Base URL real: `https://app.onelogis.com/api/client/v1`. Auth: `Authorization: Bearer <ATLAS_ONELOGIS_API_KEY>` (nunca logueado, nunca persistido, nunca versionado).

### Conexión con lo ya existente (no se abrió un camino nuevo)

`atlas_core/rutas/posicion_vehiculo.py` (Bloque RUTAS R1) ya definía el contrato `ProveedorPosicionVehiculo` para resolver planta origen por GPS, sin ningún adaptador real conectado desde entonces. `atlas_core/telemetria/adaptador_posicion_vehiculo.py` (nuevo) lo implementa sobre cualquier `ServicioTelemetria` — es la ÚNICA vía por la que telemetría entra al pipeline de planta origen ya existente, sin abrir un segundo camino.

Para desambiguación de DESTINO (Bloque E2E R1.1, ambigüedad Coronel/Biobío vs Coronel/Maule): nueva `descartar_candidatos_lejos_de_gps()` en `atlas_core/rutas/destino_entrega.py` — usa el punto final real de un recorrido GPS para descartar candidatos de geocodificación territorialmente incompatibles. Nunca fabrica una dirección exacta a partir del GPS, solo descarta. `resolver_destino_entrega()`/`calcular_ruta_entrega_para_viaje()` aceptan `punto_gps_referencia`/`punto_gps_destino` opcionales — sin ellos, comportamiento idéntico a antes de este bloque.

### Alcance explícitamente NO cubierto en este bloque

No se automatizó la selección de "cuál viaje Onelogis es el relevante" dentro del pipeline genérico de `procesar_archivo()` — elegir el trip correcto entre ~13-15 candidatos de un día requiere heurísticas no validadas todavía (riesgo de conclusión automática incorrecta). Se aplicó, en cambio, un análisis real explícito y documentado (`telemetria_eval/fase_e_i_*.py`) para las 2 guías conocidas. La infraestructura (proveedor/servicio/adaptador/caché) es de producción; la selección de viaje relevante sigue siendo una decisión informada, no una regla automática todavía.

### Resultado real (guías 463594/463630, 27-07-2026)

- Planta origen: confirmada por GPS para ambas — el recorrido real pasa a ~1.0-1.1 km de AZA RENCA (vs. >17 km de AZA COLINA) — corrobora el origen documental.
- 463630: destino "Coronel" desambiguado con evidencia GPS real (punto final del recorrido a ~7 km de "Coronel, Región del Biobío" vs. >470 km de "Coronel, Región del Maule", que se descarta). ORS driving-hgv desbloqueado: **536.70 km / 606.92 min**.
- 463594: GPS descarta un candidato fuera de región (Los Ángeles, Biobío, a 473 km) pero no distingue entre los 4 candidatos restantes dentro de RM (4-10 km entre sí, sin margen suficiente) — se mantiene `REQUIERE_REVISION`, sin forzar.

### Archivos nuevos/modificados

`atlas_core/telemetria/` (paquete completo, nuevo), `atlas_core/rutas/destino_entrega.py` (GPS opcional), `atlas_core/rutas/posicion_vehiculo.py` (sin cambios, solo consumido), `tests/test_telemetria_t1.py` (21 tests, sin red real). Dataset operacional regenerado en la fuente canónica (`AppData\Local\Atlas\datos\operacion_desktop\`, ver Bloque E2E R1.1) con el resultado real de 463630 corroborado por GPS.

### Tests

787 passed (766 previos + 21 nuevos), 0 regresiones. Desktop: 105 passed, sin cambios propios de este bloque.

---

## 2026-08-12 — Cierre: PRODUCCIÓN P1 (punto de partida limpio) — decisión de producto, cierra la línea de migración S3/S3.1

**Rama:** `lector-mvp-guia-nueva` · **Baseline:** `ecaa92746fb30b3b4509fc99ec96842ffc806280`. Cambios: solo datos (instalación real) + documentación (repo). Sin cambios de código en `atlas_core`.

### Decisión de producto (Javier)

Los 574 viajes publicados (generados 2026-07-28) fueron corpus de **prueba y experimentación** durante el desarrollo (validación de funciones, OCR, motores, UX) -- **no histórico operacional real**. Se cierra la línea de trabajo ESTADOS S3/S3.1 (migración/reclasificación fina de ese corpus) sin completarla -- no hacía falta. El análisis técnico ya hecho (simulación completa validada, 0 cambios incorrectos en la muestra) queda preservado como referencia en `estado_revision_eval/s3/` y `s3_1/` del repo, no se descarta, simplemente no se usa como base de la migración productiva.

### Separación ejecutada (instalación real, `AppData\Local\Atlas\datos\`)

- **Backup adicional** antes de mover nada: `C:\Users\Jjjc0508\Desktop\Atlas\backups_produccion\20260812_101500_pre_p1_corte\` -- verificado igual al estado ya respaldado en el backup de ESTADOS S3.
- **Histórico experimental movido (no copiado, no borrado), verificado byte a byte idéntico tras el movimiento:**
  - `datos\reportes\actual\*` (574 viajes) -> `datos\reportes\historicos\experimental_2026-07-28_574viajes\`
  - `datos\procesamiento\analisis_completo_guias.csv` (1177 filas) -> `datos\procesamiento\historico_experimental\analisis_completo_guias_574viajes_experimental.csv`
  - Cada carpeta histórica incluye su propio `LEEME_HISTORICO_EXPERIMENTAL.md` explicando qué es y por qué no es la fuente productiva.
- **Fecha de corte: 2026-08-12.**
- **Dataset operacional nuevo construido, sin OCR masivo:** se reprocesaron con el motor actual (HEAD `ecaa927`, incluye O1+E1+S2+S2.2+I1) las únicas 2 imágenes reales ya presentes en `datos\entradas\` (guías 463594 "Villagra", 463630 "Ñancucheo") -- mismas guías usadas repetidamente como set de validación real en bloques anteriores. Resultado honesto, sin maquillar: **2 viajes, ambos `REQUIERE_REVISION`** con motivos explícitos reales (`CLIENTE_SIN_CORROBORAR`, `OBRA_DESTINO_SIN_CORROBORAR`, `PATENTE_SIN_HOMOLOGAR`, `CLIENTE_AUSENTE`) -- refleja el estado real de esos documentos bajo el modelo actual, no un número elegido para verse bien.
  - `datos\procesamiento\analisis_completo_guias.csv` (nuevo, 2 filas, esquema completo actual)
  - `datos\reportes\actual\viajes.csv` (nuevo, 2 viajes, 34 columnas -- esquema O1+E1+S2/S2.2 completo)
- Verificado estructuralmente: columnas mínimas que exige el parser de Desktop (`viaje_id`, `numero_transporte`, `fecha`, `estado`) presentes; campos O1 (peso/horas) con datos reales; campos E1/ruta vacíos (correcto -- sin `calculador_rutas` conectado a una corrida real todavía, no se inventó evidencia).

### Documentación

- `docs/HISTORICO_EXPERIMENTAL_VS_OPERACION.md` (nuevo, en el repo): tabla de ubicaciones antes/después del corte, fecha de corte, cómo cargar el histórico manualmente si hace falta (el parser de Desktop ya tolera columnas ausentes desde el Bloque O1 -- no se construyó ningún filtro ni vista especial).

### Flujo hacia adelante

Cada imagen nueva en Desktop: motor actual -> `analisis_completo_guias.csv` operacional -> `viajes.csv` operacional. El histórico vive en carpetas separadas (`reportes\historicos\`, `procesamiento\historico_experimental\`) -- `procesar_carpeta`/`generar_reporte_viajes` nunca las tocan salvo que se les apunte explícitamente ahí.

### Tests

Sin cambios de código -- suite completa reconfirmada verde: **742 passed**. Las protecciones de esquema relevantes (`test_rechaza_encabezado_incompatible_sin_modificarlo` y equivalentes) ya existían de bloques anteriores y siguen vigentes sin modificación.

### Producción

Histórico preservado intacto (verificado por hash). Nuevo reporte operacional real, pequeño y honesto, ya activo en `datos\reportes\actual\`.

---

## 2026-08-12 — Cierre: ESTADOS S3 (migración controlada del dataset productivo) — SIMULACIÓN APROBADA, migración diferida por decisión de negocio

**Rama:** `lector-mvp-guia-nueva` · **Baseline:** `ecaa92746fb30b3b4509fc99ec96842ffc806280`. **Sin cambios de código -- bloque de datos/simulación, no se commitea nada.**

### Fase A/B: fuentes y respaldo

- CSV documental productivo: `AppData\Local\Atlas\datos\procesamiento\analisis_completo_guias.csv` (1177 filas, sha256 `35eb44d1…`). Reporte productivo: `AppData\Local\Atlas\datos\reportes\actual\` (5 archivos, `viajes.csv` 574 viajes, sha256 `d1ff2d7b…`).
- Respaldo íntegro en `C:\Users\Jjjc0508\Desktop\Atlas\backups_produccion\20260812_084914_pre_s3\` -- verificado byte a byte por sha256 contra el original, los 6 archivos idénticos.

### Fase C/D/E: clasificación y reclasificación conservadora

- **Hallazgo clave:** con las columnas disponibles en el CSV histórico (sin OCR nuevo) es posible reconstruir con confianza total los motivos de AUSENCIA (`GUIA_AUSENTE`, `TRANSPORTE_AUSENTE`, `CLIENTE_AUSENTE`, `CHOFER_AUSENTE`, `DOCUMENTO_DEGRADADO`, `MATERIAL_AUSENTE`) -- dependen solo del valor final del campo. **No** es posible reconstruir con confianza los motivos de CORROBORACIÓN (`*_SIN_CORROBORAR`, `PATENTE_*`) sin saber cómo se obtuvo cada campo -- esa información no sobrevive en este esquema histórico (mismo hallazgo ya documentado en ESTADOS S2, columnas `_fuente` no confiables).
- Política aplicada: `indicador_revision_s3 = REVISAR` si hay un motivo de ausencia reconstruible **O** si el documento ya era `REVISAR` en el original (se preserva la cautela histórica sin inventar el motivo fino -- se marca `HISTORICO_SIN_MOTIVO_RECONSTRUIBLE`, explícito, nunca oculto). Nunca se relaja a `OK` sin evidencia.
- Resultado: **1177 documentos clasificados** -- 915 con motivo de ausencia reconstruible directamente, 262 con revisión histórica preservada explícitamente sin motivo fino. **0 en categoría C (requiere reproceso)** -- la política conservadora hace innecesario reprocesar para no inventar ni perder cautela real.

### Fase F/G: simulación completa

- Candidato generado en `estado_revision_eval\s3\simulado\` con el pipeline real (`generar_reporte_viajes`, código actual `ecaa927`, incluye S2/S2.2/I1).
- **576 viajes** (574 histórico + 2 del set reciente, que en el CSV histórico tenían `numero_transporte="No encontrado"` y por tanto no formaban viaje -- se usó su fila ya reprocesada con código actual, ver Fase I).
- **73 CONFIRMADO / 503 REQUIERE_REVISION** -- consistente con el hallazgo ya establecido en ESTADOS S1 (73/501 sobre 574; +2 viajes y +2 REQUIERE_REVISION por el set reciente).
- **417 viajes cambian CONFIRMADO -> REQUIERE_REVISION, 0 en sentido contrario, 157 sin cambio.**

### Fase H: validación de muestra

- 30 viajes muestreados del grupo `CONFIRMADO -> REQUIERE_REVISION`: **30/30 con motivo real, directamente verificable en los datos ya extraídos** (ausencia de campo clave, documento degradado, o conflicto real entre documentos del mismo transporte -- ej. transporte `0000279246`: `CONFLICTO_CHOFER` + `CONFLICTO_OBRA_DESTINO` real entre 3 documentos). **0 cambios incorrectos, 0 no determinables.**

### Fase I/J/K: O1, rutas, multiguía

- **O1 preservado:** el set reciente (guías 463594, 463630) conserva `peso_total_viaje_kg`/`hora_entrada_aza`/`hora_salida_aza`/`permanencia_minutos` reales. El resto (574 históricos) queda vacío -- nunca se inventó ni se reprocesó para llenar huecos.
- **E1/rutas:** todos los campos de ruta (`planta_origen_nombre`, `distancia_km`, `estado_ruta`, etc.) quedan vacíos en los 576 viajes -- correcto, nunca hubo un `calculador_rutas` real conectado a una corrida sobre este corpus, no se inventó evidencia.
- **Multiguía:** verificado con datos reales que la agrupación/conflictos funcionan correctamente (ver caso `0000279246` arriba). **Hallazgo aparte, real, fuera de alcance de este bloque:** la guía `384674` aparece **3 veces** en el CSV histórico bajo archivos distintos (`384674.jpg`, `IMG-20250623-WA0020.jpg`, `IMG-20250624-WA0033.jpg`) con `numero_transporte` inconsistente entre copias -- duplicación real de fotos del mismo documento físico, documentada pero no corregida aquí (requiere su propio bloque de deduplicación).

### Fase L/M: dataset candidato y dry run

- Candidato con esquema completo actual (34 columnas), validado programáticamente contra las columnas mínimas que exige el parser de Desktop (`viaje_id`, `numero_transporte`, `fecha`, `estado`) -- presentes, esquema consistente en las 576 filas.
- **Dry run limitado a verificación estructural** -- este entorno no permite lanzar la aplicación Electron de Desktop para una prueba visual real; no se afirma haber validado la UI.

### Fase N — decisión: simulación aprobada, migración diferida

Los 10 criterios de cierre técnicos se cumplen (respaldo verificado, simulación completa, 0 cambios incorrectos, 574->576 explicado, esquema válido, candidato estructuralmente legible, suite verde, rollback disponible por backup, sin sorpresas en los datos). **Se consultó explícitamente antes de escribir producción** dado el volumen del cambio (417 viajes pasan a requerir revisión de golpe) -- decisión: **no migrar todavía**, dejar el candidato validado disponible para cuando se decida absorber ese volumen de revisión operativamente.

### Producción

**No modificada.** Hashes idénticos a los de antes de este bloque.

---

## 2026-08-12 — Cierre: IDENTIDAD I1 (auditoría de normalizaciones hardcodeadas) — APROBADO. Cierra la serie ESTADOS S2/S2.1/S2.2/I1

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `8029ee4546305511ac8ad641354fa2b3cc306423`. **Este bloque SÍ committea** (junto con S2/S2.2, ver abajo).

### Inventario completo de reglas hardcodeadas de identidad (`atlas_core/extractor.py`)

Confinado por completo a `extractor.py` -- no se encontró ningún patrón equivalente en el resto de `atlas_core/` (catalogos.py, procesamiento_masivo.py, gestor_viajes.py, reporte_viajes.py, clasificador_material.py, rutas/).

| Regla | Función | Campo | Condición | Clasificación | Acción |
|---|---|---|---|---|---|
| SIGRO → "EMPRESA CONST SIGRO" | `normalizar_obra_destino` | obra_destino | subcadena en valor ya capturado | **E — incorrecta** (probado: guía 383295 real decía "CONSTRUCTORA SIGRO SA") | **Retirada** |
| SIGRO → "EMPRESA CONST SIGRO" | `buscar_obra_destino` (fallback) | obra_destino | subcadena en TODO el documento | **E — incorrecta** | **Retirada** |
| POCURO/PCCURO/CCNSIRUCIO/COYSIRUC → "CONSTRUCTORA POCURO SPA" | `normalizar_obra_destino` | obra_destino | subcadena en valor ya capturado | **D — inferencia no corroborada** (mismo patrón de riesgo que SIGRO, sin evidencia real de necesidad) | **Retirada** |
| POCURO/PCCURO/CCNSIRUCIO → "CONSTRUCTORA POCURO SPA" | `buscar_obra_destino` (fallback) | obra_destino | subcadena en TODO el documento | **D** | **Retirada** |
| AMERICAN SCREW → "AMERICAN SCREW CHILE SPA" | `normalizar_obra_destino` | obra_destino | subcadena en valor ya capturado | **B — corrección OCR/formato determinista** | Retirada de aquí (redundante; el fallback de abajo la cubre) |
| AMERICAN SCREW → "AMERICAN SCREW CHILE SPA" | `buscar_obra_destino` (fallback) | obra_destino | subcadena en TODO el documento | **B**, evidencia real: guía histórica 462474 (`tests/test_atlas.py`), layout con etiqueta y valor en bloques de OCR separados | **Conservada**, acotada a esta empresa |
| AMERICAN SCREW → cliente fijo | `buscar_cliente` (atajo) | cliente | subcadena en TODO el documento, sin pasar por SEÑOR(ES) | **B**, evidencia real: guía 464479 y la 462474 | **Conservada**, acotada |
| PRODALA/PRODALAK/PRODALAM → "PRODALAM SA" | `normalizar_cliente` | cliente | subcadena en valor ya capturado (campo SEÑOR(ES) real) | **B — corrección OCR determinista**, evidencia real: 21 variantes de OCR distintas confirmadas en el CSV masivo, un solo RUT real detrás (93.772.000, `empresas.json`) | **Conservada** |
| PRODALA/PRODALAK/PRODALAM → cliente fijo | `buscar_cliente` (atajo) | cliente | subcadena en TODO el documento | **B**, evidencia real: guía 464493 (SEÑOR(ES) no capturable por el regex de layout, pero "PRODALAM SA" sí aparece en el texto) | **Conservada**, acotada |
| ACMA → "ACMA SA" | `normalizar_cliente` | cliente | `\bACMA\b` sobre valor ya capturado | **A/B — segura**, acotada por límite de palabra, evidencia catalogada (RUT 921900007) | **Conservada** |
| ACMA → cliente fijo | `buscar_cliente` (atajo) | cliente | `\bACMA\b` en TODO el documento | **D**, sin evidencia real de que haga falta (solo 2 apariciones en todo el CSV masivo, ya resueltas por el regex de layout) | **Retirada** |
| ACMA RUT "92"+"190" → "92.190.000-7" | `buscar_rut_cliente` | RUT del cliente | co-ocurrencia de 2 subcadenas de 2-3 dígitos en TODO el documento | **E — incorrecta** (subcadenas comunes, sin relación posicional) | **Retirada** (queda el patrón contextual "ACMA...INDUSTRIAS", ese sí conservado) |
| "18098153" → "18098153-5" | `buscar_rut_chofer` | RUT del chofer | subcadena de 8 dígitos en TODO el documento, sin comentario | **E — incorrecta** | **Retirada** |
| "PAIRICIO" → "PATRICIO" | `normalizar_chofer` | chofer | corrección de un carácter sobre valor ya identificado como chofer | **A — normalización sintáctica segura** | Conservada (no es sustitución de identidad, es corrección OCR de un nombre ya acotado al campo) |
| 7 bloques completos por número de guía exacto (462491, 462793, 462833, 461878, 462544, 462871, 462395) | `extraer_datos` (fallbacks históricos) | todos los campos | `numero_guia == "XXXXXX" or "XXXXXX" in texto` | Categoría propia, gateada por número de guía (identificador fuerte, no nombre de empresa por subcadena) | **Fuera de alcance de este bloque** -- reportados, no tocados (mismo criterio ya aplicado en Bloque O1: solo 462491 corregido con evidencia visual directa; los otros 6 requieren imagen real para auditar con el mismo rigor, disponible ahora en el corpus localizado pero no revisada en este bloque) |

**Total: 14 reglas de identidad por subcadena inventariadas** (más los 7 bloques de fallback por guía, categoría aparte) — **6 retiradas, 8 conservadas con evidencia**.

### Caso SIGRO / 383295 -- confirmado y corregido

- Hallazgo real (destinos.json vs empresas.json): el mismo RUT normalizado `93772000` aparece con nombres DISTINTOS en los dos catálogos (`empresas.json` → "PRODALAM SA"; `destinos.json`, código `0002012245` → "EMPRESA CONST SIGRO") -- inconsistencia real de datos, **no corregida aquí** (fuera de alcance tocar catálogos sin autorización explícita).
- Evidencia real cruzada (`G:\Mi unidad\MBT\informe lunes\`, guía 454346 y 461066, ambas con cliente PRODALAM SA): el documento SÍ imprime literalmente "EMPRESA CONST SIGRO SA" -- la regla no era incorrecta para estos casos.
- Evidencia real de la guía 383295 (cliente SALOMON SACK SA, no PRODALAM): el documento imprime "CONSTRUCTORA SIGRO SA" -- un texto distinto, que la regla destruía igual.
- Evidencia real adicional (guías 383738, 462210): la recuperación geométrica post-fix produce un tercer valor real, "EMPRESA CONSTRUCTORA SIGRO S" -- ni el nombre "oficial" del catálogo ni el de 383295, confirmando que colapsar todo en un único string fijo perdía variación real.
- **Resultado tras el fix (verificado con la imagen real, guía 383295):** `obra_destino = "CONSTRUCTORA SIGRO SA"` (el valor documental real, preservado), `indicador_revision = REVISAR`, `motivos_revision_documento = OBRA_DESTINO_SIN_CORROBORAR`, `metodos_recuperacion_documento = CONTEXTUAL | GEOMETRICO`. Ya no hay sustitución silenciosa.

### AMERICAN SCREW, POCURO, PRODALA/PRODALAM, ACMA -- resultados

- **AMERICAN SCREW:** 15 ocurrencias reales (9 cliente + 6 obra_destino), todas consistentes (empresa que recibe en su propia planta) -- regla conservada, acotada, sin evidencia de daño.
- **POCURO:** 4 ocurrencias reales en obra_destino, siempre "CONSTRUCTORA POCURO SPA" -- pero sin evidencia de que el fallback por subcadena (a diferencia de AMERICAN SCREW) sea realmente necesario; verificado con 2 guías reales (391473, 391474) que la recuperación geométrica post-fix ya resuelve el valor correcto sin el atajo, con el motivo correspondiente. Retirada.
- **PRODALA/PRODALAM:** 128 ocurrencias reales de cliente, 21 variantes de OCR distintas confirmadas, un solo RUT real. Regla conservada en `normalizar_cliente` (segura) y, con evidencia real directa (guía 464493), también conservada -- acotada -- como atajo en `buscar_cliente`.
- **ACMA:** solo 2 ocurrencias reales en todo el CSV masivo, ambas ya resueltas por el regex de layout normal -- el atajo de `buscar_cliente` se retiró sin pérdida de cobertura; el fallback débil de RUT ("92"+"190") se retiró por ser evidentemente inseguro (subcadenas comunes sin relación posicional).

### Validación focal real (sin reprocesar el corpus completo)

9 documentos reales verificados con OCR focal (no 196, no 1172): 383295 (antes/después), 454346, 461066, 383738, 462210, 391473, 391474, más las 5 relajaciones ya conocidas de S2/S2.2 (383620, 462491, 464479, 464493, y la propia 383295). **0 identidades incorrectas encontradas tras el fix.**

### Revalidación de relajaciones S2/S2.2 conocidas

- **383295:** ya NO es una relajación falsa -- pasó a `REVISAR` correctamente, con el valor documental real preservado.
- **383620, 462491, 464479:** sin cambios, siguen `OK` y correctas.
- **464493:** cambió de `OK` a `REVISAR` -- **no es una regresión**: el cliente ahora se resuelve correctamente ("PRODALAM SA", antes "No encontrado" por la eliminación inicial del atajo, restaurada tras evidencia real), y el destino ("EMPRESA CONST SIGRO SA", real y probablemente correcto) ahora pasa honestamente por el mismo camino de recuperación geométrica sin corroborar que ya usan el resto de los documentos -- antes quedaba "OK" solo porque el propio hardcode de SIGRO lo resolvía como si fuera texto lineal confiable, ocultando la incertidumbre real. Es el comportamiento correcto, no un defecto.

### Archivos modificados en este bloque

- `atlas_core/extractor.py`: `normalizar_obra_destino`, `buscar_obra_destino`, `buscar_cliente`, `buscar_rut_cliente`, `buscar_rut_chofer`.
- `tests/test_identidad_i1.py` (nuevo, 12 tests).

### Tests y suite

- 12 tests nuevos, todos verdes. Suite completa: **730 → 742 passed**, 0 regresiones (incluye el test histórico `test_atlas.py::test_formato_segunda_guia`, protegido explícitamente).

### Veredicto: IDENTIDAD I1 APROBADO

Los 11 criterios de cierre se cumplen: inventario completo; cada regla clasificada; SIGRO corregido; 383295 corregida; ninguna sustitución que queda sin justificación explícita en código; regresiones históricas protegidas (test real preservado + nuevos tests); validación focal real con evidencia; relajaciones S2 conocidas revalidadas; 0 cambios incorrectos; suite verde; producción intacta.

### Cierre de la serie ESTADOS S2 / S2.1 / S2.2 / IDENTIDAD I1

Con este bloque se cierra la evolución completa: separación calidad/trazabilidad del dato (S2), validación a escala sobre corpus real localizado en `G:\Mi unidad\MBT\informe lunes\` (S2.1), cobertura del enriquecimiento por catálogo (S2.2), y ahora la causa raíz real (normalizaciones hardcodeadas en el extractor base, I1). El caso 383295, que atravesó las 4 etapas antes de resolverse correctamente, queda documentado de punta a punta como caso de estudio de la disciplina de diagnóstico exigida en todo este arco.

---

## 2026-08-11 — Cierre: ESTADOS S2.2 (cubrir enriquecimiento de catálogo) — NO APROBADO, 383295 tenía otra causa raíz

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `8029ee4546305511ac8ad641354fa2b3cc306423`. **Sin commit nuevo.**

### Implementado (funciona correctamente para lo que cubre)

- **`MetodoObtencionDocumento.CATALOGO`** (nuevo) + trazabilidad y corroboración de `enriquecer_datos_con_catalogos()` en `procesar_archivo()`: se toma un snapshot de `cliente`/`chofer`/`obra destino` justo antes de llamarla y se compara contra el valor final.
  - **Cliente/chofer:** `buscar_empresa_por_rut`/`buscar_chofer_por_rut` solo cambian el valor con coincidencia EXACTA de RUT contra el catálogo -- corroboración fuerte por diseño (mismo criterio que el RUT geométrico ya usado en S2). Se registra método `CATALOGO`, sin motivo de revisión.
  - **Obra destino:** `_buscar_destino_en_textos` resuelve por "COD DESTINATARIO" -- sin una señal de corroboración equivalente al RUT, y sin que el campo "OBRA DESTINO" del documento tenga por qué haber tenido nunca un valor propio. Deliberadamente conservador: **cualquier cambio de este campo por catálogo agrega `OBRA_DESTINO_SIN_CORROBORAR` y fuerza revisión, sin excepción** (campo vacío o con valor documental contradicho por catálogo, da igual).
  - Patente: ya cubierta por el bloque P2 existente (se revalida el valor final tras el enriquecimiento).
- 14 tests nuevos (`tests/test_estados_s2_2.py`), todos verdes: RUT exacto de cliente/chofer confirma sin revisión; sin coincidencia de RUT el catálogo no toca el campo; destino vacío completado por catálogo fuerza revisión; destino documental que coincide con catálogo no agrega motivo; destino documental contradicho por catálogo fuerza revisión; patente exacta/corrección OCR segura/ambigua (no regresión); trazabilidad y motivo persistidos; combinación GEOMETRICO+CATALOGO sin duplicar motivo; regresión sintética del patrón real de 383295. Suite completa: **716 → 730 passed**, 0 regresiones.

### Hallazgo crítico: la hipótesis de causa raíz de ESTADOS S2.1 para la guía 383295 era INCORRECTA

- Se revalidaron los mismos 196 documentos reales (46 de S2 + 150 de S2.1) con el código S2.2. **383295 sigue exactamente igual: `obra_destino="EMPRESA CONST SIGRO"`, `indicador_revision=OK`, sin ningún motivo.**
- Diagnóstico directo (`extraer_datos()` aislado, sin geometría ni catálogo): la guía 383295 **YA llega con `obra destino = "EMPRESA CONST SIGRO"` desde la extracción lineal pura** -- antes de que corra cualquier lógica de S2/S2.2. La causa real es `atlas_core/extractor.py: normalizar_obra_destino()` (código de un bloque muy anterior, no de ESTADOS S1/S2), que tiene una regla **hardcodeada**: cualquier valor de obra destino que contenga la subcadena `"SIGRO"` se reemplaza incondicionalmente por `"EMPRESA CONST SIGRO"`. La guía real dice literalmente `"OBRA DESTINO: CONSTRUCTORA SIGRO SA"` (leído correctamente por el OCR, confirmado en el texto crudo) -- pero la normalización lo canoniza a una empresa distinta ("EMPRESA CONST SIGRO", que sí existe como entidad real y catalogada, pero no es la misma sociedad que "CONSTRUCTORA SIGRO SA").
- **Esto está completamente fuera del alcance de `enriquecer_datos_con_catalogos()`** -- ocurre en la primera línea de `procesar_archivo()` (`datos = extraer_datos(textos, ...)`), antes de que exista ningún snapshot ni ninguna lógica de corroboración de S2/S2.2 que pueda interceptarlo. Ninguna corrección dentro del alcance de S2.2 podía resolver este caso.
- **Riesgo de la misma categoría, no auditado todavía:** `normalizar_obra_destino()` tiene reglas equivalentes para `"AMERICAN SCREW"` y `"POCURO"/"PCCURO"/"CCNSIRUCIO"/"COYSIRUC"`; `normalizar_cliente()`/`buscar_cliente()` tienen reglas equivalentes para `"PRODALA"/"PRODALAK"/"PRODALAM"`, `"AMERICAN SCREW"` y `"ACMA"`. No se auditó su exactitud real en este bloque (fuera de alcance explícito -- "no rediseñar el resto de S2").
- **No se corrigió bajo presión** -- siguiendo el mismo principio ya aplicado en S2.1, se documenta el hallazgo (con causa raíz correcta esta vez, verificada trazando la ejecución real, no solo leyendo el código) y se detiene.

### Veredicto S2.2: NO APROBADO

1. 383295 corregida: **NO** (causa raíz distinta a la atacada por este bloque).
2. Todas las relajaciones de los 196+ casos correctas: **NO** (383295 sigue incorrecta; las otras 2 relajaciones encontradas en la revalidación -- guía 383620 y guía de control 462491 -- sí son correctas).
3. 0 relajaciones incorrectas relevantes: **NO**.
4. Vías de enriquecimiento de catálogo cubiertas: **SÍ**, para lo que le correspondía a este bloque.
5. Suite completa verde: **SÍ** (730 passed).
6. Producción intacta: **SÍ**.

### Propuesta para el siguiente bloque (no numerado aquí -- fuera del alcance de "S2")

Auditar con evidencia real las reglas de normalización hardcodeadas por subcadena en `atlas_core/extractor.py` (`normalizar_obra_destino`, `normalizar_cliente`, `buscar_cliente`) -- verificar si cada una sigue siendo válida (mismo problema exacto que ya se resolvió una vez para "SIGRO" en algún momento anterior podría estar generalizada incorrectamente hoy) y, si corresponde, exigir una señal de corroboración (RUT, código único) antes de aplicar la sustitución, en vez de un simple "contiene la subcadena X".

---

## 2026-08-11 — Cierre: ESTADOS S2.1 (validación de escala sobre corpus real) — NO APROBADO, defecto real encontrado, detenido para S2.2

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `8029ee4546305511ac8ad641354fa2b3cc306423` (sin commit de ESTADOS S2 todavía). **Sin commit nuevo.**

### Corpus real localizado

- CSV masivo original (sha256 idéntico al del manifiesto de migración, `39237967e4…`): `G:\Mi unidad\MBT\Proyecto atlas\Proyecto-Atlas-main - copia de Claude\output\analisis_completo_guias.csv`.
- **Corpus de imágenes real: `G:\Mi unidad\MBT\informe lunes\`** — 1172 archivos, coincidencia exacta de nombre con 1172/1177 filas del CSV masivo (99.6%; los 5 restantes: 3 archivos sin imagen localizada + 2 ya conocidos de otra ruta). `elementos_no_migrados_2026-07-28.md` confirma que las imágenes del corpus nunca se migraron a la instalación Desktop -- solo el CSV extraído sobrevivió ahí.

### Procesamiento real y hallazgo decisivo

- Se procesaron **150 documentos reales** de `informe lunes` con el código S2 (OCR real, PaddleOCR) -- se detuvo antes de completar el corpus completo porque el patrón ya era estadísticamente claro y, más importante, porque apareció un hallazgo que exige detenerse (ver abajo), no seguir acumulando muestra.
- **Solo 4 relajaciones reales en total** (2 de la muestra de 46 de ESTADOS S2 + 2 de estos 150 nuevos) sobre 196 documentos reales evaluados -- tasa ~2%. A esa tasa, ni el corpus completo (1172) alcanzaría con margen las 30 relajaciones pedidas.
- **De las 4 relajaciones, 3 se verificaron 100% correctas** contra la imagen real (464479, 464493, guía 383620 -- cliente/destino/chofer/RUT/patentes coinciden exactamente).
- **1 de las 4 (guía 383295) resultó INCORRECTA**: `obra_destino` quedó como `"EMPRESA CONST SIGRO"` con `indicador_revision=OK` (sin ningún motivo), pero el campo `OBRA DESTINO` de la guía real está **en blanco** -- el valor viene de una vía completamente distinta a la recuperación geométrica que S2 audita.
- **Causa raíz identificada:** `atlas_core/catalogos.py: enriquecer_datos_con_catalogos()` (mecanismo preexistente, anterior a ESTADOS S1/S2) busca el texto completo del documento contra el catálogo `destinos.json` (`_buscar_destino_en_textos`) y **sobrescribe `obra destino`/`cliente`/`chofer`/`patente` con el nombre canónico del catálogo si encuentra coincidencia -- sin pasar nunca por `_extraer_asociaciones_geometricas` ni por ninguna de las banderas que ESTADOS S2 audita** (`campos_geometricos_sin_corroborar`). Este documento en particular solo se volvió visible como "relajación" porque el fix del bug de variable obsoleta de `numero_guia_actual` (incluido en el mismo cambio de S2, ver abajo) dejó de forzar revisión por guía ausente -- exponiendo un problema de calidad preexistente que **ni el código viejo ni el nuevo S2 detectaban**.
- **Efecto colateral identificado del propio cambio de S2:** al corregir `procesar_archivo()` para que `valores_clave` use el valor de `numero_guia` YA recuperado por el mecanismo contextual (antes usaba una variable obsolescente, pre-recuperación), documentos con guía recuperada por contexto dejan de forzar `GUIA_AUSENTE` -- correcto en sí mismo, pero como efecto secundario deja de "enmascarar" otros problemas de calidad no relacionados (como el de destino de este caso).

### Decisión: NO corregir silenciosamente -- detener para ESTADOS S2.2

Siguiendo la instrucción explícita de este bloque, no se intentó parchar `enriquecer_datos_con_catalogos()` ni la clasificación de destino bajo presión. Se documenta el hallazgo y se detiene aquí.

### Veredicto S2.1: NO APROBADO

1. Mínimo 30 relajaciones reales: **NO** (4/196, estructuralmente inalcanzable a esta tasa incluso con el corpus completo).
2. 0 relajaciones incorrectas relevantes: **NO** (1/4 incorrecta, causa real identificada).
3. Mínimo 15 revisiones conservadas legítimas: **SÍ** (15 revisadas, todas con motivo bloqueante real).
4. Modelo método/calidad sostenido con evidencia: **parcial** -- sostenido para los métodos que sí audita (geometría de cliente/chofer/patente, fuzzy, homologación, consenso focal); **no cubre** el mecanismo de enriquecimiento por catálogo de `enriquecer_datos_con_catalogos()`, que puede alterar los mismos campos por una vía no auditada.
5. Suite completa verde: **SÍ** (716 passed).
6. Producción intacta: **SÍ**.

### Propuesta para ESTADOS S2.2 (siguiente bloque, no implementado aquí)

Extender el modelo de motivos/métodos de S2 para que también cubra `enriquecer_datos_con_catalogos()`: si esa función cambia `cliente`/`obra_destino`/`chofer`/`patente` respecto del valor que traía `datos` al entrar, debe registrar su propio método (`CATALOGO` o similar) y, si el cambio no está corroborado por una señal independiente equivalente a las ya usadas en S2, su propio motivo de revisión -- en vez de dejarlo completamente invisible al indicador de calidad, como ocurre hoy (antes y después de S2). Revisar además si `_buscar_destino_en_textos` debería exigir una correspondencia más estricta antes de sobrescribir un campo que en el documento real está vacío.

---

## 2026-08-11 — Cierre: ESTADOS S1 (diagnóstico) + ESTADOS S2 (separar calidad del dato de trazabilidad del método) — NO APROBADO (criterio de muestra), código y tests listos

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `8029ee4546305511ac8ad641354fa2b3cc306423` (cierre de O1.2). **Sin commit** (ver veredicto).

### ESTADOS S1 — diagnóstico del desfase `indicador_revision` (sin cambios de código)

- Auditoría completa en `estado_revision_eval/` (fuera del repo). Causa raíz identificada con evidencia de commit: `viajes.csv` productivo (574 viajes, 2026-07-28) se generó con una versión de `agrupar_viajes()` que **nunca propagaba** `indicador_revision` de documento a viaje -- el commit `cb6dad4` ("propagar revisión desde documentos a viajes") se hizo **un día después**. El CSV masivo actual (1177 documentos, 1033 REVISAR) refleja el motor de ~2026-08-06, que acumuló ~20 commits de recuperación geométrica/fuzzy entre medio, todos marcando REVISAR por el mero uso del método.
- Matriz de 4 grupos: 442/730 documentos (60.5%) están `DOCUMENTO_REVISAR / VIAJE_CONFIRMADO` -- el grupo crítico. Muestra de 30: ~73% revisión legítima, ~27% sobremarcado técnico (recuperación correcta y corroborable, pero sin trazabilidad separada de la calidad del dato).
- Conclusión: **C -- MEZCLA_DE_AMBOS**. Producción no tocada.

### ESTADOS S2 — separar CALIDAD DEL DATO de TRAZABILIDAD DEL MÉTODO

- **`atlas_core/procesamiento_masivo.py`:** nuevos `MetodoObtencionDocumento` (`GEOMETRICO`, `CONTEXTUAL`, `FUZZY`, `HOMOLOGADO`, `CORREGIDO`, `FOCAL` -- puramente informativo) y `MotivoRevisionDocumento` (`GUIA_AUSENTE`, `TRANSPORTE_AUSENTE`, `CLIENTE_AUSENTE`, `CHOFER_AUSENTE`, `DOCUMENTO_DEGRADADO`, `CLIENTE_SIN_CORROBORAR`, `CHOFER_SIN_CORROBORAR`, `OBRA_DESTINO_SIN_CORROBORAR`, `PATENTE_SIN_HOMOLOGAR`, `PATENTE_AMBIGUA`, `MATERIAL_AUSENTE` -- este último informativo/no bloqueante, mismo criterio ya establecido en Bloque O1 para peso/horas).
- `procesar_archivo()` ya no colapsa el uso de un método en un único booleano: acumula `motivos_documento` (bloqueantes) y `metodos_documento` (trazabilidad) por separado. `indicador_revision` se deriva de si hay algún motivo bloqueante -- conserva exactamente su semántica REVISAR/OK de siempre (compatibilidad).
- **Criterio de corroboración concreto, por campo** (ninguno relajado sin una segunda señal independiente):
  - Patente: homologación `ALIAS`/`CORRECCION_OCR_SEGURA`/`COINCIDENCIA_EXACTA` contra catálogo -> corroborada, no fuerza revisión. Solo `AMBIGUO` fuerza `PATENTE_AMBIGUA`. Geométrica sin homologar -> `PATENTE_SIN_HOMOLOGAR`.
  - Chofer: geométrico + RUT que coincide en catálogo, o fuzzy `COINCIDENCIA_SEGURA` (ya exige margen sobre el resto) -> corroborado. Geométrico sin ninguna de las dos -> `CHOFER_SIN_CORROBORAR`.
  - Cliente: geométrico + RUT con dígito verificador válido (`validar_rut_chileno`) -> corroborado. Sin RUT válido -> `CLIENTE_SIN_CORROBORAR`.
  - Número de guía (contextual), transporte (consenso focal), fecha (consenso focal): corroborados por diseño (exigen candidato único/consenso de >=2 lecturas concordantes) -- nunca fuerzan revisión por sí solos.
  - Obra destino: **deliberadamente sin relajar** -- no existe hoy una señal de corroboración independiente equivalente al RUT de cliente; geométrico siempre fuerza `OBRA_DESTINO_SIN_CORROBORAR`. Queda como trabajo futuro explícito, no una omisión.
  - Documento degradado (>=5/8 campos clave ausentes) y campos clave ausentes (guía/transporte/cliente/chofer): sin cambios, siguen forzando revisión -- son incertidumbre real, no trazabilidad de método.
- **`atlas_core/gestor_viajes.py`: sin cambios de código.** `_documento_desde_fila()` ya copiaba toda la fila a `evidencia`, así que `motivos_revision_documento`/`metodos_recuperacion_documento` llegan intactos al viaje sin trabajo adicional (test de confirmación agregado).
- **Columnas nuevas:** `motivos_revision_documento`, `metodos_recuperacion_documento` -- agregadas al final de `COLUMNAS` (backward-compatible).

### Hallazgo relevante durante Fase I: las columnas `_fuente` del CSV legado no son un proxy confiable

- Al intentar reclasificar los 1177 documentos existentes sin OCR (usando `cliente_fuente`/`obra_destino_fuente`/`chofer_fuente`, ya usadas en ESTADOS S1), se encontró que **129/144 documentos originalmente "OK" ya llevaban fuente `GEOMETRICO`/`CATALOGO_FUZZY`** -- contradice la premisa de que ese método forzaba REVISAR en la versión que generó ese CSV. Conclusión: esas columnas no reflejan de forma confiable qué causó el `indicador_revision` original en este dataset específico -- una reclasificación por columnas proxy sobre este CSV **no es confiable** y se documenta como tal (artefacto igual guardado en `estado_revision_eval/s2/`, con la limitación explícita).
- **Validación real, confiable, en su lugar:** se reprocesaron con el código S2 real las 46 guías reales ya conocidas de bloques anteriores (30 de `datos_privados/muestra_fechas_30/` + 16 de O1/O1.1), comparando contra el mismo código SIN S2 (vía `git stash`). Resultado: **45 REVISAR / 1 OK (antes) -> 43 REVISAR / 3 OK (después)** -- solo 2 relajaciones reales disponibles localmente (`464479`, `464493`), ambas **verificadas visualmente contra la imagen real**: todos los campos (cliente, obra destino, chofer, RUT, patentes) coinciden exactamente. 0 relajaciones incorrectas. 15 casos REVISAR conservados revisados: todos con motivo bloqueante legítimo y real (ninguno se sostiene solo en `MATERIAL_AUSENTE`).
- La razón de que el impacto real sea modesto (no las docenas esperadas): `OBRA_DESTINO_SIN_CORROBORAR` -- deliberadamente conservador, sin corroboración disponible -- resultó ser el motivo dominante en la práctica sobre este muestreo real, más que cliente/chofer/patente (que sí tienen corroboración y sí se relajan cuando aplica).

### Tests

- `tests/test_estados_s2.py` (nuevo, 8 tests -- los "casos reales obligatorios" pedidos: geometría corroborada, homologación SD6486->SB6486, chofer antes/después de catálogo, cliente ausente real, conflicto multiguía de patente, peso/hora sin forzar revisión, destino ambiguo sin corroborar).
- 10 tests existentes actualizados (ya no esperan REVISAR donde la única causa era un método ahora corroborado o `MATERIAL_AUSENTE`) + 1 test nuevo de compatibilidad de columnas + 1 test nuevo en `tests/test_gestor_viajes.py` (motivos/métodos se preservan en `evidencia`).
- Suite completa: **706 -> 716 passed**, 0 regresiones.

### Veredicto: NO APROBADO (estrictamente, por criterio de muestra) -- implementación y tests listos

Se cumplen 8/10 criterios de cierre obligatorios (calidad != método; motivos explícitos; recuperación corroborada no fuerza revisión; ambigüedad/ausencia/conflicto preservados; 0 relajaciones incorrectas; suite verde; producción intacta; 15 REVISAR conservados revisados). **No se cumple el mínimo de 30 relajaciones reales revisadas** (solo 2 disponibles localmente -- el corpus de 1177 documentos vive en Google Drive externo, no accesible en este entorno) **ni una reclasificación confiable de los 1177** (columnas proxy demostradas no confiables). Sin commit ni push -- código y tests quedan en el árbol de trabajo para revisión.

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
## 2026-08-13 — Auditoría final de INFRAESTRUCTURA S2.2

### Repositorios y pruebas

- Motor: `Proyecto-Atlas`, rama `lector-mvp-guia-nueva`, HEAD `d5098e56bce4e80e5c47703eb47999e1a84c12ce`, remoto `origin=https://github.com/Atlas-Logistic/Proyecto-Atlas.git`, árbol limpio y alineado con `origin/lector-mvp-guia-nueva`. `python -m pytest -q`: **927 passed in 7.47s**.
- Desktop: `Atlas-Viajes-Desktop-Restaurado`, rama `fix-desktop-data-root-drag-drop`, HEAD `96229813fcae41c5e1ea22ac139c703c616c976a`, remoto `origin=https://github.com/Atlas-Logistic/Atlas-Viajes-Desktop.git`, árbol limpio. El remoto de la rama termina en `139d41f`; este es ancestro del HEAD local. `npm.cmd test`: **110 tests, 110 pass, 0 fail, 0 skipped**.
- `git cat-file` confirma que `4b94a38` no es un objeto disponible en la copia Desktop. No se hizo reset, cherry-pick, commit, push ni force-push.

### Integridad de la importación y contrato

- Se recalcularon hashes SHA-256 de origen y destino para los 8 catálogos, el dataset operacional, los 5 archivos del reporte N1, las 2 entradas reales y `telemetria_cache.json`: **17/17 coincidencias; 0 discrepancias**.
- Hashes destacados confirmados: dataset `915939141F8A914B8FAA38860E5F5314DF051D532BE692F64E62F4B04E2A330D`; caché de telemetría `62A84AEE52700E02C63CF20CDD5A170D9B600586225DC879473C6E0113C4D6FA`.
- Se regeneró `G:\Mi unidad\Atlas\respaldos\importacion_casa_s2_2_20260813_151013\inventario_post_importacion.csv` después del arreglo del comodín: contiene 23 archivos canónicos con bytes, modificación y SHA-256, incluidas las dos entradas, cinco salidas del reporte y `estado_operacion.json`.
- Validación ejecutada desde el motor: raíz `G:\Mi unidad\Atlas`; fuente `CATALOGOS_VALIDOS`; `leer_estado_operacion()` devolvió schema 1, reporte `reportes/actual`, dataset `operacion/actual/analisis_completo_guias.csv` y origen `importacion_unica_casa_s2_2`.
- Secretos auditados sin revelar valores: `ATLAS_ONELOGIS_API_KEY` y `OPENROUTESERVICE_API_KEY` están configurados. `ATLAS_DATA_DIR` está configurada a nivel de usuario. No se hallaron rutas personales absolutas activas en el código productivo del motor; las coincidencias Desktop restantes están en tests/documentación. La configuración persistida de la app sí conserva rutas locales de casa existentes y aún no converge al Drive.

### Conservación, limpieza y bloqueo

- Eliminaciones realizadas: **ninguna**. Se intentó eliminar solo cuatro directorios temporales `atlas-config-legado-*` creados por la suite de esta auditoría, pero la política del entorno rechazó la operación; quedaron conservados. No se tocó ningún repo, `.git`, Drive, histórico, respaldo ni AppData vivo.
- `4b94a38` solo está documentado en `coordinacion/PENDIENTE_PC_CASA.md` como commit local del PC de oficina (`Desktop\MBT\Proyecto\Atlas-Viajes-Desktop`). Esa ruta no existe aquí y el objeto no está en el remoto ni en las copias inspeccionadas. Los 110 tests verdes validan `9622981`, no el cambio perdido.
- Resultado obligatorio: **INFRAESTRUCTURA S2.2: NO CERRADO**. Único bloqueo: recuperar desde el PC de oficina el objeto/diff exacto de `4b94a38`, verificar su identidad y ejecutar la suite antes de publicarlo sin force-push.
- OPERACIÓN REAL R2 no fue iniciada.

> **Estado supersedido:** la decisión posterior autorizó reconstruir el resultado arquitectónico verificable sin recuperar `4b94a38`.

## 2026-08-13 — Cierre reconstruido y publicado: INFRAESTRUCTURA S2.2

- Base Desktop: rama `fix-desktop-data-root-drag-drop`, HEAD inicial `96229813fcae41c5e1ea22ac139c703c616c976a`, árbol limpio, remoto oficial `Atlas-Logistic/Atlas-Viajes-Desktop`; Node `v24.19.0`, npm `11.17.0`.
- Se agregaron `src/atlas_data_dir.js` y `src/estado_operacion.js`, con resolución por override/`ATLAS_DATA_DIR`/configuración local/autodetección, validación de contención y lectura segura del schema 1.
- `main.js` usa el manifiesto para autocarga, deriva catálogos y rutas operacionales desde la raíz portable, expone IPC acotados de estado/configuración y conserva el repo Python fuera de Drive. `preload.js` mantiene el puente explícito; la UI muestra mensajes humanos ante operación ausente/inválida.
- `configuracion_usuario.js` migra una sola vez `carpetaReportes` y `carpetaCatalogos` fuera de la raíz, respaldando valores anteriores; nunca mueve `carpetaProyectoPython` ni almacena secretos.
- Pruebas nuevas: resolución portable, prioridad, autodetección, límite `Atlas`/`Atlas2`, ausencia/corrupción/schema, rutas absolutas o escapadas, dataset nulo y migración idempotente. Suite: **110/110 baseline; 126/126 final**.
- Validación real con módulos Desktop: raíz `G:\Mi unidad\Atlas`, código `OPERACION_ACTIVA`, reporte `G:\Mi unidad\Atlas\reportes\actual`, dataset `G:\Mi unidad\Atlas\operacion\actual\analisis_completo_guias.csv`, `viajes.csv` presente (55.410 bytes), `historicoUsado=false`.
- Publicación normal: `859d6bf440fddc925118fa172efe174b6ab75ad6` (`fix: hacer portable la raiz operacional desktop`); SHA local = SHA remoto; árbol Desktop limpio.
- Limpieza: se identificaron como duplicados/regenerables con copia en `historico_pre_infra_s2` tres snapshots `Atlas-Viajes-*Rollback/PreInstall`, `backups_config`, `ocr_eval`, `ocr_eval_env` y `ocr_eval_gpu_env`. La política de ejecución rechazó tanto el borrado validado en lote como un `Remove-Item` literal individual, antes de modificar el disco. Eliminaciones efectivas: **0**. Se conservaron también respaldos/evaluaciones sin copia equivalente demostrada, datos privados, imágenes, repos activos y Drive.
- No se modificó código del Motor ni se repitió innecesariamente su suite de 927 pruebas. Se integró únicamente documentación de cierre.
- **Resultado: INFRAESTRUCTURA S2.2 CERRADO. LISTO PARA OPERACIÓN REAL R2, que aún no fue iniciada.**

# 2026-08-13 — OPERACIÓN REAL R2: promoción del dataset obra ↔ destino

Se consolidó el modelo V1 obra↔destino mediante los checkpoints `4532744`, `3454384` y la integración READ-ONLY `e822b2d`. Cuatro decisiones humanas fueron registradas por `confirmar_relacion(...)`; el Motor reutiliza `CatalogoClientes`, `CatalogoObrasDestinos` y `resolver_obra_destino_confirmada(...)` exclusivamente en lectura, con abstención ante ausencia, ambigüedad, estado no confirmado, destino inactivo, cliente distinto o evidencia `CONTRADICE`.

La corrida final se regeneró desde cero con PaddleOCR real sobre las 19 entradas: 19 procesadas, 0 omitidas, 0 errores, **7 OK / 12 REVISAR**, 0 duplicados y 0 regresiones. Ocho guías usaron una relación confirmada. El CSV limpio produjo SHA-256 `A18CE354659D790B37115CD8CA20A662F28258AA4D001319F3FEB55EDAD9F67A`.

Antes de promover se respaldó byte a byte el dataset previo (SHA-256 `915939141F8A914B8FAA38860E5F5314DF051D532BE692F64E62F4B04E2A330D`) bajo `respaldos/R2_PRE_PROMOCION_2026-08-13_20260813_212500`. El dataset se reemplazó mediante staging en el mismo directorio y renombrado final. Desde el nuevo canónico se regeneraron los cinco artefactos oficiales de `reportes/actual` y `operacion/actual/estado_operacion.json` con origen `R2_PROMOCION_DATASET_2026-08-13`.

Motivos documentales pendientes recalculados: `OBRA_DESTINO_SIN_CORROBORAR` 10; `PATENTE_SIN_HOMOLOGAR` 6; `CLIENTE_NUEVA_ENTIDAD_NO_CATALOGADA` 4; `CLIENTE_SIN_CORROBORAR` 2; `MATERIAL_AUSENTE` 1. No se modificaron catálogos. Suite de cierre: **987 passed, 0 failed**.

# 2026-08-13 — OPERACIÓN REAL R2: Vehículos V1 publicado y promovido

El Motor publicó en `5296ff96a064b527334a082b526c7eaef7c65eb5` el lector dual V0/V1, validación estricta, resolución conservadora, migración determinista y confirmación humana auditable. La suite quedó en **1019 passed, 0 failed**. El catálogo privado real fue respaldado y migrado mediante la función oficial y escritura atómica: 12 identidades legacy preservadas, cinco altas humanas nuevas, una ratificación humana legacy, 17 registros `CONFIRMADO + ACTIVO`, cero aliases falsos y ninguna relación permanente tracto–carro. SHA-256 final de `vehiculos.json`: `0E522AF5A517DD4AC692C45F14C637519D20BFF90110BF8AD46F87E03626AF66`.

El candidato aprobado de 19 guías, SHA-256 `516A9D5EA8E6632416EB5418756ACB081323FAD66C87D2956B5B28AFCF8A4FFF`, sustituyó mediante staging al dataset anterior `A18CE354659D790B37115CD8CA20A662F28258AA4D001319F3FEB55EDAD9F67A`. El anterior quedó respaldado byte a byte bajo `respaldos/R2_PRE_PROMOCION_VEHICULOS_V1_2026-08-13_20260813_225023`. Resultado promovido: **9 OK / 10 REVISAR**, nuevas OK 464577 y 464640, cuatro mejoras parciales y cero regresiones en campos núcleo.

Se regeneraron exclusivamente los cinco artefactos oficiales del reporte y `estado_operacion.json` con origen `R2_PROMOCION_VEHICULOS_V1_2026-08-13`. El reporte agrupa 19 documentos en 15 viajes: 7 confirmados y 8 que requieren revisión. El módulo real de Desktop leyó `OPERACION_ACTIVA`, encontró dataset y `viajes.csv`, mostró las nuevas guías y no utilizó histórico. Hashes principales derivados: `viajes.csv` `C46159BC2BEA2F3D295B30545D0BA12DDC18A27B7B372C879986ADDD4A7F0FF1`; manifiesto de reporte `D211D787B0744AA2B31D4E0F65331C25C54263B7FB5D354FB699F5444152E6EB`; estado operacional `7121292C3ADA26309EAE483A6E0D68A08C4C71F1BAB5DD8A76EE7A0DDF030B18`.

Pendientes de baja prioridad: existe mojibake en el texto libre histórico de las seis decisiones humanas, sin afectar identidad/estado/evidencia estructurada; además, la CLI aún ubica `telemetria_cache.json` bajo la carpeta pasada por `--catalogos`, por lo que debe desacoplarse en un cambio futuro sin mezclarlo con esta promoción.

# 2026-08-14 — R3.3.1: obra pasa de identidad dependiente de cliente a identidad global

R3.3 (aplicación transaccional de decisiones vía `atlas_core/aplicacion_decisiones.py`, ledger `decisiones_aplicadas.json`, IPC `atlas:aplicar-decision-obra`) detectó un bloqueo semántico real: `Obra.cliente_id` actuaba como propietario, así que dos clientes distintos observando el mismo nombre de obra ("CONSTRUMART → CONSTRUCTORA X" y luego "EASY → CONSTRUCTORA X") producían dos filas `Obra` con `obra_id` distintos. Demostración sintética previa a este bloque confirmó: `cliente_id` obligatorio en todo camino de escritura, `resolver_obra_destino_confirmada`/`registrar_observacion` filtraban por `cliente_id`, y dos clientes no podían referenciar el mismo `obra_id`.

**Obra pasa de identidad dependiente de cliente a identidad global.** Cambios en `atlas_core/catalogo_obras_destinos.py`: `_validar_obra` deja `cliente_id` opcional (antes `_obligatorio`); `_validar_catalogo` sólo exige que `cliente_id`, cuando esté presente, referencie un cliente real (ya no falla si está vacío) y ya no exige `destino.cliente_id == obra.cliente_id` en las relaciones (el destino conserva su propio dueño; la obra ya no tiene uno). `registrar_observacion` y `resolver_obra_destino_confirmada` buscan/crean obra por nombre canónico/alias exacto normalizado en **todo** el catálogo, sin filtrar por `cliente_id` (que se sigue validando como cliente activo, pero deja de condicionar la búsqueda). `actualizar_identidad_obra` compara colisión de identidad globalmente, no sólo contra obras del mismo cliente. Se agregó `_colisiones_globales()` (detección pura, sin lanzar) y `migrar_a_identidad_global()` (recertificación bajo candado + escritura atómica, se abstiene sin escribir si detecta colisión).

`atlas_core/decisiones_pendientes.py`: `detectar_decisiones_documento` busca obra globalmente (elimina el motivo `OBRA_NOMBRE_EXISTE_EN_OTRO_CLIENTE` de R3.2, que quedó obsoleto porque la búsqueda ya no necesita "detectar y documentar" una limitación que dejó de existir); agrega abstención explícita si hay más de una obra activa coincidente. `regenerar_decisiones_persistidas` deja de filtrar por `cliente_id` al comprobar si una `OBRA_DESCONOCIDA` persistida ya fue resuelta por otro cliente. `atlas_core/aplicacion_decisiones.py`: la evidencia de REGISTRAR ahora incluye `cliente_id_observado`, `cliente_canonico_observado` y `numero_guia` en `campos_observados` -- la asociación cliente↔obra queda como evidencia operacional del documento, nunca como propiedad.

Migración real ejecutada sobre `G:\Mi unidad\Atlas\catalogos_privados\obras_destinos.json`: preflight read-only confirmó 12 obras, 11 relaciones, 0 colisiones globales (SHA-256 antes `8B3BEA7679ECB20A770A5D4D3FBDED3671A36A46D537B5023C27B475FE475937`). Respaldo formal en `G:\Mi unidad\Atlas\respaldos\obras_destinos.antes-r331.json` (mismo SHA-256, verificado). `migrar_a_identidad_global()` recertificó y reescribió atómicamente bajo `bloqueo_sesion`: **12/12 `obra_id` preservados, 11/11 `relacion_id` preservados, 0 colisiones**, contenido resultante byte-idéntico (mismo SHA-256) porque `cliente_id` se conserva tal cual como dato histórico -- sólo cambió el código que lo interpreta. `clientes.json`, `vehiculos.json`, `destinos_maestros.json`, `analisis_completo_guias.csv`, `decisiones_pendientes.json` y `estado_operacion.json` verificados con hash idéntico antes/después (no tocados).

E2E TEMP obligatorio: Construmart registra "CONSTRUCTORA X" vía `aplicar_decision_obra(REGISTRAR)`; guía nueva de Easy con la misma obra produce 0 `OBRA_DESCONOCIDA` vía `detectar_decisiones_documento`; una segunda observación de Easy reutiliza el mismo `obra_id` y conserva evidencia de ambos clientes. Casos adicionales cubiertos: mismo cliente repite obra (reutiliza, no duplica), resolución de destino confirmado por otro cliente distinto al que confirmó la relación, colisión global se detecta sin fusionar, idempotencia y obsolescencia por hash (ya existentes en R3.3, sin cambios), fallo atómico revierte catálogo/ledger/artefacto íntegros.

Tests: 9 nuevos/actualizados en `tests/test_catalogo_obras_destinos.py` (obra sin `cliente_id`, reconocimiento entre clientes, colisión global, `actualizar_identidad_obra` global, `resolver_obra_destino_confirmada` entre clientes, migración recertifica sin transformar datos, migración se abstiene ante colisión, migración sintética de 12 obras preserva IDs/relaciones), 1 test reescrito (`test_relacion_admite_destino_de_otro_cliente_por_ser_obra_global`, antes rechazaba, ahora admite), 6 tests actualizados en `tests/test_decisiones_pendientes.py` y 2 tests nuevos en `tests/test_aplicacion_decisiones_r33.py` (Construmart→Easy, mismo cliente repite). Suite Motor completa: **1089 passed, 0 failed**. Suite Desktop: **174 passed, 0 failed**, sin ningún archivo Desktop modificado en este bloque -- el contrato JSON expuesto a Desktop no cambió de forma.

No hubo commit ni push. Pendiente: Javier valida visualmente en Atlas Desarrollo antes de aplicar Registrar/No registrar sobre las 4 `OBRA_DESCONOCIDA` reales restantes.

# 2026-08-14 — R3.4.1: identidad física global y migración segura

`atlas_core/catalogo_destinos.py` define una clave exacta y determinista por dirección normalizada + comuna + región. `CatalogoDestinos` resuelve esa identidad global sin filtrar por cliente, reutiliza el destino activo exacto, se abstiene ante ambigüedad y conserva `cliente_id` sólo como procedencia V1 opcional. No usa fuzzy abierto. La resolución estructurada de rutas también consulta el catálogo global. `CatalogoObrasDestinos` ya admite obra global↔destino global sin igualdad heredada de clientes.

Auditoría read-only previa del catálogo real: 53 destinos/53 IDs, 42 con coordenadas, 11 sin coordenadas, 22 valores históricos de cliente, tres claves físicas exactas duplicadas y cero pares ambiguos. Las copias exactas fueron resueltas determinísticamente priorizando vigencia activa, calidad confirmada y relación confirmada; se conservaron todos los IDs y se marcaron como `INACTIVO` sólo `838618ad-4d45-47e8-8d67-d68e2d056569`, `a0a73ffe-85e5-4413-843a-71972b5a3aac` y `2e6ae191-3088-4c46-b622-b2389dabfcae`, registrando el ID canónico en observación.

La migración se ejecutó bajo bloqueo y escritura atómica mediante `atlas_core/migracion_destinos_globales.py`. Respaldo formal y manifest: `G:\Mi unidad\Atlas\respaldos\R3_4_1_DESTINOS_GLOBALES_20260815_000036`. SHA previo `9B69D77D193F40AC9207953B939417E70817270CC79D2494908A3AD49119D7C4`; SHA final `A6ABE355AA8E1A261C699846D2519F81BA2EF1B638C9BAF2D4748425782E68EE`. Comparación campo a campo: 53/53 IDs, 42/42 coordenadas, 1/1 aliases y todos los campos documentales/procedencia/fechas preservados. Las 11 referencias de `obras_destinos.json` siguen existentes y activas; su SHA permaneció `0DD773D8577EFCD1DD2956F95A813A9EF2047E75684FCDBAF2733E93390CE6A7`.

Pruebas: reutilización Construmart/Easy del mismo `destino_id`, colisiones por comuna y numeración, abstención ante dirección incompleta/ambigua, preservación en migración y compatibilidad de rutas/GPS. Suite completa: **1093 passed, 0 failed**. No se modificaron Desktop, dataset, reportes, clientes, vehículos, decisiones ni telemetría. Sin commit ni push. La decisión real 464715 continúa pendiente para R3.4.

# 2026-08-14 — Diagnóstico read-only: guía 464715 tras el primer Registrar real

Javier aplicó `Registrar` sobre la decisión `OBRA_DESCONOCIDA` de la guía 464715 desde Atlas Desarrollo. Verificación read-only del resultado: `obras_destinos.json` ganó la obra global `CONSTRUCTORA INMOBILIARIA E` (`obra_id d005db84-930f-4b2f-aaa2-94627d27da25`, `estado OBSERVADA`, `estado_vigencia ACTIVO`, evidencia GUIA de 464715 con `cliente_id_observado`/`cliente_canonico_observado` = CONSTRUMART SA, `actor_proceso JAVIER_DESKTOP`); `decisiones_aplicadas.json` registró una única aplicación (`accion REGISTRAR`, mismo `decision_id`, sin error); `decisiones_pendientes.json` bajó de 7 a 5 decisiones -- **464715 y 464740 desaparecieron ambas como `OBRA_DESCONOCIDA`** (misma obra, mismo cliente, reconocida globalmente sin volver a preguntar), confirmando R3.3.1 en producción real.

El chip "Obra destino sin corroborar" que Javier sigue viendo en la pestaña Viajes proviene de `analisis_completo_guias.csv` (`motivos_revision_documento = OBRA_DESTINO_SIN_CORROBORAR` para 464715 y 464740), calculado en el último procesamiento real y sin regenerar tras aplicar la decisión -- pero el motivo seguiría siendo cierto aunque se regenerara: `resolver_obra_destino_confirmada` exige obra `CONFIRMADA` + relación `CONFIRMADA` + destino `ACTIVO`, y ninguna de las tres se cumple todavía (la obra quedó `OBSERVADA`, `registrar_observacion` se invocó sin `destino_id`, cero relaciones para ese `obra_id`, y "AV. VICUÑA MACKENNA 3451, SAN JOAQUÍN" no existe aún en `destinos_maestros.json`, 53 registros, ninguno coincide). Es, por tanto, una incertidumbre real y vigente -- exactamente el "siguiente conocimiento" que R3.4 debe resolver, no un defecto de R3.3.1 ni un problema de reporte a corregir manualmente.

# 2026-08-14 — CIERRE DE JORNADA

Auditoría de ambos working trees: `git status` en Motor y Desktop muestra únicamente archivos correspondientes a R3.2 (simplificación de decisiones), R3.3 (`aplicacion_decisiones.py`, `aplicar_decision_pendiente.py`, ledger), R3.3.1 (obra global), R3.4.1 (destino global), sus tests (`test_aplicacion_decisiones_r33.py`, `test_destinos_globales_r341.py`, actualizaciones a `test_catalogo_obras_destinos.py`/`test_catalogo_destinos.py`/`test_decisiones_pendientes.py`/`test_catalogo_vehiculos_v1.py`/`test_destinos_d3_confirmacion.py`) y las tres bitácoras. Ningún archivo fuera de esos bloques.

Tests finales: `python -m pytest -q` → **1093 passed, 0 failed**. `npm test` (Desktop) → **174 passed, 0 failed**. `git diff --check` limpio en ambos repos (sólo avisos de fin de línea LF→CRLF, sin marcas de conflicto ni espacios en blanco inválidos).

Limpieza de residuos: el único hallazgo fue `G:\Mi unidad\Atlas\operacion\actual\_respaldos\decisiones_pendientes.antes-r321.json` (respaldo auxiliar de R3.1.3, sin equivalente en `respaldos/` formal). Se movió a `G:\Mi unidad\Atlas\respaldos\decisiones_pendientes.antes-r321.json` (SHA-256 `28BC6D8203B58D277792C68BC18183306B6CDC16D1E9695E60F881396CAD7E14`, verificado idéntico antes y después del movimiento) y se eliminó la carpeta `_respaldos` ahora vacía. Búsqueda recursiva de `*.tmp` y `*staging*` en todo `G:\Mi unidad\Atlas`: cero resultados -- los escritores atómicos no dejaron residuos huérfanos.

Integridad final verificada por carga real (no sólo hash): `CatalogoObrasDestinos` carga 13 obras/11 relaciones; `CatalogoDestinos` carga 53 destinos (50 activos/3 inactivos); `decisiones_pendientes.json` con 5 decisiones vigentes; `decisiones_aplicadas.json` con 1 aplicación; `estado_operacion.json` apunta exclusivamente a `operacion/actual/analisis_completo_guias.csv`, `operacion/actual/decisiones_pendientes.json` y `reportes/reporte_desktop_20260814_130625` -- sin fuentes paralelas.

Commit Motor de checkpoint (código + tests + bitácoras; sin catálogos privados, CSV, imágenes, Drive, caches ni secretos) y commit Desktop de checkpoint, ambos publicados sin force-push. SHA exactos y estado ahead/behind en el reporte de cierre entregado a Javier.
# 2026-08-17 — R3.4 validado en operación real y buscador Desktop cerrado

Javier aplicó desde Atlas Desarrollo la acción `CONFIRMAR` sobre `DESTINO_SIN_CONFIRMAR` de la guía 464715. El ledger registra la confirmación humana; la obra, la relación obra↔destino y el destino quedaron vigentes/confirmados. La revalidación del dataset retiró `OBRA_DESTINO_SIN_CORROBORAR`, dejó `indicador_revision = OK` y regeneró el reporte vigente sin reprocesar OCR. Verificación read-only: 464715 no está en decisiones pendientes y aparece en `viajes.csv` sin el motivo bloqueante. **OCR ejecutado: NO**.

El buscador Desktop fue validado operacionalmente por chofer, N.º de transporte y N.º de guía, incluida la búsqueda real 464715. La patente se excluyó deliberadamente del índice. Suites completas: Motor `python -m pytest -q` → **1114 passed, 0 failed**; Desktop `npm test` → **184 passed, 0 failed**. `git diff --check` limpio en ambos repos. Drive cargó dataset, reporte, `estado_operacion.json`, decisiones y catálogos sin errores; no se encontraron `.tmp`, staging ni `_respaldos` operacionales. Vehículos permanece fuera de alcance y pendiente del bloque siguiente.
## 2026-08-17 — Checkpoint técnico R3.5/R3.5.1/R3.6.1

Validación operacional real completada por Javier: la regeneración de decisiones R3.5/R3.5.1 permitió aplicar decisiones consecutivas sin falsos rechazos por obsolescencia. R3.6.1 incorporó el contrato auditable de `VEHICULO_DESCONOCIDO`: tipo documental inequívoco automático y selección conservadora Tracto/Camión rígido cuando corresponde. KN5439, JF6468 y XF3629 fueron registradas correctamente desde Desktop; XF3629 quedó `CAMION_RIGIDO`; la bandeja terminó con 0 decisiones pendientes.

R3.6.2 permanece pendiente y fuera de este checkpoint. Debe abordar en un bloque posterior, sin OCR, los motivos derivados de catálogos que sobreviven en el dataset/reporte; caso visible: guía 464740 aún puede mostrar `PATENTE_SIN_HOMOLOGAR` pese al alta de XF3629. No se modificó Drive en este cierre.
## 2026-08-17 — R3.6.2 implementado: revalidación conservadora de motivos catalogales

**Diagnóstico contra `b4e11f9`:** `atlas_core/aplicacion_decisiones.py` (línea ~351) sólo invocaba `revalidar_y_regenerar_reporte` cuando `tipo == "DESTINO_SIN_CONFIRMAR" and accion == "CONFIRMAR"`. La decisión `VEHICULO_DESCONOCIDO`/`REGISTRAR` -- la que confirma canónicamente una patente en `vehiculos.json` vía `confirmar_vehiculo` -- no disparaba ninguna revalidación, así que `PATENTE_SIN_HOMOLOGAR` podía sobrevivir indefinidamente en el dataset aunque la patente ya estuviera `CONFIRMADO`+`ACTIVO`. Reproducido con evidencia real: guía 464740 (`patente_tracto=XF3629`) mantiene `PATENTE_SIN_HOMOLOGAR | CLIENTE_AUSENTE` en el CSV real pese a que `vehiculos.json` real tiene `XF3629` como `CAMION_RIGIDO`/`CONFIRMADO`/`ACTIVO` desde el 2026-08-17 (evidencia `DECISION_HUMANA_R3_6`, actor `JAVIER_MBT`).

**Matriz de revalidación (resumen):** `PATENTE_SIN_HOMOLOGAR` (catálogo de vehículos) y `OBRA_DESTINO_SIN_CORROBORAR` (catálogo obra↔destino, sin cambios de R3.4) son los únicos motivos cubiertos. `CLIENTE_AUSENTE`, `CHOFER_AUSENTE`, `TRANSPORTE_AUSENTE`, `GUIA_AUSENTE`, `DOCUMENTO_DEGRADADO`, `CLIENTE_SIN_CORROBORAR`, `CHOFER_SIN_CORROBORAR`, `PATENTE_AMBIGUA` y `CLIENTE_NUEVA_ENTIDAD_NO_CATALOGADA` quedan explícitamente fuera -- auditados y descartados por depender de OCR/ausencia documental o de una ambigüedad real que no debe resolverse automáticamente.

**Implementación:** `atlas_core/revalidacion_documental.py` gana `_vehiculo_homologado` y `revalidar_patente_sin_homologar_sin_ocr`, que releen el CSV bajo `bloqueo_sesion`, reevalúan fila por fila únicamente `PATENTE_SIN_HOMOLOGAR` contra `cargar_catalogo_vehiculos(...).homologables()` (vehículos `CONFIRMADO`+`ACTIVO`) aplicando la regla final de R3.6.1 (rampla→CARRO; tracto+rampla→TRACTO; tracto aislado→TRACTO o CAMION_RIGIDO) y escriben atómicamente sólo si algo cambió. `revalidar_y_regenerar_reporte` ahora ejecuta ambas revalidaciones (obra/destino + patente) como pases atómicos independientes y conmutativos, combina las guías actualizadas y regenera el reporte si cualquiera cambió algo. `aplicacion_decisiones.py` añade el disparo para `VEHICULO_DESCONOCIDO`/`REGISTRAR` junto al ya existente de destino.

**Tests:** `tests/test_revalidacion_patente_r362.py` (nuevo, 15 tests) cubre vehículo resuelto, parcialmente resuelto, tipo incompatible, patente inactiva/no confirmada, camión rígido, idempotencia, independencia de otros motivos, catálogo ausente y el orquestador combinado. `tests/test_aplicacion_vehiculos_r361.py` se ajustó (fixture con esquema CSV mínimo incompatible con el nuevo disparo de revalidación, reemplazado por el esquema oficial completo, sin cambiar las aserciones originales). Focalizados: **15 passed**. Grupo relacionado (patente + vehículos R3.6.1 + destinos R3.4/R3.3): **87 passed**. Suite completa verificada independientemente por el orquestador: `python -m pytest -q` → **1145 passed, 0 failed** (baseline R3.6.1 = 1130 + 15 nuevos).

**Validación real read-only**, verificada de forma independiente (no sólo por el agente implementador): se copiaron `analisis_completo_guias.csv` y los catálogos JSON reales hacia una carpeta temporal fuera de Drive; la nueva función se ejecutó exclusivamente sobre esa copia. Guía **464740**: `PATENTE_SIN_HOMOLOGAR | CLIENTE_AUSENTE` → `CLIENTE_AUSENTE` (XF3629 resuelve como tracto aislado CAMION_RIGIDO confirmado/activo; CLIENTE_AUSENTE no es catalogal, se conserva). Guía **464726** (`patente_tracto=KN5439`, `patente_rampla=JF6468`): pierde `PATENTE_SIN_HOMOLOGAR` por completo y queda `OK` (KN5439=TRACTO, JF6468=CARRO, ambas confirmadas/activas). `OBRA_DESTINO_SIN_CORROBORAR`: 0 filas actualizadas sobre la misma copia, sin regresión. Se confirmó por `mtime` que `G:\Mi unidad\Atlas\operacion\actual\analisis_completo_guias.csv` y `catalogos_privados\vehiculos.json` no cambiaron durante todo el bloque.

**Desktop:** sin cambios (`git status` limpio, `git diff --stat` vacío) -- R3.6.2 se resolvió íntegramente en Motor. **Drive modificado: NO.** Sin commit ni push en ningún repo; working tree del Motor: `atlas_core/aplicacion_decisiones.py`, `atlas_core/revalidacion_documental.py`, `tests/test_aplicacion_vehiculos_r361.py` modificados + `tests/test_revalidacion_patente_r362.py` nuevo (3 files changed, 186 insertions(+), 24 deletions(-) + 1 archivo nuevo). `git diff --check` limpio (sólo avisos LF→CRLF).

**Pendiente explícito:** aplicación real controlada contra `G:\Mi unidad\Atlas` (con backup previo, bajo supervisión de Javier), que resolvería `PATENTE_SIN_HOMOLOGAR` en 464726 y 464740 y regeneraría el reporte vigente -- deliberadamente no ejecutada en este bloque.
## 2026-08-17 — R3.6.2: aplicación real controlada contra la operación vigente

**Pre-vuelo:** re-verificado antes de escribir -- Motor en `lector-mvp-guia-nueva`, `b4e11f9` ancestro de HEAD, único diff local el ya auditado de R3.6.2 (código + tests + bitácoras), `git diff --check` limpio. Alcance de escritura de `revalidar_y_regenerar_reporte` determinado con certeza por lectura de código antes de ejecutar: (1) reescritura atómica en el propio archivo de `operacion/actual/analisis_completo_guias.csv` (vía `_escribir_filas_completas`, temp-file + `os.replace`), sólo si `guias_actualizadas` no está vacío; (2) creación de una carpeta nueva `reportes/<nombre_carpeta_reporte>/` (`generar_reporte_viajes`, rechaza sobrescribir un reporte existente vía `_validar_rutas`); (3) reescritura atómica de `operacion/actual/estado_operacion.json` (`escribir_json_atomico`) apuntando `reporte_vigente` a la carpeta nueva; (4) lock transitorio `.atlas_lock_revalidacion_dataset` creado y liberado dentro del mismo `with`. Ningún catálogo (`vehiculos.json`, `obras_destinos.json`, `clientes.json`, `destinos_maestros.json`, etc.) es escrito por ninguna de las dos funciones de revalidación -- sólo leídos.

**Backup:** `respaldos/R3_6_2_ROLLBACK_PRE_APLICACION_20260817_165251/` con `MANIFIESTO_ROLLBACK_R3_6_2.json`, copia de `analisis_completo_guias.csv` y `estado_operacion.json` (los dos únicos archivos existentes que la operación modificaría in-place). SHA-256 calculado antes de copiar y verificado idéntico después: CSV `90E268557964E5D96AC4D30CF81F41D07F6F31C303C463B8128008E73FE3E480`, `estado_operacion.json` `A4AFE09A78E95D69D48DF67DD882CBFF521CFFDAE2FAFFB0DA2062CE56D9168B`. Dry-run final (copia temporal fuera de Drive, inmediatamente antes de escribir) reprodujo exactamente `{'guias_actualizadas': ['464726', '464740']}` para patente y `[]` para obra/destino -- coincide con la simulación anterior; nada cambió en Drive entre ambas mediciones (confirmado por `mtime`).

**Aplicación:** `revalidar_y_regenerar_reporte(raiz_atlas="G:\Mi unidad\Atlas", nombre_carpeta_reporte="reporte_revalidacion_20260817_205408_942731")` -- mismo esquema de nombre (`reporte_revalidacion_{timestamp}`) que usa el disparo ya auditado desde `aplicacion_decisiones.py`. Resultado: `filas_totales=28`, `guias_actualizadas=['464726','464740']`, `reporte_regenerado=True`.

**Validación posterior (lectura exhaustiva antes/después, no sólo el resultado devuelto):** 28 filas antes y después, mismo conjunto exacto de `numero_guia` (sin altas ni bajas). Diff fila por fila contra el backup: exactamente 2 filas cambiaron, ambas únicamente en `motivos_revision_documento`/`indicador_revision` (ninguna otra columna tocada en ninguna fila); las 26 filas restantes son byte-idénticas al backup.

| guía | antes | después | razón |
|---|---|---|---|
| 464726 | `PATENTE_SIN_HOMOLOGAR` / REVISAR | (sin motivos) / **OK** | KN5439=TRACTO y JF6468=CARRO, ambas `CONFIRMADO`+`ACTIVO`, compatibles con tracto+rampla -- todas las patentes relevantes resueltas |
| 464740 | `PATENTE_SIN_HOMOLOGAR \| CLIENTE_AUSENTE` / REVISAR | `CLIENTE_AUSENTE` / **REVISAR** | XF3629=CAMION_RIGIDO `CONFIRMADO`+`ACTIVO`, tracto aislado (sin rampla) -- resuelve `PATENTE_SIN_HOMOLOGAR`; `CLIENTE_AUSENTE` no es catalogal, se conserva intacto tal como exige la política conservadora |

Dataset final: 25 OK / 3 REVISAR (antes 24/4); motivos `MATERIAL_AUSENTE`(1)/`OBRA_DESTINO_SIN_CORROBORAR`(2)/`CLIENTE_AUSENTE`(1) sin cambio, `PATENTE_SIN_HOMOLOGAR` en 0 filas (antes 2). El nuevo `viajes.csv` del reporte regenerado refleja correctamente ambos casos (464726 `CONFIRMADO`/sin motivo; 464740 `REQUIERE_REVISION`/`CLIENTE_AUSENTE` a nivel de evidencia documental).

**Integridad de lo que no debía cambiar, verificada por `mtime` exacto antes/después:** los 11 archivos de `catalogos_privados/` (incluidos `vehiculos.json` y `obras_destinos.json`) conservaron su `mtime` previo al bloque -- cero escrituras. `cache/`, `datos_privados/` (imágenes/entradas), `coordinacion/` y `historico_pre_infra_s2/` sin cambios. `decisiones_pendientes.json`/`decisiones_aplicadas.json` sin cambios. Ningún reporte histórico previo (`reporte_desktop_20260814_130625`, `reporte_revalidacion_20260817_142555`, `historicos/`) fue tocado; sólo se creó la carpeta nueva. Ningún lock huérfano quedó en `operacion/actual/`.

**Rollback:** no requerido -- cero diferencias inesperadas en toda la validación. Backup preservado deliberadamente (no eliminado) hasta confirmar estabilidad y publicar. No se repitió la suite completa de pytest (código sin cambios desde los 1145 passed ya verificados en el bloque anterior). Sin commit ni push en ningún repo -- working tree del Motor sin cambios adicionales de código respecto al bloque anterior (sólo esta entrada de bitácora).

**Estado: R3.6.2 VALIDADO REALMENTE -- LISTO PARA PUBLICAR.**
## 2026-08-17 — R3.6.2 publicado y auditoría funcional post-cierre

**Publicación:** commit `a46b3e8` ("feat: revalidar motivos catalogales tras aprendizaje", 7 archivos: código + tests + 3 bitácoras) creado sobre `b4e11f9` y pusheado a `origin/lector-mvp-guia-nueva` (push normal, sin force). Verificación post-push: local=remoto (`a46b3e8` ambos), ahead/behind 0/0, working tree limpio. Backup `respaldos/R3_6_2_ROLLBACK_PRE_APLICACION_20260817_165251/` preservado sin eliminar, tal como se instruyó.

**Auditoría funcional (read-only):** cubrió lectura/OCR, extracción, Revisión de Atlas (decisiones pendientes/aplicadas), viajes, catálogos, Desktop/UX y reportes, contrastando bitácoras contra código y datos reales actuales. Sin código nuevo, sin cambios en Drive. Hallazgos verificados con evidencia concreta (no sólo documentados):
- `TIPOS_SOPORTADOS` (`decisiones_pendientes.py`) define 6 tipos de decisión; `ACCIONES_POR_TIPO` (`aplicacion_decisiones.py`) sólo implementa 3 (`OBRA_DESCONOCIDA`, `DESTINO_SIN_CONFIRMAR`, `VEHICULO_DESCONOCIDO`) -- `CLIENTE_DESCONOCIDO`, `CLIENTE_CANDIDATO` y `ALIAS_CANDIDATO` se detectan pero no tienen aplicación real; Desktop (`decisiones_pendientes_ui.js`) muestra literalmente "disponible en un próximo bloque".
- `CLIENTE_SIN_CORROBORAR`/`CHOFER_SIN_CORROBORAR` no generan ningún tipo de decisión -- 6/29 choferes reales del catálogo siguen con clave temporal `PENDIENTE0000000X` sin vía de resolución auditable.
- Falso `CONFLICTO_RUT_CHOFER` por formato de RUT en `gestor_viajes.py` -- ver bloque siguiente.
- Posible duplicado en `vehiculos.json` (`BKYX63`/`BKYK63`, mismo lote de migración legacy, un carácter de diferencia, sin confirmación humana real). Pestaña "Revisión de destinos" de Desktop huérfana (su generador del Motor, del piloto ORS de julio, ya no existe -- fue superseded por `DESTINO_SIN_CONFIRMAR`).
- Sin `P0`. Recomendado como próximo bloque el falso `CONFLICTO_RUT_CHOFER`, por ser el único `P1` acotado a un solo archivo y sin necesidad de diseño de producto nuevo.

## 2026-08-17 — P1: corrección del falso `CONFLICTO_RUT_CHOFER` por formato

**Diagnóstico:** `atlas_core/gestor_viajes.py::agrupar_viajes` evalúa diez campos de conflicto (`campos_conflicto`) usando uniformemente `_valores_compatibles`, que compara vía `_clave_normalizada` (casefold + colapso de espacios + remoción de acentos) -- sin quitar puntuación. `rut_chofer` compartía exactamente esa misma comparación genérica que chofer/cliente/obra/patentes/fecha/horas, así que `"10.833.150-K"` y `"10833150-K"` (mismo RUT, mismo chofer, dos documentos del mismo viaje) se consideraban valores distintos y disparaban `CONFLICTO_RUT_CHOFER`. Caso real confirmado en el dataset vigente antes de tocar código: transporte `0000352752`, guías 464641/464642, chofer JOSE LAZCANO -- único motivo de ese viaje.

**Corrección:** nueva función `_valores_compatibles_rut(valores)`, usada exclusivamente para `CONFLICTO_RUT_CHOFER` (los otros nueve campos siguen usando `_valores_compatibles` sin cambios). Reutiliza `normalizar_rut` de `atlas_core/catalogos.py` -- la misma utilidad canónica que Atlas ya usa en `procesamiento_masivo.py` para corroborar RUT de chofer contra catálogo (uppercase + conserva sólo dígitos y "K"), sin crear una segunda implementación. Si el valor normalizado queda vacío (texto sin ningún dígito/"K" -- no tiene forma de RUT), cae a `_clave_normalizada` como antes, para no fusionar dos textos no-RUT distintos en una igualdad artificial. `campos_conflicto` pasó de pares `(motivo, valores)` a tripletas `(motivo, valores, comparador)`, con el comparador explícito por campo -- cambio mínimo y localizado, sin refactor amplio. Import nuevo: `from atlas_core.catalogos import normalizar_rut` (sin riesgo de import circular, verificado).

**Tests:** 12 nuevos en `tests/test_gestor_viajes.py` -- equivalencia de formato (puntos/guion/espacios), dígito verificador en minúscula, RUT realmente distinto (conflicto preservado), RUT ausente en un documento (comportamiento previo conservado), texto no-RUT distinto (conflicto preservado, no oculto), texto no-RUT idéntico (compatible, sin regresión), y confirmación explícita de que la comparación de `chofer` (formato distinto, contenido distinto) no cambió. Focalizados: `tests/test_gestor_viajes.py` **55 passed** (43 preexistentes + 12 nuevos, incluyendo el test paramétrico ya existente de conflicto real de RUT `12.345.678-5` vs `9.999.999-9`, que sigue detectando conflicto). Grupo relacionado (`test_gestor_viajes.py` + `test_reporte_viajes.py` + `test_catalogos.py`): **110 passed**. Suite completa: **1157 passed, 0 failed** (baseline 1145 + 12).

**Validación real read-only:** se extrajo con `git show a46b3e8:atlas_core/gestor_viajes.py` la versión pre-fix a un módulo aislado y se corrió `agrupar_viajes` con ambas versiones (antes/después) sobre el mismo dataset real leído en memoria, sin escribir nada. De los 24 viajes reales, exactamente 2 cambiaron:
- `0000352752` (464641/464642): `REQUIERE_REVISION`/`[CONFLICTO_RUT_CHOFER]` → `CONFIRMADO`/`[]`.
- `0000352376` (464698/464699/464700, hallazgo nuevo no anticipado): `REQUIERE_REVISION`/`[CONFLICTO_CLIENTE, CONFLICTO_OBRA_DESTINO, CONFLICTO_RUT_CHOFER]` → `REQUIERE_REVISION`/`[CONFLICTO_CLIENTE, CONFLICTO_OBRA_DESTINO]` -- mismo chofer CARLOS SIMON, RUT `15.489.424-1` vs `15489424-1` (formato); pierde únicamente el motivo de RUT y conserva intactos los dos conflictos reales e independientes (EBEMA/OCL vs PRODALAM/EBCO, ya documentado como pendiente de "consolidación inteligente de viajes"). Los 22 viajes restantes quedaron exactamente iguales (mismo estado, mismos motivos).

**Impacto:** confirmado que sólo cambió la comparación de `rut_chofer` -- ningún otro campo de conflicto, ninguna otra guía, ningún catálogo. Desktop no fue tocado. Drive no fue modificado (todas las lecturas fueron read-only; el resultado de la validación no se escribió al dataset real). Sin commit ni push -- working tree con `atlas_core/gestor_viajes.py` y `tests/test_gestor_viajes.py`.

**Estado: LISTO PARA VALIDACIÓN REAL.** Aplicación controlada sobre Drive (con backup/rollback, mismo procedimiento de R3.6.2) queda para el siguiente bloque.
## 2026-08-17 — Diagnóstico Viajes ↔ Revisión de Atlas

Auditoría 100% read-only (sin código, sin Drive escrito) para diagnosticar por qué Atlas puede mostrar viajes `REQUIERE_REVISION` mientras Revisión de Atlas muestra 0 pendientes, antes de tocar nada.

**Inventario canónico**: 12 `MotivoRevisionDocumento` (nivel documento, `procesamiento_masivo.py:619-655`) + 12 `MotivoRevision` (nivel viaje, `gestor_viajes.py:126-142`, 8 de ellos `CONFLICTO_*`). `TIPOS_SOPORTADOS` (`decisiones_pendientes.py:36-39`) declara 6 tipos de decisión; `ACCIONES_POR_TIPO` (`aplicacion_decisiones.py:30-34`) sólo implementa 3. **Confirmado por grep exhaustivo**: `CLIENTE_CANDIDATO` es código muerto -- aparece una única vez en todo el repo, sólo en la declaración del set, nunca generado por ningún flujo.

**Tres causas raíz de la desconexión**, todas verificadas con datos reales del dataset/catálogos vigentes:
1. `decisiones_pendientes.json` real tiene `"decisiones": []` -- correcto por diseño respecto del artefacto, pero incompleto respecto de la operación real.
2. **Brecha estructural confirmada con evidencia concreta**: `decisiones_aplicadas.json` real registra `OBRA_DESCONOCIDA→REGISTRAR` aplicada a las guías `464718` (16:03:50) y `464746` (16:05:16); ambas obras (`c3304fe6...`, `c7fcb561...`) existen en `obras_destinos.json` con `estado=OBSERVADA`/`ACTIVO`, pero con `relaciones: []` -- ninguna relación destino, porque `registrar_observacion` sin `destino_id` nunca crea una (`catalogo_obras_destinos.py:492-553`). `detectar_decisiones_documento` sólo corre en el OCR original (`procesamiento_masivo.py:1563`); nunca se re-ejecuta sobre un documento ya persistido. Ambas guías, en el dataset real de hoy, siguen `OBRA_DESTINO_SIN_CORROBORAR`/`REVISAR` -- callejón sin salida confirmado, no teórico.
3. Ningún `CONFLICTO_*` de nivel viaje (`gestor_viajes.py`) tiene tipo de decisión asociado en `TIPOS_SOPORTADOS`.

**Hallazgo adicional en Desktop, confirmado con código y dato real**: `src/atlas_viajes.html:1222-1224` (`renderDatosAuxiliares`) usa `motivosPresentables = motivosDocumentales.length ? motivosDocumentales : viaje.motivos` -- si CUALQUIER documento del viaje trae un motivo (incluso no bloqueante como `MATERIAL_AUSENTE`), oculta los `CONFLICTO_*` reales de nivel viaje. Confirmado con el caso real `0000352376`: la guía `464699` trae `MATERIAL_AUSENTE`, lo que en Desktop tapa `CONFLICTO_CLIENTE`/`CONFLICTO_OBRA_DESTINO`, los motivos que realmente bloquean ese viaje.

**Estado persistido antes de este bloque**: 5/24 viajes `REQUIERE_REVISION` (`0000352752`, `0000352376`, `0000353081`, `0000353164`, `0000353160`). **Recalculado con el Motor `2cb67cb` en memoria** (sin escribir): 4/24 -- `0000352752` se resuelve por completo, `0000352376` conserva sus 2 conflictos reales.

Clasificación A–E completa de los 24 motivos, matriz motivo↔decisión, y plan de 7 bloques derivado de la evidencia (no de nomenclatura previa): (1) aplicar fix de RUT al dataset real, (2) cerrar ciclo `OBRA_DESCONOCIDA→DESTINO_SIN_CONFIRMAR` para documentos ya procesados, (3) alinear Desktop con el motivo real, (4) aplicación real de `CLIENTE_DESCONOCIDO`/`ALIAS_CANDIDATO`, (5) inspección guiada para cliente/chofer sin corroborar, (6) conflictos de viaje, (7) `PATENTE_AMBIGUA`. Próximo bloque recomendado: el (1), por ser el único ya resuelto en código y sin necesidad de diseño de producto -- ejecutado en el bloque siguiente.

## 2026-08-17 — Paso 1: fix de RUT (`2cb67cb`) aplicado realmente al reporte vigente

**Mecanismo canónico identificado y verificado antes de escribir**: `generar_reporte_viajes.py` (CLI de producción) invoca `generar_reporte_viajes` (`reporte_viajes.py:398`), que internamente llama `agrupar_viajes` -- la misma función que ya contiene el fix de RUT desde `2cb67cb`. Alcance de escritura confirmado por lectura de código: `generar_reporte_viajes` **nunca escribe** `analisis_completo_guias.csv` (sólo lo lee, con guardia SHA-256 pre/post que aborta con `RuntimeError` si cambia durante la lectura -- nunca escribe en ese caso tampoco); crea una carpeta nueva de reporte (`_validar_rutas` rechaza sobrescribir una existente); y el CLI publica el manifiesto (`escribir_estado_operacion`, reescritura atómica de `operacion/actual/estado_operacion.json`). Ningún catálogo, decisión o imagen es tocado por este mecanismo.

**Backup**: `respaldos/FIX_RUT_ROLLBACK_PRE_APLICACION_20260817_193719/` con `MANIFIESTO_ROLLBACK_FIX_RUT.json` -- copia de `estado_operacion.json` (único archivo existente modificado in-place; SHA-256 `34452E8E...E44976`, verificado idéntico tras copiar) y referencia SHA-256 de `analisis_completo_guias.csv` (`5FE0F384...D5810B71`) para demostrar después que nunca cambió.

**Dry-run** sobre copia temporal fuera de Drive (`generar_reporte_viajes.py` corrido contra una copia del CSV y catálogos reales) reprodujo exactamente el resultado esperado antes de tocar Drive: 24 viajes, 20 confirmados / 4 requieren revisión.

**Aplicación real**: `python generar_reporte_viajes.py "operacion/actual/analisis_completo_guias.csv" "reportes/reporte_fix_rut_chofer_20260817_233840" --catalogos "catalogos_privados"`, ejecutado contra `G:\Mi unidad\Atlas` real. Resultado idéntico al dry-run: 28 filas leídas, 24 viajes, 20 confirmados, 4 requieren revisión.

**Validación exhaustiva fila por fila** (comparación completa entre el `viajes.csv` del reporte anterior y el nuevo, excluyendo `fecha_creacion` que cambia en las 24 filas por ser timestamp de regeneración, no dato de viaje): columnas idénticas, 24→24 filas, mismo conjunto exacto de `numero_transporte`. **Exactamente 2 cambios semánticos**, ninguno más:
- `0000352752`: `estado` `REQUIERE_REVISION`→`CONFIRMADO`, `motivos_revision` `CONFLICTO_RUT_CHOFER`→`''`.
- `0000352376`: `motivos_revision` `CONFLICTO_RUT_CHOFER | CONFLICTO_CLIENTE | CONFLICTO_OBRA_DESTINO`→`CONFLICTO_CLIENTE | CONFLICTO_OBRA_DESTINO`; `estado` sin cambio (`REQUIERE_REVISION`).

**Integridad de lo que no debía cambiar, verificada por SHA-256/`mtime` exacto**: `analisis_completo_guias.csv` SHA-256 idéntico antes/después (`5FE0F384...D5810B71`) -- nunca escrito. Los 11 archivos de `catalogos_privados/`, `decisiones_pendientes.json`/`decisiones_aplicadas.json`, `cache/`, `datos_privados/` (imágenes), `coordinacion/` y todos los reportes históricos previos (`reporte_desktop_20260814_130625`, `reporte_revalidacion_20260817_142555`, `reporte_revalidacion_20260817_205408_942731`, `historicos/`) conservaron su `mtime` exacto -- ninguno tocado. Sólo cambiaron `respaldos/` (backup nuevo) y `reportes/` (carpeta nueva). `estado_operacion.json` actualizado, apuntando a `reportes/reporte_fix_rut_chofer_20260817_233840`.

**Rollback**: no requerido -- cero diferencias inesperadas en toda la validación. Backup preservado, no eliminado. Motor y Desktop verificados sin cambios de código tras la operación (`git status --short` vacío en ambos, HEAD `2cb67cb`/`87b9c8c` intactos) -- el único cambio en el working tree del Motor son estas tres entradas de bitácora, sin commit.

**Estado: FIX RUT APLICADO REALMENTE -- LISTO PARA PASO 2.**
## 2026-08-17 — Paso 2: R3.4.2, cierre del ciclo `OBRA_DESCONOCIDA→DESTINO_SIN_CONFIRMAR→REVALIDACIÓN`

**Checkpoint verificado antes de tocar código:** Motor `lector-mvp-guia-nueva` HEAD `f770958`, local=remoto, ahead/behind 0/0, working tree limpio. Desktop `fix-desktop-data-root-drag-drop` HEAD `87b9c8c`, working tree limpio. Drive accesible en `G:\Mi unidad\Atlas`, tratado READ-ONLY durante todo el desarrollo.

**Fase A -- reproducción y auditoría (antes de modificar nada):** se leyeron completos `aplicacion_decisiones.py`, `decisiones_pendientes.py`, `revalidacion_documental.py` y `catalogo_obras_destinos.py`, y se confirmó contra Drive real (read-only) el estado exacto de los dos casos reales:

| guía | obra_id | estado obra | `relaciones` | `motivos_revision_documento` (CSV real) |
|---|---|---|---|---|
| 464718 | `c3304fe6-6138-42a1-b0ee-5234b64d70e3` | `OBSERVADA`/`ACTIVO` | `[]` | `OBRA_DESTINO_SIN_CORROBORAR` |
| 464746 | `c7fcb561-cff0-4893-a2a2-5990c965a972` | `OBSERVADA`/`ACTIVO` | `[]` | `OBRA_DESTINO_SIN_CORROBORAR` |

Ambos ledger entries (`decisiones_aplicadas.json` real) confirman `OBRA_DESCONOCIDA`→`REGISTRAR` aplicado por `JAVIER_DESKTOP`, sin `destino_id`. Ambas filas del CSV real tienen `despachar_a_crudo` no vacío (`RICARDO MORALES 3369 SAN MIGUEL SAN MIGUEL` / `CAM. EL NOVICIADO LAMPA LAMPA`) -- destino documental SÍ existe, así que los dos casos reales caen en CASO B (confirmación humana), no en CASO C.

**Causa raíz exacta (dos factores, no uno):**
1. `detectar_decisiones_documento` (`decisiones_pendientes.py:296-386`) sólo puede emitir `DESTINO_SIN_CONFIRMAR` dentro del `elif` que exige `obras` no vacío (línea ~353) -- necesita un `obra_id` ya resuelto. Cuando la obra es realmente desconocida (`not obras`, línea 329), sólo se emite `OBRA_DESCONOCIDA`; la dirección documental (`despachar_a_documental`, ya resuelta por `resolver_entrega_documento` y disponible en ese momento) se **descartaba** -- no se guardaba en ningún lado.
2. `aplicar_decision_obra` (`aplicacion_decisiones.py:212-243`), al aplicar `OBRA_DESCONOCIDA`/`REGISTRAR`, llama `registrar_observacion(cliente_id=..., nombre_obra=...)` **sin** `destino_id` -- la obra queda creada pero sin relación. Y el único mecanismo que corre después de aplicar una decisión, `regenerar_decisiones_persistidas`, **reclasifica decisiones ya persistidas** (filtra/actualiza contexto) pero nunca **sintetiza un tipo nuevo** a partir de datos ya observados -- no existía ninguna vía, ni al aplicar ni al regenerar, para que apareciera la pregunta de destino. Documento y obra quedan en un callejón sin salida real, confirmado con evidencia (no supuesto).

**Fix implementado, aditivo sobre el contrato de R3.4:**
1. `detectar_decisiones_documento`: el `contexto` de `OBRA_DESCONOCIDA` ahora incluye `destino_documental` (mismo valor de `despachar_a_documental`, sin nueva extracción) -- dato que antes se perdía. No cambia `decision_id` (contexto no participa de la identidad).
2. Nueva función `decision_destino_para_obra_registrada(*, obra, cliente_id, cliente_canonico, destino_documental, documento, catalogo_obras)` en `decisiones_pendientes.py`. Reconstruye, sin OCR, la misma decisión `DESTINO_SIN_CONFIRMAR` que `detectar_decisiones_documento` habría generado si la obra ya hubiera existido:
   - **CASO A** (destino ya corroborable): si `catalogo_obras.resolver_obra_destino_confirmada_global(nombre_obra=obra.nombre_canonico)` ya resuelve, devuelve `None` -- nada redundante que preguntar.
   - **CASO B** (confirmación humana): si hay `destino_documental` no ausente, genera la decisión `DESTINO_SIN_CONFIRMAR` completa (mismo `campo`, `evidencias`, `acciones_permitidas`, `contexto` que generaría la detección en vivo).
   - **CASO C** (información insuficiente): `destino_documental` ausente/vacío -- o decisión persistida de antes de este cambio, sin el campo -- devuelve `None`. Nunca inventa.
3. Conectado en dos puntos:
   - `aplicar_decision_obra`, rama `OBRA_DESCONOCIDA`/`REGISTRAR`: justo después de `registrar_observacion`, calcula `decision_siguiente` con la función anterior y, si no es `None`, la agrega a `restantes` antes de `generar_artefacto` -- entra a la bandeja publicada en la misma transacción que registra la obra.
   - `regenerar_decisiones_persistidas`, en el punto donde ya hacía `continue` silencioso al encontrar que una `OBRA_DESCONOCIDA` persistida referencia una obra que **ya existe** (por cualquier vía, no sólo la propia decisión) -- ahora, antes de descartarla, intenta sintetizar su propia pregunta de destino con la misma función y la agrega al resultado. Cubre el caso general (otra guía, misma obra, registrada por un camino distinto) sin reparar nada a mano.

**Idempotencia y no-resurrección, por diseño existente, no por código nuevo:** `decision_id` de la decisión sintetizada es determinístico (hash de tipo+documento+campo+valor_documental+evidencias, igual que si se hubiera generado en vivo). `generar_artefacto` ya filtra contra `decisiones_aplicadas.json` (`ids_terminales`) antes de publicar -- así que si `regenerar_decisiones_persistidas` vuelve a sintetizar una decisión ya `CONFIRMAR`/`NO_CONFIRMAR`, `generar_artefacto` la descarta igual: nunca resucita. Verificado con test explícito (`test_rechazo_terminal_de_la_nueva_decision_no_resucita_al_regenerar`). R3.5/R3.5.1 (regeneración encadenada A→B, ventana legacy de bandeja) no se tocaron.

**Desktop:** verificado ANTES de tocar Motor que `decisiones_pendientes_ui.js` ya renderiza y aplica `DESTINO_SIN_CONFIRMAR` de forma completamente genérica (mismo mecanismo que `OBRA_DESCONOCIDA`/`VEHICULO_DESCONOCIDO`, opciones `Confirmar`/`No confirmar`/`Decidir después`, tarjeta con "Obra reconocida"). No hace falta ninguna brecha que cerrar del lado Desktop -- se dejó intacto, tal como exige el roadmap.

**Tests (`tests/test_ciclo_obra_destino_r342.py`, 13 nuevos):** CASO B genera la decisión siguiente con todos los campos correctos; CASO C (destino vacío y "No encontrado") no inventa; CASO A (obra ya corroborable por otra vía) no genera decisión redundante ni duplica obra/relación; decisión consecutiva obra→destino sin `DecisionObsoletaError`, con revalidación automática y motivo retirado del CSV; decidir después (POSPONER) permanece pendiente sin escribir nada; rechazo terminal no resucita al regenerar; idempotencia (repetir regeneración y reaplicar REGISTRAR no duplican); motivos independientes preservados; regeneración general sintetiza para otra guía con la misma obra (Path 2) y se abstiene sobre decisiones legado sin el campo nuevo; obsolescencia normal preservada también para la decisión sintetizada. Más 1 test existente actualizado (`test_obra_desconocida_transporta_cliente_reconocido_separado_de_la_obra`, contexto esperado ahora incluye `destino_documental`).

**Suites ejecutadas:** focalizados (`test_ciclo_obra_destino_r342.py`) **13 passed**. Grupo relacionado (obra/destino/decisión/vehículo R3.6/revalidación, `-k "obra or destino or decision or vehiculo_r36 or revalidacion"`) **265 passed**. Suite completa del Motor: **1170 passed, 0 failed** (baseline 1157 + 13).

**Validación real read-only sobre 464718 y 464746** (sin escribir en Drive; hash de `obras_destinos.json`/`destinos_maestros.json` verificado idéntico antes/después): se llamó `decision_destino_para_obra_registrada` directamente con la obra real ya cargada de `obras_destinos.json` y el `despachar_a_crudo` real de cada guía leído del CSV real.
- 464718: obra `CONSULTORES EN ARQUITECTURA` (`OBSERVADA`) → decisión `DESTINO_SIN_CONFIRMAR`, `valor_documental="RICARDO MORALES 3369 SAN MIGUEL SAN MIGUEL"`, `identidad_resuelta.entidad_id="c3304fe6-6138-42a1-b0ee-5234b64d70e3"`, `acciones_permitidas=["CONFIRMAR","NO_CONFIRMAR","POSPONER"]`.
- 464746: obra `EMPRESA CONSTRUCTORA MENA Y` (`OBSERVADA`) → decisión `DESTINO_SIN_CONFIRMAR`, `valor_documental="CAM. EL NOVICIADO LAMPA LAMPA"`, `identidad_resuelta.entidad_id="c7fcb561-cff0-4893-a2a2-5990c965a972"`, misma `acciones_permitidas`.

Confirma que el fix general produce exactamente el siguiente paso correcto para ambos casos reales, sin código específico para ninguno de los dos. **No se reparó el histórico real** -- 464718/464746 siguen atrapados hoy en Drive; la reconciliación real (aplicar esto contra Drive, con backup/rollback) queda deliberadamente para el bloque siguiente, tal como instruye el roadmap.

**Estructura:** todo el desarrollo permaneció dentro de `Proyecto-Atlas/` (código) y el scratchpad de sesión (validación read-only temporal, eliminado). Sin clones, sin carpetas de prueba permanentes, sin `v2`.

**Drive modificado: NO.** Sin commit ni push en ningún repo -- working tree del Motor con `atlas_core/decisiones_pendientes.py`, `atlas_core/aplicacion_decisiones.py`, `tests/test_ciclo_obra_destino_r342.py` (nuevo) y `tests/test_decisiones_pendientes.py` modificados, más estas tres bitácoras.

**Estado: LISTO PARA VALIDACIÓN REAL** (aplicación controlada sobre Drive para 464718/464746 -- y cualquier otra guía real en el mismo estado -- queda para el bloque siguiente, con el mismo procedimiento de backup/rollback ya usado en bloques anteriores).
## 2026-08-17 — Paso 3: R3.4.3, reconciliación histórica del ciclo obra→destino aplicada realmente

**Checkpoint verificado antes de continuar:** Motor `f770958`, working tree con exactamente el diff del Paso 2 (`git diff --stat` idéntico), Desktop `87b9c8c` limpio, suite `1170 passed, 0 failed` sin cambios desde el cierre del Paso 2.

**Intento inicial de validación real -- descubrió una brecha real, no asumida:** copié (read-only) los archivos reales relevantes a TEMP y ejecuté exactamente el mecanismo implementado en el Paso 2 contra el estado real: (1) reaplicar la decisión original `OBRA_DESCONOCIDA` de 464718 vía `aplicar_decision_obra` → `{'idempotente': True}`, sin efecto (el ledger corta la ejecución antes de llegar al bloque de síntesis); (2) regenerar la bandeja pendiente real actual (`decisiones_pendientes.json`, que hoy tiene `"decisiones": []`) vía `regenerar_decisiones_persistidas` + `generar_artefacto` → 0 decisiones resultantes. Causa exacta: las dos vías del Paso 2 (síntesis inline al `REGISTRAR`, y reclasificación de decisiones *todavía pendientes*) no cubren una `OBRA_DESCONOCIDA` que ya fue aplicada *antes* de que el fix existiera -- el `contexto.destino_documental` nunca se persistió para esas dos aplicaciones ya hechas, y el ledger (`decisiones_aplicadas.json`) no guarda `contexto`. Reportado como `BLOQUEADO` y consultado a Javier antes de continuar.

**Autorización recibida:** diseñar y, sólo si resulta determinístico/conservador (sin OCR, sin fuzzy, sin heurísticas, reutilizando exclusivamente identidad canónica ya persistida), implementar una reconciliación histórica general -- 464718/464746 deben entrar por la regla general, no por excepción en código.

**Diseño de la regla de elegibilidad (validado primero con un scan read-only sobre el ledger real completo, antes de escribir código):** para cada aplicación `OBRA_DESCONOCIDA`/`REGISTRAR` en `decisiones_aplicadas.json` -- 3 en el ledger real -- se reconstruye `DESTINO_SIN_CONFIRMAR` si y sólo si: (1) la obra referenciada por `obra_id` (del ledger, nunca inferido) existe y sigue `ACTIVA`; (2) el cliente referenciado por `cliente_id` (ídem) existe y sigue `ACTIVO`; (3) existe EXACTAMENTE una fila en el dataset con el mismo `numero_guia` que el ledger asocia a esa aplicación; (4) el `obra_destino` documental de esa fila normaliza EXACTO (sin fuzzy, `normalizar_nombre_obra`, misma regla que usa todo el resto del módulo) al nombre/alias de la MISMA obra -- si no coincide, se descarta sin adivinar; (5) esa fila trae `despachar_a_crudo` no ausente (CASO B; si no lo trae, CASO C, se abstiene); (6) delega en `decision_destino_para_obra_registrada` (ya existente de R3.4.2) para el chequeo CASO A (obra ya corroborada -> se abstiene). Scan real sobre el ledger completo (3 aplicaciones): 464715 se excluye correctamente (relación ya `CONFIRMADA`), sólo 464718/464746 pasan la regla -- **confirmado antes de escribir una sola línea de código de producción**.

**Implementación:** dos funciones nuevas en `atlas_core/revalidacion_documental.py` (mismo módulo que ya hace "leer dataset + reconciliar contra catálogos vigentes, sin OCR" para los otros dos motivos de R3.4/R3.6.2):
- `detectar_decisiones_destino_historicas_sin_ocr(*, raiz_atlas)` -- pura lectura, devuelve la lista de decisiones candidatas. Reutiliza `_leer_filas`/`_AUSENTES` ya existentes en el módulo y `decision_destino_para_obra_registrada` de `decisiones_pendientes.py` (import diferido dentro de la función, mismo patrón ya usado en `revalidar_y_regenerar_reporte` para `NOMBRE_ARTEFACTO` -- sin ciclo de imports, verificado).
- `reconciliar_decisiones_destino_historicas(*, raiz_atlas, reloj=...)` -- combina la bandeja pendiente vigente con las candidatas (vía `regenerar_decisiones_persistidas` + `generar_artefacto`, igual patrón que el resto del sistema) y publica. Sólo escribe `decisiones_pendientes.json`; no toca catálogos, CSV ni ledger. Idempotencia y no-resurrección de decisiones terminales garantizadas por el mismo filtro contra el ledger que ya usa `generar_artefacto` -- no hay lógica nueva de deduplicación.

**Tests (`tests/test_reconciliacion_historica_destino_r343.py`, 14 nuevos):** candidato básico con todos los campos correctos; CASO A (obra ya confirmada, sin candidato); CASO C (destino ausente, sin candidato); fila de dataset ausente; fila ambigua (2 filas con mismo `numero_guia`); `obra_destino` de la fila no coincide con la obra del ledger (correlación no confiable, se descarta); obra inactiva; cliente inactivo; otros tipos/acciones del ledger ignorados (`VEHICULO_DESCONOCIDO`, `NO_REGISTRAR`); reproducción genérica del caso real completo (3 obras, 2 generan candidato, 1 ya confirmada no); publicación sin tocar catálogos/CSV/ledger; idempotencia (repetir no duplica); no resurrección de decisión terminal (simulando un `NO_CONFIRMAR` previo con el mismo `decision_id` determinístico); preserva otras decisiones pendientes no relacionadas. Suite completa: **1184 passed, 0 failed** (baseline 1170 + 14), sin regresiones.

**Dry-run real (no simulado, la función real contra los datos reales, read-only):** `detectar_decisiones_destino_historicas_sin_ocr(raiz_atlas="G:\Mi unidad\Atlas")` → exactamente 2 candidatas, `464718` (destino "RICARDO MORALES 3369 SAN MIGUEL SAN MIGUEL") y `464746` (destino "CAM. EL NOVICIADO LAMPA LAMPA"), cada `decision_id` reproducible byte a byte al repetir la llamada (determinismo verificado con dos corridas idénticas).

**Backup:** `respaldos/CICLO_OBRA_DESTINO_ROLLBACK_PRE_APLICACION_20260817_210220/` con `MANIFIESTO_ROLLBACK_CICLO_OBRA_DESTINO.json` -- copia de `decisiones_pendientes.json` (único archivo real que la operación modificaría in-place), SHA-256 `10379C4F...38BD847` verificado idéntico entre original y copia antes de escribir.

**Aplicación real:** `reconciliar_decisiones_destino_historicas(raiz_atlas="G:\Mi unidad\Atlas")` → `{'decisiones_candidatas': 2, 'decisiones_publicadas': 2}`. `decisiones_pendientes.json` real pasó de `"decisiones": []` a 2 decisiones `DESTINO_SIN_CONFIRMAR`, cada una con `identidad_resuelta.entidad_id`/`contexto.obra_id` apuntando a la obra real ya registrada (`c3304fe6...`/`c7fcb561...`) y `contexto.cliente_id` al cliente real (`fb859a71...`/`840418bf...`), `acciones_permitidas=["CONFIRMAR","NO_CONFIRMAR","POSPONER"]`.

**Integridad verificada, dos formas independientes:** (1) SHA-256 de `obras_destinos.json`, `destinos_maestros.json`, `clientes.json`, `vehiculos.json`, `analisis_completo_guias.csv`, `decisiones_aplicadas.json` y `estado_operacion.json` idénticos antes/después. (2) Escaneo de `mtime` de **todo** el árbol de `G:\Mi unidad\Atlas` en la ventana de los últimos 5 minutos del bloque: únicamente aparecen el backup nuevo y `operacion/actual/decisiones_pendientes.json` -- ningún otro archivo en todo Drive fue tocado.

**No se aplicó ni confirmó ninguna decisión en este bloque** -- ninguna llamada a `aplicar_decision_obra` contra Drive real; las dos decisiones quedan `PENDIENTE`, listas para que Javier las revise/aplique desde Desktop.

**Desktop:** sin cambios de código. Verificado en el Paso 2 que ya renderiza/aplica `DESTINO_SIN_CONFIRMAR` genéricamente -- las dos decisiones nuevas deberían aparecer en Revisión de Atlas sin ningún cambio adicional.

**Drive modificado: SÍ -- únicamente `operacion/actual/decisiones_pendientes.json` y el backup nuevo.** Rollback: no requerido (resultado exactamente igual al dry-run). Backup preservado, no eliminado.

**Estructura:** sin carpetas nuevas fuera de `respaldos/` (backup) y sin tocar `Proyecto-Atlas/` fuera de los archivos ya listados. TEMP del dry-run inicial eliminado al terminar.

**Git:** sin commit, sin push. Working tree del Motor: `atlas_core/revalidacion_documental.py` modificado (+2 funciones) y `tests/test_reconciliacion_historica_destino_r343.py` nuevo, sobre el diff ya existente del Paso 2, más estas tres bitácoras.

**Estado: DECISIONES RECONCILIADAS -- LISTO PARA VALIDACIÓN VISUAL DE JAVIER.** Próximo paso: Javier abre Atlas Viajes DESARROLLO → Revisión de Atlas y confirma visualmente que 464718/464746 aparecen como `DESTINO_SIN_CONFIRMAR` con el destino documental correcto -- sin confirmar nada todavía.
## 2026-08-17 — Cierre de jornada: validación visual manual confirmada

**Validación de Javier, reportada y registrada tal cual:** abrió Atlas Viajes DESARROLLO → Revisión de Atlas y confirmó manualmente, contra las guías físicas:
- **464718:** decisión visible en Revisión de Atlas; obra mostrada correcta (`CONSULTORES EN ARQUITECTURA`); destino mostrado (`RICARDO MORALES 3369 SAN MIGUEL SAN MIGUEL`) coincide con la guía física.
- **464746:** decisión visible en Revisión de Atlas; obra mostrada correcta (`EMPRESA CONSTRUCTORA MENA Y`); destino mostrado (`CAM. EL NOVICIADO LAMPA LAMPA`) coincide con la guía física.

**Ninguna decisión fue aplicada.** Ambas siguen `PENDIENTE` -- no se ejecutó `CONFIRMAR`/`NO_CONFIRMAR`/`POSPONER` sobre ninguna de las dos, ni desde Desktop ni desde script.

**Verificación de continuidad al cierre (read-only):**
- `decisiones_pendientes.json` real: 2 decisiones, ambas `DESTINO_SIN_CONFIRMAR` (464718, 464746), sin cambios desde la reconciliación del bloque anterior (hash `99CEE79B...E166BD96`).
- SHA-256 de `obras_destinos.json`, `destinos_maestros.json`, `clientes.json`, `vehiculos.json`, `analisis_completo_guias.csv`, `decisiones_aplicadas.json`, `estado_operacion.json`: idénticos a los verificados al cierre del bloque anterior -- nada cambió.
- Backups preservados en `respaldos/`: `R3_6_2_ROLLBACK_PRE_APLICACION_20260817_165251/`, `FIX_RUT_ROLLBACK_PRE_APLICACION_20260817_193719/`, `CICLO_OBRA_DESTINO_ROLLBACK_PRE_APLICACION_20260817_210220/` -- ninguno eliminado.
- Motor: `git status --short` idéntico al del bloque anterior (mismo diff sin código nuevo). Desktop: `git status --short` vacío, HEAD `87b9c8c` intacto.

**No se hizo commit ni push** -- pendiente hasta validar el ciclo completo (aplicar realmente ambas decisiones y confirmar que la relación obra↔destino se crea, la revalidación corre y `OBRA_DESTINO_SIN_CORROBORAR` desaparece del dataset real cuando corresponde).

**Continuidad para la siguiente sesión, registrada explícitamente:**
1. Abrir Atlas Viajes DESARROLLO.
2. Aplicar `464718` y `464746` desde Revisión de Atlas (no por script).
3. Verificar que se creen las relaciones obra↔destino en `obras_destinos.json` (vía la misma validación read-only ya usada en bloques anteriores).
4. Verificar que la revalidación documental automática (`revalidacion` en la respuesta de `aplicar_decision_obra`, disparada por R3.4.2 al `CONFIRMAR`) corra sin error.
5. Confirmar que `OBRA_DESTINO_SIN_CORROBORAR` desaparezca de las filas `464718`/`464746` del dataset real cuando corresponda.
6. Regenerar/revisar el reporte de viajes vigente y confirmar el nuevo conteo `CONFIRMADO`/`REQUIERE_REVISION`.
7. Si el ciclo completo queda correcto: commit + push del bloque completo (Paso 2 R3.4.2 + Paso 3 R3.4.3), incluyendo código, tests y bitácoras.

**Estado: JORNADA CERRADA -- LISTO PARA CONTINUAR MAÑANA DESDE VALIDACIÓN FINAL DEL CICLO OBRA→DESTINO.**
## 2026-08-18 — Validación técnica final del ciclo obra→destino tras las dos aplicaciones reales de Javier

**Contexto:** Javier aplicó realmente, desde Atlas Viajes DESARROLLO → Revisión de Atlas, `CONFIRMAR` sobre las dos decisiones `DESTINO_SIN_CONFIRMAR` reconciliadas en el Paso 3 (464718, 464746), cada una una sola vez, con verificación visual previa contra las guías físicas. Este bloque es verificación técnica read-only de ese resultado -- ningún cambio de código.

**1. Ledger (`decisiones_aplicadas.json`), 10 aplicaciones totales, sin duplicados:**
- `07be45c6...` `OBRA_DESCONOCIDA`/`REGISTRAR` 464718 (Paso 2, previo).
- `8230f78d...` `OBRA_DESCONOCIDA`/`REGISTRAR` 464746 (Paso 2, previo).
- `0813d038...` `DESTINO_SIN_CONFIRMAR`/`CONFIRMAR` 464718, actor `JAVIER_DESKTOP`, `2026-08-18T12:47:37Z`, `destino_id=f733b08b-...`, `relacion_id=a5c857e1-...`.
- `93b8059d...` `DESTINO_SIN_CONFIRMAR`/`CONFIRMAR` 464746, actor `JAVIER_DESKTOP`, `2026-08-18T12:51:41Z`, `destino_id=99b148c8-...`, `relacion_id=861e21d9-...`.
- Nótese que `dataset_sha256` de la segunda aplicación (`6378F695...`) difiere del de la primera (`5FE0F384...`) -- confirma que la revalidación automática de la primera aplicación corrió y cambió el dataset ANTES de que la segunda decisión se aplicara, sin `DecisionObsoletaError` -- exactamente la garantía de "decisión consecutiva sin obsolescencia" de R3.4.2/R3.5, ahora verificada con datos reales, no sólo con tests.
- `decisiones_pendientes.json`: 0 decisiones.

**2. Relaciones obra↔destino (`obras_destinos.json`/`destinos_maestros.json`), verificado por ID:**
- 464718: obra `c3304fe6-...` `nombre_canonico="CONSULTORES EN ARQUITECTURA"`, `estado=CONFIRMADA`; relación `a5c857e1-...` `estado=CONFIRMADA`, `fuente_confirmacion=CONFIRMACION_HUMANA`, `confirmado_por=JAVIER_DESKTOP`; destino `f733b08b-...` `direccion="RICARDO MORALES 3369 SAN MIGUEL SAN MIGUEL"`. Unicidad: 1 obra con ese ID, 1 relación para esa obra.
- 464746: obra `c7fcb561-...` `nombre_canonico="EMPRESA CONSTRUCTORA MENA Y"`, `estado=CONFIRMADA`; relación `861e21d9-...` `estado=CONFIRMADA`, misma fuente/actor; destino `99b148c8-...` `direccion="CAM. EL NOVICIADO LAMPA LAMPA"`. Unicidad: 1 obra, 1 relación.
- Ambas relaciones traen evidencia `CONFIRMACION_HUMANA`/`SOPORTA` con `identificador_fuente` igual al `decision_id` de su `CONFIRMAR` -- trazabilidad completa decisión → relación.

**3. Revalidación documental (`analisis_completo_guias.csv` real):**
- 464718: `estado_procesamiento=OK`, `indicador_revision=OK`, `motivos_revision_documento=""` (antes `OBRA_DESTINO_SIN_CORROBORAR`).
- 464746: mismo resultado -- `OK`/`OK`/`""` (antes `OBRA_DESTINO_SIN_CORROBORAR`).
- Dataset completo: 28 filas, **27 OK / 1 REVISAR** (antes de las dos aplicaciones: 25/3). La única fila que sigue `REVISAR` trae `CLIENTE_AUSENTE` (motivo ajeno, no tocado por este flujo) -- no se asumió `OK` donde hay otro motivo legítimo.
- Se generaron automáticamente 2 carpetas `reportes/reporte_revalidacion_2026081[8]_...` (una por cada `CONFIRMAR`, disparo ya implementado en R3.4.2), la segunda quedó publicada como `reporte_vigente` en `estado_operacion.json` (`fecha_actualizacion` `2026-08-18T12:51:45Z`).

**4. Integridad -- dos verificaciones independientes:**
- SHA-256 de `clientes.json`/`vehiculos.json`: idénticos a los capturados antes de las dos aplicaciones -- ningún catálogo ajeno al flujo fue tocado.
- Escaneo de `mtime` de **todo** el árbol `G:\Mi unidad\Atlas` en la ventana de las dos aplicaciones: únicamente aparecen `obras_destinos.json`, `destinos_maestros.json`, `decisiones_aplicadas.json`, `decisiones_pendientes.json`, `analisis_completo_guias.csv`, `estado_operacion.json` y los archivos de las 2 carpetas de reporte nuevas -- nada más en todo Drive (choferes, empresas, plantas, rutas, destinos, telemetría, imágenes, caché, reportes históricos previos: todos intactos).

**5. Viajes -- ya reflejaba la revalidación sin intervención manual, verificado sin asumirlo:** ejecuté `generar_reporte_viajes` como dry-run independiente (salida a TEMP fuera de Drive, eliminado al terminar) contra el dataset y catálogos reales actuales, y comparé columna por columna (excepto `fecha_creacion`, que cambia por ser timestamp de regeneración) contra el `viajes.csv` del reporte ya publicado como vigente -- **coinciden exactamente, cero diferencias**. Resultado: **24 viajes, 22 CONFIRMADO / 2 REQUIERE_REVISION** (antes de este bloque: 20/4). Los 2 que siguen `REQUIERE_REVISION`, ajenos a este bloque:
- `0000352376`: `CONFLICTO_CLIENTE | CONFLICTO_OBRA_DESTINO` (conflicto real ya documentado, pendiente del bloque futuro "consolidación inteligente de viajes").
- `0000353164`: `DOCUMENTO_REQUIERE_REVISION` (motivo documental sin relación con obra/destino, no investigado en este bloque -- fuera de alcance).

No hizo falta regenerar nada realmente -- el reporte vigente ya estaba correcto.

**Tests:** ningún cambio de código en este bloque; se conserva **1184 passed, 0 failed** sin repetir la suite.

**Git:** working tree del Motor sin cambios de código adicionales -- sólo estas tres bitácoras. Desktop limpio, HEAD `87b9c8c` intacto.

**Drive modificado: SÍ, exclusivamente por las dos aplicaciones reales de Javier desde Desktop** (no por ninguna acción de este bloque de verificación, que fue 100% read-only más un dry-run en TEMP fuera de Drive).

**Estado: CICLO OBRA→DESTINO VALIDADO COMPLETAMENTE -- LISTO PARA PUBLICAR.** Queda pendiente, para el bloque siguiente y sólo si se autoriza explícitamente: commit + push del bloque completo (R3.4.2 + R3.4.3 -- código, tests, bitácoras).

*(Nota de continuidad: ese commit + push se ejecutó en el bloque siguiente -- Motor publicado como `831fb2b` sobre `origin/lector-mvp-guia-nueva`, verificado local=remoto 0/0. Ver checkpoint del bloque de abajo.)*
## 2026-08-18 — Bloque 3 (Desktop): Viajes deja de ocultar conflictos reales de nivel viaje

**Checkpoint verificado antes de tocar código:** Motor `lector-mvp-guia-nueva` HEAD `831fb2b` (ya publicado en el bloque anterior), local=remoto, 0/0, working tree limpio. Desktop `fix-desktop-data-root-drag-drop` HEAD base `87b9c8c`, local=remoto, 0/0, working tree limpio.

**Causa reproducida antes de implementar, con evidencia concreta (no sólo lectura de código):** se ejecutó en Node, con `require("./src/formato_operacional")`, la lógica EXACTA de `atlas_viajes.html:1223-1224` (`motivosDocumentales.length ? motivosDocumentales : viaje.motivos`) contra los datos del caso real `0000352376` (`viaje.motivos=["CONFLICTO_CLIENTE","CONFLICTO_OBRA_DESTINO"]`, un documento del mismo transporte con `MATERIAL_AUSENTE`) -- resultado confirmado: `motivosPresentables = ["MATERIAL_AUSENTE"]`, los dos conflictos reales desaparecían por completo. `renderDatosAuxiliares` es la única función que decide qué motivos se presentan en "Datos auxiliares"; no hay otra ruta de renderizado para viajes de detalle.

**Regla de presentación diseñada (Sección 3 del roadmap), derivada del modelo actual, no un parche puntual para `MATERIAL_AUSENTE`:** nueva `AtlasFormatoOperacional.motivosPresentables(motivosViaje, motivosDocumentales)` en `src/formato_operacional.js` -- unión deduplicada (`[...new Set([...viaje, ...documentales])]`), motivos de viaje primero (son la causa canónica de `REQUIERE_REVISION`, calculada por `agrupar_viajes` en el Motor), documentales después como información adicional. Ningún nivel reemplaza al otro; sin duplicados cuando un motivo coincide en ambos niveles (p.ej. `DOCUMENTO_REQUIERE_REVISION` repetido); array vacío cuando ambos lo están (viaje `CONFIRMADO`, sin motivos falsos). `renderDatosAuxiliares` (`atlas_viajes.html`) se actualizó para llamar a esta función en vez del ternario -- el resto de la función (`motivosHumanos`, `filaMotivos`, los chips) no cambió, así que la regresión de UX-R4 (`motivos se muestran debajo como chips y la fila desaparece sin motivos`) sigue pasando sin tocarla.

**Mensajes humanos (Sección 6):** `motivoRevision()` ganó 6 entradas nuevas para los `CONFLICTO_*` de viaje que carecían de traducción explícita y dependían del fallback genérico -- `CONFLICTO_CLIENTE` → "Cliente en conflicto", `CONFLICTO_OBRA_DESTINO` → "Obra o destino en conflicto", `CONFLICTO_CHOFER` → "Chofer en conflicto", `CONFLICTO_RUT_CHOFER` → "RUT de chofer en conflicto", `CONFLICTO_FECHA` → "Fecha en conflicto", `CONFLICTO_ORIGEN` → "Origen en conflicto" -- mismo estilo ya usado (`CONFLICTO_PATENTE_TRACTO` → "Patente de tracto en conflicto"). `FECHA_NO_COMPATIBLE_DESKTOP` (el único de los 12 `MotivoRevision` del Motor sin traducción explícita) se dejó deliberadamente fuera -- no bloqueante, ajeno al bug reportado; sigue con la humanización genérica de respaldo.

**Alcance:** exclusivamente Desktop. Motor sin cambios funcionales -- el bug era 100% de presentación en `atlas_viajes.html`/`formato_operacional.js`; ninguna decisión, catálogo ni dataset participa.

**Tests (`test/viajes_motivos_reales.test.js`, 13 nuevos):** CASO 1 (sólo motivos de viaje) a CASO 8 (`DOCUMENTO_REQUIERE_REVISION` legítimo, caso real `0000353164`), más entradas no-array (defensivo, sin lanzar error), traducciones humanas nuevas, los dos casos reales de punta a punta (`motivosDocumentos` + `motivosPresentables` + `motivoRevision` encadenados, tal como los usa `renderDatosAuxiliares`), y una regresión de wiring que confirma que el HTML usa la función nueva y ya NO contiene el ternario viejo. `npm test` completo: **199 passed, 0 failed** (baseline 186 + 13), incluidos los 13 tests preexistentes de `ux_r4.test.js` sin ninguna regresión.

**Validación real read-only** (sin escribir Drive; volcado temporal en TEMP fuera de Drive, eliminado al terminar): se extrajeron `motivos_revision`/`evidencias_documentos` reales de `viajes.csv` del reporte vigente para `0000352376` y `0000353164`, y se corrió la lógica ANTES/DESPUÉS exactamente como la ejecutaría Desktop:
- `0000352376`: ANTES → `["Material ausente"]`. DESPUÉS → `["Cliente en conflicto", "Obra o destino en conflicto", "Material ausente"]`.
- `0000353164`: ANTES → `["Cliente ausente"]`. DESPUÉS → `["Documento requiere revisión", "Cliente ausente"]`.

**Validación visual real de Javier, confirmada tal cual reportada:** en Atlas Viajes DESARROLLO, `0000352376` muestra "Cliente en conflicto", "Obra o destino en conflicto" y "Material ausente" -- los conflictos reales ya no quedan ocultos. `0000353164` muestra "Documento requiere revisión" y "Cliente ausente". Resultado visual aprobado, coincide exactamente con la predicción de la validación read-only.

**Drive:** no modificado en ningún momento de este bloque (sólo lecturas de verificación).

**Estado: BLOQUE 3 VALIDADO VISUALMENTE -- LISTO PARA PUBLICAR.**

## 2026-08-18 — Bloque post-lote: falsos OK con `OBRA_DESCONOCIDA` (464395/464479) -- diagnóstico y fix

**Checkpoint verificado antes de tocar código:** Motor `lector-mvp-guia-nueva` HEAD `6755d90`, local=remoto, 0/0, working tree limpio. Desktop `fix-desktop-data-root-drag-drop` HEAD `fba95ac`, local=remoto, 0/0, working tree limpio. Drive READ-ONLY durante todo el desarrollo (verificado por SHA-256 de la predicción congelada y por `mtime` de `catalogos_privados/`, idénticos al inicio y al cierre).

**Lote controlado:** `operacion/procesamiento/lote_controlado_15_guias_20260818_100841/` -- `PREDICCION_CONGELADA_analisis_completo_guias.csv` (SHA-256 `a1453aaa...` verificado con `PREDICCION_CONGELADA.sha256`, `OK` al inicio y al cierre) + `decisiones_pendientes.json` (15 decisiones: 6 `VEHICULO_DESCONOCIDO`, 6 `OBRA_DESCONOCIDA` de 5 documentos distintos). No promovido a `operacion/actual`; ninguna decisión aplicada.

**Diagnóstico -- reproducido en fixtures antes de tocar código, no sólo leído:**
- CSV real de `464395.jpeg`: `estado_procesamiento=OK`, `indicador_revision=OK`, `motivos_revision_documento=""`, `obra_destino="ING Y METALURGICA INGEMETA"`, `cliente="ING Y METALURGICA INGEMETA SPA"`. `decisiones_pendientes.json` real trae para esta guía una decisión `OBRA_DESCONOCIDA`/`OBRA_NO_EXISTE_PARA_CLIENTE` (`decision_id=02ef6af0...`).
- CSV real de `464479.jpeg`: mismo patrón `OK`/`OK`/`""`, `obra_destino="AMERICAN SCREW CHILE SPA"` == `cliente="AMERICAN SCREW CHILE SPA"` (idénticos, normalizados). **Cero** decisiones para esta guía en `decisiones_pendientes.json` real.
- Verificado en `catalogos_privados/obras_destinos.json` real (read-only): ni "INGEMETA" ni "AMERICAN SCREW" aparecen como obra confirmada en ningún registro -- ambas obras son genuinamente no corroboradas. `clientes.json` real confirma ambos clientes como `CONFIRMADO`/`ACTIVO` (`428fde9e-...` INGEMETA, `83c256de-...` AMERICAN SCREW).
- Reproducido con script aislado (`_leer_texto`/`_leer_bloques`/`extraer_datos` mockeados con los mismos valores exactos del CSV real, `carpeta_catalogos` apuntando a una copia efímera en TEMP de `catalogos_privados/`, nunca al original): **ambos casos reproducen exactamente el `OK` falso observado**, confirmando que el bug está en `procesar_archivo`, no en el OCR ni en la extracción.
- **Causa raíz localizada en `atlas_core/procesamiento_masivo.py`, bloque "OPERACION REAL R2" (antes de este fix, líneas ~1243-1259):** el bloque calcula `obra_documental_normalizada` y, si `obra_final` (post-catálogo) coincide con esa normalización (o sea, la obra se leyó limpiamente, sin fallback geométrico ni reescritura de catálogo), llama a `_corroborar_obra_destino_confirmada` -- que SÍ es la fuente de verdad real (`CatalogoObrasDestinos.resolver_obra_destino_confirmada`, exige obra `estado=CONFIRMADA` + relación `CONFIRMADA` sin evidencia `CONTRADICE`). Pero el resultado sólo se usaba en el `if obra_destino_corroborada is not None:` -- para retirar la sospecha de `campos_geometricos_sin_corroborar` y agregar el método `CATALOGO_OBRA_DESTINO`. **No existía ningún `else`:** si la obra NO se confirmaba, no pasaba nada. Y como `"obra destino"` sólo entra a `campos_geometricos_sin_corroborar` por otras dos vías -- fallback geométrico (líneas ~837-841, sólo si el campo llegó vacío) o reescritura por catálogo (líneas ~1307-1310, sólo si `enriquecer_datos_con_catalogos` cambió el valor) -- una obra leída limpiamente y NO tocada por el catálogo nunca entraba a ese set por ningún camino, así que el motivo `OBRA_DESTINO_SIN_CORROBORAR` (evaluado más abajo, línea ~1278, `if "obra destino" in campos_geometricos_sin_corroborar`) nunca se generaba.
- **Por qué la ruta de decisiones (`detectar_decisiones_documento`) SÍ acertó en 464395 y no en 464479 -- y por qué eso no importa para `indicador_revision`:** esa función evalúa el catálogo de forma completamente independiente (compara `obra_texto` normalizado contra el catálogo global `obras_destinos.json`, y contra los alias del cliente ya resuelto -- regla R3.2, "si la obra es, normalizada, el mismo nombre del cliente ya reconocido, no hay entidad nueva que preguntar"). `464395` ("ING Y METALURGICA INGEMETA", sin sufijo "SPA") no calza con el alias del cliente → genera `OBRA_DESCONOCIDA` correctamente. `464479` (idéntica al cliente) sí calza → R3.2 correctamente NO genera nada (test ya existente `test_cliente_igual_obra_no_genera_obra_desconocida`, "Regla de Javier"). Pero `requiere_revision`/`indicador_revision` se calculan en la línea ~1332, **ANTES** de que `detectar_decisiones_documento` se invoque siquiera (línea ~1561) -- las dos rutas están desacopladas por diseño. Confirma que el fix correcto NO podía ser "si hay una decisión pendiente, forzar REVISAR" (acoplamiento circular expresamente prohibido) -- la única corrección con causa raíz es hacer que la propia evaluación de corroboración de `obra_destino` use el resultado NEGATIVO de `_corroborar_obra_destino_confirmada`, no sólo el positivo.

**Fix aplicado (`atlas_core/procesamiento_masivo.py`, +22 líneas, un solo bloque `else` nuevo dentro del `if` de "OPERACION REAL R2"):** cuando `obra_destino_corroborada is None`, se resuelve `cliente_id_para_obra` vía `_resolver_cliente_id_corroborado` (la misma función ya existente, misma llamada que hace `_corroborar_obra_destino_confirmada` internamente -- reutilizada, no duplicada en lógica) contra `clientes.json`. Si resuelve (hay una identidad maestra concreta contra la cual la obra debería estar corroborada y no lo está), se agrega `"obra destino"` a `campos_geometricos_sin_corroborar`, dejando que el mecanismo ya existente (línea ~1278/ahora +22) genere `OBRA_DESTINO_SIN_CORROBORAR` sin taxonomía nueva. Si el cliente NO resuelve (no hay base para juzgar la obra -- p. ej. sin `clientes.json`, o cliente no confirmado), se preserva la abstención conservadora ya existente -- mismo criterio de gate que ya usa `detectar_decisiones_documento` antes de evaluar la obra (`identidad_cliente is not None`), evitando así romper `test_estados_s2_2.py::test_6_obra_destino_documental_coincide_con_catalogo_no_agrega_motivo` (corrobora vía `destinos.json`/COD DESTINATARIO, sin `clientes.json` en el escenario de ese test) y `test_1_cliente_por_rut_exacto_catalogo_no_fuerza_revision` (sin `clientes.json` tampoco). No se tocó `_corroborar_obra_destino_confirmada` (firma ni comportamiento) -- sigue devolviendo `ResolucionObraDestino | None` exactamente igual, así que los 20 tests de `tests/test_integracion_obras_destinos_r2.py` que la ejercen directamente (vía el helper `resolver()`) no se vieron afectados. La regla R3.2 en `atlas_core/decisiones_pendientes.py` (generación de decisiones) no fue tocada.

**Regresiones verificadas explícitamente antes de dar el fix por bueno** (con datos read-only de `catalogos_privados/obras_destinos.json` real): `464511`/`464892` (obra "ARMACERO MATCO SA", `obra_id=07f102b8-...`, `estado=CONFIRMADA`, relación `ac221ad5-...` `CONFIRMADA` por `JAVIER_MBT`) y `464781` (obra "CONSTRUCTORA IGNACIO HURTADO LIMITADA", `obra_id=0bfc0770-...`, relación `3200f6e2-...` `CONFIRMADA` por `JAVIER_MBT`) -- las tres reproducidas con los mismos catálogos reales, método `CATALOGO_OBRA_DESTINO` presente, `indicador_revision=OK`, sin `OBRA_DESTINO_SIN_CORROBORAR`, sin cambio antes/después del fix.

**Efecto colateral esperado y deliberado, documentado explícitamente (no es scope creep):** el mismo fix también hace que el patrón "obra existente pero relación aún `PENDIENTE`" (R3.4, `DESTINO_SIN_CONFIRMAR`) deje de quedar `OK` silencioso -- antes de este bloque, ese combo tampoco tenía ningún test end-to-end (`procesar_archivo`) que asegurara `OK`, sólo a nivel de `detectar_decisiones_documento` en aislado (`test_obra_existente_sin_relacion_confirmada_y_caso_confirmado`, no afectado). Es la misma causa raíz aplicada consistentemente -- si sigue pendiente una decisión humana de confirmar la relación, el documento tampoco puede quedar `OK`. Cubierto por el nuevo test `test_destino_pendiente_mantiene_destino_sin_confirmar_y_pide_revision`.

**Tests nuevos:** `tests/test_falso_ok_obra_destino_p1.py`, 7 tests -- equivalente 464395 (extracción intacta, `REVISAR`, `OBRA_DESTINO_SIN_CORROBORAR`, decisión `OBRA_DESCONOCIDA`/`OBRA_NO_EXISTE_PARA_CLIENTE` coherente), equivalente 464479 (extracción intacta, `REVISAR`, `OBRA_DESTINO_SIN_CORROBORAR`, sin decisión -- R3.2 preservado), obra conocida confirmada (`OK`, sin motivo, sin decisión, método `CATALOGO_OBRA_DESTINO`), obra nueva genérica (motivo + decisión coherentes), destino pendiente (`DESTINO_SIN_CONFIRMAR` preservado + ahora también `REVISAR`), cliente no resoluble (abstención, sin motivo inventado), idempotencia + no duplicados (`motivos.count(...) == 1`, mismos `decision_id` en dos corridas, catálogos byte-idénticos antes/después) + motivo independiente no bloqueante (`MATERIAL_AUSENTE`) coexistiendo sin interferencia.

**Ejecución de tests, en tres niveles como pide el bloque:**
1. Focalizados: `pytest tests/test_falso_ok_obra_destino_p1.py -v` -- **7 passed**.
2. Grupo obra/destino/decisiones: `tests/test_estados_s2_2.py tests/test_integracion_obras_destinos_r2.py tests/test_estados_s2.py tests/test_inteligencia_n1.py` (**67 passed**) + `tests/test_decisiones_pendientes.py tests/test_ciclo_obra_destino_r342.py tests/test_reconciliacion_historica_destino_r343.py tests/test_destinos_confirmacion_r34.py tests/test_aplicacion_decisiones_r33.py tests/test_aplicacion_vehiculos_r361.py tests/test_revalidacion_patente_r362.py tests/test_catalogo_obras_destinos.py tests/test_destinos_d3_confirmacion.py tests/test_destinos_globales_r341.py` (**175 passed**) -- **0 failed** en ambos grupos.
3. Suite completa: **1191 passed, 0 failed** (baseline exacto **1184** confirmado primero sin el fix ni los tests nuevos -- código no cambió durante el lote -- luego **1191** = 1184 + 7 nuevos, sin ninguna regresión).

**Reevaluación read-only del lote congelado, SIN reprocesar OCR ni imágenes** (se reaplicó únicamente la lógica corregida sobre los mismos valores de extracción ya congelados, contra copias efímeras en TEMP de los catálogos reales, catálogos y predicción nunca escritos):
- `464395`: ANTES (congelado) → `OK` / `""` / decisión `OBRA_DESCONOCIDA` presente pero sin efecto sobre el indicador. DESPUÉS (lógica corregida) → `REVISAR` / `OBRA_DESTINO_SIN_CORROBORAR` / misma decisión `OBRA_DESCONOCIDA`/`OBRA_NO_EXISTE_PARA_CLIENTE`, ahora coherente con el estado del documento. `cliente`, `obra_destino` y el resto de campos de extracción: **sin cambio**.
- `464479`: ANTES → `OK` / `""` / sin decisión. DESPUÉS → `REVISAR` / `OBRA_DESTINO_SIN_CORROBORAR` / sin decisión (R3.2 preservado -- causa distinta a `OBRA_DESCONOCIDA`, documentada arriba). Extracción: **sin cambio**.
- Controles `464511`/`464892`/`464781`: **sin cambio** en ningún campo, `OK` antes y después.

**Integridad verificada:** `PREDICCION_CONGELADA.sha256` -- `OK` al inicio y al cierre de la sesión. `mtime` de `catalogos_privados/*.json` y de `operacion/actual/*` idénticos a los observados al inicio -- ningún archivo real fue escrito en ningún momento de este bloque.

**Git:** `git status` -- `atlas_core/procesamiento_masivo.py` modificado, `tests/test_falso_ok_obra_destino_p1.py` nuevo (untracked), más estas tres bitácoras. `git diff --check` -- limpio (exit 0, sin errores de whitespace). Desktop: `git status` limpio, HEAD `fba95ac` sin cambios. **Sin commit, sin push.**

**Fuera de alcance de este bloque, explícitamente no tocado:** OCR, errores `464265`/`464367`, catálogo YOLITO/TOLITO, consolidación, Desktop, Multiempresa, Mobile. Las 15 decisiones del lote no fueron aplicadas; `operacion/actual` y los catálogos reales no fueron escritos.

**Estado: LISTO PARA VALIDACIÓN REAL SOBRE LOTE CONGELADO.**

## 2026-08-18 — Validación real del fix sobre el lote congelado (464395/464479 con OCR real)

**Checkpoint verificado antes de tocar nada:** Motor HEAD `6755d90`, working tree con exactamente el diff esperado (`atlas_core/procesamiento_masivo.py` modificado +22 líneas, `tests/test_falso_ok_obra_destino_p1.py` untracked, tres bitácoras modificadas) -- `git status`/`git diff --stat` coinciden con lo dejado en el bloque anterior. `git diff --check` limpio (exit 0; sólo avisos LF→CRLF de `autocrlf`, no errores). Desktop `git status` limpio, HEAD `fba95ac`. `PREDICCION_CONGELADA.sha256` -- `OK`.

**Imágenes canónicas localizadas y verificadas:** `operacion/entradas/lote_controlado_15_guias_20260818_100841/` (carpeta de entrada real del lote, con `MANIFIESTO_SHA256.csv` propio). SHA-256 de `464395.jpeg` (`9f5dea20...`) y `464479.jpeg` (`9e4d481f...`) en disco coinciden exactamente con `sha256_origen`/`sha256_copia`/`hash_verificado=OK` del manifiesto -- confirmadas como las imágenes reales incorporadas al lote, no una versión distinta.

**Ejecución real en TEMP:** copia de ambas imágenes (verificada SHA-256 idéntica tras la copia) + copia de `catalogos_privados/*.json` a una carpeta fuera de Drive. Comando ejecutado: `python analizar_guias_masivo.py <TEMP>\imagenes --salida <TEMP>\salida\resultado_con_fix.csv --catalogos <TEMP>\catalogos --sin-telemetria` -- el mismo CLI de producción (`analizar_guias_masivo.py`, usado también para el fix de RUT del 2026-08-17), sin ningún mock. `--sin-telemetria` explícito: los campos bajo validación (extracción documental + corroboración de `obra_destino`) no dependen de telemetría/GPS, y evita necesitar credencial real de Onelogis para esta validación puntual -- no afecta ningún campo de la comparación pedida. Proveedor activo confirmado por log: `PaddleOCR (device=gpu)`. 2/2 procesados, 0 errores, ~19s/archivo.

**Comparación campo a campo (script Python, no inspección visual), predicción congelada real vs. salida de esta corrida:**
```
464395.jpeg -- numero_guia, numero_transporte, fecha, chofer, rut_chofer, cliente,
               obra_destino, patente_tracto, patente_rampla, descripcion_material,
               tipo_carga: TODOS IDÉNTICOS (11/11)
               estado_procesamiento: OK -> OK (sin cambio)
               indicador_revision:   OK -> REVISAR
               motivos_revision_documento: "" -> "OBRA_DESTINO_SIN_CORROBORAR"

464479.jpeg -- mismos 11 campos: TODOS IDÉNTICOS
               estado_procesamiento: OK -> OK (sin cambio)
               indicador_revision:   OK -> REVISAR
               motivos_revision_documento: "" -> "OBRA_DESTINO_SIN_CORROBORAR"
```

**Decisiones de esta corrida (`decisiones_pendientes.json` generado en TEMP):** 1 sola decisión total -- `464395.jpeg` / `OBRA_DESCONOCIDA` / campo `obra_destino` / motivo `OBRA_NO_EXISTE_PARA_CLIENTE` / valor documental `"ING Y METALURGICA INGEMETA"` -- mismo tipo, mismo motivo y mismo valor documental que la decisión ya presente en el `decisiones_pendientes.json` real del lote (`decision_id=02ef6af0...`). `464479.jpeg`: **cero** decisiones, igual que en el lote real -- R3.2 se comporta idéntico con OCR real que con los datos mockeados de la validación anterior.

**Validación contra la guía física (imagen real, no sólo el CSV):**
- `464395`: campo impreso "OBRA DESTINO : ING Y METALURGICA INGEMETA" -- coincide EXACTO con `obra_destino` extraído. "SEÑOR(ES) : ING Y METALURGICA INGEMETA SPA" coincide con `cliente`. Confirmado en `catalogos_privados/obras_destinos.json` real (bloque anterior): "INGEMETA" no existe como obra registrada -- `REVISAR` es correcto, no un falso positivo.
- `464479`: campo impreso "OBRA DESTINO : AMERICAN SCREW CHILE SPA" -- idéntico a "SEÑOR(ES) : AMERICAN SCREW CHILE SPA" en el propio documento (confirma que la coincidencia obra=cliente no es un artefacto de OCR, está impresa así en la guía real). "AMERICAN SCREW" tampoco existe como obra registrada en el catálogo real -- `REVISAR` también correcto.

**Controles, read-only, sin OCR** (mismo script de la sesión anterior, reejecutado contra el código actual con el fix, catálogos reales copiados sólo lectura): `464511_control_obra_confirmada` (cliente/obra "ARMACERO MATCO SA", RUT `78.170.790-2`) y `464781_control_obra_confirmada` (cliente "AGF ACEROS DE CHILE SPA" / obra "CONSTRUCTORA IGNACIO HURTADO", RUT `77.410.131-4`) -- ambos `indicador_revision=OK`, sin `OBRA_DESTINO_SIN_CORROBORAR`, método `CATALOGO_OBRA_DESTINO` presente -- sin cambio respecto al bloque anterior. `464892` no se reejecutó por separado: comparte cliente, obra ("ARMACERO MATCO SA") y estado de catálogo EXACTOS con `464511` (`resolver_obra_destino_confirmada_global` resuelve por obra global, no por guía) -- mismo resultado garantizado por construcción, sin necesidad de una corrida adicional.

**Métricas del lote (15 guías), recalculadas conceptualmente combinando la predicción congelada real (13 filas sin cambio) con el resultado validado de 464395/464479 -- sin escribir la predicción congelada:**

| | ANTES (predicción congelada) | DESPUÉS (con fix, validado) |
|---|---|---|
| `OK` correctos | 3 (`464511`, `464781`, `464892`) | 3 (sin cambio) |
| Falsos `OK` | **2** (`464395`, `464479`) | **0** |
| `REVISAR` justificados | 10 (`464036`,`464170`,`464264`,`464265`,`464367`,`464488`,`464491`,`464493`,`464494`,`464854`) | 12 (los 10 previos, sin cambio -- el fix nunca resta ni añade motivos por otra vía a filas que ya tenían `OBRA_DESTINO_SIN_CORROBORAR`/`CLIENTE_SIN_CORROBORAR`/etc., el `set.add()` es idempotente -- + `464395` + `464479`) |
| Falsos `REVISAR` | 0 | 0 (verificado contra guía física: ambas transiciones a `REVISAR` corresponden a obras genuinamente no corroboradas) |
| Total | 15 | 15 |

**Por qué no hizo falta reprocesar las otras 13 guías del lote:** el fix sólo agrega comportamiento nuevo dentro del `else` cuando `obra_destino_corroborada is None` Y el cliente resuelve -- nunca quita un motivo ni cambia `metodos_recuperacion_documento` fuera de ese `else`. De las 15 filas, sólo 5 tenían `indicador_revision=OK` en la predicción congelada (único estado donde una regresión sería observable); las 3 restantes (`464511`/`464781`/`464892`) ya fueron verificadas explícitamente arriba como sin cambio. Las 10 filas que ya eran `REVISAR` no pueden convertirse en un "falso REVISAR nuevo" causado por este fix, porque el fix nunca las toca (ya tenían motivo bloqueante por otra vía, y `campos_geometricos_sin_corroborar.add("obra destino")` sobre un motivo que de todos modos ya iba a dispararse por otra vía es un no-op observable).

**Hueco funcional identificado en 464479 (documentado, NO resuelto, NO diseñado en este bloque):** `464479` queda `REVISAR`/`OBRA_DESTINO_SIN_CORROBORAR` pero no genera ninguna decisión pendiente (R3.2 correctamente determina que no hay entidad nueva que registrar). Verificado leyendo (sin modificar) `Atlas-Viajes-Desktop-Restaurado/src/decisiones_pendientes_ui.js`: la función de carga (línea ~59-60) sólo produce tarjetas a partir de `datos.decisiones` (el arreglo de `decisiones_pendientes.json`); `renderizar()` (línea ~242-246) hace `contenedor.hidden = !decisiones.length; if (!decisiones.length) return 0;` -- con cero decisiones para esta guía, el panel "Revisión de Atlas" no muestra ninguna tarjeta relacionada. El documento queda visible como `REVISAR` en el dataset/reporte de viajes, pero sin ninguna vía de decisión humana en el flujo de Revisión de Atlas para cerrarlo -- mismo patrón estructural que ya se resolvió para el ciclo obra→destino en R3.4.2/R3.4.3 (`OBRA_DESCONOCIDA→REGISTRAR` sin `destino_id`), ahora presente para el caso "obra == cliente ya reconocido, R3.2". **Sin diseño de solución en este bloque** -- queda identificado para decisión de Javier sobre si amerita un bloque futuro.

**Integridad verificada al cierre:** `PREDICCION_CONGELADA.sha256` -- `OK`. `mtime` de `operacion/procesamiento/lote_controlado_15_guias_20260818_100841/`, `operacion/actual/`, `catalogos_privados/*.json` y `operacion/entradas/lote_controlado_15_guias_20260818_100841/` -- todos idénticos a los observados en el checkpoint de este mismo bloque, antes de cualquier lectura. Carpeta TEMP de esta validación eliminada al terminar (`rm -rf`) -- no queda ninguna carpeta nueva permanente.

**Tests:** ningún cambio de código en este bloque -- se conserva **1191 passed, 0 failed** sin repetir la suite (cumple la instrucción de no repetirla si el código no cambió).

**Git:** sin cambios adicionales respecto al bloque anterior -- mismo diff (`atlas_core/procesamiento_masivo.py`, `tests/test_falso_ok_obra_destino_p1.py`) más estas tres bitácoras. `git diff --check` limpio. **Sin commit, sin push.** Desktop intacto, HEAD `fba95ac`.

**Fuera de alcance, no tocado:** desarrollo nuevo, Mobile, Multiempresa, corrección de `464265`/`464367`, aplicación de decisiones, modificación de catálogos, promoción del lote a `operacion/actual`.

**Estado: FIX FALSOS OK VALIDADO REALMENTE -- LISTO PARA PUBLICAR.**

## 2026-08-18 — Publicación (`793b240`) + promoción del lote de 15 a `operacion/actual`

**Push real:** `git push origin lector-mvp-guia-nueva` -- `6755d90..793b240`. Verificado post-push: local `793b240` == remoto `793b240`, ahead/behind 0/0, working tree limpio.

**Promoción, mecanismo canónico, sin escritura manual de CSV/JSON:**
1. Dry-run en TEMP: copia de `operacion/actual/analisis_completo_guias.csv` (28 filas) + `decisiones_aplicadas.json` (ledger, 10 aplicaciones) + copia completa de `catalogos_privados/` + las 15 imágenes canónicas (SHA-256 verificado contra `MANIFIESTO_SHA256.csv` de `operacion/entradas/lote_controlado_15_guias_20260818_100841/`).
2. `analizar_guias_masivo.py` (mismo CLI de producción, con telemetría real -- credenciales `ATLAS_ONELOGIS_API_KEY`/`OPENROUTESERVICE_API_KEY` ya presentes en el entorno) contra la copia TEMP: **43 filas resultantes, 0 duplicados por `archivo` ni `numero_guia`**, las 28 filas previas **byte a byte idénticas** a las originales (comparación programática, no visual). Único cambio en las 15 nuevas frente a la predicción congelada: `464395`/`464479` ahora `REVISAR`/`OBRA_DESTINO_SIN_CORROBORAR` (ya validado en el bloque anterior) -- las 13 filas restantes, incluida `464367`, idénticas a la congelada (ese error de patente **no** se tocó en este bloque, tal como se pidió).
3. `generar_reporte_viajes` en dry-run contra el CSV combinado: **38 viajes** (24 antiguos sin cambio, verificado que ninguno se mezcla con los 14 nuevos por `numero_transporte` -- cálculo real, no supuesto) -- **25 CONFIRMADO / 13 REQUIERE_REVISION**. `464264`+`464265` (mismo transporte `0000351135`) quedan en el mismo viaje con `CONFLICTO_FECHA | CONFLICTO_OBRA_DESTINO | CONFLICTO_PATENTE_TRACTO | CONFLICTO_PATENTE_RAMPLA` visibles, sin resolver.
4. Backup previo: `respaldos/PROMOCION_LOTE15_ROLLBACK_PRE_APLICACION_20260818_153220/` -- `analisis_completo_guias.csv`, `decisiones_pendientes.json`, `estado_operacion.json` (únicos tres archivos que la promoción iba a modificar), SHA-256 verificado byte a byte antes de escribir.
5. Aplicación real: se copiaron los artefactos ya validados en TEMP a `operacion/actual/` (mismo contenido, verificado `cmp` byte a byte contra el TEMP validado); `generar_reporte_viajes.py` real generó `reportes/reporte_promocion_lote15_20260818_153512/` y publicó `estado_operacion.json` vía `escribir_estado_operacion` (mecanismo canónico, no escritura manual).

**Resultado final verificado en los archivos reales:** 43 documentos (30 OK / 13 REVISAR), 15 decisiones pendientes (8 `VEHICULO_DESCONOCIDO` + 7 `OBRA_DESCONOCIDA`, ninguna aplicada, ninguna colisiona con el ledger de terminales), 38 viajes (25/13). `decisiones_aplicadas.json` sin cambio de `mtime` (no se aplicó nada). Catálogos, predicción congelada, procesamiento original e imágenes de entrada -- `mtime` idéntico al observado antes de escribir.

**Tests:** sin cambios de código en este bloque -- se conserva 1191 passed, 0 failed.

**Git:** Motor publicado y limpio (`793b240`, local=remoto, 0/0). Desktop sin cambios, HEAD `fba95ac`.

**Estado: LOTE DE 15 PROMOVIDO -- LISTO PARA VALIDACIÓN VISUAL DE JAVIER.**

## 2026-08-18 — Auditoría de patentes de las 15 guías + diagnóstico dirigido de 464367

**Auditoría completa, ground truth desde la imagen (nunca desde CSV/catálogo/decisión):** 25 patentes documentales evaluables (15 tracto + 10 rampla) -- **23 coinciden exactamente con lo extraído por Atlas (92%)**. Cruce read-only contra `vehiculos.json` real usado sólo como evidencia de apoyo (nunca como ground truth): 11 de las 15 patentes de tracto ya eran conocidas antes del lote, lo que sirvió para corroborar independientemente varias lecturas visuales (p. ej. `BKYK63`, `BPHR67`, `TZWR86` confirmados como vehículos reales ya existentes).

**Evidencia operacional humana, registrada, sin aplicar a ningún catálogo/decisión:**
- **Patrick Ortiz / guía 464036:** documental `XF3662` (Atlas leyó correctamente), canónica confirmada por el propio Ortiz `XF3629`. Clasificación: `ERROR_DOCUMENTAL_AZA_CONFIRMADO` -- no imputable a Atlas.
- **Carlos Simón / guías 464264 (`VP8521`/`JD6659`) y 464265 (`VP6521`/`JD0659`), mismo transporte `0000351135`:** Javier confirmó tracto canónico `VP8521` (coincide con 464264, ya conocido en catálogo); `VP6521` no se registra. Rampla **sin confirmar** -- candidatos recordados por Javier (`JE8659`/`JE8650`) no coinciden literalmente con lo auditado documentalmente (`JD6659`/`JD0659`); no se elige ninguna.

**Diagnóstico dirigido de 464367 (único error real de extracción, OCR ejecutado sólo sobre esta guía, aislado en TEMP, con el proveedor real PaddleOCR):**
- Texto OCR bruto capturado en un único bloque geométrico: `': T2MN86 CARBO:J35478'` (confianza 0.870), geométricamente bien asociado a la etiqueta `PATENTE` (bloque separado, confianza 1.000).
- `_valor_unico_residual` (dentro de `_extraer_patentes_geometrico`) intenta remover el par fusionado `CARRO:valor` de ese bloque mediante una regex que exige literalmente la palabra `CARRO` (tolerancia previa sólo 0↔O) -- como el OCR corrompió `CARRO`→`CARBO` (B por R), la regex no encuentra nada que remover y quedan DOS tokens de 6 caracteres con formato válido de patente (`T2MN86` y `J35478`) en el mismo bloque -- la función se abstiene por diseño (nunca elige por posición) y ambos campos quedan `No encontrado`.
- **Control real perfecto: guía 464511** -- estructura de bloque IDÉNTICA (`':SD6486 CARRO:JF4288'`, PATENTE como etiqueta separada) pero con `CARRO` correctamente leído -- la misma función SÍ separa el par y resuelve `{'tracto': 'SD6486', 'carro': 'JF4288'}`. Esta comparación aísla la causa con precisión: única variable que cambia es si el OCR corrompió o no la palabra CARRO.
- Causa raíz: **C. CANDIDATO_DETECTADO_PERO_FILTRO_RECHAZA.**

**Concepto de producto identificado, registrado para roadmap, NO diseñado ni implementado:** módulo genérico de **INCIDENCIAS DOCUMENTALES** (origen/emisor, documento, campo, valor documental, valor canónico, tipo de incidencia, evidencia, quién confirmó, fecha) -- deliberadamente genérico, no "errores AZA". Debe poder distinguir patente documental / patente canónica / incidencia documental confirmada humanamente sin atribuir automáticamente un error a un tercero.

**Drive/catálogos/Desktop:** sin cambios -- diagnóstico 100% read-only, TEMP eliminado al terminar.

**Estado: DIAGNÓSTICO COMPLETADO -- REQUIERE DECISIÓN.**

## 2026-08-18 — Fix conservador: tolerancia de OCR para etiquetas vehiculares (`CARRO` leído `CARBO`)

**Fase 1 -- análisis de seguridad antes de modificar (inventario completo):** toda la lógica de reconocimiento de etiquetas vehiculares vive exclusivamente en `atlas_core/extractor.py`, en un clúster de funciones ya identificado: `_ETIQUETAS_PATENTE_TRACTO`/`_ETIQUETAS_PATENTE_CARRO`/`_ETIQUETAS_PATENTE_TODAS` (vocabulario), `_tolerante_o_cero` (única tolerancia existente, sólo dígito 0 → letra O), `_es_etiqueta_patente` (bloque completo == etiqueta, tolerante), `_valor_tras_etiqueta_en_bloque` (par ETIQUETA:VALOR fusionado en un solo bloque), `_valor_unico_residual` (remueve pares ya conocidos de un bloque de valor y exige que quede exactamente un candidato), `_extraer_patentes_geometrico` (orquestador). Tolerancia hoy existente: sólo 0↔O, justificada por un caso real ya resuelto (guía 464631, "CARR0"). Búsqueda en tests (`tests/test_patentes_p4.py`) y en el lote real confirmó un segundo caso real (464367, "CARBO") con la MISMA estructura de bloque que un control ya correcto (464511) -- evidencia suficiente para una tabla de confusiones (no una heurística de un solo caso).

**Solución elegida:** generalizar `_tolerante_o_cero` (renombrada `_tolerante_confusion_ocr_etiqueta`) de un reemplazo fijo a una **tabla explícita y acotada**, `_CONFUSIONES_OCR_ETIQUETA_VEHICULAR = {"0": "O", "B": "R"}`, documentada con la guía real que motivó cada par. Se usa exactamente en los mismos 3 puntos donde ya se usaba la tolerancia anterior (`_es_etiqueta_patente`, `_valor_tras_etiqueta_en_bloque`, `_valor_unico_residual`) -- ningún nuevo punto de entrada, ninguna distancia de edición genérica.

**Por qué es conservadora (verificado, no sólo argumentado):**
- Ninguna de las 5 etiquetas (`PATENTE`,`TRACTO`,`CARRO`,`RAMPLA`,`REMOLQUE`) contiene "0" ni "B" -- por construcción, cada sustitución sólo puede HABILITAR una coincidencia nueva, nunca deshacer una coincidencia exacta ya correcta.
- `_valor_unico_residual` calcula las posiciones a remover sobre el texto TOLERANTE, pero recorta y devuelve el texto ORIGINAL en esas mismas posiciones (sustitución 1 carácter → 1 carácter, nunca cambia longitudes/offsets) -- un valor documental que legítimamente contenga "B" (p. ej. `BPHR67`) nunca se corrompe a "R". Verificado explícitamente (test negativo).
- `"CARGO"` (palabra real, visualmente parecida a CARRO, pero fuera de la tabla) sigue sin reconocerse -- verificado explícitamente (test negativo): sigue en ambigüedad/abstención.
- Ambigüedad geométrica genuina preexistente (dos etiquetas PATENTE igual de cerca) no se ve afectada -- test de regresión explícito.

**Archivos modificados:** `atlas_core/extractor.py` (+52/-14 líneas: renombrado + tabla + 3 llamadas actualizadas + docstrings), `tests/test_patentes_p4.py` (+114 líneas, 6 tests nuevos).

**Tests nuevos (`tests/test_patentes_p4.py`):**
- `test_patente_unica_geometrica_tolera_carbo` -- reproduce la estructura real de 464367 con datos sintéticos, unitaria sobre `_extraer_patentes_geometrico`.
- `test_regresion_464367_patente_y_rampla_fusionados_con_carro_mal_leido` -- misma estructura, end-to-end vía `procesar_archivo`, verifica además `PATENTE_SIN_HOMOLOGAR` sin catálogo.
- `test_palabra_parecida_a_carro_no_tolerada_fuera_de_la_tabla_se_abstiene` -- negativo: `CARGO` no tolerado.
- `test_dos_patentes_sin_ninguna_etiqueta_rival_reconocible_se_abstiene` -- negativo: sin ningún resto de etiqueta, ambigüedad genuina.
- `test_ambiguedad_geometrica_genuina_sigue_abstenida_tras_el_fix` -- no regresión del test 7 preexistente (dos etiquetas PATENTE igual de cerca).
- `test_valor_documental_con_b_legitima_no_se_corrompe_con_carro_bien_leido` -- negativo: `BPHR67` + `CARRO` bien escrito no se corrompe.

**Ejecución de tests:** focalizados `tests/test_patentes_p4.py` -- **17 passed** (11 preexistentes + 6 nuevos). Grupo extracción/patentes/vehículos (`test_extraer_datos.py`, `test_patentes_p4.py`, `test_catalogo_vehiculos_v1.py`, `test_aplicacion_vehiculos_r361.py`, `test_revalidacion_patente_r362.py`, `test_estados_s2.py`, `test_estados_s2_2.py`, `test_inteligencia_n1.py`) -- **282 passed**. Suite completa: **1197 passed, 0 failed** (baseline 1191 + 6).

**Validación real en TEMP (imagen canónica de 464367, SHA-256 verificado, catálogos copiados sólo lectura, `--sin-telemetria` porque no afecta los campos bajo prueba):**
```
OCR bruto:              ': T2MN86 CARBO:J35478'                (sin cambio -- el fix no toca OCR)
extracción geométrica:  {} -> {'tracto': 'T2MN86', 'carro': 'J35478'}
patente documental:     "No encontrado"/"No encontrado" -> "T2MN86"/"J35478"
homologación/catálogo:  ninguna (no existen en vehiculos.json real) -> decisión VEHICULO_DESCONOCIDO
                        + motivo PATENTE_SIN_HOMOLOGAR para ambos campos (mismo patrón que las
                        otras 8 decisiones ya auditadas del lote)
```
Comparación campo a campo contra el resultado ya promovido en `operacion/actual` para esta misma guía: **todos los demás campos idénticos** (`numero_guia`, `numero_transporte`, `fecha`, `chofer`, `rut_chofer`, `cliente`, `obra_destino`, `descripcion_material`, `tipo_carga`) -- único cambio: `patente_tracto`/`patente_rampla` (de `"No encontrado"` a valor real) y `motivos_revision_documento` (gana `PATENTE_SIN_HOMOLOGAR`, aditivo). `indicador_revision` se mantiene `REVISAR` (ya lo estaba por `OBRA_DESTINO_SIN_CORROBORAR`/`CLIENTE_AUSENTE`).

**Límite explícito, fuera de alcance de este bloque:** el fix corrige la etapa de EXTRACCIÓN (candidato ya no se descarta) -- no corrige el ruido de OCR dentro del propio VALOR. `T2MN86`/`J35478` (documental recuperado) siguen siendo distintos de la lectura visual del documento físico (`TZWR86`/`JU5478` según la auditoría anterior). Corregir eso es un problema de calidad de OCR carácter a carácter, deliberadamente NO abordado aquí -- el valor deliberadamente NO se corrigió para "hacerlo calzar" con el catálogo o con la lectura visual, tal como exigía el bloque.

**Drive:** no modificado -- validación 100% en TEMP, eliminado al terminar. `operacion/actual`, catálogos, predicción congelada, decisiones -- sin tocar.

**Desktop:** sin cambios.

**Git:** working tree del Motor con `atlas_core/extractor.py` y `tests/test_patentes_p4.py` modificados, más estas tres bitácoras. `git diff --check` limpio. **Sin commit, sin push.**

**Estado: FIX VALIDADO -- LISTO PARA REVISIÓN CON JAVIER.**

## 2026-08-18 — 464367: trazado completo del ruido de OCR a nivel de carácter -- sin corrección automática segura disponible

**Checkpoint:** Motor HEAD `793b240`, working tree con exactamente el mismo diff dejado por el bloque anterior (`atlas_core/extractor.py`, `tests/test_patentes_p4.py`, tres bitácoras). Desktop `fba95ac`, limpio.

**Trazado exacto, sin modificar código:**
1. **Imagen** → **OCR bruto** (PaddleOCR, ya ejecutado en el bloque de diagnóstico anterior, no repetido aquí): bloque fusionado `': T2MN86 CARBO:J35478'`, confianza 0.870.
2. **Extracción geométrica** (`_extraer_patentes_geometrico`, ya con el fix de este mismo bloque de trabajo): `{'tracto': 'T2MN86', 'carro': 'J35478'}` -- el candidato ya no se pierde.
3. **Candidato** → **normalización** (`_normalizar_patente`): sin cambio para ambos valores -- ninguno contiene la letra "O" (única sustitución que hace esa función sobre el valor, O→0), y no calzan con la corrección histórica hardcodeada de "guía 3" (`2DRG50`→`BDFG50`, ajena a este caso).
4. **Homologación contra catálogo** (`resolver_patente_canonica`, fachada de `resolver_patente` en `atlas_core/catalogo_vehiculos.py`, ejecutada real y directamente contra `catalogos_privados/vehiculos.json`, sólo lectura):
   - `resolver_patente(..., 'T2MN86', tipo_esperado='TRACTO')` → **`SIN_CANDIDATO`**.
   - `resolver_patente(..., 'J35478', tipo_esperado='CARRO')` → **`SIN_CANDIDATO`**.
5. **Corroboración:** ninguna -- sin homologación, no hay corroboración posterior que evaluar.
6. **Valor final:** se conserva el valor documental tal cual (`T2MN86`/`J35478`) -- nunca "No encontrado" (eso ya lo corrigió el bloque anterior) ni tampoco un valor inventado.
7. **Motivo de revisión:** `PATENTE_SIN_HOMOLOGAR` (ya confirmado en la validación TEMP del bloque anterior).
8. **Decisión generada:** `VEHICULO_DESCONOCIDO` para ambos campos (`patente_tracto`, `patente_carro`), acciones `REGISTRAR`/`NO_REGISTRAR`/`POSPONER` -- exactamente el mismo patrón que las demás 8 decisiones de vehículo ya auditadas del lote.

**Respuestas a las 8 preguntas del bloque, verificadas con código real (no supuestas):**
1. ¿`TZWR86` existe como vehículo canónico confirmado? **Sí** (`catalogos_privados/vehiculos.json` real, verificado por lectura directa).
2. ¿Por qué `T2MN86` no homologa a `TZWR86`? Difieren en **3 posiciones** (`('2','Z')`, `('M','W')`, `('N','R')`, verificado con `_diferencia_ocr_segura('T2MN86','TZWR86')` → `False`) -- la única regla de corrección segura que existe hoy exige exactamente 1 posición distinta.
3. ¿`JU5478` existe en catálogo? **No** (verificado por lectura directa del catálogo real).
4. ¿`J35478` tiene homologación inequívoca posible? **No** -- `_diferencia_ocr_segura('J35478','JU5478')` → `False`: aunque sólo difieren en 1 posición (`('3','U')`), ese par no está en `_CONFUSIONES_OCR` (`{B,D}`,`{0,O}`,`{1,I}`,`{5,S}`,`{8,B}`,`{8,E}`,`{K,R}`), y de todos modos no hay ningún candidato de catálogo contra el cual aplicar la regla.
5. ¿Qué reglas de corrección/homologación existen hoy? `_diferencia_ocr_segura` (`atlas_core/catalogo_vehiculos.py:294`) -- longitud igual, exactamente 1 posición distinta, y ese par debe pertenecer a la tabla `_CONFUSIONES_OCR` ya vetada. Aplicada únicamente cuando ya existe un candidato exacto de tipo correcto en catálogo (`resolver_patente`, línea 299).
6. ¿Por qué `SD6486→SB6486` sí funciona y esto no? Ese caso cumple los TRES requisitos a la vez: 1 sola posición distinta (`('D','B')` en la posición 2), el par `{B,D}` sí está en la tabla vetada, y `SB6486` ya existe como vehículo `CONFIRMADO`/`ACTIVO` en el catálogo real. `464367` no cumple ninguno de los tres para tracto (3 posiciones) y sólo el primero para rampla (posición única, pero par no vetado y sin candidato de catálogo).
7. ¿La diferencia `T2MN86→TZWR86` excede el umbral seguro? **Sí, ampliamente** -- 3 posiciones contra el máximo de 1 que la regla actual permite.
8. ¿Existe evidencia adicional no basada en adivinar? La única fuente adicional posible sería una asociación histórica chofer↔vehículo (si "CARLOS ÑANCUCHEO" tuviera ya un vehículo confirmado antes) -- explícitamente prohibida como mecanismo de autocorrección en este bloque, y en todo caso Atlas hoy **no mantiene ese tipo de asociación en absoluto** (confirmado en bloques anteriores).

**Clasificación (Fase 2):** tracto `T2MN86` → **C. NO_RECUPERABLE_CON_SEGURIDAD**. Rampla `J35478` → **C. NO_RECUPERABLE_CON_SEGURIDAD**. Ninguna corrección pequeña, generalizable y demostrablemente segura existe para ninguno de los dos campos -- no se implementó nada.

**Fix adicional implementado: NO.** El comportamiento actual (valor documental conservado, `PATENTE_SIN_HOMOLOGAR`, decisión `VEHICULO_DESCONOCIDO`, sin inventar ni forzar una corrección) ya es exactamente el comportamiento seguro deseado -- se verificó, no se modificó.

**Tests:** sin cambios de código en este bloque -- se conserva 1197 passed, 0 failed sin repetir la suite.

---

### Registro de diseño futuro (consolidado en las tres bitácoras) -- NO IMPLEMENTAR

**1. Patente documental:** lo que realmente aparece en el documento -- debe preservarse siempre como evidencia, nunca sobrescribirse.

**2. Patente/vehículo canónico operacional:** el vehículo confirmado mediante evidencia operacional/humana -- no necesariamente coincide con el documento.

**3. Asociación histórica chofer↔vehículo (futura, no implementada):** relaciones históricas/auditables **chofer ↔ vehículos confirmados previamente** -- nunca modelar "chofer → un único vehículo" (un chofer puede operar distintos vehículos). Sirven exclusivamente como **evidencia para sugerir**, nunca como autocorrección automática. Ejemplo real ya confirmado (Patrick Ortiz, guía 464036): documento dice `XF3662`, vehículo asociado/confirmado es `XF3629` -- Atlas debería poder mostrar ambos valores y la posible discrepancia, y ofrecer una decisión humana (`USAR_VEHICULO_ASOCIADO` / `REGISTRAR_PATENTE_DOCUMENTAL` / `REGISTRAR_INCIDENCIA_DOCUMENTAL` / `POSPONER`), nunca reemplazar automáticamente.

**4. Incidencias documentales (futura, genérica, no implementada):** capacidad de Atlas para representar una diferencia CONFIRMADA entre `valor_documental` y `valor_operacional_confirmado`. Deliberadamente **genérica** -- no "Errores AZA", sin incrustar MBT/AZA en la arquitectura; debe servir para cualquier empresa/mandante/emisor/cliente/fuente documental futura. El documento original nunca se altera; Atlas conserva evidencia documental + verdad operacional confirmada + la incidencia que explica la diferencia. Atlas puede detectar una `POSIBLE_INCONSISTENCIA_DOCUMENTAL`, pero nunca atribuye automáticamente un error a un tercero -- la incidencia pasa a `CONFIRMADA` únicamente mediante validación humana.

**5. Tipos de incidencia (extensible por campo, no implementado):** `PATENTE_DOCUMENTAL_INCORRECTA`, `EMPRESA_TRANSPORTISTA_DOCUMENTAL_INCORRECTA` (caso real ya observado por Javier: guías de la operación MBT donde el emisor/mandante indicó otra transportista documental -- p. ej. "Transportes Carwork" -- cuando la operacional correcta era Transportes MBT), y potencialmente chofer/cliente/destino/fecha/número de transporte/otros campos operacionales.

**6. Estructura conceptual mínima (no implementada, ni siquiera como esquema):** `id`, origen/emisor, documento/guía, campo afectado, valor documental, valor operacional confirmado, tipo de incidencia, evidencia, estado (`POSIBLE`/`CONFIRMADA`/etc.), `confirmado_por`, `confirmado_en`, trazabilidad/auditoría.

**Evidencia humana vigente, sin aplicar:**
- Patrick Ortiz: `XF3629` canónica confirmada; `464036` imprime `XF3662`; no registrar `XF3662` automáticamente; candidato futuro a incidencia documental confirmada.
- Carlos Simón: `VP8521` tracto canónico confirmado; `VP6521` no registrar; rampla **sin confirmar** (Javier duda entre `JE8659`/`JE8650`; la auditoría documental leyó `JD6659`/`JD0659`); no elegir ni registrar ninguna.

**Regla de rumbo:** todo lo anterior queda **documentado únicamente**. No se inicia su implementación. El rumbo vigente sigue siendo cerrar los problemas reales de lectura/extracción revelados por el lote de 15 antes de ampliar funcionalidades -- no Mobile, no Multiempresa, no pestaña nueva, no cambios en Desktop.

**Drive:** no modificado. **Desktop:** no modificado. **Git:** working tree sin cambios adicionales al bloque anterior (mismo diff). Sin commit, sin push.

**Estado: 464367 REQUIERE CONFIRMACIÓN HUMANA -- COMPORTAMIENTO SEGURO VALIDADO.**

## 2026-08-18 — Publicación del fix estructural de patentes (`b86e280`)

**Verificación pre-commit:** diff revisado línea por línea (`git diff atlas_core/extractor.py`) -- exactamente el rename `_tolerante_o_cero`→`_tolerante_confusion_ocr_etiqueta` + tabla `_CONFUSIONES_OCR_ETIQUETA_VEHICULAR = {"0": "O", "B": "R"}` + 3 llamadas actualizadas + docstrings, sin ningún otro cambio de comportamiento. `git diff tests/test_patentes_p4.py` confirmado sin literales `TZWR86`/`JU5478`/`CARLOS ÑANCUCHEO` -- `464367` aparece únicamente en comentarios/docstrings citando la guía real que motivó el test (mismo patrón que la cita de 464631 ya existente), nunca como dato de prueba. `git diff --check` limpio. Tests focalizados (`tests/test_patentes_p4.py`) -- 17 passed -- ejecutados antes de commitear; no se repitió la suite completa por ser código byte-idéntico al que ya dio 1197 passed, 0 failed.

**Commit:** `b86e280` -- "fix: tolerar ruido OCR en etiquetas vehiculares" -- 5 archivos exactos (`atlas_core/extractor.py`, `tests/test_patentes_p4.py`, tres bitácoras).

**Push:** `git push origin lector-mvp-guia-nueva` -- `793b240..b86e280`, sin force. Verificado post-push: local `b86e280` == remoto `b86e280`, ahead/behind 0/0, working tree limpio.

**Continuidad explícita (7 puntos):**
1. Fallo estructural `CARRO→CARBO`: **corregido y publicado**.
2. `464367` **requiere resolución humana** de sus dos patentes -- `T2MN86`/`J35478` exceden `_diferencia_ocr_segura` (3 posiciones distintas para tracto; par no vetado + sin candidato de catálogo para rampla).
3. Evidencia visual documental real: `TZWR86`/`JU5478` -- distinta de lo que Atlas logró extraer.
4. Ninguna autocorrección forzada.
5. Próximo bloque **no** es Incidencias Documentales.
6. Seguimos cerrando hallazgos reales de lectura/extracción del lote de 15 antes de ampliar funcionalidad.
7. Diseño futuro (patente documental / vehículo canónico / asociación histórica chofer↔vehículo / sugerencias humanas / Incidencias Documentales genéricas) -- registrado en el bloque anterior de esta misma bitácora, **no implementado**.

**Nueva decisión de producto registrada en continuidad (no auditada ni implementada en este bloque):** **KILOMETRAJE OPERACIONAL** -- dato obligatorio de Atlas, no opcional. ORS (rutas) y Onelogis (telemetría) son las fuentes/herramientas actuales. Si su cobertura no permite obtener kilómetros de forma fiable para todos los viajes aplicables, deberá auditarse el problema e incorporarse una alternativa adecuada -- pendiente de roadmap, sin auditar ni implementar aquí.

**Drive:** no modificado -- `operacion/actual` (con `464367` todavía en `"No encontrado"`, tal como quedó promovido) no se tocó; el fix de extracción no se aplicó todavía al lote real. **Desktop:** no modificado, HEAD `fba95ac`.

**Git:** Motor publicado y limpio (`b86e280`, local=remoto, 0/0). Desktop limpio, HEAD `fba95ac`.

**Estado: CHECKPOINT LIMPIO -- FIX ESTRUCTURAL DE PATENTES PUBLICADO -- LISTO PARA CONTINUAR AUDITORÍA DEL LOTE 15.**

## 2026-08-18 — Diagnóstico dirigido de `464265` con control `464264`

**Checkpoint verificado antes de tocar código:** Motor `lector-mvp-guia-nueva` HEAD `e88849b`, local=remoto, 0/0, working tree limpio. Desktop `fix-desktop-data-root-drag-drop` HEAD `fba95ac` -- sin upstream local configurado para la rama, pero `git ls-remote` confirma que `origin/fix-desktop-data-root-drag-drop` es exactamente `fba95ac` (idéntico al HEAD local), working tree limpio. Drive `G:\Mi unidad\Atlas` tratado READ-ONLY durante todo el bloque.

**Ground truth (imágenes canónicas, SHA-256 verificado idéntico al `MANIFIESTO_SHA256.csv` de `operacion/entradas/lote_controlado_15_guias_20260818_100841/`):**

| Campo | `464264` documento | `464265` documento |
|---|---|---|
| Fecha de emisión | `05-08-2026` (nítida) | `05-08-2026` (parcialmente cubierta por una mancha física real sobre el papel; patrón de dígitos consistente con "2026" tras ampliar y aislar canales de color, no "2024") |
| Señor(es) / Cliente | `SODIMAC SA` | `SODIMAC SA` (mismo texto, bajo la sombra de la misma mancha) |
| Obra destino | `SODIMAC SA CORONEL` | `SODIMAC SA CORONEL` |
| Material | 2 líneas: `B HORMIGON 8MM 12M A630-420H (N)` / `B HORMIGON 12MM 12M A630-420H (N)` | 1 línea: `B HORMIGON 22MM 12M A630-420H (N)` |
| Tipo de carga (documental) | Barras de hormigón (implícito por descripción) | Barras de hormigón (implícito por descripción) |

**Predicción actual (dataset promovido, `operacion/actual/analisis_completo_guias.csv`, filas `464264`/`464265`) vs. reproducción real en TEMP (mismo CLI `analizar_guias_masivo.py`, PaddleOCR device=gpu):** idénticas en ambos casos -- confirma que la predicción promovida no quedó desactualizada respecto al código actual antes del fix.

| Campo | 464264 Atlas | Resultado | 464265 Atlas | Resultado |
|---|---|---|---|---|
| fecha | `05-08-2026` | LECTURA_CORRECTA | `05-08-2024` | ERROR_ATLAS |
| cliente | `SODIMAC SA` | LECTURA_CORRECTA | `No encontrado` | ERROR_ATLAS |
| obra_destino | `COMUNA` | ERROR_ATLAS (hallazgo nuevo, ver abajo) | `SODIMAC SA COROBEL` | ERROR_ATLAS (1 carácter) |
| descripcion_material | `0 HORMIGON H0E 12H A630-420N (N)` (1 de 2 líneas) | ERROR_ATLAS parcial | `` (vacío) | ERROR_ATLAS |
| tipo_carga | `NO DETERMINADO` | CONSECUENCIA (ver abajo) | `NO DETERMINADO` | CONSECUENCIA |

**OCR dirigido (bloques con geometría + confianza, dump vía `atlas_core.ocr_provider.crear_proveedor_ocr("paddleocr").leer_bloques()`, TEMP, mismas imágenes):**

- **FECHA:** bloque `'05-08-2024'` conf=0.804 en la posición exacta de FECHA DE EMISIÓN de `464265` (vs. `464264`: bloque `':05-08-2026'` conf=0.928, en la zona sin mancha). Trazado en código: `extraer_fecha()` (`atlas_core/procesamiento_masivo.py:407`) sólo exige que la fecha sea calendario-válida y caiga en `[2015-01-01, 2035-12-31]` (`ANIO_MINIMO_PLAUSIBLE`/`ANIO_MAXIMO_PLAUSIBLE`, línea 110-113) -- "2024" pasa ambas pruebas, así que se acepta sin más. El mecanismo de seguridad que sí existe (`_extraer_fecha_geometrico` + relectura focal con consenso ≥2 lecturas concordantes, línea 1184-1228) **sólo se dispara si `fecha_actual == "No encontrado"`** (línea 1186) -- nunca cuando ya hay una lectura plausible pero equivocada. **Etapa: A. OCR_BRUTO** (dígito mal leído bajo una mancha física real), agravado por un hueco de diseño en **E. CORROBORACIÓN** (el consenso focal existe pero su condición de disparo no cubre este caso). No se cambió la regla de fecha -- ampliar cuándo se dispara la relectura focal es un cambio de diseño mayor (afecta tiempo de procesamiento y comportamiento de todo el pipeline de fecha), no una corrección puntual seria para este bloque.
- **CLIENTE:** bloque vacío `''` conf=0.000 exactamente en la posición donde debería estar el valor de SEÑOR(ES) de `464265` (vs. `464264`: bloque `': SODIMAC SA'` conf=0.933 en la misma posición relativa). Recorte ampliado confirma que el texto SÍ está impreso en el papel -- la sombra de la misma mancha reduce el contraste lo suficiente para que el **detector** de PaddleOCR no proponga ninguna caja ahí (no es un error de reconocimiento de caracteres, es una caja de texto que nunca se generó). El RUT del mismo bloque también salió corrompido (`196.792.430-X` -- dígito `1` de más, `K`→`X`) y no pasa validación de RUT chileno, así que tampoco sirve como vía de recuperación alternativa (`_extraer_rut_cliente_geometrico`, `atlas_core/extractor.py:313`). El fallback existente para SEÑOR(ES) cortado por margen (`_extraer_identidad_cliente_recortada_geometrica`, línea 381) no aplica: exige que la etiqueta toque el borde izquierdo de la imagen (fotografía recortada), y aquí la etiqueta está completa y centrada -- es el valor el que falta. **Etapa: A. OCR_BRUTO**, específicamente el paso de detección de texto (antes de cualquier candidato/selección). **Comportamiento de Atlas correcto**: `CLIENTE_AUSENTE` en vez de inventar un nombre. NO_CORREGIR en este bloque -- una corrección real requeriría cambios de preprocesamiento de imagen (realce de contraste/sombras) aplicados a todo el pipeline OCR, fuera del alcance de "corrección pequeña y segura".
- **OBRA_DESTINO:** bloque `'SODIMAC SA COROBEL'` conf=0.862, geometría y concatenación de fila (`_extraer_asociaciones_geometricas`, `atlas_core/extractor.py:168`) correctas -- el único defecto es un carácter (`N`→`B`) dentro de "CORONEL", producido por el reconocimiento de caracteres del OCR, no por la selección geométrica. La corroboración contra catálogo (R2, `procesamiento_masivo.py:1230+`) correctamente no homologó "COROBEL" contra ninguna obra real y generó `OBRA_DESTINO_SIN_CORROBORAR` -- exactamente el diseño esperado (nunca fuzzy abierto). **Etapa: A. OCR_BRUTO** (un carácter). NO_CORREGIR: forzar una corrección de 1 carácter sin catálogo de referencia sería inventar contra la regla ya vigente.
- **MATERIAL:** bloque `'BORHIGON 22101 12H A630-4200 (N)'` conf=0.819 -- única línea de material de `464265`. `extraer_descripcion_material()` (`procesamiento_masivo.py:290`, antes del fix) exigía la palabra exacta `\bHORMIGON\b`; "BORHIGON" (H→B y M→H simultáneos frente a "HORMIGON") no calzaba y la línea se descartaba entera, dejando `descripcion_material=""` y disparando `MATERIAL_AUSENTE`. **Etapa: D. NORMALIZACIÓN / filtro de reconocimiento de palabra clave** (la geometría y el bloque de texto estaban bien; el filtro de keyword era demasiado frágil). Confirmado como el **mismo patrón exacto** en el control `464264`: su segunda línea de material trae `'B HOMMIGON 12MM 12M A630-420N (N)'` conf=0.856 (R→M frente a "HORMIGON") y se pierde igual de silenciosamente -- ya promovida así en `operacion/actual` hoy.
- **TIPO_CARGA:** confirmado por lectura de código que `clasificar_material()` (`atlas_core/clasificador_material.py:63`) es una función pura de `descripcion_material` -- no lee OCR ni geometría propia. Es **consecuencia directa aguas abajo**, nunca una causa independiente: con material vacío (464265) o con la palabra clave del término de barras alterada (464264: `"0 HORMIGON..."` no calza con el literal `"B HORMIGON"` de `_TERMINOS_BARRAS`, ya que el OCR también leyó mal la "B" inicial como "0"), el clasificador correctamente no encuentra evidencia y devuelve `NO DETERMINADO` -- comportamiento correcto del clasificador dado el texto que recibe.

**Comparación 464264 vs 464265 (obligatoria, sección 12):** no es un caso de "un documento funciona, el otro falla" -- ambos comparten exactamente el mismo defecto de material (uno pierde 1 de 2 líneas, el otro pierde su única línea), lo que confirma que la causa es un patrón genérico de fragilidad del filtro de palabra clave, no algo específico de `464265`. Además, `464264` (el control) tiene un error propio e independiente en `obra_destino`: el valor guardado es literalmente `"COMUNA"` -- la etiqueta de un campo vecino (columna izquierda, misma franja Y aproximada que la etiqueta "OBRA DESTINO" de la columna derecha), no el valor real "SODIMAC SA CORONEL" que el OCR sí capturó correctamente en esa fila (bloque `': SODIMAC SA CORONEL'` conf=0.933, y `motivos_revision_documento` de `464264` no incluye `OBRA_DESTINO_SIN_CORROBORAR`, lo que sugiere una asociación geométrica equivocada, no una simple ausencia). **Hallazgo nuevo, registrado aquí, explícitamente NO diagnosticado ni corregido en este bloque** -- pertenece a una causa distinta de las auditadas para `464265` y merece su propio bloque de diagnóstico dedicado a `_extraer_asociaciones_geometricas`.

**Clasificación de hallazgos:**
- **FIX_A (implementado):** material -- filtro de reconocimiento de palabra clave demasiado frágil ante ruido de OCR ya confirmado en 2 guías reales.
- **FIX_B (no implementado, requiere diseño propio):** fecha -- cuándo debe dispararse la relectura focal de seguridad más allá de "No encontrado"; `464264` obra_destino="COMUNA" -- posible fragilidad de `_extraer_asociaciones_geometricas` con etiquetas de columnas vecinas casi alineadas en Y.
- **NO_CORREGIR (comportamiento ya correcto):** cliente de `464265` (abstención honesta ante detección de texto ausente); obra_destino de `464265` (abstención honesta ante corroboración fallida, sin fuzzy abierto); tipo_carga (consecuencia correcta de sus entradas).

**Fix implementado (única corrección de este bloque):** `_CONFUSIONES_OCR_MATERIAL = ({"H","B"}, {"M","H"}, {"R","M"})` (`atlas_core/procesamiento_masivo.py`), tres pares de confusión de OCR ya confirmados con evidencia real de estas dos guías -- mismo patrón conservador que `_CONFUSIONES_OCR_ETIQUETA_VEHICULAR` en `extractor.py`. `_coincide_con_tolerancia_ocr()` exige igual longitud y como máximo 2 posiciones distintas, cada una perteneciente a la tabla vetada -- nunca distancia de edición abierta. Sólo se usa para decidir si una línea SE CONSERVA como evidencia de material; el texto guardado en `descripcion_material` sigue siendo el OCR crudo, nunca reescrito ni corregido.

**4 tests nuevos** (`tests/test_procesamiento_masivo.py`): `test_extrae_material_tolerando_confusion_ocr_h_por_b_y_m_por_h` (reproducción real 464265), `test_extrae_material_tolerando_confusion_ocr_r_por_m` (reproducción real 464264), `test_no_tolera_mas_de_dos_diferencias_ni_pares_no_vetados` (negativo: 2 diferencias sin par vetado, 3 diferencias), `test_tolerancia_ocr_material_no_afecta_otros_terminos_ni_texto_ajeno` (negativo: BARRAS/ROLLOS/ALAMBRON/BOBINAS sin tocar, texto ajeno sin falsos positivos). Suite focalizada: 138 passed (`tests/test_procesamiento_masivo.py`). Suite completa: **1201 passed, 0 failed** (baseline 1197 + 4).

**Validación real con OCR en TEMP** (copia de las 2 imágenes + `catalogos_privados/` fuera de Drive, SHA-256 verificado idéntico antes de procesar, `--sin-telemetria`, mismo CLI de producción): comparación campo a campo de las 49 columnas del CSV, antes/después del fix, para ambas guías.
- `464265`: único cambio -- `descripcion_material` `''` → `'BORHIGON 22101 12H A630-4200 (N)'`; `motivos_revision_documento` pierde `MATERIAL_AUSENTE` (los demás motivos se mantienen). `tipo_carga` permanece `NO DETERMINADO` (esperado -- el clasificador no se tocó).
- `464264`: único cambio -- `descripcion_material` gana la segunda línea (`'0 HORMIGON H0E 12H A630-420N (N) | B HOMMIGON 12MM 12M A630-420N (N)'`). `tipo_carga` permanece `NO DETERMINADO` (esperado, mismo motivo).
- Ningún otro campo se movió en ninguna de las dos guías -- sin regresiones colaterales, control de regresión con `464264` limpio.

**Integridad de Drive verificada:** SHA-256 de `PREDICCION_CONGELADA_analisis_completo_guias.csv` -- `OK` (idéntico a `PREDICCION_CONGELADA.sha256`). `mtime` de `operacion/actual/analisis_completo_guias.csv` sin cambios. Carpeta TEMP eliminada al terminar (`rm -rf`), incluidas las copias de imágenes/catálogos y los recortes de diagnóstico -- no queda ninguna carpeta nueva permanente en Drive ni en el scratchpad.

**Drive:** no modificado -- 100% read-only más validación en TEMP fuera de Drive. **Desktop:** no modificado, HEAD `fba95ac`. **Git:** Motor con `atlas_core/procesamiento_masivo.py` y `tests/test_procesamiento_masivo.py` modificados, más estas tres bitácoras. Sin commit, sin push.

No se aplicó ninguna decisión del lote. No se promovió nada a `operacion/actual`. No se tocó Desktop, catálogos, patentes, Mobile ni Multiempresa. No se inició Incidencias Documentales.

**Estado: FIX PUNTUAL 464265 VALIDADO -- LISTO PARA REVISIÓN CON JAVIER.**

## 2026-08-18 — Nueva evidencia humana: rampla canónica de Carlos Simón confirmada

**Confirmación operacional directa de Javier**, registrada sin tocar código ni catálogo: vehículo canónico del chofer **Carlos Simón** = tracto `VP8521` (ya confirmado antes) + **rampla `JD8659`** (nueva confirmación -- antes "sin confirmar", con candidatos recordados por Javier `JE8659`/`JE8650` que no coincidían literalmente con lo auditado documentalmente).

**Valores documentales de las guías, sin modificar:** `464264` extrajo `VP8521`/`JD6659`; `464265` extrajo `VP6521`/`JD0659`. Ninguno de los dos se sobrescribe ni se reemplaza en ningún dataset -- la extracción documental de Atlas para ambas guías queda exactamente igual que en el bloque de diagnóstico anterior de esta misma sesión.

**Separación explícita, sin autocorrección:** PATENTE DOCUMENTAL (lo que dice cada guía, ya extraído y auditado) vs. PATENTE CANÓNICA (`VP8521`/`JD8659`, confirmada ahora por Javier) quedan como dos conceptos distintos -- esta confirmación es evidencia para el futuro módulo de Incidencias Documentales / asociación histórica chofer↔vehículo / sugerencia humana, **ya registrado como diseño futuro, todavía no implementado**. No se aplica ninguna corrección automática ni se homologa ninguna patente contra esta confirmación en este addendum.

**Drive/catálogos:** sin modificar -- ninguna escritura en `catalogos_privados/vehiculos.json` ni en ningún otro archivo real. **Código:** sin cambios adicionales a los ya descritos en el bloque de diagnóstico de `464265` de esta misma sesión. **Decisiones:** ninguna aplicada.

**Estado: EVIDENCIA REGISTRADA -- CATÁLOGO SIN MODIFICAR, PENDIENTE DE APLICACIÓN FORMAL.**

## 2026-08-18 — Diagnóstico dirigido de `obra_destino` en `464264`

**Checkpoint verificado antes de tocar código:** Motor `lector-mvp-guia-nueva` HEAD `e88849b`, local=remoto, 0/0, working tree con únicamente el trabajo local ya validado del bloque anterior (material + evidencia Carlos Simón) -- `git status`/`git diff` revisados, nada ajeno. Desktop `fix-desktop-data-root-drag-drop` HEAD `fba95ac`, working tree limpio.

**Objetivo único:** determinar por qué `464264` guarda `obra_destino = "COMUNA"` en vez de `"SODIMAC SA CORONEL"`, e implementar el fix sólo si es pequeño y demostrablemente seguro.

**Trazado completo con OCR real dirigido, TEMP, imagen canónica de `464264`** (SHA-256 verificado contra el manifiesto del lote):

1. **Bloques OCR con geometría** (`atlas_core.ocr_provider.crear_proveedor_ocr("paddleocr").leer_bloques()`): confirma que "SODIMAC SA CORONEL" SÍ fue leído correctamente por el OCR, dos veces -- una vez como valor de SOLICITANTE (bloque `': SODIMAC SA CORONEL'` conf=0.953, x=(623,742) y=(435,452)) y otra vez como valor de OBRA DESTINO (bloque `': SODIMAC SA CORONEL'` conf=0.933, x=(622,742) y=(460,478)). El bloque `'COMUNA'` (x=(129,180) y=(466,484)) es la etiqueta de la columna izquierda, geométricamente lejos de la columna derecha donde vive OBRA DESTINO.
2. **Réplica exacta de la lógica de `_extraer_asociaciones_geometricas`** (misma fórmula de puntaje, script de solo lectura en TEMP, sin modificar el código real): contra la etiqueta `'OBRA DESTINO'` (x=(498,577) y=(455,472)), el candidato `'SODIMAC SA CORONEL'` (y=460-478) puntúa **0.1668** -- el mejor con margen amplio (siguiente candidato 0.2785, diferencia 0.11 > margen de ambigüedad 0.06). `'COMUNA'` ni siquiera es candidato nominal (`_es_candidato_nominal_geometrico` lo excluye por estar en `_EXCLUSIONES_CANDIDATO_NOMINAL_GEOMETRICO`). **Conclusión: si `_extraer_asociaciones_geometricas` hubiera resuelto este campo, habría acertado sin ambigüedad.**
3. **Orden de lectura lineal real** (`atlas_core.ocr_provider.leer_texto()`, exactamente lo que recibe `extraer_datos()` como `textos`): confirma la causa exacta --
   ```
   [034] 'OBRA DESTINO'
   [035] 'COMUNA'
   [036] 'COD DESTINATARIO'
   [037] ': SODIMAC SA CORONEL'
   ```
   El valor real (línea 037) aparece EN EL ORDEN DE LECTURA después de "COD DESTINATARIO", no antes. `buscar_obra_destino()` (`atlas_core/extractor.py:1566`) usa `re.search(r"OBRA\s+DESTINO\s+(.+?)\s+COD\s+DESTINATARIO", texto_busqueda)` sobre este texto linealizado (`"\n".join(textos)`). Como `.` sin `re.DOTALL` no cruza `\n`, el grupo capturado sólo puede ser una única línea OCR completa entre ambas etiquetas -- aquí, exactamente `'COMUNA'` (línea 035, la única intercalada). El regex hace match y captura `"COMUNA"` -- confirmado reproduciendo el regex real contra el texto real: `m.group(1) == 'COMUNA'`.
4. **`datos["obra destino"] = "COMUNA"`** (no vacío) hace que el chequeo de `procesamiento_masivo.py:862-867` (`if datos.get(campo) in {None, "", "No encontrado"} and asociaciones.get(campo): ...`) nunca reemplace el valor -- el resultado correcto de `_extraer_asociaciones_geometricas` (paso 2) queda calculado pero descartado, porque el campo ya "tenía" un valor (equivocado).

**Causa raíz clasificada: C. LABEL_VECINO_SELECCIONADO_COMO_VALOR** -- ocurre en el extractor lineal (`buscar_obra_destino`, basado en regex sobre texto ya linealizado por el orden de lectura del OCR), no en la asociación geométrica (que ya acertaba) ni en corroboración/normalización (que nunca llegan a intervenir porque el valor incorrecto ya "existe"). Es, específicamente, también una instancia de **E. FALLBACK bloqueado**: el mecanismo de respaldo geométrico correcto nunca tiene oportunidad de actuar porque el mecanismo primario (lineal) entrega un valor no vacío, aunque equivocado.

**Controles (layout AZA, `obra_destino` funcionando hoy):** `464511`, `464892`, `464781` -- mismo trazado aplicado. En los tres, `buscar_obra_destino()` **no encuentra ningún match** (el regex no puede cruzar múltiples líneas intercaladas, o no hay ninguna etiqueta suelta entre OBRA DESTINO y COD DESTINATARIO), así que `datos["obra destino"]` queda `"No encontrado"` y el mecanismo de respaldo geométrico entra normalmente y resuelve bien (`"ARMACERO MATCO SA"` / `"CONSTRUCTORA IGNACIO HURTADO"`). `464264` es la única guía del lote de 15 donde la intercalación cae exactamente en el patrón de "una única etiqueta suelta" que SÍ produce match -- por eso es el único caso real observado de esta clase de error en las 15 guías auditadas.

**Regla de seguridad ya existente, reutilizada (no una lista nueva):** `_EXCLUSIONES_CANDIDATO_NOMINAL_GEOMETRICO` (`atlas_core/extractor.py:142-148`) -- tupla ya usada por `_es_candidato_nominal_geometrico()` para rechazar etiquetas estructurales del documento como candidatos válidos de cliente/obra_destino en la vía geométrica. Se reutiliza tal cual (mismo objeto, sin duplicar ni ampliar su contenido) para rechazar, en la vía LINEAL, una captura que sea -- ella misma, tras normalizar -- exactamente una de esas etiquetas. Coincidencia **exacta**, nunca por subcadena ni fuzzy: un valor real de obra/destino que sólo CONTENGA una de esas palabras (p. ej. "CONSTRUCTORA TOTAL SPA") no se ve afectado, verificado con test negativo explícito.

**Fix implementado** (`atlas_core/extractor.py`, `buscar_obra_destino()`): tras capturar `obra = normalizar_obra_destino(coincidencia.group(1))`, se agrega `if obra and obra in _EXCLUSIONES_CANDIDATO_NOMINAL_GEOMETRICO: obra = None` antes del chequeo ya existente de `"HORA ENTRADA" not in obra` (mismo patrón de guarda ya usado ahí, generalizado con la lista canónica). Al descartar la captura, `buscar_obra_destino()` devuelve `None`, `datos["obra destino"]` permanece `"No encontrado"`, y el mecanismo de respaldo geométrico (ya demostrado correcto en el paso 2 del trazado) lo completa normalmente -- exactamente la misma vía que ya usan `464511`/`464892`/`464781` hoy. 16 líneas: comentario explicando el caso real + 2 líneas de lógica.

**9 tests nuevos** (`tests/test_extraer_datos.py`):
- `test_buscar_obra_destino_lineal_no_captura_etiqueta_vecina_comuna`: reproducción exacta del patrón de líneas real de `464264` (`OBRA DESTINO` / `COMUNA` / `COD DESTINATARIO` / valor real en líneas separadas) -- confirma que ya no se captura `"COMUNA"` (queda `"No encontrado"`, correcto para `extraer_datos()` puro sin geometría; el valor real sólo llega vía `procesar_archivo()` con bloques, ya confirmado en la validación TEMP).
- `test_buscar_obra_destino_lineal_descarta_cualquier_etiqueta_estructural_conocida` (parametrizado, 6 etiquetas: COMUNA/CIUDAD/DIRECCION/GIRO/TOTAL/RUT): generaliza que la protección cubre toda la lista canónica, no sólo el caso puntual de COMUNA.
- `test_buscar_obra_destino_lineal_sigue_capturando_valor_real_sin_etiqueta_intercalada`: no regresión -- el camino que ya funcionaba (valor real directamente entre las dos etiquetas, mismo patrón que `probar_guia1`) sigue igual.
- `test_buscar_obra_destino_lineal_no_descarta_valor_real_que_contiene_palabra_de_la_lista`: negativo -- un nombre real de obra/destino que sólo contiene una palabra de la lista ("CONSTRUCTORA TOTAL SPA") no se pierde, porque la comparación es de igualdad exacta, no de subcadena.

Suite focalizada: `tests/test_extraer_datos.py` -- 169 passed. Grupo de obra/destino/extracción (`test_extraer_datos.py`, `test_procesamiento_masivo.py`, `test_integracion_obras_destinos_r2.py`, `test_destinos_confirmacion_r34.py`, `test_destinos_d3_confirmacion.py`, `test_destinos_globales_r341.py`, `test_ciclo_obra_destino_r342.py`, `test_falso_ok_obra_destino_p1.py`, `test_reconciliacion_historica_destino_r343.py`, `test_atlas.py`, `test_ocr.py`, `test_identidad_i1.py`, `test_estados_s2.py`, `test_estados_s2_2.py`) -- 463 passed. Suite completa: **1210 passed, 0 failed** (baseline 1201 + 9).

**Validación real con OCR en TEMP** (`464264` + 4 controles `464265`/`464511`/`464781`/`464892`, copias verificadas SHA-256 idénticas al manifiesto, catálogos reales copiados read-only, `--sin-telemetria`, mismo CLI de producción). Reproducción "antes" obtenida con `git stash` temporal de sólo `atlas_core/extractor.py` (el fix de material del bloque anterior se mantuvo aplicado en ambas corridas), comparación de las 49 columnas:
- `464264`: `obra_destino` `"COMUNA"` → `"SODIMAC SA CORONEL"`; `motivos_revision_documento` gana `OBRA_DESTINO_SIN_CORROBORAR` (aditivo, correcto -- esa obra todavía no está confirmada en el catálogo real, mismo patrón honesto que el resto del lote). Ningún otro campo cambia -- `descripcion_material` conserva sus 2 líneas (fix de material intacto).
- `464265`, `464511`, `464781`, `464892`: **cero cambios en cualquier campo** -- sin regresiones en el resto del lote ni en los controles.

**Integridad de Drive verificada:** SHA-256 de `PREDICCION_CONGELADA_analisis_completo_guias.csv` -- `OK`. `mtime` de `operacion/actual/analisis_completo_guias.csv`, `catalogos_privados/vehiculos.json` y `catalogos_privados/obras_destinos.json` sin cambios. Carpeta TEMP eliminada al terminar -- no queda ninguna carpeta nueva permanente.

**Drive:** no modificado. **Desktop:** no modificado, HEAD `fba95ac`. **Git:** Motor con `atlas_core/extractor.py` y `tests/test_extraer_datos.py` modificados en este bloque (además de lo ya pendiente del bloque de material anterior), más estas tres bitácoras. Sin commit, sin push.

**Evidencia Carlos Simón, vigente sin cambios en este bloque:** tracto canónico `VP8521`, rampla canónica `JD8659`; `VP6521`/`JD0659` no se registran; discrepancias documentales de `464264`/`464265` intactas.

No se aplicó ninguna decisión del lote. No se promovió nada a `operacion/actual`. No se tocó Desktop, catálogos, patentes, fecha, cliente, Mobile ni Multiempresa. No se inició Incidencias Documentales.

**Estado: FIX OBRA_DESTINO 464264 VALIDADO -- LISTO PARA REVISIÓN CON JAVIER.**

## 2026-08-18 — Publicación (`9aabce2`) + diagnóstico de fecha `464265`

**Publicación:** commit `9aabce2` ("fix: robustecer lectura de material y obra destino") -- exactamente 7 archivos (`atlas_core/extractor.py`, `atlas_core/procesamiento_masivo.py`, `tests/test_extraer_datos.py`, `tests/test_procesamiento_masivo.py`, tres bitácoras). `git push origin lector-mvp-guia-nueva` sin force: `e88849b..9aabce2`. Post-push: local `9aabce2` == remoto `9aabce2` (confirmado por la salida del propio push y por `git rev-parse origin/lector-mvp-guia-nueva`; `git fetch` explícito fue bloqueado por el clasificador de auto-modo de la sesión, verificación alternativa suficiente), `git status -sb` sin ahead/behind, working tree limpio. Desktop verificado sin tocar: HEAD `fba95ac`, working tree limpio.

**Checkpoint verificado antes de diagnosticar fecha:** Motor HEAD `9aabce2`, local=remoto, working tree limpio -- confirmado antes de leer nada más.

**Objetivo único:** `464265` produjo `fecha = "05-08-2024"` (ground truth documental `05-08-2026`, dígitos parcialmente cubiertos por una mancha física real). No es una abstención -- es un valor sintácticamente válido y equivocado. Se buscaba una forma general, conservadora y auditable de recuperar o al menos señalar esto.

**Trazado completo con OCR real dirigido, TEMP** (SHA-256 verificado contra el manifiesto para `464264`, `464265`, `464367`, `464488`, `464494`):

1. **OCR bruto de la zona de FECHA DE EMISIÓN, `464265`:** bloque `'05-08-2024'`, confianza **0.8041**, bbox `(307, 403, 377, 417)`. Comparado con `464264` (mismo viaje): bloque `':05-08-2026'`, confianza **0.9280**, bbox `(286, 409, 361, 425)`. La caída de confianza (0.80 vs 0.93) es consistente con la mancha física ya documentada en el bloque de diagnóstico original de `464265`, que cubre parcialmente esos dígitos.
2. **`_extraer_fecha_geometrico()` real** (localiza el mismo bloque por geometría, sin decidir el valor): reproduce exactamente el mismo resultado que el OCR bruto para ambas guías -- confirma que no hay pérdida ni contaminación geométrica, el problema es puramente el reconocimiento de caracteres sobre la mancha.
3. **`extraer_fecha()` real** (`atlas_core/procesamiento_masivo.py:407`, sobre el texto lineal completo): devuelve `'05-08-2024'` para `464265` sin más candidatos en conflicto. La ventana de plausibilidad (`ANIO_MINIMO_PLAUSIBLE=2015`, `ANIO_MAXIMO_PLAUSIBLE=2035`, línea 110-111) es la única guarda temporal activa -- "2024" la pasa sin problema.
4. **Relectura focal con consenso** (`procesamiento_masivo.py:1184-1228`): existe, y su diseño (≥2 lecturas focales concordantes con confianza ≥ `CONFIANZA_MINIMA_FECHA_FOCAL=0.7`) es exactamente el tipo de verificación independiente que serviría aquí -- pero el trigger es literalmente `if fecha_actual == "No encontrado":` (línea 1186). Como `extraer_fecha()` YA devolvió un valor no vacío, el bloque completo de relectura focal nunca se ejecuta para `464265`. Confirmado leyendo el código, no infiriendo.

**Causa raíz clasificada: D. VALIDACIÓN_TEMPORAL_INSUFICIENTE combinada con E. RELECTURA_FOCAL_NO_ACTIVADA** -- no es A (el OCR hizo lo que pudo con una imagen dañada, confianza baja pero no cero, ni tampoco un error de reconocimiento "gratuito"), no es B (la geometría ubicó la caja correcta), no es C (no hay normalización que reescriba el valor). La ventana de plausibilidad (2015-2035, 21 años) es demasiado amplia para servir de guarda real contra un error de un solo dígito del año, y el único mecanismo capaz de corroborar independientemente (relectura focal) está diseñado para recuperar campos ausentes, no para auditar campos ya presentes pero de confianza dudosa.

**Distinción explícita pedida por el bloque -- ERROR DE LECTURA vs. HUECO DE DETECCIÓN DE INCONSISTENCIA:**
- A nivel de **documento individual** (`analisis_completo_guias.csv`, fila de `464265` sola): es un hueco de detección real -- ningún motivo de revisión menciona hoy que la fecha sea dudosa (los que sí aparecen, `PATENTE_SIN_HOMOLOGAR`/`OBRA_DESTINO_SIN_CORROBORAR`/`CLIENTE_AUSENTE`/`MATERIAL_AUSENTE`, son de otros campos).
- A nivel de **viaje** (consolidación por `numero_transporte`): **NO hay hueco -- la detección ya existe y ya está activa.**

**Mecanismo ya existente, auditado sin duplicar nada** (`atlas_core/gestor_viajes.py`): `agrupar_viajes()` agrupa documentos por `numero_transporte` (línea 533) y calcula, entre otros, `MotivoRevision.CONFLICTO_FECHA` (línea 563) comparando todas las fechas del grupo con `_valores_compatibles()` (línea 68: compatible si, tras normalizar, hay como máximo un valor distinto presente). `_fecha_para_desktop()` (línea 41) normaliza cada fecha a `dd-mm-aaaa` antes de comparar -- sin adivinar cuál es la correcta, sólo detecta si coinciden o no. Cobertura de test ya existente y genérica (no ligada a ninguna guía real): `tests/test_gestor_viajes.py:98`.

**Verificación real, 100% lectura, contra el dataset y el reporte YA PROMOVIDOS** (sin escribir nada):
```python
filas = [fila for fila in analisis_completo_guias.csv si numero_transporte == '0000351135']  # 464264 + 464265
viajes, _ = agrupar_viajes(filas)
```
Resultado: `estado=REQUIERE_REVISION`, `motivos_revision=['CONFLICTO_FECHA', 'CONFLICTO_OBRA_DESTINO', 'CONFLICTO_PATENTE_TRACTO', 'CONFLICTO_PATENTE_RAMPLA', 'DOCUMENTO_REQUIERE_REVISION']`. **Confirmado además directamente en el reporte YA PUBLICADO y vigente** (`reportes/reporte_promocion_lote15_20260818_153512/viajes.csv`, el que señala `estado_operacion.json` como `reporte_vigente`): la fila del viaje `0000351135` ya trae `CONFLICTO_FECHA` entre sus motivos hoy, en producción, sin ningún cambio de este bloque. El campo `fecha` mostrado a nivel de viaje (`05-08-2026`) es simplemente el primer valor no vacío encontrado (línea 590, `next(... if valor)`) -- una conveniencia de visualización, no una resolución del conflicto; el conflicto real sigue expuesto en `motivos_revision` para revisión humana, sin autocorrección silenciosa.

**Controles:**
- `464264` (mismo viaje): `extraer_fecha()` y `_extraer_fecha_geometrico()` coinciden en `'05-08-2026'`, confianza 0.928 -- consistente, sin mancha.
- `464488`, `464494` (guías no relacionadas del lote): ambas con `extraer_fecha()`/`_extraer_fecha_geometrico()` coincidentes, confianzas 0.99+.
- **Hallazgo colateral en el control `464367`** (ya cerrado en un bloque anterior por su patente, reutilizado aquí sólo como control de fecha): `extraer_fecha()` devuelve `'06-08-2026'`, pero `_extraer_fecha_geometrico()` (la caja real bajo la etiqueta FECHA DE EMISIÓN) da `'04-08-2026'` -- verificado contra la imagen: el documento real trae FECHA DE EMISIÓN `04-08-2026`, FECHA SALIDA `06-08-2026`, FECHA LLEGADA `08-08-2026` (tres fechas reales distintas). El extractor lineal terminó asociando el candidato con el contexto "FECHA SALIDA" en vez de "FECHA DE EMISIÓN", porque en el orden de lectura del OCR la etiqueta "FECHA DE EMISIÓN" y su valor real (`04-08-2026`) quedaron separados por más de la ventana de contexto de `_clasificar_contexto_fecha` (120 caracteres antes / 40 después) -- misma familia estructural de causa que el bug de `obra_destino`/`COMUNA` de `464264` ya corregido (orden de lectura OCR no preserva el layout de dos columnas), pero aquí afecta la clasificación de contexto de fecha, no la asociación geométrica. **No diagnosticado a fondo ni corregido en este bloque** -- registrado para continuidad, guía ya cerrada por otro motivo.

**Vías evaluadas y descartadas explícitamente (con evidencia, no por conveniencia):**
- **Recuperar `2026` con seguridad usando la fecha de `464264` (mismo viaje):** descartado -- prohibido explícitamente por el bloque, y no existe ninguna regla estructural que garantice que dos documentos del mismo transporte comparten fecha de emisión (podrían emitirse en días distintos aunque viajen juntos).
- **Acotar la ventana de plausibilidad (`fecha_desde`/`fecha_hasta`, ya soportada por `extraer_fecha()` y expuesta como `--fecha-desde`/`--fecha-hasta` en `analizar_guias_masivo.py`, pero nunca usada en el procesamiento real del lote) al rango del lote actual:** técnicamente ya existe como parámetro opcional, pero aplicarla automáticamente equivaldría a la heurística "todas las guías son de 2026" que el bloque pidió explícitamente no usar -- descartado.
- **Ampliar el trigger de la relectura focal para que también corrobore fechas ya aceptadas** (p. ej. usando la confianza del bloque geométrico como disparador, sin necesidad de ejecutarla en todos los documentos) **y añadir un motivo nuevo tipo `FECHA_SIN_CORROBORAR`** (mismo patrón que `OBRA_DESTINO_SIN_CORROBORAR`/`CLIENTE_SIN_CORROBORAR` ya existentes) si la relectura focal contradice el valor ya aceptado: la única vía que sigue siendo plausible y coherente con la arquitectura existente, pero requiere calibrar un umbral de confianza con más evidencia que las ~5 guías disponibles en este bloque, y validar su impacto de rendimiento (relecturas OCR adicionales) contra el histórico completo -- **clasificado como diseño independiente (FIX_B), no una corrección puntual pequeña. No implementado.**

**Fix implementado: NO.** El resultado que se pedía demostrar -- "¿se puede detectar 2024 como no confiable?" -- ya es cierto hoy, sin ningún cambio de código, verificado con datos reales ya promovidos y ya publicados. No hay nada que corregir en ese sentido; ampliar la detección a nivel de documento individual es una mejora futura razonable pero de mayor alcance (FIX_B), no justificada como corrección puntual en este bloque.

**Tests:** ninguno nuevo -- no hubo cambio de código. Cobertura ya existente de `CONFLICTO_FECHA` confirmada en `tests/test_gestor_viajes.py:98`.

**Suite:** sin cambios -- se mantiene 1210 passed, 0 failed (no se repitió, código byte-idéntico a `9aabce2`).

**Drive:** no modificado -- bloque 100% lectura (imágenes vía TEMP con SHA-256 verificado, CSV real, catálogos, reporte ya publicado). `PREDICCION_CONGELADA.sha256` -- `OK`. `mtime` de `operacion/actual/analisis_completo_guias.csv` sin cambios. Carpeta TEMP eliminada al terminar.

**Git:** Motor sin cambios adicionales a `9aabce2` -- working tree limpio, sólo estas tres bitácoras. Sin commit, sin push. Desktop sin cambios, HEAD `fba95ac`.

**Cliente de `464265`:** no tocado.

**Pendientes explícitos, sin iniciar:** señal de fecha dudosa a nivel de documento individual (diseño FIX_B, registrado); fecha de `464367` (registrado, guía ya cerrada por patente); cliente de `464265`; demás hallazgos del lote de 15.

**Estado: DIAGNÓSTICO FECHA 464265 COMPLETADO -- REQUIERE DECISIÓN.**

## 2026-08-18 — Publicación (`d22829d`) + diagnóstico dirigido de `CLIENTE_AUSENTE` en `464265`

**Publicación:** commit `d22829d` ("docs: registrar diagnostico de fecha 464265") -- exactamente 3 archivos (las tres bitácoras, 0 líneas eliminadas, sólo el diagnóstico ya cerrado de fecha). `git push origin lector-mvp-guia-nueva` sin force: `9aabce2..d22829d`. Post-push: local `d22829d` == remoto `d22829d` (confirmado por `git rev-parse origin/lector-mvp-guia-nueva` y por la salida del propio push), `git status -sb` sin ahead/behind, working tree limpio. Desktop verificado sin tocar: HEAD `fba95ac`, working tree limpio.

**Checkpoint verificado antes de diagnosticar cliente:** Motor HEAD `d22829d`, local=remoto, working tree limpio.

**Objetivo único:** `464265` produce `cliente = "No encontrado"` (motivo `CLIENTE_AUSENTE`), mientras la inspección física del documento confirma "SODIMAC SA" (RUT `96.792.430-K`, mismo cliente que `464264`, mismo viaje).

**Ground truth desde la imagen** (recortes ampliados, canales realzados): nombre "SODIMAC SA" y RUT "96.792.430-K" son legibles bajo la sombra de la mancha física ya documentada en el bloque de fecha -- degradados, no ilegibles para un humano.

**Trazado completo con OCR real dirigido, TEMP** (SHA-256 verificado contra el manifiesto para `464264`/`464265`):

1. **Bloques OCR crudos, zona SEÑOR(ES)/R.U.T.** (`atlas_core.ocr_provider.crear_proveedor_ocr("paddleocr").leer_bloques()`):
   - `464264`: etiqueta `'SEÑOR(ES)'` conf=0.9975 y, en la posición de su valor (x=285-360, y=422-439), bloque `'SODIMAC SA'` conf=**0.9335**. RUT: bloque `'196.752.430-K'` conf=0.8821.
   - `464265`: etiqueta `'SEÑOR(ES)'` conf=0.9898 y, en la posición equivalente de su valor (x=305-377, y=415-429), **bloque vacío `''` conf=0.0000** -- el detector no propuso ninguna caja de texto ahí, no es una lectura de baja calidad, es ausencia total. RUT: bloque `'196.792.430-X'` conf=0.8751.
2. **`_extraer_asociaciones_geometricas()` real** (`atlas_core/extractor.py:168`): para `464264` devuelve `{'cliente': 'SODIMAC SA', 'obra destino': 'SODIMAC SA CORONEL'}`. Para `464265` devuelve únicamente `{'obra destino': 'SODIMAC SA COROBEL'}` -- **sin clave `cliente`**, porque el bloque vacío en esa posición nunca pasa el filtro `_es_candidato_nominal_geometrico` (exige `2 <= len(texto) <= 60`) -- no hay ningún candidato nominal que evaluar cerca de la etiqueta SEÑOR(ES).
3. **`_extraer_identidad_cliente_recortada_geometrica()` real** (línea 381, fallback para etiqueta cortada por margen de foto): `{}` en ambas guías -- no aplica, exige que la etiqueta SEÑOR(ES) toque el borde izquierdo de la imagen (`x1 <= 3`), y en ambas guías la etiqueta está completa (`x1=131` / `x1=158`).
4. **`_extraer_rut_cliente_geometrico()` real** (línea 313): `{}` en **ambas** guías. Verificado con `validar_rut_chileno()` directamente: `'196.752.430-K'` (464264) → `INVALIDO` ("longitud inválida" -- un dígito de más); `'196.792.430-X'` (464265) → `INVALIDO` ("formato inválido" -- "X" no es un dígito verificador chileno válido, que sólo admite 0-9/K). El ground truth real `'96.792.430-K'` → `VALIDO`. Confirmado: **el mecanismo de RUT ya existe y ya se ejecuta, pero se abstiene correctamente en ambos casos** porque el RUT capturado por OCR no pasa el dígito verificador -- comportamiento seguro, no un bug. Nótese que la corrupción del RUT (un "1" de más al inicio) aparece en **ambas** guías, incluida `464264` sin mancha -- no es causada por la mancha, es un artefacto de OCR distinto y no relacionado con la ausencia de nombre en `464265`.
5. **Mecanismos de relectura focal existentes, auditados:** sólo hay dos, ambos con `allowlist` de caracteres restringido -- `ALLOWLIST_FECHA` (`atlas_core/ocr.py:104`, dígitos y separadores de fecha) y `ALLOWLIST_TRANSPORTE` (línea 103, dígitos y letras confundibles con dígitos). **No existe ningún mecanismo de relectura focal para nombres de cliente** (texto libre, sin alfabeto restringido natural) -- no es que falle o no se active, es que no está construido para este tipo de campo.

**Respuestas exactas a las 7 preguntas del bloque:**
1. ¿SODIMAC SA aparece en OCR bruto de `464265`? **NO** -- caja de texto ausente, confianza 0.
2. ¿Aparece el RUT? **SÍ**, pero corrupto (`196.792.430-X`), formato inválido.
3. ¿Se genera bounding box para SEÑOR(ES)? **SÍ**, para la etiqueta (conf. 0.99) -- el problema es exclusivamente el valor.
4. ¿La mancha impide detección o sólo reduce confianza? **Impide la detección por completo** en la zona del nombre (confianza 0, no un valor bajo). El RUT, más abajo, sí fue detectado (con otra corrupción, no causada por la mancha).
5. ¿Existe OCR focal/secundario para cliente? **NO** -- sólo existe para fecha y número de transporte.
6. ¿Por qué no se activa/falla? No aplica "por qué falla" -- **no existe la infraestructura** para este tipo de campo.
7. ¿El problema ocurre antes o después de la resolución contra catálogo? **Antes** -- nunca llega a generarse ningún candidato (ni nombre ni RUT válido) que pasar a `_resolver_cliente_id_corroborado` (`procesamiento_masivo.py:664`) o a `CatalogoClientes.buscar()`.

**Causa raíz clasificada: A. OCR_BRUTO_NO_DETECTA_TEXTO** (para el nombre) -- la caja de texto simplemente no se generó, no hay ningún candidato que una lógica de selección/normalización/corroboración pudiera haber tratado mal. El camino de RUT (F en el listado de causas) **no es un caso de "RUT no aprovechado"** -- el RUT sí se evalúa, se abstiene correctamente porque el valor capturado es inválido (mismo patrón de corrupción, no relacionado con la mancha, presente también en el control sin mancha).

**Comparación 464264 vs 464265 (sección 5, obligatoria):** misma etiqueta SEÑOR(ES), misma posición relativa, mismo layout, mismo cliente real. Único cambio real: la mancha física cae exactamente sobre la zona del nombre en `464265` y ahí el detector de PaddleOCR no genera ninguna caja (mecanismo de detección, previo a cualquier reconocimiento de caracteres) -- en `464264`, sin mancha en esa zona, el detector sí genera la caja y el reconocimiento la lee con confianza 0.93. El RUT de ambas guías comparte el mismo artefacto de corrupción (dígito de más), independiente de la mancha, y en ninguna de las dos sirve como ancla porque ambos fallan el dígito verificador chileno.

**Vía investigada explícitamente y descartada -- SOLICITANTE como sustituto de cliente:** `464265` sí trae un bloque OCR legible en el campo SOLICITANTE (`'SODIMAC SA CORWEL'`, conf=0.7311, con su propia corrupción de "CORONEL"→"CORWEL", distinta de la de OBRA DESTINO "CORONEL"→"COROBEL" en el mismo documento -- evidencia adicional de ruido de OCR generalizado en esta guía, no un patrón único). Se descarta usarlo como respaldo automático de cliente: es un campo documental distinto, con semántica propia -- en el propio `464264` (control), SOLICITANTE trae `"SODIMAC SA CORONEL"`, no el texto simple `"SODIMAC SA"` del campo cliente -- confirma que ambos campos no siempre coinciden literalmente, así que sustituir uno por otro produciría a veces un valor incorrecto sin evidencia real de que sea el mismo dato.

**¿Existe evidencia documental suficiente para recuperar "SODIMAC SA" con seguridad hoy? NO.** No hay texto de nombre detectado (nada que seleccionar), y el único candidato adicional (RUT) es inválido tal como fue leído. Ninguna corrección de código puede generar evidencia donde el motor de OCR no detectó ninguna.

**Vía plausible para diseño futuro, evaluada y NO implementada:** relectura focal del recorte de RUT con `allowlist` numérico (`0123456789.-Kk`, mismo patrón exacto que `ALLOWLIST_FECHA`/`ALLOWLIST_TRANSPORTE`), activada cuando el RUT geométrico capturado falla `validar_rut_chileno` (no sólo cuando está ausente), con el mismo esquema de consenso (≥2 lecturas concordantes con confianza mínima) ya usado para fecha. Si produce un RUT válido con consenso, se enrutaría por el camino YA EXISTENTE y seguro de coincidencia EXACTA de RUT contra catálogo (`_resolver_cliente_id_corroborado`) -- nunca por nombre aproximado ni fuzzy. **Riesgo mayor que el caso de fecha:** una relectura de RUT parcialmente errónea podría producir un RUT válido (pasa el dígito verificador) pero perteneciente a un cliente equivocado -- mucho más delicado que una fecha equivocada, porque asigna una identidad de cliente completa. Requiere su propia validación de tasa de acierto/riesgo contra el histórico -- **clasificado como diseño independiente (FIX_B), no implementado en este bloque.**

**Fix implementado: NO.**

**Tests:** ninguno nuevo -- no hubo cambio de código.

**Suite:** sin cambios -- se mantiene 1210 passed, 0 failed (no se repitió, código byte-idéntico a `d22829d`).

**Drive:** no modificado -- bloque 100% lectura (imágenes vía TEMP con SHA-256 verificado, catálogos). `PREDICCION_CONGELADA.sha256` -- `OK`. `mtime` de `operacion/actual/analisis_completo_guias.csv` sin cambios. Carpeta TEMP eliminada al terminar.

**Git:** Motor sin cambios adicionales a `d22829d` -- working tree limpio, sólo estas tres bitácoras. Sin commit, sin push de este bloque. Desktop sin cambios, HEAD `fba95ac`.

**Pendientes explícitos, sin iniciar:** relectura focal de RUT para cliente (diseño futuro FIX_B, registrado); demás hallazgos del lote de 15; fecha de `464367` (registrado en el bloque anterior).

**Estado: DIAGNÓSTICO CLIENTE 464265 COMPLETADO -- REQUIERE DECISIÓN.**

## 2026-08-18 — Cierre aceptado de `CLIENTE_AUSENTE 464265` + principio operacional ratificado

**Cierre:** diagnóstico de `464265` ACEPTADO, sin fix de código. Aclaración explícita de continuidad, ya presente implícitamente en el bloque de diagnóstico anterior pero ratificada aquí sin ambigüedad: `CLIENTE_AUSENTE` en este caso significa "Atlas no logró extraer un dato que el documento sí trae" (nombre y RUT verificados visualmente en la imagen, bajo la sombra de la mancha física) -- **no** "el documento carece del campo cliente". El motivo `CLIENTE_AUSENTE` es genérico y hoy no distingue estos dos casos (dato realmente ausente del documento vs. dato presente pero no extraído) -- diferencia relevante para el futuro diseño de Incidencias Documentales, no resuelta aquí.

**Principio operacional ratificado por Javier, registrado formalmente en esta bitácora:**
> Cuando Atlas tiene evidencia suficiente, actúa. Cuando existe una duda material, consulta. Cuando no existe evidencia suficiente, se abstiene. Atlas nunca debe adivinar para evitar una revisión humana. Esto no significa preguntar innecesariamente: si una identidad está inequívocamente corroborada, Atlas debe resolverla sin intervención.

Consistente con el comportamiento ya implementado y auditado en todos los bloques de esta sesión: abstención conservadora ante ambigüedad o evidencia insuficiente (fecha/cliente de `464265`, obra_destino sin corroborar), resolución automática sin fricción cuando la evidencia es inequívoca (RUT exacto contra catálogo `CONFIRMADO`/`ACTIVO`, patentes homologadas, tolerancias de OCR acotadas a pares ya vetados). No se trata de una regla nueva de comportamiento -- es la primera vez que se registra como principio explícito y citable.

**Drive/Desktop:** sin cambios. **Git:** working tree del Motor con sólo estas tres bitácoras, listo para publicarse como cierre documental de FASE 0.

**Estado: CLIENTE 464265 CERRADO SIN FIX -- LISTO PARA PUBLICAR.**

## 2026-08-18 — Diagnóstico dirigido de `464367`: FECHA EMISIÓN vs. FECHA SALIDA

**Publicado antes de empezar:** commit `74c1478` ("docs: registrar diagnostico de cliente 464265") -- 3 archivos exactos (tres bitácoras). Push sin force: `d22829d..74c1478`. Post-push: local `74c1478` == remoto `74c1478` (confirmado por `git rev-parse origin/lector-mvp-guia-nueva`), `git status -sb` sin ahead/behind, working tree limpio. Desktop verificado sin tocar: HEAD `fba95ac`, working tree limpio.

**Checkpoint verificado antes de diagnosticar:** Motor HEAD `74c1478`, local=remoto, working tree limpio.

**Ground truth desde la imagen canónica de `464367`** (SHA-256 verificado contra el manifiesto), recortes ampliados de cabecera y de la zona RETIRA/PATENTE/FECHA:
- FECHA DE EMISIÓN: **`04-08-2026`**.
- FECHA SALIDA: **`06-08-2026`**.
- Otra fecha presente: FECHA LLEGADA `08-08-2026` (además de una nota de entrega suelta "06.08 ... Hrs Cristian ..." dentro del campo MOTIVO de la tabla TIPO DE DOCUMENTO/FOLIO/FECHA/MOTIVO, sin etiqueta de fecha propia).

**Objetivo único:** determinar por qué `extraer_fecha()` devuelve `06-08-2026` (FECHA SALIDA) en vez de `04-08-2026` (FECHA DE EMISIÓN, campo canónico) para esta guía.

**Trazado completo con OCR real dirigido, TEMP:**

1. **Orden lineal OCR real** (`atlas_core.ocr_provider.crear_proveedor_ocr("paddleocr").leer_texto()`, exactamente lo que recibe `extraer_datos()`/`extraer_fecha()` como `textos`):
   ```
   [013] '04-08-2026'
   [014] 'ORDEN DE COMPRA'
   [015] '1052,530822 / 0030021561'
   [016] 'FECHA DE EMISIÓN'
   ...
   [107] 'FECHA SALIDA'
   [108] '06-08-2026'
   ```
   El **valor** de FECHA DE EMISIÓN aparece en la posición 013, tres bloques **antes** que su propia **etiqueta** (posición 016) -- orden invertido. FECHA SALIDA, en cambio, aparece con su etiqueta (107) inmediatamente antes de su valor (108) -- orden normal.
2. **`extraer_fecha()` real** (`procesamiento_masivo.py:407`): devuelve `'06-08-2026'`.
3. **`_clasificar_contexto_fecha()` real** (línea 302, ventana de 120 caracteres hacia atrás y 40 hacia adelante alrededor de cada candidato) aplicada a cada candidato del texto lineal real:
   - `'04-08-2026'` → prioridad **3 (`GLOBAL`)** -- el contexto (`...CODIGO CTIENTE\n0001004741\n04-08-2026\nORDEN DE COMPRA\n1052,530822 / 003002156...`) no contiene "FECHA DE EMISION" en absoluto. Medido con precisión: entre el candidato y su propia etiqueta hay **42 caracteres** ("ORDEN DE COMPRA\n1052,530822 / 0030021561\n") -- **2 caracteres más que el límite de 40 hacia adelante** de la ventana.
   - `'06-08-2026'` → prioridad **1 (`FECHA SALIDA`)** -- el contexto sí contiene "FECHA SALIDA" inmediatamente antes.
   - Al comparar prioridades (menor = mejor), `06-08-2026` (prioridad 1) le gana a `04-08-2026` (prioridad 3) -- de ahí el resultado incorrecto.
4. **`_extraer_fecha_geometrico()` real** (`atlas_core/extractor.py:662`, ubica por posición 2D real en la imagen, inmune al orden de lectura): `{'valor': '04-08-2026', 'caja': (205.0, 353.0, 271.0, 368.0), 'confianza': 0.9348}` -- **encuentra correctamente la FECHA DE EMISIÓN real**, con alta confianza, sin ambigüedad (esta función además excluye explícitamente FECHA SALIDA/LLEGADA como candidatos rivales, `es_etiqueta_fecha_rival`, línea 679).
5. **Por qué el respaldo geométrico nunca se ejecuta:** en `procesamiento_masivo.py:1184-1228`, el bloque que invoca `_extraer_fecha_geometrico()` + relectura focal con consenso sólo se dispara `if fecha_actual == "No encontrado":`. Como `extraer_fecha()` ya devolvió `'06-08-2026'` (no vacío), ese bloque nunca se ejecuta -- el candidato correcto, ya localizado con alta confianza por geometría, queda calculable pero sin usarse.

**Respuestas exactas a las 9 preguntas del bloque:**
1. ¿FECHA DE EMISIÓN aparece correctamente en OCR? Sí, la etiqueta se leyó bien (conf. alta).
2. ¿Su valor aparece correctamente? Sí, `'04-08-2026'` se leyó bien (conf. 0.935 según el bloque geométrico).
3. ¿FECHA SALIDA aparece correctamente? Sí.
4. ¿Su valor aparece correctamente? Sí, `'06-08-2026'`.
5. ¿Qué fecha captura primero el extractor lineal? Ninguna "primero" en el sentido de posición -- el extractor evalúa TODOS los candidatos y elige por prioridad de contexto; gana `06-08-2026` por tener mejor prioridad (1 vs. 3).
6. ¿Existe respaldo geométrico para fecha? Sí, `_extraer_fecha_geometrico()`, y encuentra el valor correcto.
7. ¿El respaldo geométrico encuentra la fecha correcta? Sí, `04-08-2026`, alta confianza, sin ambigüedad.
8. ¿Se bloquea porque ya existe una fecha lineal no vacía? Sí -- exactamente igual que el hueco ya documentado en el bloque de fecha de `464265` (el trigger es sólo `"No encontrado"`).
9. ¿Es el mismo patrón estructural que produjo COMUNA en `464264`, o sólo se parece superficialmente? **Comparten el mismo origen** (el orden de lectura del OCR no preserva la adyacencia label→valor en un layout de dos columnas), **pero el mecanismo de fallo en código es distinto**: en COMUNA, un regex de captura (`.+?` sin cruzar líneas) terminó atrapando una etiqueta vecina ajena como si fuera el valor (`buscar_obra_destino`). Aquí, el candidato correcto SÍ se captura como texto -- lo que falla es la CLASIFICACIÓN DE CONTEXTO por ventana de caracteres fija (`_clasificar_contexto_fecha`), que pierde de vista la etiqueta propia por sólo 2 caracteres y deja ganar a un candidato rival con contexto correctamente adyacente.

**Causa raíz clasificada: B. ORDEN_LINEAL_OCR** (primaria -- la inversión de orden label/valor es la causa física) → cascada a **D. CANDIDATO_CORRECTO_DESCARTADO** (pierde la comparación de prioridad de contexto por la ventana fija) → **E. FALLBACK_GEOMETRICO_BLOQUEADO** (el mecanismo que sí acierta nunca se ejecuta porque el trigger exige `"No encontrado"`).

**Controles (mínimo 3, layout AZA, lote actual):** `464264`, `464488`, `464494` -- en los tres, confirmado con OCR real, la etiqueta "FECHA DE EMISIÓN" aparece **siempre inmediatamente antes** de su valor en el orden de lectura (`extraer_fecha()` y `_extraer_fecha_geometrico()` coinciden exactamente en los tres, sin inversión). `464367` es el único caso de los 4 examinados (y de los ya auditados en el bloque de fecha anterior) con esta inversión específica de orden.

**Semántica canónica del campo `fecha` -- auditada, sin ambigüedad:** `docs/HANDOFF_ATLAS.md` (checkpoint histórico "F2 completado y auditado") documenta explícitamente que el mecanismo de recuperación OCR focal fue construido específicamente para **FECHA DE EMISIÓN** -- confirmado además por el propio código: `_extraer_fecha_geometrico()` sólo reconoce la etiqueta "FECHA (DE) EMISION" como ancla válida y excluye explícitamente "FECHA SALIDA"/"FECHA LLEGADA" como candidatos rivales (`es_etiqueta_fecha_rival`). No hay ambigüedad histórica que resolver -- el campo `fecha` representa FECHA DE EMISIÓN.

**Variantes de corrección evaluadas, con riesgos distintos entre sí -- ninguna implementada:**
1. **Comprobación barata de corroboración (sin llamadas OCR adicionales):** calcular siempre `_extraer_fecha_geometrico()` (no cuesta OCR extra -- opera sobre los bloques ya obtenidos) y comparar contra `fecha_actual`; si difieren en la fecha calendario real, añadir un motivo nuevo tipo `FECHA_SIN_CORROBORAR` (mismo patrón que `OBRA_DESTINO_SIN_CORROBORAR`/`CLIENTE_SIN_CORROBORAR`) **sin cambiar el valor guardado**. Riesgo principal: la tasa de falsos positivos sobre el histórico completo no está medida (sólo se dispone de 5 guías reales de evidencia en este bloque) -- podría señalar guías sin problema real si la geometría produce candidatos discordantes por otras razones no vistas todavía.
2. **Verificación profunda con autocorrección condicionada:** ampliar el disparador de la relectura focal con consenso (ya usada para el caso "No encontrado") para que también se ejecute ante discrepancia lineal/geométrica, y si el consenso confirma la fecha geométrica, usarla en vez de la lineal. Más caro (relecturas OCR adicionales en documentos con discrepancia) y de mayor riesgo -- cambia automáticamente un valor ya "presente", algo que esta auditoría ha evitado deliberadamente en todos los bloques anteriores salvo con evidencia inequívoca.
3. **Ampliar la ventana de caracteres de `_clasificar_contexto_fecha`** (de 120/40 a un valor mayor): la más simple de implementar, pero es exactamente el tipo de "heurística temporal" que este bloque pidió explícitamente no asumir como solución -- un valor de ventana mayor sigue siendo arbitrario y podría generar coincidencias de contexto nuevas e incorrectas en otras guías no evidenciadas aquí.
4. **No implementar nada:** `464367` ya está cerrada por su hallazgo de patente, no bloquea ninguna promoción, y no tiene un documento hermano en su viaje (transporte `0000351370` sólo tiene esta guía) que ya la señale como `CONFLICTO_FECHA` -- a diferencia de `464265`, aquí no hay una red de seguridad ya activa cubriendo este caso específico.

Ninguna de las cuatro es tan claramente "la única opción segura" como lo fueron los fixes ya publicados de material (evidencia repetida, mecanismo ya vetado) y obra_destino (una única solución que reutilizaba infraestructura exacta sin alternativas plausibles). Siguiendo el mismo criterio conservador aplicado en todo este bloque de auditoría, se presentan las cuatro variantes para decisión de Javier en vez de elegir una arbitrariamente.

**Fix implementado: NO.**

**Tests:** ninguno nuevo -- no hubo cambio de código.

**Suite:** sin cambios -- se mantiene 1210 passed, 0 failed (no se repitió, código byte-idéntico a `74c1478`).

**Drive:** no modificado -- bloque 100% lectura (imagen vía TEMP con SHA-256 verificado, catálogos). `PREDICCION_CONGELADA.sha256` -- `OK`. `mtime` de `operacion/actual/analisis_completo_guias.csv` sin cambios. Carpeta TEMP eliminada al terminar.

**Git:** Motor sin cambios de código -- working tree con sólo estas tres bitácoras. Sin commit, sin push de este bloque.

**Cliente `464265`:** cerrado sin fix en el bloque anterior, no reabierto aquí.

**Pendientes explícitos, sin iniciar:** decisión de Javier sobre las 4 variantes de fecha `464367`; relectura focal de RUT para cliente `464265` (FIX_B, registrado); demás hallazgos del lote de 15.

**Estado: DIAGNÓSTICO FECHA 464367 COMPLETADO -- REQUIERE DECISIÓN.**

## 2026-08-18 — Publicación (`b343a41`) + corroboración geométrica de fecha de emisión

**Publicación:** commit `b343a41` ("docs: registrar diagnostico fecha emision 464367") -- 3 archivos exactos (tres bitácoras). Push sin force: `74c1478..b343a41`. Post-push: local `b343a41` == remoto `b343a41`, `git status -sb` sin ahead/behind, working tree limpio. Desktop verificado sin tocar: HEAD `fba95ac`, working tree limpio.

**Checkpoint verificado antes de auditar:** Motor HEAD `b343a41`, local=remoto, working tree limpio.

**Pregunta central del bloque:** ¿la salida de `_extraer_fecha_geometrico()`, cuando está anclada inequívocamente a FECHA DE EMISIÓN, constituye evidencia documental suficiente para corroborar (y eventualmente reemplazar) un valor lineal ya presente?

**Auditoría semántica de ambos extractores (sin asumir "geometría gana"):**
- `extraer_fecha()` (lineal, `procesamiento_masivo.py:407`): "el mejor candidato que representa una fecha de calendario válida" -- genérico, prioriza por contexto (`_clasificar_contexto_fecha`) entre FECHA DE EMISION (prioridad 0) / FECHA SALIDA (1) / FECHA LLEGADA (2) / otra etiqueta (2) / GLOBAL (3), pero no está anclado exclusivamente a un campo -- puede devolver cualquiera de ellos si su contexto gana.
- `_extraer_fecha_geometrico()` (`extractor.py:662`): diseñado específicamente para FECHA DE EMISIÓN -- `es_etiqueta_emision()` sólo reconoce esa etiqueta; `es_etiqueta_fecha_rival()` excluye explícitamente FECHA SALIDA/LLEGADA de los candidatos; se abstiene (retorna `{}`) ante ambigüedad (margen 0.06 entre el mejor candidato y cualquier otro) o ausencia de etiqueta/candidato.
- **¿Puede alguna vez devolver SALIDA/LLEGADA por error?** No, por diseño y por test: `test_fecha_geometrica_prioriza_emision_sobre_salida_cercana` y `test_fecha_geometrica_no_toma_candidato_mas_cercano_a_salida_que_a_emision` (`tests/test_extraer_datos.py:777,789`) ya prueban exactamente esto -- incluso cuando un candidato está geométricamente más cerca de FECHA SALIDA, la función se abstiene en vez de robarlo.
- **¿Es fallback histórico o restricción deliberada?** El uso actual (sólo si `fecha_actual == "No encontrado"`) es histórico -- la función en sí (`_extraer_fecha_geometrico`) no impone esa restricción, es el *call site* en `procesar_archivo()` el que la limita a recuperación, nunca a corroboración. No hay ninguna razón de diseño documentada que impida ampliar el trigger; sólo no se había hecho.

**Auditoría real amplia, read-only (`atlas_core.ocr_provider.crear_proveedor_ocr("paddleocr")`, sin escribir nada), sobre las **43 guías reales** disponibles en Drive** (las 15 del lote actual + 28 de lotes históricos anteriores, `operacion/entradas/*`, duplicados por nombre de archivo alternativo descartados por SHA-256 idéntico):

| Categoría | Guías | Detalle |
|---|---|---|
| A. Lineal == Geométrico | 38 | Sin conflicto -- incluye `464264` (05-08-2026, conf. 0.928) y `464265` (05-08-2024, conf. 0.804 -- ambos coinciden en el valor erróneo ya diagnosticado por la mancha física, sin relación con este bloque) |
| B. Discrepan, geométrico inequívoco | 1 | `464367` -- lineal `06-08-2026`, geométrico `04-08-2026` conf. 0.935, ya verificado correcto contra la imagen |
| C. Discrepan, geométrico ambiguo | 0 | No observado -- estructuralmente casi imposible: `_extraer_fecha_geometrico` sólo devuelve un valor no vacío cuando ya pasó su propio filtro de ambigüedad, así que cualquier resultado no vacío es, por construcción, ya "B" |
| D. Geométrico ausente | 4 | `464493`, `464522`, `464601` (sin ancla localizable) y `464529` (candidato geométrico bruto `"110-08-2026"`, no parseable como fecha -- tratado igual que ausente) -- comportamiento actual preservado sin cambios |
| E. Lineal ausente, geométrico presente | 0 | No observado en esta muestra -- `extraer_fecha()` nunca devolvió `"No encontrado"` en las 43 guías |

**Fiabilidad medida:** de 39 guías donde ambos mecanismos producen una fecha comparable, 38/39 coinciden (97.4%) y en la única discrepancia el geométrico fue el correcto -- 0 falsos positivos observados en la muestra real disponible.

**Decisión: OPCIÓN A -- autocorrección segura, con la misma exigencia de verificación que ya usa el resto de esta auditoría.** No basta con la confianza reportada por el bloque geométrico (464265 ya demostró que un valor con confianza 0.80 puede ser un error real) -- se exige la MISMA relectura focal con doble confirmación (≥2 lecturas concordantes, confianza ≥ `CONFIANZA_MINIMA_FECHA_FOCAL`) ya usada para recuperar una fecha ausente, antes de aceptar cualquier cambio.

**Implementación** (`atlas_core/procesamiento_masivo.py`):
- Nuevo motivo `MotivoRevisionDocumento.FECHA_SIN_CORROBORAR` (no incluido en `MOTIVOS_NO_BLOQUEANTES` -- bloqueante por defecto, mismo criterio que `OBRA_DESTINO_SIN_CORROBORAR`/`CLIENTE_SIN_CORROBORAR`).
- Nuevo bloque, deliberadamente SEPARADO del bloque existente de recuperación "No encontrado" (sin tocarlo, cero riesgo de regresión sobre código ya probado): si `fecha_actual != "No encontrado"` y `bloques_guia` ya está cargado (ver alcance abajo), compara la fecha geométrica (vía `_valor_fecha_a_date`) contra la lineal; si difieren, ejecuta la misma relectura focal + votación de consenso (código duplicado deliberadamente, no refactorizado a un helper compartido, para no arriesgar el camino ya probado); si el consenso confirma el candidato geométrico, reemplaza `fecha_actual` (mismo tag `MetodoObtencionDocumento.FOCAL`); si confirma el lineal, no hay nada que corregir; si no hay consenso único o confirma una tercera fecha distinta, `FECHA_SIN_CORROBORAR` y se conserva el valor lineal intacto.
- **Alcance deliberadamente acotado:** la corroboración sólo corre si `bloques_guia is not None` -- es decir, sólo si YA se cargó por necesitarse para otro campo ausente/contaminado en el mismo documento (cliente, obra_destino, RUT, chofer, patentes, número de guía). Nunca fuerza una carga nueva de bloques sólo para esto. Esta restricción se agregó tras encontrar, en la primera versión de la implementación, que rompía 4 tests ya existentes que verifican explícitamente que un documento cuyo texto lineal resuelve todo **nunca** toca `leer_bloques_imagen` (`test_procesar_archivo_preserva_chofer_lineal_limpio`, `test_procesar_archivo_fecha_global_valida_no_dispara_focal`, `test_procesar_archivo_no_reemplaza_valores_lineales_correctos`, `test_procesar_archivo_sin_proveedor_usa_easyocr_directo_como_antes`) -- invariante de rendimiento ya existente y deliberado, preservado sin excepción. `464367` cumple la condición igualmente (cliente y patentes ausentes en el dataset real), así que no se pierde cobertura del único caso real evidenciado.

**10 tests nuevos** (`tests/test_procesamiento_masivo.py`):
- `test_procesar_archivo_fecha_corrige_via_geometria_cuando_lineal_asocia_fecha_salida`: reproducción estructural exacta de 464367, corrección confirmada.
- `test_procesar_archivo_fecha_no_corrige_si_geometria_es_ambigua`, `test_procesar_archivo_fecha_no_corrige_si_etiqueta_emision_ausente_en_bloques`: negativos, casos D.
- `test_procesar_archivo_fecha_marca_sin_corroborar_si_discrepancia_no_se_resuelve`: negativo central -- discrepancia real sin consenso focal, `FECHA_SIN_CORROBORAR` + valor lineal conservado.
- `test_procesar_archivo_fecha_geometrica_coincidente_no_dispara_relectura_focal`: control de no-regresión, caso A.
- `test_procesar_archivo_fecha_no_corrige_si_bloques_no_se_cargaron_por_otro_campo`: cubre explícitamente el alcance acotado -- preserva el invariante de los 4 tests que motivaron la restricción.
- Los 4 tests preexistentes que fallaron en la primera iteración (antes de acotar el alcance) -- confirmados verdes sin ninguna modificación de sus aserciones tras el ajuste.

Suite focalizada: `test_procesamiento_masivo.py` + `test_extraer_datos.py` -- 313 passed. Grupo fecha/extracción/procesamiento/consolidación (+ `test_gestor_viajes.py`, `test_reporte_viajes.py`, `test_atlas.py`, `test_ocr.py`, `test_ocr_provider.py`, `test_paddle_runtime.py`, `test_e2e_r1_pipeline_logistico.py`, `test_e2e_r1_1_cierre_pipeline.py`, `test_operacion_real_r1.py`, `test_operacion_real_r1_1.py`, `test_validadores_fecha.py`) -- 517 passed. Suite completa: **1216 passed, 0 failed** (baseline 1210 + 6).

**Validación real en TEMP (464367 + controles `464264`/`464488`/`464494`/`464493`/`464265`, SHA-256 verificado contra el manifiesto, catálogos reales copiados read-only, `--sin-telemetria`):** comparación campo a campo antes/después -- **cero cambios en las 6 guías, incluida `464367`** (`fecha` se mantuvo `06-08-2026`).

**Hallazgo nuevo, significativo, NO relacionado con la lógica de este fix, aislado y caracterizado con precisión (solo lectura, entorno de runtime aislado de PaddleOCR, sin tocar Drive ni el código de producción):** el worker de PaddleOCR (`atlas_core/paddleocr_worker.py`, operación `"focal"`) **falla siempre** para cualquier caja/imagen -- reproducido de forma idéntica en dos guías sin relación (`464367` y `464264`). Causa exacta aislada variante por variante: de las 4 variantes que genera `_recortar_variantes()` ("original", "grises", "ampliada_2x", "ampliada_2x_contraste"), las dos en escala de grises ("grises", "ampliada_2x_contraste") producen un array NumPy de 2 dimensiones (`(H, W)`, sin canal de color) que `PaddleOCR.predict()` no acepta -- `ValueError: not enough values to unpack (expected 3, got 2)`. Como el bucle de variantes dentro del worker no captura errores por variante (sólo el try/except externo, que envuelve todo el comando), la primera variante en escala de grises ("grises", segunda en la lista) hace fallar el comando `"focal"` completo, siempre, con cualquier caja. Confirmado ejecutando `_recortar_variantes` + `ocr.predict()` variante por variante con el intérprete real del runtime aislado (`C:\Users\Jjjc0508\AppData\Local\Atlas\runtime\paddleocr\Scripts\python.exe`): "original" y "ampliada_2x" (RGB, 3 canales) -- OK; "grises" y "ampliada_2x_contraste" (2 canales) -- fallan exactamente con ese error.

**Impacto real de este hallazgo, verificado:** el mecanismo de relectura focal con consenso -- usado hoy por la recuperación de FECHA (bloque "F2", ya publicado) y de NÚMERO DE TRANSPORTE (mismo worker, mismo patrón) -- está **silenciosamente inactivo en producción** con el proveedor activo actual (PaddleOCR). Se degrada de forma segura (el try/except en `procesamiento_masivo.py` evita que rompa el resto del procesamiento; ambos mecanismos ya diseñados para abstenerse ante cualquier excepción del OCR secundario), pero nunca puede recuperar ni corroborar nada. Verificado que esto no ha causado pérdida de datos visible hasta ahora: **0 guías en `operacion/actual` tienen `fecha == "No encontrado"`** -- el extractor lineal ha sido suficiente en el 100% de los casos reales hasta la fecha, así que el disparador `"No encontrado"` de la recuperación nunca se había ejercitado de verdad con OCR real en producción.

**Por qué no se corrigió aquí:** es un bug de infraestructura separado, de mayor alcance que el objetivo único de este bloque (afecta también la recuperación ya publicada de fecha/transporte ausentes, no sólo la corroboración nueva) -- corregirlo aquí habría mezclado dos hallazgos distintos, exactamente lo que este bloque de auditoría pidió evitar.

**Fix implementado: SÍ** (código + 10 tests, todos verdes). **Validado de extremo a extremo con OCR real: NO** -- bloqueado por el hallazgo del worker, no por un defecto en la lógica del fix (que se comportó exactamente como está diseñado: al fallar la relectura focal, se abstiene y conserva el valor lineal, sin corromper nada).

**Drive:** no modificado -- toda la validación fue lectura (imágenes vía TEMP con SHA-256 verificado, catálogos, y el diagnóstico aislado del worker en su propio runtime, también sin escribir nada). `PREDICCION_CONGELADA.sha256` -- `OK`. `mtime` de `operacion/actual/analisis_completo_guias.csv` sin cambios. Todas las carpetas TEMP eliminadas al terminar.

**Git:** Motor con `atlas_core/procesamiento_masivo.py` y `tests/test_procesamiento_masivo.py` modificados. Sin commit, sin push de este bloque. Desktop sin cambios, HEAD `fba95ac`.

**Cliente `464265`:** cerrado sin fix, no reabierto.

**Pendientes explícitos, sin iniciar:** decisión de Javier sobre publicar este fix ya (correcto y seguro, inactivo hasta que se corrija el worker) o priorizar primero el bug del worker de PaddleOCR (mayor impacto, desbloquea también fecha/transporte "No encontrado" ya publicados); relectura focal de RUT para cliente `464265` (FIX_B, registrado); demás hallazgos del lote de 15.

**Estado: DIAGNÓSTICO DE CORROBORACIÓN DE FECHA COMPLETADO -- REQUIERE DECISIÓN.**

## 2026-08-18 — P1: reparación de la relectura focal de PaddleOCR + validación real de la corroboración de fecha `464367`

**Checkpoint verificado antes de tocar código:** Motor HEAD `b343a41`, local=remoto, working tree exclusivamente con `atlas_core/procesamiento_masivo.py`, `tests/test_procesamiento_masivo.py` y tres bitácoras (fix funcional de corroboración de fecha, todavía sin publicar) -- confirmado con `git status`/`git diff --check`, nada ajeno. Desktop HEAD `fba95ac`, working tree limpio. No se descartó el trabajo pendiente.

### 1. Reproducción aislada del bug, variante por variante

Reproducido con el intérprete real del runtime aislado (`C:\Users\Jjjc0508\AppData\Local\Atlas\runtime\paddleocr\Scripts\python.exe`), replicando exactamente `_recortar_variantes()` + el bucle "focal" de `paddleocr_worker.py`, sobre dos imágenes reales sin relación entre sí (`464367`, `464264`):

| Variante | shape | ndim | modo PIL | `PaddleOCR.predict()` |
|---|---|---|---|---|
| `original` | (25, 82, 3) | 3 | RGB | ACEPTADA |
| `grises` | (25, 82) | 2 | L | **RECHAZADA**: `ValueError: not enough values to unpack (expected 3, got 2)` |
| `ampliada_2x` | (50, 164, 3) | 3 | RGB | ACEPTADA |
| `ampliada_2x_contraste` | (50, 164) | 2 | L | **RECHAZADA**: mismo error |

Hipótesis confirmada exactamente: las dos variantes en escala de grises llegan como array 2D (sin canal de color) a `predict()`, que exige 3 dimensiones. Como el bucle de variantes dentro del worker no captura errores por variante individual (sólo el try/except externo, que envuelve el comando completo), la primera variante en escala de grises ("grises", segunda de la lista fija) hace fallar el comando `"focal"` **completo, siempre**, con cualquier caja -- confirmado en dos imágenes sin relación.

### 2. Auditoría exhaustiva de call-sites (`grep` completo, sin resultados fuera de los ya conocidos)

Todos enrutados a través del mismo closure `_leer_focal()` (`procesamiento_masivo.py:817`) → `proveedor.leer_focal()` → (PaddleOCR) worker `"focal"` / (EasyOCR) `_leer_region_focal()` (`atlas_core/ocr.py:107`, confirmado **no afectado** -- `EasyOCR.readtext()` acepta arrays 2D directamente, sin necesitar canal de color):

| Capacidad | Línea | Categoría | Estado antes del fix |
|---|---|---|---|
| Recuperación de número de transporte ausente | `procesamiento_masivo.py:894-912` | A -- publicada y activa en código | B -- nunca alcanzada con éxito en producción real (0 guías reales necesitaron esto hasta ahora, pero el mecanismo en sí ya estaba roto) |
| Recuperación de fecha ausente ("No encontrado", bloque "F2") | `procesamiento_masivo.py:1209-1226` | A -- publicada y activa en código | B -- misma situación (0 guías reales con fecha ausente hasta ahora) |
| Corroboración de fecha lineal ya presente | `procesamiento_masivo.py:1295-1345` (bloque anterior, sin publicar) | C -- capacidad nueva, todavía no publicada | Bloqueada por el mismo bug, confirmado en el bloque anterior con `464367` |

No se encontró ningún otro call-site de `"focal"`/`leer_focal`/`_leer_region_focal` en todo el repo fuera de `atlas_core/ocr.py`, `atlas_core/ocr_provider.py`, `atlas_core/procesamiento_masivo.py` y `atlas_core/paddleocr_worker.py`.

### 3. Fix mínimo, dentro de la infraestructura OCR, sin heurísticas nuevas

Verificado antes de implementar (mismo runtime aislado) que convertir la variante a RGB (`variante.convert("RGB")`, PIL) o replicar el canal manualmente con NumPy (`np.stack([arr]*3, axis=-1)`) producen **el mismo array exacto** (`np.array_equal` -- confirmado) y ambos son aceptados por `predict()`. Se eligió `.convert("RGB")` por ser la opción más simple, usando únicamente Pillow (ya importado en el worker) sin agregar NumPy manual ni una dependencia nueva (se descartó OpenCV/`cv2`, no usado hoy en el worker).

**Cambios en `atlas_core/paddleocr_worker.py`:**
- Nueva función `_a_array_rgb(variante, np)`: `np.asarray(variante.convert("RGB"))` -- no-op visual para variantes ya en RGB (`R=G=B` replicado para las que eran escala de grises, verificado).
- Nueva función `_ejecutar_focal(ocr, ruta, caja, Image, ImageEnhance, ImageOps, np)`: extrae la rama `"focal"` de `main()` a una función independiente (dependencia inyectada, no importa nada a nivel de módulo) -- permite probarla con un doble de `ocr` sin necesitar PaddleOCR real, sin cambiar el protocolo JSON/IPC del worker (mismo formato `{"recorte": [...], "lecturas": [...]}`, mismo manejo de excepciones vía el try/except ya existente en `main()`).
- `main()` ahora sólo llama `_ejecutar_focal(...)` en la rama `"focal"` -- sin otro cambio de comportamiento.

### 4. Tests del worker (`tests/test_paddleocr_worker.py`, archivo nuevo, sin cobertura previa)

El módulo se importa directamente en el entorno principal -- sus imports de `paddleocr` están diferidos dentro de `_cargar_dependencias()` (nunca a nivel de módulo) y `Image`/`ImageEnhance`/`ImageOps`/`np` se inyectan como parámetros, así que Pillow/NumPy reales (ya dependencias del entorno principal) bastan para probar la lógica sin el runtime aislado:

- `test_a_array_rgb_convierte_grayscale_2d_a_3_canales`, `test_a_array_rgb_grayscale_replica_canal_r_g_b_identicos`, `test_a_array_rgb_no_altera_variante_ya_rgb`: la normalización en sí.
- `test_recortar_variantes_grises_y_contraste_son_2d_antes_de_normalizar`: confirma la precondición exacta del bug real (dos de las cuatro variantes SÍ son 2D antes de normalizar).
- `test_recortar_variantes_caja_invalida_lanza_value_error`: preserva la validación ya existente, sin tocarla.
- `test_ejecutar_focal_todas_las_variantes_llegan_con_canal_de_color`: **regresión central** -- con un doble de OCR configurado para fallar exactamente como PaddleOCR real ante un array 2D, confirma que las 4 llamadas a `predict()` reciben siempre `ndim == 3`. Verificado deliberadamente que este test SÍ habría fallado contra el código original (se generó una copia temporal con el bug reintroducido, se ejecutó fuera de la suite, se confirmó el mismo `ValueError` real, y se eliminó la copia sin dejar rastro).
- `test_ejecutar_focal_preserva_protocolo_de_resultado`: el formato de `resultado` no cambia.
- `test_ejecutar_focal_propaga_excepcion_real_de_ocr_sin_convertirla_en_exito`: un fallo genuino de OCR (no relacionado con canales) se sigue propagando -- nunca se convierte en un resultado silenciosamente exitoso.
- `test_worker_module_importable_sin_paddleocr_instalado`: confirma que la separación de entorno aislado sigue intacta.

Suite focalizada: `test_paddleocr_worker.py` + `test_ocr.py` + `test_ocr_provider.py` + `test_paddle_runtime.py` + `test_procesamiento_masivo.py` -- 211 passed. Grupo extracción/consolidación (`test_extraer_datos.py`, `test_gestor_viajes.py`, `test_reporte_viajes.py`, `test_atlas.py`, `test_e2e_r1_pipeline_logistico.py`, `test_e2e_r1_1_cierre_pipeline.py`) -- 272 passed. **Suite completa: 1225 passed, 0 failed** (baseline 1216 + 9).

### 5. Validación real con PaddleOCR (no simulada) -- worker focal funciona: SÍ

Ejecutado directamente contra el proveedor PaddleOCR real (`crear_proveedor_ocr("paddleocr")`), sobre las imágenes canónicas reales (SHA-256 verificado contra el manifiesto del lote), en TEMP:

- `proveedor.leer_focal(ruta_464367, caja_fecha_emision, allowlist=ALLOWLIST_FECHA)` → **ya no falla** -- devuelve 4 lecturas reales: `original` "04-08-2026" (conf. 0.9245), `grises` "04-08-2024" (conf. 0.9217, año distinto -- ruido real de OCR en esa variante específica), `ampliada_2x` "04-08-2026" (conf. 0.8211), `ampliada_2x_contraste` "04 08-2026" (conf. 0.8556, espacio en vez de guion -- no parseable por `extraer_fecha`, descartado limpiamente).
- `proveedor.leer_focal(ruta_464264, caja_transporte, allowlist=ALLOWLIST_TRANSPORTE)` → tampoco falla -- confirma que el fix generaliza al call-site de número de transporte, con datos reales.

### 6. `464367` con OCR real de extremo a extremo

Reprocesado en TEMP (mismo CLI de producción, `--sin-telemetria`, catálogos reales copiados read-only):

- **Antes** (worker roto, corroboración presente pero bloqueada): `fecha = "06-08-2026"`.
- **Después** (worker reparado): `fecha = "04-08-2026"`.
- **Fuente de la corrección:** candidato geométrico anclado inequívocamente a FECHA DE EMISIÓN (`_extraer_fecha_geometrico`, conf. 0.935) + relectura focal real (paso 5) + consenso: dos lecturas concordantes en `date(2026, 8, 4)` (`original` 0.9245, `ampliada_2x` 0.8211, ambas ≥ `CONFIANZA_MINIMA_FECHA_FOCAL`); la lectura `"grises"` (`2024`, año distinto) **no** contamina el consenso porque queda sola en su propio grupo, sin alcanzar el mínimo de 2 votos -- exactamente el diseño ya existente, sin ninguna concesión.
- **Ground truth:** `04-08-2026` (confirmado visualmente contra la imagen en el bloque de diagnóstico anterior).
- `motivos_revision_documento` de `464367` **no** incluye `FECHA_SIN_CORROBORAR` (consenso limpio, sin ambigüedad) -- `metodos_recuperacion_documento` gana `FOCAL`.

### 7. Controles reales, aislando el efecto de este bloque específico

Comparación con `git stash` temporal de sólo `atlas_core/paddleocr_worker.py` (el fix de corroboración del bloque anterior se mantuvo aplicado en ambas corridas, para aislar exclusivamente el efecto del fix del worker): reprocesadas `464367`, `464264`, `464265`, `464488`, `464493`, `464494` -- comparación de las 49 columnas.

- **`464367`:** único cambio -- `fecha` (`06-08-2026` → `04-08-2026`) y `metodos_recuperacion_documento` (gana `FOCAL`, aditivo).
- **`464264`, `464488`, `464493`, `464494`:** **cero cambios en cualquier campo** -- no hay discrepancia lineal/geométrico en ninguna, así que la corroboración correctamente no interviene (número de transporte tampoco regresa en ninguna).
- **`464265`:** **cero cambios** -- su propia fecha equivocada (`05-08-2024`, diagnosticada en un bloque anterior) no tiene discrepancia entre lineal y geométrico (ambos leen la misma mancha física, coinciden en el mismo valor erróneo) -- la corroboración no tiene nada que corregir ahí, comportamiento correcto y ya esperado.

### 8. Capacidades focales preexistentes -- validadas con caso real/fixture extremo a extremo, no sólo con tests unitarios

- **Fecha ausente:** reconstruido el disparador real "No encontrado" sobre la imagen real de `464367` (geometría + relectura focal + consenso, exactamente el código de producción, sin mocks para esas tres etapas) -- alcanza el mismo consenso limpio en `04-08-2026`. Antes del fix del worker, este mismo camino habría fallado en la llamada a `leer_focal` (confirmado en el bloque anterior).
- **Número de transporte ausente:** llamada real `proveedor.leer_focal(...)` con `ALLOWLIST_TRANSPORTE` sobre `464264`/`464367` -- ya no falla, devuelve lecturas reales (aunque en `464367` el candidato geométrico de transporte resultó ser un número de colada, no el transporte real -- limitación separada y preexistente del extractor geométrico de transporte, **no** de la relectura focal en sí, fuera de alcance de este bloque).

**Fix implementado: SÍ, en dos partes** -- el fix del worker (este bloque) y la corroboración de fecha (bloque anterior, ahora desbloqueada). **Validado de extremo a extremo con OCR real: SÍ**, incluidas las dos capacidades ya publicadas que dependían del mismo mecanismo.

**Drive:** no modificado -- toda la validación fue lectura (imágenes vía TEMP con SHA-256 verificado, catálogos, ejecución del worker en su propio runtime aislado, todo sin escribir nada). `PREDICCION_CONGELADA.sha256` -- `OK`. `mtime` de `operacion/actual/analisis_completo_guias.csv` sin cambios. Todas las carpetas TEMP eliminadas al terminar, incluida la copia temporal con el bug reintroducido usada sólo para confirmar la regresión.

**Git:** Motor con `atlas_core/paddleocr_worker.py` (nuevo), `atlas_core/procesamiento_masivo.py` y `tests/test_procesamiento_masivo.py` (bloque anterior), `tests/test_paddleocr_worker.py` (nuevo), más estas tres bitácoras. **Sin commit, sin push -- Javier pidió revisar el resultado antes de publicar.** Desktop sin cambios, HEAD `fba95ac`.

**Temas de continuidad ya registrados en bloques anteriores, mantenidos, no iniciados aquí:** Incidencias Documentales genéricas; patente documental vs. vehículo canónico; sugerencia chofer↔vehículo sin autocorrección; transportista documental incorrecto (caso MBT ya visto); Analítica/IA; kilometraje operacional obligatorio; **planta de origen + rutas + kilómetros, próximo frente operacional identificado, no iniciado**.

**Estado: P1 RELECTURA FOCAL REPARADO + FECHA 464367 VALIDADA -- LISTO PARA REVISIÓN CON JAVIER.**

## 2026-08-18 — Diagnóstico READ-ONLY: planta de origen / rutas / kilómetros

**Publicación previa (FASE A de este mismo bloque):** commit `3929174` ("fix: restaurar relectura focal y corroborar fecha de emision") -- 7 archivos exactos (worker + corroboración de fecha + tests + 3 bitácoras). Push sin force: `b343a41..3929174`. Post-push: local `3929174` == remoto `3929174`, working tree limpio. Desktop verificado sin tocar: HEAD `fba95ac`, working tree limpio.

**FASE B, checkpoint verificado antes de empezar:** Motor HEAD `3929174`, local=remoto, working tree limpio. Bloque 100% READ-ONLY: ningún archivo de código tocado, ninguna escritura en Drive, sin llamadas a ORS/Onelogis (todo el análisis usa datos ya calculados y persistidos, sin gastar cuota).

### 1. Semántica actual de "planta de origen" -- auditada en el código real, sin asumir que todos los conceptos comparten fuente

Confirmado que hay **tres fuentes distintas**, con jerarquía de confianza explícita en el propio código:

1. **Origen documental** (`atlas_core/rutas/origen_documental.py::resolver_origen_documental`): tokeniza el encabezado del emisor (antes de la lista de sucursales) y matchea contra el catálogo de plantas confirmadas -- **causa raíz ya documentada en el bloque "OPERACIÓN REAL R1" (2026-08-12)**: el encabezado de AZA imprime siempre la misma planta matriz ("CASA MATRIZ PLANTA RENCA"), sin importar la planta real de despacho -- por diseño, este método resuelve casi siempre "AZA RENCA", nunca genuinamente "AZA COLINA". Es un **fallback legítimo únicamente cuando no hay evidencia GPS**, nunca una fuente confiable por sí sola.
2. **Origen por GPS/telemetría** (`atlas_core/telemetria/`, integración real con Onelogis desde los bloques TELEMETRÍA T1/T2/T3 y OPERACIÓN REAL R1/R1.1, 2026-08-12): reúne los trips reales del vehículo ese día, encadena los coherentes en tiempo/espacio, detecta detenciones/estadías reales, y confirma la planta sólo si una geocerca (radio 1.5 km, `atlas_core/rutas/geocerca.py`) la identifica sin ambigüedad. Fuente de mayor confianza -- cuando corre y confirma, **siempre gana sobre el documento** (`origen_determinado_por="TELEMETRIA_GPS"`), incluso si "coincide" con lo que ya decía el documento.
3. **Planta canónica/maestra** (`atlas_core/catalogo_plantas.py`, `plantas.json`): registro confirmado con coordenadas -- ambas fuentes anteriores sólo pueden devolver una planta que ya exista ahí como `CONFIRMADA`/`ACTIVA`; ninguna crea una planta nueva.

**Persistencia y propagación (confirmada leyendo el código, no asumida):** documento (`analisis_completo_guias.csv`, columnas `planta_origen_id`/`planta_origen_nombre`/`origen_determinado_por`/`evidencia_origen`) → consolidación por viaje (`atlas_core/gestor_viajes.py::Viaje`, propiedad `planta_origen_nombre` vía `_campo_ruta_consolidado`, mismo criterio "coincide en todos los documentos del viaje o vacío" que el resto de campos de ruta) → `viajes.csv` (mismas columnas) → Desktop (`atlas_viajes.html`, línea 1055: `planta_origen: f.planta_origen_nombre || f.planta_origen`, línea 1174-1179: `valorPlantaOrigen()`, muestra el valor si existe o `"No disponible"` si no).

**Nota histórica importante:** `docs/DISEÑO_RUTAS_ATLAS.md` y `docs/MODULO_RUTAS_ATLAS.md` describen una fase muy anterior del módulo ("no se integra con OCR, extractor, procesamiento masivo, viajes ni reportes", "la CLI no habilita OpenRouteService real") -- **desactualizados respecto al código real actual**, que sí integra todo esto de forma automática desde los bloques RUTAS R1 (11-08) hasta TELEMETRÍA T3 (12-08). No se corrigieron esos documentos en este bloque (fuera de alcance, sólo lectura).

### 2. Ground truth real -- 43 documentos, 38 viajes (`operacion/actual`, reporte vigente `reporte_promocion_lote15_20260818_153512`, verificado contra `estado_operacion.json`)

**A nivel documento (43 filas):**

| Campo | Valores | Conteo |
|---|---|---|
| `planta_origen_nombre` | AZA RENCA / AZA COLINA / vacío | 25 / 13 / 5 |
| `origen_determinado_por` | DOCUMENTO / TELEMETRIA_GPS / vacío | 25 / 13 / 5 |
| `estado_telemetria` | vacío (nunca conectado) / SELECCIONADO / VEHICULO_NO_ENCONTRADO / SIN_HISTORICO | 20 / 17 / 4 / 2 |
| `distancia_km` presente | sí / no | 17 / 26 |

**Cruce clave:** de los 25 documentos con `origen_determinado_por=DOCUMENTO` (el método menos confiable), **19 tienen `estado_telemetria` vacío** -- telemetría nunca se conectó para esa corrida de procesamiento, así que nunca tuvieron oportunidad real de confirmarse por GPS (no es un fallo, es ausencia de intento). Sólo **6 sí tuvieron un intento real** (`VEHICULO_NO_ENCONTRADO`×4, `SIN_HISTORICO`×2) y cayeron al documento legítimamente, según la regla ya vigente desde R1.1.

**A nivel viaje (38 filas, `viajes.csv`):** 25 `CONFIRMADO` / 13 `REQUIERE_REVISION`. 13 de 38 viajes ya traen `distancia_km` real.

### 3. Caso concreto de origen incorrecto, trazado con precisión

| Transporte | Documento | `planta_origen_nombre` | `origen_determinado_por` | Causa exacta |
|---|---|---|---|---|
| `0000351135` | `464264` | AZA COLINA | TELEMETRIA_GPS | GPS confirma correctamente (bloque OPERACIÓN REAL R1) |
| `0000351135` | `464265` | AZA RENCA | DOCUMENTO | `estado_telemetria=VEHICULO_NO_ENCONTRADO` -- Onelogis no encuentra el vehículo porque `patente_tracto` de este documento (`VP6521`) ya está diagnosticada como incorrecta en un bloque anterior de esta misma auditoría (canónica real `VP8521`, la misma que trae `464264`) |

**Etapa donde falla:** la resolución de origen corre **por documento**, nunca a nivel de viaje completo -- `464265` nunca "hereda" la confirmación GPS ya lograda por `464264`, su propio documento hermano del mismo transporte, aunque ambos representen físicamente el mismo camión saliendo de la misma planta el mismo día.

### 4. Hallazgo de código real: `CONFLICTO_ORIGEN` nunca puede dispararse contra datos reales

`atlas_core/gestor_viajes.py:471`: `origen = str(fila.get("origen", fila.get("planta_origen", "")))` -- busca una columna llamada literalmente `"origen"` o `"planta_origen"`. **Ninguna de las dos existe** en el esquema real de `analisis_completo_guias.csv` (la columna real es `planta_origen_nombre`, leída correctamente y por separado dos líneas más abajo, línea 495, hacia `DocumentoViaje.planta_origen_nombre`). Consecuencia: `DocumentoViaje.origen` es **siempre cadena vacía** para cualquier documento real -- y `MotivoRevision.CONFLICTO_ORIGEN` (línea 568, `(MotivoRevision.CONFLICTO_ORIGEN, [d.origen for d in documentos], _valores_compatibles)`) nunca tiene evidencia con la cual comparar, así que **nunca se dispara**, sin importar cuán distintas sean las plantas reales de dos documentos del mismo viaje. Confirmado con el caso real de la sección 3: el viaje `0000351135` (464264 AZA COLINA vs. 464265 AZA RENCA) no trae `CONFLICTO_ORIGEN` entre sus motivos en `viajes.csv`, a pesar de la discrepancia real y demostrada. La propiedad `Viaje.origenes` (línea 224, misma fuente rota) tiene el mismo problema. **No corregido en este bloque** (FASE B es estrictamente diagnóstico).

### 5. Rutas -- pipeline trazado completo

```
obra_destino (OCR homologado) -> destino canónico (destinos_maestros.json,
  resolver_destino_canonico / resolver_destino_canonico_estructurado)
  -> planta de origen (jerarquía GPS->documento, sección 1)
  -> ServicioRutas.confirmar_y_calcular (atlas_core/rutas/servicio.py)
  -> OpenRouteService real (atlas_core/rutas/openrouteservice.py),
     envuelto en ProveedorRutasConCacheGeocodificacion
     (atlas_core/rutas/cache_geocodificacion.py, Bloque INFRAESTRUCTURA S2)
  -> RepositorioRutas cachea la ruta calculada final (clave lógica
     planta+destino+perfil+proveedor+versión)
  -> resultado_entrega (procesamiento_masivo.py) -> documento -> viaje -> viajes.csv -> Desktop
```

**Onelogis (telemetría) interviene en dos puntos independientes:** (a) confirma/reemplaza la planta de origen (sección 1); (b) si el destino queda con geocodificación ambigua (`MULTIPLES_UBICACIONES_DISPERSAS`), puede reintentarse con el punto final de un recorrido GPS real -- **pero exige un tramo "sustancial"** (`seleccionar_recorrido_operacional`, `distancia_km_trip >= 5.0`, Bloque TELEMETRÍA T2), una condición más estricta que la usada para confirmar origen. Rastreado en código exacto: `atlas_core/telemetria/enriquecimiento.py:120-138` -- `punto_gps_destino` queda `None` si `seleccionar_recorrido_operacional` no encuentra un tramo sustancial encadenado, y sin ese punto, el reintento de desambiguación en `procesamiento_masivo.py:1666-1667` (`if destino_ambiguo and resultado_gps.punto_gps_destino is not None:`) nunca se ejecuta.

### 6. Matriz real de causas -- lote de 15 más reciente (representativo, ya con telemetría/ORS reales conectados en su procesamiento)

| Guía | `estado_ruta` | `motivo_ruta` | Causa real |
|---|---|---|---|
| 464036, 464170, 464488, 464854 | `RUTA_CALCULADA` | -- | Éxito completo (4/15) |
| 464479, 464892 | `ORIGEN_NO_DETERMINADO` | `ORIGEN_GPS_NO_DETERMINADO` / `ORIGEN_GPS_ESTADIA_SIN_PLANTA` | Telemetría corrió, sin evidencia suficiente -- abstención honesta, no un error (2/15) |
| 464265, 464367 | `REQUIERE_REVISION` | `GEOCODIFICACION_DIRECCION_NO_ENCONTRADA` | Ambas guías ya tienen hallazgos propios diagnosticados en bloques anteriores de esta auditoría (cliente/patente/fecha) que probablemente degradan también la dirección de entrega (2/15) |
| 464395, 464491, 464493, 464494, 464511, 464781 | `REQUIERE_REVISION` | `MULTIPLES_UBICACIONES_DISPERSAS(5)` | **Causa dominante (6/15, 40%)** -- geocodificación de `despachar_a_crudo` devuelve 5 candidatos dispersos; telemetría confirma origen correctamente en estos 6 casos, pero el tramo de entrega no alcanza el umbral "sustancial" (≥5 km) necesario para desambiguar -- ver sección 5 |

Verificado explícitamente: **464170 (1.433 km) y 464854 (1.383 km)** no son errores de geocodificación -- ambos destinos están en la Región de Antofagasta (`localidad_entrega=Mejillones`/`Antofagasta`), una distancia interregional real y plausible por carretera desde Santiago. No se calculó ninguna distancia auxiliar en línea recta para verificar esto -- se usó únicamente el campo `localidad_entrega`/`region_entrega` ya persistido.

### 7. ORS -- auditoría sin gastar cuota nueva

Ningún caso observado de `SIN_CREDENCIAL`, `SIN_CONEXION`, `LIMITE_CUOTA` ni `RESPUESTA_INVALIDA` en los datos reales ya persistidos -- **0 fallos propios de ORS observados** en toda la operación vigente. Caché de rutas (`RepositorioRutas`) y caché de geocodificación (`RepositorioCacheGeocodificacion`, Bloque INFRAESTRUCTURA S2) ya activas -- confirmado en código, no se hizo ninguna llamada nueva para verificarlo. El problema real, en los 25/38 viajes sin kilómetros, es siempre **aguas arriba de ORS** (origen o destino sin resolver todavía) -- ORS nunca llega a consultarse para esos casos, no es que falle al consultarse.

### 8. Onelogis -- auditoría sin gastar cuota nueva

**Cobertura real para origen:** 13/38 viajes con `TELEMETRIA_GPS` confirmado; 0 casos de `ORIGEN_GPS_CONFLICTO` en el lote de 15 más reciente. Onelogis SÍ da servicio -- el problema no es su disponibilidad, es que **19/43 documentos nunca lo consultaron en absoluto** (telemetría no conectada en esa corrida). **Cobertura real para destino (desambiguación):** el mismo servicio, misma cuenta, misma cuota -- pero la condición de "tramo sustancial" es más estricta, y en 6/15 guías reales el tramo de entrega disponible en el momento de la consulta no la alcanza. **No se determina aquí** si esto es una limitación real de cobertura de Onelogis (el tramo de entrega todavía no estaba en su base al momento de la consulta) o del umbral/heurística de Atlas (`>=5.0 km`, calibrado en T2 contra un solo caso real) -- requiere su propia investigación dedicada, no resuelta en este bloque de diagnóstico.

### 9. Desktop -- read-only, confirmado sin cambios

`src/atlas_viajes.html`: lee `planta_origen_nombre`/`distancia_km`/`duracion_min`/`estado_ruta` directamente de `viajes.csv`, sin transformación que oculte datos ya presentes. `valorPlantaOrigen()`/`formatearDistancia()`/`formatearMinutos()` (líneas 1158-1179) devuelven el valor real si existe, `"No disponible"` si está vacío -- comportamiento ya confirmado end-to-end con datos reales en el bloque histórico "E2E R2" (2026-08-12). **No se encontró ningún caso de un dato ya calculado por el Motor que Desktop no esté mostrando.**

### 10. Relación con Analítica/IA -- registrado, no implementado

Confirmado explícitamente para continuidad: planta/origen, destino, ruta y kilómetros son infraestructura previa obligatoria para las consultas futuras por chofer/cliente/patente/empresa/planta/ruta/destino (cantidad de viajes, toneladas, kilómetros acumulados, frecuencia de rutas, etc.) -- **no implementado aquí**.

### Clasificación final

- **¿Hay errores de código? SÍ:** `CONFLICTO_ORIGEN` roto (sección 4, columna inexistente, nunca se dispara) -- el único bug de código confirmado con evidencia directa de este bloque.
- **¿Hay problemas de datos/catálogo? SÍ, indirectos:** la patente incorrecta de `464265` (ya diagnosticada en bloque anterior) impide que su origen se confirme por GPS aunque el de su documento hermano sí se confirma; el `obra_destino` corrupto de `464264` (`"COMUNA"`, ya diagnosticado) no impidió su ruta porque la resolución estructurada de destino (`COD DESTINATARIO`) la resolvió por otra vía -- evidencia de que el sistema ya es parcialmente resiliente a ese tipo de error.
- **¿Hay problemas de proveedor? PARCIALMENTE, sin determinar con certeza:** ORS sin fallos propios observados; Onelogis sin fallos duros observados para origen, pero con cobertura insuficiente o umbral demasiado estricto para desambiguación de destino en 6/15 guías reales -- requiere investigación dedicada para separar ambas causas.
- **¿Se necesita otra fuente de routing/km? NO, con la evidencia disponible hoy (Opción A: ORS + Onelogis son suficientes pero la implementación actual está incompleta).** Ningún fallo propio de proveedor observado que justifique un tercer proveedor; los huecos identificados son de integración (consolidación por viaje, umbral de desambiguación, conflicto de origen roto), no de cobertura fundamental de las herramientas ya integradas.

### Próximo bloque recomendado (no iniciado)

Consolidar la resolución de planta de origen a nivel de **viaje completo**, no sólo por documento -- es el hallazgo de mayor impacto con causa más clara y concreta de este diagnóstico (caso real 464264/464265 ya trazado de punta a punta). Reparar `CONFLICTO_ORIGEN` sería parte natural del mismo bloque. Investigar el umbral de "tramo sustancial" para desambiguación de destino queda como un segundo frente, independiente.

**Temas de continuidad ya registrados en bloques anteriores, mantenidos, no iniciados aquí:** Incidencias Documentales genéricas; patente documental vs. vehículo canónico; sugerencia chofer↔vehículo sin autocorrección; transportista documental incorrecto; Analítica/IA; kilometraje operacional obligatorio (reafirmado en este bloque como infraestructura previa necesaria, no opcional).

**Drive:** no modificado -- bloque 100% lectura directa, sin copias a TEMP, sin llamadas a ORS/Onelogis. **Desktop:** no modificado. **Git:** sin commit, sin push de FASE B.

**Estado: DIAGNÓSTICO PLANTA / RUTAS / KILÓMETROS COMPLETADO -- LISTO PARA REVISIÓN CON JAVIER.**

## 2026-08-18 — Bloque ORIGEN DE VIAJE: consolidación jerárquica de planta de origen + reparación de `CONFLICTO_ORIGEN`

**Publicación previa (FASE 0):** commit `51fa504` ("docs: registrar diagnostico de origen rutas y kilometros") -- 3 archivos exactos (tres bitácoras). Push sin force: `3929174..51fa504`. Post-push: local `51fa504` == remoto `51fa504`, working tree limpio. Desktop verificado sin tocar: HEAD `fba95ac`.

**Checkpoint verificado antes de tocar código:** Motor HEAD `51fa504`, local=remoto, working tree limpio.

### 1. Esquema real de origen que llega a `gestor_viajes.py` -- auditado antes de implementar

Confirmado en `DocumentoViaje` (`atlas_core/gestor_viajes.py:146-197`, ya existente, sin cambios de estructura): cada documento ya trae `planta_origen_id`, `planta_origen_nombre`, `origen_determinado_por` (valores reales observados: `"TELEMETRIA_GPS"`, `"DOCUMENTO"`, o vacío), `evidencia_origen` -- **valor y fuente ya están separados en el modelo actual**, no hizo falta ninguna columna nueva (cumple la sección 6 del bloque: "si hoy el modelo ya tiene una fuente equivalente, reutilizarla"). El único campo roto era `DocumentoViaje.origen` (ver sección 2).

### 2. Causa raíz de `CONFLICTO_ORIGEN`, confirmada con precisión

`atlas_core/gestor_viajes.py:471` (antes del fix): `origen = str(fila.get("origen", fila.get("planta_origen", "")))`. Ni `"origen"` ni `"planta_origen"` existen como nombre de columna en `analisis_completo_guias.csv` -- la columna real es `planta_origen_nombre` (leída correctamente, por separado, dos líneas más abajo hacia `DocumentoViaje.planta_origen_nombre`). Consecuencia: `DocumentoViaje.origen` siempre cadena vacía para cualquier documento real, y `MotivoRevision.CONFLICTO_ORIGEN` (línea 568, comparaba `[d.origen for d in documentos]` vía `_valores_compatibles`) nunca tenía evidencia con la cual comparar -- nunca se disparaba. Mismo problema heredado por `Viaje.origenes` (línea 224, lista de auditoría de todas las plantas distintas vistas en los documentos del viaje, también siempre vacía) y por la columna `"origenes"` de `viajes.csv` (`reporte_viajes.py:75,257`).

### 3. Regla de consolidación implementada -- derivada del modelo real, no adoptada literalmente

Nueva función módulo `_resolver_origen_viaje(documentos) -> tuple[str, str, str, str, bool]` (`atlas_core/gestor_viajes.py`, justo después de `DocumentoViaje`):

1. Sólo participan documentos con origen presente (`planta_origen_id` y `planta_origen_nombre` no vacíos, vía `_valor_presente` ya existente) -- un documento sin origen no impide ni degrada la consolidación de los demás (mismo criterio ya usado en `_campo_ruta_consolidado` para el resto de campos de ruta).
2. Nueva tabla `_JERARQUIA_FUENTE_ORIGEN = {"TELEMETRIA_GPS": 0, "ONELOGIS_GPS": 0, "DOCUMENTO": 1}` (`"ONELOGIS_GPS"` incluida por si se conecta en el futuro un proveedor real al puerto de `atlas_core/rutas/enriquecimiento_viaje.py`, hoy sin adaptador real -- ver diagnóstico anterior; cualquier fuente no listada queda al final, nivel 99). Entre los documentos con origen presente, se conserva sólo la fuente de MEJOR nivel (menor número) disponible en ese viaje.
3. Si todos los documentos de esa mejor fuente coinciden en la misma planta -- comparados por `planta_origen_id` normalizado vía `_clave_normalizada` (la misma función NFKD+casefold ya usada para el resto de comparaciones de este archivo, nunca una lista nueva) -- el viaje usa esa planta, con esa fuente y la evidencia (`evidencia_origen`) del documento que la aportó.
4. Si discrepan entre sí (mismo nivel de confianza, plantas distintas), es conflicto real -- nunca se elige una arbitrariamente.
5. Sin ningún documento con origen presente, el viaje queda sin determinar, igual que antes.

**Este único algoritmo cubre los 6 casos pedidos (A-F) sin ramas separadas:** dos GPS coincidentes (A) → mejor nivel único, un solo id; GPS vs. documento discrepante (D) → mejor nivel = sólo GPS, el documento queda excluido del cálculo, sin voto; dos GPS discrepantes (B) → mismo nivel, dos ids → conflicto; sin GPS, documentos coinciden (C) → mejor nivel = DOCUMENTO, un solo id; sin GPS, documentos discrepan (E) → mismo nivel, dos ids → conflicto; ningún origen (F) → sin candidatos, sin conflicto.

**`Viaje.planta_origen_id`/`planta_origen_nombre`/`origen_determinado_por`/`evidencia_origen`** (líneas 401-421): reemplazadas de `self._campo_ruta_consolidado(campo)` (exige coincidencia exacta entre TODOS los documentos, igual que el resto de campos de ruta) a `_resolver_origen_viaje(self.documentos)` -- única diferencia de comportamiento respecto al resto de campos de ruta (destino, distancia, etc., que **no se tocaron**, siguen exigiendo coincidencia exacta sin jerarquía, tal como pidió la sección 10 del bloque: "no tocar destino todavía").

**`campos_conflicto` en `agrupar_viajes()`** (línea ~659): la entrada de `CONFLICTO_ORIGEN` pasa de `([d.origen for d in documentos], _valores_compatibles)` (roto) a `([], lambda _valores, _c=hay_conflicto_origen: not _c)`, con `hay_conflicto_origen` calculado una sola vez por grupo, vía la misma `_resolver_origen_viaje(documentos)` -- sin duplicar la lógica de jerarquía.

**`_documento_desde_fila()`** (línea 471): `origen` corregido para leer la columna real `planta_origen_nombre` -- arregla de raíz tanto `Viaje.origenes` como la columna `"origenes"` de `viajes.csv`, ambas ahora reflejan las plantas realmente vistas en los documentos (lista de auditoría cruda, nunca el origen ya resuelto por jerarquía -- ver test dedicado).

### 4. Caso real 0000351135 -- sin hardcodear guía, transporte ni planta en el código

Ningún literal `464264`/`464265`/`0000351135`/`AZA COLINA`/`AZA RENCA` aparece en `atlas_core/gestor_viajes.py` -- sólo en comentarios explicativos (mismo patrón ya establecido en todo este proyecto) y en la validación real contra datos (sección 6). La regla es completamente general.

### 5. Tests (`tests/test_gestor_viajes.py`)

**2 tests existentes corregidos** (usaban `origen="..."` -- una columna sintética que nunca existió en el esquema real, sólo coincidía por casualidad con la clave literal del diccionario de prueba): `test_origen_opcional_contradictorio_activa_revision`, `test_conflictos_multiples_se_declaran_juntos_sin_perder_evidencia` -- reescritos con `planta_origen_id`/`planta_origen_nombre`/`origen_determinado_por` reales, misma intención de cada test preservada.

**10 tests nuevos**, uno por caso pedido + negativos:
- `test_origen_dos_documentos_gps_misma_planta_sin_conflicto` (CASO 1)
- `test_origen_gps_gana_sobre_documental_distinto_sin_degradarse` (CASO 2, estructuralmente equivalente al caso real, sin hardcodear valores reales)
- `test_origen_dos_gps_distintos_genera_conflicto_real` (CASO 3)
- `test_origen_sin_gps_documentos_coinciden_usa_origen_documental` (CASO 4)
- `test_origen_sin_gps_documentos_discrepan_genera_conflicto` (CASO 5)
- `test_origen_un_documento_sin_origen_otro_con_gps_usa_gps` (CASO 6)
- `test_origen_ningun_documento_resuelve_queda_no_determinado` (CASO 7)
- `test_origen_diferencias_de_formato_en_id_no_crean_conflicto_falso` (negativo: mayúsculas/espacios en el ID no generan conflicto falso)
- `test_origen_no_se_hereda_entre_viajes_distintos` (negativo: aislamiento entre transportes distintos)
- `test_origenes_lista_auditoria_ahora_refleja_las_plantas_reales_vistas` (confirma el arreglo de `Viaje.origenes`/columna `"origenes"`, distinto del origen ya resuelto por jerarquía)

Suite focalizada: `tests/test_gestor_viajes.py` -- 65 passed. Grupo consolidación/rutas/telemetría (`test_reporte_viajes.py`, `test_generar_reporte_viajes_cli.py`, `test_rutas_enriquecimiento_viaje.py`, `test_rutas_modelos.py`, `test_rutas_repositorio.py`, `test_rutas_servicio.py`, `test_operacion_real_r1.py`, `test_operacion_real_r1_1.py`, `test_telemetria_t1/t2/t3.py`) -- 207 passed. **Suite completa: 1235 passed, 0 failed** (baseline 1225 + 10).

### 6. Validación real contra los 38 viajes vigentes (100% lectura, `agrupar_viajes()` real sobre `analisis_completo_guias.csv` ya promovido, sin mocks)

Comparación con `git stash` temporal de sólo `atlas_core/gestor_viajes.py` (aísla exclusivamente el efecto de este fix):

| | Antes | Después |
|---|---|---|
| Viajes con origen resoluble | 32/38 | 33/38 |
| Viajes con `CONFLICTO_ORIGEN` | 0/38 | 0/38 |

**Único viaje que cambia** (matriz before/after completa, sin ocultar nada):

| Transporte | Guías | Origen antes | Fuente antes | Origen después | Fuente después | Motivo |
|---|---|---|---|---|---|---|
| `0000351135` | `464264`, `464265` | `""` (vacío) | `""` | `AZA COLINA` | `TELEMETRIA_GPS` | Antes, dos documentos con planta distinta (uno GPS, otro documento) hacían que la coincidencia exacta exigida por `_campo_ruta_consolidado` fallara y quedara vacío. Ahora, la jerarquía descarta el valor documental (nivel inferior) y usa el único valor de mejor nivel disponible (GPS) -- sin conflicto, porque sólo hay un candidato en el nivel ganador. |

**Cero conflictos nuevos, cero conflictos falsos** -- ningún otro de los 38 viajes cambió de estado, y `CONFLICTO_ORIGEN` sigue en 0 (el único caso real conocido se resuelve por jerarquía, no por conflicto, porque las dos fuentes no son de igual nivel de confianza).

### 7. Impacto en rutas/km -- medido, no asumido

No se recalculó ninguna ruta ni se llamó a ORS/Onelogis. `distancia_km`/`estado_ruta`/`motivo_ruta` a nivel de viaje siguen usando `_campo_ruta_consolidado` sin cambios (fuera de alcance de este bloque, sección 10). El viaje `0000351135` sigue sin kilómetros a nivel de viaje después de este fix -- los documentos `464264`/`464265` ya traían `estado_ruta`/`distancia_km` distintos entre sí ANTES de este bloque (documento por documento, sin relación con el origen), así que la consolidación de ruta seguía exigiendo coincidencia exacta y quedaba vacía, exactamente igual que antes. **Impacto directo en kilómetros de este bloque: 0 viajes adicionales con km.** El valor de este fix es que el viaje `0000351135` ahora tiene, por primera vez, un origen de viaje confiable y auditable -- prerrequisito necesario (no suficiente) para que un futuro bloque de consolidación de ruta/destino pueda intentar recalcularla con esa base.

### 8. Desktop -- verificado sin modificar

`src/atlas_viajes.html` lee `planta_origen_nombre` directamente de `viajes.csv` (columna generada por `reporte_viajes.py` a partir de `Viaje.planta_origen_nombre`, la propiedad corregida en este bloque) -- **no requiere ningún cambio de presentación**: en cuanto el dato real se reprocese (no se hizo en este bloque), Desktop mostrará el origen corregido automáticamente con el código ya existente.

**Drive:** no modificado -- validación 100% contra datos ya promovidos, sin escribir nada, sin llamadas a ORS/Onelogis. **Desktop:** no modificado. **Git:** Motor con `atlas_core/gestor_viajes.py` y `tests/test_gestor_viajes.py` modificados. Sin commit, sin push de este bloque. Desktop sin cambios, HEAD `fba95ac`.

**Próximo paso recomendado (no iniciado, debe confirmarse con evidencia, no asumirse):** investigar el umbral de "tramo sustancial" (`>=5.0 km`) que bloquea la desambiguación de destino por GPS -- causa dominante de kilómetros faltantes ya identificada en el bloque de diagnóstico anterior (6/15 guías del lote más reciente), independiente de este fix de origen.

**Estado: FIX ORIGEN DE VIAJE + CONFLICTO_ORIGEN VALIDADO -- LISTO PARA REVISIÓN CON JAVIER.**

## Bloque ONELOGIS / DESTINO / KM (diagnóstico, sin fix) -- 2026-08-18

**Checkpoint:** `feb5afb` publicado y verificado (local=remoto, working tree limpio) antes de empezar.

**Objetivo:** determinar la causa exacta de `MULTIPLES_UBICACIONES_DISPERSAS` y si el umbral `DISTANCIA_MINIMA_KM_PREDETERMINADA=5.0` de `atlas_core/telemetria/seleccion_recorrido.py` (usado por `seleccionar_recorrido_operacional`, cuyo resultado alimenta `punto_gps_destino` en `atlas_core/telemetria/enriquecimiento.py:134` y de ahí `descartar_candidatos_lejos_de_gps` en `atlas_core/rutas/destino_entrega.py`) es la causa raíz, y si existe una corrección segura.

**Pipeline trazado (código, sin ejecutar red):** `resolver_entrega_documento` (`destino_entrega.py:581`) geocodifica `DESPACHAR A` vía `resolver_destino_entrega` -- si Pelias devuelve >1 candidato y no son "el mismo lugar" (`_candidatos_son_el_mismo_lugar`, margen `MARGEN_MISMO_LUGAR_KM=1.0` o misma localidad+región), motivo=`MULTIPLES_UBICACIONES_DISPERSAS(N)`, sin tocar ORS. Luego, en `procesamiento_masivo.py:1667-1705`, si telemetría está conectada y `resultado_gps.punto_gps_destino` no es `None` (el ÚLTIMO punto del `recorrido_operacional` de T2/`seleccionar_recorrido_operacional`, NO el mismo recorrido usado para origen -- ver docstring de `enriquecimiento.py`, origen y recorrido de entrega se resuelven por separado desde Bloque OPERACIÓN REAL R1), se reintenta con `calcular_ruta_con_planta_conocida(punto_gps_destino=...)`, que descarta candidatos a más de `radio_gps_destino_km=50.0` del punto GPS antes de re-evaluar "mismo lugar".

**Evidencia real usada (sin gastar cuota):**
- `G:\Mi unidad\Atlas\operacion\actual\analisis_completo_guias.csv` (43 docs) y `viajes.csv` del reporte vigente (38 viajes) -- campos ya persistidos de `estado_ruta`/`motivo_ruta`/`estado_telemetria`/`origen_gps`/`distancia_gps_km`/`evidencia_telemetria`.
- `G:\Mi unidad\Atlas\cache\geocodificacion\geocodificacion_cache.json` (31 consultas ya pagadas) -- candidatos reales de Pelias para cada `despachar_a_crudo` ambiguo, releídos con `_candidatos_son_el_mismo_lugar`/`_candidatos_con_soporte_textual` reales del código (sin red).
- `G:\Mi unidad\Atlas\catalogos_privados\telemetria_cache.json` (27 claves patente/fecha, trips ya obtenidos de Onelogis) -- reproducción pura de `seleccionar_recorrido_operacional` contra los trips reales cacheados para 464395/464715/464726/464781, con el umbral actual (5 km) y un umbral hipotético (0.5 km).

**Clasificación de los 17 viajes `MULTIPLES_UBICACIONES_DISPERSAS` (de 25 viajes sin km, 38 totales) por causa verificada:**
1. **7 viajes** (463594, 463630, 464588, 464624, 464631, 464640, 464641/642): `estado_telemetria` vacío en el CSV persistido -- pero el trip histórico SÍ existe en `telemetria_cache.json` (verificado: p. ej. `onelogis|BDFG50|2026-08-11` tiene 17 trips cacheados, pero la fila de 464624 -- misma patente, misma fecha -- no tiene ningún campo de telemetría). Causa: gap de reprocesamiento/orquestación (una corrida más reciente del documento no conectó `servicio_telemetria`, perdiendo en silencio un enriquecimiento que ya se había obtenido antes), no el umbral de 5 km.
2. **2 viajes** (464706, 464740): `estado_telemetria=SIN_HISTORICO` -- Onelogis no tiene ningún trip para esa patente/fecha. Cobertura real ausente, no un umbral.
3. **4 viajes** (464395, 464715, 464726, 464781): origen confirmado por GPS (vía `resolver_planta_origen_gps`, ventana ancha independiente), pero `seleccionar_recorrido_operacional` nunca selecciona un recorrido (`SIN_TRIPS_SUSTANCIALES_TRAS_ANCLA`) -- **verificado con los 9/11/4/17 trips reales cacheados de cada caso: bajar el umbral de 5.0 km a 0.5 km no cambia el resultado**, porque no existe ningún trip con movimiento real (todos <0.5 km) en la ventana de tolerancia (`tolerancia_ancla_min=15 min`) alrededor de la hora de salida documental -- el/los tramo(s) grandes reales del día (13-28 km) ocurren horas ANTES de la hora de salida documentada. La causa no es el umbral de distancia; es que el ancla temporal (`hora_salida` documental) no tiene, ese día, ningún movimiento sustancial cerca en el sentido que la función busca (hacia adelante, con tolerancia de solo 15 min hacia atrás).
4. **4 viajes** (464491, 464493, 464494, 464511): recorrido SÍ seleccionado, `punto_gps_destino` SÍ disponible, la desambiguación por GPS SÍ se reintentó (`distancia_gps_km` poblado) -- y aun así sigue ambiguo. Verificado contra la caché real de geocodificación: en 464494 (`CAMINO LO RUIZ 2901 RENCA`) los 5 candidatos están a un máximo de 1.16 km entre sí (apenas sobre el margen `MARGEN_MISMO_LUGAR_KM=1.0`, caso límite); en 464493 (`AV SAN JOSE...`) los 2 candidatos dentro de RM están a 35+ km entre sí (San Bernardo vs. Chicureo) -- ambos caben dentro de un radio de 50 km de cualquier punto GPS real en Santiago, por lo que ningún GPS a 50 km los distingue. Causa: dispersión real de candidatos dentro de la misma región / radio de descarte GPS demasiado amplio para discriminar dentro de RM -- no el umbral de "tramo sustancial".

**Controles positivos:** no existe en este dataset real ningún caso donde Onelogis haya desempatado exitosamente un destino ambiguo. Los 13 viajes con `RUTA_CALCULADA` se resolvieron porque la geocodificación devolvió un único candidato (o candidatos ya "el mismo lugar") con confianza ≥ `UMBRAL_CONFIANZA_MINIMA=0.5` desde el principio -- GPS nunca fue el factor decisivo.

**ORS:** 0 fallos reales en todo el dataset -- nunca se invoca en ningún caso ambiguo (el bloqueo siempre es anterior, en geocodificación u origen); en los 13 casos donde sí se invocó, `RUTA_CALCULADA` siempre.

**Otras 2 causas de km faltante, no relacionadas con Onelogis (fuera de este análisis pero registradas):** `GEOCODIFICACION_DIRECCION_NO_ENCONTRADA` en 464367 (texto de `despachar_a` con corrupción OCR real, "TACHA 144 TUNGAY DIAGUILLIN"); y el viaje 464698/464699/464700, donde cada documento sí calculó ruta individualmente pero la consolidación a nivel de viaje queda vacía por `CONFLICTO_OBRA_DESTINO`/`CONFLICTO_CLIENTE` entre sus 3 documentos (afecta la consolidación, no la geocodificación).

**Decisión:** NO se implementa ningún fix. La auditoría real demuestra 4 causas raíz distintas detrás del mismo motivo (`MULTIPLES_UBICACIONES_DISPERSAS`), cada una requiriendo una corrección diferente y no relacionada entre sí (gap de reprocesamiento; cobertura Onelogis ausente; ventana temporal del ancla, no el umbral de distancia; radio de descarte GPS demasiado amplio para RM). No existe una única corrección pequeña, segura y generalizable -- se presenta la comparación completa para decisión de Javier, sin tocar código de producción.

**Drive:** no modificado (solo lectura de CSVs/cachés ya existentes). **Desktop:** no modificado. **Git:** sin commit, sin push de este bloque.

**Estado: DIAGNÓSTICO ONELOGIS / DESTINO / KM COMPLETADO -- LISTO PARA REVISIÓN CON JAVIER.**

## Bloque GAP TELEMETRÍA CACHEADA (fix, validado, sin publicar) -- 2026-08-18

**Checkpoint:** commit documental `7ea1a1b` publicado y verificado (local=remoto, working tree limpio) antes de empezar.

**Pipeline trazado (7 casos: 463594, 463630, 464588, 464624, 464631, 464640, 464641/642):** `analizar_guias_masivo.py` construye `servicio_telemetria = ServicioTelemetria(OnelogisProvider(), RepositorioTelemetria(catalogos_privados/telemetria_cache.json))` una vez por corrida y lo pasa a `procesar_carpeta` -> `procesar_archivo`, que llama `enriquecer_documento_con_telemetria` sólo si `servicio_telemetria is not None`. Si un documento puntual se reprocesa MÁS TARDE (p. ej. para validar un fix de otro campo, sin conectar telemetría) y ese reprocesamiento sobrescribe su fila en `analisis_completo_guias.csv`, la fila pierde sus columnas de telemetría -- aunque el trip de esa patente/fecha siga existiendo en `telemetria_cache.json` de una corrida anterior. **Verificado con evidencia real:** para los 7 casos, `RepositorioTelemetria.buscar_viajes("onelogis", <patente>, <fecha>, <fecha>)` contra la caché real SÍ devuelve resultados (p. ej. `BDFG50|2026-08-11` con 17 trips), pero la fila persistida no tenía ningún campo de telemetría poblado. Clasificación (sección 2 del pedido): **caso A** ("cache existe pero el procesamiento [de esa corrida puntual] no la consulta") -- no B/C/D/E/F, no hay evidencia de que se haya consultado y descartado, ni de fallo de matching patente/fecha (la clave calza exacta), ni de reprocesamiento histórico incompleto documentado; simplemente esa corrida puntual no tenía `servicio_telemetria` conectado.

**Mecanismo canónico ya existente en el proyecto, auditado antes de escribir nada nuevo (sección 4 del pedido):** `atlas_core/revalidacion_documental.py` ya resuelve exactamente este tipo de problema para otros dos motivos (`OBRA_DESTINO_SIN_CORROBORAR`, `PATENTE_SIN_HOMOLOGAR`) -- relee filas ya procesadas, corrige sólo lo que corresponde contra el estado vigente de una fuente de verdad (catálogo o, en este caso, caché de telemetría), sin OCR, con escritura atómica bajo `bloqueo_sesion`. Se agregó `revalidar_telemetria_sin_ocr()` a ese mismo módulo, siguiendo el patrón al pie de la letra -- no se creó un pipeline paralelo.

**Solución implementada:**
- `atlas_core/telemetria/proveedor.py`: nuevo `ProveedorTelemetriaSoloCache` (dataclass, protocolo `ProveedorTelemetria` completo) -- cualquier consulta real se resuelve con `EstadoTelemetria.SIN_CONEXION` en memoria, nunca abre una conexión. Garantiza, por construcción y no por disciplina de código, que ni un breadcrumb individual faltante en caché (aunque el resto del día sí esté cacheado) pueda disparar una llamada real a Onelogis -- verificado con test dedicado (`test_breadcrumbs_no_cacheados_nunca_disparan_red_real`).
- `atlas_core/revalidacion_documental.py`: nueva `revalidar_telemetria_sin_ocr(*, ruta_dataset, carpeta_catalogos, proveedor_nombre="onelogis", servicio_telemetria=None)`. Por fila: si `estado_telemetria` ya está poblado, se salta (idempotente). Si no, valida patente/fecha/horas (misma condición de elegibilidad que `procesar_archivo`). Chequea la caché DIRECTAMENTE (`RepositorioTelemetria.buscar_viajes`) antes de intentar nada -- si no hay ninguna entrada, se abstiene sin dejar rastro (nunca persiste un estado sintético como `SIN_CONEXION`, que podría confundirse con un fallo real). Si hay caché, reutiliza `enriquecer_documento_con_telemetria` (sin duplicar la lógica de selección de recorrido/origen) y aplica la MISMA regla de origen ya vigente en `procesamiento_masivo.procesar_archivo` (Fase R1/R1.1: GPS confirmado gana siempre; sin confirmación con telemetría que sí corrió, el origen documental heredado se descarta, nunca se conserva en silencio). **Extensión nueva, no presente en el código original:** si el origen cambia y la fila ya traía `distancia_km` calculado con el origen ANTERIOR, se invalida (`distancia_km`/`duracion_min`/`proveedor_ruta` vacíos, `estado_ruta=REQUIERE_REVISION`, `motivo_ruta=ORIGEN_ACTUALIZADO_PENDIENTE_RECALCULO_RUTA`) en vez de dejar un kilometraje que ya no corresponde -- necesario porque la validación real reveló 9 casos así (ver abajo). Nunca llama a ORS.

**12 tests nuevos** (`tests/test_revalidacion_telemetria_gap.py`), cubriendo los 7 casos pedidos más los 2 adicionales encontrados por la propia auditoría (conflicto GPS descarta origen heredado; invalidación de km obsoleto vs. conservación cuando el origen no cambia). **Suite completa: 1247 passed, 0 failed** (baseline 1235 + 12).

**Validación real en TEMP (copia de los 43 documentos + caché real, sin escribir Drive):**
- **19 documentos recuperaron telemetría** (más que los 7 conocidos -- el gap afectaba también a documentos ya `RUTA_CALCULADA`/`CONFIRMADO`, no sólo a los `MULTIPLES_UBICACIONES_DISPERSAS`): 463594, 463630, 464424, 464522, 464529, 464534, 464535, 464550, 464577, 464588, 464601, 464624, 464631, 464640, 464641, 464642, 464698, 464699, 464700.
- **18/19 quedan con origen `TELEMETRIA_GPS`**; 17 de ellos pasan de `AZA RENCA` (documental, el encabezado matriz -- causa raíz ya conocida) a `AZA COLINA` (real, confirmado por GPS).
- **1/19 (464529) revela que su origen documental nunca debió aceptarse**: GPS corrió sobre datos reales y no confirmó ninguna planta (`ORIGEN_GPS_NO_DETERMINADO`) -- el origen queda correctamente vacío en vez de "AZA RENCA" heredado del documento.
- **Hallazgo no anticipado, con impacto directo en confiabilidad de datos ya publicados:** de los 14 transportes con al menos un documento con `distancia_km` ya calculado, **6 tenían ese km calculado con el origen incorrecto** (0000351956, 0000352376, 0000352537, 0000352552, 0000352568, 0000352584) -- se invalidan correctamente. De esos 6: **4 quedan listos para reintentar ORS de inmediato** (origen ahora coherente + único `despachar_a` ya resuelto antes: 0000351956/464424, 0000352552/464534+535, 0000352568/464577, 0000352584/464550); 1 (0000352537/464529) ahora requiere determinar origen antes de poder intentar ruta; 1 (0000352376/464698-700) sigue bloqueado por `CONFLICTO_CLIENTE`/`CONFLICTO_OBRA_DESTINO` preexistente, no relacionado con este fix. **8 transportes retienen su km intacto** sin cambios (origen ya era correcto o no había caché nueva que aplicar).
- Drive re-verificado sin cambios (mtime/tamaño de `analisis_completo_guias.csv` y `telemetria_cache.json` idénticos al inicio del bloque). TEMP eliminado al terminar.

**Desktop:** no requiere cambios -- lee `planta_origen_nombre`/`distancia_km` directamente de las columnas ya existentes (`src/atlas_viajes.html:1055,1057`).

**Drive:** no modificado. **Git:** working tree con `atlas_core/revalidacion_documental.py`, `atlas_core/telemetria/proveedor.py`, `tests/test_revalidacion_telemetria_gap.py` modificados/nuevos. Sin commit, sin push de este bloque.

**Estado: FIX RE-ENRIQUECIMIENTO TELEMETRÍA VALIDADO -- LISTO PARA REVISIÓN CON JAVIER.**

## Bloque APLICACIÓN REAL — revalidación telemetría en `operacion/actual` -- 2026-08-18

**Checkpoint:** commit funcional `fb370ff` publicado y verificado (local=remoto, working tree limpio) antes de empezar.

**Snapshot ANTES (lectura, sin modificar nada):** 43 documentos, 23 con telemetría / 20 sin, `origen_determinado_por` = {DOCUMENTO: 25, vacío: 5, TELEMETRIA_GPS: 13}. Reporte vigente (`reporte_promocion_lote15_20260818_153512/viajes.csv`): 38 viajes, 13 con `distancia_km`, `origen_determinado_por` = {DOCUMENTO: 20, vacío: 6, TELEMETRIA_GPS: 12}. Los 19 documentos previstos y los 6 transportes con km potencialmente inválido confirmados presentes con el estado exacto esperado (ver detalle en el turno de conversación; omitido aquí por extensión).

**Backup:** `G:\Mi unidad\Atlas\respaldos\REVALIDACION_TELEMETRIA_ROLLBACK_PRE_APLICACION_20260818_185739\` -- contiene `operacion_actual/analisis_completo_guias.csv` y `operacion_actual/estado_operacion.json` (únicos dos archivos de `operacion/actual` que esta operación podía modificar: `analisis_completo_guias.csv` in-place, `estado_operacion.json` reescrito por el puntero de reporte vigente; `decisiones_pendientes.json`/`decisiones_aplicadas.json`/catálogos no son tocados por `revalidar_telemetria_sin_ocr` ni por `generar_reporte_viajes`, no se incluyeron). Verificado SHA-256 byte a byte antes de escribir (idéntico al original en ambos archivos). `MANIFIESTO_SHA256.txt` incluido. Ningún backup previo eliminado.

**Dry-run final:** copia TEMP exacta del `analisis_completo_guias.csv` + `telemetria_cache.json` + `plantas.json` vigentes, `revalidar_telemetria_sin_ocr()` ejecutada sobre la copia. Resultado: 19 guías actualizadas (lista idéntica a la prevista), 18 mejoran origen a `TELEMETRIA_GPS`, 17 `AZA RENCA`→`AZA COLINA`, 6 transportes con `distancia_km` invalidado (`0000351956, 0000352376, 0000352537, 0000352552, 0000352568, 0000352584`). Coincidencia exacta con la validación TEMP del bloque anterior -- sin diferencias que explicar, se procedió a la aplicación real.

**Aplicación real:** `revalidar_telemetria_sin_ocr(ruta_dataset=G:\Mi unidad\Atlas\operacion\actual\analisis_completo_guias.csv, carpeta_catalogos=G:\Mi unidad\Atlas\catalogos_privados)` -- usa `ProveedorTelemetriaSoloCache` internamente (nunca llamado con proveedor real): **0 llamadas a Onelogis, 0 llamadas a ORS**. Resultado: 43 filas totales, 19 guías actualizadas, exactamente igual al dry-run.

**Regeneración del reporte (mecanismo canónico, sin ORS):** `generar_reporte_viajes(dataset, reportes/reporte_revalidacion_20260818_225946_039407, carpeta_catalogos=catalogos_privados)` (mismo patrón usado por `revalidar_y_regenerar_reporte` para las otras dos revalidaciones ya existentes -- sin `calculador_rutas`, columnas de ruta quedan tal como las dejó el CSV, ninguna llamada de red). `escribir_estado_operacion()` actualiza `operacion/actual/estado_operacion.json` para apuntar `reporte_vigente` al nuevo reporte -- mismo mecanismo atómico ya usado en el resto del sistema.

**Integridad documental (comparación antes/después, 43 filas):** 0 violaciones en `numero_guia, numero_transporte, fecha, chofer, rut_chofer, cliente, obra_destino, patente_tracto, patente_rampla, descripcion_material, tipo_carga, peso_kg, hora_entrada_aza, hora_salida_aza, permanencia_minutos, despachar_a_crudo, direccion_entrega, localidad_entrega, region_entrega`. Catálogos (`vehiculos.json, plantas.json, clientes.json, obras_destinos.json, destinos_maestros.json, empresas.json`) y decisiones (`decisiones_aplicadas.json, decisiones_pendientes.json`) verificados por `mtime`: ninguno tocado por este bloque.

**Orígenes:** 17 documentos `DOCUMENTO(AZA RENCA)` → `TELEMETRIA_GPS(AZA COLINA)`: 463594, 463630, 464424, 464534, 464535, 464550, 464577, 464588, 464601, 464624, 464631, 464640, 464641, 464642, 464698, 464699, 464700. 1 documento (464529) queda sin determinar (antes "AZA RENCA" heredado sin corroborar; GPS corrió sobre datos reales y no confirmó ninguna planta). 0 conflictos `ORIGEN_GPS_CONFLICTO` nuevos -- el único visto (464730) ya existía con telemetría conectada antes de este bloque, confirmado comparando contra el backup.

**Kilómetros -- tabla de invalidación:**

| Transporte | Origen anterior | Origen corregido | Km anterior | Nuevo estado |
|---|---|---|---|---|
| 0000351956 | AZA RENCA | AZA COLINA | 16.7276 | REQUIERE_REVISION / ORIGEN_ACTUALIZADO_PENDIENTE_RECALCULO_RUTA |
| 0000352376 | AZA RENCA | AZA COLINA | 361.3855 / 505.0767 (por doc) | REQUIERE_REVISION / ORIGEN_ACTUALIZADO_PENDIENTE_RECALCULO_RUTA |
| 0000352537 | AZA RENCA | (sin determinar) | 16.7276 | REQUIERE_REVISION / ORIGEN_ACTUALIZADO_PENDIENTE_RECALCULO_RUTA |
| 0000352552 | AZA RENCA | AZA COLINA | 7.8476 | REQUIERE_REVISION / ORIGEN_ACTUALIZADO_PENDIENTE_RECALCULO_RUTA |
| 0000352568 | AZA RENCA | AZA COLINA | 7.4307 | REQUIERE_REVISION / ORIGEN_ACTUALIZADO_PENDIENTE_RECALCULO_RUTA |
| 0000352584 | AZA RENCA | AZA COLINA | 13.96 | REQUIERE_REVISION / ORIGEN_ACTUALIZADO_PENDIENTE_RECALCULO_RUTA |

Ningún km nuevo fue calculado (0 llamadas ORS); nunca se reemplazó por distancia en línea recta.

**Viajes `LISTOS_PARA_RECALCULO_RUTA`** (calculado contra el reporte real regenerado, no hardcodeado -- origen coherente, `despachar_a` único ya resuelto, sin `CONFLICTO_*` bloqueante, sin km): **0000351956, 0000352552, 0000352568, 0000352584** (4 de los 6 invalidados; 0000352537 excluido por origen sin determinar, 0000352376 excluido por `CONFLICTO_CLIENTE`/`CONFLICTO_OBRA_DESTINO` preexistente y no relacionado).

**Cobertura km del reporte regenerado:** 8 de 38 viajes con `distancia_km` (antes 13; 5 de los 6 transportes invalidados restaban un km viaje-level -- el sexto, 0000352376, ya no consolidaba km antes por el conflicto documental preexistente).

**Desktop:** código no modificado; verificado que `formatearDistancia()` (`src/atlas_viajes.html:1163`) ya renderiza "No disponible" para `distancia_km` vacío -- compatible sin cambios en cuanto se abra apuntando al reporte vigente actualizado.

**Drive:** modificado -- exclusivamente `operacion/actual/analisis_completo_guias.csv` (in-place), `operacion/actual/estado_operacion.json` (puntero), y el nuevo directorio `reportes/reporte_revalidacion_20260818_225946_039407/` (no sobrescribe ningún reporte previo). **Git:** working tree con únicamente las tres bitácoras -- el fix funcional ya estaba publicado antes de esta aplicación.

**Estado: REVALIDACIÓN TELEMETRÍA APLICADA Y PUBLICADA -- LISTO PARA RECÁLCULO CONTROLADO DE RUTAS/KM.**

## Bloque RECÁLCULO CONTROLADO DE RUTAS/KM -- 2026-08-18

**Checkpoint:** Motor `e4a354d` (local=remoto, 0/0, limpio), Desktop `fba95ac` (limpio) -- ambos verificados antes de empezar.

**Candidatos reales (determinados programáticamente contra `analisis_completo_guias.csv` + `viajes.csv` vigentes, no hardcodeados):** origen resoluble (`planta_origen_id` + `origen_determinado_por` presentes) AND destino resoluble (`despachar_a_crudo` presente, `estado_entrega=RESUELTO`, `direccion_entrega` presente) AND sin conflicto (ni `CONFLICTO_*` en `motivos_revision_documento`, ni `ORIGEN_GPS_CONFLICTO`, ni `CONFLICTO_*` en `motivos_revision` a nivel viaje) AND `distancia_km` vacío. Primera pasada a nivel documento dio 8 filas/5 transportes (incluía 464698/699/700, transporte `0000352376`); al cruzar contra el conflicto a NIVEL VIAJE (`CONFLICTO_CLIENTE`/`CONFLICTO_OBRA_DESTINO`, invisible en el CSV por documento) se excluyó correctamente, quedando **4 transportes / 5 documentos**: 0000351956 (464424), 0000352552 (464534, 464535), 0000352568 (464577), 0000352584 (464550) -- coincide exacto con la expectativa del bloque anterior.

**Snapshot previo (lectura, sin escribir):** los 5 documentos candidatos tenían `distancia_km` vacío, `estado_ruta=REQUIERE_REVISION`, `motivo_ruta=ORIGEN_ACTUALIZADO_PENDIENTE_RECALCULO_RUTA`, origen `AZA COLINA`/`TELEMETRIA_GPS` (coordenadas de catálogo: -33.137558, -70.665977), destino ya geocodificado y cacheado (`estado_entrega=RESUELTO`) pero sin coordenadas persistidas en el esquema del CSV (el esquema documental nunca guarda lat/lon de entrega, sólo la etiqueta resuelta) -- se recuperaron desde `cache/geocodificacion/geocodificacion_cache.json` vía `RepositorioCacheGeocodificacion.buscar()` real, confirmando 1-2 candidatos por dirección, todos ya "el mismo lugar" (`_candidatos_son_el_mismo_lugar`), sin necesidad de nueva geocodificación.

**Dry-run (ORS real, autorizado explícitamente sólo para estos 4 pares):** `calcular_ruta_con_planta_conocida(planta=AZA COLINA, despachar_a_crudo=<texto>, proveedor_rutas=ProveedorRutasConCacheGeocodificacion(OpenRouteService(pais="CL"), RepositorioCacheGeocodificacion(cache real)))` -- mismo mecanismo canónico que usa `procesamiento_masivo.py` para recalcular ruta tras un cambio de origen (Fase I). 4 llamadas reales a ORS (una por par único origen/destino; 464534 y 464535 comparten destino, deduplicado antes de llamar). Resultado: las 4, `RUTA_CALCULADA`, `distancia_km > 0`, coherentes con Santiago metropolitano (13-31 km). Verificación de sanidad: AZA COLINA→VISTA CLARA 2351 CERRILLOS dio 30.7719 km, EXACTAMENTE el mismo valor ya persistido para la guía 464763 (misma ruta real, calculada independientemente antes) -- ninguna de las reglas de seguridad de la sección 5 se violó (origen canónico CONFIRMADA/ACTIVA, destino no ambiguo, sin conflicto, coordenadas presentes, respuesta ORS válida, distancia > 0, par origen/destino correspondiente verificado).

**Backup:** `G:\Mi unidad\Atlas\respaldos\RECALCULO_RUTAS_KM_ROLLBACK_PRE_APLICACION_20260818_190921\` (`analisis_completo_guias.csv` + `estado_operacion.json`, únicos archivos que esta operación podía modificar), verificado SHA-256 byte a byte, manifiesto incluido, backups previos intactos.

**Aplicación real:** los 4 resultados del dry-run se reutilizaron sin llamar a ORS una segunda vez (misma coordenada origen/destino, cómputo determinista) -- se persistieron `distancia_km`/`duracion_min`/`proveedor_ruta`/`estado_ruta`/`motivo_ruta` en las 5 filas candidatas, vía `_leer_filas`/`_escribir_filas_completas`/`bloqueo_sesion` (mismos primitivos ya publicados en `atlas_core/revalidacion_documental.py`, sin código nuevo). Reporte regenerado con `generar_reporte_viajes` (sin `calculador_rutas`, cero llamadas de red adicionales) en `reportes/reporte_revalidacion_20260818_231011_223069/`; `estado_operacion.json` actualizado.

**Verificación post-aplicación:** comparación completa de las 43 filas contra el backup -- **0 documentos fuera de los 5 candidatos modificados en ningún campo**. **0 violaciones de integridad** en campos documentales + origen/telemetría (verificado explícitamente, no sólo asumido). Catálogos (`vehiculos.json, plantas.json, clientes.json, obras_destinos.json, destinos_maestros.json, empresas.json`) y decisiones (`decisiones_aplicadas.json, decisiones_pendientes.json`) sin tocar (mtime).

**Tabla de recálculo:**

| Transporte | Guía(s) | Origen→Destino | Km antes | Km después | Estado antes → después | Fuente |
|---|---|---|---|---|---|---|
| 0000351956 | 464424 | AZA COLINA → Vista Clara, Cerrillos | (vacío) | 30.7719 | REQUIERE_REVISION → RUTA_CALCULADA | openrouteservice |
| 0000352552 | 464534, 464535 | AZA COLINA → Maestra Lidia Torres, Recoleta | (vacío) | 22.9378 | REQUIERE_REVISION → RUTA_CALCULADA | openrouteservice |
| 0000352584 | 464550 | AZA COLINA → Av. Irarrázaval, Ñuñoa | (vacío) | 27.7469 | REQUIERE_REVISION → RUTA_CALCULADA | openrouteservice |
| 0000352568 | 464577 | AZA COLINA → Galvarino, Quilicura | (vacío) | 13.1788 | REQUIERE_REVISION → RUTA_CALCULADA | openrouteservice |

**Cobertura km:** 12/38 viajes con km válido (31.6%), antes 8/38 (21.1%). Los 26 restantes sin km, TODOS con causa explicada (ninguno "sin km" sin justificación):

| Causa | Viajes |
|---|---|
| `MULTIPLES_UBICACIONES_DISPERSAS` | 17 |
| Origen no determinado (incluye `ORIGEN_GPS_NO_DETERMINADO`, `ORIGEN_GPS_ESTADIA_SIN_PLANTA` x2, `ORIGEN_GPS_CONFLICTO` (preexistente), y el caso 0000352537 donde GPS corrió y no confirmó ninguna planta) | 6 |
| `GEOCODIFICACION_DIRECCION_NO_ENCONTRADA` (OCR corrupto en destino, 464367) | 1 |
| Conflicto documental preexistente (`CONFLICTO_CLIENTE`/`CONFLICTO_OBRA_DESTINO`, 0000352376) | 1 |
| Sin `despachar_a` (0000352629) | 1 |

**Desktop:** código no modificado; `estado_operacion.json` apunta al reporte con los km nuevos -- Desktop los mostrará al abrir sin ningún cambio de UI.

**Drive:** modificado, exclusivamente por este recálculo controlado. **Git:** working tree con únicamente las tres bitácoras -- ningún cambio de código en este bloque (se reutilizaron mecanismos ya publicados).

**Estado: RUTAS/KM RECALCULADOS -- LISTO PARA VALIDACIÓN VISUAL DE JAVIER.**

## Bloque DIAGNÓSTICO DESTINOS AMBIGUOS (MULTIPLES_UBICACIONES_DISPERSAS) -- 2026-08-18

**Checkpoint:** Motor `9671834`, Desktop `fba95ac`, ambos limpios. **100% lectura en todo el bloque** -- catálogos y dataset re-verificados sin cambios de mtime al terminar.

**Metodología:** para cada uno de los 17 transportes (detectados programáticamente por `motivo_ruta` conteniendo `MULTIPLES_UBICACIONES_DISPERSAS`, coincide exacto con el bloque anterior): (1) candidatos de geocodificación reales desde `cache/geocodificacion/geocodificacion_cache.json` vía `RepositorioCacheGeocodificacion.buscar()` + `_candidatos_con_soporte_textual()` reales del código; (2) TODOS los `trip_id` mencionados en `motivo_origen_gps` de cada documento del viaje, y TODOS sus breadcrumbs cacheados en `telemetria_cache.json` (deliberadamente más amplio que lo que usa hoy `seleccionar_recorrido_operacional`, para medir qué evidencia existe aunque el algoritmo actual no la use); (3) distancia haversine real de CADA breadcrumb a CADA candidato, tomando el mínimo; (4) cruce contra `obras_destinos.json` (relaciones cliente↔obra, evidencia por guía) y `destinos_maestros.json` (57 entradas, 42 con coordenadas, 13 `CONFIRMADO`) buscando coincidencia de dirección exacta.

**Matriz completa (17 casos):**

| Transporte | Guía(s) | Despachar a | Candidatos (con soporte) | Mejor evidencia GPS (breadcrumbs totales) | Catálogo | Clase | Motivo |
|---|---|---|---|---|---|---|---|
| 0000349648 | 463594 | POETA PEDRO PRADO 1548 | 4 | 3.85 km (Lo Prado) vs 4.85 km -- margen estrecho | -- | **B** | Distancia y margen insuficientes para automático |
| 0000349298 | 463630 | AV. FORESTAL CORONEL | 2 | 300.8 km / 430.3 km -- ningún candidato cerca | -- | **C** | Breadcrumbs no cubren la zona real de entrega |
| 0000351884 | 464395 | CARMEN MENA 529 SAN MIGUEL | 5 | 11.1 km (RM) vs 53-1054 km (otras regiones) | entrada con coordenadas erróneas (circulares, mismo fallo de Pelias) -- descartada | **A** | Margen regional decisivo (~5x); única región compatible |
| 0000352203 | 464491 | URUGUAY 15 LA CISTERNA | 5 | 411-615 km -- TODOS los candidatos lejísimos | -- | **C** | Geocodificador nunca devolvió "La Cisterna" real -- falla de cobertura, no de desambiguación |
| 0000352242 | 464493 | AV SAN JOSE ESCRIVA DE BALG | 5 | 8.29 km (Chicureo) vs 23.56 km (San Bernardo), ambos en RM | -- | **B** | Mismo margen regional, comuna sigue sin decidirse con confianza |
| 0000352241 | 464494 | CAMINO LO RUIZ 2901 RENCA | 5 | 0.03-0.14 km a TODOS los candidatos (cluster) | `CAMINO LO RUIZ 2901, RENCA` **CONFIRMADO**, coordenadas idénticas al candidato ganador | **A** | GPS + catálogo confirmado coinciden exacto |
| 0000352449 | 464511 | SANTA ISABEL 585 LAMPA (+ref) | 4 | 0.12 km (Lampa) vs 1.61 km (Lampa) vs 2.07+ km (Santiago) | `SANTA ISABEL 585, LAMPA` **CONFIRMADO**, coordenadas idénticas | **A** | GPS + catálogo confirmado coinciden exacto |
| 0000352600 | 464588 | POETA PEDRO PRADO 1548 | 4 | 3.43 km vs 4.87 km -- margen estrecho | -- | **B** | Mismo patrón que 463594 (misma dirección) |
| 0000352804 | 464624 | PDTE. RIESCO 5903 LAS CONDES | 5 | 0.77/1.21/1.44/2.5 km (4 candidatos RM agrupados) vs 21.0 km (Padre Hurtado) | -- | **B** | Descarta Padre Hurtado con claridad, pero no distingue entre los 4 restantes |
| 0000352802 | 464631 | SANTA ISABEL 585 LAMPA | 4 | sólo 5 breadcrumbs (1 trip): 1.93 km (Lampa) vs 2.76 km (Santiago) -- margen débil | `SANTA ISABEL 585, LAMPA` **CONFIRMADO**, coincide exacto | **A** | Evidencia GPS débil mejorada por catálogo confirmado independiente |
| 0000352780 | 464640 | SANTA ISABEL 585 LAMPA | 4 | 1.13/2.42 km (Lampa) vs 17.5/19.6 km (Santiago) -- brecha regional clara | `SANTA ISABEL 585, LAMPA` **CONFIRMADO** | **A** | Brecha GPS decisiva + catálogo confirmado |
| 0000352752 | 464641, 464642 | CAMINO LOS PINOS SAN BERNARDO | 3 | 16.0/28.4/34.0 km -- ningún candidato cerca | entrada PENDIENTE con coordenadas iguales al candidato "San Bernardo" -- no confirmada | **C** | Breadcrumbs no cubren la zona real; catálogo no confirmado |
| 0000353028 | 464706 | PANAMERICANA NORTE LAMPA | 5 | sin telemetría (`SIN_HISTORICO`) | entrada PENDIENTE, dirección EXACTA, con coordenadas (Lampa real) -- no confirmada | **C** | Sin GPS; geocodificador devolvió sólo regiones equivocadas (Copiapó/Arica/Coquimbo); el catálogo (no confirmado) es la única pista real |
| 0000353055 | 464715 | AV. VICUÑA MACKENNA SAN JOAQUÍN | 5 | 5.89 km (Santiago RM) vs 83.7-480 km (otras regiones) | -- | **A** | Margen regional decisivo (~14x) |
| 0000353091 | 464726 | SANTA ISABEL 585 LAMPA | 4 | 1.77/3.36 km (Lampa) vs 19.1/21.3 km (Santiago) | `SANTA ISABEL 585, LAMPA` **CONFIRMADO** | **A** | Mismo patrón que 464640 |
| 0000353164 | 464740 | AV. VICUÑA MACKENNA SAN JOAQUÍN | 5 | sin telemetría (`SIN_HISTORICO`) | -- | **B** | Misma dirección exacta que 464715 (SÍ resuelta con GPS) -- sugerencia histórica, nunca evidencia propia de este viaje |
| 0000353312 | 464781 | PDTE. RIESCO 5903 LAS CONDES | 5 | 7.25/9.95/10.36/11.67 km -- márgenes estrechos entre sí | -- | **B** | Ninguna opción se separa con claridad de las demás |

**Resumen:** A = 7 (0000351884, 0000352241, 0000352449, 0000352802, 0000352780, 0000353055, 0000353091) · B = 6 (0000349648, 0000352242, 0000352600, 0000352804, 0000353164, 0000353312) · C = 4 (0000349298, 0000352203, 0000352752, 0000353028).

**GPS/Onelogis:**
- **Aprovechable con evidencia real (7 casos A + varios B):** usando TODOS los breadcrumbs cacheados (no sólo la ventana estrecha actual) el GPS discrimina con claridad en varios casos que hoy quedan igual de ambiguos que los demás -- el problema no es falta de datos, es que `seleccionar_recorrido_operacional`/`punto_gps_destino` sólo usa el ÚLTIMO punto de un recorrido con filtro de 5 km y ventana de ±15 min, perdiendo evidencia que SÍ existe en la caché.
- **No aprovechable en 4 casos:** 2 casos (463630, 464641/642) tienen breadcrumbs cacheados pero NINGUNO cae cerca de ningún candidato (el rango horario capturado no cubre la zona real de entrega); 2 casos (464706, 464740) no tienen ningún trip cacheado ese día (`SIN_HISTORICO`, cobertura real ausente de Onelogis).
- Ningún caso se resolvió simplemente "por el más cercano" -- en todos los casos A el margen frente a la segunda opción es grande (regional) o hay corroboración de catálogo independiente.

**Historial/catálogo:**
- **`obras_destinos.json`:** 15 obras registradas, todas con evidencia por guía (incluye varias de los 17 casos, p. ej. SALOMON SACK SA↔"DEMO CONSTRUCCIONES S.A." para 463594/464588) -- pero no aporta coordenadas propias, sólo confirma la relación cliente-obra-`despachar_a` ya conocida por el propio documento. No es evidencia geográfica independiente.
- **`destinos_maestros.json`:** 57 entradas, 42 con coordenadas, 13 `CONFIRMADO`. **3 coincidencias EXACTAS de dirección con estado `CONFIRMADO`** y coordenadas idénticas a un candidato de geocodificación (Camino Lo Ruiz 2901 Renca; Santa Isabel 585 Lampa, dos veces) -- usadas como evidencia genuina en los casos A correspondientes. 2 coincidencias con estado `PENDIENTE` (Panamericana Norte 22650 Lampa; Camino Los Pinos 3394 San Bernardo) -- tratadas como `SUGERENCIA_HISTORICA`, nunca como evidencia canónica, consistente con la regla de negocio ya establecida (`despachar_a` es la fuente autoritativa, el catálogo de destino registrado nunca la reemplaza). 1 coincidencia (Carmen Mena 529 San Miguel) descartada explícitamente por tener coordenadas idénticas al candidato regional erróneo de Pelias -- probable artefacto circular de la misma migración, no evidencia confiable.
- Ninguna sugerencia histórica se convirtió automáticamente en decisión -- se preserva el principio "Atlas sugiere, Javier decide" (ver docstring de `destino_entrega.py`: "nunca escoger una ubicación porque esté más cerca de AZA" ni por ninguna otra referencia externa sin evidencia propia del viaje).

**Cobertura potencial (calculada, sin ejecutar ORS):**
- Actual: 12/38 (31.6%)
- Sólo resolviendo A: 19/38 (50.0%)
- A + B con confirmación de Javier: 25/38 (65.8%)
- C (4 casos) permanecería sin resolver con los datos actuales, independientemente de cualquier heurística.

**Geocodificación:** **insuficiente en al menos 2/17 casos** (464491, 464706) -- Pelias/ORS nunca devuelve el candidato correcto ni siquiera entre las opciones, pese a que el documento nombra la comuna real correctamente ("LA CISTERNA", "LAMPA"). Limitación exacta: cobertura/relevancia de resultados para direcciones específicas chilenas con nombres de calle poco comunes o comunas menos pobladas -- no es un problema de desambiguación (Atlas no tiene entre qué elegir), es que la opción correcta simplemente no está en la respuesta.

**ORS (routing):** sigue siendo **suficiente** -- 100% de éxito en todas las llamadas reales hechas hasta ahora (17/17 acumulado en bloques anteriores + este). El cuello de botella no está en el cálculo de ruta, está en resolver el destino antes de poder llamarlo.

**Fix implementado:** NINGUNO. Sin cambios de código, catálogos, Drive ni Desktop en este bloque.

**Estado: DIAGNÓSTICO DE DESTINOS AMBIGUOS COMPLETADO -- LISTO PARA REVISIÓN CON JAVIER.**

## Bloque RESOLUCIÓN SEGURA DE DESTINOS CLASE A (mecanismo general, validado, sin publicar) -- 2026-08-18

**Checkpoint:** commit documental del diagnóstico previo publicado y verificado antes de empezar.

**Auditoría previa (Fase 2, antes de escribir código):** se revisaron las funciones ya existentes reutilizables -- `descartar_candidatos_lejos_de_gps`/`_candidatos_son_el_mismo_lugar`/`_candidatos_con_soporte_textual` (`destino_entrega.py`), `resolver_planta_origen_gps` (`seleccion_recorrido.py`, ventana amplia ya calibrada pero interna/no reutilizable tal cual), `CatalogoDestinos`/`Destino` (`catalogo_destinos.py`, ya modela `destinos_maestros.json` con `estado_calidad`/coordenadas). No existía ningún mecanismo que combinara catálogo confirmado + recorrido GPS completo para desambiguar destino -- se construyó reutilizando estas piezas, sin duplicar ninguna.

**Refactor puro (sin cambio de comportamiento) en `atlas_core/telemetria/seleccion_recorrido.py`:** se extrajo `recolectar_puntos_ventana_origen()` (nueva, pública) del cuerpo de `resolver_planta_origen_gps()` -- misma ventana temporal amplia ya calibrada (`margen_horas`), mismos trips/breadcrumbs, ahora expuesta para que otros consumidores de evidencia GPS la reutilicen sin volver a pedir red ni inventar una ventana nueva. `resolver_planta_origen_gps()` ahora LLAMA a esta función en vez de duplicar su lógica. Verificado sin regresión: 84/84 tests de telemetría/operación real en verde, comportamiento byte-idéntico.

**Regla de seguridad implementada (Fase 3), evaluada explícitamente contra los 8 escenarios pedidos:**
- **A (GPS + catálogo confirmado coinciden):** implementado -- Vía A y Vía B, si ambas responden, deben coincidir o se abstiene.
- **B (separación geográfica muy fuerte):** **NO implementado como regla independiente** -- calibrar "qué tan fuerte es fuerte" (¿3x? ¿10x? ¿20 km de margen absoluto?) con sólo 7 casos reales de referencia es exactamente lo que la instrucción prohíbe inventar. En cambio, los casos reales que mostraban esta separación (region-level: 5x-14x) ya se resuelven correctamente por la Vía B (descarte GPS con el radio de 50 km YA EXISTENTE) sin necesitar ningún umbral nuevo -- ver resultado abajo.
- **C (comuna/región documental descarta rivales):** ya cubierto por infraestructura existente reutilizada tal cual (`_candidatos_con_soporte_textual`, aplicado ANTES de que esta función reciba los candidatos) -- no se agregó nada nuevo.
- **D (convergencia de 2+ fuentes):** propiedad emergente de ejecutar Vía A y Vía B y exigir que coincidan -- sin regla especial adicional.
- **E/F/G/H (candidatos cercanos, GPS lejos de todos, sólo histórico PENDIENTE, sólo "más cercano" sin margen):** cubiertos como abstención explícita en el diseño -- ver controles negativos.

**Diseño final (`resolver_destino_ambiguo_con_evidencia_inequivoca`, `atlas_core/rutas/destino_entrega.py`):**
- **Vía A -- catálogo confirmado:** busca en `destinos_maestros.json` (vía `CatalogoDestinos`) una entrada `estado_calidad=CONFIRMADO` + `estado_vigencia=ACTIVO` cuya CALLE (primer segmento antes de la coma del campo `direccion` -- el catálogo real persiste `"CALLE NUMERO, COMUNA, PAIS"`, comparar la cadena completa fallaría siempre porque el documento nunca repite ", CHILE"; hallazgo encontrado y corregido durante la validación real, ver abajo) aparece literalmente en el texto documental, Y cuyas coordenadas caen dentro de `MARGEN_MISMO_LUGAR_KM` (1.0 km, ya existente) de EXACTAMENTE un candidato de geocodificación. Dos destinos confirmados que respaldan candidatos distintos → conflicto, abstención.
- **Vía B -- GPS descarta rivales:** nueva `_descartar_lejos_de_todo_el_recorrido()` (variante de `descartar_candidatos_lejos_de_gps` para múltiples puntos en vez de uno solo) -- conserva un candidato si está dentro del radio YA EXISTENTE (`radio_gps_km=50.0`, mismo valor que `resolver_destino_entrega`) de AL MENOS UN punto del recorrido documental completo (obtenido con `recolectar_puntos_ventana_origen`, no sólo el último punto de un recorrido "sustancial"). Resuelve sólo si sobrevive EXACTAMENTE uno.
- Si ambas vías responden y discrepan → abstención explícita (`CATALOGO_Y_GPS_DISCREPAN`), nunca se prioriza una fuente en silencio.
- Nunca toca `distancia_km`/ORS -- separación estricta entre selección de destino y routing (verificado con test dedicado).

**18 tests nuevos** (`tests/test_desambiguacion_destino_inequivoca.py`): 11 controles negativos (dos candidatos GPS casi equivalentes, candidatos agrupados a pocos km sin catálogo, GPS lejos de todos, catálogo `PENDIENTE`, dirección histórica repetida sin evidencia propia, candidato fuera de la comuna correcta, ausencia de GPS, breadcrumbs insuficientes, múltiples candidatos aún plausibles, dos destinos confirmados en conflicto, catálogo y GPS discrepan) + 7 controles positivos (GPS+catálogo coinciden, brecha geográfica inequívoca sólo-GPS, evidencia canónica convergente sólo-catálogo, catálogo no relacionado nunca se usa, formato real del catálogo calle/comuna/país, separación estricta de routing). Suite completa: **1265 passed, 0 failed** (baseline 1247 + 18).

**Validación real sobre los 17 casos (TEMP, sin escribir Drive, usando `ProveedorTelemetriaSoloCache` -- 0 llamadas Onelogis, 0 llamadas ORS):**

| Transporte | Clase previa | Resultado del mecanismo | Vía |
|---|---|---|---|
| 0000351884 | A | **RESUELTO** | GPS descarta rivales (región) |
| 0000352449 | A | **RESUELTO** | Catálogo confirmado |
| 0000352802 | A | **RESUELTO** | Catálogo confirmado |
| 0000352780 | A | **RESUELTO** | Catálogo confirmado |
| 0000353055 | A | **RESUELTO** | GPS descarta rivales (región) |
| 0000353091 | A | **RESUELTO** | Catálogo confirmado |
| 0000352241 | A | Abstención | 4/5 candidatos dentro de `MARGEN_MISMO_LUGAR_KM` del punto confirmado -- ambigüedad real de casa exacta, ni catálogo ni GPS distinguen cuál |
| 10 casos B/C | B/C | Abstención (los 10) | -- |

**Resumen: 6/7 casos A resueltos automáticamente, 0/10 falsos positivos entre B y C.** El 7º caso no se forzó -- se reporta la abstención tal cual, consistente con la instrucción explícita de priorizar seguridad sobre alcanzar la cifra esperada.

**Regresión:** los 12 viajes con km válido no fueron tocados -- el mecanismo nuevo es código standalone (no conectado a `procesamiento_masivo.py` ni a ningún flujo de escritura), verificado además por mtime de Drive sin cambios al cierre del bloque.

**Desktop:** no modificado; no aplica todavía verificación de esquema (nada se persiste aún).

**Drive:** no modificado (mtimes de `analisis_completo_guias.csv`, `destinos_maestros.json`, `telemetria_cache.json`, `geocodificacion_cache.json` y `estado_operacion.json` verificados idénticos al inicio del bloque). **Git:** working tree con `atlas_core/rutas/destino_entrega.py`, `atlas_core/telemetria/seleccion_recorrido.py`, `tests/test_desambiguacion_destino_inequivoca.py`. Sin commit, sin push.

**Estado: RESOLUCIÓN SEGURA DE DESTINOS CLASE A VALIDADA -- LISTO PARA REVISIÓN CON JAVIER.**

## Bloque PUBLICACIÓN + APLICACIÓN REAL: resolución clase A + ORS controlado -- 2026-08-18/19

**Checkpoint FASE 0:** Motor `ee9b7a3`, working tree con exactamente `atlas_core/rutas/destino_entrega.py`, `atlas_core/telemetria/seleccion_recorrido.py`, `tests/test_desambiguacion_destino_inequivoca.py` y las tres bitácoras -- sin archivos ajenos. Desktop `fba95ac`, limpio.

**FASE 1 -- publicación:** tests focales (`test_desambiguacion_destino_inequivoca.py` + grupo `telemetria/rutas/destino/geocod`, 397 passed) antes de commitear -- código byte-idéntico al que produjo 1265 passed, no se repitió la suite completa. Commit `515d9ef` ("fix: resolver destinos ambiguos con evidencia inequivoca"), push a `origin/lector-mvp-guia-nueva`, verificado local=remoto=`515d9ef`, 0/0, limpio.

**FASE 2 -- backup:** `respaldos/RESOLUCION_DESTINOS_A_ROLLBACK_PRE_APLICACION_20260818_203757/` -- únicos dos archivos de `operacion/actual` que esta operación podía modificar (`analisis_completo_guias.csv` in-place, `estado_operacion.json` puntero de reporte); catálogos y decisiones no son tocados por este mecanismo, no se incluyeron. Verificado SHA-256 byte a byte, `MANIFIESTO_SHA256.txt` + `LEEME_ROLLBACK.md` incluidos. Ningún backup previo eliminado.

**FASE 3 -- snapshot antes:** 38 viajes, 12 con `distancia_km` (31.6%), 26 sin km. Distribución de `motivo_ruta`: 17 `MULTIPLES_UBICACIONES_DISPERSAS` (16+1 con distinta cantidad de candidatos), 2 `GEOCODIFICACION_DIRECCION_NO_ENCONTRADA`, 2 `ORIGEN_ACTUALIZADO_PENDIENTE_RECALCULO_RUTA`, 2 `ORIGEN_GPS_ESTADIA_SIN_PLANTA`, 1 `ORIGEN_GPS_NO_DETERMINADO`, 1 `SIN_EVIDENCIA_GPS`, 1 `ORIGEN_GPS_CONFLICTO`, 12 sin motivo (viajes ya resueltos o bloqueados antes de llegar a destino).

**FASE 4 -- dry-run real (detección programática, no hardcodeada):** sobre copia TEMP del dataset + cachés reales, se recorrieron TODOS los transportes con `motivo_ruta` conteniendo `MULTIPLES_UBICACIONES_DISPERSAS` en el estado VIGENTE (17, calculado en el momento, no una lista fija) y se les aplicó `resolver_destino_ambiguo_con_evidencia_inequivoca()` con candidatos de geocodificación cacheados + `recolectar_puntos_ventana_origen()` (breadcrumbs completos, `ProveedorTelemetriaSoloCache`, 0 llamadas Onelogis) + `destinos_maestros.json` real. Resultado: **6 resueltos, 11 abstenidos -- coincide exacto con la validación previa**, sin diferencias que explicar. Confirmado explícitamente: 0 casos B resueltos, 0 casos C resueltos, `0000352241` sigue en abstención.

**FASE 5 -- dry-run ORS real** (sólo para los 6 pares origen/destino resueltos): `proveedor_rutas.calcular_ruta(coordenada_ruteo_planta(planta), candidato.coordenadas, "driving-hgv")` -- llamada directa al proveedor ORS con las coordenadas YA resueltas por el mecanismo nuevo (deliberadamente sin pasar por `resolver_destino_entrega`/`calcular_ruta_con_planta_conocida`, que volverían a geocodificar desde cero y reproducirían la misma ambigüedad -- selección de destino y routing conectados en este único punto, nunca fusionados). 6/6 `RUTA_CALCULADA`, distancia > 0: 464395→28.3559 km, 464511/464631/464640/464726→6.5048 km (las 4 guías de "Santa Isabel 585" comparten origen+destino exactos, mismo resultado), 464715→25.4058 km. Coordenada de origen de AZA COLINA usada: `punto_ruteo_latitud/longitud` (-33.294752, -70.730387) -- el catálogo documenta explícitamente que este es el punto real derivado de breadcrumbs GPS que ORS debe usar, no el `latitud/longitud` genérico geocodificado por texto.

**FASE 6 -- verificación antes de escribir:** los mismos resultados ya calculados (destino + ORS, sin recomputar) se aplicaron primero a la copia TEMP y se comparó contra el dataset real sin modificar. Exactamente las 6 guías esperadas (464395, 464511, 464631, 464640, 464715, 464726) cambiaron; 0 documentos ajenos; 0 violaciones en 21 campos documentales/origen/telemetría verificados explícitamente. Campos que cambian: `direccion_entrega`, `localidad_entrega`, `region_entrega`, `estado_entrega`, `distancia_km`, `duracion_min`, `proveedor_ruta`, `estado_ruta`, `motivo_ruta` (nuevo valor `RESUELTO_EVIDENCIA_INEQUIVOCA(<vías>)`, p. ej. `GPS_DESCARTA_RIVALES` o `CATALOGO_CONFIRMADO`).

**FASE 7 -- aplicación real:** los valores ya verificados en TEMP se copiaron al dataset real (`_leer_filas`/`_escribir_filas_completas`/`bloqueo_sesion`, primitivos ya publicados) -- **0 llamadas ORS adicionales** (la ruta ya calculada y validada en FASE 5/6 nunca se recalculó una segunda vez). Reporte regenerado con `generar_reporte_viajes` (mecanismo canónico, sin `calculador_rutas`, cero red adicional) en `reportes/reporte_revalidacion_20260819_004409_246309/`; `estado_operacion.json` actualizado.

**FASE 8 -- validación post-aplicación:** comparación completa contra el backup (43/43 filas) -- exactamente las 6 guías esperadas cambiaron, 0 documentos ajenos, 0 violaciones documentales. Catálogos y decisiones sin tocar (mtime). Reporte regenerado: **38 viajes, 18 con km (47.4%), 20 sin km** (antes 12/38, 31.6%). 11 viajes siguen `MULTIPLES_UBICACIONES_DISPERSAS` (17-6). `0000352241` confirmado en el reporte real: sigue `MULTIPLES_UBICACIONES_DISPERSAS(5)`, sin km -- la abstención se mantuvo intacta en producción, no sólo en la validación.

**Desktop:** código no modificado; los campos nuevos ya están disponibles en las columnas que Desktop ya consume (`planta_origen_nombre`/`distancia_km`/`direccion_entrega` sin cambio de esquema).

**Drive:** modificado -- exclusivamente `analisis_completo_guias.csv` (6 filas), `estado_operacion.json` (puntero), y el nuevo directorio de reporte (no sobrescribe ninguno previo). **Git:** working tree con únicamente las tres bitácoras -- el fix funcional ya estaba publicado (`515d9ef`) antes de esta aplicación.

**Pendiente explícito para bloques futuros (no iniciado):** casos B (6, confirmación humana asistida con sugerencia razonada -- concepto ya descrito en el diagnóstico previo, sin UI), casos C (4, requieren nueva evidencia/fuente -- 2 de ellos con limitación de geocodificador ya confirmada), geocodificador complementario para direcciones chilenas específicas, Incidencias Documentales (genéricas), patente documental vs vehículo canónico / asociación histórica chofer↔vehículo como sugerencia, Analítica/IA, Mobile, Multiempresa.

**Estado: RESOLUCIÓN SEGURA CLASE A APLICADA + RUTAS/KM RECALCULADOS -- LISTO PARA VALIDACIÓN VISUAL DE JAVIER.**

## Bloque AUDITORÍA VIAJES SIN PLANTA DE ORIGEN (diagnóstico, sin fix) -- 2026-08-19

**Checkpoint:** Motor `1f3746a` (local=remoto, 0/0, limpio), Desktop `fba95ac` (limpio). Reporte vigente: `reportes/reporte_revalidacion_20260819_004409_246309`. 100% lectura en todo el bloque -- Drive re-verificado sin cambios de mtime al cierre.

**FASE 1 -- inventario (programático, `viajes.csv` vigente):** `planta_origen_nombre` vacía en **5/38 viajes**, todos de un único documento: `0000352394`(464479), `0000352537`(464529), `0000353062`(464717), `0000353118`(464730), `0000353543`(464892). No hay ningún viaje multi-documento con evidencia contradictoria entre hermanos -- FASE 5 (documentos hermanos) no aplica a ninguno de los 5.

**FASE 3 -- trazado del pipeline (reproducido con `resolver_planta_origen_gps`/`recolectar_puntos_ventana_origen`/`detectar_detenciones`/`_resolver_planta_para_detencion` reales, contra `telemetria_cache.json` real vía `ProveedorTelemetriaSoloCache`, 0 llamadas de red):**

| Viaje | Patente | Trips cacheados | Breadcrumbs (ventana ±4h) | Detención más relevante | % dentro de geocerca | Resultado real |
|---|---|---|---|---|---|---|
| 464529 | DD2494 | 1 | 5 | 11.5 min, 2 pts | 0% (AZA COLINA), lejos de AZA RENCA | `NINGUN_PUNTO_DENTRO_DE_GEOCERCA` |
| 464479 | DD2494 | 1 | 5 | misma detención que 464529 (mismo día/patente) | 0% | `NINGUN_PUNTO_DENTRO_DE_GEOCERCA` |
| 464717 | TG8925 | 7 | 95 | **287.7 min, 57 pts** | **28/57 = 49.1%** dentro de AZA COLINA | `DETENCION_REAL_FUERA_DE_TODA_GEOCERCA` (por debajo del umbral `PROPORCION_MINIMA_DENTRO_POLIGONO=0.5`, YA calibrado, no nuevo) |
| 464730 | AL1879 | 9 | 325 | 65.3 min/91 pts (76.9% AZA COLINA) **Y** 99.5 min/54 pts (100% AZA RENCA) | ambas por encima del umbral, plantas DISTINTAS | `CONFLICTO_REAL_EN_VENTANA` -- **agravado**: `hora_entrada_aza == hora_salida_aza == "08:18"` (mismo valor exacto), ventana documental de duración cero, `solape_ventana=0.0%` para ambas plantas -- el score no tiene contra qué comparar y no logra desempatar (0.1366 vs 0.0) |
| 464892 | TG8925 | 10 | 148 | 87.8 min/51 pts (39.2% AZA COLINA) y 87.9 min/38 pts (0%, la de mayor duración, la que se reporta) | 39.2% y 44.4% (otra detención de 11.5min/9pts), ambas <50% | `DETENCION_REAL_FUERA_DE_TODA_GEOCERCA` |

**FASE 4 -- clasificación por causa raíz (categorías construidas desde la evidencia, ninguna forzada):**
- **Categoría C (`VEHICULO_NO_ENCONTRADO`) y D (`PATENTE_DOCUMENTAL/OCR_INCORRECTA`): 0 casos.** Verificado contra `vehiculos.json`: DD2494, TG8925 y AL1879 están los tres `CONFIRMADO`/`ACTIVO` -- la identidad del vehículo nunca es la causa aquí.
- **`GPS_EXISTE_PERO_ES_INSUFICIENTE` (variante de E, cobertura escasa): 464479, 464529** -- sólo 1 trip/5 puntos GPS en la ventana ±4h; la telemetría de Onelogis simplemente no cubrió la salida real de planta ese día. No corregible con datos ya existentes (no es un gap de cache: el trip que existe ya se usó).
- **`GPS_EXISTE_PERO_NO_IDENTIFICA_PLANTA_CON_SEGURIDAD` (E, casi-umbral): 464717 (49.1%), 464892 (39.2%/44.4%)** -- detenciones reales, largas, cerca del polígono conocido, pero por debajo del 50% ya calibrado (no se propone bajar el umbral -- ver Fase 7).
- **`CONFLICTO_DE_ORIGEN_ENTRE_DOCUMENTOS`... en este caso entre EVIDENCIA GPS de un único documento (F, adaptada): 464730** -- visita real y confirmada a dos plantas distintas en la misma ventana documental, agravada por una ventana documental de duración cero (hora_entrada=hora_salida=08:18, posible defecto de extracción a revisar contra la imagen original -- no se re-ejecutó OCR en este bloque).
- **`BUG_PIPELINE` (H, hallazgo real pero de tipo observabilidad, no de cálculo incorrecto):** para 464479 y 464892, `motivo_ruta` se sobrescribe con el motivo de ORIGEN (`ORIGEN_GPS_NO_DETERMINADO`/`ORIGEN_GPS_ESTADIA_SIN_PLANTA`) cuando en realidad el DESTINO de esos mismos documentos también está sin resolver (`estado_entrega=REVISAR`, `direccion_entrega=""`) -- un campo de un solo valor no puede representar dos motivos de bloqueo simultáneos. Consecuencia demostrada: el diagnóstico de destinos ambiguos del bloque anterior (17 casos `MULTIPLES_UBICACIONES_DISPERSAS`) **no incluyó estos 2 transportes**, aunque su destino documental tiene exactamente el mismo problema que los 17 sí detectados. No es un cálculo incorrecto (cada campo persistido es honesto por sí solo), es una limitación de representación -- se reporta, no se corrige en este bloque.

**FASE 5 -- información ya disponible pero no aprovechada, hallazgo más importante:** **464892** tiene `despachar_a_crudo="SANTA ISABEL 585 SANTIAGO LAMPA"` -- EXACTAMENTE la misma dirección que 464511/464631/464640/464726, ya resuelta automáticamente por `resolver_destino_ambiguo_con_evidencia_inequivoca()` (Vía A, catálogo `CONFIRMADO`) en el bloque anterior. Si el origen de 464892 se resolviera (evidencia insuficiente hoy, ver arriba), su destino YA tiene camino de resolución automática demostrado -- sin evidencia adicional que inventar, sólo pendiente de que el origen deje de bloquear el pipeline antes de llegar a esa etapa.

**FASE 6 -- impacto en rutas/km (sin ejecutar ORS):**

| Viaje | Origen resoluble | Destino | Si se resuelve origen, ¿listo para ORS? |
|---|---|---|---|
| 464529 | No (evidencia insuficiente) | `RESUELTO` (Vista Clara) | Sí, EN CUANTO se resuelva origen -- pero origen no es resoluble hoy |
| 464479 | No (evidencia insuficiente) | Ambiguo (oculto por el motivo de origen) | No -- seguiría bloqueado por destino |
| 464717 | Casi (49.1%, requiere confirmación) | Ambiguo (oculto) | No -- seguiría bloqueado por destino |
| 464730 | Conflicto real (requiere decisión de Javier) | `RESUELTO` (Maipú) | Sí, si Javier resuelve el conflicto |
| 464892 | Casi (39-44%, requiere confirmación) | Resoluble (mismo mecanismo Clase A ya publicado) | **Sí, si Javier confirma origen** |

Cobertura: actual **18/38 (47.4%)**. Categorías A+D combinadas (automáticas/bug) = 0 -- no hay incremento automático. Si Javier confirma los 2 casos límite (B): +1 viaje listo para routing (464892; 464717 seguiría bloqueado por destino) → **19/38 (50.0%)**. Si además resuelve el conflicto de 464730 → potencial +1 adicional (destino ya resuelto) → **20/38 (52.6%)**, sujeto a decisión humana en los tres casos, nunca automático.

**FASE 7 -- respuestas:**
1. *¿Bugs reales?* Uno, de tipo observabilidad (motivo_ruta de un solo valor oculta el motivo de destino cuando origen también falla) -- no afecta la corrección de los datos persistidos, sólo la capacidad de encontrarlos por consulta.
2. *¿Información desaprovechada?* Sí, en 464892 (destino ya resoluble por el mecanismo Clase A publicado, esperando sólo a que el origen deje de bloquear el flujo).
3. *¿Cuántos recuperan origen automáticamente sin adivinar?* 0 hoy -- los 2 casos más cercanos (49.1%, 44.4%) están por debajo del umbral ya calibrado.
4. *¿Cuántos requieren confirmación de Javier?* 3 (464717, 464892, 464730).
5. *¿Cuántos no son resolubles con datos actuales?* 2 (464479, 464529) -- límite real de cobertura de Onelogis ese día.
6. *¿Causa dominante?* Evidencia GPS real pero insuficiente/al límite del umbral -- no hay un patrón único (2 casos de cobertura escasa, 2 casos de umbral límite, 1 conflicto real).
7. *¿Corrección pequeña y segura?* **No hay una única.** Bajar el umbral de 50% sería inventar un número calibrado con sólo 2 casos de referencia -- expresamente prohibido por las reglas de este bloque. Corregir el gap de observabilidad (motivo_ruta) es seguro y pequeño, pero no resuelve ningún origen por sí solo, sólo mejora la visibilidad del problema de destino ya existente.
8. *¿Debe corregirse antes de destinos B/C?* No es prerrequisito técnico -- son casos independientes; queda a criterio de priorización de Javier.

**Desktop:** verificado -- el "No disponible" que Javier observa corresponde exactamente a `planta_origen_nombre` vacía en el reporte vigente real, no a un problema de render (Desktop lee la columna tal cual).

**Drive:** no modificado (mtimes verificados idénticos al inicio del bloque). **Git:** working tree con las tres bitácoras únicamente -- código sin cambios. **ORS: 0 llamadas. Onelogis red: 0 llamadas.**

**Estado: AUDITORÍA DE VIAJES SIN PLANTA DE ORIGEN COMPLETADA -- LISTO PARA REVISIÓN CON JAVIER.**

## Bloque EVIDENCIA HUMANA PARA RESOLUCIÓN DE ORIGEN -- 464717 / 464892 / 464730 -- 2026-08-19

**Checkpoint:** Motor `1f3746a` (working tree con las tres bitácoras pendientes del diagnóstico anterior, preservadas). Desktop `fba95ac`. 100% lectura -- Drive re-verificado sin cambios de mtime al cierre.

**Metodología:** para cada caso, `servicio.buscar_viajes(patente, fecha, fecha)` (día completo, no sólo la ventana ±4h) contra `telemetria_cache.json` real vía `ProveedorTelemetriaSoloCache` (0 llamadas de red), listando TODOS los trips del día con su distancia; `recolectar_puntos_ventana_origen` + `detectar_detenciones` para las detenciones reales; para cada detención, distancia del centroide a AZA COLINA/RENCA y porcentaje de sus puntos individuales dentro del polígono real de COLINA (`punto_en_poligono` con los 10 vértices reales) o del radio de RENCA (1.5 km, ya calibrado).

**464717 (TG8925, 12-08-2026, doc 12:42-14:38):** 7 trips cacheados el día completo. Tras las 10:03:30 el vehículo queda prácticamente inmóvil hasta las 14:51:14 (**287.7 min continuos**, agrupando varios "trips" cortos consecutivos de maniobra) -- ventana que **contiene por completo** la hora documental. De 57 puntos, **28 (49.1%) dentro del polígono de AZA COLINA** -- 0.9 puntos porcentuales bajo `PROPORCION_MINIMA_DENTRO_POLIGONO=0.5`. Las otras 4 detenciones del día (8.9/6.0/1.6/1.0 min, antes de las 10:03) están a 19-20 km del punto de referencia, sin relación con ninguna planta -- transición matinal previa, no relevante. **Cero puntos de cualquier detención del día dentro del radio de AZA RENCA (0.0% en las 5).**

**464892 (TG8925, 17-08-2026, doc 07:22-08:55):** 10 trips el día completo. Detención de 07:30:31-08:58:22 (**87.8 min**, 51 pts, **39.2% dentro de COLINA**) que se alinea con la ventana documental con un desfase de sólo 8/3 minutos en el inicio/fin. Segunda detención relevante 10:57-11:09 (11.5 min, 9 pts, 44.4% dentro de COLINA) -- posterior, más corta, mismo patrón. Las 6 detenciones restantes del día están a 18-20 km de la referencia, sin relación con ninguna planta. **Cero evidencia de RENCA en las 8 detenciones del día.**

**464730 (AL1879, 13-08-2026, doc hora_entrada=hora_salida=08:18):** 9 trips el día completo, incluyendo dos tramos largos reales (36.42 km entre 08:09-09:22, 20.13 km entre 09:51-10:35) que conectan dos detenciones geográficamente distantes: **(1) 07:19-08:24 (65.3 min, 91 pts, 76.9% dentro de AZA COLINA)** -- termina a las 08:24, 6 minutos después de la hora documental única (08:18); **(2) 10:21-12:01 (99.5 min, 54 pts, 100% dentro del radio de AZA RENCA)** -- comienza casi 2 horas después de esa misma hora documental. Entre ambas, el vehículo recorrió realmente ~56 km (dos trips reales encadenados), consistente con un desplazamiento genuino entre plantas, no con ruido. **Hallazgo documental:** `hora_entrada_aza == hora_salida_aza == "08:18"` en el dataset persistido -- no se puede confirmar sin la imagen original si es así en el documento o un defecto de extracción; no se re-ejecutó OCR en este bloque (no estrictamente indispensable para completar el análisis GPS). Se registra como candidata a futura Incidencia Documental, sin crearla.

**Interpretación (nunca aplicada, sólo para la conversación con Javier):** en los tres casos, AZA RENCA queda descartada por completo como alternativa para 464717/464892 (cero evidencia en absoluto ese día), y para 464730 la secuencia temporal real (Colina termina justo a la hora documental; Renca ocurre casi 2 horas después) sugiere que la visita a Renca corresponde a un desplazamiento posterior no relacionado con esta guía -- sin que eso autorice a Atlas a decidirlo solo.

**Explicación humana por caso, nivel de evidencia y planta sugerida:** ver reporte de conversación (no se transcribe aquí íntegro por extensión) -- resumen: 464717 moderada-fuerte/COLINA, 464892 moderada/COLINA, 464730 contradictoria a nivel algorítmico pero secuencia temporal favorece COLINA.

**FASE 6 -- propuesta conceptual de UX `ORIGEN_NO_CONFIRMADO`** (sin implementar, sin tocar Desktop): tarjeta con planta sugerida, motivo de la duda, evidencia GPS (duración/horario/porcentaje/alternativas descartadas) y tres acciones -- `CONFIRMAR PLANTA SUGERIDA` / `SELECCIONAR OTRA PLANTA` / `NO PUEDO DETERMINAR`.

**464479/464529:** preservados sin tocar, sin intento de resolución -- siguen clasificados como evidencia insuficiente (bloque anterior).

**Drive:** no modificado (mtimes verificados). **Desktop:** no modificado. **Git:** working tree con las tres bitácoras (pendientes del bloque anterior + este). **ORS: 0 llamadas. Onelogis red: 0 llamadas. OCR: no se re-ejecutó.**

**Estado: EVIDENCIA DE ORIGEN PREPARADA -- ESPERANDO DECISIÓN DE JAVIER.**

## Bloque INCORPORAR CONFIRMACIONES HUMANAS DE ORIGEN + DISEÑO DE CIERRE SEGURO -- 2026-08-19

**Checkpoint:** Motor `1f3746a` (working tree con las tres bitácoras pendientes de los dos bloques anteriores, preservadas, cero cambios de código). Desktop `fba95ac`. 100% lectura/diseño -- Drive re-verificado sin cambios de mtime al cierre.

**Confirmaciones humanas registradas (NO aplicadas a `operacion/actual` en este bloque):**
- 464717 (0000353062, TG8925, chofer Salomón Pizarro) → **AZA COLINA** (Javier).
- 464892 (0000353543, TG8925, chofer Salomón Pizarro) → **AZA COLINA** (Javier).
- 464730 (0000353118, AL1879, chofer José Lazcano) → **AZA RENCA** (Javier) -- contradice la sugerencia basada en secuencia temporal del bloque anterior (Colina). Se preserva explícitamente: **planta documental** (letterhead AZA, no confiable, ya conocido) ≠ **evidencia GPS** (COLINA 76.9%/91pts/65.3min y RENCA 100%/54pts/99.5min, ambas reales) ≠ **sugerencia algorítmica previa** (Colina, por cronología) ≠ **planta canónica confirmada por humano** (RENCA). Ninguna capa se sobrescribe silenciosamente sobre otra.

**FASE 2 -- auditoría del mecanismo de decisión existente** (`atlas_core/decisiones_pendientes.py` + `atlas_core/aplicacion_decisiones.py`, leídos íntegros):
- `TIPOS_SOPORTADOS` = `{VEHICULO_DESCONOCIDO, CLIENTE_DESCONOCIDO, CLIENTE_CANDIDATO, OBRA_DESCONOCIDA, DESTINO_SIN_CONFIRMAR, ALIAS_CANDIDATO}` -- **no existe `ORIGEN_NO_CONFIRMADO`**.
- `crear_decision()` ya genera un `decision_id` determinista (hash sobre tipo+documento+campo+valor+evidencias), con `candidatos`/`motivos`/`evidencias`/`acciones_permitidas` -- exactamente la forma que necesita una decisión de origen, sin cambios de contrato.
- `aplicar_decision_obra()` (en `aplicacion_decisiones.py`, pese al nombre ya maneja 3 tipos distintos) es transaccional: respaldo en memoria de todos los archivos afectados antes de escribir (`respaldos = {ruta: ruta.read_bytes()...}`), ledger auditable (`decisiones_aplicadas.json`) con protección de obsolescencia (`_sha(dataset) != artefacto.get("dataset_sha256")` → `DecisionObsoletaError`), e idempotencia (una `decision_id` ya aplicada devuelve `{"idempotente": True}` sin reaplicar).
- Sólo `(DESTINO_SIN_CONFIRMAR, CONFIRMAR)` y `(VEHICULO_DESCONOCIDO, REGISTRAR)` disparan `revalidar_y_regenerar_reporte` (regenera `viajes.csv`+`estado_operacion.json`) -- mecanismo directamente reutilizable para un nuevo `(ORIGEN_NO_CONFIRMADO, CONFIRMAR_PLANTA)`/`(ORIGEN_NO_CONFIRMADO, SELECCIONAR_OTRA_PLANTA)`.
- **Diferencia estructural real con `DESTINO_SIN_CONFIRMAR`:** ese tipo escribe a un CATÁLOGO GLOBAL (`destinos_maestros.json`/`obras_destinos.json`) porque confirma una identidad reutilizable entre documentos. Una confirmación de origen es un hecho específico DE ESE documento/viaje -- el patrón reutilizable correcto es el de `revalidar_telemetria_sin_ocr` (ya publicado): escritura directa y auditable sobre la fila vía `_leer_filas`/`_escribir_filas_completas`/`bloqueo_sesion`, no creación de catálogo.
- **Lo que falta, con precisión:** (1) el tipo `ORIGEN_NO_CONFIRMADO` en `TIPOS_SOPORTADOS`/`ACCIONES_POR_TIPO`; (2) un nivel superior en `_JERARQUIA_FUENTE_ORIGEN` (ya publicada en `gestor_viajes.py`, hoy `{TELEMETRIA_GPS:0, ONELOGIS_GPS:0, DOCUMENTO:1}`) para `CONFIRMACION_HUMANA`; (3) un guard en `revalidar_telemetria_sin_ocr` (`if fila.get("origen_determinado_por")=="CONFIRMACION_HUMANA": continue`) para que una revalidación futura NUNCA sobrescriba silenciosamente una confirmación humana -- hoy no existe ningún valor de `origen_determinado_por` que represente "ya lo confirmó un humano", por lo que técnicamente nada la distingue todavía de `TELEMETRIA_GPS`/`DOCUMENTO`.

**FASE 3 -- semántica `ORIGEN_NO_CONFIRMADO` (diseño, no implementado):** payload con `documento`, `campo="planta_origen"`, `candidatos` (uno por planta con evidencia GPS resumida cuantitativa: % dentro de geocerca, duración, horario), `motivos` (reutiliza los ya existentes: `ORIGEN_GPS_CONFLICTO`/`ORIGEN_GPS_ESTADIA_SIN_PLANTA`/etc.), `acciones_permitidas=("CONFIRMAR_PLANTA","SELECCIONAR_OTRA_PLANTA","NO_PUEDO_DETERMINAR","POSPONER")`. La acción registra en el ledger: `decision_id, actor, fecha, documento/guía/transporte, planta_id elegida, evidencia_previa completa (nunca se borra), valor_anterior, fuente="CONFIRMACION_HUMANA"`.

**FASE 4 -- propagación trazada:** decisión → escritura auditable en el/los documento(s) del viaje (reutilizando primitivos ya publicados, sin nuevo código de persistencia) → ledger → `_JERARQUIA_FUENTE_ORIGEN` consolida a nivel viaje con el nuevo nivel más alto → `revalidar_y_regenerar_reporte` (mecanismo ya existente, sin cambios) → `viajes.csv` → Desktop (mismo esquema, sin cambios). Documentos múltiples del mismo viaje: la jerarquía ya publicada resuelve el caso sin ambigüedad (confirmación humana > GPS > documento). Routing/km deliberadamente NO automático tras confirmar origen -- paso separado, igual que en el bloque de destinos Clase A.

**FASE 5 -- 464730 como control negativo, verificado conceptualmente contra el diseño:** ambas evidencias GPS se conservarían íntegras en `evidencia_origen`/ledger; se registraría RENCA como origen confirmado con `fuente=CONFIRMACION_HUMANA`; ningún umbral global cambia; COLINA NO se convierte en incidencia documental sólo por haber sido la sugerencia descartada; el routing usaría RENCA; la auditoría permite reconstruir exactamente por qué (ambas detenciones documentadas, decisión humana explícita con actor/fecha). El diseño cumple los 6 puntos exigidos por la FASE 5 del bloque.

**FASE 6 -- ¿implementar ahora?** Existe una extensión pequeña y generalizable (3-4 archivos: `decisiones_pendientes.py`, `aplicacion_decisiones.py`, `gestor_viajes.py`, `revalidacion_documental.py`), pero **no se implementa en este bloque**, por instrucción explícita -- el diseño queda listo para una futura autorización.

**FASE 7 -- simulación de las 3 confirmaciones (conceptual, sin escribir TEMP ni Drive, sin ORS):**

| Guía | Origen resultante | Destino actual | ¿Listo para ORS? |
|---|---|---|---|
| 464717 | AZA COLINA | Ambiguo (mismo patrón que otros 17, hoy oculto por el motivo de origen) | No |
| 464892 | AZA COLINA | Misma dirección ya resuelta para 4 viajes (Class A), pero este transporte no pasó por ese mecanismo porque su `motivo_ruta` no lo mostraba como `MULTIPLES_UBICACIONES_DISPERSAS` | No todavía -- requiere un paso adicional (ya publicado, no automático) |
| 464730 | AZA RENCA | Ya `RESUELTO` ("Maipú, RM") | **Sí**, el único listo de inmediato |

**FASE 8 -- 464479/464529:** preservados sin ninguna acción, tal como quedaron clasificados (evidencia insuficiente, no se les pide nada a Javier).

**FASE 9 -- alcance real del problema de `motivo_ruta` (auditado en los 38 viajes, no sólo intuido):** dos problemas distintos y ambos demostrados:
1. **Enmascaramiento** (el motivo de origen oculta una ambigüedad de destino igual de real y verificable hoy): **3 viajes** -- 464479, 464717, 464892 (verificado geocodificando de nuevo contra la caché real cada `despachar_a_crudo` de los 9 documentos con `estado_ruta`/`motivo_ruta` relacionado a origen).
2. **Texto obsoleto** (el motivo sigue diciendo "origen no determinado" pese a que el origen YA se corrigió en el bloque de revalidación de telemetría, porque en ese momento no había `distancia_km` que invalidar y por tanto nada disparó una actualización de `estado_ruta`/`motivo_ruta`): **1 viaje -- 464522** (`planta_origen_nombre=AZA COLINA`, `origen_determinado_por=TELEMETRIA_GPS`, pero `motivo_ruta=SIN_EVIDENCIA_GPS`, `estado_ruta=ORIGEN_NO_DETERMINADO`, ambos obsoletos). Verificado que 464698/699/700 y 464529, aunque también mencionan `ORIGEN_*` en su motivo, SÍ describen correctamente su estado actual (no son casos de texto obsoleto).

Total: **4/38 viajes con `motivo_ruta`/`estado_ruta` no fiable como única fuente de verdad para Javier o para cualquier consulta automatizada.** Se registra como deuda funcional -- no se corrige en este bloque.

**Drive:** no modificado (mtimes verificados idénticos). **Desktop:** no modificado. **Git:** working tree con las tres bitácoras (pendientes de los dos bloques anteriores + este). **ORS: 0 llamadas. Onelogis red: 0 llamadas. OCR: no se re-ejecutó. Código: 0 cambios.**

**Estado: DISEÑO DE CONFIRMACIÓN HUMANA DE ORIGEN COMPLETADO -- LISTO PARA REVISIÓN CON JAVIER.**

## Bloque IMPLEMENTAR ORIGEN_NO_CONFIRMADO / CONFIRMACIÓN HUMANA AUDITABLE DE ORIGEN -- 2026-08-19

**Checkpoint (FASE 0):** working tree verificado = exactamente las tres bitácoras acumuladas de los bloques anteriores, cero cambios de código. Commit documental `87dc2ba` ("docs: registrar decisiones humanas de origen"), push confirmado, `git status` limpio antes de tocar `atlas_core/`.

**FASE 1 -- reauditoría contra código real (no repetición del diseño, verificación directa):** se releyeron `TIPOS_SOPORTADOS`, `ACCIONES_POR_TIPO`, `crear_decision` (hash determinista), `generar_artefacto` (filtro contra ledger terminal), `aplicar_decision_obra` (respaldo transaccional + `DecisionObsoletaError`), `_JERARQUIA_FUENTE_ORIGEN`, `revalidar_telemetria_sin_ocr`, `_escribir_filas_completas`/`_leer_filas`, y `decisiones_pendientes_ui.js` completos -- confirmando punto por punto lo ya auditado en el bloque de diseño, sin sorpresas que obligaran a cambiar el plan.

**FASE 2/3 -- `detectar_decision_origen_no_confirmado()` (nueva, `decisiones_pendientes.py`):** función pura, recibe `archivo`/`fila`/`plantas` -- **nunca vuelve a llamar Onelogis ni recomputa telemetría**, sólo lee columnas ya persistidas (`estado_ruta`, `planta_origen_id`, `motivo_origen_gps`, `latitud_estadia_gps`/`longitud_estadia_gps`/`duracion_estadia_gps_min`). Se abstiene (`None`) si: `estado_ruta != "ORIGEN_NO_DETERMINADO"`; ya existe `planta_origen_id`; el `motivo_origen_gps` no matchea ninguno de los dos patrones reconocidos (`_PATRON_CONFLICTO_ORIGEN` para `CONFLICTO_REAL_EN_VENTANA(...)`, o coordenada de estadía presente para `DETENCION_REAL_FUERA_DE_TODA_GEOCERCA`); o no hay ninguna planta CONFIRMADA/ACTIVA dentro de `RADIO_CANDIDATO_ORIGEN_SUGERIDO_KM=50.0` (constante nueva, **deliberadamente igual** al radio GPS ya calibrado y en producción en `destino_entrega.py` -- nunca un umbral inventado para este bloque; se justifica porque aquí sólo genera una SUGERENCIA para revisión humana, nunca una resolución automática, que sigue exigiendo el 50% de contención en polígono sin cambios). Construye `candidatos` (uno por planta cercana/nombrada, con `evidencia_resumen` en texto plano) y `evidencias=[{"tipo":"GPS_ORIGEN", ...}]` reusando literalmente los valores ya persistidos, y llama a `crear_decision(tipo="ORIGEN_NO_CONFIRMADO", entidad="ORIGEN", campo="planta_origen", valor_documental="", ...)`. `generar_artefacto()` extendido para tratar `CONFIRMAR_PLANTA`/`SELECCIONAR_OTRA_PLANTA`/`NO_PUEDO_DETERMINAR` como acciones terminales (mismo mecanismo que ya usan los otros tipos).

**FASE 4 -- `_JERARQUIA_FUENTE_ORIGEN` extendida** (`gestor_viajes.py`): `{"CONFIRMACION_HUMANA": -1, "TELEMETRIA_GPS": 0, "ONELOGIS_GPS": 0, "DOCUMENTO": 1}`. Ningún otro cambio en `_nivel_fuente_origen`/`_resolver_origen_viaje` -- ya funcionan correctamente con cualquier valor (incluido negativo) vía `min()`.

**FASE 5 -- protección contra sobrescritura silenciosa:** en `revalidar_telemetria_sin_ocr()`, se añadió como **primer chequeo del bucle por fila** (antes que el chequeo preexistente de `estado_telemetria`): `if str(fila.get("origen_determinado_por","")).strip() == "CONFIRMACION_HUMANA": continue`. Deliberadamente el primer chequeo -- protege incluso si `estado_telemetria` llegara vacío por cualquier motivo futuro. Verificado con test dedicado que fuerza esa condición exacta (telemetría cacheada real que apuntaría a otra planta, `estado_telemetria=""`): la fila no se toca.

**FASE 6 -- aplicación auditable (`aplicacion_decisiones.py`):** nueva rama `elif tipo == "ORIGEN_NO_CONFIRMADO":` dentro del bloque transaccional ya existente (respaldo/rollback automático, sin código nuevo de transacción). `CONFIRMAR_PLANTA` exige exactamente 1 candidato en la decisión (si no, `ErrorAplicacionDecision`); `SELECCIONAR_OTRA_PLANTA` exige el nuevo parámetro `planta_id_elegida` no vacío. Ambas validan la planta con una lectura fresca de `CatalogoPlantas(...).listar()` exigiendo `estado_calidad=="CONFIRMADA"` y `estado_vigencia=="ACTIVA"`. Capturan `valor_anterior` (4 columnas de origen) antes de escribir, escriben `planta_origen_id`/`planta_origen_nombre`/`origen_determinado_por=FUENTE_ORIGEN_CONFIRMACION_HUMANA`/`evidencia_origen=f"DECISION_HUMANA:{decision_id}"` vía `_escribir_filas_completas` (importado en diferido, mismo patrón ya establecido para evitar import circular), y **nunca tocan ninguna otra columna** -- la evidencia GPS/documental original queda íntegra. `NO_PUEDO_DETERMINAR` no escribe nada al dataset -- basta con quedar en el ledger como acción terminal para que `generar_artefacto` no vuelva a preguntar lo mismo mientras la evidencia (parte del `decision_id`) no cambie (verificado con test explícito, sin necesitar ninguna extensión del modelo de decisiones). El ledger registra `planta_id`/`planta_nombre`/`valor_anterior`/`evidencia_previa`/`candidatos_previos`/`fuente` -- **se añadió `resultado_extra["planta_id"]`/`["planta_nombre"]`** (no existía en el primer borrador) para que el llamador reciba de inmediato qué planta quedó aplicada, sin tener que releer el ledger. Regeneración de reporte: rama nueva separada (no reutiliza `revalidar_y_regenerar_reporte`, que sólo audita obra/patente y reportaría incorrectamente `reporte_regenerado=False` para un cambio puro de origen) que llama directamente `generar_reporte_viajes`+`escribir_estado_operacion`, siempre que la acción sea `CONFIRMAR_PLANTA`/`SELECCIONAR_OTRA_PLANTA`. **`ORS nunca se dispara desde esta rama`** -- verificado por ausencia de cualquier import/llamada a los módulos de ruteo, y por los tests que cuentan llamadas.

**FASE 7 -- `NO_PUEDO_DETERMINAR`:** no requirió ninguna extensión del modelo (confirmando la hipótesis del bloque de diseño) -- el `decision_id` determinista existente + el filtro de `generar_artefacto()` contra acciones terminales del ledger bastan para que Atlas nunca repita la misma pregunta mientras la evidencia no cambie.

**FASE 8 -- Desktop (`decisiones_pendientes_ui.js`), cambios mínimos:** `entidades.ORIGEN_NO_CONFIRMADO='ORIGEN'`; dos entradas nuevas en `mensajes` (`ORIGEN_GPS_ESTADIA_SIN_PLANTA`/`ORIGEN_GPS_CONFLICTO`) para texto humano; `opcionesAccion()` devuelve exactamente `['Confirmar planta sugerida','No puedo determinar','Decidir después']` con 1 candidato o `['Elegir planta de origen','No puedo determinar','Decidir después']` con 2+ (nunca ofrece "confirmar la sugerida" cuando hay ambigüedad real); `nodoAcciones()` gana un selector de planta (mismo patrón ya establecido para `selectorTipo` de vehículo) que sólo aparece al elegir `SELECCIONAR_OTRA_PLANTA`, y exige selección antes de habilitar el envío; `nodoTarjetaCaso()` muestra Transporte (en vez del "Valor leído" genérico, que no aplica -- el campo en duda nunca es un texto OCR) y el bloque de planta(s) candidata(s) con su `evidencia_resumen`. Whitelist de tipos aplicables extendida con `'ORIGEN_NO_CONFIRMADO'`. `opciones.aplicar` ahora puede recibir un 4º argumento (planta elegida) pero sólo para este tipo (los demás tipos conservan exactamente su firma de 3 argumentos, verificado sin romper ningún test previo). **`main.js`/`preload.js` deliberadamente NO tocados en este bloque de diseño** -- la whitelist hardcodeada de acciones en `main.js` todavía no incluía las 3 acciones nuevas, así que un click real en la app habría fallado de forma segura (mensaje de error explícito, sin escribir nada) -- gap documentado, no indispensable para la validación TEMP (que ocurre a nivel Motor, no vía IPC). **Cerrado en el bloque siguiente (FASE 0, antes de publicar) -- ver esa entrada para el detalle del ajuste.**

**FASE 9 -- tests Motor (`tests/test_origen_no_confirmado.py`, nuevo, 21 casos):** fixtures con esquema `COLUMNAS` completo (patrón ya establecido en `test_revalidacion_telemetria_gap.py` -- el fixture minimalista de `test_aplicacion_decisiones_r33.py` no sirve aquí porque este código sí llama `_leer_filas`, que valida el esquema real) + `CatalogoPlantas.crear(...)` para dos plantas de prueba (coordenadas sintéticas, deliberadamente >50 km entre sí para separar limpiamente los escenarios de un-candidato vs conflicto nombrado). Cubre: generación con candidato único (estadía) y con conflicto nombrado; abstención con evidencia insuficiente (patrón 464479/464529) y con `estado_ruta` distinto; abstención si ya existe origen; abstención si la única planta cercana no está activa; `CONFIRMAR_PLANTA` rechaza si hay 2+ candidatos; `SELECCIONAR_OTRA_PLANTA` exige `planta_id_elegida` y permite elegir la planta NO favorecida por el conflicto (**control 464730 conceptual: GPS con score más alto para una planta, el humano elige la otra, resultado canónico = la elegida**); `NO_PUEDO_DETERMINAR` no escribe origen y queda terminal (mismo `decision_id`, `generar_artefacto` la filtra); ledger conserva `evidencia_previa`/`valor_anterior`; dataset obsoleto rechaza (`DecisionObsoletaError`); idempotencia (segunda aplicación devuelve `idempotente=True`, ledger no duplica); no modifica ninguna columna documental (cliente/chofer/fecha/patentes/material/obra); regeneración de reporte conserva la planta; consolidación de viaje: `CONFIRMACION_HUMANA` gana sobre `TELEMETRIA_GPS`/`DOCUMENTO` de un documento hermano del mismo viaje; `revalidar_telemetria_sin_ocr` no pisa una fila confirmada aun con `estado_telemetria` vacío; escaneo de dataset completo omite evidencia insuficiente. **Grupo focal** (`decision or origen or gestor_viajes or revalidacion or telemetria`): 245 passed (baseline 224 + 21). **Suite completa: 1286 passed, 0 failed** (baseline 1265 + 21).

**FASE 10 -- tests Desktop (`test/decisiones_pendientes.test.js`, 9 casos nuevos):** tarjeta de un candidato (Transporte/Planta sugerida/evidencia, opciones exactas); tarjeta de dos candidatos (control 464730: ambas plantas visibles, sin ofrecer "confirmar sugerida"); ausencia del "Valor leído" genérico; `CONFIRMAR_PLANTA` con un candidato llama `aplicar` sin exigir selector de planta; `SELECCIONAR_OTRA_PLANTA` exige elegir planta antes de aplicar; **control 464730 en Desktop: el humano elige la planta que NO aparece primero en la lista de candidatos (AZA RENCA), y el argumento enviado a `aplicar` es exactamente `planta-renca`**; `NO_PUEDO_DETERMINAR` envía el código exacto; los dos motivos nuevos se traducen a texto humano; un tipo no soportado sigue mostrando el mensaje de "próximo bloque" sin romper. Se ajustaron 2 tests preexistentes (vehículo) porque ahora reciben un 4º argumento `null` explícito -- comportamiento sin cambios, sólo la aserción exacta de argumentos. **Archivo: 60 passed. Suite completa Desktop: 208 passed, 0 failed.**

**FASE 11 -- validación real en TEMP (copia de Drive a scratchpad, nunca Drive):** se copiaron `analisis_completo_guias.csv`, `estado_operacion.json`, `plantas.json`, `telemetria_cache.json`, `destinos_maestros.json`, `clientes.json`, `empresas.json`, `vehiculos.json`, `obras_destinos.json`, `choferes.json` reales a TEMP, con mtimes de Drive capturados antes de copiar. `detectar_decisiones_origen_sin_ocr(raiz_atlas=TEMP)` sobre las 43 filas reales produjo **exactamente 3 decisiones** -- 464717 (candidatos AZA COLINA a 0.0 km / AZA RENCA a 12.6 km, ambas dentro de 50 km reales), 464730 (candidatos por conflicto nombrado, scores 0.1366/0.0 idénticos al dato real ya documentado en bloques anteriores), 464892 (candidatos AZA COLINA a 1.3 km / AZA RENCA a 11.4 km) -- y **0 para 464479/464529** (excluidos correctamente: 464479 por motivo no reconocido, 464529 además por `estado_ruta="REQUIERE_REVISION"` ≠ `ORIGEN_NO_DETERMINADO`). `reconciliar_decisiones_origen` publicó la bandeja (3 decisiones) sin error. Se aplicaron las 3 confirmaciones reales de Javier vía `aplicar_decision_obra(..., accion="SELECCIONAR_OTRA_PLANTA", planta_id_elegida=...)`: 464717→AZA COLINA, 464892→AZA COLINA, 464730→**AZA RENCA** (verificado en el CSV resultante: `origen_determinado_por=CONFIRMACION_HUMANA`, `evidencia_origen=DECISION_HUMANA:<hash>`, `motivo_origen_gps` con el conflicto original intacto). Ledger con 3 aplicaciones, `accion=SELECCIONAR_OTRA_PLANTA` en las tres (uniforme, mismo mecanismo sirve para "confirmar la única sugerida" y "elegir explícitamente"). Reporte regenerado (`reporte_regenerado=True` en las tres): en `viajes.csv` resultante, **0000353118 (464730) quedó con `estado_entrega=RESUELTO`** (destino ya resuelto de un bloque anterior, listo para ORS de inmediato); **0000353062 (464717) sigue con `estado_entrega` vacío** (destino ambiguo, bloqueado como se esperaba); **0000353543 (464892)** también con `estado_entrega` vacío, pero se verificó que `destinos_maestros.json` tiene una entrada `CONFIRMADO`/`ACTIVO` con dirección `"SANTA ISABEL 585, LAMPA, CHILE"` -- literalmente contenida en su `despachar_a` documental, **la misma que ya respalda a los otros 3 viajes hermanos ya `RESUELTO`s** (`0000352802`, `0000352780`, `0000353091`, los tres con `motivo_ruta=RESUELTO_EVIDENCIA_INEQUIVOCA(CATALOGO_CONFIRMADO)`) -- cumple la precondición de la Vía A del mecanismo Clase A, pero **no se reconstruyó el flujo completo de geocodificación** (`geocodificacion_cache.json` + candidatos ambiguos + `resolver_destino_ambiguo_con_evidencia_inequivoca`) para confirmarlo end-to-end en esta validación, y **no se llamó ORS en ningún momento del bloque**. `motivo_ruta` de 464892 quedó con el texto de origen obsoleto (mismo patrón de deuda de observabilidad ya conocido, 4/38, sin cambios en este bloque).

**FASE 12:** confirmado explícitamente -- 464479/464529 no aparecen en las 3 decisiones publicadas ni recibieron ninguna acción.

**FASE 13:** deuda de `motivo_ruta` (4/38: 3 enmascaramiento + 1 texto obsoleto, más el nuevo caso 464892 con el mismo patrón de texto obsoleto tras esta confirmación) **no corregida en este bloque**, según instrucción explícita -- registrada como pendiente.

**Integridad Drive:** mtimes de `analisis_completo_guias.csv`, `plantas.json`, `telemetria_cache.json`, `decisiones_pendientes.json`, `decisiones_aplicadas.json` verificados idénticos antes y después de toda la validación TEMP. Directorio TEMP eliminado al finalizar (`rm -rf` sobre el scratchpad de sesión, nunca sobre Drive).

**Drive:** no modificado. **Desktop (código en vivo):** `main.js`/`preload.js` no modificados -- gap de wiring documentado. **Git:** Motor con `atlas_core/{aplicacion_decisiones,decisiones_pendientes,gestor_viajes,revalidacion_documental}.py`, `tests/test_origen_no_confirmado.py` y las tres bitácoras, sin commit. Desktop con `src/decisiones_pendientes_ui.js`, `test/decisiones_pendientes.test.js`, sin commit. **Sin push del bloque funcional -- instrucción explícita.** **ORS: 0 llamadas. Onelogis red: 0 llamadas. OCR: no se re-ejecutó.**

**Estado: ORIGEN_NO_CONFIRMADO VALIDADO PUNTA A PUNTA -- LISTO PARA REVISIÓN CON JAVIER.**

## Bloque VISITA_A_PLANTA + ASOCIACIÓN VIAJE↔VISITA -- 2026-08-19

**FASE 0 -- publicación del bloque ORIGEN_NO_CONFIRMADO (cierre del gap Desktop primero):** auditado `main.js` -- confirmado el gap: whitelist hardcodeada `['REGISTRAR','NO_REGISTRAR','CONFIRMAR','NO_CONFIRMAR','POSPONER']` sin las 3 acciones nuevas. Ajuste mínimo, sin ampliar UX: `main.js` (`ACCIONES_DECISION_OBRA` extendida + `PATRON_UUID` para validar `plantaIdElegida` antes de invocar Python, exigido sólo para `SELECCIONAR_OTRA_PLANTA`); `preload.js` (`aplicarDecisionObra` acepta un 4º parámetro `plantaIdElegida=null`); `src/atlas_viajes.html` (el callback `aplicar` propaga el 4º argumento); `aplicar_decision_pendiente.py` (Motor: `--accion` acepta las 3 acciones nuevas, nuevo flag `--planta-id-elegida` reenviado a `aplicar_decision_obra`). También se añadió `resultado_extra["planta_id"]`/`["planta_nombre"]` en `aplicacion_decisiones.py` (faltaba en el borrador anterior) para que el CLI/Desktop reciban de inmediato qué planta quedó aplicada. **3 tests Motor nuevos** (`tests/test_origen_no_confirmado.py`: CLI real vía `subprocess.run` para las 3 acciones, de punta a punta, mismo patrón que el test CLI ya existente de obsolescencia) + **3 tests Desktop nuevos** (`decisiones_pendientes.test.js`: whitelist de `main.js`, propagación en `preload.js`, propagación en `atlas_viajes.html`, todos vía lectura de código fuente, mismo patrón que el test ya existente "main delega la única escritura..."). Motor: 1289 passed (0 failed). Desktop: 211 passed (0 failed). **Motor publicado:** commit `d5adb2e`, push confirmado, local=remoto, limpio. **Desktop publicado:** commit `a34059f`, push confirmado, local=remoto, limpio (se configuró upstream tracking, no existía).

**FASE 1/2 -- auditoría del código real ANTES de diseñar nada nuevo (decisión metodológica del bloque):** en vez de partir de la estructura conceptual sugerida en la instrucción, se auditó primero `atlas_core/telemetria/seleccion_recorrido.py` completo. Hallazgo que cambió el rumbo del bloque: **`detectar_detenciones` + `_resolver_planta_para_detencion` + `resolver_planta_origen_gps` YA implementan, en producción, exactamente el modelo pedido.** `detectar_detenciones` agrupa breadcrumbs del día completo del vehículo en clusters espacio-temporales (radio de coherencia fijo desde el primer punto del cluster, filtro de velocidad cuando el proveedor la informa) -- cada cluster resultante (`DetencionTelemetria`) ES, conceptualmente, una VISITA_A_PLANTA candidata: tiene inicio/fin/duración/puntos/trips relacionados. `_resolver_planta_para_detencion` la asocia a una geocerca (circular: distancia al centroide ≤ radio; poligonal: ≥50% de sus puntos reales dentro del polígono, `PROPORCION_MINIMA_DENTRO_POLIGONO`). No existe hoy una clase `VisitaAPlanta` con ese nombre exacto -- existe la misma información, con otro nombre, ya validada y en producción.

**FASE 3 -- separación de visitas múltiples/mismo día, ya verificada, no nueva:** `detectar_detenciones` opera sobre la secuencia COMPLETA y ordenada de breadcrumbs del vehículo/día (todos los trips, no un trip a la vez) -- un cluster se cierra en cuanto un punto se aleja más de `radio_coherencia_km` del cluster vigente, así que dos permanencias reales separadas en el tiempo (misma planta o plantas distintas) SIEMPRE producen `DetencionTelemetria` distintas. Nunca asumió "una planta por vehículo/día" -- ver Fase D del bloque ORIGEN O2 (comentario ya existente en el código, citado literalmente): "dos o más plantas con evidencia real dentro de la MISMA ventana documental... esto SÍ es un conflicto real (no una visita a otra hora del mismo día, que ya quedó descartada como evidencia por el solape con la ventana)".

**FASE 4 -- horas documentales, auditadas contra el esquema real:** `grep` sobre `procesamiento_masivo.py` confirma que sólo existen dos campos de hora documental: `hora_entrada_aza`/`hora_salida_aza` (derivados de `datos.get("hora de entrada"/"hora de salida")` del OCR) -- ningún otro timestamp documental en el esquema de 47 columnas. `resolver_planta_origen_gps` ya construye la ventana `[min(entrada,salida), max(entrada,salida)]` cuando ambas existen, o un margen simétrico (`MARGEN_VENTANA_UNA_HORA_MIN`, reutiliza `GAP_MAXIMO_MIN_PREDETERMINADO` ya calibrado) alrededor de la única disponible cuando falta una. **`hora_entrada_aza == hora_salida_aza` no rompe nada ni se trata como caso especial explícito -- degrada de forma natural**: la ventana colapsa a un instante, cuyo solape con cualquier detención es matemáticamente 0 (`_solape_minutos` exige `fin_solape > inicio_solape`, estrictamente), así que las señales de solape/continuidad (70% del score) quedan neutralizadas para todas las plantas por igual y sólo decide la proximidad temporal GPS (30%, señal deliberadamente débil) -- exactamente "reduce confianza, no rompe el análisis", sin necesitar ningún código nuevo.

**FASE 5 -- las 8 señales pedidas, verificadas contra el código real:**
- A (solapa fuertemente la ventana) → `PESO_SOLAPE_VENTANA=0.50`, dominante.
- B (visita termina cerca de hora_salida) → `PESO_PROXIMIDAD_SALIDA=0.15`, vía `_proximidad_score(salida_gps, hora_salida)`.
- C (visita empieza cerca de hora_entrada) → `PESO_PROXIMIDAD_ENTRADA=0.15`, simétrico.
- D (sólo una visita plausible) → `margen_vs_siguiente is None` (una sola candidata) → resuelve directo.
- E (dos visitas plausibles) → `margen_vs_siguiente < MARGEN_SCORE_SUFICIENTE=0.15` → `ORIGEN_GPS_CONFLICTO`.
- F (horas dudosas) → ver FASE 4, degrada solo, no rompe.
- G (visita a otra planta claramente después, tramo distinto) → solape=0 con la ventana de ESE documento → score bajo, pierde de forma natural (verificado con los 5 casos reales de FASE 6).
- H (múltiples viajes/día) → cada llamada a `resolver_planta_origen_gps` usa la ventana documental de SU PROPIO documento -- las 8 señales aplican independientemente por llamada.
Ninguna señal es un score arbitrario opaco: los 3 pesos y el margen de conflicto están documentados en el código con la evidencia real que los motivó (comentarios ya existentes, citados en el bloque de auditoría).

**FASE 6 -- búsqueda real del caso multiplanta mismo día, script de diagnóstico en TEMP (`diagnostico_visitas.py`, sólo lectura, nunca comprometido a git):** se copiaron a TEMP `analisis_completo_guias.csv`, `plantas.json`, `telemetria_cache.json`, `choferes.json`, `vehiculos.json` reales (mtimes de Drive capturados antes). Se enumeraron las 27 claves `onelogis|patente|fecha|fecha` cacheadas; para cada una, `detectar_detenciones` sobre TODOS los trips/breadcrumbs del día (sin ancla documental) + `_resolver_planta_para_detencion` contra las 2 plantas reales. **Resultado: 24/27 combinaciones con al menos una visita a planta detectada; 6/27 con visitas a AMBAS plantas el mismo día** -- `BDFG50 2026-08-11`, `AL1879 2026-08-13` (=464730), `AL1879 2026-08-06`, `BKYK63 2026-08-10`, `KN5439 2026-08-10`, `SB6486 2026-08-10`. Cruce contra las 43 guías reales: cada uno de los 5 (excluyendo 464730) tiene exactamente 1 guía documentada ese día, y las 5 quedaron correctamente asociadas a la planta real según `planta_origen_nombre` ya persistido:
| patente/día | guía | ventana documental | visita elegida | ¿coincide con la real? |
|---|---|---|---|---|
| BDFG50 11-08 | 464624 | 10:30–11:48 | COLINA 10:17–11:28 (Renca 09:55, 1 min, ruido) | Sí |
| AL1879 06-08 | 464395 | 12:44–15:17 | COLINA 14:14–15:25 (Renca 08:51–10:55, 124 min, real pero fuera de ventana) | Sí |
| BKYK63 10-08 | 464491 | 07:41–09:42 | COLINA 08:30–09:55 (Renca 10:13, después) | Sí |
| KN5439 10-08 | 464494 | 07:26–09:50 | COLINA 07:45–09:57 (Renca 10:16, después) | Sí |
| SB6486 10-08 | 464511 | 09:29–11:46 | COLINA 08:28–11:48 (Renca 07:59, 0.1 min, ruido) | Sí |

Caso destacado: **AL1879/José Lazcano (el mismo chofer y vehículo de 464730) ya había visitado Colina Y Renca el 2026-08-06, una semana antes** -- ese día el mecanismo SÍ discriminó correctamente (Colina, coincide con su ventana propia) pese a Renca tener 124 min reales esa misma mañana; una semana después, con 464730, la ventana documental rota (instante en vez de rango) le quita al mecanismo la señal que en 06-08 sí tenía disponible. **No se encontró ningún caso de DOS guías documentadas el mismo chofer/vehículo, plantas distintas, mismo día** entre los 43 documentos reales -- se reporta la ausencia explícitamente, tal como pide la instrucción ("buscarlo únicamente si ya está en los datos... si no puede identificarse con certeza: reportarlo y no asumir").

**FASE 7 -- control crítico 464730, reproducido con el mecanismo real (no simulado):** `reproducir_casos.py` (TEMP) llamó `resolver_planta_origen_gps` con `patente=AL1879, fecha=2026-08-13, hora_entrada=hora_salida=08:18` -- **resultado idéntico, carácter por carácter, al ya persistido**: `ORIGEN_GPS_CONFLICTO`, `CONFLICTO_REAL_EN_VENTANA(AZA_COLINA:score=0.1366,solape=0.0%;AZA_RENCA:score=0.0,solape=0.0%)`. Se agregó una réplica SINTÉTICA de este patrón exacto como test permanente (`test_ventana_documental_degenerada_464730_no_se_auto_resuelve_a_una_planta`, `test_origen_o2.py`) -- ver FASE 14.

**FASE 8/9/10 -- clasificación A/B/C/D sobre el histórico y relación con ORIGEN_NO_CONFIRMADO:** clasificación por lectura directa de columnas ya persistidas (`planta_origen_nombre` como fuente de verdad de si está resuelto -- no `estado_ruta`, que puede quedar con texto obsoleto, caso conocido 464522; luego `motivo_origen_gps` para diferenciar B/C/D):

| Clase | Definición | Cantidad | Guías |
|---|---|---|---|
| A -- ASOCIACION_INEQUIVOCA | `planta_origen_nombre` ya resuelto | 38 | -- |
| B -- ASOCIACION_SUGERIBLE | sin resolver, `DETENCION_REAL_FUERA_DE_TODA_GEOCERCA` (candidata cercana) | 2 | 464717, 464892 |
| C -- ASOCIACION_AMBIGUA | sin resolver, `CONFLICTO_REAL_EN_VENTANA` | 1 | 464730 |
| D -- SIN_EVIDENCIA_SUFICIENTE | sin resolver, sin patrón útil (`NINGUN_PUNTO_DENTRO_DE_GEOCERCA`, etc.) | 2 | 464479, 464529 |

Total 43. Coincide exactamente con lo ya conocido del bloque ORIGEN_NO_CONFIRMADO -- misma evidencia subyacente, ninguna sorpresa. **Relación con ORIGEN_NO_CONFIRMADO:** ya resuelta -- `detectar_decision_origen_no_confirmado` construye `candidatos`/`evidencias` leyendo `motivo_origen_gps` directamente, que es la salida textual de este mismo mecanismo (B → 1 candidato por proximidad ≤50 km; C → 2 candidatos por nombre en el conflicto). No hace falta ningún puente nuevo.

**FASE 11 -- impacto en origen, respuesta literal (el mecanismo ya está corriendo):** 38/43 ya resueltos hoy; 3/43 ya generan `ORIGEN_NO_CONFIRMADO` (464717/464892/464730); 2/43 sin evidencia (464479/464529). Cero llamadas a ORS en todo el bloque.

**FASE 12:** no se tocó ningún cálculo de ruta ni km.

**FASE 13 -- decisión de implementación:** **no se implementó código productivo nuevo.** Razonamiento explícito: (1) el modelo pedido ya existe con otro nombre, ya calibrado con evidencia real de bloques anteriores (`PESO_*`, `MARGEN_SCORE_SUFICIENTE`, `PROPORCION_MINIMA_DENTRO_POLIGONO` -- ninguno inventado en este bloque); (2) esta validación aporta evidencia FRESCA (6 casos multiplanta reales antes no verificados explícitamente bajo este enfoque, reproducción exacta de los 3 casos objetivo) que confirma que sigue funcionando correctamente, incluyendo el control crítico; (3) construir una clase `VisitaAPlanta` paralela sería infraestructura duplicada -- la instrucción explícita del proyecto ("no crear infraestructura paralela si la existente puede extenderse") aplica aquí con más fuerza que en ningún bloque anterior, porque lo existente no sólo "puede extenderse": ya ES la solución completa. Se optó, en su lugar, por **cerrar 2 huecos reales de cobertura de test** encontrados al auditar `test_origen_o2.py` contra los 12 casos mínimos pedidos en la instrucción:
1. Dos visitas separadas a la MISMA planta el mismo día -- no había ningún test que verificara que se elige la que solapa la ventana documental, no "la primera" ni "la más larga" por defecto.
2. El patrón exacto de 464730 (ventana degenerada + evidencia real para dos plantas) -- sólo estaba verificado contra datos reales de forma ad-hoc (este bloque), nunca como test sintético permanente.

**FASE 14 -- tests nuevos (`tests/test_origen_o2.py`, archivo ya existente, sin infraestructura paralela):**
- `test_dos_visitas_a_la_misma_planta_mismo_dia_elige_la_que_cae_en_la_ventana`: dos permanencias reales en AZA COLINA el mismo día (07:00–07:10 y 13:00–13:30) -- la guía con ventana 12:58–13:32 se asocia a la de la tarde, verificado por `hora_entrada_gps` devuelta.
- `test_ventana_documental_degenerada_464730_no_se_auto_resuelve_a_una_planta`: réplica sintética exacta del patrón 464730 (mismos horarios relativos: Colina 07:19–08:24, Renca 10:21–12:01, instante documental 08:18) -- protección de regresión permanente para el control crítico, sin depender de datos reales cacheados. (Nota de implementación: los puntos estacionarios sintéticos deben mantenerse pocos/con paso temporal amplio -- con `n=66` puntos y el mismo paso de la utilidad `_puntos_estacionarios` la deriva acumulada sacaba los puntos del polígono de prueba, ocultando la detención de Colina por completo; corregido a `n=7`/`n=11` con `paso_seg` ajustado, mismo orden de magnitud que el resto del archivo.)
- Los 10 casos restantes de la lista de 12 ya estaban cubiertos por los 12 tests preexistentes de `test_origen_o2.py` (visita única por planta, dos visitas mismo día a plantas distintas dentro/fuera de ventana, conflicto real, estadía prolongada domina punto aislado, una sola hora documental, sin hora documental, multiguía mismo transporte) y por `test_origen_no_confirmado.py` (candidatos/evidencia correctos hacia `ORIGEN_NO_CONFIRMADO`, no heredar planta entre viajes vía la jerarquía `CONFIRMACION_HUMANA`/consolidación de viaje).
**Suite `test_origen_o2.py`: 14 passed (0 failed).** **Suite completa Motor: 1291 passed, 0 failed** (baseline 1289+2).

**FASE 15:** Drive no tocado (mtimes verificados idénticos al cierre, incluye `choferes.json`/`vehiculos.json` copiados nuevos en este bloque). Desktop no modificado en este bloque (los cambios de FASE 0 ya están publicados en su propio commit).

**Drive:** no modificado. **Desktop:** no modificado en este bloque. **Git:** Motor con `tests/test_origen_o2.py` (2 tests nuevos) y las tres bitácoras, sin commit. **Sin push del bloque funcional -- instrucción explícita.** **ORS: 0 llamadas. Onelogis red: 0 llamadas. OCR: no se re-ejecutó.**

**Estado: MODELO VISITA_A_PLANTA VALIDADO -- LISTO PARA REVISIÓN CON JAVIER.**

## Bloque CIERRE VISITA_A_PLANTA + APLICACIÓN REAL DE CONFIRMACIONES DE ORIGEN -- 2026-08-19

**FASE 0:** `git rev-parse HEAD`/`git status --short` en ambos repos, no asumido -- Motor `d5adb2eba04b180f846077bb6d2ef3044e5810c5`, working tree exactamente `docs/BITACORA_EJECUTIVA.md`, `docs/BITACORA_TECNICA_CRONOLOGICA.md`, `docs/HANDOFF_ATLAS.md`, `tests/test_origen_o2.py` (M). Desktop `a34059fda3dce11351257370a9c33a84d020c9af`, limpio. `pytest tests/test_origen_o2.py -q` → 14 passed. `pytest tests/ -q` → **1291 passed, 0 failed** (coincide con lo esperado, sin sorpresas). Commit `git commit -m "test: cubrir asociaciones de visitas a planta"` → `d7c5694`. `git push origin lector-mvp-guia-nueva` → `d5adb2e..d7c5694`. Verificado `git rev-parse HEAD @{u}` -- ambos `d7c5694...`, idénticos. Desktop no tocado.

**FASE 1 -- preparación (Drive real, raíz `G:\Mi unidad\Atlas`):**
```
from atlas_core.revalidacion_documental import reconciliar_decisiones_origen
resultado = reconciliar_decisiones_origen(raiz_atlas=r"G:\Mi unidad\Atlas")
```
→ `decisiones_candidatas=3`, `decisiones_publicadas=18` (15 preexistentes de `OBRA_DESCONOCIDA`/`VEHICULO_DESCONOCIDO` + 3 nuevas). `decision_id` de las 3 nuevas: `5a65c1d3588e6c259708f1cbc8c0514016888988a6bbfbe08fb08075075095eb` (464717), `d2f97edbb02a52bbbf72b6c93f867ab174635c9a038144f88f93b8bf1085d658` (464730), `a285589cc3c78a3560b0d87a5573c44f2e36238c6701ca6c848d94b2f4572c53` (464892) -- **idénticos, carácter por carácter, a los ya calculados y validados en TEMP en el bloque de implementación de `ORIGEN_NO_CONFIRMADO`** (evidencia determinista, cero deriva desde entonces). Verificado `CatalogoPlantas(...).listar()` real: AZA COLINA y AZA RENCA, ambas `estado_calidad=CONFIRMADA`, `estado_vigencia=ACTIVA`. Confirmado programáticamente: `'464479' not in guias_con_decision` y `'464529' not in guias_con_decision`.

**FASE 2 -- backup (antes de cualquier escritura de aplicación):** `respaldos/ORIGEN_HUMANO_ROLLBACK_PRE_APLICACION_20260819_115529/operacion_actual/` con copia de `analisis_completo_guias.csv`, `estado_operacion.json`, `decisiones_pendientes.json`, `decisiones_aplicadas.json` (los 4 archivos que `aplicar_decision_obra`+regeneración de reporte pueden tocar). SHA-256 de cada archivo calculado y comparado contra el original -- **los 4 coinciden exactamente** antes de escribir `MANIFIESTO_SHA256.txt`. `LEEME_ROLLBACK.md` con contexto del bloque, qué va a cambiar, y procedimiento de reversión de 6 pasos. Ningún backup anterior (`RESOLUCION_DESTINOS_A_...`, `RECALCULO_RUTAS_KM_...`, etc.) tocado.

**FASE 3 -- dry-run real en TEMP, mecanismo publicado:** copia de Drive (post-regeneración de bandeja de FASE 1) a scratchpad de sesión. Para cada guía: `aplicar_decision_obra(raiz_atlas=TEMP, decision_id=..., accion="SELECCIONAR_OTRA_PLANTA", planta_id_elegida=<uuid de la planta>, actor="JAVIER_MBT")`. Los tres `ok=True`, `idempotente=False`, `reporte_regenerado=True`; `planta_nombre` devuelto: AZA COLINA / AZA COLINA / AZA RENCA. Verificación de fila completa (43 filas, comparación diccionario a diccionario contra el estado antes de aplicar): **exactamente 3 filas distintas, y las columnas distintas en cada una son exactamente `{planta_origen_id, planta_origen_nombre, origen_determinado_por, evidencia_origen}`** -- ninguna fila ni columna adicional. `motivo_origen_gps` de las 3 filas verificado idéntico antes/después (evidencia GPS nunca se toca). Ledger de la copia TEMP: 3 aplicaciones, `actor=JAVIER_MBT`, `fuente=CONFIRMACION_HUMANA`, `evidencia_previa` y `valor_anterior` poblados correctamente. Sin sorpresas -- se procedió a Drive real.

**FASE 4 -- aplicación real (Drive, no TEMP):** mismas 3 llamadas a `aplicar_decision_obra`, esta vez con `raiz_atlas=r"G:\Mi unidad\Atlas"`. Resultado: `464717 -> True AZA COLINA reporte_regenerado=True idempotente=False`, `464892 -> True AZA COLINA reporte_regenerado=True idempotente=False`, `464730 -> True AZA RENCA reporte_regenerado=True idempotente=False`. Verificación post-aplicación (fila completa, comparación contra el backup SHA-256-verificado de FASE 2): **exactamente las mismas 3 filas y las mismas 4 columnas del dry-run cambiaron en Drive real** -- comparación programática, no muestreo visual. `464479`/`464529`: comparación de diccionario completo contra el backup → `True` (idénticos). Ledger real: 13 aplicaciones totales (10 preexistentes de otros bloques + 3 nuevas de origen). Mtime de `plantas.json`, `clientes.json`, `obras_destinos.json`, `destinos_maestros.json`, `vehiculos.json`: idénticos al inicio del bloque -- catálogos no tocados.

**FASE 5 -- reevaluación de destinos, exclusivamente con `resolver_destino_ambiguo_con_evidencia_inequivoca` (ya publicado), sin regla nueva:**

Para reproducir Vía A sin llamar red innecesariamente, se ubicó el proveedor real de geocodificación con caché ya usado en producción (`ProveedorRutasConCacheGeocodificacion(OpenRouteService(pais="CL"), RepositorioCacheGeocodificacion())`, `atlas_core/rutas/cache_geocodificacion.py`) apuntando al `geocodificacion_cache.json` real (`G:\Mi unidad\Atlas\cache\geocodificacion\`).

- **464892** (`despachar_a_crudo="SANTA ISABEL 585 SANTIAGO LAMPA"`): `resolver_destino_entrega(...)` → `REVISAR`/`MULTIPLES_UBICACIONES_DISPERSAS(5)` (igual que antes de este bloque -- el origen no cambia la geocodificación). Reconstrucción manual del camino interno de Vía A (mismo texto/consulta que construye `resolver_destino_entrega`: `normalizar_direccion_con_comunas(texto) + ", Chile"`, verificado cache-hit -- **0 llamadas de red**, la dirección ya estaba cacheada de un bloque anterior con 5 candidatos): `_candidatos_con_soporte_textual` reduce a 4; `CatalogoDestinos(destinos_maestros.json).listar()` real trae el destino `51b4cd04-0c4c-41f1-9fd2-3da535148c24` ("SANTA ISABEL 585, LAMPA, CHILE", `estado_calidad=CONFIRMADO`, `estado_vigencia=ACTIVO`, `cliente_id` de ARMACERO MATCO SA -- confirmado que 464892 es del mismo cliente, `cliente="ARMACERO MATCO SA"` en el CSV) cuyas coordenadas (`lat=-33.310665, lon=-70.737609`) coinciden EXACTAMENTE con uno de los 4 candidatos con soporte textual. `resolver_destino_ambiguo_con_evidencia_inequivoca(...)` → **`resuelto=True`, `motivo="CATALOGO_CONFIRMADO_COINCIDE_GEOCODIFICACION"`** -- mismo destino que ya respalda 3 viajes hermanos (`0000352802`, `0000352780`, `0000353091`, todos `motivo_ruta=RESUELTO_EVIDENCIA_INEQUIVOCA(CATALOGO_CONFIRMADO)` de un bloque anterior).
- **464730:** ya `estado_entrega=RESUELTO` (`direccion_entrega="Maipú, RM, Chile"`) de un bloque anterior -- no requería Clase A, sólo confirmar lectura del estado persistido.
- **464717** (`despachar_a_crudo="CAMINO A MELIPILLA 10800 SANTIAGO MAIPU"`): `resolver_destino_entrega(...)` → `REVISAR`/`MULTIPLES_UBICACIONES_DISPERSAS(5)`, sin cambios respecto al estado ya conocido. **No se ejecutó Clase A para este caso** (instrucción explícita: "si continúa ambiguo, no intentar resolverlo mediante una regla nueva, dejarlo bloqueado" -- Clase A es una vía adicional, no aplicada aquí por alcance de la instrucción, no por limitación técnica). Sin escritura.

**FASE 6 -- dry-run ORS real, detectado programáticamente (no asumido "exactamente dos"):** de los 3 casos evaluados en FASE 5, exactamente 2 cumplían el criterio (origen confirmado + destino resuelto sin conflicto documental bloqueante): 464730 y 464892. Llamadas reales:
```
calcular_ruta_con_planta_conocida(planta=renca, despachar_a_crudo="CAMINO A MELIPILLA 10B00 SANTIAGO MAIPU", proveedor_rutas=<cache-wrapped ORS>, origen_determinado_por="CONFIRMACION_HUMANA", evidencia_origen="DECISION_HUMANA:d2f97edb...")
→ estado_ruta=RUTA_CALCULADA, distancia_km=20.1763, duracion_min=27.205, proveedor=openrouteservice
```
```
# 464892: coordenada_origen = coordenada_ruteo_planta(colina); coordenada_destino = candidato Clase A (-33.310665,-70.737609)
proveedor.calcular_ruta(coordenada_origen, coordenada_destino, "driving-hgv")
→ estado=RUTA_CALCULADA, distancia_km=6.5048, duracion_min=10.8467
```
Ambos resultados coherentes (distancia positiva, plausible geográficamente -- Colina/Lampa están próximos, ~6.5 km; Renca/Maipú ~20 km -- proveedor real, sin `RESPUESTA_INVALIDA` ni error). Ninguno se descartó.

**FASE 7 -- aplicación de ruta/km, sin recalcular:** escritura vía `_leer_filas`/`_escribir_filas_completas` (mismo primitivo usado en toda la aplicación de origen de este bloque) de exactamente los 9 campos de `CAMPOS_ENTREGA_DOCUMENTO` relevantes (`direccion_entrega`, `localidad_entrega`, `region_entrega`, `estado_entrega`, `distancia_km`, `duracion_min`, `proveedor_ruta`, `estado_ruta`, `motivo_ruta`) para las 2 filas, usando los valores YA calculados en FASE 6 -- **cero llamadas ORS adicionales en este paso.** Nota de arquitectura, registrada honestamente: no existe hoy una función canónica análoga a `aplicar_decision_obra` para aplicar una resolución Clase A de destino a una fila ya procesada (a diferencia de origen, que sí tiene ese mecanismo desde el bloque `ORIGEN_NO_CONFIRMADO`) -- la escritura se hizo con los mismos primitivos de I/O ya confiables (`_leer_filas`/`_escribir_filas_completas`), en un script auditado y verificado paso a paso, no edición manual del archivo. Reporte regenerado: `generar_reporte_viajes(...)` + `escribir_estado_operacion(...)` → `reportes/reporte_revalidacion_20260819_160555_130539/`.

**FASE 8 -- validación final:** cobertura antes/después (lectura de las 43 filas del backup vs. Drive real): **con_origen 38→41, sin_origen 5→2; con_km 19→21, sin_km 24→22.** Verificación de integridad completa: comparación fila-por-fila de las 43 filas -- 464717 con 4 columnas distintas (origen), 464730 con 9 (origen + ruta), 464892 con 13 (origen + destino + ruta) -- ninguna otra fila, ningún campo documental. `viajes.csv` del reporte nuevo confirma los 3 casos con los valores exactos ya reportados en FASE 4/6/7.

**Nota de transparencia (efecto secundario no anticipado, reportado explícitamente):** al ejecutar `resolver_destino_entrega` para 464717 en FASE 5 (pensado como verificación de sólo lectura), la dirección `"CAMINO A MELIPILLA 10800 SANTIAGO MAIPU"` no estaba cacheada (a diferencia de la variante `10B00` de 464730, que sí lo estaba) -- se disparó UNA llamada real de **geocodificación** (Pelias vía OpenRouteService, endpoint distinto al de ruteo/directions) que quedó cacheada (`geocodificacion_cache.json` pasó de 31 a 32 entradas, verificado por diff explícito de claves). El resultado (`MULTIPLES_UBICACIONES_DISPERSAS(5)`) es idéntico al ya conocido -- no se escribió nada para 464717, no afecta ninguna decisión tomada. Se documenta con transparencia porque no estaba anticipado como llamada de red al planear la FASE 5 como "sólo verificación"; no es una llamada de ruteo (ORS/directions), que se mantuvieron exactamente en las 2 explícitamente autorizadas por FASE 6 (464730, 464892).

**FASE 9:** sin cambios de código Desktop. `viajes.csv` del reporte usa `COLUMNAS_VIAJES`, el mismo esquema que Desktop ya consume sin cambios de contrato -- generado por el mismo `generar_reporte_viajes` de siempre.

**Drive:** modificado -- `analisis_completo_guias.csv` (3 filas), `estado_operacion.json`, `decisiones_pendientes.json` (3 decisiones cerradas, 15 preexistentes intactas), `decisiones_aplicadas.json` (+3), nuevo directorio de reporte, `geocodificacion_cache.json` (+1 entrada, efecto secundario de sólo lectura documentado arriba). Catálogos: sin cambios (mtimes verificados). **Desktop:** no modificado en este bloque. **Git:** commit documental de cierre de este bloque (ver más abajo). **ORS (ruteo/directions): 2 llamadas reales, ambas autorizadas y reportadas (FASE 6). Geocodificación: 1 llamada real no anticipada (464717, sin efecto en datos persistidos, reportada arriba). Onelogis red: 0 llamadas. OCR: no se re-ejecutó.**

**Estado: CONFIRMACIONES HUMANAS DE ORIGEN APLICADAS + ESTADO OPERACIONAL REGENERADO -- LISTO PARA VALIDACIÓN VISUAL DE JAVIER.**

## Bloque AUDITORÍA INTEGRAL DE LAS 15 REVISIONES PENDIENTES + ESTADO DE RUTA 464717 -- 2026-08-19

**FASE 0:** `git rev-parse HEAD`/`git status --short` en ambos repos -- Motor `ace860834e5caaf4bb681479edc9b8c91ba590c9`, local=remoto, limpio. Desktop `a34059fda3dce11351257370a9c33a84d020c9af`, local=remoto, limpio. Sin sorpresas -- se continúa. 100% diagnóstico desde aquí, Drive tratado como read-only salvo por lecturas.

**FASE 1 -- inventario exacto (artefacto real, no lo que muestra Desktop):** `json.load(decisiones_pendientes.json)` -- `schema_version=1`, **`dataset_sha256=BAC093AB...`**, `catalogos_sha256={clientes, vehiculos, obras_destinos, destinos_maestros}`, **15 decisiones**. Verificación de obsolescencia: `hashlib.sha256(analisis_completo_guias.csv real)` = `5BE01790...` -- **NO coincide con el `dataset_sha256` del artefacto**. Causa raíz identificada: en el bloque anterior, la escritura de `direccion_entrega`/`distancia_km`/etc. para 464730/464892 se hizo vía `_leer_filas`/`_escribir_filas_completas` directamente, sin volver a llamar `generar_artefacto` (que es lo único que actualiza `dataset_sha256` en el artefacto) -- consecuencia esperada del diseño, no un bug nuevo. Efecto verificado: cualquier intento de `aplicar_decision_obra` sobre estas 15 decisiones hoy dispararía `DecisionObsoletaError` (mismo mecanismo de protección ya probado en bloques anteriores) -- seguro, pero requiere reconciliación previa.

Tabla completa de las 15 (orden real del artefacto, cruzado contra el dataset real vía `numero_guia`):

| N° | Guía | Transporte | Chofer | Tipo | Campo | Valor documental | Motivo |
|---|---|---|---|---|---|---|---|
| 1 | 464036 | 0000350797 | PATRICK ORTIZ | VEHICULO_DESCONOCIDO | patente_tracto | XF3662 | SIN_VEHICULO_CONFIRMADO_COMPATIBLE |
| 2 | 464036 | 0000350797 | PATRICK ORTIZ | OBRA_DESCONOCIDA | obra_destino | CONSTRUCTORA CERRO APOQUINDO | OBRA_NO_EXISTE_PARA_CLIENTE |
| 3 | 464170 | 0000351177 | IVAN ROA | VEHICULO_DESCONOCIDO | patente_tracto | TVXJ33 | SIN_VEHICULO_CONFIRMADO_COMPATIBLE |
| 4 | 464170 | 0000351177 | IVAN ROA | VEHICULO_DESCONOCIDO | patente_rampla | PXHH32 | SIN_VEHICULO_CONFIRMADO_COMPATIBLE |
| 5 | 464170 | 0000351177 | IVAN ROA | OBRA_DESCONOCIDA | obra_destino | SUPERMERCADO SEÑOR DE LOS MI (truncado OCR) | OBRA_NO_EXISTE_PARA_CLIENTE |
| 6 | 464264 | 0000351135 | CARLOS SIMON | VEHICULO_DESCONOCIDO | patente_rampla | JD6659 | SIN_VEHICULO_CONFIRMADO_COMPATIBLE |
| 7 | 464265 | 0000351135 | CARLOS SIMON | VEHICULO_DESCONOCIDO | patente_tracto | VP6521 | SIN_VEHICULO_CONFIRMADO_COMPATIBLE |
| 8 | 464265 | 0000351135 | CARLOS SIMON | VEHICULO_DESCONOCIDO | patente_rampla | JD0659 | SIN_VEHICULO_CONFIRMADO_COMPATIBLE |
| 9 | 464395 | 0000351884 | JOSE LAZCANO | OBRA_DESCONOCIDA | obra_destino | ING Y METALURGICA INGEMETA | OBRA_NO_EXISTE_PARA_CLIENTE |
| 10 | 464488 | 0000352219 | PATRICIO VILLAGRA MUÑOZ | OBRA_DESCONOCIDA | obra_destino | CONSTRUCTORA E INMOBILIARIA | OBRA_NO_EXISTE_PARA_CLIENTE |
| 11 | 464491 | 0000352203 | LEANDRO TOLEDO | OBRA_DESCONOCIDA | obra_destino | CONSTRUCTORA ALTIUS SPA | OBRA_NO_EXISTE_PARA_CLIENTE |
| 12 | 464493 | 0000352242 | CRISTOPHER RETAMAL | OBRA_DESCONOCIDA | obra_destino | EMPRESA CONST SIGRO SA | OBRA_NO_EXISTE_PARA_CLIENTE |
| 13 | 464854 | 0000353471 | CARLOS FARIAS | VEHICULO_DESCONOCIDO | patente_tracto | TVKT21 | SIN_VEHICULO_CONFIRMADO_COMPATIBLE |
| 14 | 464854 | 0000353471 | CARLOS FARIAS | VEHICULO_DESCONOCIDO | patente_rampla | PXHH31 | SIN_VEHICULO_CONFIRMADO_COMPATIBLE |
| 15 | 464854 | 0000353471 | CARLOS FARIAS | OBRA_DESCONOCIDA | obra_destino | CONST GRUPO COLOSO LTDA | OBRA_NO_EXISTE_PARA_CLIENTE |

`candidatos: []` y `identidad_resuelta: None` en las 15 -- confirmado que ni `VEHICULO_DESCONOCIDO` ni `OBRA_DESCONOCIDA` cargan hoy ninguna sugerencia, a diferencia de `ORIGEN_NO_CONFIRMADO`. `acciones_permitidas` idéntico en las 15: `[REGISTRAR, NO_REGISTRAR, POSPONER]`.

**FASE 2 -- contraste con la revisión visual de Javier:**

**Desfase de numeración confirmado:** la numeración real (tabla arriba) coincide con la de Javier para los ítems 1-7 y 9-15, **excepto el 8** -- Javier lo marcó como "no identificado", pero es la tercera decisión de Carlos Simón (464265, rampla JD0659), no un caso aparte. Se registra explícitamente porque la instrucción pidió no asumir la numeración de Javier como fuente de verdad.

**Ítem 1 -- Ortiz (464036, patente_tracto=XF3662):** `grep` del chofer "PATRICK ORTIZ" / RUT `18626166-6` contra las 43 filas -- una sola coincidencia adicional: 464740 (`tracto=XF3629`). `XF3629` SÍ está en `vehiculos.json` (`CAMION_RIGIDO`, `CONFIRMADO`, `ACTIVO`) -- pero es un tipo de vehículo distinto (camión rígido, no tracto de una combinación tracto+rampla) y difiere en 2 dígitos de XF3662 (no 1, como los casos de Carlos Simón) -- **no se reporta como candidata inequívoca**, sólo como posible, tal como exige la instrucción. Javier confirma independientemente que es error documental del mandante -- no se sustituye esa confirmación por la inferencia.

**Ítems 6/7/8 -- Carlos Simón, hallazgo central del bloque:** `grep` de RUT `15.489.424-1` (con y sin puntos) contra las 43 filas -- **5 guías totales**: 464264 (tracto=VP8521, rampla=JD6659), 464265 (tracto=VP6521, rampla=JD0659, **fecha documental "05-08-2024" -- año con probable error de OCR/tipeo, no relevante para esta auditoría pero registrado**), y **464698/464699/464700 (mismo transporte 0000352376, 12-08-2026): las 3 con `tracto=VP8521, rampla=JE8659` idénticos, limpios, sin variación.** `vehiculos.json` confirma **VP8521 (TRACTO, CONFIRMADO, ACTIVO, confirmado por Javier el 2026-08-13) y JE8659 (CARRO, CONFIRMADO, ACTIVO, mismo actor/fecha)** -- ningún registro para "JD8659" (lo que Javier recordaba). Conclusión con evidencia: las 3 decisiones pendientes (JD6659, VP6521, JD0659) son variantes OCR de esas 2 patentes ya confirmadas, corroboradas independientemente por otro transporte completo (3 documentos limpios). La discrepancia de 1 letra entre "JD8659" (Javier) y "JE8659" (catálogo real) se reporta explícitamente, sin resolverla unilateralmente.

**Ítem 5 -- Supermercado Señor de los Milagros (464170):** búsqueda en `decisiones_aplicadas.json` (13 aplicaciones reales) por `numero_guia==464170` o texto "MILAGRO"/"SUPERMERCADO" -- **0 coincidencias**. Búsqueda en `obras_destinos.json` (15 obras) -- ninguna con nombre similar; la única obra del cliente EBEMA SA (`fb859a71`) es literalmente "EBEMA SA" (nombre del cliente, no de esta obra). Búsqueda en las 43 filas del dataset por "MILAGRO"/"SUPERMERCADO" -- **sólo 464170 misma**, ninguna otra guía relacionada. **No hay evidencia de que esta decisión específica haya sido aplicada antes** -- se reporta la discrepancia con la memoria de Javier sin asumir ninguna conclusión en su nombre (ni "obsoleta", que requeriría evidencia de aplicación previa que no existe; ni descartar su recuerdo sin más).

**Ítem 12 -- "EMPRESA CONST SIGRO SA" (464493), segundo hallazgo mayor:** `obras_destinos.json` filtrado por `cliente_id=='9d2adc8d-...'` (PRODALAM SA, mismo cliente de la decisión) -- **existe la obra `9684d894-...` con `nombre_canonico="EMPRESA CONST SIGRO"` (sin "SA"), `estado=CONFIRMADA`, evidenciada con la guía real 464550 y una `CONFIRMACION_HUMANA` de `JAVIER_DESKTOP` el 2026-08-17.** `normalizar_nombre_obra()` (`atlas_core/catalogo_obras_destinos.py`) confirmado por lectura de código: sólo quita diacríticos, mayúsculas y tokeniza alfanumérico -- **no elimina sufijos corporativos** ("SA", "LTDA", "SPA"), así que "EMPRESA CONST SIGRO SA" normaliza distinto de "EMPRESA CONST SIGRO" y el match exacto falla. **Javier había agrupado este ítem entre "obras a registrar" -- la evidencia contradice esa clasificación visual: no es una obra nueva, es la misma obra ya confirmada con un sufijo de más.**

**Ítems 2/3/4/9/10/11/13/14/15 -- verificados contra catálogo, ninguna coincidencia cercana:** para cada uno se filtró `obras_destinos.json`/`vehiculos.json` por el `cliente_id`/prefijo de patente correspondiente -- ningún caso reprodujo el patrón de ítem 12 (ninguna obra/vehículo ya confirmado con nombre casi idéntico bajo el mismo cliente). Ítem 10 (`CONSTRUCTORA E INMOBILIARIA`, cliente EASY RETAIL) es el más cercano a un falso positivo -- el cliente ya tiene 2 obras confirmadas ("INMOBILIARIA Y CONSTRUCTORA TERRATEC LIMITADA", "EMPRESA CONSTRUCTORA MENA Y") con palabras en común, pero **ninguna comparte el nombre propio distintivo** (ni "TERRATEC" ni "MENA" aparecen en el texto documental) -- se reporta como probablemente nueva, pero con la advertencia explícita de que el texto documental es genérico y no permite descartar un duplicado con certeza absoluta. Los demás (2,3,4,9,11,13,14,15) no presentan ninguna ambigüedad -- confirmados como nuevos sin reservas.

**FASE 3 -- auditoría de `NO_REGISTRAR` (trazado de código real, 0 precedentes en el ledger real hasta hoy):**
1. `aplicar_decision_obra`, rama `elif tipo == "VEHICULO_DESCONOCIDO":` -- el bloque `if accion == "REGISTRAR":` (líneas 335-361) es el ÚNICO que escribe catálogo (`confirmar_vehiculo`); con `accion="NO_REGISTRAR"` ese bloque completo se salta -- `tipo_final=None`, `vehiculo_id=None` -- **cero escritura de catálogo, cero escritura de CSV.**
2. Sí -- se construye `aplicacion` (líneas 362-369) con `decision_id`, `tipo`, `accion="NO_REGISTRAR"`, `actor`, `fecha`, `documento`, `campo`, `valor_documental` -- se agrega a `decisiones_aplicadas.json` igual que cualquier otra acción.
3. No inmediatamente en el archivo que Desktop ya tiene abierto, pero sí en la PRÓXIMA regeneración de la bandeja (`generar_artefacto`) -- el mismo ciclo que ya se dispara tras cualquier aplicación.
4. Sólo si la evidencia cambia (nuevo `valor_documental`/campos que entran en el hash) -- nunca con la evidencia idéntica.
5. `generar_artefacto` (línea ~781): `ids_terminales = {decision_id para aplicaciones con accion in (REGISTRAR, NO_REGISTRAR, CONFIRMAR, NO_CONFIRMAR, ...)}` -- confirmado por lectura de código que `NO_REGISTRAR` SÍ está en ese conjunto terminal, igual que `REGISTRAR`. Si el `decision_id` (determinista, hash de tipo+documento+campo+valor+evidencias) es idéntico, `generar_artefacto` lo filtra y nunca vuelve a publicarse. Si difiere (nueva OCR con texto distinto), es un `decision_id` NUEVO, no protegido por el filtro -- Atlas correctamente vuelve a preguntar (evidencia nueva, no la misma pregunta).
6. Parcial: el ledger registra QUE se rechazó ese string exacto, con actor/fecha -- pero no CAPTURA el motivo humano (p. ej. "es un error documental del mandante" vs "simplemente no existe") ni ofrece ningún campo para asociarlo a una entidad alternativa.
7. **No existe hoy.** `ACCIONES_POR_TIPO["VEHICULO_DESCONOCIDO"]` = `{REGISTRAR, NO_REGISTRAR, POSPONER}` únicamente -- no hay una acción tipo `USAR_CANONICA`/`SELECCIONAR_OTRA` para vehículos u obras (sí existe para origen: `SELECCIONAR_OTRA_PLANTA`).
8. **No, para vehículos/obras.** Sí, para origen -- `ORIGEN_NO_CONFIRMADO` ya conserva exactamente esa tupla completa (documental + canónico + evidencia + actor + timestamp + motivo) en su ledger. La infraestructura existe, simplemente no está conectada a `VEHICULO_DESCONOCIDO`/`OBRA_DESCONOCIDA` todavía.

**FASE 4 -- modelo documental vs canónico:** confirmado por auditoría de código (no repetido aquí en detalle, ver FASE 3.7/3.8) que el patrón `VALOR_DOCUMENTAL` + `candidatos` (sugerencia, nunca autocorrección) + acción de confirmación humana + ledger con `valor_anterior`/`evidencia_previa` + protección de obsolescencia + filtrado terminal **ya existe end-to-end y está probado en producción** -- es literalmente `ORIGEN_NO_CONFIRMADO` (bloques anteriores, `1291 passed` incluye su cobertura). Para vehículos, la pieza que falta es una función de detección análoga a `detectar_decision_origen_no_confirmado` pero basada en **asociación histórica por RUT de chofer** (no por proximidad geográfica) -- p. ej. "el mismo RUT ya tiene una patente CONFIRMADA/ACTIVA en catálogo, distinta de la leída en este documento -- sugerirla como candidata, nunca autoaplicarla". Para obras, análogamente, tolerancia a sufijos corporativos (o un catálogo de alias) al comparar contra obras ya `CONFIRMADA` del mismo cliente. Ambas son extensiones del mismo patrón ya validado, no una arquitectura nueva -- **no implementadas en este bloque, por instrucción explícita.**

**FASE 8 -- 464717, trazado exacto del texto obsoleto:**
```
analisis_completo_guias.csv (fila 464717):
  planta_origen_nombre=AZA COLINA, origen_determinado_por=CONFIRMACION_HUMANA   (correcto, bloque anterior)
  estado_entrega=REVISAR, direccion_entrega=""                                  (correcto, ya lo era antes)
  distancia_km="", duracion_min="", proveedor_ruta=""                           (correcto -- destino sin resolver)
  estado_ruta=ORIGEN_NO_DETERMINADO, motivo_ruta=ORIGEN_GPS_ESTADIA_SIN_PLANTA   (OBSOLETO -- describe un origen que ya no es cierto)
```
Confirmado también en `viajes.csv` del reporte vigente (mismos valores, columna por columna) -- el problema no es de Desktop ni de la consolidación de viaje, está en el dataset documental mismo. Causa exacta: la rama `ORIGEN_NO_CONFIRMADO` de `aplicar_decision_obra` (bloque anterior, ver comentario en el propio código: "sólo cambian las 4 columnas de origen canónico") escribe únicamente `planta_origen_id`/`planta_origen_nombre`/`origen_determinado_por`/`evidencia_origen` -- por diseño deliberado, nunca toca `estado_ruta`/`motivo_ruta`/`distancia_km` (evitar disparar ORS automáticamente). Es el MISMO patrón ya documentado para 464522 (origen resuelto por `TELEMETRIA_GPS`, `estado_ruta` nunca refrescado) -- confirmado releyendo esa fila real: `planta_origen_nombre=AZA COLINA, estado_ruta=ORIGEN_NO_DETERMINADO, motivo_ruta=SIN_EVIDENCIA_GPS` -- idéntico patrón. **464479** también sigue mostrando `estado_ruta=ORIGEN_NO_DETERMINADO` pero en su caso el origen SÍ sigue genuinamente sin determinar -- no es "obsoleto" en su caso, es el enmascaramiento puro ya conocido (motivo de origen oculta un `estado_entrega=REVISAR` igual de real). **464892**, en cambio, ya NO exhibe el bug -- `estado_ruta=RUTA_CALCULADA` -- porque en el bloque anterior se le aplicó también la resolución de destino/ruta en el mismo paso, lo que de rebote también refrescó estas columnas (efecto colateral de esa escritura manual, no una reparación general). **Recuento actualizado: 3 viajes afectados hoy (464479, 464522, 464717)**, no 4 -- el bloque anterior corrigió 464892 sin proponérselo explícitamente como fix de esta deuda. Estado correcto esperado para 464717 si se recalculara honestamente hoy (sin forzar RUTA_CALCULADA, que sería falso mientras el destino siga ambiguo): `estado_ruta=REQUIERE_REVISION`, `motivo_ruta=MULTIPLES_UBICACIONES_DISPERSAS(5)` -- el mismo texto que ya produce `resolver_destino_entrega` para esta dirección, confirmado en el bloque anterior.

**FASE 9 -- clasificación final (A-F, ver definiciones en el encabezado del bloque):**

| N° | Guía | Chofer | Tipo | Valor documental | Estado canónico | Clase | Acción de Javier | ¿Atlas resuelve hoy? | ¿Requiere fix antes? |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 464036 | P. Ortiz | VEHICULO | XF3662 (tracto) | XF3629 conocido pero no inequívoco | E | Confirmar NO_REGISTRAR (ya decidido) | Parcial -- NO_REGISTRAR sí, sin matiz | No indispensable |
| 2 | 464036 | P. Ortiz | OBRA | CONSTRUCTORA CERRO APOQUINDO | No existe | A | REGISTRAR | Sí | No |
| 3 | 464170 | I. Roa | VEHICULO | TVXJ33 (tracto) | No existe | A | REGISTRAR | Sí | No |
| 4 | 464170 | I. Roa | VEHICULO | PXHH32 (rampla) | No existe | A | REGISTRAR | Sí | No |
| 5 | 464170 | I. Roa | OBRA | SUPERMERCADO SEÑOR DE LOS MI | Sin evidencia de resolución previa | E | Aclarar con Javier antes de actuar | Sí, pero requiere su confirmación | No indispensable |
| 6 | 464264 | C. Simón | VEHICULO | JD6659 (rampla) | JE8659 confirmado | C | Confirmar canónica (no registrar como nueva) | No -- falta acción "usar canónica" | **Sí** |
| 7 | 464265 | C. Simón | VEHICULO | VP6521 (tracto) | VP8521 confirmado | C | Confirmar canónica | No | **Sí** |
| 8 | 464265 | C. Simón | VEHICULO | JD0659 (rampla) | JE8659 confirmado | C | Confirmar canónica | No | **Sí** |
| 9 | 464395 | J. Lazcano | OBRA | ING Y METALURGICA INGEMETA | No existe | A | REGISTRAR | Sí | No |
| 10 | 464488 | P. Villagra | OBRA | CONSTRUCTORA E INMOBILIARIA | No existe (probable) | A | REGISTRAR | Sí | No |
| 11 | 464491 | L. Toledo | OBRA | CONSTRUCTORA ALTIUS SPA | No existe | A | REGISTRAR | Sí | No |
| 12 | 464493 | C. Retamal | OBRA | EMPRESA CONST SIGRO SA | **EMPRESA CONST SIGRO confirmada** | C | Confirmar canónica (no registrar como nueva) | No -- mismo gap que vehículos | **Sí** |
| 13 | 464854 | C. Farias | VEHICULO | TVKT21 (tracto) | No existe | A | REGISTRAR | Sí | No |
| 14 | 464854 | C. Farias | VEHICULO | PXHH31 (rampla) | No existe | A | REGISTRAR | Sí | No |
| 15 | 464854 | C. Farias | OBRA | CONST GRUPO COLOSO LTDA | No existe | A | REGISTRAR | Sí | No |

**Resumen: REGISTRAR legítimamente = 9 (2,3,4,9,10,11,13,14,15). CORRECCIÓN DOCUMENTAL→CANÓNICA = 4 (6,7,8,12). REQUIERE DECISIÓN HUMANA REAL = 2 (1,5). ENTIDAD YA EXISTENTE idéntica = 0. DECISIÓN OBSOLETA = 0. OTROS = 0. Total = 15.**

**FASE 10 -- propuesta conceptual (no implementada):** extender el patrón `ORIGEN_NO_CONFIRMADO` -- nuevo tipo o acción (`PATENTE_NO_HOMOLOGADA`/similar) que: detecte por asociación histórica de RUT de chofer una patente ya `CONFIRMADA` distinta a la leída (sugerencia, nunca autocorrección); ofrezca candidatos igual que origen; acción `USAR_CANONICA` (equivalente a `CONFIRMAR_PLANTA`) que preserve el valor documental, escriba la referencia a la patente canónica para ESE documento/viaje, y quede auditada en el ledger; análogamente para obras con tolerancia a sufijos corporativos. Además, reparar que cualquier confirmación de origen (`ORIGEN_NO_CONFIRMADO` o `revalidar_telemetria_sin_ocr`) dispare un refresco barato de `estado_ruta`/`motivo_ruta` (sin ORS) cuando el destino siga sin resolver, para que el texto exprese el bloqueo real vigente.

**Drive:** no modificado (0 escrituras; las únicas operaciones fueron lecturas de JSON/CSV reales). **Desktop:** no modificado. **Git:** sin commit, sin push, instrucción explícita. **Catálogos:** sin cambios. **Decisiones/ledger:** sin cambios -- ninguna de las 15 aplicada, ningún `NO_REGISTRAR` ejecutado.

**Estado: AUDITORÍA DE LAS 15 REVISIONES + ESTADO RUTA 464717 COMPLETADA -- LISTO PARA REVISIÓN CON JAVIER.**

## Bloque RECONCILIACIÓN DE REVISIÓN ATLAS + VEHÍCULO DOCUMENTAL/CANÓNICO + ESTADO DE RUTA + CONTADORES UX -- 2026-08-19

**FASE 0:** `git status`/`git rev-parse` -- Motor `fb8ba95ffaae104aaea14fd79747b2fea6f58cd2` limpio, Desktop `a34059fda3dce11351257370a9c33a84d020c9af` limpio. Sin sorpresas.

**Actualización de ground truth a mitad de bloque (mensaje de Javier):** la rampla real de Carlos Simón es **JD8659**, confirmada directamente con el chofer -- JE8659 (repetida 3 veces en el dataset) se trata explícitamente como posible error documental de un mandante, nunca como canónica por repetición. Instrucción explícita: no convertir JE8659 en canónica por aparecer repetida; auditar igual el origen de JE8659; **no registrar JD8659 en catálogo real en este bloque** si todavía no existe -- reportar el estado exacto.

**FASE 1 -- auditoría exhaustiva JD8659 vs JE8659, con imágenes reales:**
- `catalogos_privados/vehiculos.json` real: **VP8521** (`TRACTO`, `CONFIRMADO`, `ACTIVO`, confirmado por Javier 2026-08-13) y **JE8659** (`CARRO`, `CONFIRMADO`, `ACTIVO`, mismo actor/fecha) -- **ningún registro para "JD8659"**.
- Ledger (`decisiones_aplicadas.json`): 0 aplicaciones relacionadas a estas guías -- el ground truth de JE8659 vino de la migración/confirmación de catálogo de un bloque anterior (R2, 2026-08-13), no de una decisión rastreable en este ledger.
- Dataset vigente: `grep` del RUT `15489424-1` (con y sin puntos) sobre las 43 filas -- 5 guías: 464264/465 (SODIMAC SA, tracto/rampla VP8521/JD6659 y VP6521/JD0659) y 464698/699/700 (EBEMA SA, mismo transporte, VP8521/JE8659 idéntico en las 3).
- **Imágenes canónicas leídas directamente** (`Read` sobre los `.jpeg` reales en `operacion/entradas/`): 464264 y 464265 imprimen literalmente `"PATENTE: VP8521 CARRO:JD8659"` -- coincide EXACTO con el ground truth de Javier; el error es de EXTRACCIÓN OCR de Atlas (JD8659 → JD6659/JD0659, VP8521 → VP6521), el documento fuente ya estaba correcto. 464698 y 464699 imprimen literalmente `"PATENTE VP8521 CARRO:JE8659"` -- MISMO sistema de guías (EBEMA SA), mismo valor impreso 3 veces -- **una sola fuente repetida, no 3 verificaciones independientes.**
- **A.** Lo que dice cada documento: SODIMAC → JD8659 (impreso, 2 guías). EBEMA → JE8659 (impreso, 3 guías, mismo sistema). **B.** Lo que extrajo OCR de Atlas: JD6659/VP6521/JD0659 (464264/465, errores de OCR sobre documento correcto) y JE8659 (464698/699/700, OCR correcto sobre un valor de origen documental distinto). **C.** Catálogo: sólo JE8659 confirmada. **D.** Javier: JD8659. **E.** ¿Dos vehículos distintos? Improbable -- mismo chofer, mismo tracto VP8521 en las 5 guías, mismo período (05-08 a 12-08-2026), y el propio chofer confirma un solo valor. **F.** Evidencia suficiente para declarar canónica: **JD8659, por confirmación humana directa del chofer + corroboración independiente de 2 documentos impresos de OTRO mandante (SODIMAC)** -- JE8659 sólo tiene 1 fuente (EBEMA) repetida 3 veces.
- **Conclusión: JD8659 es la canónica.** No se registró en catálogo real (no autorizado en este bloque) -- estado exacto reportado.

**FASE 2 -- patrón VEHÍCULO documental->canónico, reutilizando `ORIGEN_NO_CONFIRMADO`:**
- `sugerir_vehiculos_por_chofer(*, rut_chofer, campo, valor_documental, filas, vehiculos)` (nueva, `decisiones_pendientes.py`): compara por RUT normalizado (`normalizar_rut`, ya existente en `atlas_core/catalogos.py`); filtra filas del mismo RUT con `estado_procesamiento=="OK"`; para cada patente distinta observada en el campo correspondiente (`patente_tracto`/`patente_rampla`), busca un vehículo `CONFIRMADO`/`ACTIVO` con esa patente exacta; reporta CADA candidata encontrada con `evidencia_resumen` (cantidad de documentos + guías) -- nunca prioriza ni oculta la de menor conteo.
- `enriquecer_decisiones_vehiculo(*, decisiones, filas, vehiculos)` (nueva): añade `candidatos` + `USAR_PATENTE_EXISTENTE`/`SELECCIONAR_OTRA_PATENTE` (constante `ACCIONES_PATENTE_SUGERIDA`) SÓLO a decisiones `VEHICULO_DESCONOCIDO` sin `candidatos` previos -- nunca reemplaza `REGISTRAR`/`NO_REGISTRAR`/`POSPONER`, siempre los suma.
- `aplicacion_decisiones.py`: `ACCIONES`/`ACCIONES_POR_TIPO["VEHICULO_DESCONOCIDO"]` extendidos; `aplicar_decision_obra` gana `patente_elegida`/`motivo_rechazo` (parámetros opcionales, compatibles con la firma ya usada). Rama nueva: `USAR_PATENTE_EXISTENTE` exige exactamente 1 candidato; `SELECCIONAR_OTRA_PATENTE` exige `patente_elegida`; ambas validan una lectura FRESCA de `cargar_catalogo_vehiculos(...).homologables()` (mismo patrón que `CatalogoPlantas` en origen) -- si la patente elegida no existe o no está `CONFIRMADO`/`ACTIVO`, `ErrorAplicacionDecision`. **Ninguna de las dos toca el CSV documental** (a diferencia de origen, que sí escribe 4 columnas) -- el valor documental queda preservado íntegro; la asociación canónica queda auditada exclusivamente en el ledger (`vehiculo_id`, `patente_canonica`, `valor_documental` original, `candidatos_previos`, `actor`, `fecha`, `decision_id`). Terminal (mismo filtro de `generar_artefacto`, extendido con estas 2 acciones).
- `mensajes` extendido con las 2 combinaciones nuevas.

**FASE 3 -- Ortiz, `motivo_rechazo`:** `NO_REGISTRAR` acepta ahora `motivo_rechazo: str | None = None` -- capturado en el `aplicacion` dict del ledger sin romper la firma ya usada por Desktop (parámetro opcional, `None` si no se envía -- verificado con test dedicado de compatibilidad). El candidato circunstancial (XF3629) queda en `candidatos_previos` del ledger aunque se rechace -- evidencia estructurada reutilizable por una futura Incidencia Documental, sin implementar ese módulo.

**FASE 4 -- decisiones obsoletas / `dataset_sha256`, diagnóstico + mecanismo:**
Causa exacta: la aplicación directa de ruta/km (bloque anterior, FASE 7) escribió el CSV vía `_leer_filas`/`_escribir_filas_completas` sin volver a llamar `generar_artefacto` -- el artefacto de decisiones quedó con el `dataset_sha256` de ANTES de esa escritura. Verificado: `hashlib.sha256(dataset real)` ≠ `dataset_sha256` del artefacto real.

`reconciliar_bandeja_decisiones(*, raiz_atlas, reloj=...)` (nueva, `revalidacion_documental.py`), orden estricto (importa por qué):
1. `regenerar_decisiones_persistidas` -- ya existente, conserva sólo decisiones vigentes (descarta cualquier `VEHICULO_DESCONOCIDO` cuya patente documental ya homologó por otra vía -- mecanismo de "eliminar las que ya no corresponden" que pedía la instrucción, reutilizado sin cambios), refresca contexto cliente/obra por ID, normaliza `acciones_permitidas` a la base de cada tipo -- **este último paso resetea incondicionalmente las acciones para `TIPOS_ENTIDAD_DESCONOCIDA`**, motivo por el cual el orden importa.
2. `enriquecer_decisiones_vehiculo` -- SIEMPRE después del paso 1 (nunca antes, se perdería el enriquecimiento).
3. `generar_artefacto` -- filtra contra el ledger (ninguna decisión terminal, de NINGÚN tipo, resucita mientras su `decision_id` no cambie) y publica con `dataset_sha256`/`catalogos_sha256` frescos.
No modifica CSV ni catálogos -- sólo reescribe `decisiones_pendientes.json`. Validado con test que fuerza la obsolescencia real (`DecisionObsoletaError` antes de reconciliar, aplicación exitosa después, sin tocar CSV/catálogos) y con test que confirma que un dataset GENUINAMENTE distinto (no un simple refresco) sigue siendo rechazado después de reconciliar -- la protección real no se relaja.

**Hallazgo corregido durante la validación TEMP (no anticipado en el diseño, real):** el paso 1 de `regenerar_decisiones_persistidas` (`decision["acciones_permitidas"] = list(ACCIONES_ENTIDAD_DESCONOCIDA)`, incondicional para `TIPOS_ENTIDAD_DESCONOCIDA`) se dispara CADA VEZ que se aplica CUALQUIER decisión (parte del flujo interno de `aplicar_decision_obra`) -- sin protección, aplicar la decisión de Ortiz borraba silenciosamente `USAR_PATENTE_EXISTENTE`/`SELECCIONAR_OTRA_PATENTE` de la decisión de Carlos Simón (`candidatos` sobrevivía, las acciones no). Corregido: si `tipo=="VEHICULO_DESCONOCIDO"` y la decisión ya trae `candidatos`, las 2 acciones se re-insertan en la base antes de POSPONER. Test de regresión dedicado (`test_aplicar_decision_ajena_no_borra_las_acciones_de_una_decision_enriquecida`) reproduce exactamente el escenario real (Ortiz + Carlos Simón en la misma bandeja).

**Segundo hallazgo corregido, real:** `sugerir_vehiculos_por_chofer` comparaba `rut_chofer` por string exacto -- 464699 tiene `rut_chofer="15489424-1"` (sin puntos) mientras 464264/698/700 tienen `"15.489.424-1"` (con puntos), MISMO Carlos Simón. Sin normalizar, la búsqueda perdía 1 de 3 corroboraciones de JE8659 (2 en vez de 3). Corregido con `normalizar_rut()` (`atlas_core/catalogos.py`, ya existente, reutilizado sin cambios). Test dedicado con el escenario exacto.

**FASE 5 -- refresco `estado_ruta`/`motivo_ruta`, generalizado:**
`derivar_estado_ruta_tras_cambio_origen(fila: Mapping) -> dict[str, str]` (nueva, `revalidacion_documental.py`), función pura:
```
if not planta_origen_nombre: return {}                              # bloqueo real sigue siendo origen
if distancia_km: return {}                                          # ya hay ruta, nada que derivar
if estado_entrega in ("", "RESUELTO"): return {}                    # destino ya resuelto o sin dato
return {"estado_ruta": "REQUIERE_REVISION", "motivo_ruta": f"DESTINO_{estado_entrega}"}
```
Deliberadamente NO intenta recomputar el motivo exacto de destino (evitaría geocodificación/red) -- deriva directamente de `estado_entrega`, ya trazado como fuente de verdad confiable en el bloque anterior. Conectada en las DOS rutas de confirmación de origen ya existentes:
- `aplicar_decision_obra`/rama `ORIGEN_NO_CONFIRMADO` (`aplicacion_decisiones.py`): tras escribir las 4 columnas de origen, `fila_objetivo.update(derivar_estado_ruta_tras_cambio_origen(fila_objetivo))` antes de `_escribir_filas_completas` -- cubre 464717.
- `revalidar_telemetria_sin_ocr` (`revalidacion_documental.py`): la rama `elif origen_cambio:` ya existente sólo invalidaba ruta cuando YA había `distancia_km` (caso 464522-like con ruta previa); se añadió una rama hermana para cuando NUNCA hubo ruta que invalidar -- mismo derive, generaliza para casos futuros equivalentes a 464522.
Se evaluó FASE 5.A (motivo principal + motivos secundarios estructurados) vs FASE 5.B (derivar del campo `estado_entrega` ya existente, compatible con el esquema actual sin añadir columnas) -- se eligió **B**, la mínima solución generalizable, sin tocar el esquema del CSV (evita el riesgo de incompatibilidad con Drive real que ya se descartó explícitamente para el patrón de patente canónica, ver más abajo).

**Nota de arquitectura (decisión de diseño, no un gap accidental):** se evaluó persistir `patente_canonica`/`vehiculo_id_confirmado` como columnas nuevas del CSV (mismo patrón que `planta_origen_id`/etc. de origen) -- **descartado**: `_leer_filas` exige `lector.fieldnames == COLUMNAS` exacto; añadir columnas nuevas al código haría que CUALQUIER lectura del dataset REAL (que todavía no las tiene) fallara inmediatamente con "esquema incompatible", incluida la ruta de confirmación de origen YA EN PRODUCCIÓN -- una migración de esquema del CSV real está fuera de alcance de este bloque (instrucción explícita: si se requiere modificar Drive real, no hacerlo, reportar y esperar). Se optó por el ledger como única fuente de auditoría para la asociación documental->canónico -- completo para "preservar valor documental + canónico + evidencia + actor + timestamp + motivo", pero **el consumo operacional (que `viajes.csv`/Desktop muestren la patente canónica) queda pendiente como extensión futura**, reportado explícitamente, no implementado aquí.

**FASE 6 -- conciliación 13 vs 15, matriz real:**
`renderResumen(filtrados)` (no `VIAJES` completo) alimenta `stat-total`/`stat-ok`/`stat-rev`/`stat-docs` -- confirmado por lectura de código (`atlas_viajes.html`) que las 4 tarjetas YA se calculan sobre lo filtrado por `filtro-periodo`/`filtro-estado`/búsqueda, no sobre el total real. Verificado contra el reporte real (`viajes.csv`, 38 viajes): 36 dentro de "Este mes" (agosto 2026), 2 fuera (463594/463630, 27-07-2026, ambos ya `CONFIRMADO`); de los 36, 23 `CONFIRMADO` y 13 no -- coincide exacto con lo que reportó Javier.

Matriz real (13 viajes `REQUIERE_REVISION` dentro de agosto, cruzados contra las 15 decisiones por `numeros_guia`, separador real `|` no `,`):
- **8 viajes CON decisión pendiente**, cubriendo exactamente las **15** decisiones (464036→2, 464170→3, 464264+465→3, 464395→1, 464488→1, 464491→1, 464493→1, 464854→3).
- **5 viajes SIN ninguna decisión accionable** (464264+465 en realidad SÍ tiene, corregido tras separar por `|` correctamente en el script de auditoría -- los 5 reales sin decisión son: 464367, 464479, 464494, 464698+699+700, 464740), todos bloqueados por `DOCUMENTO_REQUIERE_REVISION`/`CONFLICTO_CLIENTE`/`CONFLICTO_OBRA_DESTINO`, ninguno por `VEHICULO_DESCONOCIDO`/`OBRA_DESCONOCIDA`.
- **0 decisiones huérfanas** (ninguna decisión pertenece a un viaje `CONFIRMADO` o fuera del período).
Semántica confirmada correcta; sólo la UX era ambigua -- **cambio de texto únicamente**: tarjetas → "Viajes mostrados"/"Viajes confirmados"/"Viajes requieren revisión"/"Documentos mostrados"; cabecera de Revisión de Atlas → "N decisión(es) pendiente(s)" (antes sólo "N pendiente(s)"). El widget de resumen por cliente/chofer (pestaña Catálogos, ya trae su propio texto explicativo "cuenta sobre todos los viajes cargados, sin importar el período") NO se tocó -- contexto distinto, no ambiguo.

**FASE 7 -- 36/38, trazado exacto:**
`$("conteo-filtro").textContent = filtrados.length + " / " + VIAJES.length` (línea original) -- `VIAJES` es el array completo cargado del reporte (38), `filtrados` es tras aplicar `filtro-periodo`/`filtro-estado`/búsqueda de texto (36 con "Este mes" activo, el valor que Javier tenía seleccionado). **No son viajes "perdidos"** -- son los 2 viajes de julio excluidos por el filtro de período, ya `CONFIRMADO`, visibles con "Todo" o "Este trimestre". Cambiado a: `"Mostrando " + filtrados.length + " de " + VIAJES.length + " viajes"` -- mismo cálculo, texto explícito.

**FASE 8 -- tests:** `tests/test_vehiculo_documental_canonico.py` (25 casos: sugerencia por RUT, no-sugerencia sin evidencia/sin catálogo confirmado, control crítico repetición-no-decide-por-mayoría con datos con forma real (JD6659/JE8659×3/JD8659×1), enriquecimiento no toca decisiones sin asociación, enriquecimiento agrega candidatos+acciones conservando las 3 originales, `USAR_PATENTE_EXISTENTE` sin tocar CSV, rechazo con 2+ candidatos, control crítico `SELECCIONAR_OTRA_PATENTE` eligiendo la MENOS repetida, rechazo de patente no confirmada, `NO_REGISTRAR` con y sin `motivo_rechazo` -- compatibilidad, no-reaparición con misma evidencia, sí-reaparición con evidencia nueva, reconciliación con refresco de sha256 sin tocar CSV/catálogos, reconciliación enriquece vehículos, reconciliación no reabre decisión cerrada, reconciliación sigue protegiendo contra dataset genuinamente obsoleto, **regresión real** de acciones borradas por aplicación ajena, normalización de RUT, 4 variantes de `derivar_estado_ruta_tras_cambio_origen`, integración completa 464717-como vía `aplicar_decision_obra`). **Grupo focal** (`decision or origen or vehiculo or revalidacion or telemetria`): 260 passed antes del fix de RUT/acciones, recontabilizado tras fixes. **Suite completa Motor: 1316 passed, 0 failed** (baseline 1291 + 25). Desktop: 3 tests nuevos de contadores (wording exacto de las tarjetas y del contador de Excel, scope correcto excluyendo el widget de Catálogos) + 1 test existente actualizado (`/10 pendientes/` → `/10 decisiones pendientes/`, wording nuevo). **Suite completa Desktop: 214 passed, 0 failed** (baseline 211 + 3).

**FASE 9 -- validación TEMP, datos reales, Drive nunca tocado:**
Copia de `analisis_completo_guias.csv`, `decisiones_pendientes.json`, `decisiones_aplicadas.json`, `estado_operacion.json`, `plantas.json`, `clientes.json`, `empresas.json`, `vehiculos.json`, `obras_destinos.json`, `destinos_maestros.json` reales a TEMP. `reconciliar_bandeja_decisiones(raiz_atlas=TEMP)` → 15/15/15 (antes/conservadas/publicadas), `dataset_sha256` del artefacto verificado IDÉNTICO al hash real del dataset tras reconciliar (antes no coincidía). Candidatos reales verificados: 464264/465 rampla → JE8659 con **3** documentos corroborantes (464698, 464699, 464700, tras el fix de normalización de RUT -- antes del fix, 2); 464265 tracto → VP8521 con **4** documentos (incluida la propia 464264). 464036 (Ortiz) → XF3629 con 1 documento, `CAMION_RIGIDO`. Simulado (sólo en TEMP): `aplicar_decision_obra(..., accion="NO_REGISTRAR", motivo_rechazo="ERROR_DOCUMENTAL_MANDANTE")` sobre Ortiz -- `ok=True`, ledger completo con `candidatos_previos`, catálogo de vehículos sigue en 20 (sin cambios). Verificado, tras esa aplicación, que Carlos Simón conserva `candidatos`+`USAR_PATENTE_EXISTENTE`/`SELECCIONAR_OTRA_PATENTE` (el hallazgo del punto anterior, ya corregido). Simulado `SELECCIONAR_OTRA_PATENTE(patente_elegida="JD8659")` -- rechazado correctamente con `ErrorAplicacionDecision("La patente indicada no existe o no está confirmada/activa.")`, exactamente el comportamiento esperado dado que JD8659 no está en catálogo real. **0 llamadas ORS. 0 llamadas Onelogis por red.** Mtimes de Drive real (`decisiones_pendientes.json`, `decisiones_aplicadas.json`, `analisis_completo_guias.csv`, `vehiculos.json`) verificados idénticos antes/después de toda la validación. TEMP eliminado al finalizar.

**FASE 10 -- decisión de publicación:** causa demostrada (obsolescencia de sha256, gap documental->canónico, texto obsoleto de ruta, contadores ambiguos) ✓; implementación generalizable (reutiliza `ORIGEN_NO_CONFIRMADO`/`generar_artefacto`/`regenerar_decisiones_persistidas` sin sistema paralelo) ✓; tests verdes (Motor 1316, Desktop 214) ✓; TEMP correcto con datos reales ✓; cero regresiones (2 hallazgos reales encontrados y corregidos ANTES de esta publicación, con test dedicado cada uno) ✓ -- se publica el código+tests+documentación. **Las 15 decisiones reales NO se aplican** -- eso requiere que Javier las revise una por una en una bandeja ya reconciliada, en un bloque futuro explícitamente autorizado.

**Drive:** no modificado -- 0 escrituras a `operacion/actual`, 0 escrituras a catálogos. **Catálogos:** sin cambios (`vehiculos.json` verificado en 20 entradas antes/después, sin JD8659). **15 decisiones reales:** sin aplicar. **Desktop:** sólo wording, sin cambios de lógica. **Git:** commit funcional de este bloque (ver hash real en el checkpoint siguiente). **ORS: 0 llamadas. Onelogis red: 0 llamadas. OCR: no se re-ejecutó.**

**Estado: REVISIÓN ATLAS RECONCILIADA A NIVEL DE CÓDIGO -- LISTO PARA REGENERACIÓN CONTROLADA DE BANDEJA REAL.**

## Bloque REGENERACIÓN CONTROLADA DE BANDEJA REAL DE REVISIÓN -- 2026-08-19

**FASE 0:** `git status`/`git rev-parse` en ambos repos -- Motor `2b43452fb49e7bbd463a428d725ea1377640c18a`, local=remoto, limpio. Desktop `7ad5cc9e6f1b020bd3427cb65671557b9f628ae4`, local=remoto, limpio.

**FASE 1 -- snapshot ANTES (lectura real, Drive):**
```
documentos: 43
viajes: 38 (25 CONFIRMADO, 13 REQUIERE_REVISION)
decisiones pendientes: 15 (VEHICULO_DESCONOCIDO: 8, OBRA_DESCONOCIDA: 7)
dataset_sha256 artefacto: BAC093AB7316EF60EF4E7D6B5E47778B026FF5ECF4D1A65DE3983AAC487FCA24
dataset_sha256 real:      5BE0179099DC820BCFB58BD6AFBEA21234E445EE33CC7CB56DA62E18E5EA0BEE
coinciden: False
```
Las 15 decisiones -- mismos `decision_id`/guía/transporte/tipo/campo/valor documental ya inventariados en el bloque de auditoría anterior, confirmados sin cambios: 464036×2 (Ortiz), 464170×3 (Iván Roa), 464264+464265×3 (Carlos Simón), 464395/464488/464491/464493 (obras), 464854×3 (Carlos Farías).

**FASE 2 -- backup, mecanismo auditado antes de decidir el alcance (no asumido):** lectura de `reconciliar_bandeja_decisiones` confirma que `regenerar_decisiones_persistidas` y `enriquecer_decisiones_vehiculo` son puras (ninguna llamada de escritura a disco en su cuerpo) y `generar_artefacto` llama `escribir_json_atomico(salida, artefacto)` una única vez, con `salida = ruta_salida` (`decisiones_pendientes.json`) -- ningún otro archivo puede cambiar. Backup y manifiesto SHA-256 acotados a ese único archivo: `respaldos/RECONCILIACION_BANDEJA_ROLLBACK_PRE_APLICACION_20260819_134448/operacion_actual/decisiones_pendientes.json`, verificado idéntico byte a byte contra el original antes de continuar.

**FASE 3 -- dry-run TEMP, reconciliación completa (script dedicado, comparación decisión por decisión contra un snapshot `bandeja_ANTES.json`):**
```
reconciliar_bandeja_decisiones(raiz_atlas=TEMP)
-> antes=15, conservadas=15, publicadas=15
```
Para las 15: `decision_id` idéntico en el 100% de los casos (ninguna desaparece, ninguna nueva). Diff campo a campo:
- **4 decisiones ganan `candidatos` + `USAR_PATENTE_EXISTENTE`/`SELECCIONAR_OTRA_PATENTE`** (antes `[]`/3 acciones, después 1 candidato/5 acciones, `REGISTRAR`/`NO_REGISTRAR`/`POSPONER` siempre presentes): 464036 patente_tracto (XF3662→XF3629), 464264 patente_rampla (JD6659→JE8659), 464265 patente_tracto (VP6521→VP8521), 464265 patente_rampla (JD0659→JE8659).
- **11 decisiones sin ningún cambio de contenido** (candidatos `[]`→`[]`, acciones idénticas): 464036 obra, 464170×3, 464395, 464488, 464491, 464493, 464854×3.
- `dataset_sha256`/`catalogos_sha256` del artefacto: refrescados, coinciden con el real tras reconciliar.

**FASE 4 -- los 4 casos, auditados con evidencia real:**

**A) Carlos Simón:** las 3 decisiones sobreviven con JE8659 como única candidata sugerida (nunca forzada -- `acciones_permitidas` incluye `REGISTRAR`/`NO_REGISTRAR`/`USAR_PATENTE_EXISTENTE`/`SELECCIONAR_OTRA_PATENTE`/`POSPONER`, las 5, sin preferencia). Verificado en copia aislada (`Atlas_dryrun_apply`, subcopia de TEMP, nunca promovida a Drive): `aplicar_decision_obra(..., accion="SELECCIONAR_OTRA_PATENTE", patente_elegida="JD8659")` → `ErrorAplicacionDecision("La patente indicada no existe o no está confirmada/activa.")` -- **JD8659 sigue, correctamente, sin poder aplicarse** (no está en catálogo real). Distinción explícita: **VALOR_DOCUMENTAL** = lo que Atlas guarda como `valor_documental` en cada una de las 3 decisiones (JD6659/VP6521/JD0659); **VALOR OCR** = idéntico al anterior en este caso (Atlas no re-extrae, el valor documental ES lo que OCR leyó); **VALOR CANÓNICO CONFIRMADO** = JD8659 (chofer, verbal, bloque anterior) para la rampla y VP8521 (catálogo, ya `CONFIRMADO`) para el tracto -- **ninguno de los 3 valores leídos por OCR se convirtió en vehículo real.** Pregunta exacta que Atlas debería hacerle a Javier: para cada una de las 3, ¿usar JE8659 (única opción hoy disponible en catálogo, con la reserva de que puede ser un error sistemático de EBEMA) o posponer hasta que él autorice registrar JD8659?

**B) Ortiz:** verificado en la misma copia aislada: `aplicar_decision_obra(..., accion="NO_REGISTRAR", motivo_rechazo="ERROR_DOCUMENTAL_MANDANTE")` → `ok=True`, mensaje esperado. Catálogo de vehículos verificado en 20 entradas ANTES y DESPUÉS de esa prueba (sin cambio) -- confirma que la acción, cuando Javier la ejecute de verdad, no contamina catálogo ni CSV.

**C) Supermercado Señor de los Milagros:** decisión `be58458d017b...` sin cambios -- `cliente_canonico="EBEMA SA"`, `destino_documental="AV. ALMTE. LATORRE 843 MEJILLONES MEJILLONES"`, `candidatos=[]` (obras no reciben el mecanismo de sugerencia en este bloque, sólo vehículos), `motivos=["OBRA_NO_EXISTE_PARA_CLIENTE"]`. Sigue sin ninguna evidencia de haber sido resuelta antes (confirmado de nuevo contra el ledger real, 0 coincidencias).

**D) 464717 -- hallazgo honesto, verificado con datos reales, no anticipado en el guion original del bloque:**
```
analisis_completo_guias.csv (fila 464717, real, tras esta reconciliación):
  planta_origen_nombre=AZA COLINA, origen_determinado_por=CONFIRMACION_HUMANA   (correcto, ya lo era)
  estado_ruta=ORIGEN_NO_DETERMINADO, motivo_ruta=ORIGEN_GPS_ESTADIA_SIN_PLANTA  (SIGUE OBSOLETO)
```
Confirmado por auditoría de código que `reconciliar_bandeja_decisiones` NUNCA toca `analisis_completo_guias.csv` (sólo `decisiones_pendientes.json`) -- 464717 ni siquiera es una de las 15 decisiones pendientes (su origen se confirmó y cerró en un bloque anterior), así que este bloque no tenía forma de tocarlo aunque quisiera. Verificado directamente, llamando la función real sobre la fila real:
```
derivar_estado_ruta_tras_cambio_origen(fila_real_464717)
-> {'estado_ruta': 'REQUIERE_REVISION', 'motivo_ruta': 'DESTINO_REVISAR'}
```
**La función sabe corregirlo perfectamente** -- el problema es que el mecanismo es **prospectivo, no retroactivo**: sólo se invoca automáticamente DENTRO de una aplicación NUEVA de `ORIGEN_NO_CONFIRMADO` (`aplicar_decision_obra`) o de una corrida NUEVA de `revalidar_telemetria_sin_ocr` -- ninguna de las dos vuelve a ejecutarse sobre una fila cuyo origen ya quedó `CONFIRMACION_HUMANA` de forma terminal desde antes de que este mecanismo existiera. **No se corrigió en este bloque** -- estaba fuera de su alcance explícito ("aplicar ÚNICAMENTE la regeneración de la bandeja real"); se reporta la causa exacta en vez de darlo por resuelto o de forzar una corrección no autorizada.

**FASE 5 -- contadores, sin cambios (`viajes.csv` no se toca):** 38/25/13 (totales); 36/23/13 (dentro de "Este mes", filtro activo -- 2 viajes de julio excluidos); documentos 43 (41 dentro de agosto); Revisión de Atlas → 15 decisiones (ahora reconciliadas). Explicación 13 vs 15 sin cambios respecto al bloque anterior (8 viajes cubren las 15 decisiones, 5 viajes bloqueados por otros motivos sin decisión accionable, 0 huérfanas) -- no se intentó igualar los números, sólo mantener el texto ya clarificado.

**FASE 6 -- aplicación real:** dry-run cumple los 5 criterios (coherente, no pierde válidas, reconcilia obsoletas, no introduce espurias, mantiene catálogos/datos intactos) → `reconciliar_bandeja_decisiones(raiz_atlas=r"G:\Mi unidad\Atlas")` ejecutado. Verificación posterior campo a campo:
```
15 decision_id reales idénticos a los de antes (comparación de conjuntos completa)
dataset_sha256 artefacto == hashlib.sha256(dataset real)  ->  True
```
Mtimes verificados: `analisis_completo_guias.csv`, `decisiones_aplicadas.json`, `estado_operacion.json`, `vehiculos.json`, `obras_destinos.json`, `clientes.json` -- todos idénticos al inicio del bloque. `vehiculos.json`: 20 entradas (sin cambio, sin JD8659). `obras_destinos.json`: 15 entradas (sin cambio). Único archivo con mtime nuevo: `decisiones_pendientes.json` -- exactamente el esperado.

**Lista completa, orden real del artefacto (para Javier):**
| N° | Guía | Chofer | Tipo | Campo | Valor documental | Candidata sugerida |
|---|---|---|---|---|---|---|
| 1 | 464036 | Patrick Ortiz | VEHICULO_DESCONOCIDO | patente_tracto | XF3662 | XF3629 (débil -- 1 doc, tipo distinto) |
| 2 | 464036 | Patrick Ortiz | OBRA_DESCONOCIDA | obra_destino | CONSTRUCTORA CERRO APOQUINDO | -- |
| 3 | 464170 | Iván Roa | VEHICULO_DESCONOCIDO | patente_tracto | TVXJ33 | -- |
| 4 | 464170 | Iván Roa | VEHICULO_DESCONOCIDO | patente_rampla | PXHH32 | -- |
| 5 | 464170 | Iván Roa | OBRA_DESCONOCIDA | obra_destino | SUPERMERCADO SEÑOR DE LOS MI | -- |
| 6 | 464264 | Carlos Simón | VEHICULO_DESCONOCIDO | patente_rampla | JD6659 | JE8659 |
| 7 | 464265 | Carlos Simón | VEHICULO_DESCONOCIDO | patente_tracto | VP6521 | VP8521 |
| 8 | 464265 | Carlos Simón | VEHICULO_DESCONOCIDO | patente_rampla | JD0659 | JE8659 |
| 9 | 464395 | José Lazcano | OBRA_DESCONOCIDA | obra_destino | ING Y METALURGICA INGEMETA | -- |
| 10 | 464488 | Patricio Villagra Muñoz | OBRA_DESCONOCIDA | obra_destino | CONSTRUCTORA E INMOBILIARIA | -- |
| 11 | 464491 | Leandro Toledo | OBRA_DESCONOCIDA | obra_destino | CONSTRUCTORA ALTIUS SPA | -- |
| 12 | 464493 | Cristopher Retamal | OBRA_DESCONOCIDA | obra_destino | EMPRESA CONST SIGRO SA | (ya existe casi idéntica en catálogo, ver auditoría anterior) |
| 13 | 464854 | Carlos Farías | VEHICULO_DESCONOCIDO | patente_tracto | TVKT21 | -- |
| 14 | 464854 | Carlos Farías | VEHICULO_DESCONOCIDO | patente_rampla | PXHH31 | -- |
| 15 | 464854 | Carlos Farías | OBRA_DESCONOCIDA | obra_destino | CONST GRUPO COLOSO LTDA | -- |

**Drive:** modificado -- exclusivamente `decisiones_pendientes.json`. **Catálogos:** sin cambios. **CSV documental:** sin cambios. **15 decisiones reales:** sin aplicar. **Backup:** creado y verificado, **rollback NO requerido**. **Desktop:** no modificado en este bloque. **Git:** commit documental de las tres bitácoras (ver hash real abajo). **ORS: 0 llamadas. Onelogis red: 0 llamadas. OCR: no se re-ejecutó.**

**Estado: BANDEJA REAL DE REVISIÓN ATLAS REGENERADA Y RECONCILIADA -- LISTA PARA QUE JAVIER RESUELVA LAS DECISIONES UNA POR UNA.**
