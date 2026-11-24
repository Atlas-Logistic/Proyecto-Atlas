# Corrección de planta de origen desde B1

Con esta acción, B1 corrige la planta de origen de una guía cuyo origen ya está determinado y que no tiene una tarjeta de revisión pendiente. Usa el canal oficial de acciones: la acción se llama `DOCUMENTO_CORREGIR_PLANTA_ORIGEN`, tiene riesgo `OPERACIONAL_REVERSIBLE` y requiere el escritor global.

Ejemplo de frase: «La planta de origen de la guía 464900 es Renca».

## Cuándo se usa y cuándo no

Si la guía tiene una revisión `ORIGEN_NO_CONFIRMADO` pendiente, B1 la resuelve con esa tarjeta (`DECISION_APLICAR` + `SELECCIONAR_OTRA_PLANTA`), como hasta ahora.

La acción directa también se niega si alguna guía del viaje tiene una revisión de origen pendiente. Así, la tarjeta no queda saltada.

## Identidad

- La guía debe tener folio y corresponder a un solo documento. Si un folio aparece en varios documentos, la acción se rechaza; no se elige uno.
- La empresa de la raíz debe coincidir con la del proceso.
- La planta debe estar `CONFIRMADA` y `ACTIVA` en el catálogo. B1 la resuelve por nombre o por comuna única y nunca crea plantas.
- El transporte debe ser un número válido. Un placeholder como «No encontrado» o un valor vacío se rechaza, para no agrupar documentos sueltos.

## El origen es del viaje

La planta de origen pertenece al viaje físico (el transporte), no a una guía suelta. Por eso cambia junta en **todas** las guías del transporte. Así el viaje, sus entregas y sus rutas nunca quedan con dos orígenes.

Las guías de otros viajes no se tocan.

## Bloqueos (no se escribe nada)

- El transporte pertenece a una agrupación activa.
- Alguna guía del viaje está en investigación, no tiene folio o está repetida.
- Hay un evento activo del transporte cuyo vínculo es inconsistente: vínculo incompleto, o guías que no pertenecen al viaje. Caso real: un evento cita el folio truncado «83487».
- El registro de eventos, el de agrupaciones, el catálogo o el ledger están ilegibles.

Los eventos con vínculo consistente (estadía, observación, devolución, doble vuelta) no dependen de la planta. Se conservan sin cambios y la vista previa los informa.

## Destino confirmado por una persona

Origen y destino son independientes: un destino confirmado ya no bloquea la corrección.

- Se conservan íntegros la decisión (dirección y comuna), el cliente y la obra. No se crea una tarjeta nueva ni se vuelve a pedir la confirmación del destino.
- Solo se invalida la ruta guardada, que salió de la planta anterior.
- La ruta nueva se calcula desde la nueva planta hasta el **mismo** destino:
  - si la ruta anterior tenía coordenadas, se conservan (junto con la región y los códigos territoriales) y solo se pide al proveedor el recorrido hasta ellas; el destino no se vuelve a geocodificar;
  - si no las tenía, se usa el mismo cálculo de la confirmación (`calcular_ruta_operacional`), con la comuna confirmada como control.
- Si el proveedor no responde, la ruta queda pendiente (`ORIGEN_MODIFICADO_RUTA_PENDIENTE`): se publican el destino y sus coordenadas, pero nunca los kilómetros anteriores.
- En las decisiones con «conservar estado», la ruta sigue requiriendo comprobación; la distancia documental (calculada desde la planta anterior y protegida en el dataset) deja de publicarse.

La ruta se guarda en `metricas_procesamiento_json.ruta_operacional_recalculada`, ligada a la decisión, la dirección, la comuna y la **planta de origen** (`planta_origen_id`). Se escribe en el mismo bloqueo que la planta nueva. La auditoría `recalculo_ruta_origen` registra la ruta anterior y la nueva.

`proyectar_destino` publica una ruta solo si salió de la planta que el documento tiene hoy. Las rutas antiguas sin planta registrada valen mientras ninguna `CORRECCION_ORIGEN_OPERACIONAL` posterior a la decisión haya incluido el documento.

Volver a la planta anterior es otra corrección igual: recalcula la ruta hacia las mismas coordenadas.

## Vista previa

La vista previa no escribe datos y muestra:

- la empresa y la guía;
- la planta actual y la propuesta;
- las guías del viaje afectadas;
- la ruta anterior de cada guía, que se invalida;
- los eventos que se conservan;
- si se reemplaza un origen que una persona confirmó antes;
- cada destino confirmado que se conserva, con su ruta anterior y el recálculo previsto.

Requiere la confirmación de una persona: `_confirmante_humano` rechaza identidades técnicas.

## Al confirmar

1. Bajo el escritor global, se releen todas las precondiciones. Si alguna guía del viaje cambió desde la vista previa, la acción se rechaza sin escribir.
2. Se respaldan el dataset, la bandeja y el ledger.
3. En cada guía del viaje:
   - se fija la nueva planta, con `origen_determinado_por = CONFIRMACION_HUMANA`;
   - la ruta calculada desde la planta anterior se invalida, de modo que no se publica una distancia obsoleta;
   - las revalidaciones automáticas no sobrescriben un origen confirmado por una persona.
4. Se intenta recalcular la ruta con el mecanismo existente (`revalidar_ruta_sin_destino_calculado_sin_ocr`). Si no se resuelve, queda pendiente.
5. Se recalculan los indicadores y se reconcilia la bandeja.
6. Se regenera el reporte. No se vuelve a leer el original ni el OCR.

## Trazabilidad

El ledger registra una entrada de tipo `CORRECCION_ORIGEN_OPERACIONAL` con:

- la guía nombrada, el transporte y la empresa;
- el origen anterior y el confirmado;
- el actor y el confirmante;
- en `documentos_viaje`, el estado previo de cada guía: planta, fuente, evidencia, distancia y estado de ruta;
- en `destinos_confirmados`, cada decisión de destino del viaje con su ruta anterior y la recalculada.

La evidencia GPS y documental previa de las filas no se borra. La auditoría registra `APLICADA` o el fallo.

## Fallos

| Situación | Resultado |
|---|---|
| Falla el servicio con el escritor vigente | Se restaura el respaldo. |
| Se pierde el escritor, falla la bandeja o no se regenera el reporte | La acción devuelve `PUBLICACION_INCOMPLETA` y la marca de publicación bloquea la lectura. |

En el segundo caso, el estado se inspecciona con `inspeccionar_publicacion_interrumpida`. No existe recuperación automática para esta acción: un estado parcialmente escrito requiere revisión operacional.

## Simulación sobre una copia de los datos reales (24/11/2026)

Solo se hicieron vistas previas, sin confirmar. De los 720 transportes, 666 admiten la corrección: 588 de una guía y 78 de varias.

Los bloqueados son:

| Motivo | Transportes |
|---|---|
| Destino confirmado por una persona | 37 |
| Agrupación activa | 8 |
| Folio repetido | 5 |
| Folio inválido | 2 |
| Evento con folio truncado | 1 |
| Transporte «No encontrado» | 1 |
