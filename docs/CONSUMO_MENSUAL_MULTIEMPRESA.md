# Medicion mensual de documentos: investigacion

Estado: no implementado; no apto para facturacion. Base 59c3f33.

La medicion debe registrar una sola unidad por documento terminado y aceptado, por empresa, con mes calculado en su zona horaria configurada. Reintentos, duplicados, relecturas, reprocesos y correcciones no deben crear otra unidad; Mobile puede aportar varias guias.

## Evidencia de la base

* `clasificar_reingesta_documental` identifica duplicados confirmados solo mediante guia y transporte validos. Una identidad incompleta se clasifica como nueva y una guia con transporte distinto pasa al flujo normal. Una correccion de estos campos puede cambiar esa clave. No es una identidad inmutable suficiente para facturacion.
* `procesar_carpeta` escribe el dataset por lotes, conserva filas de error y la relectura promovida figura en `archivos_procesados_ahora`. Este resumen no es un registro de nuevas unidades aceptadas. El campo `fecha_ingesta_utc` representa procesamiento, no una prueba durable de finalizacion y unicidad.
* La base de alta y aislamiento de empresas no configura una zona horaria por empresa. La zona del host o el instante de recepcion no son sustitutos seguros.
* El lock y la escritura atomica de archivos existentes protegen recursos individuales. Una escritura adicional despues del dataset puede perderse ante un corte; escribirla antes puede contar un documento que no termino. Sin un compromiso durable comun o recuperacion verificable no se garantiza contabilizacion exacta.

## Coordinacion requerida

Coordinar con Code un identificador documental estable y su continuidad al corregir, resolver identidades ambiguas y reprocesar; una fuente validada de zona horaria IANA por empresa; y un punto durable de finalizacion con publicacion recuperable e idempotente. La identidad y la configuracion estan en trabajo concurrente. No se debe atribuir una unidad a una identidad ambigua ni sustituir la zona faltante por la del equipo.

Una implementacion debe demostrar, con MBT y Andes ficticias, varias guias por envio, duplicados incluso entre lotes y reinicios, correcciones de identidad, reprocesos, errores, cortes antes y despues de la publicacion, concurrencia, igual folio en empresas distintas y cambio de mes en cada zona. Consultas y evidencia deben poder auditar la identidad, empresa, instante y periodo sin exponer ni alterar datos operacionales. No se ha implementado el contador ni ejecutado esas validaciones.
