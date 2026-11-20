# Limitaciones de la instantánea de correcciones en lote

Diagnóstico sobre la base `3163c015f36ebfae8f055b13142d75881e6a4973`,
comparada con las interfaces del Motor CASA `c08bc3804eed69200a6bd1eff1bba52fc9580e4d`.
Esta etapa queda incompleta: no hay adaptador ni una instantánea apta para
alimentar el preview operacional.

## Coherencia

* `acciones_operacionales._Contexto.instantanea_documental` lee dataset,
  ledger y bandeja bajo el bloqueo documental. En modo sin bloqueo comprueba
  la marca de publicación antes y después; esa marca sólo cubre las acciones
  seleccionadas por `_publicacion_protegida`, no todas las fuentes ni todos
  sus escritores. No incluye agrupaciones, catálogos ni investigación.
* `estado_operacion.json` describe el reporte y puede contener una huella del
  dataset; no es una generación común de todas esas fuentes.
* La custodia Cloud conserva versiones y huellas para alinear la copia, pero
  `CustodiaEstado._confirmar_rutas` confirma cambios por lotes de 50. Una
  versión observada entre lotes no demuestra, por sí sola, que todas las
  fuentes correspondan al mismo estado lógico. Tampoco se debe modificar la
  custodia para implementar este adaptador.
* Una comparación de huellas antes y después detectaría cambios durante la
  captura, pero no detectaría a un escritor detenido entre dos modificaciones,
  ni un cambio que se revierta entre ambas verificaciones. No demuestra por
  sí sola una transacción completa. La ausencia de una marca de publicación
  tampoco cubre esos casos.

Falta una API o evidencia oficial de lectura sin bloquear escritores que
identifique una generación completa y coherente para todas las fuentes
necesarias, o que demuestre que no hay una operación de múltiples archivos
en curso o interrumpida. Hasta disponer de ella, una captura operacional no
puede declararse confiable ni producir un preview aplicable. El fallback de
estabilidad sigue siendo útil para rechazar cambios observados, pero no cubre
por sí solo esta limitación.

## Dependencias y errores de lectura

* `InstantaneaLote` sólo transporta empresa, filas, aplicaciones, decisiones
  y archivos en investigación. El preview no recibe agrupaciones confirmadas
  ni el estado del equipo operacional. En CASA, la precondición individual
  de fecha considera agrupaciones y sustituciones de patentes basadas en
  asignaciones y catálogos. Agregar datos al adaptador sin integrarlos a la
  evaluación dejaría el resultado incompleto.
* `agrupaciones_activas` transforma errores de lectura en una lista vacía;
  `investigacion_documental.leer_registro` también devuelve un registro vacío
  ante archivos ilegibles. El resolutor de equipo puede tratar catálogos
  ilegibles como vacíos. Un adaptador no puede distinguir ausencia legítima de
  error usando solamente esos resultados, y no debe inferir que no existen
  protecciones o dependencias.
* La investigación vigente puede depender de la huella de la evidencia
  documental; verificar sólo el JSON del registro no cubre esa dependencia.

Se necesitan interfaces de lectura que distingan de forma verificable estado
vacío, ausente e ilegible, y un contrato de snapshot/preview que incorpore y
evalúe las dependencias pertinentes. No se ha cambiado la implementación de
fechas de CASA, `acciones_operacionales.py`, ni los protocolos de custodia.

## Verificación de la base

En el worktree basado exactamente en `3163c015`, se ejecutó
`python -m pytest tests/test_lote_correcciones.py -q -p no:cacheprovider`:
16 pruebas aprobadas. Son pruebas sintéticas del preview existente; no prueban
la captura operacional ni establecen la coherencia de archivos reales.
