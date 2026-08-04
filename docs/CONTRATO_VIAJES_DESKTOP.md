# Contrato de viajes y reportes para Atlas Desktop

## Entrada

`generar_reporte_viajes.py` recibe:

```text
python generar_reporte_viajes.py <csv_masivo> <directorio_nuevo> [--catalogos <directorio>]
```

El CSV usa `;`, codificación UTF-8-SIG y valores de texto.

### Columnas oficiales obligatorias

Son las 15 columnas de `atlas_core.procesamiento_masivo.COLUMNAS`:

```text
archivo
estado_procesamiento
error
numero_guia
numero_transporte
fecha
chofer
rut_chofer
cliente
obra_destino
patente_tracto
patente_rampla
descripcion_material
tipo_carga
indicador_revision
```

La salida nueva de procesamiento añade `peso` como evidencia adicional
compatible. No altera las 15 columnas oficiales: conserva exclusivamente el
valor extraído del documento y el reporte lo incluye en
`evidencias_documentos` para permitir el detalle y la suma conservadora.

### Columnas históricas opcionales

```text
numero_guia_fuente
numero_guia_motivo
rut_chofer_estado_validacion
cliente_fuente
obra_destino_fuente
chofer_fuente
```

Se aceptan columnas adicionales. Las filas no agrupadas conservan exactamente
las columnas recibidas. No se crean valores para columnas ausentes. Todos los
identificadores permanecen como texto para conservar ceros iniciales.

## Agrupación e impacto cruzado

- Solo un transporte presente y con formato válido forma un viaje.
- Varias guías del mismo transporte se agrupan y sus números se conservan.
- Filas exactamente duplicadas no duplican evidencia; filas diferentes nunca
  se eliminan.
- Ausencia no equivale a contradicción y no autoriza copiar el valor de otra
  guía.
- Contradicciones de fecha, chofer, RUT, cliente, destino, origen o patentes
  activan `REQUIERE_REVISION` con motivos explícitos.
- Cliente y destino no se infieren mutuamente.
- El nombre de chofer solo se canoniza mediante el fuzzy conservador oficial.
- `evidencias_documentos` conserva, como JSON, cada fila original que originó
  los valores agregados.

## Salidas

El directorio de salida debe ser nuevo o no contener un reporte anterior:

- `viajes.csv`
- `documentos_sin_transporte.csv`
- `clientes_no_reconocidos.csv`
- `resumen_viajes.md`
- `manifest_reporte_viajes.json`

`viajes.csv` mantiene las columnas consumidas por Desktop y añade evidencia
agregada de destinos, RUT, ramplas, orígenes y filas fuente. Desktop puede
ignorar esas columnas adicionales.

`resumen_procesamiento_desktop.py` conserva los subcomandos `snapshot` y
`resumen` utilizados por el proceso principal de Electron.
