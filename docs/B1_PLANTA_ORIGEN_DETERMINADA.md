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

- Alguna guía del viaje tiene un destino operacional confirmado por una persona. La ruta guardada en esa decisión se calculó desde la planta anterior, y la proyección del reporte la seguiría publicando.
- El transporte pertenece a una agrupación activa.
- Alguna guía del viaje está en investigación, no tiene folio o está repetida.
- Hay un evento activo del transporte cuyo vínculo es inconsistente: vínculo incompleto, o guías que no pertenecen al viaje. Caso real: un evento cita el folio truncado «83487».
- El registro de eventos, el de agrupaciones, el catálogo o el ledger están ilegibles.

Los eventos con vínculo consistente (estadía, observación, devolución, doble vuelta) no dependen de la planta. Se conservan sin cambios y la vista previa los informa.

## Vista previa

La vista previa no escribe datos y muestra:

- la empresa y la guía;
- la planta actual y la propuesta;
- las guías del viaje afectadas;
- la ruta anterior de cada guía, que se invalida;
- los eventos que se conservan;
- si se reemplaza un origen que una persona confirmó antes.

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
- en `documentos_viaje`, el estado previo de cada guía: planta, fuente, evidencia, distancia y estado de ruta.

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
