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
