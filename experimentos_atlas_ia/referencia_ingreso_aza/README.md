# Referencia para evaluar la calidad de ingreso de guías AZA

Herramienta y método para preparar una muestra de guías AZA con valores de
referencia por campo, con la que evaluar el ingreso actual de Atlas (Mobile y
Desktop manual). Sólo lee las fuentes: no ejecuta OCR, no corrige guías ni
escribe en Drive, Motor, Desktop, Mobile, Cloud o PULL.

**Las imágenes, el manifiesto y los valores de referencia son privados y no se
versionan.** Aquí sólo viven la herramienta y este documento.

## Uso

```powershell
python -I construir_referencia.py --raiz-atlas "G:\Mi unidad\Atlas" `
  --motor C:\Atlas\Proyecto-Atlas --salida <dir_privado_nuevo> `
  --discrepancias <dir_privado>\discrepancias_bitacora_o1.json
```

Sólo usa la biblioteca estándar (`leer_xlsx.py` lee .xlsx sin `openpyxl`) e
importa `atlas_core.validadores.validar_rut_chileno` de Motor, que sólo
depende de `atlas_core.modelos`. La salida debe ser un directorio nuevo.

Entregables (en `<dir_privado_nuevo>`):

| Archivo | Contenido |
|---|---|
| `imagenes/` | Copias de cada imagen o PDF, con prefijo `A##`/`B##`/`C##` |
| `manifiesto.csv` | Procedencia, SHA-256, bytes, formato, resolución, páginas y criterio de selección por muestra |
| `referencia_campos.csv` | Una fila por muestra y campo: valor de referencia, estado, valor crudo, fuente, alternativa no confirmada y nota |
| `pendientes_confirmacion.csv` | Subconjunto de A que una persona debe confirmar mirando la imagen |
| `planilla_confirmacion.csv` | Formato ancho (campo + `__estado`) para completar B, C y los pendientes de A |
| `resumen.json` | SHA de herramienta y fuentes, commit de Motor, universo, conteos por estado y campo |
| `SHA256SUMS` | Sumas de todos los entregables (`sha256sum -c SHA256SUMS`) |

## Campos y estados

Campos: `fecha_emision`, `numero_guia`, `numero_transporte`, `cliente`,
`rut_cliente`, `obra_destino`, `cod_destinatario`, `direccion_destino`,
`comuna`, `despachar_a`, `chofer`, `rut_chofer`, `patente_tracto`,
`patente_rampla`, `descripcion_material`, `peso_kg`, `hora_entrada`,
`hora_salida`.

| Estado | Significado |
|---|---|
| `CONFIRMADO_HUMANO` | Valor transcrito y validado por una persona, sin dudas registradas |
| `AUSENTE` | La persona registró que el campo no aparece en una guía completa |
| `ILEGIBLE` | Guía marcada ilegible por la persona y campo vacío |
| `NO_APLICA` | Sólo si una persona lo declara; no se infiere (hoy 0 casos) |
| `PENDIENTE_CONFIRMACION` | Sin referencia humana, con duda registrada o con evidencia en conflicto |

Normalización, siempre conservando el valor crudo: fecha serial de Excel a
`AAAA-MM-DD`, hora como fracción de día a `HH:MM:SS`, peso `12.345,00` a
`12345` kg. Si el formato no se puede interpretar sin suponer (por ejemplo
`12.345678` o `10:20;00`), el campo queda pendiente.

## Fuentes y bloques

**A: referencia humana existente (30 guías).** Fotos de
`datos_privados/muestra_fechas_30` y planilla
`datos_privados/ground_truth/validacion_atlas_30_guias_v1.xlsx` (idéntica a
`validacion_completa_30_guias_ordenada.xlsx`). `..._sap_corregido.xlsx` sólo
cambia el N° SAP (fuera de alcance) y recorta una observación. Selección
original documentada en `validaciones_historicas/resumen_seleccion.md`.

Reglas que dejan un campo de A en `PENDIENTE_CONFIRMACION`:

1. Hoja «Pendientes de verificación» **sin resolver**. Esa hoja es la lista de
   dudas previa a la revisión: comparada con `..._prellenada.xlsx`, la persona
   cambió 100 de los 118 campos y validó la fila (`VALIDADO = SI`). Un campo
   cuenta como resuelto sólo si su valor final difiere del prellenado.
2. Marcas de duda en el valor (`?`, `REVISAR`).
3. Discrepancias de la bitácora técnica de Motor (bloque O1, 2026-08-11). La
   alternativa proviene de una verificación visual de un agente y se anota
   como `alternativa_no_confirmada`, nunca como referencia.
4. Fecha distinta en `muestra_fechas_revision_actualizada.xlsx` (revisión
   humana de fechas).
5. RUT inválido según `validar_rut_chileno`; patente fuera de los formatos
   chilenos `LLNNNN`/`LLLLNN`; código destinatario igual al código cliente
   (confusión de campo detectada en D3).
6. Guía marcada `ILEGIBLE` con valores escritos (la observación del validador
   indica deducción), o campo vacío en una guía `INCOMPLETA`.
7. `despachar_a`: no existe en la planilla. Según la regla E1, la ruta usa
   DESPACHAR A, distinto de la obra o dirección registradas.

La columna `fuente` distingue entre «corregido en revisión humana» y «valor
prellenado, fila validada por persona». El origen del prellenado no está
documentado.

**B: canal Mobile actual (20 envíos).** Proviene de `operacion/mobile/envios`
(174 envíos con rol GUIA o sin rol; se excluye el rol EVIDENCIA). De
`envio.json` sólo se leen metadatos del chofer o de la recepción (fecha,
chofer, rol, novedades, guía firmada por correo, SHA declarado). **Nunca
`datos_ocr`, `resultado_asociacion`, `estado` ni `atlas_ia`.** Orden de
selección:

1. Un envío por cada novedad declarada.
2. Dos guías firmadas por correo.
3. Al menos un envío por chofer.
4. El resto, equidistante por fecha con `round(i·(N−1)/(k−1))`, la misma regla
   de la selección histórica.

Los choferes se seudonimizan como `CH##`. Todos los campos quedan pendientes.

**C: ingreso manual Desktop (15 archivos).** Proviene de `operacion/entradas`
(455 archivos). Cuotas por formato: 3 PNG, 5 PDF (reenviados `[MBT] … firmada`
y numéricos) y 7 JPEG, equidistantes por carpeta de ingreso y deduplicados por
SHA. El número que aparece en el nombre de archivo se guarda como
`pista_nombre_archivo`, que no es referencia. Todos los campos quedan
pendientes.

## Resultado de la corrida del 2026-10-22

| Bloque | Muestras | Confirmado | Ausente | Ilegible | Pendiente |
|---|---:|---:|---:|---:|---:|
| A (humano) | 30 | 422 | 21 | 1 | 96 |
| B (Mobile) | 20 | 0 | 0 | 0 | 360 |
| C (manual) | 15 | 0 | 0 | 0 | 270 |

De los 96 pendientes de A, 30 son `despachar_a`. Los otros 66 están en 21
guías, y 11 de ellos tienen una alternativa no confirmada.

## Cobertura y brechas

- **Resolución.** A es WhatsApp comprimido (0,9–1,9 MP, mediana 1,4). B son
  originales de cámara (mediana 12,1 MP, hasta 13 MP, incluidas panorámicas de
  4000×1848). Una evaluación basada sólo en A no representa el canal actual.
- **Formatos.** A y B sólo tienen JPEG. C agrega PNG (capturas) y PDF de una
  página. No hay PDF multipágina ni guías en papel escaneadas.
- **Variedad.** A cubre de jun-2025 a jul-2026, 11 choferes y un solo
  transportista (MBT), con 15 imágenes buenas, 6 regulares y 9 borrosas, y
  sólo una rampla registrada. B cubre ago–oct 2026, 10 choferes y las 4
  novedades declaradas.
- **Campos sin referencia humana:** `despachar_a` en toda la muestra y todos
  los campos de B y C.
- **`descripcion_material`** fue resumida por la persona (diámetros, largo,
  norma), no copiada literalmente: se compara semánticamente, no carácter a
  carácter.
- **Patente rampla vacía** significa «no aparece» según el diccionario de la
  planilla. Si un camión rígido realmente no lleva rampla (`NO_APLICA`), debe
  declararlo una persona.

## Respaldo de los estados de A (auditoría 2026-10-22)

`auditar_respaldo_a.py` no modifica la referencia: escribe aparte el respaldo
de cada campo de A. Hechos verificados en las planillas:

- v1 fue creada por un script (openpyxl, 17/07) y guardada después por una
  persona en Excel (18/07). La versión prellenada es salida del script.
- Los colores de celda (verde «alta confianza», amarillo) son idénticos en el
  prellenado: los puso el generador, no son una marca humana.
- `VALIDADO`: 10 filas ya traían «SÍ» desde el prellenado, sin marca humana
  posterior. 20 filas pasaron de «REVISAR» a «SI», lo que es una marca humana
  explícita, pero de fila, no de campo.
- Un cambio frente al prellenado no prueba por sí solo autoría humana del
  campo, y la ausencia de cambio no prueba duda.
- El único respaldo explícito **por campo** es `fecha_real_validada` de la
  revisión humana de fechas.

| Respaldo | Campos de A |
|---|---:|
| `EXPLICITO_CAMPO_REVISION_FECHAS` | 29 |
| `CONFLICTO_ENTRE_FUENTES_HUMANAS` | 1 |
| `EXPLICITO_FILA` (fila marcada SI tras el prellenado) | 320 |
| `NINGUNO` (fila «SÍ» del generador) | 160 |
| `SIN_FUENTE` (`despachar_a`) | 30 |

144 valores marcados hoy `CONFIRMADO_HUMANO` tienen respaldo `NINGUNO`. Un
comparador estricto debe filtrar por la columna `respaldo`.

## Propuestas visuales del agente y revisión por lotes

Las lecturas del agente se guardan **separadas** de la referencia, con
`fuente = AGENTE_VISUAL <modelo>`, el recorte usado como evidencia y su caja
normalizada. Sólo cubren campos `PENDIENTE_CONFIRMACION` (todos los de B y C,
y los pendientes de A). No se usó OCR ni resultados de Atlas. No se completó
nada a partir de otras guías ni de catálogos.

Estados de propuesta: `PROPUESTA`, `AMBIGUO` (los caracteres dudosos se
marcan con `?`), `ILEGIBLE`, `AUSENTE_EN_DOCUMENTO` y `NO_VISIBLE`.

| Bloque | Propuesta | Ambiguo | Ilegible | Ausente en documento | Total |
|---|---:|---:|---:|---:|---:|
| A (pendientes) | 69 | 20 | 1 | 6 | 96 |
| B | 345 | 4 | 0 | 11 | 360 |
| C | 233 | 24 | 8 | 5 | 270 |

Herramientas:

- `recortar.py`: recorta, rota y amplía con Pillow. Caja normalizada 0–1; sin
  OCR.
- `preparar_revision.py`: genera `propuestas_agente.csv` y lotes de hasta 50
  filas sin partir guías. Cada lote tiene una página HTML estática (recorte
  junto a la propuesta, sin scripts ni recursos externos) y un CSV donde la
  persona registra `ACEPTAR`, `CORREGIR` (con `valor_corregido` o
  `estado_corregido`) o `DUDA`.

Regla para el comparador: leer sólo `referencia_campos.csv`. Las propuestas
pasan a la referencia únicamente con una decisión humana registrada en el CSV
del lote; hasta entonces cuentan como pendientes.

Hallazgos visuales que conviene confirmar primero: el código de destinatario
impreso coincide con el código de cliente en varias guías (es el documento, no
un error de transcripción). La planilla registra en algunos casos SOLICITANTE
u OBRA como cliente, o DESPACHAR A como dirección. Hay patentes leídas con un
carácter distinto del registrado.

## Reutilizable para el comparador

En Motor: `atlas_core.catalogos.normalizar_rut` y `normalizar_patente`,
`atlas_core.validadores.validar_rut_chileno`,
`atlas_core.territorio_chile.normalizar_comuna`,
`atlas_core.normalizacion_semantica.normalizar_nombre_societario` y
`atlas_core.atlas_ia.candidatos_externos.comparar_*`. El contrato
`atlas_core.atlas_ia.contratos.ResultadoShadow.ground_truth_humano` ya prevé
una referencia humana que nunca se entrega al modelo.

Regla para cualquier evaluación: comparar sólo contra `CONFIRMADO_HUMANO`,
`AUSENTE` e `ILEGIBLE`, y contar `PENDIENTE_CONFIRMACION` aparte, nunca como
acierto ni como error.
