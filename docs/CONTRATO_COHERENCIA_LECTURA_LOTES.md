# Contrato propuesto: lectura de una generación operacional

Estado: **diseño pendiente; ninguna garantía nueva está implementada**. Base
`4e2a33713f202e60ea7fb934caccb68912f31730`; comparación de la interfaz de
fechas con `c08bc3804eed69200a6bd1eff1bba52fc9580e4d`. No autoriza cambios,
confirmaciones ni ejecución de lotes.

## Resultado de la revisión

No existe actualmente una generación completa, inmutable y públicamente
identificable que cubra todas las fuentes de esta lectura. Por tanto no se
puede implementar aquí un lector confiable sin cambiar al escritor oficial o
su protocolo. Un lector que simplemente hashée dos veces puede pasar mientras
un escritor está detenido entre dos archivos; un lector de una versión Cloud
puede observar una versión intermedia de la confirmación por lotes de 50.

Las evidencias concretas son:

* `acciones_operacionales._publicacion_protegida` selecciona sólo ciertas
  acciones; `_lectura_documental` en modo de sólo consulta verifica esas
  marcas, e `instantanea_documental` cubre filas, ledger y bandeja, no el
  conjunto completo de dependencias. El bloqueo de esta capa no es una
  garantía para escritores que no participan de él.
* `almacenamiento_portable.leer_estado_operacion` lee un manifiesto de reporte,
  no un commit global de todas las fuentes. Los campos de versión derivada y
  huella del dataset no certifican una generación del ledger, agrupaciones,
  catálogos o evidencia.
* `estado_confirmado.CustodiaEstado._confirmar_rutas` usa `LOTE_CONFIRMACION`
  y avanza la versión en cada lote. `_recuperar_pendiente` utiliza un diario
  local de rutas y versión base: no es una señal compartida de publicación
  completa para lectores, y su recuperación no prueba por sí sola que una
  operación lógica interrumpida haya terminado. `LeaseEscritorOperativo.cerrar`
  intenta confirmar custodia y libera el turno aun si la confirmación falla.
* El turno de `exclusion_local` y el lease coordinan escritores participantes;
  no entregan una instantánea a lectores, y su cobertura de guardia tiene
  límites expresamente documentados en ese módulo. Sin participación de todo
  escritor relevante no hay garantía global.
* Los lectores de agrupaciones, cuarentena y equipo pueden convertir errores
  de lectura en vacíos. `resolver_ruta_evidencia` depende además de rutas,
  contenido y metadatos de evidencias móviles, entradas, relecturas y depósito.

No se ha demostrado que los objetos y endpoints actuales tengan la retención,
lectura consistente, aislamiento por empresa y atomicidad necesarios para
ser usados como almacén de generaciones. No se propone tratar esas propiedades
como existentes sin pruebas. Tampoco se implementa un lector que devuelva una
instantánea parcial bajo el nombre de confiable.

## Cambio mínimo indispensable, para una etapa posterior

El cambio indispensable es que **el escritor oficial, y todos los caminos que
modifican las fuentes incluidas**, emitan una frontera durable y verificable de
publicación. Como diseño candidato, reutilizar custodia y objetos direccionados
por contenido existentes, sujeto a demostrar sus garantías; no desplegar una
segunda infraestructura. El mecanismo siguiente requiere cambios productivos
que están fuera del alcance de esta etapa:

1. Antes de la primera modificación relevante, el coordinador oficial publica
   para la empresa un control autoritativo `PENDIENTE` con identificador único
   de operación y generación previa, mediante una transición atómica
   condicionada por el lease y la versión previa. No comenzar escrituras si
   esta transición falla. Una señal local o replicada sin orden no basta.
2. El escritor conserva `PENDIENTE` durante cambios, reconciliación y
   recuperación. Una caída, lease perdido, error de lectura o publicación
   parcial no puede convertirla en `COMPLETA`. Una recuperación oficial debe
   terminar o revertir la operación y verificar todas las fuentes antes de
   emitir una nueva generación; no basta confirmar el diario de rutas.
3. Con turno y lease vigentes, el escritor captura el conjunto completo de
   fuentes en objetos inmutables, verifica identidad, estructura y huellas,
   y emite un descriptor inmutable con empresa, identificador único de
   generación, esquema, inventario completo y referencia verificable por cada
   fuente. La ausencia permitida debe estar declarada explícitamente, con su
   semántica; un error o una fuente requerida ausente impide completar.
4. Sólo cuando todos los objetos y el descriptor son durables y accesibles,
   el escritor sustituye atómicamente `PENDIENTE` por `COMPLETA`, apuntando
   al descriptor, bajo el mismo control de versión/lease. Esta transición única
   es el punto de publicación; las versiones intermedias de custodia no son
   generaciones completas. Debe garantizarse retención de objetos mientras
   haya lectores, o devolver `NO_CONFIABLE` si ya no están disponibles.
5. Una API oficial de sólo lectura obtiene el control desde el origen
   autoritativo, exige `COMPLETA`, verifica descriptor y cada objeto, y vuelve
   a consultar el control al terminar. Ante `PENDIENTE`, cambio de generación,
   identidad ajena, datos ausentes o ilegibles, fallo de verificación, esquema
   no admitido o control inaccesible devuelve `NO_CONFIABLE`, sin datos
   utilizables por el preview. Las dos lecturas del control sólo funcionan como
   detección de cambio porque el protocolo garantiza identidad monotónica o
   única, transición durable previa a toda escritura y objetos inmutables;
   no sustituyen esas garantías. No se bloquea al escritor durante la lectura.

La vista cubre **sólo** las fuentes enumeradas y verificadas por el descriptor.
La generación completa puede ser anterior al momento de lectura; si se exige
estado vigente, la API debe definir y verificar la frescura contra el control
autoritativo. Una réplica Drive que pueda entregar archivos y marcas fuera de
orden no puede usarse como control autoritativo sin una garantía adicional.

### Inventario y puntos de integración

El inventario exacto debe cerrarse a partir de las lecturas del preview y las
precondiciones oficiales, no de una lista adivinada. Como mínimo deben
evaluarse: identidad de empresa y marca de custodia; dataset documental;
ledger; bandeja; agrupaciones; registro de investigación y sus dependencias de
evidencia; catálogos de choferes y vehículos; y cualquier otra fuente que
consuman la proyección de destino y las precondiciones de fecha. Si falta una
dependencia, la operación que la necesita queda `NO_CONFIABLE`.

Los puntos existentes que requieren diseño e integración posterior son:

* `atlas_core/escritor_operativo.py`: adquisición, vida y cierre del turno;
  introducir o invocar las fronteras del protocolo oficial en un lugar que
  abarque todos los caminos de escritura pertinentes, incluyendo fallos y
  recuperación. Verificar también `EscritorEquipoUnico` y los escritores que
  no usan este lease; si no participan, deben quedar fuera de la garantía.
* `atlas_core/estado_confirmado.py`: preparar y verificar objetos y descriptor,
  así como conservar la frontera pendiente a través de lotes, caídas y
  recuperación. `ClienteEstado` puede ser candidato para el almacenamiento
  existente; confirmar primero si sus operaciones y el servicio soportan la
  transición atómica y retención requeridas. Si no, se necesitará un cambio
  adicional del servicio oficial; no hay base para prometer que basta un
  cambio local del Motor.
* Los lectores oficiales de las fuentes deberán exponer lectura estricta o un
  modo equivalente que distinga vacío válido, ausencia explícita y error.
  Deben aceptar los bytes de la generación, sin volver a leer archivos vivos;
  en particular la resolución de evidencia y equipo no debe consultar el
  filesystem fuera del inventario. Las interfaces concretas se definirán tras
  auditar las dependencias transitivas y los autores de cada fuente.
* Un lector nuevo consumirá el descriptor oficial y entregará un resultado
  tipado `CONFIABLE(generacion, empresa, fuentes)` o
  `NO_CONFIABLE(codigo, detalle)`; no modifica `lote_correcciones.py` en esta
  etapa. La posterior integración del preview es un trabajo separado.

Este es un contrato de seguridad y una propuesta verificable, no una lista de
archivos suficiente para afirmar que la implementación es trivial. Es
obligatorio auditar todos los escritores, la semántica del servicio Cloud y la
disponibilidad de objetos antes de definir el diff mínimo definitivo.

## Pruebas de aceptación previstas

Todas con datos sintéticos, control de almacenamiento y tiempo determinista:

| Escenario | Resultado exigido |
| --- | --- |
| Generación completa con todas las fuentes | Ambos lectores reciben los mismos bytes y la misma identidad de generación. |
| Descriptor, objeto o fuente requerida faltante, corrupta o ilegible | `NO_CONFIABLE`; nunca colección vacía de reemplazo. |
| Publicación pendiente, caída antes o durante los lotes, o lease perdido | `NO_CONFIABLE`; no se observa una mezcla como completa. |
| Generación cambia mientras se leen objetos | `NO_CONFIABLE`, incluso si el contenido de una fuente vuelve a su valor previo. |
| Escritor pausado entre dos archivos | `PENDIENTE` durable impide aceptar la captura. |
| Recuperación pendiente | Sigue rechazando hasta recuperación verificada y publicación completa; después acepta la nueva generación. |
| Dos lectores simultáneos y escritor activo | Sin locks de lector sobre el escritor; cada lector obtiene una generación completa o `NO_CONFIABLE`. |
| Empresa ajena, objeto no inventariado o fuente requerida no cubierta | `NO_CONFIABLE`; sin cruce de empresa ni garantía global parcial. |
| Falla antes y después de cada transición o lote | Nunca aparece `COMPLETA` con descriptor incompleto; verificar durabilidad y CAS en el servicio oficial. |
| Lectura y preview | Ninguna escritura en archivos operacionales; pruebas que intercepten los canales de escritura. |

Estas pruebas están especificadas, no ejecutadas: no existe aún la
implementación ni el protocolo sobre los que puedan probarse.
