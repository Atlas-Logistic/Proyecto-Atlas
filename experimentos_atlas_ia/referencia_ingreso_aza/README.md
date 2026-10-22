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
