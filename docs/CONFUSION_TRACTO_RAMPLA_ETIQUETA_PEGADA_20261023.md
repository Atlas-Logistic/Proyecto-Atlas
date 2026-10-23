# Confusión tracto/rampla por etiqueta CARRO pegada (23/10/2026)

## Causa raíz
Casos 482953 (José Lazcano, "ND6443CARRO:JB6878") y 482772/482902 (Luis Reyes, "KN5439CARRO:JF6468").
El OCR (RapidOCR) leyó bien las dos patentes, pero en un solo bloque, con la etiqueta CARRO pegada al valor
del tracto. El fallo estaba en el extractor (`_extraer_patentes_geometrico`): las expresiones de etiqueta
usaban `\b`, y no hay borde de palabra entre "3" y "C". La etiqueta no se reconocía, el par CARRO:valor no se
removía, el tracto quedaba como token de 11 caracteres y el único token de 6 que sobrevivía, el del carro, se
tomaba como tracto. La regla `carro != tracto` descartaba entonces el carro. La ruta lineal
(`buscar_chofer_y_patentes`) tenía el mismo defecto. No había decisión de reconciliación involucrada; las
filas quedaban con PATENTE_SIN_HOMOLOGAR sin tarjeta.

## Corrección
- Toda patente chilena termina en dígito. Por eso una etiqueta sólo se rechaza si la precede una letra, y un
  valor de 6 caracteres puede terminar justo antes de una etiqueta pegada.
- El par ETIQUETA:valor siempre se remueve del residual. Ante una etiqueta pegada irreconocible, el
  extractor se abstiene en lugar de tomar el carro.
- La ruta lineal enmascara el par CARRO:valor antes de buscar el tracto.
- Salvaguarda en la ingesta (`clasificar_patentes_por_asignacion_vigente`): aplica con el chofer
  identificado y exactamente un TRACTO y un CARRO vigentes confirmados. Una patente que coincide
  EXACTAMENTE con la asignación vigente, pero que fue leída en el campo del otro tipo, vuelve a su campo.
  - Nunca completa un campo no leído ni corrige valores.
  - Se abstiene ante evidencia contradictoria.
  - La lectura original queda en `metricas.reclasificacion_patentes`.

## Verificación
`tests/test_patentes_etiqueta_pegada_tracto_rampla.py` (14), con coordenadas reales. Suites focales de
patentes, vehículos, extractor, reparador y procesamiento: 721 aprobadas. Los 6 fallos de
`test_procesamiento_masivo` son preexistentes en 14f3c22. Las 3 filas se repararon con
DOCUMENTO_CORREGIR_CAMPO, con ensayo previo en copia; el ledger conserva el valor documental.
