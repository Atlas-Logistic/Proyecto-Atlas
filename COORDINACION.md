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

## Reserva liberada — OFICINA (JAVO): actualización Motor + Desktop (2026-11-25)

- Equipo: OFICINA, hostname JAVO, MachineGuid 354cc598-6628-4cb1-af15-05fa4ee7f1a8. Autoriza Javier.
- Motor Estable: `918d629` → `26fa210` (avance directo con `scripts/actualizar_equipo_relevo.ps1`, rama local deploy/estable-oficina-20261125, árbol limpio). Sin multiempresa (f4b7775/b09bd28) ni acceso admin MBT.
- Desktop: app.asar `f41a13a` (31099128…) → `327c69e` construido en OFICINA (`electron-builder --win --dir`, worktree core.autocrlf=true): **0C1159AD…496D**. No reproduce el 9B8A688A de CASA; una compilación LF exacta da 94C9C31F…. Los fuentes del asar coinciden con 327c69e salvo fin de línea; exe, config.json y app.asar.unpacked idénticos al instalado. Javier eligió instalar 0C1159AD.
- Mobile 0.17.23, Worker y CASA sin cambios.
- Custodia: la verificación inicial contra Cloud v669 dio 1 distinto (`operacion/evidencia_orientada/2413aa6d…json`, escrito por el ciclo cortado del 19-11 11:50, pendiente local base v535). El primer ciclo lo puso en cuarentena local (`%LOCALAPPDATA%\Atlas\cache\estado_confirmado\cuarentena\20261125T101433096277Z`) y restauró la versión Cloud. Después: v669, 1257 archivos, 0 distintos. OFICINA tomó el turno por relevo (época 6751 → 7807).
- PULL: el ciclo de las 06:48 (Motor 918d629) tardó 15 min en arrancar tras el encendido (INICIO 07:03:41, espera de E/S, sin escrituras); Javier lo finalizó. Con 26fa210: ciclo 07:13:14–07:15:41 FIN 0 (alineación) y 07:20:47–07:21:33 FIN 0. Tarea reactivada.
- Verificado en solo lectura: Desktop carga el reporte vigente (719 viajes; ayer 8, 15 días 64), bandeja Revisión de Atlas sin pendientes (10 fotos descartadas, 9 guías móviles), B1 responde desde Desktop, informe MBT genera el PDF (la vista previa no dibuja con la ventana oculta tras VS Code: falta mirarla en pantalla), expediente SX4253 (5 activos + 1 pendiente; revisión técnica y gases vencen 25-11), coberturas confirmables a mano (RC, seguro de carga, robo). El CLI B1 sin turno queda bloqueado por EscrituraSinTurno, como corresponde.
- Respaldo y reversión: `C:\Atlas\actualizacion-oficina-20261125\respaldo` (bundle 918d629, app.asar f41a13a, config, tarea XML). Revertir: deshabilitar tarea y esperar ciclo, `git switch deploy/estable-oficina-20261111` en Estable, copiar el app.asar del respaldo, reactivar.

## Reserva liberada — OFICINA (JAVO): relevo Motor b0b42e4 + Desktop 2914483 (2026-11-26)

- Equipo: OFICINA, hostname JAVO, MachineGuid 354cc598-6628-4cb1-af15-05fa4ee7f1a8. Autoriza Javier (opción 2).
- Kit oficial `G:\Mi unidad\Atlas\coordinacion\ACTUALIZAR_OFICINA\ACTUALIZAR_ESTE_PC.ps1`: se detuvo antes de cambiar nada porque el app.asar instalado en OFICINA (`0C1159ADC24F833C12E1785ABFB77F28194EEBFB97E6759B3F7843C6D979496D`) no estaba en `$anteriores`. Se confirmó que es la compilación OFICINA de `327c69e`: coincide byte a byte con `C:\Atlasctualizacion-oficina-20261125\desktop-327c69e\dist\win-unpackedesourcespp.asar`, árbol en 327c69e sin cambios. Se agregó ese SHA-256 completo a `$anteriores` sin tocar la comprobación. El kit queda válido para CASA (9B8A688A) y OFICINA (0C1159AD). Respaldo del script previo (A2401F20…): `C:\Atlaselevo-oficina-20261126espaldo_kit\` y `ACTUALIZAR_OFICINAnterior-b1-adicionales-multiples-20261125\ACTUALIZAR_ESTE_PC.ps1.antes-hash-oficina-20261126`.
- Paquete `b1-pdf.asar`: SHA-256 completo `E2C7E61B106A8E244E7649DB9DD6DE636871A60909DE5F534F8B3C2728030C05` verificado antes de instalar.
- Relevo de escritor previo: el ciclo de las 09:29 (Motor 26fa210) perdió el lease durante el arranque en frío y terminó con código 1, sin confirmar nada en Cloud. El ciclo 09:37–09:46 terminó con FIN 0: confirmó 2 envíos Mobile (a9cc50f4, 27015b62). OFICINA tomó el turno: época 7812 → 8195. Custodia antes del kit: v695, 1302 archivos, 0 distintos.
- Kit ejecutado entre 09:47 y 09:48:43, EXIT 0. El script oficial pausó la tarea PULL, esperó el fin natural del ciclo, hizo fast-forward `26fa210` → `b0b42e4` y reactivó la tarea. Verificación en solo lectura: v696, 1311 archivos, 0 distintos. Desktop app.asar = E2C7E61B; respaldo `app.asar.antes-b1-pdf-20261125` = 0C1159AD. Mobile 0.17.23, Worker y CASA sin cambios.
- PULL con b0b42e4: ciclos 09:51:13–09:51:48 y 09:55:55–09:56:29, ambos FIN 0, sin pérdida de escritor. Tarea en Ready. Época 8197. Custodia final: v696, 1311 archivos, 0 distintos.
- Verificado por CDP con la ventana visible: Desktop carga 728 viajes sin franja de modo. B1 «Viajes de ayer» devuelve 7 viajes (periodo AYER) con tabla y botón «Exportar PDF». La vista previa «listado_viajes.pdf · 1 página» muestra 7 viajes del 25-11 agrupados por chofer (captura `C:\Atlaselevo-oficina-20261126ista_previa_b1_pdf.png`). Se cerró con «Volver», sin descargar. Atlas se reabrió desde el acceso directo normal, sin puerto de depuración.
- Accesos directos: uno en el escritorio, `Atlas.lnk`, que apunta a `%LOCALAPPDATA%\Programs\Atlas Viajes\Atlas Viajes.exe`. La entrada del menú Inicio del instalador apunta al mismo ejecutable.
- Observación menor, sin cambio: la ventana de vista previa B1 conserva el título «Vista previa — Informe MBT PDF», aunque su cabecera dice «Vista previa - Listado».
- Reversión: deshabilitar la tarea y esperar el fin del ciclo. Restaurar `app.asar.antes-b1-pdf-20261125` (0C1159AD) sobre `app.asar`. En Estable (rama local deploy/estable-oficina-20261125), `git reset --keep 26fa210`. Luego reactivar la tarea.
