# Ensayo: recuperación automática de chofer y RUT por asignación vigente corroborada

02/11/2026, Claude Code. Encargo de Javier. **Solo lectura**: copias aisladas del dataset, del ledger y de los
catálogos (copiados a las 18:23; sha256 en `huellas_insumos.txt`). Trazas OCR leídas de G: sin modificarlas. Motor 515dda7.
Sin cambios de código, datos, catálogos, ledgers ni estados.

## Regla evaluada (todas las condiciones a la vez)
1. Guía candidata: chofer o RUT ausente o inválido, o motivo CHOFER_AUSENTE / CHOFER_SIN_CORROBORAR / RUT_CHOFER_INVALIDO.
2. Sin decisión humana previa sobre el chofer (corrección de chofer o RUT, identidad o chofer operacional en el ledger).
3. Patente documental (tracto y/o carro) que identifique un único vehículo CONFIRMADO/ACTIVO del catálogo.
4. Asignación de CONFIRMACION_HUMANA con fecha local ≤ fecha de emisión (nunca posterior). Se toma la última; si tracto
   y carro apuntan a choferes distintos, revisión. Si la asignación es del mismo día de la emisión, revisión.
5. Chofer activo, con RUT canónico y sin `asignacion_variable`.
6. Corroboración dentro del documento: nombre o alias exacto (RETIRA o campo chofer leído), RUT válido exacto, o RUT
   OCR inválido a ≤ 1 dígito del confirmado sin otro chofer activo a esa distancia. Un nombre o RUT válido de otro
   chofer es contradicción.
No se usa historial, rutas, clientes, proximidad de fechas ni la patente sola.

## Resultado sobre el dataset actual (696 filas, 11 candidatas)
| Categoría | N | Guías |
|---|---|---|
| Recuperable automáticamente | **0** | — |
| Requiere revisión humana | **2** | 482741, 483226 |
| Protegida por decisión humana | **2** | 482553, 483267 |
| Sin evidencia suficiente | **7** | 482188, 82187, 482396, 482580, 482726, 482761, 482850 |

Detalle:
- **482741** (21-10, TG8925/JF9575): asignación vigente desde 17-09 a SALOMÓN PIZARRO (18.091.588-5); sin traza OCR
  (envío Mobile), no hay corroboración documental. El envío Mobile lo hizo `chofer_id` 180915885 = SALOMÓN PIZARRO.
- **483226** (26-10, ND6443/JB6878): asignación desde 23-10 a JOSE LAZCANO; sin traza OCR (Mobile). El envío lo hizo
  `chofer_id` 10833150K = JOSE LAZCANO.
- **482553, 483267**: chofer operacional fijado por una persona (DOCUMENTO_CORREGIR_CHOFER_OPERACIONAL); se preservan.
- **482396, 482761, 482850** (16-22/10, ND6443): la única asignación (23-10) es posterior a la emisión -> excluidas.
- **482188** (XF3629): el vehículo no tiene asignación humana.
- **82187, 482580, 482726**: fecha de emisión ilegible (y sin patente) -> no se puede evaluar vigencia.

## Caso de referencia 483859 (dataset y ledger previos a su corrección, respaldo 18:13)
RECUPERABLE_AUTOMATICO: AL1879 -> RENÉ GARCÍA (asignación 23-10, emisión 02-11), corroboración
`RUT_OCR_1_DIGITO:9706225-1`, sin contradicciones. En el dataset actual ya no es candidata (corregida por Javier).

## Falsos positivos y regresiones
- Control: guías con chofer y RUT válidos y catalogados donde la regla también encontraría un chofer por asignación.
  **204 de 204 coinciden** con el chofer real (203 en el estado previo a 483859); **0 discrepancias**.
- Ninguna patente tiene más de una asignación ni fue reasignada; ningún chofer tiene dos tractos.
- Riesgos:
  - Las asignaciones no tienen fecha de término: si un vehículo cambia de chofer sin registrarse, la regla seguiría
    usando la asignación anterior. La corroboración documental obligatoria es la defensa.
  - Parte de las asignaciones pudo confirmarse mirando las mismas guías: el control no es totalmente independiente.
  - Las guías Mobile no conservan traza OCR: sin ella no hay corroboración posible (caso 482741/483226).
  - Fuera de alcance, pero observado: `extractor.py` contiene RUT de chofer fijos en el código (líneas 3811-3862).

## Evidencia de RUT inválido (punto 5)
Hoy la ingesta guarda el RUT inválido solo en memoria (`RUT del chofer (documento, invalido)`) y
`_extraer_rut_chofer_geometrico` lo descarta. Propuesta: conservarlo en `metricas_procesamiento_json` como
`evidencia_rut_chofer_documental` = {valor_leido, estado DV_INVALIDO, fuente LINEAL|GEOMETRICA, traza}; nunca en la columna
`rut_chofer`, nunca como dato válido; solo como corroboración de la regla y para la revisión humana.

## Propuesta mínima
1. **Ingesta (implementación general)**: función pura `chofer_por_asignacion_corroborada(fila, lineas_ocr, catalogos, ledger)`
   con las reglas 2-6, invocada solo cuando el chofer quedó ausente. Escribe chofer y RUT canónico con método
   `ASIGNACION_VIGENTE_CORROBORADA` y la evidencia en la fila; retira CHOFER_AUSENTE; nunca escribe en el ledger como
   confirmación humana. Sin corroboración: tarjeta de Revisión con el chofer sugerido.
2. **Evidencia**: extractor geométrico y lineal entregan el RUT documental inválido como evidencia (punto 5).
3. **Recuperación histórica**: hoy no hay ninguna guía recuperable automáticamente (0). No conviene implementar una
   revalidación histórica ahora; las 2 en revisión se resuelven con DOCUMENTO_CORREGIR_IDENTIDAD_CHOFER, mirando el original.
4. **Decisión pendiente de Javier**: si la identidad de quien envía por Mobile (`chofer_id`) puede contar como
   corroboración. Hoy no se usa: el envío lo puede hacer otra persona con la cuenta del chofer.

## Archivos
`resultado_actual.json`, `resultado_pre_483859.json` (detalle por guía y control), `simular_chofer.py`,
`huellas_insumos.txt`.
