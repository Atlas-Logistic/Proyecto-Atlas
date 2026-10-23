# Reparador: RapidOCR y procedencia documental (23/10/2026)

## Problema
`reprocesamiento_reparador` sólo reconocía `PaddleOCRProvider` como OCR principal y promovía
cualquier valor con formato válido. En la relectura RapidOCR de 12 guías leídas con EasyOCR de
respaldo propuso 20 valores incorrectos: hora de entrada como salida (482580), monto como peso
(482580), carro como tracto (482661, 482634), horas cruzadas (473325), un RUT no impreso (482553),
destinos con texto de otra sección o ilegibles, y borraba la patente J56468 con "No encontrado".

## Cambio
- `RapidOCRProvider` (incluye `RapidOCRManualProvider`) cuenta como relectura del OCR principal.
  El proveedor sigue saliendo de la configuración (`ATLAS_OCR_PROVIDER`); no se cambia el OCR de Atlas.
- La reextracción persiste su traza en un directorio temporal propio; el reparador lee de ahí
  las líneas y bloques de la lectura de la que salió cada valor.
- Procedencia por campo (`_valor_con_procedencia`); sin evidencia, abstención:
  - horas: el bloque de la hora tiene como etiqueta más cercana de su fila la de ese campo;
  - peso: igual al valor alineado con `PESO KG.` o a `PESO BRUTO - TARA`; nunca montos;
  - patentes: impresas; el tracto no es el valor tras `CARRO`, la rampla no es el que lo precede;
  - RUT chofer/cliente y transporte: el literal está impreso en la lectura.
- Un valor que la propia reextracción marca degradado (`*_SIN_CORROBORAR`, etc.) no se promueve.
- Destino: rechaza etiquetas de otra sección (`RUTCHOFER`, `FECHASALIDA`, ...) y textos sin calle y
  número o con tokens que mezclan letras y dígitos (`525HANTIAGO`, `13I3`).
- Una ausencia nunca reemplaza un valor presente.
- Coherencia: salida no posterior a la entrada (ambas respaldadas) o tracto igual a rampla no se
  promueven; la permanencia se calcula de horas finales respaldadas por la misma lectura.

## Laboratorio (copia aislada, RapidOCR, dry_run, 12 documentos)
| | Antes | Después |
|---|---|---|
| Valores correctos propuestos | 43 | 43 |
| Valores incorrectos propuestos | 20 | 3 |
| Abstenciones | — | 19 |

Incorrectos restantes: 473326 destino con número de calle mal leído ("97" por "5497"), material
de 473412/473444 con errores tipográficos/líneas faltantes (reemplazan texto aún peor). No son
confusiones de campo; quedan con su motivo para revisión.

## Pruebas
`tests/test_reparador_rapidocr_semantico.py` (bloques reales de laboratorio). Los dobles de
`procesar_archivo` de las suites del reparador publican su lectura con
`tests/lectura_ocr_reparador.con_lectura`.
