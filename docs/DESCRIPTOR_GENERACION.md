# Descriptor preparado de generación operacional (contrato v1)

Módulo: `atlas_core/descriptor_generacion.py`. Pruebas: `tests/test_descriptor_generacion.py`.
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

* `version_contrato`: entero en `VERSIONES_COMPATIBLES` (hoy `{1}`).
* `empresa_id`: obligatorio, patrón `^[a-z][a-z0-9-]{1,38}[a-z0-9]$` (el de
  `aislamiento_empresas`, sin su lista de reservados: ver conciliación).
* `generacion`: `GeneracionSolicitada(generacion_id, secuencia>=1, previa_id)`. `secuencia 1`
  no admite previa; `secuencia > 1` la exige y debe ser distinta.
* `declaracion`: número **exacto** de objetos por tipo, según la enumeración oficial del
  llamador. Todo tipo conocido debe aparecer. `0` es la única forma de declarar vacío y sólo
  vale donde el tipo lo admite. Un tipo omitido nunca equivale a vacío.
* `objetos`: `ObjetoFuente` por objeto.

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

### Tipos v1

| Tipo | Cardinalidad | Vacío admitido |
| --- | --- | --- |
| `IDENTIDAD_EMPRESA` | exactamente 1 | no |
| `DATASET_OPERACIONAL` | exactamente 1 | no |
| `LEDGER_DECISIONES` | exactamente 1 | no |
| `DECISIONES_HUMANAS` | exactamente 1 | no |
| `BANDEJA_REVISION` | exactamente 1 | no |
| `AGRUPACIONES_CONFIRMADAS` | exactamente 1 | no |
| `REGISTRO_INVESTIGACION` | exactamente 1 | no |
| `CATALOGO` | 1 o más | no (admite globales) |
| `ASIGNACIONES` | 1 o más | no |
| `CUARENTENA` | 0 o más | sí, declarado `0` |
| `EVIDENCIA_DOCUMENTAL` | 0 o más | sí, declarado `0` |

Un archivo de colección vacía (`[]`, `{}`, CSV con sólo encabezado) sigue siendo un objeto con
huella; su inexistencia es `FUENTE_OBLIGATORIA_AUSENTE`.

### Salida serializada

JSON canónico (claves ordenadas, sin espacios, UTF-8, sin NaN). Fuentes ordenadas por
identidad; referencias por `(identidad, huella)` sin duplicados; metadatos y declaración por
clave. Campos de primer nivel exactos:

```
esquema="atlas.descriptor_generacion", version_contrato=1, clase, completitud,
algoritmo_huella="sha256", empresa_id, generacion{id,secuencia,previa_id},
declaracion{tipo:n}, fuentes[...], resumen{objetos,obligatorios,bytes_declarados,
tamanos_desconocidos}, huella_descriptor
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
`DESCRIPTOR_ALTERADO`.

## Campos que requieren conciliación antes de integrar

El contrato definitivo de custodia de generaciones no está disponible (el worktree
`cloud-generaciones-completas-20261120` de Codex no tiene commits nuevos sobre `b28d594`).
No se inventa ninguna API productiva. Antes de integrar hay que acordar:

1. **Identidad de generación**: quién asigna `generacion_id` y `secuencia` (¿la custodia al
   abrir `PENDIENTE`?), su formato y si `previa_id` debe coincidir con la última `COMPLETA`
   autoritativa. Aquí sólo se valida la forma y la coherencia interna.
2. **Empresa**: `aislamiento_empresas.validar_empresa_id` reserva `mbt`, `oficina` y
   `empresa-prueba-javier`; el descriptor los acepta porque MBT opera con esos nombres. Hay
   que fijar qué identificador lleva el descriptor (local `mbt` o Cloud
   `empresa-prueba-javier`) y cómo se cruza con `catalogos_privados/empresa_identidad.json`.
3. **Inventario exacto de tipos**: la tabla v1 sigue la lista del encargo y de 51167a7.
   Falta mapear cada tipo a los archivos reales que leen el preview y las precondiciones
   (p. ej. `acciones_operacionales.json` como `DECISIONES_HUMANAS`,
   `agrupaciones_viaje.json`, catálogos de choferes/vehículos y asignaciones). Cambiar la
   tabla exige subir `VERSION_CONTRATO`.
4. **Identidad lógica vs. ruta de custodia**: la custodia direcciona por ruta relativa
   (`operacion/actual/...`) y SHA-256 hex sin prefijo. Hay que definir la traducción
   identidad ↔ ruta y si la huella viaja como `sha256:<hex>` o hex.
5. **Evidencia fuera de la semilla**: originales de `operacion/entradas`, fotos Mobile y
   rutas de `resolver_ruta_evidencia` no están en `rutas_semilla`. Hace falta decidir cómo
   llegan como objetos durables antes de poder referenciarlos.
6. **Catálogos globales**: `COMPARTIDA_GLOBAL` (sin empresa) es una propuesta; confirmar si
   la custodia por empresa puede servir objetos globales o si deben copiarse por empresa.
7. **Tamaño del descriptor**: es un único objeto, no N entradas de manifiesto, así que no
   depende de `LOTE_CONFIRMACION = 50` ni del límite de 200 rutas del Worker. Falta fijar
   dónde se guarda (objeto R2 por huella) y su límite (95 MiB por objeto en el Worker
   inspeccionado; 100 fuentes sintéticas producen unos 30 KB).
8. **Recuperación**: qué hace el protocolo con un descriptor preparado de una operación
   interrumpida. Este módulo no tiene estado; volver a construirlo con el mismo inventario
   da los mismos bytes.

## Limitaciones

* El descriptor certifica la **coherencia interna del inventario recibido**, no que el
  inventario represente el estado real: eso depende de que el llamador lo capture bajo el
  protocolo oficial (turno, lease y frontera `PENDIENTE`). Nada aquí lo garantiza.
* `verificar_contenido` comprueba bytes entregados en memoria; quién los obtiene y desde
  dónde es responsabilidad del protocolo.
* Las referencias sólo se validan dentro del inventario; no hay resolución transitiva de
  evidencia fuera de él.
