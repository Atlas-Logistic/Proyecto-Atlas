# Descriptor preparado de generación operacional (contrato v2; lee v1)

Módulo: `atlas_core/descriptor_generacion.py`. Pruebas: `tests/test_descriptor_generacion_v2.py`
(v2) y `tests/test_descriptor_generacion.py` (reglas v1, que siguen vigentes para leer).
Base: Motor CASA `c08bc3804eed69200a6bd1eff1bba52fc9580e4d`. Responde al paso 2 del
"cambio mínimo recomendado" de `docs/VERIFICACION_CUSTODIA_GENERACIONES.md` (625ab15) y al
punto 3 del contrato de `docs/CONTRATO_COHERENCIA_LECTURA_LOTES.md` (51167a7), **sólo en la
parte pura**: construir y verificar el descriptor. No integra el preview `f1aa2bd`.

## Qué es y qué no es

| Concepto | Dónde vive | En este módulo |
| --- | --- | --- |
| **Descriptor preparado** | Este contrato | Sí: inventario completo, verificado y con huella propia. |
| **Generación publicada** | Protocolo oficial de publicación (pendiente) | No. La transición `PENDIENTE -> COMPLETA` que apunta a un descriptor no existe aquí. |
| **Estado de custodia** | `estado_confirmado.py` / Worker | No. Versión, lease, marca, objetos durables y retención no entran al descriptor. |

El descriptor declara siempre `"clase": "DESCRIPTOR_PREPARADO"` y
`"completitud": "PENDIENTE_PROTOCOLO_OFICIAL"`. No puede afirmar que está completo:
`leer_descriptor` rechaza (`DESCRIPTOR_AUTODECLARADO`) cualquier otra clase o completitud y
cualquier campo de publicación/custodia (`estado`, `completa`, `custodia`, `lease`,
`version_custodia`, ...), aunque la huella se haya recalculado. Los mismos nombres están
prohibidos en los metadatos de las fuentes.

El módulo no lee archivos, no consulta Cloud, no escribe, no publica y no confirma. Sólo
importa `hashlib`, `json`, `re`, `dataclasses`, `typing` y `collections`; una prueba lo
verifica por AST y otra con un audit hook que registra cualquier `open`, borrado, renombre,
socket o subproceso durante construir, serializar, leer y rechazar.

## API

```python
construir_descriptor(Inventario) -> DescriptorPreparado   # o ErrorDescriptor
serializar_descriptor(DescriptorPreparado) -> bytes        # JSON canónico UTF-8
leer_descriptor(bytes) -> DescriptorPreparado              # revalida todo; o ErrorDescriptor
verificar_contenido(ObjetoFuente, bytes) -> None           # huella y tamaño, en memoria
huella_contenido(bytes) -> "sha256:<hex>"
```

`ErrorDescriptor` (subclase de `ValueError`) trae `problemas` (tupla ordenada de
`Problema(codigo, sujeto, detalle)`), `codigos` y `codigo`. Nunca se devuelve un descriptor
parcial: un solo problema rechaza el inventario completo.

### Entrada: `Inventario`

* `version_contrato`: entero en `VERSIONES_COMPATIBLES` (`{1, 2}`). **2 es la vigente**; cada
  inventario se valida con la tabla y reglas de su versión (ver «Versiones»).
* `empresa_id`: obligatorio, patrón `^[a-z][a-z0-9-]{1,38}[a-z0-9]$`. Es la **identidad
  de custodia** (`ContextoEmpresa.cloud_id`, la que Cloud deduce del token Motor); para MBT,
  `empresa-prueba-javier`. Los identificadores locales `mbt` y `oficina` se rechazan
  (`EMPRESA_INVALIDA`): no se traducen.
* `generacion`: `GeneracionSolicitada(generacion_id, secuencia>=1, previa_id)`. `secuencia 1`
  no admite previa; `secuencia > 1` la exige y debe ser distinta.
* `declaracion`: número **exacto** de objetos por tipo, según la enumeración oficial del
  llamador. Todo tipo conocido debe aparecer. `0` es la única forma de declarar vacío y sólo
  vale donde el tipo lo admite. Un tipo omitido nunca equivale a vacío.
* `objetos`: `ObjetoFuente` por objeto.
* `derivaciones` (v2): `{derivación: {ranura: identidad}}`; ver «Derivaciones». En v1 debe ir vacío.

### `ObjetoFuente`

| Campo | Regla |
| --- | --- |
| `identidad` | Identidad lógica estable: minúsculas, segmentos `[a-z0-9][a-z0-9._-]*` separados por `/`, máx. 256. Sin unidades, `..`, `\`, ni ruta absoluta. Única en el inventario. |
| `tipo` | Uno de `TIPOS` (tabla siguiente). |
| `huella` | `sha256:<64 hex minúsculas>`. Ausente o vacía: `OBJETO_SIN_HUELLA`; otro algoritmo o formato: `CONTENIDO_NO_VERIFICABLE`. |
| `tamano` | Entero `>= 0` o `None` (desconocido; se cuenta en `resumen.tamanos_desconocidos`). Coherente con la huella del contenido vacío. |
| `empresa_id` / `relacion` | `PROPIA`: debe ser la empresa del inventario. `COMPARTIDA_GLOBAL`: `empresa_id = None`, sólo para `CATALOGO`. |
| `obligatorio` | Booleano. Debe ser `True` en tipos obligatorios. |
| `metadatos` | Mapa `clave -> str/int/bool/None`; claves `^[a-z][a-z0-9_]{0,63}$`. Sin rutas absolutas ni URLs en los valores, sin claves con aspecto de credencial ni reservadas al protocolo. |
| `referencias` | `Referencia(identidad, huella, empresa_id)` hacia otro objeto del **mismo** inventario y empresa, con la huella exacta inventariada. Una fuente obligatoria no puede depender de un objeto opcional. |
| `rol` (v2) | Obligatorio en `DECISIONES_HUMANAS`, `CATALOGO` y `EVIDENCIA_DOCUMENTAL`; prohibido en los demás tipos (`ROL_INVALIDO`). En v1 no existe. |
| `documento` (v2) | Sólo en evidencia de documento: el `archivo` real (máx. 512, sin control, sin ruta absoluta ni URL; puede llevar mayúsculas, espacios o `::pagina=NNNN`). En v1 no existe. |

### Tipos

| Tipo | v1 | v2 | Vacío admitido |
| --- | --- | --- | --- |
| `IDENTIDAD_EMPRESA` | exactamente 1; **0 para MBT** | igual | sólo MBT, declarado `0` |
| `DATASET_OPERACIONAL` | exactamente 1 | igual | no |
| `LEDGER_DECISIONES` | exactamente 1 | igual | no |
| `DECISIONES_HUMANAS` | exactamente 1 | **exactamente 2**, uno por rol | no |
| `BANDEJA_REVISION` | exactamente 1 | igual | no |
| `AGRUPACIONES_CONFIRMADAS` | exactamente 1 | igual | no |
| `REGISTRO_INVESTIGACION` | exactamente 1 | igual | no |
| `CATALOGO` | 1 o más | 1 o más, rol único por catálogo | no (admite globales) |
| `ASIGNACIONES` | 1 o más | **no es tipo**: derivación (abajo) | — |
| `CUARENTENA` | 0 o más | igual | sí, declarado `0` |
| `EVIDENCIA_DOCUMENTAL` | 0 o más | 0 o más, con rol y documento | sí, declarado `0` |

Un archivo de colección vacía (`[]`, `{}`, CSV con sólo encabezado) sigue siendo un objeto con
huella; su inexistencia es `FUENTE_OBLIGATORIA_AUSENTE`.

MBT opera sin `catalogos_privados/empresa_identidad.json`; en su custodia una marca indica
empresa ajena (`aislamiento_empresas.verificar_manifiesto_empresa`). Por eso, para
`EMPRESAS_SIN_MARCA = {"empresa-prueba-javier"}` (= `CLOUD_MBT`, verificado por prueba) el tipo
se declara `0` y un objeto `IDENTIDAD_EMPRESA` es `EMPRESA_INCORRECTA`. Las demás empresas
siguen exigiendo exactamente una marca. La regla vale en v1 y v2.

### Reglas v2 (fuentes reales, `docs/FUENTES_GENERACION.md`)

**Decisiones humanas.** Exactamente dos objetos originales, obligatorios, con identidades y
huellas propias. Roles: `acciones_operacionales` (`operacion/actual/acciones_operacionales.json`)
y `operaciones_conversacionales` (`operacion/actual/operaciones_conversacionales.json`). Cada rol
aparece una vez: si falta uno, `FUENTE_OBLIGATORIA_AUSENTE` con sujeto
`DECISIONES_HUMANAS:<rol>`; un rol repetido es `IDENTIDAD_CONTRADICTORIA`; otro rol (p. ej.
`asignaciones`) es `ROL_INVALIDO`. No se fusionan ni se crea un archivo artificial.

**Derivaciones.** Un concepto sin almacén propio se representa por sus fuentes originales
del mismo inventario, sin copiarlas:

```
derivaciones = {"ASIGNACIONES": {"vehiculos": <identidad CATALOGO rol vehiculos>,
                                 "choferes":  <identidad CATALOGO rol choferes>,
                                 "ledger":    <identidad LEDGER_DECISIONES>}}
```

Se exige la derivación y sus tres ranuras. Cada una debe apuntar a un objeto presente, del
tipo y rol esperados, y propio de la empresa (no global). Los errores son
`DEPENDENCIA_INCOMPLETA` y `EMPRESA_INCORRECTA`; una ranura desconocida es `FORMATO_INVALIDO`.
Como todas las ranuras apuntan dentro del mismo descriptor, sus objetos son de la misma
generación. Ninguna ranura admite `DECISIONES_HUMANAS`: **una asignación inferida nunca
figura como confirmación humana**. Un objeto de tipo `ASIGNACIONES` en v2 es `TIPO_DESCONOCIDO`.
`DescriptorPreparado.derivacion("ASIGNACIONES")` devuelve los objetos originales.

**Evidencia documental.** Admite varios objetos por generación.
* Roles de documento: `original`, `orientada`, `pdf`, `pdf-pagina` y `pdf-texto`. Los dos
  últimos son la «evidencia procesada», es decir, los derivados técnicos del PDF.
* Identidad verificable: `evidencia/<sha256(documento)>/<rol>/<sha256 del contenido>`
  (`identidad_evidencia`). Si no coincide con `documento`, `rol` y `huella`, el error es
  `EVIDENCIA_NO_VERIFICABLE`, igual que si falta el `documento`.
* El hash del contenido evita colisiones entre varias fotos del mismo documento (relecturas).
* La ubicación (Mobile, `entradas`, `evidencia_resuelta`) **no** es rol ni parte de la
  identidad: mover un archivo no cambia su identidad.
* Índices: `registro-relecturas` (identidad fija `evidencia/registro-relecturas`) y
  `registro-evidencias-adicionales` (`evidencia/pdf/evidencias-adicionales`), sin documento.
* La referencia a la guía puede ir en `metadatos` (p. ej. `numero_guia`) y en `referencias`
  desde el dataset.
* Fuera de este contrato: almacenamiento, movimiento, purga y retención.

**Catálogos.** `rol` es el nombre del catálogo (`vehiculos`, `choferes`, `geografia_chile`...),
único entre los catálogos del inventario.

### Versiones

* `construir_descriptor` y `leer_descriptor` aplican las reglas y la serialización de **la
  versión del inventario o del descriptor**: `TIPOS_POR_VERSION = {1: TIPOS_V1, 2: TIPOS_V2}`.
* Un descriptor v1 se lee con sus reglas y sus mismos bytes y huella (fixture
  `tests/fixtures/descriptor_generacion_v1.json`, generado con el código de 57e5173/c90053b).
  Se devuelve con `version_contrato == 1`, sin derivaciones ni roles.
* Un descriptor v1 nunca se promueve a v2: cambiarle la versión o agregarle `derivaciones` es
  `FORMATO_INVALIDO`, y su inventario no cumple las reglas v2.
* Un inventario v1 con `rol`, `documento` o `derivaciones` es `FORMATO_INVALIDO`.
* Cualquier otra versión es `VERSION_INCOMPATIBLE`.
* Los consumidores deben comprobar `version_contrato` antes de suponer las garantías v2.

### Salida serializada

JSON canónico (claves ordenadas, sin espacios, UTF-8, sin NaN). Fuentes ordenadas por
identidad; referencias por `(identidad, huella)` sin duplicados; metadatos y declaración por
clave. Campos de primer nivel exactos:

```
esquema="atlas.descriptor_generacion", version_contrato, clase, completitud,
algoritmo_huella="sha256", empresa_id, generacion{id,secuencia,previa_id},
declaracion{tipo:n}, fuentes[...], resumen{objetos,obligatorios,bytes_declarados,
tamanos_desconocidos}, huella_descriptor
v2 además: derivaciones{nombre:{ranura:identidad}}; cada fuente lleva rol y documento (null si no aplican)
```

`huella_descriptor` = `sha256` del JSON canónico de todos los demás campos. El orden de
entrada no altera ni la huella ni los bytes; cualquier cambio de contenido, metadato o
generación sí. `leer_descriptor` reconstruye el descriptor desde el contenido, lo revalida
por completo y exige huella **y** bytes canónicos idénticos (`DESCRIPTOR_ALTERADO`).

### Códigos de rechazo

`FORMATO_INVALIDO`, `VERSION_INCOMPATIBLE`, `EMPRESA_AUSENTE`, `EMPRESA_INVALIDA`,
`EMPRESA_INCORRECTA`, `GENERACION_INVALIDA`, `TIPO_DESCONOCIDO`, `IDENTIDAD_INVALIDA`,
`IDENTIDAD_DUPLICADA`, `IDENTIDAD_CONTRADICTORIA`, `OBJETO_SIN_HUELLA`,
`CONTENIDO_NO_VERIFICABLE`, `CAMPO_PROHIBIDO`, `OBLIGATORIEDAD_INCONSISTENTE`,
`FUENTE_OBLIGATORIA_AUSENTE`, `INVENTARIO_INCOMPLETO`, `INVENTARIO_INCONSISTENTE`,
`REFERENCIA_INCONSISTENTE`, `REFERENCIA_ENTRE_EMPRESAS`, `DESCRIPTOR_AUTODECLARADO`,
`DESCRIPTOR_ALTERADO`; v2: `ROL_INVALIDO`, `EVIDENCIA_NO_VERIFICABLE`, `DEPENDENCIA_INCOMPLETA`.

## Compatibilidad con la custodia de generaciones Cloud v1

Conciliado contra Atlas-Mobile-Cloud `61c28726cd7aafbfa3113f4e5ef77487dd8aa1f9`
(`docs/custodia-generaciones-v1.md`, `migrations/0013_generaciones_custodia.sql`,
`src/worker.js` `descriptorGeneracion`/`prepararGeneracion`/`publicarGeneracion`/
`leerGeneracion`). Módulo `atlas_core/descriptor_custodia.py`, también puro:

```python
proyectar_para_custodia(DescriptorPreparado, empresa_custodia) -> ProyeccionCustodia
verificar_generacion_custodia(descriptor_cloud, descriptor_sha256, datos_descriptor,
                              empresa_custodia) -> DescriptorPreparado
```

`ProyeccionCustodia` lleva los bytes del campo `descriptor` de `POST .../preparar`
(idénticos a los que Cloud guarda con `JSON.stringify`), el `descriptor_sha256` que Cloud
debe devolver, `anterior_id` (= `previa_id`) y los bytes del descriptor Motor a subir como
objeto. No incluye `lease_token` ni `version_base` (estado de custodia) ni hace HTTP.
`verificar_generacion_custodia` valida la respuesta de `GET .../actual` junto con los bytes
del objeto descriptor Motor descargados por el llamador, y exige coincidencia exacta.

### Representación

* Descriptor Cloud v1: `{version: 1, empresa_id, generacion_id, objetos: [{ruta, sha256}]}`.
* Cada fuente Motor es un objeto: `ruta` = identidad lógica, `sha256` = huella sin el
  prefijo `sha256:`. La gramática de identidades Motor es un subconjunto estricto de
  `rutaEstadoValida` (sin `:`, `\`, `/` inicial, segmentos vacíos, `.` ni `..`; máx. 256 < 512).
* El descriptor Motor serializado viaja **como un objeto más** en
  `RUTA_DESCRIPTOR = "_atlas/descriptor_generacion.json"`. Es la única forma de que tipos,
  obligatoriedad, referencias, vacíos declarados, secuencia y `previa_id` lleguen a Cloud sin
  cambiar su API: Cloud lo trata como un objeto opaco y lo verifica por SHA-256. La ruta
  empieza por `_`, fuera del espacio de identidades Motor, por lo que no puede colisionar.

### Puntos conciliados

| # | Punto | Resolución |
| --- | --- | --- |
| 1 | Identidad empresarial | `empresa_id` del descriptor = identidad autenticada de Cloud = `ContextoEmpresa.cloud_id`. La proyección exige que coincidan y no traduce: `mbt`/`oficina` se rechazan. No se cambió ningún identificador. |
| 2 | Generación | `generacion_id` Motor (`^[a-z0-9][a-z0-9._-]{0,127}$`) ⊂ `ID_SEGURO` Cloud. `anterior_id` = `previa_id`. `secuencia` no existe en Cloud: viaja dentro del objeto descriptor Motor. |
| 3 | Identidades lógicas | `ruta` = identidad, sin traducción (ver Representación). |
| 4 | Huellas | `sha256:<hex>` en Motor, `<hex>` en Cloud; misma función SHA-256 sobre los mismos bytes. `descriptor_sha256` se calcula igual que el Worker y la prueba cruzada lo compara. |
| 5 | Serialización y versión | Dos versiones independientes: `version` Cloud (=1, sin cambios) y `version_contrato` Motor (2 vigente, 1 legible). Cualquier otra se rechaza (`VERSION_INCOMPATIBLE`) en ambos lados. |
| 6 | Tipos obligatorios | Cloud no los conoce ("el llamador debe enumerar todas las fuentes"). Se validan en el Motor al construir y otra vez al verificar la lectura, desde el objeto descriptor Motor. Corrección: MBT no lleva marca (tabla de tipos). |
| 7 | Vacíos explícitos | Cloud sólo ve objetos presentes; el `0` declarado viaja en el descriptor Motor. Cloud exige ≥ 1 objeto, siempre cumplido (descriptor Motor + obligatorias). |
| 8 | Evidencia y referencias | La evidencia es un objeto más (subida por `PUT .../estado/objetos/<sha>`, por empresa), sin depender de `rutas_semilla`. Cloud verifica su existencia e integridad al publicar y leer; el Motor verifica que cada sha coincida con su huella y marca `REFERENCIA_INCONSISTENTE` si la fuente es referida. |
| 9 | Preparado vs. publicado | `PENDIENTE`/`PUBLICADA` sólo existen en respuestas Cloud. El descriptor Motor conserva `PENDIENTE_PROTOCOLO_OFICIAL`; un cuerpo Cloud con campos extra (p. ej. `estado`) se rechaza. |

Catálogos `COMPARTIDA_GLOBAL`: en Cloud los objetos son por empresa
(`estado-operativo/<empresa>/<sha>`), así que un catálogo global se sube como objeto en la
custodia de cada empresa que lo inventaría. No requiere cambios.

### Cambios del descriptor Motor

* 57e5173 (sin cambio de formato): se endurecieron `mbt`/`oficina` como empresa y la marca de
  identidad en MBT.
* v2 (este contrato): decisiones humanas, derivación de asignaciones y evidencia con rol.
  **El adaptador Cloud no cambió.** El descriptor Cloud sigue siendo
  `{version: 1, empresa_id, generacion_id, objetos:[{ruta, sha256}]}`, con
  `_atlas/descriptor_generacion.json` como objeto. Las identidades v2 (las de evidencia tienen
  unos 150 caracteres) cumplen `rutaEstadoValida`. Las derivaciones viajan dentro del objeto
  descriptor Motor; Cloud no las ve ni las necesita.
* Los descriptores v1 siguen proyectándose y verificándose igual; quien los lea debe comprobar
  `version_contrato`.
* Las pruebas v1 (78 + 31) sólo cambiaron de forma mecánica: `TIPOS` pasó a `TIPOS_V1` y la
  versión «desconocida» de prueba pasó de 2 a 3, porque 2 ahora es válida.

### Pendientes y cambios que debería evaluar Codex en Cloud

Ninguno es necesario para intercambiar descriptores válidos: la prueba cruzada contra
`61c2872` pasa sin modificar Cloud. Antes de integrar el escritor:

1. **Límite de 1000 objetos** (`descriptorGeneracion`). Con el descriptor Motor caben 999
   fuentes (`LIMITE_CUSTODIA` si se excede). Un inventario real que incluya toda la evidencia
   documental probablemente lo supere (el censo del 19/11 contó 395 envíos Mobile con foto y
   la copia de CASA del 17/11 tenía 811 filas en el dataset, más los originales de sus guías;
   no se midió el inventario real en esta tarea). Cambio
   mínimo en Cloud: elevar el límite o admitir el inventario en varias partes, conservando un
   solo `descriptor_sha256` y una sola transición de puntero. Medir el inventario real antes
   de decidir.
2. **`GET .../actual` no devuelve `anterior_id` ni `version_base`.** El lector Motor obtiene
   `previa_id` desde el objeto descriptor, pero Cloud no comprueba que `anterior_id` del
   `preparar` coincida con él, porque no interpreta ese objeto. Opcional: incluir
   `anterior_id` en la respuesta de `actual` para que el lector lo compare.
3. **Formato de `cloud_id`**: Cloud acepta cualquier cadena y `inicializar_empresa` sólo exige
   que no esté vacía; el descriptor exige `^[a-z][a-z0-9-]{1,38}[a-z0-9]$`. `empresa-prueba-javier`
   cumple. Hay que verificar los `cloud_id` de las demás empresas; si alguno no cumple, se
   ampliaría el patrón Motor y no se cambiaría el identificador.
4. **Convención `RUTA_DESCRIPTOR`**: requiere el visto bueno de Codex. Cloud no necesita
   cambios para soportarla.
5. **Retención R2** y semántica real de D1/R2 desplegados: siguen pendientes según
   `custodia-generaciones-v1.md`.
6. **Mapeo de tipos a archivos reales** (p. ej. `acciones_operacionales.json` →
   `DECISIONES_HUMANAS`) y quién asigna `generacion_id`/`secuencia`: siguen pendientes de la
   integración con el escritor oficial y no se inventan aquí.

### Prueba de contrato cruzada

`tests/test_descriptor_custodia.py::test_contrato_cruzado_con_worker_cloud` ejecuta
`tests/contrato_custodia/cruce_generaciones.mjs`. El script carga el `src/worker.js` real y su
arnés `test/d1_sqlite.js` (SQLite y R2 en memoria, migraciones reales), sin red ni
credenciales. Se activa con `DESCRIPTOR_CLOUD_CONTRATO_DIR=<copia del código Cloud>` y `node`
≥ 22.5 (usa `node:sqlite`; validado con 24.22.0); si falta, se omite. Para preparar una copia de sólo lectura:

```
git -C <repo Cloud> archive 61c28726cd7aafbfa3113f4e5ef77487dd8aa1f9 | tar -x -C <carpeta>
```

Cubre: aceptación del descriptor Motor con igual `descriptor_sha256`, idempotencia, rechazo
de la empresa cruzada y de la versión 2, publicación, lectura y verificación Motor,
aislamiento de la otra empresa (`actual`, objeto y publicar), `NO_CONFIABLE` con evidencia sin
subir, encadenamiento `anterior_id` = `previa_id` y lectura de la generación 2.

## Limitaciones

* El descriptor certifica la **coherencia interna del inventario recibido**, no que el
  inventario represente el estado real: eso depende de que el llamador lo capture bajo el
  protocolo oficial (turno, lease y frontera `PENDIENTE`). Nada aquí lo garantiza.
* `verificar_contenido` comprueba bytes entregados en memoria; quién los obtiene y desde
  dónde es responsabilidad del protocolo.
* Las referencias sólo se validan dentro del inventario; no hay resolución transitiva de
  evidencia fuera de él.
