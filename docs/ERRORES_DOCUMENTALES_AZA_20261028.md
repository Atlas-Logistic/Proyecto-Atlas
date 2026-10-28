# Errores documentales AZA y comuna de destino no oficial (28/10/2026)

## Equipo operacional frente a lo impreso (`atlas_core/equipo_operacional.py`)

El valor operacional de `patente_tracto`/`patente_rampla` de un documento se resuelve en este orden
(reporte de viajes, revalidación de `PATENTE_SIN_HOMOLOGAR` y bandeja), siempre por `archivo` y nunca
propagado a guías hermanas:

1. Ledger de decisiones ya existente (`USAR_PATENTE_EXISTENTE`/`SELECCIONAR_OTRA_PATENTE`).
2. **Error documental AZA confirmado** por el administrador: entrada `ERROR_DOCUMENTAL_AZA` del ledger
   (append-only) con, por campo, el valor impreso y el operacional. Vale mientras la lectura vigente sea
   la registrada.
3. **Regla general conservadora**: chofer inequívoco (chofer operacional fijado, o nombre y RUT impresos
   que corroboran la misma identidad activa) y exactamente una asignación vigente confirmada por un
   humano (`CHOFER_ASIGNAR_VEHICULO`/`rut_chofer_asociado`) para ese tipo, desde una fecha no posterior a
   la guía. Se abstiene ante identidad ambigua o contradictoria, asignación variable o múltiple, patente
   ausente (nunca completa) o patente impresa conocida en el catálogo (posible cambio real de equipo).
4. Convergencia OCR existente.

El dataset documental no se modifica: lo impreso queda en `analisis_completo_guias.csv` y en
`evidencias_documentos` del reporte.

Incidencias: la confirmación registra `ERROR_DOCUMENTAL_AZA` **CONFIRMADA** por campo (patentes y RUT
del chofer). La regla general registra **DETECTADA** sólo si la patente impresa está bien formada y a
distancia de edición ≥ 3 de la operacional (una lectura OCR cercana nunca es incidencia). Una DETECTADA
que luego confirma un humano se reemplaza por la confirmada (misma identidad, sin duplicar). Las
tarjetas `VEHICULO_DESCONOCIDO` de un campo ya resuelto no se republican.

## Acciones (capa canónica, preview + confirmación humana + auditoría)

- `DOCUMENTO_CONFIRMAR_ERROR_DOCUMENTAL_AZA(numero_guia, archivo?, referencia?)`: exige chofer inequívoco
  (fijar antes el chofer operacional si el RUT impreso es de otra identidad) y asignación vigente única
  por tipo; rechaza si la patente impresa es un vehículo conocido.
- `DOCUMENTO_NORMALIZAR_COMUNA_DESTINO(numero_guia, comuna, archivo?, referencia?)`: la comuna impresa
  (último tramo de `despachar_a_crudo` o `localidad_entrega`) no es oficial y la indicada sí
  (`territorio_chile.normalizar_comuna`). Reescribe el destino operacional `<dirección>, <COMUNA>`
  superando la confirmación previa, conserva lo impreso en el ledger (`normalizacion_geografica`),
  corrige la comuna de los destinos del catálogo con esa dirección y comuna no oficial, registra
  `COMUNA_DOCUMENTAL_INCORRECTA` CONFIRMADA y revalida sólo esa guía: la ruta se calcula únicamente si el
  geocodificador devuelve calle y número coherentes.

## Prevención

- `REGISTRAR_DIRECCION` rechaza una `comuna_manual` que no sea comuna oficial (caso 482909, «CAUTIN»).
- El ciclo del PULL (`revalidar_y_regenerar_reporte`) vuelve a retirar los motivos de identidad de chofer
  de documentos con chofer operacional fijado (antes sólo lo hacía `reconciliar_estado_derivado`).
