# Transcripción — Desktop UX: Reprocesamiento Inteligente

## Solicitud

Eliminar la ambigüedad al volver a arrastrar documentos ya procesados y hacer
que la elección del usuario gobierne reutilización, reprocesamiento o
cancelación, sin modificar el motor congelado.

## Resultado

Desktop consulta el CSV antes de iniciar el trabajo y muestra un diálogo nativo
con las tres acciones. El reprocesamiento se ejecuta en un CSV nuevo y se
integra mediante reemplazo atómico, preservando todas las filas no seleccionadas.

Con 464089, reutilizar conservó exactamente el archivo acumulado. Reprocesar
ejecutó OCR, produjo `LEANDRO IOLEDO`, regeneró el reporte y publicó
`LEANDRO TOLEDO` en la vista Desktop, conservando el valor OCR en el JSON de
evidencia.
