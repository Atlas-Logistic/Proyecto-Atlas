# Handoff — Validación Operacional Masiva, Fase 1

La fase midió el snapshot operacional más amplio disponible: 1.177 guías
reales, 1.177 procesamientos OK y 574 viajes. No se modificó código, OCR, UX,
Multicampo ni Política.

| Campo | Total | Aceptado sin revisión | En documento REVISAR | No encontrado | Cobertura | Precisión masiva |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Cliente | 1.177 | 144 | 575 | 458 | 61,09 % | No medible |
| Destino | 1.177 | 136 | 641 | 400 | 66,02 % | No medible |
| Chofer | 1.177 | 144 | 567 | 466 | 60,41 % | No medible |
| Transporte | 1.177 | 144 | 586 | 447 | 62,02 % | No medible |
| Patente tracto | 1.177 | 19 | 83 | 1.075 | 8,67 % | No medible |
| Patente rampla | 1.177 | 5 | 27 | 1.145 | 2,72 % | No medible |
| Peso | 1.177 | 0 | 0 | 1.177 | 0,00 % | No medible |
| Cantidad | 1.177 | 0 | 0 | 1.177 | 0,00 % | No medible |
| Material | 1.177 | 144 | 120 | 913 | 22,43 % | No medible |
| Origen | 1.177 | 0 | 0 | 1.177 | 0,00 % | No medible |
| Kilómetros | 574 viajes | 0 | 0 | 574 | 0,00 % | No medible |
| Consolidación | 1.177 | 529 | 201 | 447 | 62,02 % | 730/730 estructural |

`Aceptado sin revisión` describe el estado publicado, no un acierto contra
verdad humana. El corpus masivo carece de ground truth por campo; la única
precisión oficial comparable permanece en 48/49 valores E2E (97,96 %).

Los fallos dominantes son la ausencia de Origen/Peso/Cantidad en el esquema del
snapshot, rampla, tracto, material/tipo de carga, kilómetros bloqueados por
Origen, Chofer, Cliente, Transporte y Destino. El siguiente bloque debe ser
Reprocesamiento Operacional Controlado y Ground Truth Estratificado.
