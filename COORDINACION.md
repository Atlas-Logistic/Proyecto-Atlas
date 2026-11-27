# Coordinación — B1 correcciones, 2026-11-09

Trabajo aislado en `C:/Atlas/pruebas/b1-correcciones-generales-20261109/motor`, rama `feat/b1-correcciones-generales-20261109`, desde `4204163`. No modificar los worktrees de otros agentes ni datos operacionales.

- `d178377`: recupera el cambio focal de `e478c8b` y sus pruebas; conserva destino y ruta ante corrección de folio.
- `2a6b9ed`: distingue confirmación humana de B1 de una corrección automática al proyectar el destino.
- Verificación sintética: `tests/test_revision_sin_folio_p0.py` y `tests/test_acciones_operacionales.py`, 63 aprobadas.
- Prueba pendiente encontrada en `C:/Atlas/pruebas/revision-sin-folio-20261109/motor/tests/test_tarjeta_documental_sin_folio_p0.py`: tres casos fallan; las instrucciones desde tarjeta sin folio aún no se interpretan. Se conserva el original en su worktree.
- No habilitar ni desplegar escrituras generales de B1: falta identidad estable para todos los campos, conservar correcciones en cualquier orden y publicación coherente del dataset, ledger, bandeja y reporte ante fallos o pérdida del escritor. La restauración actual cubre la aplicación inicial pero los pasos posteriores ocurren fuera del bloque de recuperación; no demuestra publicación atómica para lectores ni recuperación ante interrupción.
- Pendiente: evitar revalidaciones y cambios operacionales por correcciones documentales, señalar rutas que requieran comprobación, implementar lenguaje natural y pruebas individuales y combinadas para los campos solicitados.

## Cierre focal: tarjeta documental sin folio

B1 identifica la tarjeta por archivo, transporte y fila vigente; admite folio, obra existente y destino con vista previa y confirmación. En este flujo conserva los estados y la ruta histórica y marca la ruta para comprobación ante un destino nuevo. Se probó el caso 0000369009 en tres órdenes, con cliente y original intactos, y el rechazo de identidades ambiguas. Las tres pruebas pendientes y las regresiones relacionadas aprobaron. La publicación coherente general sigue fuera de este componente; no se desplegó ni se escribieron datos productivos.

## Publicación B1: avance parcial, instalación bloqueada

Se registra de forma durable el inicio de las tres correcciones antes de escribir. Si el proceso se interrumpe, el token y nuevas correcciones documentales quedan bloqueados; también se rechazan confirmantes automáticos. Dos pruebas sintéticas cortan antes y después del ledger y comprueban que el reintento no duplica la decisión. Esto no recupera la publicación ni hace atómica la lectura de dataset, ledger, bandeja y reporte: permanecen pendientes la recuperación segura y el protocolo común de publicación y lectura. No instalar en CASA hasta resolver y probar esos puntos. El motor CASA seguía en `4204163`; no se pausó ni modificó PULL.

## Recuperación sin efectos

La marca de inicio conserva huellas de dataset, ledger, bandeja y estado del reporte, junto con la confirmación humana. La capa oficial puede reanudar, con la misma confirmación y comprobando nuevamente el preview, sólo si esas huellas siguen iguales y el token no está en el ledger. Si detecta una diferencia, no restaura ni aplica. Se probaron reinicios para folio, obra y destino, cambio ajeno y exclusión de un reintento concurrente. Las marcas anteriores a este cambio, sin huellas o confirmante, no se recuperan automáticamente. La recuperación de publicaciones parcialmente escritas y la coherencia de lectores todavía no están resueltas: no instalar ni ampliar campos.

## Prueba reproducible de publicación parcial

La reproducción original detuvo una corrección de folio después de escribir el CSV y antes del ledger, y mostró que un lector podía leer el folio nuevo y el ledger anterior.

## Protección de la lectura oficial B1

La capa de acciones usa el mismo bloqueo portable para sus lecturas de filas, decisiones, consultas y previews. `instantanea_documental` toma dataset, ledger y bandeja bajo una única adquisición. Un lector en otro proceso espera durante la escritura; tras un corte, una publicación sin terminar provoca un rechazo explícito. La espera tiene límite de tres segundos; el bloqueo huérfano usa la caducidad existente de seis horas y la marca de publicación sigue impidiendo lecturas parciales después de esa caducidad. Las pruebas con otro proceso y con terminación forzada son sintéticas. Lecturas directas de archivos por reportes, Desktop u otros consumidores no quedan protegidas; tampoco se ha implementado recuperación de escrituras parciales. No declarar resuelta la publicación completa ni instalar. No se modificaron CASA, PULL, Desktop, Mobile ni Worker.

## Inspección de interrupciones

La capa de acciones puede comparar las huellas previas y actuales de dataset, ledger, bandeja y estado del reporte, y verificar el token, la identidad documental, el valor y la confirmación humana en el ledger. Una diferencia sólo indica que el archivo cambió; no atribuye su autor ni autoriza sobrescribirlo. Se probaron cortes sintéticos antes y después del ledger, después de la bandeja y después del estado del reporte, además de folio, obra, destino y confirmación alterada. La recuperación sigue bloqueada si hay archivos modificados: falta identificar sin ambigüedad los cambios propios frente a concurrentes y completar o revertir cada etapa con seguridad. Los lectores directos siguen fuera del bloqueo; no declarar publicación coherente ni instalar.

## Recuperación parcial con reintento automático

Se recuperan seis escenarios sintéticos: corte tras confirmar y antes de modificar datos para folio, obra o destino (tres); corte tras el CSV y antes del ledger para folio u obra conservando estado (dos); y corte tras el ledger de destino sin recalcular ruta y antes del reporte (uno). Un reintento del mismo token conserva la confirmación original, comprueba huellas y resultado canónico, y reejecuta por la acción oficial; si el reporte falla, mantiene la marca y no registra aplicación definitiva. Para el CSV y el ledger se verifica byte por byte el resultado esperado y se restaura el respaldo sólo bajo el bloqueo de ese recurso. Se probaron reinicio en otro proceso, reintentos, conflicto ajeno, segundo corte tras restauración y generación de reporte real sintético.

Esto no cubre los cortes posteriores al ledger de folio u obra, la bandeja ya trasladada ni el estado de reporte ya publicado: siguen bloqueados ante diferencias. Los lectores directos de reportes y otros consumidores siguen fuera de `instantanea_documental`. No declarar completa la publicación coherente ni instalar.

## Recuperación tras ledger y bandeja

Folio y obra con ledger escrito, y folio con bandeja trasladada, se recuperan al reintentar el token si dataset, ledger y bandeja coinciden byte por byte con sus estados previos o el resultado canónico de esa operación, y el estado del reporte permanece sin cambio. Se verifican identidad, confirmante y valor; los respaldos se restauran bajo los locks locales de los recursos y la acción oficial vuelve a comprobar el preview. Se probaron cortes adicionales durante la restauración, reinicio, reintentos, conflictos ajenos y comparación con una ejecución sin corte.

El estado del reporte ya publicado **sigue bloqueado** para folio, obra y destino. Una prueba con generación real sintética interrumpe justo después de publicar ese estado y comprueba que el reintento no lo sobrescribe. No existe aún evidencia durable suficiente para atribuir ese estado al token sin confundirlo con una publicación concurrente. Los lectores directos de reportes siguen sin protección; no declarar completa la publicación coherente ni instalar.


## B1: error documental de patente (23/11/2026)

Sobre 96c9351, integrada la interfaz f9074bc. B1 exige declaracion explicita de error documental u OCR, guia, tipo y patente; contrasta la propuesta con la unica discrepancia de la accion oficial y exige confirmacion humana. Se conservan asignaciones, documento y OCR; respaldo, auditoria y proyeccion siguen el canal oficial. Si hay otras discrepancias, B1 se abstiene. Pruebas sinteticas: 70 focales aprobadas; regresion B1 y acciones 1035 aprobadas y una falla preexistente reproducida en la base (test_bandeja_se_reconcilia_una_sola_vez). No instalado ni se modificaron datos reales, Cloud, Mobile o PULL.


## P0.1: diario de recuperación persistido en Cloud (27/11/2026)

Rama feat/diario-recuperacion-remoto-20261127 sobre 48d6096 (Claude Code, encargo Javier). Solo cambia atlas_core/estado_confirmado.py. Reutiliza los endpoints de custodia del Worker desplegado (b28d594), sin cambios Cloud ni migraciones.

- Antes de la primera escritura de cada ruta del turno, la custodia sube el diario a R2 (PUT /estado/objetos/<sha>, exige lease) y confirma su puntero en la marca: `.atlas_custodia/diarios/<escritor_id>/<epoca>.json`. El diario es JSON canónico con tipo, formato, empresa_id, escritor_id, época del lease, sha256 del lease_token, version_base, raíz, rutas y huellas base. Queda en el espacio Cloud de la empresa del token.
- Si no se persiste (Cloud caído, lease vencido, versión superada), `DiarioNoPersistido` sale del audit hook y la escritura se aborta.
- Al confirmar el turno, el puntero se anula en el mismo lote final que los datos. Si el corte ocurre entre lotes, el diario sigue abierto. La recuperación del mismo equipo (pendiente.json) también lo cierra.
- Ningún turno anula ni adopta el diario de otro turno. `alinear` lo informa en `resumen["diarios_abiertos"]` y nunca restaura rutas `.atlas_custodia/` a la raíz. La verificación tampoco las compara ni las cuenta como datos.
- Lectura desde cualquier equipo: `python -m atlas_core.estado_confirmado --raiz-atlas X --diarios`. Es de solo lectura, verifica la huella, la estructura y la ruta frente al turno y la empresa. El campo `vigente` indica que nadie confirmó después.
- Costo: cada ruta nueva de un turno suma una versión y un objeto de alrededor de 1 KB, y el cierre suma una versión más. Reescribir un contenido idéntico ya no deja la marca intacta: se abre y se cierra el diario, pero no se publican datos.
- Compatibilidad: un Motor anterior que alinee mientras haya un diario abierto restauraría ese archivo dentro de su raíz, en la carpeta oculta `.atlas_custodia/`, que es inocua. Conviene instalar en CASA y OFICINA juntos.
- No incluido (siguiente etapa): adoptar o resolver desde otro equipo el turno perdido, avisar en Desktop, y el contrato v2.

Pruebas: tests/test_diario_recuperacion_remoto.py, 8 pruebas nuevas. Suite de custodia: 275 de 276; la falla test_lease_multiequipo::test_manual_y_pull_nunca_escriben_a_la_vez ya existía en 48d6096. Validación aislada scripts/validacion_diario_remoto/validar.py: Worker b28d594 real sobre D1/R2 en memoria, equipo A muerto con taskkill y borrado por completo, equipo B lee el diario íntegro y trabaja. Resultado 18/18. NO instalado. No se tocaron CASA, PULL, Drive ni Cloud productiva.


## P0.2: recuperación de turnos desde otro escritor (27/11/2026)

Rama feat/recuperacion-turno-remoto-20261127 sobre acbe227 (Claude Code, encargo Javier). Worker sin cambios (b28d594).

- Diario formato 2. Además de las rutas, guarda el contenido custodiado de cada una: la huella, ya subida a R2 ANTES de que el archivo cambie en la raíz.
  - En el patrón temporal + os.replace, el audit hook lee el temporal completo antes del reemplazo. Los borrados también se anotan.
  - Las escrituras directas quedan pendientes hasta `estado_confirmado.punto_de_control(ruta)`, tras cerrar el archivo. Se agregó el punto de control en procesamiento_masivo._escribir_filas (ingesta), en b1_observabilidad.jsonl y en storage.py. Si el punto de control falla, solo se registra la advertencia: la fila ya está escrita y relanzar invitaría a duplicarla.
  - Solo se sube lo que falta: una consulta `faltantes` por anotación.
- Recuperación: `python -m atlas_core.estado_confirmado --raiz-atlas X --recuperar-turno <diario> [--aplicar]`. Exige lease vigente y custodia alineada. Sin `--aplicar` es una vista previa. Funciona todo o nada y se bloquea (código 3, nada escrito) ante:
  - DIARIO_SIN_CONTENIDO: diario formato 1.
  - CONTENIDO_NO_CUSTODIADO: rutas pendientes.
  - VERSION_POSTERIOR: una ruta cambió en Cloud después de la base; nunca se pisa.
  - COPIA_LOCAL_DISTINTA.
  - VERSION_INCOMPATIBLE.
  - PERDERIA_DOCUMENTOS: el dataset resultante pierde identidades.
  - RECUPERACION_INTERRUMPIDA.
  - Además, un dataset con identidades duplicadas o un contenido cuya huella no coincide hacen fallar la recuperación sin escribir.
- Al aplicar: el diario ajeno se cierra en el mismo lote final que confirma los datos, y queda un registro en operacion/actual/recuperaciones_turno/<escritor>__<epoca>.json. Un segundo intento da YA_CERRADO sin cambios.
- Cortes durante la recuperación:
  - Falla en proceso: se deshace lo escrito y no se cierra el diario ajeno.
  - Muerte del recuperador: su diario declara antes la recuperación esperada. Ni él al volver (pendiente.json) ni otro equipo cierran el diario ajeno con una recuperación parcial.
- Alineación: un dataset local que coincide con el contenido custodiado de un diario abierto ya no bloquea (caso de Drive que trajo el trabajo del equipo caído, incidente del 26/11). Se pone en cuarentena, se restaura y luego se recupera desde Cloud.
- acciones_operacionales: si se pierde el escritor global y la auditoría de la falla no puede persistirse (la custodia bloquea escribir sin lease), la acción devuelve igual FALLIDA con el código real y `auditoria_persistida: false`. Esto corrige la regresión de acbe227 en test_escritor_global_cierre (4 pruebas).
- Costo: cada reescritura atómica de una ruta suma una versión y su objeto en R2, que crecen sin compactación. Conviene medirlo antes de instalar.

Pruebas:
- tests/test_recuperacion_turno_remoto.py: 14 pruebas nuevas.
- Suite completa del Motor (sin los disparadores de pip): 46 fallas en la rama contra 46 en 48d6096. La diferencia era test_accion_con_lease_perdido, hoy corregida. test_falso_ok_obra_destino_p1 es intermitente.
- Validación aislada scripts/validacion_diario_remoto/validar.py: 23/23, con el Worker b28d594 real sobre D1/R2 en memoria.
  - A ingesta con el escritor real, muere con taskkill y se borra por completo.
  - C, que tenía el dataset parcial de A, recupera exactamente lo que A escribió.
  - El reintento no cambia nada y B ve la guía una sola vez.
  - Con una versión posterior, la recuperación se bloquea sin tocar Cloud.

NO instalado. No se tocaron CASA, PULL, Drive ni Cloud productiva.


## P0.3: protección efectiva frente a la pérdida del lease (27/11/2026)

Rama fix/escritor-sustituido-20261127 sobre 78a3ca3 (Claude Code, encargo Javier). Solo cambia atlas_core/estado_confirmado.py; el Worker no cambia (b28d594).

El destino compartido tiene dos caras. Cloud ya rechaza en el servidor toda confirmación sin el token vigente y la versión base. La raíz en Drive no admite fencing propio: si un escritor viejo escribe, Drive replica su archivo. La protección queda en cada escritura y en la confirmación, no en el heartbeat:

1. Servidor en cada escritura. La publicación del diario exige el lease en Cloud. Si no hay nada nuevo que publicar (reescritura idéntica, escritura directa sobre una ruta pendiente), se renueva el lease en el servidor. La renovación falla si el lease venció o lo tomó otro, y la escritura se aborta (`EscritorSustituido`) aunque `lease.vigente` local diga True.
2. Compare-and-swap en el destino. Antes de escribir, el archivo debe contener lo que el turno espera: lo último que escribió o la huella de la marca alineada. Si no, `ContenidoAjeno` y no se escribe, así que el nuevo titular nunca construye sobre lo que Drive trajo del anterior. Una ruta que la marca no conoce o una escritura directa sin punto de control no tiene referencia y no se comprueba.
3. Confirmación. Se publica la huella custodiada al escribir, no la que haya en la raíz. Un contenido ajeno aparecido después se informa en `ajenos_descartados` y la próxima alineación lo pone en cuarentena. Lo mismo aplica al recuperar pendiente.json del mismo equipo, que ahora guarda el contenido.

Residuales (no se amplió el alcance):
- Los bytes del escritor viejo sí llegan a SU disco si la escritura ya había empezado; nunca llegan a Cloud ni se confirman.
- Si Drive lleva a B un dataset con documentos que Cloud no tiene, la protección previa del dataset (incidente del 26/11) detiene a B sin escribir hasta una revisión humana.
- No se detecta la contaminación cruzada: B lee un archivo ajeno que no escribe y deriva otro archivo de él.
- Cada escritura sin publicación hace una solicitud de renovación.

Pruebas:
- tests/test_escritor_sustituido.py: 7 pruebas nuevas. Se ajustaron dobles de lease y escritores simulados en el mismo proceso: Drive es otro proceso.
- Suite completa del Motor: 47 fallas contra 46 en 48d6096. La diferencia, test_mobile_historial_por_lote, es intermitente en ambos (2 de 4 en la rama, 1 de 6 en la base).
- Validación aislada scripts/validacion_diario_remoto/validar_lease.py: 16/16, con el Worker real.
  - A, sin heartbeat, escribe media fila; el lease vence y B lo adquiere.
  - A termina creyéndose vigente: su punto de control, otra escritura y su cierre son rechazados, y nada llega a Cloud.
  - Drive lleva el dataset de A a B a mitad del turno de B: B se niega a escribir sobre él y confirma lo suyo.
  - El turno de A no puede recuperarse encima de B.
- validar.py (P0.1/P0.2) sigue en 23/23.

NO instalado. No se tocaron CASA, PULL, Drive ni Cloud productiva.


## P0.3.1: aislar las escrituras no confirmadas (27/11/2026)

Rama feat/raiz-trabajo-aislada-20261127 sobre 1c307bd (Claude Code, encargo Javier). Solo cambia atlas_core/estado_confirmado.py; el Worker no cambia (b28d594).

- Raíz de trabajo local, fuera de Drive. El Motor de cada equipo escribe en ella: los puntos de entrada (PULL, Desktop, B1, altas) ya reciben la raíz desde la configuración y no cambian. Cada turno la alinea desde Cloud y aparta en cuarentena lo no confirmado.
- Raíz publicada (Drive). Recibe solo datos confirmados por Cloud:
  - Después de cada lote confirmado se copia la huella confirmada (desde la raíz de trabajo o, si allí difiere, desde Cloud).
  - Los reportes, respaldos y backups del turno se publican solo si el turno confirmó.
  - Si la publicación falla, queda en `publicacion_pendiente.json` y se reintenta al alinear el siguiente turno, con el valor vigente en Cloud.
- De la raíz publicada solo bajan carpetas de reportes/respaldos/backups que falten en la raíz de trabajo, sin sobrescribir; existen allí solo si su turno confirmó. Nada custodiado fluye de Drive a la raíz de trabajo.
- Activación opcional por empresa: `raiz_publicada.json` en la carpeta local de la empresa, creada con `python -m atlas_core.estado_confirmado --raiz-atlas <trabajo> --preparar-raiz-trabajo <Drive>`. Ese comando copia Drive a la carpeta local una sola vez y nunca escribe en Drive. Ya activada, un turno sobre la raíz publicada se rechaza (ESTADO_NO_VERIFICADO). Sin el archivo, todo sigue igual que antes.
- Al volver, un equipo cuyo propio turno fue superado ya no queda detenido por la protección del dataset (26/11). La excepción aplica solo en modo aislado y solo si un diario abierto de ese mismo escritor nombra el dataset. Ese contenido va a cuarentena local y su diario sigue en Cloud. Sin modo aislado, la protección se mantiene.

Pruebas:
- tests/test_raiz_trabajo_aislada.py: 9 pruebas nuevas.
- Suite completa del Motor: 46 fallas, igual que 48d6096. Las diferencias son las intermitentes conocidas (test_falso_ok_obra_destino_p1 y test_mobile_historial_por_lote).
- Validación aislada scripts/validacion_diario_remoto/validar_aislada.py: 14/14, con el Worker real.
  - Dos escritores, cada uno con raíz de trabajo y su copia de Drive, sincronizada durante la operación interrumpida.
  - A, sin heartbeat, escribe media fila y un reporte; el lease vence y B lo toma.
  - B ingesta dos veces sin contaminación ni bloqueo.
  - Las dos copias de Drive quedan con lo de B y nada de A.
  - A vuelve, aísla su turno y trabaja.
- validar.py 23/23 y validar_lease.py 16/16 (modo no aislado) siguen aprobando.

Antes de instalar:
- Activar en CASA y OFICINA a la vez.
- Desktop debe leer la raíz publicada o la de trabajo; es decisión de instalación.
- El primer copiado de Drive es completo.
- Revisar escritores externos al Motor que escriban en Drive.

NO instalado. No se tocaron CASA, PULL, Drive ni Cloud productiva.


## P0.4: recuperación automática de turnos interrumpidos en el PULL (27/11/2026)

Rama feat/recuperacion-automatica-pull-20261127 sobre 015047a (Claude Code, encargo Javier). Cambia atlas_core/estado_confirmado.py y sincronizar_mobile_cloud.py (ejecutar_pull_con_escritor); el Worker no cambia (b28d594).

- `CustodiaEstado.recuperar_automaticamente(lease)` corre en cada pasada del PULL, después de adquirir el lease y alinear y ANTES de tomar envíos: las escrituras de la pasada dejarían sin base a los diarios pendientes. Nunca corta el PULL; su resultado sale en `resultado["recuperacion_turnos"]`.
- Recorre los diarios abiertos, del más antiguo al más nuevo y de cualquier equipo, incluido el propio con su LOCALAPPDATA perdido. Aplica cada uno con `recuperar_turno` de P0.2: todo o nada, sin pisar versiones posteriores, sin perder ni duplicar documentos, y con el diario cerrado en el mismo lote. Es idempotente: un diario cerrado ya no se ve.
- Los incompatibles se conservan abiertos en Cloud para revisión, con su motivo, en `en_revision` y en `diarios_en_revision.json` de la carpeta local.
  - Los bloqueos que no cambian con el tiempo (DIARIO_SIN_CONTENIDO, CONTENIDO_NO_CUSTODIADO, VERSION_POSTERIOR, PERDERIA_DOCUMENTOS, INTEGRIDAD) se recuerdan por huella del diario y no se reevalúan en cada ciclo (`omitidos`).
  - Los transitorios se reintentan.
  - Un diario bloqueado no detiene la pasada ni las operaciones independientes.
- Si el lease se pierde durante la recuperación, se detiene sin error. Lo ya confirmado queda; lo demás se reintenta en el próximo ciclo.

Pruebas:
- tests/test_recuperacion_automatica_pull.py: 5 pruebas nuevas, sobre el ejecutar_pull_con_escritor real.
- Suite completa del Motor: 45 fallas contra 46 en 48d6096. La única diferencia es la intermitente test_falso_ok_obra_destino_p1, que esta vez pasó.
- Validación aislada scripts/validacion_diario_remoto/validar_pull.py: 16/16, con el PULL real (sincronizar_mobile_cloud.py --sin-procesar), el Worker b28d594 real y envíos Mobile reales.
  - A ingesta una guía, muere y se elimina por completo.
  - El PULL de B recupera el turno y recibe E1 en el mismo ciclo; el segundo ciclo no repite ni duplica.
  - El turno de C, sin contenido custodiado, queda en revisión mientras E2 y E3 entran.
- validar.py 23/23, validar_lease.py 16/16 y validar_aislada.py 14/14 siguen aprobando.

Antes de instalar:
- Lo mismo que P0.1 a P0.3.1.
- Mostrar `diarios_en_revision` en Desktop, que hoy solo está en el log y el resultado del PULL.

NO instalado. No se tocaron CASA, PULL, Drive ni Cloud productiva.
