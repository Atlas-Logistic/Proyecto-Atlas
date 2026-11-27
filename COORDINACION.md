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
