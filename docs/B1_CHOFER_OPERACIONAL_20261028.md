# B1: corrección segura del chofer operacional (28/10/2026)

B1 fija el chofer **operacional** de una guía desde una tarjeta de Revisión de Atlas o con una
instrucción en lenguaje natural. Nunca modifica lo documental.

## Uso

- Lenguaje natural: «El chofer de la guía 483267 es RENE GARCIA», «En la guía N el chofer
  correcto es X», «Corrige el chofer de la guía N a X». X es un nombre o RUT que se resuelve
  sólo contra el catálogo activo; un chofer ambiguo, inexistente o inactivo pide aclaración.
- Tarjeta de chofer (`CHOFER_DESCONOCIDO`/`CHOFER_CANDIDATO`, campo `chofer` o `rut_chofer`):
  «el chofer es X», «X» o el RUT solo.
- Preview: guía y transporte, chofer actual, chofer propuesto, RUT asociado del catálogo, RUT
  impreso (se conserva) y guías hermanas (no se modifican). Se aplica con «sí».
- Si el RUT impreso es válido y pertenece a otra identidad, el preview lo muestra como
  DISCREPANCIA y un «sí» no aplica nada: hace falta escribir «confirmo la discrepancia de RUT»
  (en Desktop, casilla + «Aplicar con discrepancia»). B1 vuelve a previsualizar con
  `confirmar_discrepancia_rut=true` y sólo ejecuta si el estado base es el mismo que vio el
  humano.

## Acción `DOCUMENTO_CORREGIR_CHOFER_OPERACIONAL` (OPERACIONAL_REVERSIBLE)

- Escribe una entrada append-only `CHOFER_OPERACIONAL_DOCUMENTO` en `decisiones_aplicadas.json`
  (documento, chofer operacional, chofer/RUT documentales, discrepancia, actor, confirmado_por,
  referencia). La última entrada por `archivo` gana.
- En el dataset sólo retira de ESA fila los motivos de identidad (`CHOFER_SIN_CORROBORAR`,
  `CHOFER_AUSENTE`, `RUT_CHOFER_INVALIDO`) y recalcula sus estados. `chofer`, `rut_chofer`,
  OCR y fotografía quedan intactos.
- Verifica en disco la entrada del ledger y la fila antes de informar
  (`persistencia_verificada`); si no, falla y la capa restaura el respaldo.
- Reconciliación focal de esa guía y reporte regenerado. Sin revalidar otras guías, sin tocar
  catálogos ni asignaciones de vehículos.

## Persistencia frente a OCR, PULL y revalidaciones

`atlas_core/chofer_operacional.py` es la única lectura del ledger:
- `reporte_viajes` → `agrupar_viajes(choferes_operacionales=...)` usa el chofer y RUT
  operacionales del documento; `evidencias_documentos` conserva lo impreso. Las guías hermanas
  conservan el suyo (un conflicto queda visible).
- `revalidar_chofer_sin_corroborar_por_catalogo_sin_ocr` vuelve a retirar los motivos de
  identidad de ese documento si una relectura los trae de nuevo, sin tocar `chofer`/`rut_chofer`.
- `regenerar_decisiones_persistidas` retira las tarjetas de chofer de ese documento (por
  `archivo`; tarjetas antiguas `original.jpg` por guía y transporte exactos).
