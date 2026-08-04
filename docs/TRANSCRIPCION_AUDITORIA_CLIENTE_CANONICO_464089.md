# Transcripción técnica — Auditoría de Cliente canónico 464089

Se recorrió el campo Cliente desde la imagen real hasta Atlas Desktop. El OCR
completo contiene `SEÑOR(ES) COMERCIAL B LIDA` y un RUT degradado. La etapa de
extracción reduce el nombre a `COMERCIAL` y deja el RUT como `No encontrado`.

El Resolver de Clientes, ejecutado con el catálogo privado activo, devuelve
`NO_RESUELTO`, valor canónico nulo, identificador nulo, confianza 0,0. La razón
social documental `COMERCIAL A Y B LTDA` y su RUT `78.634.910-9` no existen en
el catálogo. La Política de Activación PRODUCTIVO publica entonces el valor
OCR anterior: `COMERCIAL`.

El mismo valor aparece en `analisis_completo_guias.csv`, en la columna
`clientes` de `viajes.csv`, en `evidencias_documentos` y en la vista Desktop.
La causa está antes de la publicación: evidencia OCR/extracción insuficiente y
catálogo sin la entidad; no en la Política, el reporte ni la interfaz.
