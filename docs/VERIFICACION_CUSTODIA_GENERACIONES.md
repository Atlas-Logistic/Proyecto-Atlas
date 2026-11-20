# Verificación de custodia para generaciones operacionales

## Decisión: OPCIÓN B — REQUIERE AMPLIACIÓN

La custodia aporta objetos direccionados por contenido, historial de huellas,
aislamiento por empresa y confirmación condicionada por versión y lease. No
ofrece hoy un punto que publique y recupere una **generación operacional
completa**. Se pueden aprovechar esas piezas, pero hace falta ampliar el
protocolo del escritor y de custodia; no se ha demostrado que baste cambiar
sólo el Motor ni que el servicio desplegado tenga el código inspeccionado.

Referencia de Motor: `51167a7c6c864b4193906d48790872d0f97c3b61`, basada en
`3163c015`; la comparación de interfaces de fecha instalada corresponde a
`c08bc3804eed69200a6bd1eff1bba52fc9580e4d`. El commit de protecciones
`f1aa2bda74388096afc836a7570a57cf8d802211` existe localmente pero no fue
integrado. El código Cloud inspeccionado es la copia local del commit
`b28d5946c4f06db13b102bd874e0a879375e9ba8` de `Atlas-Mobile-Cloud`; no se
consultó ni modificó el despliegue. Las conclusiones sobre el servicio se
refieren a ese código, no a una versión desplegada verificada.

## A. Contenido de una generación

`atlas_core/estado_confirmado.py`: `rastreable`, `rutas_semilla`, `registrar`
y `_auditar` registran y confirman archivos, no un inventario certificado de
dependencias. La semilla enumera `operacion/actual`,
`operacion/procesamiento`, `catalogos_privados`, `fichas_digitales` y los
`envio.json` de Mobile. No incluye de forma general los originales de
`operacion/entradas`, todas las fotos Mobile ni los demás lugares que usa
`evidencia_documental.resolver_ruta_evidencia`. Un archivo fuera de la semilla
puede ser rastreado si un evento de escritura posterior queda bajo custodia
activa, pero eso no prueba que el inventario inicial sea completo. El hook
de auditoría tiene alcance limitado a eventos y procesos observados.

El dataset, ledger, bandeja, agrupaciones, registro de investigación,
identidad y catálogos pueden estar representados por archivos rastreables;
su mera presencia en el historial no certifica que procedan de una operación
completa, ni que las fuentes requeridas estuvieran presentes y fueran legibles.
La vigencia de investigación puede depender también del contenido y la
resolución de evidencia. No se garantiza el conjunto solicitado.

## B. Publicación atómica

En el Worker inspeccionado, `confirmarEstado` comprueba lease, versión base y
existencia de objetos y usa `DB.batch` para confirmar **una solicitud**; el
límite de la API es 200 entradas. En el Motor,
`CustodiaEstado._confirmar_rutas` divide cambios en lotes de **50** y llama a
`ClienteEstado.confirmar` por cada lote. Cada llamada avanza la versión. Por
tanto el límite afecta a la publicación, no sólo a la verificación: una
interrupción entre lotes deja una versión visible con sólo parte de los
cambios. Las acciones documentales protegidas tienen marcas propias en
`acciones_operacionales.py`, pero no abarcan todos los escritores y fuentes.

El manifiesto del Worker (`manifiestoEstado`) lee la marca y después consulta
los archivos mediante dos consultas separadas. Su código no fija en la segunda
consulta la versión leída ni establece una transacción de lectura compartida;
una confirmación concurrente entre consultas puede hacer que la respuesta
contenga entradas posteriores a la marca. No equivale a un descriptor inmutable
de una generación. El historial de rutas de `0006_estado_confirmado.sql` es
por archivo y no contiene un estado durable global `PENDIENTE/COMPLETA`.

## C. Lectura sin bloquear

El Worker inspeccionado direcciona objetos R2 por empresa y SHA-256; `PUT`
exige lease, comprueba el contenido y evita volver a subir si ya existe, y
`GET` los descarga sin adquirir el turno escritor. La prueba sintética de
aislamiento existente verifica separación de empresas. Estas son piezas
útiles, no una garantía de generación: no se certifica qué conjunto leer,
su completitud, ni la retención y disponibilidad de todos los objetos durante
una lectura. El tamaño máximo implementado por objeto es 95 MiB. Una fuente
ilegible o ausente debe rechazarse explícitamente; algunos lectores de dominio
actuales convierten errores en vacíos.

## D. Interrupción y recuperación

`_recuperar_pendiente` sólo confirma rutas del diario local si escritor,
raíz y versión base coinciden con la versión actual; si no coinciden, elimina
el diario y deja que la alineación actúe según la marca. No contiene un commit
global ni una operación para restaurar o terminar una generación completa.
`LeaseEscritorOperativo._cerrar_custodia` registra el fallo y libera el lease;
no crea una señal compartida de generación pendiente para lectores.

La prueba sintética `tests/test_custodia_limite_generacion.py` usa 51 archivos
temporales y un cliente en memoria. Interrumpe el segundo lote: comprueba que
la versión avanzó con 50 archivos y que, al quedar superada la versión base
del diario, el método de recuperación examinado lo elimina sin confirmar el
archivo restante. Esto demuestra ese camino concreto, no que todos los casos
de recuperación fallen. La idempotencia de la recuperación de generaciones
completas no está implementada ni demostrada.

## E. Lotes de 50

El lote limita cada actualización efectiva del manifiesto de custodia y
genera una versión por llamada. El Worker inspeccionado admite como máximo
200 rutas por solicitud. Aun cuando una sola solicitud pueda confirmar sus
entradas en un batch, eso no garantiza que la operación lógica completa haya
sido capturada, ni resuelve fuentes ausentes, interrupciones anteriores,
completitud de inventario o lectores concurrentes. Agrandar el lote no basta.

## Cambio mínimo recomendado en una etapa posterior

1. En `atlas_core/escritor_operativo.py` y los demás caminos oficiales de
   escritura que afecten las fuentes, introducir una frontera durable común
   por empresa antes de la primera mutación y conservarla hasta terminar o
   recuperar la operación. Exigir participación de todos los escritores
   incluidos y rechazar versiones antiguas; auditar la cobertura real.
2. Ampliar `atlas_core/estado_confirmado.py` para preparar objetos y un
   descriptor inmutable que inventaríe todas las fuentes requeridas y sus
   ausencias legítimas; validar legibilidad, empresa, integridad y dependencias.
   La evidencia no incluida en la semilla requiere tratamiento explícito.
3. En la interfaz oficial de custodia (`ClienteEstado` y, si es necesario,
   el Worker `confirmarEstado`/`manifiestoEstado` y su esquema D1), definir
   un control autoritativo por empresa con estado pendiente y una transición
   única a descriptor completo, bajo lease y comparación de versión. La
   recuperación deberá ser idempotente y nunca promover una mezcla; la
   disponibilidad y retención de los objetos debe estar garantizada o el
   lector devolver `NO_CONFIABLE`. Determinar mediante pruebas del servicio si
   sus primitivas actuales bastan o si requiere una ampliación del Worker.
4. Introducir lectores oficiales estrictos de los objetos del descriptor y
   de sus dependencias, con errores explícitos y sin relecturas de fuentes
   vivas. El contrato y los casos de concurrencia están detallados en
   `docs/CONTRATO_COHERENCIA_LECTURA_LOTES.md`.

No se construyó la prueba de concepto de publicación de generaciones: la
condición para hacerlo sin modificar al escritor ni crear otro publicador no
se cumple. El protocolo recomendado exige cambios futuros sujetos a revisión,
y no constituye una garantía productiva actualmente disponible.

## Pruebas ejecutadas

* Motor, con Python del entorno existente y directorios temporales sintéticos:
  `pytest tests/test_custodia_limite_generacion.py tests/test_estado_confirmado.py
  -q -p no:cacheprovider` — **14 aprobadas**.
* Código Cloud local `b28d594`, con SQLite y R2 en memoria, sin conexión ni
  cambios de servicio: `node --test test/estado_confirmado.test.js
  test/multiempresa.test.js` — **18 aprobadas**. Son pruebas locales del código
  inspeccionado, no una verificación del despliegue ni del protocolo propuesto.

No se accedió a los datos operacionales reales, no se cambió CASA u OFICINA,
y no se modificaron PULL, Cloud, el escritor ni la custodia productivos.
