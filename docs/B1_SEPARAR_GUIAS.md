# B1: separar guías de un viaje agrupado

Acciones `VIAJE_SEPARAR_GUIAS` y `VIAJE_REVERTIR_SEPARACION`, ambas de riesgo `OPERACIONAL_REVERSIBLE`. Usan el canal oficial: vista previa, confirmación humana, respaldo, auditoría, reconciliación de la bandeja, revalidación focal y regeneración del reporte.

## Transporte AZA y viaje físico Atlas

- **Transporte AZA**: la carga que AZA despachó. Sus guías nunca se reparten entre viajes.
- **Viaje físico Atlas**: uno o más transportes AZA completos. Por defecto es un solo transporte. Una persona puede unir varios con `VIAJE_AGRUPAR_GUIAS`, lo que queda registrado en `agrupaciones_viaje.json`.

Separar saca transportes **completos** de una agrupación activa. Cada transporte separado vuelve a ser su propio viaje; los restantes siguen juntos si son dos o más.

Si una guía «no pertenece» a su propio transporte, el error es documental: el número de transporte está mal leído. B1 lo explica y remite a esa corrección, que tiene su propia vista previa.

## Frases

| Frase | Resultado |
|---|---|
| «separa la guía N del viaje» | separa N |
| «saca las guías N y M del viaje de la guía K» | separa N y M; K identifica el viaje que queda |
| «la guía N no es del mismo viaje que la guía K» | separa N del viaje de K |
| «las guías K y N no son del mismo viaje» | solo con dos guías; separa N del viaje de K |
| «deshaz la separación de la guía N» | revierte la separación |

## Abstenciones

En estos casos B1 explica el motivo y no escribe nada:

- La guía no existe o figura en varios documentos.
- El transporte no es válido.
- Las guías pertenecen a viajes distintos.
- Se nombra solo una parte de un transporte.
- Un transporte del viaje tiene un documento sin folio o con folio repetido.
- El registro está contradictorio: un transporte figura en dos agrupaciones activas.
- Se nombran todas las guías de un viaje de tres o más transportes, y no se sabe cuáles siguen juntos.

Con dos transportes, nombrar todas las guías deshace la agrupación: el principal conserva el viaje.

## Datos que cuelgan del viaje

No se mueven ni se inventan.

**Eventos** (estadías, observaciones, adicionales), indexados por `numero_transporte`:

- Se conservan sin cambios si todas sus guías quedan en un único viaje resultante cuya clave sea ese mismo transporte.
- Bloquean la separación si:
  - no tienen guías vinculadas;
  - sus guías quedarían en viajes distintos (el caso típico de un evento registrado sobre el viaje agrupado completo);
  - quedarían colgados de un transporte que ya no es la clave de su viaje.

**Revisión «sin incidencia»:** se conserva en su transporte. La vista previa avisa qué viaje resultante quedará como no revisado.

**Peso total confirmado:** permanece en el ledger. Solo se aplica si el viaje resultante conserva ese total; si no, se vuelve a evaluar. La vista previa lo avisa.

**Confirmaciones por documento** (destino, chofer, correcciones): son del archivo y no cambian.

## Registro y reversión

- La agrupación original queda con estado `SEPARADA` y un bloque `separacion` que indica quién, cuándo, la fuente `ACCION_OPERACIONAL:<token>` y qué transportes salieron.
- Si quedan dos o más transportes, se crea una agrupación `ACTIVA` derivada (`derivada_de`).
- `VIAJE_REVERTIR_SEPARACION` reactiva la original, conserva la historia en `historial` y marca la derivada como `REVERTIDA`. Exige que el resultado de la separación siga intacto. Además repite las validaciones de agrupar: estructura, y que no haya eventos propios en transportes que volverían a quedar absorbidos.
- Nunca se borran registros.

## Vista previa

Muestra la empresa, el viaje original y cada viaje resultante con:

- transportes, guías y pesos;
- entregas con destino y kilómetros;
- peso total;
- estado con sus motivos.

Todo se calcula con el mismo `agrupar_viajes` del reporte, usando la bandeja vigente y los pesos confirmados. El dataset documental nunca cambia.
