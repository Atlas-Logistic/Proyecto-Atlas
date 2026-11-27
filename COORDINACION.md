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

## Reserva P0 patentes por asignación vigente — 2026-11-17
Codex trabaja aisladamente en C:/Atlas/pruebas/patentes-asignacion-20261117/motor, rama p0/patentes-asignacion-vigente-20261117, base 8c97a5d. Sin modificar datos operacionales ni instalar; verificación en copia. Integración a cargo de Claude Code.

### Estado P0 patentes: investigación incompleta
La rama aislada sigue en 8c97a5d, sin cambios de código ni commit. La regla actual excluye patentes conocidas y ausentes; el reporte no resuelve valores vacíos; el procesamiento puede sustituir OCR antes de persistirlo; la vista de incidencias filtra detecciones no confirmadas. Una prueba exploratoria de proyección produjo 28 aprobadas y 2 fallidas; se descartó el cambio experimental por no cumplir auditoría y visibilidad. La copia coherencia-comuna-casa-20261117/foto contiene 811 filas y cero decisiones en la bandeja, por lo que no permite identificar tarjetas actuales innecesarias. Falta implementación integral, pruebas, verificación sobre copia apropiada y push. No integrar ni instalar.

## Reserva diagnóstico destino 485018 — 2026-11-18
Codex: únicamente lectura y pruebas aisladas de diagnóstico sobre Motor 95f14d6, documento y datos existentes. Sin edición de código ni datos, OCR, reconciliaciones o decisiones. Reserva limitada a este diagnóstico.

2026-11-18 Codex: reserva diagnóstico destino 485018 liberada. Lectura y pruebas puras aisladas; sin OCR, reconciliaciones, cambios de código ni datos operacionales.

## P0 proyección de MATERIAL — 2026-11-23
Codex creó el worktree C:/Atlas/pruebas/material-confirmado-20261123/motor, rama fix/material-confirmado-20261123 desde c08bc38. Se detuvo sin editar código ni reservar archivos: en 437fbaf la generación del reporte precede a la auditoría APLICADA de la acción, por lo que una proyección que exija ese estado durante el reporte no puede reconocer la corrección en curso. Coordinar el contrato de publicación con Code antes de implementar; no se modificaron datos operacionales ni se instalaron reportes. No hay reservas pendientes de Codex.

## Reserva P0 proyección de MATERIAL — 2026-11-23
Codex: rama fix/proyeccion-material-humano-20261123, worktree C:/Atlas/pruebas/proyeccion-material-humano-20261123/motor, base c3fda7f. Reserva atlas_core/gestor_viajes.py, atlas_core/reporte_viajes.py y tests de proyección de MATERIAL. Sin cambios a B1, canal, interfaz ni datos operacionales.

### Cierre P0 proyección de MATERIAL — 2026-11-23
Codex: commit d7c44634217f8c2e0a27b2df9fb980559d7edf42 publicado y SHA remoto verificado en fix/proyeccion-material-humano-20261123, base c3fda7f (incluye 437fbaf). Proyección del material humano vigente mediante la interfaz oficial; OCR conserva credibilidad previa. 219 pruebas focales y regresiones aprobadas, incluido reporte sintético antes de auditoría APLICADA. Sin datos reales ni instalación; pendiente comprobar el reporte real de la guía 485242 después de instalar. Reserva de gestor_viajes.py, reporte_viajes.py y pruebas liberada.

## Reserva P0 capacidades operacionales B1 — 2026-11-23
Codex: worktree C:/Atlas/pruebas/b1-operaciones-viaje-20261123/motor, rama feat/b1-operaciones-viaje-20261123, base 71bddbf. Reserva limitada a atlas_core/intenciones_equipo_operacional.py y tests/test_intenciones_equipo_operacional.py; no editar B1 ni canal/documentales reservados. Sin instalación ni datos reales.

### Cierre parcial P0 capacidades operacionales B1 — 2026-11-23
Commit f9074bc10d19df1717d5165296b0bf81af0f8316 publicado en feat/b1-operaciones-viaje-20261123, SHA remoto verificado. Nueva interfaz de interpretación para error documental de equipo, sin ejecución ni conexión B1. B1 ya conecta chofer y agrupación explícita. Bloqueante observado en base 71bddbf: DOCUMENTO_CONFIRMAR_ERROR_DOCUMENTAL_AZA acepta confirmado_por=ATLAS_AUTOMATICO; requiere corregir canal oficial reservado antes de conectar esta intención. Patente distinta a asignación confirmada y separación de guías no cuentan con conexión segura dentro de archivos permitidos; no se habilitaron. Pruebas: 94 aprobadas en suite focal y regresión y 12 en ejecución focal final (una prueba adicional de aislamiento entre raíces). No se modificaron datos reales ni se instaló. Reserva de intenciones_equipo_operacional.py y test_intenciones_equipo_operacional.py liberada.

## Reserva B1 simplificación visual — 2026-11-25
Codex: worktree C:/Atlas/pruebas/b1-simplificacion-visual-20261125/desktop, base fa2a002; Motor de referencia 7e861b6. Reserva presentación de listados B1 en Desktop y pruebas focales. Sin cambios al Motor ni datos.

### Cierre parcial B1 simplificación visual — 2026-11-25
Commit Desktop 8388baf publicado en fix/b1-simplificacion-visual-20261125. Agrupa por chofer y fecha, simplifica listados y presenta pendiente; prueba sintética del renderer en Electron para listado general y adicionales aprobada. Bloqueante: Motor 7e861b6 recorta _observaciones_texto a 300 caracteres en soporte_consultas.py y cli_consulta_atlas.py excluye el campo completo; no se puede preservar la observación completa desde Desktop. No se modificó Motor ni datos; no se validaron consultas reales ni se instaló en CASA ni actualizó kit de OFICINA. Reserva liberada.

## Reserva B1 observaciones completas — 2026-11-25
Codex: continuación Desktop 8388baf, Motor base 7e861b6. Para coordinación con Code se reserva exclusivamente atlas_core/soporte_consultas.py (eliminar recorte de observación) y prueba focal del contrato; Desktop presentación B1. No tocar multiempresa, intérprete, filtros, cálculos ni datos operacionales. Trabajo aislado; avisar aquí cualquier conflicto antes de integrar o instalar.

### Cierre B1 observaciones completas — 2026-11-25
Reserva de soporte_consultas.py y presentación Desktop liberada. Motor a9a6c825aade7f0a0db3a1ae1462860d8dccde25 y Desktop ab8a92e43048dd4916c780ecd877482edcba6cd8 publicados y SHAs remotos verificados. Motor solo elimina recorte de 300; prueba focal con texto mayor aprobada. Salidas de consultas reales, renderizadas en Electron: adicional 33, Versalles 10, noviembre 144; agrupación, fechas, columnas y texto recibido comprobados. La consulta real más larga tenía 185 caracteres; el caso mayor se comprobó con prueba focal. CASA: Motor fast-forward desde 7e861b6, COORDINACION.md local conservado, PULL reactivado en su estado anterior; app.asar SHA256 25D5B01D433614031F5E561DADA2F7797047000CC39E5AF9748B650CFDEFD3B4, respaldo app.asar.antes-b1-visual-20261125; proceso Desktop iniciado. Kit ACTUALIZAR_OFICINA actualizado con respaldo anterior-b1-visual-20261125; no ejecutado en OFICINA. Sin cambios de intérprete, filtros, cálculos, multiempresa ni datos operacionales.

## Reserva B1 exportación PDF — 2026-11-25
Codex: Desktop base ab8a92e, worktree C:/Atlas/pruebas/b1-pdf-20261125/desktop. Reserva presentación de resultados B1, canal PDF/vista previa y pruebas focales; sin cambios Motor, datos ni multiempresa. Distribución CASA y kit al validar.

### Cierre B1 exportación PDF — 2026-11-25
Desktop 2914483cc80633ee39e188b66e6fa42e585ea8aa publicado en feat/b1-exportar-pdf-20261125, SHA remoto verificado. Botón PDF para tablas visibles de viajes, usa printToPDF y vista previa/guardado existentes, empresa activa de Desktop. Validación con respuestas reales del Motor a9a6c82 renderizadas en Electron: Lazcano adicional 10 filas, todos adicional 33 y noviembre 144; PDFs revisados visualmente, 1, 2 y 7 páginas; cabeceras repetidas, fechas, transportes y observaciones comparados sin ausencias. Pruebas focales de vista previa 9 aprobadas. CASA app.asar SHA256 E2C7E61B106A8E244E7649DB9DD6DE636871A60909DE5F534F8B3C2728030C05, respaldo app.asar.antes-b1-pdf-20261125; Desktop iniciado. Kit ACTUALIZAR_OFICINA actualizado con respaldo anterior-b1-pdf-20261125; no ejecutado en OFICINA. Motor sin modificar, datos operacionales y multiempresa intactos. Reserva liberada.

## Coordinación consumo mensual multiempresa — 2026-11-25
Codex investiga contrato de consumo desde Motor 59c3f33 en worktree aislado. Code trabaja identidad y permisos en C:/Atlas/pruebas/multiempresa-identidad-20261125/motor; Codex no reserva ni modifica sus archivos. Se solicita coordinar identidad documental estable y configuración de zona horaria de empresa; sin datos reales ni instalación.

### Consumo mensual — investigación parcial y coordinación — 2026-11-25
Codex: commit documental 28697d3283990f3edc1399c1417fe53e45f45c10 publicado en investigacion/consumo-mensual-20261125, base 59c3f33. Sin contador ni reservas de archivos de producto. Se solicita a Code coordinar identidad documental estable ante correcciones/ambigüedad y zona IANA por empresa; también falta publicación recuperable del hecho de procesamiento finalizado junto a la medición. La identidad de reingesta actual usa guía/transporte completos y el resumen incluye relecturas y errores, por lo que no sostienen el requisito de consumo exacto. No se ejecutaron las validaciones MBT/Andes ni se instaló. Sin datos reales, G: ni Cloudflare. Reserva de investigación liberada.

## Reserva plantas configurables — 2026-11-25
Codex: investigación y cambios aislados de catálogo y selección de plantas, Mobile, recepción y rutas; no editar identidad ni permisos de Code. Base Motor 59c3f33, Cloud 2031e50, Mobile 8f10a61. Solicita coordinación con Code para la distribución aislada de catálogos por empresa autenticada. Sin G:, producción, CASA o Cloudflare real.

### Plantas configurables — avance parcial — 2026-11-25
Motor dc292876eeb6f72706465ff929aa3048727b78a5 publicado y SHA remoto verificado en feat/plantas-configurables-20261125, base 59c3f33. Resolución de origen por planta_id confirmada y activa en catálogo de la empresa; conserva códigos legados; 47 pruebas focales aprobadas, con MBT/Andes sintéticas y rechazo de ID ajeno/inactivo. No existe todavía distribución del catálogo al Worker y Mobile ni recepción de IDs en Motor; tampoco se validó preservación histórica de rutas o procesamiento completo. No integrar ni instalar el cambio parcial. Pendiente coordinar con Code identidad/permisos y contrato de sincronización por empresa, incluidos envíos offline capturados antes de desactivación. Sin cambios a Mobile, Cloud, autenticación, OCR ni datos reales; sin G:, CASA ni Cloudflare real. Reservas liberadas.


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


## P0.5: actualización automática entre equipos (27/11/2026)

Rama feat/actualizacion-automatica-20261127 sobre 5e3f3b9 (Claude Code, encargo Javier). El Worker no cambia (b28d594) y Desktop no cambia (main.js protegido).

- Versión publicada. Es un descriptor en la custodia Cloud de la empresa, `.atlas_custodia/version/vigente.json`, confirmado bajo lease. Fija:
  - Motor: rama y commit, que debe estar publicado en origin (mismo criterio que actualizar_equipo_relevo.ps1).
  - Desktop (opcional): un paquete zip reproducible con app.asar y app.asar.unpacked, subido a R2 y verificado por SHA-256.
  - `nivel_custodia_minimo`.
  - Se publica con `python actualizar_atlas.py --publicar --version V --rama R --commit C [--desktop-recursos ...] --nivel-minimo N --raiz-atlas X`. No permite bajar el nivel ya publicado, repetir una versión ni exigir más que el nivel del propio Motor.
- Al iniciar Atlas corre `scripts/iniciar_atlas.ps1`, que ejecuta `python -B actualizar_atlas.py` y luego abre Desktop con lo que quede instalado. El actualizador (atlas_core/actualizacion_atlas.py):
  1. Verifica todo antes de tocar nada: Motor sin cambios, Desktop cerrado, commit publicado, paquete íntegro y extraíble.
  2. Toma el turno local de la raíz, el mismo mecanismo de exclusión del PULL.
  3. Escribe un diario de actualización y respalda Desktop de forma atómica (`app.asar.antes-<version>`).
  4. Aplica el Motor (`git reset --keep`) y luego Desktop.
  5. Comprueba la salud en un proceso nuevo: importa la custodia y los puntos de entrada, exige el nivel publicado y verifica la cabecera del asar.
  6. Ante cualquier falla vuelve a la versión anterior.
  - Si el proceso se corta a mitad, el siguiente arranque encuentra el diario, revierte (solo con un respaldo completo y verificado por huella) y reintenta.
  - Una versión que falla 2 veces se omite hasta que se publique otra.
- Sin escrituras incompatibles, en dos capas:
  - (a) En la alineación, un Motor con `NIVEL_CUSTODIA` menor al publicado no escribe (`MOTOR_INCOMPATIBLE`), ni siquiera para confirmar su pendiente.
  - (b) `PROTOCOLO = 3`: con `protocolo_minimo = 3` en el Worker (D1, paso de instalación), los Motores anteriores, que no respetan diario, contenido ni escritor sustituido, no obtienen lease (`ESCRITOR_PROTOCOLO_OBSOLETO`).

Pruebas:
- tests/test_actualizacion_atlas.py: 10 pruebas nuevas, con git real de prueba, asar sintético y la compuerta sobre la Cloud simulada.
- Suite completa del Motor: 45 fallas contra 46 en 48d6096. La diferencia es la intermitente conocida.
- Validación aislada scripts/validacion_diario_remoto/validar_actualizacion.py: 17/17. Usa el Worker b28d594 real, dos instalaciones reales del Motor (clones git de un origin local con C1, C2 de nivel 2 y C3 rota) y Desktop sintético.
  - Y, en C1, no puede escribir.
  - Su inicio cortado a mitad se revierte y se completa en el siguiente inicio.
  - Y trabaja en C2.
  - C3 se revierte dos veces y luego se omite; Y sigue trabajando.
  - Con protocolo_minimo=3, un Motor de protocolo 2 queda fuera.
- iniciar_atlas.ps1 se probó con configuración de prueba y sin token (SIN_VERIFICAR).
- Las validaciones P0.1 a P0.4 siguen aprobando: 23/23, 16/16, 14/14 y 16/16.

Antes de instalar (pasos manuales, no hechos):
- Instalar por primera vez en CASA y OFICINA, porque el actualizador no existe en los Motores actuales.
- Cambiar el acceso directo de Atlas por iniciar_atlas.ps1.
- Subir `protocolo_minimo` a 3 en D1 una vez que ambos equipos tengan este Motor.
- Publicar la primera versión.
- Revisar que el paquete Desktop incluya todo `resources` necesario (hoy: app.asar y app.asar.unpacked).
- La salud de Desktop verifica el asar, no abre Electron.

NO instalado. No se tocaron Atlas Viajes instalado, CASA, PULL, Drive ni Cloud productiva.


## P0.6: validación integral del P0 estructural (27/11/2026)

Rama fix/p0-integral-20261127 sobre fcbea6b (Claude Code, encargo Javier). Valida P0.1 a P0.5 juntos y corrige solo regresiones del P0. NO instalado ni activado.

Regresiones corregidas, cada una con su prueba en tests/test_p0_integral_regresiones.py:
- R1 (P0.3.1):
  - Con la raíz de trabajo en C:, `compartida()` la trataba como privada, y las escrituras de Desktop (ingreso, acciones) iban sin lease ni custodia, así que nunca se publicaban.
  - Además Desktop muestra la raíz publicada y la entrega al Motor.
  - Corrección: atlas_core/raiz_publicada.py (nuevo, solo biblioteca estándar). Al importar atlas_core redirige `--raiz-atlas`/`ATLAS_DATA_DIR` de la raíz publicada a la de trabajo. desktop_operacion redirige su solicitud y responde con rutas de la publicada. `compartida()` (desktop_operacion y exclusion_local) incluye la raíz de trabajo.
  - actualizar_atlas.py importa atlas_core antes de leer argumentos y redirige la raíz de la configuración.
- R2 (P0.3.1): la raíz publicada real (G:) está protegida por la guardia del turno local, así que publicar sin su turno fallaba siempre. Corrección: la publicación toma el turno de la raíz publicada.
- R3 (P0.5): la salud de una versión de Desktop solo miraba la cabecera del asar. Ahora arranca Electron de verdad, aislado (sin datos, sin credenciales, sin autorización de escritura, carpeta de usuario temporal y puerto de depuración local), y exige que cargue atlas_viajes.html. Parámetro `--desktop-exe`, que por omisión es el exe junto a resources.

Validación integral (scripts/validacion_diario_remoto/validar_integral.py): **36/36**.
- Entorno: dos instalaciones aisladas, cada una con Motor clonado de un origin local, copia del Atlas Viajes instalado (Electron real inspeccionado por CDP), Drive protegida como G:, raíz de trabajo y LOCALAPPDATA propio. Worker b28d594 real con métricas, PULL real, OCR RapidOCR real, B1 desde la ventana real y datos sintéticos MBTMARCA.
- Ingesta Mobile completa: OCR, dataset, reporte, publicación en Drive y visualización en Desktop.
- Pérdida y recuperación:
  - Desktop no ve el turno sin confirmar de X.
  - X se elimina por completo.
  - El PULL de Y lo recupera solo, procesa un envío nuevo, no duplica y Desktop lo muestra.
- Corrección B1 desde la ventana real (preview y «sí»), publicada en Drive.
- Informes y exportaciones: reporte vigente, Excel real del renderer y HTML del PDF MBT con los 5 viajes confirmados.
- Actualización: versión Motor C2 + Desktop v2 aplicada al iniciar, con arranque real de Electron. Una versión con Desktop roto se revierte sola y Desktop vuelve a abrir.
- Drive siempre igual al estado confirmado, y un proceso del Motor no puede escribir directo en Drive (guardia).

Costo Cloud (medir_costo_cloud.py), con la carga real de MBT medida en solo lectura: 12 guías/día (máximo 21), dataset de 5,7 MB, foto de 2,6 MB, 43 % Mobile.
- Por guía: ~157 solicitudes, ~44 filas D1 y 7 contenidos del dataset custodiados. Un ciclo ocioso: 6 solicitudes y 0 escrituras.
- Proyección: ~6.100 solicitudes/día, ~530 filas D1/día (~193.000/año) y ~490 MB/día de R2 y de subida (~175 GB/año).
- Sin compactación ni recolección de basura: conviene compactar en el Worker antes de un año.

Migración coordinada (scripts/migracion_p0, ver PLAN_MIGRACION_P0.md): preflight.ps1, migrar_equipo.ps1, revertir_equipo.ps1 y protocolo_d1.ps1. Todos simulan si no reciben `-Aplicar`.
- Ensayo validar_migracion.py: **20/20**, sobre un equipo sintético con el Motor 48d6096 instalado y el Worker real:
  - comprobación previa;
  - migración con respaldos (rama remota, configuración local, asar, acceso directo);
  - PULL con OCR;
  - protocolo 3 que excluye al Motor anterior;
  - reversión con el Motor anterior trabajando y 0 diferencias.

Pruebas: tests/test_p0_integral_regresiones.py con 6 pruebas; la de R2 falla sin la corrección. Suite completa: 46 fallas contra 46 en 48d6096. Las diferencias son intermitentes de reloj: test_falso_ok_obra_destino_p1, y test_trazabilidad_ocr::test_traza_no_cambia_campos_finales_extraidos, que falla 2 de 10 veces tanto en la base como en la rama. Las validaciones P0.1 a P0.5 aprueban.

No se tocaron Atlas Viajes instalado (solo se copió), CASA, PULL, Drive ni Cloud productiva.


## Instalación P0: corrección R4 e instalador por equipo (27/11/2026)

Sobre 3456d77. Lo detectó el reconocimiento previo a la migración productiva de CASA.

- R4 (P0.3.1/P0.6): el lanzador productivo del PULL (`scripts/pull_pc_nuevo.ps1`) exporta `ATLAS_CATALOGOS_DIR` sobre la raíz configurada (G:), y la redirección solo cubría `ATLAS_DATA_DIR`. El PULL habría usado los catálogos de Drive, y sus escrituras de catálogos chocarían con la guardia o quedarían fuera de la custodia.
  - Corrección: `raiz_publicada.redirigir_proceso` redirige toda variable `ATLAS_*` que nombra la raíz publicada o algo dentro de ella, salvo `ATLAS_EXCLUSION_RAICES`.
  - La prueba en test_p0_integral_regresiones.py falla sin la corrección.
  - La validación integral ahora corre el PULL con el lanzador real pull_pc_nuevo.ps1: 36/36.
- `scripts/migracion_p0/instalar_equipo.ps1`: instalador por equipo (identidad, respaldo y stash de cambios locales, cierre de Desktop, preflight con espera, migración y verificación).
- Accesos directos múltiples, que vuelven al exe si `iniciar_atlas.ps1` no existe.
- Ensayo validar_migracion.py: 23/23, incluye el árbol sucio como en CASA y dos accesos directos. Pruebas focales del P0: 381/381.


## Migración productiva P0: CASA (27/11/2026)

CASA = JAVO, MachineGuid 0fb5d7fa-4e1a-44ed-b103-2b8f9e189150, escritor pc-b7804417-42c3-4be3-b8b1-9ea3db3ec36b. Motor instalado **8d699c1** en C:\Atlas\Proyecto-Atlas (rama casa/asociacion-manual-mobile-20261126 avanzada por fast-forward).

- Respaldos:
  - origin/respaldo/antes-p0-casa-20261127-133053 = 48d6096;
  - LOCALAPPDATA\Atlas\respaldo-p0-20261127-133053 (configuración y accesos directos);
  - app.asar.antes-p0-20261127-133053;
  - notas de Codex: stash «antes-p0-casa-20261127-133038» y copia en respaldo-p0-cambios-locales-20261127-133038.
- Raíz de trabajo C:\AtlasTrabajo\Atlas; G: pasa a ser la raíz publicada (raiz_publicada.json). Accesos directos del escritorio y del menú Inicio apuntan a iniciar_atlas.ps1, con vuelta al exe.
- Defectos del P0 encontrados en producción y corregidos antes o durante la instalación (decisión de Javier):
  - ATLAS_CATALOGOS_DIR del lanzador sin redirigir (1d208ca);
  - conteo de tareas y procesos de un elemento en PowerShell 5.1 (3390845);
  - valores relativos resueltos contra la carpeta actual: el token se corrompía con la carpeta actual en G: (8d699c1).
- Javier reabrió Desktop durante la migración e ingresó 2 guías (492336, 492337). Ese ingreso pasó por el camino P0 y quedó confirmado y publicado.
- Verificación:
  - ciclos PULL con código 0 en 8d699c1 (13:54 y 13:56), con la raíz redirigida;
  - custodia v827: 1381 archivos, 0 distintos, sin diarios ni publicación pendiente;
  - G: idéntico a Cloud en 1381 rutas, y los 17 archivos cambiados en G: desde la migración están confirmados;
  - consulta B1 de solo lectura sobre G: correcta, con el dataset intacto;
  - iniciar_atlas.ps1 responde SIN_VERSION_PUBLICADA;
  - recepción Mobile: ciclos con consulta de pendientes correcta; no hubo envíos reales en la ventana.
- NO activados, por decisión de Javier: protocolo 3 y primera versión publicada. OFICINA sin migrar: ver scripts/migracion_p0/OFICINA_PENDIENTE.md, mismo commit 8d699c1.
- Notas de Codex reaplicadas sin commit en el Motor instalado, lo que bloquea la actualización automática y revertir_equipo.ps1 hasta que se hagan commit o se muevan.
