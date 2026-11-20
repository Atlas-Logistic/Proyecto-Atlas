# Contrato de fuentes reales de una generación operacional

Base: Motor CASA `c08bc38` + descriptor `9b99abb` + compatibilidad Cloud `57e5173`.
Contrato declarativo: `atlas_core/fuentes_generacion.py`. Pruebas:
`tests/test_fuentes_generacion.py`. Sólo inspección de código: no se leyeron datos reales
ni se crearon capturadores, adaptadores ni publicadores.

Las pruebas atan el contrato al código: cada ruta se recalcula con las constantes y funciones
de ruta del Motor, cada escritor, lector y lock declarado debe existir en `atlas_core`, y la
cobertura de custodia se compara con `estado_confirmado.SEMILLA_*`. Si el código cambia, la
prueba falla en vez de dejar el contrato desactualizado.

## Advertencia principal

**Una lista de archivos no es una instantánea coherente.** Ninguna fila de esta matriz es
legible de forma confiable sin la frontera común del escritor oficial (`PENDIENTE` durable
antes de la primera mutación y transición única a `COMPLETA`; ver
`docs/CONTRATO_COHERENCIA_LECTURA_LOTES.md`). El código actual muestra por qué los locks no
bastan:

* Los locks son archivos por recurso (`almacenamiento_portable.bloqueo_sesion`, `:362`),
  distintos por fuente, y se consideran huérfanos a las 6 h. No hay un lock común.
* Una decisión humana (`aplicacion_decisiones.aplicar_decision_obra`, `:651`) es una
  transacción lógica bajo el lock exterior `aplicar_decision_obra` (`:665-670`). El dataset se
  escribe bajo `revalidacion_dataset`, que **no es reentrante** y se toma y suelta en varias
  ventanas dentro de ella (`:1404-1412`). Entre ventanas, un lector que respete el lock del
  dataset ve estado intermedio. El propio código documenta un *GAP RESIDUAL* con
  `reconciliar_estado_derivado` (`mobile.py:1402-1415`).
* `reproceso_cuarentena.promover_candidato` (`:142-149`) escribe dataset y bandeja bajo
  `promocion_reproceso_cuarentena`, que no excluye a `revalidacion_dataset`.
* La bandeja y la investigación usan `decisiones_pendientes`; el dataset,
  `revalidacion_dataset`; el ledger, `aplicar_decision_obra`; las agrupaciones,
  `agrupaciones_viaje`; los catálogos, uno propio cada uno; la evidencia,
  `evidencia_documental` y `evidencias_adicionales`.
* `acciones_operacionales.publicacion_documental_incompleta` (`:277`) es la única marca de
  publicación en curso y sólo cubre las acciones de `_publicacion_protegida`.
* Desktop (Electron) copia la evidencia a `operacion/entradas` fuera de Python, por lo que el
  hook de custodia no la observa.

Por eso todas las fuentes mutables requieren la frontera común. `integracion` dice sólo si,
**además**, falta algo propio de la fuente.

## Matriz resumida

| Tipo descriptor | Fuente real (ruta relativa a la raíz de la empresa) | Identidad propuesta | Mapeo | Integración | Custodia actual |
| --- | --- | --- | --- | --- | --- |
| `IDENTIDAD_EMPRESA` | `catalogos_privados/empresa_identidad.json` (MBT: no existe) | `empresa/identidad` | RESUELTO | LISTA_TRAS_FRONTERA | en semilla |
| `DATASET_OPERACIONAL` | `operacion/actual/analisis_completo_guias.csv` | `operacion/dataset` | RESUELTO | LISTA_TRAS_FRONTERA | en semilla |
| `LEDGER_DECISIONES` | `operacion/actual/decisiones_aplicadas.json` | `operacion/ledger` | RESUELTO | LISTA_TRAS_FRONTERA | en semilla |
| `DECISIONES_HUMANAS` | `operacion/actual/acciones_operacionales.json` **y** `operacion/actual/operaciones_conversacionales.json` | `operacion/acciones-operacionales`, `operacion/operaciones-conversacionales` | **AMBIGUO** | **BLOQUEADA** | en semilla |
| `BANDEJA_REVISION` | `operacion/actual/decisiones_pendientes.json` | `operacion/bandeja` | RESUELTO | LISTA_TRAS_FRONTERA | en semilla |
| `AGRUPACIONES_CONFIRMADAS` | `operacion/actual/agrupaciones_viaje.json` | `operacion/agrupaciones` | RESUELTO | LISTA_TRAS_FRONTERA | en semilla |
| `REGISTRO_INVESTIGACION` | `operacion/actual/documentos_en_investigacion.json` | `operacion/investigacion` | RESUELTO | LISTA_TRAS_FRONTERA (depende de evidencia) | en semilla |
| `CUARENTENA` | — (estado `EN_INVESTIGACION` dentro del registro de investigación) | — | SIN_ALMACEN_PROPIO | DECLARAR_CERO | — |
| `EVIDENCIA_DOCUMENTAL` | binarios en `operacion/{entradas/<lote>, mobile/envios/<envio_id>, evidencia_pdf, evidencia_orientada, evidencia_resuelta/<entrada>}`; `operacion/relecturas_documentales.json`; `operacion/evidencia_pdf/evidencias_adicionales.json` | `evidencia/<sha256(archivo)>/<rol>`, `evidencia/registro-relecturas`, `evidencia/pdf/evidencias-adicionales` | RESUELTO | **BLOQUEADA** | **fuera de semilla** |
| `CATALOGO` | `catalogos_privados/{choferes, vehiculos, clientes, empresas, destinos_maestros, plantas, rutas, obras_destinos, incidencias_documentales}.json`; global `catalogos_privados/geografia_chile.json` del repositorio | `catalogos/<nombre>`, `global/geografia-chile` | RESUELTO | LISTA_TRAS_FRONTERA | en semilla (geografía: versionada en código) |
| `ASIGNACIONES` | — (dentro de `vehiculos.json`, más `choferes.json` y el ledger) | — | SIN_ALMACEN_PROPIO | **BLOQUEADA** | — |

## Detalle por fuente

Formato de cada ítem: escritores y lock · empresa · cardinalidad y vacío · dependencias ·
ausencia frente a vacío hoy · riesgo.

### Identidad empresarial
* `catalogos_privados/empresa_identidad.json` (`aislamiento_empresas.RUTA_MARCA`).
  Escritor: `inicializar_empresa` (`:299`), una vez por empresa. Propia.
* Obligatoria salvo MBT. MBT no tiene marca, y una marca en su custodia es empresa ajena
  (`verificar_manifiesto_empresa`, `:346`); el descriptor ya la declara 0 para
  `empresa-prueba-javier`.
* Riesgo bajo. La identidad del descriptor es el `cloud_id`, no el contenido de este archivo.

### Dataset operacional
* `operacion/actual/analisis_completo_guias.csv` (`acciones_operacionales._Contexto`, `:295`).
* Escritores (todos con `revalidacion_dataset` salvo indicación):
  * `procesamiento_masivo`, `revalidacion_documental`, `mobile`;
  * `aplicacion_decisiones`, dentro de `aplicar_decision_obra`;
  * `acciones_operacionales`;
  * `recuperacion_numero_guia`, `recuperacion_material`, `recuperacion_fila_custodia`, `recuperacion_incremental`;
  * `reprocesamiento_reparador`, `recalculo_ruta_planta`;
  * `reproceso_cuarentena`, con otro lock.
* Exactamente 1. Un CSV con encabezado y sin filas es vacío legítimo.
* Depende de ledger, bandeja, investigación y evidencia (columnas `archivo` y
  `evidencia_documentos_relacionados`).
* Hoy un archivo inexistente se lee como `[]` (`_Contexto._filas_sin_bloqueo`, `:344`).
* Riesgo alto (ver la advertencia principal).

### Ledger y confirmaciones humanas
* Ledger: `operacion/actual/decisiones_aplicadas.json` (`aplicacion_decisiones.LEDGER`).
  * Escritores: `aplicacion_decisiones.aplicar_decision_obra` y `acciones_operacionales`
    (p. ej. `CORREGIR_CAMPO`, `:1684`), ambos bajo `aplicar_decision_obra`.
  * Contiene aplicaciones humanas y automáticas, que se distinguen por el actor
    (`decisiones_pendientes._actor_es_humano`, `:1519`).
  * Lista `aplicaciones` vacía es legítima. Hoy un ledger ausente se lee como vacío en
    `instantanea_documental` y en `equipo_operacional` (`ResolutorEquipoOperacional`, `:251`).
* Registros humanos candidatos a `DECISIONES_HUMANAS`, ambos en semilla:
  * `operacion/actual/acciones_operacionales.json`. Lo escribe
    `CapaAccionesOperacionales._guardar_registro` (`:3299`) bajo el lock
    `acciones_operacionales`. Guarda previews, auditoría de confirmaciones (`confirmado_por`)
    y las marcas `publicacion_iniciada` / `confirmacion_recuperable`. Si no existe, se trata
    como vacío (`_leer_registro`, `:3291`).
  * `operacion/actual/operaciones_conversacionales.json`. Es el ledger de instrucciones
    humanas chofer-vehículo (`operaciones_conversacionales._ledger_ruta`, `:44`). Si no
    existe, se trata como vacío (`_leer_ledger`, `:48`). Además escribe `vehiculos.json`.
* **BLOQUEADA:** el descriptor exige exactamente 1 `DECISIONES_HUMANAS` y hay dos registros
  reales. Las decisiones aplicadas viven además en el ledger. Ver «Decisiones pendientes».

### Revisión y pendientes
* `operacion/actual/decisiones_pendientes.json`. Es un artefacto derivado y regenerable; su
  escritor principal es `decisiones_pendientes._generar_artefacto_sin_lock` (`:4780`), y
  también escriben `revalidacion_documental`, `mobile` y `acciones_operacionales`, todos bajo
  `decisiones_pendientes`.
* Depende de dataset, ledger e investigación (que excluye decisiones de documentos en
  investigación). Lista `decisiones` vacía es legítima.
* Hoy un archivo ausente se lee como `{}` (`_decisiones_sin_bloqueo`).
* Otros pendientes **fuera de la tabla v1**: `pendientes_tecnicos.json` (cola técnica de
  `reconciliacion_estado_derivado`). `incidencias_documentales.json` figura aquí como catálogo
  porque vive en `catalogos_privados` y `_Contexto` lo trata así.

### Agrupaciones de viajes
* `operacion/actual/agrupaciones_viaje.json`. Escritor: `registrar_agrupacion` (`:180`), lock
  `agrupaciones_viaje`.
* Exactamente 1; la lista `agrupaciones` vacía es legítima. Depende del dataset.
* Hoy un archivo inexistente es vacío (`_leer`, `:48`) y cualquier error también
  (`agrupaciones_activas`, `:58`).
* Sin este archivo el reporte cambia de cardinalidad: en una copia se observaron 699 viajes
  con él y 703 sin él.

### Investigación y cuarentena
* `operacion/actual/documentos_en_investigacion.json` (`investigacion_documental.ruta_registro`).
  Escritor: el propio módulo (`:176`, `:226`), bajo `decisiones_pendientes`, el mismo lock que
  la bandeja.
* Su identidad estable es `archivo` más el SHA-256 de la evidencia, así que depende de la
  evidencia documental.
* Hoy un registro ilegible o inexistente se lee como vacío (`leer_registro`, `:59`).
* **Cuarentena:** no hay almacén propio. La cuarentena operacional es el estado
  `EN_INVESTIGACION` de ese registro. `reproceso_cuarentena` trabaja en un `--workspace` que
  elige el operador (herramienta manual) y `estado_confirmado` tiene una cuarentena local de
  custodia en `LOCALAPPDATA`. Ninguno de los dos es estado de la generación: `CUARENTENA` se
  declara 0.

### Evidencia documental
* No es un archivo. `evidencia_documental.resolver_ruta_evidencia` (`:171`) resuelve el
  `documento.archivo`, en este orden:
  1. Mobile: `operacion/mobile/envios/<envio_id>/<foto>`;
  2. la relectura vigente de `operacion/relecturas_documentales.json`;
  3. los lotes de Desktop en `operacion/entradas/<lote>/<archivo>`;
  4. el depósito `operacion/evidencia_resuelta/<entrada>/` (`metadata.json` más la imagen).

  Las páginas PDF usan derivados en `operacion/evidencia_pdf`, con
  `evidencias_adicionales.json` (`ingesta_pdf`, `:536`, `:592`, `:656`). Las imágenes
  orientadas están en `operacion/evidencia_orientada` (`orientacion_documental`, `:254`).
* Se distinguen `NO_ENCONTRADA` y `PURGADA` (explícitas); el 0 sólo es legítimo si el dataset
  no referencia evidencia. Los registros de relecturas y de evidencias adicionales, en cambio,
  se leen como vacíos si no existen (`leer_registro_relecturas`, `:107`; `:592`).
* Escritores:
  * Desktop (Electron), `mobile.RepositorioEnviosMobile`, `ingesta_pdf`, `orientacion_documental`;
  * `registrar_relectura` (`:116`) y los movimientos y purgas `mover_evidencia_resuelta_sin_revision_pendiente`
    (`:367`) y `purgar_evidencia_resuelta_vencida` (`:430`), con retención de 30 días.
* Identidad: el `archivo` real no es una identidad válida, por mayúsculas, espacios o `<pdf>::pagina=NNNN`
  (`:` está prohibido en el Motor y en `rutaEstadoValida` de Cloud). Se propone
  `evidencia/<sha256(archivo)>/<rol>` (`identidad_evidencia`), con el `archivo` original en
  metadatos. Roles: `activa-mobile`, `activa-desktop`, `derivada-pdf`, `texto-pdf`,
  `orientada`, `resuelta`.
* **BLOQUEADA:**
  * los binarios están fuera de la semilla de custodia y Desktop los escribe fuera del hook;
  * el inventario es derivado: dataset (`archivo`, `evidencia_documentos_relacionados`) más
    relecturas, y su resolución cambia con movimientos y purgas no coordinados con una frontera;
  * Cloud admite como máximo 1000 objetos por generación.

### Catálogos
* `catalogos_privados/`, en semilla, con los 7 archivos de `fuente_catalogos.ARCHIVOS_REQUERIDOS`
  más `obras_destinos.json` e `incidencias_documentales.json` (`_Contexto.archivos`).
  Todos son propios y obligatorios, y un archivo inexistente es ausencia.
* Escritores verificados:
  * `catalogos.cambiar_estado_chofer` (lock `choferes`);
  * `catalogo_vehiculos.confirmar_vehiculo` / `asociar_chofer_a_vehiculo_confirmado` (`:408`, `:496`, lock `catalogo_vehiculos`);
  * `catalogo_clientes`, `catalogo_destinos`, `catalogo_obras_destinos`, `incidencias_documentales`.

  Para `empresas`, `plantas` y `rutas` no hay escritor en `atlas_core`.
* Global: `catalogos_privados/geografia_chile.json`, versionado en el repositorio
  (`atlas_core/geografia/cl.py`). Se identifica como `COMPARTIDA_GLOBAL`.
* Riesgo: `fuente_catalogos.resolver_fuente_catalogos` acepta `ATLAS_CATALOGOS_DIR`, luego
  `./catalogos` del directorio actual si están los 7, y luego la raíz portable. El escritor
  debe fijar la carpeta de la empresa, no resolverla.
* Pendiente: `evidencia_entidades.json` (lo usa `aplicacion_decisiones`) no está en la lista
  requerida. Falta decidir si el inventario toma la carpeta completa o una lista cerrada.

### Asignaciones de choferes y vehículos
* No hay almacén propio. `equipo_operacional.asignaciones_vigentes_con_fecha` (`:166`) las
  deriva de las evidencias `CONFIRMACION_HUMANA` con `rut_chofer_asociado` y fecha dentro de
  `vehiculos.json` (escritas por `asociar_chofer_a_vehiculo_confirmado` u
  `operaciones_conversacionales`). `ResolutorEquipoOperacional` (`:251`) agrega
  `FLAG_ASIGNACION_VARIABLE` de `choferes.json` y las decisiones del ledger, y convierte
  cualquier error de lectura en vacío.
* `cloud_asignaciones_vehiculo` publica una **derivación** hacia Cloud; no es fuente.
* **BLOQUEADA:** el descriptor exige al menos un objeto `ASIGNACIONES` con identidad propia,
  pero la fuente real está dentro de `vehiculos.json`. No se fabrica un objeto equivalente.

## Archivos reales fuera de la tabla de tipos v1

`FUERA_DE_TABLA_V1` en el módulo. Hay que decidir si las precondiciones del preview los leen:

* `operacion/actual/`:
  * `eventos_operacionales.json`: estadías, devoluciones y dobles vueltas;
  * `pendientes_tecnicos.json`;
  * `estado_operacion.json`: manifiesto del reporte;
  * `b1_operador_conversaciones.json`;
  * `recuperaciones_incrementales.json`.
* `catalogos_privados/`: `registro_relaciones_operacionales.json` y `evidencia_entidades.json`.
* Carpetas en semilla, no auditadas aquí: `operacion/procesamiento/` y `fichas_digitales/`.

## Cobertura de custodia actual

`estado_confirmado.SEMILLA_CARPETAS` (`:44`) = `operacion/actual`, `operacion/procesamiento`,
`catalogos_privados`, `fichas_digitales`; además, de Mobile sólo cada `envio.json`. Todo lo de
`operacion/actual` y `catalogos_privados` de esta matriz está en la semilla. La evidencia
(binarios, relecturas, `evidencia_pdf`, `evidencia_orientada`, `evidencia_resuelta`) es
`rastreable()` pero no está en la semilla: sólo entra si un escritor Python observado la toca
con custodia activa.

## Listas para integración y bloqueadas

**Listas, a la espera de la frontera común:** identidad empresarial (con la excepción MBT),
dataset, ledger, bandeja, agrupaciones, registro de investigación (condicionado a la
evidencia), catálogos y geografía global. `CUARENTENA` se declara 0.

**Bloqueadas:**
1. `DECISIONES_HUMANAS`: hay dos registros humanos reales para un tipo de cardinalidad 1.
2. `ASIGNACIONES`: no tiene almacén propio; vive en `vehiculos.json`.
3. `EVIDENCIA_DOCUMENTAL`: está fuera de custodia, es derivada, se mueve y se purga, y choca
   con el límite de 1000 objetos de Cloud.

Las pruebas `test_contrato_actual_no_produce_inventario_completo` (empresa normal y MBT) e
`test_incluir_ambos_registros_humanos_viola_la_cardinalidad` demuestran que, con el contrato
actual, el descriptor rechaza el inventario exactamente por esos tipos: no se omite nada en
silencio.

## Decisiones pendientes (no tomadas aquí)

El contrato de compatibilidad (`57e5173`) no se modificó. Los bloqueos 1 y 2 son
incompatibilidades demostradas entre la tabla de tipos v1 y las fuentes reales, pero
resolverlas exige decidir semántica:

* `DECISIONES_HUMANAS`: cardinalidad `1..n`, o un tipo por registro, o declarar el ledger como
  única fuente de decisiones humanas y tratar `acciones_operacionales.json` como estado de
  publicación. Cualquiera cambia la tabla de tipos y exige subir `VERSION_CONTRATO`.
* `ASIGNACIONES`: declararlo 0 con la regla «contenidas en `CATALOGO` vehículos», o eliminar el
  tipo. Ambas cambian la tabla.
* Evidencia: la regla de inventario (qué binarios por documento, cuáles en `evidencia_resuelta`,
  qué hacer con `PURGADA`), cómo entran a custodia los binarios de Desktop, y el límite de 1000
  objetos de Cloud.
* Catálogos: carpeta completa o lista cerrada, incluidos `evidencia_entidades.json` y las fichas.
* Las fuentes de `FUERA_DE_TABLA_V1`.
