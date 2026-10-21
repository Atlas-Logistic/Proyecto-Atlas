# Operación manual en JAVO — 21/10/2026

Sustituye la conclusión anterior sobre una credencial de oficina: Javier confirmó que hay un único computador, siempre con él. El ingreso manual no consume PULL ni necesita autenticarse en Cloud.

`ATLAS_CLOUD_MOTOR_TOKEN` es el Bearer de `CLOUD_MOTOR_AUTH_SECRET` del Worker Atlas Mobile Cloud. No lo emite Desktop: un administrador configura el mismo secreto en el Worker y en el cliente autorizado. El script Cloud `configurar_secreto_motor_prueba.ps1` sirve para ese aprovisionamiento. No se ejecutó, no se generó ningún secreto y no se desplegó Cloud.

La política local explícita `modo_escritor=equipo_unico` está ligada al hostname, MachineGuid y raíz exacta. Adquiere un mutex Global de Windows antes de crear locks/entradas; rechaza otro escritor y comprueba periódicamente que no existan procesos o tareas PULL habilitados. Si se pierde esa condición, las escrituras fallan cerrado. El perfil no se deduce de un token ausente. Para varios computadores se conserva el lease Cloud y su credencial legítima.

Los locks de archivo del Motor permanecen. Tras una caída, sólo bajo mutex adquirido se recuperan locks del mismo host cuyo PID se comprueba terminado; un PID vivo, inaccesible o remoto se conserva. El guardián de escrituras sigue limitado a la raíz aprobada, temporales, modelos y el directorio local de caché derivado. El caché de relaciones históricas siempre se verifica contra las huellas de los reportes; no reemplaza al dataset.

El ingreso usa Python de `.venv`, conserva el original y evita reingresar una guía numérica ya existente. Mantiene las decisiones ajenas al alcance focal y no revalida rutas geográficas ajenas durante ese ingreso. La búsqueda de reportes enumera sólo el directorio padre, sin listar cada subcarpeta remota.

Validación final: 96 pruebas Motor focales/regresión; Windows mutex entre procesos, pérdida/ocupación y recuperación de locks; prueba de ingreso/selector/revisión/lector en la aplicación instalada con datos aislados. La primera guía real autorizada se conserva una sola vez y se visualiza en la aplicación principal; los campos no reconocidos se mantienen para revisión, sin confirmación ficticia. Evidencia local en C:\Atlas\cierre-desktop-20261021. No se versionan datos operacionales, imágenes ni configuración local con identidad del equipo.

