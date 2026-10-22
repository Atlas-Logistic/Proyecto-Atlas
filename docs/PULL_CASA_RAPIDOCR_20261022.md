# PULL CASA con RapidOCR y lease compartido

## Estado de cierre: NO reactivar autom?ticamente

Los cuatro env?os se recuperaron con RapidOCR y ACK normal, pero la tarea CASA qued? Disabled y el gate se retir?. El ciclo 22/10 16:18:15?16:26:03 termin? con c?digo 0; ese ?xito t?cnico NO certifica respeto del alcance solicitado.

La activaci?n expuso una dependencia no detectada por las pruebas focales del lanzador/lease: `mobile._regenerar_reporte_tras_envio_mobile` llama `revalidar_y_regenerar_reporte` sin alcance (mobile.py:2405), y `reconciliar_bandeja_diferida_mobile` llama al reconciliador global sin alcance (mobile.py:2950 aprox.; invocado por cloud_mobile_sync_cliente.py:296). El resumen acredita que la reconciliaci?n global se ejecut?. No debi? activarse con la prohibici?n de reconciliaci?n global antes de revisar esas entradas.

Impacto comparado con respaldo: 578 -> 582 filas; 577 filas previas id?nticas, cuatro nuevas y la gu?a previa 482188 con cambios de campos derivados de entrega/ruta (direcci?n/coordenadas administrativas/ruta vaciadas, motivo GEOCODIFICACION_CALLE_DOCUMENTAL_DISTINTA: HOLANDA != NUEVA). No se restaur? a ciegas. Cat?logos conservan sus hashes; decisiones humanas no confirmadas por el agente.

Dependencia m?nima antes de reactivar: focalizar en Motor la regeneraci?n/revalidaci?n y la reconciliaci?n diferida por los documentos/env?os causales, preservando otras filas y tarjetas; comprobar tambi?n la revalidaci?n de asociaci?n de otros env?os. Probar esa preservaci?n con dataset previo y luego evaluar por separado 482188 mediante canal controlado. No requiere cambios en la app Mobile, Desktop ni Cloud, pero ampl?a el alcance m?s all? del lanzador/configuraci?n/tarea y no se implement? en este cierre. No correr nuevamente PULL para intentar repararlo.

Informe privado y reversi?n: C:/Atlas/diagnostico-mobile-20261022/activacion-casa. Las pruebas sint?ticas acreditan solo los controles y la configuraci?n ensayados, no la focalidad del flujo Mobile operativo.

Base d495011. Incremento operacional; no resuelve arbitraje frente a escritores remotos que ignoran Cloud.

## Contrato
- Perfil local existente LOCALAPPDATA/Atlas/desktop_operacion.json: proyecto, raiz, autorizada=true, habilitada=true, modo_escritor=lease_cloud. Conserva equipo/MachineGuid para reversi?n. No se elimina equipo_unico: sigue rechazado por PULL. Manual Motor en ra?z Drive entra por la rama de lease Cloud existente; manual/PULL no comparten mutex local incompatible.
- Credencial ATLAS_CLOUD_MOTOR_TOKEN del usuario Windows. No se copia al JSON, tarea, argumentos ni Git. Perfil opcional python; por defecto proyecto/.venv/Scripts/python.exe. Runtime ATLAS_RAPIDOCR_PYTHON existente o LOCALAPPDATA/Atlas/runtime/rapidocr/Scripts/python.exe. No instalaci?n de dependencias.
- Autorizaci?n local LOCALAPPDATA/Atlas/pull_autorizacion.json: autor Javier, exclusividad_verificada=true y vence_utc futuro. Registrar fundamento real y plazo; no generar este archivo autom?ticamente ni deducir seguridad de lease vac?o. Para esta recuperaci?n el fundamento es OFICINA apagado confirmado por Javier.
- Entrada ?nica pull_pc_nuevo.ps1: RapidOCR, modo no manual, rutas resueltas y gate. ejecutar_pull_cloud_oculto.ps1 delega a esa entrada; ya no contiene rutas personales ni evita gate.
- Lease Cloud actual, heartbeat y margen de relevo conservados. Guardia adicional de mutaciones Python bajo ra?z operacional mientras el lease est? vigente: detiene nuevas aperturas de escritura, reemplazos y borrados al marcarse perdido, tambi?n durante procesamiento. No es fencing distribuido, no intercepta escrituras en handles previamente abiertos ni procesos ajenos al int?rprete. Escritores at?micos publican mediante rename, que queda protegido. Una ca?da puede dejar locks propios recuperables por el procedimiento existente, sin borrarlos manualmente.
- El CLI devuelve c?digo no cero si exclusividad no adquirida/perdida o hay errores de recepci?n/procesamiento. Logging INFO identifica proveedor efectivo; resumen por ciclo prueba los ACK normales en confirmados. No se confirma manualmente.

## Instalaci?n reproducible (pasos operacionales separados)
1. Acreditar exclusividad y ausencia de operaciones activas; mantener OFICINA apagado o sus escritores inmovilizados. Respaldar perfil completo con atributos, autorizaci?n si existe y Export-ScheduledTask antes de modificar.
2. Publicar/probar rama y fast-forward del Motor operativo sin WIP; no cambiar Desktop/Mobile/Cloud.
3. Cambiar expl?citamente modo_escritor a lease_cloud y emitir autorizaci?n con plazo y fundamento. No cambiar tokens. Validar worker RapidOCR existente y ejecutar pull_pc_nuevo.ps1 -Validar (no consulta Cloud ni hace OCR).
4. Ejecutar scripts/instalar_tarea_pull.ps1 -Plan para revisar, luego sin -Plan. Reutiliza por defecto Atlas PULL PC nuevo - DESHABILITADO; rechaza otras tareas consumidoras y reinstalaci?n con tarea activa. Respalda XML previo, registra deshabilitada con IgnoreNew, al inicio de sesi?n y repetici?n cada cinco minutos (CadaMinutos configurable). Perfil interactivo del usuario, ejecuci?n ilimitada para no matar OCR. No inicia PULL ni cambia perfil/gate. La pol?tica ExecutionPolicy Bypass es por proceso y sigue la convenci?n del host oculto existente; no evita autorizaci?n Atlas.
5. Revisar XML/acci?n/usuario/triggers antes de Enable-ScheduledTask y Start-ScheduledTask, autorizados de forma separada. Verificar ciclo completo por logs/pull_ciclos, resumen, recepci?n durable, dataset y reporte vigente; despu?s un ciclo iniciado por trigger. Si hay otro titular/consumidor no intervenirlo ni forzar.

## Reversi?n
Deshabilitar tarea y esperar finalizaci?n natural del proceso/lease (no matar OCR). Con exclusividad y sin procesos operativos, restaurar XML previo manteni?ndolo Disabled, perfil y atributos desde respaldo y gate previo o eliminar ?nicamente el gate nuevo conocido. Restaurar Motor al commit base mediante fast-forward inverso aprobado o revert del commit, conservando cambios posteriores. Nunca restaurar snapshots de datos productivos. No volver a equipo_unico mientras siga un ciclo activo. No encender OFICINA con sus escritores activos mientras CASA consuma: antes detener nuevas ejecuciones CASA, esperar cierre y liberar lease; verificar/arbitrar OFICINA antes del relevo. Lease cooperativo no excluye equipo_unico remoto ni consumidores hist?ricos.

## Pruebas
Sint?ticas con perfiles temporales y red simulada: configuraci?n RapidOCR/rutas con espacios, rechazo equipo_unico/gate vencido, plan e instalaci?n repetida con registro simulado, dos equipos contendiendo, p?rdida/renovaci?n/cierre de lease antiguo, guardia durante procesamiento y contenci?n manual/PULL existente. No Cloud productivo en pruebas.
