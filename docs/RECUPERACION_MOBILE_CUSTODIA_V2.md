# Recuperacion explicita Mobile con custodia protocolo 2

Cambio preparado, no desplegado. Esta herramienta realiza escrituras operacionales y OCR: no ejecutarla hasta tener autorizacion explicita, diagnostico cerrado, ventana segura y respaldo verificado. No operar mientras otro escritor este activo.

El repositorio Mobile y el dataset deben estar bajo la misma raiz operacional. Se vincula la raiz antes de adquirir el turno local y lease Cloud, que alinea custodia; si no puede verificarse, no procesa. Tras alinear se vuelve a comprobar el dataset configurado. La guardia comprueba la vigencia durante escrituras y la CLI confirma explicitamente la custodia antes de devolver resultado. Se mantienen las validaciones originales de estado ERROR, identidad, foto, duplicados y permiso.

Uso una vez instalado y autorizado (credencial por entorno, no en linea de comandos):

```
python recuperar_envio_mobile_error.py --envio-id <UUID> --raiz-atlas <RAIZ_OPERACIONAL>
```

Exige ATLAS_CLOUD_MOTOR_TOKEN y la configuracion de Cloud del entorno. NO_ADQUIRIDO y su motivo significan que no se inicio el procesamiento; no forzar lease ni saltar alineacion. Un resultado con custodia incluye version y numero de rutas confirmadas: contrastar estado del envio, dataset y marca conforme al procedimiento operativo antes de declarar exito. Un resultado de procesamiento ERROR no es recuperacion exitosa.

Si se pierde el lease, falla la confirmacion, se interrumpe el proceso o aparece excepcion, no repetir a ciegas. La operacion puede haber escrito parcialmente; conservar diario y evidencia, verificar lease, marca, registro del envio y presencia de fila documental. El cierre intenta confirmar cambios parciales; si no puede, el diario local permanece y el protocolo puede confirmar o poner en cuarentena segun la version y titular posteriores. No garantiza atomicidad ni recuperacion automatica de todo corte; no restaurar ni reprocesar hasta determinar el estado. El protocolo de custodia vigente tiene prioridad sobre una supuesta reversibilidad del comando.
