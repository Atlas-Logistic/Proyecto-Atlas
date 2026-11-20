# Continuidad operacional CASA / OFICINA

**Alcance.** Diagnóstico y diseño, **sin implementar**. Base Motor `2c524c9`.
* Evidencia: código del Motor; Desktop instalado en CASA (`app.asar` `b091419b…`, leído sin
  modificar); Worker Cloud `61c2872` (copia de sólo lectura).
* Configuración de CASA leída en sólo lectura: política, tareas programadas.
* Pruebas sintéticas `tests/test_continuidad_casa_oficina.py` (9) sobre la **custodia real**
  (`estado_confirmado.CustodiaEstado`) con dos raíces locales y un cliente Cloud en memoria.
* No se tocó OFICINA, G:, Cloud ni datos reales.

**Supuesto operacional:** CASA y OFICINA nunca están encendidos a la vez. Sí se contemplan
apagados inesperados, cortes de red, Drive incompleto y operaciones interrumpidas.

## 1. Flujo actual

### 1.1 Qué es cada cosa

| Capa | Dónde vive | Cómo pasa de un equipo al otro |
| --- | --- | --- |
| **Archivos operacionales** | `G:\Mi unidad\Atlas` (Google Drive) | Drive, archivo por archivo, sin orden ni plazo; sólo sube mientras el equipo está encendido. |
| **Estado confirmado (custodia, protocolo 2)** | Cloud: marca por empresa (versión), manifiesto `ruta → sha256` y objetos R2 por SHA | Al cerrar cada turno de escritor (`LeaseEscritorOperativo.cerrar` → `CustodiaEstado.confirmar`). |
| **Turno de escritor** | Lease Cloud (120 s, heartbeat 30 s, época) + turno local | Cloud arbitra; el último escritor conserva prioridad 10 min. |
| **Código instalado** | Motor en `C:\Atlas\Proyecto-Atlas` y Desktop en `%LOCALAPPDATA%\Programs\Atlas Viajes` (`app.asar`), **por equipo** | **No** se sincroniza. Cloud sólo exige `protocolo_minimo` (Worker `:867`); no conoce el commit del Motor ni del Desktop. |
| **Configuración local** | `%LOCALAPPDATA%\Atlas\desktop_operacion.json`, autorización PULL, credencial (variable de usuario) | Por equipo. |

### 1.2 Cierre del equipo activo (hoy)

| Evento | Qué pasa | Fuentes en riesgo | Cómo lo reconoce Atlas |
| --- | --- | --- | --- |
| **PULL termina bien** | La pasada (tarea programada al iniciar sesión y cada 2 min; `pull_pc_nuevo.ps1` → `sincronizar_mobile_cloud.py`) toma el lease, `vincular_raiz` alinea, procesa y al cerrar confirma la custodia: sube objetos y confirma por lotes de 50. | Ninguna, si la confirmación llegó. | Marca Cloud con versión nueva. |
| **Desktop se cierra normalmente** | `window-all-closed` → salir. No hay vaciado ni espera. Cada operación de Desktop ya abrió y cerró su propio turno (`desktop_operacion.sesion`) y confirmó al terminar. | Ninguna, si cada confirmación llegó. | — |
| **Confirmación falla al cerrar el turno** (red o Cloud) | `_cerrar_custodia` **sólo registra un warning**, conserva el diario local `pendiente.json` (en `LOCALAPPDATA` de **ese** equipo) y libera el lease. **Desktop informa éxito igual.** | Todo lo escrito en ese turno: dataset, ledger, bandeja, evidencia. | Sólo el diario local de ese equipo. El otro equipo no lo ve. |
| **Windows se apaga con PULL o una operación a medias** | El proceso muere; el lease vence a los 120 s. Escrituras parciales en G:, diario local en ese equipo. | Las de la operación. | Sólo el diario local. |
| **Pérdida de conexión** | Sin lease no se escribe: la sesión Desktop y PULL bloquean. Lo ya escrito queda sin confirmar hasta que vuelva la red **en ese equipo**. | Ídem. | Ídem. |
| **Drive no terminó de sincronizar** | Atlas no consulta la cola de Drive. Si la confirmación de custodia llegó a Cloud, el otro equipo restaura desde Cloud (§1.3). | Lo que la custodia **no rastrea**: `reportes/`, `respaldos/`, `backups/`, `investigacion/` (`EXCLUIDOS_PRIMER_NIVEL`), temporales y locks. | No se reconoce. |

**La custodia sí rastrea la evidencia escrita dentro de un turno.** El audit hook de custodia
(`estado_confirmado._auditar`) registra toda escritura gobernada en la raíz, incluido el ingreso
de Desktop a `operacion/entradas/...` y las fotos de PULL (prueba
`test_apagado_normal_y_drive_atrasado_continua_desde_cloud`). «Fuera de semilla» en
`FUENTES_GENERACION.md` significa fuera de la **línea base inicial**, no fuera de custodia.
Quedan fuera la evidencia histórica anterior a la activación y lo escrito sin el hook
(procesos ajenos; copias `CopyFile2`, sin ocurrencias operacionales hoy).

### 1.3 Inicio en el otro equipo (hoy)

1. Windows inicia sesión y la tarea PULL arranca al iniciar sesión (y cada 2 min). Exige la
   política `lease_cloud` habilitada y autorizada y la credencial del usuario.
2. PULL pide el lease. Si el último escritor fue el otro equipo y no hubo relevo confirmado,
   espera un margen (30 s), y Cloud le niega el lease durante la prioridad de 10 min tras la
   última actividad del otro. Con equipos que no coinciden, esto ya expiró.
3. **Alineación** (`CustodiaEstado.alinear`, `estado_confirmado.py:305`):
   * descarga el manifiesto de la marca vigente;
   * confirma su propio diario si es del mismo equipo y nadie confirmó después
     (`_recuperar_pendiente`, `:353`);
   * compara cada archivo rastreado con su SHA. Si difiere: el contenido nunca confirmado va a
     **cuarentena local** y se **restaura** la versión de Cloud;
   * un archivo faltante o corrupto se restaura;
   * si restaurar el dataset **eliminaría documentos locales**, falla cerrado
     (`EstadoNoVerificado`, `:260-289`) y no escribe;
   * con cualquier duda, libera el lease sin escribir.
4. Desktop **no alinea ni verifica al abrir**: lee G: tal como esté (sólo busca
   actualizaciones de la aplicación). Hasta la primera pasada PULL alineada, la interfaz y los
   lectores (B1 de consulta, previews) pueden ver archivos atrasados o mezclados.
5. **Si Cloud no responde:** no hay lease, así que nadie escribe (PULL no hace nada y Desktop
   informa error). Los lectores siguen leyendo G:, sin garantía.

**Cómo se identifica hoy «la última operación válida»:** por la marca de custodia, es decir,
la última versión de cada archivo confirmado. **No es una generación coherente.** No hay
registro que diga que una operación terminó completa; ésa es la frontera
`PENDIENTE → COMPLETA` del diseño `DISENO_COHERENCIA_GENERACIONES.md`, aún no implementada.

## 2. Riesgos reales (demostrados con la custodia real, en sintético)

| # | Riesgo | Prueba | Efecto |
| --- | --- | --- | --- |
| R1 | **Trabajo no confirmado se revierte en el otro equipo sin aviso.** CASA cierra el turno sin confirmar (red caída al final del día); Drive lleva el archivo; OFICINA alinea y lo pone en su cuarentena local, restaurando la versión anterior. | `test_trabajo_no_confirmado_se_revierte_en_el_otro_equipo` | La decisión humana de CASA desaparece del estado operacional y sólo queda una copia en `LOCALAPPDATA` de OFICINA, con un warning en el log. |
| R2 | **Bloqueo que exige recuperación manual.** Igual que R1, pero con documentos nuevos en el dataset. | `test_trabajo_no_confirmado_con_documentos_nuevos_bloquea_al_otro_equipo` | OFICINA no puede escribir (`EstadoNoVerificado`) hasta que CASA se encienda y confirme, o se recupere a mano. |
| R3 | **El diario del equipo apagado se descarta** si el otro confirmó después. | `test_diario_del_equipo_apagado_se_descarta_si_el_otro_confirmo_despues` | Al volver, CASA pone su trabajo en cuarentena: pérdida operacional silenciosa. |
| R4 | **Confirmación por lotes interrumpida = mezcla aceptada.** Un corte entre lotes de 50 avanza la marca con una parte de la operación. | `test_confirmacion_por_lotes_interrumpida_queda_como_mezcla_aceptada` | Ambos equipos aceptan como confirmado un estado con 50 archivos nuevos y 1 viejo; el diario propio se descarta porque su versión base quedó superada por su propio lote. |
| R5 | **Envío Mobile consumido y revertido.** PULL confirma cada envío en Cloud (`_confirmar_cloud`, `cloud_mobile_sync_cliente.py:434`) **antes** de que el turno confirme la custodia. Si el equipo cae entre ambos y el otro trabaja primero, R1 revierte los archivos del envío y Cloud ya no lo vuelve a entregar. | Lectura de código (no reproducido) | Envío perdido operacionalmente. Hay herramientas **manuales** por envío (`recuperar_envio_mobile_error.py`, `recuperacion_fila_custodia`), pero no detección automática. |
| R6 | **Lectores sin alinear al arrancar** (Desktop, B1 de consulta, previews antes de la primera pasada PULL). | Lectura de código | Muestran estado atrasado o mezclado como si fuera el vigente. |
| R7 | **Versión instalada distinta entre equipos.** Cloud sólo controla el protocolo. | Lectura de código; OFICINA no verificada | Un Motor más antiguo escribe con reglas antiguas. |
| R8 | **Fuentes no custodiadas** (`reportes/`, `investigacion/`). | Código | Se regeneran o quedan atrasadas. `estado_operacion.json` (custodiado) puede apuntar a un reporte que Drive no entregó. |

Comportamientos **correctos ya verificados**:
* continuidad con Drive atrasado, restaurando desde Cloud;
* reinicio en el mismo equipo, confirmando su diario;
* archivo local faltante o corrupto, que se restaura;
* objeto Cloud corrupto, que bloquea;
* Cloud inaccesible, que impide escribir.

Pruebas `test_apagado_normal_y_drive_atrasado_continua_desde_cloud`,
`test_reinicio_en_el_mismo_equipo_confirma_el_diario`,
`test_archivo_local_corrupto_o_faltante_se_restaura`, `test_objeto_cloud_corrupto_bloquea` y
`test_cloud_inaccesible_no_permite_escribir`.

## 3. Protocolo mínimo recomendado

**Principio:** la continuidad ya existe y es automática (protocolo 2: PULL al iniciar sesión
alinea desde Cloud). No se crea un sistema paralelo. Se agregan cinco piezas, de menor a mayor:

1. **Estado de continuidad visible** (sólo lectura). Un diagnóstico del Motor que responda, sin
   escribir:
   * ¿hay diario `pendiente.json` en este equipo (trabajo sin confirmar)?
   * ¿coincide la copia local con la marca Cloud? Ya existe `estado_confirmado --verificar`
     (`verificar_sin_escribir`).
   * ¿Cloud responde?
   * versión de la marca, fecha de la última confirmación y su titular.

   Desktop lo muestra: **«Listo para cambiar de equipo»** sólo si no hay diario pendiente y la
   copia coincide con la marca. Al abrir, si no coincide, muestra «Alineando…» y desactiva las
   acciones de escritura y las vistas coherentes hasta la primera pasada alineada.
2. **Fallo de confirmación como estado, no como warning.** Si la custodia no confirma al cerrar
   el turno, el resultado de la operación lo dice («guardado en este equipo, **sin confirmar en
   Cloud**») y PULL lo reintenta en la próxima pasada, cosa que ya hace con `_recuperar_pendiente`
   cada 2 min si el equipo sigue encendido. Así Javier no apaga sin saberlo.
3. **Diario por lote** (sólo Motor, mínimo). En `_confirmar_rutas`, tras cada lote confirmado,
   reescribir `pendiente.json` con las rutas restantes y la nueva versión base. Así el mismo
   equipo completa una confirmación interrumpida (cierra R4 en el mismo equipo).
4. **Trabajo no confirmado del otro equipo: explícito.** Hoy la alineación lo pone en cuarentena
   en silencio (R1, R3) o bloquea sin explicación (R2). Con la frontera `PENDIENTE` del diseño
   de generaciones, el estado sería `INTERRUMPIDA_EN_OTRO_EQUIPO`, con dos salidas:
   * encender el equipo titular, que confirma su diario;
   * relevo **autorizado por Javier**, que restaura la última generación completa e informa
     qué trabajo no confirmado se descarta.

   Nunca se aplica una confirmación humana que no esté confirmada en Cloud.
5. **Generación completa como objetivo de alineación.** La alineación restaura la **última
   generación COMPLETA**, que es coherente, y no la última versión de cada archivo. Eso cierra R4
   en el otro equipo. Una generación anterior íntegra se presenta como «último estado completo
   (hora)», nunca como el estado vigente si hay `PENDIENTE` o `INTERRUMPIDA`.

Más dos piezas acotadas:
* **R5:** al alinear, detectar envíos `COMPLETADO` en Cloud sin archivos locales confirmados y
  reprocesarlos desde R2 con la herramienta existente. Alternativa: confirmar el envío en Cloud
  sólo después de confirmar la custodia del turno.
* **R7:** compuerta de versión. Un archivo custodiado de compatibilidad (p. ej.
  `operacion/actual/compatibilidad_motor.json` con un nivel operacional entero) que la
  instalación eleva. Al alinear, un Motor con nivel menor no escribe («actualice este equipo»).
  No requiere cambios en Cloud. Al instalar en un equipo se instala el nivel, y el otro lo
  exige al arrancar.

## 4. Secuencia automática de recuperación (al iniciar Atlas)

1. **Diagnóstico** (pieza 1, sólo lectura):
   * Cloud no responde → **SÓLO LECTURA** («sin árbitro; datos sin garantía»), sin escrituras;
     reintento automático.
   * Diario local pendiente → se confirma en la primera pasada si nadie confirmó después
     (automático).
2. **Primera pasada PULL** (ya ocurre al iniciar sesión) → alineación:
   * diferencias con contenido conocido en Cloud → restaurar (automático);
   * archivo faltante o corrupto → restaurar (automático);
   * objeto Cloud corrupto → **bloquear**;
   * contenido local nunca confirmado → con la pieza 4, `INTERRUMPIDA_EN_OTRO_EQUIPO`, **bloquear
     y pedir decisión** (hoy: cuarentena silenciosa);
   * dataset que perdería documentos → **bloquear y pedir decisión** (como hoy, pero
     explicado).
3. Con la pieza 5: si la marca o el control indica `PENDIENTE` o `INTERRUMPIDA` → mostrar la
   última COMPLETA como «anterior» y no escribir hasta resolverlo.
4. Desktop habilita la escritura cuando el diagnóstico dice «alineado» y el lease es obtenible.

## 5. Condiciones de bloqueo seguro

No se escribe (y Desktop lo explica) cuando:
* Cloud no responde;
* la copia local no coincide con la marca tras alinear;
* un objeto de Cloud no coincide con su huella;
* la alineación eliminaría documentos;
* hay trabajo no confirmado de otro equipo o una generación `INTERRUMPIDA` (piezas 4 y 5);
* el Motor está por debajo del nivel exigido (R7);
* la raíz no está montada (ya existe para borrados).

**Autorización humana** sólo para descartar trabajo no confirmado de otro equipo o documentos
locales. Nunca se requiere en el cambio normal de equipo.

## 6. Escenarios

| # | Escenario | Detección | Automático | Confiable | Bloquear escritura | Humano |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Apagado normal, sincronización completa | marca = copia local | sí | marca Cloud | no | no |
| 2 | Apagado normal, Drive atrasado | alineación (difiere, contenido conocido) | **sí** (restaura desde Cloud; probado) | marca Cloud | hasta alinear (hoy no se bloquea la lectura: R6) | no |
| 3 | Apagado inesperado durante PULL | diario local; en el otro equipo, contenido desconocido; envíos ya `COMPLETADO` (R5) | en el mismo equipo, sí; en el otro, **no** (hoy cuarentena silenciosa) | última confirmación | sí, en el otro equipo con la pieza 4 | sí, para descartar; R5 requiere la detección propuesta |
| 4 | Caída entre dos escrituras | ídem | ídem | ídem | ídem | ídem |
| 5 | Publicación interrumpida (lotes) | hoy **no se detecta** (R4) | mismo equipo con la pieza 3; otro equipo con la pieza 5 | la última COMPLETA (pieza 5) | sí, con la pieza 5 | no, si el titular la completa |
| 6 | Cloud disponible, Drive desactualizado | alineación | **sí** | Cloud | hasta alinear | no |
| 7 | Drive disponible, Cloud inaccesible | sin lease | no aplica | nada como vigente | **sí** (ya ocurre) | no |
| 8 | Archivo faltante o corrupto | SHA en la alineación | **sí** (probado) | Cloud | si Cloud también está corrupto, sí (probado) | sólo si no hay copia íntegra |
| 9 | Evidencia pendiente de sincronizar | escrita en turno: custodiada y se restaura; histórica o ajena: no se detecta | sí, si estaba custodiada | Cloud | no | si falta evidencia no custodiada |
| 10 | Reinicio en el mismo equipo tras un fallo | diario propio | **sí** (probado), salvo R4 sin la pieza 3 | diario + marca | no | no |

## 7. Estado operacional frente a versión instalada

* **Estado operacional:** archivos de G: más la marca de custodia (y en el futuro las
  generaciones). Se restaura y alinea automáticamente.
* **Versión instalada:** Motor y Desktop de cada equipo. Ni Drive ni Cloud la sincronizan ni la
  comparan: Cloud sólo controla el protocolo. CASA: Motor `c08bc38`, Desktop `b091419b`. OFICINA
  no se verificó (según el registro M0 era desconocida).
* La continuidad automática exige poder confiar en que ambos equipos aplican las mismas reglas
  (R7, compuerta de versión).
* Un estado coherente escrito por un Motor nuevo puede ser malinterpretado por uno antiguo.

## 8. Dependencias

* **Cloud** (Codex): contrato v2 de inventarios fragmentados, **no anticipado aquí**. Las piezas
  4 y 5 dependen de:
  * la frontera `PENDIENTE` y el CAS a `COMPLETA` (`DISENO_COHERENCIA_GENERACIONES.md` §9);
  * generaciones publicables con evidencia, que necesitan el contrato fragmentado por el límite
    de 1000 objetos.

  Las piezas 1, 2 y 3 y la compuerta R7 **no dependen de Cloud**.
* **R5** necesita poder listar los envíos `COMPLETADO` de Cloud (lectura) o cambiar el orden de
  confirmación en PULL.
* **Google Drive:** ninguna pieza depende de que Drive termine. La custodia es la fuente
  confiable; Drive es la copia de trabajo. No se puede leer la cola de Drive de forma
  confiable, y no se propone.
* **Desktop:** las piezas 1 y 2 necesitan mostrar el estado (encargo Desktop).

## 9. Etapas de implementación (pequeñas e independientes)

| Etapa | Componente | Contenido | Riesgo |
| --- | --- | --- | --- |
| **K1** | Motor | Diagnóstico de continuidad de sólo lectura (pieza 1): diario local, `verificar_sin_escribir`, Cloud alcanzable, versión y titular de la marca. CLI + función. | Nulo (no escribe). |
| K2 | Desktop | Indicador «Listo para cambiar de equipo» / «Alineando» / «Sin Cloud» usando K1; desactivar escrituras y vistas coherentes mientras no esté alineado. | Bajo. |
| K3 | Motor | Fallo de confirmación como resultado explícito de la operación (pieza 2). | Bajo. |
| K4 | Motor | Diario por lote en `_confirmar_rutas` (pieza 3). | Bajo; toca la custodia, requiere aprobación. |
| K5 | Motor | Compuerta de versión con un archivo custodiado (R7). | Bajo. |
| K6 | Motor | Detección de envíos `COMPLETADO` sin custodia local y reproceso automático (R5). | Medio. |
| K7 | Motor + Cloud | Piezas 4 y 5 sobre la frontera de generaciones (E1–E4 del diseño de coherencia), después del contrato Cloud v2. | Alto; depende de Codex. |

## 10. Pruebas para validar sin arriesgar datos

* **Sintéticas** (este repositorio): extender `test_continuidad_casa_oficina.py`, con dos raíces
  y la custodia real, a cada etapa:
  * K3: el fallo de confirmación se informa;
  * K4: el mismo equipo completa los lotes;
  * K5: un Motor de nivel menor no escribe;
  * K6: un envío `COMPLETADO` se recupera;
  * K7: `INTERRUMPIDA_EN_OTRO_EQUIPO`.
* **CASA, sólo lectura:** `python -m atlas_core.estado_confirmado --raiz-atlas "G:\Mi unidad\Atlas"
  --verificar` (existente; no escribe) antes de apagar y tras alinear.
* **OFICINA, sólo lectura y en una visita autorizada:**
  * SHA del `app.asar`, commit de `Proyecto-Atlas`, claves no secretas de la política y estado
    de las tareas;
  * el mismo `--verificar` tras iniciar sesión.

  Nada de esto escribe.
* **Ensayo de relevo con raíz sintética:** perfil `ATLAS_PRUEBA_ROOT` de Desktop y una empresa
  de prueba en Cloud de pruebas, nunca la de MBT. Cuando exista K1, alternar dos raíces locales
  marcadas `SOLO_DATOS_SINTETICOS`.

## 11. Limitaciones

* Las pruebas usan la custodia real, pero un cliente Cloud en memoria y dos carpetas locales en
  lugar de Drive. No prueban el Worker desplegado, la semántica real de Drive (conflictos,
  orden) ni Windows apagándose.
* R5 (envío Mobile) y R6 (lectores al arrancar) se derivan del código, no se reprodujeron.
* OFICINA no se verificó: versión instalada, política ni tareas.
* No se verificó qué hace Windows con los procesos hijos de Desktop al apagar.
